"""Record one labeled 0.9-second sensor window per trial to CSV."""
import argparse
import csv
import time
from pathlib import Path

import serial

from imu_utils import BAUD, CSV_HEADER, MIN_SAMPLES, WINDOW_SECONDS, capture_window

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DEFAULT_LABELS = ["idle", "swipe_left", "swipe_right", "flick_up"]

parser = argparse.ArgumentParser()
parser.add_argument("--port", required=True, help="Arduino serial port, e.g. COM5")
parser.add_argument("--trials", type=int, default=25, help="New trials per gesture")
parser.add_argument("--labels", nargs="+", default=DEFAULT_LABELS)
args = parser.parse_args()
if args.trials < 1 or any(not all(c.isalnum() or c == '_' for c in label)
                         for label in args.labels):
    parser.error("Use a positive trial count and labels with letters/numbers/underscores")

DATA_DIR.mkdir(exist_ok=True)
print("Mount the sensor in the same orientation for every trial.")
print("At GO, perform the indicated gesture ONCE, then return to rest.")
print("For 'idle', hold still for the entire recording window.")
print("Press Ctrl+C at any time to stop; saved trials remain on disk.")

try:
    with serial.Serial(args.port, BAUD, timeout=0.2) as ser:
        time.sleep(2)
        for label in args.labels:
            print(f"\n=== {label} ({args.trials} new recordings) ===")
            for trial in range(args.trials):
                input(f"Trial {trial+1}/{args.trials}: press Enter when ready...")
                print("Ready...")
                time.sleep(1.0)
                print("GO!", flush=True)
                rows = capture_window(ser, WINDOW_SECONDS)
                if len(rows) < MIN_SAMPLES:
                    print(f"Only {len(rows)} rows; retry this trial.")
                    continue
                suffix = 1
                while (DATA_DIR / f"{label}_{suffix:04d}.csv").exists():
                    suffix += 1
                target = DATA_DIR / f"{label}_{suffix:04d}.csv"
                with target.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(CSV_HEADER)
                    for row in rows:
                        writer.writerow([int(row[0]), *row[1:]])
                print(f"Saved {target.name}: {len(rows)} sensor samples")
except KeyboardInterrupt:
    print("\nStopped. Existing CSV data is safe.")
except serial.SerialException as exc:
    raise SystemExit(f"Serial error on {args.port}: {exc}") from exc

print("\nFinished! Train with: python src/train.py")
