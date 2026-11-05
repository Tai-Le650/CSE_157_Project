from __future__ import annotations

import numpy as np

EPOCH_SEPARATOR_S = 1.0


def timeline_seconds(t_us: np.ndarray, epoch: np.ndarray, separator_s: float = EPOCH_SEPARATOR_S) -> np.ndarray:
    out = np.full(len(t_us), np.nan, dtype=np.float64)
    if len(t_us) == 0:
        return out
    offset = 0.0
    seen: list[int] = []
    for e in epoch:
        if e >= 0 and (not seen or seen[-1] != e) and e not in seen:
            seen.append(int(e))
    for e in seen:
        mask = (epoch == e) & np.isfinite(t_us)
        if not mask.any():
            continue
        t0 = t_us[mask][0]
        rel = (t_us[mask] - t0) / 1e6
        out[mask] = offset + rel
        offset = offset + float(np.nanmax(rel)) + separator_s
    return out
