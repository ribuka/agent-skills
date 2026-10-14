#!/usr/bin/env python3
"""Resolve the worker settings (model / effort, concurrency) for orca-issue-coordinator.

The required --agent claude|codex selects both the Coordinator and worker agent.
Precedence (highest first):
  1. command-line flags (--impl-model, --impl-effort, --merge-model, --merge-effort,
     --max-workers)
  2. <skill-dir>/config.conf
  3. built-in defaults

The config file uses plain KEY=VALUE lines; `#` starts a comment. Model and
effort keys use CLAUDE_ or CODEX_ prefixes; only MAX_WORKERS is shared.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CLAUDE_DEFAULTS = {
    "IMPL_MODEL": "opus",
    "IMPL_EFFORT": "medium",
    "MERGE_MODEL": "sonnet",
    "MERGE_EFFORT": "medium",
    "MAX_WORKERS": "3",
}
CODEX_DEFAULTS = {
    **CLAUDE_DEFAULTS,
    "IMPL_MODEL": "gpt-6.1-sol",
    "MERGE_MODEL": "gpt-6.1-sol",
}
DEFAULTS = {"claude": CLAUDE_DEFAULTS, "codex": CODEX_DEFAULTS}
CONFIG_KEYS = {f"{agent.upper()}_{key}" for agent in DEFAULTS
               for key in CLAUDE_DEFAULTS if key != "MAX_WORKERS"} | {"MAX_WORKERS"}
EFFORTS = {
    "claude": {"low", "medium", "high", "xhigh", "max"},
    "codex": {"minimal", "low", "medium", "high", "xhigh"},
}
SKILL_DIR = Path(__file__).resolve().parent.parent


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.split(" #", 1)[0].strip().strip("'\"")
        if not sep or key not in CONFIG_KEYS:
            print(f"warning: {path}:{n}: ignored line: {raw}", file=sys.stderr)
            continue
        values[key] = value
    return values


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--agent", required=True, choices=DEFAULTS,
                    help="Coordinator agent; workers always use the same agent")
    for key in CLAUDE_DEFAULTS:
        ap.add_argument("--" + key.lower().replace("_", "-"), dest=key)
    ap.add_argument("--json", action="store_true", help="emit JSON")
    opts = ap.parse_args()

    resolved = {k: (v, "default") for k, v in DEFAULTS[opts.agent].items()}
    config = SKILL_DIR / "config.conf"
    if config.is_file():
        values = parse_env(config)
        for k in resolved:
            config_key = k if k == "MAX_WORKERS" else f"{opts.agent.upper()}_{k}"
            if config_key in values:
                resolved[k] = (values[config_key], str(config))
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
        if k == "MAX_WORKERS" and not (v.isascii() and v.isdigit() and int(v) >= 1):
            print(f"error: {k}={v} (from {src}) is not an integer >= 1", file=sys.stderr)
            return 1

    if opts.json:
        print(json.dumps({"AGENT": {"value": opts.agent, "source": "argument"},
                          **{k: {"value": v, "source": s} for k, (v, s) in resolved.items()}},
                         ensure_ascii=False, indent=2))
    else:
        print(f"agent: {opts.agent}")
        for phase in ("IMPL", "MERGE"):
            m, ms = resolved[f"{phase}_MODEL"]
            e, es = resolved[f"{phase}_EFFORT"]
            print(f"{phase.lower()}: --model {m} --effort {e}  (model: {ms}; effort: {es})")
        w, ws = resolved["MAX_WORKERS"]
        print(f"max-workers: {w}  (from {ws})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
