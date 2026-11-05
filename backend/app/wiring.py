from __future__ import annotations

from fastapi import APIRouter

from .api import routes_advanced, routes_datasets, routes_ml, routes_recordings
from .container import AppContainer
from .control.cursor import CursorController
from .control.mappings import MappingService
from .ml.artifacts import ModelRegistry
from .ml.inference import RecognitionEngine
from .ml.training import TrainingService
from .processing.activation import SoundActivationService
from .recordings.datasets import DatasetService
from .recordings.importer import ImportService
from .recordings.labels import LabelService
from .recordings.library import RecordingLibrary
from .recordings.recorder import RecorderService
from .recordings.sessions import SessionService
from .sensors.sync import SyncService


def attach_services(c: AppContainer) -> list[APIRouter]:
    c.labels = LabelService(c.db, c.activity, c.workspace)
    c.sessions = SessionService(c.db, c.workspace)
    c.library = RecordingLibrary(c.paths, c.db, c.hub, c.activity, c.workspace)
    c.importer = ImportService(c.paths, c.db, c.library, c.labels, c.sessions, c.activity, c.workspace)
    c.datasets = DatasetService(c.paths, c.db, c.library, c.activity, c.workspace)
    c.recorder = RecorderService(c.paths, c.bus, c.sensors, c.hub, c.activity, c.library, c.labels, c.sessions, c.workspace)
    c.registry = ModelRegistry(c.paths, c.db, c.activity, c.labels, c.workspace)
    c.training = TrainingService(c.paths, c.db, c.datasets, c.library, c.labels, c.registry, c.hub, c.activity, c.workspace, c.config.training_start_method)
    c.mappings = MappingService(c.db, c.settings, c.labels, c.activity, on_change=lambda _pid: c.control.disarm("mappings_changed"))
    c.recognition = RecognitionEngine(c.sensors, c.registry, c.settings, c.hub, c.activity, c.control, c.mappings, c.paths.src_dir, c.workspace)
    c.sync = SyncService(c.db, c.bus, c.sensors, c.hub, c.activity, c.workspace)
    c.cursor = CursorController(c.sensors, c.settings, c.control, c.hub, c.activity)
    c.sound = SoundActivationService(c.settings, c.hub, c.activity, c.workspace)
    c.control.activation_check = c.sound.is_active
    c.settings.add_listener(lambda old, new: c.sound.reconfigure() if old.sound != new.sound else None)
    c.settings.add_listener(lambda old, new: on_mode_change(c) if old.demo_mode != new.demo_mode else None)
    c.control.prerequisites = lambda: arm_prerequisites(c)
    c.control.cooldown_provider = lambda: float(c.recognition.config.get("cooldown_s", c.settings.current.inference.cooldown_s)) if c.recognition.running else c.settings.current.inference.cooldown_s
    c.extensions.extend([c.recorder, c.training, c.recognition, c.sync, c.cursor, c.sound])
    return [
        routes_recordings.recorder,
        routes_recordings.recordings,
        routes_recordings.imports,
        routes_recordings.labels,
        routes_recordings.sessions,
        routes_datasets.datasets,
        routes_datasets.analysis,
        routes_ml.training,
        routes_ml.models,
        routes_ml.recognition,
        routes_ml.mappings,
        routes_advanced.advanced,
    ]


def arm_prerequisites(c: AppContainer) -> list[str]:
    reasons: list[str] = []
    recognition = c.recognition
    if not recognition.running or recognition.model is None:
        reasons.append("Start Live Recognition with a trained model first.")
    else:
        if recognition.model.workspace != c.workspace():
            reasons.append("The running model belongs to the other mode.")
        session = c.sensors.sessions.get(recognition.sensor_id)
        if session is None or session.status != "streaming":
            reasons.append(f"Recognition sensor {recognition.sensor_id} is not streaming.")
    if c.mappings.enabled_count() == 0:
        reasons.append("The active mapping profile has no enabled mappings.")
    if c.settings.current.control.sound_activation_required:
        available, why = c.sound.available()
        if not available:
            reasons.append(f"Sound activation is required in Settings but unavailable: {why}")
    return reasons


def on_mode_change(c: AppContainer) -> None:
    c.cursor.stop("mode_changed")
    c.sound.stop_source()
