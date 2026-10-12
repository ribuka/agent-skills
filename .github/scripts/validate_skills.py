"""Check that every skills/<name>/SKILL.md has valid frontmatter.

Run with: uv run --with pyyaml .github/scripts/validate_skills.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


def check(skill_dir: Path) -> list[str]:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return ["SKILL.md is missing"]

    text = skill_md.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if not text.startswith("---") or len(parts) < 3:
        return ["SKILL.md does not start with a --- frontmatter block"]

    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        return [f"frontmatter is not valid YAML: {exc}"]
    if not isinstance(meta, dict):
        return ["frontmatter is not a mapping"]

    errors = []
    for key in ("name", "description"):
        if not isinstance(meta.get(key), str) or not meta[key].strip():
            errors.append(f"frontmatter `{key}` is missing or empty")
    if meta.get("name") != skill_dir.name:
        errors.append(f"frontmatter name {meta.get('name')!r} does not match directory {skill_dir.name!r}")
    return errors


def main() -> int:
    skill_dirs = sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir())
    failed = False
    for skill_dir in skill_dirs:
        for error in check(skill_dir):
            print(f"skills/{skill_dir.name}: {error}")
            failed = True
    if not failed:
        print(f"{len(skill_dirs)} skills OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
