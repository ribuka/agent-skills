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
branch/PR state, review counts, pending CI heads/deadlines, and automation ID.
Refresh it before ending each turn. This is the active Run checkpoint; quota
pauses also require the durable checkpoint described in `quota-pause.md`.

Load `orca-cli`, resolve its executable and absolute path, and confirm its
installed automation guide. Use one automation named `coordinator-wait:<run-id>`
as a recovery mechanism. Check `orca automations list --json` first; reuse only
an entry with the same Run, terminal, checkpoint and schedule. Remove an obsolete
matching entry before replacing it. Never touch another Run's automation.

Create it with the following shape (POSIX quoting shown; use literal quoting
for the invoking shell, including doubled embedded single quotes in PowerShell):

```sh
orca automations create --name 'coordinator-wait:<run-id>' \
  --trigger '*/15 * * * *' --timezone '<local-IANA-timezone>' \
  --provider codex --prompt 'Unused: precheck always exits nonzero' \
  --precheck 'uv run --no-project "<absolute-quota-guard-dir>/scripts/quota_guard.py" wake --orca "<absolute-orca-executable>" --terminal "<coordinator-handle>" --text "Resume the existing Run <run-id> from <absolute-checkpoint-path>. Follow the installed orca-issue-coordinator Codex waiting reference. Check quota first, reconcile once, then end the turn if still waiting."' \
  --precheck-timeout 120 --workspace 'path:<absolute-repo-path>' \
  --missed-run-grace-minutes 15 --enabled
```

`quota-guard` documents `wake`: it sends input to the saved terminal and always
exits nonzero, so no separate automation agent starts. Record the returned ID
and verify name, terminal, schedule and precheck using `automations list`.
Do not turn the precheck exit into success. The fallback deliberately permits
one Coordinator turn every 15 minutes even when idle; it does not poll a model
between wakes. Orca and the terminal must remain available. If setup fails,
stop dispatching and report manual resumption instead of relying on notifications.

## On an orchestration notification or recovery wake-up

If a wake arrives during an active turn, finish the current operation first.
Treat queued wake prompts as reconciliation requests against the latest saved
checkpoint and live Run, never as permission to repeat a dispatch or merge.

1. If quota-paused, follow `quota-pause.md` first. Otherwise run `<quota-check>`;
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
4. Process ready work within quota and concurrency limits. If still waiting,
   update the checkpoint and end the turn. Do not call `check --wait`, launch
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
then end the turn with the recovery automation enabled. At subsequent wakes,
inspect that PR once; never reset its deadline on a heartbeat or a context
restart. Do not build a tight CI polling loop. If the deadline expires, report
`monitor-error: CI deadline exceeded` and block the PR. Other errors, failed or
cancelled checks also block it; an empty check set is not success. Read only
relevant failed logs. Verify all checks and the current head again immediately
before merging; a new head needs fresh review/test/sync verification.

On Run completion, remove the recorded waiting automation with
`orca automations remove <id>` and verify it is absent before deleting the Run's
temporary directory. Resolve removal failures; do not abandon a recurring wake-up.
After quota resumption, reconcile saved/live state and recreate exactly one
waiting automation only if this Run still needs to wait.
