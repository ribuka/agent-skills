"""Collect Claude statusLine telemetry and gate work; Python standard library only."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from datetime import datetime


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
    if valid_window(previous) and previous["resets_at"] > reset:
        return  # Do not regress to an older reset window.
    high = window["used_percentage"]
    if previous.get("resets_at") == reset and number(previous.get("used_percentage")):
        high = max(high, previous["used_percentage"])
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
                    and window["resets_at"] > now):
                records.append(data)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    # Never resurrect an older window when newer evidence becomes stale.
    reset = max((r["window"]["resets_at"] for r in records), default=None)
    records = [r for r in records if r["window"]["resets_at"] == reset]
    fresh = [r for r in records if 0 <= now - r["source_at"] <= max_age]
    high = [r for r in records if r["window"]["used_percentage"] >= threshold]
    result = {"state": "UNKNOWN", "reason": "missing_or_stale_telemetry",
              "threshold": threshold, "upstream_freshness": "not_guaranteed"}
    if high:
        chosen = max(high, key=lambda r: r["window"]["resets_at"])
        result.update(state="PAUSED_QUOTA", reason="threshold_reached",
                      **chosen["window"])
        result.update(wakeup(chosen["window"]["resets_at"] + 120))
    elif fresh:
        chosen = max(fresh, key=lambda r: r["window"]["used_percentage"])
        result.update(state="READY", reason="recent_local_evidence", **chosen["window"])
    else:
        result.update(wakeup(now + 900))
    return result


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
    previous_file = root / "previous-statusline.json"
    old = config.get("statusLine")
    script = Path(__file__).resolve()
    command = (f'{quote_command(sys.executable)} {quote_command(script)} statusline '
               f'--state-dir {quote_command(root.resolve())} '
               f'--previous-config {quote_command(previous_file.resolve())}')
    if old and (not isinstance(old, dict) or old.get("type") != "command"
                or not isinstance(old.get("command"), str)):
        raise ValueError("Unsupported existing statusLine; leave settings unchanged")
    already = isinstance(old, dict) and "quota_guard.py" in old.get("command", "")
    if not already:
        atomic_json(previous_file, old or {})
    elif not previous_file.exists():
        raise ValueError("Previous statusLine backup missing; leave settings unchanged")
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


def render_previous(path: Path | None, raw: str):
    if not path:
        return ""
    previous = read_json(path)
    command = previous.get("command")
    if not command:
        return ""
    completed = subprocess.run(command, shell=True, input=raw, text=True,
                               encoding="utf-8", errors="replace", capture_output=True,
                               timeout=3)
    if completed.returncode:
        raise RuntimeError("Existing statusLine command failed")
    return completed.stdout.rstrip("\n")


def main():
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    default = Path.home() / ".claude" / "quota-guard"
    for name in ("statusline", "check", "configure"):
        item = sub.add_parser(name)
        item.add_argument("--state-dir", type=Path, default=default)
        if name in ("statusline", "check"):
            item.add_argument("--threshold", type=float, default=95)
            item.add_argument("--max-age", type=float, default=180)
        if name == "statusline":
            item.add_argument("--previous-config", type=Path)
        if name == "configure":
            item.add_argument("--settings", type=Path,
                              default=Path.home() / ".claude" / "settings.json")
    args = parser.parse_args()
    try:
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
        result = check(args.state_dir, time.time(), args.threshold, args.max_age)
        print(json.dumps(result, separators=(",", ":")))
        return {"READY": 0, "PAUSED_QUOTA": 10, "UNKNOWN": 20}[result["state"]]
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print(json.dumps({"state": "UNKNOWN", "reason": str(error)}))
        return 20


if __name__ == "__main__":
    sys.exit(main())
