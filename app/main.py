from contextlib import asynccontextmanager
import logging
from pathlib import Path
import re
import shutil
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile, status
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app import database
from app.audio_engine import AudioEngine
from app.models import (
    EngineState,
    ModeRequest,
    SoundEntry,
    SoundEntryCreate,
    SoundEntryUpdate,
    SoundscapeMode,
)
from app.scheduler import SoundscapeScheduler


logging.basicConfig(level=logging.INFO)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "web"
SOUNDS_DIR = PROJECT_ROOT / "sounds"
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg"}

audio_engine = AudioEngine()
scheduler = SoundscapeScheduler(audio_engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield
    scheduler.stop()


app = FastAPI(title="Greenhouse Soundscape Simulator", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/sounds", response_model=list[SoundEntry])
def list_sound_entries() -> list[SoundEntry]:
    return database.list_sounds()


@app.post("/api/sounds", response_model=SoundEntry, status_code=status.HTTP_201_CREATED)
def create_sound_entry(sound: SoundEntryCreate) -> SoundEntry:
    created = database.create_sound(sound)
    scheduler.refresh(database.list_sounds())
    return created


def _sanitize_filename(filename: str) -> str:
    original = Path(filename).name
    stem = Path(original).stem.strip().lower()
    extension = Path(original).suffix.lower()
    safe_stem = re.sub(r"[^a-z0-9._-]+", "-", stem).strip(".-_")
    if not safe_stem:
        safe_stem = "sound"
    return f"{safe_stem}{extension}"


def _name_from_filename(filename: str) -> str:
    stem = Path(filename).stem.replace("-", " ").replace("_", " ").strip()
    return " ".join(stem.split()).title() or "Sound"


def _unique_sound_path(filename: str) -> Path:
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    candidate = SOUNDS_DIR / filename
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    extension = candidate.suffix
    while True:
        candidate = SOUNDS_DIR / f"{stem}-{uuid4().hex[:8]}{extension}"
        if not candidate.exists():
            return candidate


@app.post("/api/sounds/upload", response_model=SoundEntry, status_code=status.HTTP_201_CREATED)
def upload_sound_entry(
    file: UploadFile = File(...),
    name: Annotated[str | None, Form()] = None,
    profile: Annotated[str, Form()] = "both",
    type: Annotated[str, Form()] = "loop",
    volume: Annotated[int, Form()] = 70,
    enabled: Annotated[bool, Form()] = True,
    min_interval_seconds: Annotated[int, Form()] = 30,
    max_interval_seconds: Annotated[int, Form()] = 120,
    probability: Annotated[int, Form()] = 100,
    fade_in_seconds: Annotated[float, Form()] = 0.0,
    fade_out_seconds: Annotated[float, Form()] = 0.0,
    repeat_count_min: Annotated[int, Form()] = 1,
    repeat_count_max: Annotated[int, Form()] = 1,
    repeat_gap_seconds: Annotated[float, Form()] = 1.0,
) -> SoundEntry:
    safe_filename = _sanitize_filename(file.filename or "")
    extension = Path(safe_filename).suffix.lower()
    if extension not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Upload an .mp3, .wav, or .ogg file.",
        )

    destination = _unique_sound_path(safe_filename)
    relative_path = destination.relative_to(PROJECT_ROOT).as_posix()

    try:
        with destination.open("wb") as output:
            shutil.copyfileobj(file.file, output)

        sound = SoundEntryCreate(
            name=name or _name_from_filename(safe_filename),
            file_path=relative_path,
            enabled=enabled,
            profile=profile,
            type=type,
            volume=volume,
            min_interval_seconds=min_interval_seconds,
            max_interval_seconds=max_interval_seconds,
            probability=probability,
            fade_in_seconds=fade_in_seconds,
            fade_out_seconds=fade_out_seconds,
            repeat_count_min=repeat_count_min,
            repeat_count_max=repeat_count_max,
            repeat_gap_seconds=repeat_gap_seconds,
        )
        created = database.create_sound(sound)
    except ValidationError as exc:
        if destination.exists():
            destination.unlink()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc
    except Exception:
        if destination.exists():
            destination.unlink()
        raise
    finally:
        file.file.close()

    scheduler.refresh(database.list_sounds())
    return created


@app.post("/api/sounds/{sound_id}/test")
def test_sound_entry(sound_id: int) -> dict[str, object]:
    sound = database.get_sound(sound_id)
    if sound is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sound entry not found")
    try:
        return audio_engine.test_playback(sound)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.put("/api/sounds/{sound_id}", response_model=SoundEntry)
def update_sound_entry(sound_id: int, patch: SoundEntryUpdate) -> SoundEntry:
    updated = database.update_sound(sound_id, patch)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sound entry not found")
    scheduler.refresh(database.list_sounds())
    return updated


@app.delete("/api/sounds/{sound_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sound_entry(sound_id: int) -> Response:
    deleted = database.delete_sound(sound_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sound entry not found")
    scheduler.refresh(database.list_sounds())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/engine", response_model=EngineState)
def get_engine_state() -> EngineState:
    return scheduler.state()


@app.get("/api/engine/active-sounds")
def get_active_sounds() -> dict[str, object]:
    return scheduler.active_sound_report(database.list_sounds())


@app.post("/api/engine/start", response_model=EngineState)
def start_engine() -> EngineState:
    sounds = database.list_sounds()
    try:
        if scheduler.mode.value == "off":
            return scheduler.set_mode(SoundscapeMode.auto, sounds)
        return scheduler.start(None, sounds)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/api/engine/stop", response_model=EngineState)
def stop_engine() -> EngineState:
    return scheduler.set_mode(SoundscapeMode.off, database.list_sounds())


@app.post("/api/engine/mode", response_model=EngineState)
def set_engine_mode(request: ModeRequest) -> EngineState:
    try:
        return scheduler.set_mode(request.mode, database.list_sounds())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
