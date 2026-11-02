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
from typing import NamedTuple, NoReturn

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
CHDIR_OPTIONS = {"env": {"-C", "--chdir"}, "sudo": {"-D", "--chdir"}}
BLOCK_OPENERS = {"if", "while", "until", "for", "case", "select"}
BLOCK_CLOSERS = {"fi", "done", "esac"}
SUBST_MARKER = r"\$__HOOK_SUBST_(\d+)__"
# Prefix of a word that only carries substitutions from a redirection target.
REDIRECT = "\0redirect:"
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


class Found(NamedTuple):
    """Command substitutions and heredocs taken out of a command line."""

    substitutions: list[str]
    heredocs: list[tuple[str, str, bool]]


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
    """Move heredoc bodies out of the command text, leaving a marker word.

    The marker ``$__HOOK_HEREDOC_<n>__`` is placed right after the heredoc
    operator, so the body is checked with the command that reads it.

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
        i += 1
        words = {
            os.path.basename(w).lower().removesuffix(".exe")
            for w in re.findall(r"[\w./\\-]+", line)
        }
        receiver = (
            "shell" if words & SHELLS else "interpreter" if words & INTERPRETERS else ""
        )
        marked, end = [], 0
        for match in re.finditer(r"<<-?\s*(['\"]?)(\w+)\1", line):
            body = []
            while i < len(lines) and lines[i].strip() != match.group(2):
                body.append(lines[i])
                i += 1
            i += 1
            marked.append(line[end : match.end()])
            marked.append(f" $__HOOK_HEREDOC_{len(heredocs)}__")
            end = match.end()
            heredocs.append((receiver, "\n".join(body), not match.group(1)))
        kept.append("".join(marked) + line[end:])
    return "\n".join(kept), heredocs


def mark_substitutions(text: str, quotes: bool = True) -> tuple[str, list[str]]:
    """Replace each command substitution the shell runs with a marker word.

    ``$(...)`` and backquotes run unless they are inside single quotes or a
    comment. Each one becomes ``$__HOOK_SUBST_<n>__``, a variable that is never
    set, so a path built from it stays unknown.

    Parameters
    ----------
    text : str
        Shell command text.
    quotes : bool
        False for a heredoc body, where quotes are literal characters.

    Returns
    -------
    tuple[str, list[str]]
        The text with markers, and the commands inside each substitution.
    """
    out, found = [], []
    single = double = False
    i = 0
    while i < len(text):
        c = text[i]
        if single:
            single = c != "'"
            out.append(c)
            i += 1
        elif c == "\\":
            out.append(text[i : i + 2])
            i += 2
        elif quotes and c == "'" and not double:
            single = True
            out.append(c)
            i += 1
        elif quotes and c == '"':
            double = not double
            out.append(c)
            i += 1
        elif (
            quotes
            and c == "#"
            and not double
            and (i == 0 or text[i - 1] in " \t\n;&|()")
        ):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        elif text.startswith("$(", i) or c == "`":
            if c == "`":
                end = text.find("`", i + 1)
                end = len(text) if end < 0 else end
                found.append(text[i + 1 : end])
                i = end + 1
            else:
                depth, j = 1, i + 2
                while j < len(text) and depth:
                    depth += {"(": 1, ")": -1}.get(text[j], 0)
                    j += 1
                found.append(text[i + 2 : j - 1 if depth == 0 else j])
                i = j
            out.append(f"$__HOOK_SUBST_{len(found) - 1}__")
        else:
            out.append(c)
            i += 1
    return "".join(out), found


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
            # A redirection target is not an argument, but its substitutions still run.
            current.extend(REDIRECT + m[0] for m in re.finditer(SUBST_MARKER, token))
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


def resolve_dir(path: str, cwd: str | None) -> str | None:
    """Resolve the directory a `cd`-like change moves to.

    Parameters
    ----------
    path : str
        Directory as written in the command.
    cwd : str or None
        Working directory before the change, or None when it is unknown.

    Returns
    -------
    str or None
        The new working directory, or None when it is unknown or does not exist
        (a failed change leaves the directory as it was).
    """
    if path == "-" or "$" in path or "`" in path:
        return None
    target = to_native(path)
    if not os.path.isabs(target):
        if cwd is None:
            return None
        target = os.path.join(cwd, target)
    return os.path.normpath(target) if os.path.isdir(target) else None


def strip_prefix(command: list[str]) -> tuple[list[str], bool, str | None]:
    """Remove keywords, variable assignments and wrappers such as `sudo` and `timeout`.

    Parameters
    ----------
    command : list[str]
        Simple command.

    Returns
    -------
    tuple[list[str], bool, str or None]
        The command starting at the program that actually runs, whether a
        wrapper was removed, and the directory a wrapper runs it in
        (`env -C`, `sudo -D`), if any.
    """
    wrapped, chdir = False, None
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
            value = None
            if option in takes_value:
                value, command = (command[0] if command else ""), command[1:]
            elif "=" in option:
                option, value = option.split("=", 1)
            if option in CHDIR_OPTIONS.get(name, set()):
                chdir = value or ""
        command = command[PREFIX_POSITIONALS.get(name, 0) :]
    return command, wrapped, chdir


def check_find(args: list[str]) -> None:
    """Deny `find` that deletes non-empty entries.

    Parameters
    ----------
    args : list[str]
        Arguments after `find`.
    """
    # find evaluates left to right, so -delete is safe only after -empty has
    # matched, with no negation or alternative that could skip -empty.
    if "-delete" in args and (
        "-empty" not in args
        or args.index("-empty") > args.index("-delete")
        or any(a in ("!", "-not", "-o", "-or", ",") for a in args)
    ):
        deny(f"find -delete は中身ごと消せるので禁止です。{HOW_TO}")
    for i, arg in enumerate(args[:-1]):
        if (
            arg in ("-exec", "-execdir", "-ok", "-okdir")
            and os.path.basename(args[i + 1]) == "rm"
            and is_recursive_rm(args[i + 2 :])
        ):
            deny(f"find -exec rm -r は中身ごと消せるので禁止です。{HOW_TO}")


def check_command(command: list[str], cwd: str | None, found: Found) -> str | None:
    """Check one simple command.

    Parameters
    ----------
    command : list[str]
        Simple command.
    cwd : str or None
        Working directory before the command, or None when it is unknown.
    found : Found
        Command substitutions and heredocs replaced by markers in the text.

    Returns
    -------
    str or None
        Working directory after the command (changed by `cd`).
    """
    # The calling shell expands substitutions in this command's working directory.
    words, heredocs = [], []
    for word in command:
        heredoc = re.fullmatch(r"\$__HOOK_HEREDOC_(\d+)__", word)
        if heredoc:
            receiver, body, expands = found.heredocs[int(heredoc.group(1))]
            heredocs.append((receiver, body))
            if expands:
                for inner in mark_substitutions(body, quotes=False)[1]:
                    check_shell(inner, cwd)
            continue
        for index in re.findall(SUBST_MARKER, word):
            check_shell(found.substitutions[int(index)], cwd)
        if not word.startswith(REDIRECT):
            words.append(word)

    command, wrapped, chdir = strip_prefix(words)
    after = cwd
    if chdir is not None:
        cwd = resolve_dir(chdir, cwd)
    # The program reading a heredoc runs where a wrapper (`env -C`) moved it.
    for receiver, body in heredocs:
        if receiver == "shell":
            check_shell(body, cwd)
        elif receiver == "interpreter":
            scan_raw(body)
    if not command:
        return after
    name = os.path.basename(command[0]).lower().removesuffix(".exe")
    args = command[1:]

    if name == "cd":
        return os.path.expanduser("~") if not args else resolve_dir(args[0], after)

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
    return after


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
    marked, substitutions = mark_substitutions(stripped)
    found = Found(substitutions, heredocs)
    try:
        tokens = tokenize(marked)
    except ValueError:
        if re.search(r"\brm\s[^\n;|&]*(-[a-zA-Z]*[rR]|--recursive)", stripped):
            deny(f"コマンドを解析できず、再帰的な rm を含むので止めました。{HOW_TO}")
        scan_raw(stripped)
        check_command(re.findall(r"\$__HOOK_\w+", marked), cwd, found)
        return
    items = split_commands(tokens)
    # Every directory the shell may be in; a cd that may not run keeps the old ones.
    cwds: list[str | None] = [cwd]
    saved: list[list[str | None]] = []
    depth = 0
    for i, item in enumerate(items):
        if item == "(":
            saved.append(cwds)
        elif item == ")":
            if saved:
                cwds = saved.pop()
        elif isinstance(item, list):
            if item[0] in BLOCK_OPENERS:
                depth += 1
            elif item[0] in BLOCK_CLOSERS:
                depth = max(depth - 1, 0)
            after_cd = [check_command(item, c, found) for c in cwds]
            before = items[i - 1] if i else ""
            after = items[i + 1] if i + 1 < len(items) else ""
            if before in SUBSHELL_OPERATORS or after in SUBSHELL_OPERATORS:
                continue  # Pipelines and background jobs run in a subshell.
            if depth or before in ("&&", "||") or after == "||":
                after_cd = cwds + after_cd
            cwds = list(dict.fromkeys(after_cd))


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
