"""``noclick shell``: a terminal in a sandbox, on a machine or beside an agent's work, or one command run there.

    noclick shell <sandbox>                    # bash in a sandbox, in this terminal (resize, Ctrl-C and Ctrl-D go in)
    noclick shell --machine support-box        # on a machine (what noclick machines ssh opens)
    noclick shell --agent coder                # in an agent's sandbox, beside its work
    noclick shell <sandbox> -- python -V       # one command: its output, then its exit code as this one's
    noclick shell --app shop -- npm test       # an app's live container takes commands, not a terminal

A command needs no terminal, so it works piped. The terminal speaks the API's terminal socket (each target's
``shell()``); a command is the target's ``exec``, whose output comes back once it ends.
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from typing import Any, List, Optional, Sequence

from ... import cli
from .. import output
from ...agent import Agent
from ...machine import Machine
from ...project import Project
from ...sandbox import Sandbox

_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_EXAMPLE = "noclick shell <sandbox> -- ls"


def _named(cls: Any, ref: str) -> Any:
    """A machine, agent or app by its id or its name."""
    return cls.from_id(ref) if _ID.match(ref) else cls.from_name(ref)


def _target(args: argparse.Namespace) -> tuple:
    """(what, where, command): which kind of place, its name as given, and the command after it (empty: a
    terminal)."""
    words: List[str] = list(args.words or [])
    named = [(kind, getattr(args, kind)) for kind in ("machine", "agent", "app") if getattr(args, kind)]
    if len(named) > 1:
        raise cli.CommandError("Name one place: --machine, --agent or --app.", next_step=_EXAMPLE, run=[_EXAMPLE])
    if args.conversation and not args.agent:
        raise cli.CommandError("--conversation is an agent's.", next_step="Name the agent too.",
                               run=["noclick shell --agent <name> --conversation <id>"])
    if named:
        return named[0][0], named[0][1], words
    if not words:
        raise cli.CommandError("Name where to open it: a sandbox's id, or --machine, --agent or --app.",
                               next_step="noclick shell <sandbox>, or noclick shell --machine <name>",
                               run=["noclick shell <sandbox>", "noclick shell --machine <name>"])
    return "sandbox", words[0], words[1:]


def cmd_shell(args: argparse.Namespace) -> int:
    what, where, command = _target(args)
    if command:
        return _run(what, where, command, args)
    if what == "app":
        raise cli.CommandError("An app's live container takes one command at a time, not a terminal.",
                               next_step=f"noclick shell --app {where} -- <command>",
                               run=[f"noclick shell --app {where} -- <command>"])
    if not sys.stdout.isatty():
        raise cli.CommandError("noclick shell needs a terminal to open one; pass a command to run it instead.",
                               next_step=f"noclick shell {_flags(what, where)}-- <command>",
                               run=[f"noclick shell {_flags(what, where)}-- <command>"])
    opener = _opener(what, where, args.conversation)
    opened = opener()
    return cli._attach_shell(opened.url, opened.token, renew=lambda: opener().token, command="noclick shell")


def _flags(what: str, where: str) -> str:
    return f"{where} " if what == "sandbox" else f"--{what} {where} "


def _opener(what: str, where: str, conversation: Optional[str]) -> Any:
    """What opens a shell there again (a renew asks it once more)."""
    if what == "sandbox":
        sandbox = Sandbox.from_id(where)
        return sandbox.shell
    if what == "machine":
        return _named(Machine, where).shell
    sandbox = _named(Agent, where).sandbox(conversation)
    return sandbox.shell


def _run(what: str, where: str, command: Sequence[str], args: argparse.Namespace) -> int:
    line = command[0] if len(command) == 1 else shlex.join(command)
    if what == "sandbox":
        result = Sandbox.from_id(where).exec(line, timeout_s=args.timeout)
    elif what == "machine":
        result = _named(Machine, where).exec(line, timeout_s=args.timeout)
    elif what == "agent":
        result = _named(Agent, where).sandbox(args.conversation).exec(line, timeout_s=args.timeout)
    else:
        result = _named(Project, where).live.exec(line, **({"timeout_s": args.timeout} if args.timeout else {}))
    if args.json:
        output.print_json({"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.exit_code})
    else:
        if result.stdout:
            output.line(result.stdout[:-1] if result.stdout.endswith("\n") else result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr if result.stderr.endswith("\n") else result.stderr + "\n")
            sys.stderr.flush()
    if getattr(result, "timed_out", False) or (getattr(result, "raw", None) or {}).get("timed_out"):
        output.note(f"It was stopped at its time limit ({args.timeout or 'the default'}s); --timeout sets "
                        "another.")
    return result.exit_code if isinstance(result.exit_code, int) else 1


def register(kit: Any) -> None:
    shell = kit.command(kit.commands, "shell", cmd_shell,
                        "A terminal (or one command) in a sandbox, on a machine or in an agent's sandbox.",
                        parents=[kit.as_json])
    shell.epilog = ("A terminal needs one (on Windows, use WSL); a command after -- doesn't, and exits with the "
                    "command's own exit code.")
    shell.add_argument("words", nargs="*", metavar="sandbox [-- command]",
                       help="A sandbox's id, then (after --) a command to run instead of a terminal.")
    shell.add_argument("--machine", metavar="NAME", help="A machine, by name or id.")
    shell.add_argument("--agent", metavar="NAME", help="An agent's sandbox, by name or id, beside its work.")
    shell.add_argument("--conversation", metavar="ID", help="With --agent: that conversation's (default: its session).")
    shell.add_argument("--app", metavar="NAME", help="An app's live container, by name or id (commands only).")
    shell.add_argument("--timeout", type=int, metavar="SECONDS",
                       help="With a command: stop it after this long (at most 90).")
