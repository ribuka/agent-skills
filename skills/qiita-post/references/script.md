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
  - `private-info` (exit 5): the article looks like it contains private
    information; nothing was sent. The reason lists each hit as
    `title: ...`, `tags: ...`, or `body line N: <kind> (<masked text>)`.

## Private information check

`create` and `update` check the local title, tags, and body; `publish` checks
the article on Qiita (it may have been edited there). They report:

- email addresses, except `git@...` and example domains (`example.com`, `*.test`, ...);
- user home paths (`C:\Users\<name>`, `/Users/<name>`, `/home/<name>`), except
  placeholders such as `<name>`, `%USERNAME%`, `Public`, `you`;
- 40-hex strings (the shape of a Qiita token, and of a full commit SHA),
  GitHub tokens, `sk-` API keys, AWS access keys, Slack tokens, private keys;
- words in `PRIVATE_WORDS`, and the name of the current user's home directory.
  Matching ignores case; ASCII words match only as whole words.
- Invalid CLI syntax exits 2.

## Configuration

`DRAFTS_DIR` in this skill's `config.conf` (shipped as `~/Documents/qiita-post`);
the git-ignored `config.local.conf` beside it overrides it (e.g. a OneDrive
folder shared with a phone).

`PRIVATE_WORDS`: comma-separated words that must never appear in an article
(real name, account names, private repository or company names). Shipped
empty; the user keeps the real list in `config.local.conf` so it never enters
the repository.

`KEY=value` lines; blank and `#` lines are skipped. Only `PRIVATE_WORDS` may be empty.
