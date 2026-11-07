"""Apply the optional standalone local-main synchronization after a confirmed merge."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from config import read_config

SKILL_DIR = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--mode", required=True, choices=("standalone", "worker"))
    parser.add_argument("--pr-state", required=True, choices=("MERGED", "OPEN", "CLOSED", "UNKNOWN"))
    args = parser.parse_args(argv)
    if args.mode != "standalone" or args.pr_state != "MERGED":
        print("local-main-sync: skipped (requires standalone and confirmed MERGED)")
        return 0
    try:
        if not read_config(SKILL_DIR / "config.conf")["SYNC_LOCAL_MAIN_AFTER_MERGE"]:
            print("local-main-sync: skipped (disabled)")
            return 0
        script = Path.home() / ".agents/skills/fast-forward-local-branch/scripts/fast_forward.py"
        proc = subprocess.run(["uv", "run", "--no-project", str(script),
                               "--repo", args.repo, "--branch", "main"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
        if proc.stdout.strip():
            print(proc.stdout.strip())
        if proc.returncode != 0:
            if proc.stderr.strip() or not proc.stdout.strip():
                reason = f": {proc.stderr.strip()}" if proc.stderr.strip() else ""
                print(f"error: fast-forward-local-branch failed (exit {proc.returncode}){reason}")
            return 1
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"error: post-merge synchronization: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
