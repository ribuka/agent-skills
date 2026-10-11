#!/usr/bin/env python3
"""Resolve the worker model / effort settings for orchestrate-issues.

Precedence (highest first):
  1. command-line flags (--impl-model, --impl-effort, --merge-model, --merge-effort)
  2. <project-dir>/.orchestrate-issues.env
  3. <skill-dir>/config.env
  4. built-in defaults

Config files use plain KEY=VALUE lines; `#` starts a comment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULTS = {
    "IMPL_MODEL": "opus",
    "IMPL_EFFORT": "medium",
    "MERGE_MODEL": "sonnet",
    "MERGE_EFFORT": "medium",
}
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
SKILL_DIR = Path(__file__).resolve().parent.parent
PROJECT_FILE = ".orchestrate-issues.env"


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
        if not sep or key not in DEFAULTS:
            print(f"warning: {path}:{n}: ignored line: {raw}", file=sys.stderr)
            continue
        values[key] = value
    return values


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for key in DEFAULTS:
        ap.add_argument("--" + key.lower().replace("_", "-"), dest=key)
    ap.add_argument("--project-dir", default=".", help="directory holding .orchestrate-issues.env")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    opts = ap.parse_args()

    resolved = {k: (v, "default") for k, v in DEFAULTS.items()}
    for path in (SKILL_DIR / "config.env", Path(opts.project_dir) / PROJECT_FILE):
        if path.is_file():
            for k, v in parse_env(path).items():
                resolved[k] = (v, str(path))
    for k in DEFAULTS:
        if getattr(opts, k):
            resolved[k] = (getattr(opts, k), "argument")

    for k, (v, src) in resolved.items():
        if not v:
            print(f"error: {k} is empty (from {src})", file=sys.stderr)
            return 1
        if k.endswith("_EFFORT") and v not in EFFORTS:
            print(f"error: {k}={v} (from {src}) is not one of {sorted(EFFORTS)}", file=sys.stderr)
            return 1

    if opts.json:
        print(json.dumps({k: {"value": v, "source": s} for k, (v, s) in resolved.items()},
                         ensure_ascii=False, indent=2))
    else:
        for phase in ("IMPL", "MERGE"):
            m, ms = resolved[f"{phase}_MODEL"]
            e, es = resolved[f"{phase}_EFFORT"]
            print(f"{phase.lower()}: --model {m} --effort {e}  (model: {ms}; effort: {es})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
