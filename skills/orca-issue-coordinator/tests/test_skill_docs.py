"""Tests that SKILL.md keeps the quota pause procedure in its reference.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL_MD = SKILL_DIR / "SKILL.md"
QUOTA_PAUSE = SKILL_DIR / "references" / "quota-pause.md"
QUOTA_PAUSE_INSTALLED = "~/.agents/skills/orca-issue-coordinator/references/quota-pause.md"


def test_skill_md_points_to_installed_quota_pause_reference() -> None:
    assert QUOTA_PAUSE.is_file()
    assert QUOTA_PAUSE_INSTALLED in SKILL_MD.read_text(encoding="utf-8")


def test_quota_pause_procedure_lives_only_in_reference() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    reference = QUOTA_PAUSE.read_text(encoding="utf-8")
    for heading in ("## On PAUSED_QUOTA or UNKNOWN", "## While paused", "## On wake-up"):
        assert heading in reference
    for detail in ("CronList", "recurring: false", "checkpoints/<run-id>.md"):
        assert detail in reference
        assert detail not in skill


def test_wake_up_carries_reference_path() -> None:
    assert QUOTA_PAUSE_INSTALLED in QUOTA_PAUSE.read_text(encoding="utf-8")
