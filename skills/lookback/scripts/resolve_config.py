#!/usr/bin/env python3
"""Resolve the lookback settings and print them.

`config.conf` (tracked) holds every default; `config.local.conf` beside it
(git-ignored, optional) overrides single keys. Both files hold `KEY=value`
lines; blank lines and lines starting with `#` are skipped, key and value are
trimmed, and the value is taken literally. An unknown key, a duplicate key, an
empty value, a line without `=`, or an invalid value is an error naming the
file and line.

Output (exit 0): one `KEY=value` line per setting, in a fixed order, or with
--json an object {KEY: {"value": ..., "source": <file path>}}. Exit 1 with
`error: ...` on stderr when a file is unreadable or invalid.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

INTEGER_KEYS = ("MAX_SESSIONS", "MAX_ISSUES_PER_RUN")
BOOLEAN_KEYS = ("CONFIRM_BEFORE_PUBLISH",)
CONFIG_KEYS = ("MAX_SESSIONS", "MAX_ISSUES_PER_RUN", "ISSUE_LABEL", "CONFIRM_BEFORE_PUBLISH")
CONFIG_FILES = ("config.conf", "config.local.conf")
SKILL_DIR = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    """A config file is unreadable or invalid."""


def _check_value(key: str, value: str, where: str) -> None:
    """Raise ConfigError when the value does not fit the key's type."""
    if key in INTEGER_KEYS and not (value.isascii() and value.isdecimal() and int(value) >= 1):
        raise ConfigError(f"{where}: {key}={value} is not an integer >= 1")
    if key in BOOLEAN_KEYS and value not in ("true", "false"):
        raise ConfigError(f"{where}: {key}={value} is not true or false")


def read_config_file(path: Path) -> dict[str, str]:
    """Validate the whole file and return its KEY=value pairs."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"{path}: cannot read: {error}") from None
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        where = f"{path}: line {number}"
        if not sep:
            raise ConfigError(f"{where}: expected KEY=value")
        if key not in CONFIG_KEYS:
            raise ConfigError(f"{where}: unknown key: {key}")
        if key in values:
            raise ConfigError(f"{where}: duplicate key: {key}")
        if not value:
            raise ConfigError(f"{where}: empty value for {key}")
        _check_value(key, value, where)
        values[key] = value
    return values


def load_config(skill_dir: Path) -> dict[str, tuple[str, str]]:
    """Return {KEY: (value, source path)} from config.conf, then config.local.conf."""
    resolved: dict[str, tuple[str, str]] = {}
    for name in CONFIG_FILES:
        path = skill_dir / name
        if name != CONFIG_FILES[0] and not (path.exists() or path.is_symlink()):
            continue
        for key, value in read_config_file(path).items():
            resolved[key] = (value, str(path))
    missing = [key for key in CONFIG_KEYS if key not in resolved]
    if missing:
        raise ConfigError(f"{skill_dir / CONFIG_FILES[0]}: missing keys: {', '.join(missing)}")
    return {key: resolved[key] for key in CONFIG_KEYS}


def _typed(key: str, value: str) -> bool | int | str:
    """Convert a validated value to its JSON type."""
    if key in INTEGER_KEYS:
        return int(value)
    if key in BOOLEAN_KEYS:
        return value == "true"
    return value


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="emit JSON with each value's source")
    opts = parser.parse_args()
    try:
        resolved = load_config(SKILL_DIR)
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if opts.json:
        print(json.dumps({key: {"value": _typed(key, value), "source": source}
                          for key, (value, source) in resolved.items()},
                         ensure_ascii=False, indent=2))
    else:
        for key, (value, _source) in resolved.items():
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
