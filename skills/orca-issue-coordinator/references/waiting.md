# Waiting, receiving, and timed wake-ups

Use this for both Claude Code and Codex Coordinators. `<orca>`, `<handle>`,
`<run-id>`, `<agent>`, and `<quota-check>` mean the same as in `SKILL.md`;
`<orca>` is always the absolute path printed as `orca-executable:`.

## Wait by ending the turn

After starting every worker the Run can start within `MAX_WORKERS`, save the
checkpoint (below) and **end the turn**. Orca wakes this terminal when a worker
reports. Never wait in a tool call:

- No waiter, watcher, or polling script, in the foreground or the background,
  and no `check --wait` or repeated `check`: a plain `check` takes the mail,
  so Orca has nothing left to wake you with.
- No timed wake-up whose only purpose is to see whether workers are alive or
  to wait for a worker message or a user answer. Only the times in
  **Timed wake-ups** get one.
- No `gh pr checks --watch` (foreground or background) and no sleep loop.

## Receive messages

- A notification that carries the whole message: act on it as it is.
- A notification that names a `check` command: run exactly that command (its
  terminal and Run), once. A consuming `check` marks the batch it returns as
  read; there is no `--ack` step. Process every row of that batch before the
  next `check`.
- `worker_done`: record its handoff fields; verify the report before acting on
  it. A failed `worker_done` settles the Task as failed: never treat it as
  succeeded or mark the Task completed.
- `question`: answer it with `<orca> orchestration reply --id <message-id> --body "<answer>"`
  following `SKILL.md` **Answering worker questions**.
- `escalation` with `stopReason`: the worker stopped without `worker_done`.
  Load Orca's `references/recovery-and-cleanup.md` and steer it with `send`,
  retry it, or tell the user.
- Heartbeats or other notifications carry no work by themselves. Do not assume
  how often they arrive or what their text says.
- A lost `check` response: rerun it with the `--retry-request <id>` it printed.
- After losing context (compaction, a new conversation), recover mail that was
  already read with `<orca> orchestration inbox --terminal run:<run-id> --limit 50`;
  add `--full` only when a preview cuts off a body you need. Mail being read
  does not mean it was processed: compare it with the checkpoint.

## Checkpoint

Save `tmp/<run-id>/coordinator.md` under the Coordinator's working repository
root (git-ignored, not the installed skill checkout) and use its absolute path
everywhere. Update it before ending every turn and right after every
`worker-start`, merge, or reservation change. It holds:

- Run ID, Coordinator terminal handle, agent, absolute `<orca>` path, and the
  resolved worker settings.
- Per Task: phase, dispatch ID, worktree, branch, PR URL, review count, open
  findings, blockers, and the IDs of the messages already processed.
- Pending CI: PR, head SHA, and absolute deadline.
- Every pending time as its own line
  `wake-at: <ISO-8601 time with offset> <reason>` (e.g.
  `wake-at: 2026-10-16T14:05:00+09:00 ci #84`), and the current reservation
  as `reservation: <id> <time>` or `reservation: none`.

## Timed wake-ups

Only these times get a reservation: the next pending-CI inspection
(**Pending CI**), a reviewer quota retry (`review-quota-retry.md`), and the
Coordinator's own quota resumption (`quota-pause.md`). Keep **at most one**
future reservation per Run, at the earliest `wake-at:` time:

- While the quota is paused, `quota-guard:<run-id>` (from `quota-pause.md`) is
  the only reservation: remove `coordinator-wait:<run-id>` first and keep its
  `wake-at:` lines in the checkpoint.
- Otherwise use one reservation named `coordinator-wait:<run-id>`. When the
  earliest `wake-at:` time changes or none remains, remove the old reservation,
  confirm it is gone, then create the new one (or record `reservation: none`).
  If removal fails, resolve that before creating another. Never touch another
  Run's reservations.

Wake text (the same for both agents):
`Resume the existing Run <run-id> from <absolute-checkpoint-path>. Follow ~/.agents/skills/orca-issue-coordinator/references/waiting.md: check quota first, reconcile once, then end the turn if still waiting.`

**Claude Code:** run `CronList` and look for `coordinator-wait:<run-id>`; remove
an obsolete one with `CronDelete`. Create one one-shot (`recurring: false`)
`CronCreate` at the time, in the scheduler's local timezone, whose prompt
contains the marker `coordinator-wait:<run-id>` and the wake text. A fired
one-shot is gone.

**Codex:** use an Orca automation; do not use `CronCreate` / `CronList`.
Check `<orca> automations list --json` first and remove an obsolete
`coordinator-wait:<run-id>` with `<orca> automations remove <id>`. Do not load
`orca-cli` or read `automations create --help`; this command is complete
(POSIX quoting shown; use literal quoting for the invoking shell, doubling
embedded single quotes in PowerShell):

```sh
<orca> automations create --name 'coordinator-wait:<run-id>' \
  --trigger '<minute> <hour> <day> <month> *' --timezone '<local-IANA-timezone>' \
  --provider codex --prompt 'Unused: precheck always exits nonzero' \
  --precheck 'uv run --no-project "<absolute-quota-guard-dir>/scripts/quota_guard.py" wake --orca "<orca>" --terminal "<handle>" --text "<wake text>"' \
  --precheck-timeout 120 --workspace 'path:<absolute-repo-path>' \
  --missed-run-grace-minutes 60 --enabled
```

`quota-guard`'s `wake` sends the text to the Coordinator terminal and always
exits non-zero, so no separate automation agent starts. It does not read the
inbox or worker state. Record the returned ID and verify it with
`automations list`. The five-field cron recurs every year, so the first thing a
woken Codex Coordinator does is remove that automation (**On every resume**).
If the automation cannot be created, report that resumption at that time must
be manual.

## On every resume

A notification, a user message, or a timed wake-up all resume the Run the same
way. If one arrives during an active turn, finish the current operation first.

1. If the quota is paused, follow `quota-pause.md` first.
2. If a `coordinator-wait:<run-id>` time has come: in Codex remove that
   automation now (resolve a failure before creating another); in Claude Code
   it is already gone. Record `reservation: none`.
3. Run `<quota-check>`; continue only on exit `0` (see `SKILL.md`
   **Quota control**).
4. Process the messages as in **Receive messages**.
5. Reconcile once: compare the checkpoint with live state (`list_workers.py`
   from `SKILL.md`, `task-list`, PRs). Never repeat a dispatch, phase, or
   merge the checkpoint or live state shows as done or in progress; a second
   wake for the same event is not a new event.
6. Handle due `wake-at:` times (pending CI, a reviewer retry per
   **On wake-up** in `review-quota-retry.md`), then start ready work within
   quota and `MAX_WORKERS`.
7. Set the reservation to the earliest remaining `wake-at:` time (none if
   nothing remains), save the checkpoint, and end the turn. If a question to
   the user is pending, end with the reminder line from `SKILL.md`
   **Asking the user**.

A missing notification, silence, a timeout, or `unverifiable` liveness alone
is never a reason to stop, retry, abandon, or release a worker.

## Pending CI

Run `gh pr checks <pr>` once. Exit `8` means pending: record the PR, its head
SHA, and an absolute deadline 30 minutes after the first pending observation,
add `wake-at:` for the earlier of 15 minutes from now and the deadline, update
the reservation, and end the turn. On that wake-up inspect the PR once more
the same way; never reset the deadline on a later wake or after a context
restart. If the deadline passes while CI is still pending, report
`monitor-error: CI deadline exceeded` and block the PR. Other errors and failed
or cancelled checks also block it; an empty check set is not success. Recheck
the current head and all checks immediately before merging; a new head needs
fresh review, test, and sync verification.

## Run completion

Remove the Run's reservation (Codex: `<orca> automations remove <id>`; Claude
Code: `CronDelete`) and confirm it is gone before `SKILL.md` step 17 deletes
the Run's files. Report a removal that keeps failing instead of leaving it.
