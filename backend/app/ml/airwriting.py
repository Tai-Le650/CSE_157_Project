from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

FEATURE_VERSION = "airwriting-dtw-v1"
SEQUENCE_POINTS = 32
BAND_FRACTION = 0.2


def preprocess(t_us: np.ndarray, values: np.ndarray, points: int = SEQUENCE_POINTS) -> np.ndarray:
    if len(t_us) < 8:
        raise ValueError("Too few samples for an air-writing sequence")
    rel = (t_us - t_us[0]) / 1e6
    grid = np.linspace(0, rel[-1], points)
    seq = np.column_stack([np.interp(grid, rel, values[:, i]) for i in (3, 4, 5)])
    std = seq.std(axis=0)
    std[std < 1e-6] = 1.0
    return ((seq - seq.mean(axis=0)) / std).astype(np.float64)


def dtw_distance(a: np.ndarray, b: np.ndarray, band_fraction: float = BAND_FRACTION) -> float:
    n, m = len(a), len(b)
    band = max(1, int(round(band_fraction * max(n, m))))
    a_list = a.tolist()
    b_list = b.tolist()
    inf = float("inf")
    previous = [inf] * (m + 1)
    previous[0] = 0.0
    for i in range(1, n + 1):
        current = [inf] * (m + 1)
        ai = a_list[i - 1]
        lo = max(1, i - band)
        hi = min(m, i + band)
        for j in range(lo, hi + 1):
            bj = b_list[j - 1]
            cost = ((ai[0] - bj[0]) ** 2 + (ai[1] - bj[1]) ** 2 + (ai[2] - bj[2]) ** 2) ** 0.5
            best = previous[j]
            if current[j - 1] < best:
                best = current[j - 1]
            if previous[j - 1] < best:
                best = previous[j - 1]
            current[j] = cost + best
        previous = current
    return previous[m] / (n + m)


def nearest(templates: np.ndarray, labels: list[str], seq: np.ndarray, k: int = 1) -> dict:
    distances = np.array([dtw_distance(seq, t) for t in templates])
    order = np.argsort(distances)
    votes = Counter(labels[i] for i in order[:k])
    label = votes.most_common(1)[0][0]
    ranking = []
    seen = set()
    for i in order:
        if labels[i] not in seen:
            seen.add(labels[i])
            ranking.append({"label": labels[i], "distance": float(distances[i])})
        if len(ranking) == 3:
            break
    return {"label": label, "distance": float(distances[order[0]]), "ranking": ranking}


def evaluate(templates: np.ndarray, labels: list[str], groups: list[str]) -> dict:
    per_label: dict[str, set] = defaultdict(set)
    for lab, g in zip(labels, groups):
        per_label[lab].add(g)
    lacking = sorted(lab for lab, g in per_label.items() if len(g) < 2)
    if lacking or len(set(groups)) < 2:
        return {"status": "insufficient_grouped_data", "classes_lacking_groups": lacking, "message": "Every character needs examples from at least two sessions for leave-one-session-out evaluation."}
    correct = 0
    predictions = []
    for g in sorted(set(groups)):
        train = [i for i, gg in enumerate(groups) if gg != g]
        test = [i for i, gg in enumerate(groups) if gg == g]
        for i in test:
            result = nearest(templates[train], [labels[j] for j in train], templates[i])
            predictions.append((labels[i], result["label"]))
            correct += int(result["label"] == labels[i])
    classes = sorted(set(labels))
    matrix = [[sum(1 for t, p in predictions if t == a and p == b) for b in classes] for a in classes]
    return {"status": "evaluated", "method": "leave-one-session-out 1-NN DTW", "accuracy": correct / len(predictions), "tested": len(predictions), "confusion_matrix": {"labels": classes, "matrix": matrix}}


def save_model(out_dir: Path, model_id: str, name: str, templates: np.ndarray, labels: list[str], groups: list[str], evaluation: dict, workspace: str, dataset: dict) -> tuple[Path, dict]:
    out_dir.mkdir(parents=True, exist_ok=False)
    path = out_dir / "templates.npz"
    np.savez(path, templates=templates.astype(np.float64), labels=np.array(labels, dtype="U48"), groups=np.array(groups, dtype="U96"))
    manifest = {
        "model_id": model_id,
        "name": name,
        "kind": "airwriting",
        "experimental": True,
        "feature_version": FEATURE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "workspace": workspace,
        "labels": sorted(set(labels)),
        "window": {"window_s": None},
        "preprocessing": f"gyro gx,gy,gz linearly resampled to {SEQUENCE_POINTS} points per trial, z-normalised per channel",
        "classifier": {"type": "1-NN dynamic time warping", "band_fraction": BAND_FRACTION},
        "templates": int(len(labels)),
        "evaluation": evaluation,
        "training_data": {"dataset": dataset, "templates_per_label": dict(Counter(labels))},
        "artifact": {"file": "templates.npz", "format": "numpy npz (no pickle)"},
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path, manifest


def load_templates(path: Path) -> tuple[np.ndarray, list[str]]:
    with np.load(path, allow_pickle=False) as data:
        return data["templates"], [str(x) for x in data["labels"]]
