#!/usr/bin/env python3
"""Implement GitHub issues one at a time, each in a new unattended agent session.

For each issue, in the given order, in a dedicated git worktree of the
repository: create the branch `detoxer/issue-<n>` from the latest
origin/<base>, start `claude -p` or `codex exec` (the agent given by --agent)
there, and ask it to run the implement-review-merge skill on the issue in
Standalone mode. Stop at the first issue that is not merged, comment the reason
on that issue with `gh`, and leave the rest not started. Settings come from
resolve_config.py (IMPLEMENT_TIMEOUT_SECONDS, CLAUDE_PERMISSION_MODE,
CODEX_SANDBOX). Session output goes to log files in the run directory, never to
stdout.

The run directory is <system temp>/detoxer/<repo>-<timestamp>/; it holds
summary.md, one log per issue, and the worktree (removed when every issue is
merged, kept otherwise).

With --detach the script starts itself in the background, detached from the
caller, prints `started: <pid>` and `summary: <path>`, and exits 0.

Without --detach, output (stdout): one line per issue,
`#<n>: <merged|stopped|timeout|failed|not-started> <detail>`, then
`summary: <path>`. Exit codes: 0 every issue merged; 2 some issue not merged;
1 nothing was started (invalid settings, agent, git, or gh not found, not a git
repository, worktree creation failed), with `error: ...` on stderr.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

AGENTS = ("claude", "codex")
RESULT_LINE = re.compile(r"^detoxer-result:\s*(merged|stopped)\s+(.+?)\s*$", re.MULTILINE)
PROMPT = """\
Use the implement-review-merge skill in its default (Standalone) mode to \
implement GitHub issue #{issue} through to merge, on the current branch \
`{branch}`. Nobody is watching this session: whenever the skill says to stop \
and ask the user, do not wait for an answer; stop instead. End your final \
message with exactly one line, either `detoxer-result: merged <pull request URL>` \
when the pull request is merged, or `detoxer-result: stopped <one-line reason>` \
otherwise."""


class SetupError(Exception):
    """Nothing could be started."""


def _load_resolve_config():
    """Load the sibling resolve_config.py of this skill."""
    path = Path(__file__).resolve().parent / "resolve_config.py"
    spec = importlib.util.spec_from_file_location("detoxer_resolve_config", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_prompt(issue: int, branch: str) -> str:
    """Return the instruction given to the new session."""
    return PROMPT.format(issue=issue, branch=branch)


def build_command(agent: str, executable: str, settings: dict[str, str],
                  last_message: Path) -> list[str]:
    """Return the argv that starts the unattended session; the prompt goes on stdin.

    The prompt never goes on the command line: a `.cmd` shim (e.g. npm's codex.cmd)
    passes it through cmd.exe, which breaks on newlines and special characters.
    """
    if agent == "claude":
        return [executable, "-p", "--permission-mode", settings["CLAUDE_PERMISSION_MODE"]]
    command = [executable, "exec", "--sandbox", settings["CODEX_SANDBOX"],
               "--output-last-message", str(last_message)]
    if settings["CODEX_SANDBOX"] == "workspace-write":
        command += ["-c", "sandbox_workspace_write.network_access=true"]
    return [*command, "-"]


def parse_result(final_message: str) -> tuple[str, str]:
    """Return (merged|stopped, detail) from the last result line, or failed when none."""
    matches = RESULT_LINE.findall(final_message)
    if not matches:
        return "failed", "the session ended without a detoxer-result line"
    return matches[-1]


def _kill_tree(process: subprocess.Popen) -> None:
    """Kill the session and every process it started."""
    taskkill = shutil.which("taskkill") if os.name == "nt" else None
    if taskkill:
        subprocess.run([taskkill, "/F", "/T", "/PID", str(process.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    elif os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()
    process.wait()


def run_session(command: list[str], cwd: Path, prompt_path: Path, log_path: Path,
                timeout: int) -> int | None:
    """Run the session with the prompt file on stdin and its output in the log.

    Return its exit code, or None on timeout.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with prompt_path.open("rb") as prompt, \
            log_path.open("w", encoding="utf-8", errors="replace") as log:
        process = subprocess.Popen(command, cwd=cwd, stdin=prompt, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(process)
            return None


def _git(git: str, cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """Run git quietly and return the completed process."""
    return subprocess.run([git, *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


def _git_error(completed: subprocess.CompletedProcess) -> str:
    """Return the last line git printed, for a one-line reason."""
    lines = (completed.stderr or completed.stdout).strip().splitlines()
    return lines[-1] if lines else f"git exited with code {completed.returncode}"


def implement_one(agent: str, executable: str, settings: dict[str, str], git: str,
                  worktree: Path, base: str, issue: int, run_dir: Path) -> tuple[str, str]:
    """Implement one issue on a new branch in the worktree; return (result, detail)."""
    branch = f"detoxer/issue-{issue}"
    for args in (("fetch", "origin", base), ("switch", "-c", branch, f"origin/{base}")):
        completed = _git(git, worktree, *args)
        if completed.returncode != 0:
            return "failed", f"git {args[0]}: {_git_error(completed)}"
    log_path = run_dir / f"issue-{issue}.log"
    last_message = run_dir / f"issue-{issue}-last-message.txt"
    prompt_path = run_dir / f"issue-{issue}-prompt.txt"
    prompt_path.write_text(build_prompt(issue, branch), encoding="utf-8")
    command = build_command(agent, executable, settings, last_message)
    timeout = int(settings["IMPLEMENT_TIMEOUT_SECONDS"])
    code = run_session(command, worktree, prompt_path, log_path, timeout)
    if code is None:
        return "timeout", f"killed after {timeout}s"
    source = last_message if agent == "codex" else log_path
    text = source.read_text(encoding="utf-8", errors="replace") if source.exists() else ""
    result, detail = parse_result(text)
    if result == "failed" and code != 0:
        detail = f"the session exited with code {code}"
    return result, detail


def comment_on_issue(gh: str, repo: Path, issue: int, body_file: Path) -> bool:
    """Post the file as a comment on the issue; return whether it was posted.

    The body goes in a file, never on the command line: `gh` may be a `.cmd` shim,
    and cmd.exe cuts arguments at newlines.
    """
    completed = subprocess.run([gh, "issue", "comment", str(issue), "--body-file", str(body_file)],
                               cwd=repo, capture_output=True, text=True, check=False)
    return completed.returncode == 0


def run_all(agent: str, executable: str, settings: dict[str, str], git: str, gh: str,
            repo: Path, base: str, issues: list[int], run_dir: Path) -> list[tuple[int, str, str]]:
    """Implement the issues in order and write summary.md; return (issue, result, detail)."""
    worktree = run_dir / "worktree"
    for args in (("fetch", "origin", base),
                 ("worktree", "add", "--detach", str(worktree), f"origin/{base}")):
        completed = _git(git, repo, *args)
        if completed.returncode != 0:
            raise SetupError(f"git {args[0]}: {_git_error(completed)}")

    results: list[tuple[int, str, str]] = []
    for issue in issues:
        if results and results[-1][1] != "merged":
            results.append((issue, "not-started", "an earlier issue was not merged"))
            continue
        result, detail = implement_one(agent, executable, settings, git, worktree, base,
                                       issue, run_dir)
        if result != "merged":
            body_file = run_dir / f"issue-{issue}-comment.md"
            body_file.write_text(
                f"detoxer stopped implementing this issue: {result} - {detail}\n\n"
                f"Session log: `{run_dir / f'issue-{issue}.log'}` on the machine that ran it.\n",
                encoding="utf-8")
            if not comment_on_issue(gh, repo, issue, body_file):
                detail += " (commenting on the issue failed)"
        results.append((issue, result, detail))

    all_merged = all(result == "merged" for _issue, result, _detail in results)
    if all_merged:
        removed = _git(git, repo, "worktree", "remove", "--force", str(worktree))
        worktree_note = "removed" if removed.returncode == 0 else f"not removed: {_git_error(removed)}"
    else:
        worktree_note = "kept for inspection"
    lines = [f"# detoxer implementation run", "", f"- Repository: `{repo}`",
             f"- Base: `origin/{base}`", f"- Agent: {agent}",
             f"- Worktree: `{worktree}` ({worktree_note})", ""]
    lines += [f"- #{issue}: {result} {detail}" for issue, result, detail in results]
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return results


def detach(argv: list[str], run_dir: Path) -> int:
    """Start this script again in the background, detached from the caller; return its pid."""
    log = (run_dir / "coordinator.log").open("w", encoding="utf-8")
    command = [sys.executable, str(Path(__file__).resolve()), *argv, "--run-dir", str(run_dir)]
    options: dict = {"stdin": subprocess.DEVNULL, "stdout": log, "stderr": subprocess.STDOUT,
                     "close_fds": True}
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            process = subprocess.Popen(command, creationflags=flags
                                       | subprocess.CREATE_BREAKAWAY_FROM_JOB, **options)
        except OSError:
            # The caller's job object may forbid breakaway; detach within it.
            process = subprocess.Popen(command, creationflags=flags, **options)
    else:
        process = subprocess.Popen(command, start_new_session=True, **options)
    log.close()
    return process.pid


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agent", required=True, choices=AGENTS,
                        help="the agent to start; use the one running the caller")
    parser.add_argument("--base", required=True, help="default branch name (e.g. main)")
    parser.add_argument("--issues", required=True, type=int, nargs="+",
                        help="issue numbers, in the order to implement them")
    parser.add_argument("--repo", type=Path, default=Path.cwd(),
                        help="repository root (default: the current directory)")
    parser.add_argument("--detach", action="store_true",
                        help="run in the background, detached from the caller")
    parser.add_argument("--run-dir", type=Path, help=argparse.SUPPRESS)
    opts = parser.parse_args()

    resolve_config = _load_resolve_config()
    try:
        settings = {key: value for key, (value, _src)
                    in resolve_config.load_config(resolve_config.SKILL_DIR).items()}
    except resolve_config.ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    tools = {name: shutil.which(name) for name in (opts.agent, "git", "gh")}
    missing = [name for name, path in tools.items() if not path]
    if missing:
        print(f"error: not found in PATH: {', '.join(missing)}", file=sys.stderr)
        return 1
    repo = opts.repo.resolve()
    top = _git(tools["git"], repo, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        print(f"error: {repo}: not a git repository", file=sys.stderr)
        return 1

    run_dir = opts.run_dir or (Path(tempfile.gettempdir()) / "detoxer"
                               / f"{repo.name}-{time.strftime('%Y%m%d-%H%M%S')}")
    run_dir.mkdir(parents=True, exist_ok=True)
    if opts.detach:
        argv = ["--agent", opts.agent, "--base", opts.base, "--repo", str(repo),
                "--issues", *map(str, opts.issues)]
        print(f"started: {detach(argv, run_dir)}")
        print(f"summary: {run_dir / 'summary.md'}")
        return 0

    try:
        results = run_all(opts.agent, tools[opts.agent], settings, tools["git"], tools["gh"],
                          repo, opts.base, opts.issues, run_dir)
    except SetupError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for issue, result, detail in results:
        print(f"#{issue}: {result} {detail}")
    print(f"summary: {run_dir / 'summary.md'}")
    return 0 if all(result == "merged" for _issue, result, _detail in results) else 2


if __name__ == "__main__":
    sys.exit(main())
