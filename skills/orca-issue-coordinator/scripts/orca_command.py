"""Run commands and return only their exit code and standard output."""

from __future__ import annotations

import shutil
import subprocess


def run_stdout(cmd: list[str], timeout_seconds: float) -> tuple[int, str]:
    """Resolve and run a command, dropping stderr and replacing invalid UTF-8."""
    exe = shutil.which(cmd[0])
    if exe is None:
        return 127, ""
    try:
        proc = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        return 124, ""
    return proc.returncode, proc.stdout
