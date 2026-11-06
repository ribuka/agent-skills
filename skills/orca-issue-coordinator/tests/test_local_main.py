"""Tests for local_main.py, using real git repositories in a temporary directory.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "local_main.py"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def load_module():
    spec = importlib.util.spec_from_file_location("local_main", SCRIPT)
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
    (checkout / "skills" / "example").mkdir(parents=True)
    monkeypatch.setattr(module, "SKILL_DIR", checkout / "skills" / "example")
    module.checkout, module.pusher, module.tmp = checkout, pusher, tmp_path
    return module


def out_lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return capsys.readouterr().out.splitlines()


def branch(repo: Path) -> str:
    return git(repo, "branch", "--show-current")


def test_freeze_same_repo_detaches_at_head(env, capsys: pytest.CaptureFixture[str]) -> None:
    head = git(env.checkout, "rev-parse", "HEAD")
    assert env.main(["freeze", "--repo", str(env.checkout)]) == 0
    assert out_lines(capsys) == [f"skill-checkout-frozen: {head}"]
    assert branch(env.checkout) == ""
    assert git(env.checkout, "rev-parse", "HEAD") == head


def test_freeze_from_another_worktree_of_same_repo(env,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    worktree = env.tmp / "worktree"
    git(env.checkout, "worktree", "add", "-q", "-b", "topic", str(worktree))
    assert env.main(["freeze", "--repo", str(worktree)]) == 0
    assert out_lines(capsys)[0].startswith("skill-checkout-frozen: ")
    assert branch(env.checkout) == ""
    assert branch(worktree) == "topic"


def test_freeze_other_repo_changes_nothing(env, capsys: pytest.CaptureFixture[str]) -> None:
    remote, _ = make_remote(env.tmp, "other")
    other = env.tmp / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True)
    assert env.main(["freeze", "--repo", str(other)]) == 0
    assert out_lines(capsys) == ["skill-checkout-frozen: no"]
    assert branch(env.checkout) == "main"


def test_freeze_already_detached_fails(env, capsys: pytest.CaptureFixture[str]) -> None:
    git(env.checkout, "switch", "-q", "--detach")
    assert env.main(["freeze", "--repo", str(env.checkout)]) == 1
    assert out_lines(capsys)[0].startswith("error: the skill checkout ")


def test_finish_restores_frozen_checkout_and_fast_forwards(
        env, capsys: pytest.CaptureFixture[str]) -> None:
    assert env.main(["freeze", "--repo", str(env.checkout)]) == 0
    frozen = out_lines(capsys)[0].split(": ", 1)[1]
    new = push_new_commit(env.pusher, "v2")
    assert env.main(["finish", "--frozen", frozen, "--repo", str(env.checkout)]) == 0
    assert out_lines(capsys) == ["local-main: updated", f"local-main-head: {new}"]
    assert branch(env.checkout) == "main"
    assert git(env.checkout, "rev-parse", "HEAD") == new
    assert (env.checkout / "file.txt").read_text(encoding="utf-8") == "v2"


def test_finish_sha_mismatch_changes_nothing(env, capsys: pytest.CaptureFixture[str]) -> None:
    head = git(env.checkout, "rev-parse", "HEAD")
    push_new_commit(env.pusher, "v2")
    # Not detached.
    assert env.main(["finish", "--frozen", head, "--repo", str(env.checkout)]) == 2
    assert out_lines(capsys) == [f"error: the skill checkout is not detached at {head}"]
    # Detached at another commit.
    git(env.checkout, "switch", "-q", "--detach")
    other = "0" * 40
    assert env.main(["finish", "--frozen", other, "--repo", str(env.checkout)]) == 2
    assert out_lines(capsys) == [f"error: the skill checkout is not detached at {other}"]
    assert branch(env.checkout) == ""
    assert git(env.checkout, "rev-parse", "refs/heads/main") == head


def test_finish_merges_in_clean_checked_out_worktree(env,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    new = push_new_commit(env.pusher, "v2")
    assert env.main(["finish", "--frozen", "no", "--repo", str(env.checkout)]) == 0
    assert out_lines(capsys) == ["local-main: updated", f"local-main-head: {new}"]
    assert git(env.checkout, "rev-parse", "HEAD") == new
    assert (env.checkout / "file.txt").read_text(encoding="utf-8") == "v2"


def test_finish_merges_in_the_worktree_that_has_main(env,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    worktree = env.tmp / "worktree"
    git(env.checkout, "worktree", "add", "-q", "-b", "topic", str(worktree))
    new = push_new_commit(env.pusher, "v2")
    assert env.main(["finish", "--frozen", "no", "--repo", str(worktree)]) == 0
    assert out_lines(capsys) == ["local-main: updated", f"local-main-head: {new}"]
    assert git(env.checkout, "rev-parse", "HEAD") == new
    assert (env.checkout / "file.txt").read_text(encoding="utf-8") == "v2"


def test_finish_updates_ref_when_not_checked_out(env, capsys: pytest.CaptureFixture[str]) -> None:
    git(env.checkout, "switch", "-q", "-c", "topic")
    new = push_new_commit(env.pusher, "v2")
    assert env.main(["finish", "--frozen", "no", "--repo", str(env.checkout)]) == 0
    assert out_lines(capsys) == ["local-main: updated", f"local-main-head: {new}"]
    assert git(env.checkout, "rev-parse", "refs/heads/main") == new
    assert branch(env.checkout) == "topic"
    assert "orca-issue-coordinator: fast-forward to origin/main" in git(
        env.checkout, "reflog", "-1", "--format=%gs", "refs/heads/main")


def test_finish_up_to_date(env, capsys: pytest.CaptureFixture[str]) -> None:
    head = git(env.checkout, "rev-parse", "HEAD")
    assert env.main(["finish", "--frozen", "no", "--repo", str(env.checkout)]) == 0
    assert out_lines(capsys) == ["local-main: up-to-date", f"local-main-head: {head}"]


def test_finish_skips_diverged_branch(env, capsys: pytest.CaptureFixture[str]) -> None:
    local = commit(env.checkout, "local")
    push_new_commit(env.pusher, "v2")
    assert env.main(["finish", "--frozen", "no", "--repo", str(env.checkout)]) == 0
    assert out_lines(capsys) == ["local-main: skipped (diverged)", f"local-main-head: {local}"]


def test_finish_skips_dirty_worktree(env, capsys: pytest.CaptureFixture[str]) -> None:
    head = git(env.checkout, "rev-parse", "HEAD")
    push_new_commit(env.pusher, "v2")
    (env.checkout / "file.txt").write_text("dirty", encoding="utf-8")
    assert env.main(["finish", "--frozen", "no", "--repo", str(env.checkout)]) == 0
    lines = out_lines(capsys)
    assert lines[0].startswith("local-main: skipped (dirty: ")
    assert Path(lines[0][len("local-main: skipped (dirty: "):-1]).samefile(env.checkout)
    assert lines[1] == f"local-main-head: {head}"
    assert git(env.checkout, "rev-parse", "HEAD") == head


def test_finish_ignores_untracked_files(env, capsys: pytest.CaptureFixture[str]) -> None:
    new = push_new_commit(env.pusher, "v2")
    (env.checkout / "untracked.txt").write_text("x", encoding="utf-8")
    assert env.main(["finish", "--frozen", "no", "--repo", str(env.checkout)]) == 0
    assert out_lines(capsys) == ["local-main: updated", f"local-main-head: {new}"]


def test_finish_without_origin_default_branch_fails(env,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    git(env.checkout, "remote", "remove", "origin")
    assert env.main(["finish", "--frozen", "no", "--repo", str(env.checkout)]) == 1
    assert out_lines(capsys)[0].startswith("error: ")


def test_finish_rejects_invalid_frozen_value(env) -> None:
    with pytest.raises(SystemExit):
        env.main(["finish", "--frozen", "abc123"])
