"""Tests for resolve_config.py, with the skill directory redirected to a temp dir.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "resolve_config.py"


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    spec = importlib.util.spec_from_file_location("resolve_config", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SKILL_DIR", tmp_path)
    shutil.copy2(SKILL_DIR / "config.conf", tmp_path / "config.conf")

    def _run(*args: str, config: str | None = None,
             agent: str | None = "claude") -> tuple[int, str, str]:
        """Run with `config` written to config.local.conf (the shipped config.conf stays)."""
        if config is not None:
            (tmp_path / "config.local.conf").write_text(config, encoding="utf-8")
        argv = list(args)
        if "--agent" not in argv and agent is not None:
            argv = ["--agent", agent, *argv]
        monkeypatch.setattr(sys, "argv", ["resolve_config.py", *argv])
        code = module.main()
        out, err = capsys.readouterr()
        return code, out, err

    return _run


# The removed key and flag, split so `git grep` finds no trace of them.
OLD_KEY = "MAX_" + "WORKERS"
OLD_FLAG = "--max-" + "workers"
LIMITS = [("MAX_IMPL_WORKERS", "--max-impl-workers", "max-impl-workers"),
          ("MAX_MERGE_WORKERS", "--max-merge-workers", "max-merge-workers")]


@pytest.mark.parametrize("key,flag,label", LIMITS)
def test_worker_limit_defaults_to_one(run, tmp_path: Path, key: str, flag: str, label: str) -> None:
    code, out, _ = run("--json")
    assert code == 0
    assert json.loads(out)[key] == {"value": "1", "source": str(tmp_path / "config.conf")}


@pytest.mark.parametrize("key,flag,label", LIMITS)
def test_text_output_shows_worker_limit_and_source(run, tmp_path: Path, key: str, flag: str,
                                                   label: str) -> None:
    code, out, _ = run()
    assert code == 0
    assert f"{label}: 1  (from {tmp_path / 'config.conf'})" in out.splitlines()
    assert not any(line.startswith(OLD_FLAG[2:] + ":") for line in out.splitlines())


@pytest.mark.parametrize("key,flag,label", LIMITS)
def test_worker_limit_from_config(run, tmp_path: Path, key: str, flag: str, label: str) -> None:
    code, out, _ = run("--json", config=f"{key}=2\n")
    assert code == 0
    assert json.loads(out)[key] == {"value": "2", "source": str(tmp_path / "config.local.conf")}


@pytest.mark.parametrize("key,flag,label", LIMITS)
def test_worker_limit_argument_overrides_config(run, key: str, flag: str, label: str) -> None:
    code, out, _ = run("--json", flag, "3", config=f"{key}=2\n")
    assert code == 0
    assert json.loads(out)[key] == {"value": "3", "source": "argument"}


def test_worker_limits_are_independent(run, tmp_path: Path) -> None:
    code, out, _ = run("--json", "--max-merge-workers", "4", config="MAX_IMPL_WORKERS=2\n")
    assert code == 0
    data = json.loads(out)
    assert data["MAX_IMPL_WORKERS"] == {"value": "2", "source": str(tmp_path / "config.local.conf")}
    assert data["MAX_MERGE_WORKERS"] == {"value": "4", "source": "argument"}


@pytest.mark.parametrize("key,flag,label", LIMITS)
@pytest.mark.parametrize("value", ["0", "-1", "2.5", "two", "\u0663"])
def test_invalid_worker_limit_fails(run, key: str, flag: str, label: str, value: str) -> None:
    code, out, err = run(flag, value)
    assert code == 1
    assert out == ""
    assert key in err


@pytest.mark.parametrize("key,flag,label", LIMITS)
def test_invalid_worker_limit_in_config_fails(run, tmp_path: Path, key: str, flag: str,
                                              label: str) -> None:
    code, _, err = run(config=f"{key}=0\n")
    assert code == 1
    assert key in err
    assert str(tmp_path / "config.local.conf") in err


@pytest.mark.parametrize("key,flag,label", LIMITS)
@pytest.mark.parametrize("with_config", [False, True])
def test_empty_worker_limit_argument_fails(run, key: str, flag: str, label: str,
                                           with_config: bool) -> None:
    code, out, err = run(f"{flag}=", config=f"{key}=2\n" if with_config else None)
    assert code == 1
    assert out == ""
    assert f"{key} is empty (from argument)" in err


def test_max_workers_is_an_unknown_key(run, tmp_path: Path) -> None:
    code, out, err = run("--json", config=f"{OLD_KEY}=3\n")
    assert (code, out) == (1, "")
    assert err == f"error: {tmp_path / 'config.local.conf'}: line 1: unknown key: {OLD_KEY}\n"


def test_max_workers_flag_is_gone(run) -> None:
    with pytest.raises(SystemExit) as exc:
        run(OLD_FLAG, "2")
    assert exc.value.code == 2


def test_serial_defaults_to_false(run) -> None:
    code, out, _ = run()
    assert code == 0
    assert "serial: false  (default)" in out.splitlines()
    code, out, _ = run("--json")
    assert json.loads(out)["SERIAL"] == {"value": False, "source": "default"}


def test_serial_flag_turns_serial_mode_on(run, tmp_path: Path) -> None:
    code, out, _ = run("--serial")
    assert code == 0
    assert "serial: true  (from argument)" in out.splitlines()
    assert f"max-impl-workers: 1  (from {tmp_path / 'config.conf'})" in out.splitlines()
    code, out, _ = run("--serial", "--json")
    assert json.loads(out)["SERIAL"] == {"value": True, "source": "argument"}


def test_serial_is_not_a_config_key(run) -> None:
    code, _, err = run(config="SERIAL=true\n")
    assert code == 1
    assert "unknown key: SERIAL" in err


@pytest.mark.parametrize("agent,impl,merge", [
    ("claude", "opus", "sonnet"),
    ("codex", "gpt-6.1-sol", "gpt-6.1-sol"),
])
def test_agent_defaults(run, tmp_path: Path, agent: str, impl: str, merge: str) -> None:
    code, out, _ = run("--agent", agent, "--json")
    assert code == 0
    data = json.loads(out)
    assert data["AGENT"] == {"value": agent, "source": "argument"}
    for key, expected in (("IMPL_MODEL", impl), ("MERGE_MODEL", merge),
                          ("IMPL_EFFORT", "medium"), ("MERGE_EFFORT", "medium")):
        assert data[key] == {"value": expected, "source": str(tmp_path / "config.conf")}


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
    assert "config.local.conf" in err


def test_old_unprefixed_keys_are_errors(run, tmp_path: Path) -> None:
    code, out, err = run("--json", config="IMPL_MODEL=old\n")
    assert (code, out) == (1, "")
    assert err == f"error: {tmp_path / 'config.local.conf'}: line 1: unknown key: IMPL_MODEL\n"


def test_text_output_includes_agent(run) -> None:
    code, out, _ = run("--agent", "codex")
    assert code == 0
    assert "agent: codex" in out
    assert "impl: --model gpt-6.1-sol --effort medium" in out


def test_agent_is_required(run) -> None:
    with pytest.raises(SystemExit) as exc:
        run(agent=None)
    assert exc.value.code == 2


def test_fresh_worker_context_tokens_defaults_to_200000(run, tmp_path: Path) -> None:
    code, out, _ = run("--json", agent="codex")
    assert code == 0
    assert json.loads(out)["FRESH_WORKER_CONTEXT_TOKENS"] == {
        "value": "200000", "source": str(tmp_path / "config.conf")}
    code, out, _ = run()
    assert (f"fresh-worker-context-tokens: 200000  (from {tmp_path / 'config.conf'})"
            in out.splitlines())


def test_fresh_worker_context_tokens_precedence(run, tmp_path: Path) -> None:
    config = "FRESH_WORKER_CONTEXT_TOKENS=150000\n"
    code, out, err = run("--json", config=config)
    assert code == 0 and "warning" not in err
    assert json.loads(out)["FRESH_WORKER_CONTEXT_TOKENS"] == {
        "value": "150000", "source": str(tmp_path / "config.local.conf")}
    code, out, _ = run("--json", "--fresh-worker-context-tokens", "90000", config=config)
    assert json.loads(out)["FRESH_WORKER_CONTEXT_TOKENS"] == {
        "value": "90000", "source": "argument"}


@pytest.mark.parametrize("value", ["0", "-1", "1e5", "abc"])
def test_fresh_worker_context_tokens_rejects_invalid(run, value: str) -> None:
    code, _, err = run("--fresh-worker-context-tokens", value)
    assert code == 1
    assert "FRESH_WORKER_CONTEXT_TOKENS" in err


def test_prefixed_fresh_worker_context_tokens_is_an_error(run) -> None:
    code, _, err = run("--json", config="CLAUDE_FRESH_WORKER_CONTEXT_TOKENS=5\n")
    assert code == 1 and "unknown key: CLAUDE_FRESH_WORKER_CONTEXT_TOKENS" in err


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_local_config_overrides_one_key_only(run, tmp_path: Path, agent: str) -> None:
    code, shipped, _ = run("--agent", agent, "--json")
    assert code == 0
    code, out, err = run("--agent", agent, "--json",
                         config="# personal\n\n  MAX_MERGE_WORKERS = 2 \n")
    assert (code, err) == (0, "")
    expected = json.loads(shipped)
    expected["MAX_MERGE_WORKERS"] = {"value": "2", "source": str(tmp_path / "config.local.conf")}
    assert json.loads(out) == expected


def test_text_output_names_local_config_as_source(run, tmp_path: Path) -> None:
    code, out, _ = run(config="CLAUDE_IMPL_EFFORT=high\n")
    assert code == 0
    assert (f"impl: --model opus --effort high  (model: {tmp_path / 'config.conf'}; "
            f"effort: {tmp_path / 'config.local.conf'})") in out.splitlines()


@pytest.mark.parametrize("name", ["config.conf", "config.local.conf"])
@pytest.mark.parametrize("content,line,problem", [
    ("BOGUS=1\n", 1, "unknown key: BOGUS"),
    ("MAX_IMPL_WORKERS=2\n# c\nMAX_IMPL_WORKERS=3\n", 3, "duplicate key: MAX_IMPL_WORKERS"),
    ("\nCLAUDE_IMPL_MODEL=  \n", 2, "empty value for CLAUDE_IMPL_MODEL"),
    ("MAX_IMPL_WORKERS\n", 1, "expected KEY=value"),
])
def test_invalid_config_names_file_and_line(run, tmp_path: Path, name: str, content: str,
                                            line: int, problem: str) -> None:
    (tmp_path / name).write_text(content, encoding="utf-8")
    code, out, err = run("--json")
    assert (code, out) == (1, "")
    assert err == f"error: {tmp_path / name}: line {line}: {problem}\n"


def test_missing_key_in_config_conf_is_an_error(run, tmp_path: Path) -> None:
    (tmp_path / "config.conf").write_text("MAX_IMPL_WORKERS=3\n", encoding="utf-8")
    code, out, err = run("--json", config="FRESH_WORKER_CONTEXT_TOKENS=5\n")
    assert (code, out) == (1, "")
    assert "missing keys: CLAUDE_IMPL_MODEL" in err


def test_script_holds_no_defaults() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for value in ('"opus"', '"sonnet"', '"gpt-', '"200000"', '"3"'):
        assert value not in source
