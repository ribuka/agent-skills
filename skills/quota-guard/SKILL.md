---
name: quota-guard
description: Gate long-running work at a configured percentage (shipped as 95%) of Claude Code or Codex five-hour quota and resume after reset. Use when another skill requests quota checks or when asked to pause at high quota usage. Uses Claude statusLine telemetry or Codex app-server, with scheduled resumption.
---

# Quota Guard

- Respond in Japanese. Apply this guard within the caller's already-authorized workflow.
- Use Python 3.10+ and only its standard library. Locate this skill's own
  `scripts/quota_guard.py`; do not assume the current directory is the skill folder.

## Initialize automatically

Choose the current runtime's provider explicitly. In Codex, read
[codex.md](references/codex.md), skip Claude configuration entirely, and run
`uv run --no-project "<skill-dir>/scripts/quota_guard.py" check --provider codex`.
No statusLine setup, local freshness check, or session-log scan is needed.
The following initialization steps apply only to Claude Code.

1. Treat this skill folder as already placed or linked. Use its bundled helper
   directly; do not require an installer, extract an embedded payload, or copy
   this skill to another directory.
2. Read [integration.md](references/integration.md) when setting up or integrating.
   On first invocation for a caller Run, execute
   `uv run --no-project "<skill-dir>/scripts/quota_guard.py" configure` in the target Claude
   Code environment. Perform this authorized setup yourself; do not stop to ask
   the user to run it. The helper makes no settings writes or backups when the
   same configuration is already present (`changed: false`).
3. Inspect effective project/local overrides. If they replace this statusLine,
   configure the effective scope explicitly with the same helper and state path;
   do not assume user settings are effective. Preserve existing settings.
4. Run `check`. Verify real `rate_limits.five_hour` telemetry after a normal
   Claude response. Missing or stale telemetry is UNKNOWN; setup alone does not
   prove usage is available. Never generate repeated model requests just to
   refresh telemetry, and never substitute synthetic data for live usage.
   Use an interactive terminal Claude Code session that actually runs statusLine;
   do not assume Desktop Code tabs or `claude -p` produce it. A coordinator in
   such an environment needs fresh evidence from a terminal session on the same
   account. If settings are not picked up, checkpoint and restart the affected
   Claude session. After an ORCA session launch, verify the effective command
   still invokes this helper; if ORCA replaced it, configure that scope again
   and confirm real telemetry before dispatching work.
5. Share the same state directory among sessions using the same Claude account.
   Use separate `--state-dir` paths for different accounts; no credentials are read.
6. Execute setup only where Claude Code actually runs. If this runtime cannot
   access that machine, report that limitation; do not configure an unrelated
   remote environment or claim the user's machine was configured.

## Gate at safe boundaries

- Run `uv run --no-project "<skill-dir>/scripts/quota_guard.py" check --provider <claude|codex>` before a task dispatch,
  a new expensive phase, merge preparation, or merge; also check after worker completion.
- Read only this short result. Never send per-minute samples to the conversation.
- Honor the caller's safety, review, and merge requirements.

| `state` | Action |
| --- | --- |
| `READY` | Continue the caller's next authorized action. |
| `PAUSED_QUOTA` | Stop starting work; save state and schedule resumption. |
| `UNKNOWN` | Stop starting work; diagnose telemetry and use a bounded retry. |

- Gate on the exit code: `check` exits `0` only on READY, so chain
  `check ... && <command>`. On a non-zero exit, read the JSON `state` to tell
  PAUSED_QUOTA from UNKNOWN; a non-zero exit without a parseable `state` is
  UNKNOWN. The process exits 10 / 20 for PAUSED_QUOTA / UNKNOWN, but shells
  such as PowerShell `-Command` (used by Codex) report any failing native
  command as `1`, so never rely on the specific non-zero code.

- Threshold: `THRESHOLD` in this skill's `config.conf` (shipped as 95);
  `--threshold` overrides it. The script has no built-in threshold: when
  `config.conf` is missing or its `THRESHOLD` is missing or not a number in
  (0, 100], `check` returns UNKNOWN with a `config.conf` reason. The result's
  `threshold` is the value applied; callers that need it read it there.
  Claude local evidence age limit: 180 seconds.
  Codex also blocks an exhausted secondary window (100%). A server limit signal
  without an identifiable blocking window is UNKNOWN; never continue on it.
- Treat the threshold as a boundary check, not a guaranteed hard cap. Existing workers can
  continue consuming quota. Ask them through the caller's existing authorized
  worker protocol to checkpoint at safe boundaries; verify their actual states.
  Do not kill processes or claim all work has stopped.

## Pause and resume

1. Save a durable caller checkpoint as `<operation-id>.md` under the result's
   `checkpoint_dir` (outside any worktree): the operation/run ID and the caller-defined state
   needed to resume (for example phases, work locations, and pending
   operations). Retain permissions and record the helper/state paths and
   current session. Do not store secrets.
2. Read the result's `wake_at`, `wake_local`, and `cron`. Threshold pauses use
   reset + 2 minutes, rounded up; unknown telemetry uses one 15-minute retry.
3. If `CronCreate` and `CronList` are available, check for this operation's
   existing wake-up. Create at most one one-shot (`recurring: false`) prompt,
   using the runtime's actual schema. Match the scheduler's local timezone.
   Include a stable marker `quota-guard:<operation-id>`, the checkpoint path,
   and an explicit instruction to run `check`, reconcile live state, and resume
   only on READY. Never cancel another operation's scheduled tasks.
   In Codex, use the Orca automation procedure in [codex.md](references/codex.md)
   instead: deduplicate by operation name, use `wake` as the nonzero precheck,
   and remove the recurring automation first on wake-up. Without
   `ORCA_TERMINAL_HANDLE`, save the checkpoint and report manual resumption;
   do not create an automation.
   `wake` is the precheck command:
   `uv run --no-project "<skill-dir>/scripts/quota_guard.py" wake --orca <absolute-orca-executable> --terminal <handle> --text <text>`.
   All three arguments are required. It sends `<text>` with Enter to the Orca
   terminal `<handle>` with that executable's `terminal send`, prints
   `{"sent": <bool>}`, and always exits `1`, whether delivery succeeded,
   failed, or timed out, so the automation never starts its own agent
   (exit `2` means invalid arguments). It reads no quota, inbox, or worker
   state.
4. End this turn. Do not wait using `/loop`, repeated model calls, or long sleeps.
5. On wake-up, run `check` again. Resume only on READY after reconciling the
   saved state with the actual repositories/workers. Otherwise schedule one retry;
   do not restart completed phases or duplicate dispatches.
   If the first check immediately after setup or wake-up is UNKNOWN, allow one
   local retry after the result's `local_retry_seconds` for an in-flight
   statusLine callback to finish.
   Do not make another model request; if still UNKNOWN, use the scheduled retry.
6. If the tools/session cannot schedule or remain available, keep the checkpoint
   and report that manual or external resumption is required. Never promise recovery
   after the session exits. Timers do not independently fetch fresh quota data.
7. When the operation completes and no resumption remains, delete its
   checkpoint with
   `uv run --no-project "<skill-dir>/scripts/quota_guard.py" clear-checkpoint --provider <claude|codex> --operation <operation-id>`.
   It deletes only `<operation-id>.md` under that provider's `checkpoint_dir`
   and prints `{"removed": <bool>, "path": ...}`. Exit `0`: deleted or
   already absent; `1`: deletion failed (`path` remains, `reason` says why);
   `2`: invalid operation ID, nothing deleted. On a failure, report the
   remaining path instead of deleting it another way.

## Limits

- For Claude, collect the statusLine's supplied telemetry; do not call undocumented APIs.
  For Codex, use the documented experimental app-server `account/rateLimits/read`.
  A 60-second helper timer is not a guaranteed 60-second upstream fetch.
- For Claude, reject missing, malformed, expired, or stale low-usage evidence. Repeated
  identical timer input does not refresh the evidence timestamp. Conservatively
  retain the maximum usage seen per reset window (reset timestamps within
  120 seconds are treated as the same window); a fresh distinctly later window
  supersedes it. Upstream freshness cannot be proved from this schema.
- The helper records and reports quota; caller boundary checks enforce pausing.
  It neither schedules Cron tasks itself nor intercepts every worker/API request.
- Keep the original caller workflow's invocation restrictions. A wake-up continues
  an already-authorized saved operation; it must not bypass a refused Skill call
  or trigger a new restricted skill. Use the available runtime's documented tools.
