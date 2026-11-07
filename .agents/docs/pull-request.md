# Pull request

## Agent review

- Follow the `implement-review-merge` skill for the review cycle (review, fix, sync with `main`, merge) and the `pr-cross-review` skill for running a review. Those skills and the review scripts are the source of truth; this section only adds repository rules.
- NEVER invoke `codex`/`claude` or `gh pr comment` directly for a review.
- Only the agent that created the pull request may request cross-reviews.
- Do not request a cross-review for a version bump (`bump-version` skill).
- Request a re-review only after pushing a commit that fixes review findings, or when a sync with `main` changed the implementation in substance. Otherwise do not request one (e.g. when the previous review had no findings, or when you only explained or disputed a finding without changing code).
- Reply on the pull request to every finding, stating what changed or why it was deferred.
- Changes to `skills/pr-cross-review/` itself take effect on the review run immediately (the skill is symlinked). If the change breaks the review run, report it instead of working around it.

## Merge conditions

- The branch is in sync with the latest `main`, and all CI checks have succeeded on that state.
- No unresolved must findings remain. A deferred or disputed must finding, or reaching the `pr-cross-review` per-PR review limit (`MAX_REVIEWS`) with must findings left, requires user confirmation before merge. Optional suggestions do not block merging; reply with the reason for not adopting each one and report valuable suggestions as follow-up candidates per `implement-review-merge`.

## Model labeling

- **ALWAYS** add exactly one model-family label:
  - `model:gpt`
  - `model:claude`
- Create the required label if it does not exist.
- **NEVER** create any other `model:*` label.

## Optional information

- Optionally add the following information to the pull request description:
  - `Implementation agent: <agent>`
  - `Implementation model: <exact model>`
  - `Reasoning effort: <reasoning effort>`

Example:

```text
Implementation agent: Claude Code
Implementation model: claude-opus-5-5
Reasoning effort: high
```

## Attribution

- NEVER include session URLs (e.g. `https://claude.ai/code/session_...`) in pull request descriptions.
  - Omit the trailing session link.
- The "Generated with Claude Code" line is allowed.
