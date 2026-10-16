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
- Gate new work on the current agent's 5-hour quota. Follow **Quota control**
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
commits or uncommitted skill changes not on it (so no one runs stale skills).
If it exits non-zero,
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

Then identify this Coordinator's runtime as `<agent>` (`claude` or `codex`).
Workers always use that same agent; do not offer an independent worker-agent
override. Resolve the worker settings for it.

Run once at the start, passing through any `--impl-model`, `--impl-effort`,
`--merge-model`, `--merge-effort`, or `--max-workers` flags the user gave.
If the user explicitly asks to run the Issues serially (one at a time), pass
`--max-workers 1`:

```bash
uv run <skill-dir>/scripts/resolve_config.py --agent <agent> [user flags]
```

It prints the agent, the `--model` / `--effort` pair for each phase, the
`max-workers: <n>` concurrency limit (`MAX_WORKERS`), and each value's source
(argument > `<skill-dir>/config.conf` > defaults). Configuration keys are
`CLAUDE_IMPL_MODEL`, `CLAUDE_IMPL_EFFORT`, `CLAUDE_MERGE_MODEL`,
`CLAUDE_MERGE_EFFORT`, their `CODEX_` equivalents, and shared `MAX_WORKERS`.
Unprefixed model/effort keys are not supported. Claude defaults remain
`opus`/`medium` for implementation and `sonnet`/`medium` for merge preparation;
Codex defaults are `gpt-6.1-sol`/`medium` for both phases.
Concurrency defaults to 3. Always pass `--agent <agent>` and the resolved
model/effort on every `worker-start`, and never exceed `MAX_WORKERS`.
Claude effort values: `low`, `medium`, `high`, `xhigh`, `max`;
Codex: `minimal`, `low`, `medium`, `high`, `xhigh` (no `max`).

For every implementation and merge-preparation dispatch, verify
`launch.effective`. A ready receipt confirms launch preferences, not successful
model execution. On a recovery wake or a worker-status inspection, if no
assistant result has appeared, inspect bounded worker output for provider
errors even if the fleet projection says live/working. A positive provider
rejection blocks that attempt: load Orca's orchestration recovery guide, stop
the failed attempt with `worker-stop --dispatch <dispatch-id>` following its
authority rules, report the blocker and ask the user for a supported model.
Do not retry the rejected model or automatically fall back to another model.
Silence alone is not evidence of failure and does not authorize stopping.

## 1. Plan and dispatch

1. Read the compact guide: `orca skills get orchestration`. Do **not** use
   `--full`; load a bundled reference only when the guide's action gate needs
   it: `orca skills get orchestration --reference <name>`.
2. Inspect only what planning needs: Issue number, title, labels, and stated
   dependencies (e.g. `gh issue list --json number,title,labels` or
   `gh issue view <n> --json number,title,labels`), plus existing PRs and
   branches. Do not read full Issue bodies or investigate code; workers do
   that. Step 3 gives the only exception. Avoid duplicating or overwriting
   existing changes.
3. Identify dependencies, overlapping areas, and potential conflicts from that
   summary. Open an Issue body only when a dependency or an overlap involving
   that Issue cannot be decided otherwise, and only for the Issues involved
   (`gh issue view <n> --json body`), once each. Decide how Tasks that edit
   the same file run:
   - **Same part of the same file** (the Issue titles or existing PRs and
     branches show they edit the same step, section, or function): treat
     this as a dependency and run the Tasks in order (step 5).
   - **Distant parts of the same file only:** run the Tasks in parallel and
     expect merge preparation (step 13) to resolve the resulting conflicts.
   - If the overlap is still unclear after reading the Issue bodies, run the
     Tasks in order.
4. Create one Orchestration Run. Then, before any dispatch, set up the
   quota guard with this Run ID (see **Quota control**). In Codex, after READY,
   set up the recovery automation in [Codex waiting](references/codex-waiting.md)
   before dispatching. Plan one Task per
   Issue by default, and create each Task in exactly one way:
   - **Independent Task** (no dependencies): do not create it in advance.
     `worker-start --spec "<brief>" --task-title "#<issue> <title>" --agent <agent>`
     creates the Task and starts its worker in one call (step 6).
   - **Dependent Task** (has dependencies, or other Tasks depend on it):
     create it up front with
     `task-create --spec "<brief>" --task-title "#<issue> <title>" --deps '<json_array>'`
     so the DAG is recorded, then start it with
     `worker-start --task <task_id> --agent <agent>` (step 6).
   - Never create a Task you will not start. Never start a worker with
     `--spec` for an Issue that already has a Task; that leaves an unused
     Task in the Run, and cancelling it leaves a `failed` one.
5. Represent actual dependencies in the task DAG, including the
   same-part overlaps from step 3. Orca unblocks a dependent
   Task as soon as its dependency Task completes, and an Implementation Task
   completes when its PR is opened, before the PR is merged. Dispatch a
   dependent Task only after every dependency's PR has been **merged**; never
   dispatch on Orca's ready state alone. Tell its worker to start from the
   latest `origin/main`, which includes those merges.
6. Before the first dispatch, briefly present the execution plan to the
   user: Task dependencies, dispatch order, and the resolved worker model,
   effort, and `MAX_WORKERS` from step 0. For Tasks that edit the same file
   but run in parallel, state that decision and its reason (e.g. which
   parts each edits). Then start dispatching without waiting for approval.
   Dispatch independent tasks to separate worktrees, with at most
   **`MAX_WORKERS` workers running concurrently**. Merge-preparation workers
   count toward this limit. With `MAX_WORKERS=1`, run fully serially:
   implement one Issue, prepare and merge its PR, and only then dispatch the
   next Issue. Start each worker as step 4 decided for its Task:
   `worker-start --spec` for an independent Task,
   `worker-start --task <task_id>` for a Task created with `task-create`.
   Run the quota `check` before each
   dispatch and dispatch only on READY. Always pass `--agent <agent>` and the implementation
   `--model` and `--effort` from step 0, and confirm `launch.effective` in the
   receipt.

## 2. Parallel implementation

7. Instruct each worker to run `implement-review-merge` explicitly in
   **Orchestration worker / Implementation** mode.
   - Provide the Issue number, scope, acceptance criteria, and dependencies.
     Tell the worker to read the Issue itself.
   - Require implementation, tests, commit, push, PR creation,
     and `pr-cross-review` with findings addressed. Codex workers use the
     Claude reviewer; Claude workers use the Codex reviewer, as that skill
     specifies.
   - Require the handoff fields in its `worker_done` report (see the
     implement-review-merge skill). The report may also state whether the
     PR conflicts with `main`.
   - Tell the worker not to rebase onto or merge `origin/main` even if
     `main` moves during implementation. Syncing with `main`, resolving
     conflicts, and re-checking CI happen once, in merge preparation
     (step 13).
   - Workers must not merge or schedule resumption wake-ups; the
     Coordinator alone owns the Run's checkpoint and wake-up.
   - If `pr-cross-review` fails because the reviewer's quota is exhausted,
     the worker stops and reports the `reviewer-quota-exhausted`,
     `reviewer-quota-detected-at`, and `reviewer-quota-reset` lines unchanged
     in `worker_done`.
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
    - All CI checks have passed on the current head commit
      (`gh pr checks <pr>`). Check all CI even when no required checks are
      configured. Exit `8` means pending: do not take
      this shortcut. Any other non-zero result needs inspection; report
      monitoring errors as blockers instead of treating them as pending.
      An empty check set is not proof of success.
    - No review findings are open (per the worker handoff and the latest
      cross-review).
13. When a worker slot is free (within `MAX_WORKERS`) and after a READY
    quota `check`, start a **new** worker for
    **Orchestration worker / Merge preparation** mode in the PR's existing
    worktree, with `--agent <agent>` and the merge-preparation `--model` / `--effort` from step 0:
    `worker-start --spec "<handoff>" --task-title "#<issue> PR #<pr> merge prep" --worktree branch:<branch> --agent <agent>`.
    The Implementation Task is already completed and cannot be started again,
    so do not pass `--task <task_id>`. Do not reuse the implementation
    worker's conversation. The `<handoff>` is short:
    - Issue number, PR URL, branch, and worktree.
    - Cross-reviews used so far (the latest `review-count: <count>/<max>`)
      and any open findings or blockers.
    - The tasks: fetch and rebase onto the latest `origin/main` as needed;
      re-run tests and CI; repeat cross-review per the re-review criteria
      below.
    - Re-review criteria after a rebase or conflict resolution:
      - **Mechanical:** the resolution only keeps both sides' changes as
        they are, or only moves lines. Do not repeat cross-review.
      - **Newly written:** the resolution writes text or logic that no
        cross-review has seen (e.g. re-applying this PR's change to a file
        or section that `main` added or rewrote). Repeat cross-review
        within `MAX_REVIEWS`; if the limit is already reached, report a
        blocker instead of merging.
    - The `worker_done` report must state, besides the handoff fields,
      whether the resolution was `none`, `mechanical`, or `newly written`
      (naming the files), and whether cross-review was repeated.
14. Independently verify:
    - Only if the merge-preparation worker reported a `newly written`
      resolution: a cross-review ran after it with no outstanding findings.
      If that review is missing, has open findings, or could not run
      because the limit was reached, block the PR and ask the user.
    - No outstanding review findings.
    - No more than `<max>` cross-reviews on the PR: run
      `bash ~/.agents/skills/pr-cross-review/scripts/review_status.sh <pr-number>`
      and check that its `review-count: <count>/<max>` line has
      `<count>` ≤ `<max>`. Do not count PR comments yourself; other
      comments are mixed in. Compare this output with the review count in
      the worker handoff; if they differ, use the script's count and note
      the mismatch in the Issue's report (step 17). If the script exits non-zero,
      block the PR and ask the user.
    - The PR branch includes the latest `origin/main`.
    - Required tests and CI have passed on the current PR commit.
    - GitHub merge requirements are satisfied.
    - If CI checks are pending in **Codex**, follow
      [Codex waiting](references/codex-waiting.md): save the PR/head/deadline,
      end the turn, and inspect once on the next wake-up. Do not run a foreground
      watcher or merge while pending. In **Claude Code**, use
      `gh pr checks <pr> --watch --interval 30` with an overall timeout
      (default: 30 minutes) set before starting. Use automatic completion
      notifications only when the harness guarantees them and enforces a
      hard timeout; otherwise collect the same background process's output
      and exit status at least once per minute. A session yield is not a
      timeout. On timeout terminate it; on monitoring error
      or timeout report `monitor-error: <reason>` and block this PR. Use
      only `gh` built-in features, never external `jq` or custom CI loops.
      Recheck the current head and all CI checks before merging.
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
    Remove this Run's waiting automation, if any (see **Waiting**).
    Then end the Run. ORCA has no command that closes a Run; the Run ends
    when no worker terminal still owes a decision:
    `orca orchestration worker-list --run <run-id> --terminal-state reclaimable --json`
    must return none (release any it lists). Finally delete only
    `tmp/<run-id>/` (see **Rules**).

## Quota control

Use the `quota-guard` skill (`~/.agents/skills/quota-guard`) to stop starting
new work near the 5-hour limit. `<quota-check>` below means
`uv run --no-project ~/.agents/skills/quota-guard/scripts/quota_guard.py check --provider <agent>`.

- **Setup, once per Run:** right after creating the Orchestration Run (its
  ID is `<run-id>` below), load `quota-guard` once and run the first `<quota-check>`.
  Claude Code first performs its documented `configure` setup using `uv run`;
  Codex skips Claude setup and uses the live Codex provider. If that check already blocks,
  pause as below; no worker has been dispatched yet. Do not reload the skill
  or read snapshot history afterwards; only run `<quota-check>` and read its
  one-line JSON result.
- **Boundaries:** run `<quota-check>` before every Task dispatch, before
  every merge-preparation dispatch, before every merge, after processing
  each `worker_done`, and before starting the waiter. Continue only on
  READY. PAUSED_QUOTA and UNKNOWN block all new work (dispatch, merge
  preparation, merge, re-dispatch).
- **Judge READY by exit code only:** `<quota-check>` exits `0` only on
  READY. Chain the gated command as `<quota-check> && <command>` so it runs
  only on exit `0`. Never grep the JSON output to decide READY, and never
  run the gated command on a separate line after the check.
- **Tell blocked states apart by JSON:** on a non-zero exit, read the
  `state` field of the one-line JSON result to tell PAUSED_QUOTA from
  UNKNOWN. Do not rely on the specific non-zero code: PowerShell
  `-Command` (used by Codex) reports any failing native command as `1`.
  A non-zero exit without a parseable `state` counts as UNKNOWN.
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
to its Dispatch: `orca orchestration send --to dispatch:<dispatch_id> ...`.
Take the dispatch ID (`ctx_…`) from the `worker-start` receipt and record it
with the Task; no terminal handle is needed.

- Always keep the `dispatch:` prefix. A bare `--to ctx_…` fails with
  `terminal_not_found`.
- `--to dispatch:<dispatch_id>` addresses that exact attempt. After a
  re-dispatch, send to the new dispatch ID.

## Asking the user

These rules apply to every question to the user, in both Codex and Claude
Code Coordinators (blockers, decisions, model choices, or anything else).

- **Write the full question in the final message of the turn.** Never rely
  only on `request_user_input_async`, `AskUserQuestion`, or another
  input UI: later terminal input (heartbeat nudges, recovery wake text) and
  later turns can hide or scroll it away. You may also open such a UI, but
  the final message must stand on its own.
- Use this format:
  - **Background:** what happened and why a decision is needed, with the
    Issue/PR numbers.
  - **Options:** each choice and its consequence.
  - **Recommendation:** the option you recommend and why.
  - **Example reply:** a short reply the user can copy (e.g. `#32: A`).
- Explain terms the user may not know (e.g. Git submodules) inside the
  question.
- Ask related pending questions together in one message, numbered, instead
  of one at a time.
- While a question is unanswered, end every later turn (including
  heartbeat-only and wake-up turns) with a one-line reminder that names the
  pending question and the expected reply, instead of an empty or
  waiting-only message.

## Waiting

**Codex:** follow [Codex waiting](references/codex-waiting.md). End the turn
while idle; never run or poll `wait_actionable.py`, even in the background.
Keep exactly one wake-up per Run: the 15-minute recovery wake while workers or
CI are pending, one wake at the time when the Run waits only for a known time
(e.g. a reviewer quota retry), and none while it waits only for the user.

The 15-minute recovery wake runs this precheck, which reads Orca state and the
Run checkpoint without starting a model:

```bash
uv run --no-project <skill-dir>/scripts/wake_if_actionable.py --orca <orca> --terminal <handle> --run <run-id> --checkpoint <checkpoint> --text "<wake text>" [--safety-minutes 60]
```

- It sends `<wake text>` to the Coordinator terminal only when there is an
  unread `worker_done` / `escalation` / `question` (peeked, not
  acknowledged), a worker requiring action per `worker-list`, no worker in
  progress while Tasks remain, a passed `wake-at: <ISO-8601 time> <reason>`
  line in the checkpoint, an `orca` failure or unreadable checkpoint, or
  `--safety-minutes` since its last wake. A condition already seen on its
  previous run wakes again only after it clears and returns. It reads every
  `worker-list` page and caps its `orca` queries at 60 seconds in total, so
  the wake is still sent within the automation's 120-second precheck timeout.
- It prints one JSON line `{"wake": <bool>, "reasons": [...], "sent": <bool|null>}`
  (plus `errors` when a check failed) and always exits non-zero, so the
  automation never starts its own agent: `1` nothing new (no input sent),
  `2` wake text sent, `3` wake needed but sending failed.

**Claude Code:** run the bundled waiter as a **background** command whenever you are waiting
for workers, and only after a READY `<quota-check>`:

```bash
uv run --no-project ~/.agents/skills/quota-guard/scripts/quota_guard.py check --provider claude && uv run --no-project <skill-dir>/scripts/wait_actionable.py [--terminal <handle>] [--run <run_id>]
```

The `&&` starts the waiter only when the check exits `0` (READY); on a
non-zero exit, handle the pause as in **Quota control** instead.

- It loops `check --wait --types "worker_done,escalation,question"`,
  acknowledges heartbeat-only batches itself, and runs `worker-list` after
  repeated empty waits.
- It exits only when something needs the Coordinator, printing a compact
  summary:
  - `0`: actionable messages; the Delivery is left **unacknowledged**.
    The body of every `worker_done`, `escalation`, and `question` message is
    printed in full, so read the worker handoff fields from this output.
    Process every row, then `check --ack <delivery_id>`.
  - `3`: a worker requires action (per `worker-list`).
  - `4`: no in-progress worker remains; check `task-list` and `worker-list`.
  - `5`: `--max-minutes` (default 240) elapsed; restart the waiter.
  - `2`: an `orca` call failed; inspect before retrying.
- Do not re-read message bodies with `check --peek`. Use `worker-read` only
  after the waiter has exited and a worker's terminal output is needed.
- While the quota is paused, do not start or restart the waiter; handle any
  waiter exit as in the quota pause reference (see **Quota control**).

## Token budget

- **Codex:** consume one non-waiting Delivery per notification as specified in
  the waiting reference, acknowledge heartbeat-only batches, then end the turn.
  Do not assume a heartbeat nudge carries actionable work.

- **Claude Code: ignore heartbeat nudges.** While the waiter is running, ORCA still types
  `You have N orchestration message(s). Run orca orchestration check ...` into
  this terminal on every heartbeat. Do not call any tool for it. Reply with
  one short line (e.g. `待機中`) and end the turn. Act only when the waiter
  exits. If a question to the user is pending, that line is the reminder
  from **Asking the user**.
- **While the quota is paused,** handle every wake-up as in the quota pause
  reference (see **Quota control**).
- Report to the user only when state changes (dispatch, worker_done, merge,
  blocker, question). Never post "no news yet" updates.
- Keep reports short: Issue, PR URL, state, next step.
- **Read each guide or reference at most once per Run:** a skill's
  `SKILL.md`, an `orca skills get` guide or `--reference`, and this skill's
  `references/`. Never load the same one again through another command (e.g.
  `Get-Content` after `orca skills get`). Read it again only when it is no
  longer in this conversation (after compaction or in a new conversation).
- Load only the skills and references this skill tells you to load. Do not
  read `--help` output for commands whose usage this skill or its references
  already give (e.g. `orca automations create`,
  `orca orchestration worker-start`).
- Do not re-read large outputs (full guides, Issue bodies, full worker
  transcripts, raw JSON) that the summaries already cover.

## Rules

- **Only the Coordinator may merge.** Workers must stop after their
  assigned phase and report through ORCA Orchestration.
- Preserve the existing `implement-review-merge` workflow,
  `pr-cross-review` requirements, and GitHub authentication conventions.
- Sync each PR with `main` only in merge preparation. Implementation
  workers never rebase while implementing, and the Coordinator never tells
  a worker still implementing to rebase, even after merging another PR. If
  a worker asks, tell it to send `worker_done` without rebasing.
- Never exceed the `pr-cross-review` per-PR review limit (`MAX_REVIEWS`),
  counting all phases and dispatches. Track this across worker restarts and
  pass it in every handoff.
- If a worker reports that the reviewer's quota is exhausted
  (`reviewer-quota-exhausted`) with a known reset time, do not ask the user:
  keep the PR blocked, make sure the Coordinator wakes at the reset, and
  retry the review then, following
  [Reviewer quota retry](references/review-quota-retry.md).
- If any other review failure occurs, the reset time is unknown, the
  quota retry fails again, the limit is reached, or a conflict cannot be
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
- Put every temporary file the Coordinator creates under `tmp/<run-id>/`
  in the repository root. When the Run ends, delete only that directory;
  never delete `tmp/` as a whole or other files in it (e.g. `rm -rf tmp/*`).
- Resolve routine technical decisions autonomously; ask the user
  only when a safe decision cannot be made.
