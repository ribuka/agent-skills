"""Tests that config.conf holds the defaults and config.local.conf overrides single keys."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from types import ModuleType

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def config(tmp_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("irm_config", SKILL_DIR / "scripts" / "config.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    shutil.copy2(SKILL_DIR / "config.conf", tmp_path / "config.conf")
    return mod


def test_shipped_config_sets_every_key(config: ModuleType) -> None:
    assert set(config.read_config(SKILL_DIR)) == set(config.CONFIG_KEYS)


def test_without_local_config_uses_config_conf(config: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "config.conf").write_text(
        "SYNC_LOCAL_MAIN_AFTER_MERGE=false\nCI_REGISTRATION_TIMEOUT_SECONDS=42\n", encoding="utf-8")
    assert config.read_config(tmp_path) == {
        "SYNC_LOCAL_MAIN_AFTER_MERGE": False, "CI_REGISTRATION_TIMEOUT_SECONDS": 42}


def test_local_config_overrides_one_key(config: ModuleType, tmp_path: Path) -> None:
    shipped = config.read_config(tmp_path)
    (tmp_path / "config.local.conf").write_text(
        "# personal\n\n  CI_REGISTRATION_TIMEOUT_SECONDS = 7 \n", encoding="utf-8")
    assert config.read_config(tmp_path) == {**shipped, "CI_REGISTRATION_TIMEOUT_SECONDS": 7}


@pytest.mark.parametrize("name", ["config.conf", "config.local.conf"])
@pytest.mark.parametrize("content,line,problem", [
    ("UNKNOWN=1\n", 1, "unknown key: UNKNOWN"),
    ("CI_REGISTRATION_TIMEOUT_SECONDS=5\nCI_REGISTRATION_TIMEOUT_SECONDS=6\n", 2,
     "duplicate key: CI_REGISTRATION_TIMEOUT_SECONDS"),
    ("# c\nCI_REGISTRATION_TIMEOUT_SECONDS=\n", 2,
     "empty value for CI_REGISTRATION_TIMEOUT_SECONDS"),
    ("no equals sign\n", 1, "expected KEY=value"),
])
def test_invalid_lines_name_file_and_line(config: ModuleType, tmp_path: Path, name: str,
                                          content: str, line: int, problem: str) -> None:
    (tmp_path / name).write_text(content, encoding="utf-8")
    with pytest.raises(ValueError) as error:
        config.read_config(tmp_path)
    assert str(error.value) == f"{tmp_path / name}: line {line}: {problem}"


def test_missing_key_in_config_conf_is_an_error(config: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "config.conf").write_text("SYNC_LOCAL_MAIN_AFTER_MERGE=true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing keys: CI_REGISTRATION_TIMEOUT_SECONDS"):
        config.read_config(tmp_path)


def test_missing_config_conf_is_an_error(config: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "config.conf").unlink()
    with pytest.raises(ValueError, match="cannot read"):
        config.read_config(tmp_path)
