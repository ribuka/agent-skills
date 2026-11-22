"""Tests for lookback's sessions.py (review window, session search, digest).

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "sessions.py"

spec = importlib.util.spec_from_file_location("lookback_sessions", SCRIPT)
sessions = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sessions  # dataclasses look the module up while the class is built
spec.loader.exec_module(sessions)

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _git(repo: Path, *args: str, date: str | None = None) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    if date:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = date
    subprocess.run([shutil.which("git"), "-C", str(repo), *args], check=True,
                   capture_output=True, env=env)


def _jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _skill_use(ts: str, skill: str) -> dict:
    return {"type": "assistant", "timestamp": ts, "cwd": "/w",
            "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": skill}}]}}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    skill = root / "skills" / "demo"
    (skill / "tests").mkdir(parents=True)
    _git(root, "init", "-q")
    (skill / "SKILL.md").write_text("v1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "first", date="2026-11-01T00:00:00Z")
    (skill / "SKILL.md").write_text("v2\n", encoding="utf-8")
    _git(root, "commit", "-qam", "change skill", date="2026-11-05T00:00:00Z")
    (skill / "tests" / "test_x.py").write_text("x\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "tests only", date="2026-11-09T00:00:00Z")
    return root


def test_window_starts_at_last_skill_commit_ignoring_tests(repo: Path) -> None:
    window = sessions.fix_window(repo / "skills" / "demo")
    assert sessions._iso(window.since) == "2026-11-05T00:00:00Z"
    assert window.basis.endswith("change skill")


def test_window_uncommitted_change_moves_start(repo: Path) -> None:
    (repo / "skills" / "demo" / "SKILL.md").write_text("v3\n", encoding="utf-8")
    window = sessions.fix_window(repo / "skills" / "demo")
    assert window.basis.startswith("uncommitted ")
    assert window.since > datetime(2026, 11, 9, tzinfo=timezone.utc)


def test_window_since_accepts_date_and_commit(repo: Path) -> None:
    skill_dir = repo / "skills" / "demo"
    assert sessions._iso(sessions.fix_window(skill_dir, "2026-10-01").since) == "2026-10-01T00:00:00Z"
    assert sessions._iso(sessions.fix_window(skill_dir, "HEAD~2").since) == "2026-11-01T00:00:00Z"
    with pytest.raises(sessions.LookbackError):
        sessions.fix_window(skill_dir, "no-such-ref")


def test_claude_invocations_in_window_until_lookback(tmp_path: Path) -> None:
    path = _jsonl(tmp_path / "claude" / "p" / "s.jsonl", [
        _skill_use("2026-10-30T00:00:00Z", "demo"),
        {"type": "user", "timestamp": "2026-11-02T00:00:00Z",
         "message": {"content": "<command-name>/demo</command-name>"}},
        _skill_use("2026-11-03T00:00:00Z", "demo"),
        _skill_use("2026-11-04T00:00:00Z", "lookback"),
        _skill_use("2026-11-05T00:00:00Z", "demo"),
    ])
    found = sessions.scan_session(path, "claude", "demo", T0)
    assert (sessions._iso(found.first), found.count, found.cwd) == ("2026-11-02T00:00:00Z", 2, "/w")
    assert sessions.scan_session(path, "claude", "other", T0) is None


def test_codex_skill_block_and_skill_md_read(tmp_path: Path) -> None:
    path = _jsonl(tmp_path / "codex" / "2026" / "rollout-x.jsonl", [
        {"type": "session_meta", "timestamp": "2026-11-02T00:00:00Z", "payload": {"cwd": "/c"}},
        {"type": "response_item", "timestamp": "2026-11-02T00:00:01Z",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "<skill>\n<name>demo</name>\n..."}]}},
        {"type": "response_item", "timestamp": "2026-11-02T00:00:02Z",
         "payload": {"type": "function_call", "name": "shell",
                     "arguments": "Get-Content C:\\\\x\\\\skills\\\\demo\\\\SKILL.md"}},
        {"type": "response_item", "timestamp": "2026-11-02T00:00:03Z",
         "payload": {"type": "message", "role": "developer",
                     "content": [{"type": "input_text", "text": "- demo: ... (file: skills/demo/SKILL.md)"}]}},
    ])
    found = sessions.scan_session(path, "codex", "demo", T0)
    assert (found.count, found.cwd) == (2, "/c")


def test_find_sessions_newest_first(tmp_path: Path) -> None:
    _jsonl(tmp_path / "claude" / "a" / "1.jsonl", [_skill_use("2026-11-02T00:00:00Z", "demo")])
    _jsonl(tmp_path / "claude" / "b" / "2.jsonl", [_skill_use("2026-11-03T00:00:00Z", "demo")])
    found = sessions.find_sessions("demo", T0, "all", tmp_path / "claude", tmp_path / "codex")
    assert [s.path.name for s in found] == ["2.jsonl", "1.jsonl"]


def test_digest_skips_meta_and_keeps_errors(tmp_path: Path) -> None:
    path = _jsonl(tmp_path / "s.jsonl", [
        {"type": "file-history-snapshot", "message": {"content": "noise"}},
        {"type": "user", "isMeta": True, "timestamp": "2026-11-02T00:00:00Z", "message": {"content": "skill body"}},
        {"type": "user", "timestamp": "2026-11-02T00:00:01Z",
         "message": {"content": "do it<system-reminder>hidden</system-reminder>"}},
        _skill_use("2026-11-02T00:00:02Z", "demo"),
        {"type": "user", "timestamp": "2026-11-02T00:00:03Z", "message": {"content": [
            {"type": "tool_result", "is_error": True, "content": "boom"},
            {"type": "tool_result", "content": "fine"}]}},
    ])
    text = sessions.digest(path, None, 10000)
    assert "noise" not in text and "skill body" not in text and "hidden" not in text
    assert "USER: do it" in text
    assert 'TOOL Skill: {"skill": "demo"}' in text
    assert "TOOL ERROR: boom" in text and "fine" not in text
    assert sessions.digest(path, datetime(2026, 11, 2, 0, 0, 2, tzinfo=timezone.utc), 10000).startswith(
        "[2026-11-02T00:00:02Z] TOOL Skill")
