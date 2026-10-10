#!/usr/bin/env bash
# Launch Claude Code non-interactively to review a pull request of the current
# checkout's repository, and confirm that it posted the review comment.
#
# Usage:
#   run_claude_review.sh <pr-number> [options] [-- <extra instructions>]
#
# Options (defaults come from config.env):
#   --model <model>            CLAUDE_MODEL
#   --effort <effort>          CLAUDE_EFFORT (low|medium|high|xhigh|max)
#   --permission-mode <mode>   CLAUDE_PERMISSION_MODE
#
# Anything after a literal `--` is appended to the review prompt.

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "${script_dir}/common.sh"

reject_nested_review

if [ "$#" -lt 1 ]; then
    die "usage: $0 <pr-number> [options] [-- <extra instructions>]"
fi

pr_number=$1
shift
require_positive_int "<pr-number>" "$pr_number"

load_config REVIEW_LANGUAGE MAX_REVIEWS REVIEW_BODY_DIR REVIEW_BODY_NOT_IGNORED CLAUDE_MODEL CLAUDE_EFFORT CLAUDE_PERMISSION_MODE

model=$CLAUDE_MODEL
effort=$CLAUDE_EFFORT
permission_mode=$CLAUDE_PERMISSION_MODE
extra_instructions=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --model)
            require_value "$@"
            model=$2
            shift 2
            ;;
        --effort)
            require_value "$@"
            effort=$2
            shift 2
            ;;
        --permission-mode)
            require_value "$@"
            permission_mode=$2
            shift 2
            ;;
        --)
            shift
            extra_instructions="$*"
            break
            ;;
        *)
            die "unknown option: $1"
            ;;
    esac
done

command -v claude >/dev/null 2>&1 || die "claude command not found in PATH"

repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
prepare_review_context "$repo" "$pr_number" claude
prepare_body_file "$pr_number" claude
build_review_prompt "$pr_number" claude "$extra_instructions"
export_review_environment

trap stop_reviewer EXIT INT TERM

start_reviewer claude -p --model "$model" --effort "$effort" --permission-mode "$permission_mode" "$REVIEW_PROMPT"

set +e
wait "$REVIEWER_PID"
exit_code=$?
set -e

if [ "$exit_code" -ne 0 ]; then
    exit "$exit_code"
fi

set +e
report_posted_review "$repo" "$pr_number" claude
status=$?
set -e
if [ "$status" -eq 0 ]; then
    remove_body_file
fi
exit "$status"
