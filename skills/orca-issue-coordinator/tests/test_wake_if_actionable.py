"""Tests for wake_if_actionable.py wake decisions.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "wake_if_actionable.py"


def load_module():
    spec = importlib.util.spec_from_file_location("wake_if_actionable", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def worker(dispatch: str, outcome: str = "in_progress", requires: bool = False,
           kind: str = "none") -> dict:
    return {"dispatchId": dispatch, "projection": {
        "outcome": outcome,
        "attention": {"categories": ["stalled"] if requires else [], "requiresAction": requires},
        "nextAction": {"kind": kind, "argv": []},
    }}


class Orca:
    """Fake orca responses keyed by subcommand; a value of Exception raises."""

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.workers: list[dict] = [worker("ctx_1")]
        self.worker_pages: list[list[dict]] | None = None
        self.tasks: list[dict] = [{"id": "task_1", "status": "dispatched"}]
        self.fail: str | None = None
        self.calls: list[list[str]] = []

    def __call__(self, orca: str, args: list[str], budget) -> dict:
        budget.timeout()
        self.calls.append(args)
        if self.fail == args[1]:
            raise RuntimeError(f"orca {args[1]} failed: boom")
        if args[1] == "check":
            assert "--peek" in args and "--ack" not in args and "--wait" not in args
            return {"messages": self.messages}
        if args[1] == "worker-list":
            if self.worker_pages is None:
                return {"workers": self.workers}
            index = int(args[args.index("--cursor") + 1]) if "--cursor" in args else 0
            more = index + 1 < len(self.worker_pages)
            return {"workers": self.worker_pages[index],
                    "page": {"hasMore": more, "nextCursor": str(index + 1) if more else None}}
        if args[1] == "task-list":
            return {"tasks": self.tasks}
        raise AssertionError(args)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = load_module()
    orca = Orca()
    sent: list[str] = []
    send_ok = {"value": True}

    def fake_send(exe: str, terminal: str, text: str) -> bool:
        sent.append(text)
        return send_ok["value"]

    monkeypatch.setattr(module, "run_orca", orca)
    monkeypatch.setattr(module, "send_wake", fake_send)
    checkpoint = tmp_path / "coordinator.md"
    checkpoint.write_text("# Run run_1\nwaiting-mode: recurring\n", encoding="utf-8")

    def run(capsys: pytest.CaptureFixture[str], *extra: str) -> tuple[int, dict]:
        monkeypatch.setattr("sys.argv", [
            "wake_if_actionable.py", "--terminal", "term_c", "--run", "run_1",
            "--checkpoint", str(checkpoint), "--text", "Resume", "--orca", "orca", *extra])
        code = module.main()
        return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    return {"module": module, "orca": orca, "sent": sent, "send_ok": send_ok,
            "checkpoint": checkpoint, "run": run, "state": tmp_path / "wake-state.json"}


def test_nothing_actionable_does_not_wake(env, capsys) -> None:
    code, result = env["run"](capsys)
    assert code == 1
    assert result == {"wake": False, "reasons": [], "sent": None}
    assert env["sent"] == []


def test_unread_actionable_message_wakes(env, capsys) -> None:
    env["orca"].messages = [{"type": "worker_done", "id": "msg_1"}]
    code, result = env["run"](capsys)
    assert code == 2
    assert result["reasons"] == ["message:worker_done:msg_1"]
    assert result["sent"] is True
    assert env["sent"] == ["Resume"]
    peek = env["orca"].calls[0]
    assert peek[peek.index("--types") + 1] == "worker_done,escalation,question"


def test_heartbeat_message_does_not_wake(env, capsys) -> None:
    env["orca"].messages = [{"type": "heartbeat", "id": "msg_h"}]
    code, _ = env["run"](capsys)
    assert code == 1


@pytest.mark.parametrize("w", [worker("ctx_1", requires=True),
                               worker("ctx_1", kind="release")])
def test_worker_requiring_action_wakes(env, capsys, w: dict) -> None:
    env["orca"].workers = [w]
    code, result = env["run"](capsys)
    assert code == 2
    assert result["reasons"][0].startswith("worker:ctx_1:")


def test_no_worker_in_progress_while_tasks_remain_wakes(env, capsys) -> None:
    env["orca"].workers = [worker("ctx_1", outcome="succeeded")]
    env["orca"].tasks = [{"id": "task_1", "status": "completed"},
                         {"id": "task_2", "status": "ready"}]
    code, result = env["run"](capsys)
    assert code == 2
    assert result["reasons"] == ["idle:task_2"]


def test_no_worker_and_no_remaining_task_does_not_wake(env, capsys) -> None:
    env["orca"].workers = [worker("ctx_1", outcome="succeeded")]
    env["orca"].tasks = [{"id": "task_1", "status": "completed"}]
    code, _ = env["run"](capsys)
    assert code == 1


def test_passed_deadline_wakes_and_future_one_does_not(env, capsys) -> None:
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
    future = (datetime.now().astimezone() + timedelta(hours=1)).isoformat(timespec="seconds")
    env["checkpoint"].write_text(
        f"waiting-mode: recurring\n- wake-at: {future} review retry #9\n"
        f"- wake-at: {past} ci #12\n", encoding="utf-8")
    code, result = env["run"](capsys)
    assert code == 2
    assert result["reasons"] == [f"deadline:{past} ci #12"]


def test_unparseable_deadline_wakes_as_error(env, capsys) -> None:
    env["checkpoint"].write_text("wake-at: soon\n", encoding="utf-8")
    code, result = env["run"](capsys)
    assert code == 2
    assert result["reasons"] == ["error:checkpoint"]
    assert "soon" in result["errors"][0]


def test_missing_checkpoint_wakes_as_error(env, capsys) -> None:
    env["checkpoint"].unlink()
    code, result = env["run"](capsys)
    assert code == 2
    assert "error:checkpoint" in result["reasons"]


@pytest.mark.parametrize("sub", ["check", "worker-list", "task-list"])
def test_orca_failure_wakes(env, capsys, sub: str) -> None:
    env["orca"].workers = [worker("ctx_1", outcome="succeeded")]
    env["orca"].fail = sub
    code, result = env["run"](capsys)
    assert code == 2
    name = "check" if sub == "check" else "worker-list"
    assert f"error:{name}" in result["reasons"]
    assert "boom" in " ".join(result["errors"])


def test_safety_interval_wakes(env, capsys) -> None:
    old = time.time() - 61 * 60
    os.utime(env["checkpoint"], (old, old))
    code, result = env["run"](capsys)
    assert code == 2
    assert result["reasons"] == ["safety:60m"]
    code, _ = env["run"](capsys)
    assert code == 1


def test_seen_condition_does_not_wake_again_until_it_returns(env, capsys) -> None:
    env["orca"].messages = [{"type": "question", "id": "msg_q"}]
    assert env["run"](capsys)[0] == 2
    assert env["run"](capsys)[0] == 1
    env["orca"].messages = []
    assert env["run"](capsys)[0] == 1
    env["orca"].messages = [{"type": "question", "id": "msg_q"}]
    assert env["run"](capsys)[0] == 2
    assert len(env["sent"]) == 2


def test_failed_send_retries_on_next_run(env, capsys) -> None:
    env["orca"].messages = [{"type": "escalation", "id": "msg_e"}]
    env["send_ok"]["value"] = False
    code, result = env["run"](capsys)
    assert code == 3
    assert result["sent"] is False
    env["send_ok"]["value"] = True
    code, result = env["run"](capsys)
    assert code == 2
    assert result["reasons"] == ["message:escalation:msg_e"]


def test_state_is_kept_next_to_checkpoint(env, capsys) -> None:
    env["orca"].messages = [{"type": "worker_done", "id": "msg_1"}]
    env["run"](capsys)
    state = json.loads(env["state"].read_text(encoding="utf-8"))
    assert state["seen"] == ["message:worker_done:msg_1"]
    assert datetime.fromisoformat(state["last_wake"]).tzinfo is not None


def test_worker_list_reads_every_page(env, capsys) -> None:
    env["orca"].worker_pages = [[worker("ctx_new")],
                                [worker("ctx_old", outcome="succeeded", kind="release")]]
    code, result = env["run"](capsys)
    assert code == 2
    assert result["reasons"] == ["worker:ctx_old:-:release"]
    cursors = [c[c.index("--cursor") + 1] for c in env["orca"].calls if "--cursor" in c]
    assert cursors == ["1"]


def test_exhausted_query_budget_still_sends_wake(env, capsys, monkeypatch) -> None:
    monkeypatch.setattr(env["module"], "QUERY_BUDGET_S", 0)
    code, result = env["run"](capsys)
    assert code == 2
    assert result["reasons"] == ["error:check", "error:worker-list"]
    assert all("budget exhausted" in e for e in result["errors"])
    assert env["sent"] == ["Resume"]


def test_orca_calls_share_one_time_budget(tmp_path, monkeypatch) -> None:
    module = load_module()
    calls: list[float] = []

    def fake_run(cmd, **kwargs):
        calls.append(kwargs["timeout"])
        raise module.subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    budget = module.Budget(module.QUERY_BUDGET_S)
    with pytest.raises(module.subprocess.TimeoutExpired):
        module.run_orca("orca", ["orchestration", "check"], budget)
    assert calls == [module.CALL_TIMEOUT_S]
    assert module.QUERY_BUDGET_S + module.SEND_TIMEOUT_S < 120
