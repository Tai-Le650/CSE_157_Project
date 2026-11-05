from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, Any] = Field(description="Partial settings object; nested keys are merged.")


class DemoModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    confirm: bool = Field(False, description="Required because switching disconnects all sensors and disarms PC control.")


class StorageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data_dir: str | None = Field(None, max_length=400, description="Absolute folder for data/ (app.db, raw, processed, exports). Null restores the default. Takes effect after restart.")
