from __future__ import annotations

import sys
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def _versions() -> dict:
    import joblib
    import numpy
    import scipy
    import sklearn

    return {"python": sys.version.split()[0], "numpy": numpy.__version__, "scipy": scipy.__version__, "scikit_learn": sklearn.__version__, "joblib": joblib.__version__}


def run_training_job(spec: dict, queue) -> None:
    def emit(stage: str, progress: float, message: str = "", **extra) -> None:
        queue.put({"type": "progress", "stage": stage, "progress": round(progress, 4), "message": message, **extra})

    try:
        import joblib
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier

        from ..recordings.storage import sha256_file, write_json
        from .dataset_builder import SHIFTS_S, build_windows
        from .evaluation import grouped_evaluation
        from .features.registry import FEATURES

        feature = FEATURES[spec["feature_version"]]
        members = spec["members"]
        window_s = float(spec["window_s"])
        idle_ids = set(spec["idle_ids"])
        emit("loading", 0.02, f"Loading {len(members)} dataset member(s)")
        windows = build_windows(
            members,
            feature,
            window_s,
            Path(spec["src_dir"]),
            bool(spec.get("augment", True)),
            idle_ids,
            progress=lambda i, n: emit("windows", 0.02 + 0.3 * i / n, f"Extracted windows from member {i}/{n}"),
        )
        if len(windows.y) == 0:
            raise ValueError(f"No usable windows (rejected: {dict(windows.rejected)})")
        labels = sorted({str(v) for v in windows.y})
        if len(labels) < 2:
            raise ValueError(f"Only one label produced windows: {labels}")
        rf_params = dict(spec["rf"])

        def factory():
            return RandomForestClassifier(**rf_params)

        emit("evaluating", 0.34, "Grouped cross-validation (sessions/recordings never split across folds)", windows=int(len(windows.y)))
        with joblib.parallel_config(backend="threading"):
            evaluation = grouped_evaluation(
                windows.X,
                windows.y,
                windows.groups,
                factory,
                n_splits_max=int(spec.get("n_splits_max", 5)),
                random_state=int(rf_params.get("random_state", 42)),
                progress=lambda k, n: emit("evaluating", 0.34 + 0.46 * k / n, f"Fold {k}/{n}"),
            )
            emit("final_fit", 0.84, "Fitting the final model on every window")
            model = factory()
            model.fit(windows.X, windows.y)
        emit("saving", 0.95, "Saving model artifact and manifest")
        out_dir = Path(spec["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=False)
        artifact_path = out_dir / "model.joblib"
        joblib.dump(
            {"model": model, "feature_version": feature.version, "window_seconds": window_s, "labels": [str(c) for c in model.classes_], "model_id": spec["model_id"]},
            artifact_path,
        )
        digest = sha256_file(artifact_path)
        rates = [m["fs_median_hz"] for m in members if m.get("fs_median_hz")]
        group_kinds = {m["group_kind"] for m in members}
        manifest = {
            "model_id": spec["model_id"],
            "name": spec["name"],
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "workspace": spec["workspace"],
            "source": "app",
            "app": spec.get("app"),
            "artifact": {"file": "model.joblib", "sha256": digest, "format": "joblib dict {model, feature_version, window_seconds, labels, model_id}"},
            "feature_version": feature.version,
            "feature_names": list(feature.feature_names),
            "feature_description": feature.description,
            "preprocessing": feature.preprocessing,
            "window": {"window_s": window_s, "default_hop_s": 0.1, "augment_shifts_s": list(SHIFTS_S) if (spec.get("augment", True) and feature.resamples) else []},
            "labels": [str(c) for c in model.classes_],
            "idle_labels": sorted(idle_ids & set(labels)),
            "rate_requirements": {
                "training_fs_min_hz": min(rates) if rates else None,
                "training_fs_max_hz": max(rates) if rates else None,
                "accept_min_hz": 0.85 * min(rates) if rates else None,
                "accept_max_hz": 1.15 * max(rates) if rates else None,
                "basis": "Measured median sampling rates of the training recordings",
            },
            "classifier": {"type": "RandomForestClassifier", "params": rf_params},
            "training_data": {
                "dataset": spec["dataset"],
                "members": [{k: m.get(k) for k in ("recording_id", "segment_id", "derivative_id", "sha256", "label_id", "group", "source")} for m in members],
                "windows": int(len(windows.y)),
                "windows_per_label": dict(Counter(str(v) for v in windows.y)),
                "rejected_windows": dict(windows.rejected),
                "members_without_windows": windows.members_without_windows,
                "group_kind": group_kinds.pop() if len(group_kinds) == 1 else "mixed",
                "feature_matrix_shape": list(windows.X.shape),
                "finite_check": bool(np.all(np.isfinite(windows.X))),
            },
            "evaluation": evaluation,
            "versions": _versions(),
        }
        write_json(out_dir / "manifest.json", manifest, exclusive=True)
        queue.put({"type": "done", "manifest": manifest, "sha256": digest})
    except Exception as exc:
        queue.put({"type": "error", "message": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-4000:]})


def run_airwriting_job(spec: dict, queue) -> None:
    try:
        import numpy as np

        from .airwriting import evaluate, preprocess, save_model
        from .dataset_builder import load_member_signal

        members = spec["members"]
        sequences, labels, groups, skipped = [], [], [], []
        for i, member in enumerate(members):
            signal = load_member_signal(member)
            mask = np.ones(len(signal.t_us), dtype=bool)
            if member.get("segment"):
                mask = (signal.timeline >= member["segment"]["start_s"]) & (signal.timeline <= member["segment"]["end_s"])
            try:
                sequences.append(preprocess(signal.t_us[mask], signal.values[mask]))
                labels.append(member["label_id"])
                groups.append(member["group"])
            except ValueError as exc:
                skipped.append({"recording_id": member["recording_id"], "reason": str(exc)})
            queue.put({"type": "progress", "stage": "sequences", "progress": 0.05 + 0.4 * (i + 1) / len(members), "message": f"Prepared {i + 1}/{len(members)} sequences"})
        if len(set(labels)) < 2:
            raise ValueError("Air-writing needs at least two characters")
        templates = np.stack(sequences)
        queue.put({"type": "progress", "stage": "evaluating", "progress": 0.5, "message": "Leave-one-session-out DTW evaluation"})
        evaluation = evaluate(templates, labels, groups)
        queue.put({"type": "progress", "stage": "saving", "progress": 0.95, "message": "Saving templates"})
        path, manifest = save_model(Path(spec["output_dir"]), spec["model_id"], spec["name"], templates, labels, groups, evaluation, spec["workspace"], spec["dataset"])
        manifest["training_data"]["skipped"] = skipped
        manifest["versions"] = _versions()
        manifest["source"] = "app"
        (Path(spec["output_dir"]) / "manifest.json").write_text(__import__("json").dumps(manifest, indent=2), encoding="utf-8")
        from ..recordings.storage import sha256_file

        queue.put({"type": "done", "manifest": manifest, "sha256": sha256_file(path)})
    except Exception as exc:
        queue.put({"type": "error", "message": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-4000:]})
