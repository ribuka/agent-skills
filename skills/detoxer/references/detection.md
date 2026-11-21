# Detection

Run tools without adding them to the project (`uvx`, `npx --yes`), in the
scan worktree `<scan-dir>/checkout`, and write their output to `<scan-dir>`
(never into the repository). A tool that is missing or fails is skipped
and named in the report; it never stops the run.

## Tools

| Language / target | Tool | Command (example) | Finds |
|-------------------|------|-------------------|-------|
| Any text | jscpd | `npx --yes jscpd --silent --reporters json --output <scan-dir>/jscpd <paths>` | Copy-pasted blocks across files |
| Python | Ruff | `uvx ruff check --select C90,PLR0911,PLR0912,PLR0913,PLR0915 --output-format json <paths>` | Complexity, too many branches/arguments/statements |
| Python | Vulture | `uvx vulture --min-confidence 80 <paths>` | Unused functions, classes, variables |
| Python | Radon | `uvx radon cc -s -j <paths>` | Cyclomatic complexity per function (for trends) |
| JS / TS | ESLint complexity rules, knip | `npx --yes knip --reporter json` | Unused exports, files, dependencies |

- Ruff: pass `--select` explicitly so the scan does not depend on the
  project's rule set, but keep the project's `exclude` and per-file
  ignores.
- Complexity hits in tests (e.g. many fixture arguments) are usually tool
  noise; drop them unless the test itself is hard to change.
- Vulture reports false positives for entry points, fixtures, and dynamic
  dispatch; confirm each hit with a search before keeping it.
- jscpd on Markdown is useful in documentation-heavy repositories (e.g.
  the same rule copied into several `SKILL.md` files), but read the
  repository's rules on intentional duplication first.

## Read the code yourself

Tools find shapes, not intent. Read the hotspot files and their direct
callers and callees, and look for:

- The same decision made in several places (a condition, a mapping, a
  retry policy) that would have to change together.
- Parallel implementations of one concept with drifted behavior (two
  config readers, two path resolvers).
- Functions that grew a mode flag per caller.
- Modules whose recent commits keep touching the same other module
  (change coupling: `git log --name-only` over the window).
- Conventions the repository states (AGENTS.md, CLAUDE.md, docs) that the
  hotspot breaks.
- Leftovers: compatibility paths, unused options, stale comments or docs
  describing removed behavior.
- Tests that duplicate setup heavily or test implementation details that
  block refactoring.
