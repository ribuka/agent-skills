# Codex quota and Orca resumption

## Live check

```text
uv run --no-project "<skill-dir>/scripts/quota_guard.py" check --provider codex
```

Install/sign in to Codex CLI on the same machine/account as the operation.
The helper launches `codex app-server` over stdio, waits for `initialize`,
sends `initialized`, then calls `account/rateLimits/read`. It never starts a
thread or a model turn. The round trip has a 20-second timeout, and the helper
terminates the server afterwards. This documented app-server interface is
experimental; an unavailable CLI, authentication error, timeout, malformed
response, missing bucket, or expired window returns UNKNOWN, never READY.
No statusLine configuration or session-log freshness inference is used.

The `rateLimits` bucket must have `limitId: codex` and a valid 300-minute
`primary`. Five-hour usage at or above `--threshold` (default 95) pauses.
An exhausted secondary window (100%, normally weekly) also pauses; 95% weekly
usage alone does not. When both block, wake after the later reset. A non-null
`rateLimitReachedType` without a numerically identified blocking window returns
UNKNOWN, since a safe reset time cannot be inferred from that signal.
Missing optional `secondary` is accepted; malformed present windows fail closed.
Other model-specific buckets and API billing are outside this guard's scope.

The result contract is the same as for Claude (see `SKILL.md`): exit `0` only
on READY, and the JSON `state` distinguishes PAUSED_QUOTA from UNKNOWN, because
Codex runs commands through PowerShell `-Command`, which reports the helper's
10 / 20 as `1`. Blocked results
include `checkpoint_dir`, `wake_at`, `wake_local`, and `cron`. UNKNOWN also
includes `local_retry_seconds`: wait that short interval and check once locally
without another model response, then schedule the one retry if still UNKNOWN.
Quota pauses wake after reset plus the safety margin, rounded to a minute;
UNKNOWN schedules a 15-minute retry. No stale high-usage latch is used for the
live provider. `--max-age` applies only to Claude. Codex checkpoints default to
`~/.codex/quota-guard/checkpoints`; `--state-dir` changes the parent directory.

## Pause without consuming model turns

1. Save the operation's durable checkpoint under the returned `checkpoint_dir`.
   Include the operation ID, authorized work, progress, helper path, provider,
   terminal handle, and all information needed to reconcile live state.
2. If `ORCA_TERMINAL_HANDLE` is absent, do not create an automation. Report the
   checkpoint path and that manual resumption is required, then end the turn.
3. Load `orca-cli` and resolve its executable for this session. Use that
   executable for all `orca` placeholders below. Resolve its absolute path
   now and embed it in the precheck's required `--orca` argument; do not rely
   on the scheduler inheriting this terminal's environment. If CLI/runtime access is
   unavailable, keep the checkpoint and report manual resumption.
4. Run `orca automations list --json` and look for the exact stable name
   `quota-guard:<operation-id>`. Reuse the matching pending automation; never
   create two for one operation. Verify its terminal, checkpoint, and schedule
   match this pause. Remove an obsolete matching automation before replacing
   it; never remove another operation's automation.
5. Prepare resume text containing the automation name, absolute checkpoint
   path, and this instruction: "First remove this automation by its ID, load
   the checkpoint, run check --provider codex again, and resume the saved
   authorized operation only on READY after reconciling live state. Otherwise
   checkpoint and schedule one retry, then end the turn."
6. Create the automation using the returned `cron`, the machine's actual local
   timezone (matching `wake_local`), an absolute helper path, and the saved
   Coordinator terminal handle. Example (POSIX shell quoting shown):

   ```sh
   orca automations create --name 'quota-guard:<operation-id>' \
     --trigger '<cron>' --timezone '<local-IANA-timezone>' \
     --provider codex --prompt 'Unused: precheck must always exit nonzero' \
     --precheck 'uv run --no-project "<absolute-skill-dir>/scripts/quota_guard.py" wake --orca "<absolute-orca-executable>" --terminal "<handle>" --text "<resume-text>"' \
     --precheck-timeout 120 --workspace 'path:<absolute-repo-path>' \
     --missed-run-grace-minutes 60 --enabled
   ```

   Use the invoking shell's literal argument quoting; never interpolate raw
   checkpoint paths or resume text as shell code. In PowerShell, pass the
   precheck as one single-quoted argument and escape embedded single quotes
   by doubling them. `wake` passes terminal/text as separate subprocess
   arguments; it always exits 1, whether delivery succeeds, fails, or times out.
   Thus the run is `skipped_precheck` and no automation agent starts. Do not
   append a command that converts this precheck to success.
7. Record the returned automation ID in the checkpoint. Verify the matching
   name/ID/schedule with `orca automations list --json`. The scheduler belongs
   to Orca's local service: Orca must be running at the scheduled time. This
   example allows a missed run up to 60 minutes late; beyond that window,
   require manual resumption. Do not promise wake-up after Orca/session exit.
8. End the turn. Never wait in a long sleep, polling loop, or repeated model
   calls. Only a single bounded local UNKNOWN retry is allowed.

## On wake-up

First find the recorded ID (or exact operation name via `automations list`) and
run `orca automations remove <id>`. The five-field cron recurs annually, so
remove it even if work is already complete or the next check still blocks.
If removal fails, resolve it before scheduling a replacement. Inspect delivery
with `orca automations runs` when needed; `skipped_precheck` alone does not
prove delivery (inspect `wake`'s `sent` result). A missing/closed terminal needs
manual resumption. Run `check --provider codex` again. Only on READY reconcile
the checkpoint with live repositories/workers and resume; otherwise save state
and create at most one new wake-up using the new result. This does not relax
the caller's approval/review requirements or authorize new restricted work.

## Source

[Official Codex app-server documentation](https://developers.openai.com/codex/app-server)
documents initialization and `account/rateLimits/read`. Orca automation/precheck
and terminal-send behavior was verified in Issue #58 with Orca 1.4.222; use the
installed `orca-cli` guide and `--help` to confirm the current command schema.
