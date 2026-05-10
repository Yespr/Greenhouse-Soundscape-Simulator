import sqlite3
from pathlib import Path
from typing import Any, Iterable

from app.models import SoundEntry, SoundEntryCreate, SoundEntryUpdate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "soundscape.sqlite3"

SOUND_COLUMNS = (
    "id",
    "name",
    "file_path",
    "enabled",
    "profile",
    "type",
    "volume",
    "min_interval_seconds",
    "max_interval_seconds",
    "probability",
    "fade_in_seconds",
    "fade_out_seconds",
    "repeat_count_min",
    "repeat_count_max",
    "repeat_gap_seconds",
)


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
        _create_sound_entries_table(connection)
        _migrate_db(connection)
        _migrate_percent_schema(connection)


def _create_sound_entries_table(connection: sqlite3.Connection, table_name: str = "sound_entries") -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            profile TEXT NOT NULL CHECK(profile IN ('day', 'evening', 'both')),
            type TEXT NOT NULL CHECK(type IN ('loop', 'random')),
            volume INTEGER NOT NULL DEFAULT 70 CHECK(volume >= 0 AND volume <= 100),
            min_interval_seconds INTEGER NOT NULL CHECK(min_interval_seconds >= 0),
            max_interval_seconds INTEGER NOT NULL CHECK(max_interval_seconds >= 0),
            probability INTEGER NOT NULL DEFAULT 100 CHECK(probability >= 0 AND probability <= 100),
            fade_in_seconds REAL NOT NULL CHECK(fade_in_seconds >= 0.0),
            fade_out_seconds REAL NOT NULL CHECK(fade_out_seconds >= 0.0),
            repeat_count_min INTEGER NOT NULL DEFAULT 1 CHECK(repeat_count_min >= 1),
            repeat_count_max INTEGER NOT NULL DEFAULT 1 CHECK(repeat_count_max >= 1),
            repeat_gap_seconds REAL NOT NULL DEFAULT 1.0 CHECK(repeat_gap_seconds >= 0.0),
            CHECK(repeat_count_max >= repeat_count_min),
            CHECK(max_interval_seconds >= min_interval_seconds)
        )
        """
    )


def _migrate_db(connection: sqlite3.Connection) -> None:
    existing_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(sound_entries)").fetchall()
    }
    migrations = {
        "repeat_count_min": "ALTER TABLE sound_entries ADD COLUMN repeat_count_min INTEGER NOT NULL DEFAULT 1 CHECK(repeat_count_min >= 1)",
        "repeat_count_max": "ALTER TABLE sound_entries ADD COLUMN repeat_count_max INTEGER NOT NULL DEFAULT 1 CHECK(repeat_count_max >= 1)",
        "repeat_gap_seconds": "ALTER TABLE sound_entries ADD COLUMN repeat_gap_seconds REAL NOT NULL DEFAULT 1.0 CHECK(repeat_gap_seconds >= 0.0)",
    }
    for column, statement in migrations.items():
        if column not in existing_columns:
            connection.execute(statement)


def _migrate_percent_schema(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'sound_entries'"
    ).fetchone()
    table_sql = row["sql"] if row else ""
    existing_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(sound_entries)").fetchall()
    }
    if (
        "volume <= 1.0" not in table_sql
        and "probability <= 1.0" not in table_sql
        and not (existing_columns - set(SOUND_COLUMNS))
    ):
        return

    rows = connection.execute("SELECT * FROM sound_entries").fetchall()
    connection.execute("ALTER TABLE sound_entries RENAME TO sound_entries_old")
    _create_sound_entries_table(connection)

    for row in rows:
        data = _row_with_defaults(row, existing_columns)
        data["volume"] = _to_percent(data["volume"])
        data["probability"] = _to_percent(data["probability"])
        placeholders = ", ".join(f":{column}" for column in SOUND_COLUMNS)
        connection.execute(
            f"INSERT INTO sound_entries ({', '.join(SOUND_COLUMNS)}) VALUES ({placeholders})",
            {column: data[column] for column in SOUND_COLUMNS},
        )

    connection.execute("DROP TABLE sound_entries_old")


def _row_with_defaults(row: sqlite3.Row, columns: set[str]) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "id": None,
        "name": "Sound",
        "file_path": "sounds/missing.wav",
        "enabled": 1,
        "profile": "both",
        "type": "loop",
        "volume": 70,
        "min_interval_seconds": 30,
        "max_interval_seconds": 120,
        "probability": 100,
        "fade_in_seconds": 0.0,
        "fade_out_seconds": 0.0,
        "repeat_count_min": 1,
        "repeat_count_max": 1,
        "repeat_gap_seconds": 1.0,
    }
    for column in columns:
        if column in defaults:
            defaults[column] = row[column]
    return defaults


def _to_percent(value: Any) -> int:
    number = float(value)
    if number <= 1.0:
        number *= 100
    return max(0, min(100, int(round(number))))


def _row_to_sound(row: sqlite3.Row) -> SoundEntry:
    data = dict(row)
    data["enabled"] = bool(data["enabled"])
    return SoundEntry.model_validate(data)


def _write_values(sound: SoundEntryCreate) -> dict[str, Any]:
    data = sound.model_dump()
    data["profile"] = sound.profile.value
    data["type"] = sound.type.value
    data["enabled"] = int(sound.enabled)
    return data


def list_sounds() -> list[SoundEntry]:
    with get_connection() as connection:
        rows = connection.execute(
            f"SELECT {', '.join(SOUND_COLUMNS)} FROM sound_entries ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [_row_to_sound(row) for row in rows]


def get_sound(sound_id: int) -> SoundEntry | None:
    with get_connection() as connection:
        row = connection.execute(
            f"SELECT {', '.join(SOUND_COLUMNS)} FROM sound_entries WHERE id = ?",
            (sound_id,),
        ).fetchone()
    return _row_to_sound(row) if row else None


def create_sound(sound: SoundEntryCreate) -> SoundEntry:
    values = _write_values(sound)
    columns = ", ".join(values.keys())
    placeholders = ", ".join(f":{key}" for key in values.keys())
    with get_connection() as connection:
        cursor = connection.execute(
            f"INSERT INTO sound_entries ({columns}) VALUES ({placeholders})",
            values,
        )
        sound_id = int(cursor.lastrowid)
    created = get_sound(sound_id)
    if created is None:
        raise RuntimeError("created sound entry could not be loaded")
    return created


def update_sound(sound_id: int, patch: SoundEntryUpdate) -> SoundEntry | None:
    current = get_sound(sound_id)
    if current is None:
        return None

    merged = current.model_dump()
    for key, value in patch.model_dump(exclude_unset=True).items():
        if value is not None:
            merged[key] = value

    updated = SoundEntryCreate.model_validate({k: v for k, v in merged.items() if k != "id"})
    values = _write_values(updated)
    values["id"] = sound_id
    assignments = ", ".join(f"{key} = :{key}" for key in values.keys() if key != "id")
    with get_connection() as connection:
        connection.execute(
            f"UPDATE sound_entries SET {assignments} WHERE id = :id",
            values,
        )
    return get_sound(sound_id)


def delete_sound(sound_id: int) -> bool:
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM sound_entries WHERE id = ?", (sound_id,))
        return cursor.rowcount > 0


def replace_seed_data(entries: Iterable[SoundEntryCreate]) -> None:
    with get_connection() as connection:
        count = connection.execute("SELECT COUNT(*) FROM sound_entries").fetchone()[0]
    if count:
        return
    for entry in entries:
        create_sound(entry)
