# Triage

Most raw findings should be dropped. A finding becomes a candidate only if
it passes every filter, then candidates are ranked by score.

## Filters (drop the finding if any applies)

- **Coincidental duplication**: the copies look alike but serve
  requirements that change for different reasons. Merging them would
  couple unrelated changes.
- **Below the rule of three**: two small copies with no sign of a third.
  Note it only if the two must change together (a shared rule or format).
- **Intentional**: the repository documents the duplication or structure
  as deliberate (e.g. a caller repeating rules it needs at decision time).
- **Cold code**: not changed for a long time and not on any hotspot path;
  refactoring it buys little.
- **No safety net and high blast radius**: no tests cover the code and the
  change touches many callers. Turn it into a "add tests first" candidate
  instead, or drop it.
- **Already in flight**: an open pull request is changing the same code.
- **Tool noise**: a lint/complexity number with no concrete maintenance
  problem behind it.

## Score

Rate each 1-3 and compute `benefit * 2 - cost - risk`:

| Axis | 1 | 2 | 3 |
|------|---|---|---|
| Benefit | Cosmetic | Removes a real duplication or simplifies a hot function | Prevents a likely bug or unblocks planned work |
| Cost | One file, under an hour | A few files | Many files or a design decision needed |
| Risk | Covered by tests, local | Partly covered | Untested or widely called |

Break ties by how often the code changed in the window. Record the three
ratings in the issue so a reader can disagree with them.

## Merging findings

Findings that one pull request would fix become one candidate (e.g. three
jscpd clones of the same helper). A candidate too large for one pull
request is split, and only its first step is filed.
