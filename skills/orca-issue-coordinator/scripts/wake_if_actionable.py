#!/usr/bin/env python3
"""Wake the Codex Coordinator terminal only when the Run needs it.

Used as the precheck of the Codex waiting automation. It reads Orca state and
the Run checkpoint without starting a model, and sends the wake text to the
Coordinator terminal only when one of these holds:

  message   an unread worker_done / escalation / question for the Coordinator
  worker    worker-list reports a worker that requires action
  idle      no worker is in progress while Tasks remain
  deadline  a `wake-at:` time in the checkpoint has passed
  safety    --safety-minutes elapsed since the last wake
  error     an orca call failed or the checkpoint cannot be read

A condition already seen on the previous run does not wake again until it
clears and returns; the safety interval still wakes. Prints one JSON line and
always exits non-zero so the automation never starts its own agent:

  1  nothing new; no input was sent
  2  the wake text was sent
  3  a wake was needed but sending it failed
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WAKE_TYPES = "worker_done,escalation,question"
DONE_TASK_STATES = {"completed", "failed", "cancelled", "canceled"}
WAKE_AT = re.compile(r"^\s*(?:[-*]\s+)?`?wake-at:\s*(\S+?)`?(?:\s+(.*))?$")
STATE_FILE = "wake-state.json"
EXIT_IDLE, EXIT_SENT, EXIT_SEND_FAILED = 1, 2, 3


def run_orca(orca: str, args: list[str], timeout_s: float = 60) -> dict:
    proc = subprocess.run(
        [orca, *args],
        capture_output=True,
        timeout=timeout_s,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        tail = (proc.stdout or proc.stderr or "").strip()[-300:]
        raise RuntimeError(f"orca {args[1]} exited {proc.returncode}: {tail}")
    if not data.get("ok", False):
        err = data.get("error") or data
        raise RuntimeError(f"orca {args[1]} failed: {json.dumps(err, ensure_ascii=False)[:300]}")
    return data.get("result") or {}


def message_reasons(orca: str, terminal: str, run: str) -> list[str]:
    result = run_orca(orca, ["orchestration", "check", "--terminal", terminal, "--run", run,
                             "--peek", "--types", WAKE_TYPES, "--json"])
    return [f"message:{m.get('type')}:{m.get('id')}" for m in result.get("messages") or []
            if m.get("type") in WAKE_TYPES.split(",")]


def worker_reasons(orca: str, run: str) -> list[str]:
    workers = run_orca(orca, ["orchestration", "worker-list", "--run", run, "--json"]
                       ).get("workers") or []
    reasons, in_progress = [], 0
    for w in workers:
        proj = w.get("projection") or {}
        if proj.get("outcome") == "in_progress":
            in_progress += 1
        att = proj.get("attention") or {}
        nxt = proj.get("nextAction") or {}
        if att.get("requiresAction") or nxt.get("kind") not in (None, "none"):
            categories = ",".join(sorted(att.get("categories") or [])) or "-"
            reasons.append(f"worker:{w.get('dispatchId')}:{categories}:{nxt.get('kind') or 'none'}")
    if in_progress == 0:
        tasks = run_orca(orca, ["orchestration", "task-list", "--run", run, "--json"]
                         ).get("tasks") or []
        remaining = sorted(t.get("id") for t in tasks if t.get("status") not in DONE_TASK_STATES)
        if remaining:
            reasons.append("idle:" + ",".join(remaining))
    return reasons


def parse_time(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return value if value.tzinfo else value.astimezone()


def deadline_reasons(checkpoint: Path, now: datetime) -> list[str]:
    reasons = []
    for line in checkpoint.read_text(encoding="utf-8").splitlines():
        match = WAKE_AT.match(line)
        if not match:
            continue
        try:
            due = parse_time(match.group(1))
        except ValueError:
            raise ValueError(f"unparseable wake-at time: {match.group(1)}")
        if due <= now:
            reasons.append(f"deadline:{match.group(1)} {(match.group(2) or '').strip()}".rstrip())
    return reasons


def load_state(path: Path, checkpoint: Path) -> tuple[datetime, set[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return parse_time(data["last_wake"]), set(data.get("seen") or [])
    except (OSError, ValueError, KeyError, TypeError):
        # First run: the Coordinator last acted when it wrote the checkpoint.
        try:
            return datetime.fromtimestamp(checkpoint.stat().st_mtime, timezone.utc), set()
        except OSError:
            return datetime.now(timezone.utc), set()


def save_state(path: Path, last_wake: datetime, seen: list[str]) -> None:
    try:
        path.write_text(json.dumps({"last_wake": last_wake.isoformat(), "seen": seen}) + "\n",
                        encoding="utf-8")
    except OSError:
        pass


def send_wake(orca: str, terminal: str, text: str) -> bool:
    try:
        completed = subprocess.run(
            [orca, "terminal", "send", "--terminal", terminal, "--text", text, "--enter"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        return completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--terminal", required=True, help="Coordinator terminal handle")
    ap.add_argument("--run", required=True, help="Orchestration Run id")
    ap.add_argument("--checkpoint", required=True, type=Path,
                    help="absolute path of the Run checkpoint (tmp/<run-id>/coordinator.md)")
    ap.add_argument("--text", required=True, help="wake text sent to the Coordinator terminal")
    ap.add_argument("--orca", default=shutil.which("orca") or "orca",
                    help="resolved Orca executable absolute path")
    ap.add_argument("--safety-minutes", type=float, default=60,
                    help="wake at least this often even when nothing changed (default 60)")
    opts = ap.parse_args()

    now = datetime.now(timezone.utc)
    state_path = opts.checkpoint.parent / STATE_FILE
    last_wake, seen = load_state(state_path, opts.checkpoint)

    reasons: list[str] = []
    errors: list[str] = []
    checks = (
        ("check", lambda: message_reasons(opts.orca, opts.terminal, opts.run)),
        ("worker-list", lambda: worker_reasons(opts.orca, opts.run)),
        ("checkpoint", lambda: deadline_reasons(opts.checkpoint, now)),
    )
    for name, check in checks:
        try:
            reasons += check()
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
            reasons.append(f"error:{name}")
            errors.append(f"{name}: {exc}")

    new = [r for r in reasons if r not in seen]
    if now - last_wake >= timedelta(minutes=opts.safety_minutes):
        new.append(f"safety:{opts.safety_minutes:g}m")

    result: dict = {"wake": bool(new), "reasons": new, "sent": None}
    if errors:
        result["errors"] = errors
    code = EXIT_IDLE
    if new:
        result["sent"] = send_wake(opts.orca, opts.terminal, opts.text)
        if result["sent"]:
            last_wake = now
            code = EXIT_SENT
        else:
            # Keep the previous view so the next run retries these conditions.
            reasons = sorted(seen)
            code = EXIT_SEND_FAILED
    save_state(state_path, last_wake, sorted(set(reasons)))
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
