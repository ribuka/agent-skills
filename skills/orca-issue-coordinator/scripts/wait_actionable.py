#!/usr/bin/env python3
"""Wait for actionable ORCA orchestration mail without waking the coordinator.

Loops `orca orchestration check --wait --types worker_done,escalation,question`
and exits only when the coordinator has something to act on:

  0  actionable messages arrived (bodies printed in full; the Delivery is NOT acked)
  3  worker-list reports a worker that requires action
  4  worker-list reports no in-progress worker for the Run
  5  --max-minutes elapsed with nothing actionable
  2  an orca call failed

Delivery batches that contain only heartbeats are acknowledged automatically.
Any other batch is left unacknowledged so the coordinator can process every
row before running `check --ack <delivery_id>` itself.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time

WAKE_TYPES = "worker_done,escalation,question"
FULL_BODY_TYPES = set(WAKE_TYPES.split(","))
AUTO_ACK_TYPES = {"heartbeat"}
BODY_CHARS = 300


def out(line: str = "") -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def run_orca(orca: str, args: list[str], timeout_s: float) -> dict:
    proc = subprocess.run(
        [orca, *args],
        capture_output=True,
        timeout=timeout_s,
        encoding="utf-8",
        errors="replace",
    )
    # stdout holds one JSON document; stderr carries keepalive lines only.
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        tail = (proc.stdout or proc.stderr or "").strip()[-500:]
        raise RuntimeError(f"orca {args[1]} exited {proc.returncode}: {tail}")
    if not data.get("ok", False):
        err = data.get("error") or data
        raise RuntimeError(f"orca {args[1]} failed: {json.dumps(err, ensure_ascii=False)[:500]}")
    return data.get("result") or {}


def payload_of(msg: dict) -> dict:
    raw = msg.get("payload")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def one_line(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def print_delivery(result: dict) -> None:
    messages = result.get("messages") or []
    skipped = [m for m in messages if m.get("type") in AUTO_ACK_TYPES]
    shown = [m for m in messages if m.get("type") not in AUTO_ACK_TYPES]
    out(f"ACTIONABLE delivery={result.get('deliveryId')} messages={len(messages)} "
        f"heartbeats={len(skipped)}")
    for m in shown:
        p = payload_of(m)
        fields = [
            f"type={m.get('type')}",
            f"id={m.get('id')}",
            f"task={p.get('taskId')}",
            f"dispatch={p.get('dispatchId')}",
        ]
        if p.get("outcome"):
            fields.append(f"outcome={p['outcome']}")
        out("- " + " ".join(fields))
        out(f"  subject: {one_line(m.get('subject', ''), 120)}")
        body = m.get("body")
        if not body:
            continue
        if m.get("type") in FULL_BODY_TYPES:
            # Handoff fields (PR URL, review-count, CI status) must survive intact.
            out("  body: |")
            for line in body.strip("\n").splitlines():
                out(f"    {line}".rstrip())
        else:
            out(f"  body: {one_line(body, BODY_CHARS)}")
    out("Process every row, then: orca orchestration check --ack "
        f"{result.get('deliveryId')} --json")


def inspect_workers(orca: str, base: list[str]) -> int | None:
    args = ["orchestration", "worker-list", "--json"]
    if "--run" in base:
        args += base[base.index("--run"):base.index("--run") + 2]
    result = run_orca(orca, args, 120)
    workers = result.get("workers") or []
    attention, in_progress = [], 0
    for w in workers:
        proj = w.get("projection") or {}
        if proj.get("outcome") == "in_progress":
            in_progress += 1
        att = proj.get("attention") or {}
        nxt = proj.get("nextAction") or {}
        if att.get("requiresAction") or nxt.get("kind") not in (None, "none"):
            attention.append((w, proj, att, nxt))
    if attention:
        out(f"WORKER-ATTENTION workers={len(workers)} needing_action={len(attention)}")
        for w, proj, att, nxt in attention:
            out(f"- dispatch={w.get('dispatchId')} task={w.get('taskId')} "
                f"outcome={proj.get('outcome')} liveness={(proj.get('liveness') or {}).get('verdict')} "
                f"categories={','.join(att.get('categories') or []) or '-'}")
            if nxt.get("argv"):
                out(f"  nextAction: {' '.join(nxt['argv'])}")
        return 3
    if in_progress == 0:
        out(f"NO-ACTIVE-WORKERS workers={len(workers)}; check task-list and worker-list.")
        return 4
    return None


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--timeout-ms", type=int, default=900_000,
                    help="timeout of one check --wait call (default 900000)")
    ap.add_argument("--max-minutes", type=float, default=240,
                    help="give up after this many minutes (default 240)")
    ap.add_argument("--empty-waits", type=int, default=3,
                    help="consecutive empty waits before inspecting worker-list (default 3)")
    ap.add_argument("--terminal", help="coordinator terminal handle (outside an Orca terminal)")
    ap.add_argument("--run", help="Run id (defaults to the bound Run)")
    ap.add_argument("--orca", default=shutil.which("orca") or "orca", help="orca executable")
    opts = ap.parse_args()

    base: list[str] = []
    if opts.terminal:
        base += ["--terminal", opts.terminal]
    if opts.run:
        base += ["--run", opts.run]

    deadline = time.monotonic() + opts.max_minutes * 60
    pending_ack: str | None = None
    empty = 0
    acked_heartbeats = 0
    try:
        while True:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                out(f"TIMEOUT after {opts.max_minutes:g} min; heartbeats_acked={acked_heartbeats}")
                if pending_ack:
                    out(f"Unacked heartbeat-only delivery: {pending_ack}")
                return 5
            wait_ms = min(opts.timeout_ms, remaining_ms)
            args = ["orchestration", "check", *base]
            if pending_ack:
                args += ["--ack", pending_ack]
            args += ["--wait", "--types", WAKE_TYPES, "--timeout-ms", str(wait_ms), "--json"]
            result = run_orca(opts.orca, args, wait_ms / 1000 + 120)
            pending_ack = None
            messages = result.get("messages") or []

            if messages and all(m.get("type") in AUTO_ACK_TYPES for m in messages):
                pending_ack = result.get("deliveryId")
                acked_heartbeats += len(messages)
                continue
            if messages:
                print_delivery(result)
                return 0

            empty += 1
            if empty >= opts.empty_waits:
                empty = 0
                code = inspect_workers(opts.orca, base)
                if code is not None:
                    return code
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        out(f"ERROR {exc}")
        if pending_ack:
            out(f"Unacked heartbeat-only delivery: {pending_ack}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
