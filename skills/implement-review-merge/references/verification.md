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

## Restating a criterion's check

Issues written by `refine-issue` give each acceptance criterion an
`Intent:` (the criterion) and a `Check:` / `Passing:` (one way to check it).

- When a `Check:` or `Passing:` cannot hold as written (it contradicts the
  Specification or a fact of the current code, a count is wrong, a needed
  tool is missing) but another check verifies the same `Intent:`, choose
  that check yourself and continue. Do not ask.
- Never restate a criterion in a way that drops or weakens its intent,
  relaxes the scale, conditions, or threshold the Issue requires, or
  changes user-visible behavior into a form the Issue does not state. For
  those, ask as before: the Coordinator in worker mode, the user in
  Standalone mode.
- For a criterion without `Intent:` (an issue written by hand or before
  this format), read the intent from the criterion's wording and the Goal.
  Restate it only when the intent has a single reading; otherwise ask.
- Record every restatement in a `Restated acceptance criteria` section of
  the PR body: for each criterion, the original check, the new check, and
  why the intent is preserved.
- In worker mode, also report it in `worker_done` as
  `restated acceptance criteria:` with the same three points per criterion.
  List every restatement applied to the PR so far, not only the current
  phase's: a Merge preparation or resumed worker carries over those in the
  handoff and the PR body's `Restated acceptance criteria` section and adds
  its own. Write `none` only when the PR has none. Keep it separate from
  `unmet/unverified acceptance criteria:`.
- Decisions marked `[auto]` were not chosen by the user. Do not change one
  yourself: ask the Coordinator in worker mode, the user in Standalone mode.

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

## Local test failures

In every mode, when a test fails in a local run (while developing in step
2, the full run before pushing, or the re-verification in step 9) and you
believe the cause is not the diff, do not judge it unrelated until you
have checked it on `main`. When the cause is known to be the diff, fix it
as usual.

1. Run the failed test alone on the branch (only that test, e.g. a pytest
   node ID).
2. Run `git fetch origin main`, then create a temporary worktree outside
   the repository: `git worktree add --detach <dir> origin/main`, where
   `<dir>` is a new temporary directory (e.g. from `mktemp -d`). Prepare
   the dependencies the test needs as the repository's docs say, and run
   the same test alone there. Then remove it with
   `git worktree remove --force <dir>`. Never switch branches in the
   working worktree.
3. Handle the result:

| Branch alone | `main` alone | Handling |
|---|---|---|
| fails | fails | Existing failure. Do not fix; add it as a follow-up candidate. |
| passes | passes | Order-dependent or flaky. Do not fix; add it as a follow-up candidate. |
| fails | passes | Caused by the diff. Fix it (steps 2–4; also steps 6–7 if already reviewed). |
| passes | fails | Existing failure on `main`. Do not fix; add it as a follow-up candidate. |
| cannot run on `main` (e.g. dependency setup fails) | — | Do not judge it unrelated. In worker mode, report it as a blocker with the reason; in Standalone mode, report it to the user and wait for instructions. |

Add each follow-up candidate as one item, with no review comment URL, to
`follow-up candidates:` in `worker_done` (worker mode) or to **起票候補** in
the final report (Standalone mode). Do not create Issues.

```text
local test failure: <test ID> — failed in: <the run that failed, e.g. full suite on branch>; branch alone: <failed|passed>; main alone (<first 7 characters of the main SHA>): <failed|passed>
```
