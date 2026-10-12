# Commit

## Message format

- Write the subject line as `<type>: <summary>`.
  - Write `<summary>` in Japanese.
  - Start `<summary>` with the skill name when the change targets one skill.
  - Keep code identifiers (skill names, file paths, options, etc.) as-is.
- Optionally add a body after a blank line to explain why the change was made.

### Types

- `feat`: A new skill or a new capability of a skill
- `fix`: A bug fix
- `refactor`: A change that neither fixes a bug nor adds a capability
- `test`: Adding or updating tests
- `docs`: Documentation-only changes (`SKILL.md` wording, `references/`, `AGENTS.md`, `.agents/docs/`)
- `ci`: Changes to CI configuration and scripts (`.github/`)
- `chore`: Other maintenance (e.g. `.gitignore`, version bumps)
- `revert`: Reverting a previous commit

Example:

```text
feat: pr-cross-review の再レビュー対象を前回レビュー以降のコミットに限定する
```

## Attribution

- NEVER include session URLs (e.g. `https://claude.ai/code/session_...`) in commit messages.
  - Omit the `Claude-Session:` trailer.
- `Co-Authored-By:` trailers are allowed.
