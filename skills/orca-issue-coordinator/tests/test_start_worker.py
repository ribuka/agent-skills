"""Tests for start_worker.py, using fixture receipts and a fake command runner.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "start_worker.py"
ORCA = "/opt/orca/bin/orca"
ARGS = ["--spec", "brief", "--task-title", "#1 title", "--worktree", "new-top-level",
        "--name", "issue-1", "--setup", "run", "--agent", "claude", "--model", "opus",
        "--effort", "medium"]


def load_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("start_worker", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def receipt(state: str, **fields) -> str:
    result = {"dispatchId": "ctx_1", "taskId": "task_1", "runId": "run_1", "state": state,
              **fields}
    return json.dumps({"id": "x", "ok": state == "ready", "result": result})


READY = receipt("ready", launch={"effective": {"agent": "claude", "model": "opus",
                                               "effort": "medium"}})


@pytest.fixture
def sw(monkeypatch: pytest.MonkeyPatch):
    module = load_module(monkeypatch)
    calls: list[list[str]] = []
    module.reply = (0, READY)

    def fake_run(cmd: list[str], timeout_seconds: float) -> tuple[int, str]:
        assert timeout_seconds == 900
        calls.append(cmd)
        return module.reply

    monkeypatch.setattr(module, "run_stdout", fake_run)
    module.calls = calls
    return module


def start(sw, reply: tuple[int, str]) -> int:
    sw.reply = reply
    return sw.main(["--orca", ORCA, "--", *ARGS])


def test_ready_adds_json_full_and_prints_dispatch(sw, capsys: pytest.CaptureFixture[str]) -> None:
    assert start(sw, (0, READY)) == 0
    assert sw.calls == [[ORCA, "orchestration", "worker-start", *ARGS, "--json", "--full"]]
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "start: ready"
    assert "dispatch: ctx_1" in out
    assert "effective: agent=claude model=opus effort=medium" in out


def test_exit_code_of_worker_start_is_ignored(sw) -> None:
    # With --full, worker-start exits 1 for anything but ready; the JSON decides.
    assert start(sw, (1, READY)) == 0
    unobserved = receipt("outcome_unknown", turnStart="unobserved")
    assert start(sw, (0, unobserved)) == 3


@pytest.mark.parametrize("fields", [{"turnStart": "unobserved"},
                                    {"stage": "turn_start_unobserved"}])
def test_unobserved_turn_start_waits(sw, capsys: pytest.CaptureFixture[str], fields) -> None:
    assert start(sw, (1, receipt("outcome_unknown", **fields))) == 3
    out = capsys.readouterr().out
    assert out.startswith("start: unobserved\n")
    assert "dispatch: ctx_1" in out


@pytest.mark.parametrize("state", ["failed", "outcome_unknown"])
def test_failed_or_unknown_start_is_not_rerun(sw, capsys: pytest.CaptureFixture[str],
                                              state: str) -> None:
    reply = receipt(state, failedStage="agent_launch", lastError="boom",
                    recovery="orca orchestration worker-show --dispatch ctx_1",
                    nextCommands=["orca orchestration worker-release --dispatch ctx_1"])
    assert start(sw, (1, reply)) == 1
    out = capsys.readouterr().out
    assert out.startswith("start: failed\n")
    assert f"state: {state}" in out
    assert "failed-stage: agent_launch" in out
    assert "error: boom" in out
    assert "next: orca orchestration worker-show --dispatch ctx_1" in out
    assert "next-command: orca orchestration worker-release --dispatch ctx_1" in out
    assert len(sw.calls) == 1


@pytest.mark.parametrize("reply", [
    (1, ""),
    (1, "not json"),
    (1, json.dumps({"ok": False, "error": {"code": "selector_not_found"}})),
    (0, json.dumps({"ok": True, "result": []})),
    (0, json.dumps({"ok": True, "result": {"state": "ready"}})),
    (0, json.dumps({"ok": True, "result": {"dispatchId": "ctx_1"}})),
    (0, receipt("ready")),
    (0, receipt("ready", launch={"effective": None})),
    (0, receipt("starting")),
    (124, ""),
])
def test_invalid_receipt_is_a_failed_start(sw, capsys: pytest.CaptureFixture[str],
                                           reply: tuple[int, str]) -> None:
    assert start(sw, reply) == 2
    assert capsys.readouterr().out.startswith("start: invalid\n")
    assert len(sw.calls) == 1


def test_launch_mismatch_is_reported(sw, capsys: pytest.CaptureFixture[str]) -> None:
    reply = receipt("ready", launch={"effective": {"agent": "claude", "model": "sonnet",
                                                   "effort": "medium"}})
    assert start(sw, (0, reply)) == 4
    out = capsys.readouterr().out
    assert out.startswith("start: mismatch\n")
    assert "launch-mismatch: model" in out


@pytest.mark.parametrize("extra", [["--json"], ["--full"], []])
def test_rejects_own_flags_or_no_arguments(sw, extra: list[str]) -> None:
    argv = ["--orca", ORCA, "--", *(ARGS + extra if extra else [])]
    with pytest.raises(SystemExit):
        sw.main(argv)
    assert sw.calls == []
