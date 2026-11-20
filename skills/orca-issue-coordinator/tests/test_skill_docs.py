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
    merge_prep_step = skill.split("13. When a merge-preparation worker slot is free", 1)[1].split("14. ", 1)[0]
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
    for text in ("`follow-up candidates:`", "**起票候補**",
                 "for a review suggestion, its summary and review comment URL",
                 "for a `local test failure:` item (no review comment URL), its line as reported",
                 "Do not create Issues", "user decides"):
        assert text in step17


def test_step17_aggregates_local_test_failures_with_ci_reruns() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    step17 = skill.split("17. Mark", 1)[1].split("## Quota control", 1)[0]
    for text in ("Merge `local test failure:` items with the same test ID into one entry",
                 "the count and the Issue numbers it came from",
                 "every CI rerun of the same test ID recorded in step 14 (`ci-reruns:`)",
                 "a rerun test with no such report gets its own entry",
                 'whose total is two or more with "suggest filing an Issue"',
                 "still list entries with a total of one"):
        assert text in step17
    assert "more than once" not in step17
    waiting = " ".join(WAITING.read_text(encoding="utf-8").split())
    per_task = waiting.split("- Per Task:", 1)[1].split("- Pending CI:", 1)[0]
    for text in ("`follow-up candidates:` from each handoff, unchanged",
                 "`ci-reruns: <test ID> x<count> ...`", "`ci-reruns: none`"):
        assert text in per_task


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
    assert "Exit `8` or an empty check set means pending" in common
    assert "Inspect any other non-zero result" in common
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


def test_concurrency_limits_are_per_phase() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    flat = " ".join(skill.split())
    dispatch_section = " ".join(
        skill.split("## 1. Plan and dispatch", 1)[1].split("## 2.", 1)[0].split())
    assert ("`MAX_IMPL_WORKERS`, `MAX_MERGE_WORKERS`, and whether the serial mode is on"
            " from step 0") in dispatch_section
    assert ("**`MAX_IMPL_WORKERS` implementation workers running concurrently**"
            in dispatch_section)
    assert "Merge-preparation workers do not count toward this limit" in dispatch_section
    assert "With `serial: true`, run fully serially" in dispatch_section
    assert "The two limits are independent" in flat
    assert "the other phase's workers do not count" in flat
    assert ("If the user explicitly asks to run the Issues serially (one at a time),"
            " pass `--serial`") in flat
    assert ("When a merge-preparation worker slot is free (within `MAX_MERGE_WORKERS`;"
            " implementation workers do not count)") in flat
    for path in [SKILL_MD, *SKILL_MD.parent.joinpath("references").glob("*.md")]:
        text = path.read_text(encoding="utf-8")
        assert "MAX_" + "WORKERS" not in text, path
        assert "--max-" + "workers" not in text, path


def test_implementation_workers_do_not_sync_with_main() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    worker_step = skill.split("7. Instruct each worker", 1)[1].split("8. ", 1)[0]
    assert "not to rebase onto or merge `origin/main`" in worker_step
    assert "happen once, in merge preparation" in worker_step
    assert "whether the\n     PR conflicts with `main`" in worker_step
    rules = skill.split("## Rules", 1)[1]
    assert "Sync each PR with `main` only in merge preparation." in rules
    assert "never tells\n  a worker still implementing to rebase" in rules


def test_main_moves_without_messaging_workers() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    rules = " ".join(skill.split("## Rules", 1)[1].split())
    assert (
        "When `main` moves (e.g. after merging another PR), send no message asking for a "
        "rebase or re-sync to any worker, whether in Implementation or Merge preparation"
    ) in rules
    assert "Its PR is judged after its `worker_done`, in step 14." in rules
    assert "start a new merge preparation (step 13) for it" in rules


def test_no_send_to_finished_dispatch() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    messaging = " ".join(
        skill.split("## Messaging workers", 1)[1].split("### Answering worker questions", 1)[0].split()
    )
    assert "Never `send` to a Dispatch that already sent `worker_done`." in messaging
    assert "Orca treats such a message as a follow-up" in messaging
    assert "bypasses `start_worker.py`, the quota check, and the worker limits" in messaging
    assert "Use `send` only for a worker still working its Dispatch" in messaging
    assert "follow-ups" not in messaging


def test_functional_dependencies_and_orderings_are_separate() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    step3 = skill.split("3. Create one Orchestration Run", 1)[1].split("4. Before creating any Task", 1)[0]
    for phrase in ("**Functional dependency:**", "\"depends on\"", "\"blocked by\"",
                   "relies on code, an API, a configuration, or data",
                   "only after the earlier PR is **merged**", "**Ordering:**",
                   "same part of the same file", "still unclear after reading the Issue bodies",
                   "Do not record it in the DAG",
                   "**Distant parts of the same file only:** run the Tasks in parallel",
                   "merge preparation (step 13)"):
        assert phrase in step3
    step5 = skill.split("5. Represent only functional dependencies", 1)[1].split("6. Before", 1)[0]
    for phrase in ("(`--deps`)", "An ordered Task", "Independent Task (step 4, `--spec`)",
                   "from the latest `origin/main`", "the earlier PR is merged",
                   "waiting for the user's decision or held by the user's choice"):
        assert phrase in step5
    plan_step = skill.split("6. Before the first dispatch", 1)[1].split("## 2.", 1)[0]
    assert "functional dependencies, orderings, and **Last** Issues (listed separately)" in plan_step
    assert "For each ordering, state the reason" in plan_step
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


def test_unmet_criteria_leave_a_draft_comment_before_merge_without_asking() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    section = skill.split("### Unmet or unverified acceptance criteria", 1)[1].split("## Asking the user", 1)[0]
    for phrase in ("every Implementation or Merge preparation `worker_done`",
                   "`unmet/unverified acceptance criteria:` in the handoff",
                   "do not open Issue bodies", "field is missing, ask the worker",
                   "never infer `none` from success or a clean review",
                   "latest of the Implementation and Merge preparation handoffs",
                   "do not ask the user and do not stop the Run",
                   "right before the merge (step 15)",
                   "Write one draft comment on the original Issue",
                   "## 起票候補（下書き）", "PR #<pr> でマージ", "起票はしていません",
                   "- **概要**：", "- **起票を提案した理由**：",
                   "Record the comment URL, the criteria, the reasons, and the merge-target head (full SHA)",
                   "in the Run checkpoint, then merge", "Keep `Closes #<issue>`",
                   "do not change it to `Refs`",
                   "comment cannot be confirmed, do not merge",
                   "Never create an Issue for the remaining criteria",
                   "never let a worker create one",
                   "File an Issue only when the user instructs it",
                   "reuse the comment recorded in the checkpoint",
                   "references the same PR before writing one",
                   "Never write a duplicate",
                   "Never decide on your own that a criterion is unnecessary",
                   "never merge without the draft comment"):
        assert phrase in section
    for phrase in ("Hold the PR", "approved head", "Provide the missing value",
                   "Ask the user before merging", "Create a split"):
        assert phrase not in section
    common = skill.split("### Common verification conditions", 1)[1].split("### Merge sequence", 1)[0]
    assert "`unmet/unverified acceptance criteria:` is `none`, or the draft comment" in common
    assert "missing field is not `none`" in common
    assert "user explicitly approved" not in common
    handoff = skill.split("13. When a merge-preparation worker slot is free", 1)[1].split("14. Independently", 1)[0]
    assert ("`unmet/unverified acceptance criteria:`, and `restated acceptance criteria:` "
            "from the Implementation handoff.") in handoff
    assert "user decision" not in handoff
    step15 = skill.split("15. Merge the PR yourself", 1)[1].split("16. ", 1)[0]
    assert "first write the draft comment" in step15
    step16 = skill.split("16. After each merge", 1)[1].split("17. ", 1)[0]
    step17 = skill.split("17. Mark only confirmed", 1)[1].split("## Quota control", 1)[0]
    for step in (step16, step17):
        assert "**起票候補**" in step
        assert "the summary, the reasons for proposing an Issue, and the draft comment URL" in step
        assert "Do not ask whether to file" in step
    assert "closed by the merge" in step17
    assert "file only what the user instructs" in step17
    waiting = " ".join(WAITING.read_text(encoding="utf-8").split())
    assert "**Unmet or unverified acceptance criteria** before any merge decision" in waiting
    assert "`unmet/unverified acceptance criteria:` with reasons" in waiting
    assert ("any draft comment for remaining criteria (comment URL, criteria, reasons, "
            "and merge-target head as a full SHA)") in waiting
    assert "user decision" not in waiting


def test_brief_never_relaxes_the_issue_scale() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    step7 = skill.split("7. Instruct each worker", 1)[1].split("8. ", 1)[0]
    for phrase in ("Add only what the Issue requires, such as the E2E suite or the benchmark scale it needs",
                   "Never write a smaller scale than the Issue requires",
                   "any instruction that relaxes the Issue's conditions",
                   "left to the worker's **Token budget**"):
        assert phrase in step7
    assert "limits specific to the Issue" not in step7


def test_no_split_off_wording_remains() -> None:
    skills = SKILL_MD.parents[1]
    for path in skills.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".py"}:
            assert "split" + "-off" not in path.read_text(encoding="utf-8").lower(), path


def test_waiting_for_the_user_keeps_independent_tasks_going() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    section = skill.split("## Asking the user", 1)[1].split("## Waiting", 1)[0]
    for phrase in ("**Keep other work going while waiting.**", "While any question is unanswered",
                   "do not functionally depend on the affected PR", "within `MAX_IMPL_WORKERS` / `MAX_MERGE_WORKERS`",
                   "not while it is PAUSED_QUOTA or UNKNOWN", "an ordered Task may start"):
        assert phrase in section


def test_guides_and_references_are_read_once_per_run() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    budget = skill.split("## Token budget", 1)[1].split("\n## ", 1)[0]
    assert "**Read each guide or reference at most once per Run:**" in budget
    assert "Never load the same one again through another command" in budget
    assert "no\n  longer in this conversation" in budget
    assert "Do not\n  read `--help` output" in budget


def test_issue_bodies_are_read_only_when_pre_dispatch_check_is_off() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    inspect_step = " ".join(
        skill.split("2. Inspect only what planning needs", 1)[1].split("3. ", 1)[0].split())
    assert "Do not read full Issue bodies or investigate code" in inspect_step
    assert "Only with `PRE_DISPATCH_CHECK: false` does step 3 give an exception" in inspect_step
    overlap_step = skill.split("3. Create one Orchestration Run", 1)[1].split("4. Before creating any Task", 1)[0]
    on = " ".join(overlap_step.split("**`PRE_DISPATCH_CHECK: true`:**", 1)[1]
                  .split("**`PRE_DISPATCH_CHECK: false`:**", 1)[0].split())
    assert "do not open Issue bodies or investigate code yourself" in on
    assert "gh issue view" not in on
    off = " ".join(overlap_step.split("**`PRE_DISPATCH_CHECK: false`:**", 1)[1]
                   .split("Classify each relation", 1)[0].split())
    assert "only for the Issues involved" in off
    assert "`gh issue view <n> --json body`), once each" in off


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
    flat = " ".join(rule.split())
    assert "record the rerun and the test ID in the Task's `ci-reruns:` checkpoint line" in flat
    assert "counts it with the `local test failure:` reports of the same test" in flat
    assert "more than once" not in rule


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
    assert "never select the executable again" in " ".join(step0.split())
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
    assert "never close the terminal another way" in step
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
    assert ("Do not report the Run complete while a release or an unknown state other than "
            "an unfound-terminal release remains") in step


def _step11(skill: str) -> str:
    return _flat_step(skill, "11. Workers in an existing", "## 3.")


def _step17(skill: str) -> str:
    return _flat_step(skill, "17. Mark only confirmed", "## Quota control")


def test_unfound_terminal_release_is_retried_once_and_recorded_mid_run() -> None:
    step = _step11(SKILL_MD.read_text(encoding="utf-8"))
    definition = step.split("An **unfound-terminal release** is", 1)[1].split(". ", 1)[0]
    for condition in ("`state` `succeeded` or `failed`", "`terminalState` `release_unknown`",
                      "`liveness` `unverifiable`", "`list_workers.py` row"):
        assert condition in definition, condition
    assert "never by the receipt's `lastError` text" in step
    assert step.index("`worker-show --dispatch <dispatch_id> --json` once") < step.index(
        "retry `worker-release` exactly once with a fresh request ID (without `--retry-request`)")
    assert "do not retry again" in step
    assert ("`unreleased: <dispatch_id> <absolute worktree path> (terminal not found)` on that "
            "Task's checkpoint entry") in step
    assert "keep the Run going" in step
    assert "state it in one line in that turn's final message" in step
    waiting = WAITING.read_text(encoding="utf-8")
    checkpoint = " ".join(waiting.split("## Checkpoint", 1)[1].split("\n## ", 1)[0].split())
    per_task = checkpoint.split("- Per Task:", 1)[1].split(" - ", 1)[0]
    assert "`ci-reruns: <test ID> x<count> ...`" in per_task
    assert ("`unreleased: <dispatch_id> <absolute worktree path> (terminal not found)` for each "
            "unfound-terminal release (`SKILL.md` step 11)") in per_task


def test_run_end_completes_with_unfound_terminal_releases_listed_apart() -> None:
    step = _step17(SKILL_MD.read_text(encoding="utf-8"))
    assert "Run `worker-release` exactly once for each unfound-terminal release" in step
    assert "if it is released, treat it as any released worker" in step
    assert "it does not block the Run's completion" in step
    report = step.split("When only unfound-terminal releases remain", 1)[1].split(
        "Finally delete", 1)[0]
    assert "report the Run complete" in report
    assert "**解放を確かめられなかった worker**, one item per worker" in report
    for item in ("the Issue number", "the dispatch ID", "the absolute worktree path",
                 "the reason (Orca no longer finds the terminal it recorded, so it cannot prove "
                 "the process is gone)",
                 "what the user should do (in the Orca UI, check whether an agent terminal is "
                 "still running in that worktree, and close it if one is)"):
        assert item in report, item


def test_other_unresolved_release_states_still_block_run_completion() -> None:
    step = _step17(SKILL_MD.read_text(encoding="utf-8"))
    assert ("report `release_pending` / `release_unknown` and unresolved `stop_unknown` results "
            "as unresolved blockers, not as done, except an unfound-terminal release (step 11)"
            ) in step
    assert ("Do not report the Run complete while a release or an unknown state other than "
            "an unfound-terminal release remains") in step


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
    assert "`monitor-error: no checks reported`" in ci
    assert "Exit `8` or an empty check set" in ci
    assert "do not ask the user" in ci
    assert "transition between them never resets it" in ci
    common = " ".join(skill.split("### Common verification conditions", 1)[1]
                      .split("### Merge sequence", 1)[0].split())
    assert "Exit `8` or an empty check set means pending" in common
    shortcut = " ".join(skill.split("12. Select", 1)[1].split("13. When", 1)[0].split())
    assert "An empty check set follows **Pending CI**" in shortcut
    assert "empty check set" in verify


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
    for item in ("Run ID, agent, absolute `<orca>` path",
                 "`coordinator-terminal: <handle>`: the Coordinator terminal handle",
                 "dispatch ID, worktree, branch, PR URL, review count",
                 "IDs of the messages already processed",
                 "head SHA, and absolute deadline",
                 "`wake-at: <ISO-8601 time with offset> <reason>`",
                 "`reservation: <id> <time>` or `reservation: none`",
                 "`pre-dispatch-check: running <dispatch-id> | done | skipped (<reason>) | disabled`",
                 "do not run the check again",
                 "find that dispatch with `list_workers.py` instead of starting a second worker",
                 "`awaiting-issue-fix: #<n> ...`",
                 "for removals the user chose for a `spec-gap` (step 6)"):
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
    merge_prep_step = skill.split("13. When a merge-preparation worker slot is free", 1)[1].split("14. ", 1)[0]
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
    handoff = skill.split("13. When a merge-preparation worker slot is free", 1)[1].split("14. Independently", 1)[0]
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
                 "--terminal <worker-terminal>",
                 "--task <task_id> --retry-of <dispatch_id> --worktree branch:<branch> "
                 "--agent <agent> --model <model> --effort <effort>",
                 "Do not create a new Task with `--spec`"):
        assert text in reference
    assert "FRESH_WORKER_CONTEXT_TOKENS=200000" in (
        SKILL_DIR / "config.conf").read_text(encoding="utf-8")


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
    assert "only then\n   dispatch the next Issue" in dispatch_section


def test_merge_command_pins_verified_head_and_handles_failures() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    merge = " ".join(skill.split("15. Merge", 1)[1].split("16. After", 1)[0].split())
    assert "gh pr checks <pr> && gh pr merge <pr> --merge --match-head-commit <sha>" in merge
    assert "full `headRefOid` verified in step 14" in merge
    assert "never use `--squash`, `--rebase`, `--auto`, or `--admin`" in merge
    assert "including pending exit `8`" in merge
    assert "return to step 14's CI handling" in merge
    assert "If `gh pr merge` fails, reread the head" in merge
    assert "gh pr view <pr> --json headRefOid --jq .headRefOid" in merge
    assert "If the head differs from `<sha>`, restart verification from step 14" in merge
    assert "Never retry by removing `--match-head-commit`" in merge
    assert "merely replacing `<sha>` with the new head" in merge
    assert "If the head is unchanged, do not retry: block this PR" in merge
    assert "**Asking the user**" in merge


def test_issue_set_is_fixed_planned_and_restored_from_checkpoint() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    inspect = " ".join(skill.split("2. Inspect", 1)[1].split("3. Create one", 1)[0].split())
    assert "Fix the Run's Issue set at this step" in inspect
    assert 'resolve even "all open Issues" to the Issues open now' in inspect
    assert "when saving the Run checkpoint in step 3" in inspect
    plan = " ".join(skill.split("6. Before", 1)[1].split("## 2.", 1)[0].split())
    assert "the fixed Issue set by number" in plan
    waiting = WAITING.read_text(encoding="utf-8")
    checkpoint = waiting.split("## Checkpoint", 1)[1].split("\n## ", 1)[0]
    assert "`issues: #<n> #<n> ...`" in checkpoint
    assert "only for additions explicitly instructed by the user" in checkpoint
    resume = " ".join(waiting.split("## On every resume", 1)[1].split("\n## ", 1)[0].split())
    assert "Use the checkpoint's `issues:` line as the Run's Issue set" in resume
    assert "never list Issues again to expand that set" in resume


def test_issue_additions_require_explicit_instruction_and_no_provenance_guess() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    rules = " ".join(skill.split("## Rules", 1)[1].split())
    for rule in ("Do not add or dispatch Issues that appear during the Run",
                 "regardless of who created them",
                 "do not ask whether to add them",
                 "an explicit instruction from the user in chat naming Issue numbers",
                 "step 3's dependency/overlap assessment (with",
                 "a new pre-dispatch check worker for the added Issues and every Issue of the "
                 "Run not yet merged) and step 5's DAG rules",
                 "update the checkpoint's `issues:` line before dispatch",
                 "Never treat silence as consent",
                 "only as verified facts: author account and creation time",
                 "Do not infer who requested or why someone created an Issue",
                 "an `app/claude` author does not establish that a worker created it"):
        assert rule in rules, rule
    report = " ".join(skill.split("17. Mark", 1)[1].split("\n## ", 1)[0].split())
    assert "outside this Run's scope, with their numbers and titles" in report


def test_implementation_worker_confirms_ci_and_coordinator_skips_ci_wait() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    brief = " ".join(skill.split("\n7. Instruct each worker", 1)[1].split("\n8. ", 1)[0].split())
    for phrase in ("confirm CI completion (success or failure) on the PR's final head before "
                   "`worker_done`",
                   "never handing off with `CI pending`",
                   "report that head (full SHA) and the CI result",
                   "A failure related to the PR's diff is fixed by the worker",
                   "cross-reviewed within `MAX_REVIEWS`",
                   "An unrelated failure", "not fixed or rerun",
                   "failed test names and why it judged them unrelated",
                   "step 14's **If a CI check fails**"):
        assert phrase in brief
    track = " ".join(skill.split("\n10. Track", 1)[1].split("\n11. ", 1)[0].split())
    for phrase in ("CI-verified head and CI result",
                   "without the CI-verified head and CI result is incomplete",
                   "go on to step 12 without reserving a CI wake-up",
                   "When the head changed after the report",
                   "**Pending CI** in [Waiting](references/waiting.md)"):
        assert phrase in track
    assert "**Pending CI** in [Waiting](references/waiting.md) in both Claude Code and Codex" \
        in " ".join(skill.split())


def test_restated_checks_and_auto_decisions_do_not_go_to_the_user() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    section = " ".join(skill.split("### Answering worker questions", 1)[1].split("\n## ", 1)[0].split())
    for phrase in ("**Restating a check:**", "keeping its `Intent:`", "is not **Changes the Issue**",
                   "`restated acceptance criteria:`", "**`[auto]` decisions:**",
                   "was not chosen by the user", "Decide yourself"):
        assert phrase in section
    flat = " ".join(skill.split())
    common = flat.split("### Common verification conditions", 1)[1].split("### Merge sequence", 1)[0]
    for phrase in ("`restated acceptance criteria:`", "A missing field is not `none`",
                   "do not merge; handle it as **Changes the Issue**"):
        assert phrase in common
    assert "except restating a check that keeps the criterion's `Intent:`" in flat
    assert "add one line per restated criterion" in flat
    assert "`restated acceptance criteria:`" in " ".join(WAITING.read_text(encoding="utf-8").split())


PRE_DISPATCH_CHECK = SKILL_DIR / "references" / "pre-dispatch-check.md"
PRE_DISPATCH_CHECK_INSTALLED = "~/.agents/skills/orca-issue-coordinator/references/pre-dispatch-check.md"
REPORT_KINDS = ("functional-dependency", "ordering", "last", "distant-same-file", "implied-change",
                "spec-gap")


def _flat_step(skill: str, start: str, end: str) -> str:
    return " ".join(skill.split(start, 1)[1].split(end, 1)[0].split())


def test_run_is_created_before_relations_are_identified() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step3 = _flat_step(skill, "3. Create one Orchestration Run", "4. Before creating any Task")
    first = step3.split("Then identify dependencies", 1)[0]
    for phrase in ("set up the quota guard with this Run ID", "save the Run checkpoint"):
        assert phrase in first
    step4 = _flat_step(skill, "4. Before creating any Task", "5. Represent")
    assert "Orchestration Run" not in step4
    assert "quota guard" not in step4


def test_pre_dispatch_check_runs_as_an_orca_worker() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step3 = _flat_step(skill, "3. Create one Orchestration Run", "4. Before creating any Task")
    for phrase in ("**`PRE_DISPATCH_CHECK: true`:**", "start one pre-dispatch check worker",
                   "`start_worker.py` (**Starting workers**)",
                   "`<quota-check> && uv run --no-project <skill-dir>/scripts/start_worker.py",
                   '--task-title "pre-dispatch check" --worktree current --agent <agent> '
                   "--model <pre-dispatch-check-model> --effort <pre-dispatch-check-effort>",
                   PRE_DISPATCH_CHECK_INSTALLED,
                   "does not count toward `MAX_IMPL_WORKERS` or `MAX_MERGE_WORKERS`",
                   "`pre-dispatch-check: running <dispatch-id>`",
                   "is not an Implementation or Merge preparation handoff",
                   "`restated acceptance criteria:`", "do not release it",
                   "Classify from its report alone",
                   "Treat a relation the report does not settle as an **Ordering**"):
        assert phrase in step3, phrase
    for kind in REPORT_KINDS:
        assert f"`{kind}`" in step3, kind
    assert "spawn_agent" not in skill
    assert "general-purpose" not in skill


def test_failed_pre_dispatch_check_retries_once_then_asks() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step3 = _flat_step(skill, "3. Create one Orchestration Run", "4. Before creating any Task")
    failure = step3.split("**If it fails:**", 1)[1].split("**`PRE_DISPATCH_CHECK: false`:**", 1)[0]
    for phrase in ("follows the exit codes in **Starting workers**", "`worker-quota-paused:`",
                   "breaks the line format or the 60-line limit",
                   "start one new pre-dispatch check worker (a new Task with `--spec`",
                   "and the same arguments) once", "exit `1`, `2`, or `4`",
                   "ask the user before the first dispatch",
                   "proceed without the pre-dispatch check",
                   "`pre-dispatch-check: skipped (<reason>)`", "stop the Run",
                   "Dispatch nothing until the user replies"):
        assert phrase in failure, phrase


def test_last_issues_wait_for_every_other_merge() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step3 = _flat_step(skill, "3. Create one Orchestration Run", "4. Before creating any Task")
    last = step3.split("**Last:** the Issue", 1)[1]
    for phrase in ("acceptance criterion over the whole repository",
                   "functional dependency on every other Task of the Run",
                   "only after every other PR is **merged**"):
        assert phrase in last, phrase
    step5 = _flat_step(skill, "5. Represent only functional dependencies", "6. Before")
    for phrase in ("A **Last** Task (step 3) is a Dependent Task whose `--deps` lists every "
                   "other Task of the Run",
                   "only after every other PR of the Run has been **merged**"):
        assert phrase in step5, phrase
    step6 = _flat_step(skill, "6. Before the first dispatch", "## 2.")
    assert "orderings, and **Last** Issues (listed separately)" in step6
    assert "the pre-dispatch check state" in step6


def test_spec_gaps_stop_the_whole_run_and_offer_three_choices() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step6 = _flat_step(skill, "6. Before the first dispatch", "## 2.")
    gaps = step6.split("**Specification gaps:**", 1)[1]
    for phrase in ("a change the Issue needs but does not state, with two or more fixes "
                   "consistent with the Issue",
                   "stop the whole Run", "dispatch nothing until the user replies",
                   "**Fix the Issue first:**", "the Issue stays in the Run",
                   "Never edit the Issue yourself", "`awaiting-issue-fix: #<n> ...`",
                   "start a new pre-dispatch check worker (step 3)",
                   "**Dispatch as is:**", "**Remove from the Run:**",
                   "update the checkpoint's `issues:` line"):
        assert phrase in gaps, phrase
    asking = " ".join(skill.split("## Asking the user", 1)[1].split("\n## ", 1)[0].split())
    assert "it holds every dispatch until the user replies" in asking


def test_pre_dispatch_check_reference_defines_report_and_read_only_rules() -> None:
    ref = " ".join(PRE_DISPATCH_CHECK.read_text(encoding="utf-8").split())
    for line in ("functional-dependency: #<earlier> -> #<later> | evidence:",
                 "ordering: #<earlier> -> #<later> | evidence:",
                 "last: #<n> | evidence:",
                 "distant-same-file: #<a> #<b> | evidence:",
                 "implied-change: #<n> | evidence: <path:line ...> | change:",
                 "spec-gap: #<n> | evidence: <path:line ...> | gap:"):
        assert line in ref, line
    for phrase in ("`worker_done`", "at most **60 lines**", "the single line `none`",
                   "`unclear:`", "## Read only", "Change nothing",
                   "`git grep <pattern> origin/HEAD`", "do not read the working tree's files"):
        assert phrase in ref, phrase


def test_coordinator_never_reads_pre_dispatch_check_reference() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    budget = " ".join(skill.split("## Token budget", 1)[1].split("\n## ", 1)[0].split())
    assert "Never read `references/pre-dispatch-check.md`" in budget


def test_resolve_config_output_names_pre_dispatch_check() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    for phrase in ("`--pre-dispatch-check`", "`--pre-dispatch-check-model`",
                   "`--pre-dispatch-check-effort`",
                   "`pre-dispatch-check: <true|false> --model <m> --effort <e>`",
                   "`CLAUDE_PRE_DISPATCH_CHECK_MODEL`", "`CLAUDE_PRE_DISPATCH_CHECK_EFFORT`",
                   "`PRE_DISPATCH_CHECK` (`true` or `false`)"):
        assert phrase in skill, phrase


def test_several_last_issues_are_ordered_by_the_user_before_tasks_exist() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step3 = _flat_step(skill, "3. Create one Orchestration Run", "4. Before creating any Task")
    last = step3.split("**Several Last Issues**", 1)[1]
    for phrase in ("making each depend on the others would leave none startable",
                   "before creating any Task, ask the user", "which to remove from the Run",
                   "Each later **Last** Issue then also depends on the earlier ones"):
        assert phrase in last, phrase
    step5 = _flat_step(skill, "5. Represent only functional dependencies", "6. Before")
    assert "except the **Last** Tasks ordered after it" in step5
    asking = " ".join(skill.split("## Asking the user", 1)[1].split("\n## ", 1)[0].split())
    assert "several **Last** Issues (step 3)" in asking


def test_issue_set_and_dag_are_settled_before_tasks_are_created() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step4 = _flat_step(skill, "4. Before creating any Task", "5. Represent")
    for phrase in ("settle every question that changes the Issue set or the DAG",
                   "a `spec-gap` (step 6) and several **Last** Issues (step 3)",
                   "create Tasks only from the Issue set and relations left after the user's reply",
                   "Do not create the Tasks held by **Fix the Issue first** (step 6) until the "
                   "pre-dispatch check after the fix is settled"):
        assert phrase in step4, phrase
    step6 = _flat_step(skill, "6. Before the first dispatch", "## 2.")
    gaps = step6.split("**Specification gaps:**", 1)[1]
    for phrase in ("create no Task and dispatch nothing until the user replies (step 4)",
                   "Do not create or dispatch its Task",
                   "by holding their dispatch (a created Task keeps its `--deps`)",
                   "Offer it only while none of those Issues has a Task",
                   "offer only the other two choices for an Issue that has a Task"):
        assert phrase in gaps, phrase


def _ref_definition(ref: str, kind: str) -> str:
    return ref.split(f"- `{kind}`:", 1)[1].split(" - ", 1)[0]


def test_pre_dispatch_check_splits_implied_changes_from_spec_gaps() -> None:
    ref = " ".join(PRE_DISPATCH_CHECK.read_text(encoding="utf-8").split())
    implied = _ref_definition(ref, "implied-change")
    for phrase in ("still hard-code the old form of a behavior the Issue explicitly changes",
                   "only one fix is consistent with the Issue",
                   "a test asserts the old list of menu items",
                   "the Issue lists one test import to change",
                   "patch the same private function"):
        assert phrase in implied, phrase
    gap = _ref_definition(ref, "spec-gap")
    for phrase in ("two or more fixes are consistent with the Issue",
                   "renames a configuration key", "migrated or rejected",
                   "When unsure whether only one fix fits, report `spec-gap`"):
        assert phrase in gap, phrase
    for phrase in ("monkeypatch", "import", "private function"):
        assert phrase not in gap, phrase


def test_pre_dispatch_check_drops_implied_changes_after_distant_same_file() -> None:
    ref = " ".join(PRE_DISPATCH_CHECK.read_text(encoding="utf-8").split())
    drop = ref.split("If the findings exceed 60 lines", 1)[1]
    assert "drop `distant-same-file` lines first" in drop
    assert "then `implied-change` lines" in drop
    assert drop.index("`distant-same-file` lines first") < drop.index("then `implied-change` lines")
    assert "Never drop a `functional-dependency`, `ordering`, `last`, or `spec-gap` line" in drop


def test_implied_changes_go_into_the_brief_without_stopping_the_run() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step3 = _flat_step(skill, "3. Create one Orchestration Run", "4. Before creating any Task")
    assert "`implied-change` → a change added to that Issue's brief (steps 6 and 7)" in step3
    assert "Record `pre-dispatch-check: done` and the report lines in the checkpoint" in step3
    step6 = _flat_step(skill, "6. Before the first dispatch", "## 2.")
    plan = step6.split("**Specification gaps:**", 1)[0]
    assert ("For each Issue with an `implied-change`, list each change that its brief adds "
            "(step 7)") in plan
    assert "An `implied-change` alone never stops the Run or waits for approval" in plan
    exception = plan.split("Then start dispatching without waiting for approval,", 1)[1]
    exception = exception.split("`spec-gap`.", 1)[0]
    assert "unless step 3 requires asking for the order" in exception
    assert "implied-change" not in exception
    fix = step6.split("**Fix the Issue first:**", 1)[1].split("**Dispatch as is:**", 1)[0]
    assert ("Add a new `implied-change` only to the briefs of Tasks not yet dispatched; never "
            "send it to a Task already dispatched") in fix
    step7 = _flat_step(skill, "7. Instruct each worker", "8. Fill available")
    assert ("For each `implied-change` the pre-dispatch check reported for the Issue, add the "
            "change and tell the worker to make it as a consequence of the Issue's scope and to "
            "state the change in the PR body") in step7


def _rebind(waiting: str) -> str:
    resume = " ".join(waiting.split("## On every resume", 1)[1].split("\n## ", 1)[0].split())
    return resume.split("1. **Re-bind to this terminal.**", 1)[1].split(
        "2. If the quota is paused", 1)[0]


def test_skill_md_defines_handle_from_preconditions() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    step0 = skill.split("## 0. Check preconditions", 1)[1].split("## 1. Plan and dispatch", 1)[0]
    assert ("prints `skill-checkout: <path>`, `orca-executable: <path>`, and "
            "`coordinator-terminal: <handle>`; keep all three") in step0
    assert ("`<handle>` below is the Coordinator terminal handle: the `coordinator-terminal:` "
            "value, and after the Run is re-bound to a new terminal (**Re-bind to this terminal** "
            "in [Waiting](references/waiting.md)), the checkpoint's `coordinator-terminal:` "
            "value") in step0
    waiting = " ".join(WAITING.read_text(encoding="utf-8").split())
    intro = waiting.split("## Wait by ending the turn", 1)[0]
    assert "`<handle>` is always the checkpoint's `coordinator-terminal:` value" in intro


def test_resume_rebinds_the_run_before_quota_and_messages() -> None:
    waiting = WAITING.read_text(encoding="utf-8")
    resume = " ".join(waiting.split("## On every resume", 1)[1].split("\n## ", 1)[0].split())
    rebind_at = resume.index("**Re-bind to this terminal.**")
    assert rebind_at < resume.index("follow `quota-pause.md` first")
    assert rebind_at < resume.index("Run `<quota-check>`")
    assert rebind_at < resume.index("Process the messages")
    rebind = _rebind(waiting)
    for text in ("`$ORCA_TERMINAL_HANDLE` in bash", "`$env:ORCA_TERMINAL_HANDLE` in PowerShell",
                 "compare it with the checkpoint's `coordinator-terminal:`",
                 "If they are equal, do nothing",
                 "Run `<orca> orchestration run-use --id <run-id> --json` once",
                 "rewrite the checkpoint's `coordinator-terminal:` to this handle",
                 "`<handle>` is this value from now on",
                 "the Run was re-bound to this terminal",
                 "fails with `consumer_fenced`", "retry the failed command once"):
        assert text in rebind, text
    assert rebind.index("run-use --id <run-id>") < rebind.index(
        "rewrite the checkpoint's `coordinator-terminal:`")


def test_rebind_updates_quota_checkpoint_and_retargets_reservations() -> None:
    rebind = _rebind(WAITING.read_text(encoding="utf-8"))
    assert ("While the quota is paused, also rewrite the terminal handle in the quota checkpoint "
            "(`<run-id>.md` under `checkpoint_dir`") in rebind
    for text in ("if the checkpoint's `reservation:` is not `none`",
                 "the `quota-guard:<run-id>` wake-up",
                 "**Codex:** remove the automation with `<orca> automations remove <id>`",
                 "`<orca> automations list --json` that it is gone",
                 "create it again with the same name and time, passing the new `<handle>` to "
                 "`--terminal`",
                 "**Claude Code:** run `CronList` and look for the reservation's marker",
                 "`CronCreate` it again at the same time with the same marker"):
        assert text in rebind, text
    pause = " ".join(QUOTA_PAUSE.read_text(encoding="utf-8").split())
    checkpoint = pause.split("## On PAUSED_QUOTA or UNKNOWN", 1)[1].split("2. Ask every", 1)[0]
    assert "the Coordinator terminal handle (`<handle>`)" in checkpoint
    assert "saved Coordinator terminal (`<handle>`)" in pause


def test_rebind_failure_stops_the_run() -> None:
    rebind = _rebind(WAITING.read_text(encoding="utf-8"))
    assert ("If `run-use` fails, do not repeat it: report its `error:` line to the user "
            "(`SKILL.md` **Asking the user**) and do not advance the Run") in rebind


def test_quota_pause_rebinds_first_by_reference_only() -> None:
    pause = QUOTA_PAUSE.read_text(encoding="utf-8")
    rebind = "do **Re-bind to this terminal** (**On every resume** in [Waiting](waiting.md))"
    paused = " ".join(pause.split("## While paused", 1)[1].split("\n## ", 1)[0].split())
    assert paused.split("2. ", 1)[0].endswith(f"1. Before anything else, {rebind}. ")
    wake = " ".join(pause.split("## On wake-up", 1)[1].split("\n## ", 1)[0].split())
    assert wake.startswith(f"Before anything else, {rebind}.")
    for copied in ("run-use", "coordinator-terminal:", "consumer_fenced"):
        assert copied not in pause


def test_worker_terminal_placeholder_differs_from_coordinator_handle() -> None:
    pause = " ".join(QUOTA_PAUSE.read_text(encoding="utf-8").split())
    assert "--terminal <handle>" not in pause
    assert "the worker's terminal handle (`<worker-terminal>`)" in pause
    assert "where `<worker-terminal>` is the worker's terminal handle you recorded" in pause


def test_waiting_section_warns_about_agent_sleep() -> None:
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    section = skill.split("## Waiting", 1)[1].split("## Token budget", 1)[0]
    for text in ("Orca's Agent sleep suspends a waiting Coordinator",
                 "not processed until the user resumes the Coordinator",
                 "**Re-bind to this terminal** in [Waiting](references/waiting.md) before "
                 "anything else",
                 "first re-binds the Run to this terminal if its handle changed"):
        assert text in section, text
    plan = skill.split("6. Before the first dispatch", 1)[1].split("## 2.", 1)[0]
    assert "sleep" not in plan.lower()
