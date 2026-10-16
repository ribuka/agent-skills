"""Tests that the docs do not require exit codes 10 / 20 to be observable.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
DOCS = (
    SKILL_DIR / "SKILL.md",
    SKILL_DIR / "references" / "codex.md",
    SKILL_DIR / "references" / "integration.md",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_docs_do_not_make_10_20_the_state_contract() -> None:
    for doc in DOCS:
        text = _read(doc)
        for stale in ("`PAUSED_QUOTA` / 10", "`UNKNOWN` / 20", "PAUSED_QUOTA/10", "exit 0 / 10 / 20"):
            assert stale not in text, (doc.name, stale)


def test_docs_gate_on_zero_and_read_state_for_blocked_results() -> None:
    for doc in DOCS:
        text = _read(doc)
        assert "PowerShell" in text, doc.name
        assert "`-Command`" in text, doc.name
    skill = _read(SKILL_DIR / "SKILL.md")
    assert "exits `0` only on READY" in skill
    assert "read the JSON `state` to tell\n  PAUSED_QUOTA from UNKNOWN" in skill
    assert "without a parseable `state` is\n  UNKNOWN" in skill
