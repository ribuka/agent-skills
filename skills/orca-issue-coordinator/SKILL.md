---
name: orca-issue-coordinator
description: Coordinate multiple GitHub Issues through ORCA Orchestration. Delegate implementation and cross-review to parallel workers using the implement-review-merge skill, then verify and merge pull requests sequentially. Use when explicitly asked to orchestrate multiple issues or coordinate parallel development.
disable-model-invocation: true
---

# Coordinate GitHub Issues

- Act as the Coordinator. Delegate implementation to workers and retain
  exclusive responsibility for merging pull requests.
- Use ORCA Orchestration to manage tasks, dependencies, workers, and results.
- Respond in Japanese.
- Keep the Coordinator's context small: every turn re-reads it. Follow
  **Token budget** below throughout the run.
- Gate new work on the Claude Code 5-hour quota. Follow **Quota control**
  below throughout the run.

`<skill-dir>` below is the directory containing this file.

## 0. Resolve worker settings

Run once at the start, passing through any `--impl-model`, `--impl-effort`,
`--merge-model`, or `--merge-effort` flags the user gave:

```bash
uv run <skill-dir>/scripts/resolve_config.py [user flags]
```

It prints the `--model` / `--effort` pair for each phase and where each value
came from (argument > `<skill-dir>/config.conf` > defaults: implementation
`opus`/`medium`, merge preparation `sonnet`/`medium`). Use these values on every `worker-start`.

## 1. Plan and dispatch

1. Read the compact guide: `orca skills get orchestration`. Do **not** use
   `--full`; load a bundled reference only when the guide's action gate needs
   it: `orca skills get orchestration --reference <name>`.
2. Inspect only what planning needs: Issue number, title, labels, and stated
   dependencies (e.g. `gh issue list --json number,title,labels` or
   `gh issue view <n> --json number,title,labels`), plus existing PRs and
   branches. Do not read full Issue bodies or investigate code; workers do
   that. Avoid duplicating or overwriting existing changes.
3. Identify dependencies, overlapping areas, and potential conflicts from that
   summary. Open an Issue body only when a dependency cannot be decided
   otherwise.
4. Create one Orchestration Run, with one Task per Issue by default. Then,
   before any dispatch, set up the quota guard with this Run ID (see
   **Quota control**).
5. Represent actual dependencies in the task DAG.
6. Dispatch independent tasks to separate worktrees, with at most
   **3 workers running concurrently**. Run the quota `check` before each
   dispatch and dispatch only on READY. Always pass the implementation
   `--model` and `--effort` from step 0, and confirm `launch.effective` in the
   receipt.

## 2. Parallel implementation

7. Instruct each worker to run `implement-review-merge` explicitly in
   **Orchestration worker / Implementation** mode (steps 1–7).
   - Provide the Issue number, scope, acceptance criteria, and dependencies.
     Tell the worker to read the Issue itself.
   - Require implementation, tests, commit, push, PR creation,
     and `pr-cross-review` with findings addressed.
   - Require the handoff fields in its `worker_done` report (see the
     implement-review-merge skill).
   - Workers must not merge or create wake-ups (`CronCreate`); the
     Coordinator alone owns the Run's checkpoint and wake-up.
8. Fill available worker slots before waiting for completions.
   Dispatch additional ready tasks as slots become available.
9. Wait with the bundled script (see **Waiting**), never with a hand-rolled
   `check` loop.
10. Track each Task's worktree, branch, PR URL, review status, review count,
    and blockers. Verify reports rather than treating `worker_done`
    as proof of completion. Run the quota `check` after processing each
    `worker_done`.
11. After verifying an Implementation `worker_done`, release that worker's
    terminal (`worker-release`); merge preparation starts a fresh worker.

## 3. Sequential merge

12. Select the next PR based on dependencies and readiness.
13. After a READY quota `check`, start a **new** worker for
    **Orchestration worker / Merge preparation** mode (steps 8–9) in the
    PR's existing worktree (`worker-start --task <task_id> --worktree <selector>`), with the
    merge-preparation `--model` / `--effort` from step 0. Do not reuse the
    implementation worker's conversation. Give it a short handoff:
    - Issue number, PR URL, branch, and worktree.
    - Cross-reviews used so far (out of `MAX_REVIEWS`) and any open findings or blockers.
    - The tasks: fetch and rebase onto the latest `origin/main` as needed;
      re-run tests and CI; repeat cross-review only if substantive changes
      require it.
14. Independently verify:
    - No outstanding review findings.
    - No more than `MAX_REVIEWS` cross-reviews for the PR (`pr-cross-review`
      `config.env`).
    - The PR branch includes the latest `origin/main`.
    - Required tests and CI have passed on the current PR commit.
    - GitHub merge requirements are satisfied.
15. Merge the PR yourself only when all conditions are met and the quota
    `check` immediately before the merge is READY.
16. After each merge, fetch the latest `origin/main` and repeat
    merge preparation for the next PR. If `main` changes before
    merging, revalidate the affected PR.
17. Mark only confirmed merged Issues as complete. Report the
    outcome and PR URL for each Issue.

## Quota control

Use the `quota-guard` skill (`~/.agents/skills/quota-guard`) to stop starting
new work near the 5-hour limit. `<quota-check>` below means
`python ~/.agents/skills/quota-guard/scripts/quota_guard.py check`.

- **Setup, once per Run:** right after creating the Orchestration Run (its
  ID is `<run-id>` below), load `quota-guard` once, perform its setup
  (`configure`) and the first `<quota-check>`. If that check already blocks,
  pause as below; no worker has been dispatched yet. Do not reload the skill
  or read snapshot history afterwards; only run `<quota-check>` and read its
  one-line JSON result.
- **Boundaries:** run `<quota-check>` before every Task dispatch, before
  every merge-preparation dispatch, before every merge, after processing
  each `worker_done`, and before starting the waiter. Continue only on
  READY. PAUSED_QUOTA and UNKNOWN block all new work (dispatch, merge
  preparation, merge, re-dispatch).
- **Ownership:** the Coordinator alone owns the Run checkpoint and the
  resumption wake-up. Workers never create wake-ups.
- **On PAUSED_QUOTA or UNKNOWN:**
  1. Write the checkpoint (outside any worktree, e.g.
     `~/.claude/quota-guard/checkpoints/<run-id>.md`): Run ID, each Task's
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
     path, and the instruction to run `<quota-check>`, reconcile the
     checkpoint with live `task-list` / `worker-list` / PR state, and resume
     this Run only on READY. For UNKNOWN, follow `quota-guard`'s single
     2-second local retry first, then its 15-minute retry.
  4. End the turn.
- **While paused:** whatever wakes the Coordinator (a worker message, the
  waiter exiting, or a heartbeat nudge), first run `CronList` and look for
  `quota-guard:<run-id>`. If it exists, do not create another; only record
  delivered worker states in the checkpoint (see **Waiting**), reply with one
  short line, and end the turn. Never create a second wake-up for one Run.
- **On wake-up:** the fired one-shot is gone. Run `<quota-check>`. If it is
  not READY, create exactly one new one-shot wake-up as above and end the
  turn. On READY, reconcile the checkpoint with live `task-list`,
  `worker-list`, branches, and PRs, then resume without repeating completed
  phases or duplicating dispatches:
  - A stopped worker whose phase is unfinished and whose terminal is still
    available: send it an ORCA message to continue the remaining work of
    its phase and report `worker_done` as before.
  - A stopped worker that is no longer available: confirm from its branch
    and PR what was already done, then start one fresh worker for the same
    phase with a handoff of that state and the review count. Never run two
    workers on one Task.
  - Then continue dispatching ready Tasks and start the waiter as usual.
- If `CronCreate` / `CronList` are unavailable, keep the checkpoint and tell
  the user that manual resumption is required.

## Waiting

Run the bundled waiter as a **background** command whenever you are waiting
for workers, and only after a READY `<quota-check>`:

```bash
python <skill-dir>/scripts/wait_actionable.py [--terminal <handle>] [--run <run_id>]
```

- It loops `check --wait --types "worker_done,escalation,question"`,
  acknowledges heartbeat-only batches itself, and runs `worker-list` after
  repeated empty waits.
- It exits only when something needs the Coordinator, printing a compact
  summary:
  - `0`: actionable messages; the Delivery is left **unacknowledged**.
    Process every row, then `check --ack <delivery_id>`.
  - `3`: a worker requires action (per `worker-list`).
  - `4`: no in-progress worker remains; check `task-list` and `worker-list`.
  - `5`: `--max-minutes` (default 240) elapsed; restart the waiter.
  - `2`: an `orca` call failed; inspect before retrying.
- Use `worker-read` or `check --peek` only after the waiter has exited and
  the summary is insufficient.
- While the quota is paused (PAUSED_QUOTA or UNKNOWN):
  - Do not start a new waiter, and do not restart it after exit `5`.
  - If a waiter exits `0` or `3`, only record the delivered worker states in
    the checkpoint (and `check --ack` the Delivery after exit `0`); do not
    dispatch, prepare merges, or merge. Then follow **While paused** in
    **Quota control**.

## Token budget

- **Ignore heartbeat nudges.** While the waiter is running, ORCA still types
  `You have N orchestration message(s). Run orca orchestration check ...` into
  this terminal on every heartbeat. Do not call any tool for it. Reply with
  one short line (e.g. `待機中`) and end the turn. Act only when the waiter
  exits.
- **While the quota is paused,** handle every wake-up (worker message, waiter
  exit, heartbeat nudge) as in **While paused** in **Quota control**: one
  `CronList` check, no new wake-up if one exists, one short line, end the
  turn.
- Report to the user only when state changes (dispatch, worker_done, merge,
  blocker, question). Never post "no news yet" updates.
- Keep reports short: Issue, PR URL, state, next step.
- Do not re-read large outputs (full guides, Issue bodies, full worker
  transcripts, raw JSON) that the summaries already cover.

## Rules

- **Only the Coordinator may merge.** Workers must stop after their
  assigned phase and report through ORCA Orchestration.
- Preserve the existing `implement-review-merge` workflow,
  `pr-cross-review` requirements, and GitHub authentication conventions.
- Never exceed `MAX_REVIEWS` cross-reviews per PR (`pr-cross-review`
  `config.env`), counting all phases and
  dispatches. Track this across worker restarts and pass it in every handoff.
- If a review fails, the limit is reached, or a conflict cannot be
  resolved safely, block that PR and ask the user.
- Continue other independent Tasks whenever possible, except while the quota
  is PAUSED_QUOTA or UNKNOWN (see **Quota control**).
- Never discard uncommitted changes or use `git push --force`.
  Use `--force-with-lease` only when required after a safe rebase.
- Avoid concurrent changes that would conflict or invalidate another
  worker's assumptions; serialize dependent Tasks.
- Verify worker state before retrying failed dispatches to avoid
  duplicate execution.
- Do not merge when review, CI, or branch synchronization status
  cannot be verified.
- Follow ORCA's protocol for completion reporting and cleanup.
- Resolve routine technical decisions autonomously; ask the user
  only when a safe decision cannot be made.

Briefly present the execution plan (including the resolved worker model and
effort), then start orchestration without waiting for additional approval.
