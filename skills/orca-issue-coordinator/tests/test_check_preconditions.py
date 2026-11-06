"""Tests for check_preconditions.py, using a fake command runner.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_preconditions.py"
CHECKOUT = "/home/user/repos/agent-skills"
ORCA = os.path.abspath("/opt/orca/bin/orca")
AUTO_RELEASE = "orchestration.worker-auto-release.v1"
HEAD_SHA = "1234567890abcdef1234567890abcdef12345678"


def load_module():
    spec = importlib.util.spec_from_file_location("check_preconditions", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def status_json(reachable: bool = True, capabilities: list[str] | None = None) -> str:
    runtime = {"reachable": reachable,
               "capabilities": [AUTO_RELEASE] if capabilities is None else capabilities}
    return json.dumps({"ok": True, "result": {"runtime": runtime}})


@pytest.fixture
def cp(monkeypatch: pytest.MonkeyPatch):
    module = load_module()
    responses: dict[str, tuple[int, str]] = {
        "orca": (0, status_json()),
        "gh": (0, "Logged in to github.com"),
        "rev-parse": (0, CHECKOUT),
        "rev-parse HEAD": (0, HEAD_SHA),
        "symbolic-ref": (0, "main"),
        "fetch": (0, ""),
        "rev-list": (0, "0 0"),
        "status": (0, ""),
        "codex": (0, "codex-cli 0.162.1"),
    }
    calls: list[list[str]] = []

    def fake_run(cmd: list[str]) -> tuple[int, str]:
        calls.append(cmd)
        # git commands are keyed by subcommand: git -C <dir> <subcommand> ...
        if cmd[0] == "git":
            return responses["rev-parse HEAD" if cmd[3:] == ["rev-parse", "HEAD"] else cmd[3]]
        return responses["orca" if cmd[0] == ORCA else cmd[0]]

    executables = {"orca": ORCA}
    monkeypatch.setattr(module.shutil, "which", executables.get)
    monkeypatch.setattr(module, "run", fake_run)
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_test")
    module.responses = responses
    module.calls = calls
    module.executables = executables
    return module


def claude(*extra: str) -> list[str]:
    return ["--agent", "claude", "--orca", "orca", *extra]


def codex() -> list[str]:
    return ["--agent", "codex", "--orca", "orca"]


def test_all_checks_pass(cp, capsys: pytest.CaptureFixture[str]) -> None:
    assert cp.main(claude()) == 0
    assert capsys.readouterr().out.splitlines() == [
        "preconditions: ok",
        f"skill-checkout: {CHECKOUT}",
        f"orca-executable: {ORCA}",
    ]
    assert [ORCA, "status", "--json"] in cp.calls
    assert ["gh", "auth", "status"] in cp.calls
    assert ["git", "-C", str(cp.SKILL_DIR), "rev-parse", "--show-toplevel"] in cp.calls
    assert ["git", "-C", CHECKOUT, "symbolic-ref", "-q", "--short", "HEAD"] in cp.calls
    assert ["git", "-C", CHECKOUT, "fetch", "--quiet", "origin",
            "+refs/heads/main:refs/remotes/origin/main"] in cp.calls
    assert ["git", "-C", CHECKOUT, "rev-list", "--left-right", "--count",
            "HEAD...origin/main"] in cp.calls
    assert ["git", "-C", CHECKOUT, "status", "--porcelain", "--",
            str(cp.SKILL_DIR.parent)] in cp.calls


def test_skill_dir_is_the_resolved_script_parent(cp) -> None:
    assert cp.SKILL_DIR == SCRIPT.parents[1]


@pytest.mark.parametrize("counts, expected", [
    ("0 3", "is 3 commit(s) behind origin/main,"),
    ("2 0", "has 2 commit(s) not on origin/main,"),
    ("1 4", "is 4 commit(s) behind origin/main and has 1 commit(s) not on origin/main,"),
])
def test_stale_skill_checkout_stops(cp, capsys: pytest.CaptureFixture[str],
                                    counts: str, expected: str) -> None:
    cp.responses["rev-list"] = (0, counts)
    assert cp.main(claude()) == 1
    out = capsys.readouterr().out
    assert f"STOP: the skill checkout {CHECKOUT} {expected}" in out
    assert "stale skills" in out


def test_uncommitted_skill_changes_stop(cp, capsys: pytest.CaptureFixture[str]) -> None:
    cp.responses["status"] = (0, " M skills/example/SKILL.md")
    assert cp.main(claude()) == 1
    assert (f"STOP: the skill checkout {CHECKOUT} has uncommitted changes under its skills,"
            in capsys.readouterr().out)


def test_detached_skill_checkout_stops_with_restore_command(
        cp, capsys: pytest.CaptureFixture[str]) -> None:
    cp.responses["symbolic-ref"] = (1, "")
    assert cp.main(claude()) == 1
    out = capsys.readouterr().out
    assert f"STOP: the skill checkout {CHECKOUT} is detached at {HEAD_SHA};" in out
    assert ("`uv run --no-project ~/.agents/skills/orca-issue-coordinator/scripts/local_main.py "
            f"finish --frozen {HEAD_SHA} --repo {CHECKOUT}`") in out
    assert not any(cmd[3] == "fetch" for cmd in cp.calls if cmd[0] == "git")


def test_skill_checkout_on_other_branch_stops(cp, capsys: pytest.CaptureFixture[str]) -> None:
    cp.responses["symbolic-ref"] = (0, "topic")
    assert cp.main(claude()) == 1
    out = capsys.readouterr().out
    assert f"STOP: the skill checkout {CHECKOUT} is on branch `topic`, not `main`;" in out
    assert "switch it to `main`" in out


@pytest.mark.parametrize("key, response, expected", [
    ("rev-parse", (128, "fatal: not a git repository"), "is not inside a git checkout (exit 128)"),
    ("symbolic-ref", (128, "fatal: bad HEAD"), "`git symbolic-ref HEAD` failed"),
    ("fetch", (128, "fatal: could not read from remote"),
     f"`git fetch origin main` failed in the skill checkout {CHECKOUT} (exit 128)"),
    ("rev-list", (128, "fatal: bad revision"), "cannot compare the skill checkout"),
    ("rev-list", (0, "garbage"), "cannot compare the skill checkout"),
    ("status", (128, "fatal: bad pathspec"), "`git status` failed in the skill checkout"),
])
def test_unverifiable_skill_checkout_stops(cp, capsys: pytest.CaptureFixture[str], key: str,
                                           response: tuple[int, str], expected: str) -> None:
    cp.responses[key] = response
    assert cp.main(claude()) == 1
    assert expected in capsys.readouterr().out


def test_outside_orca_terminal_stops(cp, monkeypatch: pytest.MonkeyPatch,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("ORCA_TERMINAL_HANDLE")
    assert cp.main(claude()) == 1
    out = capsys.readouterr().out
    assert "STOP: not running inside an Orca terminal" in out
    assert "Do not work around it." in out


def test_blank_terminal_handle_stops(cp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "  ")
    assert cp.main(claude()) == 1


@pytest.mark.parametrize("response, expected", [
    ((1, "connection refused"), f"`{ORCA} status --json` failed (exit 1)"),
    ((127, "orca: command not found"), f"`{ORCA} status --json` failed (exit 127)"),
    ((0, "not json"), "unexpected output"),
    ((0, json.dumps({"ok": True, "result": {"runtime": []}})), "unexpected output"),
    ((0, status_json(reachable=False)), "Orca runtime is not reachable"),
])
def test_orca_runtime_failure_stops(cp, capsys: pytest.CaptureFixture[str],
                                    response: tuple[int, str], expected: str) -> None:
    cp.responses["orca"] = response
    assert cp.main(claude()) == 1
    assert expected in capsys.readouterr().out


def test_gh_auth_failure_stops(cp, capsys: pytest.CaptureFixture[str]) -> None:
    cp.responses["gh"] = (1, "HTTP 401: Bad credentials")
    assert cp.main(claude()) == 1
    out = capsys.readouterr().out
    assert "STOP: `gh auth status` failed (exit 1): HTTP 401: Bad credentials" in out


def test_reports_every_failure(cp, monkeypatch: pytest.MonkeyPatch,
                               capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("ORCA_TERMINAL_HANDLE")
    cp.responses["gh"] = (1, "not logged in")
    assert cp.main(claude()) == 1
    assert capsys.readouterr().out.count("STOP:") == 2


@pytest.fixture
def codex_home(cp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    return tmp_path


def write_version(home: Path, latest: str, dismissed: str | None = None) -> None:
    info = {"latest_version": latest, "last_checked_at": "2026-10-16T00:00:00Z",
            "dismissed_version": dismissed}
    (home / "version.json").write_text(json.dumps(info), encoding="utf-8")


def test_codex_pending_update_prompt_stops(cp, codex_home: Path,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    write_version(codex_home, "0.163.0")
    assert cp.main(codex()) == 1
    out = capsys.readouterr().out
    assert ("STOP: Codex 0.162.1 will show an update prompt for 0.163.0 when a worker starts"
            in out)
    assert "agent-update-prompt" in out
    assert ["codex", "--version"] in cp.calls


def test_claude_agent_skips_codex_check(cp, codex_home: Path) -> None:
    write_version(codex_home, "0.163.0")
    assert cp.main(claude()) == 0
    assert ["codex", "--version"] not in cp.calls


def test_agent_is_required(cp) -> None:
    with pytest.raises(SystemExit):
        cp.main([])


@pytest.mark.parametrize("latest, dismissed", [
    ("0.163.0", "0.163.0"),  # dismissed with "skip this version"
    ("0.162.1", None),  # already up to date
    ("0.161.0", None),  # cache older than the installed version
    ("0.164.0-alpha.1", None),  # pre-releases are not offered
])
def test_codex_without_update_prompt_passes(cp, codex_home: Path, latest: str,
                                            dismissed: str | None) -> None:
    write_version(codex_home, latest, dismissed)
    assert cp.main(codex()) == 0


def test_codex_source_build_passes(cp, codex_home: Path) -> None:
    write_version(codex_home, "0.163.0")
    cp.responses["codex"] = (0, "codex-cli 0.0.0")
    assert cp.main(codex()) == 0


@pytest.mark.parametrize("content", [
    None, "not json", "{}", "[]", '{"latest_version": 1}',
    # Codex rejects a cache without a valid RFC 3339 last_checked_at.
    '{"latest_version": "0.163.0"}',
    '{"latest_version": "0.163.0", "last_checked_at": "2026-10-16"}',
    '{"latest_version": "0.163.0", "last_checked_at": "yesterday"}',
    '{"latest_version": "0.163.0", "last_checked_at": "2026-10-16T00:00:00Z",'
    ' "dismissed_version": 1}',
])
def test_codex_without_cached_latest_version_passes(cp, codex_home: Path,
                                                    content: str | None) -> None:
    if content is not None:
        (codex_home / "version.json").write_text(content, encoding="utf-8")
    assert cp.main(codex()) == 0
    assert ["codex", "--version"] not in cp.calls


def test_codex_update_check_disabled_in_config_passes(cp, codex_home: Path) -> None:
    write_version(codex_home, "0.163.0")
    (codex_home / "config.toml").write_text("check_for_update_on_startup = false\n",
                                            encoding="utf-8")
    assert cp.main(codex()) == 0


def test_codex_version_failure_stops(cp, codex_home: Path,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    write_version(codex_home, "0.163.0")
    cp.responses["codex"] = (127, "codex: command not found")
    assert cp.main(codex()) == 1
    assert "STOP: `codex --version` failed (exit 127)" in capsys.readouterr().out


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_real_checkout_compares_with_fetched_main(tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module()
    remote, checkout, other = tmp_path / "remote.git", tmp_path / "checkout", tmp_path / "other"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True)
    git(other, "config", "user.email", "test@example.com")
    git(other, "config", "user.name", "test")
    skill_md = Path("skills") / "example" / "SKILL.md"
    (other / skill_md).parent.mkdir(parents=True)
    (other / skill_md).write_text("v1", encoding="utf-8")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "v1")
    git(other, "push", "-q", "origin", "HEAD:main")
    subprocess.run(["git", "clone", "-q", str(remote), str(checkout)], check=True)
    monkeypatch.setattr(module, "SKILL_DIR", checkout / skill_md.parent)
    assert module.check_skill_checkout()[1] is None

    # A fetch refspec that does not track main must not hide a newer remote main.
    git(checkout, "config", "remote.origin.fetch", "+refs/heads/topic:refs/remotes/origin/topic")
    (other / skill_md).write_text("v2", encoding="utf-8")
    git(other, "commit", "-q", "-am", "v2")
    git(other, "push", "-q", "origin", "HEAD:main")
    assert "is 1 commit(s) behind origin/main" in module.check_skill_checkout()[1]

    git(checkout, "merge", "-q", "--ff-only", "origin/main")
    assert module.check_skill_checkout()[1] is None
    git(checkout, "switch", "-q", "--detach")
    assert "is detached at " in module.check_skill_checkout()[1]
    git(checkout, "switch", "-q", "-c", "topic")
    assert "is on branch `topic`, not `main`" in module.check_skill_checkout()[1]
    git(checkout, "switch", "-q", "main")
    (checkout / skill_md).write_text("stale", encoding="utf-8")
    assert "has uncommitted changes under its skills" in module.check_skill_checkout()[1]


@pytest.mark.parametrize("capabilities", [[], ["orchestration.worker-keep-open.v1"]])
def test_runtime_without_auto_release_stops(cp, capsys: pytest.CaptureFixture[str],
                                            capabilities: list[str]) -> None:
    cp.responses["orca"] = (0, status_json(capabilities=capabilities))
    assert cp.main(claude()) == 1
    out = capsys.readouterr().out
    assert f"STOP: the Orca runtime does not advertise {AUTO_RELEASE}" in out
    assert "update Orca" in out


def test_runtime_status_without_capabilities_stops(cp) -> None:
    cp.responses["orca"] = (0, json.dumps({"ok": True, "result": {"runtime": {
        "reachable": True}}}))
    assert cp.main(claude()) == 1


def test_orca_is_required(cp) -> None:
    with pytest.raises(SystemExit):
        cp.main(["--agent", "claude"])


def test_unresolvable_orca_stops_without_fallback(cp, capsys: pytest.CaptureFixture[str]) -> None:
    assert cp.main(["--agent", "claude", "--orca", "orca-dev"]) == 1
    out = capsys.readouterr().out
    assert "STOP: the selected Orca executable `orca-dev` cannot be resolved" in out
    assert "do not fall back to another executable" in out
    assert not any(cmd[0] in ("orca", ORCA) for cmd in cp.calls)


def test_selected_orca_is_the_only_candidate(cp, capsys: pytest.CaptureFixture[str]) -> None:
    ide = os.path.abspath("/usr/local/bin/orca-ide")
    cp.executables["orca-ide"] = ide
    cp.responses[ide] = (0, status_json())
    assert cp.main(["--agent", "claude", "--orca", "orca-ide"]) == 0
    assert f"orca-executable: {ide}" in capsys.readouterr().out
    assert [ide, "status", "--json"] in cp.calls
    assert not any(cmd[0] in ("orca", ORCA) for cmd in cp.calls)


def test_resolve_orca_returns_absolute_path_of_a_real_file(tmp_path: Path) -> None:
    module = load_module()
    windows = sys.platform == "win32"
    exe = tmp_path / ("orca-test.cmd" if windows else "orca-test")
    exe.write_text("@echo off" if windows else "#!/bin/sh", encoding="utf-8")
    exe.chmod(0o755)
    resolved, failure = module.resolve_orca(str(exe))
    assert failure is None
    assert os.path.isabs(resolved)
    assert Path(resolved).samefile(exe)
    assert module.resolve_orca(str(tmp_path / "missing"))[0] is None
