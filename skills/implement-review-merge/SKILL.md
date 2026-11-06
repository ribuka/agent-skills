---
name: implement-review-merge
description: Take a task from implementation to merge - implement, commit, push, open (or update) a pull request, get it cross-reviewed with the pr-cross-review skill, iterate on findings, sync with the latest main, confirm tests and CI pass, then merge. Use when asked to implement a task and see it through to merge, or to continue the work on the current branch until it is merged.
disable-model-invocation: false
---

# Implement, review, merge

- Carry a task through the full pull-request cycle. Stop and ask the user
whenever a step below says so; never merge on a guess.
- Respond in Japanese.
- Follow **Token budget** (at the end) throughout, in every mode.

## Execution modes

- **Standalone (default):** Always use Standalone mode unless
  Orchestration worker mode is explicitly requested.
  Execute steps 1–10, including merge.
- **Orchestration worker:** Only when explicitly instructed by an ORCA
  Coordinator, execute the assigned phase:
  - **Implementation:** Execute steps 1–7, then report the PR URL,
    branch, review status, review count (the latest
    `review-count: <count>/<max>` from `pr-cross-review`), open findings,
    and any blockers, so a fresh worker can take over. Do not merge.
  - **Merge preparation:** Execute steps 8–9 only after the Coordinator
    requests it. This usually starts in a new conversation: rebuild the
    state from the Coordinator's handoff, `gh pr view <pr-number>` (without
    `--comments`), and the `pr-cross-review` status script
    (`bash ~/.agents/skills/pr-cross-review/scripts/review_status.sh <pr-number>`,
    which prints `review-count: <count>/<max>`,
    `review-latest: <comment-url>`, and `review-latest-commit: <sha>`)
    before step 8. Read only the latest review comment, and use the larger
    of the handed-off review count and the printed count. If
    `review-latest-commit` differs from the PR's `headRefOid`, commits were
    pushed after the latest review: before step 8, run steps 6–7 on them
    within the review limit, or report a blocker if the limit is reached.
    Skip this re-review only when the handoff states that the user
    approved merging that head without a further review.
    Report the head before and after the sync (full SHAs), test/CI results,
    review status, total review count, and any blockers. Do not merge.
- In worker mode:
  - The Coordinator alone decides when and in what order to merge PRs.
  - Report blockers to the Coordinator instead of asking the user directly.
  - Preserve the `pr-cross-review` per-PR review limit (`MAX_REVIEWS`)
    across all phases and dispatches.
  - Report completion or failure using the ORCA Orchestration protocol.
  - Stop after the assigned phase; never proceed to the next phase
    without an explicit dispatch.
  - **Resumed phase:** when the branch already has a pull request (a phase
    retried after a stop), rebuild the state before continuing, as
    Merge preparation does: `gh pr view <pr-number>` (without `--comments`),
    `review_status.sh`, the latest review comment only, and
    `git status` for changes left uncommitted. Continue with the remaining
    work; do not redo finished steps.
  - **Quota pause:** when a tool call is denied with a reason that the
    5-hour quota is `PAUSED_QUOTA`, stop the phase at the nearest safe
    boundary (commit and push finished changes, or let a running review
    finish; leave uncommitted changes in the worktree). Never stop
    mid-rebase: if a rebase, merge, or cherry-pick is in progress, run its
    `--abort` (e.g. `git rebase --abort`) and list it in the work left. Only
    the commands the denial allows still run. Then run
    `uv run --no-project ~/.agents/skills/implement-review-merge/scripts/context_tokens.py --provider <claude|codex>`
    (prints `context-tokens: <n>`, or `context-tokens: unknown`) and send
    `worker_done --outcome failed` whose body has the handoff fields, the
    work left in the phase, and these two lines, each on its own line:
    `worker-quota-paused: <the quota JSON from the denial, unchanged>` and
    `context-tokens: <n|unknown>` as printed. Do not wait for the reset,
    retry, or schedule a wake-up; the Coordinator resumes the work.
- Running inside ORCA does not implicitly enable worker mode.
  If the execution mode or assigned phase is unspecified, use
  Standalone mode.

## Workflow

### 1. Confirm the task

- If the task is not stated explicitly, infer it from the branch name.
- If you are not confident what the task is, ask before making changes.

### 2. Implement

Implement the task, or address the review findings from step 6.

Run the relevant tests as **Token budget** below says.

### 3. Commit

Commit the changes with a message that describes them.

### 4. Push

Push the branch to `origin`.

### 5. Open or update the pull request

- First pass: create the pull request.
- After a review: reply to the review comment, stating how each finding was
  addressed (or why it was not).

### 6. Cross-review

Run the `pr-cross-review` skill for the pull request.

- Wait for the script to finish; do not continue while it is running.
- On success it prints `review-posted: <comment-url>` and
  `review-count: <count>/<max>`. Keep the count, and read only that
  comment: `gh api repos/{owner}/{repo}/issues/comments/<id> --jq .body`,
  where `<id>` is the number after `#issuecomment-` in the URL. Do not read
  all PR comments with `gh pr view --comments`.
- If the reviewer's quota is exhausted, the script exits 75 and prints
  `reviewer-quota-exhausted: <agent>`, `reviewer-quota-detected-at: <time>`,
  and `reviewer-quota-reset: <reset-time>`.
  No review was posted. Do not wait for the reset or retry on your own.
  In Standalone mode, ask the user, stating the reset time. In worker mode,
  stop the phase and send `worker_done` with `--outcome failed`, the handoff
  fields, and the three lines exactly as printed.

### 7. Iterate on findings

If the review has findings, go back to step 2.

- `pr-cross-review` allows at most `MAX_REVIEWS` reviews per pull request;
  the script rejects further runs.
- If the limit is reached, or the script exits with an error, do **not**
  merge. Report the situation and ask the user how to proceed.
- Run a review beyond the limit only when the user (in worker mode, the
  Coordinator's handoff) approved one extra review: add `--extra-review` to
  the review script, once per approval. Never edit `pr-cross-review`'s
  config file to raise the limit.

### 8. Sync with the latest `main`

```bash
git fetch --prune origin
```

- If the branch is behind `origin/main`, run `git rebase origin/main`.
- If conflicts occur, read both sides and resolve them correctly.
- If a conflict cannot be resolved safely, do **not** merge; ask the user.
- If the rebase rewrote history, push with `git push --force-with-lease`.
  Never use `git push --force`.

### 9. Re-verify on the synced branch

Re-run the tests and CI on the branch as synced with `main`, and confirm that
everything passes.

- If the rebase or conflict resolution changed the implementation in
  substance, re-run `pr-cross-review` as needed.
- Re-reviews count toward the `MAX_REVIEWS` limit.

Keep test and CI output small (see **Token budget**); never read full logs:

- Wait for CI with `gh pr checks <pr> --watch --interval 30` using only
  GitHub CLI's built-in features; never pipe to an external `jq` or write
  a custom CI polling loop.
- Set a finite overall timeout before starting, collect the background
  result through automatic completion notifications only when the harness
  guarantees them and enforces a hard timeout; otherwise poll the same
  process at least once per minute. Stop and report
  `monitor-error: <reason>` on a monitoring error or timeout. A tool yielding
  a session ID is not a timeout. Follow [CI waiting](references/ci-waiting.md)
  for process ownership, exit codes, and verification before merging.
- Only when a check fails, run `gh run view <run-id> --log-failed` and read only
  the part you need (e.g. the tail), not the whole log.

### 10. Merge

Merge only when all of the following hold:

- The latest review has no outstanding findings.
- The branch is in sync with the latest `main`.
- Tests and CI all pass on that synced state.

Otherwise, do not merge; report what is blocking and ask the user.

## Token budget

These rules apply in every mode. Each tool call re-sends the whole
conversation, so a large context multiplies the cost of every later step.
Where skipping a step would lower quality, do it only when needed and keep
its scope narrow.

- **Broad investigation:** delegate it to a subagent and take back only a
  summary. Before changing code, read the lines you change yourself.
- **Files:** read only the lines you need. Do not re-read a file whose
  content is still in the conversation.
- **Tests:** while developing, run only the related tests (one file or
  `-k`). Run the full pytest and E2E suites once, before pushing. Use
  options that narrow the output (e.g. pytest `-q --tb=short`) and read only
  the information about failed tests.
- **Benchmarks:** while developing, run on small data with few repetitions.
  Run once at the scale the acceptance criteria require, at the end.
- **Images** (screenshots, E2E captures): do not load them into the
  conversation by default. Only when the acceptance criteria require a
  visual check, load downscaled images one at a time.
- **Command output:** keep it short (`tail`, `head`, `-q`, filters). Do not
  repeat the same short command in a tight loop; wait as step 9 describes.
