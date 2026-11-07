"""Read and validate personal implement-review-merge settings."""

from pathlib import Path


def read_config(path: Path) -> dict[str, bool | int]:
    """Return validated settings, using defaults for absent files or keys."""
    values: dict[str, bool | int] = {
        "SYNC_LOCAL_MAIN_AFTER_MERGE": True,
        "CI_REGISTRATION_TIMEOUT_SECONDS": 300,
    }
    if not path.exists():
        return values
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or key not in values:
            raise ValueError(f"invalid setting at {path}:{number}")
        if key == "SYNC_LOCAL_MAIN_AFTER_MERGE":
            if value not in {"true", "false"}:
                raise ValueError(f"{key} must be true or false at {path}:{number}")
            values[key] = value == "true"
        else:
            if not value.isascii() or not value.isdecimal() or int(value) < 1:
                raise ValueError(f"{key} must be a positive integer at {path}:{number}")
            values[key] = int(value)
    return values
