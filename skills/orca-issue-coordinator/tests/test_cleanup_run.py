"""Tests for cleanup_run.py.

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cleanup_run.py"
spec = importlib.util.spec_from_file_location("cleanup_run", SCRIPT)
cleanup_run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup_run)


def make_run_dir(root: Path, run_id: str = "run_79c8a7731261") -> Path:
    target = root / "tmp" / run_id
    (target / "nested").mkdir(parents=True)
    (target / "coordinator.md").write_text("x", encoding="utf-8")
    (target / "nested" / "file.txt").write_text("y", encoding="utf-8")
    return target


def test_removes_only_the_run_directory(tmp_path: Path) -> None:
    target = make_run_dir(tmp_path)
    sibling = make_run_dir(tmp_path, "run_other")
    (tmp_path / "tmp" / "keep.txt").write_text("z", encoding="utf-8")
    code, result = cleanup_run.cleanup(tmp_path, "run_79c8a7731261")
    assert code == 0
    assert result == {"status": "removed", "path": str(target)}
    assert not target.exists()
    assert sibling.is_dir()
    assert (tmp_path / "tmp" / "keep.txt").is_file()


def test_absent_directory_is_success(tmp_path: Path) -> None:
    code, result = cleanup_run.cleanup(tmp_path, "run_gone")
    assert code == 0
    assert result["status"] == "absent"


def test_removes_read_only_files(tmp_path: Path) -> None:
    target = make_run_dir(tmp_path)
    read_only = target / "nested" / "file.txt"
    os.chmod(read_only, stat.S_IREAD)
    code, result = cleanup_run.cleanup(tmp_path, "run_79c8a7731261")
    assert (code, result["status"]) == (0, "removed")
    assert not target.exists()


@pytest.mark.parametrize("run_id", ["", ".", "..", "../x", "a/b", "a\\b", "/abs",
                                    "C:\\x", "*", "-x", "tmp/..", " run"])
def test_refuses_invalid_run_ids(tmp_path: Path, run_id: str) -> None:
    make_run_dir(tmp_path, "x")
    code, result = cleanup_run.cleanup(tmp_path, run_id)
    assert code == 2
    assert result["status"] == "refused"
    assert (tmp_path / "tmp" / "x").is_dir()


def test_refuses_non_directory_target(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    target = tmp_path / "tmp" / "run_file"
    target.write_text("x", encoding="utf-8")
    code, result = cleanup_run.cleanup(tmp_path, "run_file")
    assert (code, result["status"]) == (2, "refused")
    assert target.is_file()


def symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"cannot create a directory symlink here: {error}")


def test_refuses_target_linked_outside(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "tmp").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("x", encoding="utf-8")
    symlink_or_skip(root / "tmp" / "run_link", outside)
    code, result = cleanup_run.cleanup(root, "run_link")
    assert (code, result["status"]) == (2, "refused")
    assert (outside / "precious.txt").is_file()


def test_refuses_tmp_linked_outside(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = make_run_dir(tmp_path / "outside")
    symlink_or_skip(root / "tmp", outside.parent)
    code, result = cleanup_run.cleanup(root, "run_79c8a7731261")
    assert (code, result["status"]) == (2, "refused")
    assert outside.is_dir()


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def run_script(cwd: Path, run_id: str) -> tuple[int, dict]:
    proc = subprocess.run([sys.executable, str(SCRIPT), "--run-id", run_id], cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, json.loads(proc.stdout)


def test_script_uses_git_top_level_of_current_directory(tmp_path: Path) -> None:
    git("init", "-q", cwd=tmp_path)
    target = make_run_dir(tmp_path)
    subdir = tmp_path / "sub"
    subdir.mkdir()
    code, result = run_script(subdir, "run_79c8a7731261")
    assert (code, result["status"]) == (0, "removed")
    assert not target.exists()
    assert not (subdir / "tmp").exists()


def test_script_refuses_outside_git_repository(tmp_path: Path) -> None:
    outside = tmp_path / "not_a_repo"
    outside.mkdir()
    env_ceiling = {**os.environ, "GIT_CEILING_DIRECTORIES": str(tmp_path)}
    proc = subprocess.run([sys.executable, str(SCRIPT), "--run-id", "run_x"], cwd=outside,
                          capture_output=True, text=True, encoding="utf-8", env=env_ceiling)
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["status"] == "refused"


def test_script_reports_failure_with_exit_1(tmp_path: Path, monkeypatch) -> None:
    target = make_run_dir(tmp_path)

    def fail(*_args, **_kwargs):
        raise PermissionError("blocked")

    monkeypatch.setattr(cleanup_run.shutil, "rmtree", fail)
    code, result = cleanup_run.cleanup(tmp_path, "run_79c8a7731261")
    assert code == 1
    assert result == {"status": "failed", "path": str(target), "reason": "blocked"}
    assert target.is_dir()
