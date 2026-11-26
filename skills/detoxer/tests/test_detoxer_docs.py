"""Tests that detoxer keeps its configuration, safety rules, and candidate formats.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL_MD = SKILL_DIR / "SKILL.md"
CONFIG = SKILL_DIR / "config.conf"
CANDIDATE = SKILL_DIR / "references" / "candidate.md"
TRIAGE = SKILL_DIR / "references" / "triage.md"
REPORT = SKILL_DIR / "references" / "report.md"

CONFIG_KEYS = (
    "MAX_ISSUES_PER_RUN",
    "SCAN_WINDOW_DAYS",
    "ISSUE_LABEL",
    "CONFIRM_BEFORE_PUBLISH",
    "IMPLEMENT_FILED_ISSUES",
    "IMPLEMENT_WITH",
    "IMPLEMENT_TIMEOUT_SECONDS",
    "CLAUDE_PERMISSION_MODE",
    "CODEX_SANDBOX",
)


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _step(number: int) -> str:
    body = re.split(rf"### {number}\. ", _flat(SKILL_MD), maxsplit=1)[1]
    return re.split(r"### \d+\. ", body, maxsplit=1)[0]


def _config() -> dict[str, str]:
    values = {}
    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def test_config_defines_exactly_the_documented_keys() -> None:
    assert set(_config()) == set(CONFIG_KEYS)
    skill = SKILL_MD.read_text(encoding="utf-8")
    for key in CONFIG_KEYS:
        assert f"`{key}`" in skill


def test_config_defaults() -> None:
    config = _config()
    assert config["IMPLEMENT_FILED_ISSUES"] == "false"
    assert config["IMPLEMENT_WITH"] == "new-session"
    assert config["CONFIRM_BEFORE_PUBLISH"] in ("true", "false")
    assert int(config["MAX_ISSUES_PER_RUN"]) >= 1
    assert config["SCAN_WINDOW_DAYS"] == ""
    assert config["ISSUE_LABEL"] == "detoxer"


def test_empty_scan_window_scans_the_whole_repository() -> None:
    text = _flat(SKILL_MD)
    assert "or the whole repository when it is empty" in text
    scope = _step(1)
    assert "with `SCAN_WINDOW_DAYS` empty and no `--since`, the hotspot is every file" in scope
    assert "git ls-tree -r --name-only <scan-ref>" in scope


def test_scan_runs_in_a_temporary_worktree_outside_the_repository() -> None:
    scope = _step(1)
    for phrase in ("under the system temp directory",
                   "`uv run --no-project ~/.agents/skills/detoxer/scripts/scan_dir.py "
                   "create --ref <scan-ref>`",
                   "`scan_dir: <path>`", "`checkout: <path>`", "`commit: <sha>`", "Exit 1",
                   "never keep them in a shell variable or another file",
                   "Keep every temporary file of the run in `<scan-dir>`, "
                   "never in the repository."):
        assert phrase in scope
    assert "git worktree add" not in scope
    assert "file in `<scan-dir>`" in _step(6)
    report = _step(7)
    remove = ("`uv run --no-project ~/.agents/skills/detoxer/scripts/scan_dir.py "
              "remove <scan-dir>`")
    assert report.index(remove) < report.index("Write the report in your final response")
    for phrase in ("on every path through steps 1-6 (including errors)",
                   "never from inside `<scan-dir>`", "never delete them yourself",
                   "exit 1", "2 (`refused:`", "still write the report"):
        assert phrase in report
    for command in ("rm ", "rmdir", "Remove-Item", "git worktree remove"):
        assert command not in report
    detection = _flat(SKILL_DIR / "references" / "detection.md")
    assert "`<scan-dir>/checkout`" in detection
    assert "tmp/" not in detection
    assert "tmp/" not in SKILL_MD.read_text(encoding="utf-8")


def test_local_mode_skips_every_github_lookup() -> None:
    scope = _step(1)
    for phrase in ("`git remote`", "`gh auth status`",
                   "`gh repo view --json nameWithOwner,defaultBranchRef`",
                   "`<scan-ref>`, is `origin/<default-branch>`",
                   "**Not on GitHub (local mode):** `<scan-ref>` is `HEAD`",
                   "step 2, the pull request check in step 5, and steps 6 and 8"):
        assert phrase in scope
    assert scope.index("decide whether the repository is on GitHub") < scope.index(
        "scan_dir.py create")
    assert "in local mode (step 1), skip this step" in _step(6)


def test_referenced_files_exist() -> None:
    for link in re.findall(r"\]\((references/[^)]+)\)", SKILL_MD.read_text(encoding="utf-8")):
        assert (SKILL_DIR / link).is_file(), link


def test_scan_is_read_only_and_implementation_is_gated() -> None:
    rules = _flat(SKILL_MD).split("## Rules", 1)[1].split("## Inputs", 1)[0]
    assert "read-only on the code" in rules
    assert "only when `IMPLEMENT_FILED_ISSUES` is `true`" in rules
    assert "### 8. Implement (only when `IMPLEMENT_FILED_ISSUES` is `true`)" in _flat(SKILL_MD)
    assert "Skip this step with `--dry-run`" in _step(8)


def test_every_candidate_is_refined_at_filing_without_interview() -> None:
    assert "Run the refine-issue skill on the request with `--no-interview`" in _step(6)
    for number in (7, 8):
        assert "refine-issue skill" not in _step(number)


def test_implementation_modes() -> None:
    implement = _step(8)
    assert "same-session" not in SKILL_MD.read_text(encoding="utf-8")
    new_session = implement.split("**`new-session` (default):**", 1)[1].split("**`orca`:**", 1)[0]
    for phrase in ("detached, and do not wait for it", "one at a time",
                   "implement-review-merge skill in Standalone mode",
                   "`detoxer/issue-<number>`", "its own git worktree",
                   "stops at the first issue that is not merged",
                   "comments the reason on that issue",
                   "~/.agents/skills/detoxer/scripts/implement_issues.py",
                   "--agent <claude|codex> --base <default-branch> --detach",
                   "--issues <number> <number> ...",
                   "`started: <pid>`", "`summary: <path>`", "exit 1",
                   "this session's work ends here"):
        assert phrase in new_session
    orca = implement.split("**`orca`:**", 1)[1]
    for phrase in ("a new Orca agent that runs the orca-issue-coordinator skill",
                   "do not wait for it", "`ORCA_CLI_COMMAND`",
                   "<orca> agent launch --agent <claude|codex> --surface terminal --json",
                   "Use the orca-issue-coordinator skill to coordinate GitHub issues",
                   "`journaled`", "`handed-to-terminal`", "`result.launch.outcome.handle`",
                   "this session's work ends here", "the issues stay filed"):
        assert phrase in orca


def test_skill_does_not_name_other_skills_internals() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "refine-issue/config" not in text
    assert "implement-review-merge/config" not in text


def test_settings_are_resolved_by_the_script() -> None:
    configuration = _flat(SKILL_MD).split("## Configuration", 1)[1].split("## Workflow", 1)[0]
    for phrase in ("`config.local.conf`", "overrides single keys",
                   "Never read the files yourself",
                   "~/.agents/skills/detoxer/scripts/resolve_config.py",
                   "Exit 1", "stop without scanning"):
        assert phrase in configuration


def test_dedup_reads_records_respects_rejections_and_open_prs() -> None:
    loaded = _step(2)
    for phrase in ('gh api --method GET --paginate "repos/{owner}/{repo}/issues"',
                   "-f labels=<ISSUE_LABEL> -f state=all -f per_page=100",
                   "never inside the URL", "never a capped list",
                   "the marker in its body", "`not_planned`"):
        assert phrase in loaded
    assert "--limit" not in loaded
    assert "issues?" not in loaded
    dedup = _step(5)
    for phrase in ("fingerprint", "compare by intent", "`gh pr list`"):
        assert phrase in dedup


def test_filing_is_capped_labelled_and_records_each_issue() -> None:
    filing = _step(6)
    for phrase in ("`MAX_ISSUES_PER_RUN`", "`CONFIRM_BEFORE_PUBLISH`", "`--dry-run`",
                   "local mode", "gh label create",
                   "gh issue edit <number> --add-label <ISSUE_LABEL>",
                   "Append the fingerprint marker to its body",
                   "gh issue edit <number> --body-file <file>",
                   "gh issue comment <number> --body-file <file>",
                   "or several, if it splits the work", "markdown file"):
        assert phrase in filing


def test_report_keeps_every_unfiled_candidate_in_the_session_log() -> None:
    step = _step(7)
    assert "in your final response, so it stays in the session log" in step
    assert "[report.md](references/report.md)" in step
    assert "every list of items is a table" in step
    assert "unfiled candidates" in _step(5)
    report = REPORT.read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", report, flags=re.MULTILINE)
    assert headings == ["Scope", "Filed issues", "Unfiled candidates",
                        "Skipped as duplicates", "Dropped findings", "Detectors"]
    assert "Put every list of items in a table" in _flat(REPORT)
    unfiled = _flat(REPORT).split("## Unfiled candidates", 1)[1].split(
        "## Skipped as duplicates", 1)[0]
    for phrase in ("Every candidate that passed triage but was not filed",
                   "| # | Title | Score | B / C / R | Why not filed |",
                   "`MAX_ISSUES_PER_RUN`", "rejected at confirmation",
                   "open pull request", "refine-issue did not file it", "`--dry-run`",
                   "local mode", "Fingerprint:", "| Axis | Rating | Reason |",
                   "| Evidence | What is there |", "**Proposed change:**"):
        assert phrase in unfiled


def test_dry_run_skips_filing_and_implementing() -> None:
    assert "| `--dry-run` | Skip filing and implementing (steps 6 and 8)" in _flat(SKILL_MD)
    filing = _step(6)
    assert filing.index("skip this step") < filing.index("write the request")
    assert "every candidate goes to the report's unfiled candidates" in filing
    assert "Skip this step with `--dry-run`" in _step(8)


def test_filing_after_a_dry_run_reuses_the_reported_candidates() -> None:
    inputs = _flat(SKILL_MD).split("## Inputs", 1)[1].split("## Configuration", 1)[0]
    follow_up = inputs.split("**Filing after a dry run:**", 1)[1]
    for phrase in ("in the same session", "without re-scanning",
                   "git fetch origin <default-branch>",
                   "compare `origin/<default-branch>` with the report's Scope Commit",
                   "If they differ, do not use the reported candidates",
                   "run again from step 1 without `--dry-run`",
                   "create a new `<scan-dir>`",
                   "detached worktree of the scanned commit",
                   "redo step 2 and step 5",
                   "Do not redo step 3 or step 4",
                   "their `--dry-run` skips do not apply to this follow-up",
                   "the top `MAX_ISSUES_PER_RUN` by score",
                   "In local mode there is nothing to file to"):
        assert phrase in follow_up
    assert follow_up.index("If they differ") < follow_up.index("create a new `<scan-dir>`")


def test_candidate_request_and_record_formats() -> None:
    candidate = CANDIDATE.read_text(encoding="utf-8")
    request = candidate.split("\n## Request\n", 1)[1].split("\n## Record\n", 1)[0]
    for heading in ("## Problem", "## Evidence", "## Proposed change", "## Not doing"):
        assert heading in request
    assert "behavior must stay unchanged" in request
    marker = candidate.split("\n## Fingerprint marker\n", 1)[1].split("\n## Record\n", 1)[0]
    assert "<!-- detoxer fingerprint: <kind>:" in marker
    assert "appended to the end of the issue body" in marker
    record = candidate.split("\n## Record\n", 1)[1].split("\n## Fingerprint\n", 1)[0]
    for phrase in ("## Detoxer record", "Fingerprint:", "Scanned: <default branch commit SHA>",
                   "Benefit:", "Cost:", "Risk:", "Score:"):
        assert phrase in record
    for kind in ("duplication", "complexity", "dead-code", "coupling",
                 "convention", "leftover", "test"):
        assert f"`{kind}`" in candidate


def test_triage_score_matches_record() -> None:
    formula = "benefit * 2 - cost - risk"
    assert formula in _flat(TRIAGE)
    assert formula in _flat(CANDIDATE)
    triage = _flat(TRIAGE)
    for phrase in ("Coincidental duplication", "rule of three", "Intentional",
                   "Already in flight"):
        assert phrase in triage
