"""Tests for list_workers.py, using fixture pages and a fake command runner.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "list_workers.py"
ORCA = "/opt/orca/bin/orca"


def load_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("list_workers", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def worker(n: int, argv: list[str] | None = None, terminal: str = "released",
           auto_release: str | None = None) -> dict:
    return {
        "dispatchId": f"ctx_{n}", "taskId": f"task_{n}", "runId": "run_1",
        "workerState": "succeeded", "terminalState": terminal,
        "resource": {"autoReleaseAt": auto_release},
        "projection": {"liveness": {"verdict": "exited"},
                       "nextAction": {"argv": argv or []}},
    }


def page(workers: list[dict], cursor: str | None = None, **extra) -> tuple[int, str]:
    body = {"workers": workers, "page": {"hasMore": cursor is not None, "nextCursor": cursor},
            **extra}
    return 0, json.dumps({"id": "x", "ok": True, "result": body})


@pytest.fixture
def lw(monkeypatch: pytest.MonkeyPatch):
    module = load_module(monkeypatch)
    calls: list[list[str]] = []
    module.pages = [page([worker(1)])]

    def fake_run(cmd: list[str], timeout_seconds: float) -> tuple[int, str]:
        assert timeout_seconds == 60
        calls.append(cmd)
        return module.pages[len(calls) - 1]

    monkeypatch.setattr(module, "run_stdout", fake_run)
    module.calls = calls
    return module


def rows(out: str) -> list[dict]:
    return [json.loads(line) for line in out.splitlines()]


def test_single_page_uses_detailed_json(lw, capsys: pytest.CaptureFixture[str]) -> None:
    assert lw.main(["--orca", ORCA, "--run", "run_1"]) == 0
    assert lw.calls == [[ORCA, "orchestration", "worker-list", "--run", "run_1", "--limit",
                         "100", "--json", "--full"]]
    out = rows(capsys.readouterr().out)
    assert out == [
        {"dispatch": "ctx_1", "task": "task_1", "state": "succeeded",
         "terminalState": "released", "liveness": "exited", "autoReleaseAt": None, "next": []},
        {"workers": 1, "pages": 1},
    ]


def test_follows_every_cursor(lw, capsys: pytest.CaptureFixture[str]) -> None:
    lw.pages = [page([worker(n)], f"c{n}") for n in range(1, 30)] + [page([worker(30)])]
    assert lw.main(["--orca", ORCA, "--run", "run_1", "--terminal-state", "reclaimable"]) == 0
    assert len(lw.calls) == 30
    assert lw.calls[0][-4:] == ["--terminal-state", "reclaimable", "--json", "--full"]
    assert lw.calls[1][-4:] == ["--cursor", "c1", "--json", "--full"]
    out = rows(capsys.readouterr().out)
    assert out[-1] == {"workers": 30, "pages": 30}
    assert [row["dispatch"] for row in out[:-1]] == [f"ctx_{n}" for n in range(1, 31)]


def test_next_action_and_auto_release_are_reported(lw, capsys: pytest.CaptureFixture[str]) -> None:
    lw.pages = [page([
        worker(1, ["orca", "orchestration", "worker-release", "--dispatch", "ctx_1"],
               terminal="reclaimable"),
        worker(2, ["orchestration", "worker-show", "--dispatch", "ctx_2"]),
        worker(3, terminal="reclaimable", auto_release="2026-11-05T10:00:00Z"),
    ])]
    assert lw.main(["--orca", ORCA, "--run", "run_1"]) == 0
    out = rows(capsys.readouterr().out)
    assert out[0]["next"] == [ORCA, "orchestration", "worker-release", "--dispatch", "ctx_1"]
    assert out[1]["next"] == [ORCA, "orchestration", "worker-show", "--dispatch", "ctx_2"]
    assert out[2]["autoReleaseAt"] == "2026-11-05T10:00:00Z"
    assert out[2]["next"] == []


def test_empty_run_is_a_complete_empty_list(lw, capsys: pytest.CaptureFixture[str]) -> None:
    lw.pages = [page([])]
    assert lw.main(["--orca", ORCA, "--run", "run_1"]) == 0
    assert rows(capsys.readouterr().out) == [{"workers": 0, "pages": 1}]


def missing(field: str) -> dict:
    row = worker(1)
    del row[field]
    return row


@pytest.mark.parametrize("pages, reason", [
    ([(1, "")], "exited 1"),
    ([(0, "not json")], "not a detailed receipt"),
    ([(0, json.dumps({"ok": True, "result": {"workers": [], "nextCursor": None}}))],
     "not a detailed receipt"),
    ([(0, json.dumps({"ok": False, "result": {"workers": [], "page": {}}}))],
     "not a successful receipt"),
    ([page([], None, partialHostErrors=[{"name": "remote"}])], "incomplete host inventory"),
    ([page([missing("dispatchId")])], "missing dispatchId"),
    ([page([missing("workerState")])], "missing workerState"),
    ([page([missing("projection")])], "no projection"),
    ([page([{**worker(1), "projection": {"liveness": {"verdict": "x"},
                                         "nextAction": {"argv": "bad"}}}])],
     "malformed nextAction"),
    ([page([worker(1)], "c1"), (1, "")], "exited 1 on page 2"),
    ([page([worker(1)], "")], "no new nextCursor"),
    ([(0, json.dumps({"ok": True, "result": {"workers": [], "page": {
        "nextCursor": "remaining-page"}}}))], "no boolean page.hasMore"),
    ([(0, json.dumps({"ok": True, "result": {"workers": [], "page": {
        "hasMore": None, "nextCursor": "c1"}}}))], "no boolean page.hasMore"),
    ([(0, json.dumps({"ok": True, "result": {"workers": [], "page": {
        "hasMore": "false"}}}))], "no boolean page.hasMore"),
    ([page([worker(1)], "c1"), page([worker(2)], "c1")], "no new nextCursor"),
])
def test_incomplete_list_is_an_error(lw, capsys: pytest.CaptureFixture[str], pages,
                                     reason: str) -> None:
    lw.pages = pages
    assert lw.main(["--orca", ORCA, "--run", "run_1"]) == 1
    out = rows(capsys.readouterr().out)
    assert len(out) == 1
    assert reason in out[0]["error"]


def test_page_limit_is_an_error(lw, capsys: pytest.CaptureFixture[str]) -> None:
    lw.pages = [page([worker(n)], f"c{n}") for n in range(lw.MAX_PAGES + 1)]
    assert lw.main(["--orca", ORCA, "--run", "run_1"]) == 1
    assert "more than" in rows(capsys.readouterr().out)[0]["error"]
