# Quota pause and resume

Read this when `<quota-check>` returns PAUSED_QUOTA or UNKNOWN, or when the
Coordinator is woken while a Run is paused. `<quota-check>`, `<run-id>`,
`<orca>`, and `<skill-dir>` mean the same as in `SKILL.md`. While paused, no
new work starts:
no dispatch, merge preparation, merge, or re-dispatch, and the normal rule to
continue other independent Tasks does not apply.

For either agent, UNKNOWN immediately after setup or wake-up permits one local
retry after the returned `local_retry_seconds`, without another model request.
If it remains UNKNOWN, use the provider's scheduled retry below.

## Checkpoint lifecycle

The quota checkpoint lives for the whole Run: create it on the first pause,
update it on later pauses and wake-ups, and keep it after resuming on READY.
Delete it only when the Run completes, with `quota-guard`'s `clear-checkpoint`
command in `SKILL.md` step 17; never delete it by path.

## On PAUSED_QUOTA or UNKNOWN

1. Write the checkpoint to `<run-id>.md` under the result's
   `checkpoint_dir`: Run ID, each Task's
   phase, dispatch ID, worktree, branch, PR URL, review count, blockers,
   and pending actions, plus the quota helper path and state directory.
   For each worker asked to stop, record the work left in that phase.
2. Ask every active worker, through ORCA Orchestration messages sent to its
   Dispatch (`send --to dispatch:<dispatch_id>`, see `SKILL.md`
   **Messaging workers**), to stop at a safe boundary (after a commit/push
   or a finished review, never mid-rebase) and report its state. Verify the
   reported states with `list_workers.py` (`SKILL.md` step 10). Never kill
   worker processes or claim that all work has stopped.
3. For either agent, first remove the Run's `coordinator-wait:<run-id>`
   reservation, if any, and confirm it is gone; keep its `wake-at:` lines in
   the Run checkpoint ([Waiting](waiting.md)). The quota wake-up is then the
   Run's only reservation.
   **Codex:** follow the
   `quota-guard` skill's Codex Orca automation procedure: deduplicate the
   `quota-guard:<run-id>` name, use its `wake` precheck with the saved terminal
   and the absolute `<orca>` from the checkpoint, record the automation ID,
   and verify it.
   Include this reference's installed path and the checkpoint in the wake text.
   On wake-up remove that automation before checking quota. Do not use
   `CronCreate` / `CronList` in Codex.
   **Claude Code:** ensure exactly one wake-up (see **While paused**): if none exists,
   create one one-shot (`recurring: false`) wake-up at the result's
   `cron`, containing the marker `quota-guard:<run-id>`, the checkpoint
   path, the path of this file
   (`~/.agents/skills/orca-issue-coordinator/references/quota-pause.md`),
   and the instruction to follow **On wake-up** in it: run `<quota-check>`,
   reconcile the checkpoint with live `task-list` / `list_workers.py` / PR
   state, and resume this Run only on READY. For UNKNOWN right after setup
   or a wake-up, first wait the result's `local_retry_seconds` and re-run
   `<quota-check>` once (no model request); only if it is still UNKNOWN,
   use its `cron`.
4. End the turn.

If the current agent's scheduler or target terminal is unavailable, keep the checkpoint and tell
the user that manual resumption is required.

## While paused

Whatever wakes the Coordinator (a worker message, a user message, or any
other notification):

1. In Codex, reconcile the recorded automation with `<orca> automations list
   --json` and keep exactly one quota wake-up per Run, following `quota-guard`.
   In Claude Code, run `CronList` and look for `quota-guard:<run-id>`. If it exists, do not
   create another; never create a second wake-up for one Run. If it is
   missing, create it as in **On PAUSED_QUOTA or UNKNOWN** step 3.
2. Receive the messages as in **Receive messages** in [Waiting](waiting.md)
   and record every delivered worker state in the checkpoint. Answer
   questions, but start no new work. Do not create a `coordinator-wait`
   reservation while paused.
3. Reply with one short line and end the turn.

## On wake-up

In Codex, remove the recorded quota automation first (its cron recurs);
resolve removal failures before creating another. In Claude Code, the fired
one-shot is gone. Run `<quota-check>`. If it is not READY, create
exactly one new provider-specific wake-up as in **On PAUSED_QUOTA or UNKNOWN** and end
the turn. On READY, reconcile the checkpoint with live `task-list`,
`list_workers.py`, branches, and PRs, then resume without repeating completed
phases or duplicating dispatches:

- A stopped worker whose phase is unfinished and whose terminal is still
  available: send it an ORCA message (`send --to dispatch:<dispatch_id>`) to
  continue the remaining work of its phase and report `worker_done` as before.
- A stopped worker that is no longer available: confirm from its branch and
  PR what was already done, then start one fresh worker for the same phase
  with a handoff of that state and the review count. Never run two workers on
  one Task.
- Then continue dispatching ready Tasks, reserve the earliest remaining
  `wake-at:` time again, and wait as in [Waiting](waiting.md).
