# Candidate request and record

Each candidate produces two texts: the **request** handed to the
refine-issue skill, which turns it into the issue body, and the **record**
comment this skill posts on every issue created from it. The record keeps
what refine-issue does not: the fingerprint, the evidence, and the score.
Keep the headings in English.

## Request

Free text for refine-issue's Create mode. State the problem and the
proposed change; leave the specification, acceptance criteria, and title to
refine-issue.

```markdown
Refactoring candidate found by a periodic scan of <default branch commit SHA>.

## Problem

What is wrong now and why it costs something (what change becomes harder
or riskier because of it).

## Evidence

- `<path>:<start>-<end>`: what is there.
- Tool output excerpt, or the commits that show the change coupling.

## Proposed change

The refactoring in a few sentences. The behavior must stay unchanged; the
existing tests must keep passing.

## Not doing

Alternatives considered and why not (e.g. "keep both copies").
```

## Record

Posted with `gh issue comment <number> --body-file <file>` on each issue
created from the candidate.

```markdown
<!-- detoxer fingerprint: <kind>:<path>[,<path>...]:<symbol-or-topic> -->

## Detoxer record

- Scanned: <default branch commit SHA>
- Benefit: <1-3> - <reason>
- Cost: <1-3> - <reason>
- Risk: <1-3> - <reason; which tests cover it>
- Score: <benefit * 2 - cost - risk>

## Evidence

- `<path>:<start>-<end>`: what is there.
```

## Fingerprint

- `kind` is one of `duplication`, `complexity`, `dead-code`, `coupling`,
  `convention`, `leftover`, `test`.
- Paths are repository-relative and sorted; `symbol-or-topic` is the
  function, class, or a short kebab-case topic.
- The fingerprint is a first-pass match only. Code moves and renames break
  it, so deduplication also compares by intent.
