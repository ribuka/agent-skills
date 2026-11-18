#!/usr/bin/env python3
"""Resolve the worker settings (model / effort, concurrency) for orca-issue-coordinator.

The required --agent claude|codex selects both the Coordinator and worker agent.
Precedence (highest first):
  1. command-line flags (--impl-model, --impl-effort, --merge-model, --merge-effort,
     --max-impl-workers, --max-merge-workers, --fresh-worker-context-tokens)
  2. <skill-dir>/config.local.conf (git-ignored, optional; overrides single keys)
  3. <skill-dir>/config.conf (tracked; the only source of the defaults)

Both files hold `KEY=value` lines; blank lines and lines starting with `#` are
skipped, key and value are trimmed, and the value is taken literally. An unknown
key, a duplicate key, an empty value, or a line without `=` is an error naming
the file and line. Model and effort keys use CLAUDE_ or CODEX_ prefixes;
MAX_IMPL_WORKERS, MAX_MERGE_WORKERS, and FRESH_WORKER_CONTEXT_TOKENS are shared.
--serial (a flag only, never a config key) selects the serial mode: one worker
at a time, each Issue merged before the next is dispatched.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PHASE_KEYS = ("IMPL_MODEL", "IMPL_EFFORT", "MERGE_MODEL", "MERGE_EFFORT")
SHARED_KEYS = ("MAX_IMPL_WORKERS", "MAX_MERGE_WORKERS", "FRESH_WORKER_CONTEXT_TOKENS")
SETTINGS = (*PHASE_KEYS, *SHARED_KEYS)
AGENTS = ("claude", "codex")
CONFIG_KEYS = {f"{agent.upper()}_{key}" for agent in AGENTS for key in PHASE_KEYS} | set(SHARED_KEYS)
CONFIG_FILES = ("config.conf", "config.local.conf")
EFFORTS = {
    "claude": {"low", "medium", "high", "xhigh", "max"},
    "codex": {"minimal", "low", "medium", "high", "xhigh"},
}
SKILL_DIR = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    """A config file is unreadable or invalid."""


def read_config_file(path: Path) -> dict[str, str]:
    """Validate the whole file and return its KEY=value pairs."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"{path}: cannot read: {error}") from None
    values: dict[str, str] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep:
            raise ConfigError(f"{path}: line {n}: expected KEY=value")
        if key not in CONFIG_KEYS:
            raise ConfigError(f"{path}: line {n}: unknown key: {key}")
        if key in values:
            raise ConfigError(f"{path}: line {n}: duplicate key: {key}")
        if not value:
            raise ConfigError(f"{path}: line {n}: empty value for {key}")
        values[key] = value
    return values


def load_config(agent: str) -> dict[str, tuple[str, str]]:
    """Return {setting: (value, source path)} from config.conf, then config.local.conf."""
    resolved: dict[str, tuple[str, str]] = {}
    for name in CONFIG_FILES:
        path = SKILL_DIR / name
        if name != CONFIG_FILES[0] and not (path.exists() or path.is_symlink()):
            continue
        values = read_config_file(path)
        for key in SETTINGS:
            config_key = key if key in SHARED_KEYS else f"{agent.upper()}_{key}"
            if config_key in values:
                resolved[key] = (values[config_key], str(path))
    missing = [key if key in SHARED_KEYS else f"{agent.upper()}_{key}"
               for key in SETTINGS if key not in resolved]
    if missing:
        raise ConfigError(f"{SKILL_DIR / CONFIG_FILES[0]}: missing keys: {', '.join(missing)}")
    return {key: resolved[key] for key in SETTINGS}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--agent", required=True, choices=AGENTS,
                    help="Coordinator agent; workers always use the same agent")
    for key in SETTINGS:
        ap.add_argument("--" + key.lower().replace("_", "-"), dest=key)
    ap.add_argument("--serial", action="store_true",
                    help="run Issues one at a time, each merged before the next starts")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    opts = ap.parse_args()

    try:
        resolved = load_config(opts.agent)
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for k in resolved:
        if getattr(opts, k) is not None:
            resolved[k] = (getattr(opts, k), "argument")

    for k, (v, src) in resolved.items():
        if not v:
            print(f"error: {k} is empty (from {src})", file=sys.stderr)
            return 1
        if k.endswith("_EFFORT") and v not in EFFORTS[opts.agent]:
            print(f"error: {k}={v} (from {src}) is not one of {sorted(EFFORTS[opts.agent])}", file=sys.stderr)
            return 1
        if k in SHARED_KEYS and not (v.isascii() and v.isdigit() and int(v) >= 1):
            print(f"error: {k}={v} (from {src}) is not an integer >= 1", file=sys.stderr)
            return 1

    serial_source = "argument" if opts.serial else "default"
    if opts.json:
        print(json.dumps({"AGENT": {"value": opts.agent, "source": "argument"},
                          **{k: {"value": v, "source": s} for k, (v, s) in resolved.items()},
                          "SERIAL": {"value": opts.serial, "source": serial_source}},
                         ensure_ascii=False, indent=2))
    else:
        print(f"agent: {opts.agent}")
        for phase in ("IMPL", "MERGE"):
            m, ms = resolved[f"{phase}_MODEL"]
            e, es = resolved[f"{phase}_EFFORT"]
            print(f"{phase.lower()}: --model {m} --effort {e}  (model: {ms}; effort: {es})")
        for key in ("MAX_IMPL_WORKERS", "MAX_MERGE_WORKERS"):
            w, ws = resolved[key]
            print(f"{key.lower().replace('_', '-')}: {w}  (from {ws})")
        print(f"serial: {str(opts.serial).lower()}  "
              + ("(from argument)" if opts.serial else "(default)"))
        t, ts = resolved["FRESH_WORKER_CONTEXT_TOKENS"]
        print(f"fresh-worker-context-tokens: {t}  (from {ts})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
