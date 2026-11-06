#!/usr/bin/env bash
# Print the cross-review status of a pull request of the current checkout's
# repository without reading the comment bodies into the caller's context.
#
# Usage:
#   review_status.sh <pr-number>
#
# Output (stdout):
#   review-count: <count>/<max>    cross-reviews on the PR and MAX_REVIEWS
#   review-extra: <count>          reviews beyond MAX_REVIEWS (each one ran with
#                                  --extra-review after user approval)
#   review-latest: <comment-url>   the latest cross-review comment, or `none`
#   review-latest-commit: <sha>    the commit the latest cross-review saw (its
#                                  `Reviewed commit:` footer), or `none`

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "${script_dir}/common.sh"

if [ "$#" -ne 1 ]; then
    die "usage: $0 <pr-number>"
fi

pr_number=$1
require_positive_int "<pr-number>" "$pr_number"

load_config MAX_REVIEWS

if ! repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner); then
    echo "error: failed to resolve the repository of the current checkout" >&2
    exit 2
fi
if ! review_history=$(list_review_history "$repo" "$pr_number"); then
    echo "error: failed to query review history for PR #${pr_number}" >&2
    exit 2
fi

review_count=$(
    printf '%s\n' "$review_history" | awk 'NF { count++ } END { print count + 0 }'
)
latest_url=$(
    printf '%s\n' "$review_history" | awk -F '\t' 'NF { url=$2 } END { print url }'
)
latest_commit=$(
    printf '%s\n' "$review_history" | awk -F '\t' 'NF { commit=$3 } END { print commit }'
)

echo "review-count: ${review_count}/${MAX_REVIEWS}"
echo "review-extra: $((review_count > MAX_REVIEWS ? review_count - MAX_REVIEWS : 0))"
echo "review-latest: ${latest_url:-none}"
echo "review-latest-commit: ${latest_commit:-none}"
