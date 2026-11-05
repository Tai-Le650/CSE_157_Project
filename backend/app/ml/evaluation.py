from __future__ import annotations

from collections import defaultdict
from typing import Callable

import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import StratifiedGroupKFold


class LeakageError(AssertionError):
    pass


def groups_per_label(y: np.ndarray, groups: np.ndarray) -> dict[str, int]:
    found: dict[str, set] = defaultdict(set)
    for label, group in zip(y, groups):
        found[str(label)].add(str(group))
    return {label: len(g) for label, g in sorted(found.items())}


def grouped_evaluation(
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    model_factory: Callable[[], object],
    n_splits_max: int = 5,
    random_state: int = 42,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    labels = sorted({str(v) for v in y})
    per_label = groups_per_label(y, groups)
    lacking = [label for label, count in per_label.items() if count < 2]
    distinct = len({str(g) for g in groups})
    base = {"labels": labels, "groups_per_label": per_label, "groups_total": distinct, "windows": int(len(y))}
    if len(labels) < 2:
        return {**base, "status": "insufficient_classes", "message": "At least two labels are needed for evaluation."}
    if lacking or distinct < 2:
        return {
            **base,
            "status": "insufficient_grouped_data",
            "classes_lacking_groups": lacking,
            "message": "Grouped evaluation needs every label in at least two independent sessions (or recordings). No metrics are reported to avoid misleading results; record another session for: " + ", ".join(lacking or labels),
        }
    n_splits = max(2, min(n_splits_max, min(per_label.values())))
    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=random_state)
    y_true_all: list[str] = []
    y_pred_all: list[str] = []
    folds = []
    for k, (train, test) in enumerate(splitter.split(X, y, groups)):
        train_groups = {str(g) for g in groups[train]}
        test_groups = {str(g) for g in groups[test]}
        if train_groups & test_groups:
            raise LeakageError(f"Fold {k} shares groups between train and test: {sorted(train_groups & test_groups)[:3]}")
        model = model_factory()
        model.fit(X[train], y[train])
        pred = model.predict(X[test])
        y_true_all.extend(str(v) for v in y[test])
        y_pred_all.extend(str(v) for v in pred)
        folds.append({
            "fold": k + 1,
            "train_windows": int(len(train)),
            "test_windows": int(len(test)),
            "test_groups": sorted(test_groups),
            "missing_train_labels": sorted(set(labels) - {str(v) for v in y[train]}),
            "accuracy": float(accuracy_score([str(v) for v in y[test]], [str(v) for v in pred])),
        })
        if progress:
            progress(k + 1, n_splits)
    precision, recall, f1, _ = precision_recall_fscore_support(y_true_all, y_pred_all, labels=labels, average="macro", zero_division=0)
    report = classification_report(y_true_all, y_pred_all, labels=labels, output_dict=True, zero_division=0)
    per_class = {label: {"precision": report[label]["precision"], "recall": report[label]["recall"], "f1": report[label]["f1-score"], "support": int(report[label]["support"])} for label in labels}
    matrix = confusion_matrix(y_true_all, y_pred_all, labels=labels)
    return {
        **base,
        "status": "evaluated",
        "method": "StratifiedGroupKFold",
        "n_splits": n_splits,
        "folds": folds,
        "accuracy": float(accuracy_score(y_true_all, y_pred_all)),
        "macro": {"precision": float(precision), "recall": float(recall), "f1": float(f1)},
        "per_class": per_class,
        "confusion_matrix": {"labels": labels, "matrix": matrix.tolist(), "rows": "true", "columns": "predicted"},
    }
