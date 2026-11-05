from __future__ import annotations

import sys
import threading
from typing import Callable

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HOTKEY_ID = 0x4750

VIRTUAL_KEYS = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "pause": 0x13, "esc": 0x1B, "space": 0x20,
    "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24, "insert": 0x2D, "delete": 0x2E,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
    **{chr(c): c - 32 for c in range(ord("a"), ord("z") + 1)},
    **{str(d): 0x30 + d for d in range(10)},
}
MODIFIER_BITS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT}


def parse_hotkey(spec: str) -> tuple[int, int]:
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if len(parts) < 2:
        raise ValueError("A global hotkey needs at least one modifier and one key, e.g. ctrl+alt+backspace")
    *mods, key = parts
    bits = 0
    for mod in mods:
        if mod not in MODIFIER_BITS:
            raise ValueError(f"Unknown modifier '{mod}'")
        bits |= MODIFIER_BITS[mod]
    if key not in VIRTUAL_KEYS:
        raise ValueError(f"Unsupported hotkey key '{key}'")
    return bits | MOD_NOREPEAT, VIRTUAL_KEYS[key]


def hotkeys_supported() -> bool:
    return sys.platform == "win32"


class GlobalHotkey:
    def __init__(self, spec: str, callback: Callable[[], None]):
        self.spec = spec
        self.callback = callback
        self.modifiers, self.vk = parse_hotkey(spec)
        self.thread: threading.Thread | None = None
        self.thread_id: int | None = None
        self.registered = threading.Event()
        self.failed: str | None = None
        self._ready = threading.Event()

    def start(self) -> bool:
        if not hotkeys_supported():
            self.failed = "Global hotkeys are only supported on Windows"
            return False
        self.thread = threading.Thread(target=self._run, name="estop-hotkey", daemon=True)
        self.thread.start()
        self._ready.wait(timeout=2)
        return self.registered.is_set()

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, HOTKEY_ID, self.modifiers, self.vk):
            self.failed = f"RegisterHotKey failed for {self.spec} (another program may already use it)"
            self._ready.set()
            return
        self.registered.set()
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    try:
                        self.callback()
                    except Exception:
                        pass
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            self.registered.clear()

    def stop(self) -> None:
        if self.thread is None or self.thread_id is None:
            return
        import ctypes

        ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        self.thread.join(timeout=2)
        self.thread = None
