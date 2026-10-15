# Reproducing Coordinator validation

Use the [2026-10-15 evidence report](validation-2026-10-15.md) for executed
observations and their limits. This guide describes procedures; reading it or
passing unit tests does not execute them. Follow the installed skill and
version-matched Orca guides for commands and authority, including quota gates.

## Record and isolate

Use a dedicated Run and bounded fixtures in an authorized worktree. Record the
source SHA, Orca/agent versions, timezone, resolved executable, effective launch
settings, Run/Task/Dispatch IDs and terminal handles. Keep temporary ledgers
under repository `tmp/<run-id>/`; publish methods, timestamps and receipt IDs,
not raw transcripts, credentials or private telemetry. Keep the installed
checkout unchanged. Do not implement a second state machine to simulate the
Coordinator instructions.

## Idle notifications and heartbeat cost

1. Start one read-only worker through real orchestration. Save ready,
   `input_accepted`, `turn_started` and `launch.effective` receipts separately;
   absence of a receipt is a gap, not inferred success.
2. Let the Codex Coordinator end its turn before each isolated question,
   escalation and completion. Record worker send, message creation/delivery,
   prior idle boundary and first new-turn tool time. Report send-to-first-tool
   latency, not exact model-start latency. Process bodies, reply through Orca,
   release settled workers and acknowledge only processed Deliveries.
3. In a separate active window, request only the preamble's natural five-minute
   heartbeat cadence. Record cadence origin, due/send times and sample count;
   do not add nudges. End the Coordinator turn between events.
4. Isolate that heartbeat turn's local token records by session/turn IDs and
   start/end times. Sum input, cached input and output per request; subtract
   cached from input for uncached input. Exclude recovery turns. Do not infer
   monetary cost, unique context size or a frequency guarantee.
5. Verify recovery with an actual scheduled run: inspect trigger, scheduled
   time, precheck exit/sent/status and terminal/session fields. A manual run
   does not prove scheduler behavior or suppression of a separate agent.
   Removal may delete automation run history. Use an independent bounded
   observer to persist the receipt before removal; never delay remove-first
   quota resumption to collect history. Report missing fields explicitly.

## Recovery overlap and simultaneous arrivals

Arrange an authorized scheduled recovery and native worker completion near one
another. Record precheck interval, first tool, native creation/delivery and
consumption time. Reconcile against the latest checkpoint and live Run; verify
completed phases are not dispatched or merged twice. Distinguish arrival during
an active recovery turn from exactly simultaneous arrivals. Reverse ordering
and context-restart trials need their own receipts; one overlap cannot cover
all race permutations.

## Pending CI and fail-closed boundaries

1. On a dedicated PR with real pending workflows, run `gh pr checks <pr>` once.
   Record exit 8, exact head SHA, observation time and absolute deadline.
   Save them in the checkpoint and end the Codex Coordinator turn; use no
   foreground watcher or tight polling loop.
2. On the next scheduled wake, compare saved head/deadline with the original
   values, inspect checks once, and reverify head and all checks before merge.
   A new head requires fresh review/test/sync verification. Separately test a
   context restart and deadline expiry: neither a heartbeat nor a restart may
   extend the deadline; expiry must report `monitor-error` and block merge.
3. Exercise empty checks, failed/cancelled checks and API errors separately on
   authorized disposable targets. Record command, exit, head and block decision;
   nonzero is never converted to success or an empty inbox/check set.
   An empty-check response and an API failure are different cases.
4. For a bounded failed-check control, a dedicated synthetic commit-status
   context may demonstrate the CLI/block decision. Label it synthetic, never
   change real workflow conclusions, and let its owner clear only that context
   after recording the failure. An invalid PR lookup can demonstrate an API
   error, but does not prove handling of an outage for a valid PR. Reverify the
   valid PR after either control. Unexecuted cases remain gaps.

## Controlled quota pause and READY reconciliation

For an implementation-level experiment, inspect the provider's current tests
to construct a disposable acquisition fixture around the actual quota CLI.
Use their complete valid five-hour Codex sample, including provider identity
and a future reset; vary usage to 96%, missing limits, then 4%. Do not copy an
internal function name or partial payload schema from this guide. Only
acquisition is substituted; parsing, exit selection and CLI handling remain
real. No public fixture-input CLI is established here. Run the temporary
harness with `uv run --no-project <fixture.py> <case>`, using the documented
`--state-dir` under `tmp/<run-id>/`. Record JSON and exits: PAUSED_QUOTA/10,
UNKNOWN/20, READY/0. This does not exhaust the live account.

For an authorized manual Orca CRUD fixture, follow
[quota pause/resume](quota-pause.md): remove the fixture waiting entry, create
one disabled quota entry, list twice to compare its identity, remove it before
the READY check and reconcile live `task-list`/`worker-list`. Create exactly
one disabled waiting replacement only if waiting is still needed, then remove
fixture entries and verify absence. Record IDs and order. This measures manual
operations, not autonomous deduplication or scheduled quota delivery.

The report also records one controlled scheduled quota wake with a worker
paused at a safe boundary, with incomplete run-history evidence. Separate
future trials must cover complete scheduled receipts, repeated paused wakes,
UNKNOWN local retry and additional resume races. Never kill a worker or bypass
quota or nesting limits to obtain evidence.

## Actual Claude evidence and lifecycle completion

Use an actual interactive Claude session and the documented quota-guard setup.
Preserve unrelated settings and use its effective interpreter. Verify the
effective statusLine invokes the helper; if project/local overrides replace
it, configure that effective scope as quota-guard instructs.
Collect a real `check --provider claude` result, including evidence source,
usage/reset and observation time. Record snapshot age separately when known;
local recency does not guarantee upstream freshness. Do not replace Claude
telemetry with synthetic JSON or claim an absent age field exists.

From an authorized depth-0 Coordinator, verify effective Claude worker model
and effort, actual child launch, background waiter and actionable/heartbeat
handling. A `nested_worker_depth_exceeded` refusal proves only the boundary;
do not bypass it. For either agent, record implementation review count/latest
comment, fresh merge-preparation handoff, exact reviewed/tested head and CI,
Coordinator merge, then dependent launch only after confirmed merge. Finally
verify worker release, empty reclaimable list and removal of Run wake-ups.

At publication, separate executed observations from remaining work. The report
records one Codex lifecycle through PR #67 merge; Claude child/waiter, exact
simultaneity, autonomous quota deduplication across races and final whole-Run
cleanup still need evidence. Unit tests and this documentation are not substitutes.
