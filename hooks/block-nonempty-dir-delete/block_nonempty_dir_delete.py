"""PreToolUse hook for Bash: block commands that delete a non-empty directory.

Agents have deleted other tasks' files with `rm -rf tmp`. This hook denies:

- `rm -r` (and `-rf`, `-R`, `--recursive`) whose target is a non-empty directory,
  or whose target cannot be checked (command substitution, unset variable).
- Deletes whose targets cannot be checked at all: `find -delete` (unless `-empty`),
  `find -exec rm -r`, `xargs rm -r`, `git clean`, `shutil.rmtree`,
  `Remove-Item -Recurse`, `rd /s`, `rimraf`, `fs.rm(..., {recursive: true})`.

Files and empty directories can still be deleted with `rm` and `rmdir`.

Reads the hook input (JSON) from stdin and prints a deny decision, or nothing.
"""

import glob
import json
import os
import re
import shlex
import sys
from typing import NoReturn

PUNCTUATION = ";&|()<>\n"
PREFIXES = {
    "sudo",
    "command",
    "builtin",
    "env",
    "time",
    "nohup",
    "exec",
    "nice",
    "timeout",
}
SHELLS = {"bash", "sh", "zsh", "dash"}
INTERPRETERS = {
    "python",
    "python3",
    "py",
    "uv",
    "uvx",
    "node",
    "deno",
    "bun",
    "npx",
    "perl",
    "ruby",
    "pwsh",
    "powershell",
    "cmd",
}
RAW_PATTERNS = [
    (r"\brmtree\b", "shutil.rmtree"),
    (r"\bremove-item\b[^\n;|]*\s-r(ecurse)?\b", "Remove-Item -Recurse"),
    (r"\b(rd|rmdir)\s+(/{1,2}q\s+)?/{1,2}s\b", "rd /s"),
    (r"\brimraf\b", "rimraf"),
    (r"\bdeltree\b", "deltree"),
    (
        r"\b(rm|rmSync|rmdir|rmdirSync)\s*\([^)]*recursive\s*:\s*true",
        "fs.rm(recursive)",
    ),
]
STRING_LITERAL = re.compile(
    r'""".*?"""' r"|'''.*?'''" r'|"(\\.|[^"\\\n])*"' r"|'(\\.|[^'\\\n])*'", re.DOTALL
)
HOW_TO = "消すファイルを指定して rm で消し、空になったディレクトリを rmdir で消してください。"


class DeniedError(Exception):
    """The command must not run. The message is the reason shown to the agent."""


def deny(reason: str) -> NoReturn:
    """Stop checking and deny the command.

    Parameters
    ----------
    reason : str
        Reason shown to the agent.

    Raises
    ------
    DeniedError
        Always.
    """
    raise DeniedError(reason)


def scan_raw(text: str) -> None:
    """Deny code that deletes a directory tree with a library call.

    Parameters
    ----------
    text : str
        Code passed to an interpreter (an argument or a heredoc body).
    """
    # Text inside string literals is data (e.g. a script that edits code calling rmtree), not a call.
    code = STRING_LITERAL.sub('""', text)
    for pattern, label in RAW_PATTERNS:
        if re.search(pattern, code, re.IGNORECASE):
            deny(f"中身ごと消す削除（{label}）は禁止です。{HOW_TO}")


def split_heredocs(text: str) -> tuple[str, list[str]]:
    """Separate heredoc bodies from the command text.

    Parameters
    ----------
    text : str
        Shell command text.

    Returns
    -------
    tuple[str, list[str]]
        The text without heredoc bodies, and the bodies fed to interpreters or shells.
    """
    lines = text.split("\n")
    kept, scanned = [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        for _, word in re.findall(r"<<-?\s*(['\"]?)(\w+)\1", line):
            body = []
            while i < len(lines) and lines[i].strip() != word:
                body.append(lines[i])
                i += 1
            i += 1
            words = {
                os.path.basename(w).lower().removesuffix(".exe")
                for w in re.findall(r"[\w./\\-]+", line)
            }
            if words & (INTERPRETERS | SHELLS):
                scanned.append("\n".join(body))
    return "\n".join(kept), scanned


def tokenize(text: str) -> list[str]:
    """Split shell text into words and operator tokens (newline is an operator).

    Parameters
    ----------
    text : str
        Shell command text without heredoc bodies.

    Returns
    -------
    list[str]
        Tokens with quotes removed.

    Raises
    ------
    ValueError
        If a quote is not closed.
    """
    lexer = shlex.shlex(text, posix=True, punctuation_chars=PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    return list(lexer)


def split_commands(tokens: list[str]) -> list[list[str]]:
    """Group tokens into simple commands, dropping redirections.

    Parameters
    ----------
    tokens : list[str]
        Tokens from `tokenize`.

    Returns
    -------
    list[list[str]]
        Non-empty simple commands in order.
    """
    commands, current, skip = [], [], False
    for token in tokens:
        if skip:
            skip = False
            continue
        if token and all(c in PUNCTUATION for c in token):
            if "<" in token or ">" in token:
                if current and current[-1].isdigit():
                    current.pop()
                skip = True
            else:
                commands.append(current)
                current = []
            continue
        current.append(token)
    commands.append(current)
    return [c for c in commands if c]


def to_native(path: str) -> str:
    """Convert a Git Bash path (`/c/...`, `~`) to a path Python can open.

    Parameters
    ----------
    path : str
        Path as written in the command.

    Returns
    -------
    str
        Native path.
    """
    match = re.match(r"^/([a-zA-Z])(/|$)(.*)", path)
    if match and os.name == "nt":
        return f"{match.group(1)}:/{match.group(3)}"
    return os.path.expanduser(path)


def expand_braces(word: str) -> list[str]:
    """Expand `{a,b}` like the shell does.

    Parameters
    ----------
    word : str
        Word that may contain brace lists.

    Returns
    -------
    list[str]
        Expanded words.
    """
    match = re.search(r"\{([^{}]*,[^{}]*)\}", word)
    if not match:
        return [word]
    head, tail = word[: match.start()], word[match.end() :]
    return [
        w
        for part in match.group(1).split(",")
        for w in expand_braces(head + part + tail)
    ]


def check_target(target: str, cwd: str | None) -> None:
    """Deny when a recursive delete target is, or may be, a non-empty directory.

    Parameters
    ----------
    target : str
        Operand of `rm -r`, with quotes removed.
    cwd : str or None
        Working directory, or None when it is unknown.
    """
    if "$(" not in target:
        target = os.path.expandvars(target)
    if "$" in target or "`" in target:
        deny(
            f"消す対象を確かめられないので止めました（{target}）。対象をそのまま書いてください。"
        )
    for word in expand_braces(target):
        path = to_native(word)
        if not os.path.isabs(path):
            if cwd is None:
                deny(
                    f"作業ディレクトリが分からないので止めました（{target}）。絶対パスで書いてください。"
                )
            path = os.path.join(cwd, path)
        for match in glob.glob(path) if glob.has_magic(path) else [path]:
            if os.path.islink(match) or not os.path.isdir(match):
                continue
            with os.scandir(match) as entries:
                if next(entries, None) is not None:
                    deny(f"中身のあるディレクトリは消せません（{word}）。{HOW_TO}")


def is_recursive_rm(args: list[str]) -> bool:
    """Tell whether `rm` arguments include a recursive option.

    Parameters
    ----------
    args : list[str]
        Arguments after `rm`.

    Returns
    -------
    bool
        True for `-r`, `-R`, `-rf`, `--recursive` and the like.
    """
    for arg in args:
        if arg == "--":
            break
        if arg == "--recursive" or (
            arg.startswith("-") and not arg.startswith("--") and "r" in arg[1:].lower()
        ):
            return True
    return False


def check_rm(args: list[str], cwd: str | None) -> None:
    """Check every operand of a recursive `rm`.

    Parameters
    ----------
    args : list[str]
        Arguments after `rm`.
    cwd : str or None
        Working directory, or None when it is unknown.
    """
    if not is_recursive_rm(args):
        return
    options_done = False
    for arg in args:
        if not options_done and arg == "--":
            options_done = True
        elif options_done or not arg.startswith("-") or arg == "-":
            check_target(arg, cwd)


def strip_prefix(command: list[str]) -> list[str]:
    """Remove variable assignments and wrappers such as `sudo` and `env`.

    Parameters
    ----------
    command : list[str]
        Simple command.

    Returns
    -------
    list[str]
        The command starting at the program that actually runs.
    """
    while command:
        name = os.path.basename(command[0]).lower()
        if re.match(r"^\w+=", command[0]) or name in PREFIXES:
            command = command[1:]
            while command and command[0].startswith("-"):
                command = command[1:]
        else:
            break
    return command


def check_find(args: list[str]) -> None:
    """Deny `find` that deletes non-empty entries.

    Parameters
    ----------
    args : list[str]
        Arguments after `find`.
    """
    if "-delete" in args and "-empty" not in args:
        deny(f"find -delete は中身ごと消せるので禁止です。{HOW_TO}")
    for i, arg in enumerate(args[:-1]):
        if (
            arg in ("-exec", "-execdir", "-ok", "-okdir")
            and os.path.basename(args[i + 1]) == "rm"
            and is_recursive_rm(args[i + 2 :])
        ):
            deny(f"find -exec rm -r は中身ごと消せるので禁止です。{HOW_TO}")


def check_command(command: list[str], cwd: str | None) -> str | None:
    """Check one simple command.

    Parameters
    ----------
    command : list[str]
        Simple command.
    cwd : str or None
        Working directory before the command, or None when it is unknown.

    Returns
    -------
    str or None
        Working directory after the command (changed by `cd`).
    """
    command = strip_prefix(command)
    if not command:
        return cwd
    name = os.path.basename(command[0]).lower().removesuffix(".exe")
    args = command[1:]

    if name == "cd":
        if not args:
            return os.path.expanduser("~")
        if args[0] == "-" or "$" in args[0] or "`" in args[0]:
            return None
        target = to_native(args[0])
        return os.path.normpath(
            target
            if os.path.isabs(target) or cwd is None
            else os.path.join(cwd, target)
        )

    if name == "rm":
        check_rm(args, cwd)
    elif name == "find":
        check_find(args)
    elif name == "xargs":
        for i, arg in enumerate(args):
            if os.path.basename(arg) == "rm" and is_recursive_rm(args[i + 1 :]):
                deny(f"xargs rm -r は消す対象を確かめられないので禁止です。{HOW_TO}")
    elif (
        name == "git"
        and "clean" in args
        and not any(a == "--dry-run" or re.match(r"^-[a-z]*n", a) for a in args)
    ):
        deny(
            "git clean は追跡していないファイルをまとめて消すので禁止です。消すファイルを指定して rm で消してください。"
        )

    if name in SHELLS:
        for i, arg in enumerate(args[:-1]):
            if arg == "-c":
                check_shell(args[i + 1], cwd)
    if name in INTERPRETERS:
        scan_raw(" ".join(args))
        if name in ("pwsh", "powershell"):
            for arg in args:
                if " " in arg:
                    check_shell(arg, cwd)
    return cwd


def check_shell(text: str, cwd: str | None) -> None:
    """Check a whole shell command line.

    Parameters
    ----------
    text : str
        Command text as given to the Bash tool.
    cwd : str or None
        Working directory, or None when it is unknown.
    """
    stripped, bodies = split_heredocs(text)
    for body in bodies:
        scan_raw(body)
    try:
        tokens = tokenize(stripped)
    except ValueError:
        if re.search(r"\brm\s[^\n;|&]*(-[a-zA-Z]*[rR]|--recursive)", stripped):
            deny(f"コマンドを解析できず、再帰的な rm を含むので止めました。{HOW_TO}")
        scan_raw(stripped)
        return
    for command in split_commands(tokens):
        cwd = check_command(command, cwd)


def main() -> None:
    """Read the hook input from stdin and print a deny decision when needed."""
    data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    command = (data.get("tool_input") or {}).get("command") or ""
    try:
        check_shell(command, data.get("cwd") or os.getcwd())
    except DeniedError as e:
        reason = str(e)
    except Exception as e:  # noqa: BLE001 - fail closed only for commands that look like deletes
        if not re.search(
            r"\b(rm|find|xargs|git|rmtree|remove-item|rd|rimraf)\b",
            command,
            re.IGNORECASE,
        ):
            return
        reason = f"削除コマンドの確認中にフックが失敗したので止めました（{type(e).__name__}: {e}）。{HOW_TO}"
    else:
        return
    decision = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }
    json.dump({"hookSpecificOutput": decision}, sys.stdout, ensure_ascii=True)


if __name__ == "__main__":
    main()
