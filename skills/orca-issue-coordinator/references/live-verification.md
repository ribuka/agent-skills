# Codex Coordinator live verification

This is a bounded observation for [Issue #62](https://github.com/ribuka/agent-skills/issues/62),
not a guarantee of notification delivery or a full step 0–17 certification.
Times below are UTC on 2026-10-14 (2026-10-15 in Asia/Tokyo).

## Environment and scope

- Orca desktop/runtime: 1.4.222, reachable with `orca status --json`.
- Resolved CLI: `C:/Users/rtagu/AppData/Local/Programs/orca/resources/bin/orca.exe`.
  `Get-Command orca` resolved it in this managed terminal; no PATH edit was needed.
  The previous process's missing PATH is not reproduced, and its cause is unknown.
- Codex CLI: 0.162.1. Coordinator agent: Codex.
- Installed skill checkout: `C:/Users/rtagu/repos/agent-skills`, commit `6e86d54`.
  The installed `check_preconditions.py` passed, including runtime, GitHub auth,
  checkout freshness and clean skills. The checkout was not updated during probes.
- Run: `run_8101d957c231`; Coordinator:
  `term_7830c8db-6085-46f2-a489-5a100eaaca65`.
- Workers used the existing issue worktree with no source or GitHub mutations.
  They were smoke tests, not implementation or merge-preparation phase executions.
  No test PR was merged. The report PR is handled separately by the Coordinator.
- Quota checks used the live Codex provider and returned READY. Usage changed from
  49% to 53% while the Coordinator, workers and tests were active; this is not an
  idle-token measurement and cannot be attributed to heartbeats.

## Reproducible procedure

1. Load the version-matched `orca-cli` and `orchestration` guides and their
   automation, launch-preference and messaging references. Run the installed
   precondition check and `resolve_config.py --agent codex`.
2. Create a bounded probe Run. Save an absolute checkpoint under `tmp/<run-id>/`.
   Create one `coordinator-wait:<run-id>` automation using the Codex waiting
   reference and verify its schedule, terminal, workspace and nonzero precheck.
3. Gate each dispatch on `quota_guard.py check --provider codex` exit 0.
   Launch fresh `worker-start --worktree current --agent codex` workers with the
   resolved phase model and effort. Record `launch.effective` and turn-start proof.
4. Have the implementation-model probe send heartbeat, blocking `ask`, escalation
   and `worker_done` using its live preamble. Consume a non-waiting Delivery,
   answer the question, process every returned row, and acknowledge it. Check
   settlement and release the worker; acknowledgment can return another Delivery.
5. Observe an actual scheduled automation run using `automations runs`, including
   precheck output and terminal/session fields. Do not infer delivery from
   `skipped_precheck` alone. Remove only this Run's automation afterwards.
6. Confirm no reclaimable worker remains and no matching automation remains,
   then delete only this Run's temporary directory.

## Worker launch receipts

| Probe | Task / Dispatch | `launch.effective` | Turn start |
| --- | --- | --- | --- |
| Implementation model | `task_befa1a7725a3` / `ctx_f2051d9a09b5` | `codex`, `gpt-6.1-sol`, `medium` | observed |
| Merge-preparation model | `task_4915079e5205` / `ctx_455cb748f241` | `codex`, `gpt-6.1-terra`, `medium` | observed |
| Corrected merge-model retry | `task_4915079e5205` / `ctx_cecb6f8282be` | `codex`, `gpt-6.1-sol`, `medium` | observed |

These receipts establish Orca's effective launch settings, not an independent
attestation of the model serving the requests. The first worker did not know its
exact model name; its self-description was not used as launch evidence.

## Message observations

| Type | Durable creation | Observation |
| --- | --- | --- |
| heartbeat | 22:55:42 | Read in an active Coordinator turn; acknowledged |
| question | 22:55:44 | Answered at 22:56:04, 20 seconds after creation |
| escalation | 22:56:11 | Read in an active Coordinator turn; acknowledged |
| worker_done | 22:56:26 | Accepted success, Task completed; worker released with transcript captured |

The question's 20 seconds is creation-to-answer time, not native notification
latency. All rows were inspected through the inbox during the same active turn.
This does not establish that any type wakes an idle Coordinator. Only one
heartbeat was explicitly requested; no natural cadence or heartbeat-only model
invocation/token cost was measured.

## Automation observations

The first automation used `*/15 * * * *`, Asia/Tokyo, a 120-second precheck
timeout and `quota-guard wake` targeting the saved Coordinator. A manual
`automations run` at 22:55:37 produced run
`6d7b448f-5958-4499-a72c-1e236e04f47b` with `status: dispatched`,
`precheckResult: null`, and a new terminal. Thus manual execution did not validate
the scheduler's precheck path. The automation was disabled and removed, and its
extra terminal was closed with `ptyKilled: true`; no source edit was observed.

The replacement automation `ce6e27f9-243e-4b5c-85fe-a1b482bb5528` used the same
15-minute schedule. Its scheduled run `90dd205a-8b55-45c6-acba-2df693406421`
was due at 23:00:00; precheck started at 23:00:29.980 and completed at
23:00:32.251 (2.271 seconds), returning exit 1 and `{"sent": true}`.
The run was `skipped_precheck`, with all agent terminal/session IDs null.
The existing idle Coordinator received that exact recovery prompt and began a
new turn; reconciliation at 23:00:43 found no new messages, one completed worker
and one still-dispatched probe. No dispatch was repeated. The approximately
32-second schedule-to-send interval is one observation, not a delivery SLA.
The automation was removed and `automations list` returned no entries.

## Unsupported merge model

Despite a ready receipt and observed turn start, the original merge-model probe
failed before producing an assistant result. Its terminal showed HTTP 400:
`gpt-6.1-terra` is unsupported with this ChatGPT account. The fleet projection
still reported live/working, so that projection alone was insufficient to detect
this provider rejection. Bounded terminal output supplied the positive failure
evidence; `worker-stop` closed the exact failed probe with `ptyKilled: true`.

The Codex merge-preparation default, example and default-resolution test now use
`gpt-6.1-sol`/`medium`, matching the successfully executed implementation probe.
This is a direct default replacement, with no automatic model fallback. Explicit
model overrides remain available for accounts supporting other models. The
installed skill checkout stayed unchanged during this Run; the replacement
probe passes the corrected model explicitly.

The retry completed successfully: `worker_done` was created at 23:02:10 and
marked delivered at 23:02:11. A native orchestration notification reached the
Coordinator during its active second turn and was consumed without another
dispatch. The one-second durable delivery interval is not idle wake latency.
The completed replacement worker was released with its transcript captured.

## Coverage limits

The remaining live acceptance cases are tracked in
[Issue #63](https://github.com/ribuka/agent-skills/issues/63) and need a separate
controlled session:

- End the Coordinator turn before each native `worker_done`, `escalation` and
  `question`; record sender timestamps, observed new turns and delivery latency.
- Measure natural heartbeat cadence and heartbeat-only model turns/tokens with
  other activity excluded. Require an Orca notification filter if cost is excessive.
- Prove recovery from a lost native notification while the Coordinator is idle,
  and overlapping wake/notification reconciliation without duplicate dispatch/merge.
- Exercise the actual step 0–17 implementation/merge cycle with an explicitly
  bounded disposable Issue/PR; these launch probes do not cover phase handoffs,
  cross-review, dependencies or merge decisions.
- Exercise pending CI across ended turns with an unchanged saved deadline, plus
  failure, API error and empty-check cases that block merge.
- Exercise quota pause/removal/deduplicated resumption and READY reconciliation
  using a controlled fixture; do not intentionally exhaust real quota.
- Run a Claude Coordinator with its own live quota evidence to verify its worker
  defaults and background waiter. Passing unit tests alone is not live parity proof.

Local baseline: 187 tests passed across quota-guard, pr-cross-review and
orca-issue-coordinator. This verifies local regression coverage, not the live
cases above. See Issue #62 for follow-up tracking and final report PR/CI results.
