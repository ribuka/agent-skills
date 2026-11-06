# Quota pause and resume

Read this when `<quota-check>` returns PAUSED_QUOTA or UNKNOWN, when a
worker reports `worker-quota-paused:`, when a worker's `escalation` carries
`failureKind=usageLimitReached`, or when the Coordinator is woken while
a Run is paused. `<quota-check>`, `<run-id>`,
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

## Worker stopped by the quota pause

A worker whose tool calls were denied at the quota pause sends
`worker_done --outcome failed` with a `worker-quota-paused: <quota JSON>` line
and a `context-tokens: <n|unknown>` line. It is a quota pause, not a failed
Task:

1. Choose how to resume it, by its conversation size and
   `FRESH_WORKER_CONTEXT_TOKENS` (`fresh-worker-context-tokens:` from
   `SKILL.md` step 0):
   - **Same conversation:** `context-tokens` is a number below the
     threshold. Its context is still worth reusing, so keep its terminal:
     run `<orca> orchestration worker-keep-open --dispatch <dispatch_id>`
     and do not release it.
   - **Fresh worker:** `context-tokens` is at or above the threshold, or
     `unknown`. While the quota waits, the prompt cache expires, so the
     same conversation would be written to the cache again in full and then
     resent on every call. Release the worker as `SKILL.md` step 11 says.
2. Record in the checkpoint the Task, dispatch ID, terminal handle,
   worktree, branch, PR URL, review count, open findings, the work left,
   `context-tokens`, and the chosen resume method.
3. Run `<quota-check>`. On PAUSED_QUOTA or UNKNOWN, follow
   **On PAUSED_QUOTA or UNKNOWN** (or **While paused** when the Run is
   already paused). On READY, resume it at once as **On wake-up** says.

## Worker stopped by the usage limit

An `escalation` whose payload has `failureKind=usageLimitReached` means the
worker's agent hit its usage limit and stopped mid-turn, without
`worker_done`. It is a quota pause, not a failed Task. Never resume it in its
own conversation: a message sent to it with `send`
reaches it only after its next turn ends, and its long conversation would be
written to the expired prompt cache again in full. Always use the **fresh
worker** method:

1. Record in the checkpoint the Task, dispatch ID, terminal handle,
   worktree, branch, PR URL (if any), review count, open findings, and the
   resume method `fresh worker`. The work left is unknown until the branch
   and PR are checked (**Handoff to a retried worker**).
2. Stop the old dispatch, so that it cannot continue beside its successor:
   `<orca> orchestration worker-stop --dispatch <dispatch_id>`, following
   Orca's `references/recovery-and-cleanup.md`. The escalation is positive
   proof that the worker stopped its work; silence or `unverifiable`
   liveness alone still never authorizes a stop ([Waiting](waiting.md)).
   Respect its identity, custody, and Keep open refusals: never stop a
   worker the user kept open or took over; ask the user instead. Treat the
   dispatch as stopped only on a confirmed stopped result. On `stop_unknown`,
   inspect `<orca> orchestration worker-show --dispatch <dispatch_id>`, then
   report the blocker to the user; do not repeat the stop or start another
   worker for the Task.
3. Run `<quota-check>` and continue as step 3 of **Worker stopped by the
   quota pause** says.

## Handoff to a retried worker

A worker started with `--retry-of` gets the Task's original brief only, so
it asks for the handoff (`question`) before it does anything else. Before
starting it, confirm the state from the branch and PR, not from the
checkpoint alone: the PR (`gh pr list --head <branch> --state all`), its
review count and latest review (`review_status.sh` from `pr-cross-review`,
then that comment only), and the worktree (`git -C <worktree> status
--short` and `git -C <worktree> log --oneline origin/main..HEAD`). Record
that handoff in the checkpoint. It holds:

- Issue number, PR URL, branch, and worktree.
- The review count (the larger of the recorded and printed counts) and the
  open findings from the latest review.
- The work left in the phase, any blockers, and any user approvals (an
  extra review, merging a head as is).

When its `question` arrives, reply with the recorded handoff
(`<orca> orchestration reply --id <message-id> --body "<handoff>"`). Do not
send the handoff with `send` instead: it is not read before the worker's
first turn ends.

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

- A worker still running its Dispatch (stopped on the Coordinator's
  request, without `worker_done` and without a `usageLimitReached`
  escalation) whose terminal is still available: send it
  an ORCA message (`send --to dispatch:<dispatch_id>`) to continue the
  remaining work of its phase and report `worker_done` as before.
- A worker that reported `worker-quota-paused:` with the **same
  conversation** method and whose kept-open terminal is still available:
  start it again in its own conversation with `start_worker.py`
  (`SKILL.md` **Starting workers**) and
  `--task <task_id> --retry-of <dispatch_id> --worktree branch:<branch> --terminal <handle>`
  (no `--model` / `--effort`; they cannot combine with `--terminal`). After
  verifying its next `worker_done`, release the terminal you kept open as
  `SKILL.md` step 11 says.
- Any other stopped worker (the **fresh worker** method, including every
  `usageLimitReached` worker, or a terminal that is no longer available):
  start it only after its old dispatch has settled (`worker_done`, or a
  confirmed `worker-stop`). Prepare the handoff as **Handoff to a retried
  worker** says, then retry the same failed Task with one fresh worker in
  the existing worktree, with `start_worker.py` and
  `--task <task_id> --retry-of <dispatch_id> --worktree branch:<branch> --agent <agent> --model <model> --effort <effort>`
  (the phase's model and effort from `SKILL.md` step 0). Do not create a new
  Task with `--spec`: the failed Task would stay failed and block the Tasks
  that depend on it. The retried Task keeps its brief; the new worker
  asks for the handoff, then rebuilds the state (PR, review count, latest
  review, uncommitted changes) from its branch and PR, as
  `implement-review-merge` says for a resumed phase. Never run two workers
  on one Task.
- Then continue dispatching ready Tasks, reserve the earliest remaining
  `wake-at:` time again, and wait as in [Waiting](waiting.md).
