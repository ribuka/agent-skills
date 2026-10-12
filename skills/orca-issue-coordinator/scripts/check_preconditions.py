#!/usr/bin/env python3
"""Check the preconditions for running orca-issue-coordinator.

Checks:
  1. This process runs inside an Orca terminal (ORCA_TERMINAL_HANDLE is set),
     so ORCA Orchestration can identify the Coordinator as the sender.
  2. The Orca runtime is reachable (`orca status --json`).
  3. GitHub CLI authentication works (`gh auth status`).

Exit status: 0 when every check passes, 1 when any check fails. On failure the
Coordinator must stop and report to the user; it must not work around it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

TIMEOUT_SECONDS = 60


def run(cmd: list[str]) -> tuple[int, str]:
    """Run a command and return its exit code and combined output."""
    exe = shutil.which(cmd[0])
    if exe is None:
        return 127, f"{cmd[0]}: command not found"
    try:
        proc = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return 124, f"{' '.join(cmd)}: timed out after {TIMEOUT_SECONDS}s"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def check_orca_terminal() -> str | None:
    if os.environ.get("ORCA_TERMINAL_HANDLE", "").strip():
        return None
    return ("not running inside an Orca terminal (ORCA_TERMINAL_HANDLE is not set); "
            "start this skill from an Orca terminal")


def check_orca_runtime() -> str | None:
    code, out = run(["orca", "status", "--json"])
    if code != 0:
        return f"`orca status --json` failed (exit {code}): {out}"
    try:
        result = json.loads(out)["result"]
        reachable = bool(result["runtime"]["reachable"])
    except (ValueError, KeyError, TypeError):
        return f"`orca status --json` returned unexpected output: {out[:200]}"
    if not reachable:
        return "the Orca runtime is not reachable (`orca status --json`)"
    return None


def check_gh_auth() -> str | None:
    code, out = run(["gh", "auth", "status"])
    if code != 0:
        return f"`gh auth status` failed (exit {code}): {out}"
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    failures = [msg for msg in (check_orca_terminal(), check_orca_runtime(), check_gh_auth())
                if msg]
    if not failures:
        print("preconditions: ok")
        return 0
    for msg in failures:
        print(f"STOP: {msg}")
    print("Stop and report this to the user. Do not work around it.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
