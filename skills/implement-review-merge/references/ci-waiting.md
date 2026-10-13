# Wait for CI

Use GitHub CLI's built-in watcher:

```bash
gh pr checks <pr> --watch --interval 30
```

Add `--required` only when the task requires checking required checks alone.
Add `--fail-fast` when a failed check should end the wait immediately.
Never pipe to an external `jq` or build a custom CI polling loop. If JSON
inspection is needed, use `gh ... --json ... --jq ...`; `--jq` is built into
`gh` and does not require the standalone executable.

## Own the watcher until it exits

1. Before starting, set an overall deadline (default: 30 minutes) with the
   execution tool's hard timeout. If the tool cannot enforce a hard timeout,
   record the deadline and terminate its process/session when it expires.
   Do not start a detached process whose result or termination cannot be
   collected. A short tool yield that returns a session ID only backgrounds
   the command; it does not enforce the overall deadline.
2. Use background execution when available. Keep the returned session/task
   ID and collect output and exit status from that same process at least
   once per minute until it exits. Do not start duplicate watchers. Report
   completion or failure as soon as it is collected, within a minute of
   the process ending; never leave the watcher unattended while doing
   unrelated work or ending the conversation.
3. On timeout, terminate the watcher and report
   `monitor-error: CI watch timed out after <duration>`. On a GitHub/API,
   authentication, missing executable, or other monitoring error, stop and
   report `monitor-error: <reason>` with the exit status and short stderr.
   Do not silently restart or interpret these failures as pending CI.
   In worker mode, report the blocker to the Coordinator.

## Interpret the result and verify the current head

- Exit `0`: the selected checks completed successfully. Inspect the check
  summary; skipped checks are not evidence that an expected test ran.
- A failed/cancelled check blocks merging. Read only the relevant failed
  output with `gh run view <run-id> --log-failed`.
- Exit `8` from a one-shot `gh pr checks <pr>` means checks are pending,
  not that monitoring failed. Start the bounded watcher above. If a watcher
  returns `8`, CI is still unverified; report it instead of merging.
- Other non-zero exits require inspecting the short output to distinguish
  failed checks from a monitoring error. No checks reported is not proof
  of success; verify expected workflows have started on the pushed head.
- Before merging, confirm the PR head is still the commit you tested and
  reviewed, and run a final `gh pr checks <pr>` (with the same check scope).
  If checks are pending, wait again with a new explicit deadline. If the
  head changed, repeat verification for that head. Never merge on an empty
  check set, an error, a timeout, or an unverified result.

GitHub CLI documents watch options and pending exit code `8` in the
[official command reference](https://cli.github.com/manual/gh_pr_checks).
