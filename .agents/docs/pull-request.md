# Pull request

## Agent review

- Request cross-reviews with the `pr-cross-review` skill (`skills/pr-cross-review/SKILL.md`). NEVER invoke `codex`/`claude` or `gh pr comment` directly for a review.
- Only the agent that created the pull request may request cross-reviews; a review agent must not request another review.
- Request the initial review once after creating the pull request.
- Request a re-review only after pushing a commit that fixes review findings. Do not request one when the previous review had no findings or when you only explained or disputed a finding without changing code.
- A re-review must not raise new findings about existing code outside the reviewed commit range.
- Wait for the review script to exit. Proceed only after exit status 0 and `review-posted: <comment-url>`; read that comment before acting on it.
- Reply on the pull request to every finding, stating what changed or why it was deferred.
- Changes to `skills/pr-cross-review/` itself take effect on the review run immediately (the skill is symlinked). If the change breaks the review run, report it instead of working around it.

## Merge conditions

- All CI checks have succeeded.
- No unresolved findings remain. A deferred or disputed finding, or reaching the review limit (`MAX_REVIEWS`) with findings left, requires user confirmation before merge.

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
