from __future__ import annotations

import numpy as np

FEATURE_VERSION = "stats-spectral-v1"
PREPROCESSING = "resample-linear-100hz-v1"
TARGET_HZ = 100.0
MAX_GAP_MS = 50.0
EDGE_TOLERANCE_MS = 30.0
CHANNELS = ("ax", "ay", "az", "gx", "gy", "gz", "amag", "gmag")
STATS = ("mean", "std", "min", "max", "rms", "energy", "dominant_hz", "spectral_energy")
FEATURE_NAMES = tuple(f"{channel}_{stat}" for channel in CHANNELS for stat in STATS)


class WindowRejected(ValueError):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason


def resample_window(t_us: np.ndarray, values: np.ndarray, start_us: float, window_s: float, fs: float = TARGET_HZ) -> np.ndarray:
    n = int(round(window_s * fs))
    end_us = start_us + window_s * 1e6
    mask = (t_us >= start_us - EDGE_TOLERANCE_MS * 1e3) & (t_us <= end_us + EDGE_TOLERANCE_MS * 1e3)
    t, v = t_us[mask], values[mask]
    if len(t) < max(8, int(0.5 * n * 0.5)):
        raise WindowRejected("insufficient_samples", f"{len(t)} samples in window")
    if t[0] > start_us + EDGE_TOLERANCE_MS * 1e3 or t[-1] < end_us - EDGE_TOLERANCE_MS * 1e3 - 1e6 / fs:
        raise WindowRejected("insufficient_coverage", "window not covered by samples")
    gaps = np.diff(t)
    if len(gaps) and np.max(gaps) > MAX_GAP_MS * 1e3:
        raise WindowRejected("gap_too_large", f"gap of {np.max(gaps) / 1e3:.0f} ms inside window")
    if len(gaps) and np.any(gaps <= 0):
        raise WindowRejected("non_monotonic", "timestamps not increasing")
    grid = start_us + np.arange(n) * (1e6 / fs)
    return np.column_stack([np.interp(grid, t, v[:, i]) for i in range(6)])


def _channels(uniform: np.ndarray) -> np.ndarray:
    accel = np.sqrt(np.sum(uniform[:, 0:3] ** 2, axis=1))
    gyro = np.sqrt(np.sum(uniform[:, 3:6] ** 2, axis=1))
    return np.column_stack([uniform, accel, gyro])


def extract(uniform: np.ndarray, fs: float = TARGET_HZ) -> np.ndarray:
    data = _channels(np.asarray(uniform, dtype=np.float64))
    n = data.shape[0]
    hann = np.hanning(n)
    freqs = np.fft.rfftfreq(n, 1.0 / fs)
    features = []
    for i in range(data.shape[1]):
        s = data[:, i]
        mean = float(np.mean(s))
        centered = s - mean
        power = np.abs(np.fft.rfft(centered * hann)) ** 2
        if len(power) > 1 and power[1:].max() > 1e-18:
            dominant = float(freqs[1 + int(np.argmax(power[1:]))])
        else:
            dominant = 0.0
        features.extend([
            mean,
            float(np.std(s)),
            float(np.min(s)),
            float(np.max(s)),
            float(np.sqrt(np.mean(s * s))),
            float(np.sum(s * s) / fs),
            dominant,
            float(np.sum(power[1:]) / n),
        ])
    return np.asarray(features, dtype=np.float64)
