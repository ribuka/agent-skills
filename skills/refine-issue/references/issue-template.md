# Issue template

Use these sections in this order. Omit a section only when it truly does not
apply, and never leave a placeholder ("TBD", "TODO", "?") in the output.

```markdown
## Background

Why this is needed: the problem or goal, and who is affected.

## Goal

What is true once this issue is done, in one or two sentences.

## Specification

The required behavior, stated precisely enough that two implementers would
build the same thing:

- Inputs, outputs, and formats (with concrete examples).
- Behavior for normal cases, edge cases, and errors (messages, exit codes,
  status codes).
- Configuration keys, defaults, and allowed values.
- UI / CLI / API shape (names, arguments, flags).

## Out of scope

What this issue deliberately does not do.

## Implementation plan

Ordered, concrete steps. Name the files, modules, functions, and commands to
add or change. Each step is small enough to implement and verify on its own.

## Acceptance criteria

- [ ] Checkable statements, each verifiable by a test or a command the
      implementing agent can run, with the passing result.
- [ ] Include the tests to add or update.

## Post-merge checks

- Checks wanted but not runnable by the implementing agent (real device,
  account, human operation), with who runs them and the passing result.

## Decisions

Points settled during refinement, with the chosen option and the reason:

- <question>: <decision> (<reason>)
```

## Title

A short imperative summary of the change (e.g. "Add a --dry-run flag to
sync"). No prefixes such as "[Feature]" unless the repository's existing
issues use them.

## Granularity

If the work is too large for one pull request, say so in the Implementation
plan and split it into ordered steps that each fit one pull request. Ask the
user (step 5) whether to keep it as one issue or split it into several
issues; when splitting, create each issue the same way and link them.

## Acceptance criteria and checks

Write acceptance criteria from step 4 of the skill. Add nothing extra when
every criterion is checked by the repository's tests or commands.

| Case | Where to write it |
|------|-------------------|
| Automated test or command the agent runs | Acceptance criteria, naming the test or command and the passing result. |
| Simulated check covering only part of the path | Acceptance criteria for the covered part, stating what it does not cover; the rest goes by the rows below. |
| Wanted, but the agent cannot run it | Post-merge checks. Not an acceptance criterion. |
| The user requires it before merging | Acceptance criteria, followed by indented lines for who runs it, environment and steps, timing, passing result, and what happens if it cannot be run. |
| Feasibility unknown and it would decide the merge | A first implementation step (or a separate issue) for a short investigation; the dependent criteria are fixed from its result, and the issue says how. |

Omit the Post-merge checks section when there are none.

Example: a feature that drops files from Explorer onto a WebView2 control.
A synthetic drop event dispatched in the page reaches the drop handler but
skips the OS drag-and-drop into WebView2, so it does not verify the same
path. Write the synthetic-drop test as an acceptance criterion and say what
it does not cover. Then ask the user whether a real drop from Explorer must
pass before merging. If not, put it under Post-merge checks. If so, write it
as an acceptance criterion like:

```markdown
- [ ] Dropping a file from Explorer onto the WebView2 view opens it.
  - Who: the user, on request from the implementing agent.
  - Environment and steps: Windows 11, a build of the PR head; drag
    `sample.csv` from Explorer onto the view.
  - When: after the cross-review has no must findings, before merging.
  - Passing result: the file opens with no error dialog.
  - If it cannot be run: do not merge; the PR waits for the check.
```
