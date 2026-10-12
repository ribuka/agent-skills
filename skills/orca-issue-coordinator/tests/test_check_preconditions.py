"""Tests for check_preconditions.py, using a fake command runner.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_preconditions.py"
CHECKOUT = "/home/user/repos/agent-skills"


def load_module():
    spec = importlib.util.spec_from_file_location("check_preconditions", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def status_json(reachable: bool = True) -> str:
    return json.dumps({"ok": True, "result": {"runtime": {"reachable": reachable}}})


@pytest.fixture
def cp(monkeypatch: pytest.MonkeyPatch):
    module = load_module()
    responses: dict[str, tuple[int, str]] = {
        "orca": (0, status_json()),
        "gh": (0, "Logged in to github.com"),
        "rev-parse": (0, CHECKOUT),
        "fetch": (0, ""),
        "rev-list": (0, "0 0"),
        "status": (0, ""),
    }
    calls: list[list[str]] = []

    def fake_run(cmd: list[str]) -> tuple[int, str]:
        calls.append(cmd)
        # git commands are keyed by subcommand: git -C <dir> <subcommand> ...
        return responses[cmd[3] if cmd[0] == "git" else cmd[0]]

    monkeypatch.setattr(module, "run", fake_run)
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_test")
    module.responses = responses
    module.calls = calls
    return module


def test_all_checks_pass(cp, capsys: pytest.CaptureFixture[str]) -> None:
    assert cp.main() == 0
    assert capsys.readouterr().out.splitlines() == [
        "preconditions: ok",
        f"skill-checkout: {CHECKOUT}",
    ]
    assert ["orca", "status", "--json"] in cp.calls
    assert ["gh", "auth", "status"] in cp.calls
    assert ["git", "-C", str(cp.SKILL_DIR), "rev-parse", "--show-toplevel"] in cp.calls
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
    assert cp.main() == 1
    out = capsys.readouterr().out
    assert f"STOP: the skill checkout {CHECKOUT} {expected}" in out
    assert "stale skills" in out


def test_uncommitted_skill_changes_stop(cp, capsys: pytest.CaptureFixture[str]) -> None:
    cp.responses["status"] = (0, " M skills/example/SKILL.md")
    assert cp.main() == 1
    assert (f"STOP: the skill checkout {CHECKOUT} has uncommitted changes under its skills,"
            in capsys.readouterr().out)


@pytest.mark.parametrize("key, response, expected", [
    ("rev-parse", (128, "fatal: not a git repository"), "is not inside a git checkout (exit 128)"),
    ("fetch", (128, "fatal: could not read from remote"),
     f"`git fetch origin main` failed in the skill checkout {CHECKOUT} (exit 128)"),
    ("rev-list", (128, "fatal: bad revision"), "cannot compare the skill checkout"),
    ("rev-list", (0, "garbage"), "cannot compare the skill checkout"),
    ("status", (128, "fatal: bad pathspec"), "`git status` failed in the skill checkout"),
])
def test_unverifiable_skill_checkout_stops(cp, capsys: pytest.CaptureFixture[str], key: str,
                                           response: tuple[int, str], expected: str) -> None:
    cp.responses[key] = response
    assert cp.main() == 1
    assert expected in capsys.readouterr().out


def test_outside_orca_terminal_stops(cp, monkeypatch: pytest.MonkeyPatch,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("ORCA_TERMINAL_HANDLE")
    assert cp.main() == 1
    out = capsys.readouterr().out
    assert "STOP: not running inside an Orca terminal" in out
    assert "Do not work around it." in out


def test_blank_terminal_handle_stops(cp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "  ")
    assert cp.main() == 1


@pytest.mark.parametrize("response, expected", [
    ((1, "connection refused"), "`orca status --json` failed (exit 1)"),
    ((127, "orca: command not found"), "`orca status --json` failed (exit 127)"),
    ((0, "not json"), "unexpected output"),
    ((0, status_json(reachable=False)), "Orca runtime is not reachable"),
])
def test_orca_runtime_failure_stops(cp, capsys: pytest.CaptureFixture[str],
                                    response: tuple[int, str], expected: str) -> None:
    cp.responses["orca"] = response
    assert cp.main() == 1
    assert expected in capsys.readouterr().out


def test_gh_auth_failure_stops(cp, capsys: pytest.CaptureFixture[str]) -> None:
    cp.responses["gh"] = (1, "HTTP 401: Bad credentials")
    assert cp.main() == 1
    out = capsys.readouterr().out
    assert "STOP: `gh auth status` failed (exit 1): HTTP 401: Bad credentials" in out


def test_reports_every_failure(cp, monkeypatch: pytest.MonkeyPatch,
                               capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("ORCA_TERMINAL_HANDLE")
    cp.responses["gh"] = (1, "not logged in")
    assert cp.main() == 1
    assert capsys.readouterr().out.count("STOP:") == 2


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
    (checkout / skill_md).write_text("stale", encoding="utf-8")
    assert "has uncommitted changes under its skills" in module.check_skill_checkout()[1]
