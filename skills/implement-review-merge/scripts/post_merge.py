"""Apply the optional standalone local-main synchronization after a confirmed merge."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]


def sync_enabled(path: Path) -> bool:
    """Resolve the personal setting, defaulting to enabled when absent."""
    if not path.exists():
        return True
    values = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, sep, value = line.partition("=")
        if not sep or key.strip() != "SYNC_LOCAL_MAIN_AFTER_MERGE":
            raise ValueError(f"invalid setting at {path}:{number}")
        if value.strip() not in {"true", "false"}:
            raise ValueError(f"SYNC_LOCAL_MAIN_AFTER_MERGE must be true or false at {path}:{number}")
        values[key.strip()] = value.strip()
    return values.get("SYNC_LOCAL_MAIN_AFTER_MERGE", "true") == "true"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--mode", required=True, choices=("standalone", "worker"))
    parser.add_argument("--pr-state", required=True, choices=("MERGED", "OPEN", "CLOSED", "UNKNOWN"))
    args = parser.parse_args(argv)
    if args.mode != "standalone" or args.pr_state != "MERGED":
        print("local-main-sync: skipped (requires standalone and confirmed MERGED)")
        return 0
    try:
        if not sync_enabled(SKILL_DIR / "config.conf"):
            print("local-main-sync: skipped (disabled)")
            return 0
        script = Path.home() / ".agents/skills/fast-forward-local-branch/scripts/fast_forward.py"
        proc = subprocess.run(["uv", "run", "--no-project", str(script),
                               "--repo", args.repo, "--branch", "main"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120)
        if proc.stdout.strip():
            print(proc.stdout.strip())
        if proc.returncode != 0:
            print(f"error: fast-forward-local-branch failed (exit {proc.returncode}): "
                  f"{proc.stderr.strip()}")
            return 1
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"error: post-merge synchronization: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
