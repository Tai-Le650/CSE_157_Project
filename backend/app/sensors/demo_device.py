from __future__ import annotations

import math
import random
import threading
import time
from collections import deque
from dataclasses import dataclass

DEMO_PREFIX = "DEMO-"
DEMO_GESTURES = ("swipe_left", "swipe_right", "wrist_rotation")
BASE_ACCEL = (0.02, -0.04, 0.99)
GYRO_BIAS = (0.5, -1.2, 0.3)


@dataclass
class ActiveGesture:
    label: str
    start_k: int
    length: int
    amplitude: float


def gesture_delta(label: str, u: float, amplitude: float, duration_s: float) -> tuple[float, float, float, float, float, float]:
    if label == "swipe_left" or label == "swipe_right":
        sign = -1.0 if label == "swipe_left" else 1.0
        bump = math.sin(math.pi * u) ** 2
        gz = sign * 190.0 * amplitude * bump
        ay = sign * 0.55 * amplitude * math.sin(2 * math.pi * u)
        ax = 0.12 * amplitude * bump
        gx = 12.0 * amplitude * math.sin(2 * math.pi * u)
        return ax, ay, 0.0, gx, 0.0, gz
    if label == "sync_tap":
        spike = math.exp(-((u - 0.2) / 0.12) ** 2)
        return 0.0, 0.0, 2.4 * amplitude * spike, 0.0, 0.0, 0.0
    if label == "wrist_rotation":
        theta_max = math.radians(80.0 * amplitude)
        theta = theta_max * math.sin(math.pi * u) ** 2
        omega = theta_max * math.pi * math.sin(2 * math.pi * u) / duration_s
        ay = math.sin(theta) * BASE_ACCEL[2]
        az = (math.cos(theta) - 1.0) * BASE_ACCEL[2]
        return 0.0, ay, az, math.degrees(omega), 6.0 * amplitude * math.sin(math.pi * u), 0.0
    return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0


GESTURE_DURATIONS = {"swipe_left": 0.5, "swipe_right": 0.5, "wrist_rotation": 0.8, "sync_tap": 0.06}
HIDDEN_GESTURES = ("sync_tap",)


class DemoSerial:
    def __init__(
        self,
        rate_hz: float = 100.0,
        seed: int = 7,
        auto: bool = False,
        start_us: int = 2_000_000,
        header: bool = True,
        gestures: tuple[str, ...] = DEMO_GESTURES,
        glitch_every: int | None = None,
        timeout: float = 0.05,
    ):
        self.rate_hz = rate_hz
        self.interval_us = 1e6 / rate_hz
        self.rng = random.Random(seed)
        self.auto = auto
        self.start_us = start_us
        self.gestures = gestures
        self.glitch_every = glitch_every
        self.timeout = timeout
        self.t_start = time.perf_counter()
        self.k = 0
        self.buffer = bytearray(b"t_us,ax,ay,az,gx,gy,gz\n" if header else b"")
        self.lock = threading.Lock()
        self.active: ActiveGesture | None = None
        self.requests: deque[str] = deque()
        self.next_auto_k = int(self.rate_hz * 2.0)
        self.history: deque[dict] = deque(maxlen=100)
        self.closed = False
        self.paused = False

    @property
    def current_gesture(self) -> str | None:
        return self.active.label if self.active else None

    @property
    def in_waiting(self) -> int:
        self._generate()
        return len(self.buffer)

    def read(self, size: int = 1) -> bytes:
        if self.closed:
            raise OSError("Demo device closed")
        self._generate()
        if not self.buffer:
            time.sleep(min(self.timeout, self.interval_us / 1e6))
            self._generate()
        with self.lock:
            chunk = bytes(self.buffer[:size])
            del self.buffer[:size]
        return chunk

    def write(self, data: bytes) -> int:
        return len(data)

    def close(self) -> None:
        self.closed = True

    def perform(self, label: str) -> bool:
        if label not in self.gestures and label not in HIDDEN_GESTURES:
            return False
        with self.lock:
            self.requests.append(label)
        return True

    def set_auto(self, enabled: bool) -> None:
        with self.lock:
            self.auto = enabled
            self.next_auto_k = self.k + int(self.rate_hz * 1.5)

    def _generate(self) -> None:
        with self.lock:
            if self.paused:
                self.t_start = time.perf_counter() - self.k / self.rate_hz
                return
            due = int((time.perf_counter() - self.t_start) * self.rate_hz) + 1
            while self.k < due:
                self._emit(self.k)
                self.k += 1

    def _start_gesture(self, label: str, k: int) -> None:
        amplitude = 1.0 if label in HIDDEN_GESTURES else self.rng.uniform(0.8, 1.2)
        duration = GESTURE_DURATIONS.get(label, 0.5) * (1.0 if label in HIDDEN_GESTURES else self.rng.uniform(0.85, 1.15))
        length = max(3 if label in HIDDEN_GESTURES else 5, int(duration * self.rate_hz))
        self.active = ActiveGesture(label, k, length, amplitude)
        self.history.append({"label": label, "device_t_us": int(self.start_us + k * self.interval_us), "host_time": time.time(), "duration_s": duration})

    def _emit(self, k: int) -> None:
        if self.active is None:
            if self.requests:
                self._start_gesture(self.requests.popleft(), k)
            elif self.auto and k >= self.next_auto_k:
                self._start_gesture(self.rng.choice(self.gestures), k)
                self.next_auto_k = k + int(self.rate_hz * self.rng.uniform(2.5, 4.0))
        delta = (0.0,) * 6
        if self.active is not None:
            u = (k - self.active.start_k) / self.active.length
            if u >= 1.0:
                self.active = None
            else:
                delta = gesture_delta(self.active.label, u, self.active.amplitude, self.active.length / self.rate_hz)
        gauss = self.rng.gauss
        ax = BASE_ACCEL[0] + delta[0] + gauss(0, 0.008)
        ay = BASE_ACCEL[1] + delta[1] + gauss(0, 0.008)
        az = BASE_ACCEL[2] + delta[2] + gauss(0, 0.008)
        gx = GYRO_BIAS[0] + delta[3] + gauss(0, 0.6)
        gy = GYRO_BIAS[1] + delta[4] + gauss(0, 0.6)
        gz = GYRO_BIAS[2] + delta[5] + gauss(0, 0.6)
        t_us = int(self.start_us + k * self.interval_us + self.rng.uniform(-40, 40)) % (1 << 32)
        stamp = str(t_us)
        if self.glitch_every and k > 0 and k % self.glitch_every == 0 and len(stamp) > 3:
            stamp = stamp[3:]
        line = f"{stamp},{ax:.3f},{ay:.3f},{az:.3f},{gx:.3f},{gy:.3f},{gz:.3f}\n"
        self.buffer.extend(line.encode("ascii"))
