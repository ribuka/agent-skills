#!/usr/bin/env python3
"""Find and condense past Claude Code / Codex sessions that used a skill.

Commands:

  find <skill> [--since <ref|date>] [--agent claude|codex|all] [--limit N]
      Resolve the installed skill, fix the review window, and list the
      sessions that invoked the skill inside it, newest first.

      The window starts when the skill took its current form: the commit time
      of the newest first-parent commit at HEAD of the skill's checkout that
      changed the skill directory (tests/ excluded), or the newest
      modification time of an uncommitted or untracked file in it, whichever
      is later. Outside git, the newest modification time of a file in the
      skill directory (tests/ excluded). --since <ref|date> replaces it.

      Output (exit 0), one `key: value` line each, then the sessions:
        skill_dir: <resolved skill directory>
        repo: <git top level of the skill's checkout, or empty>
        since: <ISO 8601 UTC>
        basis: commit <sha> <subject> | uncommitted <path> | mtime <path> | --since <value>
        sessions: <count found> (<count listed>)
        session: <agent>\t<path>\t<first invocation>\t<invocations>\t<cwd>

  digest <path> [--from <ISO 8601>] [--max-chars N]
      Print a condensed transcript of one session file: user and assistant
      text, tool calls with shortened input, and failed tool results.

An invocation is an explicit skill call (Claude Code: the Skill tool or a
`/<skill>` command; Codex: an injected `<skill>` block) or, for Codex, a tool
call that reads the skill's SKILL.md. Invocations after the session's first
lookback invocation are ignored: that part of the session reviews the skill
rather than uses it.

Exit 1 with `error: ...` on stderr when the skill is not installed or an
argument is invalid.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SELF_NAME = "lookback"
INSTALL_ROOTS = (Path.home() / ".agents" / "skills", Path.home() / ".claude" / "skills")
CLAUDE_ROOT = Path.home() / ".claude" / "projects"
CODEX_ROOT = Path.home() / ".codex" / "sessions"
EXCLUDED_DIRS = ("tests", "__pycache__")
TEXT_LIMIT = 600
TOOL_INPUT_LIMIT = 300


class LookbackError(Exception):
    """An argument or the environment does not allow the command to run."""


@dataclass
class Window:
    skill_dir: Path
    repo: str
    since: datetime
    basis: str


@dataclass
class Session:
    agent: str
    path: Path
    first: datetime
    count: int
    cwd: str


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(text: str) -> datetime | None:
    try:
        return _utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def _git(repo: Path, *args: str) -> str | None:
    """Run git in repo and return stdout, or None when it fails."""
    git = shutil.which("git")
    if git is None:
        return None
    result = subprocess.run([git, "-C", str(repo), *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", check=False)
    return result.stdout.rstrip() if result.returncode == 0 else None


def resolve_skill_dir(skill: str, roots: tuple[Path, ...] = INSTALL_ROOTS) -> Path:
    """Return the real directory of the installed skill."""
    for root in roots:
        candidate = root / skill
        if (candidate / "SKILL.md").is_file():
            return candidate.resolve()
    raise LookbackError(f"skill not installed: {skill} (looked in {', '.join(map(str, roots))})")


def _skill_files(skill_dir: Path) -> Iterator[Path]:
    for path in skill_dir.rglob("*"):
        rel = path.relative_to(skill_dir).parts
        if path.is_file() and rel[0] not in EXCLUDED_DIRS and "__pycache__" not in rel:
            yield path


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def fix_window(skill_dir: Path, since: str | None = None) -> Window:
    """Return the review window of the skill (see the module docstring)."""
    top = _git(skill_dir, "rev-parse", "--show-toplevel")
    repo = str(Path(top).resolve()) if top else ""
    if since:
        start = _parse_time(since)
        if start is None and repo:
            committed = _git(Path(repo), "log", "-1", "--format=%cI", since, "--")
            start = _parse_time(committed) if committed else None
        if start is None:
            raise LookbackError(f"--since is neither a date nor a commit: {since}")
        return Window(skill_dir, repo, start, f"--since {since}")
    if not repo:
        newest = max(_skill_files(skill_dir), key=lambda p: p.stat().st_mtime)
        return Window(skill_dir, repo, _mtime(newest), f"mtime {newest}")
    rel = skill_dir.relative_to(Path(repo)).as_posix()
    pathspec = [rel, *(f":(exclude){rel}/{name}" for name in EXCLUDED_DIRS)]
    line = _git(Path(repo), "log", "-1", "--first-parent", "--format=%H%x09%cI%x09%s",
                "HEAD", "--", *pathspec)
    if not line:
        raise LookbackError(f"no commit at HEAD touches {rel}; pass --since")
    sha, committed, subject = line.split("\t", 2)
    start, basis = _parse_time(committed), f"commit {sha[:12]} {subject}"
    status = _git(Path(repo), "status", "--porcelain", "--untracked-files=all", "--", *pathspec) or ""
    for entry in status.splitlines():
        path = Path(repo) / entry[3:].split(" -> ")[-1].strip('"')
        if path.is_file() and _mtime(path) > start:
            start, basis = _mtime(path), f"uncommitted {path}"
    return Window(skill_dir, repo, start, basis)


def _claude_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(item.get("text", "") for item in content
                         if isinstance(item, dict) and item.get("type") == "text")
    return ""


def _claude_invoked(record: dict) -> list[str]:
    """Return the skill names a Claude Code transcript record invokes."""
    message = record.get("message") or {}
    if record.get("type") == "user":
        return re.findall(r"<command-name>/([\w:.-]+)</command-name>", _claude_text(message.get("content")))
    if record.get("type") == "assistant" and isinstance(message.get("content"), list):
        return [item.get("input", {}).get("skill", "") for item in message["content"]
                if isinstance(item, dict) and item.get("type") == "tool_use" and item.get("name") == "Skill"]
    return []


def _codex_invoked(record: dict) -> list[str]:
    """Return the skill names a Codex rollout record invokes or reads."""
    payload = record.get("payload") or {}
    if record.get("type") != "response_item":
        return []
    if payload.get("type") == "message" and payload.get("role") == "user":
        text = "\n".join(item.get("text", "") for item in payload.get("content") or []
                         if isinstance(item, dict))
        return re.findall(r"<skill>\s*<name>([\w:.-]+)</name>", text)
    if payload.get("type") in ("function_call", "custom_tool_call"):
        args = str(payload.get("arguments") or payload.get("input") or "")
        return re.findall(r"skills[\\/]+([\w.-]+)[\\/]+SKILL\.md", args)
    return []


def _records(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


def scan_session(path: Path, agent: str, skill: str, since: datetime) -> Session | None:
    """Return the session's invocations of skill inside the window, or None."""
    invoked = _claude_invoked if agent == "claude" else _codex_invoked
    first: datetime | None = None
    count, cwd = 0, ""
    for record in _records(path):
        cwd = cwd or record.get("cwd") or (record.get("payload") or {}).get("cwd") or ""
        names = invoked(record)
        if SELF_NAME in names and skill != SELF_NAME:
            break
        if skill not in names:
            continue
        stamp = _parse_time(str(record.get("timestamp", "")))
        if stamp is None or stamp < since:
            continue
        first = first or stamp
        count += 1
    return Session(agent, path, first, count, cwd) if first else None


def _candidates(root: Path, pattern: str, since: datetime, skill: str) -> Iterator[Path]:
    if not root.is_dir():
        return
    needle = skill.encode()
    for path in root.glob(pattern):
        if _mtime(path) < since:
            continue
        try:
            if needle in path.read_bytes():
                yield path
        except OSError:
            continue


def find_sessions(skill: str, since: datetime, agent: str,
                  claude_root: Path = CLAUDE_ROOT, codex_root: Path = CODEX_ROOT) -> list[Session]:
    """Return the sessions that invoked skill since the window start, newest first."""
    sources = []
    if agent in ("claude", "all"):
        sources.append(("claude", claude_root, "*/*.jsonl"))
    if agent in ("codex", "all"):
        sources.append(("codex", codex_root, "**/rollout-*.jsonl"))
    found = [session
             for name, root, pattern in sources
             for path in _candidates(root, pattern, since, skill)
             if (session := scan_session(path, name, skill, since))]
    return sorted(found, key=lambda s: s.first, reverse=True)


def _short(text: str, limit: int) -> str:
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.S)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + " …"


def _claude_digest(record: dict) -> Iterator[str]:
    kind = record.get("type")
    if kind not in ("user", "assistant") or record.get("isMeta") or record.get("isSidechain"):
        return
    message = record.get("message") or {}
    content = message.get("content")
    if kind == "user" and isinstance(content, str):
        yield f"USER: {_short(content, TEXT_LIMIT)}"
        return
    for item in content if isinstance(content, list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and item.get("text", "").strip():
            yield f"{'USER' if kind == 'user' else 'ASSISTANT'}: {_short(item['text'], TEXT_LIMIT)}"
        elif item.get("type") == "tool_use":
            yield f"TOOL {item.get('name')}: {_short(json.dumps(item.get('input'), ensure_ascii=False), TOOL_INPUT_LIMIT)}"
        elif item.get("type") == "tool_result" and item.get("is_error"):
            yield f"TOOL ERROR: {_short(_claude_text(item.get('content')) or str(item.get('content')), TEXT_LIMIT)}"


def _codex_digest(record: dict) -> Iterator[str]:
    payload = record.get("payload") or {}
    if record.get("type") != "response_item":
        return
    kind = payload.get("type")
    if kind == "message" and payload.get("role") in ("user", "assistant"):
        text = "\n".join(item.get("text", "") for item in payload.get("content") or []
                         if isinstance(item, dict))
        if text.strip() and not text.lstrip().startswith(("<environment_context>", "<skill>", "# AGENTS.md")):
            yield f"{payload['role'].upper()}: {_short(text, TEXT_LIMIT)}"
    elif kind in ("function_call", "custom_tool_call"):
        args = str(payload.get("arguments") or payload.get("input") or "")
        yield f"TOOL {payload.get('name')}: {_short(args, TOOL_INPUT_LIMIT)}"
    elif kind in ("function_call_output", "custom_tool_call_output"):
        output = str(payload.get("output") or "")
        if re.search(r"exit[ _]code\W{0,3}[1-9]", output, re.I):
            yield f"TOOL ERROR: {_short(output, TEXT_LIMIT)}"


def digest(path: Path, start: datetime | None, max_chars: int) -> str:
    """Return a condensed transcript of the session file."""
    agent_digest = _codex_digest if path.name.startswith("rollout-") else _claude_digest
    lines: list[str] = []
    total = 0
    for record in _records(path):
        stamp = _parse_time(str(record.get("timestamp", "")))
        if start and (stamp is None or stamp < start):
            continue
        for line in agent_digest(record):
            entry = f"[{_iso(stamp) if stamp else '?'}] {line}"
            total += len(entry) + 1
            if total > max_chars:
                lines.append(f"… truncated at {max_chars} characters; rerun with --from to read further")
                return "\n".join(lines)
            lines.append(entry)
    return "\n".join(lines)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    find = sub.add_parser("find", help="fix the window and list sessions that used the skill")
    find.add_argument("skill")
    find.add_argument("--since")
    find.add_argument("--agent", choices=("claude", "codex", "all"), default="all")
    find.add_argument("--limit", type=int, default=10)
    dig = sub.add_parser("digest", help="print a condensed transcript of one session")
    dig.add_argument("path", type=Path)
    dig.add_argument("--from", dest="start")
    dig.add_argument("--max-chars", type=int, default=60000)
    opts = parser.parse_args()
    try:
        if opts.command == "find":
            window = fix_window(resolve_skill_dir(opts.skill), opts.since)
            sessions = find_sessions(opts.skill, window.since, opts.agent)
            print(f"skill_dir: {window.skill_dir}")
            print(f"repo: {window.repo}")
            print(f"since: {_iso(window.since)}")
            print(f"basis: {window.basis}")
            print(f"sessions: {len(sessions)} ({min(len(sessions), opts.limit)})")
            for s in sessions[:opts.limit]:
                print(f"session: {s.agent}\t{s.path}\t{_iso(s.first)}\t{s.count}\t{s.cwd}")
        else:
            if not opts.path.is_file():
                raise LookbackError(f"no such session file: {opts.path}")
            start = _parse_time(opts.start) if opts.start else None
            if opts.start and start is None:
                raise LookbackError(f"--from is not an ISO 8601 time: {opts.start}")
            print(digest(opts.path, start, opts.max_chars))
    except LookbackError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
