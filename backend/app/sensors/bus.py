from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger("gesture_to_pc.bus")

Subscriber = Callable[[str, list], None]


class SampleBus:
    def __init__(self):
        self._subscribers: dict[str, Subscriber] = {}
        self._lock = threading.Lock()
        self.errors = 0

    def subscribe(self, name: str, callback: Subscriber) -> None:
        with self._lock:
            self._subscribers[name] = callback

    def unsubscribe(self, name: str) -> None:
        with self._lock:
            self._subscribers.pop(name, None)

    def publish(self, sensor_id: str, samples: list) -> None:
        with self._lock:
            subscribers = list(self._subscribers.items())
        for name, callback in subscribers:
            try:
                callback(sensor_id, samples)
            except Exception:
                self.errors += 1
                logger.exception("Sample subscriber %s failed", name)
