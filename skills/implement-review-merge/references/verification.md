# Verification

How to decide what to verify, how to verify it, and what to report as
`unmet/unverified acceptance criteria:`.

## Which criteria apply

- Criteria are only what the Issue's tasks and acceptance criteria state.
- An environment mentioned only in the Issue's background, current state,
  or measurement notes (e.g. "measured in the app window (WebView2)") is
  context, not a criterion.
- Never add verification in an environment or with data the Issue does not
  require (production, an executable, real hardware, real data, and so on).
- Still report a behavior the Issue's goal clearly requires even when the
  Issue does not state it. A missing behavior is not an added criterion;
  an added environment or data set is.
- A Coordinator's brief does not lower the Issue's requirements: verify at
  the scale and under the conditions the Issue requires.

## How to verify

- Follow the verification method the repository's docs (`AGENTS.md`,
  `CLAUDE.md`, and the docs they reference) set for that kind of change.
- Without such a rule, use the repository's tests and a check you actually
  ran locally.
- State what you verified with in the PR body's test section.

## Bug fixes: reproduction conditions

When the Issue fixes a bug and states its reproduction conditions (data
shape and scale, steps, environment):

- Confirm the fix under those conditions.
- If the data can be synthesized from the Issue's description, create it
  and verify with it. Keep it outside git (e.g. under `tmp/`) and delete it
  when done.
- While developing, run on small data (**Token budget**, Benchmarks), then
  confirm once under the reproduction conditions at the end.
- Report only the conditions you cannot prepare locally (e.g. real
  hardware) in `unmet/unverified acceptance criteria:`, with the reason.
