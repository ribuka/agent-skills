"""Regression tests; all fixtures are local, never configure real Claude settings."""
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "quota_guard.py"
spec = importlib.util.spec_from_file_location("quota_guard", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def payload(session, used, reset):
    return {"session_id": session, "rate_limits": {
        "five_hour": {"used_percentage": used, "resets_at": reset}}}


def previous_path(settings):
    command = guard.read_json(settings)["statusLine"]["command"]
    tokens = shlex.split(command)
    return Path(tokens[tokens.index("--previous-config") + 1])


@pytest.mark.parametrize("offset", [-120, -1, 0, 1, 120])
@pytest.mark.parametrize("same_session", [False, True])
def test_high_usage_survives_reset_jitter(tmp_path, offset, same_session):
    guard.record(tmp_path, payload("a", 42, 1800005000), 1800001000)
    guard.record(tmp_path, payload("a" if same_session else "b", 96,
                                   1800005000 + offset), 1800001001)
    result = guard.check(tmp_path, 1800001002)
    assert result["state"] == "PAUSED_QUOTA"
    assert result["used_percentage"] == 96
    assert result["resets_at"] == max(1800005000, 1800005000 + offset)
    assert result["wake_at"] >= result["resets_at"] + 120


def test_expired_nearby_high_still_blocks(tmp_path):
    guard.record(tmp_path, payload("a", 96, 1800005000), 1800004900)
    guard.record(tmp_path, payload("b", 42, 1800005001), 1800004999)
    assert guard.check(tmp_path, 1800005000)["state"] == "PAUSED_QUOTA"
    assert guard.check(tmp_path, 1800005121)["state"] == "UNKNOWN"


@pytest.mark.parametrize("same_session", [False, True])
def test_distinct_new_window_supersedes_high(tmp_path, same_session):
    guard.record(tmp_path, payload("a", 96, 1800005000), 1800001000)
    guard.record(tmp_path, payload("a" if same_session else "b", 42, 1800005121), 1800001001)
    assert guard.check(tmp_path, 1800001002)["state"] == "READY"
    assert guard.check(tmp_path, 1800001200)["state"] == "UNKNOWN"


def test_timer_repeat_does_not_refresh_low_evidence(tmp_path):
    item = payload("a", 42, 1800005000)
    guard.record(tmp_path, item, 1800001000)
    guard.record(tmp_path, item, 1800001500)
    assert guard.check(tmp_path, 1800001500)["state"] == "UNKNOWN"


def test_high_latches_and_older_window_cannot_regress(tmp_path):
    guard.record(tmp_path, payload("a", 96, 1800005000), 1800001000)
    guard.record(tmp_path, payload("a", 42, 1800004999), 1800001001)
    guard.record(tmp_path, payload("a", 10, 1800004000), 1800001002)
    assert guard.check(tmp_path, 1800001500)["state"] == "PAUSED_QUOTA"


def test_settings_scopes_preserve_independent_commands(tmp_path):
    root = tmp_path / "state"
    user, project = tmp_path / "user.json", tmp_path / "project.json"
    for settings, label in [(user, "USER"), (project, "PROJECT")]:
        guard.atomic_json(settings, {"other": 123, "statusLine": {
            "type": "command", "command": f"printf '{label}'", "padding": 2}})
        guard.configure(root, settings)
    assert previous_path(user) != previous_path(project)
    assert guard.render_previous(previous_path(user), "{}") == "USER"
    assert guard.render_previous(previous_path(project), "{}") == "PROJECT"
    assert guard.read_json(user)["other"] == 123
    assert guard.read_json(user)["statusLine"]["padding"] == 2
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert guard.configure(root, user)["changed"] is False
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_legacy_wrapper_migrates_referenced_backup(tmp_path):
    legacy = tmp_path / "previous-statusline.json"
    guard.atomic_json(legacy, {"type": "command", "command": "printf 'OLD'"})
    settings = tmp_path / "settings.json"
    guard.atomic_json(settings, {"statusLine": {"type": "command", "command":
        f'python quota_guard.py statusline --previous-config {guard.quote_command(legacy)}'}})
    assert guard.configure(tmp_path, settings)["changed"] is True
    assert previous_path(settings) != legacy
    assert guard.render_previous(previous_path(settings), "{}") == "OLD"
    assert guard.configure(tmp_path, settings)["changed"] is False


def test_missing_legacy_backup_leaves_settings_unchanged(tmp_path):
    settings = tmp_path / "settings.json"
    guard.atomic_json(settings, {"statusLine": {"type": "command", "command":
        f'python quota_guard.py statusline --previous-config {guard.quote_command(tmp_path / "missing.json")}'}})
    before = settings.read_bytes()
    with pytest.raises(OSError):
        guard.configure(tmp_path, settings)
    assert settings.read_bytes() == before


def test_posix_shell_preserves_stdin_and_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("QUOTA_GUARD_TEST", "forwarded")
    previous = tmp_path / "previous.json"
    guard.atomic_json(previous, {"command":
        'case "${QUOTA_GUARD_TEST-}" in forwarded) printf "POSIX:"; cat ;; *) exit 1 ;; esac'})
    raw = '{"value":"日本語"}'
    assert guard.render_previous(previous, raw) == "POSIX:" + raw


@pytest.mark.parametrize("value", [[], None, "invalid", 123])
def test_invalid_previous_json_does_not_break_quota_line(tmp_path, value):
    previous = tmp_path / "previous.json"
    guard.atomic_json(previous, value)
    result = subprocess.run([sys.executable, str(SCRIPT), "statusline",
                             "--state-dir", str(tmp_path / "state"),
                             "--previous-config", str(previous)], input=json.dumps(payload("a", 42, time.time() + 5000)),
                            text=True, capture_output=True, encoding="utf-8")
    assert result.returncode == 0
    assert "[previous statusLine unavailable]" in result.stdout
    assert "5h 42% READY" in result.stdout
    assert "telemetry write failed" not in result.stdout


def test_explicit_git_bash_path_has_precedence(tmp_path, monkeypatch):
    bash = tmp_path / "bash.exe"
    bash.touch()
    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", str(bash))
    assert guard.git_bash() == str(bash)
    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", str(tmp_path / "absent.exe"))
    with pytest.raises(FileNotFoundError):
        guard.git_bash()


def test_windows_shell_uses_hidden_process(tmp_path, monkeypatch):
    previous = tmp_path / "previous.json"
    guard.atomic_json(previous, {"command": "printf 'ok'"})
    monkeypatch.setattr(guard.sys, "platform", "win32")
    monkeypatch.setattr(guard, "git_bash", lambda: "git-bash.exe")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "ok\n", "")

    monkeypatch.setattr(guard.subprocess, "run", run)
    assert guard.render_previous(previous, "raw") == "ok"
    assert calls[0][0] == ["git-bash.exe", "-c", "printf 'ok'"]
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["input"] == "raw"
    assert calls[0][1]["creationflags"] == 0x08000000


@pytest.mark.parametrize("used", [None, 42, 96])
def test_check_reports_checkpoint_dir(tmp_path, used):
    if used is not None:
        guard.record(tmp_path, payload("a", used, 1800005000), 1800001000)
    result = guard.check(tmp_path, 1800001002)
    assert result["checkpoint_dir"] == str(tmp_path / "checkpoints")


def test_unknown_reports_local_retry_wait(tmp_path):
    result = guard.check(tmp_path, 1800001002)
    assert result["state"] == "UNKNOWN"
    assert result["local_retry_seconds"] == guard.LOCAL_RETRY_SECONDS
    assert "cron" in result


def run_clear(state, operation, provider="claude"):
    result = subprocess.run([sys.executable, str(SCRIPT), "clear-checkpoint",
                             "--provider", provider, "--state-dir", str(state),
                             f"--operation={operation}"],
                            text=True, capture_output=True, encoding="utf-8")
    return result.returncode, json.loads(result.stdout)


def test_clear_checkpoint_deletes_only_that_operation(tmp_path):
    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir()
    (checkpoints / "run_a.md").write_text("a", encoding="utf-8")
    (checkpoints / "run_b.md").write_text("b", encoding="utf-8")
    code, result = run_clear(tmp_path, "run_a")
    assert (code, result) == (0, {"removed": True, "path": str(checkpoints / "run_a.md")})
    assert not (checkpoints / "run_a.md").exists()
    assert (checkpoints / "run_b.md").is_file()
    assert run_clear(tmp_path, "run_a", "codex") == (
        0, {"removed": False, "path": str(checkpoints / "run_a.md")})


@pytest.mark.parametrize("operation", ["", ".", "..", "../run_a", "a/b", "a\b", "-x", "*"])
def test_clear_checkpoint_refuses_invalid_operation(tmp_path, operation):
    (tmp_path / "run_a.md").write_text("a", encoding="utf-8")
    code, result = run_clear(tmp_path / "state", operation)
    assert code == 2
    assert result["removed"] is False
    assert (tmp_path / "run_a.md").is_file()


def test_clear_checkpoint_reports_failure(tmp_path):
    (tmp_path / "checkpoints" / "run_dir.md").mkdir(parents=True)
    code, result = guard.clear_checkpoint(tmp_path, "run_dir")
    assert code == 1
    assert result["removed"] is False
    assert result["reason"]
    assert (tmp_path / "checkpoints" / "run_dir.md").is_dir()


def test_clear_checkpoint_default_state_dir_follows_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(guard.Path, "home", classmethod(lambda cls: tmp_path))
    for provider, home in (("claude", ".claude"), ("codex", ".codex")):
        path = tmp_path / home / "quota-guard" / "checkpoints" / "run_a.md"
        path.parent.mkdir(parents=True)
        path.write_text("a", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["quota_guard.py", "clear-checkpoint",
                                          "--provider", provider, "--operation", "run_a"])
        assert guard.main() == 0
        assert not path.exists()
