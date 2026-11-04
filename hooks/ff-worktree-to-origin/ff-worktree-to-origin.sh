#!/bin/sh
# SessionStart hook: fast-forward a freshly started session's worktree to origin's default branch.
# Desktop-app worktrees are cut from local refs and the app ignores worktree.baseRef, so this
# brings them up to date with origin. Runs only when all of these hold, otherwise does nothing:
#   - source is "startup" (not resume/clear/compact)
#   - cwd is a linked git worktree under .claude/worktrees/
#   - the worktree is on a branch and has no changes
#   - the branch can be fast-forwarded (it has no commits of its own past origin's default branch)

input=$(cat)

# Read a top-level string field from the hook's JSON input (no jq on this machine).
get() {
  printf '%s' "$input" | tr -d '\n' |
    sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" |
    sed 's/\\\\/\\/g'
}

[ "$(get source)" = startup ] || exit 0
dir=$(get cwd)
[ -n "$dir" ] || exit 0
cd "$dir" 2>/dev/null || exit 0

case "$(pwd -P)" in
  */.claude/worktrees/*) ;;
  *) exit 0 ;;
esac

gitdir=$(git rev-parse --absolute-git-dir 2>/dev/null) || exit 0
common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 0
[ "$gitdir" != "$common" ] || exit 0          # main checkout, not a linked worktree
git symbolic-ref -q HEAD >/dev/null || exit 0  # detached HEAD
[ -z "$(git status --porcelain 2>/dev/null)" ] || exit 0

GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="ssh -o BatchMode=yes" \
  git fetch --quiet origin >/dev/null 2>&1 || exit 0
base=$(git symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null) || base=origin/main
git rev-parse -q --verify "$base^{commit}" >/dev/null || exit 0

before=$(git rev-parse --short HEAD)
git merge --ff-only --quiet "$base" >/dev/null 2>&1 || exit 0
after=$(git rev-parse --short HEAD)
[ "$before" = "$after" ] || echo "Fast-forwarded this worktree's branch from $before to $base ($after) at session start."
exit 0
