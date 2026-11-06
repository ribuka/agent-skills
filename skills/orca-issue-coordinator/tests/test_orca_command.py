"""Tests for stdout command execution and direct worker-script entry points."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def command() -> ModuleType:
    spec = importlib.util.spec_from_file_location("orca_command", SCRIPTS / "orca_command.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_executable(command: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(command.shutil, "which", lambda name: None)
    assert command.run_stdout(["missing-orca", "argument"], 60) == (127, "")


def test_timeout_discards_partial_output(command: ModuleType, tmp_path: Path) -> None:
    child = tmp_path / "slow.py"
    child.write_text("import time\nprint('partial', flush=True)\ntime.sleep(30)\n",
                     encoding="utf-8")
    assert command.run_stdout([sys.executable, str(child)], 0.2) == (124, "")


def test_stdout_decoding_stderr_and_exit_code(command: ModuleType, tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    child = tmp_path / "output.py"
    child.write_text("import sys\nsys.stdout.buffer.write(b'out\\xe3\\x81\\x82\\xff')\n"
                     "sys.stderr.buffer.write(b'err\\xff')\nsys.exit(7)\n", encoding="utf-8")
    monkeypatch.setattr(command.shutil, "which", lambda name: sys.executable)
    assert command.run_stdout(["fixture-python", str(child)], 60) == (7, "outあ\ufffd")


@pytest.mark.parametrize("script,args,code,output", [
    ("start_worker.py", ["--", "--spec", "fixture"], 2, "start: invalid"),
    ("list_workers.py", ["--run", "fixture"], 1, '"error": "worker-list exited 127'),
])
def test_direct_script_path(script: str, args: list[str], code: int, output: str,
                            tmp_path: Path) -> None:
    proc = subprocess.run([sys.executable, str(SCRIPTS / script), "--orca",
                           str(tmp_path / "missing-orca"), *args],
                          cwd=tmp_path, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=10)
    assert proc.returncode == code
    assert output in proc.stdout
    assert proc.stderr == ""
