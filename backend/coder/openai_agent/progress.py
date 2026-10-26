"""Whether a tool call only looked: ``only_reads(tool, arguments)`` is true when the call is known to have changed
nothing (no file written, nothing saved, sent, started or bought), and false whenever that can't be told, so a call
of unknown effect counts as progress. ``guards.TurnGuard`` counts the calls in a row that only read.

``execute_bash`` is judged by its command (``shell_reads``): every command in it a reader (``cat``, ``grep``,
``sed -n``, ``git log``, a ``python3``/``node`` snippet that opens nothing for writing), and no redirect into a file.
Any other tool is judged by the judges a platform registers (``register``): each answers for the tools it knows
(True: only read; False: changed something) and None for the rest."""

from __future__ import annotations

import json
import os
import re
import shlex
from typing import Any, Callable, List, Mapping, Optional

Judge = Callable[[str, Mapping[str, Any]], Optional[bool]]
_JUDGES: List[Judge] = []

SHELL_TOOL = "execute_bash"

# Commands that only print what's there, whatever their arguments (a redirect is judged apart).
_READERS = frozenset({
    "cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "ag", "wc", "ls", "stat", "file", "du",
    "df", "pwd", "echo", "printf", "true", "false", "test", "[", "[[", ":", "which", "whereis", "type", "date",
    "whoami", "id", "uname", "hostname", "tree", "diff", "cmp", "comm", "cut", "tr", "nl", "od", "xxd", "hexdump",
    "strings", "md5sum", "sha1sum", "sha256sum", "shasum", "cksum", "jq", "column", "fold", "fmt", "rev", "tac",
    "paste", "join", "expand", "basename", "dirname", "realpath", "readlink", "seq", "sleep", "cd", "pushd", "popd",
    "export", "unset", "set", "ps", "free", "nproc", "uptime", "printenv", "dig", "nslookup", "host", "locale",
    "getconf", "outline", "break", "continue", "exit", "return", "wait", "done", "fi", "esac", "}",
})
# Words that begin a compound command (``if``, ``do``) or run the command after them (``timeout 5 grep``): skipped,
# with a wrapper's own flags and numbers.
_KEYWORDS = frozenset({"if", "then", "else", "elif", "while", "until", "do", "!", "{", "time"})
_WRAPPERS = frozenset({"sudo", "timeout", "nice", "env", "nohup", "stdbuf", "builtin", "xargs", "command"})
# A loop's or a case's header reads nothing itself.
_HEADERS = frozenset({"for", "select", "case"})
_FIND_WRITES = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf",
                          "-fls"})
_GIT_READS = frozenset({"status", "log", "diff", "show", "rev-parse", "ls-files", "ls-tree", "grep", "blame",
                        "describe", "shortlog", "cat-file", "rev-list", "merge-base", "name-rev", "count-objects"})
# These read with no positional argument (``git branch``, ``git tag -l``) and write with one.
_GIT_LISTS = frozenset({"branch", "tag", "remote", "stash"})
_INTERPRETERS = {"python": "-c", "node": "-e", "nodejs": "-e", "bun": "-e", "perl": "-e", "ruby": "-e"}
_SHELLS = frozenset({"sh", "bash", "zsh", "dash"})
# Code that writes, deletes, runs another program or sends something: any of these and the snippet changed something.
_CODE_WRITES = re.compile(
    r"""\bopen\s*\([^)]*?,\s*(?:mode\s*=\s*)?['"][rbtU]*[wax+]"""  # open(p, 'w'), open(p, mode="a")
    r"|\.write_(?:text|bytes)\s*\("
    r"|\bos\.(?:remove|unlink|rename|renames|replace|makedirs|mkdir|rmdir|removedirs|symlink|link|truncate|chmod"
    r"|chown|utime|system|popen|exec\w*|spawn\w*|kill|open)\s*\("
    r"|\bshutil\.|\bsubprocess\b|\bpty\.|\bchild_process\b"
    r"|\.(?:unlink|rmdir|mkdir|touch|rename|symlink_to|hardlink_to|chmod|extractall|extract|savefig|to_csv"
    r"|to_json|to_excel|to_parquet|save|dump|post|put|patch|delete)\s*\("
    r"""|\bmethod\s*[=:]\s*['"](?:POST|PUT|PATCH|DELETE)"""
    r"|\b(?:writeFile|appendFile|createWriteStream|copyFile|cpSync|rmSync|unlinkSync|renameSync|mkdirSync"
    r"|execSync|spawnSync|execFile)|\bfs\.(?:rm|unlink|rename|mkdir|write|cp)"
    r"|(?<![.\w])(?:exec|spawn|eval|system)\s*\("
    r"|\bFile\.(?:write|open|delete|rename)|\bIO\.write"
    r"|\b(?:insert\s+into|update\s+\w+\s+set|delete\s+from|create\s+table|drop\s+table|alter\s+table)\b",
    re.IGNORECASE)
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_OPERATOR_CHARS = set(";&|<>()\n")
_INPUT = frozenset({"<", "<<", "<<-", "<<<"})


def register(judge: Judge) -> None:
    """A platform's judge of its own tools (True: the call only read; False: it changed something; None: not one
    of its tools)."""
    if judge not in _JUDGES:
        _JUDGES.append(judge)


def only_reads(tool: str, arguments: Any) -> bool:
    """Whether the call is known to have changed nothing."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except ValueError:
            return False
    if not isinstance(arguments, Mapping):
        return False
    if tool == SHELL_TOOL:
        command = arguments.get("command")
        return isinstance(command, str) and shell_reads(command)
    for judge in _JUDGES:
        verdict = judge(tool, arguments)
        if verdict is not None:
            return bool(verdict)
    return False


def code_reads(code: str) -> bool:
    """Whether a snippet of Python, JavaScript, Perl or Ruby opens nothing for writing and runs, sends or deletes
    nothing."""
    return not _CODE_WRITES.search(code)


def shell_reads(command: str) -> bool:
    """Whether every command in a shell command only reads: no redirect into a file (``/dev/null`` and the like are
    fine), every command a reader, a heredoc fed to an interpreter a snippet that only reads. Anything it can't
    parse changed something."""
    if "`" in command:
        return False
    shell, bodies = _split_heredocs(command)
    try:
        lexer = shlex.shlex(shell, posix=True, punctuation_chars=";&|<>()\n")
        lexer.whitespace, lexer.whitespace_split = " \t\r", True
        tokens = list(lexer)
    except ValueError:
        return False
    words: List[str] = []
    heredoc = None
    skip = False
    for i, token in enumerate(tokens):
        if skip:
            skip = False
            continue
        if not _is_operator(token):
            words.append(token)
            continue
        if ">" in token:
            target = tokens[i + 1] if i + 1 < len(tokens) else ""
            if not (target.startswith("/dev/") or (token.endswith("&") and (target.isdigit() or target == "-"))):
                return False
            skip = True
        elif token in _INPUT:
            if token in ("<<", "<<-"):
                heredoc = bodies.pop(0) if bodies else ""
            skip = True
        else:  # a separator: one command ends
            if words and not _reads(words, heredoc):
                return False
            words, heredoc = [], None
    return not words or _reads(words, heredoc)


def _split_heredocs(command: str):
    """The command with each heredoc's body taken out, and the bodies in order."""
    lines, kept, bodies = command.split("\n"), [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        for match in _HEREDOC.finditer(line):
            body = []
            while i < len(lines) and lines[i].strip() != match.group(2):
                body.append(lines[i])
                i += 1
            i += 1
            bodies.append("\n".join(body))
    return "\n".join(kept), bodies


def _is_operator(token: str) -> bool:
    return bool(token) and set(token) <= _OPERATOR_CHARS


def _reads(words: List[str], heredoc: Optional[str]) -> bool:
    """Whether one simple command only reads (``heredoc``: the body it takes on stdin)."""
    words = _unwrapped(words)
    if not words:
        return True
    name, args = os.path.basename(words[0]), words[1:]
    if name in _READERS or name in _HEADERS:
        return True
    if name == "sed":
        return not any(a == "--in-place" or (a.startswith("-") and not a.startswith("--") and "i" in a)
                       for a in args)
    if name in ("awk", "gawk", "mawk"):
        return not any("system(" in a or re.search(r"""[>|]\s*["$]""", a) or a == "inplace" for a in args)
    if name == "find":
        return not any(a in _FIND_WRITES for a in args)
    if name in ("sort", "uniq"):
        positional = [a for a in args if not a.startswith("-")]
        return not any(a in ("-o", "--output") or a.startswith("--output=") for a in args) and (
            name == "sort" or len(positional) <= 1)
    if name == "tee":
        return all(a.startswith("-") or a.startswith("/dev/") for a in args)
    if name == "git":
        return _git_reads(args)
    if name == "curl":
        return _curl_reads(args)
    if name == "html-script":
        return args[:1] == ["list"]
    if name == "ctags":
        return "-x" in args or "-f-" in args or ("-f" in args and args[args.index("-f") + 1:][:1] == ["-"])
    if name in _SHELLS:
        if "-n" in args:
            return True
        if "-c" in args:
            code = args[args.index("-c") + 1:][:1]
            return bool(code) and shell_reads(code[0])
        return not args and heredoc is not None and shell_reads(heredoc)
    flag = _INTERPRETERS.get(re.sub(r"[\d.]+$", "", name))
    if flag is not None:
        return _snippet_reads(name, args, flag, heredoc)
    return False


def _unwrapped(words: List[str]) -> List[str]:
    """The command a line runs, past ``A=1`` assignments, keywords (``if``, ``do``) and wrappers like
    ``timeout 5``."""
    i = 0
    while i < len(words):
        word = words[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", word) or word in _KEYWORDS:
            i += 1
        elif os.path.basename(word) in _WRAPPERS:
            if word == "command" and words[i + 1:i + 2] in (["-v"], ["-V"]):
                return []
            i += 1
            while i < len(words) and (words[i].startswith("-") or re.match(r"^[\d.]+[smhd]?$", words[i])):
                i += 1
        else:
            break
    return words[i:]


def _git_reads(args: List[str]) -> bool:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in ("-C", "-c") else 1
    if i >= len(args):
        return True
    sub, rest = args[i], args[i + 1:]
    if sub in _GIT_READS:
        return not any(a in ("-o", "--output") or a.startswith("--output") for a in rest)
    if sub in _GIT_LISTS:
        positional = [a for a in rest if not a.startswith("-")]
        return not positional or (sub in ("remote", "stash") and positional[0] in ("get-url", "show", "list"))
    if sub == "config":
        return any(a in ("--get", "--get-all", "--list", "-l") for a in rest)
    return False


def _curl_reads(args: List[str]) -> bool:
    for i, arg in enumerate(args):
        if arg.startswith("--"):
            name = arg.split("=", 1)[0]
            if name in ("--output", "--remote-name", "--remote-name-all", "--upload-file", "--form", "--json") or \
                    name.startswith("--data"):
                return False
            if name == "--request":
                method = arg.split("=", 1)[1] if "=" in arg else (args[i + 1] if i + 1 < len(args) else "")
                if method.upper() not in ("GET", "HEAD"):
                    return False
        elif arg.startswith("-") and len(arg) > 1:
            if set(arg[1:]) & set("oOTdF"):
                return False
            if "X" in arg[1:]:
                method = arg[arg.index("X") + 1:] or (args[i + 1] if i + 1 < len(args) else "")
                if method.upper() not in ("GET", "HEAD"):
                    return False
    return True


def _snippet_reads(name: str, args: List[str], flag: str, heredoc: Optional[str]) -> bool:
    """An interpreter given code (``-c``/``-e``, or a heredoc on stdin) reads when its code does; a script file or a
    module may do anything, except the few that only check or print."""
    if name in ("perl", "ruby") and any(a.startswith("-") and not a.startswith("--") and "i" in a for a in args):
        return False  # perl -pi -e edits in place
    if name in ("node", "nodejs") and any(a in ("--check", "-c") for a in args):
        return True
    if flag in args:
        code = args[args.index(flag) + 1:][:1]
        return bool(code) and code_reads(code[0])
    if name.startswith("python") and "-m" in args:
        return args[args.index("-m") + 1:][:1] in (["json.tool"], ["py_compile"], ["tokenize"], ["pydoc"])
    positional = [a for a in args if not a.startswith("-") or a == "-"]
    if heredoc is not None and (not positional or positional == ["-"]):
        return code_reads(heredoc)
    return bool(args) and all(a in ("--version", "-V") for a in args)
