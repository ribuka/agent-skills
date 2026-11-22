"""Post a Markdown article to Qiita as private (limited share), update it, and make it public on request.

The Qiita access token is stored in Windows Credential Manager by `set-token`,
never in this repository, in the article file, or on the command line.
A new article is always created private; only `publish` makes it public.
"""

from __future__ import annotations

import argparse
import datetime
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://qiita.com/api/v2"
CRED_TARGET = "agent-skills/qiita-post"
SKILL_DIR = Path(__file__).resolve().parents[1]
FIELDS = ("title", "tags", "private", "id", "url", "updated_at")
TIMEOUT_SECONDS = 30
SET_TOKEN_COMMAND = "uv run --no-project ~/.agents/skills/qiita-post/scripts/qiita_post.py set-token"


class Failure(Exception):
    """A command failed; `kind` is printed so callers need not rely on exit codes."""

    def __init__(self, message: str, kind: str = "failed", code: int = 1) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code


def no_token(message: str) -> Failure:
    return Failure(f"{message}; ask the user to run `{SET_TOKEN_COMMAND}` in their own terminal",
                   "no-token", 3)


def out_of_sync(message: str) -> Failure:
    return Failure(message, "out-of-sync", 4)


# --- config -----------------------------------------------------------------

def load_config() -> dict[str, str]:
    """Read config.conf, then the git-ignored config.local.conf over it."""
    shared = SKILL_DIR / "config.conf"
    if not shared.is_file():
        raise Failure(f"{shared} is missing")
    values: dict[str, str] = {}
    for path in (shared, SKILL_DIR / "config.local.conf"):
        if not path.is_file():
            continue
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not sep or key not in CONFIG_KEYS or (not value and key != "PRIVATE_WORDS"):
                raise Failure(f"{path}:{number}: invalid line: {raw}")
            values[key] = value
    for key in CONFIG_KEYS:
        if key not in values:
            raise Failure(f"{key} is not set in {shared}")
    return values


CONFIG_KEYS = ("DRAFTS_DIR", "PRIVATE_WORDS")


def drafts_dir() -> Path:
    return Path(os.path.expandvars(os.path.expanduser(load_config()["DRAFTS_DIR"])))


# --- private information check ----------------------------------------------

# Boundaries use ASCII classes, not \b: \b treats Japanese as word characters, so
# "連絡先taro@example.jpです" would not match.
_BEFORE = r"(?<![A-Za-z0-9_])"
_AFTER = r"(?![A-Za-z0-9_])"
SECRET_PATTERNS = (
    ("email address", re.compile(r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+)@"
                                 r"((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})(?![A-Za-z0-9-])")),
    ("user home path", re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/]+Users[\\/]+([^\\/\s\"'`<>|]+)")),
    ("user home path", re.compile(r"(?<![A-Za-z0-9_.~:])/(?:Users|home)/([^/\s\"'`<>|]+)")),
    ("40-hex token (shorten a commit SHA)", re.compile(r"(?<![0-9A-Fa-f])[0-9a-f]{40}(?![0-9A-Fa-f])")),
    ("GitHub token", re.compile(_BEFORE + r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("API key", re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}")),
    ("AWS access key", re.compile(_BEFORE + r"AKIA[0-9A-Z]{16}" + _AFTER)),
    ("Slack token", re.compile(_BEFORE + r"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)
PLACEHOLDER_USERS = {"public", "default", "user", "username", "yourname", "you", "me", "name",
                     "example", "runner", "foo"}
PLACEHOLDER_EMAIL_LOCALS = {"git"}
EXAMPLE_DOMAIN = re.compile(r"(?i)(?:^|\.)(?:example\.(?:com|org|net)|[a-z0-9-]+\.(?:example|test|invalid))$")


def private_words() -> list[str]:
    """PRIVATE_WORDS from the config, plus the name of the current user's home directory."""
    words = [w.strip() for w in load_config()["PRIVATE_WORDS"].split(",") if w.strip()]
    home = Path.home().name
    if home and home.lower() not in PLACEHOLDER_USERS:
        words.append(home)
    return words


def is_placeholder(kind: str, match: re.Match) -> bool:
    if kind == "email address":
        return match.group(1).lower() in PLACEHOLDER_EMAIL_LOCALS or bool(EXAMPLE_DOMAIN.search(match.group(2)))
    if kind == "user home path":
        name = match.group(1)
        return name[0] in "<%${*" or name.lower() in PLACEHOLDER_USERS
    return False


def mask(text: str) -> str:
    return text[:3] + "***" if len(text) > 4 else "***"


def word_pattern(word: str) -> re.Pattern:
    """Match a word case-insensitively; ASCII words only as whole words."""
    escaped = re.escape(word)
    if word.isascii():
        escaped = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
    return re.compile(escaped, re.IGNORECASE)


def find_private_info(text: str, words: list[str]) -> list[str]:
    """Return `line N: <kind> (<masked match>)` for each suspected piece of private information."""
    checks = [*SECRET_PATTERNS, *(("private word", word_pattern(w)) for w in words)]
    findings = []
    for number, line in enumerate(text.split("\n"), 1):
        for kind, pattern in checks:
            for match in pattern.finditer(line):
                if not is_placeholder(kind, match):
                    findings.append(f"line {number}: {kind} ({mask(match.group(0))})")
    return findings


def check_private_info(title: str, tags: list[str], body: str) -> None:
    """Stop before sending an article that looks like it contains private information."""
    words = private_words()
    findings = [f"title: {f.split(': ', 1)[1]}" for f in find_private_info(title, words)]
    findings += [f"tags: {f.split(': ', 1)[1]}" for f in find_private_info(" ".join(tags), words)]
    findings += [f"body {f}" for f in find_private_info(body, words)]
    if findings:
        raise Failure("the article looks like it contains private information; generalize or remove it: "
                      + "; ".join(findings), "private-info", 5)


# --- article file -----------------------------------------------------------

def parse_value(raw: str) -> object:
    """Parse the small YAML subset this script writes: JSON strings/lists, booleans, empty."""
    if raw == "":
        return None
    if raw in ("true", "false"):
        return raw == "true"
    if raw[0] in "\"[":
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if raw[0] == "[" and raw.endswith("]"):
                return [t.strip().strip("'\"") for t in raw[1:-1].split(",") if t.strip()]
            raise
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1].replace("''", "'")
    return raw


def read_article(path: Path) -> tuple[dict[str, object], str]:
    """Return (frontmatter, body) of an article file and validate title and tags."""
    if not path.is_file():
        raise Failure(f"{path} does not exist")
    lines = path.read_text(encoding="utf-8").removeprefix("﻿").split("\n")
    if lines[0].rstrip("\r") != "---":
        raise Failure(f"{path} does not start with a --- frontmatter block")
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r") == "---"), None)
    if end is None:
        raise Failure(f"{path}: frontmatter block is not closed")
    meta: dict[str, object] = {}
    for raw in lines[1:end]:
        line = raw.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        key = key.strip()
        if not sep or key not in FIELDS:
            raise Failure(f"{path}: unsupported frontmatter line: {line!r} "
                          f"(keys: {', '.join(FIELDS)}; tags as [\"A\", \"B\"])")
        try:
            meta[key] = parse_value(value.strip())
        except json.JSONDecodeError as exc:
            raise Failure(f"{path}: invalid value for `{key}`: {exc}") from exc
    title, tags = meta.get("title"), meta.get("tags")
    if not isinstance(title, str) or not title.strip():
        raise Failure(f"{path}: frontmatter `title` is missing")
    if (not isinstance(tags, list) or not 1 <= len(tags) <= 5
            or not all(isinstance(t, str) and t and not re.search(r"\s", t) for t in tags)):
        raise Failure(f"{path}: frontmatter `tags` must list 1-5 tag names without spaces")
    body = "\n".join(lines[end + 1:]).lstrip("\r\n")
    if not body.strip():
        raise Failure(f"{path}: article body is empty")
    return meta, body


def dump_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value, ensure_ascii=False)


def write_article(path: Path, meta: dict[str, object], body: str) -> None:
    lines = ["---", *(f"{key}: {dump_value(meta.get(key))}".rstrip() for key in FIELDS), "---", "", body]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def sync_meta(meta: dict[str, object], item: dict) -> None:
    """Record the server-owned fields of a Qiita item in the frontmatter.

    Tags are taken from Qiita too: it may rename a tag to its canonical name (e.g. `test` to `テスト`).
    """
    meta.update(id=item["id"], url=item["url"], private=item["private"], updated_at=item["updated_at"],
                tags=[t["name"] for t in item["tags"]])


def tag_payload(names: list[str]) -> list[dict]:
    return [{"name": name, "versions": []} for name in names]


def normalize(text: str) -> str:
    """Ignore only line-ending style and trailing newlines; other whitespace can change Markdown."""
    return text.replace("\r\n", "\n").rstrip("\n")


def same_content(meta: dict[str, object], body: str, item: dict) -> bool:
    return (meta["title"] == item["title"]
            and meta["tags"] == [t["name"] for t in item["tags"]]
            and normalize(body) == normalize(item["body"]))


def require_id(meta: dict[str, object], path: Path) -> str:
    item_id = meta.get("id")
    if not isinstance(item_id, str) or not re.fullmatch(r"[0-9a-f]{20}", item_id):
        raise Failure(f"{path} has no valid Qiita `id`; run create first")
    return item_id


# --- token (Windows Credential Manager) --------------------------------------

def _credential_api():  # noqa: ANN202 - ctypes objects
    if sys.platform != "win32":
        raise Failure("token storage needs Windows Credential Manager (win32 only)")
    import ctypes
    from ctypes import wintypes

    class Credential(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
        ]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.POINTER(ctypes.POINTER(Credential))]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    advapi32.CredWriteW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    return ctypes, advapi32, Credential


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


def read_token() -> str | None:
    ctypes, advapi32, credential = _credential_api()
    pointer = ctypes.POINTER(credential)()
    if not advapi32.CredReadW(CRED_TARGET, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        error = ctypes.get_last_error()
        if error == ERROR_NOT_FOUND:
            return None
        raise Failure(f"reading the token from Credential Manager failed: {ctypes.FormatError(error)}")
    try:
        cred = pointer.contents
        return ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize).decode("utf-8")
    finally:
        advapi32.CredFree(pointer)


def store_token(token: str) -> None:
    ctypes, advapi32, credential = _credential_api()
    blob = token.encode("utf-8")
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = credential()
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = CRED_TARGET
    cred.UserName = "qiita"
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    if not advapi32.CredWriteW(ctypes.byref(cred), 0):
        raise Failure("storing the token in Credential Manager failed: "
                      f"{ctypes.FormatError(ctypes.get_last_error())}")


def token() -> str:
    value = read_token()
    if not value:
        raise no_token("no Qiita token is stored")
    return value


# --- Qiita API --------------------------------------------------------------

def api(method: str, path: str, access_token: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(f"{API_BASE}{path}", data=data, method=method, headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "agent-skills-qiita-post",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("message", detail)
        except (json.JSONDecodeError, AttributeError):
            pass
        if exc.code == 401:
            raise no_token(f"Qiita rejected the token (401: {detail})") from exc
        raise Failure(f"{method} {path} failed ({exc.code}): {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise Failure(f"{method} {path} failed: {getattr(exc, 'reason', exc)}") from exc


# --- commands ---------------------------------------------------------------

def cmd_set_token() -> list[str]:
    value = getpass.getpass("Qiita access token (scopes: read_qiita, write_qiita): ").strip()
    if not value:
        raise Failure("no token entered")
    user = api("GET", "/authenticated_user", value)
    store_token(value)
    return [f"stored: token for Qiita user {user.get('id')}"]


def cmd_draft_path(slug: str) -> list[str]:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise Failure(f"slug must be lowercase ASCII words joined by '-': {slug!r}")
    path = drafts_dir() / f"{datetime.date.today():%Y%m%d}-{slug}.md"
    if path.exists():
        raise Failure(f"{path} already exists; choose another slug")
    path.parent.mkdir(parents=True, exist_ok=True)
    return [f"path: {path}"]


def cmd_create(path: Path) -> list[str]:
    meta, body = read_article(path)
    if meta.get("id"):
        raise Failure(f"{path} is already posted (id {meta['id']}); use update")
    if meta.get("private") is False:
        raise Failure(f"{path}: the first post is always private; remove `private: false`")
    check_private_info(meta["title"], meta["tags"], body)
    item = api("POST", "/items", token(), {
        "title": meta["title"], "body": body, "tags": tag_payload(meta["tags"]),
        "private": True, "tweet": False,
    })
    sync_meta(meta, item)
    write_article(path, meta, body)
    if item["private"] is not True:
        raise Failure(f"posted, but Qiita reports the item as public: {item['url']}")
    return [f"id: {item['id']}", f"url: {item['url']}", "private: true"]


def cmd_update(path: Path) -> list[str]:
    meta, body = read_article(path)
    item_id = require_id(meta, path)
    check_private_info(meta["title"], meta["tags"], body)
    access_token = token()
    remote = api("GET", f"/items/{item_id}", access_token)
    if remote["updated_at"] != meta.get("updated_at"):
        raise out_of_sync(f"the article on Qiita was changed after {path} was last synced "
                          f"(remote updated_at {remote['updated_at']}); run pull to take the remote version")
    item = api("PATCH", f"/items/{item_id}", access_token, {
        "title": meta["title"], "body": body, "tags": tag_payload(meta["tags"]),
        "private": remote["private"],
    })
    sync_meta(meta, item)
    write_article(path, meta, body)
    return [f"url: {item['url']}", f"private: {dump_value(item['private'])}"]


def cmd_publish(path: Path) -> list[str]:
    meta, body = read_article(path)
    item_id = require_id(meta, path)
    access_token = token()
    remote = api("GET", f"/items/{item_id}", access_token)
    if not same_content(meta, body, remote):
        raise out_of_sync(f"{path} differs from the article on Qiita; run update (and let the user "
                          "review it) or pull before publishing")
    if remote["private"] is False:
        sync_meta(meta, remote)
        write_article(path, meta, body)
        return [f"url: {remote['url']}", "private: false", "note: already public"]
    check_private_info(remote["title"], [t["name"] for t in remote["tags"]], remote["body"])
    item = api("PATCH", f"/items/{item_id}", access_token, {
        "title": remote["title"], "body": remote["body"],
        "tags": [{"name": t["name"], "versions": t.get("versions", [])} for t in remote["tags"]],
        "private": False,
    })
    sync_meta(meta, item)
    write_article(path, meta, body)
    return [f"url: {item['url']}", f"private: {dump_value(item['private'])}"]


def cmd_pull(path: Path) -> list[str]:
    meta, _ = read_article(path)
    item_id = require_id(meta, path)
    remote = api("GET", f"/items/{item_id}", token())
    meta["title"] = remote["title"]
    sync_meta(meta, remote)
    write_article(path, meta, remote["body"])
    return [f"url: {remote['url']}", f"private: {dump_value(remote['private'])}", "note: local file replaced"]


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("set-token", help="store the Qiita token (run by the user in a terminal)")
    draft = commands.add_parser("draft-path", help="print the path for a new article file")
    draft.add_argument("--slug", required=True)
    for name in ("create", "update", "publish", "pull"):
        commands.add_parser(name).add_argument("file", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "set-token":
            lines = cmd_set_token()
        elif args.command == "draft-path":
            lines = cmd_draft_path(args.slug)
        else:
            handler = {"create": cmd_create, "update": cmd_update,
                       "publish": cmd_publish, "pull": cmd_pull}[args.command]
            lines = handler(args.file.expanduser().resolve())
    except Failure as exc:
        print(f"error: {exc.kind}: {exc}")
        return exc.code
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
