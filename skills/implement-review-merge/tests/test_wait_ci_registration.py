"""Exercise registration with a stub gh and a deterministic monotonic clock."""

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
HEAD = "a" * 40


@pytest.fixture
def module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("wait_ci_registration", SCRIPTS / "wait_ci_registration.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "SKILL_DIR", tmp_path)
    clock = [0.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    monkeypatch.setattr(mod.time, "sleep", sleep)
    return mod


@pytest.mark.parametrize("responses,timeout,code,calls", [
    ([(HEAD, [{}])], 300, 0, 1),
    ([("b" * 40, [{}]), (HEAD, []), (HEAD, [{}])], 90, 0, 3),
    ([(HEAD, None)], 31, 2, 2),
    ([(HEAD, [])], 60, 2, 2),
])
def test_registration(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    responses: list[tuple[str, list[dict[str, object]] | None]], timeout: int, code: int, calls: int,
) -> None:
    seen = []

    def gh(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        assert cmd == ["gh", "pr", "view", "135", "--json", "headRefOid,statusCheckRollup"]
        assert kwargs["timeout"] > 0
        head, checks = responses[min(len(seen), len(responses) - 1)]
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, json.dumps({
            "headRefOid": head, "statusCheckRollup": checks}), "")

    monkeypatch.setattr(module.subprocess, "run", gh)
    assert module.wait_for_registration(135, HEAD, timeout) == code
    assert len(seen) == calls
    expected = (f"ci-registration: registered {HEAD}" if code == 0 else
                f"ci-registration: timeout after {timeout}s (head {HEAD})")
    assert capsys.readouterr().out.strip() == expected


@pytest.mark.parametrize("failure", ["exit", "missing", "json", "shape", "checks"])
def test_gh_errors(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    def gh(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if failure == "missing":
            raise FileNotFoundError("gh missing")
        stdout = {"exit": "", "json": "{", "shape": "[]",
                  "checks": json.dumps({"headRefOid": HEAD, "statusCheckRollup": {}})}[failure]
        return subprocess.CompletedProcess(cmd, 1 if failure == "exit" else 0, stdout, "denied")

    monkeypatch.setattr(module.subprocess, "run", gh)
    assert module.main(["--pr", "135", "--head", HEAD]) == 1
    assert capsys.readouterr().out.startswith("error: ")


def test_gh_cannot_exceed_registration_deadline(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def gh(cmd: list[str], **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(module.subprocess, "run", gh)
    assert module.main(["--pr", "135", "--head", HEAD]) == 2
    assert "timeout after 300s" in capsys.readouterr().out


@pytest.mark.parametrize("value,expected", [(None, 300), ("1", 1), ("45", 45),
                                           ("0", None), ("-1", None), ("abc", None),
                                           ("1.5", None), ("", None)])
def test_timeout_config(
    module: ModuleType, tmp_path: Path, value: str | None, expected: int | None,
) -> None:
    path = tmp_path / "config.conf"
    if value is not None:
        path.write_text(f"CI_REGISTRATION_TIMEOUT_SECONDS={value}", encoding="utf-8")
    if expected is None:
        with pytest.raises(ValueError, match="positive integer"):
            module.read_config(path)
    else:
        assert module.read_config(path)["CI_REGISTRATION_TIMEOUT_SECONDS"] == expected


def test_missing_timeout_key_uses_default(module: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "config.conf"
    path.write_text("SYNC_LOCAL_MAIN_AFTER_MERGE=false\n", encoding="utf-8")
    assert module.read_config(path) == {"SYNC_LOCAL_MAIN_AFTER_MERGE": False,
                                       "CI_REGISTRATION_TIMEOUT_SECONDS": 300}


@pytest.mark.parametrize("config", ["UNKNOWN=true", "CI_REGISTRATION_TIMEOUT_SECONDS=0",
                                   "SYNC_LOCAL_MAIN_AFTER_MERGE=no"])
def test_invalid_config_prevents_gh(
    module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], config: str,
) -> None:
    (tmp_path / "config.conf").write_text(config, encoding="utf-8")

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid config must not invoke gh")

    monkeypatch.setattr(module.subprocess, "run", forbidden)
    assert module.main(["--pr", "135", "--head", HEAD]) == 1
    assert capsys.readouterr().out.startswith("error: ")
