"""Tests that SKILL.md keeps its mode-independent token budget.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL_MD = SKILL_DIR / "SKILL.md"
COORDINATOR_MD = SKILL_DIR.parent / "orca-issue-coordinator" / "SKILL.md"


def _section(text: str, heading: str) -> str:
    return text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def test_token_budget_applies_in_every_mode() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    intro = skill.split("## Execution modes", 1)[0]
    assert "**Token budget**" in intro
    assert "in every mode" in intro
    assert "applies in every mode" in _section(skill, "Token budget").replace(
        "rules\napply", "rules apply"
    ) or "apply in every mode" in _section(skill, "Token budget")


def test_token_budget_covers_each_rule() -> None:
    budget = _section(SKILL_MD.read_text(encoding="utf-8"), "Token budget")
    for label in (
        "**Broad investigation:**",
        "**Files:**",
        "**Tests:**",
        "**Benchmarks:**",
        "**Images**",
        "**Command output:**",
    ):
        assert label in budget
    assert "subagent" in budget
    assert "read the lines you change yourself" in budget
    assert "once, before pushing" in budget
    assert "-q --tb=short" in budget


def test_images_and_benchmarks_keep_quality_exceptions() -> None:
    budget = _section(SKILL_MD.read_text(encoding="utf-8"), "Token budget")
    images = budget.split("**Images**", 1)[1].split("\n- **", 1)[0]
    assert "by default" in images
    assert "acceptance criteria require" in images
    assert "one at a time" in images
    benchmarks = budget.split("**Benchmarks:**", 1)[1].split("\n- **", 1)[0]
    assert "small data" in benchmarks
    assert "acceptance criteria require" in benchmarks


def test_test_output_rule_lives_only_in_token_budget() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert skill.count("-q --tb=short") == 1
    assert "see step 9" not in skill


def test_coordinator_does_not_copy_token_budget() -> None:
    coordinator = COORDINATOR_MD.read_text(encoding="utf-8")
    step7 = coordinator.split("\n7. ", 1)[1].split("\n8. ", 1)[0]
    assert "implement-review-merge" in step7
    assert "**Token budget**" in step7
    assert "Do not restate general token-saving rules" in step7
    for phrase in ("small data", "downscaled images", "read only the lines"):
        assert phrase not in coordinator


def test_worker_quota_pause_report_includes_context_size() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    assert "**Quota pause:**" in skill
    assert "~/.agents/skills/implement-review-merge/scripts/context_tokens.py" in skill
    assert (SKILL_DIR / "scripts" / "context_tokens.py").is_file()
    for text in ("`worker_done --outcome failed`", "`worker-quota-paused:",
                 "`context-tokens: <n|unknown>`", "Never stop mid-rebase",
                 "`git rebase --abort`", "**Resumed phase:**",
                 "schedule a wake-up"):
        assert text in skill
