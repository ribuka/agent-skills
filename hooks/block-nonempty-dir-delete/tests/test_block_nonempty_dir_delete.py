"""Tests for the PreToolUse hook that blocks deleting non-empty directories.

Run with: uv run --no-project --with pytest -m pytest hooks/block-nonempty-dir-delete/tests
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "block_nonempty_dir_delete.py"
spec = importlib.util.spec_from_file_location("block_nonempty_dir_delete", SCRIPT)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "full" / "sub").mkdir(parents=True)
    (tmp_path / "full" / "a.txt").write_text("a")
    (tmp_path / "full" / "sub" / "b.txt").write_text("b")
    (tmp_path / "empty").mkdir()
    (tmp_path / "file.txt").write_text("f")
    (tmp_path / "x.jpg").write_text("x")
    return tmp_path


def run_hook(monkeypatch, capsys, command: str, cwd: str) -> str:
    data = json.dumps({"tool_input": {"command": command}, "cwd": cwd})
    stdin = SimpleNamespace(buffer=io.BytesIO(data.encode("utf-8")))
    monkeypatch.setattr(hook.sys, "stdin", stdin)
    hook.main()
    return capsys.readouterr().out


ALLOWED = [
    "rm file.txt",
    "rm -f *.jpg",
    "rm -rf empty",
    "rm -rf nonexistent",
    "rmdir empty",
    "rm -rf file.txt empty 2>/dev/null; ls",
    "cd <tree> && rm -r empty",
    "git status && git diff",
    "git commit -F - <<'EOF'\nfix: avoid shutil.rmtree and rm -rf tmp\nEOF",
    "uv run -m pytest 2>&1 | tail -2",
    "find <tree> -type d -empty -delete",
    "find <tree> -name '*.txt'",
    "echo 'rm -rf tmp' > /dev/null",
    "git clean -n",
    "git clean --dry-run -d",
    "uv run - <<'EOF'\ns = s.replace('shutil.rmtree(x)', 'shutil.rmtree(y)')\nEOF",
]

DENIED = [
    "rm -rf full",
    "rm -fr full",
    "rm -r -f full",
    "rm -R full",
    "rm --recursive full",
    "rm -rf {empty,full}",
    "rm -rf fu*",
    "rm -rf <tree>/* <tree>/.[!.]*",
    "cd <tree> && rm -rf full",
    "rm -rf <tree>/full",
    "rm -rf x/$(date)",
    "rm -rf `pwd`/full",
    "bash -c 'rm -rf full'",
    "sudo rm -rf full",
    "env FOO=1 rm -rf full",
    "FOO=1 rm -rf full",
    "find <tree> -delete",
    "find <tree> -type f -delete",
    "find . -name __pycache__ -type d -exec rm -rf {} +",
    "ls | xargs rm -rf",
    "git clean -fdx",
    "uv run python -c \"import shutil; shutil.rmtree('full')\"",
    "uv run - <<'PY'\nimport shutil\nshutil.rmtree('full')\nPY",
    'powershell -Command "Remove-Item -Recurse -Force full"',
    "cmd //c rd /s /q full",
    "npx rimraf tmp",
    "node -e \"require('fs').rmSync('full', {recursive: true})\"",
    "rm -rf 'full",
]


@pytest.mark.parametrize("command", ALLOWED)
def test_allowed(tree, monkeypatch, capsys, command):
    command = command.replace("<tree>", tree.as_posix())
    assert run_hook(monkeypatch, capsys, command, tree.as_posix()) == ""


@pytest.mark.parametrize("command", DENIED)
def test_denied(tree, monkeypatch, capsys, command):
    command = command.replace("<tree>", tree.as_posix())
    out = run_hook(monkeypatch, capsys, command, tree.as_posix())
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "deny"
    assert decision["permissionDecisionReason"]


def test_rm_leaves_tree_untouched_when_denied(tree, monkeypatch, capsys):
    run_hook(monkeypatch, capsys, "rm -rf full", tree.as_posix())
    assert (tree / "full" / "sub" / "b.txt").is_file()


def test_variable_pointing_to_nonexistent_path_is_allowed(tree, monkeypatch, capsys):
    monkeypatch.setenv("TARGET_DIR", (tree / "nonexistent").as_posix())
    assert run_hook(monkeypatch, capsys, 'rm -rf "$TARGET_DIR"', tree.as_posix()) == ""


def test_unset_variable_is_denied(tree, monkeypatch, capsys):
    monkeypatch.delenv("TARGET_DIR", raising=False)
    out = run_hook(monkeypatch, capsys, 'rm -rf "$TARGET_DIR"', tree.as_posix())
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_variable_pointing_to_full_directory_is_denied(tree, monkeypatch, capsys):
    monkeypatch.setenv("HOME", (tree / "full").as_posix())
    out = run_hook(monkeypatch, capsys, 'rm -rf "$HOME"', tree.as_posix())
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.skipif(os.name != "nt", reason="Git Bash drive paths exist only on Windows")
def test_git_bash_drive_path_is_resolved(tree, monkeypatch, capsys):
    drive, rest = tree.as_posix().split(":", 1)
    out = run_hook(
        monkeypatch, capsys, f"rm -rf /{drive.lower()}{rest}/full", tree.as_posix()
    )
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_deny_reason_is_ascii_json(tree, monkeypatch, capsys):
    out = run_hook(monkeypatch, capsys, "rm -rf full", tree.as_posix())
    assert out.isascii()
    assert "rmdir" in json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
