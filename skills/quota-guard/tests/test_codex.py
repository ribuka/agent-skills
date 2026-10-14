"""Codex live transport and Orca wake regression tests using local fixtures only."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "quota_guard.py"
spec = importlib.util.spec_from_file_location("quota_guard_codex", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
NOW = 1800001000


def snapshot(used: float = 4, secondary: float | None = 7) -> dict:
    return {"rateLimits": {"limitId": "codex", "primary": {
        "usedPercent": used, "windowDurationMins": 300, "resetsAt": NOW + 5000},
        "secondary": None if secondary is None else {
            "usedPercent": secondary, "windowDurationMins": 10080,
            "resetsAt": NOW + 50000}, "rateLimitReachedType": None}}


@pytest.mark.parametrize("used,state", [(0, "READY"), (94.9, "READY"),
                                        (95, "PAUSED_QUOTA"), (100, "PAUSED_QUOTA")])
def test_five_hour_boundary(tmp_path, monkeypatch, used, state):
    monkeypatch.setattr(guard, "read_codex_limits", lambda: snapshot(used))
    result = guard.check_codex(tmp_path, NOW)
    assert result["state"] == state
    assert result["used_percentage"] == used
    assert result["checkpoint_dir"] == str(tmp_path / "checkpoints")
    if state == "PAUSED_QUOTA":
        assert result["wake_at"] >= NOW + 5120
        assert result["blocking_window"] == "primary"
    else:
        assert "cron" not in result


@pytest.mark.parametrize("secondary,state", [(None, "READY"), (95, "READY"),
                                             (100, "PAUSED_QUOTA")])
def test_secondary_policy(tmp_path, monkeypatch, secondary, state):
    monkeypatch.setattr(guard, "read_codex_limits", lambda: snapshot(4, secondary))
    result = guard.check_codex(tmp_path, NOW)
    assert result["state"] == state
    if secondary == 100:
        assert result["reason"] == "secondary_exhausted"
        assert result["blocking_window"] == "secondary"
        assert result["wake_at"] >= NOW + 50120


def test_both_windows_block_until_later_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "read_codex_limits", lambda: snapshot(96, 100))
    assert guard.check_codex(tmp_path, NOW)["wake_at"] >= NOW + 50120


@pytest.mark.parametrize("field,value", [("usedPercent", True), ("usedPercent", -1),
    ("usedPercent", 101), ("usedPercent", float("nan")), ("resetsAt", None),
    ("resetsAt", NOW), ("resetsAt", 1e100), ("windowDurationMins", 10080), ("windowDurationMins", True)])
def test_invalid_primary_fails_closed(tmp_path, monkeypatch, field, value):
    data = snapshot()
    data["rateLimits"]["primary"][field] = value
    monkeypatch.setattr(guard, "read_codex_limits", lambda: data)
    result = guard.check_codex(tmp_path, NOW)
    assert result["state"] == "UNKNOWN"
    assert result["local_retry_seconds"] > 0
    assert result["wake_at"] >= NOW + 900


@pytest.mark.parametrize("data", [{}, {"rateLimits": None}, {"rateLimits": []},
    {"rateLimits": {"limitId": "other"}}, {"rateLimits": {"limitId": "codex"}}])
def test_missing_bucket_fails_closed(tmp_path, monkeypatch, data):
    monkeypatch.setattr(guard, "read_codex_limits", lambda: data)
    assert guard.check_codex(tmp_path, NOW)["state"] == "UNKNOWN"


def test_server_signal_without_window_is_unknown(tmp_path, monkeypatch):
    data = snapshot()
    data["rateLimits"]["rateLimitReachedType"] = "unexpected_limit"
    monkeypatch.setattr(guard, "read_codex_limits", lambda: data)
    result = guard.check_codex(tmp_path, NOW)
    assert result["state"] == "UNKNOWN"
    assert result["reason"] == "server_limit_reached"


def test_invalid_secondary_is_unknown(tmp_path, monkeypatch):
    data = snapshot()
    data["rateLimits"]["secondary"] = {"usedPercent": 1}
    monkeypatch.setattr(guard, "read_codex_limits", lambda: data)
    assert guard.check_codex(tmp_path, NOW)["state"] == "UNKNOWN"


@pytest.mark.parametrize("error", [FileNotFoundError(), TimeoutError(), ValueError(),
                                    subprocess.TimeoutExpired("codex", 20)])
def test_acquisition_errors_are_unknown(tmp_path, monkeypatch, error):
    def fail() -> dict:
        raise error
    monkeypatch.setattr(guard, "read_codex_limits", fail)
    assert guard.check_codex(tmp_path, NOW)["state"] == "UNKNOWN"


@pytest.fixture
def fake_server(tmp_path, monkeypatch):
    """Launch a real local pipe peer; never invoke Codex or use the network."""
    script = tmp_path / "server.py"
    script.write_text('''import json, sys, time, subprocess
mode = sys.argv[1]
first = json.loads(sys.stdin.readline())
assert first['method'] == 'initialize'
assert first['params']['clientInfo']['name'] == 'quota_guard'
if mode == 'descendant':
    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
if mode in ('timeout', 'descendant'):
    time.sleep(30)
    sys.exit(0)
if mode == 'eof':
    sys.exit(0)
if mode == 'malformed':
    print('invalid json', flush=True)
    sys.exit(0)
print(json.dumps({'method': 'notification'}), flush=True)
print(json.dumps({'id': 99, 'result': {}}), flush=True)
print(json.dumps({'id': 1, 'result': {}}), flush=True)
assert json.loads(sys.stdin.readline())['method'] == 'initialized'
assert json.loads(sys.stdin.readline()) == {'id': 2, 'method': 'account/rateLimits/read'}
reply = {'id': 2, 'error': {'message': 'unauthorized'}} if mode == 'error' else {'id': 2, 'result': {'rateLimits': {'test': True}}}
print(json.dumps(reply), flush=True)
sys.stdin.read()
''', encoding="utf-8")
    original = subprocess.Popen
    processes = []
    mode = ["ok"]

    def start(command: list[str], **kwargs) -> subprocess.Popen:
        assert command == [sys.executable, "app-server"]
        process = original([sys.executable, str(script), mode[0]], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(guard.shutil, "which", lambda _: sys.executable)
    transport = SimpleNamespace(**vars(subprocess))
    transport.Popen = start
    monkeypatch.setattr(guard, "subprocess", transport)
    yield mode, processes
    assert processes and all(process.poll() is not None for process in processes)


def test_transport_handshake_and_notifications(fake_server):
    assert guard.read_codex_limits() == {"rateLimits": {"test": True}}


@pytest.mark.parametrize("mode", ["error", "eof", "malformed", "timeout"])
def test_transport_errors_and_cleanup(fake_server, mode):
    fake_server[0][0] = mode
    with pytest.raises((ValueError, TimeoutError)):
        guard.read_codex_limits(timeout=0.3 if mode == "timeout" else 5)


def test_timeout_terminates_descendants_without_blocking_close(fake_server):
    fake_server[0][0] = "descendant"
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        guard.read_codex_limits(timeout=1)
    assert time.monotonic() - started < 8


@pytest.mark.parametrize("error", [ProcessLookupError(), PermissionError()])
def test_cleanup_skips_locked_pipe_and_tolerates_exited_group(monkeypatch, error):
    messages = guard.queue.Queue()
    for request_id in (1, 2):
        messages.put(json.dumps({"id": request_id, "result": {}}))
    events = []
    stream = SimpleNamespace(close=lambda: pytest.fail("Must not close an active reader's pipe"))
    process = SimpleNamespace(
        pid=123, stdin=io.StringIO(), stdout=stream, poll=lambda: None,
        kill=lambda: events.append("kill"), wait=lambda **_: events.append("wait"))
    reader = SimpleNamespace(start=lambda: None, join=lambda **_: None, is_alive=lambda: True)
    transport = SimpleNamespace(**vars(subprocess))
    transport.Popen = lambda *_, **__: process

    def killpg(pid: int, sig: int) -> None:
        assert pid == 123
        raise error

    monkeypatch.setattr(guard, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(guard, "signal", SimpleNamespace(SIGKILL=9))
    monkeypatch.setattr(guard, "subprocess", transport)
    monkeypatch.setattr(guard, "threading", SimpleNamespace(Thread=lambda **_: reader))
    monkeypatch.setattr(guard, "queue", SimpleNamespace(Queue=lambda: messages))
    monkeypatch.setattr(guard.os, "killpg", killpg, raising=False)
    monkeypatch.setattr(guard.shutil, "which", lambda _: "fake-codex")
    assert guard.read_codex_limits() == {}
    assert events == ["kill", "wait"]
    assert process.stdin.closed


@pytest.mark.parametrize("state,code", [("READY", 0), ("PAUSED_QUOTA", 10), ("UNKNOWN", 20)])
def test_codex_cli_contract(tmp_path, monkeypatch, capsys, state, code):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "check", "--provider", "codex",
                                      "--state-dir", str(tmp_path)])
    monkeypatch.setattr(guard, "read_codex_limits", lambda: snapshot(
        96 if state == "PAUSED_QUOTA" else 4))
    monkeypatch.setattr(guard.time, "time", lambda: NOW if state != "UNKNOWN" else NOW + 60000)
    monkeypatch.setattr(guard, "configure", lambda *_: pytest.fail("Codex must not configure Claude"))
    assert guard.main() == code
    assert json.loads(capsys.readouterr().out)["state"] == state


def test_explicit_claude_state_path_is_preserved_for_codex(monkeypatch, capsys):
    root = Path.home() / ".claude" / "quota-guard"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "check", "--provider", "codex",
                                      "--state-dir", str(root)])

    def check(state_dir: Path, now: float, threshold: float) -> dict:
        assert state_dir == root
        return {"state": "READY"}

    monkeypatch.setattr(guard, "check_codex", check)
    assert guard.main() == 0
    assert json.loads(capsys.readouterr().out)["state"] == "READY"


@pytest.mark.parametrize("returncode", [0, 1])
def test_wake_always_fails_precheck(monkeypatch, capsys, returncode):
    monkeypatch.delenv("ORCA_CLI_COMMAND", raising=False)
    executable = str(Path.cwd() / "custom-orca")
    calls = []

    def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, returncode)

    monkeypatch.setattr(guard.subprocess, "run", run)
    text = 'Resume quota-guard:op; checkpoint "C:/notes/a b.md"; check --provider codex; READY only'
    assert guard.wake("term_123", text, executable) == 1
    assert json.loads(capsys.readouterr().out) == {"sent": returncode == 0}
    assert calls[0][0] == [executable, "terminal", "send", "--terminal", "term_123",
                           "--text", text, "--enter"]
    assert calls[0][1]["timeout"] == 30
    assert calls[0][1]["stdout"] == subprocess.DEVNULL
    assert calls[0][1]["stderr"] == subprocess.DEVNULL


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("orca", 30)])
def test_wake_send_failure_still_skips_agent(monkeypatch, capsys, error):
    def run(*args, **kwargs) -> None:
        raise error
    monkeypatch.setattr(guard.subprocess, "run", run)
    assert guard.wake("term_123", "resume", "custom-orca") == 1
    assert json.loads(capsys.readouterr().out) == {"sent": False}
