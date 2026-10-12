---
name: pr-cross-review
description: Have the other coding agent review a GitHub pull request and post the review as a PR comment. Use after opening or updating a pull request when a cross-review is wanted - Claude Code launches a Codex reviewer, Codex launches a Claude reviewer. Handles re-reviews (only commits since the previous review), a per-PR review limit, timeouts, and confirms that the comment was actually posted.
disable-model-invocation: false
---

# PR cross-review

Spawn the *other* agent as a non-interactive reviewer for a pull request of the
current repository. Run the script from the repository root (it uses `gh` in
the current checkout).

| You are    | Run                                  |
|------------|--------------------------------------|
| Claude Code | `bash ~/.agents/skills/pr-cross-review/scripts/run_codex_review.sh <pr-number>` |
| Codex       | `bash ~/.agents/skills/pr-cross-review/scripts/run_claude_review.sh <pr-number>` |

Append `-- <text>` to add instructions to the review prompt (for example what
to focus on). Model, effort and other options can be overridden per run; see
[references/options.md](references/options.md). Persistent defaults live in
`~/.agents/skills/pr-cross-review/config.conf`.

## Result

- Success: the script prints `review-posted: <comment-url>` and exits 0.
  Read the comment with `gh pr view <pr-number> --comments` and address it.
- Failure: non-zero exit with an `error:` line on stderr. Report it rather than
  retrying blindly; exit codes are listed in references/options.md.

## Rules the scripts enforce

- The first review covers the whole PR; later reviews cover only commits added
  since the previous review. Re-running without new commits is rejected.
- At most `MAX_REVIEWS` (config.conf) cross-reviews per PR, Codex and Claude combined.
- A reviewer cannot launch another review (nested runs are rejected).
- The reviewer must post through `scripts/post_pr_comment.sh`, which adds the
  footer the scripts use to count reviews. Do not post review comments by hand
  with that footer.
- The reviewer writes the comment body to `<REVIEW_BODY_DIR>/pr-<number>-review-<agent>.md`
  (default `tmp/`, from the repository root). The run stops if git would not
  ignore that file, and `post_pr_comment.sh` rejects any other body file
  (both configurable in config.conf).

The run can take several minutes (Codex has a 30 minute hard timeout by
default), so run it in the background if your tooling supports that.

Do not redirect the script's output to a file in the working tree (for
example `> review_out.txt`). Use your tool's background-execution output
instead; if you must capture it to a file, create it with `mktemp` outside the
repository and delete it afterwards.
