#!/usr/bin/env python3
"""List every worker of one Orca Run from the detailed worker-list.

Runs `<orca> orchestration worker-list --run <run-id> --json --full` and
follows `result.page.nextCursor` until `result.page.hasMore` is false, so no
worker on a later page is missed. Every page must be a successful detailed
receipt; a CLI error, malformed JSON, an incomplete host inventory, or a
worker row without the fields below is an error, never an empty list.

Output: one JSON line per worker
`{"dispatch", "task", "state", "terminalState", "liveness", "autoReleaseAt", "next"}`
where `next` is the worker's next action as an argument list starting with
the Orca executable (`[]` when Orca expects nothing), then one summary line
`{"workers": <n>, "pages": <n>}`. On failure it prints one JSON line
`{"error": "<reason>"}` instead of the summary.

Exit status: 0 the list is complete, 1 the list could not be read completely.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from typing import Any

TIMEOUT_SECONDS = 60
MAX_PAGES = 100
TERMINAL_STATES = ("active", "reclaimable", "retained", "release_pending", "release_unknown",
                   "released")


class ListError(Exception):
    """The worker list could not be read completely."""


def run(cmd: list[str]) -> tuple[int, str]:
    """Run a command and return its exit code and stdout (stderr is dropped)."""
    exe = shutil.which(cmd[0])
    if exe is None:
        return 127, ""
    try:
        proc = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return 124, ""
    return proc.returncode, proc.stdout


def worker_row(worker: Any, orca: str) -> dict[str, Any]:
    """Return the compact row for one detailed worker record."""
    if not isinstance(worker, dict):
        raise ListError("a worker row is not an object")
    projection, resource = worker.get("projection"), worker.get("resource") or {}
    for key in ("dispatchId", "taskId", "workerState"):
        if not isinstance(worker.get(key), str):
            raise ListError(f"a worker row is missing {key}")
    try:
        argv = projection["nextAction"]["argv"]
        liveness = projection["liveness"]["verdict"]
    except (KeyError, TypeError) as error:
        raise ListError(f"worker {worker['dispatchId']} has no projection {error}") from None
    if not isinstance(argv, list) or not all(isinstance(arg, str) for arg in argv):
        raise ListError(f"worker {worker['dispatchId']} has a malformed nextAction")
    if argv[:1] == ["orca"]:
        argv = argv[1:]
    return {
        "dispatch": worker["dispatchId"],
        "task": worker["taskId"],
        "state": worker["workerState"],
        "terminalState": worker.get("terminalState"),
        "liveness": liveness,
        "autoReleaseAt": projection.get("autoReleaseAt") or (
            resource.get("autoReleaseAt") if isinstance(resource, dict) else None),
        "next": [orca, *argv] if argv else [],
    }


def list_workers(orca: str, run_id: str, terminal_state: str | None) -> tuple[list[dict], int]:
    """Return (rows, pages) for every worker of the Run."""
    base = [orca, "orchestration", "worker-list", "--run", run_id, "--limit", "100"]
    if terminal_state:
        base += ["--terminal-state", terminal_state]
    rows: list[dict] = []
    cursor: str | None = None
    seen: set[str] = set()
    for page_number in range(1, MAX_PAGES + 1):
        cmd = [*base, *(["--cursor", cursor] if cursor else []), "--json", "--full"]
        code, out = run(cmd)
        if code != 0:
            raise ListError(f"worker-list exited {code} on page {page_number}")
        try:
            response = json.loads(out)
            result = response["result"]
            workers, page = result["workers"], result["page"]
        except (ValueError, KeyError, TypeError):
            raise ListError(f"worker-list page {page_number} is not a detailed receipt") from None
        if response.get("ok") is not True or not isinstance(workers, list) \
                or not isinstance(page, dict):
            raise ListError(f"worker-list page {page_number} is not a successful receipt")
        if result.get("partialHostErrors"):
            raise ListError("worker-list reports an incomplete host inventory")
        rows.extend(worker_row(worker, orca) for worker in workers)
        if not isinstance(page.get("hasMore"), bool):
            raise ListError(f"worker-list page {page_number} has no boolean page.hasMore")
        if not page["hasMore"]:
            return rows, page_number
        cursor = page.get("nextCursor")
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise ListError(f"worker-list page {page_number} has more rows but no new nextCursor")
        seen.add(cursor)
    raise ListError(f"worker-list has more than {MAX_PAGES} pages")


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--orca", required=True, help="absolute Orca executable path")
    parser.add_argument("--run", required=True, help="the Orchestration Run ID")
    parser.add_argument("--terminal-state", choices=TERMINAL_STATES)
    opts = parser.parse_args(argv)
    try:
        rows, pages = list_workers(opts.orca, opts.run, opts.terminal_state)
    except ListError as error:
        print(json.dumps({"error": str(error)}))
        return 1
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    print(json.dumps({"workers": len(rows), "pages": pages}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
