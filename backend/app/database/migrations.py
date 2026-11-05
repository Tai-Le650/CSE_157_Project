from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, LabelRow, MappingRow, ProfileRow, SettingRow

SCHEMA_VERSION = 1

BUILTIN_LABELS = [
    ("idle", "Idle / No Gesture", True, True),
    ("swipe_left", "Swipe Left", True, False),
    ("swipe_right", "Swipe Right", True, False),
    ("wrist_rotation", "Twist (Wrist Rotation)", True, False),
    ("swipe_up", "Swipe Up", False, False),
    ("swipe_down", "Swipe Down", False, False),
    ("tap", "Tap", False, False),
    ("double_tap", "Double Tap", False, False),
    ("circle", "Circle", False, False),
    ("flick_up", "Flick Up (legacy CLI)", False, False),
]

BROWSER_PROFILE_ID = "browser-navigation"
LEGACY_PROFILE_ID = "legacy-cli"

BUILTIN_PROFILES = [
    (
        BROWSER_PROFILE_ID,
        "Browser navigation (suggested)",
        "Suggested starting point. Every entry starts disabled; review and enable the ones you want.",
        False,
        [
            ("swipe_left", {"type": "hotkey", "modifiers": ["ctrl", "shift"], "key": "tab"}, False),
            ("swipe_right", {"type": "hotkey", "modifiers": ["ctrl"], "key": "tab"}, False),
            ("wrist_rotation", {"type": "scroll", "notches": -3}, False),
        ],
    ),
    (
        LEGACY_PROFILE_ID,
        "Legacy CLI (preserved)",
        "Exact copy of the mapping in src/control.py. Read-only; duplicate it to make changes.",
        True,
        [
            ("swipe_left", {"type": "key", "key": "left"}, True),
            ("swipe_right", {"type": "key", "key": "right"}, True),
            ("flick_up", {"type": "key", "key": "space"}, True),
        ],
    ),
]


def init_db(engine: Engine, session_factory: sessionmaker[Session]) -> None:
    Base.metadata.create_all(engine)
    with session_factory.begin() as db:
        version = db.get(SettingRow, "schema_version")
        if version is None:
            db.add(SettingRow(key="schema_version", value={"version": SCHEMA_VERSION}))
        existing_labels = set(db.scalars(select(LabelRow.label_id)).all())
        for label_id, name, enabled, is_idle in BUILTIN_LABELS:
            if label_id not in existing_labels:
                db.add(LabelRow(label_id=label_id, display_name=name, enabled=enabled, builtin=True, is_idle=is_idle))
        existing_profiles = set(db.scalars(select(ProfileRow.profile_id)).all())
        for profile_id, name, description, read_only, entries in BUILTIN_PROFILES:
            if profile_id in existing_profiles:
                continue
            db.add(ProfileRow(profile_id=profile_id, name=name, description=description, read_only=read_only))
            db.flush()
            for label_id, action, enabled in entries:
                db.add(MappingRow(profile_id=profile_id, label_id=label_id, action=action, enabled=enabled))
