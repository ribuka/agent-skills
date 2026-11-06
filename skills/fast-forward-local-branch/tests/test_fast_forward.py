"""Tests for fast_forward.py, using real git repositories in a temporary directory.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fast_forward.py"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def load_module():
    spec = importlib.util.spec_from_file_location("fast_forward", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def commit(repo: Path, content: str) -> str:
    (repo / "file.txt").write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", content)
    return git(repo, "rev-parse", "HEAD")


def make_remote(tmp_path: Path, name: str) -> tuple[Path, Path]:
    """Create a bare origin with one commit on main and a clone used to push to it."""
    remote, pusher = tmp_path / f"{name}.git", tmp_path / f"{name}-pusher"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(pusher)], check=True,
                   capture_output=True)
    git(pusher, "switch", "-q", "-c", "main")
    commit(pusher, "v1")
    git(pusher, "push", "-q", "origin", "main")
    return remote, pusher


def push_new_commit(pusher: Path, content: str) -> str:
    sha = commit(pusher, content)
    git(pusher, "push", "-q", "origin", "main")
    return sha


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    global_config = tmp_path / "gitconfig"
    global_config.write_text("[user]\n\temail = test@example.com\n\tname = test\n"
                             "[commit]\n\tgpgsign = false\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    module = load_module()
    remote, pusher = make_remote(tmp_path, "skills")
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(remote), str(checkout)], check=True)
    module.checkout, module.pusher, module.tmp = checkout, pusher, tmp_path
    return module


def out_lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return capsys.readouterr().out.splitlines()


def branch(repo: Path) -> str:
    return git(repo, "branch", "--show-current")


@pytest.mark.parametrize("checkout", [True, False])
def test_updates_checked_out_or_unchecked_branch(env, capsys, checkout: bool) -> None:
    if not checkout:
        git(env.checkout, "switch", "-q", "-c", "topic")
    new = push_new_commit(env.pusher, "v2")
    assert env.main(["--repo", str(env.checkout), "--branch", "main"]) == 0
    assert out_lines(capsys) == ["local-branch: updated", f"local-branch-head: {new}"]
    assert branch(env.checkout) == ("main" if checkout else "topic")
    assert (env.checkout / "file.txt").read_text() == ("v2" if checkout else "v1")


def test_updates_branch_in_another_worktree(env, capsys) -> None:
    topic = env.tmp / "topic"
    git(env.checkout, "worktree", "add", "-q", "-b", "topic", str(topic))
    new = push_new_commit(env.pusher, "v2")
    assert env.main(["--repo", str(topic), "--branch", "main"]) == 0
    assert out_lines(capsys) == ["local-branch: updated", f"local-branch-head: {new}"]
    assert branch(topic) == "topic"
    assert (env.checkout / "file.txt").read_text() == "v2"
    assert (topic / "file.txt").read_text() == "v1"


@pytest.mark.parametrize("state", ["same", "ahead", "diverged", "dirty", "missing", "fetch", "untracked"])
def test_skips_and_errors_preserve_ref_and_files(env, capsys, state: str) -> None:
    if state in {"ahead", "diverged"}:
        commit(env.checkout, "local")
    if state in {"diverged", "dirty"}:
        push_new_commit(env.pusher, "v2")
    if state == "dirty":
        (env.checkout / "file.txt").write_text("dirty")
    if state == "missing":
        git(env.checkout, "switch", "-q", "-c", "topic")
        git(env.checkout, "branch", "-D", "main")
    if state == "fetch":
        git(env.checkout, "remote", "set-url", "origin", str(env.tmp / "absent.git"))
    if state == "untracked":
        (env.pusher / "collision.txt").write_text("remote")
        push_new_commit(env.pusher, "v2")
        (env.checkout / "collision.txt").write_text("local")
    old = None if state == "missing" else git(env.checkout, "rev-parse", "refs/heads/main")
    content = (env.checkout / "file.txt").read_bytes()
    assert env.main(["--repo", str(env.checkout), "--branch", "main"]) == (
        1 if state in {"fetch", "untracked"} else 0)
    lines = out_lines(capsys)
    if state in {"fetch", "untracked"}:
        assert lines[0].startswith("error: `git " + ("fetch" if state == "fetch" else "merge"))
    else:
        expected = {"same": "up-to-date", "ahead": "skipped (diverged)",
                    "diverged": "skipped (diverged)", "missing": "skipped (missing local branch)"}
        if state == "dirty":
            assert lines[0].startswith("local-branch: skipped (dirty: ")
        else:
            assert lines[0] == f"local-branch: {expected[state]}"
        assert lines[1:] == ([] if old is None else [f"local-branch-head: {old}"])
    if old is not None:
        assert git(env.checkout, "rev-parse", "refs/heads/main") == old
    else:
        assert "main" not in git(env.checkout, "branch", "--format=%(refname:short)").splitlines()
    assert (env.checkout / "file.txt").read_bytes() == content
    if state == "untracked":
        assert (env.checkout / "collision.txt").read_text() == "local"


