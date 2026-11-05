"""Recognize gestures from USB IMU data and optionally send keyboard keys."""
import argparse
import time
from pathlib import Path

import joblib
import serial

from imu_utils import BAUD, MIN_SAMPLES, capture_window, extract_features

ROOT = Path(__file__).resolve().parents[1]
MODEL_FILE = ROOT / "models" / "gestures.joblib"
ACTIONS = {
    "swipe_left": "left",
    "swipe_right": "right",
    "flick_up": "space",
}

parser = argparse.ArgumentParser()
parser.add_argument("--port", required=True, help="Arduino COM port, e.g. COM5")
parser.add_argument("--actions", action="store_true", help="Actually press keys in the focused app")
parser.add_argument("--threshold", type=float, default=0.85)
parser.add_argument("--cooldown", type=float, default=1.2)
args = parser.parse_args()
if not 0 < args.threshold <= 1 or args.cooldown < 0:
    parser.error("Threshold must be in (0,1] and cooldown must be nonnegative")
if not MODEL_FILE.exists():
    raise SystemExit("Train the classifier first with: python src/train.py")

# IMPORTANT: Only open a joblib file you produced yourself (pickle-based).
model_info = joblib.load(MODEL_FILE)
if model_info.get("feature_version") != "summary-60-v1":
    raise SystemExit("Model feature mismatch. Retrain with python src/train.py")
model = model_info["model"]
window_seconds = model_info["window_seconds"]

if args.actions:
    import pyautogui

print("LIVE gestures:", ACTIONS)
print("Press Ctrl+C to stop.")
print("KEYS ENABLED" if args.actions else "PREVIEW MODE (will not press keys)")
print("Return to idle between gestures to rearm detection.")

armed = True
last_action_at = 0.0
try:
    with serial.Serial(args.port, BAUD, timeout=0.2) as ser:
        time.sleep(2)
        while True:
            rows = capture_window(ser, window_seconds)
            if len(rows) < MIN_SAMPLES:
                print("Not enough serial samples. Check device/port.")
                continue
            sample_features = extract_features(rows).reshape(1, -1)
            probabilities = model.predict_proba(sample_features)[0]
            best = int(probabilities.argmax())
            gesture = str(model.classes_[best])
            confidence = float(probabilities[best])
            print(f"{gesture:12} confidence={confidence:.2f} (n={len(rows)})")

            if gesture == "idle" and confidence >= args.threshold:
                armed = True
                continue

            now = time.monotonic()
            if (gesture in ACTIONS and confidence >= args.threshold
                and armed and now - last_action_at >= args.cooldown):
                key = ACTIONS[gesture]
                if args.actions:
                    pyautogui.press(key)
                    print(f"  -> PRESSED: {key}")
                else:
                    print(f"  -> WOULD PRESS: {key}")
                armed = False
                last_action_at = now
except KeyboardInterrupt:
    print("\nStopped.")
except serial.SerialException as exc:
    raise SystemExit(f"Serial error on {args.port}: {exc}") from exc
