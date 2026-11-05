from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[3]
LOCAL_SETTINGS_FILE = "settings.local.json"
DATA_DIR_ENV = "GESTURE_TO_PC_DATA_DIR"
MODELS_DIR_ENV = "GESTURE_TO_PC_MODELS_DIR"

WORKSPACES = ("real", "demo")


class PathOutsideBase(ValueError):
    pass


def read_local_settings(root: Path) -> dict:
    path = root / LOCAL_SETTINGS_FILE
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_local_settings(root: Path, payload: dict) -> Path:
    path = root / LOCAL_SETTINGS_FILE
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def resolve_data_dir_override(root: Path) -> Path | None:
    env = os.environ.get(DATA_DIR_ENV)
    if env:
        return Path(env).expanduser().resolve()
    value = read_local_settings(root).get("data_dir")
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser().resolve()
    return None


@dataclass(frozen=True)
class AppPaths:
    root: Path
    data_dir: Path
    models_dir: Path
    cli_data_dir: Path
    reference_root: Path
    config_root: Path

    @classmethod
    def default(cls) -> "AppPaths":
        root = APP_ROOT
        override = resolve_data_dir_override(root)
        models_env = os.environ.get(MODELS_DIR_ENV)
        return cls(
            root=root,
            data_dir=override or root / "data",
            models_dir=Path(models_env).expanduser().resolve() if models_env else root / "models",
            cli_data_dir=root / "data",
            reference_root=root.parent,
            config_root=root,
        )

    @classmethod
    def isolated(cls, base: Path, root: Path | None = None, reference_root: Path | None = None) -> "AppPaths":
        app_root = root or APP_ROOT
        return cls(
            root=app_root,
            data_dir=base / "data",
            models_dir=base / "models",
            cli_data_dir=base / "cli_data",
            reference_root=reference_root or base / "reference",
            config_root=base,
        )

    @classmethod
    def for_tests(cls, base: Path, root: Path | None = None, reference_root: Path | None = None) -> "AppPaths":
        return cls.isolated(base, root, reference_root)

    @property
    def src_dir(self) -> Path:
        return self.root / "src"

    @property
    def frontend_dist(self) -> Path:
        return self.root / "frontend" / "dist"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def default_data_dir(self) -> Path:
        return self.config_root / "data"

    @property
    def data_dir_is_default(self) -> bool:
        return self.data_dir == self.default_data_dir

    def raw_root(self, workspace: str) -> Path:
        return self.data_dir / "raw" / "demo" if workspace == "demo" else self.data_dir / "raw"

    def staging_dir(self, workspace: str) -> Path:
        return self.raw_root(workspace) / "_staging"

    def imports_dir(self, workspace: str) -> Path:
        return self.raw_root(workspace) / "imports"

    def processed_dir(self, workspace: str) -> Path:
        return self.data_dir / "processed" / "demo" if workspace == "demo" else self.data_dir / "processed"

    def exports_dir(self, workspace: str) -> Path:
        return self.data_dir / "exports" / "demo" if workspace == "demo" else self.data_dir / "exports"

    def models_root(self, workspace: str) -> Path:
        return self.models_dir / "demo" if workspace == "demo" else self.models_dir

    def base_dir(self, base: str) -> Path:
        mapping = {
            "data": self.data_dir,
            "cli_data": self.cli_data_dir,
            "models": self.models_dir,
            "reference": self.reference_root,
        }
        if base not in mapping:
            raise PathOutsideBase(f"Unknown storage base '{base}'")
        return mapping[base]

    def resolve(self, base: str, relative: str) -> Path:
        base_dir = self.base_dir(base).resolve()
        target = (base_dir / relative).resolve()
        if target != base_dir and base_dir not in target.parents:
            raise PathOutsideBase(f"Path '{relative}' escapes storage base '{base}'")
        return target

    def relative_to_base(self, base: str, path: Path) -> str:
        base_dir = self.base_dir(base).resolve()
        resolved = path.resolve()
        if resolved != base_dir and base_dir not in resolved.parents:
            raise PathOutsideBase(f"Path '{path}' is not inside storage base '{base}'")
        return resolved.relative_to(base_dir).as_posix()

    def ensure(self) -> None:
        for workspace in WORKSPACES:
            for directory in (
                self.raw_root(workspace),
                self.staging_dir(workspace),
                self.imports_dir(workspace),
                self.processed_dir(workspace),
                self.exports_dir(workspace),
                self.models_root(workspace),
            ):
                directory.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
