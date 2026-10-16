#!/usr/bin/env python3
"""Delete a finished Run's temporary directory, `<repo-root>/tmp/<run-id>/`.

The repository root is the git top level of the current directory. The script
deletes only that one directory: it refuses a Run ID that is not a plain
directory name, and a target whose resolved path (after symlinks or junctions)
is not exactly `<repo-root>/tmp/<run-id>`.

Prints one JSON line `{"status": ..., "path": ...}` (plus `reason` unless
removed or absent).

Exit status:
  0  removed, or already absent
  1  deletion failed; `path` (and anything left in it) still exists
  2  refused; nothing was deleted
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
TIMEOUT_SECONDS = 30


def repo_root() -> Path:
    """Return the git top level of the current directory."""
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=TIMEOUT_SECONDS)
    if proc.returncode != 0:
        raise ValueError(f"not inside a git repository: {proc.stderr.strip()}")
    return Path(proc.stdout.strip())


def make_writable_and_retry(func, path, _exc) -> None:
    """Clear the read-only bit (e.g. git objects on Windows) and retry once."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def cleanup(root: Path, run_id: str) -> tuple[int, dict]:
    """Delete `<root>/tmp/<run_id>` and return the exit status and result."""
    if not RUN_ID.fullmatch(run_id):
        return 2, {"status": "refused", "path": None,
                   "reason": f"invalid run ID: {run_id!r}"}
    tmp = root / "tmp"
    target = tmp / run_id
    result = {"status": "refused", "path": str(target)}
    real_root = os.path.realpath(root)
    if os.path.realpath(tmp) != os.path.join(real_root, "tmp"):
        return 2, {**result, "reason": "tmp/ resolves outside the repository root"}
    if not os.path.lexists(target):
        return 0, {"status": "absent", "path": str(target)}
    if os.path.realpath(target) != os.path.join(real_root, "tmp", run_id):
        return 2, {**result, "reason": "target is a link that resolves elsewhere"}
    if not target.is_dir():
        return 2, {**result, "reason": "target is not a directory"}
    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(target, onexc=make_writable_and_retry)
        else:
            shutil.rmtree(target, onerror=make_writable_and_retry)
    except OSError as error:
        return 1, {"status": "failed", "path": str(target), "reason": str(error)}
    return 0, {"status": "removed", "path": str(target)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        root = repo_root()
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        code, result = 2, {"status": "refused", "path": None, "reason": str(error)}
    else:
        code, result = cleanup(root, args.run_id)
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    sys.exit(main())
