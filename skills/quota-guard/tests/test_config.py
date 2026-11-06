"""Tests that the pause threshold comes from config.conf and --threshold overrides it.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys

import pytest


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "quota_guard.py"
spec = importlib.util.spec_from_file_location("quota_guard_config", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

NOW = 1800001002


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "config.conf"
    monkeypatch.setattr(guard, "CONFIG_FILE", path)
    return path


def run_check(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
              state: Path, *extra: str) -> tuple[int, dict]:
    guard.record(state, {"session_id": "a", "rate_limits": {
        "five_hour": {"used_percentage": 90, "resets_at": NOW + 4000}}}, NOW - 1)
    monkeypatch.setattr(guard.time, "time", lambda: NOW)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "check", "--state-dir", str(state), *extra])
    code = guard.main()
    return code, json.loads(capsys.readouterr().out)


def test_shipped_config_sets_threshold() -> None:
    assert guard.CONFIG_FILE == SKILL_DIR / "config.conf"
    assert 0 < guard.load_threshold() <= 100


def test_script_holds_no_default_threshold() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"\b95\b", source)


@pytest.mark.parametrize("threshold,code,state", [(90, 10, "PAUSED_QUOTA"), (91, 0, "READY")])
def test_config_threshold_decides_state(tmp_path, config, monkeypatch, capsys,
                                        threshold, code, state) -> None:
    config.write_text(f"# comment\n\nTHRESHOLD={threshold}\n", encoding="utf-8")
    result_code, result = run_check(monkeypatch, capsys, tmp_path / "state")
    assert (result_code, result["state"], result["threshold"]) == (code, state, threshold)


def test_option_overrides_config(tmp_path, config, monkeypatch, capsys) -> None:
    config.write_text("THRESHOLD=91\n", encoding="utf-8")
    code, result = run_check(monkeypatch, capsys, tmp_path / "state", "--threshold", "80")
    assert (code, result["state"], result["threshold"]) == (10, "PAUSED_QUOTA", 80)


def test_option_works_without_config(tmp_path, config, monkeypatch, capsys) -> None:
    code, result = run_check(monkeypatch, capsys, tmp_path / "state", "--threshold", "95")
    assert (code, result["state"]) == (0, "READY")


def test_crlf_config_is_accepted(tmp_path, config, monkeypatch, capsys) -> None:
    config.write_bytes(b"THRESHOLD=90\r\n")
    code, result = run_check(monkeypatch, capsys, tmp_path / "state")
    assert (code, result["threshold"]) == (10, 90)


@pytest.mark.parametrize("content", [None, "", "# THRESHOLD=95\n", "OTHER=1\n",
                                     "THRESHOLD=\n", "THRESHOLD=abc\n", "THRESHOLD=0\n",
                                     "THRESHOLD=-5\n", "THRESHOLD=100.1\n", "THRESHOLD=nan\n",
                                     "THRESHOLD=inf\n"])
def test_missing_or_invalid_config_is_unknown(tmp_path, config, monkeypatch, capsys,
                                              content) -> None:
    if content is not None:
        config.write_text(content, encoding="utf-8")
    code, result = run_check(monkeypatch, capsys, tmp_path / "state")
    assert code == 20
    if content is None:
        reason = f"config.conf unreadable: {config}"
    elif "THRESHOLD=" not in content or content.startswith("#"):
        reason = f"THRESHOLD missing from config.conf: {config}"
    else:
        reason = f"THRESHOLD in config.conf must be a number in (0,100]: {config}"
    assert result == {
        "state": "UNKNOWN", "reason": reason,
        "checkpoint_dir": str(tmp_path / "state" / "checkpoints"),
        "local_retry_seconds": guard.LOCAL_RETRY_SECONDS,
        **guard.wakeup(NOW + 900)}


def test_missing_config_fails_codex_without_reading_limits(tmp_path, config, monkeypatch,
                                                           capsys) -> None:
    monkeypatch.setattr(guard, "read_codex_limits",
                        lambda: pytest.fail("must not read limits without a threshold"))
    monkeypatch.setattr(guard.time, "time", lambda: NOW)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "check", "--provider", "codex",
                                      "--state-dir", str(tmp_path)])
    assert guard.main() == 20
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "state": "UNKNOWN", "reason": f"config.conf unreadable: {config}", "provider": "codex",
        "checkpoint_dir": str(tmp_path / "checkpoints"),
        "local_retry_seconds": guard.LOCAL_RETRY_SECONDS,
        **guard.wakeup(NOW + 900)}
