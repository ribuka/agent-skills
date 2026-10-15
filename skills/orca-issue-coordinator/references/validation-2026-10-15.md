# Codex Coordinator observations: 2026-10-15

These are two smoke fixtures for [Issue #63](https://github.com/ribuka/agent-skills/issues/63),
not proof of the complete steps 0–17 lifecycle. All times below are UTC on
2026-10-15. Latency means worker send to the Coordinator's first tool call in
the new turn; it is not exact model start latency or a delivery guarantee.

## Environment and provenance

- Frozen source checkout: `3b870b9`; Orca `1.4.222`, codex-cli `0.162.1`,
  Claude Code `2.1.300`; Windows, local timezone `Asia/Tokyo`.
- Resolved CLI: `C:/Users/rtagu/AppData/Local/Programs/orca/resources/bin/orca.exe`.
  Installed skill-checkout precheck succeeded before dispatch; the instruction
  was to leave that checkout unchanged during the Run.
- Run: `run_3e6426b79cb0`; Coordinator: Codex,
  `term_3cfdb8f8-bc11-4819-a0d0-c246defb53fc`; worker defaults:
  `gpt-6.1-sol`, medium effort, concurrency 1.
- Measurement ledger: `tmp/run_3e6426b79cb0/coordinator.md` and
  `heartbeat-worker.md` in the source checkout. These local, ignored ledgers
  are provenance, not published raw transcripts. Supplemental token and cleanup
  receipts were supplied by the Coordinator.
- The notification fixture ledger records ready, `input_accepted`,
  `turn_started`, and `launch.effective` Codex / `gpt-6.1-sol` / medium.
  The heartbeat fixture ledger records ready, `turn_started`, and the same
  effective launch settings; it does not record `input_accepted`.
  Neither worker was relaunched.

## Idle notification fixture

Task `task_5ae072c8b1b3`, Dispatch `ctx_b54c81b09f2a`, worker
`term_36721d20-6e97-4101-840d-28e6d717dae6` performed read-only notification work.
The Coordinator ended its turn between stages instead of waiting in a tool.

| Event / message | Prior idle boundary | Worker send | Created / delivered | First new-turn tool | Latency |
| --- | --- | --- | --- | --- | --- |
| Question `msg_21f5fdc54a8a` | 05:33:55.8412479 | 05:35:02.9881993 | 05:35:03 / 05:35:03 | 05:35:08.2723195 | 5.284 s |
| Escalation `msg_05ce1af83b22` | 05:35:20.9053779 | 05:36:17.0435321 | 05:36:17 / 05:36:17 | 05:36:23.0203950 | 5.977 s |
| worker_done `msg_35074c1caf3b` | 05:36:33.1114437 | 05:37:48.5043459 | 05:37:48 / 05:37:49 | 05:37:56.3214851 | 7.817 s |

The Coordinator checked quota first (READY: 28%, 28%, 29% respectively),
read the inbox, replied `proceed` to the question, and sent `continue` to the
original Dispatch after escalation. Deliveries `delivery_78e9b465135b`,
`delivery_59321e7a5c85`, and `delivery_3301bf2a4d61` were acknowledged.
The succeeded completion was accepted and the worker released before the last
acknowledgment. No tracked edits were made by this fixture.

## Natural heartbeat and measured usage

Task `task_9a5d465808d1`, Dispatch `ctx_a14cb5d33425`, worker
`term_31e30e0e-58a1-4925-93dc-ebf04e3937c2` ran an isolated heartbeat window.
The preamble requested a heartbeat every five minutes while active; no extra
heartbeat or status nudges were requested.

- Cadence origin: 05:38:58; first heartbeat due: 05:43:58.
- Coordinator idle boundary: 05:39:01.9634415.
- Single send: 05:44:07.265 (`msg_1fb0610f222d`, phase `waiting`), 9.265 s
  after due time; created 05:44:07, delivered 05:44:08.
- First new-turn tool: 05:44:13.5320962, observed latency 6.267 s.
  Quota was READY, 32%; no actionable rows were present.
  `delivery_b686d9abcaaf` was acknowledged and the Coordinator ended its turn.
- The worker reached its end time at its 05:46:04 clock read. One heartbeat
  was sent; the next was not due before completion. This single sample does
  not establish a frequency guarantee.

Local `event_msg token_count` records isolate the heartbeat-only turn
`01a13e16-dcb3-7880-b995-4c795161e6a8` in Coordinator session
`01a13e05-4e5d-7720-be96-225be7ce4dc7`, from `task_started`
05:44:08.135 to `task_complete` 05:44:25.838. Exactly three requests were recorded:

| Request | Input tokens | Cached input tokens | Output tokens |
| --- | ---: | ---: | ---: |
| 1 | 86,786 | 86,528 | 84 |
| 2 | 87,493 | 86,656 | 233 |
| 3 | 88,002 | 87,296 | 8 |
| Total | 262,281 | 260,480 | 325 |

Uncached input totaled 1,801 tokens. These totals count repeated context across
requests; they are not unique context size, monetary cost, or account quota
percentage. No other work is included. In particular, the recovery turn
05:45:34.856–05:45:59.359 is excluded. The raw transcript is not for publication.
Native heartbeat notifications can therefore cause model work without an
actionable message. Track an Orca-side native heartbeat notification filter;
no implemented filter is established here.

## Scheduled recovery and cleanup

The pre-existing recovery automation `8897f5b8-ec6c-433e-a23d-002da7a7577d`
was named `coordinator-wait:run_3e6426b79cb0`, scheduled every 15 minutes in
`Asia/Tokyo`. Its actual scheduled run, not a manual trigger, was inspected:

| Receipt field | Observed value |
| --- | --- |
| Run ID | `0b7f690c-ad7a-44a4-92b9-16ed5b1bdb35` |
| Trigger / scheduledFor | `scheduled` / 05:45:00 |
| Precheck start / end | 05:45:32.494 / 05:45:34.921 (2,427 ms) |
| Exit / sent / status | `1` / `true` / `skipped_precheck` |
| chatSessionId / terminalSessionId / terminalPaneKey / terminalPtyId | all `null` |
| Existing Coordinator first tool | 05:45:42.1583497 |

The precheck woke the existing Coordinator without starting a separate
automation agent. Reconciliation found an empty inbox, the completed/released
notification fixture, and the active heartbeat fixture; no new Dispatch or
merge occurred. Native heartbeat and recovery were separate turns and did
**not** overlap.

The second completion, `msg_43ff56cb5e9e`, was created at 05:46:18 and
delivered at 05:46:19; the Coordinator's first tool was at 05:46:24.8476987.
Both fixture workers were successfully released and the reclaimable list was
empty. The recovery automation was removed at approximately 05:46:34 and the
automation list was empty at that point, closing the fixture window rather
than establishing cleanup for the entire ongoing Run. The tracked tree was
clean before documentation work.

## Open validation

The first two smoke fixtures do not establish:

- Simultaneous notifications or recovery arriving during an active turn, with
  overlap reconciliation and duplicate-action prevention.
- Pending CI preserving the original head and absolute deadline across wakes
  and context restarts.
- Controlled quota pause scheduling, deduplication, and READY reconciliation.
- A real Claude Coordinator's quota behavior and background waiter.
- The full dependent implementation / merge-preparation / merge lifecycle.
  [Issue #65](https://github.com/ribuka/agent-skills/issues/65) is a real
  phase-validation target; [Issue #66](https://github.com/ribuka/agent-skills/issues/66)
  must start only after its PR merges. Creating this reference is not evidence
  that either lifecycle has completed.

Later validation must supply its own receipts; do not infer success from these
observations or describe steps 0–17 as fully validated.

## Subsequent validation (after the two-fixture window)

The following observations were supplied by the source Coordinator for
[Issue #66](https://github.com/ribuka/agent-skills/issues/66), separately from
the two smoke fixtures above. Reproduction and unexecuted trials are in the
[reproducibility guide](validation-reproduction.md). Additional local ledgers
are `quota-lifecycle-receipts.json`, `quota_fixture.py`, `quota_lifecycle.py`
and `claude-diagnostic.md` beside the original Coordinator ledger; they are
ignored local provenance, not durable public artifacts. Times remain UTC.

### Controlled Codex quota and manual automation CRUD

The actual quota CLI ran with only `read_codex_limits` patched and isolated
state under repository `tmp/`. A Codex primary 300-minute bucket with future
reset and usage 96% returned PAUSED_QUOTA/exit 10; missing limits returned
UNKNOWN/20; usage 4% returned READY/0. The live account was not exhausted.

Manual real Orca operations used disabled fixture schedules: removed waiting
`56b85eaf-9471-416d-81fb-8262b49672be`, created quota
`6bb3088d-9e61-48ed-be30-572d0f075d7d`, listed twice and found exactly one
identical quota entry, removed it before READY and live task/worker
reconciliation, created one waiting replacement
`c2dd5dbf-175b-446c-a1e9-36c433cffd84`, then removed it and verified no fixture
entries remained. No scheduled quota delivery or active-worker stop was
exercised; this is not proof of autonomous behavior under every race.

### Real Claude diagnostic and nesting boundary

Interactive Claude setup ran once with `changed:false`, using the interpreter
already in its effective user-scope statusLine and no project/local overrides.
At 05:55:57, actual `check --provider claude` returned READY,
`recent_local_evidence`, usage 55%, `resets_at:1792052400`. Snapshot files were
written 1–10 seconds before the check; the result has no age field and upstream
freshness is not guaranteed. No synthetic telemetry was substituted.

Resolved Claude settings were implementation opus/medium, merge sonnet/medium,
maximum workers 3. Child Run `run_6f91c0f97f0a` was created, but `worker-start`
refused `nested_worker_depth_exceeded` (depth 2, maximum 1,
`effectsApplied:false`); no tasks, workers or reclaimable terminals remained
in that child Run. Diagnostic Task `task_00522ad78b07`, Dispatch
`ctx_9a4eae6f8ae8` completed and was released. Actual Claude child launch and
background waiter remain untested and require depth-0 validation.

### Real CI empty/pending boundaries and active-turn overlap

A scoped rerun of validation run `38688996409` around 05:52 returned
`no checks reported`/exit 1 for PR #67 head `491a7fd...`; merge was blocked.
A later review fix changed head to
`3ee05c5ee48358aac6333e841db865c20ba7c6b2` and received clean review 2/3
([latest comment](https://github.com/ribuka/agent-skills/pull/67#issuecomment-6185480843)).

Validation run `38689171603`, attempt 2, had all three checks pending/exit 8
at 05:57:53.2899856 on that head. The Coordinator saved absolute deadline
06:27:53.2899856 and ended its turn without a foreground watcher. Scheduled
recovery first tool at 06:00:50.2518192 used the same head and original
deadline; all three checks passed. This establishes preservation across that
wake, not a context restart or deadline-expiry trial. No API-error or
failed-check test was run in this observation window.

Recovery run `379b0dd4-2771-4324-a509-92b3e89eef80`, scheduled for 06:00,
had precheck 06:00:32.574–06:00:35.057, exit 1, `sent:true`,
`skipped_precheck`, and resumed the existing Coordinator. During its active
reconciliation turn, native completion `msg_a6dce8f5b9bb` (created 06:00:59,
delivered 06:01:00) arrived and was consumed at 06:01:07.6333837.
Latest checkpoint/live state were used without repeated dispatch or merge.
This is active-turn overlap, not exactly simultaneous clock-time arrivals or
proof of all race permutations.

### First implementation / fresh preparation / merge path

Fresh Codex merge-preparation Task `task_08f0bcd378a3`, Dispatch
`ctx_d57407a0d0ed`, terminal `term_bb20263d-f247-48e2-9493-ccb166493194`
started after implementation Dispatch `ctx_e9294f5888c1` was released.
Ready, `input_accepted`, `turn_started` and effective Codex / gpt-6.1-sol /
medium were confirmed. Preparation fetched main: same reviewed head,
behind 0/ahead 2, resolution none, no edits, 187 local tests passed outside
the sandbox, six skill frontmatters validated, all three CI checks passed,
review 2/3 without findings or a repeated review. The completion above was
released before acknowledgment `delivery_27e34bf69961`.

The Coordinator independently checked review count/latest comment, main
ancestry, exact head, all three CI checks, CLEAN merge state, `model:gpt` and
READY quota, then squashed with `--match-head-commit`.
[PR #67](https://github.com/ribuka/agent-skills/pull/67) merged at 06:01:39 as
`21f18ba1d2dbdb3cf4d4070090ebfb43de9f3ead`. Issue #66 launch was held after
its DAG became ready until that merge was confirmed. This establishes the
first Codex path through merge. Issue #66 completion and final whole-Run
cleanup remain future at this checkpoint; the original two-fixture scope
above is unchanged. Root Issue #63 tracks final results and remaining gaps.
