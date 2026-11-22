# Finding request and record

Each filed finding produces the **request** handed to the refine-issue
skill, the **fingerprint marker** appended to every issue created from it,
and the **record** comment posted on each of those issues. Keep the
headings in English. Follow the privacy rule in `SKILL.md`: no user names,
home paths, tokens, account IDs, or raw log dumps.

## Request

Free text for refine-issue's Create mode. State the problem and the
proposed change to the skill; leave the specification, acceptance
criteria, and title to refine-issue.

```markdown
Improvement to the <skill> skill found by looking back on its runs since
<since> (<basis>).

## Problem

What went wrong in the runs and why the skill's current instructions or
scripts let it happen.

## Evidence

- <agent> session on <date>: <what happened, at which step of the skill>.
- <agent> session on <date>: <the same problem again, if seen>.
- `skills/<skill>/<file>:<line>`: the instruction that allows it.

## Proposed change

The change to the skill in a few sentences, and which situation it covers.

## Not doing

Alternatives considered and why not (e.g. "add a rule to every caller").
```

## Fingerprint marker

```markdown
<!-- lookback fingerprint: <skill>:<kind>:<topic> -->
```

`kind` is one of the kinds in [analysis.md](analysis.md); `topic` is a short
kebab-case name of the situation (e.g. `merge-after-red-ci`). The
fingerprint is a first-pass match only; deduplication also compares by
intent.

## Record

```markdown
## Lookback record

- Fingerprint: `<skill>:<kind>:<topic>`
- Window: since <since> (<basis>); <n> sessions read
- Impact: <1-3> - <reason>
- Recurrence: <1-3> - <sessions it was seen in>
- Cost: <1-3> - <reason>
- Score: <impact * 2 + recurrence - cost>
```
