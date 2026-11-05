from __future__ import annotations

import os
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .paths import AppPaths

BIND_HOST = "127.0.0.1"
HOSTED_BIND_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
HOSTED_DEFAULT_PORT = 10000
DEV_PORT = 5173
ENV_PREFIX = "GESTURE_TO_PC_"


def default_origins(port: int, dev_port: int) -> list[str]:
    origins = []
    for p in (port, dev_port):
        origins.append(f"http://127.0.0.1:{p}")
        origins.append(f"http://localhost:{p}")
    return origins


def env_number(name: str, default: float, cast: type, low: float, high: float) -> Any:
    raw = os.environ.get(ENV_PREFIX + name, "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        return default
    return cast(min(max(value, low), high))


def hosted_port(explicit: int | None) -> int:
    if explicit:
        return explicit
    raw = os.environ.get("PORT", "").strip()
    try:
        return int(raw) if raw else HOSTED_DEFAULT_PORT
    except ValueError:
        return HOSTED_DEFAULT_PORT


@dataclass(frozen=True)
class HostedLimits:
    max_sandboxes: int = 3
    max_sandboxes_per_ip: int = 2
    idle_minutes: float = 10.0
    max_age_minutes: float = 60.0
    max_trees: int = 30
    max_folds: int = 3
    min_hop_s: float = 0.25
    max_sensors: int = 2
    max_streaming_sensors: int = 2
    max_demo_rate_hz: float = 120.0
    default_threshold: float = 0.7
    default_smoothing_k: int = 1
    default_debounce_n: int = 1
    project_url: str | None = None

    @classmethod
    def from_env(cls) -> "HostedLimits":
        d = cls()
        return cls(
            max_sandboxes=env_number("MAX_SANDBOXES", d.max_sandboxes, int, 1, 50),
            max_sandboxes_per_ip=env_number("MAX_SANDBOXES_PER_IP", d.max_sandboxes_per_ip, int, 1, 50),
            idle_minutes=env_number("SANDBOX_IDLE_MINUTES", d.idle_minutes, float, 1, 240),
            max_age_minutes=env_number("SANDBOX_MAX_MINUTES", d.max_age_minutes, float, 5, 1440),
            max_trees=env_number("MAX_TREES", d.max_trees, int, 10, 2000),
            max_folds=env_number("MAX_FOLDS", d.max_folds, int, 2, 10),
            min_hop_s=env_number("MIN_HOP_S", d.min_hop_s, float, 0.02, 2.0),
            max_sensors=env_number("MAX_SENSORS", d.max_sensors, int, 1, 8),
            max_streaming_sensors=env_number("MAX_STREAMING_SENSORS", d.max_streaming_sensors, int, 1, 50),
            max_demo_rate_hz=env_number("MAX_DEMO_RATE_HZ", d.max_demo_rate_hz, float, 20, 500),
            default_threshold=env_number("DEFAULT_THRESHOLD", d.default_threshold, float, 0.3, 1.0),
            default_smoothing_k=env_number("DEFAULT_SMOOTHING_K", d.default_smoothing_k, int, 1, 20),
            default_debounce_n=env_number("DEFAULT_DEBOUNCE_N", d.default_debounce_n, int, 1, 20),
            project_url=os.environ.get(ENV_PREFIX + "PROJECT_URL", "").strip() or None,
        )

    def public(self) -> dict:
        return asdict(self)


@dataclass
class AppConfig:
    paths: AppPaths
    port: int = DEFAULT_PORT
    dev_port: int = DEV_PORT
    allowed_hosts: list[str] = field(default_factory=lambda: ["127.0.0.1", "localhost"])
    allowed_origins: list[str] = field(default_factory=list)
    session_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    enable_os_control: bool = True
    enable_global_hotkey: bool = True
    serve_frontend: bool = True
    serial_opener: Callable[[str, int], Any] | None = None
    health_interval_s: float = 0.5
    ui_flush_interval_s: float = 0.05
    stall_timeout_s: float = 1.5
    training_start_method: str = "spawn"
    log_to_file: bool = True
    hosted: bool = False
    hosted_limits: HostedLimits = field(default_factory=HostedLimits)
    sandbox_root: Path | None = None
    bind_host: str | None = None

    def __post_init__(self) -> None:
        if not self.allowed_origins:
            self.allowed_origins = default_origins(self.port, self.dev_port)

    @property
    def host(self) -> str:
        if not self.hosted:
            return BIND_HOST
        return self.bind_host or HOSTED_BIND_HOST


def hosted_config(paths: AppPaths, port: int | None = None, serve_frontend: bool = True, **overrides: Any) -> AppConfig:
    sandbox_dir = os.environ.get(ENV_PREFIX + "SANDBOX_DIR", "").strip()
    options: dict[str, Any] = dict(
        paths=paths,
        port=hosted_port(port),
        allowed_hosts=["*"],
        enable_os_control=False,
        enable_global_hotkey=False,
        serve_frontend=serve_frontend,
        log_to_file=False,
        health_interval_s=1.0,
        ui_flush_interval_s=0.1,
        hosted=True,
        hosted_limits=HostedLimits.from_env(),
        sandbox_root=Path(sandbox_dir) if sandbox_dir else Path(tempfile.gettempdir()) / "gesture-to-pc-sandboxes",
        bind_host=os.environ.get(ENV_PREFIX + "BIND_HOST", "").strip() or None,
    )
    options.update(overrides)
    return AppConfig(**options)
