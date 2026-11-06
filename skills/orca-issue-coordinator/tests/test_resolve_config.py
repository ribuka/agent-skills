"""Tests for resolve_config.py, with the skill directory redirected to a temp dir.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "resolve_config.py"


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    spec = importlib.util.spec_from_file_location("resolve_config", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SKILL_DIR", tmp_path)

    def _run(*args: str, config: str | None = None,
             agent: str | None = "claude") -> tuple[int, str, str]:
        if config is not None:
            (tmp_path / "config.conf").write_text(config, encoding="utf-8")
        argv = list(args)
        if "--agent" not in argv and agent is not None:
            argv = ["--agent", agent, *argv]
        monkeypatch.setattr(sys, "argv", ["resolve_config.py", *argv])
        code = module.main()
        out, err = capsys.readouterr()
        return code, out, err

    return _run


def test_max_workers_defaults_to_three(run) -> None:
    code, out, _ = run("--json")
    assert code == 0
    assert json.loads(out)["MAX_WORKERS"] == {"value": "3", "source": "default"}


def test_text_output_shows_max_workers_and_source(run) -> None:
    code, out, _ = run()
    assert code == 0
    assert "max-workers: 3  (from default)" in out.splitlines()


def test_max_workers_from_config(run, tmp_path: Path) -> None:
    code, out, _ = run("--json", config="MAX_WORKERS=2\n")
    assert code == 0
    assert json.loads(out)["MAX_WORKERS"] == {
        "value": "2", "source": str(tmp_path / "config.conf")}


def test_max_workers_argument_overrides_config(run) -> None:
    code, out, _ = run("--json", "--max-workers", "1", config="MAX_WORKERS=2\n")
    assert code == 0
    assert json.loads(out)["MAX_WORKERS"] == {"value": "1", "source": "argument"}


@pytest.mark.parametrize("value", ["0", "-1", "2.5", "two", "٣"])
def test_invalid_max_workers_fails(run, value: str) -> None:
    code, out, err = run("--max-workers", value)
    assert code == 1
    assert out == ""
    assert "MAX_WORKERS" in err


def test_invalid_max_workers_in_config_fails(run) -> None:
    code, _, err = run(config="MAX_WORKERS=0\n")
    assert code == 1
    assert "config.conf" in err


@pytest.mark.parametrize("config", [None, "MAX_WORKERS=2\n"])
def test_empty_max_workers_argument_fails(run, config: str | None) -> None:
    code, out, err = run("--max-workers=", config=config)
    assert code == 1
    assert out == ""
    assert "MAX_WORKERS is empty (from argument)" in err


@pytest.mark.parametrize("agent,impl,merge", [
    ("claude", "opus", "sonnet"),
    ("codex", "gpt-6.1-sol", "gpt-6.1-sol"),
])
def test_agent_defaults(run, agent: str, impl: str, merge: str) -> None:
    code, out, _ = run("--agent", agent, "--json")
    assert code == 0
    data = json.loads(out)
    assert data["AGENT"] == {"value": agent, "source": "argument"}
    for key, expected in (("IMPL_MODEL", impl), ("MERGE_MODEL", merge),
                          ("IMPL_EFFORT", "medium"), ("MERGE_EFFORT", "medium")):
        assert data[key] == {"value": expected, "source": "default"}


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_config_selects_only_current_agent(run, agent: str) -> None:
    code, out, err = run("--agent", agent, "--json", config=(
        "CLAUDE_IMPL_MODEL=claude-custom\nCODEX_IMPL_MODEL=codex-custom\n"
        "CLAUDE_MERGE_EFFORT=max\nCODEX_MERGE_EFFORT=xhigh\n"))
    assert code == 0
    assert err == ""
    data = json.loads(out)
    assert data["IMPL_MODEL"]["value"] == f"{agent}-custom"
    assert data["MERGE_EFFORT"]["value"] == ("max" if agent == "claude" else "xhigh")


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_phase_arguments_override_prefixed_config(run, agent: str) -> None:
    code, out, _ = run("--agent", agent, "--json", "--impl-model", "override",
                       "--impl-effort", "high", "--merge-model", "merge-override",
                       "--merge-effort", "low", config=(
                           f"{agent.upper()}_IMPL_MODEL=config-model\n"
                           f"{agent.upper()}_MERGE_EFFORT=medium\n"))
    assert code == 0
    data = json.loads(out)
    for key, value in (("IMPL_MODEL", "override"), ("IMPL_EFFORT", "high"),
                       ("MERGE_MODEL", "merge-override"), ("MERGE_EFFORT", "low")):
        assert data[key] == {"value": value, "source": "argument"}


@pytest.mark.parametrize("flag", ["--impl-effort", "--merge-effort"])
def test_codex_rejects_max_effort(run, flag: str) -> None:
    code, out, err = run("--agent", "codex", flag, "max")
    assert code == 1
    assert out == ""
    assert "not one of" in err


def test_codex_rejects_invalid_effort_from_config(run) -> None:
    code, _, err = run("--agent", "codex", config="CODEX_IMPL_EFFORT=max\n")
    assert code == 1
    assert "config.conf" in err


def test_old_unprefixed_keys_are_not_applied(run) -> None:
    code, out, err = run("--json", config="IMPL_MODEL=old\nMERGE_EFFORT=low\n")
    assert code == 0
    assert "ignored line" in err
    assert json.loads(out)["IMPL_MODEL"]["value"] == "opus"
    assert json.loads(out)["MERGE_EFFORT"]["value"] == "medium"


def test_text_output_includes_agent(run) -> None:
    code, out, _ = run("--agent", "codex")
    assert code == 0
    assert "agent: codex" in out
    assert "impl: --model gpt-6.1-sol --effort medium" in out


def test_agent_is_required(run) -> None:
    with pytest.raises(SystemExit) as exc:
        run(agent=None)
    assert exc.value.code == 2


def test_fresh_worker_context_tokens_defaults_to_200000(run) -> None:
    code, out, _ = run("--json", agent="codex")
    assert code == 0
    assert json.loads(out)["FRESH_WORKER_CONTEXT_TOKENS"] == {
        "value": "200000", "source": "default"}
    code, out, _ = run()
    assert "fresh-worker-context-tokens: 200000  (from default)" in out.splitlines()


def test_fresh_worker_context_tokens_precedence(run, tmp_path: Path) -> None:
    config = "FRESH_WORKER_CONTEXT_TOKENS=150000\n"
    code, out, err = run("--json", config=config)
    assert code == 0 and "warning" not in err
    assert json.loads(out)["FRESH_WORKER_CONTEXT_TOKENS"] == {
        "value": "150000", "source": str(tmp_path / "config.conf")}
    code, out, _ = run("--json", "--fresh-worker-context-tokens", "90000", config=config)
    assert json.loads(out)["FRESH_WORKER_CONTEXT_TOKENS"] == {
        "value": "90000", "source": "argument"}


@pytest.mark.parametrize("value", ["0", "-1", "1e5", "abc"])
def test_fresh_worker_context_tokens_rejects_invalid(run, value: str) -> None:
    code, _, err = run("--fresh-worker-context-tokens", value)
    assert code == 1
    assert "FRESH_WORKER_CONTEXT_TOKENS" in err


def test_prefixed_fresh_worker_context_tokens_is_ignored(run) -> None:
    code, out, err = run("--json", config="CLAUDE_FRESH_WORKER_CONTEXT_TOKENS=5\n")
    assert code == 0 and "ignored line" in err
    assert json.loads(out)["FRESH_WORKER_CONTEXT_TOKENS"]["source"] == "default"
