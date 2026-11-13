#!/usr/bin/env bash
# Launch Claude Code non-interactively to review a pull request of the current
# checkout's repository, and confirm that it posted the review comment.
#
# Usage:
#   run_claude_review.sh <pr-number> [options] [-- <extra instructions>]
#
# Options (defaults come from config.local.conf, then config.conf):
#   --model <model>            CLAUDE_MODEL
#   --effort <effort>          CLAUDE_EFFORT (low|medium|high|xhigh|max)
#   --permission-mode <mode>   CLAUDE_PERMISSION_MODE
#   --extra-review             Run one user-approved review beyond MAX_REVIEWS
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
extra_review="false"
extra_instructions=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --extra-review)
            extra_review="true"
            shift
            ;;
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
prepare_review_context "$repo" "$pr_number" claude "$extra_review"
prepare_body_file "$pr_number" claude
build_review_prompt "$pr_number" claude "$extra_instructions"
export_review_environment

# The reviewer's final reply repeats the posted review, so it is kept out of
# this script's output: it goes to a temp log that is always removed, and its
# tail is printed to stderr only on failure.
log_file=$(mktemp)

cleanup() {
    stop_reviewer
    rm -f "$log_file"
}
trap cleanup EXIT INT TERM

start_reviewer claude -p --model "$model" --effort "$effort" --permission-mode "$permission_mode" "$REVIEW_PROMPT" >"$log_file" 2>&1

finish_review "$repo" "$pr_number" claude "claude -p" "$log_file"
