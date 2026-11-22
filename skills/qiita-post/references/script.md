# qiita_post.py reference

Run: `uv run --no-project ~/.agents/skills/qiita-post/scripts/qiita_post.py <command> ...`

| Command | What it does |
|---|---|
| `set-token` | Prompts for a Qiita access token (scopes `read_qiita` and `write_qiita`; the script reads private items back), checks it with `GET /api/v2/authenticated_user`, and stores it in Windows Credential Manager. Only the user runs it, in their own terminal. |
| `draft-path --slug <slug>` | Prints `path: <DRAFTS_DIR>/<YYYYMMDD>-<slug>.md` and creates the directory. Fails if the file exists. The slug is lowercase ASCII words joined by `-`. |
| `create <file>` | `POST /api/v2/items` with `private: true` and `tweet: false`. Fails if the file already has an `id` or says `private: false`. |
| `update <file>` | `PATCH` title, body, and tags, keeping the current visibility. Fails with `out-of-sync` if the article on Qiita changed since the file was last synced. |
| `publish <file>` | Makes the article public with the content currently on Qiita. Fails with `out-of-sync` if the file differs from it (only line-ending style and trailing newlines are ignored), even when the article is already public. Already public with the same content: no change. |
| `pull <file>` | Replaces the file's title, tags, and body with the article on Qiita. |

After `create`, `update`, `publish`, and `pull`, the script writes `id`, `url`,
`private`, and `updated_at` back into the file's frontmatter.

## Article file

```markdown
---
title: "VS Code の Copilot で承認依頼を減らす"
tags: ["GitHubCopilot", "VSCode"]
---

本文 (Qiita Markdown)
```

- Frontmatter keys: `title`, `tags`, and the script-owned `private`, `id`,
  `url`, `updated_at`. Other keys are rejected.
- Values: write `title` as a JSON string and `tags` as a one-line JSON array
  (1-5 names without spaces). Block lists (`- tag`) are not supported.
- Everything after the closing `---` (leading blank lines dropped) is the body.

## Output

- Success (exit 0): `key: value` lines, e.g. `id: ...`, `url: ...`,
  `private: true`, and sometimes `note: ...`.
- Failure: one line `error: <kind>: <reason>` on stdout. Decide by `<kind>`,
  not by the exit code (PowerShell may report any failure as 1):
  - `failed` (exit 1): fix the cause named in the reason.
  - `no-token` (exit 3): no stored token, or Qiita rejected it (401).
  - `out-of-sync` (exit 4): the file and the article on Qiita disagree.
- Invalid CLI syntax exits 2.

## Configuration

`DRAFTS_DIR` in this skill's `config.conf` (shipped as `~/Documents/qiita-post`);
the git-ignored `config.local.conf` beside it overrides it (e.g. a OneDrive
folder shared with a phone). `KEY=value` lines; blank and `#` lines are skipped.
