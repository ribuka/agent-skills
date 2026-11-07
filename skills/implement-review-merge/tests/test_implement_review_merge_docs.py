"""Tests that SKILL.md keeps its mode-independent token budget.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL_MD = SKILL_DIR / "SKILL.md"
COORDINATOR_MD = SKILL_DIR.parent / "orca-issue-coordinator" / "SKILL.md"


def test_ci_registration_and_worker_completion_contract() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    waiting = " ".join((SKILL_DIR / "references/ci-waiting.md").read_text(encoding="utf-8").split())
    for text in (skill, waiting):
        for phrase in ("wait_ci_registration.py --pr <pr-number> --head <full-sha>",
                       "CI_REGISTRATION_TIMEOUT_SECONDS", "30 seconds", "Exit `0`",
                       "Exit `2`", "Exit `1`", "monitor-error: no checks reported on",
                       "CI completion (success or failure) on the synced head before `worker_done`",
                       "never hand off with `CI pending`"):
            assert phrase in text


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
    assert "acceptance criteria or a bug's reproduction" in benchmarks


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


def test_both_worker_phases_report_unmet_or_unverified_criteria() -> None:
    modes = " ".join(_section(SKILL_MD.read_text(encoding="utf-8"), "Execution modes").split())
    contract = modes.split("- In worker mode:", 1)[1].split(
        "The Coordinator alone decides", 1)[0]
    for phrase in ("In both Implementation and Merge preparation",
                   "`unmet/unverified acceptance criteria:` in `worker_done`",
                   "every criterion not met or not verified",
                   "reason for each", "`none` only when all criteria are met and verified",
                   "separate from review findings and blockers"):
        assert phrase in contract


def test_resumed_phase_asks_for_handoff_first() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    resumed = skill.split("**Resumed phase:**", 1)[1].split("**Quota pause:**", 1)[0]
    assert "commits not on `origin/main`, uncommitted changes, or a pull request" in resumed
    assert "Implementation phase retried after a stop" in resumed
    assert resumed.index("ask the Coordinator for the handoff") < resumed.index(
        "rebuild the state")
    assert "end the turn" in resumed
    assert "larger of the handed-off and printed review counts" in resumed


def test_post_merge_completion_is_standalone_only_after_confirmed_merge() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    completion = skill.split("### Standalone post-merge completion", 1)[1].split("## Token budget", 1)[0]
    assert skill.index("### 10. Merge") < skill.index("### Standalone post-merge completion")
    for text in ("Only in Standalone mode", "confirms the target PR's state", "`MERGED`",
                 "immediately before", "final report", "Do not run this completion in any worker phase",
                 "merge failed", "unconfirmed", "--mode standalone --pr-state MERGED",
                 "merge result and local synchronization result separately",
                 "Never retry the merge because synchronization failed"):
        assert text in completion


def test_findings_control_iteration_and_merge_gate() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    step7 = skill.split("### 7. Iterate on findings", 1)[1].split("### 8.", 1)[0]
    for text in ("**must >= 1:**", "fix every must finding", "worthwhile optional suggestions",
                 "**must = 0:** do not change code and do not request a re-review",
                 "explaining why each optional suggestion is not adopted",
                 "review-latest-findings: unknown", "read only the latest review body",
                 "review-latest-findings: none", "do not merge"):
        assert text in step7
    merge = skill.split("### 10. Merge", 1)[1].split("### Standalone", 1)[0]
    assert "no unresolved must findings" in merge
    assert "optional suggestions do not block merging" in merge


def test_followup_candidates_are_reported_in_all_modes() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    assert "**起票候補** in the final report; do not create Issues" in skill
    assert "summary and review comment URL for each" in skill
    assert "In both worker phases" in skill
    assert "`worker_done` as `follow-up candidates:`" in skill
    modes = skill.split("## Execution modes", 1)[1].split("## Workflow", 1)[0]
    assert modes.count("`follow-up candidates:`") == 2
    step5 = skill.split("### 5.", 1)[1].split("### 6.", 1)[0]
    assert "For each optional suggestion not adopted, explain why in the PR reply" in step5


def test_worker_mode_does_not_add_verification_environments() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    worker = skill.split("- In worker mode:", 1)[1].split("- Running inside ORCA", 1)[0]
    for phrase in ("[Verification](references/verification.md)",
                   "Verify with the method the repository's docs",
                   "without one, use the repository's tests and a check you actually ran locally",
                   "Never add, as a criterion, verification in an environment or with data the Issue does not require",
                   "background, current state, or measurement notes is not a criterion",
                   "only the Issue's tasks and acceptance criteria are",
                   "Still report a missing behavior the Issue's goal clearly requires",
                   "a missing behavior is not an added criterion",
                   "PR body's test section"):
        assert phrase in worker


def test_bug_fixes_are_verified_under_reproduction_conditions() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    implement = skill.split("### 2. Implement", 1)[1].split("### 3. Commit", 1)[0]
    for phrase in ("fixes a bug and states its reproduction conditions",
                   "confirm the fix under those conditions once at the end",
                   "synthesize data the Issue describes",
                   "report only an environment you cannot prepare, with the reason"):
        assert phrase in implement
    ref = " ".join((SKILL_DIR / "references/verification.md").read_text(encoding="utf-8").split())
    for phrase in ("Confirm the fix under those conditions",
                   "create it and verify with it", "under `tmp/`", "delete it when done",
                   "run on small data", "confirm once under the reproduction conditions at the end",
                   "Report only the conditions you cannot prepare locally",
                   "is context, not a criterion",
                   "A Coordinator's brief does not lower the Issue's requirements"):
        assert phrase in ref
