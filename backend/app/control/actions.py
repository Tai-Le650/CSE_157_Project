from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

NAV_KEYS = ("left", "right", "up", "down", "space", "enter", "tab", "esc", "pageup", "pagedown", "home", "end")
LETTER_KEYS = tuple(chr(c) for c in range(ord("a"), ord("z") + 1))
DIGIT_KEYS = tuple(str(d) for d in range(10))
FUNCTION_KEYS = tuple(f"f{i}" for i in range(1, 13))
MEDIA_KEYS = ("volumeup", "volumedown", "volumemute", "playpause", "nexttrack", "prevtrack")
ALLOWED_KEYS = NAV_KEYS + LETTER_KEYS + DIGIT_KEYS + FUNCTION_KEYS + MEDIA_KEYS
MODIFIERS = ("ctrl", "alt", "shift")
BLOCKED_COMBOS = (
    frozenset({"alt", "f4"}),
    frozenset({"ctrl", "shift", "esc"}),
    frozenset({"ctrl", "alt", "esc"}),
)
WHEEL_DELTA = 120

AllowedKey = Literal[ALLOWED_KEYS]
Modifier = Literal[MODIFIERS]

KEY_LABELS = {
    "left": "Left Arrow", "right": "Right Arrow", "up": "Up Arrow", "down": "Down Arrow",
    "space": "Space", "enter": "Enter", "tab": "Tab", "esc": "Esc",
    "pageup": "Page Up", "pagedown": "Page Down", "home": "Home", "end": "End",
    "volumeup": "Volume Up", "volumedown": "Volume Down", "volumemute": "Mute",
    "playpause": "Play/Pause", "nexttrack": "Next Track", "prevtrack": "Previous Track",
}


def key_label(key: str) -> str:
    if key in KEY_LABELS:
        return KEY_LABELS[key]
    return key.upper()


class KeyAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["key"] = "key"
    key: AllowedKey


class HotkeyAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["hotkey"] = "hotkey"
    modifiers: list[Modifier] = Field(min_length=1, max_length=3)
    key: AllowedKey

    @field_validator("modifiers")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Modifiers must not repeat")
        return [m for m in MODIFIERS if m in value]

    @model_validator(mode="after")
    def _blocked(self) -> "HotkeyAction":
        combo = frozenset([*self.modifiers, self.key])
        if combo in BLOCKED_COMBOS:
            raise ValueError(f"The combination {'+'.join(self.modifiers + [self.key])} is blocked for safety")
        return self


class ClickAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["click"] = "click"
    button: Literal["left", "right", "middle"] = "left"


class DoubleClickAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["double_click"] = "double_click"
    button: Literal["left"] = "left"


class ScrollAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["scroll"] = "scroll"
    notches: int = Field(ge=-20, le=20, description="Positive scrolls up, negative scrolls down. One notch is one mouse-wheel click.")

    @field_validator("notches")
    @classmethod
    def _nonzero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Scroll amount must not be zero")
        return value


class MouseMoveAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["mouse_move"] = "mouse_move"
    dx: int = Field(ge=-400, le=400)
    dy: int = Field(ge=-400, le=400)


GestureAction = Annotated[Union[KeyAction, HotkeyAction, ClickAction, DoubleClickAction, ScrollAction], Field(discriminator="type")]
AnyAction = Annotated[Union[KeyAction, HotkeyAction, ClickAction, DoubleClickAction, ScrollAction, MouseMoveAction], Field(discriminator="type")]

_gesture_adapter = TypeAdapter(GestureAction)
_any_adapter = TypeAdapter(AnyAction)


def parse_gesture_action(data: dict) -> BaseModel:
    return _gesture_adapter.validate_python(data)


def parse_any_action(data: dict) -> BaseModel:
    return _any_adapter.validate_python(data)


def describe_action(action: BaseModel | dict) -> str:
    if isinstance(action, dict):
        action = parse_any_action(action)
    if isinstance(action, KeyAction):
        return f"Press {key_label(action.key)}"
    if isinstance(action, HotkeyAction):
        return "Press " + "+".join([m.capitalize() for m in action.modifiers] + [key_label(action.key)])
    if isinstance(action, ClickAction):
        return f"{action.button.capitalize()} click"
    if isinstance(action, DoubleClickAction):
        return "Double-click"
    if isinstance(action, ScrollAction):
        direction = "up" if action.notches > 0 else "down"
        count = abs(action.notches)
        return f"Scroll {direction} {count} notch{'es' if count != 1 else ''}"
    if isinstance(action, MouseMoveAction):
        return f"Move cursor by ({action.dx}, {action.dy}) px"
    return "Unknown action"


def allowlist_description() -> dict:
    return {
        "keys": list(ALLOWED_KEYS),
        "modifiers": list(MODIFIERS),
        "blocked_combinations": ["+".join(sorted(c)) for c in BLOCKED_COMBOS],
        "types": ["key", "hotkey", "click", "double_click", "scroll"],
        "cursor_only_types": ["mouse_move"],
        "never_allowed": ["text typing", "launching programs", "shell commands", "Windows key combinations"],
    }
