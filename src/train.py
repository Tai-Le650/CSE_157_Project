"""Train a baseline gesture recognizer on separate recorded windows."""
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

from imu_utils import MIN_SAMPLES, WINDOW_SECONDS, extract_features

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "models"
MODEL_FILE = MODEL_DIR / "gestures.joblib"

X, y = [], []
for path in sorted(DATA_DIR.glob("*.csv")):
    # Filename examples: idle_0001.csv, swipe_left_0001.csv
    if "_" not in path.stem:
        continue
    label, number = path.stem.rsplit("_", 1)
    if not number.isdigit():
        continue
    try:
        rows = np.genfromtxt(path, delimiter=",", skip_header=1)
        rows = np.atleast_2d(rows)
        if rows.shape[1] != 7 or len(rows) < MIN_SAMPLES or not np.isfinite(rows).all():
            print(f"Skipping bad/short file: {path.name}")
            continue
        X.append(extract_features(rows))
        y.append(label)
    except (ValueError, OSError) as exc:
        print(f"Skipping {path.name}: {exc}")

counts = Counter(y)
print("Trials per class:", dict(sorted(counts.items())))
if len(counts) < 2 or min(counts.values(), default=0) < 5:
    raise SystemExit("Record at least 5 trials of each of at least 2 classes first.")
if "idle" not in counts:
    raise SystemExit("Record an 'idle' class to reduce unwanted actions.")

X, y = np.asarray(X), np.asarray(y)
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)
model = RandomForestClassifier(
    n_estimators=300, random_state=42, class_weight="balanced_subsample"
)
model.fit(X_train, y_train)
pred = model.predict(X_test)
print("\nHeld-out test results (same collection session; preliminary):")
print(classification_report(y_test, pred, zero_division=0))
print("Class order:", list(model.classes_))
print("Confusion matrix:\n", confusion_matrix(y_test, pred, labels=model.classes_))

MODEL_DIR.mkdir(exist_ok=True)
joblib.dump({
    "model": model,
    "feature_version": "summary-60-v1",
    "window_seconds": WINDOW_SECONDS,
}, MODEL_FILE)
print(f"\nSaved model to: {MODEL_FILE}")
print("For a stronger evaluation, collect a different-day/session test set.")
