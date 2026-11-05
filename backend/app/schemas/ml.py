from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = False


class ModelPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)


class RecognitionStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str | None = Field(None, max_length=96)
    sensor_id: str | None = Field(None, max_length=32)
    hop_s: float | None = Field(None, ge=0.02, le=2.0, description="Window step; overlap = window − hop")
    threshold: float | None = Field(None, gt=0, le=1)
    smoothing_k: int | None = Field(None, ge=1, le=20)
    debounce_n: int | None = Field(None, ge=1, le=20)
    cooldown_s: float | None = Field(None, ge=0, le=30)
    require_idle_rearm: bool | None = None


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=1000)
    copy_from: str | None = Field(None, max_length=64)


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, max_length=120)
    description: str | None = Field(None, max_length=1000)


class ActiveProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: str | None = Field(None, max_length=64)


class MappingUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: dict = Field(description="One allowlisted action, e.g. {\"type\": \"hotkey\", \"modifiers\": [\"ctrl\"], \"key\": \"tab\"}")
    enabled: bool = False


class SimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label_id: str | None = Field(None, max_length=48)
    action: dict | None = None
