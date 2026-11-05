from __future__ import annotations

import importlib.util
import threading
from pathlib import Path
from types import ModuleType

import numpy as np

FEATURE_VERSION = "summary-60-v1"
AXIS_NAMES = ("ax", "ay", "az", "gx", "gy", "gz")
STAT_NAMES = ("mean", "std", "min", "max", "p10", "p90", "mean_abs_diff", "bin1_mean", "bin2_mean", "bin3_mean")
FEATURE_NAMES = tuple(f"{axis}_{stat}" for axis in AXIS_NAMES for stat in STAT_NAMES)

_lock = threading.Lock()
_modules: dict[str, ModuleType] = {}


def load_legacy_module(src_dir: Path) -> ModuleType:
    path = (Path(src_dir) / "imu_utils.py").resolve()
    key = str(path)
    with _lock:
        if key in _modules:
            return _modules[key]
        if not path.is_file():
            raise FileNotFoundError(f"Legacy feature module not found: {path}")
        spec = importlib.util.spec_from_file_location("gesture_to_pc_legacy_imu_utils", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        _modules[key] = module
        return module


def legacy_constants(src_dir: Path) -> dict:
    module = load_legacy_module(src_dir)
    return {"window_seconds": float(module.WINDOW_SECONDS), "min_samples": int(module.MIN_SAMPLES), "baud": int(module.BAUD)}


def extract(samples_7col: np.ndarray, src_dir: Path) -> np.ndarray:
    module = load_legacy_module(src_dir)
    return np.asarray(module.extract_features(np.asarray(samples_7col, dtype=np.float64)), dtype=np.float64)
