# pr-cross-review options

Defaults come from `config.conf` in the skill directory. It is the only place
defaults are defined; a missing key stops the script. Command-line options
override it for a single run.

Common to both scripts:

```
<script> <pr-number> [options] [-- <extra instructions>]
```

| config.conf key   | Meaning |
|-------------------|---------|
| `REVIEW_LANGUAGE` | Language of the review comment, as an English name (`Japanese`, `English`, ...) |
| `MAX_REVIEWS`     | Maximum cross-reviews per PR (Codex + Claude combined) |
| `REVIEW_BODY_DIR` | Directory for the comment body file `pr-<number>-review-<agent>.md`; relative paths start at the repository root. The script creates it and passes the exact file path in the prompt |
| `REVIEW_BODY_NOT_IGNORED` | `error` / `warn`: what to do when that file is not ignored by git |
| `REVIEW_BODY_PATH_ENFORCED` | `true` / `false`: `post_pr_comment.sh` rejects any other body file (and stdin) |

The body file is removed after a successful post and kept on failure.

## run_codex_review.sh

| Option | config.conf key | Notes |
|--------|----------------|-------|
| `--model <model>` | `CODEX_MODEL` | |
| `--effort <effort>` | `CODEX_EFFORT` | Passed as `-c model_reasoning_effort=<effort>` |
| `--sandbox <mode>` | `CODEX_SANDBOX` | `read-only` / `workspace-write` / `danger-full-access` |
| `--network-access <true\|false>` | `CODEX_NETWORK_ACCESS` | `workspace-write` only; posting needs `true` |
| `--timeout-seconds <n>` | `CODEX_TIMEOUT_SECONDS` | Hard limit on the whole run |
| `--heartbeat-timeout-seconds <n>` | `CODEX_HEARTBEAT_TIMEOUT_SECONDS` | Kill when the progress log stops growing |
| `--approve-for-me` | - | Passed through to `codex exec` |

The progress log is a temp file (path printed to stderr at start, so it can be
tailed). It is always removed; on failure its last 40 lines go to stderr, each
cut to 300 characters and marked `... [truncated <n> chars]` when cut.

## run_claude_review.sh

| Option | config.conf key | Notes |
|--------|----------------|-------|
| `--model <model>` | `CLAUDE_MODEL` | |
| `--effort <effort>` | `CLAUDE_EFFORT` | `low` / `medium` / `high` / `xhigh` / `max` |
| `--permission-mode <mode>` | `CLAUDE_PERMISSION_MODE` | The reviewer runs `gh` via post_pr_comment.sh non-interactively |

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Review posted (`review-posted: <url>` and `review-count: <count>/<max>` on stdout) |
| 1 | Usage/config error, review limit reached, no new commits since the last review, or the reviewer exited without posting |
| 2 | GitHub lookup failed (PR head or comment history) |
| 124 | Codex hard timeout |
| 125 | Codex heartbeat timeout (hang suspected) |
| other | Exit status of `codex exec` / `claude -p` |
