"""Tests for the PreToolUse hook that stops Orca workers at the quota pause.

Run with: uv run --no-project --with pytest -m pytest hooks/worker-quota-guard/tests
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

HOOK_DIR = Path(__file__).resolve().parents[1]
SCRIPT = HOOK_DIR / "worker_quota_guard.py"
spec = importlib.util.spec_from_file_location("worker_quota_guard", SCRIPT)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)

TERMINAL = "term_worker"
PAUSED = {"state": "PAUSED_QUOTA", "used_percentage": 96, "threshold": 95}


@pytest.fixture
def env(monkeypatch, tmp_path: Path):
    """A worker terminal with the real config and fake quota / Orca results."""
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", TERMINAL)
    state = SimpleNamespace(quota=(10, json.dumps(PAUSED)), workers=[
        {"terminal": TERMINAL, "outcome": "in_progress"}], calls=[])

    def fake_run(cmd: list[str], timeout: int) -> tuple[int, str]:
        state.calls.append(cmd)
        if "check" in cmd:
            return state.quota
        return 0, json.dumps({"ok": True, "result": {"workers": state.workers}})

    monkeypatch.setattr(hook, "run", fake_run)
    monkeypatch.setattr(hook.shutil, "which", lambda name: "orca")
    return state


def run_hook(monkeypatch, capsys, tool_name: str, tool_input: dict) -> str:
    data = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    monkeypatch.setattr(hook.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(data.encode())))
    assert hook.main(["--provider", "claude"]) == 0
    return capsys.readouterr().out


def denied(out: str) -> bool:
    return bool(out) and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_ready_allows_without_output(env, monkeypatch, capsys):
    env.quota = (0, json.dumps({"state": "READY"}))
    assert run_hook(monkeypatch, capsys, "Bash", {"command": "pytest"}) == ""
    assert env.calls[0][-3:] == ["check", "--provider", "claude"]
    assert not any("--threshold" in arg for call in env.calls for arg in call)


@pytest.mark.parametrize("quota", [(20, json.dumps({"state": "UNKNOWN"})), (1, ""), (-1, "")])
def test_unknown_or_unparseable_allows(env, monkeypatch, capsys, quota):
    env.quota = quota
    assert run_hook(monkeypatch, capsys, "Edit", {"file_path": "x"}) == ""


def test_paused_worker_denies_other_commands_with_reason(env, monkeypatch, capsys):
    out = run_hook(monkeypatch, capsys, "Bash", {"command": "pytest -q"})
    assert denied(out)
    reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "PAUSED_QUOTA" in reason and "worker_done" in reason and "config.conf" in reason


@pytest.mark.parametrize("tool", ["Read", "Edit", "Grep", "Agent", "mcp__x__y"])
def test_paused_worker_denies_non_shell_tools(env, monkeypatch, capsys, tool):
    assert denied(run_hook(monkeypatch, capsys, tool, {"file_path": "x"}))


@pytest.mark.parametrize("command", [
    "git add -A && git commit -m 'wip; keep' && git push",
    'git commit -m "$(cat <<\'EOF\'\nfix: x\n\nbody\nEOF\n)"',
    "cd /c/repo && git status",
    "orca orchestration send --from t --type worker_done --body 'a; b' --outcome failed",
    r"C:\Users\u\bin\orca.cmd orchestration check",
    "uv run --no-project ~/.agents/skills/quota-guard/scripts/quota_guard.py check --provider claude",
    "uv run --no-project ~/.agents/skills/implement-review-merge/scripts/context_tokens.py --provider claude",
    "bash ~/.agents/skills/pr-cross-review/scripts/review_status.sh 12",
    "gh pr view 12 --json headRefOid",
])
def test_paused_worker_allows_safe_boundary_commands(env, monkeypatch, capsys, command):
    assert run_hook(monkeypatch, capsys, "Bash", {"command": command}) == ""


@pytest.mark.parametrize("command", [
    "git push && pytest",
    "git status; rm -f x",
    "git add .\nuv run pytest",
    "git status | xargs echo",
    "echo $(git status)",
    "gitx status",
    "",
])
def test_paused_worker_denies_mixed_commands(env, monkeypatch, capsys, command):
    assert denied(run_hook(monkeypatch, capsys, "Bash", {"command": command}))


def test_powershell_is_a_shell_tool(env, monkeypatch, capsys):
    assert run_hook(monkeypatch, capsys, "PowerShell", {"command": "git push"}) == ""


@pytest.mark.parametrize("workers", [
    [],
    [{"terminal": TERMINAL, "state": "succeeded"}],
    [{"terminal": "term_other", "outcome": "in_progress"}],
])
def test_paused_non_worker_terminal_allows(env, monkeypatch, capsys, workers):
    env.workers = workers
    assert run_hook(monkeypatch, capsys, "Bash", {"command": "pytest"}) == ""


def test_worker_found_on_later_page(env, monkeypatch, capsys):
    pages = iter([
        {"workers": [{"terminal": "term_other"}], "nextCursor": "c1"},
        {"workers": [{"terminal": TERMINAL, "outcome": "in_progress"}]},
    ])

    def fake_run(cmd, timeout):
        if "check" in cmd:
            return 10, json.dumps(PAUSED)
        env.calls.append(cmd)
        return 0, json.dumps({"ok": True, "result": next(pages)})

    monkeypatch.setattr(hook, "run", fake_run)
    assert denied(run_hook(monkeypatch, capsys, "Bash", {"command": "pytest"}))
    assert env.calls[-1][-2:] == ["--cursor", "c1"]


@pytest.mark.parametrize("result", [(1, ""), (0, "not json"), (-1, "")])
def test_orca_failure_allows(env, monkeypatch, capsys, result):
    def fake_run(cmd, timeout):
        return (10, json.dumps(PAUSED)) if "check" in cmd else result

    monkeypatch.setattr(hook, "run", fake_run)
    assert run_hook(monkeypatch, capsys, "Bash", {"command": "pytest"}) == ""


def test_outside_orca_allows_without_checking(env, monkeypatch, capsys):
    monkeypatch.delenv("ORCA_TERMINAL_HANDLE")
    assert run_hook(monkeypatch, capsys, "Bash", {"command": "pytest"}) == ""
    assert env.calls == []


@pytest.mark.parametrize("content", [None, "QUOTA_GUARD=a\nBOGUS=1\n", "ALLOW_COMMAND=(\n",
                                     "SHELL_TOOL=Bash\n"])
def test_missing_or_invalid_config_allows_with_warning(env, monkeypatch, capsys, tmp_path,
                                                       content):
    config = tmp_path / "config.conf"
    if content is not None:
        config.write_text(content, encoding="utf-8")
    monkeypatch.setattr(hook, "CONFIG", config)
    data = json.dumps({"tool_name": "Bash", "tool_input": {"command": "pytest"}})
    monkeypatch.setattr(hook.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(data.encode())))
    assert hook.main(["--provider", "codex"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and "worker-quota-guard:" in captured.err
    assert env.calls == []


def test_running_twice_gives_the_same_result(env, monkeypatch, capsys):
    first = run_hook(monkeypatch, capsys, "Bash", {"command": "pytest"})
    assert first == run_hook(monkeypatch, capsys, "Bash", {"command": "pytest"})


def test_script_holds_no_threshold_or_allowed_commands():
    source = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"\b9[0-9]\b|--threshold\"", source)
    for word in ("git ", "orchestration send", "quota_guard.py check"):
        assert f'"{word}' not in source
    config = hook.load_config(HOOK_DIR / "config.conf")
    assert config["QUOTA_GUARD"] and config["ALLOW_COMMAND"] and config["SHELL_TOOL"]
