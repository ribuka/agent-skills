# Initial configuration and caller integration

## Windows / Claude Code

Requires `uv` and Python 3.10+.
Use the already-placed skill folder. A link from `.claude/skills/quota-guard` to
this repository's `skills/quota-guard` is sufficient; do not copy the files again.
configure writes a statusLine command that launches the helper through the
absolute path of `uv` (`"<uv>" run --isolated --no-project --no-config --python ">=3.10" ...`),
never the interpreter that ran configure, so the command is the same from every
repository. The session's working directory (its `.venv`, `.python-version`, and
uv configuration) does not affect which Python runs the statusLine.

The invoking agent performs configure once on entry; the user need not run a
separate installer. Equivalent commands in PowerShell:

```powershell
uv run --no-project "$HOME/.claude/skills/quota-guard/scripts/quota_guard.py" configure
uv run --no-project "$HOME/.claude/skills/quota-guard/scripts/quota_guard.py" check
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
- `check --provider claude|codex`: print one JSON decision whose `state` is
  READY, PAUSED_QUOTA, or UNKNOWN; exit 0 only on READY. The process exits
  10 / 20 for PAUSED_QUOTA / UNKNOWN, but PowerShell `-Command` reports any
  failing native command as `1`, so callers read `state` for blocked results.
  The default provider is Claude.
  See [codex.md](codex.md) for live Codex acquisition and Orca wake-ups.
  It includes `checkpoint_dir` (where callers save their checkpoint) and,
  when not READY, `wake_at` / `wake_local` / `cron` for the resumption wake-up.
  An UNKNOWN result also includes `local_retry_seconds`, the wait before one
  local re-check.
- `configure`: perform initial environment configuration, preserve settings,
  wrap the old statusLine, and enable the timer. Return `changed: false` on a no-op.
- `wake --orca <absolute-executable> --terminal <handle> --text <text>`: send an Orca terminal prompt, print
  `{"sent":true|false}`, and always exit 1, including send failure or timeout.
  This is an automation precheck, so its nonzero exit must not be treated as
  an instruction to run the automation's agent. It never schedules anything.
- `clear-checkpoint --provider claude|codex --operation <operation-id>`: delete
  `<operation-id>.md` under that provider's `checkpoint_dir` once the operation
  completes. Operation IDs start with a letter or digit and contain only
  letters, digits, `_`, `.`, and `-`. Exit 0 when deleted or already absent,
  1 when deletion failed, 2 on an invalid ID; `--state-dir` applies as for `check`.
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
by a prior high reading. The Claude provider covers only the 5-hour window;
it does not enforce 7-day limits or API billing limits.

## Caller contract

- Load `quota-guard` and, for Claude only, run `configure` once per caller operation; afterwards
  only call the `check` helper at the caller's boundaries, without reloading
  the skill or reading snapshot history.
- Continue only on READY; PAUSED_QUOTA and UNKNOWN block new work.
- One owner per operation writes the checkpoint (`<operation-id>.md` under
  `checkpoint_dir` from the `check` result), deletes it with `clear-checkpoint`
  when the operation completes, and creates the resumption wake-up: at most one one-shot
  wake-up per operation, marked `quota-guard:<operation-id>`, at the result's
  `cron`. Other participants may run `check` but never schedule competing
  wake-ups for the same operation.
- A wake-up does not relax the caller's own invocation restrictions or any
  approval/review rules. The saved authorized operation may be reconciled on
  wake-up; a refused skill call must not be reproduced through a wake-up's text
  as a workaround.

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
race a pending statusLine callback. Wait the result's `local_retry_seconds` and
check once more locally
without requesting another model response; if it remains UNKNOWN, follow the
15-minute one-shot retry protocol.
