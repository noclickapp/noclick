"""Shell completion, read from the spec as it is when Tab is pressed, so it follows every command the CLI has.

``noclick completion <shell>`` prints a short script that asks ``noclick __complete -- <words>`` what the word under
the cursor completes to: the commands at that point (curated ones and every API operation), a command's flags, a
flag's choices, a profile's name, and an app's name from a short-lived cache in the config directory (a stale one is
read again by a process of its own, never on the Tab that found it stale). Each answer is a line, ``value<TAB>what it
is``. The npm CLI answers the same way (``src/cli/completion.ts``), so one installed script works with either.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .spec import Spec, load

COMMAND = "__complete"
SHELLS = ("bash", "zsh", "fish", "powershell")
# What a line naming it in a shell's startup file ends with, so --install adds it once.
MARK = "# noclick completion"
APPS_FILE = "apps.json"
APPS_FRESH_S = 300
# The arguments and flags that name an app.
APP_NAMES = ("app", "project")
# The commands whose argument names a profile.
PROFILE_ARGS = (["profile", "use"], ["profile", "show"])
OP_FLAGS: Tuple[Dict[str, Any], ...] = (
    {"flag": "--json", "type": "bool", "help": "Print the whole answer as JSON."},
    {"flag": "--user", "type": "string", "help": "Act for this user: your id for them."},
    {"flag": "--data", "type": "string", "help": "The whole request body: JSON, @file or - for stdin."},
    {"flag": "--no-wait", "type": "bool", "help": "When it starts an operation, print its id instead of waiting."},
    {"flag": "--timeout", "type": "number", "help": "Stop waiting after this many seconds."},
)
HELP_FLAG = {"flag": "--help", "type": "bool", "help": "Show this help."}

Candidate = Tuple[str, str]


def short(text: Optional[str]) -> str:
    """A summary's first sentence, at most 70 characters."""
    first = (text or "").split("\n")[0].split(". ")[0].rstrip(".")
    return first if len(first) <= 70 else first[:69] + "…"


# --- what a command line names ------------------------------------------------------------------------------------


def _flag_of(name: str) -> str:
    from .commands import flag_of

    return flag_of(name)


def _op_flags(op: Dict[str, Any]) -> List[Dict[str, Any]]:
    kinds = {"boolean": "bool", "list": "list", "integer": "integer", "number": "number"}
    own = [{"flag": _flag_of(p["name"]), "type": kinds.get(p["type"], "string"), "help": p.get("description") or "",
            **({"choices": p["choices"]} if p.get("choices") and p["type"] not in ("boolean", "list", "json") else {})}
           for p in op["params"] if p["in"] != "path"]
    return [*own, *OP_FLAGS]


class _Line:
    """A command line read up to the word under the cursor: the command it names, how many positional words it has,
    and the flag waiting for a value."""

    def __init__(self, spec: Spec, before: Sequence[str]):
        self.spec = spec
        self.areas = spec.areas()
        self.path: List[str] = []
        self.command: Optional[Dict[str, Any]] = None
        self.op: Optional[Dict[str, Any]] = None
        self.positional = 0
        self.expecting: Optional[Dict[str, Any]] = None
        for word in before:
            if self.expecting is not None:
                self.expecting = None
            elif word.startswith("-"):
                flag = None if "=" in word else self.flag(word)
                self.expecting = flag if flag and flag["type"] != "bool" else None
            elif self.command is None and self.op is None and self._is_node([*self.path, word]):
                self.path.append(word)
                self.command = next((c for c in spec.commands if c["path"] == self.path), None)
                if self.command is None and len(self.path) == 2:
                    self.op = spec.find(self.path[0], self.path[1])
            else:
                self.positional += 1

    def _is_node(self, path: List[str]) -> bool:
        if any(c["path"][:len(path)] == path for c in self.spec.commands):
            return True
        return (len(path) == 1 and path[0] in self.areas) or (len(path) == 2 and self.spec.find(*path) is not None)

    def flags(self) -> List[Dict[str, Any]]:
        own = (self.command or {}).get("flags") or (_op_flags(self.op) if self.op else [])
        return [*own, *self.spec.manifest["globals"], HELP_FLAG]

    def flag(self, word: str) -> Optional[Dict[str, Any]]:
        return next((f for f in self.flags() if word in (f["flag"], f.get("short"))), None)

    def children(self) -> List[Candidate]:
        depth = len(self.path)
        found: Dict[str, str] = {}
        summaries = {name: summary for section in self.spec.manifest["screens"]["sections"]
                     for name, summary in section["commands"]}
        for c in self.spec.commands:
            if c["path"][:depth] == self.path and len(c["path"]) > depth:
                name = c["path"][depth]
                found.setdefault(name, c["summary"] if len(c["path"]) == depth + 1 else summaries.get(name, ""))
        if depth == 0:
            for name, summary in summaries.items():
                found[name] = summary
            for area, ops in self.areas.items():
                found.setdefault(area, f"{len(ops)} API operations")
        elif depth == 1 and self.path[0] in self.areas:
            for op in self.areas[self.path[0]]:
                found.setdefault(op["command"], short(op["summary"]))
        return [(name, short(summary)) for name, summary in found.items()]

    def argument(self) -> Optional[Dict[str, Any]]:
        args = (self.command or {}).get("args") or []
        if self.positional < len(args):
            return args[self.positional]
        return args[-1] if args and args[-1].get("many") else None


def candidates(words: Sequence[str], *, profiles: Callable[[], List[str]],
               apps: Callable[[], List[str]]) -> List[Candidate]:
    """What the last of ``words`` (the one under the cursor, perhaps empty) completes to."""
    words = list(words) or [""]
    current, line = words[-1], _Line(load(), words[:-1])
    found: List[Candidate]
    if line.expecting is not None:
        flag = line.expecting
        if flag["flag"] == "--profile":
            found = [(name, "profile") for name in profiles()]
        elif flag.get("dest") in APP_NAMES or flag["flag"] == "--app":
            found = [(name, "app") for name in apps()]
        else:
            found = [(str(choice), "") for choice in flag.get("choices") or []]
    elif current.startswith("-"):
        found = [(f["flag"], short(f.get("help"))) for f in line.flags()]
    elif line.command is None and line.op is None:
        found = [] if line.positional else line.children()  # a word that names nothing: nothing follows it
    else:
        arg = line.argument()
        if arg is None:
            found = []
        elif line.path in PROFILE_ARGS:
            found = [(name, "profile") for name in profiles()]
        elif arg["name"] in APP_NAMES:
            found = [(name, "app") for name in apps()]
        else:
            found = [(str(choice), "") for choice in arg.get("choices") or []]
    seen = set()
    return [(value, what) for value, what in found
            if value.startswith(current) and not (value in seen or seen.add(value))]


# --- app names, kept a few minutes -------------------------------------------------------------------------------


def _apps_path() -> Path:
    from ..cli import config_dir

    return config_dir() / "cache" / APPS_FILE


def _read_apps() -> Dict[str, Any]:
    try:
        return json.loads(_apps_path().read_text())
    except (OSError, ValueError):
        return {}


def _write_apps(profile: str, entry: Dict[str, Any]) -> None:
    path = _apps_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**_read_apps(), profile: entry}) + "\n")


def _refresh_in_background(profile: str) -> None:
    detached: Dict[str, Any] = ({"creationflags": 0x00000008} if os.name == "nt" else {"start_new_session": True})
    try:
        subprocess.Popen([sys.executable, "-m", "noclick", COMMAND, "--refresh-apps", profile],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True, **detached)
    except OSError:
        pass


def app_names(profile: str, *, now: Optional[float] = None,
              refresh: Callable[[str], None] = _refresh_in_background) -> List[str]:
    """The profile's apps as last read; when that's older than a few minutes, a read is started for the next Tab."""
    now = time.time() if now is None else now
    kept = _read_apps().get(profile) or {}
    if now - float(kept.get("at") or 0) >= APPS_FRESH_S:
        try:
            _write_apps(profile, {**kept, "at": now})  # one read started per few minutes, whether or not it answers
        except OSError:
            return list(kept.get("names") or [])
        refresh(profile)
    return list(kept.get("names") or [])


def refresh_apps(profile: str) -> int:
    from .. import cli
    from ..project import Project

    creds = cli.resolve_credentials(profile)
    names: List[str] = []
    if creds.key:
        cli.configure(api_key=creds.key, base_url=creds.api_url)
        try:
            names = sorted(p.name for p in Project.list(limit=200) if p.name)
        except Exception:  # noqa: BLE001 - what can't be read now is read again later
            return 0
    _write_apps(profile, {"at": time.time(), "names": names})
    return 0


# --- the scripts --------------------------------------------------------------------------------------------------

SCRIPTS = {
    "bash": """# noclick completion for bash: each Tab asks noclick what the word completes to.
_noclick_complete() {
  local IFS=$'\\n' line out
  out=$(noclick __complete -- "${COMP_WORDS[@]:1:COMP_CWORD}" 2>/dev/null) || return 0
  COMPREPLY=()
  for line in $out; do COMPREPLY+=("${line%%$'\\t'*}"); done
}
complete -o default -F _noclick_complete noclick
""",
    "zsh": """#compdef noclick
# noclick completion for zsh: each Tab asks noclick what the word completes to.
_noclick() {
  local -a lines described
  local line
  lines=("${(@f)$(noclick __complete -- "${(@)words[2,CURRENT]}" 2>/dev/null)}")
  if [[ -z "${lines[1]}" ]]; then _files; return; fi
  for line in "${lines[@]}"; do described+=("${${line%%$'\\t'*}//:/\\\\:}:${line#*$'\\t'}"); done
  _describe 'noclick' described
}
if [[ "${funcstack[1]}" == "_noclick" ]]; then
  _noclick "$@"
else
  (( $+functions[compdef] )) || { autoload -Uz compinit && compinit; }
  compdef _noclick noclick
fi
""",
    "fish": """# noclick completion for fish: each Tab asks noclick what the word completes to.
function __noclick_complete
    set -l words (commandline -opc)
    set -e words[1]
    set -l current (commandline -ct)
    noclick __complete -- $words "$current" 2>/dev/null
end
complete -c noclick -f -a '(__noclick_complete)'
""",
    "powershell": """# noclick completion for PowerShell: each Tab asks noclick what the word completes to.
Register-ArgumentCompleter -Native -CommandName noclick -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    $words = @($commandAst.CommandElements | Select-Object -Skip 1 | ForEach-Object { $_.ToString() })
    $space = @()
    if ($wordToComplete -eq '') { $space = @('--space') }
    noclick __complete @space -- @words 2>$null | ForEach-Object {
        $value, $what = $_ -split "`t", 2
        if (-not $what) { $what = $value }
        [System.Management.Automation.CompletionResult]::new($value, $value, 'ParameterValue', $what)
    }
}
""",
}


def _home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def _data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or _home() / ".local" / "share") / "noclick"


def places(shell: str) -> Tuple[Path, Optional[Path], Optional[str]]:
    """Where --install writes the script, the startup file that loads it (None where the shell loads it by itself)
    and the line it adds there."""
    config = Path(os.environ.get("XDG_CONFIG_HOME") or _home() / ".config")
    if shell == "fish":
        return config / "fish" / "completions" / "noclick.fish", None, None
    script = _data_dir() / f"completion.{ {'bash': 'bash', 'zsh': 'zsh', 'powershell': 'ps1'}[shell] }"
    if shell == "powershell":
        rc = (_home() / "Documents" / "PowerShell" if os.name == "nt" else config / "powershell") \
            / "Microsoft.PowerShell_profile.ps1"
        return script, rc, f'if (Test-Path "{script}") {{ . "{script}" }}  {MARK}'
    rc = (Path(os.environ.get("ZDOTDIR") or _home()) / ".zshrc") if shell == "zsh" else _home() / ".bashrc"
    return script, rc, f'[ -f "{script}" ] && . "{script}"  {MARK}'


def install(shell: str) -> List[str]:
    """Put the script in place and have the shell load it; what it says, each line. Run again, it changes nothing
    but the script, which it writes as this version has it."""
    script, rc, load_line = places(shell)
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(SCRIPTS[shell])
    said = [f"Installed noclick completion for {shell}: {script}"]
    if rc is None:
        said.append("fish loads it by itself.")
        return said
    held = rc.read_text() if rc.exists() else ""
    if MARK in held:
        said.append(f"{rc} already loads it.")
    else:
        rc.parent.mkdir(parents=True, exist_ok=True)
        with rc.open("a") as out:
            out.write(("" if not held or held.endswith("\n") else "\n") + load_line + "\n")
        said.append(f"{rc} loads it (added a line).")
    return said


# --- the hidden command a script calls ----------------------------------------------------------------------------


def answer(argv: Sequence[str]) -> int:
    """``noclick __complete [--space] -- <words>``: one ``value<TAB>what`` line per candidate. ``--space`` says the
    cursor is past the last word (PowerShell can't pass an empty word); ``--refresh-apps <profile>`` reads the
    profile's apps into the cache."""
    argv = list(argv)
    if argv[:1] == ["--refresh-apps"]:
        return refresh_apps(argv[1] if len(argv) > 1 else "default")
    space = "--space" in argv[:argv.index("--")] if "--" in argv else "--space" in argv
    words = argv[argv.index("--") + 1:] if "--" in argv else [w for w in argv if w != "--space"]
    if space:
        words.append("")
    from .. import cli

    given = next((w.split("=", 1)[1] for w in words if w.startswith("--profile=")), None) or next(
        (words[i + 1] for i, w in enumerate(words[:-1]) if w == "--profile"), None)
    profile = cli.active_profile(given)[0]
    try:
        found = candidates(words, profiles=lambda: sorted(cli._read_config().get("profiles", {})),
                           apps=lambda: app_names(profile))
    except Exception:  # noqa: BLE001 - a Tab that can't be answered completes to nothing, never a traceback
        return 0
    try:
        sys.stdout.write("".join(f"{value}\t{what}\n" for value, what in found))
        sys.stdout.flush()
    except BrokenPipeError:
        pass
    return 0
