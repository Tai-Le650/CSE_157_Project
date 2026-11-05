from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Any, Callable

from .paths import AppPaths

BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEV_PORT = 5173


def default_origins(port: int, dev_port: int) -> list[str]:
    origins = []
    for p in (port, dev_port):
        origins.append(f"http://127.0.0.1:{p}")
        origins.append(f"http://localhost:{p}")
    return origins


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

    def __post_init__(self) -> None:
        if not self.allowed_origins:
            self.allowed_origins = default_origins(self.port, self.dev_port)

    @property
    def host(self) -> str:
        return BIND_HOST
