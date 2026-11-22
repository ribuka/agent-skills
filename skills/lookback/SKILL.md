---
name: lookback
description: Look back on how a skill actually ran - read the sessions that used it since it took its current form (or the current session), find where the run went wrong or wasted effort, separate one-off agent mistakes from problems in the skill itself, and file the skill problems worth fixing as implementation-ready GitHub issues (refined with the refine-issue skill), skipping ones already filed or rejected. Never edits the skill. Use when asked to review or reflect on a skill's runs, e.g. "lookback orca-issue-coordinator", "/lookback", "このスキルの実行を振り返って", "今回の作業を振り返って改善点を起票して".
disable-model-invocation: true
---

# Lookback

Turn evidence from real runs of a skill into a few fixes to that skill. One
invocation reviews one skill (or the skills used in the current session).

## Rules

- Read-only on every skill and every repository: never edit, format, or
  commit files. The only writes are issues (with the fingerprint marker in
  their bodies), labels, and issue comments, all in step 6.
- Review only runs of the skill in its current form. A finding from a run
  of an older version is noise unless the current `SKILL.md`, references,
  and scripts still allow it. Check every finding against the current files
  and drop it when they already address it.
- Every finding cites evidence: the session (agent, date, file) and the
  exact step, tool call, or message. State facts and inferences separately;
  never invent a step the session does not show. Unreadable or missing logs
  are reported as unchecked, not guessed.
- File at most `MAX_ISSUES_PER_RUN` findings per run, and only findings
  whose fix belongs in the skill. Filing nothing is a valid outcome.
- Never re-file a finding that matches an open issue, or a closed one
  closed as not planned.
- Issues hold no personal or session-private data: no user names, home
  paths, tokens, account IDs, or raw log dumps. Quote at most a few lines,
  with paths shortened to `~/` or repository-relative ones.

## Inputs

| Argument | Meaning |
|----------|---------|
| (none) | Review the current session: every skill invoked in it, with this conversation as the evidence. |
| `<skill>` | Review the past sessions that used `<skill>` since it took its current form. |
| `--since <ref\|date>` | Start the window at that commit or date instead (e.g. to include runs before a typo fix). |
| `--dry-run` | Skip filing (step 6); report every finding as unfiled. |

## Configuration

Resolve the settings once at the start; never read the config files yourself:

```bash
uv run --no-project ~/.agents/skills/lookback/scripts/resolve_config.py
```

It prints one `KEY=value` line per setting. Exit 1 means a file is invalid:
report its `error:` line and stop.

| Key | Meaning |
|-----|---------|
| `MAX_SESSIONS` | Upper bound on past sessions read, newest first. |
| `MAX_ISSUES_PER_RUN` | Upper bound on findings filed in one run. |
| `ISSUE_LABEL` | Label put on every filed issue; also used to find past ones. |
| `CONFIRM_BEFORE_PUBLISH` | `true`: ask for approval of each finding before it is filed. |

## Workflow

### 1. Fix the target and the window

With `<skill>` (and for each skill the current session invoked, in no-arg
mode), run:

```bash
uv run --no-project ~/.agents/skills/lookback/scripts/sessions.py \
  find <skill> --limit <MAX_SESSIONS> [--since <ref|date>]
```

It prints `skill_dir:`, `repo:` (the skill's git checkout, or empty),
`since:` and `basis:` (where the window starts and why), `sessions:`, and
one tab-separated `session:` line per session (agent, file, first
invocation, invocation count, cwd); details in
[sessions.md](references/sessions.md). Exit 1: report the `error:` line and
stop.

Read the skill's current `SKILL.md`, references, and scripts in `skill_dir`.
In no-arg mode, also note whether the window starts after the skill was
loaded in this session: then the session ran an older version.

If no session is found, or fewer than three, say so in the report and
suggest `--since` with an earlier commit; still review what there is.

### 2. Load what was already decided

Skip this step when `repo` has no GitHub remote. Otherwise, in `repo`, list
every issue with the label, following every page:

```bash
gh api --method GET --paginate "repos/{owner}/{repo}/issues" \
  -f labels=<ISSUE_LABEL> -f state=all -f per_page=100 \
  --jq '.[] | select(.pull_request | not) | {number, title, state, state_reason, body}'
```

Collect each issue's fingerprint (see [finding.md](references/finding.md))
and summary.

### 3. Collect the evidence

In no-arg mode the evidence is this conversation. Otherwise, for each
session, newest first, read its digest from the first invocation on:

```bash
uv run --no-project ~/.agents/skills/lookback/scripts/sessions.py \
  digest <file> --from <first invocation>
```

Follow up in the raw session file, or in the pull requests and issues the
session names, only where the digest is not enough to settle a finding.

### 4. Analyze

Judge every run with [analysis.md](references/analysis.md): find the
problems, classify each by where its fix belongs (`skill`, `agent`,
`environment`), merge the same problem seen in several sessions, and score
the `skill` findings. Drop findings the current skill files already
address.

### 5. Deduplicate

Drop findings whose fingerprint matches step 2, and findings that describe
the same change as an existing issue (compare by intent). Also check open
pull requests in `repo` (`gh pr list`) that already change the same part of
the skill; such a finding is not filed this run.

### 6. Refine and file

Skip this step with `--dry-run`, when `repo` has no GitHub remote, or when
the current directory is not inside `repo`
(refine-issue files in the current repository): every finding goes to the
report's unfiled findings.

Take the top `MAX_ISSUES_PER_RUN` `skill` findings by score. For each,
write the request and the record from [finding.md](references/finding.md),
in the language of the repository's recent issues, to files under the
system temp directory. Then:

- If `CONFIRM_BEFORE_PUBLISH` is `true`, show the requests and ask for
  approval per finding with a multiple-choice question; drop the rejected
  ones.
- Ensure the label exists:
  `gh label create <ISSUE_LABEL> --description "Found by lookback" --force`.
- For each finding, highest score first:
  1. Run the refine-issue skill on the request with `--no-interview`. It
     creates the issue (or several) and reports the URLs. If it saved a
     markdown file instead, delete that file and report the finding as not
     filed.
  2. For each created issue: `gh issue edit <number> --add-label <ISSUE_LABEL>`;
     append the fingerprint marker to its body (save
     `gh issue view <number> --json body --jq .body` to a file, add the
     marker line, `gh issue edit <number> --body-file <file>`); post the
     record with `gh issue comment <number> --body-file <file>`.

Delete the temporary files afterwards.

### 7. Report

Write the report in your final response, with the sections and tables in
[report.md](references/report.md). The session log is the only place
unfiled findings are kept.
