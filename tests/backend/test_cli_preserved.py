from __future__ import annotations

import ast
import subprocess
import sys

import pytest

from conftest import ROOT


@pytest.mark.parametrize("script, expected", [
    ("collect.py", "--trials"),
    ("control.py", "--actions"),
    ("check_stream.py", "--seconds"),
])
def test_legacy_cli_help_still_works(script, expected):
    result = subprocess.run([sys.executable, "-B", str(ROOT / "src" / script), "--help"], capture_output=True, text=True, timeout=60, cwd=str(ROOT))
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout


def test_backend_never_imports_legacy_cli_scripts():
    legacy = {"collect", "train", "control", "check_stream"}
    for path in (ROOT / "backend").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = {node.module.split(".")[0]}
            else:
                continue
            assert not names & legacy, f"{path} imports a legacy CLI script: {names & legacy}"
