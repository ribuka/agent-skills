---
name: quota-guard
description: Set up and apply a reusable Claude Code 5-hour quota guard for long-running tasks, orchestration, implementation, or reviews. Use when another skill requests quota checks or when asked to pause at 95% usage and resume after reset. Includes a local Python statusLine helper; does not support Codex quota telemetry.
---

# Quota Guard

- Respond in Japanese. Apply this guard within the caller's already-authorized workflow.
- Use Python 3.10+ and only its standard library. Locate this skill's own
  `scripts/quota_guard.py`; do not assume the current directory is the skill folder.

## Initialize automatically

1. Treat this skill folder as already placed or linked. Use its bundled helper
   directly; do not require an installer, extract an embedded payload, or copy
   this skill to another directory.
2. Read [integration.md](references/integration.md) when setting up or integrating.
   On first invocation for a caller Run, execute
   `python "<skill-dir>/scripts/quota_guard.py" configure` in the target Claude
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

- Run `python "<skill-dir>/scripts/quota_guard.py" check` before a task dispatch,
  a new expensive phase, merge preparation, or merge; also check after worker completion.
- Read only this short result. Never send per-minute samples to the conversation.
- Honor the caller's safety, review, and merge requirements.

| State / exit code | Action |
| --- | --- |
| `READY` / 0 | Continue the caller's next authorized action. |
| `PAUSED_QUOTA` / 10 | Stop starting work; save state and schedule resumption. |
| `UNKNOWN` / 20 | Stop starting work; diagnose telemetry and use a bounded retry. |

- Default threshold: 95%; local evidence age limit: 180 seconds.
- Treat 95% as a boundary check, not a guaranteed hard cap. Existing workers can
  continue consuming quota. Ask them through the caller's existing authorized
  worker protocol to checkpoint at safe boundaries; verify their actual states.
  Do not kill processes or claim all work has stopped.

## Pause and resume

1. Save a durable caller checkpoint under the result's `checkpoint_dir`
   (outside any worktree): the operation/run ID and the caller-defined state
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
4. End this turn. Do not wait using `/loop`, repeated model calls, or long sleeps.
5. On wake-up, run `check` again. Resume only on READY after reconciling the
   saved state with the actual repositories/workers. Otherwise schedule one retry;
   do not restart completed phases or duplicate dispatches.
   If the first check immediately after setup or wake-up is UNKNOWN, allow one
   local retry after 2 seconds for an in-flight statusLine callback to finish.
   Do not make another model request; if still UNKNOWN, use the scheduled retry.
6. If the tools/session cannot schedule or remain available, keep the checkpoint
   and report that manual or external resumption is required. Never promise recovery
   after the session exits. Timers do not independently fetch fresh quota data.

## Limits

- Collect the statusLine's supplied telemetry; do not call undocumented APIs.
  A 60-second helper timer is not a guaranteed 60-second upstream fetch.
- Reject missing, malformed, expired, or stale low-usage evidence. Repeated
  identical timer input does not refresh the evidence timestamp. Conservatively
  retain the maximum usage seen per reset window (reset timestamps within
  120 seconds are treated as the same window); a fresh distinctly later window
  supersedes it. Upstream freshness cannot be proved from this schema.
- The helper records and reports quota; caller boundary checks enforce pausing.
  It neither schedules Cron tasks itself nor intercepts every worker/API request.
- Keep the original caller workflow's invocation restrictions. A wake-up continues
  an already-authorized saved operation; it must not bypass a refused Skill call
  or trigger a new restricted skill. Use the available runtime's documented tools.
