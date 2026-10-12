# Quota pause and resume

Read this when `<quota-check>` returns PAUSED_QUOTA or UNKNOWN, or when the
Coordinator is woken while a Run is paused. `<quota-check>`, `<run-id>`, and
`<skill-dir>` mean the same as in `SKILL.md`. While paused, no new work starts:
no dispatch, merge preparation, merge, or re-dispatch, and the normal rule to
continue other independent Tasks does not apply.

## On PAUSED_QUOTA or UNKNOWN

1. Write the checkpoint to `<run-id>.md` under the result's
   `checkpoint_dir`: Run ID, each Task's
   phase, worker handle, worktree, branch, PR URL, review count, blockers,
   and pending actions, plus the quota helper path and state directory.
   For each worker asked to stop, record the dispatch it was running and
   the work left in that phase.
2. Ask every active worker, through ORCA Orchestration messages, to stop
   at a safe boundary (after a commit/push or a finished review, never
   mid-rebase) and report its state. Verify the reported states with
   `worker-list`. Never kill worker processes or claim that all work has
   stopped.
3. Ensure exactly one wake-up (see **While paused**): if none exists,
   create one one-shot (`recurring: false`) wake-up at the result's
   `cron`, containing the marker `quota-guard:<run-id>`, the checkpoint
   path, the path of this file
   (`~/.agents/skills/orca-issue-coordinator/references/quota-pause.md`),
   and the instruction to follow **On wake-up** in it: run `<quota-check>`,
   reconcile the checkpoint with live `task-list` / `worker-list` / PR
   state, and resume this Run only on READY. For UNKNOWN right after setup
   or a wake-up, first wait the result's `local_retry_seconds` and re-run
   `<quota-check>` once (no model request); only if it is still UNKNOWN,
   use its `cron`.
4. End the turn.

If `CronCreate` / `CronList` are unavailable, keep the checkpoint and tell
the user that manual resumption is required.

## While paused

Whatever wakes the Coordinator (a worker message, the waiter exiting, or a
heartbeat nudge):

1. Run `CronList` and look for `quota-guard:<run-id>`. If it exists, do not
   create another; never create a second wake-up for one Run. If it is
   missing, create it as in **On PAUSED_QUOTA or UNKNOWN** step 3.
2. Only record delivered worker states in the checkpoint. After a waiter exit
   `0`, also `check --ack` the Delivery. Do not start a new waiter, and do
   not restart it after exit `5`.
3. Reply with one short line and end the turn.

## On wake-up

The fired one-shot is gone. Run `<quota-check>`. If it is not READY, create
exactly one new one-shot wake-up as in **On PAUSED_QUOTA or UNKNOWN** and end
the turn. On READY, reconcile the checkpoint with live `task-list`,
`worker-list`, branches, and PRs, then resume without repeating completed
phases or duplicating dispatches:

- A stopped worker whose phase is unfinished and whose terminal is still
  available: send it an ORCA message to continue the remaining work of its
  phase and report `worker_done` as before.
- A stopped worker that is no longer available: confirm from its branch and
  PR what was already done, then start one fresh worker for the same phase
  with a handoff of that state and the review count. Never run two workers on
  one Task.
- Then continue dispatching ready Tasks and start the waiter as usual
  (`SKILL.md` **Waiting**).
