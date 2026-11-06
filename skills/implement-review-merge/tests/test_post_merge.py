"""Test standalone completion gating and personal configuration without real settings."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/post_merge.py"


@pytest.fixture
def module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("post_merge", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "SKILL_DIR", tmp_path)
    return mod


@pytest.mark.parametrize("config", [None, "", "# comment\n", "SYNC_LOCAL_MAIN_AFTER_MERGE=true"])
def test_enabled_defaults_invoke_public_cli(module, tmp_path, monkeypatch, config) -> None:
    if config is not None:
        (tmp_path / "config.conf").write_text(config)
    calls = []

    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        assert kwargs.get("timeout") is None  # Provider owns operation timeouts.
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "local-branch: updated\n", "")

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module.main(["--repo", "working repo", "--mode", "standalone", "--pr-state", "MERGED"]) == 0
    assert calls == [["uv", "run", "--no-project",
                      str(Path.home() / ".agents/skills/fast-forward-local-branch/scripts/fast_forward.py"),
                      "--repo", "working repo", "--branch", "main"]]


@pytest.mark.parametrize("mode,state,config,result", [
    ("standalone", "MERGED", "SYNC_LOCAL_MAIN_AFTER_MERGE=false", 0),
    ("standalone", "MERGED", "SYNC_LOCAL_MAIN_AFTER_MERGE=invalid", 1),
    ("standalone", "MERGED", "SYNC_LOCAL_MAIN_AFTER_MERGE=", 1),
    ("standalone", "MERGED", "bad setting", 1),
    *( (mode, state, "invalid", 0) for mode in ("standalone", "worker")
       for state in ("OPEN", "CLOSED", "UNKNOWN", "MERGED")
       if (mode, state) != ("standalone", "MERGED") ),
])
def test_disabled_errors_and_ineligible_modes_never_invoke(
        module, tmp_path, monkeypatch, mode, state, config, result) -> None:
    (tmp_path / "config.conf").write_text(config)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("must not invoke synchronization or fetch")

    monkeypatch.setattr(module.subprocess, "run", forbidden)
    assert module.main(["--repo", "repo", "--mode", mode, "--pr-state", state]) == result


def test_sync_failure_is_reported_without_retry(module, monkeypatch, capsys) -> None:
    calls = []

    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "error: git fetch failed\n", "")

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module.main(["--repo", "repo", "--mode", "standalone", "--pr-state", "MERGED"]) == 1
    assert len(calls) == 1
    assert capsys.readouterr().out.splitlines() == ["error: git fetch failed"]
