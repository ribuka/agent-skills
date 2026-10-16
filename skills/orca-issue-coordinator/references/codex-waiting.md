# Codex waiting without a running tool call

Use this only for a Codex Coordinator. Claude Code keeps its background waiter.
Do not run a foreground waiter, repeatedly collect a background tool session,
or sleep through worker/CI waits: each collection can invoke the model again.

## Set up a recovery wake-up

Before the first dispatch, save `tmp/<run-id>/coordinator.md` under the
Coordinator's working repository root (git-ignored, not the installed skill
checkout). Resolve this checkpoint to an absolute path before recording it or
embedding it in any wake prompt. Save: Run ID,
Coordinator terminal handle, agent, resolved settings, task/dispatch/worktree/
branch/PR state, review counts, pending CI heads/deadlines, the waiting mode
(see **Waiting modes**), and automation ID. Refresh it before ending each turn. This is the active Run checkpoint; quota
pauses also require the durable checkpoint described in `quota-pause.md`.

Record every time at which the Coordinator must look again as its own line
`wake-at: <ISO-8601 time with offset> <reason>` (e.g.
`wake-at: 2026-10-16T14:05:00+09:00 ci #84`): the next pending-CI inspection
(see **Pending CI**) and any reviewer quota retry time
(`review-quota-retry.md`). Remove or replace a line once it is handled. The
wake precheck reads only these lines from the checkpoint.

Resolve only the absolute path of the `orca` executable (PowerShell:
`(Get-Command orca).Source`; POSIX: `command -v orca`) and record it in the
checkpoint. Do not load `orca-cli` or its automation guide, and do not read
`orca automations create --help`: the command below is complete.
Use one automation named `coordinator-wait:<run-id>`
as a recovery mechanism. Check `orca automations list --json` first; reuse only
an entry with the same Run, terminal, checkpoint and schedule. Remove an obsolete
matching entry before replacing it. Never touch another Run's automation.

Create it with the following shape (POSIX quoting shown; use literal quoting
for the invoking shell, including doubled embedded single quotes in PowerShell):

```sh
orca automations create --name 'coordinator-wait:<run-id>' \
  --trigger '*/15 * * * *' --timezone '<local-IANA-timezone>' \
  --provider codex --prompt 'Unused: precheck always exits nonzero' \
  --precheck 'uv run --no-project "<absolute-skill-dir>/scripts/wake_if_actionable.py" --orca "<absolute-orca-executable>" --terminal "<coordinator-handle>" --run "<run-id>" --checkpoint "<absolute-checkpoint-path>" --text "Resume the existing Run <run-id> from <absolute-checkpoint-path>. Follow the installed orca-issue-coordinator Codex waiting reference. Check quota first, reconcile once, then end the turn if still waiting."' \
  --precheck-timeout 120 --workspace 'path:<absolute-repo-path>' \
  --missed-run-grace-minutes 15 --enabled
```

`wake_if_actionable.py` (see SKILL.md **Waiting**) sends the wake text to the
Coordinator terminal only when the Run needs it (an unread actionable message,
a worker requiring action, no worker in progress while Tasks remain, a passed
`wake-at:` time, the 60-minute safety interval, or an `orca` failure) and
always exits nonzero, so no separate automation agent starts and an idle fire
makes no model request. Record the returned ID and verify name, terminal,
schedule and precheck using `automations list`. Do not turn the precheck exit
into success. Orca and the terminal must remain
available. If setup fails, stop dispatching and report manual resumption
instead of relying on notifications.

## Waiting modes

Keep exactly one wake-up per Run: at most one `coordinator-wait:<run-id>`
automation, and no other waiting automation (a quota pause replaces it, see
`quota-pause.md`). Before ending each turn, choose the mode from what the Run
still waits for and record it in the checkpoint as `waiting-mode: <mode>`:

- `recurring`: a worker is active, CI is pending (see **Pending CI**), or the
  Run waits for anything else without a known time. Use the 15-minute
  automation above. A known-time wait (below) that is due during this mode is
  handled on the first fire at or after its `wake-at:` time.
- `known-time <local-time> <reason>`: no worker is active, no CI is pending,
  and at least one remaining wait ends at a known time, such as a reviewer
  quota retry time (`review-quota-retry.md`). Use one wake at the earliest
  such time; other Tasks may still wait for the user.
- `user-only`: no worker is active, no CI is pending, nothing waits for a
  known time, and every remaining Task waits for a user answer. Remove the
  automation and record `automation: none`. A user answer arrives through the
  chat and starts a turn by itself; idle wakes would only scroll the pending
  question away (SKILL.md **Asking the user**).

To switch modes, remove the recorded automation with
`orca automations remove <id>` and verify it is absent, then create the new
one (none for `user-only`) and record its ID. If the mode and wake time are
unchanged, keep the existing automation. Create the `known-time` automation
with the command above, changing `--trigger` to a five-field cron for the
wake time in the same timezone (`<minute> <hour> <day> <month> *`),
`--missed-run-grace-minutes` to `60`, and the precheck to
`uv run --no-project "<absolute-quota-guard-dir>/scripts/quota_guard.py" wake --orca "<absolute-orca-executable>" --terminal "<coordinator-handle>" --text "<same wake text>"`.
`quota-guard` documents `wake`: it always sends the text and exits nonzero, so
the one known-time fire always wakes. That cron recurs annually, so remove it
on wake-up (step 1 below).

Returning to `recurring`: a turn that starts while the mode is `known-time` or
`user-only` (the known-time wake, a user answer, a worker message, or a
heartbeat nudge) follows the steps below and chooses the mode again at the
end. Recreate exactly one waiting automation only if the Run still needs to
wait.

## On an orchestration notification or recovery wake-up

If a wake arrives during an active turn, finish the current operation first.
Treat queued wake prompts as reconciliation requests against the latest saved
checkpoint and live Run, never as permission to repeat a dispatch or merge.

1. If quota-paused, follow `quota-pause.md` first. If the checkpoint's mode is
   `known-time` and its time has come, remove that automation now, resolve a
   removal failure before creating another, and record `automation: none`.
   Then run `<quota-check>`;
   proceed only on exit 0. A blocking result switches to the quota pause procedure,
   which removes this waiting automation before scheduling quota resumption.
2. Run exactly one non-waiting
   `orca orchestration check --terminal <handle> --run <run-id> --json`.
   Process every row of the returned Delivery, including full `worker_done`,
   `escalation`, and `question` bodies. Record their handoff fields and respond
   to questions through ORCA. Then acknowledge that Delivery with
   `check --terminal <handle> --run <run-id> --ack <delivery_id> --json`;
   if acknowledgment also returns messages, process and acknowledge those too
   before ending the turn. Never acknowledge unread messages.
3. Heartbeat-only batches need acknowledgment but no dispatch or user update.
   On recovery wakes, also inspect `worker-list` and `task-list` once: recover
   completed/missing/stuck workers even if a notification was lost. Verify live
   state before redispatching. Treat errors as blockers, not empty mail.
4. Process ready work within quota and concurrency limits. If a recorded
   reviewer quota retry time has passed, follow **On wake-up** in
   `review-quota-retry.md` for that PR. If still waiting, choose the waiting
   mode (**Waiting modes**), update the checkpoint and end the turn. If a question to the user is
   pending, end with the reminder line from the SKILL.md **Asking the user**
   rules; never end with only "waiting for an answer". Do not call `check --wait`, launch
   `wait_actionable.py`, or start a foreground `gh pr checks --watch`.

Notifications are best-effort, so neither actionable delivery nor a fixed
heartbeat frequency is assumed. A heartbeat can cause a model turn even if
there is no actionable work. The recovery automation covers lost notifications;
it does not suppress native heartbeat nudges. Before a production Run, verify
worker_done, escalation and question delivery and observe heartbeat frequency
with the installed Orca build. If nudges are too frequent, report the measured
cost and require an Orca notification filter rather than claiming token-free
waiting. No delivery/frequency measurement is established by these instructions.

Verify recovery through an actual scheduled run, inspecting precheck output and
terminal/session fields. Manual `automations run` is not evidence that the
scheduler's precheck ran or suppressed a separate agent; confirm the behavior
against the installed Orca build.

## Pending CI at step 14

Run `gh pr checks <pr>` once. Exit 8 means pending: save the PR head SHA and
an absolute deadline (default 30 minutes from the first pending observation),
and a `wake-at:` line for the next inspection 15 minutes from now (never later
than the deadline), then end the turn with the recovery automation enabled.
At subsequent wakes, inspect that PR once and replace its `wake-at:` line the
same way while it stays pending; never reset its deadline on a heartbeat or a
context restart. Do not build a tight CI polling loop. If the deadline expires, report
`monitor-error: CI deadline exceeded` and block the PR. Other errors, failed or
cancelled checks also block it; an empty check set is not success. Read only
relevant failed logs. Verify all checks and the current head again immediately
before merging; a new head needs fresh review/test/sync verification.

On Run completion, remove the recorded waiting automation with
`orca automations remove <id>` and verify it is absent before deleting the Run's
temporary directory and quota checkpoint (`SKILL.md` step 17). Resolve removal failures; do not abandon a recurring wake-up.
After quota resumption, reconcile saved/live state and choose the waiting mode
again (**Waiting modes**).
