"""Read and validate implement-review-merge settings.

`config.conf` (tracked) holds every default; `config.local.conf` beside it
(git-ignored, optional) overrides single keys. Both files hold `KEY=value`
lines; blank lines and lines starting with `#` are skipped, key and value are
trimmed, and the value is taken literally. An unknown key, a duplicate key, an
empty value, or a line without `=` is an error naming the file and line.
"""

from pathlib import Path

CONFIG_FILES = ("config.conf", "config.local.conf")
CONFIG_KEYS = ("SYNC_LOCAL_MAIN_AFTER_MERGE", "CI_REGISTRATION_TIMEOUT_SECONDS")


def read_config_file(path: Path) -> dict[str, bool | int]:
    """Validate the whole file and return its parsed values."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"{path}: cannot read: {error}") from None
    values: dict[str, bool | int] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        where = f"{path}: line {number}"
        if not sep:
            raise ValueError(f"{where}: expected KEY=value")
        if key not in CONFIG_KEYS:
            raise ValueError(f"{where}: unknown key: {key}")
        if key in values:
            raise ValueError(f"{where}: duplicate key: {key}")
        if not value:
            raise ValueError(f"{where}: empty value for {key}")
        if key == "SYNC_LOCAL_MAIN_AFTER_MERGE":
            if value not in {"true", "false"}:
                raise ValueError(f"{where}: {key} must be true or false")
            values[key] = value == "true"
        else:
            if not value.isascii() or not value.isdecimal() or int(value) < 1:
                raise ValueError(f"{where}: {key} must be a positive integer")
            values[key] = int(value)
    return values


def read_config(skill_dir: Path) -> dict[str, bool | int]:
    """Return every setting from config.conf, overridden by config.local.conf."""
    values = read_config_file(skill_dir / CONFIG_FILES[0])
    local = skill_dir / CONFIG_FILES[1]
    if local.exists() or local.is_symlink():
        values.update(read_config_file(local))
    missing = [key for key in CONFIG_KEYS if key not in values]
    if missing:
        raise ValueError(f"{skill_dir / CONFIG_FILES[0]}: missing keys: {', '.join(missing)}")
    return values
