"""Tests for detoxer's implement_issues.py (the detached coordinator).

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "implement_issues.py"

spec = importlib.util.spec_from_file_location("detoxer_implement_issues", SCRIPT)
implement_issues = importlib.util.module_from_spec(spec)
spec.loader.exec_module(implement_issues)

SETTINGS = {"CLAUDE_PERMISSION_MODE": "bypassPermissions", "CODEX_SANDBOX": "danger-full-access",
            "IMPLEMENT_TIMEOUT_SECONDS": "60"}
GIT = shutil.which("git")


def test_prompt_asks_for_standalone_unattended_run_and_result_line() -> None:
    prompt = implement_issues.build_prompt(42, "detoxer/issue-42")
    for phrase in ("#42", "`detoxer/issue-42`", "implement-review-merge skill",
                   "Standalone", "do not wait for an answer",
                   "`detoxer-result: merged <pull request URL>`",
                   "`detoxer-result: stopped <one-line reason>`"):
        assert phrase in prompt


def test_claude_command_reads_the_prompt_from_stdin() -> None:
    command = implement_issues.build_command("claude", "/bin/claude", SETTINGS, Path("last.txt"))
    assert command == ["/bin/claude", "-p", "--permission-mode", "bypassPermissions"]


def test_codex_command_full_access_has_no_network_override() -> None:
    command = implement_issues.build_command("codex", "/bin/codex", SETTINGS, Path("last.txt"))
    assert command == ["/bin/codex", "exec", "--sandbox", "danger-full-access",
                       "--output-last-message", "last.txt", "-"]


def test_codex_command_workspace_write_gets_network() -> None:
    settings = {**SETTINGS, "CODEX_SANDBOX": "workspace-write"}
    command = implement_issues.build_command("codex", "/bin/codex", settings, Path("last.txt"))
    assert command[1:4] == ["exec", "--sandbox", "workspace-write"]
    assert command[-3:] == ["-c", "sandbox_workspace_write.network_access=true", "-"]


@pytest.mark.parametrize(("text", "expected"), [
    ("done\ndetoxer-result: merged https://github.com/o/r/pull/7\n",
     ("merged", "https://github.com/o/r/pull/7")),
    ("detoxer-result: stopped first\nmore\ndetoxer-result: stopped CI failed  \n",
     ("stopped", "CI failed")),
    ("no result here", ("failed", "the session ended without a detoxer-result line")),
])
def test_parse_result_takes_the_last_result_line(text: str, expected: tuple[str, str]) -> None:
    assert implement_issues.parse_result(text) == expected


def _script(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "fake_agent.py"
    script.write_text("import os, sys, time\n" + body, encoding="utf-8")
    return script


def _prompt(tmp_path: Path, text: str = "") -> Path:
    path = tmp_path / "prompt.txt"
    path.write_text(text, encoding="utf-8")
    return path


def test_run_session_feeds_the_prompt_and_logs_output(tmp_path: Path) -> None:
    fake = _script(tmp_path, "print(sys.stdin.read().upper()); print('err', file=sys.stderr)\n"
                             "sys.exit(3)\n")
    prompt = _prompt(tmp_path, "line one <x> & \"q\"\nline two")
    log = tmp_path / "logs" / "session.log"
    assert implement_issues.run_session([sys.executable, str(fake)], tmp_path, prompt, log, 30) == 3
    text = log.read_text(encoding="utf-8")
    assert "LINE ONE <X> & \"Q\"\nLINE TWO" in text
    assert "err" in text


def test_run_session_kills_on_timeout(tmp_path: Path) -> None:
    fake = _script(tmp_path, "time.sleep(30)\n")
    assert implement_issues.run_session([sys.executable, str(fake)], tmp_path, _prompt(tmp_path),
                                        tmp_path / "session.log", 1) is None


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run([GIT, "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A clone on branch `work` whose origin (a local bare repository) has `main`."""
    if not GIT:
        pytest.skip("git not found")
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    (work / "README.md").write_text("x\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-q", "-m", "init")
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(tmp_path / "origin.git"))
    _git(work, "remote", "add", "origin", str(tmp_path / "origin.git"))
    _git(work, "switch", "-q", "-c", "work")
    return work


@pytest.fixture
def fake_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[int, str]:
    """Replace the agent with a script; the returned map sets each issue's final message."""
    outcomes: dict[int, str] = {}
    outcomes_file = tmp_path / "outcomes.json"
    fake = _script(tmp_path, "import json\n"
                             "open('ran-here.txt', 'w').write(os.getcwd())\n"
                             "prompt = sys.stdin.read()\n"
                             "issue = prompt.split('issue #', 1)[1].split(' ', 1)[0]\n"
                             "print(json.load(open(sys.argv[1]))[issue])\n")

    def build_command(agent: str, executable: str, settings: dict[str, str],
                      last_message: Path) -> list[str]:
        outcomes_file.write_text(json.dumps({str(k): v for k, v in outcomes.items()}),
                                 encoding="utf-8")
        return [sys.executable, str(fake), str(outcomes_file)]

    monkeypatch.setattr(implement_issues, "build_command", build_command)
    return outcomes


@pytest.fixture
def comments(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, str]]:
    posted: list[tuple[int, str]] = []

    def comment_on_issue(gh: str, repo: Path, issue: int, body_file: Path) -> bool:
        posted.append((issue, body_file.read_text(encoding="utf-8")))
        return True

    monkeypatch.setattr(implement_issues, "comment_on_issue", comment_on_issue)
    return posted


def _run_all(repo: Path, issues: list[int], run_dir: Path) -> list[tuple[int, str, str]]:
    return implement_issues.run_all("claude", "fake-claude", SETTINGS, GIT, "fake-gh", repo,
                                    "main", issues, run_dir)


def test_stops_at_first_unmerged_issue_and_comments_on_it(
        repo: Path, tmp_path: Path, fake_agent: dict[int, str],
        comments: list[tuple[int, str]]) -> None:
    fake_agent.update({1: "detoxer-result: merged https://pr/1",
                       2: "detoxer-result: stopped needs a decision",
                       3: "detoxer-result: merged https://pr/3"})
    run_dir = tmp_path / "run"
    results = _run_all(repo, [1, 2, 3], run_dir)
    assert results == [(1, "merged", "https://pr/1"), (2, "stopped", "needs a decision"),
                       (3, "not-started", "an earlier issue was not merged")]
    assert [issue for issue, _body in comments] == [2]
    assert "stopped - needs a decision" in comments[0][1]
    worktree = run_dir / "worktree"
    assert worktree.is_dir()
    assert Path((worktree / "ran-here.txt").read_text(encoding="utf-8")) == worktree
    assert _git(repo, "branch", "--show-current") == "work"
    assert "detoxer/issue-3" not in _git(repo, "branch", "--list", "detoxer/*")
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    for line in ("- #1: merged https://pr/1", "- #2: stopped needs a decision",
                 "- #3: not-started an earlier issue was not merged", "(kept for inspection)"):
        assert line in summary


def test_all_merged_removes_the_worktree(repo: Path, tmp_path: Path, fake_agent: dict[int, str],
                                         comments: list[tuple[int, str]]) -> None:
    fake_agent.update({1: "detoxer-result: merged https://pr/1",
                       2: "detoxer-result: merged https://pr/2"})
    run_dir = tmp_path / "run"
    assert [r for _i, r, _d in _run_all(repo, [1, 2], run_dir)] == ["merged", "merged"]
    assert not (run_dir / "worktree").exists()
    assert comments == []
    assert "(removed)" in (run_dir / "summary.md").read_text(encoding="utf-8")
    assert _git(repo, "branch", "--list", "detoxer/*").split() == ["detoxer/issue-1",
                                                                     "detoxer/issue-2"]


def test_existing_branch_fails_the_issue(repo: Path, tmp_path: Path, fake_agent: dict[int, str],
                                         comments: list[tuple[int, str]]) -> None:
    _git(repo, "branch", "detoxer/issue-1")
    fake_agent[1] = "detoxer-result: merged https://pr/1"
    results = _run_all(repo, [1], tmp_path / "run")
    assert results[0][:2] == (1, "failed")
    assert results[0][2].startswith("git switch:")
    assert [issue for issue, _body in comments] == [1]


def test_failed_session_without_result_line(repo: Path, tmp_path: Path,
                                            fake_agent: dict[int, str],
                                            comments: list[tuple[int, str]]) -> None:
    fake_agent[1] = "crashed"
    assert _run_all(repo, [1], tmp_path / "run") == [
        (1, "failed", "the session ended without a detoxer-result line")]


def test_unknown_base_is_a_setup_error(repo: Path, tmp_path: Path) -> None:
    with pytest.raises(implement_issues.SetupError, match="git fetch"):
        implement_issues.run_all("claude", "fake-claude", SETTINGS, GIT, "fake-gh", repo,
                                 "no-such-branch", [1], tmp_path / "run")


def test_detach_restarts_itself_without_detach(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[tuple[list[str], dict]] = []

    class FakePopen:
        pid = 4321

        def __init__(self, command: list[str], **options) -> None:
            started.append((command, options))

    monkeypatch.setattr(implement_issues.subprocess, "Popen", FakePopen)
    argv = ["--agent", "claude", "--base", "main", "--repo", "R", "--issues", "1", "2"]
    assert implement_issues.detach(argv, tmp_path) == 4321
    command, options = started[0]
    assert command[:2] == [sys.executable, str(SCRIPT)]
    assert command[2:] == [*argv, "--run-dir", str(tmp_path)]
    assert "--detach" not in command
    assert options["stdin"] is subprocess.DEVNULL
    if sys.platform == "win32":
        assert options["creationflags"] & subprocess.DETACHED_PROCESS
    else:
        assert options["start_new_session"] is True


def test_main_missing_tool_is_exit_1(repo: Path, monkeypatch: pytest.MonkeyPatch,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    real_which = shutil.which
    monkeypatch.setattr(implement_issues.shutil, "which",
                        lambda name: None if name in ("claude", "gh") else real_which(name))
    monkeypatch.setattr(sys, "argv", ["implement_issues.py", "--agent", "claude", "--base", "main",
                                      "--repo", str(repo), "--issues", "1"])
    assert implement_issues.main() == 1
    assert capsys.readouterr().err == "error: not found in PATH: claude, gh\n"


def test_comment_passes_the_body_as_a_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **options) -> subprocess.CompletedProcess:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(implement_issues.subprocess, "run", run)
    body = tmp_path / "comment.md"
    assert implement_issues.comment_on_issue("gh", tmp_path, 7, body) is True
    assert calls == [["gh", "issue", "comment", "7", "--body-file", str(body)]]
