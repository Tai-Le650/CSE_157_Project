"""Shared routines for the XIAO MG24 Sense prototype."""
from __future__ import annotations

import math
import time

import numpy as np

BAUD = 115200
WINDOW_SECONDS = 0.9
MIN_SAMPLES = 30
CSV_HEADER = ("t_us", "ax", "ay", "az", "gx", "gy", "gz")


def read_sample(ser) -> list[float] | None:
    """Parse a single CSV record, skipping header/diagnostic/broken lines."""
    line = ser.readline().decode("utf-8", errors="replace").strip()
    parts = line.split(",")
    if len(parts) != 7:
        return None
    try:
        timestamp = int(parts[0])
        values = [float(item) for item in parts[1:]]
    except ValueError:
        return None
    if not all(math.isfinite(value) for value in values):
        return None
    return [float(timestamp), *values]


def capture_window(ser, seconds: float = WINDOW_SECONDS) -> np.ndarray:
    """Read current sensor data for a fixed amount of wall-clock time."""
    ser.reset_input_buffer()  # Discard stale measurements between trials.
    samples = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        sample = read_sample(ser)
        if sample is not None:
            samples.append(sample)
    if not samples:
        return np.empty((0, 7), dtype=np.float64)
    return np.asarray(samples, dtype=np.float64)


def extract_features(samples: np.ndarray) -> np.ndarray:
    """60 statistical/time-bin features shared by train and inference."""
    if samples.ndim != 2 or samples.shape[1] != 7:
        raise ValueError("Expected N rows x 7 columns: timestamp and six IMU axes")
    if len(samples) < MIN_SAMPLES:
        raise ValueError(f"Too few sensor samples: {len(samples)}")
    axes = samples[:, 1:]  # Ignore timestamp; use physical measurements.
    features = []
    for i in range(6):
        col = axes[:, i]
        bins = np.array_split(col, 3)
        features.extend([
            float(np.mean(col)),
            float(np.std(col)),
            float(np.min(col)),
            float(np.max(col)),
            float(np.percentile(col, 10)),
            float(np.percentile(col, 90)),
            float(np.mean(np.abs(np.diff(col)))),
            *(float(np.mean(b)) for b in bins),
        ])
    return np.asarray(features, dtype=np.float64)
