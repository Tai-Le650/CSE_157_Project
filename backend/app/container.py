from __future__ import annotations

import asyncio
import time

from .control.executor import PyAutoGuiBackend, RecordingFakeBackend
from .control.service import ControlService
from .database.engine import make_engine, make_session_factory
from .database.migrations import init_db
from .realtime.activity_log import ActivityLog, configure_logging
from .realtime.hub import Hub
from .sensors.bus import SampleBus
from .sensors.manager import SensorManager
from .settings.config import AppConfig
from .settings.service import SettingsService

APP_NAME = "Gesture-to-PC"
APP_VERSION = "1.0.0"


class AppContainer:
    def __init__(self, config: AppConfig):
        self.config = config
        self.paths = config.paths
        self.paths.ensure()
        configure_logging(self.paths.logs_dir if config.log_to_file else None)
        self.engine = make_engine(self.paths.db_path)
        self.db = make_session_factory(self.engine)
        init_db(self.engine, self.db)
        self.settings = SettingsService(self.db)
        self.hub = Hub(flush_interval_s=config.ui_flush_interval_s)
        self.activity = ActivityLog(self.hub)
        self.bus = SampleBus()
        self.sensors = SensorManager(
            self.bus,
            self.hub,
            self.activity,
            workspace_provider=self.workspace,
            auto_reconnect_provider=lambda: self.settings.current.acquisition.auto_reconnect,
            stall_timeout_provider=lambda: self.settings.current.acquisition.stall_timeout_s,
            opener=config.serial_opener,
            health_interval_s=config.health_interval_s,
        )
        self.control = ControlService(
            self.hub,
            self.activity,
            self.settings,
            self.workspace,
            backend_factory=self._make_os_backend,
            enable_global_hotkey=config.enable_global_hotkey,
        )
        self.control.sensor_health = self._sensor_healthy
        self.hub.close_listeners.append(self.control.on_client_closed)
        self.sensors.add_listener(self.control.on_sensor_event)
        self.settings.add_listener(self._on_settings_changed)
        self.hub.snapshot_provider = self.snapshot
        self.started_at = time.time()
        self._status_task: asyncio.Task | None = None
        self.extensions: list = []

    def workspace(self) -> str:
        return "demo" if self.settings.current.demo_mode else "real"

    def _make_os_backend(self):
        if not self.config.enable_os_control:
            return RecordingFakeBackend()
        return PyAutoGuiBackend()

    def _sensor_healthy(self, sensor_id: str) -> bool:
        session = self.sensors.sessions.get(sensor_id)
        return session is not None and session.status == "streaming"

    def _on_settings_changed(self, old, new) -> None:
        self.control.on_settings_changed(old, new)
        self.hub.publish("status", "settings", new.model_dump())
        self.publish_status()

    async def startup(self) -> None:
        await self.hub.start()
        self.sensors.start()
        self.control.start()
        for extension in self.extensions:
            hook = getattr(extension, "on_startup", None)
            if hook:
                hook()
        self.activity.info("system", f"{APP_NAME} backend started on {self.config.host}:{self.config.port}", workspace=self.workspace())
        self._status_task = asyncio.create_task(self._status_loop())

    async def shutdown(self) -> None:
        self.control.disarm("shutdown")
        if self._status_task:
            self._status_task.cancel()
            try:
                await self._status_task
            except asyncio.CancelledError:
                pass
        for extension in reversed(self.extensions):
            hook = getattr(extension, "on_shutdown", None)
            if hook:
                try:
                    hook()
                except Exception:
                    pass
        self.control.stop()
        self.sensors.stop()
        await self.hub.stop()
        self.engine.dispose()

    async def _status_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            self.publish_status()

    def modes(self) -> dict:
        sensors = self.sensors.sessions.values()
        return {
            "monitoring": any(s.status == "streaming" for s in sensors),
            "recording": bool(getattr(getattr(self, "recorder", None), "active", False)),
            "recognition": bool(getattr(getattr(self, "recognition", None), "running", False)),
            "pc_control": self.control.armed,
            "demo": self.workspace() == "demo",
        }

    def status(self) -> dict:
        modes = self.modes()
        if modes["demo"]:
            primary = "Demo"
        elif modes["pc_control"]:
            primary = "PC Control"
        elif modes["recognition"]:
            primary = "Recognition"
        elif modes["recording"]:
            primary = "Recording"
        elif modes["monitoring"]:
            primary = "Monitoring"
        else:
            primary = "Idle"
        training = getattr(self, "training", None)
        return {
            "app": APP_NAME,
            "version": APP_VERSION,
            "workspace": self.workspace(),
            "primary_mode": primary,
            "modes": modes,
            "estop_latched": self.control.estop_latched,
            "training_active": bool(training.active_job_id) if training else False,
            "sensors_streaming": sum(1 for s in self.sensors.sessions.values() if s.status == "streaming"),
            "clients": self.hub.client_count,
            "ui_frames_dropped": self.hub.ui_frames_dropped,
            "ui_samples_dropped": self.hub.ui_samples_dropped,
            "uptime_s": time.time() - self.started_at,
            "time": time.time(),
            "data_dir": str(self.paths.data_dir),
            "data_dir_is_default": self.paths.data_dir_is_default,
        }

    def publish_status(self) -> None:
        self.hub.publish("status", "status", self.status())

    def snapshot(self) -> dict:
        snap = {
            "status": self.status(),
            "sensors": self.sensors.snapshot(),
            "control": self.control.state(),
            "settings": self.settings.current.model_dump(),
            "recent_log": self.activity.recent(60),
        }
        for extension in self.extensions:
            provider = getattr(extension, "snapshot", None)
            name = getattr(extension, "snapshot_key", None)
            if provider and name:
                try:
                    snap[name] = provider()
                except Exception:
                    snap[name] = None
        return snap
