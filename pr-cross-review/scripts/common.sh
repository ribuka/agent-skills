#!/usr/bin/env bash
# Shared helpers for run_codex_review.sh and run_claude_review.sh.
#
# Sourced, not executed. Provides config loading, option validation, the
# review-history lookup (review count limit / incremental re-review), the
# reviewer prompt, process-group management, and the check that the reviewer
# actually posted a new comment.

skill_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
config_file="${skill_dir}/config.env"
post_script="${skill_dir}/scripts/post_pr_comment.sh"
in_progress_variable="PR_CROSS_REVIEW_IN_PROGRESS"

die() {
    echo "error: $*" >&2
    exit 1
}

# load_config KEY... -- source config.env and require every listed key.
# The keys are unset first so that a stray environment variable cannot stand
# in for a value missing from config.env.
load_config() {
    local key
    [ -f "$config_file" ] || die "config file not found: $config_file"
    for key in "$@"; do
        unset "$key"
    done
    # Strip CR so that a config.env saved with CRLF line endings still works.
    # shellcheck source=/dev/null
    source <(tr -d '\r' <"$config_file")
    for key in "$@"; do
        [ -n "${!key:-}" ] || die "${key} is not set in ${config_file}"
    done
}

require_value() {
    if [ "$#" -lt 2 ]; then
        die "$1 requires a value"
    fi
}

require_positive_int() {
    if ! [[ "$2" =~ ^[0-9]+$ ]] || [ "$2" -le 0 ]; then
        die "$1 must be a positive integer, got: $2"
    fi
}

reject_nested_review() {
    if [ -n "${!in_progress_variable:-}" ]; then
        die "nested review launch is not allowed while ${in_progress_variable} is set"
    fi
}

# Print a path in a form both bash and PowerShell can run (C:/... on Windows).
native_path() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -m "$1"
    else
        printf '%s\n' "$1"
    fi
}

review_agent_label() {
    case "$1" in
        codex) printf '%s\n' 'Codex' ;;
        claude) printf '%s\n' 'Claude' ;;
        *)
            echo "error: unknown review agent: $1" >&2
            return 1
            ;;
    esac
}

# One line per past cross-review comment: <id> TAB <url> TAB <sha> TAB <agent>.
# Comments are recognised by the footer post_pr_comment.sh appends.
list_review_history() {
    local repo=$1
    local pr_number=$2
    local jq_filter

    jq_filter='.[] | (.body | try capture("_Reviewed by (?<agent>Codex|Claude)\\. Posted via pr-cross-review skill\\._\\r?\\nReviewed commit: (?<sha>[0-9a-fA-F]{40})\\r?\\n?$") catch empty) as $footer | [.id, .html_url, $footer.sha, $footer.agent] | @tsv'
    gh api --paginate "repos/${repo}/issues/${pr_number}/comments" --jq "$jq_filter"
}

list_review_comments() {
    local repo=$1
    local pr_number=$2
    local agent=$3
    local agent_label
    local review_history

    agent_label=$(review_agent_label "$agent")
    review_history=$(list_review_history "$repo" "$pr_number") || return $?
    printf '%s\n' "$review_history" |
        awk -F '\t' -v agent="$agent_label" '$4 == agent { print $1 "\t" $2 }'
}

find_new_review_comment_url() {
    local repo=$1
    local pr_number=$2
    local agent=$3
    local previous_ids=$4
    local comment_id
    local comment_url
    local comments

    if ! comments=$(list_review_comments "$repo" "$pr_number" "$agent"); then
        echo "error: failed to query review comments for PR #${pr_number}" >&2
        return 2
    fi

    while IFS=$'\t' read -r comment_id comment_url; do
        if [ -z "$comment_id" ]; then
            continue
        fi

        case $'\n'"${previous_ids}"$'\n' in
            *$'\n'"${comment_id}"$'\n'*) ;;
            *)
                printf '%s\n' "$comment_url"
                return 0
                ;;
        esac
    done <<<"$comments"

    return 1
}

# Sets REVIEW_HEAD_COMMIT, REVIEW_COUNT, PREVIOUS_REVIEW_COMMIT and
# REVIEW_COMMENT_IDS_BEFORE, and rejects the run when the PR already reached
# MAX_REVIEWS or has no commits since the previous review.
prepare_review_context() {
    local repo=$1
    local pr_number=$2
    local agent=$3
    local agent_label
    local review_history

    REVIEW_HEAD_COMMIT=$(
        gh pr view "$pr_number" --repo "$repo" --json headRefOid --jq .headRefOid
    )
    if ! [[ "$REVIEW_HEAD_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]]; then
        echo "error: failed to resolve the 40-character headRefOid for PR #${pr_number}" >&2
        return 2
    fi

    if ! review_history=$(list_review_history "$repo" "$pr_number"); then
        echo "error: failed to query review history for PR #${pr_number}" >&2
        return 2
    fi

    REVIEW_COUNT=$(
        printf '%s\n' "$review_history" | awk 'NF { count++ } END { print count + 0 }'
    )
    if [ "$REVIEW_COUNT" -ge "$MAX_REVIEWS" ]; then
        echo "error: PR #${pr_number} already has ${REVIEW_COUNT} cross-reviews; the maximum is ${MAX_REVIEWS}" >&2
        return 1
    fi

    PREVIOUS_REVIEW_COMMIT=$(
        printf '%s\n' "$review_history" | awk -F '\t' 'NF { commit=$3 } END { print commit }'
    )
    if [ "$REVIEW_COUNT" -gt 0 ] && [ -z "$PREVIOUS_REVIEW_COMMIT" ]; then
        echo "error: the previous review comment does not record a Reviewed commit" >&2
        return 1
    fi
    if [ "$PREVIOUS_REVIEW_COMMIT" = "$REVIEW_HEAD_COMMIT" ]; then
        echo "error: PR #${pr_number} has no commits after the previous review (${REVIEW_HEAD_COMMIT})" >&2
        return 1
    fi

    agent_label=$(review_agent_label "$agent")
    REVIEW_COMMENT_IDS_BEFORE=$(
        printf '%s\n' "$review_history" |
            awk -F '\t' -v agent="$agent_label" '$4 == agent { print $1 }'
    )
}

# build_review_prompt <pr-number> <agent> <extra-instructions> -- sets REVIEW_PROMPT.
build_review_prompt() {
    local pr_number=$1
    local agent=$2
    local extra_instructions=$3
    local post_command

    if [ "$REVIEW_COUNT" -eq 0 ]; then
        REVIEW_PROMPT="Review PR #${pr_number} of this repository. Examine the whole diff of the PR."
    else
        REVIEW_PROMPT="Re-review PR #${pr_number} of this repository. The scope is limited to the diff ${PREVIOUS_REVIEW_COMMIT}..${REVIEW_HEAD_COMMIT} and the findings of the previous review. Check whether the previous findings have been resolved and whether the fixes introduced new problems. Do not raise new findings about existing code outside that diff."
    fi
    REVIEW_PROMPT+=" Write the review comment in ${REVIEW_LANGUAGE}."

    post_command="bash \"$(native_path "$post_script")\" ${pr_number} <body-file> ${agent}"
    REVIEW_PROMPT+=$'\n'"When the review is done, write the comment body to a file and post it with exactly this command (do not use \`gh pr comment\` directly): ${post_command}"

    if [ -n "$extra_instructions" ]; then
        REVIEW_PROMPT+=$'\n\n'"Additional instructions: ${extra_instructions}"
    fi
}

# Marks the environment the reviewer inherits: blocks nested reviews and tells
# post_pr_comment.sh which commit was reviewed.
export_review_environment() {
    export "${in_progress_variable}=1"
    export PR_CROSS_REVIEW_REVIEWED_COMMIT="$REVIEW_HEAD_COMMIT"
}

# start_reviewer <command> [args...] -- sets REVIEWER_PID.
# The reviewer runs in its own process group (via job control) so that a kill
# also reaches the tool/shell processes it spawns, before they can post a late
# comment.
# stdin is /dev/null: with job control on, bash does not redirect a background
# job's stdin, and `codex exec` waits for EOF on a non-terminal stdin even when
# the prompt is passed as an argument -- an open pipe would hang it forever.
start_reviewer() {
    set -m
    "$@" </dev/null &
    REVIEWER_PID=$!
    set +m
}

stop_reviewer() {
    if [ -z "${REVIEWER_PID:-}" ]; then
        return 0
    fi
    if kill -0 "$REVIEWER_PID" 2>/dev/null; then
        kill -TERM -- "-${REVIEWER_PID}" 2>/dev/null || kill -TERM "$REVIEWER_PID" 2>/dev/null || true
        sleep 2
        kill -KILL -- "-${REVIEWER_PID}" 2>/dev/null || kill -KILL "$REVIEWER_PID" 2>/dev/null || true
    fi
    wait "$REVIEWER_PID" 2>/dev/null || true
}

# report_posted_review <repo> <pr-number> <agent> -- prints `review-posted: <url>`
# and returns 0 when the reviewer posted a new comment; otherwise returns
# 1 (no new comment) or 2 (lookup failed).
report_posted_review() {
    local repo=$1
    local pr_number=$2
    local agent=$3
    local comment_url
    local status

    if comment_url=$(find_new_review_comment_url "$repo" "$pr_number" "$agent" "$REVIEW_COMMENT_IDS_BEFORE"); then
        echo "review-posted: ${comment_url}"
        return 0
    else
        status=$?
    fi

    if [ "$status" -eq 1 ]; then
        echo "error: $(review_agent_label "$agent") exited successfully, but no new review comment was found for PR #${pr_number}" >&2
    fi
    return "$status"
}
