---
name: orchestrate-issues
description: Coordinate multiple GitHub Issues through ORCA Orchestration. Delegate implementation and cross-review to parallel workers using the implement-review-merge skill, then verify and merge pull requests sequentially. Use when explicitly asked to orchestrate multiple issues or coordinate parallel development.
disable-model-invocation: true
---

# Coordinate GitHub Issues

- Act as the Coordinator. Delegate implementation to workers and retain
  exclusive responsibility for merging pull requests.
- Use ORCA Orchestration to manage tasks, dependencies, workers, and results.
- Respond in Japanese.

## 1. Plan and dispatch

1. Read `orca skills get orchestration --full` and follow the
   version-matched ORCA instructions.
2. Inspect the requested Issues, existing PRs, and completed work.
   Avoid duplicating or overwriting existing changes.
3. Identify dependencies, overlapping files, and potential conflicts.
4. Create one Orchestration Run, with one Task per Issue by default.
5. Represent actual dependencies in the task DAG.
6. Dispatch independent tasks to separate worktrees, with at most
   **3 workers running concurrently**.

## 2. Parallel implementation

7. Instruct each worker to run `implement-review-merge` explicitly in
   **Orchestration worker / Implementation** mode (steps 1–7).
   - Provide the Issue, scope, acceptance criteria, and dependencies.
   - Require implementation, tests, commit, push, PR creation,
     and `pr-cross-review` with findings addressed.
   - Workers must not merge.
8. Fill available worker slots before waiting for completions.
   Dispatch additional ready tasks as slots become available.
9. Track each Task's worktree, PR URL, review status, review count,
   and blockers. Verify reports rather than treating `worker_done`
   as proof of completion.

## 3. Sequential merge

10. Select the next PR based on dependencies and readiness.
11. Dispatch **Orchestration worker / Merge preparation** mode
    (steps 8–9) to the PR's worktree.
    - Fetch and rebase onto the latest `origin/main` as needed.
    - Re-run tests and CI after synchronization.
    - Repeat cross-review if substantive changes require it.
12. Independently verify:
    - No outstanding review findings.
    - No more than 3 cross-reviews for the PR.
    - The PR branch includes the latest `origin/main`.
    - Required tests and CI have passed on the current PR commit.
    - GitHub merge requirements are satisfied.
13. Merge the PR yourself only when all conditions are met.
14. After each merge, fetch the latest `origin/main` and repeat
    merge preparation for the next PR. If `main` changes before
    merging, revalidate the affected PR.
15. Mark only confirmed merged Issues as complete. Report the
    outcome and PR URL for each Issue.

## Rules

- **Only the Coordinator may merge.** Workers must stop after their
  assigned phase and report through ORCA Orchestration.
- Preserve the existing `implement-review-merge` workflow,
  `pr-cross-review` requirements, and GitHub authentication conventions.
- Never exceed **3 cross-reviews per PR**, counting all phases and
  dispatches. Track this across worker restarts.
- If a review fails, the limit is reached, or a conflict cannot be
  resolved safely, block that PR and ask the user.
- Continue other independent Tasks whenever possible.
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

Briefly present the execution plan, then start orchestration
without waiting for additional approval.
