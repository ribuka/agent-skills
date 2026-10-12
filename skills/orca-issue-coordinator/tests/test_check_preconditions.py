"""Tests for check_preconditions.py, using a fake command runner.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_preconditions.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_preconditions", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def status_json(reachable: bool = True) -> str:
    return json.dumps({"ok": True, "result": {"runtime": {"reachable": reachable}}})


@pytest.fixture
def cp(monkeypatch: pytest.MonkeyPatch):
    module = load_module()
    responses: dict[str, tuple[int, str]] = {
        "orca": (0, status_json()),
        "gh": (0, "Logged in to github.com"),
    }
    calls: list[list[str]] = []

    def fake_run(cmd: list[str]) -> tuple[int, str]:
        calls.append(cmd)
        return responses[cmd[0]]

    monkeypatch.setattr(module, "run", fake_run)
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_test")
    module.responses = responses
    module.calls = calls
    return module


def test_all_checks_pass(cp, capsys: pytest.CaptureFixture[str]) -> None:
    assert cp.main() == 0
    assert capsys.readouterr().out.strip() == "preconditions: ok"
    assert ["orca", "status", "--json"] in cp.calls
    assert ["gh", "auth", "status"] in cp.calls


def test_outside_orca_terminal_stops(cp, monkeypatch: pytest.MonkeyPatch,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("ORCA_TERMINAL_HANDLE")
    assert cp.main() == 1
    out = capsys.readouterr().out
    assert "STOP: not running inside an Orca terminal" in out
    assert "Do not work around it." in out


def test_blank_terminal_handle_stops(cp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "  ")
    assert cp.main() == 1


@pytest.mark.parametrize("response, expected", [
    ((1, "connection refused"), "`orca status --json` failed (exit 1)"),
    ((127, "orca: command not found"), "`orca status --json` failed (exit 127)"),
    ((0, "not json"), "unexpected output"),
    ((0, status_json(reachable=False)), "Orca runtime is not reachable"),
])
def test_orca_runtime_failure_stops(cp, capsys: pytest.CaptureFixture[str],
                                    response: tuple[int, str], expected: str) -> None:
    cp.responses["orca"] = response
    assert cp.main() == 1
    assert expected in capsys.readouterr().out


def test_gh_auth_failure_stops(cp, capsys: pytest.CaptureFixture[str]) -> None:
    cp.responses["gh"] = (1, "HTTP 401: Bad credentials")
    assert cp.main() == 1
    out = capsys.readouterr().out
    assert "STOP: `gh auth status` failed (exit 1): HTTP 401: Bad credentials" in out


def test_reports_every_failure(cp, monkeypatch: pytest.MonkeyPatch,
                               capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("ORCA_TERMINAL_HANDLE")
    cp.responses["gh"] = (1, "not logged in")
    assert cp.main() == 1
    assert capsys.readouterr().out.count("STOP:") == 2
