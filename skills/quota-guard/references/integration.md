# Initial configuration and caller integration

## Windows / Claude Code

Use a persistent Python 3.10+ interpreter (for example the user's installed 3.12).
Use the already-placed skill folder. A link from `.claude/skills/quota-guard` to
this repository's `skills/quota-guard` is sufficient; do not copy the files again. Do not keep the script in a uv
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
run through Git Bash on Windows: `CLAUDE_CODE_GIT_BASH_PATH` takes precedence,
then Git's installation and PATH are searched. The child uses `CREATE_NO_WINDOW`.
No cmd.exe fallback is used; a missing shell or failed command is displayed
explicitly as `[previous statusLine unavailable]`. Reconfiguring is idempotent
and does not wrap the wrapper again. When unchanged, configure returns
`changed: false` without rewriting settings or creating another backup. Invalid
settings are left unchanged.

Use `configure --settings "<file>" --state-dir "<directory>"` for another settings
scope/account. Use the same state directory in all that account's `check` calls.
Project/local settings may override the user statusLine; inspect effective settings.
Each settings path has its own `previous-<sha256>.json` backup in the shared
state directory. Reconfiguring a legacy wrapper copies its referenced backup to
the scoped filename; a backup already overwritten by the old shared-file behavior
cannot be reconstructed automatically. Recover it from the corresponding settings
backup before reconfiguring.

Use interactive terminal Claude Code sessions (including ORCA terminals) as
telemetry producers. Do not assume Desktop Code tabs or non-interactive `claude -p`
run statusLine. A coordinator without its own callback must use fresh evidence
from a terminal session on the same account; without that evidence, keep UNKNOWN.
Settings normally reload automatically. If no callback appears after a normal
response, verify the effective settings and restart the affected session after
checkpointing. ORCA may manage its own statusLine: after launching a session,
check that the effective command still contains the helper. If replaced, configure
the effective scope again and verify real telemetry. Do not infer ORCA lifecycle
compatibility from a successful synthetic shell test.

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
high usage still blocks through the reset tolerance; stale low usage becomes UNKNOWN. These
signals cannot establish the actual upstream response's observation time.
An early subscription reset is recognized only when fresh telemetry reports a
reset timestamp more than 120 seconds later. Timestamps within 120 seconds of
the latest timestamp are grouped as one window, using the latest reset for
resumption. High records are retained for 120 seconds beyond their reset so an
expired slightly earlier timestamp cannot bypass the latch. A low reading in the same reset window remains blocked
by a prior high reading. The guard covers the 5-hour window; it does not enforce
7-day limits, API billing limits, or Codex usage limits.

## Add to orchestrate-issues or another caller

Invoke `quota-guard` once at the start; let it configure the environment
autonomously, then call its `check` helper at the boundaries
without reloading the skill or reading snapshot history. The coordinator must
own the run checkpoint and wake-up; workers can check the same helper without
scheduling competing wake-ups for the same run.

Suggested caller addition (`orchestrate-issues` already contains the full
version in its `## Quota control` section; keep the two consistent):

```markdown
## Quota control

- Right after creating the Run, before any dispatch, load `quota-guard` once;
  perform its setup (`configure`) and the first `check`. Afterwards only run
  `check`.
- Check before every Task dispatch, merge-preparation dispatch, and merge,
  after processing each worker completion, and before starting a background
  waiter. Continue only on READY; PAUSED_QUOTA and UNKNOWN block new work.
- The Coordinator alone owns the Run checkpoint and the resumption wake-up;
  workers never create wake-ups.
- On PAUSED_QUOTA or UNKNOWN: write the checkpoint, ask active workers to
  stop at safe boundaries and verify their states (never kill processes),
  ensure exactly one one-shot wake-up marked `quota-guard:<run-id>`, and end
  the turn.
- While paused, whatever wakes the Coordinator (worker message, waiter exit,
  heartbeat nudge), first run `CronList` for `quota-guard:<run-id>`; if it
  exists, only record delivered worker states, reply briefly, and end the
  turn. Never create a second wake-up for one Run.
- While paused, do not start or restart the waiter, and do not apply the
  normal rule to continue other independent Tasks.
- On a READY wake-up, reconcile the checkpoint with live state, tell stopped
  workers with unfinished phases to continue (or replace an unavailable one
  with one fresh worker), and never duplicate a dispatch.
```

This does not relax `orchestrate-issues`' own `disable-model-invocation: true` or
any approval/review rules. The saved authorized run may be reconciled on wake-up;
a denied skill call must not be reproduced through its text as a workaround.

## Official sources (verified 2026-10-12)

- https://code.claude.com/docs/en/statusline — stdin schema, refreshInterval,
  rate_limits availability after the first API response, missing expired windows.
- https://code.claude.com/docs/en/scheduled-tasks — one-shot Cron tools, local
  timezone, early jitter at :00/:30, running-session limitations.
- https://code.claude.com/docs/en/skills — model invocation restrictions and
  personal/project skill directories.

`check` provides a minute-rounded date-specific cron expression in the machine's
local timezone, skipping :00/:30. Cron tools must still be verified in the user's
ORCA-hosted session. Immediately after setup or wake-up, an UNKNOWN result may
race a pending statusLine callback. Wait 2 seconds and check once more locally
without requesting another model response; if it remains UNKNOWN, follow the
15-minute one-shot retry protocol.
