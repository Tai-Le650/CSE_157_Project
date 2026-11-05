from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ArmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    control_session_id: str = Field(min_length=1, max_length=64, description="The WebSocket client_id of the browser tab that will supervise PC control.")
    confirm: bool = Field(description="Must be true; the UI asks the user to confirm the mappings first.")


class DisarmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field("user", max_length=60)


class EmergencyStopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field("ui_button", max_length=60)
