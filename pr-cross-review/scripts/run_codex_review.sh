#!/usr/bin/env bash
# Launch Codex CLI non-interactively to review a pull request of the current
# checkout's repository, and confirm that it posted the review comment.
#
# Usage:
#   run_codex_review.sh <pr-number> [options] [-- <extra instructions>]
#
# Options (defaults come from config.env):
#   --model <model>                   CODEX_MODEL
#   --effort <effort>                 CODEX_EFFORT, passed as `-c model_reasoning_effort=<effort>`
#   --sandbox <mode>                  CODEX_SANDBOX (read-only|workspace-write|danger-full-access)
#   --network-access <true|false>     CODEX_NETWORK_ACCESS (workspace-write only)
#   --approve-for-me                  Pass `--approve-for-me` to `codex exec`
#   --timeout-seconds <n>             CODEX_TIMEOUT_SECONDS; exit 124 on expiry
#   --heartbeat-timeout-seconds <n>   CODEX_HEARTBEAT_TIMEOUT_SECONDS; exit 125 when
#                                     the progress log stops growing that long
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

load_config REVIEW_LANGUAGE MAX_REVIEWS REVIEW_BODY_DIR REVIEW_BODY_NOT_IGNORED CODEX_MODEL CODEX_EFFORT CODEX_SANDBOX \
    CODEX_NETWORK_ACCESS CODEX_TIMEOUT_SECONDS CODEX_HEARTBEAT_TIMEOUT_SECONDS

model=$CODEX_MODEL
effort=$CODEX_EFFORT
sandbox=$CODEX_SANDBOX
network_access=$CODEX_NETWORK_ACCESS
timeout_seconds=$CODEX_TIMEOUT_SECONDS
heartbeat_timeout_seconds=$CODEX_HEARTBEAT_TIMEOUT_SECONDS
approve_for_me="false"
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
        --sandbox)
            require_value "$@"
            sandbox=$2
            shift 2
            ;;
        --network-access)
            require_value "$@"
            network_access=$2
            shift 2
            ;;
        --approve-for-me)
            approve_for_me="true"
            shift
            ;;
        --timeout-seconds)
            require_value "$@"
            timeout_seconds=$2
            shift 2
            ;;
        --heartbeat-timeout-seconds)
            require_value "$@"
            heartbeat_timeout_seconds=$2
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

require_positive_int "timeout seconds" "$timeout_seconds"
require_positive_int "heartbeat timeout seconds" "$heartbeat_timeout_seconds"

command -v codex >/dev/null 2>&1 || die "codex command not found in PATH"

repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
prepare_review_context "$repo" "$pr_number" codex
prepare_body_file "$pr_number" codex
build_review_prompt "$pr_number" codex "$extra_instructions"
export_review_environment

# --json makes codex emit one JSONL event per progress step, so the growth of
# the log is the heartbeat signal. The log is a temp file that is always
# removed; on failure its tail is printed to stderr for debugging.
log_file=$(mktemp)
echo "info: codex progress log (removed on exit): ${log_file}" >&2
echo "info: hard timeout: ${timeout_seconds}s, heartbeat (no-progress) timeout: ${heartbeat_timeout_seconds}s" >&2

dump_log_tail() {
    echo "---- last 40 lines of codex progress log ----" >&2
    tail -n 40 "$log_file" >&2 || true
    echo "---- end of codex progress log ----" >&2
}

cleanup() {
    stop_reviewer
    rm -f "$log_file"
}
trap cleanup EXIT INT TERM

codex_args=(exec --json --model "$model" -c "model_reasoning_effort=${effort}" --sandbox "$sandbox")
if [ "$sandbox" = "workspace-write" ]; then
    codex_args+=(-c "sandbox_workspace_write.network_access=${network_access}")
fi
if [ "$approve_for_me" = "true" ]; then
    codex_args+=(--approve-for-me)
fi

start_reviewer codex "${codex_args[@]}" "$REVIEW_PROMPT" >"$log_file" 2>&1

poll_interval_seconds=10
start_time=$(date +%s)
last_log_size=-1
last_progress_time=$start_time

while true; do
    # Re-check aliveness both before and after the sleep: codex may have
    # exited during the sleep, which must not be misreported as a timeout.
    if ! kill -0 "$REVIEWER_PID" 2>/dev/null; then
        break
    fi
    sleep "$poll_interval_seconds"
    if ! kill -0 "$REVIEWER_PID" 2>/dev/null; then
        break
    fi

    now=$(date +%s)
    if [ "$((now - start_time))" -ge "$timeout_seconds" ]; then
        echo "error: codex exec exceeded the hard timeout of ${timeout_seconds}s; killing pid ${REVIEWER_PID}" >&2
        dump_log_tail
        exit 124
    fi

    current_log_size=$(wc -c <"$log_file" 2>/dev/null || echo 0)
    if [ "$current_log_size" != "$last_log_size" ]; then
        last_log_size=$current_log_size
        last_progress_time=$now
    elif [ "$((now - last_progress_time))" -ge "$heartbeat_timeout_seconds" ]; then
        echo "error: no progress in codex log for ${heartbeat_timeout_seconds}s (hang suspected); killing pid ${REVIEWER_PID}" >&2
        dump_log_tail
        exit 125
    fi
done

set +e
wait "$REVIEWER_PID"
exit_code=$?
set -e

if [ "$exit_code" -ne 0 ]; then
    echo "error: codex exec exited with status ${exit_code}" >&2
    dump_log_tail
    exit "$exit_code"
fi

set +e
report_posted_review "$repo" "$pr_number" codex
status=$?
set -e
if [ "$status" -eq 0 ]; then
    remove_body_file
else
    dump_log_tail
fi
exit "$status"
