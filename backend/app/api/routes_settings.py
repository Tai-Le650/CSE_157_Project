from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import ValidationError

from ..schemas.settings import DemoModeRequest, SettingsPatch, StorageRequest
import os

from ..settings.paths import DATA_DIR_ENV, read_local_settings, resolve_data_dir_override, write_local_settings
from ..settings.service import AppSettings
from .deps import Container
from .errors import AppError, conflict

router = APIRouter(prefix="/api/settings", tags=["settings"])

PROTECTED_KEYS = {"demo_mode"}


@router.get("", response_model=AppSettings, summary="Read persisted settings")
def get_settings(c: Container) -> AppSettings:
    return c.settings.current


@router.patch("", response_model=AppSettings, summary="Update settings (partial)", description="Demo Mode is changed through POST /api/settings/demo-mode because switching has side effects.")
def patch_settings(body: SettingsPatch, c: Container) -> AppSettings:
    if PROTECTED_KEYS & set(body.values):
        raise AppError("use_demo_endpoint", "Change Demo Mode with POST /api/settings/demo-mode", 422)
    try:
        updated = c.settings.update(body.values)
    except ValidationError as exc:
        raise AppError("validation_error", "Invalid settings", 422, [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"]} for e in exc.errors()])
    c.activity.info("settings", "Settings updated", keys=sorted(body.values))
    return updated


@router.post("/demo-mode", response_model=AppSettings, summary="Switch between real and Demo Mode", description="Disconnects all sensors, stops recognition and disarms PC control. Requires confirm=true and no active recording or training.")
def set_demo_mode(body: DemoModeRequest, c: Container) -> AppSettings:
    current = c.settings.current.demo_mode
    if body.enabled == current:
        return c.settings.current
    if not body.confirm:
        raise conflict("confirmation_required", "Switching modes disconnects all sensors and disarms PC control. Resend with confirm=true.")
    recorder = getattr(c, "recorder", None)
    if recorder is not None and recorder.active:
        raise conflict("recording_active", "Stop the active recording before switching modes")
    training = getattr(c, "training", None)
    if training is not None and training.active_job_id:
        raise conflict("training_active", "Wait for (or cancel) the running training job before switching modes")
    c.control.disarm("mode_changed")
    recognition = getattr(c, "recognition", None)
    if recognition is not None and recognition.running:
        recognition.stop("mode_changed")
    for sensor_id in list(c.sensors.sessions):
        c.sensors.remove(sensor_id)
    updated = c.settings.update({"demo_mode": body.enabled, "selected_model_id": None, "selected_sensor_id": None})
    c.activity.warning("system", "Demo Mode ON — simulated sensors only, all OS actions simulated" if body.enabled else "Demo Mode OFF — real sensors and real PC control available")
    return updated


@router.get("/storage", summary="Data directory and storage locations")
def storage(c: Container) -> dict:
    local = read_local_settings(c.paths.config_root)
    next_dir = resolve_data_dir_override(c.paths.config_root) or c.paths.default_data_dir
    return {
        "data_dir": str(c.paths.data_dir),
        "data_dir_is_default": c.paths.data_dir_is_default,
        "models_dir": str(c.paths.models_dir),
        "cli_data_dir": str(c.paths.cli_data_dir),
        "pending_data_dir": local.get("data_dir"),
        "environment_override": os.environ.get(DATA_DIR_ENV),
        "restart_required": Path(next_dir).resolve() != c.paths.data_dir.resolve(),
    }


@router.put("/storage", summary="Change the data directory (takes effect after restart)")
def set_storage(body: StorageRequest, c: Container) -> dict:
    local = read_local_settings(c.paths.config_root)
    if body.data_dir:
        target = Path(body.data_dir).expanduser()
        if not target.is_absolute():
            raise AppError("absolute_path_required", "Use an absolute folder path", 422)
        if target.exists() and not target.is_dir():
            raise AppError("not_a_directory", "That path exists and is not a folder", 422)
        local["data_dir"] = str(target.resolve())
    else:
        local.pop("data_dir", None)
    write_local_settings(c.paths.config_root, local)
    c.activity.warning("settings", "Data directory change saved; restart the backend to apply it", data_dir=local.get("data_dir"))
    return storage(c)
