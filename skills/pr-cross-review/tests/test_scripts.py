"""Tests for the pr-cross-review scripts, using fake gh/codex/claude commands.

Run with: uv run --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
HEAD_COMMIT = "b" * 40
PREVIOUS_COMMIT = "a" * 40
EXPLORATION_SCOPE = (
    "Read code outside the diff only as far as needed to verify a finding "
    "(such as callers and dependencies of the changed code); do not explore the rest of the repository."
)


@pytest.fixture(autouse=True)
def isolated_skill(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run a copy of the skill, so a user's config.local.conf cannot affect the tests."""
    skill_dir = tmp_path_factory.mktemp("skill")
    shutil.copytree(Path(__file__).resolve().parents[1] / "scripts", skill_dir / "scripts")
    shutil.copy2(Path(__file__).resolve().parents[1] / "config.conf", skill_dir / "config.conf")
    monkeypatch.setattr(sys.modules[__name__], "SCRIPTS_DIR", skill_dir / "scripts")
    return skill_dir


def write_local_config(skill_dir: Path, text: str, newline: str = "\n") -> None:
    """Write the personal settings file of the isolated skill copy."""
    (skill_dir / "config.local.conf").write_text(text, encoding="utf-8", newline=newline)


def find_bash() -> str:
    """Return an available Bash executable."""
    bash = shutil.which("bash")
    if bash is not None:
        return bash

    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    if git_bash.is_file():
        return str(git_bash)

    pytest.skip("Bash is required to test review scripts")


REVIEW_HARNESS = r"""
gh() {
    case "$1 $2" in
        "repo view") printf '%s\n' 'owner/repo' ;;
        "pr view") printf '%s\n' "$REVIEW_HEAD_COMMIT" ;;
        "pr comment") printf 'posted-body: %s\n' "$(head -n 1 "${@: -1}")" ;;
        "api --paginate")
            printf 'call\n' >>"$REVIEW_API_FILE"
            if [ "$REVIEW_API_FAILURE_AFTER" = "true" ] && [ -f "$REVIEW_STATE_FILE" ]; then
                return 22
            fi
            comment_id=900
            for commit in $REVIEW_EXISTING_COMMITS; do
                comment_id=$((comment_id + 1))
                if [ "$commit" = "missing" ]; then
                    commit=""
                fi
                printf '%s\thttps://github.com/owner/repo/pull/123#issuecomment-%s\t%s\t%s\t%s\n' \
                    "$comment_id" "$comment_id" "$commit" "$REVIEW_AGENT_LABEL" "$REVIEW_EXISTING_FINDINGS"
            done
            if [ -f "$REVIEW_STATE_FILE" ]; then
                printf '1001\thttps://github.com/owner/repo/pull/123#issuecomment-1001\t%s\t%s\tmust=1 optional=2\n' \
                    "$REVIEW_HEAD_COMMIT" "$REVIEW_AGENT_LABEL"
            fi
            ;;
        *) return 1 ;;
    esac
}

fake_reviewer() {
    printf 'prompt: %s\n' "${!#}" >"$REVIEW_CAPTURE_FILE"
    printf 'reviewed-commit: %s\n' "$PR_CROSS_REVIEW_REVIEWED_COMMIT" >>"$REVIEW_CAPTURE_FILE"
    printf 'args: %s\n' "$*" >>"$REVIEW_CAPTURE_FILE"
    if [ -f "$REVIEW_OUTPUT_FILE" ]; then
        cat "$REVIEW_OUTPUT_FILE"
    fi
    if [ "$REVIEW_POST_COMMENT" = "true" ]; then
        printf 'review body\n' >"$PR_CROSS_REVIEW_BODY_FILE"
        if [ "$REVIEW_RUN_POST" = "true" ]; then
            printf 'review-findings: must=1 optional=2\n' >>"$PR_CROSS_REVIEW_BODY_FILE"
            # Run the exact post command the prompt hands to the reviewer.
            post_command=$(printf '%s\n' "${!#}" | sed -n 's/^Then post it with exactly this command (do not use `gh pr comment` directly): //p')
            eval "$post_command" >>"$REVIEW_CAPTURE_FILE" 2>&1 || return 3
        fi
        : >"$REVIEW_STATE_FILE"
    fi
    return "$REVIEW_EXIT_CODE"
}

claude() { fake_reviewer "$@"; }
codex() { fake_reviewer "$@"; }

export -f gh fake_reviewer claude codex

bash "$REVIEW_SCRIPT" 123 "$@"
review_status=$?
if [ -f "$REVIEW_CAPTURE_FILE" ]; then
    cat "$REVIEW_CAPTURE_FILE"
fi
printf 'api-calls: %s\n' "$(wc -l <"$REVIEW_API_FILE")"
exit "$review_status"
"""


def run_review_script(
    tmp_path: Path,
    script_name: str,
    *,
    post_comment: bool,
    existing_review_commits: tuple[str, ...] = (),
    head_commit: str = HEAD_COMMIT,
    api_failure_after_review: bool = False,
    extra_args: tuple[str, ...] = (),
    ignore_body_dir: bool = True,
    reviewer_output: str | None = None,
    reviewer_exit_code: int = 0,
    existing_findings: str = "unknown",
    run_post: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a review script with deterministic fake CLI and GitHub commands."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    if ignore_body_dir:
        (tmp_path / ".gitignore").write_text("tmp/\n", encoding="utf-8")
    api_file = tmp_path / "api"
    api_file.touch()
    output_file = tmp_path / "reviewer-output"
    if reviewer_output is not None:
        output_file.write_text(reviewer_output, encoding="utf-8", newline="\n")
    environment = {
        **os.environ,
        "REVIEW_SCRIPT": (SCRIPTS_DIR / script_name).as_posix(),
        "REVIEW_STATE_FILE": (tmp_path / "state").as_posix(),
        "REVIEW_CAPTURE_FILE": (tmp_path / "capture").as_posix(),
        "REVIEW_API_FILE": api_file.as_posix(),
        "REVIEW_OUTPUT_FILE": output_file.as_posix(),
        "REVIEW_POST_COMMENT": str(post_comment).lower(),
        "REVIEW_EXIT_CODE": str(reviewer_exit_code),
        "REVIEW_EXISTING_COMMITS": " ".join(existing_review_commits),
        "REVIEW_HEAD_COMMIT": head_commit,
        "REVIEW_API_FAILURE_AFTER": str(api_failure_after_review).lower(),
        "REVIEW_AGENT_LABEL": "Claude" if script_name == "run_claude_review.sh" else "Codex",
        "REVIEW_EXISTING_FINDINGS": existing_findings,
        "REVIEW_RUN_POST": str(run_post).lower(),
    }
    environment.pop("PR_CROSS_REVIEW_IN_PROGRESS", None)
    return subprocess.run(
        [find_bash(), "-c", REVIEW_HARNESS, "harness", *extra_args],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


SCRIPT_NAMES = ["run_claude_review.sh", "run_codex_review.sh"]


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
@pytest.mark.parametrize("existing", [(), (PREVIOUS_COMMIT,)])
def test_review_prompt_classifies_findings(
    tmp_path: Path, script_name: str, existing: tuple[str, ...]
) -> None:
    """Initial and incremental reviews share the merge-based classification contract."""
    result = run_review_script(
        tmp_path, script_name, post_comment=True, existing_review_commits=existing
    )
    assert result.returncode == 0, result.stderr
    for text in (
        "[must] means it must be fixed before merging", "[optional] means merging is acceptable",
        "at the start of its heading", "Do not use P0-P3", "last non-empty line",
        "review-findings: must=<n> optional=<n>", "both 0",
        "only unresolved must findings", "do not repeat previous optional suggestions",
        "unmet Issue specifications or acceptance criteria", "missing required tests",
        "security or data-loss risks", "misleading instructions or documentation errors",
    ):
        assert text in result.stdout


@pytest.mark.parametrize("findings", ["must=0 optional=0", "must=2 optional=10"])
def test_review_status_reports_findings(tmp_path: Path, findings: str) -> None:
    """Known counts follow the latest reviewed commit on the next line."""
    result = run_review_script(
        tmp_path, "review_status.sh", post_comment=False,
        existing_review_commits=(HEAD_COMMIT,), existing_findings=findings,
    )
    assert result.returncode == 0, result.stderr
    assert f"review-latest-commit: {HEAD_COMMIT}\nreview-latest-findings: {findings}\n" in result.stdout


@pytest.mark.parametrize("body", [
    "", "review body", "review-findings: must=-1 optional=0",
    "review-findings: must=1 optional=2 extra", "review-findings: optional=2 must=1",
    "review-findings: must=1.5 optional=0", "review-findings: must=0 optional=0\nmore text",
    "review-findings: must=0", " review-findings: must=0 optional=0",
])
def test_post_comment_rejects_invalid_findings(tmp_path: Path, body: str) -> None:
    """Malformed or missing counts must never reach the posting operation."""
    result = run_post_comment_script(tmp_path, HEAD_COMMIT, body=body)
    assert result.returncode == 1
    assert result.stderr.strip() == (
        'error: review body must end with "review-findings: must=<n> optional=<n>"'
    )
    assert result.stdout == ""


@pytest.mark.parametrize("ending", ["", "\n\n \t\n", "\r\n\r\n"])
def test_post_comment_accepts_last_nonempty_count_line(tmp_path: Path, ending: str) -> None:
    """No final newline, blank trailing lines, and Windows line endings are supported."""
    result = run_post_comment_script(
        tmp_path, HEAD_COMMIT, body="review body\r\nreview-findings: must=0 optional=3" + ending
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith(f"Reviewed commit: {HEAD_COMMIT}\nreview-findings: must=0 optional=3\n")


def test_history_parses_real_footer_counts_and_historical_reviews(tmp_path: Path) -> None:
    """Execute the actual gh jq filter against local comment fixtures without GitHub."""
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is needed to exercise the GitHub CLI filter (available in CI)")
    footer = f"_Reviewed by Claude. Posted via pr-cross-review skill._\nReviewed commit: {HEAD_COMMIT}"
    comments = [
        {"id": 1, "html_url": "old", "body": "old review\n" + footer + "\n"},
        {"id": 2, "html_url": "new", "body": footer + "\nreview-findings: must=0 optional=4\n"},
        {"id": 3, "html_url": "ordinary", "body": "review-findings: must=0 optional=0"},
        {"id": 4, "html_url": "crlf", "body": (footer + "\nreview-findings: must=12 optional=3\n").replace("\n", "\r\n")},
    ]
    fixtures = tmp_path / "comments.json"
    fixtures.write_text(json.dumps(comments), encoding="utf-8")
    result = subprocess.run(
        [find_bash(), "-c", r'''
source "$COMMON_SCRIPT"
gh() { "$JQ_EXECUTABLE" -r "${!#}" "$COMMENTS_FILE"; }
list_review_history owner/repo 123
'''],
        env={**os.environ, "COMMON_SCRIPT": (SCRIPTS_DIR / "common.sh").as_posix(),
             "JQ_EXECUTABLE": Path(jq).as_posix(), "COMMENTS_FILE": fixtures.as_posix()},
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        f"1\told\t{HEAD_COMMIT}\tClaude\tunknown",
        f"2\tnew\t{HEAD_COMMIT}\tClaude\tmust=0 optional=4",
        f"4\tcrlf\t{HEAD_COMMIT}\tClaude\tmust=12 optional=3",
    ]


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_reports_new_comment_url(tmp_path: Path, script_name: str) -> None:
    """A newly posted review comment is reported as successful completion."""
    result = run_review_script(tmp_path, script_name, post_comment=True)

    assert result.returncode == 0, result.stderr
    assert "review-posted: https://github.com/owner/repo/pull/123#issuecomment-1001\n" in result.stdout
    assert "review-count: 1/3\nreview-findings: must=1 optional=2\n" in result.stdout
    assert f"reviewed-commit: {HEAD_COMMIT}" in result.stdout
    assert "Examine the whole diff" in result.stdout
    assert EXPLORATION_SCOPE in result.stdout
    assert "post_pr_comment.sh' 123 '" in result.stdout
    assert "api-calls: 2" in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_uses_config_language(tmp_path: Path, script_name: str) -> None:
    """The review language comes from config.conf."""
    result = run_review_script(tmp_path, script_name, post_comment=True)

    config = (SCRIPTS_DIR.parent / "config.conf").read_text(encoding="utf-8")
    language = next(
        line.split("=", 1)[1].strip()
        for line in config.splitlines()
        if line.startswith("REVIEW_LANGUAGE=")
    )
    assert f"Write the review comment in {language}." in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_assigns_body_file(tmp_path: Path, script_name: str) -> None:
    """The prompt names the body file under REVIEW_BODY_DIR; it is removed after posting."""
    agent = "claude" if script_name == "run_claude_review.sh" else "codex"
    body_file = tmp_path / "tmp" / f"pr-123-review-{agent}.md"

    result = run_review_script(tmp_path, script_name, post_comment=True)

    assert result.returncode == 0, result.stderr
    assert "write the comment body to exactly this file" in result.stdout
    assert f"tmp/pr-123-review-{agent}.md" in result.stdout
    assert (tmp_path / "tmp").is_dir()
    assert not body_file.exists()


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_rejects_unignored_body_dir(tmp_path: Path, script_name: str) -> None:
    """With REVIEW_BODY_NOT_IGNORED=error, an unignored body file stops the run before launch."""
    result = run_review_script(tmp_path, script_name, post_comment=True, ignore_body_dir=False)

    assert result.returncode == 1
    assert "review body file is not ignored by git" in result.stderr
    assert "prompt:" not in result.stdout


@pytest.mark.parametrize(
    ("script_name", "expected"),
    [
        ("run_claude_review.sh", "--model override-model --effort high"),
        ("run_codex_review.sh", "--model override-model -c model_reasoning_effort=high"),
    ],
)
def test_review_script_options_override_config(
    tmp_path: Path, script_name: str, expected: str
) -> None:
    """Command-line options override the config.conf defaults."""
    result = run_review_script(
        tmp_path,
        script_name,
        post_comment=True,
        extra_args=("--model", "override-model", "--effort", "high"),
    )

    assert result.returncode == 0, result.stderr
    assert expected in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_appends_extra_instructions(tmp_path: Path, script_name: str) -> None:
    """Text after `--` is appended to the prompt."""
    result = run_review_script(
        tmp_path, script_name, post_comment=True, extra_args=("--", "focus", "on", "tests")
    )

    assert result.returncode == 0, result.stderr
    assert "Additional instructions: focus on tests" in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_fails_without_new_comment(tmp_path: Path, script_name: str) -> None:
    """A successful CLI exit without a new comment is treated as failure."""
    result = run_review_script(tmp_path, script_name, post_comment=False)

    assert result.returncode == 1
    assert "no new review comment was found" in result.stderr
    assert "review-posted:" not in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_does_not_accept_existing_comment(tmp_path: Path, script_name: str) -> None:
    """A review comment that predates the run is not accepted."""
    result = run_review_script(
        tmp_path, script_name, post_comment=False, existing_review_commits=(PREVIOUS_COMMIT,)
    )

    assert result.returncode == 1
    assert "no new review comment was found" in result.stderr
    assert "review-posted:" not in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_rejects_review_over_limit(tmp_path: Path, script_name: str) -> None:
    """A review beyond MAX_REVIEWS is rejected before an agent is launched."""
    result = run_review_script(
        tmp_path,
        script_name,
        post_comment=False,
        existing_review_commits=("1" * 40, "2" * 40, "3" * 40),
    )

    assert result.returncode == 1
    assert "the maximum is 3" in result.stderr
    assert "prompt:" not in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_rejects_unchanged_head(tmp_path: Path, script_name: str) -> None:
    """A re-review without a new commit is rejected before launch."""
    result = run_review_script(
        tmp_path, script_name, post_comment=False, existing_review_commits=(HEAD_COMMIT,)
    )

    assert result.returncode == 1
    assert "has no commits after the previous review" in result.stderr
    assert "prompt:" not in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_rejects_untracked_previous_review(tmp_path: Path, script_name: str) -> None:
    """A previous review comment without a commit cannot define a re-review range."""
    result = run_review_script(
        tmp_path,
        script_name,
        post_comment=False,
        existing_review_commits=(PREVIOUS_COMMIT, "missing"),
    )

    assert result.returncode == 1
    assert "previous review comment does not record" in result.stderr
    assert "prompt:" not in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_limits_rereview_prompt(tmp_path: Path, script_name: str) -> None:
    """A re-review prompt identifies its commit range and allowed scope."""
    result = run_review_script(
        tmp_path, script_name, post_comment=True, existing_review_commits=(PREVIOUS_COMMIT,)
    )

    assert result.returncode == 0, result.stderr
    assert f"{PREVIOUS_COMMIT}..{HEAD_COMMIT}" in result.stdout
    assert "review-count: 2/3\n" in result.stdout
    assert "Do not raise new findings about existing code outside that diff." in result.stdout
    assert EXPLORATION_SCOPE in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
@pytest.mark.parametrize("quota_message", [False, True])
def test_review_script_distinguishes_api_failure(
    tmp_path: Path, script_name: str, quota_message: bool
) -> None:
    """An API failure preserves the body and takes precedence over quota text."""
    output = reviewer_error_output(script_name, "Usage limit reached.") if quota_message else None
    result = run_review_script(
        tmp_path,
        script_name,
        post_comment=True,
        api_failure_after_review=True,
        reviewer_output=output,
    )

    assert result.returncode == 2
    assert "failed to query review comments" in result.stderr
    assert "no new review comment was found" not in result.stderr
    assert "review-posted:" not in result.stdout
    assert "reviewer-quota-exhausted:" not in result.stdout
    agent = "claude" if script_name == "run_claude_review.sh" else "codex"
    assert (tmp_path / "tmp" / f"pr-123-review-{agent}.md").read_text() == "review body\n"


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_rejects_nested_launch(tmp_path: Path, script_name: str) -> None:
    """A reviewer cannot launch another review."""
    result = subprocess.run(
        [find_bash(), (SCRIPTS_DIR / script_name).as_posix(), "123"],
        cwd=tmp_path,
        env={**os.environ, "PR_CROSS_REVIEW_IN_PROGRESS": "1"},
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 1
    assert "nested review launch is not allowed" in result.stderr


def test_review_status_reports_count_and_latest_review(tmp_path: Path) -> None:
    """The status script prints the review count and the latest review comment URL."""
    result = run_review_script(
        tmp_path,
        "review_status.sh",
        post_comment=False,
        existing_review_commits=(PREVIOUS_COMMIT, HEAD_COMMIT),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(
        "review-count: 2/3\n"
        "review-extra: 0\n"
        "review-latest: https://github.com/owner/repo/pull/123#issuecomment-902\n"
        f"review-latest-commit: {HEAD_COMMIT}\n"
    )
    assert "api-calls: 1" in result.stdout
    assert "review-latest-findings: unknown\n" in result.stdout


def test_review_status_reports_commit_of_latest_review(tmp_path: Path) -> None:
    """The latest review's commit is reported even when the PR head moved on after it."""
    result = run_review_script(
        tmp_path,
        "review_status.sh",
        post_comment=False,
        existing_review_commits=(HEAD_COMMIT, PREVIOUS_COMMIT),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(
        "review-count: 2/3\n"
        "review-extra: 0\n"
        "review-latest: https://github.com/owner/repo/pull/123#issuecomment-902\n"
        f"review-latest-commit: {PREVIOUS_COMMIT}\n"
    )


def test_review_status_without_review(tmp_path: Path) -> None:
    """A PR without a cross-review reports a zero count and no latest review."""
    result = run_review_script(tmp_path, "review_status.sh", post_comment=False)

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(
        "review-count: 0/3\n"
        "review-extra: 0\n"
        "review-latest: none\n"
        "review-latest-commit: none\n"
        "review-latest-findings: none\n"
    )


def test_review_status_reports_api_failure(tmp_path: Path) -> None:
    """A failed history lookup exits 2 without printing a status."""
    (tmp_path / "state").touch()
    result = run_review_script(
        tmp_path, "review_status.sh", post_comment=False, api_failure_after_review=True
    )

    assert result.returncode == 2
    assert "failed to query review history" in result.stderr
    assert "review-count:" not in result.stdout


def test_review_status_rejects_extra_arguments(tmp_path: Path) -> None:
    """The status script takes exactly one PR number."""
    result = run_review_script(
        tmp_path, "review_status.sh", post_comment=False, extra_args=("--model", "x")
    )

    assert result.returncode == 1
    assert "usage:" in result.stderr


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_hides_reviewer_output_on_success(tmp_path: Path, script_name: str) -> None:
    """On success, the reviewer's own output reaches neither stdout nor stderr."""
    result = run_review_script(
        tmp_path, script_name, post_comment=True, reviewer_output="REVIEWER-REPLY-BODY\n"
    )

    assert result.returncode == 0, result.stderr
    assert "review-posted:" in result.stdout
    assert "REVIEWER-REPLY-BODY" not in result.stdout
    assert "REVIEWER-REPLY-BODY" not in result.stderr
    assert "---- last " not in result.stderr


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_dumps_reviewer_log_on_failed_exit(tmp_path: Path, script_name: str) -> None:
    """A non-zero reviewer exit keeps its status and dumps the log tail to stderr."""
    result = run_review_script(
        tmp_path,
        script_name,
        post_comment=False,
        reviewer_output="REVIEWER-ERROR-DETAIL\n",
        reviewer_exit_code=3,
    )

    assert result.returncode == 3
    assert "exited with status 3" in result.stderr
    assert "REVIEWER-ERROR-DETAIL" in result.stderr
    assert "REVIEWER-ERROR-DETAIL" not in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_dumps_bounded_reviewer_log_without_comment(
    tmp_path: Path, script_name: str
) -> None:
    """Without a new comment, the log dump keeps the last 40 lines, each cut to 300 chars."""
    lines = [f"line-{index:02d} " + "x" * 1000 for index in range(50)]
    lines.append("short-final-line")
    result = run_review_script(
        tmp_path,
        script_name,
        post_comment=False,
        reviewer_output="\n".join(lines) + "\n",
    )

    assert result.returncode == 1
    assert "no new review comment was found" in result.stderr
    assert "line-" not in result.stdout
    dump = result.stderr.split("(each cut to 300 chars) ----\n", 1)[1]
    dumped_lines = dump.split("---- end of ", 1)[0].splitlines()
    assert len(dumped_lines) == 40
    expected_first = f"{lines[11][:300]}... [truncated {len(lines[11]) - 300} chars]"
    assert dumped_lines[0] == expected_first
    assert all(len(line) <= len(expected_first) for line in dumped_lines)
    assert dumped_lines[-1] == "short-final-line"


def reviewer_error_output(script_name: str, message: str) -> str:
    """Format a reviewer error message the way each reviewer CLI ends its log."""
    if script_name == "run_codex_review.sh":
        return (
            '{"type":"item.completed","item":{"type":"agent_message"}}\n'
            f'{{"type":"turn.failed","error":{{"message":"{message}"}}}}\n'
        )
    return f"{message}\n"


QUOTA_MESSAGES = {
    "run_claude_review.sh": (
        "You've hit your session limit \u00b7 resets 10:10am (Asia/Tokyo)",
        "resets 10:10am (Asia/Tokyo)",
    ),
    "run_codex_review.sh": (
        "You've hit your usage limit. Upgrade to Pro or try again at 10:10 AM.",
        "try again at 10:10 AM",
    ),
}


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_reports_reviewer_quota_exhaustion(tmp_path: Path, script_name: str) -> None:
    """A reviewer stopped by its usage limit exits 75 and reports the reset time."""
    message, reset = QUOTA_MESSAGES[script_name]
    result = run_review_script(
        tmp_path,
        script_name,
        post_comment=False,
        reviewer_output=reviewer_error_output(script_name, message),
        reviewer_exit_code=1,
    )

    agent = "claude" if script_name == "run_claude_review.sh" else "codex"
    assert result.returncode == 75
    assert f"reviewer-quota-exhausted: {agent}\n" in result.stdout
    assert re.search(r"^reviewer-quota-detected-at: 20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4}$", result.stdout, re.M)
    assert f"reviewer-quota-reset: {reset}\n" in result.stdout
    assert "usage limit was reached" in result.stderr


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_reports_quota_without_comment(tmp_path: Path, script_name: str) -> None:
    """A quota message after a zero exit without a comment is reported the same way."""
    message, reset = QUOTA_MESSAGES[script_name]
    result = run_review_script(
        tmp_path,
        script_name,
        post_comment=False,
        reviewer_output=reviewer_error_output(script_name, message),
    )

    assert result.returncode == 75
    assert f"reviewer-quota-reset: {reset}\n" in result.stdout
    assert "no new review comment was found" in result.stderr


def test_review_script_converts_epoch_reset_time(tmp_path: Path) -> None:
    """A `limit reached|<epoch>` message is reported as an ISO 8601 local time."""
    result = run_review_script(
        tmp_path,
        "run_claude_review.sh",
        post_comment=False,
        reviewer_output="Claude AI usage limit reached|1760580600\n",
        reviewer_exit_code=1,
    )

    assert result.returncode == 75
    assert re.search(r"^reviewer-quota-reset: 20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4}$", result.stdout, re.M)


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_reports_unknown_quota_reset(tmp_path: Path, script_name: str) -> None:
    """A quota message without a time reports the reset as unknown."""
    result = run_review_script(
        tmp_path,
        script_name,
        post_comment=False,
        reviewer_output=reviewer_error_output(script_name, "Usage limit reached. Please try again later."),
        reviewer_exit_code=1,
    )

    assert result.returncode == 75
    assert "reviewer-quota-reset: unknown\n" in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_ignores_quoted_quota_text(tmp_path: Path, script_name: str) -> None:
    """Quota wording outside the reviewer's final error is not a quota failure."""
    if script_name == "run_codex_review.sh":
        output = '{"type":"item.completed","item":{"text":"usage limit reached, resets 10am"}}\n'
    else:
        output = "usage limit reached, resets 10am\n" + "other output\n" * 5
    result = run_review_script(
        tmp_path,
        script_name,
        post_comment=False,
        reviewer_output=output,
        reviewer_exit_code=3,
    )

    assert result.returncode == 3
    assert "reviewer-quota" not in result.stdout


POST_HARNESS = r"""
gh() {
    case "$1 $2" in
        "repo view") printf '%s\n' 'owner/repo' ;;
        "pr view") return 0 ;;
        "pr comment")
            while [ "$#" -gt 0 ]; do
                if [ "$1" = "--body-file" ]; then
                    cat "$2"
                    return 0
                fi
                shift
            done
            return 1
            ;;
        *) return 1 ;;
    esac
}

export -f gh
bash "$POST_SCRIPT" 123 "$REVIEW_BODY_FILE" claude <<<"stdin body"
"""


def run_post_comment_script(
    tmp_path: Path,
    reviewed_commit: str | None,
    *,
    body_arg: str | None = None,
    body: str = "review body\nreview-findings: must=1 optional=2\n",
) -> subprocess.CompletedProcess[str]:
    """Run post_pr_comment.sh with a fake GitHub CLI.

    The assigned body file is tmp_path/body.md; body_arg overrides the path
    passed to the script.
    """
    body_file = tmp_path / "body.md"
    body_file.write_text(body, encoding="utf-8", newline="\n")
    environment = {
        **os.environ,
        "POST_SCRIPT": (SCRIPTS_DIR / "post_pr_comment.sh").as_posix(),
        "REVIEW_BODY_FILE": body_arg if body_arg is not None else body_file.as_posix(),
        "PR_CROSS_REVIEW_BODY_FILE": body_file.as_posix(),
    }
    if reviewed_commit is None:
        environment.pop("PR_CROSS_REVIEW_REVIEWED_COMMIT", None)
    else:
        environment["PR_CROSS_REVIEW_REVIEWED_COMMIT"] = reviewed_commit

    return subprocess.run(
        [find_bash(), "-c", POST_HARNESS],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_post_comment_records_reviewed_commit(tmp_path: Path) -> None:
    """The wrapper's reviewed commit is appended to the review footer."""
    result = run_post_comment_script(tmp_path, HEAD_COMMIT)

    assert result.returncode == 0, result.stderr
    assert "_Reviewed by Claude. Posted via pr-cross-review skill._" in result.stdout
    assert f"Reviewed commit: {HEAD_COMMIT}" in result.stdout
    assert result.stdout.endswith(f"Reviewed commit: {HEAD_COMMIT}\nreview-findings: must=1 optional=2\n")


@pytest.mark.parametrize("reviewed_commit", [None, "not-a-sha"])
def test_post_comment_requires_reviewed_commit(
    tmp_path: Path, reviewed_commit: str | None
) -> None:
    """Posting is rejected without the wrapper's valid reviewed commit."""
    result = run_post_comment_script(tmp_path, reviewed_commit)

    assert result.returncode == 1
    assert "PR_CROSS_REVIEW_REVIEWED_COMMIT must be set" in result.stderr


def test_post_comment_accepts_relative_spelling_of_body_file(tmp_path: Path) -> None:
    """The assigned body file is matched as a file, not as a string."""
    result = run_post_comment_script(tmp_path, HEAD_COMMIT, body_arg="./body.md")

    assert result.returncode == 0, result.stderr
    assert "review body" in result.stdout


@pytest.mark.parametrize("body_arg", ["other.md", "-"])
def test_post_comment_rejects_unassigned_body_file(tmp_path: Path, body_arg: str) -> None:
    """With REVIEW_BODY_PATH_ENFORCED=true, only the assigned body file is posted."""
    (tmp_path / "other.md").write_text("other body", encoding="utf-8")
    result = run_post_comment_script(tmp_path, HEAD_COMMIT, body_arg=body_arg)

    assert result.returncode == 1
    assert "the body file must be" in result.stderr
    assert "body" not in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_runs_extra_review_over_limit(tmp_path: Path, script_name: str) -> None:
    """--extra-review runs one review beyond MAX_REVIEWS without editing config.conf."""
    config = (SCRIPTS_DIR.parent / "config.conf").read_text(encoding="utf-8")
    result = run_review_script(
        tmp_path,
        script_name,
        post_comment=True,
        existing_review_commits=("1" * 40, "2" * 40, PREVIOUS_COMMIT),
        extra_args=("--extra-review",),
    )

    assert result.returncode == 0, result.stderr
    assert "review-count: 4/3\n" in result.stdout
    assert f"{PREVIOUS_COMMIT}..{HEAD_COMMIT}" in result.stdout
    assert "--extra-review" not in result.stdout.split("args: ", 1)[1]
    assert (SCRIPTS_DIR.parent / "config.conf").read_text(encoding="utf-8") == config


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_rejects_extra_review_below_limit(tmp_path: Path, script_name: str) -> None:
    """--extra-review is rejected before launch while the PR is below MAX_REVIEWS."""
    result = run_review_script(
        tmp_path,
        script_name,
        post_comment=True,
        existing_review_commits=(PREVIOUS_COMMIT,),
        extra_args=("--extra-review",),
    )

    assert result.returncode == 1
    assert "--extra-review is only for a review beyond the limit" in result.stderr
    assert "prompt:" not in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_review_script_limit_error_names_extra_review(tmp_path: Path, script_name: str) -> None:
    """The limit error points to the option instead of the config file."""
    result = run_review_script(
        tmp_path,
        script_name,
        post_comment=False,
        existing_review_commits=("1" * 40, "2" * 40, "3" * 40),
    )

    assert result.returncode == 1
    assert "needs --extra-review" in result.stderr


def test_review_status_reports_extra_reviews(tmp_path: Path) -> None:
    """Reviews beyond MAX_REVIEWS are shown as review-extra."""
    result = run_review_script(
        tmp_path,
        "review_status.sh",
        post_comment=False,
        existing_review_commits=("1" * 40, "2" * 40, "3" * 40, "4" * 40, HEAD_COMMIT),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(
        "review-count: 5/3\n"
        "review-extra: 2\n"
        "review-latest: https://github.com/owner/repo/pull/123#issuecomment-905\n"
        f"review-latest-commit: {HEAD_COMMIT}\n"
    )


def test_local_config_is_ignored_by_git() -> None:
    """The personal settings file never shows up as a change."""
    repo_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        ["git", "-C", str(repo_root), "check-ignore", "-q", "skills/pr-cross-review/config.local.conf"],
        check=False,
    )
    assert result.returncode == 0


@pytest.mark.parametrize("text", [None, "", "\n  \n", "# comment\n   # indented comment\n"])
@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_empty_local_config_keeps_defaults(
    tmp_path: Path, isolated_skill: Path, script_name: str, text: str | None
) -> None:
    """No file, an empty file, or comments only leave the shared defaults in effect."""
    if text is not None:
        write_local_config(isolated_skill, text)
    result = run_review_script(tmp_path, script_name, post_comment=True)

    assert result.returncode == 0, result.stderr
    assert "review-count: 1/3\n" in result.stdout
    assert "Write the review comment in Japanese." in result.stdout
    assert "--effort medium" in result.stdout or "model_reasoning_effort=medium" in result.stdout


LOCAL_CLAUDE_CONFIG = """\
REVIEW_LANGUAGE = English
MAX_REVIEWS=5
REVIEW_BODY_DIR=drafts
REVIEW_BODY_NOT_IGNORED=warn
REVIEW_BODY_PATH_ENFORCED=false
CLAUDE_MODEL=local-model
CLAUDE_EFFORT=high
CLAUDE_PERMISSION_MODE=plan
"""

LOCAL_CODEX_CONFIG = """\
CODEX_MODEL=local-codex
CODEX_EFFORT=low
CODEX_SANDBOX=workspace-write
CODEX_NETWORK_ACCESS=false
CODEX_TIMEOUT_SECONDS=900
CODEX_HEARTBEAT_TIMEOUT_SECONDS=300
"""


def test_local_config_overrides_claude_and_common_keys(tmp_path: Path, isolated_skill: Path) -> None:
    """Every common and Claude key can be overridden, with CRLF line endings."""
    write_local_config(isolated_skill, LOCAL_CLAUDE_CONFIG, newline="\r\n")
    result = run_review_script(tmp_path, "run_claude_review.sh", post_comment=True, ignore_body_dir=False)

    assert result.returncode == 0, result.stderr
    assert "--model local-model --effort high --permission-mode plan" in result.stdout
    assert "Write the review comment in English." in result.stdout
    assert "review-count: 1/5\n" in result.stdout
    assert "drafts/pr-123-review-claude.md" in result.stdout
    assert "warning: review body file is not ignored by git" in result.stderr


def test_local_config_overrides_codex_keys(tmp_path: Path, isolated_skill: Path) -> None:
    """Every Codex key can be overridden, and unset keys keep their defaults."""
    write_local_config(isolated_skill, LOCAL_CODEX_CONFIG)
    result = run_review_script(tmp_path, "run_codex_review.sh", post_comment=True)

    assert result.returncode == 0, result.stderr
    assert (
        "--model local-codex -c model_reasoning_effort=low --sandbox workspace-write "
        "-c sandbox_workspace_write.network_access=false"
    ) in result.stdout
    assert "hard timeout: 900s, heartbeat (no-progress) timeout: 300s" in result.stderr
    assert "review-count: 1/3\n" in result.stdout
    assert "Write the review comment in Japanese." in result.stdout


@pytest.mark.parametrize(
    ("script_name", "expected"),
    [
        ("run_claude_review.sh", "--model cli-model --effort low --permission-mode plan"),
        ("run_codex_review.sh", "--model cli-model -c model_reasoning_effort=low --sandbox read-only"),
    ],
)
def test_cli_options_override_local_config(
    tmp_path: Path, isolated_skill: Path, script_name: str, expected: str
) -> None:
    """A command-line option wins over the same key in config.local.conf."""
    codex_config = LOCAL_CODEX_CONFIG.replace("CODEX_SANDBOX=workspace-write", "CODEX_SANDBOX=read-only")
    write_local_config(isolated_skill, LOCAL_CLAUDE_CONFIG + codex_config)
    result = run_review_script(
        tmp_path, script_name, post_comment=True, ignore_body_dir=False,
        extra_args=("--model", "cli-model", "--effort", "low"),
    )

    assert result.returncode == 0, result.stderr
    assert expected in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_local_max_reviews_sets_normal_limit(
    tmp_path: Path, isolated_skill: Path, script_name: str
) -> None:
    """With MAX_REVIEWS=5, a normal review runs after 4 reviews and is rejected after 5."""
    write_local_config(isolated_skill, "MAX_REVIEWS=5\n")
    four = tuple(str(n) * 40 for n in range(1, 5))
    result = run_review_script(tmp_path / "four", script_name, post_comment=True, existing_review_commits=four)
    assert result.returncode == 0, result.stderr
    assert "review-count: 5/5\n" in result.stdout

    five = (*four, PREVIOUS_COMMIT)
    result = run_review_script(tmp_path / "five", script_name, post_comment=True, existing_review_commits=five)
    assert result.returncode == 1
    assert "the maximum is 5" in result.stderr
    assert "prompt:" not in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_local_max_reviews_sets_extra_review_threshold(
    tmp_path: Path, isolated_skill: Path, script_name: str
) -> None:
    """With MAX_REVIEWS=5, --extra-review is rejected after 4 reviews and runs after 5 as 6/5."""
    write_local_config(isolated_skill, "MAX_REVIEWS=5\n")
    four = tuple(str(n) * 40 for n in range(1, 5))
    result = run_review_script(
        tmp_path / "four", script_name, post_comment=True,
        existing_review_commits=four, extra_args=("--extra-review",),
    )
    assert result.returncode == 1
    assert "has 4 of 5 cross-reviews" in result.stderr

    result = run_review_script(
        tmp_path / "five", script_name, post_comment=True,
        existing_review_commits=(*four, PREVIOUS_COMMIT), extra_args=("--extra-review",),
    )
    assert result.returncode == 0, result.stderr
    assert "review-count: 6/5\n" in result.stdout


def test_review_status_uses_local_max_reviews(tmp_path: Path, isolated_skill: Path) -> None:
    """review_status.sh shows the same effective limit as the run scripts."""
    write_local_config(isolated_skill, "MAX_REVIEWS=5\n")
    result = run_review_script(
        tmp_path, "review_status.sh", post_comment=False,
        existing_review_commits=tuple(str(n) * 40 for n in range(1, 6)),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("review-count: 5/5\nreview-extra: 0\n")


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_body_dir_with_spaces_can_be_posted(
    tmp_path: Path, isolated_skill: Path, script_name: str
) -> None:
    """The reviewer can post the generated body from a directory whose name has spaces."""
    write_local_config(isolated_skill, "REVIEW_BODY_DIR=tmp/review drafts\n")
    result = run_review_script(tmp_path, script_name, post_comment=True, run_post=True)

    assert result.returncode == 0, result.stderr
    assert "tmp/review drafts/pr-123-review-" in result.stdout
    assert "posted-body: review body\n" in result.stdout


def test_post_comment_uses_local_path_enforcement(tmp_path: Path, isolated_skill: Path) -> None:
    """REVIEW_BODY_PATH_ENFORCED from config.local.conf applies to post_pr_comment.sh."""
    (tmp_path / "other.md").write_text("other body\nreview-findings: must=0 optional=0\n", encoding="utf-8")
    result = run_post_comment_script(tmp_path, HEAD_COMMIT, body_arg="other.md")
    assert result.returncode == 1
    assert "the body file must be" in result.stderr

    write_local_config(isolated_skill, "REVIEW_BODY_PATH_ENFORCED=false\n")
    result = run_post_comment_script(tmp_path, HEAD_COMMIT, body_arg="other.md")
    assert result.returncode == 0, result.stderr
    assert "other body" in result.stdout


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("UNKNOWN_KEY=1\n", "line 1: unknown key: UNKNOWN_KEY"),
        ("# ok\nMAX_REVIEWS=4\nMAX_REVIEWS=5\n", "line 3: duplicate key: MAX_REVIEWS"),
        ("CLAUDE_MODEL=  \n", "line 1: empty value for CLAUDE_MODEL"),
        ("CLAUDE_MODEL\n", "line 1: expected KEY=value"),
        ("=opus\n", "line 1: missing key"),
        ("export CLAUDE_MODEL=opus\n", "line 1: unknown key: export CLAUDE_MODEL"),
        ("REVIEW_LANGUAGE MAX_REVIEWS=5\n", "line 1: unknown key: REVIEW_LANGUAGE MAX_REVIEWS"),
    ],
)
@pytest.mark.parametrize("script_name", [*SCRIPT_NAMES, "review_status.sh", "post_pr_comment.sh"])
def test_invalid_local_config_is_rejected_first(
    tmp_path: Path, isolated_skill: Path, script_name: str, text: str, reason: str
) -> None:
    """Syntax and key errors stop every script with exit 1 before GitHub or a reviewer is used."""
    write_local_config(isolated_skill, text)
    if script_name == "post_pr_comment.sh":
        result = run_post_comment_script(tmp_path, HEAD_COMMIT)
    else:
        result = run_review_script(tmp_path, script_name, post_comment=True)
        assert "api-calls: 0" in result.stdout

    assert result.returncode == 1
    assert result.stderr.strip() == f"error: config.local.conf: {reason}"
    assert "prompt:" not in result.stdout
    assert "review body" not in result.stdout


@pytest.mark.parametrize("value", ["0", "05", "-1", "2147483648", "1.5", "five", "+3"])
@pytest.mark.parametrize("script_name", [*SCRIPT_NAMES, "review_status.sh"])
def test_invalid_max_reviews_is_rejected(
    tmp_path: Path, isolated_skill: Path, script_name: str, value: str
) -> None:
    """MAX_REVIEWS must be a decimal integer from 1 to 2147483647 without leading zeros."""
    write_local_config(isolated_skill, f"MAX_REVIEWS={value}\n")
    result = run_review_script(tmp_path, script_name, post_comment=True)

    assert result.returncode == 1
    assert (
        f"MAX_REVIEWS must be an integer from 1 to 2147483647 without leading zeros, got: {value}"
        in result.stderr
    )
    assert "api-calls: 0" in result.stdout


def test_max_reviews_accepts_upper_bound(tmp_path: Path, isolated_skill: Path) -> None:
    """The largest allowed limit is accepted."""
    write_local_config(isolated_skill, "MAX_REVIEWS=2147483647\n")
    result = run_review_script(tmp_path, "review_status.sh", post_comment=False)

    assert result.returncode == 0, result.stderr
    assert "review-count: 0/2147483647\n" in result.stdout


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_local_config_values_are_literal(
    tmp_path: Path, isolated_skill: Path, script_name: str
) -> None:
    """Shell syntax, quotes, `=` and `#` in a value are kept and never executed."""
    marker = tmp_path / "executed"
    value = f'"x" $(touch {marker.as_posix()}) `touch {marker.as_posix()}` a=b # c'
    write_local_config(isolated_skill, f"REVIEW_LANGUAGE= {value} \n")
    result = run_review_script(tmp_path, script_name, post_comment=True)

    assert result.returncode == 0, result.stderr
    assert f"Write the review comment in {value}." in result.stdout
    assert not marker.exists()


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_body_dir_shell_syntax_is_not_run_when_posting(
    tmp_path: Path, isolated_skill: Path, script_name: str
) -> None:
    """Shell syntax in REVIEW_BODY_DIR stays literal in the post command the reviewer runs."""
    write_local_config(isolated_skill, "REVIEW_BODY_DIR=tmp/$(touch marker) `touch marker2` $HOME\n")
    result = run_review_script(tmp_path, script_name, post_comment=True, run_post=True)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "posted-body: review body\n" in result.stdout
    assert not (tmp_path / "marker").exists()
    assert not (tmp_path / "marker2").exists()


@pytest.mark.parametrize("script_name", SCRIPT_NAMES)
def test_body_dir_with_single_quote_is_rejected(
    tmp_path: Path, isolated_skill: Path, script_name: str
) -> None:
    """A body path that cannot be single-quoted for both shells stops the run before GitHub."""
    write_local_config(isolated_skill, "REVIEW_BODY_DIR=tmp/it's\n")
    result = run_review_script(tmp_path, script_name, post_comment=True)

    assert result.returncode == 1
    assert "must not contain a single quote" in result.stderr
    assert "api-calls: 0" in result.stdout


def test_unreadable_local_config_is_rejected(tmp_path: Path, isolated_skill: Path) -> None:
    """A config.local.conf that is not a readable file stops the script."""
    (isolated_skill / "config.local.conf").mkdir()
    result = run_review_script(tmp_path, "review_status.sh", post_comment=False)

    assert result.returncode == 1
    assert result.stderr.startswith("error: config.local.conf: cannot read ")
    assert "api-calls: 0" in result.stdout
