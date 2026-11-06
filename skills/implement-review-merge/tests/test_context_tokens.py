"""Tests for scripts/context_tokens.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "context_tokens.py"
spec = importlib.util.spec_from_file_location("context_tokens", SCRIPT)
ct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ct)


def write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")


def assistant(inp: int, create: int, read: int) -> dict:
    return {"type": "assistant", "message": {"usage": {
        "input_tokens": inp, "cache_creation_input_tokens": create,
        "cache_read_input_tokens": read, "output_tokens": 9}}}


def test_claude_uses_last_assistant_usage(tmp_path):
    write_jsonl(tmp_path / ".claude/projects/C--repo/s1.jsonl", [
        assistant(1, 2, 3), assistant(2, 100, 1000), {"type": "user"}, "not json"])
    assert ct.claude_tokens({"CLAUDE_CODE_SESSION_ID": "s1"}, tmp_path) == 1102


def test_claude_honors_config_dir(tmp_path):
    write_jsonl(tmp_path / "cfg/projects/p/s1.jsonl", [assistant(5, 0, 0)])
    env = {"CLAUDE_CODE_SESSION_ID": "s1", "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")}
    assert ct.claude_tokens(env, tmp_path / "home") == 5


def test_codex_uses_last_token_count(tmp_path):
    def event(n: int) -> dict:
        return {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": n}, "model_context_window": 258400}}}

    write_jsonl(tmp_path / ".codex/sessions/2026/11/06/rollout-2026-11-06T01-02-03-t1.jsonl",
                [event(10), event(17845), {"type": "event_msg", "payload": {"type": "other"}}])
    assert ct.codex_tokens({"CODEX_THREAD_ID": "t1"}, tmp_path) == 17845


@pytest.mark.parametrize("provider,env", [
    ("claude", {}), ("claude", {"CLAUDE_CODE_SESSION_ID": "missing"}),
    ("codex", {}), ("codex", {"CODEX_THREAD_ID": "missing"})])
def test_unknown_when_missing(tmp_path, monkeypatch, capsys, provider, env):
    for key in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CONFIG_DIR", "CODEX_THREAD_ID", "CODEX_HOME"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(ct.Path, "home", lambda: tmp_path)
    assert ct.main(["--provider", provider]) == 0
    assert capsys.readouterr().out == "context-tokens: unknown\n"


def test_main_prints_tokens(tmp_path, monkeypatch, capsys):
    write_jsonl(tmp_path / ".claude/projects/p/s9.jsonl", [assistant(1, 1, 1)])
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s9")
    monkeypatch.setattr(ct.Path, "home", lambda: tmp_path)
    assert ct.main(["--provider", "claude"]) == 0
    assert capsys.readouterr().out == "context-tokens: 3\n"
