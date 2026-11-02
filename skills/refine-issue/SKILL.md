---
name: refine-issue
description: Refine a feature request or an existing GitHub issue into an implementation-ready issue with no ambiguity left, interviewing the user with multiple-choice questions until every open point is decided, then create the issue (or save it as markdown when there is no GitHub remote) or update the existing one with `gh issue edit`. Use when asked to refine, clarify, or write up an issue, e.g. "refine-issue #42", "この要望を issue にして", "issue 12 を詰めて".
disable-model-invocation: false
---

# Refine issue

Turn a rough request or an existing issue into an issue that an implementer
can pick up without asking a single question.

## Done when

- The issue is broken down to implementable granularity.
- No ambiguity remains in the specification or the implementation approach.
  Every open point was either settled from the codebase or decided by the
  user through a multiple-choice question.

## Inputs

| Input                  | Mode    | Output |
|------------------------|---------|--------|
| A request (free text)  | Create  | New GitHub issue, or a markdown file when there is no GitHub remote |
| An issue number or URL | Update  | The same issue, rewritten with `gh issue edit` |

If the input is both (an issue number plus extra requests), use Update mode
and treat the extra requests as additional requirements.

## Workflow

### 1. Gather the source

- Create mode: the user's request.
- Update mode: `gh issue view <number> --json number,title,body,labels,comments`.
  Comments may contain decisions; take them into account.

### 2. Investigate the codebase

Read the code, docs, and existing issues the request touches. Resolve
everything the repository already answers (existing conventions, file
locations, APIs, naming, test layout) yourself. Never ask the user something
the code can answer.

### 3. List the open points

Write down every point that still has more than one reasonable answer:
behavior, scope and non-goals, inputs/outputs, error handling, edge cases,
UI/CLI/API shape, configuration, compatibility, data migration, tests,
documentation. Treat vague words ("fast", "appropriate", "etc.", "as needed")
as open points until they are made concrete.

### 4. Interview the user

Resolve the open points with the agent's multiple-choice question tool
(Claude Code: `AskUserQuestion`; Codex: `request_user_input`). Only if no such
tool is available, ask with numbered options in plain text.

- Ask up to 4 questions per round, most fundamental first; later questions
  often depend on earlier answers.
- Give 2-4 concrete, mutually exclusive options. Put your recommendation
  first and mark it `(Recommended)`; explain each option's trade-off in its
  description.
- Read free-text answers carefully: they may add requirements or open new
  points.
- After each round, go back to step 3. Repeat until no open point remains.

### 5. Write the issue

Follow [the issue template](references/issue-template.md). Write the issue
in the language of the user's request (Update mode: of the existing issue).

- Update mode: rewrite the whole body; do not keep the old body (GitHub keeps
  the edit history). Fold every still-valid intent of the old body and its
  comments into the new one. Update the title too if it no longer fits.

Before publishing, check the draft against "Done when". If any sentence
still allows two readings, go back to step 4.

### 6. Confirm (optional)

Read `CONFIRM_BEFORE_PUBLISH` from `~/.agents/skills/refine-issue/config.conf`.
If `true`, show the title and body and ask for approval with the
multiple-choice tool (approve / request changes). Apply requested changes and
ask again. If `false`, go straight to step 7.

### 7. Publish

Write the body to a file under `tmp/` (git-ignored) and pass it with
`--body-file`, never inline. Delete the file afterwards.

**Update mode:**

```bash
gh issue edit <number> --body-file tmp/issue-body.md [--title "<title>"]
```

**Create mode:** use GitHub only when all of these succeed; otherwise save
a markdown file.

```bash
git remote
gh auth status
gh repo view --json nameWithOwner --jq .nameWithOwner
```

- GitHub: `gh issue create --title "<title>" --body-file tmp/issue-body.md`.
- Markdown file:
  - Directory: an existing directory in the repository that already holds
    issues or task specs (e.g. `docs/issues/`, `issues/`). If none exists,
    use `docs/issues/`.
  - File name: `issue_<yyyy-mm-ddTHHmm>.md` in local time, e.g.
    `issue_2026-11-02T1430.md`. Get it with `date +%Y-%m-%dT%H%M` (bash) or
    `Get-Date -Format "yyyy-MM-dd'T'HHmm"` (PowerShell).
  - Put the title as the first line (`# <title>`), followed by the body.

### 8. Report

Report the issue URL or the file path, and list the decisions made in the
interview.
