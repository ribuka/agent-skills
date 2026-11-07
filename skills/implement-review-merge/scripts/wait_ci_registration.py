"""Wait a bounded time for checks to be registered on the expected PR head."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from config import read_config

SKILL_DIR = Path(__file__).resolve().parents[1]


def wait_for_registration(pr: int, head: str, timeout: int) -> int:
    """Poll gh every 30 seconds until registration or the monotonic deadline."""
    gh = shutil.which("gh")
    if gh is None:
        raise ValueError("gh: command not found")
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(f"ci-registration: timeout after {timeout}s (head {head})")
            return 2
        try:
            result = subprocess.run(
                [gh, "pr", "view", str(pr), "--json", "headRefOid,statusCheckRollup"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=remaining,
            )
        except subprocess.TimeoutExpired:
            print(f"ci-registration: timeout after {timeout}s (head {head})")
            return 2
        if result.returncode:
            raise ValueError(f"gh pr view failed (exit {result.returncode}): "
                             f"{result.stderr.strip() or result.stdout.strip()}")
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or not isinstance(data.get("headRefOid"), str):
            raise ValueError("invalid gh response: missing headRefOid")
        checks = data.get("statusCheckRollup")
        if checks is not None and not isinstance(checks, list):
            raise ValueError("invalid gh response: statusCheckRollup must be a list or null")
        if time.monotonic() >= deadline:
            print(f"ci-registration: timeout after {timeout}s (head {head})")
            return 2
        if data["headRefOid"] == head and checks:
            print(f"ci-registration: registered {head}")
            return 0
        time.sleep(min(30, max(0, deadline - time.monotonic())))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--head", required=True)
    args = parser.parse_args(argv)
    if args.pr < 1 or len(args.head) != 40 or any(c not in "0123456789abcdefABCDEF" for c in args.head):
        print("error: --pr must be positive and --head must be a full SHA")
        return 1
    try:
        config = read_config(SKILL_DIR / "config.conf")
        return wait_for_registration(args.pr, args.head, config["CI_REGISTRATION_TIMEOUT_SECONDS"])
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
