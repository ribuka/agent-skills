"""Gate work on Claude statusLine or live Codex quota; standard library only."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime


RESET_TOLERANCE = 120.0
# Wait before the single local re-check of an UNKNOWN result, so that an
# in-flight statusLine callback can finish writing its snapshot.
LOCAL_RETRY_SECONDS = 2
# A caller checkpoint is `<checkpoint_dir>/<operation-id>.md`.
OPERATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".quota-", delete=False) as stream:
            name = stream.name
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def valid_window(window):
    return (isinstance(window, dict) and number(window.get("used_percentage"))
            and 0 <= window["used_percentage"] <= 100
            and number(window.get("resets_at")) and window["resets_at"] > 0)


def record(root: Path, payload: dict, now: float):
    """Keep one atomic file per session to avoid inter-session lost updates."""
    session = payload.get("session_id")
    if not isinstance(session, str) or not session:
        raise ValueError("Missing session_id in statusLine input")
    key = hashlib.sha256(session.encode()).hexdigest()
    path = root / "sessions" / f"{key}.json"
    window = (payload.get("rate_limits") or {}).get("five_hour")
    if not valid_window(window):
        # Missing fields do not erase another session's valid telemetry.
        return
    try:
        old = read_json(path)
    except (OSError, ValueError):
        old = {}
    if not isinstance(old, dict):
        old = {}
    cost = payload.get("cost") or {}
    context = payload.get("context_window") or {}
    evidence = {"window": window, "prompt": payload.get("prompt_id"),
                "api_ms": cost.get("total_api_duration_ms"),
                "input": context.get("total_input_tokens"),
                "output": context.get("total_output_tokens"),
                "usage": context.get("current_usage")}
    fingerprint = hashlib.sha256(json.dumps(evidence, sort_keys=True,
                                           allow_nan=False).encode()).hexdigest()
    source_at = now if fingerprint != old.get("fingerprint") else old.get("source_at", now)
    reset = window["resets_at"]
    previous = old.get("window") or {}
    if valid_window(previous) and previous["resets_at"] > reset + RESET_TOLERANCE:
        return  # Do not regress to an older reset window.
    high = window["used_percentage"]
    if valid_window(previous) and abs(previous["resets_at"] - reset) <= RESET_TOLERANCE:
        high = max(high, previous["used_percentage"])
        reset = max(reset, previous["resets_at"])
    atomic_json(path, {"schema": 1, "observed_at": now, "source_at": source_at,
                       "fingerprint": fingerprint,
                       "window": {"used_percentage": high, "resets_at": reset}})


def wakeup(epoch: float):
    # Ceil to a full minute and avoid Claude's :00 / :30 early-fire jitter.
    epoch = math.ceil(epoch / 60) * 60
    local = datetime.fromtimestamp(epoch).astimezone()
    if local.minute in (0, 30):
        epoch += 60
        local = datetime.fromtimestamp(epoch).astimezone()
    return {"wake_at": epoch, "wake_local": local.isoformat(),
            "cron": f"{local.minute} {local.hour} {local.day} {local.month} *"}


def check(root: Path, now: float, threshold=95.0, max_age=180.0):
    """Use fresh evidence for READY; latch high usage until its reset."""
    records = []
    for path in (root / "sessions").glob("*.json"):
        try:
            data = read_json(path)
            window = data.get("window")
            if (data.get("schema") == 1 and valid_window(window)
                    and number(data.get("source_at"))
                    and data["source_at"] <= now + 5
                    and window["resets_at"] + RESET_TOLERANCE > now):
                records.append(data)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    # Never resurrect an older window when newer evidence becomes stale.
    reset = max((r["window"]["resets_at"] for r in records), default=None)
    records = [r for r in records
               if reset - r["window"]["resets_at"] <= RESET_TOLERANCE]
    fresh = [r for r in records if 0 <= now - r["source_at"] <= max_age
             and r["window"]["resets_at"] > now]
    high = [r for r in records if r["window"]["used_percentage"] >= threshold]
    result = {"state": "UNKNOWN", "reason": "missing_or_stale_telemetry",
              "threshold": threshold, "upstream_freshness": "not_guaranteed",
              "checkpoint_dir": str(root / "checkpoints")}
    if high:
        chosen = max(high, key=lambda r: r["window"]["used_percentage"])
        result.update(state="PAUSED_QUOTA", reason="threshold_reached",
                      **chosen["window"])
        result["resets_at"] = reset
        result.update(wakeup(reset + RESET_TOLERANCE))
    elif fresh:
        chosen = max(fresh, key=lambda r: r["window"]["used_percentage"])
        result.update(state="READY", reason="recent_local_evidence", **chosen["window"])
    else:
        result["local_retry_seconds"] = LOCAL_RETRY_SECONDS
        result.update(wakeup(now + 900))
    return result


def read_codex_limits(timeout: float = 20.0) -> dict:
    """Read one live snapshot over app-server stdio, without starting a turn."""
    executable = shutil.which("codex")
    if not executable:
        raise FileNotFoundError("codex executable unavailable")
    windows = sys.platform == "win32"
    process = subprocess.Popen(
        [executable, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
        start_new_session=not windows,
        creationflags=subprocess.CREATE_NO_WINDOW if windows else 0)
    lines: queue.Queue = queue.Queue()

    def receive() -> None:
        try:
            for line in process.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=receive, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout

    def send(message: dict) -> None:
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def response(request_id: int) -> dict:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Codex app-server timed out")
            try:
                line = lines.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError("Codex app-server timed out") from None
            if line is None:
                raise ValueError("Codex app-server closed before response")
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("Invalid Codex app-server message")
            if message.get("id") != request_id:
                continue  # Ignore notifications and unrelated responses.
            if "error" in message:
                raise ValueError("Codex app-server request failed")
            result = message.get("result")
            if not isinstance(result, dict):
                raise ValueError("Invalid Codex app-server result")
            return result

    try:
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "quota_guard", "version": "1.0.0"}}})
        response(1)
        send({"method": "initialized", "params": {}})
        send({"id": 2, "method": "account/rateLimits/read"})
        return response(2)
    finally:
        # npm's Windows shim owns a child process; terminate that tree too.
        try:
            if not windows:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            elif process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            reader.join(timeout=1)
            process.stdin.close()
            # A surviving descendant may still own the pipe. Never wait on the
            # reader's buffered-stream lock after the bounded join.
            if not reader.is_alive():
                process.stdout.close()


def check_codex(root: Path, now: float, threshold: float = 95.0) -> dict:
    """Fail closed on unavailable limits; also block exhausted weekly usage."""
    result = {"state": "UNKNOWN", "reason": "codex_telemetry_unavailable",
              "provider": "codex", "threshold": threshold,
              "checkpoint_dir": str(root / "checkpoints"),
              "local_retry_seconds": LOCAL_RETRY_SECONDS,
              **wakeup(now + 900)}
    try:
        snapshot = read_codex_limits()["rateLimits"]
        if not isinstance(snapshot, dict) or snapshot.get("limitId") != "codex":
            raise ValueError("Missing Codex quota bucket")
        windows = []
        for name in ("primary", "secondary"):
            raw = snapshot.get(name)
            if raw is None and name == "secondary":
                continue
            if not isinstance(raw, dict):
                raise ValueError("Missing quota window")
            window = {"used_percentage": raw.get("usedPercent"),
                      "resets_at": raw.get("resetsAt")}
            duration = raw.get("windowDurationMins")
            if (not valid_window(window) or window["resets_at"] <= now
                    or not number(duration) or duration <= 0):
                raise ValueError("Invalid or expired quota window")
            datetime.fromtimestamp(window["resets_at"])
            windows.append((name, duration, window))
        if windows[0][1] != 300:
            raise ValueError("Primary quota window is not five hours")
        blocked = [(name, window) for name, _, window in windows
                   if window["used_percentage"] >= (threshold if name == "primary" else 100)]
        if blocked:
            name, chosen = max(blocked, key=lambda item: item[1]["resets_at"])
            schedule = wakeup(chosen["resets_at"] + RESET_TOLERANCE)
            result.update(state="PAUSED_QUOTA", reason="threshold_reached" if name == "primary"
                          else "secondary_exhausted", blocking_window=name, **chosen)
            result.update(schedule)
        elif snapshot.get("rateLimitReachedType") is not None:
            result["reason"] = "server_limit_reached"
            return result
        else:
            result.update(state="READY", reason="live_account_rate_limits", **windows[0][2])
            for key in ("wake_at", "wake_local", "cron"):
                result.pop(key)
        result.pop("local_retry_seconds")
    except (OSError, ValueError, TypeError, KeyError, OverflowError, subprocess.SubprocessError):
        pass
    return result


def wake(terminal: str, text: str, executable: str) -> int:
    """Send a resume prompt; always fail the automation precheck to skip its agent."""
    try:
        completed = subprocess.run(
            [executable, "terminal", "send", "--terminal", terminal, "--text", text, "--enter"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        print(json.dumps({"sent": completed.returncode == 0}))
    except (OSError, subprocess.SubprocessError):
        print(json.dumps({"sent": False}))
    return 1


def clear_checkpoint(root: Path, operation: str) -> tuple[int, dict]:
    """Delete one finished operation's checkpoint; absent counts as success."""
    if not OPERATION_ID.fullmatch(operation):
        return 2, {"removed": False, "reason": f"invalid operation ID: {operation!r}"}
    path = root / "checkpoints" / f"{operation}.md"
    try:
        path.unlink()
    except FileNotFoundError:
        return 0, {"removed": False, "path": str(path)}
    except OSError as error:
        return 1, {"removed": False, "path": str(path), "reason": str(error)}
    return 0, {"removed": True, "path": str(path)}


def quote_command(value):
    # Double quoted forward-slash paths work in Windows cmd and Git Bash.
    value = str(value).replace("\\", "/")
    if any(c in value for c in ('"', '$', '`', '\n', '\r', '%', '!')):
        raise ValueError("Unsupported shell metacharacter in executable/file path")
    return f'"{value}"'


def configure(root: Path, settings: Path):
    settings.parent.mkdir(parents=True, exist_ok=True)
    config = read_json(settings) if settings.exists() else {}
    if not isinstance(config, dict):
        raise ValueError("settings.json must contain an object")
    settings_key = hashlib.sha256(
        os.path.normcase(str(settings.resolve())).encode()).hexdigest()
    previous_file = root / f"previous-{settings_key}.json"
    old = config.get("statusLine")
    script = Path(__file__).resolve()
    # Launch through uv, never sys.executable: the running interpreter may be a
    # project .venv that differs per repository and can be deleted or rebuilt.
    # `uv run` exports UV as its own path; PATH may start with the venv's bin.
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        raise FileNotFoundError("uv executable unavailable")
    command = (f'{quote_command(Path(uv).resolve())} run --no-project '
               f'{quote_command(script)} statusline '
               f'--state-dir {quote_command(root.resolve())} '
               f'--previous-config {quote_command(previous_file.resolve())}')
    if old and (not isinstance(old, dict) or old.get("type") != "command"
                or not isinstance(old.get("command"), str)):
        raise ValueError("Unsupported existing statusLine; leave settings unchanged")
    already = isinstance(old, dict) and "quota_guard.py" in old.get("command", "")
    if already:
        # Migrate the backup referenced by the installed wrapper, including the
        # legacy shared filename. Never wrap the wrapper as the old command.
        tokens = shlex.split(old["command"])
        try:
            source = Path(tokens[tokens.index("--previous-config") + 1])
        except (ValueError, IndexError):
            raise ValueError("Previous statusLine backup path missing; leave settings unchanged")
        previous = read_json(source)
        if not isinstance(previous, dict):
            raise ValueError("Invalid previous statusLine backup; leave settings unchanged")
        if source.resolve() != previous_file.resolve():
            atomic_json(previous_file, previous)
    else:
        atomic_json(previous_file, old or {})
    new = dict(old or {})
    new.update(type="command", command=command)
    interval = new.get("refreshInterval", 60)
    new["refreshInterval"] = min(interval, 60) if number(interval) and interval >= 1 else 60
    result = {"settings": str(settings), "state_dir": str(root),
              "refreshInterval": new["refreshInterval"]}
    if old == new:
        previous = read_json(previous_file)
        if not isinstance(previous, dict):
            raise ValueError("Invalid previous statusLine backup; leave settings unchanged")
        return {**result, "changed": False}
    config["statusLine"] = new
    if settings.exists():
        backup = settings.with_name(f"{settings.name}.quota-guard-{time.time_ns()}.bak")
        backup.write_bytes(settings.read_bytes())
    atomic_json(settings, config)
    return {**result, "changed": True}


def git_bash():
    """Resolve the Windows shell used by Claude; never fall back to cmd.exe."""
    explicit = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if explicit:
        if Path(explicit).is_file():
            return explicit
        raise FileNotFoundError("CLAUDE_CODE_GIT_BASH_PATH does not exist")
    candidates = []
    git = shutil.which("git")
    if git:
        candidates.append(Path(git).resolve().parent.parent / "bin" / "bash.exe")
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / ("Programs/Git" if variable == "LOCALAPPDATA"
                                           else "Git") / "bin" / "bash.exe")
    candidates.append(Path(shutil.which("bash.exe") or ""))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError("Git Bash unavailable; set CLAUDE_CODE_GIT_BASH_PATH")


def render_previous(path: Path | None, raw: str):
    if not path:
        return ""
    previous = read_json(path)
    if not isinstance(previous, dict):
        raise ValueError("Previous statusLine configuration must be an object")
    command = previous.get("command")
    if not command:
        return ""
    if not isinstance(command, str):
        raise ValueError("Previous statusLine command must be a string")
    windows = sys.platform == "win32"
    invocation = [git_bash(), "-c", command] if windows else command
    completed = subprocess.run(invocation, shell=not windows, input=raw, text=True,
                               encoding="utf-8", errors="replace", capture_output=True,
                               timeout=3,
                               creationflags=subprocess.CREATE_NO_WINDOW if windows else 0)
    if completed.returncode:
        raise RuntimeError("Existing statusLine command failed")
    return completed.stdout.rstrip("\n")


def main():
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    wake_parser = sub.add_parser("wake")
    wake_parser.add_argument("--terminal", required=True)
    wake_parser.add_argument("--text", required=True)
    wake_parser.add_argument("--orca", required=True, help="Resolved Orca executable absolute path")
    default = Path.home() / ".claude" / "quota-guard"
    for name in ("statusline", "check", "configure", "clear-checkpoint"):
        item = sub.add_parser(name)
        item.add_argument("--state-dir", type=Path)
        if name in ("statusline", "check"):
            item.add_argument("--threshold", type=float, default=95)
            item.add_argument("--max-age", type=float, default=180)
        if name == "statusline":
            item.add_argument("--previous-config", type=Path)
        if name == "configure":
            item.add_argument("--settings", type=Path,
                              default=Path.home() / ".claude" / "settings.json")
        if name in ("check", "clear-checkpoint"):
            item.add_argument("--provider", choices=("claude", "codex"), default="claude")
        if name == "clear-checkpoint":
            item.add_argument("--operation", required=True)
    args = parser.parse_args()
    try:
        if args.action == "wake":
            return wake(args.terminal, args.text, args.orca)
        if args.state_dir is None:
            args.state_dir = (Path.home() / ".codex" / "quota-guard"
                              if getattr(args, "provider", None) == "codex" else default)
        if args.action == "clear-checkpoint":
            code, result = clear_checkpoint(args.state_dir, args.operation)
            print(json.dumps(result))
            return code
        if args.action == "configure":
            result = configure(args.state_dir, args.settings)
            print(json.dumps(result))
            return 0
        if not (0 < args.threshold <= 100 and args.max_age > 0
                and math.isfinite(args.max_age)):
            raise ValueError("threshold must be (0,100]; max-age must be positive")
        if args.action == "statusline":
            raw = sys.stdin.read()
            previous = ""
            try:
                previous = render_previous(args.previous_config, raw)
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                previous = "[previous statusLine unavailable]"
            try:
                record(args.state_dir, json.loads(raw), time.time())
                result = check(args.state_dir, time.time(), args.threshold, args.max_age)
                pct = result.get("used_percentage")
                text = f"5h {pct:g}% {result['state']}" if pct is not None else "5h UNKNOWN"
            except (OSError, ValueError, TypeError, AttributeError):
                text = "5h UNKNOWN (telemetry write failed)"
            print((previous + "\n" if previous else "") + text)
            return 0
        if args.provider == "codex":
            result = check_codex(args.state_dir, time.time(), args.threshold)
        else:
            result = check(args.state_dir, time.time(), args.threshold, args.max_age)
        print(json.dumps(result, separators=(",", ":")))
        return {"READY": 0, "PAUSED_QUOTA": 10, "UNKNOWN": 20}[result["state"]]
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print(json.dumps({"state": "UNKNOWN", "reason": str(error)}))
        return 20


if __name__ == "__main__":
    sys.exit(main())
