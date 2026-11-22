# Analysis

## What to look for

Compare what each run did with what the skill asks, step by step.

| Kind | Signs in a session |
|------|--------------------|
| `outcome` | The run ended without the skill's "done" state, or reported done when it was not. |
| `rework` | A step was done, undone, and redone; the user had to correct or re-ask. |
| `waste` | Repeated or unneeded tool calls, polling, reading large files to use a line, retries of the same failing command. |
| `rule-break` | The agent broke a rule the skill states. |
| `gap` | The skill says nothing about a situation the run hit, so the agent improvised (or asked). |
| `ambiguity` | The agent read an instruction a way the author likely did not mean, or hesitated between two readings. |
| `contradiction` | Two instructions (in the skill, or with a skill it calls) cannot both be followed. |
| `script` | A script of the skill failed, printed something unexpected, or its output was misread. |
| `bloat` | Instructions the runs never needed, or that the agent visibly skipped as irrelevant. |

## Where the fix belongs

Classify every finding; only `skill` findings are filed.

| Class | Meaning | Examples |
|-------|---------|----------|
| `skill` | A change to the skill's `SKILL.md`, references, or scripts would prevent it. | `gap`, `ambiguity`, `contradiction`, `script`, `bloat`; a `rule-break` seen in two or more sessions (the rule is not placed where the decision is made) |
| `agent` | A one-off mistake the current instructions already prevent. | a single `rule-break`, a typo in a command |
| `environment` | Outside the skill: tool, network, quota, another skill's bug, the user's setup. | API outage, a bug in a skill this one calls (name it in the report so it can be looked back on separately) |

Before calling a finding `skill`, check that the current files still allow
it. A rule added after the run means the finding is already handled.

## Merging

The same problem in several sessions is one finding with every occurrence
as evidence. Problems one change to the skill would fix are one finding.

## Score

Rate `skill` findings 1-3 and compute `impact * 2 + recurrence - cost`:

| Axis | 1 | 2 | 3 |
|------|---|---|---|
| Impact | Cosmetic, or a few wasted calls | Rework, a user correction, or a visibly longer run | Wrong result, data loss risk, or a stuck run |
| Recurrence | Once | Two sessions | Three or more sessions, or certain to recur |
| Cost | A sentence in `SKILL.md` | A step, a reference, or a script change | A redesign, or changes to several skills |

Do not file a finding with impact 1 and recurrence 1.
