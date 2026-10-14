"""Codex live transport and Orca wake regression tests using local fixtures only."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

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
    monkeypatch.setattr(guard, "read_codex_limits", lambda: snapshot(96 if secondary == 100 else 4, secondary))
    result = guard.check_codex(tmp_path, NOW)
    assert result["state"] == state
    if secondary == 100:
        assert result["reason"] == "secondary_exhausted"
        assert result["wake_at"] >= NOW + 50120


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
    script.write_text('''import json, sys, time
mode = sys.argv[1]
first = json.loads(sys.stdin.readline())
assert first['method'] == 'initialize'
assert first['params']['clientInfo']['name'] == 'quota_guard'
if mode == 'timeout':
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
    monkeypatch.setattr(guard.subprocess, "Popen", start)
    # The fixture launches Python directly, so no Windows npm shim needs taskkill.
    monkeypatch.setattr(guard.sys, "platform", "linux")
    yield mode, processes
    assert processes and all(process.poll() is not None for process in processes)


def test_transport_handshake_and_notifications(fake_server):
    assert guard.read_codex_limits() == {"rateLimits": {"test": True}}


@pytest.mark.parametrize("mode", ["error", "eof", "malformed", "timeout"])
def test_transport_errors_and_cleanup(fake_server, mode):
    fake_server[0][0] = mode
    with pytest.raises((ValueError, TimeoutError)):
        guard.read_codex_limits(timeout=0.3 if mode == "timeout" else 5)


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


@pytest.mark.parametrize("returncode", [0, 1])
def test_wake_always_fails_precheck(monkeypatch, capsys, returncode):
    monkeypatch.setenv("ORCA_CLI_COMMAND", "custom-orca")
    monkeypatch.setattr(guard.shutil, "which", lambda command: command)
    calls = []

    def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, returncode)

    monkeypatch.setattr(guard.subprocess, "run", run)
    text = 'Resume quota-guard:op; checkpoint "C:/notes/a b.md"; check --provider codex; READY only'
    assert guard.wake("term_123", text) == 1
    assert json.loads(capsys.readouterr().out) == {"sent": returncode == 0}
    assert calls[0][0] == ["custom-orca", "terminal", "send", "--terminal", "term_123",
                           "--text", text, "--enter"]
    assert calls[0][1]["timeout"] == 30


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("orca", 30)])
def test_wake_send_failure_still_skips_agent(monkeypatch, capsys, error):
    def run(*args, **kwargs) -> None:
        raise error
    monkeypatch.setattr(guard.subprocess, "run", run)
    assert guard.wake("term_123", "resume") == 1
    assert json.loads(capsys.readouterr().out) == {"sent": False}
