"""Tests that SKILL.md keeps the quota pause procedure in its reference.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL_MD = SKILL_DIR / "SKILL.md"
WAITING = SKILL_DIR / "references" / "waiting.md"
REVIEW_RETRY = SKILL_DIR / "references" / "review-quota-retry.md"
QUOTA_GUARD_MD = SKILL_DIR.parent / "quota-guard" / "SKILL.md"
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
    merge_prep_step = skill.split("13. When a worker slot is free", 1)[1].split("14. ", 1)[0]
    assert "`start_worker.py`" in merge_prep_step
    assert ('`--spec "<handoff>" --task-title "#<issue> PR #<pr> merge prep" '
            "--worktree branch:<branch> --agent <agent> --model <merge-model> "
            "--effort <merge-effort>`") in merge_prep_step
    assert "do not pass `--task <task_id>`" in merge_prep_step


def test_findings_status_and_followup_candidates() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    common = skill.split("### Common verification conditions", 1)[1].split("### Merge sequence", 1)[0]
    for text in ("review-latest-findings: must=0 optional=<n>", "consistent with the worker handoff",
                 "review-latest-findings: unknown", "read only the latest review body",
                 "review-latest-findings: none", "do not merge"):
        assert text in common
    step17 = skill.split("17. Mark", 1)[1].split("## Quota control", 1)[0]
    for text in ("`follow-up candidates:`", "**起票候補**", "summary and review comment URL",
                 "Do not create Issues", "user decides"):
        assert text in step17


def test_merge_prep_skipped_when_pr_is_already_ready() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    common = skill.split("### Common verification conditions", 1)[1].split("### Merge sequence", 1)[0]
    shortcut = skill.split("12. Select the next PR", 1)[1].split("13. When", 1)[0]
    verify = skill.split("14. Independently verify", 1)[1].split("15. Merge", 1)[0]
    assert "Skip step 13 and go straight to step 14" in shortcut
    for step in (shortcut, verify):
        assert "**Common verification conditions** above" in step
    for command in ("git fetch --prune origin",
                    "git merge-base --is-ancestor origin/main origin/<branch>",
                    "gh pr checks <pr>"):
        assert command in common
        for step in (shortcut, verify):
            assert command not in step
    assert "exits `0`" in common
    assert "even when no required checks" in common
    assert "Exit `8` means pending" in common
    assert "inspect any other non-zero result" in common
    assert "report monitoring errors as blockers" in common
    assert "instead of treating them as\n  pending" in common
    assert "An empty check set is not proof of success" in common
    assert "review-latest-findings: must=0 optional=<n>" in common
    assert "consistent with the worker handoff" in common
    assert "If CI is empty, pending, or has a monitoring error, do not take" in shortcut
    assert "rebase exception" not in shortcut
    assert "Required tests have passed on the current PR commit" in verify
    assert "gh pr checks <pr> --required" not in skill


def test_worker_messages_go_to_dispatch() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "## Messaging workers" in skill
    assert "<orca> orchestration send --to dispatch:<dispatch_id>" in skill
    assert "A bare `--to ctx_…` fails with" in skill
    assert "<terminalHandle>" not in skill
    reference = QUOTA_PAUSE.read_text(encoding="utf-8")
    assert reference.count("send --to dispatch:<dispatch_id>") == 2
    assert "<terminalHandle>" not in reference


def test_skill_md_freezes_skill_checkout_during_run() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "`skill-checkout: <path>`" in skill
    assert "Never update" in skill
    step0 = skill.split("## 0. Check preconditions", 1)[1].split("## 1. Plan", 1)[0]
    assert "uv run --no-project <skill-dir>/scripts/local_main.py freeze" in step0
    assert "`skill-checkout-frozen: <sha|no>`" in step0
    assert "record that value in the checkpoint" in step0
    assert "Only `local_main.py freeze` and `finish` (step 17) may" in step0
    assert "Orca fast-forwards the local `main`" in step0


def test_run_end_restores_pin_and_fast_forwards_local_main_last() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step = skill.split("17. Mark only confirmed merged Issues", 1)[1].split("## Quota control", 1)[0]
    step = " ".join(step.split())
    assert "update that checkout" not in step
    finish = "uv run --no-project <skill-dir>/scripts/local_main.py finish --frozen <sha|no>"
    assert finish in step
    assert step.index("clear-checkpoint") < step.index(finish)
    assert "`skill-checkout-frozen:` value before running `cleanup_run.py`" in step
    assert "`local-main:`" in step
    assert "report the `error:` line and the same `finish` command to the user" in step
    waiting = WAITING.read_text(encoding="utf-8")
    section = waiting.split("## Checkpoint", 1)[1].split("\n## ", 1)[0]
    assert "`skill-checkout-frozen: <sha|no>`" in section


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
    assert "Never grep the JSON output to decide READY" in skill
    assert "grep -o" not in skill


def test_blocked_states_told_apart_by_json_state() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "**Tell blocked states apart by JSON:**" in skill
    assert "PowerShell\n  `-Command`" in skill
    assert "exits `0` only on\n  READY" in skill
    assert "without a parseable `state` counts as UNKNOWN" in skill
    for stale in ("`10` on PAUSED_QUOTA", "`20` on UNKNOWN", "any\nother exit code"):
        assert stale not in skill


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


def test_overlapping_tasks_rule_and_plan() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    overlap_step = skill.split("3. Identify dependencies", 1)[1].split("4. Create one", 1)[0]
    assert "**Same part of the same file**" in overlap_step
    assert "this as a dependency and run the Tasks in order" in overlap_step
    assert "**Distant parts of the same file only:** run the Tasks in parallel" in overlap_step
    assert "merge preparation (step 13)" in overlap_step
    dag_step = skill.split("5. Represent actual dependencies", 1)[1].split("6. Before", 1)[0]
    assert "same-part overlaps from step 3" in dag_step
    plan_step = skill.split("6. Before the first dispatch", 1)[1].split("## 2.", 1)[0]
    assert "For Tasks that edit the same file" in plan_step
    assert "state that decision and its reason" in plan_step


def test_provider_is_explicit_for_config_workers_and_quota() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "resolve_config.py --agent <agent>" in skill
    assert "Always pass `--agent <agent>`" in skill
    assert "--worktree branch:<branch> --agent <agent>" in skill
    assert "check --provider <agent>" in skill
    assert "Codex skips Claude setup" in skill
    assert "Codex workers use the Claude reviewer" in " ".join(skill.split())
    assert "Workers must not merge or schedule resumption wake-ups" in skill




def test_codex_disallows_implicit_invocation() -> None:
    policy = (SKILL_DIR / "agents/openai.yaml").read_text(encoding="utf-8")
    assert "policy:\n  allow_implicit_invocation: false" in policy


def test_user_questions_are_written_in_full_in_final_message() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    section = skill.split("## Asking the user", 1)[1].split("\n## ", 1)[0]
    assert "both Codex and Claude\nCode Coordinators" in section
    assert "**Write the full question in the final message of the turn.**" in section
    assert "`request_user_input_async`" in section
    for part in ("**Background:**", "**Options:**", "**Recommendation:**", "**Example reply:**"):
        assert part in section
    assert "Explain terms the user may not know" in section
    assert "Ask related pending questions together" in section
    assert "one-line reminder" in section
    assert "**Asking the user**" in WAITING.read_text(encoding="utf-8")


def test_worker_questions_that_change_the_issue_go_to_the_user() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    section = skill.split("### Answering worker questions", 1)[1].split("\n## ", 1)[0]
    text = " ".join(section.split())
    assert "**Within the Issue as written:**" in text
    assert "answer the worker yourself" in text
    assert "**Changes the Issue:**" in text
    assert "drop, add, or weaken a scope item or acceptance criterion" in text
    assert "wait for the user's decision" in text
    assert "**Asking the user**" in text
    assert "acceptance criteria is never routine" in " ".join(skill.split())






def test_guides_and_references_are_read_once_per_run() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    budget = skill.split("## Token budget", 1)[1].split("\n## ", 1)[0]
    assert "**Read each guide or reference at most once per Run:**" in budget
    assert "Never load the same one again through another command" in budget
    assert "no\n  longer in this conversation" in budget
    assert "Do not\n  read `--help` output" in budget


def test_issue_bodies_are_read_only_for_undecidable_overlaps() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    inspect_step = skill.split("2. Inspect only what planning needs", 1)[1].split("3. ", 1)[0]
    assert "Step 3 gives the only exception" in inspect_step
    overlap_step = skill.split("3. Identify dependencies", 1)[1].split("4. Create one", 1)[0]
    assert "only for the Issues involved" in overlap_step
    assert "`gh issue view <n> --json body`), once each" in overlap_step


def test_run_end_cleanup_uses_scripts_only() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step = skill.split("17. Mark only confirmed merged Issues", 1)[1].split("## Quota control", 1)[0]
    assert "<skill-dir>/scripts/cleanup_run.py --run-id <run-id>" in step
    assert ("~/.agents/skills/quota-guard/scripts/quota_guard.py clear-checkpoint "
            "--provider <agent> --operation <run-id>") in step
    for code in ("Exit `0`", "`1`", "`2`"):
        assert code in step
    assert "do not retry with another command" in step
    assert "report the remaining paths to the user" in step
    reference = QUOTA_PAUSE.read_text(encoding="utf-8")
    assert "## Checkpoint lifecycle" in reference
    assert "clear-checkpoint" in reference


def test_docs_do_not_name_quota_guard_storage_paths() -> None:
    for doc in [SKILL_MD, *(SKILL_DIR / "references").glob("*.md")]:
        text = doc.read_text(encoding="utf-8")
        for path in ("quota-guard/checkpoints", ".claude/quota-guard", ".codex/quota-guard"):
            assert path not in text, (doc.name, path)


def test_preconditions_take_orca_and_update_prompt_stops_dispatch() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "check_preconditions.py --orca <selected-executable>" in skill
    assert "--agent <agent> --orca" not in skill
    assert "`-c check_for_update_on_startup=false` to Codex's default arguments" in skill
    assert skill.index("identify this Coordinator's runtime") < skill.index(
        "check_preconditions.py")
    assert "Agent startup blocked: agent-update-prompt" in skill
    assert "Never answer the prompt by\nsending keys to the worker terminal" in skill


def test_review_limit_exception_uses_script_option() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "**Limit reached with unreviewed fix commits:**" in skill
    rule = skill.split("**Limit reached with unreviewed fix commits:**", 1)[1].split("\n- ", 1)[0]
    for option in ("**Merge as is:**", "**One extra review:**", "**Stop:**"):
        assert option in rule
    assert "run_codex_review.sh <pr-number> --extra-review" in rule
    assert "Never edit another skill's config file" in rule
    verify_step = skill.split("14. Independently verify", 1)[1].split("\n- ", 1)[0]
    assert "review-extra: <count>" in verify_step
    assert "`<count>` ≤ `<max>`" not in verify_step
    assert "`4/3` with\n      `review-extra: 1`" in verify_step
    assert "pr-cross-review/config.conf" not in skill


def test_implementation_dispatch_names_new_top_level_worktree() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    dispatch_section = skill.split("## 1. Plan and dispatch", 1)[1].split("## 2.", 1)[0]
    assert ("<start> --worktree new-top-level --name issue-<n> --setup run "
            "--agent <agent> --model <impl-model> --effort <impl-effort>") in dispatch_section
    assert '`--spec "<brief>" --task-title "#<n> <title>"`' in dispatch_section
    assert "Orca keeps a new-worktree worker open" in dispatch_section
    assert "`--worktree new` does not exist" in dispatch_section
    assert "omitting `--name` gives a random name" in dispatch_section


def test_workers_stop_only_their_own_processes_by_pid() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    worker_step = skill.split("7. Instruct each worker", 1)[1].split("8. ", 1)[0]
    assert "stop only processes it started itself, by PID" in worker_step
    assert "never by image name" in worker_step


def test_failed_ci_reruns_once_only_when_unrelated() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    verify_step = skill.split("14. Independently verify", 1)[1].split("15. ", 1)[0]
    rule = verify_step.split("**If a CI check fails:**", 1)[1]
    assert "unrelated to the PR's diff" in rule
    assert "rerun the failed jobs once yourself" in rule
    assert "`gh run rerun <run-id> --failed`" in rule
    assert "or the rerun fails again, do not rerun further" in rule
    assert "suggest an\n      Issue for a test that failed this way more than once" in rule


def all_docs() -> list[Path]:
    return [SKILL_MD, *(SKILL_DIR / "references").glob("*.md")]


def test_old_waiters_and_ack_procedures_are_gone() -> None:
    assert not (SKILL_DIR / "scripts/wait_actionable.py").exists()
    assert not (SKILL_DIR / "scripts/wake_if_actionable.py").exists()
    assert not (SKILL_DIR / "references/codex-waiting.md").exists()
    for doc in all_docs():
        text = doc.read_text(encoding="utf-8")
        for stale in ("wait_actionable", "wake_if_actionable", "codex-waiting",
                      "check --ack", "acknowledge", "Heartbeat-only", "heartbeat-only",
                      "ignore heartbeat", "*/15 * * * *", "safety-minutes", "waiting-mode",
                      "review-retry:<run-id>:<pr>", "Get-Command orca", "command -v orca",
                      "--interval 30"):
            assert stale not in text, (doc.name, stale)


def test_cli_is_selected_once_and_used_by_absolute_path() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step0 = skill.split("## 0.", 1)[1].split("## 1.", 1)[0]
    assert "check_preconditions.py --orca <selected-executable>" in step0
    for selector in ("ORCA_CLI_COMMAND", "orca-dev", "ORCA_DEV_REPO_ROOT", "orca-ide"):
        assert selector in step0
    assert "`orca-executable: <path>`" in step0
    assert "never select\nthe executable again" in step0
    assert "do not try another Orca\nexecutable" in step0
    assert "orchestration.worker-auto-release.v1" in step0
    assert "outside the sandbox" in step0
    for doc in all_docs():
        text = doc.read_text(encoding="utf-8")
        assert re.search(r"`orca (orchestration|automations|skills|terminal)", text) is None, \
            doc.name


def test_guide_and_dag_reference_are_read_before_use() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step0 = skill.split("## 0.", 1)[1].split("## 1.", 1)[0]
    assert "`<orca> skills get orchestration`" in step0
    assert ("`<orca> skills get orchestration --reference references/coordinator-loop.md`"
            in step0)
    assert "Do **not** use `--full`" in step0


def test_workers_start_through_detailed_receipt_classifier() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    section = skill.split("### Starting workers", 1)[1].split("## 1.", 1)[0]
    flat = " ".join(section.split())
    assert "<skill-dir>/scripts/start_worker.py --orca <orca> -- <worker-start arguments>" \
        in section
    assert "`worker-start ... --json --full`" in flat
    assert "not by `worker-start`'s exit code" in flat
    for code in ("- `0` ready", "- `3` unobserved", "- `1` failed", "- `2` invalid",
                 "- `4` launch mismatch"):
        assert code in section
    assert "do not rerun" in section
    assert "never route around the breaker" in flat.lower()
    assert "record the dispatch ID in the checkpoint at once" in flat


def test_worker_list_reads_every_detailed_page() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step = skill.split("10. Track each Task", 1)[1].split("11. ", 1)[0]
    flat = " ".join(step.split())
    assert "<skill-dir>/scripts/list_workers.py --orca <orca> --run <run-id>" in step
    assert "`worker-list --json --full` page by page" in flat
    assert 'never read it as "no workers"' in flat
    assert "a failed `worker_done` is never a completed Task" in flat


def test_auto_released_and_kept_open_workers_are_told_apart() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step = " ".join(skill.split("11. Workers in an existing", 1)[1].split("## 3.", 1)[0].split())
    assert "close on their own after `worker_done` (`autoReleaseAt`); do not release them" in step
    assert "new top-level worktree, which Orca keeps open" in step
    assert "`worker-release --dispatch <dispatch_id>`" in step
    assert "`release_pending` or `release_unknown`" in step
    assert "Never release a worker the user kept open or took over" in step


def test_run_end_reconciles_every_worker() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step = " ".join(skill.split("17. Mark only confirmed", 1)[1].split("## Quota control", 1)[0]
                    .split())
    assert "ORCA has no command that closes a Run" in step
    assert "Run `list_workers.py` (step 10) for the whole Run" in step
    assert "`release_pending` / `release_unknown`" in step
    assert "`stop_unknown`" in step
    assert "intentionally retained" in step
    assert "Do not report the Run complete while a release or an unknown state remains" in step


def test_waiting_ends_turn_and_receives_without_ack() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    section = skill.split("## Waiting", 1)[1].split("\n## ", 1)[0]
    assert "[Waiting](references/waiting.md) in both Claude Code and Codex" in section
    assert "there is no `--ack` step" in section
    waiting = WAITING.read_text(encoding="utf-8")
    receive = " ".join(waiting.split("## Receive messages", 1)[1].split("\n## ", 1)[0].split())
    for rule in ("carries the whole message: act on it",
                 "names a `check` command: run exactly that command",
                 "marks the batch it returns as read; there is no `--ack` step",
                 "Process every row of that batch before the next `check`",
                 "never treat it as succeeded",
                 "<orca> orchestration reply --id <message-id>",
                 "`escalation` with `stopReason`",
                 "Do not assume how often they arrive",
                 "`--retry-request <id>`",
                 "<orca> orchestration inbox --terminal run:<run-id> --limit 50",
                 "add `--full` only when a preview cuts off",
                 "Mail being read does not mean it was processed"):
        assert rule in receive, rule
    end = " ".join(waiting.split("## Wait by ending the turn", 1)[1].split("\n## ", 1)[0].split())
    for rule in ("end the turn", "No waiter, watcher, or polling script",
                 "no `check --wait`", "No `gh pr checks --watch`",
                 "wait for a worker message or a user answer"):
        assert rule in end, rule


def test_resume_reconciles_once_without_duplicate_dispatch() -> None:
    waiting = WAITING.read_text(encoding="utf-8")
    resume = " ".join(waiting.split("## On every resume", 1)[1].split("\n## ", 1)[0].split())
    assert resume.index("follow `quota-pause.md` first") < resume.index("Run `<quota-check>`")
    assert "Never repeat a dispatch, phase, or merge" in resume
    assert "a second wake for the same event is not a new event" in resume
    assert ("A missing notification, silence, a timeout, or `unverifiable` liveness alone is "
            "never a reason to stop, retry, abandon, or release a worker") in resume
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    assert "check the checkpoint and live state for a dispatch already started" in skill


def test_timed_wake_ups_are_limited_and_exclusive() -> None:
    waiting = WAITING.read_text(encoding="utf-8")
    section = " ".join(waiting.split("## Timed wake-ups", 1)[1].split("\n## ", 1)[0].split())
    assert "Only these times get a reservation" in section
    assert ("Keep **at most one** future reservation per Run, at the earliest `wake-at:` time"
            in section)
    assert "`quota-guard:<run-id>` (from `quota-pause.md`) is the only reservation" in section
    assert "remove `coordinator-wait:<run-id>` first" in section
    assert "If removal fails, resolve that before creating another" in section
    assert "Never touch another Run's reservations" in section
    assert "one-shot (`recurring: false`) `CronCreate`" in section
    assert "do not use `CronCreate` / `CronList`" in section
    assert 'quota_guard.py" wake --orca "<orca>" --terminal "<handle>"' in section
    assert "recurs every year" in section
    pause = QUOTA_PAUSE.read_text(encoding="utf-8")
    flat_pause = " ".join(pause.split())
    assert "first remove the Run's `coordinator-wait:<run-id>`" in flat_pause
    assert "Do not create a `coordinator-wait` reservation while paused" in flat_pause
    assert "remove the recorded quota automation first" in flat_pause
    assert "Do not use `CronCreate` / `CronList` in Codex" in flat_pause


def test_ci_pending_uses_one_shot_reservation_with_deadline() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    verify = " ".join(skill.split("14. Independently verify", 1)[1].split("15. ", 1)[0].split())
    assert "**Pending CI** in [Waiting](references/waiting.md) in both Claude Code and Codex" \
        in verify
    assert "Never run `gh pr checks --watch`" in verify
    assert "gh pr checks <pr> --watch" not in skill
    waiting = WAITING.read_text(encoding="utf-8")
    ci = " ".join(waiting.split("## Pending CI", 1)[1].split("\n## ", 1)[0].split())
    assert "absolute deadline 30 minutes after the first pending observation" in ci
    assert "the earlier of 15 minutes from now and the deadline" in ci
    assert "never reset the deadline" in ci
    assert "`monitor-error: CI deadline exceeded`" in ci
    assert "an empty check set is not success" in ci


def test_review_retry_shares_the_runs_reservation() -> None:
    retry = " ".join(REVIEW_RETRY.read_text(encoding="utf-8").split())
    assert "do not create a separate wake-up" in retry
    assert "**Timed wake-ups** in [Waiting](waiting.md)" in retry
    assert "`wake-at:` line" in retry
    assert "`start_worker.py`" in retry
    assert "Remove the retry time's `wake-at:` line" in retry
    assert "`review-quota-retry.md`" in WAITING.read_text(encoding="utf-8")


def test_checkpoint_holds_resume_state() -> None:
    waiting = WAITING.read_text(encoding="utf-8")
    section = " ".join(waiting.split("## Checkpoint", 1)[1].split("\n## ", 1)[0].split())
    for item in ("Run ID, Coordinator terminal handle, agent, absolute `<orca>` path",
                 "dispatch ID, worktree, branch, PR URL, review count",
                 "IDs of the messages already processed",
                 "head SHA, and absolute deadline",
                 "`wake-at: <ISO-8601 time with offset> <reason>`",
                 "`reservation: <id> <time>` or `reservation: none`"):
        assert item in section, item


def test_token_budget_defers_to_common_receive_rules() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    budget = skill.split("## Token budget", 1)[1].split("\n## ", 1)[0]
    flat = " ".join(budget.split())
    assert "**Receive messages** in [Waiting](references/waiting.md)" in flat
    assert "Do not assume how often heartbeats arrive or what they say" in flat
    for stale in ("ignore heartbeat", "ACK", "acknowledge", "**Codex:**", "**Claude Code:"):
        assert stale not in budget


def test_quota_guard_documents_wake_contract() -> None:
    quota = " ".join(QUOTA_GUARD_MD.read_text(encoding="utf-8").split())
    assert "wake --orca <absolute-orca-executable> --terminal <handle> --text <text>`" in quota
    assert "always exits `1`" in quota
    assert "exit `2` means invalid arguments" in quota
    assert "orca-issue-coordinator" not in quota


def test_merge_requires_latest_review_to_cover_head() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    head_check = "`gh pr view <pr> --json headRefOid --jq .headRefOid`"
    common = skill.split("### Common verification conditions", 1)[1].split("### Merge sequence", 1)[0]
    assert "`review-latest-commit: <sha>`" in common
    assert "bash ~/.agents/skills/pr-cross-review/scripts/review_status.sh <pr-number>" in common
    assert head_check in common
    assert "**Merge as is** (Run checkpoint)" in common
    assert "that approval applies only to that SHA" in common
    assert "Do not read review comment bodies for this comparison" in common
    assert "**Unreviewed head**" in common
    shortcut_step = skill.split("12. Select the next PR", 1)[1].split("13. When", 1)[0]
    assert head_check not in shortcut_step
    assert "**Unreviewed head:**" in shortcut_step
    assert "do not take this shortcut: run step 13" in shortcut_step
    verify_step = skill.split("14. Independently verify", 1)[1].split("15. ", 1)[0]
    assert head_check not in verify_step
    assert "use the same `review_status.sh` output" in verify_step
    assert "`review-latest-commit`" in verify_step
    assert "`none`\n      or `mechanical` resolution" in verify_step
    assert "its head before the rebase equals" in verify_step
    assert "`review-latest-commit` or the head approved with **Merge as is**" in verify_step
    assert "its head after the rebase equals the current\n      head" in verify_step
    assert "Only if the merge-preparation worker reported a `newly written`" in verify_step
    assert "a cross-review ran after it with no unresolved must findings" in verify_step
    assert "start merge preparation\n      (step 13)" in verify_step
    for step in (shortcut_step, verify_step):
        assert "**Limit reached with unreviewed fix commits**" in step
    merge_prep_step = skill.split("13. When a worker slot is free", 1)[1].split("14. ", 1)[0]
    assert "run cross-review on the unreviewed commits" in merge_prep_step
    assert "head before the rebase and after it" in merge_prep_step


def test_merge_as_is_approval_covers_only_the_approved_head() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    rule = skill.split("**Limit reached with unreviewed fix commits:**", 1)[1].split("\n- ", 1)[0]
    merge_as_is = rule.split("**Merge as is:**", 1)[1].split("**One extra review:**", 1)[0]
    assert "record the approved head (full SHA) in the Run" in merge_as_is
    assert "approved\n    merging that head without a further review" in merge_as_is
    common = skill.split("### Common verification conditions", 1)[1].split("### Merge sequence", 1)[0]
    assert "**Merge as is**" in common
    assert "that approval applies only to that SHA" in common
    for step_start, step_end in (("12. Select the next PR", "13. When"),
                                 ("14. Independently verify", "15. Merge")):
        step = skill.split(step_start, 1)[1].split(step_end, 1)[0]
        assert "**Common verification conditions** above" in step
    handoff = skill.split("13. When a worker slot is free", 1)[1].split("14. Independently", 1)[0]
    assert "**Merge as is**" in handoff
    assert "that head, and that the user approved merging it" in handoff


def test_quota_paused_worker_resume_is_chosen_by_context_size() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    reference = " ".join(QUOTA_PAUSE.read_text(encoding="utf-8").split())
    assert "FRESH_WORKER_CONTEXT_TOKENS" in skill
    assert "--fresh-worker-context-tokens" in skill
    assert "Do not release a worker that reported `worker-quota-paused:`" in skill
    assert "## Worker stopped by the quota pause" in reference
    for text in ("worker-keep-open --dispatch <dispatch_id>",
                 "at or above the threshold, or `unknown`",
                 "--task <task_id> --retry-of <dispatch_id> --worktree branch:<branch> "
                 "--terminal <handle>",
                 "--task <task_id> --retry-of <dispatch_id> --worktree branch:<branch> "
                 "--agent <agent> --model <model> --effort <effort>",
                 "Do not create a new Task with `--spec`"):
        assert text in reference
    assert "FRESH_WORKER_CONTEXT_TOKENS=200000" in (
        SKILL_DIR / "config.conf.example").read_text(encoding="utf-8")


def test_workers_never_create_reservations_at_quota_pause() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    assert "Workers never create wake-ups." in skill
    worker = " ".join((SKILL_DIR.parent / "implement-review-merge" / "SKILL.md")
                      .read_text(encoding="utf-8").split())
    assert "retry, or schedule a wake-up; the Coordinator resumes the work" in worker


def test_usage_limit_worker_is_retried_by_fresh_worker() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    reference = " ".join(QUOTA_PAUSE.read_text(encoding="utf-8").split())
    waiting = " ".join(WAITING.read_text(encoding="utf-8").split())
    assert "`failureKind=usageLimitReached`" in skill
    assert "## Worker stopped by the usage limit" in reference
    assert "## Handoff to a retried worker" in reference
    for text in ("worker-stop --dispatch <dispatch_id>",
                 "recovery-and-cleanup.md",
                 "Treat the dispatch as stopped only on a confirmed stopped result",
                 "On `stop_unknown`",
                 "silence or `unverifiable` liveness alone still never authorizes a stop",
                 "including every `usageLimitReached` worker",
                 "start it only after its old dispatch has settled",
                 "review count (the larger of the recorded and printed counts)",
                 "unresolved must findings from the latest review",
                 "orchestration reply --id <message-id>",
                 "or only uncommitted changes",
                 "A stopped Merge preparation worker is not retried with `--retry-of`",
                 "with that handoff as its `--spec`",
                 "Never run two workers on one Task or PR"):
        assert text in reference
    assert ("without `worker_done` and without a `usageLimitReached` escalation"
            in reference)
    assert "`failureKind=usageLimitReached`" in waiting
    assert "Do not steer it with `send`" in waiting
    assert "**Handoff to a retried worker**" in waiting
    # Silence or unverifiable liveness alone still never stops a worker.
    assert "`unverifiable` liveness alone is never a reason to stop" in waiting


def test_execution_order_rules_live_in_plan_and_dispatch() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    dispatch_section = skill.split("## 1. Plan and dispatch", 1)[1].split("## 2.", 1)[0]
    assert "**Listed Issues**" in dispatch_section
    assert "not their order" in dispatch_section
    assert "if #1 depends on #3, #3's PR is merged before\n     #1 starts" in dispatch_section
    assert "**Explicit order**" in dispatch_section
    assert "ask the user for the order\n     before the first dispatch" in dispatch_section
    assert "unless step 3 requires asking for the order" in dispatch_section
    assert "only then dispatch the\n   next Issue" in dispatch_section
