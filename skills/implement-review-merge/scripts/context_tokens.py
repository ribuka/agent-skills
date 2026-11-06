#!/usr/bin/env python3
"""Print the size of this agent session's conversation as `context-tokens: <n>`.

The size is the input of the latest model request, read from the session's
own transcript:

- claude: `$CLAUDE_CODE_SESSION_ID`; the transcript is
  `<config-dir>/projects/*/<session-id>.jsonl` (`<config-dir>` is
  `$CLAUDE_CONFIG_DIR` or `~/.claude`). The size is the last assistant
  `message.usage` `input_tokens + cache_creation_input_tokens +
  cache_read_input_tokens`.
- codex: `$CODEX_THREAD_ID`; the transcript is
  `<codex-home>/sessions/YYYY/MM/DD/rollout-*-<thread-id>.jsonl`
  (`<codex-home>` is `$CODEX_HOME` or `~/.codex`). The size is the last
  `token_count` event's `info.last_token_usage.input_tokens`.

Prints `context-tokens: unknown` when the session ID, transcript, or usage is
missing. Always exits 0 (2 on invalid arguments).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def last_json_lines(path: Path) -> list[dict]:
    """Return the transcript's JSON objects, newest first (unparseable lines skipped)."""
    rows = []
    for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def claude_tokens(env: dict[str, str], home: Path) -> int | None:
    """Return the Claude Code conversation size, or None."""
    session = env.get("CLAUDE_CODE_SESSION_ID")
    if not session:
        return None
    root = Path(env["CLAUDE_CONFIG_DIR"]) if env.get("CLAUDE_CONFIG_DIR") else home / ".claude"
    for path in sorted((root / "projects").glob(f"*/{session}.jsonl")):
        for row in last_json_lines(path):
            usage = (row.get("message") or {}).get("usage") if row.get("type") == "assistant" else None
            if isinstance(usage, dict):
                keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
                values = [usage.get(key) or 0 for key in keys]
                if all(isinstance(value, int) for value in values):
                    return sum(values)
    return None


def codex_tokens(env: dict[str, str], home: Path) -> int | None:
    """Return the Codex conversation size, or None."""
    thread = env.get("CODEX_THREAD_ID")
    if not thread:
        return None
    root = Path(env["CODEX_HOME"]) if env.get("CODEX_HOME") else home / ".codex"
    for path in sorted((root / "sessions").glob(f"*/*/*/rollout-*-{thread}.jsonl")):
        for row in last_json_lines(path):
            payload = row.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "token_count":
                continue
            usage = (payload.get("info") or {}).get("last_token_usage") or {}
            if isinstance(usage.get("input_tokens"), int):
                return usage["input_tokens"]
    return None


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", required=True, choices=("claude", "codex"))
    opts = parser.parse_args(argv)
    reader = claude_tokens if opts.provider == "claude" else codex_tokens
    try:
        tokens = reader(dict(os.environ), Path.home())
    except OSError:
        tokens = None
    print(f"context-tokens: {'unknown' if tokens is None else tokens}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
