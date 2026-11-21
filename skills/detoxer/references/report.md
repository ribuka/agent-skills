# Scan report

The report that ends every run (step 7). Write it in Markdown, in the
language you answer the user in, with the sections below in this order.

- Put every list of items in a table, one row per item, never as a run of
  bullets; keep each cell to one line.
- A section with nothing to report keeps its heading and says "None" in
  one line instead of an empty table.
- Open with one or two sentences: what was scanned, how many candidates
  were found and filed, and anything the reader must know first (e.g.
  `--dry-run`).

## Scope

| Item | Value |
|------|-------|
| Commit | `<scan-ref>` at `<short SHA>` |
| Hotspot | the `--since` or `SCAN_WINDOW_DAYS` window, or the whole repository |
| Files | number of hotspot files, and what was dropped (lock, vendored, generated) |
| Past issues | issues with `ISSUE_LABEL`: open / closed |
| Open pull requests | number checked in step 5 |
| Mode | filing, `--dry-run`, or local mode |

## Filed issues

| # | Issue | Title | Score | B / C / R |
|---|-------|-------|-------|-----------|
| 1 | <URL> | <title> | <score> | <benefit> / <cost> / <risk> |

Issues split from one candidate share its number, one row each.

## Unfiled candidates

Every candidate that passed triage but was not filed, highest score first.
They are found again next run if still relevant. First an overview:

| # | Title | Score | B / C / R | Why not filed |
|---|-------|-------|-----------|---------------|
| 1 | <title> | <score> | <benefit> / <cost> / <risk> | <reason> |

Why not filed is one of: beyond `MAX_ISSUES_PER_RUN`, rejected at
confirmation, waiting for open pull request #<number>, refine-issue did not
file it (<its reason>), `--dry-run`, or local mode.

Then one subsection per candidate, in the same order:

```markdown
### <#>. <title>

Fingerprint: `<kind>:<path>[,<path>...]:<symbol-or-topic>`

| Axis | Rating | Reason |
|------|--------|--------|
| Benefit | <1-3> | <reason> |
| Cost | <1-3> | <reason> |
| Risk | <1-3> | <reason; which tests cover it> |

| Evidence | What is there |
|----------|---------------|
| `<path>:<start>-<end>` | <what is there> |
| <tool name or commits> | <output excerpt or the change coupling> |

**Proposed change:** <one or two sentences>
```

## Skipped as duplicates

| Candidate | Fingerprint | Matching issue | Match |
|-----------|-------------|----------------|-------|
| <title> | `<fingerprint>` | #<number> (open, or closed as not planned) | fingerprint, or same intent |

## Dropped findings

Only the findings worth mentioning (a reader might expect them filed).

| Finding | Location | Reason |
|---------|----------|--------|
| <what was found> | `<path>:<line>` | <triage filter or low score, and why> |

## Detectors

Every detector in [detection.md](detection.md) that fits the repository's
languages, run or skipped.

| Detector | Status | Result or reason |
|----------|--------|------------------|
| <tool> | ran / skipped | <finding count, or why it was skipped> |
