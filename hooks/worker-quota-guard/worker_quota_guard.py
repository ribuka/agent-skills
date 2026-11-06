"""PreToolUse hook: stop an Orca worker's tool calls once the 5-hour quota is paused.

Claude Code and Codex share one 5-hour quota between a Coordinator and all of
its workers, and only the Coordinator checks it, at its own boundaries. This
hook lets each worker stop itself:

1. Outside Orca (no `ORCA_TERMINAL_HANDLE`) it allows everything.
2. It runs `quota_guard.py check --provider <provider>` without `--threshold`,
   so the threshold is always quota-guard's own. Exit 0 (READY) and UNKNOWN
   allow the call; only PAUSED_QUOTA continues.
3. A shell command whose every simple command matches an `ALLOW_COMMAND`
   pattern in `config.conf` is allowed (the commands a worker needs to reach a
   safe boundary and report).
4. Otherwise, if this terminal runs an open Orca worker Dispatch
   (`orca orchestration worker-list`), the call is denied with a reason;
   Coordinator and Standalone terminals are not workers and are allowed.

The threshold and the allowed commands live in quota-guard and `config.conf`,
never in this script. A missing or unreadable `config.conf` allows every call
and warns on stderr. The hook keeps no state, so running it twice for one tool
call gives the same result.

Usage (registered as a PreToolUse command): worker_quota_guard.py --provider claude|codex
Reads the hook input (JSON) from stdin; prints a deny decision or nothing; exits 0.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG = Path(__file__).resolve().parent / "config.conf"
CONFIG_KEYS = {"QUOTA_GUARD", "SHELL_TOOL", "ALLOW_COMMAND"}
QUOTA_TIMEOUT_SECONDS = 30
ORCA_TIMEOUT_SECONDS = 15
MAX_WORKER_PAGES = 5
SEPARATORS = ";&|()\n\r`"


class ConfigError(Exception):
    """config.conf is missing or invalid."""


def load_config(path: Path) -> dict[str, list[str]]:
    """Parse KEY=VALUE lines; repeated keys accumulate in order."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(f"cannot read {path}: {error}") from None
    values: dict[str, list[str]] = {key: [] for key in CONFIG_KEYS}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or key not in CONFIG_KEYS or not value:
            raise ConfigError(f"{path}:{number}: invalid line: {raw}")
        if key == "ALLOW_COMMAND":
            try:
                re.compile(value)
            except re.error as error:
                raise ConfigError(f"{path}:{number}: invalid regex: {error}") from None
        values[key].append(value)
    if len(values["QUOTA_GUARD"]) != 1:
        raise ConfigError(f"{path}: QUOTA_GUARD must be set exactly once")
    return values


def split_commands(command: str) -> list[str]:
    """Split a shell command into simple commands at unquoted separators.

    Quotes keep their content (including newlines) in one command; each
    command's whitespace is collapsed to single spaces.
    """
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    for char in command:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char in SEPARATORS:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [" ".join(part.split()) for part in parts if part.strip()]


def command_allowed(command: str, patterns: list[str]) -> bool:
    """Return True when every simple command matches an allowed pattern."""
    commands = split_commands(command)
    return bool(commands) and all(
        any(re.match(pattern, simple) for pattern in patterns) for simple in commands)


def run(cmd: list[str], timeout: int) -> tuple[int, str]:
    """Run a command and return (exit code, stdout); failures return (-1, "")."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""
    return proc.returncode, proc.stdout


def quota_paused(quota_guard: str, provider: str) -> dict | None:
    """Return the check result when the state is PAUSED_QUOTA, else None."""
    path = str(Path(quota_guard).expanduser())
    code, out = run([sys.executable, path, "check", "--provider", provider],
                    QUOTA_TIMEOUT_SECONDS)
    if code == 0:
        return None
    try:
        result = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    return result if isinstance(result, dict) and result.get("state") == "PAUSED_QUOTA" else None


def is_open_worker(terminal: str) -> bool:
    """Return True when this terminal runs an Orca worker Dispatch still in progress."""
    orca = shutil.which("orca")
    if orca is None:
        return False
    cursor = None
    for _ in range(MAX_WORKER_PAGES):
        cmd = [orca, "orchestration", "worker-list", "--limit", "100", "--json"]
        code, out = run([*cmd, *(["--cursor", cursor] if cursor else [])], ORCA_TIMEOUT_SECONDS)
        try:
            result = json.loads(out)["result"]
            workers = result["workers"]
        except (ValueError, KeyError, TypeError):
            return False
        if code != 0 or not isinstance(workers, list):
            return False
        if any(isinstance(w, dict) and w.get("terminal") == terminal
               and w.get("outcome") == "in_progress" for w in workers):
            return True
        cursor = result.get("nextCursor")
        if not isinstance(cursor, str) or not cursor:
            return False
    return False


def deny(reason: str) -> None:
    """Print a PreToolUse deny decision."""
    decision = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }
    json.dump({"hookSpecificOutput": decision}, sys.stdout, ensure_ascii=True)


def main(argv: list[str] | None = None) -> int:
    """Read the hook input from stdin and print a deny decision when needed."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", required=True, choices=("claude", "codex"))
    opts = parser.parse_args(argv)
    data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    terminal = os.environ.get("ORCA_TERMINAL_HANDLE")
    if not terminal:
        return 0
    try:
        config = load_config(CONFIG)
    except ConfigError as error:
        print(f"worker-quota-guard: {error}; allowing every tool call", file=sys.stderr)
        return 0
    quota = quota_paused(config["QUOTA_GUARD"][0], opts.provider)
    if quota is None:
        return 0
    command = (data.get("tool_input") or {}).get("command")
    if data.get("tool_name") in config["SHELL_TOOL"] and isinstance(command, str) \
            and command_allowed(command, config["ALLOW_COMMAND"]):
        return 0
    if not is_open_worker(terminal):
        return 0
    deny("worker-quota-guard: the 5-hour quota is PAUSED_QUOTA, so this Orca worker must "
         "stop. Stop at a safe boundary (commit and push finished changes, or let a "
         "running review finish; leave uncommitted changes in the worktree) and report "
         "with worker_done. Until the quota resets, only the commands allowed in "
         f"{CONFIG} run. quota: {json.dumps(quota, ensure_ascii=True)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
