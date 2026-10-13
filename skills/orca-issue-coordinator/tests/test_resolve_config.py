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

    def _run(*args: str, config: str | None = None) -> tuple[int, str, str]:
        if config is not None:
            (tmp_path / "config.conf").write_text(config, encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["resolve_config.py", *args])
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
