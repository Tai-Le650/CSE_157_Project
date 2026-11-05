from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sklearn
from sqlalchemy import select

from ..api.errors import AppError, conflict, not_found
from ..database.models import ModelRow, iso
from ..recordings.storage import sha256_file
from .features.registry import FEATURES, FeatureSpec

LEGACY_MODEL_ID = "legacy-cli-gestures"
LEGACY_FILE = "gestures.joblib"


def major_minor(version: str | None) -> str | None:
    if not version:
        return None
    return ".".join(version.split(".")[:2])


@dataclass
class LoadedModel:
    model_id: str
    name: str
    estimator: Any
    feature: FeatureSpec
    window_s: float
    labels: list[str]
    idle_labels: list[str]
    manifest: dict
    source: str
    sha256: str
    workspace: str

    @property
    def rate_requirements(self) -> dict:
        return self.manifest.get("rate_requirements") or {}


class ModelRegistry:
    def __init__(self, paths: Any, db: Any, activity: Any, labels: Any, workspace_provider):
        self.paths = paths
        self.db = db
        self.activity = activity
        self.labels = labels
        self.workspace = workspace_provider
        self._cache: dict[tuple[str, str], LoadedModel] = {}
        self._lock = threading.Lock()

    def _path(self, row: ModelRow) -> Path:
        return self.paths.resolve("models", row.file_path)

    def _path_by_id(self, model_id: str) -> Path:
        with self.db() as db:
            return self._path(self._row(db, model_id))

    def _row(self, db, model_id: str) -> ModelRow:
        row = db.get(ModelRow, model_id)
        if row is None or row.workspace != self.workspace():
            raise not_found("Model", model_id)
        return row

    def scan_legacy(self) -> None:
        if self.workspace() != "real":
            return
        path = self.paths.models_dir / LEGACY_FILE
        with self.db.begin() as db:
            row = db.get(ModelRow, LEGACY_MODEL_ID)
            if not path.is_file():
                if row is not None:
                    row.manifest = {**(row.manifest or {}), "file_missing": True}
                return
            digest = sha256_file(path)
            if row is None:
                db.add(ModelRow(
                    model_id=LEGACY_MODEL_ID,
                    workspace="real",
                    name="Legacy CLI model (models/gestures.joblib)",
                    source="legacy_cli",
                    file_path=LEGACY_FILE,
                    sha256=digest,
                    feature_version="unknown",
                    trusted=False,
                    manifest={"source": "legacy_cli", "note": "Created by src/train.py. Not loaded until you confirm you trust this local file (joblib files can execute code when loaded).", "file_missing": False},
                ))
            elif row.sha256 != digest:
                row.sha256 = digest
                row.trusted = False
                row.manifest = {**(row.manifest or {}), "file_missing": False, "note": "The file changed since it was last trusted; confirm trust again."}
            else:
                row.manifest = {**(row.manifest or {}), "file_missing": False}

    def compatibility(self, row: ModelRow) -> dict:
        reasons, warnings = [], []
        manifest = row.manifest or {}
        if row.workspace != self.workspace():
            reasons.append("Model belongs to the other mode (Demo vs real)")
        if not row.trusted:
            reasons.append("Model is not trusted yet" if row.source == "legacy_cli" else "Model is not trusted")
        path = self._path(row)
        if not path.is_file():
            reasons.append(f"Artifact file is missing: {path}")
        if row.feature_version == "airwriting-dtw-v1":
            reasons.append("Air-writing model (experimental): use it from the Air-writing panel, not Live Recognition")
        elif row.feature_version not in FEATURES:
            reasons.append(f"Unknown feature version '{row.feature_version}'")
        trained_with = (manifest.get("versions") or {}).get("scikit_learn")
        if trained_with and major_minor(trained_with) != major_minor(sklearn.__version__):
            reasons.append(f"Trained with scikit-learn {trained_with}; this backend has {sklearn.__version__}. Retrain the model.")
        elif not trained_with:
            warnings.append(f"Training scikit-learn version not recorded; loading with {sklearn.__version__}")
        labels = manifest.get("labels") or []
        if row.trusted and not labels:
            reasons.append("Model labels are unknown")
        idle = set(self.labels.idle_ids())
        if labels and not idle & set(labels) and row.feature_version != "airwriting-dtw-v1":
            reasons.append("Model has no Idle / No Gesture class; it could act on every movement")
        window = (manifest.get("window") or {}).get("window_s")
        if row.trusted and (window is None or window < 0.2 or window > 5):
            reasons.append(f"Invalid window length {window}")
        rates = manifest.get("rate_requirements") or {}
        if row.trusted and not rates.get("accept_min_hz"):
            warnings.append("Training sampling rate not recorded; only the minimum sample count is enforced")
        return {"compatible": not reasons, "reasons": reasons, "warnings": warnings}

    def to_dict(self, row: ModelRow, selected_id: str | None = None) -> dict:
        manifest = row.manifest or {}
        evaluation = manifest.get("evaluation") or {}
        return {
            "model_id": row.model_id,
            "name": row.name,
            "source": row.source,
            "workspace": row.workspace,
            "feature_version": row.feature_version,
            "trusted": row.trusted,
            "created_at": iso(row.created_at),
            "labels": manifest.get("labels"),
            "window_s": (manifest.get("window") or {}).get("window_s"),
            "file": {"path": row.file_path, "absolute": str(self._path(row)), "sha256": row.sha256},
            "evaluation_summary": {
                "status": evaluation.get("status"),
                "accuracy": evaluation.get("accuracy"),
                "macro_f1": (evaluation.get("macro") or {}).get("f1"),
                "n_splits": evaluation.get("n_splits"),
                "message": evaluation.get("message"),
            },
            "training_windows": (manifest.get("training_data") or {}).get("windows"),
            "dataset": (manifest.get("training_data") or {}).get("dataset"),
            "rate_requirements": manifest.get("rate_requirements"),
            "selected": row.model_id == selected_id,
            "compatibility": self.compatibility(row),
            "note": manifest.get("note"),
        }

    def list(self, selected_id: str | None = None) -> list[dict]:
        self.scan_legacy()
        with self.db() as db:
            rows = db.scalars(select(ModelRow).where(ModelRow.workspace == self.workspace()).order_by(ModelRow.created_at.desc())).all()
            return [self.to_dict(r, selected_id) for r in rows]

    def detail(self, model_id: str, selected_id: str | None = None) -> dict:
        with self.db() as db:
            row = self._row(db, model_id)
            return {**self.to_dict(row, selected_id), "manifest": row.manifest}

    def register_app_model(self, manifest: dict, sha256: str) -> dict:
        model_id = manifest["model_id"]
        workspace = manifest["workspace"]
        artifact = (manifest.get("artifact") or {}).get("file", "model.joblib")
        relative = f"demo/{model_id}/{artifact}" if workspace == "demo" else f"{model_id}/{artifact}"
        with self.db.begin() as db:
            db.add(ModelRow(model_id=model_id, workspace=workspace, name=manifest["name"], source="app", file_path=relative, sha256=sha256, feature_version=manifest["feature_version"], trusted=True, manifest=manifest))
        self.activity.info("training", f"Model {manifest['name']} saved ({model_id})", model_id=model_id)
        return self.detail(model_id)

    def trust(self, model_id: str, confirm: bool) -> dict:
        if not confirm:
            raise conflict("confirmation_required", "Loading a joblib file runs Python code from that file. Only trust files you created yourself. Resend with confirm=true.")
        with self.db() as db:
            row = self._row(db, model_id)
        if row.source != "legacy_cli":
            raise conflict("already_trusted", "Models trained by this app are trusted by their recorded hash")
        path = self._path(row)
        if not path.is_file():
            raise AppError("file_missing", f"{path} is missing", 410)
        digest = sha256_file(path)
        import joblib

        payload = joblib.load(path)
        if not isinstance(payload, dict) or "model" not in payload:
            raise conflict("unexpected_artifact", "The file is not a legacy {model, feature_version, window_seconds} artifact")
        feature_version = payload.get("feature_version")
        if feature_version != "summary-60-v1":
            raise conflict("model_incompatible", f"Legacy artifact feature_version is {feature_version!r}; only summary-60-v1 is supported")
        estimator = payload["model"]
        if not hasattr(estimator, "predict_proba"):
            raise conflict("model_incompatible", "The legacy model has no predict_proba")
        labels = [str(c) for c in getattr(estimator, "classes_", [])]
        window = float(payload.get("window_seconds", 0.9))
        with self.db.begin() as db:
            live = db.get(ModelRow, model_id)
            live.trusted = True
            live.sha256 = digest
            live.feature_version = feature_version
            live.manifest = {
                **(live.manifest or {}),
                "labels": labels,
                "window": {"window_s": window, "default_hop_s": 0.1, "augment_shifts_s": []},
                "feature_version": feature_version,
                "trusted_sha256": digest,
                "note": "Trusted legacy CLI model. Its training data, scikit-learn version and sampling rate were not recorded by src/train.py.",
                "evaluation": {"status": "not_recorded", "message": "src/train.py printed a random-split report but did not store it"},
            }
        self.activity.warning("training", "Legacy CLI model trusted after confirmation", model_id=model_id, sha256=digest)
        return self.detail(model_id)

    def rename(self, model_id: str, name: str) -> dict:
        with self.db.begin() as db:
            row = self._row(db, model_id)
            row.name = name.strip() or row.name
        return self.detail(model_id)

    def delete(self, model_id: str, confirm: bool) -> dict:
        if not confirm:
            raise conflict("confirmation_required", "Resend with confirm=true")
        with self.db.begin() as db:
            row = self._row(db, model_id)
            removed = []
            if row.source == "app":
                directory = self._path(row).parent
                models_root = self.paths.models_dir.resolve()
                if directory.resolve() != models_root and models_root in directory.resolve().parents and directory.is_dir():
                    shutil.rmtree(directory)
                    removed.append(str(directory))
            db.delete(row)
        with self._lock:
            for key in [k for k in self._cache if k[0] == model_id]:
                self._cache.pop(key, None)
        kept = [] if removed else [f"{LEGACY_FILE} kept (the app never deletes CLI files)"]
        return {"model_id": model_id, "removed": removed, "kept": kept}

    def load(self, model_id: str) -> LoadedModel:
        with self.db() as db:
            row = self._row(db, model_id)
        compat = self.compatibility(row)
        if not compat["compatible"]:
            raise conflict("model_incompatible", "This model cannot be used", compat)
        path = self._path(row)
        digest = sha256_file(path)
        if digest != row.sha256:
            raise conflict("model_hash_mismatch", "The model file changed since it was registered; it will not be loaded", {"expected": row.sha256, "actual": digest})
        key = (model_id, digest)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        import joblib

        payload = joblib.load(path)
        if not isinstance(payload, dict) or "model" not in payload:
            raise conflict("unexpected_artifact", "Artifact is not a model dictionary")
        estimator = payload["model"]
        manifest = row.manifest or {}
        labels = [str(c) for c in estimator.classes_]
        if manifest.get("labels") and labels != list(manifest["labels"]):
            raise conflict("label_mismatch", "Model classes differ from the manifest", {"manifest": manifest.get("labels"), "model": labels})
        if payload.get("feature_version") != row.feature_version:
            raise conflict("feature_mismatch", "Artifact feature version differs from the registry entry")
        idle = sorted(set(self.labels.idle_ids()) & set(labels))
        loaded = LoadedModel(
            model_id=model_id,
            name=row.name,
            estimator=estimator,
            feature=FEATURES[row.feature_version],
            window_s=float(payload.get("window_seconds") or (manifest.get("window") or {}).get("window_s")),
            labels=labels,
            idle_labels=idle,
            manifest=manifest,
            source=row.source,
            sha256=digest,
            workspace=row.workspace,
        )
        with self._lock:
            self._cache[key] = loaded
        return loaded
