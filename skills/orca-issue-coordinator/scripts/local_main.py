#!/usr/bin/env python3
"""Pin the skill checkout during a Run and fast-forward the local default branch at its end.

Orca fast-forwards the local base branch to its origin each time it creates a
worktree. When the Coordinator's working repository is the repository the
skills are installed from, that would swap the skills under a running Run.

Subcommands:
  freeze [--repo <path>]
      When the working repository (`--repo`, default: the current directory)
      and the skill checkout are the same repository (same git common dir, so
      another worktree of it counts), detach the skill checkout at its current
      HEAD and print `skill-checkout-frozen: <full sha>`. Otherwise change
      nothing and print `skill-checkout-frozen: no`. Exit 0; on failure (already
      detached, git error) change nothing, print `error: <reason>`, exit 1.
  finish --frozen <sha|no> [--repo <path>]
      Run once at the end of a Run. With a SHA, switch the skill checkout back
      to the default branch `<base>` (origin's HEAD branch); exit 2 without
      changes when it is not detached at that SHA. Then fetch `<base>` from
      origin in the working repository and fast-forward its local `<base>`:
      `local-main: up-to-date`, `updated`, `skipped (diverged)`, or
      `skipped (dirty: <worktree path>)`. Finally print
      `local-main-head: <full sha>` and exit 0. On a git failure stop where it
      is, print `error: <reason>`, and exit 1.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TIMEOUT_SECONDS = 60
# Resolving follows the ~/.agents/skills symlink to the real checkout.
SKILL_DIR = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")


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


def skill_checkout() -> str:
    return git(str(SKILL_DIR), "rev-parse", "--show-toplevel").splitlines()[-1].strip()


def common_dir(path: str) -> str:
    out = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return os.path.normcase(os.path.realpath(out.splitlines()[-1].strip()))


def detached_head(path: str) -> str | None:
    """Return the full HEAD SHA when HEAD is detached, otherwise None."""
    code, _ = run(["git", "-C", path, "symbolic-ref", "-q", "HEAD"])
    if code == 0:
        return None
    if code != 1:
        raise GitError(f"`git symbolic-ref -q HEAD` failed in {path} (exit {code})")
    return git(path, "rev-parse", "HEAD")


def default_branch(repo: str) -> str:
    out = git(repo, "ls-remote", "--symref", "origin", "HEAD")
    for line in out.splitlines():
        match = re.fullmatch(r"ref: refs/heads/(\S+)\s+HEAD", line.strip())
        if match:
            return match.group(1)
    raise GitError(f"cannot determine origin's default branch in {repo}: {out[:200]}")


def freeze(repo: str) -> int:
    checkout = skill_checkout()
    if common_dir(repo) != common_dir(checkout):
        print("skill-checkout-frozen: no")
        return 0
    if detached_head(checkout) is not None:
        raise GitError(f"the skill checkout {checkout} is already detached")
    git(checkout, "switch", "--detach")
    print(f"skill-checkout-frozen: {git(checkout, 'rev-parse', 'HEAD')}")
    return 0


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
    """Fast-forward refs/heads/<base> to origin/<base> and return the `local-main:` result."""
    git(repo, "fetch", "--quiet", "origin", f"+refs/heads/{base}:refs/remotes/origin/{base}")
    ref = f"refs/heads/{base}"
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
        git(repo, "update-ref", "-m", f"orca-issue-coordinator: fast-forward to origin/{base}",
            ref, new, old)
        return "updated"
    if git(worktree, "status", "--porcelain", "--untracked-files=no"):
        return f"skipped (dirty: {worktree})"
    git(worktree, "merge", "--ff-only", "--quiet", f"origin/{base}")
    return "updated"


def finish(repo: str, frozen: str) -> int:
    base = default_branch(repo)
    if frozen != "no":
        checkout = skill_checkout()
        if detached_head(checkout) != frozen.lower():
            print(f"error: the skill checkout is not detached at {frozen}")
            return 2
        git(checkout, "switch", "--quiet", base)
    print(f"local-main: {fast_forward(repo, base)}")
    print(f"local-main-head: {git(repo, 'rev-parse', '--verify', f'refs/heads/{base}')}")
    return 0


def frozen_value(value: str) -> str:
    if value == "no" or SHA.fullmatch(value.lower()):
        return value
    raise argparse.ArgumentTypeError("expected a full commit SHA or `no`")


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    freeze_parser = sub.add_parser("freeze", help="pin the skill checkout for this Run")
    freeze_parser.add_argument("--repo", default=os.getcwd(), help="the working repository")
    finish_parser = sub.add_parser("finish", help="restore the skill checkout and "
                                   "fast-forward the local default branch")
    finish_parser.add_argument("--frozen", required=True, type=frozen_value,
                               help="the `skill-checkout-frozen:` value from freeze")
    finish_parser.add_argument("--repo", default=os.getcwd(), help="the working repository")
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            return freeze(args.repo)
        return finish(args.repo, args.frozen)
    except GitError as exc:
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
