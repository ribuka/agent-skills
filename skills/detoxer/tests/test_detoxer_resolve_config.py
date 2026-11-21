"""Tests for detoxer's resolve_config.py (config.conf overridden by config.local.conf).

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "resolve_config.py"

spec = importlib.util.spec_from_file_location("detoxer_resolve_config", SCRIPT)
resolve_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolve_config)


@pytest.fixture
def skill_dir(tmp_path: Path) -> Path:
    """A copy of the tracked config.conf with no config.local.conf."""
    shutil.copy(SKILL_DIR / "config.conf", tmp_path / "config.conf")
    return tmp_path


def _write_local(skill_dir: Path, text: str) -> None:
    (skill_dir / "config.local.conf").write_text(text, encoding="utf-8")


def _values(skill_dir: Path) -> dict[str, str]:
    return {key: value for key, (value, _src) in resolve_config.load_config(skill_dir).items()}


def test_tracked_defaults(skill_dir: Path) -> None:
    assert _values(skill_dir) == {
        "MAX_ISSUES_PER_RUN": "3",
        "SCAN_WINDOW_DAYS": "",
        "ISSUE_LABEL": "detoxer",
        "CONFIRM_BEFORE_PUBLISH": "false",
        "IMPLEMENT_FILED_ISSUES": "false",
        "IMPLEMENT_WITH": "new-session",
        "IMPLEMENT_TIMEOUT_SECONDS": "7200",
        "CLAUDE_PERMISSION_MODE": "bypassPermissions",
        "CODEX_SANDBOX": "danger-full-access",
    }


def test_local_overrides_single_keys(skill_dir: Path) -> None:
    _write_local(skill_dir, "# mine\n\n IMPLEMENT_FILED_ISSUES = true \nMAX_ISSUES_PER_RUN=1\n")
    resolved = resolve_config.load_config(skill_dir)
    assert resolved["IMPLEMENT_FILED_ISSUES"] == ("true", str(skill_dir / "config.local.conf"))
    assert resolved["MAX_ISSUES_PER_RUN"] == ("1", str(skill_dir / "config.local.conf"))
    assert resolved["SCAN_WINDOW_DAYS"] == ("", str(skill_dir / "config.conf"))


@pytest.mark.parametrize(("text", "message"), [
    ("UNKNOWN=1\n", "unknown key: UNKNOWN"),
    ("MAX_ISSUES_PER_RUN=2\nMAX_ISSUES_PER_RUN=3\n", "duplicate key"),
    ("ISSUE_LABEL=\n", "empty value"),
    ("IMPLEMENT_FILED_ISSUES\n", "expected KEY=value"),
    ("IMPLEMENT_FILED_ISSUES=yes\n", "is not true or false"),
    ("MAX_ISSUES_PER_RUN=0\n", "is not an integer >= 1"),
    ("SCAN_WINDOW_DAYS=seven\n", "is not an integer >= 1 or empty"),
    ("SCAN_WINDOW_DAYS=0\n", "is not an integer >= 1 or empty"),
    ("SCAN_WINDOW_DAYS=null\n", "is not an integer >= 1 or empty"),
    ("MAX_ISSUES_PER_RUN=\n", "empty value for MAX_ISSUES_PER_RUN"),
    ("IMPLEMENT_TIMEOUT_SECONDS=-5\n", "is not an integer >= 1"),
    ("IMPLEMENT_WITH=same-session\n", "is not one of new-session | orca"),
    ("CLAUDE_PERMISSION_MODE=plan\n", "is not one of acceptEdits"),
    ("CODEX_SANDBOX=read-only\n", "is not one of workspace-write | danger-full-access"),
])
def test_invalid_local_file_is_an_error_naming_file_and_line(
        skill_dir: Path, text: str, message: str) -> None:
    _write_local(skill_dir, text)
    with pytest.raises(resolve_config.ConfigError) as error:
        resolve_config.load_config(skill_dir)
    assert "config.local.conf" in str(error.value)
    assert message in str(error.value)


def test_missing_key_in_tracked_file_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "config.conf").write_text("ISSUE_LABEL=detoxer\n", encoding="utf-8")
    with pytest.raises(resolve_config.ConfigError, match="missing keys: MAX_ISSUES_PER_RUN"):
        resolve_config.load_config(tmp_path)


def _run_main(monkeypatch: pytest.MonkeyPatch, skill_dir: Path, *args: str) -> int:
    monkeypatch.setattr(resolve_config, "SKILL_DIR", skill_dir)
    monkeypatch.setattr(sys, "argv", ["resolve_config.py", *args])
    return resolve_config.main()


def test_main_prints_key_value_lines(skill_dir: Path, monkeypatch: pytest.MonkeyPatch,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    _write_local(skill_dir, "IMPLEMENT_FILED_ISSUES=true\n")
    assert _run_main(monkeypatch, skill_dir) == 0
    assert capsys.readouterr().out.splitlines() == [
        "MAX_ISSUES_PER_RUN=3",
        "SCAN_WINDOW_DAYS=",
        "ISSUE_LABEL=detoxer",
        "CONFIRM_BEFORE_PUBLISH=false",
        "IMPLEMENT_FILED_ISSUES=true",
        "IMPLEMENT_WITH=new-session",
        "IMPLEMENT_TIMEOUT_SECONDS=7200",
        "CLAUDE_PERMISSION_MODE=bypassPermissions",
        "CODEX_SANDBOX=danger-full-access",
    ]


def test_main_json_has_typed_values_and_sources(skill_dir: Path, monkeypatch: pytest.MonkeyPatch,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    _write_local(skill_dir, "SCAN_WINDOW_DAYS=14\n")
    assert _run_main(monkeypatch, skill_dir, "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["SCAN_WINDOW_DAYS"] == {"value": 14, "source": str(skill_dir / "config.local.conf")}
    assert data["IMPLEMENT_FILED_ISSUES"]["value"] is False
    assert data["IMPLEMENT_TIMEOUT_SECONDS"]["value"] == 7200
    assert data["IMPLEMENT_WITH"]["value"] == "new-session"
    assert data["ISSUE_LABEL"]["value"] == "detoxer"


def test_empty_scan_window_is_json_null(skill_dir: Path, monkeypatch: pytest.MonkeyPatch,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    assert _run_main(monkeypatch, skill_dir, "--json") == 0
    assert json.loads(capsys.readouterr().out)["SCAN_WINDOW_DAYS"]["value"] is None


def test_main_exits_1_with_error_line(skill_dir: Path, monkeypatch: pytest.MonkeyPatch,
                                      capsys: pytest.CaptureFixture[str]) -> None:
    _write_local(skill_dir, "MAX_ISSUES_PER_RUN=many\n")
    assert _run_main(monkeypatch, skill_dir) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: ")
