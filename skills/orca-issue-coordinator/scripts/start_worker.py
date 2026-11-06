#!/usr/bin/env python3
"""Start one Orca worker and judge the result from the detailed receipt.

Runs `<orca> orchestration worker-start <args> --json --full` once and
classifies the receipt by its `state` / `stage` / `turnStart` fields, never by
worker-start's exit code (with --full it exits 1 for anything but ready):

  ready       state "ready" with a dispatch ID and `launch.effective`.
  unobserved  state "outcome_unknown" whose turn start was not yet observed:
              the task was typed in; record the dispatch and end the turn.
  failed      state "failed" or any other "outcome_unknown": do not rerun.
  invalid     no JSON, an error envelope, or a field the decision needs is
              missing or malformed: treat it as a failed start; do not rerun.

A ready start whose `launch.effective` model or effort differs from the
requested `--model` / `--effort` is reported as `launch-mismatch`.

Output: `start: <class>` followed by the fields the Coordinator records
(`dispatch`, `task`, `run`, `effective`, `failed-stage`, `error`, `next`,
`next-command`). Exit status: 0 ready, 1 failed, 2 invalid, 3 unobserved,
4 ready with a launch mismatch.
"""

from __future__ import annotations

import argparse
import json
import sys

from orca_command import run_stdout

TIMEOUT_SECONDS = 900
EXIT = {"ready": 0, "failed": 1, "invalid": 2, "unobserved": 3, "mismatch": 4}
OWN_FLAGS = ("--json", "--full")


def option(args: list[str], name: str) -> str | None:
    """Return the value of `name` in a worker-start argument list."""
    for i, arg in enumerate(args):
        if arg == name and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return None


def classify(out: str, requested: dict[str, str | None]) -> tuple[str, list[str]]:
    """Return (class, output lines) for a worker-start --json --full receipt."""
    try:
        result = json.loads(out)["result"]
    except (ValueError, KeyError, TypeError):
        return "invalid", ["error: worker-start returned no detailed receipt"]
    if not isinstance(result, dict):
        return "invalid", ["error: worker-start receipt has no result object"]
    state, dispatch = result.get("state"), result.get("dispatchId")
    if not isinstance(state, str) or not isinstance(dispatch, str) or not dispatch:
        return "invalid", ["error: receipt is missing state or dispatchId"]
    lines = [f"dispatch: {dispatch}"]
    for key, label in (("taskId", "task"), ("runId", "run")):
        if isinstance(result.get(key), str):
            lines.append(f"{label}: {result[key]}")
    if state == "ready":
        effective = (result.get("launch") or {}).get("effective") if isinstance(
            result.get("launch"), dict) else None
        if not isinstance(effective, dict):
            return "invalid", [*lines, "error: ready receipt is missing launch.effective"]
        lines.append("effective: " + " ".join(
            f"{key}={effective.get(key)}" for key in ("agent", "model", "effort")))
        mismatched = [key for key, value in requested.items()
                      if value is not None and effective.get(key) != value]
        if mismatched:
            return "mismatch", [*lines, f"launch-mismatch: {','.join(mismatched)}"]
        return "ready", lines
    if state == "outcome_unknown" and (result.get("turnStart") == "unobserved"
                                       or result.get("stage") == "turn_start_unobserved"):
        return "unobserved", lines
    if state not in ("failed", "outcome_unknown"):
        return "invalid", [*lines, f"error: unknown state {state!r}"]
    lines.append(f"state: {state}")
    lines.append(f"failed-stage: {result.get('failedStage') or 'unknown'}")
    if result.get("lastError"):
        lines.append(f"error: {result['lastError']}")
    for key in ("recovery", "next"):
        if isinstance(result.get(key), str) and result[key]:
            lines.append(f"next: {result[key]}")
    for command in result.get("nextCommands") or []:
        lines.append(f"next-command: {command}")
    return "failed", lines


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--orca", required=True, help="absolute Orca executable path")
    parser.add_argument("args", nargs=argparse.REMAINDER,
                        help="worker-start arguments after `--`")
    opts = parser.parse_args(argv)
    args = opts.args[1:] if opts.args[:1] == ["--"] else opts.args
    if not args or any(arg in OWN_FLAGS for arg in args):
        parser.error("pass worker-start arguments after `--`, without --json or --full")
    requested = {"agent": option(args, "--agent"), "model": option(args, "--model"),
                 "effort": option(args, "--effort")}
    _, out = run_stdout([opts.orca, "orchestration", "worker-start", *args, "--json", "--full"],
                        TIMEOUT_SECONDS)
    kind, lines = classify(out, requested)
    print(f"start: {kind}")
    for line in lines:
        print(line)
    return EXIT[kind]


if __name__ == "__main__":
    sys.exit(main())
