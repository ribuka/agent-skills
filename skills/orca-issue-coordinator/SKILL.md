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

First identify this Coordinator's runtime as `<agent>` (`claude` or `codex`).
Workers always use that same agent; do not offer an independent worker-agent
override.

Then select the Orca executable once, as the installed `orchestration`
skill's `SKILL.md` says: the value of `ORCA_CLI_COMMAND` if set, otherwise
`orca-dev` in a dev checkout that exposes `ORCA_DEV_REPO_ROOT`, otherwise
`orca-ide` on Linux outside an Orca terminal, otherwise `orca`. Never run bare
`orca` when that procedure selects another executable. Before anything else,
run:

```bash
uv run <skill-dir>/scripts/check_preconditions.py --agent <agent> --orca <selected-executable>
```

It verifies that this conversation runs inside an Orca terminal, that the
selected executable resolves and its runtime is reachable and advertises
`orchestration.worker-auto-release.v1`, that `gh auth status` succeeds, and
that the git checkout the skills are installed from is on branch `main` and is
neither behind `origin/main` nor carrying commits or uncommitted skill changes
not on it (so no one runs stale skills). With `--agent codex` it also verifies that Codex
will not show its update prompt when a worker starts.
If it exits non-zero, the sender is unknown, or `run-create` later fails with
`no_active_sender_terminal`, **stop immediately** and report the `STOP:` lines
to the user. Never work around a failed precondition: do not try another Orca
executable, do not create a substitute Coordinator terminal
(`terminal create`), do not pass another terminal's handle to `--from`, and do
not unset, replace, or switch `gh` credentials (e.g. clearing `GH_TOKEN`). If
a sandbox denies access (e.g. `runtime_access_denied`), rerun the same command
outside the sandbox; that is not a failed precondition.

On success it prints `skill-checkout: <path>` and `orca-executable: <path>`;
keep both. `<orca>` below is that absolute executable path: use it for every
Orca command, in the checkpoint, and in every reservation, and never select
the executable again (e.g. with `Get-Command`).

Then, once, from the Coordinator's working repository, pin the skill checkout:

```bash
uv run --no-project <skill-dir>/scripts/local_main.py freeze
```

It prints `skill-checkout-frozen: <sha|no>` (`no` when the working repository
is not the skill checkout's repository); record that value in the checkpoint.
If it exits `1`, stop and report the `error:` line like any other failed
precondition. Never update (pull, rebase, or check out) the skill checkout
during the Run, even when merged PRs change skills: every worker must run the
same skill version. Only `local_main.py freeze` and `finish` (step 17) may
touch it, because Orca fast-forwards the local `main` each time it creates a
worktree, which would otherwise swap the skills mid-Run.

Then read Orca's version-matched compact guide and its DAG reference, once
each: `<orca> skills get orchestration` and
`<orca> skills get orchestration --reference references/coordinator-loop.md`.
Do **not** use `--full`. Load another bundled reference (recovery, placement,
messaging) only when its action gate applies, with the same `--reference`
form.

Then resolve the worker settings for `<agent>`.

Run once at the start, passing through any `--impl-model`, `--impl-effort`,
`--merge-model`, `--merge-effort`, `--max-workers`, or
`--fresh-worker-context-tokens` flags the user gave.
If the user explicitly asks to run the Issues serially (one at a time), pass
`--max-workers 1`:

```bash
uv run <skill-dir>/scripts/resolve_config.py --agent <agent> [user flags]
```

It prints the agent, the `--model` / `--effort` pair for each phase, the
`max-workers: <n>` concurrency limit (`MAX_WORKERS`), the
`fresh-worker-context-tokens: <n>` resume threshold
(`FRESH_WORKER_CONTEXT_TOKENS`, see **Quota control**), and each value's source
(argument > `<skill-dir>/config.conf` > defaults). Configuration keys are
`CLAUDE_IMPL_MODEL`, `CLAUDE_IMPL_EFFORT`, `CLAUDE_MERGE_MODEL`,
`CLAUDE_MERGE_EFFORT`, their `CODEX_` equivalents, and shared `MAX_WORKERS`
and `FRESH_WORKER_CONTEXT_TOKENS`.
Unprefixed model/effort keys are not supported. Claude defaults remain
`opus`/`medium` for implementation and `sonnet`/`medium` for merge preparation;
Codex defaults are `gpt-6.1-sol`/`medium` for both phases.
Concurrency defaults to 3; the resume threshold to 200000 tokens. Always pass `--agent <agent>` and the resolved
model/effort on every `worker-start`, and never exceed `MAX_WORKERS`.
Claude effort values: `low`, `medium`, `high`, `xhigh`, `max`;
Codex: `minimal`, `low`, `medium`, `high`, `xhigh` (no `max`).

### Starting workers

Start every worker through the bundled script, never with a bare
`worker-start`:

```bash
uv run --no-project <skill-dir>/scripts/start_worker.py --orca <orca> -- <worker-start arguments>
```

It runs `worker-start ... --json --full` once and judges the detailed receipt
by its `state` / `stage` fields, not by `worker-start`'s exit code. It prints
`start: <class>` and the `dispatch:`, `task:`, `run:`, and `effective:` lines;
record the dispatch ID in the checkpoint at once. Exit codes:

- `0` ready: the receipt's `launch.effective` matches the requested agent,
  model, and effort.
- `3` unobserved: the task was typed in but the worker was not yet seen
  starting. Do not resend or abandon it; save the checkpoint and end the turn.
  Orca wakes you when it reports.
- `1` failed (`failed`, or `outcome_unknown` otherwise): do not rerun. Read its
  `failed-stage:`, `error:`, and `next:` lines and load Orca's
  `references/recovery-and-cleanup.md`.
- `2` invalid (no detailed receipt, or a field the decision needs is missing):
  treat it as a failed start and do not rerun; reconcile with
  `list_workers.py` (step 10) before anything else.
- `4` launch mismatch: the worker runs with other launch preferences than
  requested. Handle it like a provider rejection (below).

A ready receipt confirms launch preferences, not successful model execution.
When resuming or inspecting a worker that has produced no assistant result,
inspect bounded worker output for provider errors even if the worker list says
live/working. A positive provider rejection blocks that attempt: load Orca's
`references/recovery-and-cleanup.md`, stop the failed attempt with
`worker-stop --dispatch <dispatch-id>` following its authority rules, report
the blocker and ask the user for a supported model. Do not retry the rejected
model or automatically fall back to another model. Silence alone is not
evidence of failure and does not authorize stopping.

After three failed starts of one Task, Orca circuit-breaks it: stop automatic
retries and report the failure. Never route around the breaker with a new Task
or Run, and reopen the Task only when the user explicitly asks.

If a `worker-start` fails with `Agent startup blocked: agent-update-prompt`,
the agent CLI showed its update prompt in the worker terminal. The
precondition check cannot rule this out for the whole Run: Codex refreshes
its cached latest version in the background. Never answer the prompt by
sending keys to the worker terminal (`<orca> terminal send`); its menu options
change between versions. Stop dispatching, release the failed dispatch, and
ask the user to update the agent CLI or dismiss the prompt. Retry the Task
with `--retry-of` only after the user confirms.

## 1. Plan and dispatch

1. Run every Orca command as `<orca> orchestration <command>` (shortened to
   `<command>` below), using the guide and DAG reference loaded in step 0.
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

   Then decide the execution order:
   - **Listed Issues** (e.g. "#1,2,3,4 serially"): the list sets which Issues
     to run and how many at once, not their order. Plan the order from the
     dependencies and overlaps above; keep the listed order only when it
     fits them. For example, if #1 depends on #3, #3's PR is merged before
     #1 starts.
   - **Explicit order** (e.g. "#1 → #2 → #3 → #4 serially", "in this
     order"): follow it when it fits the dependencies. If it does not, name
     the Issues involved and the reason, and ask the user for the order
     before the first dispatch.
4. Create one Orchestration Run. Then, before any dispatch, set up the
   quota guard with this Run ID (see **Quota control**), and save the Run
   checkpoint described in [Waiting](references/waiting.md). Plan one Task per
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
   - Every implementation dispatch starts a new top-level worktree named
     after the Issue. Pass exactly these `start_worker.py` arguments (only
     the first part differs):
     `<start> --worktree new-top-level --name issue-<n> --setup run --agent <agent> --model <impl-model> --effort <impl-effort>`,
     where `<start>` is `--spec "<brief>" --task-title "#<n> <title>"`
     or `--task <task_id>`. Orca keeps a new-worktree worker open after it
     reports (step 11). `--worktree new` does not exist
     (`selector_not_found`), and omitting `--name` gives a random name; do
     not load the placement reference for this.
5. Represent actual dependencies in the task DAG, including the
   same-part overlaps from step 3. Orca unblocks a dependent
   Task as soon as its dependency Task completes, and an Implementation Task
   completes when its PR is opened, before the PR is merged. Dispatch a
   dependent Task only after every dependency's PR has been **merged**; never
   dispatch on Orca's ready state (`task-list --ready`) alone. Tell its
   worker to start from the
   latest `origin/main`, which includes those merges.
6. Before the first dispatch, briefly present the execution plan to the
   user: Task dependencies, dispatch order, and the resolved worker model,
   effort, and `MAX_WORKERS` from step 0. For Tasks that edit the same file
   but run in parallel, state that decision and its reason (e.g. which
   parts each edits). Then start dispatching without waiting for approval,
   unless step 3 requires asking for the order.
   Dispatch independent tasks to separate worktrees, with at most
   **`MAX_WORKERS` workers running concurrently**. Merge-preparation workers
   count toward this limit. With `MAX_WORKERS=1`, run fully serially:
   implement one Issue, prepare and merge its PR, and only then dispatch the
   next Issue. Start each worker with `start_worker.py` (**Starting
   workers**) as step 4 decided for its Task: `--spec` for an independent
   Task, `--task <task_id>` for a Task created with `task-create`.
   Run the quota `check` before each
   dispatch and dispatch only on READY. Always pass `--agent <agent>` and the implementation
   `--model` and `--effort` from step 0. Before any dispatch, check the
   checkpoint and live state for a dispatch already started for that Task and
   phase; never start a second one.

## 2. Parallel implementation

7. Instruct each worker to run `implement-review-merge` explicitly in
   **Orchestration worker / Implementation** mode.
   - Provide the Issue number, scope, acceptance criteria, and dependencies.
     Tell the worker to read the Issue itself.
   - Do not restate general token-saving rules in the brief: the worker
     loads them with `implement-review-merge` (its **Token budget**). Add
     only limits specific to the Issue, such as the E2E suite or benchmark
     scale it needs.
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
   - If a tool call is denied because the 5-hour quota is `PAUSED_QUOTA`,
     the worker stops at a safe boundary and reports with
     `worker_done --outcome failed`, including the `worker-quota-paused:`
     and `context-tokens:` lines, as `implement-review-merge` says.
   - Tell the worker to stop only processes it started itself, by PID, and
     never by image name (e.g. `taskkill /IM uv.exe`, `pkill python`): that
     also kills the Coordinator's and other workers' processes.
8. Fill available worker slots before waiting for completions.
   Dispatch additional tasks as slots become available, holding back
   dependent Tasks until their dependency PRs are merged (step 5).
9. Then save the checkpoint and end the turn; Orca wakes you (see
   **Waiting**). Never run a watcher, a waiter, or a `check` loop.
10. Track each Task's worktree, branch, PR URL, review status, review count,
    and blockers. Verify reports rather than treating `worker_done`
    as proof of completion; a failed `worker_done` is never a completed Task.
    Run the quota `check` after processing each `worker_done`. To inspect
    workers, list every worker of the Run, across all pages:

    ```bash
    uv run --no-project <skill-dir>/scripts/list_workers.py --orca <orca> --run <run-id> [--terminal-state <state>]
    ```

    It reads `worker-list --json --full` page by page and prints one JSON row
    per worker (`dispatch`, `task`, `state`, `terminalState`, `liveness`,
    `autoReleaseAt`, `next`), then `{"workers": <n>, "pages": <n>}`, and exits
    `0`. Exit `1` with `{"error": ...}` means the list is incomplete (a CLI
    error, malformed JSON, a missing field, or an incomplete host inventory):
    never read it as "no workers". When a row's `next` is not empty, follow
    that command.
11. Workers in an existing worktree (merge preparation, review retry) close
    on their own after `worker_done` (`autoReleaseAt`); do not release them.
    An Implementation worker runs in a new top-level worktree, which Orca
    keeps open. Do not release a worker that reported `worker-quota-paused:`
    until the quota pause reference says so. After verifying any other
    `worker_done`, release it
    (`worker-release --dispatch <dispatch_id>`); merge preparation starts a
    fresh worker. On `release_pending` or `release_unknown`, follow the
    receipt's recovery action and Orca's `references/recovery-and-cleanup.md`;
    never close the terminal another way. Never release a worker the user
    kept open or took over.

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
    - The latest cross-review saw the current head commit: the
      `review-latest-commit: <sha>` line of
      `bash ~/.agents/skills/pr-cross-review/scripts/review_status.sh <pr-number>`
      (or the head the user approved with **Merge as is**, Run checkpoint)
      equals `gh pr view <pr> --json headRefOid --jq .headRefOid`. Do not
      read review comment bodies for this. When they differ, commits were
      pushed after the latest review (**Unreviewed head** below).
    - **Unreviewed head:** while `<count>` in `review-count: <count>/<max>`
      is below `<max>`, do not take this shortcut: run step 13, and state
      the reviewed commit and the head in its handoff. Once the limit is
      reached, follow **Limit reached with unreviewed fix commits**
      (**Rules**) instead.
13. When a worker slot is free (within `MAX_WORKERS`) and after a READY
    quota `check`, start a **new** worker for
    **Orchestration worker / Merge preparation** mode in the PR's existing
    worktree, with `start_worker.py` (**Starting workers**) and these
    arguments, using the merge-preparation model and effort from step 0:
    `--spec "<handoff>" --task-title "#<issue> PR #<pr> merge prep" --worktree branch:<branch> --agent <agent> --model <merge-model> --effort <merge-effort>`.
    The Implementation Task is already completed and cannot be started again,
    so do not pass `--task <task_id>`. Do not reuse the implementation
    worker's conversation. The `<handoff>` is short:
    - Issue number, PR URL, branch, and worktree.
    - Cross-reviews used so far (the latest `review-count: <count>/<max>`)
      and any open findings or blockers.
    - When the latest cross-review did not see the head (**Unreviewed
      head** in steps 12 and 14): the reviewed commit and the head, and the
      task to run cross-review on the unreviewed commits and address its
      findings before rebasing. When the user chose **Merge as is** for
      the head instead: that head, and that the user approved merging it
      without a further review.
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
      (naming the files), whether cross-review was repeated, and the PR
      head before the rebase and after it (full SHAs).
14. Independently verify:
    - Only if the merge-preparation worker reported a `newly written`
      resolution: a cross-review ran after it with no outstanding findings.
      If that review is missing, has open findings, or could not run
      because the limit was reached, block the PR and ask the user.
    - No outstanding review findings.
    - The latest cross-review saw the current head commit:
      `review-latest-commit` (from `review_status.sh`, below), or the head
      the user approved with **Merge as is** (Run checkpoint), equals
      `gh pr view <pr> --json headRefOid --jq .headRefOid`. A rebase in
      merge preparation changes the head without a new review; accept that
      difference only when the merge-preparation worker reported a `none`
      or `mechanical` resolution, its head before the rebase equals
      `review-latest-commit` or that approved head, and its head after the
      rebase equals the current head. Any other difference is an
      **Unreviewed head**: under the limit, start merge preparation
      (step 13) with the reviewed commit and the head in the handoff; once
      the limit is reached, follow
      **Limit reached with unreviewed fix commits** (**Rules**). Do not
      merge until this check passes.
    - No more than `<max>` cross-reviews on the PR, plus the extra reviews
      the user approved for it: run
      `bash ~/.agents/skills/pr-cross-review/scripts/review_status.sh <pr-number>`
      and check its `review-extra: <count>` line: it must not exceed the
      extra reviews the user approved for this PR (`0` without approval).
      Do not compare `review-count: <count>/<max>` with `<max>` alone; after
      an approved extra review it is above `<max>` (e.g. `4/3` with
      `review-extra: 1`). Do not count PR comments yourself; other
      comments are mixed in. Compare this output with the review count in
      the worker handoff; if they differ, use the script's count and note
      the mismatch in the Issue's report (step 17). If the script exits non-zero,
      block the PR and ask the user.
    - The PR branch includes the latest `origin/main`.
    - Required tests and CI have passed on the current PR commit.
    - GitHub merge requirements are satisfied.
    - If CI checks are pending, follow **Pending CI** in
      [Waiting](references/waiting.md) in both Claude Code and Codex: record
      the PR, head, and 30-minute deadline, reserve one wake-up at the
      earlier of 15 minutes from now and the deadline, end the turn, and
      inspect once on that wake-up. Never run `gh pr checks --watch` or merge
      while pending. Past the deadline, report `monitor-error: <reason>` and
      block this PR. Recheck the current head and all CI checks before
      merging.
    - **If a CI check fails:** read only the failed part
      (`gh run view <run-id> --log-failed`, tail). Only when the failure is
      unrelated to the PR's diff (e.g. a timeout or network error in a test
      the PR does not touch), rerun the failed jobs once yourself
      (`gh run rerun <run-id> --failed`), note the rerun and the test name
      for the Issue's report, and wait for CI again. If the failure relates
      to the diff, or the rerun fails again, do not rerun further: start
      merge preparation (step 13) with the failure in the handoff, or block
      the PR and ask the user. In step 17, list every rerun and suggest an
      Issue for a test that failed this way more than once.
15. Merge the PR yourself only when all conditions are met and the quota
    `check` immediately before the merge is READY.
16. After each merge, fetch the latest `origin/main` and repeat
    merge preparation for the next PR. If `main` changes before
    merging, revalidate the affected PR. Dispatch any dependent Task whose
    dependency PRs are now all merged (see step 5).
17. Mark only confirmed merged Issues as complete. Report the
    outcome and PR URL for each Issue.
    Remove this Run's reservation, if any (**Run completion** in
    [Waiting](references/waiting.md)).
    Then end the Run. ORCA has no command that closes a Run; the Run ends
    when no worker terminal still owes a decision. Run `list_workers.py`
    (step 10) for the whole Run and reconcile every row: no worker may be
    `active`; follow every non-empty `next`; release a `reclaimable` worker
    nobody will use; report `release_pending` / `release_unknown` and
    unresolved `stop_unknown` results as unresolved blockers, not as done.
    A worker the user kept open or took over stays open: name it in the
    report as intentionally retained. Do not report the Run complete while
    a release or an unknown state remains. Finally delete this Run's
    files with these commands only, from the Coordinator's working
    repository:
    - Temporary directory:
      `uv run --no-project <skill-dir>/scripts/cleanup_run.py --run-id <run-id>`.
      It deletes only `tmp/<run-id>/` under the git top level of the current
      directory and prints one JSON line `{"status": ..., "path": ...}`.
      Exit `0`: removed or already absent; `1`: deletion failed, `path`
      remains; `2`: refused (invalid Run ID, or the path resolves outside
      `tmp/<run-id>/`), nothing deleted.
    - Quota checkpoint (see **Quota control**):
      `uv run --no-project ~/.agents/skills/quota-guard/scripts/quota_guard.py clear-checkpoint --provider <agent> --operation <run-id>`.
      Exit `0`: deleted or already absent; `1`: deletion failed, `path`
      remains; `2`: invalid Run ID, nothing deleted.
    - If either command exits non-zero or is rejected (e.g. by an approval
      policy), do not retry with another command (`rm -rf`, `Remove-Item`,
      ...); report the remaining paths to the user.

    Read the checkpoint's `skill-checkout-frozen:` value before running
    `cleanup_run.py`. As the Run's very last command (so the two commands
    above still run the pinned skill version), from the Coordinator's
    working repository, run
    `uv run --no-project <skill-dir>/scripts/local_main.py finish --frozen <sha|no>`
    with that value. It restores a pinned skill checkout to its branch and
    fast-forwards the working repository's local default branch to
    `origin`. Report its `local-main:` result (`updated`, `up-to-date`, or
    `skipped (<reason>)`, stating the reason). If it exits non-zero, do not
    fix it with other commands; report the `error:` line and the same
    `finish` command to the user.

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
  each `worker_done`, and on every resume. Continue only on
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
  timed wake-ups. Workers never create wake-ups.
- **Workers stop themselves:** the Coordinator's checks only run at its own
  boundaries, so a running worker stops itself at the quota pause (a
  PreToolUse hook denies its tool calls) and sends `worker_done
  --outcome failed` with a `worker-quota-paused: <quota JSON>` line and a
  `context-tokens: <n|unknown>` line. Treat that report as a quota pause, not
  as a failed Task: follow the quota pause reference below, which also
  chooses how to resume the worker by comparing `context-tokens` with
  `FRESH_WORKER_CONTEXT_TOKENS` (step 0).
- **Workers stopped by the usage limit:** an `escalation` with
  `failureKind=usageLimitReached` is also a quota pause. Never resume that
  worker with `send`: stop its dispatch with `worker-stop` and retry the Task
  with `--retry-of` and a fresh worker, as the quota pause reference says.
- **On PAUSED_QUOTA or UNKNOWN:** stop starting all new work, then read
  `~/.agents/skills/orca-issue-coordinator/references/quota-pause.md` and
  follow it (checkpoint, stopping workers, exactly one wake-up, end the turn).
- **While paused or on wake-up:** whatever wakes the Coordinator (the quota
  wake-up, a worker message, a user message, or any other notification), first
  follow that same reference before doing anything else, even if this
  conversation's context has been compacted.

## Messaging workers

Send every message to a worker (follow-ups, stop requests, resume requests)
to its Dispatch: `<orca> orchestration send --to dispatch:<dispatch_id> ...`.
Take the dispatch ID (`ctx_…`) from the `start_worker.py` output and record it
with the Task; no terminal handle is needed.

- Always keep the `dispatch:` prefix. A bare `--to ctx_…` fails with
  `terminal_not_found`.
- `--to dispatch:<dispatch_id>` addresses that exact attempt. After a
  re-dispatch, send to the new dispatch ID.

### Answering worker questions

- **Within the Issue as written:** if the Issue's scope and acceptance
  criteria still hold whichever way you answer, answer the worker yourself.
- **Changes the Issue:** if the only answers drop, add, or weaken a scope
  item or acceptance criterion (e.g. the Issue contradicts itself), do not
  decide. Reply to the worker that it must wait for the user's decision, then
  ask the user (see **Asking the user**), naming the affected criterion.
  Answer the worker only after the user replies.

## Asking the user

These rules apply to every question to the user, in both Codex and Claude
Code Coordinators (blockers, decisions, model choices, or anything else).

- **Write the full question in the final message of the turn.** Never rely
  only on `request_user_input_async`, `AskUserQuestion`, or another
  input UI: later terminal input (Orca notifications, wake text) and
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
  notification-only and wake-up turns) with a one-line reminder that names the
  pending question and the expected reply, instead of an empty or
  waiting-only message.

## Waiting

Follow [Waiting](references/waiting.md) in both Claude Code and Codex
(`~/.agents/skills/orca-issue-coordinator/references/waiting.md`):

- After starting the workers the Run can start, save the checkpoint and end
  the turn. Orca wakes you when a worker reports; never run a waiter,
  watcher, `check --wait`, or `check` loop, and never schedule a wake-up just
  to look at workers or wait for the user.
- A consuming `check` marks its batch read; there is no `--ack` step.
- Reserve a timed wake-up only for a known time (pending CI, a reviewer quota
  retry, the quota resumption), at most one per Run, at the earliest such
  time.
- Every resume (notification, user message, or timed wake-up) checks quota,
  reconciles the checkpoint with live state once, and never repeats a
  dispatch, phase, or merge already done.

## Token budget

- Handle every notification as **Receive messages** in
  [Waiting](references/waiting.md) says, then end the turn. Do not assume
  how often heartbeats arrive or what they say; one with no work needs no
  tool call, only one short line (e.g. `待機中`). If a question to the user
  is pending, that line is the reminder from **Asking the user**.
- **While the quota is paused,** handle every wake-up as in the quota pause
  reference (see **Quota control**).
- Report to the user only when state changes (dispatch, worker_done, merge,
  blocker, question). Never post "no news yet" updates.
- Keep reports short: Issue, PR URL, state, next step.
- **Read each guide or reference at most once per Run:** a skill's
  `SKILL.md`, an `<orca> skills get` guide or `--reference`, and this skill's
  `references/`. Never load the same one again through another command (e.g.
  `Get-Content` after `skills get`). Read it again only when it is no
  longer in this conversation (after compaction or in a new conversation).
- Load only the skills and references this skill tells you to load. Do not
  read `--help` output for commands whose usage this skill or its references
  already give (e.g. `automations create`, `worker-start`).
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
  counting all phases and dispatches, except for extra reviews the user
  approved (below). Track this across worker restarts and pass it in every
  handoff.
- **Limit reached with unreviewed fix commits:** when a PR reached the
  limit (`MAX_REVIEWS` plus any approved extra reviews) and commits were
  pushed after its latest cross-review (e.g. fixes for its findings;
  **Unreviewed head** in steps 12 and 14), block
  the PR and ask the user with these options:
  - **Merge as is:** record the approved head (full SHA) in the Run
    checkpoint and continue merging; the latest commits stay unreviewed.
    The approval covers only that head (steps 12 and 14). If merge
    preparation is needed, its handoff states that the user approved
    merging that head without a further review.
  - **One extra review:** record the approval in the Run checkpoint and
    start a fresh worker in the PR's worktree for the phase that hit the
    limit. Its handoff states that the user approved exactly one extra
    review and tells it to run the review script with `--extra-review`
    (e.g. `bash ~/.agents/skills/pr-cross-review/scripts/run_codex_review.sh <pr-number> --extra-review`).
    Each further extra review needs a new approval.
  - **Stop:** leave the PR open and unmerged, and report it.

  Never edit another skill's config file (e.g. to raise `MAX_REVIEWS`), and
  never tell a worker to do so.
- If a worker reports that the reviewer's quota is exhausted
  (`reviewer-quota-exhausted`) with a known reset time, do not ask the user:
  keep the PR blocked, make sure the Coordinator wakes at the reset, and
  retry the review then, following
  [Reviewer quota retry](references/review-quota-retry.md).
- If any other review failure occurs, the reset time is unknown, the
  quota retry fails again, the limit is reached (with unreviewed commits,
  use the options above), or a conflict cannot be resolved safely, block
  that PR and ask the user.
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
  in the repository root. When the Run ends, delete only that directory, with
  `cleanup_run.py` (step 17); never delete `tmp/` as a whole or other files
  in it (e.g. `rm -rf tmp/*`), and never delete workers' files.
- Resolve routine technical decisions autonomously; ask the user
  only when a safe decision cannot be made. Changing an Issue's scope or
  acceptance criteria is never routine (see **Answering worker questions**).
