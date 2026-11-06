#!/usr/bin/env python3
"""Check the preconditions for running orca-issue-coordinator.

Checks:
  1. This process runs inside an Orca terminal (ORCA_TERMINAL_HANDLE is set),
     so ORCA Orchestration can identify the Coordinator as the sender.
  2. The Orca executable the Coordinator selected (`--orca`, a name or a path)
     resolves to an absolute path, its runtime is reachable
     (`<orca> status --json`), and it advertises
     `orchestration.worker-auto-release.v1`. Only that candidate is tried;
     a failure never falls back to another executable.
  3. GitHub CLI authentication works (`gh auth status`).
  4. The git checkout this skill is installed from (the symlink source) is on
     branch `main` and matches `origin/main`: it is neither behind it nor
     carrying commits that are not on it, and its skills have no uncommitted
     changes, so the Coordinator and its workers run the latest skills. A
     detached HEAD may be a pin a previous Run left behind; the failure shows
     the `local_main.py finish` command that restores it.

Exit status: 0 when every check passes, 1 when any check fails. On failure the
Coordinator must stop and report to the user; it must not work around it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TIMEOUT_SECONDS = 60
AUTO_RELEASE_CAPABILITY = "orchestration.worker-auto-release.v1"
# Resolving follows the ~/.agents/skills symlink to the real checkout.
SKILL_DIR = Path(__file__).resolve().parents[1]
# An explicit refspec updates origin/main whatever remote.origin.fetch says.
MAIN_REFSPEC = "+refs/heads/main:refs/remotes/origin/main"


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


def resolve_orca(selected: str) -> tuple[str | None, str | None]:
    """Return (absolute executable path, failure message) for the selected Orca CLI."""
    found = shutil.which(selected)
    if found is None:
        return None, (f"the selected Orca executable `{selected}` cannot be resolved; "
                      "do not fall back to another executable")
    return os.path.abspath(found), None


def check_orca_runtime(orca: str) -> str | None:
    code, out = run([orca, "status", "--json"])
    if code != 0:
        return f"`{orca} status --json` failed (exit {code}): {out}"
    try:
        runtime = json.loads(out)["result"]["runtime"]
        reachable = bool(runtime["reachable"])
        capabilities = runtime.get("capabilities", [])
    except (ValueError, KeyError, TypeError, AttributeError):
        return f"`{orca} status --json` returned unexpected output: {out[:200]}"
    if not reachable:
        return f"the Orca runtime is not reachable (`{orca} status --json`)"
    if not isinstance(capabilities, list) or AUTO_RELEASE_CAPABILITY not in capabilities:
        return (f"the Orca runtime does not advertise {AUTO_RELEASE_CAPABILITY}; "
                "ask the user to update Orca")
    return None


def check_gh_auth() -> str | None:
    code, out = run(["gh", "auth", "status"])
    if code != 0:
        return f"`gh auth status` failed (exit {code}): {out}"
    return None


def check_checkout_branch(checkout: str) -> str | None:
    """Return a failure message unless the skill checkout's HEAD is on branch main."""
    code, out = run(["git", "-C", checkout, "symbolic-ref", "-q", "--short", "HEAD"])
    if code == 0:
        branch = out.splitlines()[-1].strip() if out else ""
        if branch == "main":
            return None
        return (f"the skill checkout {checkout} is on branch `{branch}`, not `main`; "
                "ask the user to switch it to `main`")
    if code != 1:
        return (f"`git symbolic-ref HEAD` failed in the skill checkout {checkout} "
                f"(exit {code}): {out}")
    code, out = run(["git", "-C", checkout, "rev-parse", "HEAD"])
    if code != 0:
        return f"`git rev-parse HEAD` failed in the skill checkout {checkout} (exit {code}): {out}"
    sha = out.splitlines()[-1].strip()
    return (f"the skill checkout {checkout} is detached at {sha}; a previous Run may have left "
            "it pinned. Ask the user to restore it with `uv run --no-project "
            "~/.agents/skills/orca-issue-coordinator/scripts/local_main.py finish "
            f"--frozen {sha} --repo {checkout}`")


def check_skill_checkout() -> tuple[str | None, str | None]:
    """Return (checkout path, failure message) for the skill's source checkout."""
    code, out = run(["git", "-C", str(SKILL_DIR), "rev-parse", "--show-toplevel"])
    if code != 0:
        return None, f"{SKILL_DIR} is not inside a git checkout (exit {code}): {out}"
    checkout = out.splitlines()[-1].strip()
    branch_failure = check_checkout_branch(checkout)
    if branch_failure:
        return checkout, branch_failure
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


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--orca", required=True,
                        help="the Orca executable selected for this session (name or path)")
    args = parser.parse_args(argv)
    checkout, checkout_failure = check_skill_checkout()
    orca, orca_failure = resolve_orca(args.orca)
    checks = [check_orca_terminal(), orca_failure or check_orca_runtime(orca), check_gh_auth(),
              checkout_failure]
    failures = [msg for msg in checks if msg]
    if not failures:
        print("preconditions: ok")
        print(f"skill-checkout: {checkout}")
        print(f"orca-executable: {orca}")
        return 0
    for msg in failures:
        print(f"STOP: {msg}")
    print("Stop and report this to the user. Do not work around it.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
