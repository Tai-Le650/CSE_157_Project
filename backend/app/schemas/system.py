from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: str = Field(description="'ok' when the backend is serving requests")
    app: str
    version: str
    time: float


class HostedLimitsOut(BaseModel):
    max_sandboxes: int
    max_sandboxes_per_ip: int
    idle_minutes: float
    max_age_minutes: float
    max_trees: int
    max_folds: int
    min_hop_s: float
    max_sensors: int
    max_streaming_sensors: int
    max_demo_rate_hz: float
    default_threshold: float
    default_smoothing_k: int
    default_debounce_n: int
    project_url: str | None


class SessionOut(BaseModel):
    token: str = Field(description="Per-launch token (per-visitor sandbox token in the online demo). Send it as X-Session-Token and as ?token= on /ws.")
    header: str
    websocket_path: str
    bind_host: str
    hosted: bool = Field(False, description="True in the public online demo, where every visitor gets a private Demo Mode sandbox")
    limits: HostedLimitsOut | None = Field(None, description="Online-demo limits; null when running locally")


class ModesOut(BaseModel):
    monitoring: bool
    recording: bool
    recognition: bool
    pc_control: bool
    demo: bool


class StatusOut(BaseModel):
    app: str
    version: str
    workspace: str
    primary_mode: str
    modes: ModesOut
    estop_latched: bool
    training_active: bool
    sensors_streaming: int
    clients: int
    ui_frames_dropped: int
    ui_samples_dropped: int
    uptime_s: float
    time: float
    data_dir: str
    data_dir_is_default: bool


class PortOut(BaseModel):
    device: str
    description: str
    hwid: str
    vid: str | None
    pid: str | None
    serial_number: str | None
    manufacturer: str | None
    owned_by: str | None = Field(None, description="Sensor ID that currently owns this port in this backend, if any")


class ActivityEntry(BaseModel):
    id: int
    ts: float
    level: str
    category: str
    message: str
    data: dict[str, Any]
