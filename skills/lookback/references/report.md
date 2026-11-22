# Report

The report that ends every run (step 7). Write it in Markdown, in the
language you answer the user in, with the sections below in this order.

- Put every list of items in a table, one row per item, keeping each cell
  to one line.
- A section with nothing to report keeps its heading and says "None".
- Open with one or two sentences: which skill, how many sessions were read,
  how many findings were found and filed, and anything the reader must
  know first (e.g. `--dry-run`, too few sessions).

## Scope

| Item | Value |
|------|-------|
| Skill | `<skill>` at `<skill_dir>` |
| Window | since `<since>` (`<basis>`) |
| Sessions | read / found, per agent |
| Past issues | issues with `ISSUE_LABEL`: open / closed |
| Mode | filing, `--dry-run`, or not filed (why) |

## Filed issues

| # | Issue | Title | Score | I / R / C |
|---|-------|-------|-------|-----------|
| 1 | <URL> | <title> | <score> | <impact> / <recurrence> / <cost> |

## Unfiled findings

Every `skill` finding not filed, highest score first:

| # | Title | Kind | Score | I / R / C | Why not filed |
|---|-------|------|-------|-----------|---------------|

Why not filed is one of: beyond `MAX_ISSUES_PER_RUN`, below the filing
bar, rejected at confirmation, waiting for open pull request #<number>,
refine-issue did not file it, `--dry-run`, no GitHub remote, or the current
directory is not the skill's repository.

Then one subsection per finding: the problem, the evidence (session and
step), and the proposed change.

## Agent and environment findings

Problems whose fix does not belong in the skill:

| Finding | Class | Session | Note |
|---------|-------|---------|------|

## Skipped as duplicates

| Finding | Fingerprint | Matching issue | Match |
|---------|-------------|----------------|-------|

## Sessions

| Agent | Date | Invocations | Outcome | Notes |
|-------|------|-------------|---------|-------|

Outcome is one of: done, partly done, failed, unclear. List sessions found
but not read (beyond `MAX_SESSIONS`) as one row.
