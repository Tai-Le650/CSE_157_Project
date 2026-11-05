from __future__ import annotations

import asyncio
import logging
import re
import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ..api.errors import AppError, conflict
from ..container import AppContainer
from ..settings.config import AppConfig
from ..settings.paths import AppPaths

logger = logging.getLogger("gesture_to_pc.hosting")

SANDBOX_PREFIX = "sbx-"
SANDBOX_NAME = re.compile(r"^sbx-[0-9a-f]{16}$")
REAP_INTERVAL_S = 30.0
SENSOR_PAUSE_AFTER_S = 60.0
INACTIVE_SENSOR_STATUSES = frozenset({"disconnected", "error"})


def active_sensors(container: AppContainer) -> int:
    return sum(1 for session in list(container.sensors.sessions.values()) if session.status not in INACTIVE_SENSOR_STATUSES)


@dataclass(eq=False)
class Sandbox:
    sandbox_id: str
    token: str
    container: AppContainer
    base_dir: Path
    client_ip: str
    created: float
    last_seen: float
    sockets: set[Any] = field(default_factory=set)

    def touch(self) -> None:
        self.last_seen = time.monotonic()


class SandboxRegistry:
    def __init__(self, config: AppConfig):
        if config.sandbox_root is None:
            raise ValueError("Hosted mode needs a sandbox_root")
        self.config = config
        self.limits = config.hosted_limits
        self.root = Path(config.sandbox_root)
        self._sandboxes: dict[str, Sandbox] = {}
        self._create_lock: asyncio.Lock | None = None
        self._training_lock = threading.Lock()
        self._reaper: asyncio.Task | None = None

    def __len__(self) -> int:
        return len(self._sandboxes)

    def sandboxes(self) -> list[Sandbox]:
        return list(self._sandboxes.values())

    async def start(self) -> None:
        self._create_lock = asyncio.Lock()
        await asyncio.to_thread(self._prepare_root)
        self._reaper = asyncio.create_task(self._reap_loop())

    async def stop(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
            try:
                await self._reaper
            except asyncio.CancelledError:
                pass
            self._reaper = None
        for sandbox in self.sandboxes():
            await self.close(sandbox)

    def _prepare_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for child in self.root.iterdir():
            if child.is_dir() and SANDBOX_NAME.match(child.name):
                shutil.rmtree(child, ignore_errors=True)

    def lookup(self, token: str | None) -> Sandbox | None:
        if not token:
            return None
        sandbox = self._sandboxes.get(token)
        if sandbox is not None:
            sandbox.touch()
        return sandbox

    def require(self, token: str | None) -> AppContainer:
        sandbox = self.lookup(token)
        if sandbox is None:
            raise AppError("invalid_session_token", "This demo sandbox has expired or does not exist; reload the page to start a new one", 401)
        return sandbox.container

    async def resume_or_create(self, token: str | None, client_ip: str) -> Sandbox:
        sandbox = self.lookup(token)
        if sandbox is not None:
            return sandbox
        if self._create_lock is None:
            self._create_lock = asyncio.Lock()
        async with self._create_lock:
            if len(self._sandboxes) >= self.limits.max_sandboxes:
                raise AppError(
                    "demo_full",
                    "The online demo is full right now because it runs on a small free server. Try again in a few minutes, or run Gesture-to-PC on your own PC.",
                    503,
                    {"max_sandboxes": self.limits.max_sandboxes},
                )
            if sum(1 for s in self._sandboxes.values() if s.client_ip == client_ip) >= self.limits.max_sandboxes_per_ip:
                raise AppError(
                    "too_many_sandboxes",
                    "Your network already has the most demo sandboxes allowed. Close another Gesture-to-PC tab or browser, or wait a few minutes.",
                    429,
                    {"max_sandboxes_per_ip": self.limits.max_sandboxes_per_ip},
                )
            sandbox = await asyncio.to_thread(self._build, client_ip)
            try:
                await sandbox.container.startup()
            except BaseException:
                await self._dispose(sandbox)
                raise
            self._sandboxes[sandbox.token] = sandbox
        logger.info("Sandbox %s created (%d live)", sandbox.sandbox_id, len(self._sandboxes))
        return sandbox

    def _build(self, client_ip: str) -> Sandbox:
        from ..wiring import attach_services

        sandbox_id = SANDBOX_PREFIX + secrets.token_hex(8)
        token = secrets.token_urlsafe(32)
        base = self.root / sandbox_id
        config = replace(self.config, paths=AppPaths.isolated(base), session_token=token, serve_frontend=False, log_to_file=False)
        container = AppContainer(config)
        limits = self.limits
        try:
            attach_services(container)
            container.settings.update({
                "demo_mode": True,
                "inference": {"hop_s": limits.min_hop_s, "threshold": limits.default_threshold, "smoothing_k": limits.default_smoothing_k, "debounce_n": limits.default_debounce_n},
            })
        except BaseException:
            container.engine.dispose()
            shutil.rmtree(base, ignore_errors=True)
            raise
        now = time.monotonic()
        return Sandbox(sandbox_id=sandbox_id, token=token, container=container, base_dir=base, client_ip=client_ip, created=now, last_seen=now)

    async def close(self, sandbox: Sandbox) -> None:
        self._sandboxes.pop(sandbox.token, None)
        for socket in list(sandbox.sockets):
            try:
                await socket.close(code=1008, reason="sandbox_closed")
            except Exception:
                pass
        await self._dispose(sandbox)
        logger.info("Sandbox %s closed (%d live)", sandbox.sandbox_id, len(self._sandboxes))

    async def _dispose(self, sandbox: Sandbox) -> None:
        try:
            await sandbox.container.shutdown(blocking_in_thread=True)
        except Exception:
            logger.exception("Sandbox %s did not shut down cleanly", sandbox.sandbox_id)
        await asyncio.to_thread(shutil.rmtree, sandbox.base_dir, True)

    async def _reap_loop(self) -> None:
        while True:
            await asyncio.sleep(REAP_INTERVAL_S)
            try:
                await self.reap()
            except Exception:
                logger.exception("Sandbox cleanup failed")

    async def reap(self, now: float | None = None) -> list[str]:
        now = time.monotonic() if now is None else now
        idle_s = self.limits.idle_minutes * 60
        max_age_s = self.limits.max_age_minutes * 60
        expired = [s for s in self.sandboxes() if now - s.created >= max_age_s or (not s.sockets and now - s.last_seen >= idle_s)]
        for sandbox in expired:
            await self.close(sandbox)
        for sandbox in self.sandboxes():
            if not sandbox.sockets and now - sandbox.last_seen >= SENSOR_PAUSE_AFTER_S and active_sensors(sandbox.container):
                await asyncio.to_thread(self._pause_sensors, sandbox)
        return [s.sandbox_id for s in expired]

    def _pause_sensors(self, sandbox: Sandbox) -> None:
        sensors = sandbox.container.sensors
        for sensor_id, session in list(sensors.sessions.items()):
            if session.status in INACTIVE_SENSOR_STATUSES:
                continue
            try:
                sensors.disconnect(sensor_id)
            except Exception:
                logger.exception("Could not pause sensor %s in sandbox %s", sensor_id, sandbox.sandbox_id)
        sandbox.container.activity.info("sensor", "Simulated sensors were paused because no tab was open; reconnect them on Sensor Connections")

    def check_sensor_capacity(self) -> None:
        streaming = sum(active_sensors(s.container) for s in self.sandboxes())
        if streaming >= self.limits.max_streaming_sensors:
            raise conflict(
                "server_busy_sensors",
                f"The free demo server is already running {streaming} simulated sensor(s) for other visitors, which is its limit. Try again in a few minutes.",
                {"max_streaming_sensors": self.limits.max_streaming_sensors},
            )

    def start_training(self, container: AppContainer, config: Any) -> dict:
        clamped = config.model_copy(update={
            "n_estimators": min(config.n_estimators, self.limits.max_trees),
            "n_splits_max": min(config.n_splits_max, self.limits.max_folds),
            "n_jobs": 1,
        })
        with self._training_lock:
            if any(s.container is not container and s.container.training.active_job_id for s in self.sandboxes()):
                raise conflict("server_busy", "Another visitor is training a model right now. The free demo server trains one model at a time, so try again in a minute.")
            return container.training.start(clamped)
