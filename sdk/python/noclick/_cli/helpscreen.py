"""A command's ``--help``, as a person reads it: a ``Usage:`` line, its description, then sections (Arguments,
Commands, Options, Global flags, Notes, Examples) each under a heading (and a rule, at a terminal), names in one
column and what they do beside them. A curated command's and ``noclick --help`` are drawn from the manifest
(``command_screen``, ``render``), as the TypeScript CLI's ``helpscreen.ts`` draws them, so both print the same help,
at a terminal or piped."""

from __future__ import annotations

import argparse
import textwrap
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .style import Style

NAME_COLUMN = 28


def _invocation(parser: argparse.ArgumentParser, action: argparse.Action) -> str:
    return parser._get_formatter()._format_action_invocation(action)


def _help_of(parser: argparse.ArgumentParser, action: argparse.Action) -> str:
    return parser._get_formatter()._expand_help(action) if action.help else ""


def usage(parser: argparse.ArgumentParser, s: Style) -> str:
    """``Usage: noclick deploy [OPTIONS] [APP]``: its options as one word, its arguments as argparse names them."""
    formatter = parser._get_formatter()
    words = [parser.prog]
    if any(a.option_strings and a.help != argparse.SUPPRESS for a in parser._actions):
        words.append("[OPTIONS]")
    for action in parser._actions:
        if action.option_strings or action.help == argparse.SUPPRESS:
            continue
        if isinstance(action, argparse._SubParsersAction):
            words.append(f"{action.metavar or '<command>'} ...")
            continue
        words.append(formatter._format_args(action, action.dest))
    return f"{s.bold('Usage:')} {' '.join(words)}"


def wrap(text: str, width: int) -> List[str]:
    """``text`` in lines of at most ``width`` (a word longer than that alone on its line), as ``helpscreen.ts``
    wraps."""
    return textwrap.wrap(text, width, break_long_words=False, break_on_hyphens=False)


def rows(items: Iterable[Tuple[str, str]], s: Style, *, name_as=None, width: Optional[int] = None) -> List[str]:
    """Names in one column and what they do beside them, dimmed, wrapped under its own column."""
    items = list(items)
    if not items:
        return []
    total = width or s.width()
    column = min(max(len(name) for name, _ in items), NAME_COLUMN)
    paint = name_as or s.accent
    out: List[str] = []
    for name, text in items:
        room = max(total - column - 6, 30)
        lines = wrap(text, room) or [""]
        if len(name) > column:
            out.append(f"  {paint(name)}")
            out += [f"  {' ' * column}  {s.dim(line)}" for line in lines]
            continue
        out.append(f"  {paint(name.ljust(column))}  {s.dim(lines[0])}".rstrip())
        out += [f"  {' ' * column}  {s.dim(line)}" for line in lines[1:]]
    return out


def render(s: Style, *, usage: str, description: str = "", middle: Sequence[str] = (),
           sections: Sequence[Tuple[str, Sequence[Tuple[str, str]]]] = (), notes: str = "",
           examples: Sequence[str] = ()) -> str:
    """A help screen from its parts (``helpscreen.ts``' ``screen``)."""
    width = min(s.width(), 100)
    lines = [f"{s.bold('Usage:')} {usage}", ""]
    if description:
        lines += [*(line for p in description.split("\n") for line in (wrap(p, width) if p else [""])), ""]
    if middle:
        lines += [*middle, ""]
    for title, items in sections:
        if items:
            lines += [*s.section(title), *rows(items, s, width=width), ""]
    if notes:
        lines += [*s.section("Notes"), *(f"  {s.dim(line)}" for line in wrap(notes, width - 2)), ""]
    if examples:
        lines += [*s.section("Examples"), *(f"  {s.link(e)}" for e in examples), ""]
    return "\n".join(lines).rstrip()


def invocation(flag: Dict[str, Any]) -> str:
    """A flag as its help names it: ``-r, --recursive``, ``--app APP``, ``--env {all,production,preview}``,
    ``--preview [NAME]`` (its value may be left out)."""
    names = f"{flag['short']}, {flag['flag']}" if flag.get("short") else flag["flag"]
    if flag["type"] == "bool":
        return names
    value = ("{" + ",".join(str(c) for c in flag["choices"]) + "}" if flag.get("choices")
             else flag.get("metavar") or flag["dest"].upper())
    return f"{names} [{value}]" if "const" in flag else f"{names} {value}"


def argument(arg: Dict[str, Any]) -> str:
    name = arg.get("metavar") or arg["name"]
    return (f"[{name}]" if arg.get("optional") else f"<{name}>") + ("..." if arg.get("many") else "")


def usage_of(command: Dict[str, Any]) -> str:
    """``noclick secret set [OPTIONS] <name>``: a curated command's usage, from the manifest."""
    return " ".join(["noclick", *command["path"], *(["[OPTIONS]"] if command["flags"] else []),
                     *(argument(a) for a in command["args"])])


#: What every command's help lists after its own options: the flags any command takes.
HELP_FLAG = ("-h, --help", "Show this help.")


def global_flags(globals_: Sequence[Dict[str, Any]]) -> List[Tuple[str, str]]:
    return [*((invocation(g), g.get("help", "")) for g in globals_ if g["flag"] != "--version"), HELP_FLAG]


def command_screen(command: Dict[str, Any], globals_: Sequence[Dict[str, Any]], s: Style) -> str:
    """A curated command's help, from the manifest: what ``helpscreen.ts`` draws for it."""
    return render(s, usage=usage_of(command), description=command.get("summary", ""), sections=(
        ("Arguments", [(a.get("metavar") or a["name"], a.get("help", "")) for a in command["args"]]),
        ("Options", [(invocation(f), f.get("help", "")) for f in command["flags"]]),
        ("Global flags", global_flags(globals_)),
    ), notes=command.get("notes", ""), examples=command.get("examples") or ())


def screen(parser: argparse.ArgumentParser, s: Style, *, examples: Sequence[str] = (),
           middle: Sequence[str] = ()) -> str:
    """A parser's help, styled. ``middle``: lines put after its description in place of its list of commands (the
    top screen's sections)."""
    width = min(s.width(), 100)
    lines = [usage(parser, s), ""]
    if parser.description:
        lines += [*wrap(parser.description, width), ""]
    if middle:
        lines += [*middle, ""]
    arguments, commands = [], []
    for action in parser._actions:
        if action.option_strings or action.help == argparse.SUPPRESS:
            continue
        if isinstance(action, argparse._SubParsersAction):
            if not middle:
                commands += [(c.dest, c.help or "") for c in action._choices_actions]
        else:
            arguments.append((_invocation(parser, action), _help_of(parser, action)))
    options = [(_invocation(parser, a), _help_of(parser, a)) for a in parser._actions
               if a.option_strings and a.help != argparse.SUPPRESS]
    for title, items in (("Arguments", arguments), ("Commands", commands), ("Options", options)):
        if items:
            lines += [*s.section(title), *rows(items, s, width=width), ""]
    if parser.epilog:
        lines += [*s.section("Notes"), *(f"  {s.dim(line)}" for line in wrap(parser.epilog, width - 2)), ""]
    if examples:
        lines += [*s.section("Examples"), *(f"  {s.link(e)}" for e in examples), ""]
    return "\n".join(lines).rstrip() + "\n"
