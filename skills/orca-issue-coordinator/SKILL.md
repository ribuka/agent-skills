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

## 0. Check preconditions and resolve worker settings

Before anything else, run:

```bash
uv run <skill-dir>/scripts/check_preconditions.py
```

It verifies that this conversation runs inside an Orca terminal, that the Orca
runtime is reachable, that `gh auth status` succeeds, and that the git checkout
the skills are installed from is neither behind `origin/main` nor carrying
commits not on it (so no one runs stale skills). If it exits non-zero,
or `orca orchestration run-create` later fails with
`no_active_sender_terminal`, **stop immediately** and report the `STOP:` lines
to the user. Never work around a failed precondition: do not create a
substitute Coordinator terminal (`orca terminal create`), do not pass another
terminal's handle to `--from`, and do not unset, replace, or switch `gh`
credentials (e.g. clearing `GH_TOKEN`).

On success it prints `skill-checkout: <path>`; keep that path. Never update
(pull, rebase, or check out) that checkout during the Run, even when merged
PRs change skills: every worker must run the same skill version. Report it as
stale at the end instead (step 17).

Then resolve the worker settings.

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
5. Represent actual dependencies in the task DAG. Orca unblocks a dependent
   Task as soon as its dependency Task completes, and an Implementation Task
   completes when its PR is opened, before the PR is merged. Dispatch a
   dependent Task only after every dependency's PR has been **merged**; never
   dispatch on Orca's ready state alone. Tell its worker to start from the
   latest `origin/main`, which includes those merges.
6. Dispatch independent tasks to separate worktrees, with at most
   **3 workers running concurrently**. Run the quota `check` before each
   dispatch and dispatch only on READY. Always pass the implementation
   `--model` and `--effort` from step 0, and confirm `launch.effective` in the
   receipt.

## 2. Parallel implementation

7. Instruct each worker to run `implement-review-merge` explicitly in
   **Orchestration worker / Implementation** mode.
   - Provide the Issue number, scope, acceptance criteria, and dependencies.
     Tell the worker to read the Issue itself.
   - Require implementation, tests, commit, push, PR creation,
     and `pr-cross-review` with findings addressed.
   - Require the handoff fields in its `worker_done` report (see the
     implement-review-merge skill).
   - Workers must not merge or create wake-ups (`CronCreate`); the
     Coordinator alone owns the Run's checkpoint and wake-up.
8. Fill available worker slots before waiting for completions.
   Dispatch additional tasks as slots become available, holding back
   dependent Tasks until their dependency PRs are merged (step 5).
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
    Skip step 13 and go straight to step 14 when the PR already meets all
    of the following; merge preparation would have nothing to do:
    - The PR branch includes the latest `origin/main`: after
      `git fetch --prune origin`,
      `git merge-base --is-ancestor origin/main origin/<branch>` exits `0`.
    - All required CI checks have passed on the current head commit
      (`gh pr checks <pr> --required`).
    - No review findings are open (per the worker handoff and the latest
      cross-review).
13. After a READY quota `check`, start a **new** worker for
    **Orchestration worker / Merge preparation** mode in the PR's existing
    worktree, with the merge-preparation `--model` / `--effort` from step 0:
    `worker-start --spec "<handoff>" --task-title "#<issue> PR #<pr> merge prep" --worktree branch:<branch>`.
    The Implementation Task is already completed and cannot be started again,
    so do not pass `--task <task_id>`. Do not reuse the implementation
    worker's conversation. The `<handoff>` is short:
    - Issue number, PR URL, branch, and worktree.
    - Cross-reviews used so far (the latest `review-count: <count>/<max>`)
      and any open findings or blockers.
    - The tasks: fetch and rebase onto the latest `origin/main` as needed;
      re-run tests and CI; repeat cross-review only if substantive changes
      require it.
14. Independently verify:
    - No outstanding review findings.
    - No more than `<max>` cross-reviews on the PR: count the cross-review
      comments on the PR and compare with `<max>` from the latest
      `review-count: <count>/<max>` that `pr-cross-review` printed (as
      reported in the worker handoff).
    - The PR branch includes the latest `origin/main`.
    - Required tests and CI have passed on the current PR commit.
    - GitHub merge requirements are satisfied.
15. Merge the PR yourself only when all conditions are met and the quota
    `check` immediately before the merge is READY.
16. After each merge, fetch the latest `origin/main` and repeat
    merge preparation for the next PR. If `main` changes before
    merging, revalidate the affected PR. Dispatch any dependent Task whose
    dependency PRs are now all merged (see step 5).
17. Mark only confirmed merged Issues as complete. Report the
    outcome and PR URL for each Issue. If any merged PR belongs to the
    repository of the `skill-checkout` path from step 0, ask the user to
    update that checkout to the latest `origin/main`.

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
- **On PAUSED_QUOTA or UNKNOWN:** stop starting all new work, then read
  `~/.agents/skills/orca-issue-coordinator/references/quota-pause.md` and
  follow it (checkpoint, stopping workers, exactly one wake-up, end the turn).
- **While paused or on wake-up:** whatever wakes the Coordinator (the quota
  wake-up, a worker message, the waiter exiting, or a heartbeat nudge), first
  follow that same reference before doing anything else, even if this
  conversation's context has been compacted.

## Messaging workers

Send every message to a worker (follow-ups, stop requests, resume requests)
to its terminal handle (`term_…`):
`orca orchestration send --to <terminalHandle> ...`. Never address a worker by
its dispatch ID (`ctx_…`); that fails with `terminal_not_found`. Take the
handle from the `worker-start` receipt and record it with the Task; if it is
missing, read `terminalHandle` from
`orca orchestration worker-show --dispatch <dispatch_id> --json`.

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
- While the quota is paused, do not start or restart the waiter; handle any
  waiter exit as in the quota pause reference (see **Quota control**).

## Token budget

- **Ignore heartbeat nudges.** While the waiter is running, ORCA still types
  `You have N orchestration message(s). Run orca orchestration check ...` into
  this terminal on every heartbeat. Do not call any tool for it. Reply with
  one short line (e.g. `待機中`) and end the turn. Act only when the waiter
  exits.
- **While the quota is paused,** handle every wake-up as in the quota pause
  reference (see **Quota control**).
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
- Never exceed the `pr-cross-review` per-PR review limit (`MAX_REVIEWS`),
  counting all phases and dispatches. Track this across worker restarts and
  pass it in every handoff.
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

Only after the step 0 precondition check passes, briefly present the execution
plan (including the resolved worker model and effort), then start
orchestration without waiting for additional approval. If any precondition
fails, stop and ask the user instead.
