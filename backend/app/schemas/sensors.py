from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    port: str | None = Field(None, max_length=128, description="COM port such as COM5. Omit for simulated sensors.")
    baud: int | None = Field(None, ge=300, le=4_000_000, description="Defaults to the Settings value (115200).")
    sensor_id: str = Field(min_length=1, max_length=32)
    hand: Literal["left", "right", "unassigned"] = "unassigned"
    simulated: bool = Field(False, description="Connect a Demo Mode simulated sensor instead of a COM port.")
    demo_rate_hz: float = Field(100.0, ge=20, le=500, description="Simulated sample rate (Demo Mode only).")
    demo_auto: bool = Field(False, description="Simulated sensor performs random gestures every few seconds.")


class SensorPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sensor_id: str | None = Field(None, min_length=1, max_length=32)
    hand: Literal["left", "right", "unassigned"] | None = None


class SensorOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    sensor_id: str
    port: str
    baud: int
    hand: str
    workspace: str
    simulated: bool
    status: str
    error: dict[str, Any] | None
    rates: dict[str, Any]
    counters: dict[str, Any]
    timing: dict[str, Any]
    clock: dict[str, Any]


class DemoPerformRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str


class DemoAutoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
