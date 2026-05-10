from dataclasses import dataclass
from pathlib import Path
import random
from threading import Event, Lock, Thread
from typing import Iterable
from uuid import uuid4

from app.models import SoundEntry, SoundProfile, SoundType


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STREAM_SAMPLE_RATE = 44100
STREAM_CHANNELS = 2
STREAM_BLOCKSIZE = 1024


@dataclass(frozen=True)
class PlaybackPlan:
    profile: SoundProfile
    loop_sounds: tuple[SoundEntry, ...]
    random_sounds: tuple[SoundEntry, ...]


@dataclass
class Voice:
    voice_id: str
    sound: SoundEntry
    samples: object
    loop: bool
    done_event: Event | None = None
    position: int = 0


class SoundDeviceBackend:
    def __init__(self) -> None:
        self._lock = Lock()
        self._stream = None
        self._voices: dict[str, Voice] = {}
        self._loop_voice_ids: dict[int, str] = {}
        self._np = None
        self._sf = None
        self._sd = None

    def start(self) -> None:
        self._ensure_dependencies()
        if self._stream is not None:
            return
        try:
            self._stream = self._sd.OutputStream(
                samplerate=STREAM_SAMPLE_RATE,
                channels=STREAM_CHANNELS,
                blocksize=STREAM_BLOCKSIZE,
                dtype="float32",
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise RuntimeError(f"Audio output is not available: {exc}") from exc

    def stop_all(self) -> None:
        with self._lock:
            voices = list(self._voices.values())
            self._voices.clear()
            self._loop_voice_ids.clear()

        for voice in voices:
            if voice.done_event:
                voice.done_event.set()

    def play_loop(self, sound: SoundEntry) -> str:
        voice_id = self._add_voice(sound, loop=True, done_event=None)
        with self._lock:
            old_voice_id = self._loop_voice_ids.get(sound.id)
            self._loop_voice_ids[sound.id] = voice_id
            if old_voice_id and old_voice_id != voice_id:
                self._voices.pop(old_voice_id, None)
        return voice_id

    def play_once(self, sound: SoundEntry, done_event: Event | None = None) -> str:
        return self._add_voice(sound, loop=False, done_event=done_event)

    def stop_voice(self, voice_id: str) -> None:
        with self._lock:
            voice = self._voices.pop(voice_id, None)
        if voice and voice.done_event:
            voice.done_event.set()

    def _add_voice(self, sound: SoundEntry, loop: bool, done_event: Event | None) -> str:
        self.start()
        samples = self._load_samples(sound)
        voice_id = uuid4().hex
        voice = Voice(
            voice_id=voice_id,
            sound=sound,
            samples=samples,
            loop=loop,
            done_event=done_event,
        )
        with self._lock:
            self._voices[voice_id] = voice
        return voice_id

    def _ensure_dependencies(self) -> None:
        if self._np is not None:
            return
        try:
            import numpy as np
            import sounddevice as sd
            import soundfile as sf
        except Exception as exc:
            raise RuntimeError(
                "Audio backend dependencies are missing. Install sounddevice, soundfile, and numpy."
            ) from exc

        self._np = np
        self._sd = sd
        self._sf = sf

    def _sound_path(self, sound: SoundEntry) -> Path:
        path = Path(sound.file_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {sound.file_path}")
        return path

    def _load_samples(self, sound: SoundEntry):
        self._ensure_dependencies()
        path = self._sound_path(sound)
        data, sample_rate = self._sf.read(str(path), dtype="float32", always_2d=True)

        if data.shape[1] == 1:
            data = self._np.repeat(data, STREAM_CHANNELS, axis=1)
        elif data.shape[1] > STREAM_CHANNELS:
            data = data[:, :STREAM_CHANNELS]

        if sample_rate != STREAM_SAMPLE_RATE:
            data = self._resample(data, sample_rate)

        return self._np.ascontiguousarray(data, dtype=self._np.float32)

    def _resample(self, data, source_rate: int):
        if len(data) == 0:
            return data
        ratio = STREAM_SAMPLE_RATE / source_rate
        target_length = max(1, int(len(data) * ratio))
        source_x = self._np.linspace(0.0, 1.0, num=len(data), endpoint=False)
        target_x = self._np.linspace(0.0, 1.0, num=target_length, endpoint=False)
        channels = [
            self._np.interp(target_x, source_x, data[:, channel])
            for channel in range(data.shape[1])
        ]
        return self._np.stack(channels, axis=1).astype(self._np.float32)

    def _callback(self, outdata, frames: int, _time, status) -> None:
        mix = self._np.zeros((frames, STREAM_CHANNELS), dtype=self._np.float32)
        finished: list[str] = []

        with self._lock:
            voices = list(self._voices.values())

        for voice in voices:
            chunk, finished_voice = self._render_voice(voice, frames)
            if chunk is not None:
                mix += chunk
            if finished_voice:
                finished.append(voice.voice_id)

        if finished:
            with self._lock:
                for voice_id in finished:
                    voice = self._voices.pop(voice_id, None)
                    if voice and voice.done_event:
                        voice.done_event.set()

        outdata[:] = self._limit(mix)

    def _render_voice(self, voice: Voice, frames: int):
        samples = voice.samples
        total_frames = len(samples)
        if total_frames == 0:
            return None, True

        output = self._np.zeros((frames, STREAM_CHANNELS), dtype=self._np.float32)
        written = 0

        while written < frames:
            remaining_source = total_frames - voice.position
            remaining_output = frames - written
            take = min(remaining_source, remaining_output)

            if take > 0:
                output[written : written + take] = samples[voice.position : voice.position + take]
                voice.position += take
                written += take

            if voice.position >= total_frames:
                if voice.loop:
                    voice.position = 0
                else:
                    break

        output *= max(0.0, min(1.0, float(voice.sound.volume) / 100.0))
        finished = not voice.loop and voice.position >= total_frames
        return output, finished

    def _limit(self, samples):
        return self._np.clip(samples, -1.0, 1.0).astype(self._np.float32)


class AudioEngine:
    def __init__(self) -> None:
        self._lock = Lock()
        self._running = False
        self._plan: PlaybackPlan | None = None
        self._backend = SoundDeviceBackend()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def plan(self) -> PlaybackPlan | None:
        with self._lock:
            return self._plan

    def start(self, profile: SoundProfile, sounds: Iterable[SoundEntry]) -> PlaybackPlan:
        enabled_sounds = tuple(
            sound
            for sound in sounds
            if sound.enabled and (sound.profile == profile or sound.profile.value == "both")
        )
        plan = PlaybackPlan(
            profile=profile,
            loop_sounds=tuple(sound for sound in enabled_sounds if sound.type.value == "loop"),
            random_sounds=tuple(sound for sound in enabled_sounds if sound.type.value == "random"),
        )
        with self._lock:
            self._backend.stop_all()
            self._backend.start()
            self._plan = plan
            self._running = True
            for sound in plan.loop_sounds:
                self._backend.play_loop(sound)
        return plan

    def stop(self) -> None:
        with self._lock:
            self._backend.stop_all()
            self._running = False
            self._plan = None

    def refresh(self, sounds: Iterable[SoundEntry]) -> PlaybackPlan | None:
        with self._lock:
            plan = self._plan
        if plan is None:
            return None
        return self.start(plan.profile, sounds)

    def play_once(self, sound: SoundEntry) -> dict[str, object]:
        self._backend.play_once(sound)
        return {
            "status": "playing",
            "sound_id": sound.id,
            "file_path": sound.file_path,
            "volume": sound.volume,
        }

    def play_once_and_wait(self, sound: SoundEntry, stop_event: Event) -> dict[str, object]:
        done_event = Event()
        voice_id = self._backend.play_once(sound, done_event=done_event)

        while not done_event.wait(0.05):
            if stop_event.is_set():
                self._backend.stop_voice(voice_id)
                break

        return {
            "status": "played",
            "sound_id": sound.id,
            "file_path": sound.file_path,
            "volume": sound.volume,
        }

    def test_playback(self, sound: SoundEntry) -> dict[str, object]:
        if sound.type == SoundType.random:
            repeat_count = random.randint(sound.repeat_count_min, sound.repeat_count_max)
            Thread(
                target=self._test_random_burst,
                args=(sound, repeat_count),
                name=f"soundscape-test-random-{sound.id}",
                daemon=True,
            ).start()
            return {
                "status": "playing",
                "sound_id": sound.id,
                "file_path": sound.file_path,
                "volume": sound.volume,
                "repeat_count": repeat_count,
                "repeat_gap_seconds": sound.repeat_gap_seconds,
            }
        return self.play_once(sound)

    def _test_random_burst(self, sound: SoundEntry, repeat_count: int) -> None:
        stop_event = Event()
        for index in range(repeat_count):
            self.play_once_and_wait(sound, stop_event)
            if index < repeat_count - 1:
                stop_event.wait(sound.repeat_gap_seconds)
