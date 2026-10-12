# Python coding

## Rules

- Make changes only where necessary, minimize impact.
- Use the Python standard library only in skill scripts (`skills/*/scripts/`); they run by path on machines without a project environment.
  - Third-party packages are allowed only in tests and CI tooling (`.github/scripts/`), installed via `uv run --with`.
- Keep each script a single self-contained file runnable by path. Do not create packages or shared modules across skills.
- Start every script with a module docstring stating its purpose.
- Add type hints for all new function parameters and return types.
- Match the existing docstring and formatting style of the file you edit.

## Tests

- Put tests in `skills/<name>/tests/test_*.py`; load the script under test with `importlib.util.spec_from_file_location` as the existing tests do.
- Use only local fixtures (`tmp_path`, fake executables); NEVER touch real Claude/Codex settings, `gh`, or the network.
