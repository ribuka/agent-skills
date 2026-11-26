"""Tests for detoxer's scan_dir.py (create and remove the scan directory).

Run with: uv run --no-project --with pytest -m pytest <skill-dir>/tests
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "scan_dir.py"

spec = importlib.util.spec_from_file_location("detoxer_scan_dir", SCRIPT)
scan_dir = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan_dir)

GIT = shutil.which("git")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run([GIT, "-c", "user.name=t", "-c", "user.email=t@example.com",
                           *args], cwd=cwd, capture_output=True, text=True, check=True,
                          encoding="utf-8").stdout.strip()


@pytest.fixture
def temp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private system temp directory for the test."""
    root = tmp_path / "temp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository with two commits, used as the current directory."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q")
    for name in ("a.txt", "b.txt"):
        (path / name).write_text(name, encoding="utf-8")
        _git(path, "add", name)
        _git(path, "commit", "-q", "-m", name)
    monkeypatch.chdir(path)
    return path


def _run(capsys: pytest.CaptureFixture, *argv: str) -> tuple[int, str, str]:
    code = scan_dir.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def _create(capsys: pytest.CaptureFixture, ref: str = "HEAD") -> dict[str, str]:
    code, out, err = _run(capsys, "create", "--ref", ref)
    assert code == 0, err
    return dict(line.split(": ", 1) for line in out.splitlines())


def _worktrees(repo: Path) -> str:
    return _git(repo, "worktree", "list", "--porcelain")


def _same(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def test_create_makes_a_detached_worktree_of_the_ref(repo: Path, temp_root: Path,
                                                      capsys: pytest.CaptureFixture) -> None:
    first = _git(repo, "rev-parse", "HEAD~1")
    result = _create(capsys, "HEAD~1")
    assert list(result) == ["scan_dir", "checkout", "commit"]
    scan, checkout = Path(result["scan_dir"]), Path(result["checkout"])
    assert scan.is_absolute() and checkout.is_absolute()
    assert _same(scan.parent, temp_root)
    assert scan.name.startswith("detoxer-scan-")
    assert _same(checkout, scan / "checkout")
    assert result["commit"] == first and len(first) == 40
    assert _git(checkout, "rev-parse", "HEAD") == first
    assert _git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    assert any(_same(line[len("worktree "):], checkout)
               for line in _worktrees(repo).splitlines() if line.startswith("worktree "))


def test_create_with_an_unresolvable_ref_leaves_nothing(repo: Path, temp_root: Path,
                                                        capsys: pytest.CaptureFixture) -> None:
    before = _worktrees(repo)
    code, out, err = _run(capsys, "create", "--ref", "no-such-ref")
    assert (code, out) == (1, "")
    assert err.startswith("error: ")
    assert list(temp_root.iterdir()) == []
    assert _worktrees(repo) == before


def test_create_outside_a_repository_leaves_nothing(tmp_path: Path, temp_root: Path,
                                                    capsys: pytest.CaptureFixture,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    code, out, err = _run(capsys, "create", "--ref", "HEAD")
    assert (code, out) == (1, "")
    assert err.startswith("error: ")
    assert list(temp_root.iterdir()) == []


def test_create_failing_worktree_add_leaves_nothing(repo: Path, temp_root: Path,
                                                    capsys: pytest.CaptureFixture,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    real_git = scan_dir._git

    def failing_add(git: str, *args: str, cwd: str | None = None):
        if args[:2] == ("worktree", "add"):
            return subprocess.CompletedProcess([git, *args], 128, "", "fatal: boom\n")
        return real_git(git, *args, cwd=cwd)

    monkeypatch.setattr(scan_dir, "_git", failing_add)
    code, out, err = _run(capsys, "create", "--ref", "HEAD")
    assert (code, out) == (1, "")
    assert "fatal: boom" in err
    assert list(temp_root.iterdir()) == []


def test_create_without_git_fails(repo: Path, temp_root: Path, capsys: pytest.CaptureFixture,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scan_dir.shutil, "which", lambda name: None)
    code, out, err = _run(capsys, "create", "--ref", "HEAD")
    assert (code, out) == (1, "")
    assert "git not found" in err
    assert list(temp_root.iterdir()) == []


def test_remove_deletes_the_scan_directory_and_its_registration(
        repo: Path, temp_root: Path, capsys: pytest.CaptureFixture) -> None:
    result = _create(capsys)
    scan = result["scan_dir"]
    readonly = Path(scan) / "jscpd" / "report.json"
    readonly.parent.mkdir()
    readonly.write_text("{}", encoding="utf-8")
    os.chmod(readonly, stat.S_IREAD)
    os.chmod(Path(result["checkout"]) / "a.txt", stat.S_IREAD)
    code, out, err = _run(capsys, "remove", scan)
    assert (code, out, err) == (0, f"removed: {scan}\n", "")
    assert not os.path.lexists(scan)
    assert "detoxer-scan-" not in _worktrees(repo)
    code, out, err = _run(capsys, "remove", scan)
    assert (code, out, err) == (0, f"absent: {scan}\n", "")


def test_remove_still_deletes_when_worktree_remove_fails(
        repo: Path, temp_root: Path, capsys: pytest.CaptureFixture,
        monkeypatch: pytest.MonkeyPatch) -> None:
    scan = _create(capsys)["scan_dir"]
    real_git = scan_dir._git

    def failing_remove(git: str, *args: str, cwd: str | None = None):
        if args[:2] == ("worktree", "remove"):
            return subprocess.CompletedProcess([git, *args], 128, "", "fatal: locked\n")
        return real_git(git, *args, cwd=cwd)

    monkeypatch.setattr(scan_dir, "_git", failing_remove)
    code, out, err = _run(capsys, "remove", scan)
    assert (code, out) == (0, f"removed: {scan}\n")
    assert "fatal: locked" in err
    assert not os.path.lexists(scan)
    assert "detoxer-scan-" not in _worktrees(repo)


def test_remove_reports_failure_when_something_is_left(
        repo: Path, temp_root: Path, capsys: pytest.CaptureFixture,
        monkeypatch: pytest.MonkeyPatch) -> None:
    scan = _create(capsys)["scan_dir"]

    def failing_rmtree(path: str) -> None:
        raise OSError(f"cannot delete {path}")

    monkeypatch.setattr(scan_dir, "_rmtree", failing_rmtree)
    code, out, err = _run(capsys, "remove", scan)
    assert (code, out) == (1, f"failed: {scan}\n")
    assert err.startswith("error: cannot delete")
    assert os.path.isdir(scan)


def _assert_refused(capsys: pytest.CaptureFixture, target: Path) -> None:
    code, out, err = _run(capsys, "remove", str(target))
    assert (code, out) == (2, f"refused: {target}\n")
    assert err.startswith("error: ")


def test_remove_refuses_a_directory_outside_the_temp_directory(
        repo: Path, temp_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    outside = tmp_path / "detoxer-scan-outside"
    (outside / "keep").mkdir(parents=True)
    _assert_refused(capsys, outside)
    assert (outside / "keep").is_dir()
    nested = temp_root / "sub" / "detoxer-scan-nested"
    nested.mkdir(parents=True)
    _assert_refused(capsys, nested)
    assert nested.is_dir()


def test_remove_refuses_a_missing_path_outside_the_temp_directory(
        repo: Path, temp_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    _assert_refused(capsys, tmp_path / "detoxer-scan-missing")
    _assert_refused(capsys, temp_root / "other-missing")


def test_remove_refuses_a_name_without_the_prefix(
        repo: Path, temp_root: Path, capsys: pytest.CaptureFixture) -> None:
    other = temp_root / "other-scan"
    (other / "keep").mkdir(parents=True)
    _assert_refused(capsys, other)
    assert (other / "keep").is_dir()


def test_remove_refuses_a_file(repo: Path, temp_root: Path,
                               capsys: pytest.CaptureFixture) -> None:
    file = temp_root / "detoxer-scan-file"
    file.write_text("keep", encoding="utf-8")
    _assert_refused(capsys, file)
    assert file.read_text(encoding="utf-8") == "keep"


def _link_or_skip(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"cannot create a directory symlink: {error}")


def test_remove_refuses_a_link_pointing_outside(
        repo: Path, temp_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    target = tmp_path / "elsewhere"
    (target / "keep").mkdir(parents=True)
    link = temp_root / "detoxer-scan-link"
    _link_or_skip(link, target)
    _assert_refused(capsys, link)
    assert os.path.lexists(link)
    assert (target / "keep").is_dir()


def test_remove_refuses_a_link_to_another_scan_directory(
        repo: Path, temp_root: Path, capsys: pytest.CaptureFixture) -> None:
    target = temp_root / "detoxer-scan-real"
    (target / "keep").mkdir(parents=True)
    link = temp_root / "detoxer-scan-link"
    _link_or_skip(link, target)
    _assert_refused(capsys, link)
    assert os.path.lexists(link)
    assert (target / "keep").is_dir()


@pytest.mark.skipif(os.name != "nt", reason="junctions exist only on Windows")
def test_remove_refuses_a_junction_pointing_outside(
        repo: Path, temp_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    target = tmp_path / "elsewhere"
    (target / "keep").mkdir(parents=True)
    link = temp_root / "detoxer-scan-junction"
    made = subprocess.run([shutil.which("cmd"), "/c", "mklink", "/J", str(link), str(target)],
                          capture_output=True, check=False)
    if made.returncode != 0:
        pytest.skip("cannot create a junction")
    _assert_refused(capsys, link)
    assert os.path.lexists(link)
    assert (target / "keep").is_dir()
