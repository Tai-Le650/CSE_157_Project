from __future__ import annotations

import numpy as np
from scipy.signal import stft

from ..api.errors import AppError


def most_energetic_start(x: np.ndarray, n: int) -> int:
    centered = x - np.mean(x)
    energy = np.convolve(centered**2, np.ones(n) / n, mode="valid")
    return int(np.argmax(energy))


def fft_magnitude(segment: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    n = len(segment)
    centered = segment - segment.mean()
    hann = np.hanning(n)
    frequency = np.fft.rfftfreq(n, 1.0 / fs)
    magnitude = 2 * np.abs(np.fft.rfft(centered * hann)) / hann.sum()
    magnitude[0] /= 2
    if n % 2 == 0:
        magnitude[-1] /= 2
    return frequency, magnitude


def stft_db(x: np.ndarray, fs: float, n: int, hop: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    frequency, times, z = stft(x, fs=fs, window="hann", nperseg=n, noverlap=n - hop, detrend="constant", boundary=None, padded=False)
    return frequency, times, 20 * np.log10(np.maximum(np.abs(z), 1e-10))


def analyze_uniform(x: np.ndarray, fs: float, window: int, hop: int, fft_position: str | float = "most_energetic") -> dict:
    if window < 8:
        raise AppError("window_too_small", "Use a window of at least 8 samples", 422)
    if hop <= 0 or hop > window:
        raise AppError("invalid_hop", "Use 0 < hop <= window length", 422)
    if len(x) < window:
        raise AppError("insufficient_samples", f"Need at least {window} uniformly resampled samples; have {len(x)}", 422, {"available": int(len(x)), "window": window})
    if fft_position == "most_energetic":
        start = most_energetic_start(x, window)
    elif fft_position == "latest":
        start = len(x) - window
    else:
        start = int(round(float(fft_position) * fs))
        start = max(0, min(start, len(x) - window))
    frequency, magnitude = fft_magnitude(x[start : start + window], fs)
    peak = int(np.argmax(magnitude[1:]) + 1) if len(magnitude) > 1 else 0
    stft_f, stft_t, stft_values = stft_db(x, fs, window, hop)
    return {
        "fs_hz": fs,
        "window": window,
        "hop": hop,
        "window_s": window / fs,
        "bin_spacing_hz": fs / window,
        "hop_s": hop / fs,
        "fft": {
            "start_index": start,
            "start_s": start / fs,
            "frequency_hz": frequency.tolist(),
            "magnitude": magnitude.tolist(),
            "dominant_hz": float(frequency[peak]) if peak else None,
        },
        "stft": {
            "frequency_hz": stft_f.tolist(),
            "time_s": stft_t.tolist(),
            "db": stft_values.tolist(),
        },
    }


def uniform_from_samples(t_us: np.ndarray, x: np.ndarray, fs: float | None = None) -> tuple[np.ndarray, np.ndarray, float]:
    if len(t_us) < 2:
        raise AppError("insufficient_samples", "Need at least two samples", 422)
    order_ok = np.all(np.diff(t_us) > 0)
    if not order_ok:
        raise AppError("non_monotonic", "Timestamps must increase; apply a repair recipe first", 409)
    t = (t_us - t_us[0]) * 1e-6
    if fs is None:
        fs = 1.0 / float(np.median(np.diff(t)))
    grid = np.arange(0.0, t[-1], 1.0 / fs)
    return grid, np.interp(grid, t, x), fs
