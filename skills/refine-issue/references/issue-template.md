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

- [ ] Checkable statements, each verifiable by a test or a command.
- [ ] Include the tests to add or update.

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
user (step 4) whether to keep it as one issue or split it into several
issues; when splitting, create each issue the same way and link them.
