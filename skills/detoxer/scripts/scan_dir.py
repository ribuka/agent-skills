#!/usr/bin/env python3
"""Create and remove detoxer's scan directory and its detached worktree.

Both subcommands work on the git repository of the current directory.

`create --ref <scan-ref>` makes `detoxer-scan-<yyyymmdd-HHMMSS>-<random>`
directly under the system temp directory (`tempfile.gettempdir()`) and, in it,
a detached worktree `checkout` of `<scan-ref>`. Output (exit 0):

    scan_dir: <absolute path of the scan directory>
    checkout: <absolute path of <scan-dir>/checkout>
    commit: <40-hex SHA of the worktree's HEAD>

On failure (outside a git repository, an unresolvable ref, git not found,
worktree creation failed) it prints `error: <reason>` on stderr, leaves
nothing behind, and exits 1.

`remove <scan-dir>` deletes only a directory directly under the system temp
directory (compared after resolving symlinks and junctions) whose name starts
with `detoxer-scan-`, and that is itself neither a link nor a file. The path is
checked first, then its existence, so a missing path that fails the checks is
refused. It runs `git worktree remove --force <scan-dir>/checkout` when the
checkout exists, deletes the directory (clearing read-only bits and retrying
once), then runs `git worktree prune`. Output and exit status:

    removed: <path>   0  deleted
    absent: <path>    0  did not exist
    failed: <path>    1  something is left (`error: <reason>` on stderr)
    refused: <path>   2  nothing was deleted (`error: <reason>` on stderr)
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PREFIX = "detoxer-scan-"
TIMEOUT_SECONDS = 120


class ScanDirError(Exception):
    """The scan directory could not be created."""


def _git(git: str, *args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run git quietly and return the completed process."""
    return subprocess.run([git, *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False,
                          timeout=TIMEOUT_SECONDS)


def _git_error(completed: subprocess.CompletedProcess) -> str:
    """Return the last line git printed, for a one-line reason."""
    lines = (completed.stderr or completed.stdout).strip().splitlines()
    return lines[-1] if lines else f"git exited with code {completed.returncode}"


def _find_git() -> str:
    git = shutil.which("git")
    if git is None:
        raise ScanDirError("git not found on PATH")
    return git


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _make_writable_and_retry(func, path, _exc) -> None:
    """Clear the read-only bit (e.g. git objects on Windows) and retry once."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _rmtree(path: str) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_make_writable_and_retry)
    else:
        shutil.rmtree(path, onerror=_make_writable_and_retry)


def create(ref: str) -> tuple[str, str, str]:
    """Create the scan directory and worktree; return (scan_dir, checkout, commit)."""
    git = _find_git()
    top = _git(git, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        raise ScanDirError(f"not inside a git repository: {_git_error(top)}")
    resolved = _git(git, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if resolved.returncode != 0:
        raise ScanDirError(f"cannot resolve {ref!r} to a commit")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    scan_dir = os.path.abspath(tempfile.mkdtemp(prefix=f"{PREFIX}{stamp}-"))
    checkout = os.path.join(scan_dir, "checkout")
    try:
        added = _git(git, "worktree", "add", "--detach", checkout, resolved.stdout.strip())
        if added.returncode != 0:
            raise ScanDirError(f"worktree creation failed: {_git_error(added)}")
        head = _git(git, "rev-parse", "HEAD", cwd=checkout)
        if head.returncode != 0:
            raise ScanDirError(f"cannot read the worktree's HEAD: {_git_error(head)}")
    except (ScanDirError, OSError, subprocess.TimeoutExpired):
        _rmtree(scan_dir)
        _git(git, "worktree", "prune")
        raise
    return scan_dir, checkout, head.stdout.strip()


def _refusal(target: str) -> str | None:
    """Return why `target` must not be removed, or None when it may be."""
    temp_root = os.path.realpath(tempfile.gettempdir())
    real = os.path.realpath(target)
    if not _same_path(os.path.dirname(real), temp_root):
        return f"not directly under the system temp directory {temp_root}"
    if not os.path.basename(real).startswith(PREFIX):
        return f"name does not start with {PREFIX}"
    return None


def remove(target: str) -> tuple[int, str, str | None]:
    """Remove the scan directory; return (exit status, status word, error reason)."""
    reason = _refusal(target)
    if reason is not None:
        return 2, "refused", reason
    if not os.path.lexists(target):
        return 0, "absent", None
    parent = os.path.realpath(os.path.dirname(os.path.abspath(target)))
    own = os.path.join(parent, os.path.basename(os.path.abspath(target)))
    if os.path.islink(target) or not _same_path(os.path.realpath(target), own):
        return 2, "refused", "is a link"
    if not os.path.isdir(target):
        return 2, "refused", "not a directory"
    git = shutil.which("git")
    checkout = os.path.join(target, "checkout")
    notes = []
    had_checkout = os.path.lexists(checkout)
    if had_checkout:
        if git is None:
            notes.append("git not found on PATH; the worktree registration may remain")
        else:
            removed = _git(git, "worktree", "remove", "--force", checkout)
            if removed.returncode != 0:
                print(f"warning: git worktree remove failed: {_git_error(removed)}",
                      file=sys.stderr)
    try:
        _rmtree(target)
    except OSError as error:
        notes.insert(0, str(error))
    if had_checkout and git is not None:
        pruned = _git(git, "worktree", "prune")
        if pruned.returncode != 0:
            notes.append(f"git worktree prune failed: {_git_error(pruned)}")
    if notes:
        return 1, "failed", "; ".join(notes)
    return 0, "removed", None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    create_parser = commands.add_parser("create", help="create the scan directory")
    create_parser.add_argument("--ref", required=True, help="commit to check out")
    remove_parser = commands.add_parser("remove", help="remove a scan directory")
    remove_parser.add_argument("scan_dir")
    args = parser.parse_args(argv)
    if args.command == "create":
        try:
            scan_dir, checkout, commit = create(args.ref)
        except (ScanDirError, OSError, subprocess.TimeoutExpired) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print(f"scan_dir: {scan_dir}")
        print(f"checkout: {checkout}")
        print(f"commit: {commit}")
        return 0
    try:
        code, status, reason = remove(args.scan_dir)
    except subprocess.TimeoutExpired as error:
        code, status, reason = 1, "failed", str(error)
    print(f"{status}: {args.scan_dir}")
    if reason is not None:
        print(f"error: {reason}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
