"""Tests for wait_actionable.py output formatting.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "wait_actionable.py"

HANDOFF = "\n".join([
    "Implemented the change and opened the PR. " + "x" * 400,
    "PR: https://github.com/owner/repo/pull/123",
    "branch: owner/issue-39",
    "worktree: C:/work/issue-39",
    "review-count: 2/5",
    "open findings: none",
    "CI: passing",
])


def load_module():
    spec = importlib.util.spec_from_file_location("wait_actionable", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def message(msg_type: str, body: str) -> dict:
    payload = {"taskId": "task_1", "dispatchId": "ctx_1"}
    return {"type": msg_type, "id": f"msg_{msg_type}", "subject": "s",
            "body": body, "payload": json.dumps(payload)}


def printed(capsys: pytest.CaptureFixture[str], messages: list[dict]) -> str:
    load_module().print_delivery({"deliveryId": "dlv_1", "messages": messages})
    return capsys.readouterr().out


@pytest.mark.parametrize("msg_type", ["worker_done", "escalation", "question"])
def test_actionable_body_is_printed_in_full(
    capsys: pytest.CaptureFixture[str], msg_type: str
) -> None:
    out = printed(capsys, [message(msg_type, HANDOFF)])
    assert "  body: |" in out
    for line in HANDOFF.splitlines():
        assert f"    {line}\n" in out
    assert "…" not in out


def test_other_body_stays_one_line_summary(capsys: pytest.CaptureFixture[str]) -> None:
    out = printed(capsys, [message("status", HANDOFF)])
    body_lines = [line for line in out.splitlines() if line.startswith("  body:")]
    assert len(body_lines) == 1
    assert body_lines[0].endswith("…")
    assert "review-count: 2/5" not in out


def test_heartbeat_is_only_counted(capsys: pytest.CaptureFixture[str]) -> None:
    out = printed(capsys, [message("heartbeat", HANDOFF), message("worker_done", "done")])
    assert "heartbeats=1" in out
    assert "type=heartbeat" not in out
    assert "    done\n" in out
