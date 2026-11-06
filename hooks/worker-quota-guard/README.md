# worker-quota-guard

A PreToolUse hook that makes an Orca worker stop itself when the shared
5-hour quota reaches quota-guard's pause threshold. See the module docstring
of `worker_quota_guard.py` for the full decision order.

## Behavior

| Situation | Result |
| --- | --- |
| Not in Orca (`ORCA_TERMINAL_HANDLE` unset) | allow, no output |
| `quota_guard.py check` is READY or UNKNOWN | allow, no output |
| PAUSED_QUOTA, shell command allowed by `config.conf` | allow, no output |
| PAUSED_QUOTA, terminal is not an open Orca worker Dispatch (Coordinator, Standalone) | allow, no output |
| PAUSED_QUOTA, open Orca worker Dispatch, anything else | deny with a reason |
| `config.conf` missing or invalid | allow, warning on stderr |

- The threshold comes from quota-guard (`check` runs without `--threshold`);
  the allowed commands come from `config.conf`. The script holds neither.
- UNKNOWN is allowed because quota telemetry is often stale right after a wait.
- The Coordinator and Standalone sessions are never blocked: the Coordinator
  still needs every tool to save its checkpoint and schedule the resume, and
  it gates its own work with `quota_guard.py check`. Only the Coordinator
  schedules wake-ups; the hook schedules nothing.
- The hook is stateless: Codex may run it twice for one tool call.
- One `check` takes about 0.2 seconds; Orca is queried only when PAUSED_QUOTA.

## Install

Create one junction per agent once (from this repository's root, in PowerShell):

```powershell
New-Item -ItemType Junction -Path "$HOME\.claude\hooks\worker-quota-guard" -Target "$PWD\hooks\worker-quota-guard"
New-Item -ItemType Directory -Force -Path "$HOME\.codex\hooks"
New-Item -ItemType Junction -Path "$HOME\.codex\hooks\worker-quota-guard" -Target "$PWD\hooks\worker-quota-guard"
```

### Claude Code

Add to `~/.claude/settings.json` `hooks.PreToolUse`, using the installed path:

```json
{
  "matcher": "*",
  "hooks": [
    {
      "type": "command",
      "command": "uv run --isolated --no-project --no-config --quiet --python \">=3.10\" C:/Users/<user>/.claude/hooks/worker-quota-guard/worker_quota_guard.py --provider claude || exit 1",
      "timeout": 60
    }
  ]
}
```

### Codex

Add to `~/.codex/hooks.json` `hooks.PreToolUse`, using the Codex installed path
and `--provider codex`:

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "uv run --isolated --no-project --no-config --quiet --python \">=3.10\" C:/Users/<user>/.codex/hooks/worker-quota-guard/worker_quota_guard.py --provider codex || exit 1",
      "timeout": 60
    }
  ]
}
```

Then trust the hook in the Codex CLI with `/hooks`. Codex does not run an
untrusted hook, nor one whose content changed since it was trusted: trust it
again after every change to the script or the registration.

## Test

```bash
uv run --no-project --with pytest -m pytest hooks/worker-quota-guard/tests --tb=short -q
```
