#!/usr/bin/env python3
"""Check the preconditions for running orca-issue-coordinator.

Checks:
  1. This process runs inside an Orca terminal (ORCA_TERMINAL_HANDLE is set),
     so ORCA Orchestration can identify the Coordinator as the sender.
  2. The Orca runtime is reachable (`orca status --json`).
  3. GitHub CLI authentication works (`gh auth status`).
  4. The git checkout this skill is installed from (the symlink source) matches
     `origin/main`: it is neither behind it nor carrying commits that are not on
     it, and its skills have no uncommitted changes, so the Coordinator and its
     workers run the latest skills.
  5. With `--agent codex`: the installed Codex CLI will not show its update
     prompt at startup. Codex shows it when the latest version it cached in
     `<CODEX_HOME>/version.json` is newer than the installed one and was not
     dismissed, unless `check_for_update_on_startup = false` in its
     `config.toml`. The prompt blocks every worker launch
     (`agent-update-prompt`).

Exit status: 0 when every check passes, 1 when any check fails. On failure the
Coordinator must stop and report to the user; it must not work around it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

TIMEOUT_SECONDS = 60
# Resolving follows the ~/.agents/skills symlink to the real checkout.
SKILL_DIR = Path(__file__).resolve().parents[1]
# An explicit refspec updates origin/main whatever remote.origin.fetch says.
MAIN_REFSPEC = "+refs/heads/main:refs/remotes/origin/main"
# Codex requires an RFC 3339 `last_checked_at` in its version cache.
RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})")


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


def check_skill_checkout() -> tuple[str | None, str | None]:
    """Return (checkout path, failure message) for the skill's source checkout."""
    code, out = run(["git", "-C", str(SKILL_DIR), "rev-parse", "--show-toplevel"])
    if code != 0:
        return None, f"{SKILL_DIR} is not inside a git checkout (exit {code}): {out}"
    checkout = out.splitlines()[-1].strip()
    code, out = run(["git", "-C", checkout, "fetch", "--quiet", "origin", MAIN_REFSPEC])
    if code != 0:
        return checkout, (f"`git fetch origin main` failed in the skill checkout {checkout} "
                          f"(exit {code}): {out}")
    code, out = run(["git", "-C", checkout, "rev-list", "--left-right", "--count",
                     "HEAD...origin/main"])
    counts = out.split()
    if code != 0 or len(counts) != 2 or not all(n.isdigit() for n in counts):
        return checkout, (f"cannot compare the skill checkout {checkout} with origin/main "
                          f"(exit {code}): {out}")
    ahead, behind = (int(n) for n in counts)
    code, out = run(["git", "-C", checkout, "status", "--porcelain", "--",
                     str(SKILL_DIR.parent)])
    if code != 0:
        return checkout, (f"`git status` failed in the skill checkout {checkout} "
                          f"(exit {code}): {out}")
    problems = []
    if out:
        problems.append("has uncommitted changes under its skills")
    if behind:
        problems.append(f"is {behind} commit(s) behind origin/main")
    if ahead:
        problems.append(f"has {ahead} commit(s) not on origin/main")
    if problems:
        return checkout, (f"the skill checkout {checkout} {' and '.join(problems)}, so the run "
                          "would use stale skills; ask the user to sync it with origin/main")
    return checkout, None


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", "").strip() or Path.home() / ".codex")


def parse_version(text: str) -> tuple[int, int, int] | None:
    """Parse a plain release version (`1.2.3`); pre-releases and others give None."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", text.strip())
    return tuple(int(n) for n in match.groups()) if match else None


def is_rfc3339(value: object) -> bool:
    if not isinstance(value, str) or not RFC3339.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def read_codex_version_cache(path: Path) -> tuple[str, str | None] | None:
    """Return (latest, dismissed) only when Codex would accept the cache file."""
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict):
        return None
    latest, dismissed = info.get("latest_version"), info.get("dismissed_version")
    if (not isinstance(latest, str) or not is_rfc3339(info.get("last_checked_at"))
            or not (dismissed is None or isinstance(dismissed, str))):
        return None
    return latest, dismissed


def check_codex_update_prompt() -> str | None:
    home = codex_home()
    try:
        config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        config = {}
    if config.get("check_for_update_on_startup", True) is False:
        return None
    cache = read_codex_version_cache(home / "version.json")
    if cache is None:
        return None  # Codex shows no prompt without a valid cached latest version.
    latest, dismissed = cache
    if dismissed == latest:
        return None
    code, out = run(["codex", "--version"])
    if code != 0:
        return f"`codex --version` failed (exit {code}): {out}"
    installed = out.split()[-1] if out.split() else ""
    newer, current = parse_version(latest), parse_version(installed)
    # Source builds report 0.0.0 and never show the prompt.
    if newer is None or current in (None, (0, 0, 0)) or newer <= current:
        return None
    return (f"Codex {installed} will show an update prompt for {latest} when a worker starts, "
            "which blocks the worker launch (agent-update-prompt); ask the user to update "
            "Codex, or to start `codex` once and choose to skip this version")


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agent", required=True, choices=("claude", "codex"),
                        help="the Coordinator's runtime; workers use the same agent")
    args = parser.parse_args(argv)
    checkout, checkout_failure = check_skill_checkout()
    checks = [check_orca_terminal(), check_orca_runtime(), check_gh_auth(), checkout_failure]
    if args.agent == "codex":
        checks.append(check_codex_update_prompt())
    failures = [msg for msg in checks if msg]
    if not failures:
        print("preconditions: ok")
        print(f"skill-checkout: {checkout}")
        return 0
    for msg in failures:
        print(f"STOP: {msg}")
    print("Stop and report this to the user. Do not work around it.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
