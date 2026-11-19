"""Tests that refine-issue keeps its output format and pre-publish checks.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL_MD = SKILL_DIR / "SKILL.md"
TEMPLATE = SKILL_DIR / "references" / "issue-template.md"


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _section(text: str, heading: str) -> str:
    return text.split(f"\n{heading}\n", 1)[1].split("\n#", 1)[0]


def test_output_format_matches_template() -> None:
    output_format = _section(SKILL_MD.read_text(encoding="utf-8"), "## Output format")
    template = TEMPLATE.read_text(encoding="utf-8")
    for label in ("Intent:", "Check:", "Passing:", "[auto]", "## Related issues"):
        assert label in output_format
        assert label in template


def test_skill_does_not_name_its_callers() -> None:
    for path in (SKILL_MD, TEMPLATE):
        text = path.read_text(encoding="utf-8")
        assert "orca-issue-coordinator" not in text
        assert "implement-review-merge" not in text


def test_investigation_reads_related_issues_and_prs() -> None:
    step = _flat(SKILL_MD).split("### 2. Investigate the codebase", 1)[1].split("### 3.", 1)[0]
    for phrase in ("`gh issue list`", "`gh pr list`", "Related issues"):
        assert phrase in step


def test_verification_plan_covers_tools_and_measurement_variance() -> None:
    step = _flat(SKILL_MD).split("### 4. Plan how each acceptance criterion is verified", 1)[1]
    step = step.split("### 5.", 1)[0]
    for phrase in ("tool or permission", "attach an image", "at least 3 times",
                   "median", "spread", "`Passing:`"):
        assert phrase in step


def test_pre_publish_checks() -> None:
    step = _flat(SKILL_MD).split("### 6. Write the issue", 1)[1].split("### 7.", 1)[0]
    for phrase in ("consistent with both the Specification and the current code",
                   "count them again", "rests on a file and function you read",
                   "list every path that changes the state",
                   "no \"undecided\" or \"decide before starting\""):
        assert phrase in step


def test_interview_can_be_skipped_without_skipping_checks() -> None:
    step = _flat(SKILL_MD).split("### 5. Interview the user", 1)[1].split("### 6.", 1)[0]
    for phrase in ("`--no-interview`", "Do not skip steps 2–4 or the checks in step 6",
                   "marked `[auto]`", "Do not create a pre-merge check run by a person",
                   "`CONFIRM_BEFORE_PUBLISH`"):
        assert phrase in step
    report = _flat(SKILL_MD).split("### 9. Report", 1)[1]
    assert "`[auto]`" in report


def test_template_decisions_and_related_issues_rules() -> None:
    template = _flat(TEMPLATE)
    for phrase in ("inputs it handles poorly", "whether that is accepted",
                   "Never write \"undecided\" or \"decide before starting\"",
                   "decide it for each case", "run-to-run variation"):
        assert phrase in template
