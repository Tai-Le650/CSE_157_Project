from __future__ import annotations

import sys
import threading
import time
from collections import deque

from pydantic import BaseModel

from .actions import WHEEL_DELTA, ClickAction, DoubleClickAction, HotkeyAction, KeyAction, MouseMoveAction, ScrollAction


class FailSafeTriggered(Exception):
    pass


class PyAutoGuiBackend:
    name = "pyautogui"
    simulated = False

    def __init__(self):
        import pyautogui

        self._pg = pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.02

    def execute(self, action: BaseModel) -> None:
        pg = self._pg
        try:
            if isinstance(action, KeyAction):
                pg.press(action.key)
            elif isinstance(action, HotkeyAction):
                pg.hotkey(*action.modifiers, action.key)
            elif isinstance(action, ClickAction):
                pg.click(button=action.button)
            elif isinstance(action, DoubleClickAction):
                pg.doubleClick(button=action.button)
            elif isinstance(action, ScrollAction):
                amount = action.notches * WHEEL_DELTA if sys.platform == "win32" else action.notches
                pg.scroll(amount)
            elif isinstance(action, MouseMoveAction):
                pg.moveRel(action.dx, action.dy, duration=0)
            else:
                raise ValueError(f"Unsupported action type {type(action).__name__}")
        except pg.FailSafeException as exc:
            raise FailSafeTriggered(str(exc)) from exc


class SimulatedBackend:
    name = "simulated"
    simulated = True

    def __init__(self):
        self.calls: deque[tuple[float, dict]] = deque(maxlen=500)
        self.lock = threading.Lock()

    def execute(self, action: BaseModel) -> None:
        with self.lock:
            self.calls.append((time.time(), action.model_dump()))


class RecordingFakeBackend(SimulatedBackend):
    name = "fake-os"
    simulated = False
