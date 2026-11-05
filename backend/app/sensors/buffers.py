from __future__ import annotations

import threading

import numpy as np


class RingBuffer:
    def __init__(self, capacity: int = 30_000):
        self.capacity = capacity
        self.t_us = np.zeros(capacity, dtype=np.float64)
        self.host_ns = np.zeros(capacity, dtype=np.int64)
        self.values = np.zeros((capacity, 6), dtype=np.float64)
        self.count = 0
        self.head = 0
        self.epoch: int | None = None
        self.lock = threading.Lock()
        self.total_appended = 0

    def clear(self) -> None:
        with self.lock:
            self.count = 0
            self.head = 0

    def append(self, samples) -> None:
        with self.lock:
            for s in samples:
                if not s.good or s.t_us is None:
                    continue
                if self.epoch != s.epoch:
                    self.epoch = s.epoch
                    self.count = 0
                    self.head = 0
                i = self.head
                self.t_us[i] = s.t_us
                self.host_ns[i] = s.host_ns
                self.values[i] = s.values
                self.head = (i + 1) % self.capacity
                self.count = min(self.count + 1, self.capacity)
                self.total_appended += 1

    def _ordered(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self.count < self.capacity:
            sl = slice(0, self.count)
            return self.t_us[sl].copy(), self.host_ns[sl].copy(), self.values[sl].copy()
        idx = np.r_[self.head:self.capacity, 0:self.head]
        return self.t_us[idx], self.host_ns[idx], self.values[idx]

    def window(self, seconds: float | None = None, max_points: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        with self.lock:
            t, h, v = self._ordered()
        if len(t) and seconds is not None:
            keep = t >= t[-1] - seconds * 1e6
            t, h, v = t[keep], h[keep], v[keep]
        if max_points is not None and len(t) > max_points:
            t, h, v = t[-max_points:], h[-max_points:], v[-max_points:]
        return t, h, v

    def latest(self) -> tuple[float, int] | None:
        with self.lock:
            if self.count == 0:
                return None
            i = (self.head - 1) % self.capacity
            return float(self.t_us[i]), int(self.host_ns[i])
