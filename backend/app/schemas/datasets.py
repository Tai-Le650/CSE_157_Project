from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..processing.csv_io import CHANNELS
from ..processing.repair import RepairRecipe


class DatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=2000)


class DatasetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, max_length=120)
    description: str | None = Field(None, max_length=2000)


class MemberItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recording_id: str = Field(min_length=1, max_length=96)
    segment_id: str | None = Field(None, max_length=64)
    derivative_id: str | None = Field(None, max_length=96)


class MembersAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[MemberItem] = Field(min_length=1, max_length=2000)


class MembersRemove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    member_ids: list[int] = Field(min_length=1, max_length=2000)


class MemberDerivative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    derivative_id: str | None = Field(None, max_length=96)


class RepairFlagged(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipe_name: str = Field("default-v1", max_length=48)
    confirm: bool = False


class SpectrumRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["recording", "derivative", "live"]
    recording_id: str | None = Field(None, max_length=96)
    derivative_id: str | None = Field(None, max_length=96)
    sensor_id: str | None = Field(None, max_length=32)
    live_seconds: float = Field(10.0, ge=1, le=60)
    channel: Literal[CHANNELS] = "gx"
    window: int = Field(128, ge=8, le=4096)
    hop: int = Field(32, ge=1, le=4096)
    fft_position: Literal["most_energetic", "latest"] | float = "most_energetic"
    recipe_name: str | None = Field(None, max_length=48, description="Explicit repair recipe for flagged recordings (applied in memory, not saved)")
    recipe: RepairRecipe | None = None
