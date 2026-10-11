# Initial configuration and caller integration

## Windows / Claude Code

Use a persistent Python 3.10+ interpreter (for example the user's installed 3.12).
Use the already-placed skill folder. A link from `.claude/skills/quota-guard` to
`.agents/skills/quota-guard` is sufficient; do not copy the files again. Do not keep the script in a uv
throwaway environment: configure stores the current interpreter's absolute path.

The invoking agent performs configure once on entry; the user need not run a
separate installer. Equivalent commands in PowerShell:

```powershell
python "$HOME/.claude/skills/quota-guard/scripts/quota_guard.py" configure
python "$HOME/.claude/skills/quota-guard/scripts/quota_guard.py" check
```

Configuration updates only `statusLine` in the user settings file. It keeps a
byte-for-byte timestamped settings backup, preserves other keys and statusLine
options, and adds a timer of at most 60 seconds. Existing statusLine stdout is
retained above a short quota line; stdin is forwarded unchanged. Existing commands
run through Python's OS shell, so test shell-dependent custom commands on Windows
(cmd versus Git Bash); failure is displayed explicitly. Reconfiguring is idempotent
and does not wrap the wrapper again. When unchanged, configure returns
`changed: false` without rewriting settings or creating another backup. Invalid
settings are left unchanged.

Use `configure --settings "<file>" --state-dir "<directory>"` for another settings
scope/account. Use the same state directory in all that account's `check` calls.
Project/local settings may override the user statusLine; inspect effective settings.

## Runtime commands

- `statusline`: accept Claude Code JSON on stdin; print a terminal status line.
- `check`: print one JSON decision; exit 0 / 10 / 20 for READY / PAUSED / UNKNOWN.
- `configure`: perform initial environment configuration, preserve settings,
  wrap the old statusLine, and enable the timer. Return `changed: false` on a no-op.
- `check --threshold 95 --max-age 180 --state-dir "<path>"`: override policy.
  If changing the display policy, also edit the statusLine command's corresponding
  flags; the check command's policy controls the caller's decisions.

Snapshots live in `~/.claude/quota-guard/sessions/*.json`, one hashed filename per
session. Writes use atomic replacement so separate sessions never overwrite each
other's file. Simultaneous callbacks within one session rely on Claude Code's
cancel/debounce behavior; a byte-range lock is not implemented. Store locally,
not on NAS. Only quota and change-detection metadata are recorded, never raw
stdin, credentials, transcripts, or project contents. Old expired records do not
permit resuming. They may be removed later while the sessions are stopped.

Freshness is conservative: a change in quota, reset time, prompt ID, API duration,
or token usage refreshes local evidence. Idle timer-only repeats do not. Stale
high usage still blocks until reset; stale low usage becomes UNKNOWN. These
signals cannot establish the actual upstream response's observation time.
An early subscription reset is recognized only when fresh telemetry reports a
later reset timestamp. A low reading in the same reset window remains blocked
by a prior high reading. The guard covers the 5-hour window; it does not enforce
7-day limits, API billing limits, or Codex usage limits.

## Add to orchestrate-issues or another caller

Invoke `quota-guard` once at the start; let it configure the environment
autonomously, then call its `check` helper at the boundaries
without reloading the skill or reading snapshot history. The coordinator must
own the run checkpoint and wake-up; workers can check the same helper without
scheduling competing wake-ups for the same run.

Suggested caller addition (replace an older inline quota section):

```markdown
## Quota control

- Load `quota-guard` and follow its setup, check, and pause/resume protocol.
- Check before task dispatch, merge preparation, and merging, and after worker
  completion. Continue only on READY; PAUSED_QUOTA and UNKNOWN block new work.
- Keep one run checkpoint and one wake-up owned by the Coordinator. Request
  active workers to checkpoint at safe boundaries and verify their states.
- Apply this guard to all run phases. During a quota pause, do not apply the
  normal rule to continue other independent Tasks.
```

This does not relax `orchestrate-issues`' own `disable-model-invocation: true` or
any approval/review rules. The saved authorized run may be reconciled on wake-up;
a denied skill call must not be reproduced through its text as a workaround.

## Official sources (verified 2026-10-11)

- https://code.claude.com/docs/en/statusline — stdin schema, refreshInterval,
  rate_limits availability after the first API response, missing expired windows.
- https://code.claude.com/docs/en/scheduled-tasks — one-shot Cron tools, local
  timezone, early jitter at :00/:30, running-session limitations.
- https://code.claude.com/docs/en/skills — model invocation restrictions and
  personal/project skill directories.

`check` provides a minute-rounded date-specific cron expression in the machine's
local timezone, skipping :00/:30. Cron tools must still be verified in the user's
ORCA-hosted session. ORCA and real Windows installation cannot be tested from
this remote workspace.
