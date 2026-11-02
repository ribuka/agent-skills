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
# Options of a prefix that take a separate value, and positional arguments before the program.
PREFIX_OPTIONS = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-T", "-U"},
    "env": {"-u", "-C", "-S", "--unset", "--chdir", "--split-string"},
    "nice": {"-n", "--adjustment"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "exec": {"-a"},
    "time": {"-f", "-o", "--format", "--output"},
}
PREFIX_POSITIONALS = {"timeout": 1}
KEYWORDS = {
    "if",
    "then",
    "else",
    "elif",
    "fi",
    "do",
    "done",
    "while",
    "until",
    "!",
    "{",
    "}",
}
OPERATORS = [
    "&&",
    "||",
    ";;",
    "|&",
    "<<",
    ">>",
    "<&",
    ">&",
    "&>",
    "<>",
    ";",
    "&",
    "|",
    "(",
    ")",
    "<",
    ">",
    "\n",
]
SUBSHELL_OPERATORS = {"|", "|&", "&"}
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


def split_heredocs(text: str) -> tuple[str, list[tuple[str, str, bool]]]:
    """Separate heredoc bodies from the command text.

    Parameters
    ----------
    text : str
        Shell command text.

    Returns
    -------
    tuple[str, list[tuple[str, str, bool]]]
        The text without heredoc bodies, and for each heredoc its receiver
        (``"shell"``, ``"interpreter"`` or ``""``), its body, and whether the shell
        expands ``$(...)`` in it (the delimiter is not quoted).
    """
    lines = text.split("\n")
    kept, heredocs = [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        for quote, word in re.findall(r"<<-?\s*(['\"]?)(\w+)\1", line):
            body = []
            while i < len(lines) and lines[i].strip() != word:
                body.append(lines[i])
                i += 1
            i += 1
            words = {
                os.path.basename(w).lower().removesuffix(".exe")
                for w in re.findall(r"[\w./\-]+", line)
            }
            receiver = (
                "shell"
                if words & SHELLS
                else "interpreter"
                if words & INTERPRETERS
                else ""
            )
            heredocs.append((receiver, "\n".join(body), not quote))
    return "\n".join(kept), heredocs


def find_substitutions(text: str) -> list[str]:
    """Find the commands inside ``$(...)`` and backquotes, quoted or not.

    Parameters
    ----------
    text : str
        Shell command text.

    Returns
    -------
    list[str]
        Text of each outermost command substitution.
    """
    found = []
    i = 0
    while i < len(text):
        if text.startswith("$(", i):
            depth, j = 1, i + 2
            while j < len(text) and depth:
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
            found.append(text[i + 2 : j - 1])
            i = j
        elif text[i] == "`":
            j = text.find("`", i + 1)
            if j < 0:
                found.append(text[i + 1 :])
                break
            found.append(text[i + 1 : j])
            i = j + 1
        else:
            i += 1
    return found


def split_operators(token: str) -> list[str]:
    """Split a run of punctuation characters into shell operators.

    Parameters
    ----------
    token : str
        Token made only of `PUNCTUATION` characters, such as ``");"``.

    Returns
    -------
    list[str]
        Operators such as ``")"`` and ``";"``.
    """
    operators = []
    while token:
        operator = next(o for o in OPERATORS if token.startswith(o))
        operators.append(operator)
        token = token[len(operator) :]
    return operators


def tokenize(text: str) -> list[str]:
    """Split shell text into words and operators (newline is an operator).

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
    tokens = []
    for token in lexer:
        if token and all(c in PUNCTUATION for c in token):
            tokens.extend(split_operators(token))
        else:
            tokens.append(token)
    return tokens


def split_commands(tokens: list[str]) -> list[list[str] | str]:
    """Group tokens into simple commands and control operators, dropping redirections.

    Parameters
    ----------
    tokens : list[str]
        Tokens from `tokenize`.

    Returns
    -------
    list[list[str] | str]
        Simple commands (lists) and the operators between them (strings), in order.
    """
    items, current, skip = [], [], False
    for token in tokens:
        if skip:
            skip = False
            continue
        if token in OPERATORS:
            if "<" in token or ">" in token:
                if current and current[-1].isdigit():
                    current.pop()
                skip = True
                continue
            if current:
                items.append(current)
                current = []
            items.append(token)
            continue
        current.append(token)
    if current:
        items.append(current)
    return items


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
        # Quotes are already removed, so also check the literal path (`rm -rf 'a[1]'`).
        for match in [path, *(glob.glob(path) if glob.has_magic(path) else [])]:
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


def strip_prefix(command: list[str]) -> tuple[list[str], bool]:
    """Remove keywords, variable assignments and wrappers such as `sudo` and `timeout`.

    Parameters
    ----------
    command : list[str]
        Simple command.

    Returns
    -------
    tuple[list[str], bool]
        The command starting at the program that actually runs, and whether a
        wrapper was removed.
    """
    wrapped = False
    while command:
        name = os.path.basename(command[0]).lower()
        if command[0] in KEYWORDS or re.match(r"^\w+=", command[0]):
            command = command[1:]
            continue
        if name not in PREFIXES:
            break
        wrapped = True
        command = command[1:]
        takes_value = PREFIX_OPTIONS.get(name, set())
        while command and command[0].startswith("-") and command[0] != "-":
            option = command[0]
            command = command[1:]
            if option == "--":
                break
            if option in takes_value:
                command = command[1:]
        command = command[PREFIX_POSITIONALS.get(name, 0) :]
    return command, wrapped


def check_find(args: list[str]) -> None:
    """Deny `find` that deletes non-empty entries.

    Parameters
    ----------
    args : list[str]
        Arguments after `find`.
    """
    # Allow -delete only when every match must be empty: no negation or alternative.
    if "-delete" in args and (
        "-empty" not in args or any(a in ("!", "-not", "-o", "-or", ",") for a in args)
    ):
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
    command, wrapped = strip_prefix(command)
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
        if not os.path.isabs(target):
            if cwd is None:
                return None
            target = os.path.join(cwd, target)
        # A failed cd leaves the directory unchanged, so the cwd is unknown.
        return os.path.normpath(target) if os.path.isdir(target) else None

    if wrapped and name != "rm":
        # The wrapper's arguments were not understood; check any rm it may run.
        for i, arg in enumerate(args):
            if os.path.basename(arg) == "rm":
                check_rm(args[i + 1 :], cwd)
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
    stripped, heredocs = split_heredocs(text)
    for receiver, body, expands in heredocs:
        if receiver == "shell":
            check_shell(body, cwd)
        elif receiver == "interpreter":
            scan_raw(body)
        if expands:
            for inner in find_substitutions(body):
                check_shell(inner, cwd)
    # Command substitutions run even inside double quotes (`echo "$(rm -rf x)"`).
    for inner in find_substitutions(stripped):
        check_shell(inner, cwd)
    try:
        tokens = tokenize(stripped)
    except ValueError:
        if re.search(r"\brm\s[^\n;|&]*(-[a-zA-Z]*[rR]|--recursive)", stripped):
            deny(f"コマンドを解析できず、再帰的な rm を含むので止めました。{HOW_TO}")
        scan_raw(stripped)
        return
    items = split_commands(tokens)
    saved = []
    for i, item in enumerate(items):
        if item == "(":
            saved.append(cwd)
        elif item == ")":
            if saved:
                cwd = saved.pop()
        elif isinstance(item, list):
            after_cd = check_command(item, cwd)
            before = items[i - 1] if i else ""
            after = items[i + 1] if i + 1 < len(items) else ""
            if before in SUBSHELL_OPERATORS or after in SUBSHELL_OPERATORS:
                continue  # Pipelines and background jobs run in a subshell.
            # After `cd x || cmd`, cmd runs only when cd failed.
            cwd = None if after == "||" and after_cd != cwd else after_cd


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
