from __future__ import annotations

import math
import random
import threading
import time
from collections import deque
from typing import Any

from ..api.errors import conflict

UNAVAILABLE_REASON = (
    "The connected firmware streams IMU data only. Sound activation needs firmware that also streams "
    "microphone levels on the same link (for example lines such as M,<t_us>,<level>). No such firmware exists "
    "in this project yet; the Lab 4 microphone sketch streams raw ADC buffers (S,<value>) without IMU data, so it "
    "cannot run alongside gesture sensing."
)


class ActivationStateMachine:
    def __init__(self, threshold: float, active_window_s: float, refractory_s: float):
        self.threshold = threshold
        self.active_window_s = active_window_s
        self.refractory_s = refractory_s
        self.state = "idle"
        self.active_until = 0.0
        self.last_event = -1e9
        self.events: deque[dict] = deque(maxlen=50)

    def update(self, level: float, now: float) -> str | None:
        transition = None
        if self.state == "active" and now >= self.active_until:
            self.state = "idle"
            transition = "timeout"
        if level >= self.threshold and now - self.last_event >= self.refractory_s:
            self.last_event = now
            self.active_until = now + self.active_window_s
            self.events.append({"at": time.time(), "level": level})
            if self.state != "active":
                transition = "activated"
            self.state = "active"
        return transition

    def remaining(self, now: float) -> float:
        return max(0.0, self.active_until - now) if self.state == "active" else 0.0


class DemoMicrophone(threading.Thread):
    def __init__(self, on_level, rate_hz: float = 100.0, seed: int = 11):
        super().__init__(name="demo-mic", daemon=True)
        self.on_level = on_level
        self.rate_hz = rate_hz
        self.rng = random.Random(seed)
        self.stop_event = threading.Event()
        self.clap_at: float | None = None
        self.next_auto = time.monotonic() + 6.0
        self.auto = True

    def clap(self) -> None:
        self.clap_at = time.monotonic()

    def run(self) -> None:
        period = 1.0 / self.rate_hz
        while not self.stop_event.wait(period):
            now = time.monotonic()
            if self.auto and now >= self.next_auto:
                self.clap()
                self.next_auto = now + self.rng.uniform(7.0, 11.0)
            level = max(0.0, self.rng.gauss(0.06, 0.02))
            if self.clap_at is not None:
                age = now - self.clap_at
                if age < 0.25:
                    level = max(level, 0.92 * math.exp(-age / 0.06))
                else:
                    self.clap_at = None
            self.on_level(min(1.0, level), now)


class SoundActivationService:
    snapshot_key = "sound"

    def __init__(self, settings: Any, hub: Any, activity: Any, workspace_provider):
        self.settings = settings
        self.hub = hub
        self.activity = activity
        self.workspace = workspace_provider
        self.machine = self._new_machine()
        self.source: DemoMicrophone | None = None
        self.level = 0.0
        self.levels: deque[tuple[float, float]] = deque(maxlen=300)
        self._last_publish = 0.0
        self._lock = threading.Lock()

    def _new_machine(self) -> ActivationStateMachine:
        cfg = self.settings.current.sound
        return ActivationStateMachine(cfg.threshold, cfg.active_window_s, cfg.refractory_s)

    def available(self) -> tuple[bool, str]:
        if self.workspace() == "demo":
            return (self.source is not None, "Simulated microphone (Demo Mode)" if self.source else "Start the simulated microphone to try sound activation in Demo Mode")
        return False, UNAVAILABLE_REASON

    def is_active(self) -> bool:
        available, _ = self.available()
        return available and self.machine.state == "active"

    def snapshot(self) -> dict:
        available, reason = self.available()
        now = time.monotonic()
        with self._lock:
            levels = list(self.levels)[-200:]
        return {
            "available": available,
            "reason": reason,
            "simulated": self.workspace() == "demo",
            "source_running": self.source is not None,
            "state": self.machine.state if available else "unavailable",
            "level": self.level if available else None,
            "active_remaining_s": self.machine.remaining(now) if available else 0.0,
            "events": list(self.machine.events)[-10:],
            "levels": [{"t": t, "level": lvl} for t, lvl in levels],
            "settings": self.settings.current.sound.model_dump(),
            "required_for_actions": self.settings.current.control.sound_activation_required,
        }

    def _on_level(self, level: float, now: float) -> None:
        self.level = level
        with self._lock:
            self.levels.append((time.time(), level))
        transition = self.machine.update(level, now)
        if transition == "activated":
            self.activity.info("sound", f"Sound activation: ACTIVE for {self.machine.active_window_s:.0f} s (simulated)")
        elif transition == "timeout":
            self.activity.info("sound", "Sound activation timed out; gestures will not act until the next sound event")
        if transition or now - self._last_publish > 0.1:
            self._last_publish = now
            self.hub.publish("sound", "sound", self.snapshot())

    def start_demo_source(self) -> dict:
        if self.workspace() != "demo":
            raise conflict("demo_only", UNAVAILABLE_REASON)
        if self.source is None:
            self.machine = self._new_machine()
            self.source = DemoMicrophone(self._on_level)
            self.source.start()
            self.activity.info("sound", "Simulated microphone started (Demo Mode)")
        return self.snapshot()

    def stop_source(self) -> dict:
        if self.source is not None:
            self.source.stop_event.set()
            self.source.join(timeout=1)
            self.source = None
        return self.snapshot()

    def demo_clap(self) -> dict:
        if self.source is None:
            raise conflict("source_not_running", "Start the simulated microphone first")
        self.source.clap()
        return self.snapshot()

    def reconfigure(self) -> None:
        self.machine = self._new_machine()

    def on_shutdown(self) -> None:
        self.stop_source()
