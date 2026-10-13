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
    for detail in ("CronList", "recurring: false", "checkpoint_dir"):
        assert detail in reference
        assert detail not in skill


def test_wake_up_carries_reference_path() -> None:
    assert QUOTA_PAUSE_INSTALLED in QUOTA_PAUSE.read_text(encoding="utf-8")


def test_merge_prep_worker_starts_from_spec_in_pr_worktree() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert 'worker-start --spec "<handoff>" --task-title' in skill
    assert "--worktree branch:<branch>" in skill
    merge_prep_step = skill.split("13. When a worker slot is free", 1)[1].split("14. ", 1)[0]
    assert "worker-start --spec" in merge_prep_step
    assert "worker-start --task" not in merge_prep_step


def test_merge_prep_skipped_when_pr_is_already_ready() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "Skip step 13 and go straight to step 14" in skill
    assert "git merge-base --is-ancestor origin/main origin/<branch>" in skill
    assert "gh pr checks <pr> --required" in skill


def test_worker_messages_go_to_dispatch() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "## Messaging workers" in skill
    assert "orca orchestration send --to dispatch:<dispatch_id>" in skill
    assert "A bare `--to ctx_…` fails with" in skill
    assert "<terminalHandle>" not in skill
    reference = QUOTA_PAUSE.read_text(encoding="utf-8")
    assert reference.count("send --to dispatch:<dispatch_id>") == 2
    assert "<terminalHandle>" not in reference


def test_skill_md_freezes_skill_checkout_during_run() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "`skill-checkout: <path>`" in skill
    assert "Never update" in skill


def test_merge_prep_states_re_review_criteria_and_report() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "Re-review criteria after a rebase or conflict resolution" in skill
    for label in ("**Mechanical:**", "**Newly written:**"):
        assert label in skill
    assert "`none`, `mechanical`, or `newly written`" in skill
    assert "Only if the merge-preparation worker reported a `newly written`" in skill


def test_quota_check_gates_by_exit_code_only() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "**Judge READY by exit code only:**" in skill
    assert "`<quota-check> && <command>`" in skill
    assert "Never grep the" in skill
    assert (
        "python ~/.agents/skills/quota-guard/scripts/quota_guard.py check && "
        "python <skill-dir>/scripts/wait_actionable.py" in skill
    )
    assert "grep -o" not in skill


def test_review_count_checked_with_review_status_script() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "bash ~/.agents/skills/pr-cross-review/scripts/review_status.sh <pr-number>" in skill
    assert "Do not count PR comments yourself" in skill
    assert "count the cross-review\n      comments on the PR" not in skill


def test_plan_is_presented_before_first_dispatch() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    dispatch_section = skill.split("## 1. Plan and dispatch", 1)[1].split("## 2.", 1)[0]
    assert "Before the first dispatch, briefly present the execution plan" in dispatch_section
    assert "briefly present the execution plan" not in skill.split("## Rules", 1)[1]


def test_temporary_files_are_scoped_to_run_directory() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "`tmp/<run-id>/`" in skill
    assert "delete only that directory" in skill


def test_run_end_requires_no_reclaimable_worker_terminals() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "ORCA has no command that closes a Run" in skill
    assert "worker-list --run <run-id> --terminal-state reclaimable --json" in skill


def test_each_task_is_created_and_started_in_one_way() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    dispatch_section = skill.split("## 1. Plan and dispatch", 1)[1].split("## 2.", 1)[0]
    assert "create each Task in exactly one way" in dispatch_section
    assert "**Independent Task**" in dispatch_section
    assert 'worker-start --spec "<brief>" --task-title' in dispatch_section
    assert "**Dependent Task**" in dispatch_section
    assert "task-create --spec \"<brief>\"" in dispatch_section
    assert "--deps '<json_array>'" in dispatch_section
    assert "worker-start --task <task_id>" in dispatch_section
    assert "Never create a Task you will not start." in dispatch_section
    assert "one Task per Issue by default. Then," not in skill


def test_concurrency_limit_comes_from_max_workers() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    dispatch_section = skill.split("## 1. Plan and dispatch", 1)[1].split("## 2.", 1)[0]
    assert "effort, and `MAX_WORKERS` from step 0" in dispatch_section
    assert "**`MAX_WORKERS` workers running concurrently**" in dispatch_section
    assert "Merge-preparation workers\n   count toward this limit" in dispatch_section
    assert "With `MAX_WORKERS=1`, run fully serially" in dispatch_section
    assert "3 workers running concurrently" not in skill
    assert "pass\n`--max-workers 1`" in skill


def test_implementation_workers_do_not_sync_with_main() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    worker_step = skill.split("7. Instruct each worker", 1)[1].split("8. ", 1)[0]
    assert "not to rebase onto or merge `origin/main`" in worker_step
    assert "happen once, in merge preparation" in worker_step
    assert "whether the\n     PR conflicts with `main`" in worker_step
    rules = skill.split("## Rules", 1)[1]
    assert "Sync each PR with `main` only in merge preparation." in rules
    assert "never tells\n  a worker still implementing to rebase" in rules
