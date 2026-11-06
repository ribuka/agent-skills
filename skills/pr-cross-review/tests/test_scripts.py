"""Tests for the pr-cross-review scripts, using fake gh/codex/claude commands.

Run with: uv run --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
HEAD_COMMIT = "b" * 40
PREVIOUS_COMMIT = "a" * 40
EXPLORATION_SCOPE = (
    "Read code outside the diff only as far as needed to verify a finding "
    "(such as callers and dependencies of the changed code); do not explore the rest of the repository."
)


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
                printf '%s\thttps://github.com/owner/repo/pull/123#issuecomment-%s\t%s\t%s\n' \
                    "$comment_id" "$comment_id" "$commit" "$REVIEW_AGENT_LABEL"
            done
            if [ -f "$REVIEW_STATE_FILE" ]; then
                printf '1001\thttps://github.com/owner/repo/pull/123#issuecomment-1001\t%s\t%s\n' \
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
def test_review_script_reports_new_comment_url(tmp_path: Path, script_name: str) -> None:
    """A newly posted review comment is reported as successful completion."""
    result = run_review_script(tmp_path, script_name, post_comment=True)

    assert result.returncode == 0, result.stderr
    assert "review-posted: https://github.com/owner/repo/pull/123#issuecomment-1001\n" in result.stdout
    assert "review-count: 1/3\n" in result.stdout
    assert f"reviewed-commit: {HEAD_COMMIT}" in result.stdout
    assert "Examine the whole diff" in result.stdout
    assert EXPLORATION_SCOPE in result.stdout
    assert "post_pr_comment.sh\" 123 \"" in result.stdout
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
def test_review_script_distinguishes_api_failure(tmp_path: Path, script_name: str) -> None:
    """A GitHub API failure is reported separately from a missing comment."""
    result = run_review_script(
        tmp_path, script_name, post_comment=True, api_failure_after_review=True
    )

    assert result.returncode == 2
    assert "failed to query review comments" in result.stderr
    assert "no new review comment was found" not in result.stderr
    assert "review-posted:" not in result.stdout


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
) -> subprocess.CompletedProcess[str]:
    """Run post_pr_comment.sh with a fake GitHub CLI.

    The assigned body file is tmp_path/body.md; body_arg overrides the path
    passed to the script.
    """
    body_file = tmp_path / "body.md"
    body_file.write_text("review body", encoding="utf-8")
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
