"""Confirm that Python is receiving IMU data on the selected COM port."""
import argparse
import time

import serial

from imu_utils import BAUD, read_sample

parser = argparse.ArgumentParser()
parser.add_argument("--port", required=True, help="Arduino serial port, e.g. COM5")
parser.add_argument("--seconds", type=float, default=5.0)
args = parser.parse_args()

count = 0
start = time.monotonic()
print(f"Opening {args.port}. Close the Arduino Serial Monitor first.")
try:
    with serial.Serial(args.port, BAUD, timeout=0.2) as ser:
        time.sleep(2)  # Allow reset after opening USB serial.
        ser.reset_input_buffer()
        start = time.monotonic()
        while time.monotonic() - start < args.seconds:
            row = read_sample(ser)
            if row is None:
                continue
            count += 1
            if count <= 5:
                print("t_us, ax, ay, az, gx, gy, gz =", row)
except serial.SerialException as exc:
    raise SystemExit(f"Cannot open {args.port}: {exc}") from exc
elapsed = time.monotonic() - start
print(f"Valid rows: {count}; observed rate: {count / elapsed:.1f} rows/s")
if count == 0:
    print("No records. Check USB cable, port, baud (115200), sketch, IMU library.")
