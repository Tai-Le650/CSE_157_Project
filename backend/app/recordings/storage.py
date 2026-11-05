from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

RAW_HEADER = ("t_us", "ax", "ay", "az", "gx", "gy", "gz", "host_rx_ns")
LEGACY_HEADER = ("t_us", "ax", "ay", "az", "gx", "gy", "gz")
DERIVATIVE_HEADER = ("t_us", "ax", "ay", "az", "gx", "gy", "gz", "epoch", "segment")
UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


def safe_token(text: str | None, fallback: str = "x", max_len: int = 40) -> str:
    cleaned = UNSAFE.sub("-", text or "").strip("-_")[:max_len]
    return cleaned or fallback


def utc_stamp(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z"


def new_id(prefix: str, *parts: str | None, now: datetime | None = None) -> str:
    tokens = [safe_token(p) for p in parts if p]
    return "_".join([prefix, utc_stamp(now), *tokens, secrets.token_hex(2)])


def dated_dir(root: Path, when: datetime | None = None) -> Path:
    when = when or datetime.now(timezone.utc)
    return root / f"{when:%Y}" / f"{when:%m}" / f"{when:%d}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def format_value(value: float) -> str:
    return repr(float(value))


def write_samples_csv(path: Path, samples: Iterable) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(",".join(RAW_HEADER) + "\n")
        for s in samples:
            values = ",".join(format_value(v) for v in s.values)
            handle.write(f"{int(s.t_raw)},{values},{int(s.host_ns)}\n")
            count += 1
    return count


def write_json(path: Path, payload: dict, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, default=str)
    if exclusive:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
        return
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def move_no_overwrite(src: Path, dest_dir: Path, name: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / name
    if target.exists():
        raise FileExistsError(f"{target} already exists; raw recordings are never overwritten")
    os.rename(src, target)
    return target


def copy_no_overwrite(src: Path, dest_dir: Path, name: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / name
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    tmp = dest_dir / (name + ".part")
    shutil.copyfile(src, tmp)
    os.rename(tmp, target)
    return target


def write_bytes_no_overwrite(data: bytes, dest_dir: Path, name: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / name
    with target.open("xb") as handle:
        handle.write(data)
    return target


def write_derivative_csv(path: Path, t_us, values, epoch, segment) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(",".join(DERIVATIVE_HEADER) + "\n")
        for i in range(len(t_us)):
            vals = ",".join(f"{float(v):.6g}" for v in values[i])
            handle.write(f"{float(t_us[i]):.3f},{vals},{int(epoch[i])},{int(segment[i])}\n")


def write_legacy_csv(rows: Iterable[tuple]) -> str:
    lines = [",".join(LEGACY_HEADER)]
    for t, *values in rows:
        lines.append(f"{int(t)}," + ",".join(f"{float(v):.6g}" for v in values))
    return "\n".join(lines) + "\n"
