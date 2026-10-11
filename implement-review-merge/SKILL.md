---
name: implement-review-merge
description: Take a task from implementation to merge - implement, commit, push, open (or update) a pull request, get it cross-reviewed with the pr-cross-review skill, iterate on findings, sync with the latest main, confirm tests and CI pass, then merge. Use when asked to implement a task and see it through to merge, or to continue the work on the current branch until it is merged.
disable-model-invocation: false
---

# Implement, review, merge

- Carry a task through the full pull-request cycle. Stop and ask the user
whenever a step below says so; never merge on a guess.
- Respond in Japanese.

## Execution modes

- **Standalone (default):** Always use Standalone mode unless
  Orchestration worker mode is explicitly requested.
  Execute steps 1–10, including merge.
- **Orchestration worker:** Only when explicitly instructed by an ORCA
  Coordinator, execute the assigned phase:
  - **Implementation:** Execute steps 1–7, then report the PR URL,
    review status, review count, and any blockers. Do not merge.
  - **Merge preparation:** Execute steps 8–9 only after the Coordinator
    requests it. Report the synced commit, test/CI results, review
    status, total review count, and any blockers. Do not merge.
- In worker mode:
  - The Coordinator alone decides when and in what order to merge PRs.
  - Report blockers to the Coordinator instead of asking the user directly.
  - Preserve the **3-review limit per PR** across all phases and dispatches.
  - Report completion or failure using the ORCA Orchestration protocol.
  - Stop after the assigned phase; never proceed to the next phase
    without an explicit dispatch.
- Running inside ORCA does not implicitly enable worker mode.
  If the execution mode or assigned phase is unspecified, use
  Standalone mode.

## Workflow

### 1. Confirm the task

- If the task is not stated explicitly, infer it from the branch name.
- If you are not confident what the task is, ask before making changes.

### 2. Implement

Implement the task, or address the review findings from step 6.

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
- On success it prints `review-posted: <comment-url>`. Read that comment.

### 7. Iterate on findings

If the review has findings, go back to step 2.

- At most **3 reviews per pull request**.
- If the limit is reached, or the script exits with an error, do **not**
  merge. Report the situation and ask the user how to proceed.

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
- Re-reviews count toward the 3-review limit.

### 10. Merge

Merge only when all of the following hold:

- The latest review has no outstanding findings.
- The branch is in sync with the latest `main`.
- Tests and CI all pass on that synced state.

Otherwise, do not merge; report what is blocking and ask the user.
