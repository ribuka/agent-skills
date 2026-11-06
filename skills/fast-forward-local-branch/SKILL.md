---
name: fast-forward-local-branch
description: Safely fast-forward an existing local branch from origin without switching the caller's branch.
---

# Fast-forward local branch

Run `uv run --no-project ~/.agents/skills/fast-forward-local-branch/scripts/fast_forward.py --repo <path> --branch <name>`.
Both arguments are required. The script explicitly fetches `refs/heads/<name>`
from origin into `refs/remotes/origin/<name>` before comparing commits.

- Prints `local-branch: updated`, `up-to-date`, `skipped (missing local branch)`,
  `skipped (diverged)` (including local-only commits), or `skipped (dirty: <path>)`.
- Prints `local-branch-head: <full sha>` after processing when the local branch exists.
- Exit 0 means updated, unchanged, or skipped. Exit 1 prints `error: <reason>`
  identifying the failed Git operation. Invalid CLI syntax exits 2.

Never creates a branch or switches the caller's checkout. A clean worktree
holding the branch is updated using `git merge --ff-only` to the fetched SHA;
tracked changes cause a skip, while conflicting untracked files cause an error.
Without such a worktree, updates the ref conditional on the compared old SHA.
