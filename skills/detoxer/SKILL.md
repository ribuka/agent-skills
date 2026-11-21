---
name: detoxer
description: Detox the codebase periodically - scout the repository for refactoring candidates (duplicated logic, growing complexity, dead code, drifting conventions), triage them by benefit against change cost and regression risk, and file only the few worth doing as implementation-ready GitHub issues (refined with the refine-issue skill), skipping ones already filed or rejected. Optionally implements the filed issues through to merge when configured. Meant to run periodically (e.g. weekly) from a scheduler, or on demand. Use when asked to look for refactoring opportunities or technical debt, e.g. "detoxer", "リファクタリングのネタを探して起票して", "技術的負債を棚卸しして".
disable-model-invocation: false
---

# Detoxer

Find refactoring work that is worth doing now, and file each piece as an
implementation-ready issue a person can accept or reject. One invocation is
one scan; schedule it outside this skill (cron, a Claude Code routine, a
Codex automation).

## Rules

- The scan and filing (steps 1-7) are read-only on the code: never edit,
  format, or commit files. Their only writes are issues (including the
  fingerprint marker appended to their bodies), labels, and issue comments. Code changes happen only in step 8, and only when
  `IMPLEMENT_FILED_ISSUES` is `true`.
- File at most `MAX_ISSUES_PER_RUN` candidates per run. Fewer good issues
  beat many noisy ones; filing nothing is a valid outcome.
- Never re-file a candidate that matches an open issue, or a closed one
  closed as not planned. A past rejection stands until the code it was
  about changes substantially.
- Every candidate needs evidence (file paths, line ranges, tool output) and
  a stated cost and risk. No evidence, no issue.

## Inputs

| Argument          | Meaning |
|-------------------|---------|
| (none)            | Scan by `SCAN_WINDOW_DAYS`: the files changed in the last that many days on the default branch, or the whole repository when it is empty. |
| `--since <ref\|date>` | Hotspot is the files changed since that commit, tag, or date. |
| `--full`          | Scan the whole repository even when `SCAN_WINDOW_DAYS` is set. |
| `--dry-run`       | Skip filing and implementing (steps 6 and 8); report every candidate as unfiled. |

The hotspot narrows where problems are looked for, not what they are
compared against: duplication between a hotspot file and an unchanged file
counts.

## Configuration

This skill's `config.conf` holds every setting's default; an optional,
git-ignored `config.local.conf` beside it overrides single keys. Never read
the files yourself; resolve the settings once at the start:

```bash
uv run --no-project ~/.agents/skills/detoxer/scripts/resolve_config.py
```

It prints one `KEY=value` line per setting (`--json` adds each value's
source file). Exit 1 means a file is invalid: report its `error:` line and
stop without scanning.

| Key | Meaning |
|-----|---------|
| `MAX_ISSUES_PER_RUN` | Upper bound on candidates filed in one run. |
| `SCAN_WINDOW_DAYS` | Hotspot window in days when neither `--since` nor `--full` is given; empty scans the whole repository. |
| `ISSUE_LABEL` | Label put on every filed issue; also used to find past ones. |
| `CONFIRM_BEFORE_PUBLISH` | `true`: ask for approval of each candidate before it is refined and filed. |
| `IMPLEMENT_FILED_ISSUES` | `true`: after filing, implement each filed issue through to merge (step 8). |
| `IMPLEMENT_WITH` | How step 8 implements: `new-session` or `orca`. |
| `IMPLEMENT_TIMEOUT_SECONDS`, `CLAUDE_PERMISSION_MODE`, `CODEX_SANDBOX` | Used by `implement_issues.py` (`new-session`) only. |

## Workflow

### 1. Fix the scope

First decide whether the repository is on GitHub: it is when `git remote`
prints at least one remote and both `gh auth status` and
`gh repo view --json nameWithOwner,defaultBranchRef` succeed.

- **On GitHub:** `git fetch origin <default-branch>`; the commit to scan,
  `<scan-ref>`, is `origin/<default-branch>`.
- **Not on GitHub (local mode):** `<scan-ref>` is `HEAD`. Skip every GitHub
  lookup: step 2, the pull request check in step 5, and steps 6 and 8. Every
  candidate goes to the report's unfiled candidates.

Scan `<scan-ref>`, not the current working tree:

- Create a scan directory `<scan-dir>` under the system temp directory
  (e.g. `detoxer-scan-<repo>-<yyyymmdd-HHMMSS>`) and, in it, a detached
  worktree: `git worktree add --detach <scan-dir>/checkout <scan-ref>`.
- Run every detector and read every file in that worktree. Keep every
  temporary file of the run in `<scan-dir>`, never in the repository.

List the hotspot files with `git log --name-only --since=... <scan-ref>`
(or `<ref>..<scan-ref>`), dropping deleted, generated, vendored, and lock
files. With `--full`, or with `SCAN_WINDOW_DAYS` empty and no `--since`,
the hotspot is every file tracked at `<scan-ref>`
(`git ls-tree -r --name-only <scan-ref>`), with the same files dropped.

### 2. Load what was already decided

List every issue with the label, following every page (never a capped
list; a missing old issue would be filed again):

```bash
gh api --paginate "repos/{owner}/{repo}/issues?labels=<ISSUE_LABEL>&state=all&per_page=100" \
  --jq '.[] | select(.pull_request | not) | {number, title, state, state_reason, body}'
```

Collect each issue's fingerprint (the marker in its body, see
[candidate.md](references/candidate.md)) and its summary. Candidates
matching an open issue, or a closed one with `state_reason` `not_planned`,
are skipped in step 5.

### 3. Detect

Run the detectors in [detection.md](references/detection.md) that fit the
repository's languages and are available; skip the rest and say so in the
report. Respect the repository's own lint configuration. Then read the
hotspot files yourself for the structural problems tools miss (listed in
the same file).

### 4. Triage

Judge each raw finding with [triage.md](references/triage.md): drop the
ones that fail its filters, score the rest, and merge findings that one
change would fix into one candidate.

### 5. Deduplicate

Drop candidates whose fingerprint matches step 2, and candidates that
describe the same change as an existing issue even with a different
fingerprint (code moves; compare by intent). Also check open pull requests
(`gh pr list`) that already touch the same code; a candidate there is not
filed this run and goes to the report's unfiled candidates.

### 6. Refine and file

With `--dry-run`, or in local mode (step 1), skip this step: every
candidate goes to the report's unfiled candidates.

Take the top `MAX_ISSUES_PER_RUN` candidates by score. For each, write the
request and the record from [candidate.md](references/candidate.md), in the
language of the repository's recent issues. Then:

- If `CONFIRM_BEFORE_PUBLISH` is `true`, show the requests and ask for
  approval per candidate with a multiple-choice question; drop the
  rejected ones.
- Ensure the label exists:
  `gh label create <ISSUE_LABEL> --description "Found by detoxer" --force`.
- For each candidate, highest score first:
  1. Run the refine-issue skill on the request with `--no-interview`. It
     creates the issue (or several, if it splits the work) and reports the
     issue URLs. If it saved a markdown file instead, delete that file and
     report the candidate as not filed.
  2. For each created issue:
     - `gh issue edit <number> --add-label <ISSUE_LABEL>`.
     - Append the fingerprint marker to its body: save
       `gh issue view <number> --json body --jq .body` to a file, add the
       marker line at the end, and `gh issue edit <number> --body-file <file>`.
     - Post the record: `gh issue comment <number> --body-file <file>`.

Write every request and record to a file in `<scan-dir>` with your
file-writing tool.

### 7. Report the scan

First clean up: `git worktree remove --force <scan-dir>/checkout`, then
delete `<scan-dir>` (on every path through steps 1-6, including errors).

Write the report in your final response, so it stays in the session log:
the session log is the only place unfiled candidates are kept. Report, in
this order:

- Scope: default branch commit, hotspot window (or whole repository), number of files.
- Filed issues (URL, title, score).
- Unfiled candidates: every candidate that passed triage but was not
  filed, each with:
  - Why it was not filed: beyond `MAX_ISSUES_PER_RUN`, rejected at
    confirmation, waiting for an open pull request (its number),
    refine-issue did not file it (its reason), `--dry-run`, or local mode.
  - Title, fingerprint, and the benefit / cost / risk ratings with the
    score.
  - Evidence (paths and line ranges) and the proposed change in one or two
    sentences.

  They are found again next run if still relevant.
- Skipped as duplicates (with the matching issue number).
- Dropped findings worth mentioning, with the triage reason.
- Detectors skipped and why.

If `IMPLEMENT_FILED_ISSUES` is `false`, stop here.

### 8. Implement (only when `IMPLEMENT_FILED_ISSUES` is `true`)

Skip this step with `--dry-run` or when no issue was filed. Otherwise
implement the filed issues by `IMPLEMENT_WITH`, highest score first
(issues split from one candidate in the order refine-issue created them).

**`new-session` (default):** start the coordinator script, detached, and
do not wait for it. It implements the issues one at a time in the given
order, each in a new unattended session of the agent running this one
(`claude` or `codex`) that runs the implement-review-merge skill in
Standalone mode, on a new branch `detoxer/issue-<number>` from the latest
`origin/<default-branch>`, in its own git worktree (this checkout is not
touched). It stops at the first issue that is not merged and comments the
reason on that issue; the rest stay filed and not started.

```bash
uv run --no-project ~/.agents/skills/detoxer/scripts/implement_issues.py \
  --agent <claude|codex> --base <default-branch> --detach \
  --issues <number> <number> ...
```

It prints `started: <pid>` and `summary: <path>` (the run summary, written
when the run ends) and exits 0; exit 1 means nothing was started (`error:`
on stderr). Report the two lines; this session's work ends here.

**`orca`:** hand the filed issues to a new Orca agent that runs the
orca-issue-coordinator skill as the Coordinator (its workers implement them
in parallel and it merges them one at a time), and do not wait for it.
Select the Orca executable as the orca-cli skill says (`ORCA_CLI_COMMAND`
if set, otherwise `orca`), then start the agent running this one
(`claude` or `codex`) in this checkout, as a terminal: the Coordinator must
run in an Orca terminal.

```bash
<orca> agent launch --agent <claude|codex> --surface terminal --json \
  --prompt "Use the orca-issue-coordinator skill to coordinate GitHub issues #<number> #<number> ... through to merge."
```

The handoff is done when `result.launch.prompt.outcome` is `journaled` or
`handed-to-terminal`: report the agent handle (`result.launch.outcome.handle`)
and the issue numbers; this session's work ends here. If the launch fails
(e.g. Orca is not running), report its error; the issues stay filed.
