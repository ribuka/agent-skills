"""Safely fast-forward a local branch from its explicit origin ref."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

TIMEOUT_SECONDS = 60


class GitError(Exception):
    """A git command failed; the message is the reason to report."""


def run(cmd: list[str]) -> tuple[int, str]:
    """Run a command and return its exit code and output (stdout, or all output on failure)."""
    exe = shutil.which(cmd[0])
    if exe is None:
        return 127, f"{cmd[0]}: command not found"
    try:
        proc = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return 124, f"{' '.join(cmd)}: timed out after {TIMEOUT_SECONDS}s"
    if proc.returncode != 0:
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    return 0, proc.stdout.strip()


def git(path: str, *args: str) -> str:
    """Run git in `path` and return its output, raising GitError on failure."""
    code, out = run(["git", "-C", path, *args])
    if code != 0:
        raise GitError(f"`git {' '.join(args)}` failed in {path} (exit {code}): {out}")
    return out


def worktree_with_branch(repo: str, ref: str) -> str | None:
    """Return the path of the worktree that has `ref` checked out, if any."""
    path = None
    for line in git(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line == f"branch {ref}":
            return path
    return None


def fast_forward(repo: str, base: str) -> str:
    """Fast-forward refs/heads/<base> to origin/<base> and return the `local-branch:` result."""
    git(repo, "fetch", "--quiet", "origin", f"+refs/heads/{base}:refs/remotes/origin/{base}")
    ref = f"refs/heads/{base}"
    code, out = run(["git", "-C", repo, "show-ref", "--verify", "--quiet", ref])
    if code == 1:
        return "skipped (missing local branch)"
    if code != 0:
        raise GitError(f"`git show-ref --verify` failed in {repo} (exit {code}): {out}")
    old = git(repo, "rev-parse", "--verify", ref)
    new = git(repo, "rev-parse", "--verify", f"refs/remotes/origin/{base}")
    if old == new:
        return "up-to-date"
    code, out = run(["git", "-C", repo, "merge-base", "--is-ancestor", old, new])
    if code == 1:
        return "skipped (diverged)"
    if code != 0:
        raise GitError(f"`git merge-base --is-ancestor` failed in {repo} (exit {code}): {out}")
    worktree = worktree_with_branch(repo, ref)
    if worktree is None:
        git(repo, "update-ref", "-m", f"fast-forward-local-branch: fast-forward to origin/{base}",
            ref, new, old)
        return "updated"
    if git(worktree, "status", "--porcelain", "--untracked-files=no"):
        return f"skipped (dirty: {worktree})"
    git(worktree, "merge", "--ff-only", "--quiet", new)
    return "updated"


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch", required=True)
    args = parser.parse_args(argv)
    try:
        git(args.repo, "check-ref-format", f"refs/heads/{args.branch}")
        result = fast_forward(args.repo, args.branch)
        print(f"local-branch: {result}")
        if result != "skipped (missing local branch)":
            head = git(args.repo, "rev-parse", "--verify", f"refs/heads/{args.branch}")
            print(f"local-branch-head: {head}")
        return 0
    except GitError as exc:
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())


