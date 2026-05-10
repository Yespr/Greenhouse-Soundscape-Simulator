from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class SoundProfile(str, Enum):
    day = "day"
    evening = "evening"
    both = "both"


class SoundType(str, Enum):
    loop = "loop"
    random = "random"


class SoundscapeMode(str, Enum):
    off = "off"
    day = "day"
    evening = "evening"
    auto = "auto"


class SoundEntryBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    file_path: str = Field(min_length=1, max_length=500)
    enabled: bool = True
    profile: SoundProfile = SoundProfile.both
    type: SoundType = SoundType.loop
    volume: int = Field(default=70, ge=0, le=100)
    min_interval_seconds: int = Field(default=30, ge=0)
    max_interval_seconds: int = Field(default=120, ge=0)
    probability: int = Field(default=100, ge=0, le=100)
    fade_in_seconds: float = Field(default=0.0, ge=0.0)
    fade_out_seconds: float = Field(default=0.0, ge=0.0)
    repeat_count_min: int = Field(default=1, ge=1)
    repeat_count_max: int = Field(default=1, ge=1)
    repeat_gap_seconds: float = Field(default=1.0, ge=0.0)

    @field_validator("name", "file_path")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def validate_intervals(self) -> "SoundEntryBase":
        if self.max_interval_seconds < self.min_interval_seconds:
            raise ValueError("max_interval_seconds must be >= min_interval_seconds")
        if self.repeat_count_max < self.repeat_count_min:
            raise ValueError("repeat_count_max must be >= repeat_count_min")
        return self


class SoundEntryCreate(SoundEntryBase):
    pass


class SoundEntryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    file_path: Optional[str] = Field(default=None, min_length=1, max_length=500)
    enabled: Optional[bool] = None
    profile: Optional[SoundProfile] = None
    type: Optional[SoundType] = None
    volume: Optional[int] = Field(default=None, ge=0, le=100)
    min_interval_seconds: Optional[int] = Field(default=None, ge=0)
    max_interval_seconds: Optional[int] = Field(default=None, ge=0)
    probability: Optional[int] = Field(default=None, ge=0, le=100)
    fade_in_seconds: Optional[float] = Field(default=None, ge=0.0)
    fade_out_seconds: Optional[float] = Field(default=None, ge=0.0)
    repeat_count_min: Optional[int] = Field(default=None, ge=1)
    repeat_count_max: Optional[int] = Field(default=None, ge=1)
    repeat_gap_seconds: Optional[float] = Field(default=None, ge=0.0)

    @field_validator("name", "file_path")
    @classmethod
    def strip_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class SoundEntry(SoundEntryBase):
    id: int


class EngineState(BaseModel):
    running: bool
    mode: SoundscapeMode
    active_profile: Optional[SoundProfile] = None


class ModeRequest(BaseModel):
    mode: SoundscapeMode
