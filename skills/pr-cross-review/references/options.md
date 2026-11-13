# pr-cross-review options

## Settings

Each value comes from, in order of precedence:

1. The matching command-line option, for a single run.
2. `config.local.conf` in the skill directory: the user's personal settings,
   ignored by git and optional. Set only the keys to change.
3. `config.conf` in the skill directory: the shared defaults, the only place
   defaults are defined. A missing key stops the script.

Both files use the same format, with LF or CRLF line endings:

- One `KEY=value` per line. Blank lines and lines whose first non-blank
  character is `#` are skipped.
- Spaces around the key and the value are trimmed. Everything after the first
  `=` is the literal value, keeping inner spaces and `=`: no shell evaluation,
  no quote removal, no inline comments.
- Examples: `MAX_REVIEWS=5`, `CLAUDE_EFFORT=high`, `REVIEW_BODY_DIR=tmp/review drafts`.

Every script (`run_*_review.sh`, `review_status.sh`, `post_pr_comment.sh`)
checks both whole files before any GitHub lookup or reviewer launch. An
unknown key, a duplicate key, an empty value, a line without `=`, or an
unreadable file prints `error: <file>: ...` to stderr and exits 1. Final values
are then checked as the options are. `MAX_REVIEWS` is a decimal integer from 1
to 2147483647 without leading zeros.

`MAX_REVIEWS` is the normal per-PR limit for every PR; the run scripts and
`review_status.sh` use the same effective value. To go past it on one PR, use
`--extra-review` with the user's approval; never edit either file for that.

Keys: common `REVIEW_LANGUAGE`, `MAX_REVIEWS`, `REVIEW_BODY_DIR`,
`REVIEW_BODY_NOT_IGNORED`, `REVIEW_BODY_PATH_ENFORCED`; Codex `CODEX_MODEL`,
`CODEX_EFFORT`, `CODEX_SANDBOX`, `CODEX_NETWORK_ACCESS`,
`CODEX_TIMEOUT_SECONDS`, `CODEX_HEARTBEAT_TIMEOUT_SECONDS`; Claude
`CLAUDE_MODEL`, `CLAUDE_EFFORT`, `CLAUDE_PERMISSION_MODE`.

## Options

Common to both scripts:

```
<script> <pr-number> [options] [-- <extra instructions>]
```

| Key | Meaning |
|-----|---------|
| `REVIEW_LANGUAGE` | Language of the review comment, as an English name (`Japanese`, `English`, ...) |
| `MAX_REVIEWS`     | Maximum cross-reviews per PR (Codex + Claude combined) |
| `REVIEW_BODY_DIR` | Directory for the comment body file `pr-<number>-review-<agent>.md`; relative paths start at the repository root. The script creates it and passes the exact file path in the prompt, single-quoted in the post command, so the path must not contain `'` or the quotes PowerShell treats alike, U+2018 to U+201B (exit 1 before any GitHub lookup) |
| `REVIEW_BODY_NOT_IGNORED` | `error` / `warn`: what to do when that file is not ignored by git |
| `REVIEW_BODY_PATH_ENFORCED` | `true` / `false`: `post_pr_comment.sh` rejects any other body file (and stdin) |

The body file is removed after a successful post and kept on failure.

The reviewer's own stdout/stderr never reaches the script's output. It goes to
a temp log that is always removed; on failure its last 40 lines go to stderr,
each cut to 300 characters and marked `... [truncated <n> chars]` when cut.

Option of both review scripts:

| Option | Notes |
|--------|-------|
| `--extra-review` | Run one review beyond `MAX_REVIEWS`, only after the user approved it. Rejected (exit 1) while the PR has fewer than `MAX_REVIEWS` cross-reviews. The success output then shows a count above the limit, e.g. `review-count: 4/3` |

## run_codex_review.sh

| Option | Key | Notes |
|--------|-----|-------|
| `--model <model>` | `CODEX_MODEL` | |
| `--effort <effort>` | `CODEX_EFFORT` | Passed as `-c model_reasoning_effort=<effort>` |
| `--sandbox <mode>` | `CODEX_SANDBOX` | `read-only` / `workspace-write` / `danger-full-access` |
| `--network-access <true\|false>` | `CODEX_NETWORK_ACCESS` | `workspace-write` only; posting needs `true` |
| `--timeout-seconds <n>` | `CODEX_TIMEOUT_SECONDS` | Hard limit on the whole run |
| `--heartbeat-timeout-seconds <n>` | `CODEX_HEARTBEAT_TIMEOUT_SECONDS` | Kill when the progress log stops growing |
| `--approve-for-me` | - | Passed through to `codex exec` |

The reviewer log's path is printed to stderr at start, so it can be tailed.

## run_claude_review.sh

| Option | Key | Notes |
|--------|-----|-------|
| `--model <model>` | `CLAUDE_MODEL` | |
| `--effort <effort>` | `CLAUDE_EFFORT` | `low` / `medium` / `high` / `xhigh` / `max` |
| `--permission-mode <mode>` | `CLAUDE_PERMISSION_MODE` | The reviewer runs `gh` via post_pr_comment.sh non-interactively |

## review_status.sh

`review_status.sh <pr-number>` takes no options. It reads the effective
`MAX_REVIEWS` and prints `review-count: <count>/<max>`,
`review-extra: <count>` (cross-reviews beyond `<max>`, which only
`--extra-review` runs can add; `0` otherwise), and
`review-latest: <comment-url>` (`none` without a cross-review), and
`review-latest-commit: <sha>` (the full 40-character commit in the latest
review's `Reviewed commit:` footer; `none` without a cross-review), followed
on the next line by `review-latest-findings: must=<n> optional=<n>`.
It reports `review-latest-findings: none` without a review, or
`review-latest-findings: unknown` for a historical review without counts. Exit codes:
0 success, 1 usage/config error, 2 GitHub lookup failed.

## Exit codes of the review scripts

| Code | Meaning |
|------|---------|
| 0 | Review posted (`review-posted: <url>`, `review-count: <count>/<max>`, then `review-findings: must=<n> optional=<n>` on stdout) |
| 1 | Usage/config error, review limit reached (or `--extra-review` below the limit), no new commits since the last review, or the reviewer exited without posting |
| 2 | GitHub lookup failed (PR head or comment history) |
| 124 | Codex hard timeout |
| 125 | Codex heartbeat timeout (hang suspected) |
| 75 | The reviewer stopped on its usage limit (`reviewer-quota-exhausted: <agent>`, `reviewer-quota-detected-at: <time>`, and `reviewer-quota-reset: <reset-time>` on stdout) |
| other | Exit status of `codex exec` / `claude -p` |

## post_pr_comment.sh

The last non-empty line of the body must be
`review-findings: must=<n> optional=<n>` (non-negative integers). The counts
are recorded in the provenance footer after `Reviewed commit:`. Missing or
malformed counts prevent posting and exit 1 with this stderr message:
`error: review body must end with "review-findings: must=<n> optional=<n>"`.
