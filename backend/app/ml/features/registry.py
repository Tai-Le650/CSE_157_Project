from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import stats_spectral_v1, summary60_v1
from .stats_spectral_v1 import WindowRejected


@dataclass(frozen=True)
class FeatureSpec:
    version: str
    preprocessing: str
    default_window_s: float
    min_samples: int
    feature_names: tuple[str, ...]
    description: str
    resamples: bool

    def window_features(self, t_us: np.ndarray, values: np.ndarray, start_us: float, window_s: float, src_dir: Path) -> np.ndarray:
        if self.version == summary60_v1.FEATURE_VERSION:
            end_us = start_us + window_s * 1e6
            mask = (t_us >= start_us) & (t_us <= end_us)
            if int(mask.sum()) < self.min_samples:
                raise WindowRejected("insufficient_samples", f"{int(mask.sum())} samples; summary-60-v1 needs {self.min_samples}")
            rows = np.column_stack([t_us[mask], values[mask]])
            return summary60_v1.extract(rows, src_dir)
        if self.version == stats_spectral_v1.FEATURE_VERSION:
            uniform = stats_spectral_v1.resample_window(t_us, values, start_us, window_s)
            return stats_spectral_v1.extract(uniform)
        raise ValueError(f"Unknown feature version {self.version}")


FEATURES: dict[str, FeatureSpec] = {
    summary60_v1.FEATURE_VERSION: FeatureSpec(
        version=summary60_v1.FEATURE_VERSION,
        preprocessing="raw-samples-v1",
        default_window_s=0.9,
        min_samples=30,
        feature_names=summary60_v1.FEATURE_NAMES,
        description="Legacy CLI contract: 10 statistics per IMU axis on raw (non-resampled) samples, computed by src/imu_utils.extract_features. Includes 3 position-dependent time-bin means.",
        resamples=False,
    ),
    stats_spectral_v1.FEATURE_VERSION: FeatureSpec(
        version=stats_spectral_v1.FEATURE_VERSION,
        preprocessing=stats_spectral_v1.PREPROCESSING,
        default_window_s=1.0,
        min_samples=50,
        feature_names=stats_spectral_v1.FEATURE_NAMES,
        description="Mean, std, min, max, RMS, energy, dominant frequency and spectral energy for ax..gz, |a| and |ω| after linear resampling to 100 Hz (gaps over 50 ms reject the window).",
        resamples=True,
    ),
}


def get_feature_spec(version: str) -> FeatureSpec:
    if version not in FEATURES:
        raise KeyError(version)
    return FEATURES[version]
