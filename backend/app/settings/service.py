from __future__ import annotations

import threading
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from ..database.models import SettingRow

SETTINGS_KEY = "app"


class AcquisitionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_baud: int = Field(115200, ge=300, le=4_000_000, description="Must match the firmware's Serial.begin() value (115200 in the included sketches).")
    auto_reconnect: bool = Field(False, description="Retry a lost serial connection every 2 s. Never re-arms PC control.")
    stall_timeout_s: float = Field(1.5, ge=0.3, le=30, description="No valid samples for this long marks the sensor as stalled.")


class RecordingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trial_duration_s: float = Field(1.5, ge=0.3, le=30)
    countdown_s: float = Field(3.0, ge=0, le=10)
    trials_per_set: int = Field(10, ge=1, le=200)
    pause_between_s: float = Field(1.0, ge=0, le=30)


class DisplaySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window_s: float = Field(10.0, ge=1, le=60)
    accel_unit: Literal["g", "m/s2"] = "g"
    gyro_unit: Literal["deg/s", "rad/s"] = "deg/s"


class InferenceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hop_s: float = Field(0.1, ge=0.02, le=2.0, description="Time between consecutive windows (window minus overlap).")
    threshold: float = Field(0.85, gt=0, le=1)
    smoothing_k: int = Field(3, ge=1, le=20, description="Number of recent windows whose probabilities are averaged.")
    debounce_n: int = Field(2, ge=1, le=20, description="Consecutive smoothed windows required before a detection.")
    cooldown_s: float = Field(1.2, ge=0, le=30)
    require_idle_rearm: bool = Field(True, description="After a detection, require a confident idle window before the next one.")


class ControlSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pc_control_enabled: bool = Field(False, description="Master switch. When off, arming is impossible.")
    heartbeat_timeout_s: float = Field(3.0, ge=1, le=30)
    global_estop_hotkey: str = Field("ctrl+alt+backspace", description="System-wide Emergency Stop hotkey, registered only while armed.")
    global_hotkey_enabled: bool = True
    auto_disarm_idle_minutes: float = Field(10.0, ge=0, le=240, description="Disarm after this many minutes without an executed action (0 = never).")
    sound_activation_required: bool = Field(False, description="Only act while the sound-activation state is active (requires a microphone stream).")


class CursorSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x_axis: Literal["gx", "gy", "gz"] = "gz"
    y_axis: Literal["gx", "gy", "gz"] = "gx"
    invert_x: bool = True
    invert_y: bool = False
    gain_px_per_deg: float = Field(4.0, gt=0, le=100)
    dead_zone_dps: float = Field(8.0, ge=0, le=200)
    max_speed_px_s: float = Field(1500.0, gt=0, le=10000)
    bias_dps: dict[str, float] = Field(default_factory=lambda: {"gx": 0.0, "gy": 0.0, "gz": 0.0}, description="Gyro bias measured during stillness calibration")
    noise_dps: dict[str, float] = Field(default_factory=dict)
    calibrated_sensor_id: str | None = None
    calibrated_at: float | None = None


class SoundSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    threshold: float = Field(0.5, gt=0, le=1.0)
    active_window_s: float = Field(8.0, ge=1, le=120)
    refractory_s: float = Field(1.0, ge=0, le=10)


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    theme: Literal["light", "dark", "system"] = "light"
    demo_mode: bool = False
    selected_sensor_id: str | None = None
    selected_model_id: str | None = None
    active_profile_id: str | None = "browser-navigation"
    acquisition: AcquisitionSettings = AcquisitionSettings()
    recording: RecordingSettings = RecordingSettings()
    display: DisplaySettings = DisplaySettings()
    inference: InferenceSettings = InferenceSettings()
    control: ControlSettings = ControlSettings()
    cursor: CursorSettings = CursorSettings()
    sound: SoundSettings = SoundSettings()


def deep_merge(base: dict, patch: dict) -> dict:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class SettingsService:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._factory = session_factory
        self._lock = threading.Lock()
        self._listeners: list[Callable[[AppSettings, AppSettings], None]] = []
        self._current = self._load()

    def _load(self) -> AppSettings:
        with self._factory() as db:
            row = db.get(SettingRow, SETTINGS_KEY)
            stored = row.value if row else {}
        defaults = AppSettings().model_dump()
        try:
            return AppSettings.model_validate(deep_merge(defaults, stored or {}))
        except ValueError:
            return AppSettings()

    def _save(self, settings: AppSettings) -> None:
        with self._factory.begin() as db:
            row = db.get(SettingRow, SETTINGS_KEY)
            payload = settings.model_dump()
            if row is None:
                db.add(SettingRow(key=SETTINGS_KEY, value=payload))
            else:
                row.value = payload

    @property
    def current(self) -> AppSettings:
        return self._current

    def add_listener(self, callback: Callable[[AppSettings, AppSettings], None]) -> None:
        self._listeners.append(callback)

    def update(self, patch: dict) -> AppSettings:
        with self._lock:
            old = self._current
            merged = deep_merge(old.model_dump(), patch)
            new = AppSettings.model_validate(merged)
            self._save(new)
            self._current = new
        for callback in list(self._listeners):
            callback(old, new)
        return new

    def replace(self, settings: AppSettings) -> AppSettings:
        return self.update(settings.model_dump())
