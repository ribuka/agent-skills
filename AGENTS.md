# instructions

- A monorepo of agent skills (shared by Claude Code and Codex) and Claude Code hooks.
  - Each skill lives in `skills/<name>/` with a `SKILL.md` (YAML frontmatter + instructions) and optional `scripts/`, `references/`, `tests/`.
  - Skills are symlinked directly from this repository into both `~/.agents/skills/<name>` and `~/.claude/skills/<name>` (never chained through each other), so edits here take effect immediately. Skills referenced as `~/.agents/skills/...` resolve to this repository.
- Always respond in Japanese.
- Backward compatibility is NOT required.
  - NEVER add or keep compatibility layers, deprecated aliases, old config keys, or fallbacks for old script options.
  - When a script option, config key, output format, or file path changes, replace it outright and update every caller (`SKILL.md`, `references/`, other skills, tests, CI) in the same change.

## Skills

- Write `SKILL.md`, references, and script messages in English; keep the frontmatter `name` equal to the directory name.
- Keep `SKILL.md` short; move option tables and long details to `references/`.
- When a skill calls another skill's script, refer to it by its installed path (`~/.agents/skills/<name>/scripts/...`).
- Cross-skill contract: a skill's instructions only work while they are in the agent's context, so a caller may repeat the behavioral rules it needs at decision time. Remove a reference because it is an implementation detail, not because it is duplicated.
  - A caller may name: the skill, its installed script paths, arguments, exit codes, and output formats documented in the provider's `SKILL.md`, mode names, and behavioral rules.
  - A caller must not name: the provider's config file names or paths, internal step numbers, or internal values (retry intervals, storage paths). If the caller needs such a value, make the provider's script output it.
  - A provider must not know its callers: no caller skill names, caller frontmatter, or copies of caller-specific text. Never keep the same text in two places with an instruction to keep them consistent.

## Hooks

- Each Claude Code hook lives in `hooks/<name>/` with its script and, as needed, supporting files (e.g. `config.conf`) and `tests/`.
- Install a hook by creating a junction `~/.claude/hooks/<name>` → `hooks/<name>/` in this repository, then registering it in `~/.claude/settings.json` by its installed path (never this repository's path).
- Append `|| exit 1` to the registered command so that a missing script (exit 2 from `uv run`) does not block every tool call; return decisions as JSON on stdout with exit 0.

## Python

- Always use `uv run`.
- NEVER use `python -m`, `Set-Location` or one-liners and here-string in powershell.
- When working python coding, read `.agents/docs/python.md` and follow it.

### Verification commands

- Validate skill frontmatter: `uv run --no-project --with pyyaml .github/scripts/validate_skills.py`
- Run tests: `uv run --no-project --with pytest -m pytest <test-path>`
  - Full suite: `uv run --no-project --with pytest -m pytest skills/quota-guard/tests skills/pr-cross-review/tests skills/orca-issue-coordinator/tests skills/implement-review-merge/tests hooks/block-nonempty-dir-delete/tests hooks/worker-quota-guard/tests --tb=short -q`
  - When adding a `tests/` directory to a skill, add it to the pytest job in `.github/workflows/validate.yml`.
- Before running any pytest command, read `.agents/docs/pytest.md` and follow it.
- CI (`.github/workflows/validate.yml`) also runs shellcheck (`--severity=warning`) on `*.sh` and PSScriptAnalyzer on `*.ps1`; run them locally when available, otherwise rely on CI.

## Github

- Before creating a commit, read `.agents/docs/commit.md` and follow it.
- When creating a pull request, read `.agents/docs/pull-request.md` and follow it.

## Temporary files

- Create all temporary scripts and investigation files under `tmp/` at the repository root (git-ignored).
- NEVER create temporary files elsewhere; delete them when the task is complete.
