# sessions.py

`uv run --no-project ~/.agents/skills/lookback/scripts/sessions.py <command> ...`

## find

```text
find <skill> [--since <ref|date>] [--agent claude|codex|all] [--limit N]
```

Output, one `key: value` line each, then up to `N` sessions, newest first:

```text
skill_dir: <real path of the installed skill>
repo: <git top level of the skill's checkout, or empty>
since: <ISO 8601 UTC>
basis: <why the window starts there>
sessions: <found> (<listed>)
session: <agent>\t<file>\t<first invocation>\t<invocations>\t<cwd>
```

### The window

The window starts when the skill took its current form, so runs of an
older version do not mix in:

| `basis:` | Start |
|----------|-------|
| `commit <sha> <subject>` | Commit time of the newest first-parent commit at `HEAD` of the skill's checkout that changed the skill directory, `tests/` excluded. The installed skill is that checkout, so this is when the running version appeared. |
| `uncommitted <path>` | The checkout has uncommitted or untracked changes in the skill directory newer than that commit; the start is the newest one's modification time. |
| `mtime <path>` | The skill is not in a git checkout; the start is the newest modification time of its files, `tests/` excluded. |
| `--since <value>` | Given explicitly: an ISO 8601 date or time, or a commit (its commit time). |

Every commit resets the window, a typo fix included. When that leaves too
few sessions, rerun with `--since` set to the commit that last changed the
behavior.

### Sessions

| Agent | Files | An invocation is |
|-------|-------|------------------|
| `claude` | `~/.claude/projects/*/*.jsonl` | a `Skill` tool call with that skill, or a `/<skill>` command |
| `codex` | `~/.codex/sessions/**/rollout-*.jsonl` | an injected `<skill>` block (`$<skill>`), or a tool call that reads `skills/<skill>/SKILL.md` |

Only invocations at or after `since` count. Invocations after the
session's first lookback invocation are ignored: from there on the session
reviews skills rather than uses them. Subagent transcripts are not
searched.

## digest

```text
digest <file> [--from <ISO 8601>] [--max-chars N]
```

Prints one line per event, `[<time>] <KIND>: <text>`, shortened:
`USER`, `ASSISTANT`, `TOOL <name>` (input), and `TOOL ERROR` (Claude Code:
results flagged as errors; Codex: outputs with a non-zero exit code).
Injected context (system reminders, skill bodies, AGENTS.md) is left out.
Output stops at `N` characters (default 60000) with a line saying so; rerun
with a later `--from` to read on.

## Errors

Exit 1 with `error: ...` on stderr: the skill is not installed under
`~/.agents/skills` or `~/.claude/skills`, no commit touches the skill
directory, `--since` is neither a date nor a commit, or the session file
does not exist.
