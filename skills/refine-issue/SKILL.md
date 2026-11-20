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
  Every open point was either settled from the codebase, decided by the
  user through a multiple-choice question, or (only without an interview,
  or for the points not asked yet when the user delegates the rest partway
  through the interview, see step 5) settled by the recommended option and
  marked `[auto]`.
- Every acceptance criterion states its `Intent:` and has a `Check:` the
  implementing agent can run in its expected environment and permissions,
  with a stated `Passing:` result, or is a user-required pre-merge check
  with a plan recorded in the issue (see step 4).

## Output format

Issues this skill writes keep this format, which other tools may rely on.
The labels stay in English whatever the issue's language.

- Each acceptance criterion:

  ```markdown
  - [ ] Intent: <the property that must hold, independent of how it is checked>
    - Check: <test, command, or operation; one way to check the property>
    - Passing: <the result that counts as passing>
  ```

  `Intent:` is the criterion; `Check:` and `Passing:` are one example of
  checking it.
- Each line in Decisions is `- <question>: <decision> (<reason>)`. A
  decision the user did not choose (the recommended option taken without an
  interview, or for a point not asked yet when the user delegated the rest
  partway through the interview) starts with `- [auto] `. Points the code or
  docs settled are not marked.
- A `## Related issues` section appears when an open issue or unmerged pull
  request touches the same feature, file, or state. It states the assumed
  state of the default branch and decides every point that depends on the
  other's outcome for each case; it never says "undecided".

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

Find open issues and unmerged pull requests that touch the same feature,
files, or state (`gh issue list`, `gh pr list`) and read their bodies. Write
what you find in Related issues.

### 3. List the open points

Write down every point that still has more than one reasonable answer:
behavior, scope and non-goals, inputs/outputs, error handling, edge cases,
UI/CLI/API shape, configuration, compatibility, data migration, tests,
documentation. Treat vague words ("fast", "appropriate", "etc.", "as needed")
as open points until they are made concrete.

### 4. Plan how each acceptance criterion is verified

For each draft acceptance criterion, name the test, command, or operation
the implementing agent can run with the environment and permissions it is
expected to have, and the result that counts as passing.

- When a criterion needs real GUI interaction, a specific device, an
  account, or a human, look for an available way to check the same
  behavior (automated tests, simulated input, a headless run). If a
  simulated check covers only part of the path, state what it covers and
  what it does not (e.g. a synthetic drop event reaches the handler but
  skips the OS drag-and-drop between processes).
- A check the agent cannot run by itself is not an acceptance criterion by
  default. This includes a check that needs a tool or permission the agent
  lacks (e.g. `gh` cannot attach an image to a pull request). If the check
  is still wanted, record it as a post-merge check.
- When a criterion uses a measured value as a threshold, measure the
  default branch at least 3 times and look at the median and the spread
  (minimum to maximum) before choosing the value. State in `Passing:` how
  run-to-run variation is handled (e.g. judged on the median, or m of n
  runs pass), and record the measurements in Decisions.
  - Measure the baseline through the `Check:`'s same entry point, data,
    and settings (the same function or command). When the default branch
    cannot run that check (the feature is missing or fails), measure a
    prototype that goes through the same entry point.
  - Never choose a threshold from a measurement that skips or replaces
    part of the path (e.g. a prototype that processes all the data at
    once while the real code processes it chunk by chunk).
  - In Decisions, record the entry point measured and whether it ran on
    the default branch or a prototype.
- When a criterion records a value only the PR's own CI produces (a value
  known only after that PR's CI runs, e.g. the duration or run ID of the
  PR's run), have it recorded in a pull request comment, and make
  `Check:` reading that comment.
  - Require recording it in a file only when a file is needed: the user
    asks for it, or the repository's rules keep measurements in files.
    Then state in `Passing:` the run that counts (the run of the last
    commit that changed what is measured) and that later commits not
    changing what is measured do not replace the value.
- Only when the user explicitly requires such a check before merging, keep
  it as a pre-merge acceptance criterion and decide, before publishing: who
  runs it, the environment and steps, when it runs (e.g. after review, on
  the PR head), the passing result, and what happens if it cannot be run.
  Ask the user only for the points the code and existing procedures cannot
  settle.
- When whether a merge-deciding check can be run at all cannot be judged
  from the code and existing tests, split off a short investigation first
  (a separate issue or a first implementation step whose result decides the
  remaining criteria), and settle the criteria from its result.

Add every point this leaves undecided (e.g. whether a real-device check
must block the merge) to the open points.

### 5. Interview the user

Resolve the open points with a multiple-choice question tool, within that
tool's limits:

| Tool | Available | Questions per round | Options per question |
|------|-----------|---------------------|----------------------|
| `AskUserQuestion` (Claude Code) | Always | 1-4 | 2-4 |
| `request_user_input` (Codex) | Plan mode only | 1-3 | 2-3 |
| Numbered options in plain text | When neither tool is available | 1-4 | 2-4 |

- Ask the most fundamental questions first; later questions often depend on
  earlier answers.
  - When the request names a means (e.g. copying to the clipboard) and your
    investigation shows that the requested means cannot meet the expected
    scale or the purpose, ask about the requested means itself before any
    detailed question. Include alternative means that meet the purpose
    (e.g. an existing file export) among its options.
- Give concrete, mutually exclusive options. Put your recommendation first
  and mark it `(Recommended)`; explain each option's trade-off in its
  description.
- Read free-text answers carefully: they may add requirements or open new
  points.
- After each round, go back to step 3. Repeat until no open point remains.

**Without an interview:** when the arguments include `--no-interview`, or
the user asks to skip the interview (e.g. "インタビュー無しで", "おすすめで進めて"):

- Do not skip steps 2–4 or the checks in step 6.
- Do not ask; take the recommended option for each open point and record it
  in Decisions marked `[auto]`.
- Do not create a pre-merge check run by a person; step 4 keeps one only
  when the user explicitly requires it. Put such wanted checks under
  Post-merge checks.
- Step 7 still follows `CONFIRM_BEFORE_PUBLISH`.
- In step 9, list the `[auto]` decisions.

**Delegated partway:**

- When the user answers one question with the recommendation (picks the
  `(Recommended)` option, or writes "おすすめ" in Other), treat it as the
  answer to that question: it is the user's decision, not `[auto]`.
- When the user delegates the rest partway through the interview (e.g.
  "あとはおすすめで", "残りは任せる"):
  - Keep the points already answered as the user's decisions.
  - Take the recommended option for only the points not asked yet, and mark
    them `[auto]`.
  - From then on, follow "Without an interview" above: do not skip steps
    2–4 or the checks in step 6, do not create a pre-merge check run by a
    person, and list the `[auto]` decisions in step 9.
- When you cannot tell whether an answer is the answer to that one question
  or a delegation of the rest, treat it as the answer to that question and
  keep asking in the next round.

### 6. Write the issue

Follow [the issue template](references/issue-template.md). Write the issue
in the language of the user's request (Update mode: of the existing issue).

- Update mode: rewrite the whole body; do not keep the old body (GitHub keeps
  the edit history). Fold every still-valid intent of the old body and its
  comments into the new one. Update the title too if it no longer fits.

Before publishing, check the draft against "Done when" and these points:

- Each criterion's `Passing:` is consistent with both the Specification and
  the current code.
- Every count you wrote matches the items you listed (count them again).
- Every statement about current behavior ("same as X", "at the time of Y")
  rests on a file and function you read. For behavior driven by a trigger
  ("push on commit", "apply on save"), list every path that changes the
  state and confirm whether each goes through the trigger.
- Related issues contains no "undecided" or "decide before starting".

If any sentence still allows two readings or a check fails, go back to
step 5.

### 7. Confirm (optional)

Read `CONFIRM_BEFORE_PUBLISH` from `~/.agents/skills/refine-issue/config.conf`
(the shared defaults). If `config.local.conf` (the user's git-ignored
settings) exists beside it, read it too: a key it sets overrides the value
from `config.conf`. Both files use `KEY=value` lines; skip blank lines and
lines starting with `#`, and trim the key and value.
If `true`, show the title and body and ask for approval with the
multiple-choice tool (approve / request changes). Apply requested changes and
ask again. If `false`, go straight to step 8.

### 8. Publish

Write the body to a file under `tmp/` (git-ignored) and pass it with
`--body-file`, never inline. Delete the file afterwards.

**Update mode:**

```bash
gh issue edit <number> --body-file tmp/issue-body.md [--title "<title>"]
```

**Create mode:** use GitHub only when all of these succeed; otherwise save
a markdown file.

`git remote` must also print at least one remote.

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
  - Never overwrite an existing file. If the name is taken (e.g. several
    issues saved in the same minute), append `_2`, `_3`, ... before `.md`
    (`issue_2026-11-02T1430_2.md`), using the first free one.
  - Put the title as the first line (`# <title>`), followed by the body.

### 9. Report

Report the issue URL or the file path, and list the decisions made in the
interview and the decisions marked `[auto]`.
