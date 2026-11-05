from __future__ import annotations

import multiprocessing as mp
import queue as queue_module
import shutil
import threading
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..api.errors import AppError, conflict, not_found
from ..database.models import DerivativeRow, RecordingRow, TrainingJobRow, iso, utcnow
from ..recordings.library import APP_VERSION_TAG
from ..recordings.storage import new_id
from .features.registry import FEATURES
from .worker import run_airwriting_job, run_training_job


class TrainingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str = Field(min_length=1, max_length=64)
    name: str | None = Field(None, max_length=120)
    feature_version: Literal["stats-spectral-v1", "summary-60-v1", "airwriting-dtw-v1"] = "stats-spectral-v1"
    window_s: float | None = Field(None, ge=0.3, le=3.0)
    augment: bool = Field(True, description="Add windows shifted ±0.12 s and ±0.25 s around each gesture peak when the trial is long enough (stats-spectral-v1 only)")
    n_estimators: int = Field(300, ge=10, le=2000)
    max_depth: int | None = Field(None, ge=2, le=100)
    min_samples_leaf: int = Field(1, ge=1, le=50)
    class_weight: Literal["balanced_subsample", "balanced"] | None = "balanced_subsample"
    random_state: int = 42
    n_splits_max: int = Field(5, ge=2, le=10)
    n_jobs: int = Field(2, ge=1, le=8, description="CPU cores for the forest; keep low so acquisition stays responsive")


class TrainingService:
    snapshot_key = "training"

    def __init__(self, paths: Any, db: Any, datasets: Any, library: Any, labels: Any, registry: Any, hub: Any, activity: Any, workspace_provider, start_method: str = "spawn"):
        self.paths = paths
        self.db = db
        self.datasets = datasets
        self.library = library
        self.labels = labels
        self.registry = registry
        self.hub = hub
        self.activity = activity
        self.workspace = workspace_provider
        self.start_method = start_method
        self.active_job_id: str | None = None
        self._process = None
        self._lock = threading.Lock()
        self._live: dict[str, dict] = {}

    def _job_dict(self, row: TrainingJobRow) -> dict:
        live = self._live.get(row.job_id, {})
        return {
            "job_id": row.job_id,
            "workspace": row.workspace,
            "dataset_id": row.dataset_id,
            "config": row.config,
            "status": row.status,
            "stage": live.get("stage", row.stage),
            "progress": live.get("progress", row.progress),
            "message": live.get("message", row.message),
            "result": row.result,
            "model_id": row.model_id,
            "created_at": iso(row.created_at),
            "finished_at": iso(row.finished_at),
        }

    def list_jobs(self, limit: int = 20) -> list[dict]:
        with self.db() as db:
            rows = db.scalars(select(TrainingJobRow).where(TrainingJobRow.workspace == self.workspace()).order_by(TrainingJobRow.created_at.desc()).limit(limit)).all()
            return [self._job_dict(r) for r in rows]

    def get_job(self, job_id: str) -> dict:
        with self.db() as db:
            row = db.get(TrainingJobRow, job_id)
            if row is None or row.workspace != self.workspace():
                raise not_found("Training job", job_id)
            return self._job_dict(row)

    def snapshot(self) -> dict:
        active = None
        if self.active_job_id:
            try:
                active = self.get_job(self.active_job_id)
            except AppError:
                active = None
        return {"active_job": active, "recent": self.list_jobs(5)}

    def build_spec(self, config: TrainingConfig, job_id: str, model_id: str) -> dict:
        idle_ids = self.labels.idle_ids()
        detail = self.datasets.detail(config.dataset_id)
        airwriting = config.feature_version == "airwriting-dtw-v1"
        readiness = self.datasets.readiness(config.dataset_id, detail["members"], set() if airwriting else idle_ids)
        if airwriting:
            readiness["problems"] = [p for p in readiness["problems"] if p["code"] != "no_idle"]
            readiness["ready"] = not readiness["problems"]
        if not readiness["ready"]:
            raise conflict("dataset_not_ready", "The dataset is not ready for training", readiness)
        window_s = None if airwriting else (config.window_s or FEATURES[config.feature_version].default_window_s)
        member_specs = []
        with self.db() as db:
            for m in detail["members"]:
                rec = db.get(RecordingRow, m["recording_id"])
                d = db.get(DerivativeRow, m["derivative_id"]) if m["derivative_id"] else None
                group = f"session:{rec.session_id}" if rec.session_id else f"recording:{rec.recording_id}"
                member_specs.append({
                    "recording_id": rec.recording_id,
                    "segment_id": m["segment_id"],
                    "segment": m["segment"],
                    "label_id": m["label_id"],
                    "group": group,
                    "group_kind": "session" if rec.session_id else "recording",
                    "file": str(self.library.path_for(rec)),
                    "header_alias": rec.header_alias,
                    "time_unit": rec.time_unit,
                    "derivative_id": d.derivative_id if d else None,
                    "derivative_file": str(self.paths.resolve("data", d.file_path)) if d else None,
                    "sha256": d.sha256 if d else rec.sha256,
                    "fs_median_hz": rec.fs_median_hz,
                    "source": rec.source,
                    "kind": rec.kind,
                })
        workspace = self.workspace()
        return {
            "job_id": job_id,
            "model_id": model_id,
            "name": config.name or f"{config.feature_version} on {detail['name']}",
            "workspace": workspace,
            "feature_version": config.feature_version,
            "window_s": window_s,
            "augment": config.augment,
            "rf": {"n_estimators": config.n_estimators, "max_depth": config.max_depth, "min_samples_leaf": config.min_samples_leaf, "class_weight": config.class_weight, "random_state": config.random_state, "n_jobs": config.n_jobs},
            "n_splits_max": config.n_splits_max,
            "members": member_specs,
            "idle_ids": sorted(idle_ids),
            "src_dir": str(self.paths.src_dir),
            "output_dir": str(self.paths.models_root(workspace) / model_id),
            "dataset": {"dataset_id": detail["dataset_id"], "name": detail["name"], "member_count": len(member_specs), "readiness_warnings": readiness["warnings"]},
            "app": APP_VERSION_TAG,
        }

    def start(self, config: TrainingConfig) -> dict:
        with self._lock:
            if self.active_job_id:
                raise conflict("training_busy", "A training job is already running", {"job_id": self.active_job_id})
            job_id = new_id("job", config.feature_version)
            model_id = new_id("mdl", config.feature_version)
            spec = self.build_spec(config, job_id, model_id)
            with self.db.begin() as db:
                db.add(TrainingJobRow(job_id=job_id, workspace=spec["workspace"], dataset_id=config.dataset_id, config=config.model_dump(), status="running", stage="starting", progress=0.0, message="Starting worker process"))
            context = mp.get_context(self.start_method)
            channel = context.Queue()
            target = run_airwriting_job if config.feature_version == "airwriting-dtw-v1" else run_training_job
            process = context.Process(target=target, args=(spec, channel), name=f"train-{job_id}", daemon=True)
            process.start()
            self._process = process
            self.active_job_id = job_id
            self._live[job_id] = {"stage": "starting", "progress": 0.0, "message": "Starting worker process"}
        threading.Thread(target=self._monitor, args=(job_id, process, channel, spec), name=f"train-monitor-{job_id}", daemon=True).start()
        self.activity.info("training", f"Training started: {spec['name']} ({len(spec['members'])} members)", job_id=job_id)
        self._publish(job_id)
        return self.get_job(job_id)

    def _publish(self, job_id: str) -> None:
        try:
            self.hub.publish("training", "training", self.get_job(job_id))
        except AppError:
            pass

    def _finish(self, job_id: str, status: str, message: str, result: dict | None = None, model_id: str | None = None) -> None:
        with self.db.begin() as db:
            row = db.get(TrainingJobRow, job_id)
            if row is None:
                return
            row.status = status
            row.stage = status
            row.progress = 1.0 if status == "done" else row.progress
            row.message = message
            row.result = result or {}
            row.model_id = model_id
            row.finished_at = utcnow()
        self._live.pop(job_id, None)
        with self._lock:
            if self.active_job_id == job_id:
                self.active_job_id = None
                self._process = None
        self._publish(job_id)

    def _monitor(self, job_id: str, process, channel, spec: dict) -> None:
        last_db_write = 0.0
        while True:
            try:
                message = channel.get(timeout=0.5)
            except queue_module.Empty:
                if not process.is_alive():
                    if self.active_job_id == job_id:
                        status = "cancelled" if self._live.get(job_id, {}).get("cancelled") else "failed"
                        self._finish(job_id, status, "Cancelled by user" if status == "cancelled" else f"Worker exited unexpectedly (exit code {process.exitcode})")
                        shutil.rmtree(spec["output_dir"], ignore_errors=True)
                    return
                continue
            kind = message.get("type")
            if kind == "progress":
                self._live[job_id] = {**self._live.get(job_id, {}), "stage": message["stage"], "progress": message["progress"], "message": message.get("message", "")}
                now = time.monotonic()
                if now - last_db_write > 1.0:
                    with self.db.begin() as db:
                        row = db.get(TrainingJobRow, job_id)
                        if row is not None:
                            row.stage, row.progress, row.message = message["stage"], message["progress"], message.get("message", "")
                    last_db_write = now
                self._publish(job_id)
            elif kind == "done":
                manifest = message["manifest"]
                try:
                    self.registry.register_app_model(manifest, message["sha256"])
                    summary = {"evaluation": manifest["evaluation"], "training_data": {k: v for k, v in manifest["training_data"].items() if k != "members"}}
                    self._finish(job_id, "done", "Model trained and saved", summary, manifest["model_id"])
                    self.activity.info("training", f"Training finished: {manifest['name']} — evaluation {manifest['evaluation'].get('status')}", job_id=job_id)
                except Exception as exc:
                    self._finish(job_id, "failed", f"Could not register model: {exc}")
                process.join(timeout=5)
                return
            elif kind == "error":
                self._finish(job_id, "failed", message.get("message", "Training failed"), {"traceback": message.get("traceback")})
                self.activity.error("training", f"Training failed: {message.get('message')}", job_id=job_id)
                process.join(timeout=5)
                return

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            if self.active_job_id != job_id or self._process is None:
                raise conflict("job_not_running", "That job is not running")
            self._live[job_id] = {**self._live.get(job_id, {}), "cancelled": True}
            self._process.terminate()
        self.activity.warning("training", f"Training job {job_id} cancelled")
        deadline = time.monotonic() + 5
        while self.active_job_id == job_id and time.monotonic() < deadline:
            time.sleep(0.05)
        return self.get_job(job_id)

    def on_shutdown(self) -> None:
        if self.active_job_id and self._process is not None:
            try:
                self.cancel(self.active_job_id)
            except AppError:
                pass
