#!/usr/bin/env bash
# Shared helpers for run_codex_review.sh and run_claude_review.sh.
#
# Sourced, not executed. Provides config loading, option validation, the
# review-history lookup (review count limit / incremental re-review), the
# reviewer prompt, process-group management, the bounded reviewer log dump, and
# the check that the reviewer actually posted a new comment.

skill_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
config_file="${skill_dir}/config.conf"
local_config_file="${skill_dir}/config.local.conf"
post_script="${skill_dir}/scripts/post_pr_comment.sh"
in_progress_variable="PR_CROSS_REVIEW_IN_PROGRESS"

# Every key config.conf and config.local.conf may set.
config_keys=(
    REVIEW_LANGUAGE MAX_REVIEWS REVIEW_BODY_DIR REVIEW_BODY_NOT_IGNORED REVIEW_BODY_PATH_ENFORCED
    CODEX_MODEL CODEX_EFFORT CODEX_SANDBOX CODEX_NETWORK_ACCESS CODEX_TIMEOUT_SECONDS
    CODEX_HEARTBEAT_TIMEOUT_SECONDS
    CLAUDE_MODEL CLAUDE_EFFORT CLAUDE_PERMISSION_MODE
)
max_int32=2147483647

die() {
    echo "error: $*" >&2
    exit 1
}

# read_config_file <file> -- validate the whole file and store its values in
# config_values. Lines are KEY=value (LF or CRLF); blank lines and lines whose
# first non-blank character is `#` are skipped. Key and value are trimmed, and
# everything after the first `=` is taken literally: no shell evaluation, quote
# removal, or inline comments.
read_config_file() {
    local file=$1
    local name
    local line
    local line_number=0
    local key
    local value
    local -A seen=()

    name=$(basename -- "$file")
    [ -f "$file" ] && [ -r "$file" ] || die "${name}: cannot read ${file}"
    { : <"$file"; } 2>/dev/null || die "${name}: cannot read ${file}"
    while IFS= read -r line || [ -n "$line" ]; do
        line_number=$((line_number + 1))
        line=${line%$'\r'}
        [[ "$line" =~ ^[[:space:]]*(#.*)?$ ]] && continue
        [[ "$line" == *=* ]] || die "${name}: line ${line_number}: expected KEY=value"
        key=${line%%=*}
        value=${line#*=}
        [[ "$key" =~ ^[[:space:]]*([^[:space:]].*[^[:space:]]|[^[:space:]])[[:space:]]*$ ]] \
            || die "${name}: line ${line_number}: missing key"
        key=${BASH_REMATCH[1]}
        if [[ "$value" =~ ^[[:space:]]*([^[:space:]].*[^[:space:]]|[^[:space:]])[[:space:]]*$ ]]; then
            value=${BASH_REMATCH[1]}
        else
            die "${name}: line ${line_number}: empty value for ${key}"
        fi
        case " ${config_keys[*]} " in
            *" ${key} "*) ;;
            *) die "${name}: line ${line_number}: unknown key: ${key}" ;;
        esac
        [ -z "${seen[$key]:-}" ] || die "${name}: line ${line_number}: duplicate key: ${key}"
        seen[$key]=1
        config_values[$key]=$value
    done <"$file"
}

# load_config KEY... -- read config.conf, then config.local.conf when present
# (its keys override config.conf), validate both files whole, and set every
# listed key as a shell variable. No value comes from the environment.
load_config() {
    local key
    declare -gA config_values=()
    read_config_file "$config_file"
    if [ -e "$local_config_file" ] || [ -L "$local_config_file" ]; then
        read_config_file "$local_config_file"
    fi
    for key in "$@"; do
        [ -n "${config_values[$key]:-}" ] || die "${key} is not set in ${config_file}"
        printf -v "$key" '%s' "${config_values[$key]}"
    done
    if [ -n "${config_values[MAX_REVIEWS]:-}" ]; then
        require_max_reviews "${config_values[MAX_REVIEWS]}"
    fi
}

# MAX_REVIEWS: a decimal integer without leading zeros, 1..2147483647.
require_max_reviews() {
    if ! [[ "$1" =~ ^[1-9][0-9]{0,9}$ ]] || [ "$1" -gt "$max_int32" ]; then
        die "MAX_REVIEWS must be an integer from 1 to ${max_int32} without leading zeros, got: $1"
    fi
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

# One line per cross-review: <id> TAB <url> TAB <sha> TAB <agent> TAB <findings>.
# Findings are `must=<n> optional=<n>`, or `unknown` for historical comments.
# Comments are recognised by the footer post_pr_comment.sh appends.
list_review_history() {
    local repo=$1
    local pr_number=$2
    local jq_filter

    jq_filter='.[] | (.body | try capture("_Reviewed by (?<agent>Codex|Claude)\\. Posted via pr-cross-review skill\\._\\r?\\nReviewed commit: (?<sha>[0-9a-fA-F]{40})(?:\\r?\\nreview-findings: (?<findings>must=[0-9]+ optional=[0-9]+))?\\r?\\n?$") catch empty) as $footer | [.id, .html_url, $footer.sha, $footer.agent, ($footer.findings // "unknown")] | @tsv'
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
        awk -F '\t' -v agent="$agent_label" '$4 == agent { print $1 "\t" $2 "\t" $5 }'
}

find_new_review_comment() {
    local repo=$1
    local pr_number=$2
    local agent=$3
    local previous_ids=$4
    local comment_id
    local comment_url
    local findings
    local comments

    if ! comments=$(list_review_comments "$repo" "$pr_number" "$agent"); then
        echo "error: failed to query review comments for PR #${pr_number}" >&2
        return 2
    fi

    while IFS=$'\t' read -r comment_id comment_url findings; do
        if [ -z "$comment_id" ]; then
            continue
        fi

        case $'\n'"${previous_ids}"$'\n' in
            *$'\n'"${comment_id}"$'\n'*) ;;
            *)
                printf '%s\t%s\n' "$comment_url" "$findings"
                return 0
                ;;
        esac
    done <<<"$comments"

    return 1
}

# prepare_review_context <repo> <pr-number> <agent> <extra-review: true|false>
# Sets REVIEW_HEAD_COMMIT, REVIEW_COUNT, PREVIOUS_REVIEW_COMMIT and
# REVIEW_COMMENT_IDS_BEFORE, and rejects the run when the PR has no commits
# since the previous review, or when it already reached MAX_REVIEWS (without
# --extra-review) or has not reached it yet (with --extra-review).
prepare_review_context() {
    local repo=$1
    local pr_number=$2
    local agent=$3
    local extra_review=$4
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
    if [ "$extra_review" = "true" ]; then
        if [ "$REVIEW_COUNT" -lt "$MAX_REVIEWS" ]; then
            echo "error: --extra-review is only for a review beyond the limit; PR #${pr_number} has ${REVIEW_COUNT} of ${MAX_REVIEWS} cross-reviews" >&2
            return 1
        fi
    elif [ "$REVIEW_COUNT" -ge "$MAX_REVIEWS" ]; then
        echo "error: PR #${pr_number} already has ${REVIEW_COUNT} cross-reviews; the maximum is ${MAX_REVIEWS} (a user-approved extra review needs --extra-review)" >&2
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

require_choice() {
    local name=$1
    local value=$2
    shift 2
    local choice
    for choice in "$@"; do
        if [ "$value" = "$choice" ]; then
            return 0
        fi
    done
    die "${name} must be one of: $*; got: ${value}"
}

# prepare_body_file <pr-number> <agent> -- sets REVIEW_BODY_FILE.
# Resolves REVIEW_BODY_DIR from the repository root, checks that the body file
# would be ignored by git (REVIEW_BODY_NOT_IGNORED decides error or warning),
# creates the directory and removes a stale body file from an earlier run.
prepare_body_file() {
    local pr_number=$1
    local agent=$2
    local repo_root
    local body_dir

    require_choice REVIEW_BODY_NOT_IGNORED "$REVIEW_BODY_NOT_IGNORED" error warn
    repo_root=$(git rev-parse --show-toplevel) || die "not inside a git repository"

    case "$REVIEW_BODY_DIR" in
        /* | [A-Za-z]:[/\\]*) body_dir=$REVIEW_BODY_DIR ;;
        *) body_dir="${repo_root}/${REVIEW_BODY_DIR}" ;;
    esac
    REVIEW_BODY_FILE="${body_dir%/}/pr-${pr_number}-review-${agent}.md"

    # Exit status 0: ignored, 1: not ignored, 128: e.g. outside the repository,
    # where git cannot commit it anyway.
    local ignore_status=0
    git -C "$repo_root" check-ignore -q -- "$REVIEW_BODY_FILE" 2>/dev/null || ignore_status=$?
    if [ "$ignore_status" -eq 1 ]; then
        if [ "$REVIEW_BODY_NOT_IGNORED" = "error" ]; then
            die "review body file is not ignored by git: ${REVIEW_BODY_FILE} (add ${REVIEW_BODY_DIR}/ to .gitignore, or set REVIEW_BODY_NOT_IGNORED=warn)"
        fi
        echo "warning: review body file is not ignored by git: ${REVIEW_BODY_FILE}" >&2
    fi

    mkdir -p -- "$body_dir"
    rm -f -- "$REVIEW_BODY_FILE"
}

remove_body_file() {
    rm -f -- "$REVIEW_BODY_FILE"
}

# build_review_prompt <pr-number> <agent> <extra-instructions> -- sets REVIEW_PROMPT.
build_review_prompt() {
    local pr_number=$1
    local agent=$2
    local extra_instructions=$3
    local body_file
    local post_command

    if [ "$REVIEW_COUNT" -eq 0 ]; then
        REVIEW_PROMPT="Review PR #${pr_number} of this repository. Examine the whole diff of the PR."
    else
        REVIEW_PROMPT="Re-review PR #${pr_number} of this repository. The scope is limited to the diff ${PREVIOUS_REVIEW_COMMIT}..${REVIEW_HEAD_COMMIT} and the must findings of the previous review. Check whether the previous must findings have been resolved and whether the fixes introduced new problems. Do not raise new findings about existing code outside that diff."
    fi
    REVIEW_PROMPT+=" Read code outside the diff only as far as needed to verify a finding (such as callers and dependencies of the changed code); do not explore the rest of the repository."
    REVIEW_PROMPT+=" Write the review comment in ${REVIEW_LANGUAGE}."
    REVIEW_PROMPT+=" Classify every finding as [must] or [optional], placed at the start of its heading. [must] means it must be fixed before merging: bugs or incorrect behavior, unmet Issue specifications or acceptance criteria, missing required tests, security or data-loss risks, and misleading instructions or documentation errors. [optional] means merging is acceptable without the change: wording, naming, organization, reducing duplication, extra tests beyond requirements, and improvements for future changes. Do not use P0-P3 or other severity labels. End the body with exactly one count line as its last non-empty line: review-findings: must=<n> optional=<n> (non-negative integers; both 0 when there are no findings). On re-review, count only unresolved must findings from the previous review and new findings in this diff; do not repeat previous optional suggestions that were not adopted."

    body_file=$(native_path "$REVIEW_BODY_FILE")
    post_command="bash \"$(native_path "$post_script")\" ${pr_number} \"${body_file}\" ${agent}"
    REVIEW_PROMPT+=$'\n'"When the review is done, write the comment body to exactly this file (its directory already exists; do not write it anywhere else): ${body_file}"
    REVIEW_PROMPT+=$'\n'"Then post it with exactly this command (do not use \`gh pr comment\` directly): ${post_command}"

    if [ -n "$extra_instructions" ]; then
        REVIEW_PROMPT+=$'\n\n'"Additional instructions: ${extra_instructions}"
    fi
}

# Marks the environment the reviewer inherits: blocks nested reviews and tells
# post_pr_comment.sh which commit was reviewed and where the body file must be.
export_review_environment() {
    export "${in_progress_variable}=1"
    export PR_CROSS_REVIEW_REVIEWED_COMMIT="$REVIEW_HEAD_COMMIT"
    export PR_CROSS_REVIEW_BODY_FILE="$REVIEW_BODY_FILE"
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

# The reviewer's own output is kept out of the caller's output: the scripts
# write it to a temp log that is always removed, and dump only its tail on
# failure. A single line (for example a JSONL event holding a whole command
# output) can be huge, so each dumped line is also cut to a fixed length; the
# dump stays within both bounds.
reviewer_log_tail_lines=40
reviewer_log_tail_line_chars=300

# dump_reviewer_log <agent> <log-file> -- print the bounded tail to stderr.
dump_reviewer_log() {
    local label
    label=$(review_agent_label "$1") || return 0
    echo "---- last ${reviewer_log_tail_lines} lines of ${label} reviewer log (each cut to ${reviewer_log_tail_line_chars} chars) ----" >&2
    tail -n "$reviewer_log_tail_lines" "$2" 2>/dev/null | awk -v max="$reviewer_log_tail_line_chars" '
        length($0) > max { printf "%s... [truncated %d chars]\n", substr($0, 1, max), length($0) - max; next }
        { print }
    ' >&2 || true
    echo "---- end of ${label} reviewer log ----" >&2
}

# A reviewer that hits its usage limit ends with a short message at the end of
# its log. Only the last few lines are searched (for Codex, only its error
# events), so review text that merely quotes such a message is not mistaken
# for one.
reviewer_quota_tail_lines=5
reviewer_quota_pattern='usage limit|session limit|weekly limit|hit your limit|limit reached|quota exceeded|exceeded your quota'
reviewer_quota_exit_code=75

# reviewer_quota_message <agent> <log-file> -- print the reviewer's quota
# message and return 0, or return 1 when the log has none.
reviewer_quota_message() {
    local tail_text
    tail_text=$(tail -n "$reviewer_quota_tail_lines" "$2" 2>/dev/null) || return 1
    if [ "$1" = "codex" ]; then
        tail_text=$(printf '%s\n' "$tail_text" | grep -E '"type": ?"(error|turn\.failed)"') || return 1
    fi
    printf '%s\n' "$tail_text" | grep -iE "$reviewer_quota_pattern" | tail -n 1 | grep .
}

# quota_reset_text <message> -- print the reset time the message states: an
# ISO 8601 local time for a `limit reached|<epoch>` message, otherwise the
# message's own phrase (e.g. `resets 10:10am (Asia/Tokyo)`), or `unknown`
# when it names no time.
quota_reset_text() {
    local message=$1
    local epoch
    local reset
    epoch=$(printf '%s\n' "$message" | grep -oE 'limit reached\|[0-9]{9,}' | grep -oE '[0-9]+$' || true)
    if [ -n "$epoch" ]; then
        date -d "@${epoch}" '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null \
            || date -r "$epoch" '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null \
            || printf '@%s\n' "$epoch"
        return 0
    fi
    reset=$(printf '%s\n' "$message" | grep -oiE '(resets?|try again)[^"\\]*[0-9][^"\\]*' | head -n 1 \
        | sed -E 's/[[:space:].]+$//' | cut -c1-200 || true)
    printf '%s\n' "${reset:-unknown}"
}

# report_reviewer_quota <agent> <log-file> -- when the reviewer stopped on its
# usage limit, print `reviewer-quota-exhausted: <agent>`,
# `reviewer-quota-detected-at: <ISO 8601 local time>` (a reset phrase without a
# date means its occurrence nearest to it), and
# `reviewer-quota-reset: <reset-time|unknown>`,
# and return 0; otherwise return 1.
report_reviewer_quota() {
    local message
    message=$(reviewer_quota_message "$1" "$2") || return 1
    echo "error: the $(review_agent_label "$1") reviewer stopped because its usage limit was reached" >&2
    echo "reviewer-quota-exhausted: $1"
    echo "reviewer-quota-detected-at: $(date '+%Y-%m-%dT%H:%M:%S%z')"
    echo "reviewer-quota-reset: $(quota_reset_text "$message")"
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

# finish_review <repo> <pr-number> <agent> <command-label> <log-file> -- wait
# for the reviewer, confirm its comment, and preserve failure logs and status.
finish_review() {
    local repo=$1
    local pr_number=$2
    local agent=$3
    local command_label=$4
    local log_file=$5
    local exit_code status

    set +e
    wait "$REVIEWER_PID"
    exit_code=$?
    set -e

    if [ "$exit_code" -ne 0 ]; then
        echo "error: ${command_label} exited with status ${exit_code}" >&2
        dump_reviewer_log "$agent" "$log_file"
        if report_reviewer_quota "$agent" "$log_file"; then
            return "$reviewer_quota_exit_code"
        fi
        return "$exit_code"
    fi

    set +e
    report_posted_review "$repo" "$pr_number" "$agent"
    status=$?
    set -e
    if [ "$status" -eq 0 ]; then
        remove_body_file
    else
        dump_reviewer_log "$agent" "$log_file"
        if [ "$status" -eq 1 ] && report_reviewer_quota "$agent" "$log_file"; then
            status=$reviewer_quota_exit_code
        fi
    fi
    return "$status"
}

# report_posted_review <repo> <pr-number> <agent> -- prints `review-posted: <url>`
# and `review-count: <count>/<max>`, then `review-findings: must=<n> optional=<n>`
# (including the new review) and returns 0
# when the reviewer posted a new comment; otherwise returns 1 (no new comment)
# or 2 (lookup failed).
report_posted_review() {
    local repo=$1
    local pr_number=$2
    local agent=$3
    local comment
    local comment_url
    local findings
    local status

    if comment=$(find_new_review_comment "$repo" "$pr_number" "$agent" "$REVIEW_COMMENT_IDS_BEFORE"); then
        IFS=$'\t' read -r comment_url findings <<<"$comment"
        if ! [[ "$findings" =~ ^must=[0-9]+\ optional=[0-9]+$ ]]; then
            echo "error: posted review comment has no valid review-findings footer" >&2
            return 1
        fi
        echo "review-posted: ${comment_url}"
        echo "review-count: $((REVIEW_COUNT + 1))/${MAX_REVIEWS}"
        echo "review-findings: ${findings}"
        return 0
    else
        status=$?
    fi

    if [ "$status" -eq 1 ]; then
        echo "error: $(review_agent_label "$agent") exited successfully, but no new review comment was found for PR #${pr_number}" >&2
    fi
    return "$status"
}
