from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..processing.repair import RepairRecipe


class TrialStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label_id: str = Field(min_length=1, max_length=48)
    sensor_ids: list[str] = Field(min_length=1, max_length=4)
    duration_s: float | None = Field(None, ge=0.3, le=30)
    countdown_s: float | None = Field(None, ge=0, le=10)
    trials: int | None = Field(None, ge=1, le=200)
    pause_s: float | None = Field(None, ge=0, le=30)
    session_id: str | None = Field(None, max_length=64)
    notes: str = Field("", max_length=2000)


class ContinuousStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label_id: str | None = Field(None, max_length=48, description="Optional label hint; segments carry the training labels")
    sensor_ids: list[str] = Field(min_length=1, max_length=4)
    session_id: str | None = Field(None, max_length=64)
    notes: str = Field("", max_length=2000)


class NewSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field("", max_length=120)
    notes: str = Field("", max_length=2000)


class StagingIdsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    staging_ids: list[str] = Field(min_length=1, max_length=500)
    confirm: bool = False


class StagingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str | None = Field(None, max_length=2000)
    label_id: str | None = Field(None, max_length=48)


class RecordingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label_id: str | None = Field(None, max_length=48)
    notes: str | None = Field(None, max_length=4000)
    session_id: str | None = Field(None, max_length=64)
    kind: Literal["trial", "continuous"] | None = None
    clear_label: bool = False
    clear_session: bool = False


class SegmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label_id: str = Field(min_length=1, max_length=48)
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    notes: str = Field("", max_length=1000)


class SegmentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label_id: str | None = Field(None, max_length=48)
    start_s: float | None = Field(None, ge=0)
    end_s: float | None = Field(None, gt=0)
    notes: str | None = Field(None, max_length=1000)


class DerivativeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipe_name: str | None = Field(None, description="Preset name: default-v1, default-resampled-v1 or legacy-analyze-v1")
    recipe: RepairRecipe | None = Field(None, description="Custom recipe; overrides recipe_name")


class KnownImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: list[str] = Field(min_length=1, max_length=10)
    session_mode: Literal["batch", "per_file", "none"] = "batch"
    session_name: str | None = Field(None, max_length=120)


class LabelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label_id: str = Field(min_length=1, max_length=48)
    display_name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    description: str = Field("", max_length=500)


class LabelPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(None, max_length=80)
    enabled: bool | None = None
    description: str | None = Field(None, max_length=500)


class LabelRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_label_id: str = Field(min_length=1, max_length=48)
    confirm: bool = False


class LabelMerge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=48)
    target_id: str = Field(min_length=1, max_length=48)
    confirm: bool = False


class SessionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, max_length=120)
    notes: str | None = Field(None, max_length=2000)


class SessionAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str | None = Field(None, max_length=64)
    recording_ids: list[str] = Field(min_length=1, max_length=2000)
