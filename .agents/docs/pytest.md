# Pytest execution

## Mandatory

- Run pytest only outside the Codex Windows sandbox.
- Request out-of-sandbox execution before the first pytest run; do not try it in the sandbox first.
- If out-of-sandbox execution is unavailable or denied, do not run pytest; report it instead.
- NEVER change pytest temp-directory settings or test code merely to work around sandbox permission errors.

## Command

- Use `uv run --no-project --with pytest -m pytest <test-path>` for a targeted test.
- Use `uv run --no-project --with pytest -m pytest skills/quota-guard/tests skills/pr-cross-review/tests skills/orca-issue-coordinator/tests hooks/block-nonempty-dir-delete/tests --tb=short -q` for the full suite (the same paths CI runs).
