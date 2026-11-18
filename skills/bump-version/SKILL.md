---
name: bump-version
description: Bump the project version - edit only the VERSION file, commit, push, open a pull request, merge it (no cross-review), and fast-forward the local `main` to `origin/main`. Use when asked to bump, raise, or release a new version, or when working on a version-bump branch (e.g. `bump-version-1.4.0`, `release/v2.0.0`).
---

# Bump version

Release a version bump as a pull request that changes **only** the `VERSION`
file, then merge it. Stop and ask the user whenever a step below says so.

## Workflow

### 1. Determine the new version

- Read the current version from `VERSION`.
- Infer the new version from the user's instructions or, if none is given,
  from the branch name (e.g. `bump-version-1.4.0`, `release/v2.0.0`).
- Keep the existing format of the file (prefix such as `v`, trailing newline).
- If you are not confident about the new version — for example, the
  instructions only say "bump" without the level (major / minor / patch) and
  the branch name does not say either — ask before editing.

### 2. Edit `VERSION`

Change the version in `VERSION` and nothing else.

- Do not touch any other file (changelogs, package manifests, lock files),
  even if they also contain the version. If they look like they need updating
  too, mention it to the user instead.
- Confirm with `git status` / `git diff` that `VERSION` is the only change.

### 3. Commit and push

- If you are on `main`, create a branch first (e.g. `bump-version-<version>`).
- Commit with a message such as `Bump version to <version>`.
- Push the branch to `origin`.
- No need to run the full test suite or lint check beyond confirming that `VERSION` is the only change.

### 4. Open the pull request

Create a pull request for the branch. Cross-review is **not** needed for a
version bump; do not run `pr-cross-review`.

### 5. Merge

Merge the pull request once its required checks pass.

- If the branch is behind `origin/main` or has conflicts, rebase onto
  `origin/main`, keep the diff limited to `VERSION`, and push with
  `git push --force-with-lease` (never `--force`).
- If checks fail or the merge is blocked, do **not** merge; report what is
  blocking and ask the user.

### 6. Sync local `main`

Run this only after confirming the merge: `gh pr view <pr> --json state --jq .state`
prints `MERGED`. Skip it when you did not merge, the merge failed, or it is
unconfirmed.

```bash
uv run --no-project ~/.agents/skills/fast-forward-local-branch/scripts/fast_forward.py --repo <working-repository-path> --branch main
```

See the `fast-forward-local-branch` skill for its public results and exit codes.

- Exit 0 means updated, unchanged, or skipped: report the `local-branch: ...`
  result, including the reason for a skip.
- Exit 1 means a synchronization error: report the `error: <reason>` line.
- Report the merge result and the local synchronization result separately.
  Never retry the merge because synchronization failed.
