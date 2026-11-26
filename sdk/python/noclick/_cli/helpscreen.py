"""A command's ``--help`` at a terminal, as a person reads it: a ``Usage:`` line, its description, then sections
(Arguments, Commands, Options, Notes, Examples) each under a heading and a rule, names in one column and what they
do dimmed beside them. Off a terminal, argparse's own help is printed as it always was (``cli._Parser``)."""

from __future__ import annotations

import argparse
import textwrap
from typing import Iterable, List, Optional, Sequence, Tuple

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
        lines = textwrap.wrap(text, room) or [""]
        if len(name) > column:
            out.append(f"  {paint(name)}")
            out += [f"  {' ' * column}  {s.dim(line)}" for line in lines]
            continue
        out.append(f"  {paint(name.ljust(column))}  {s.dim(lines[0])}".rstrip())
        out += [f"  {' ' * column}  {s.dim(line)}" for line in lines[1:]]
    return out


def screen(parser: argparse.ArgumentParser, s: Style, *, examples: Sequence[str] = (),
           middle: Sequence[str] = ()) -> str:
    """A parser's help, styled. ``middle``: lines put after its description in place of its list of commands (the
    top screen's sections)."""
    width = min(s.width(), 100)
    lines = [usage(parser, s), ""]
    if parser.description:
        lines += [*textwrap.wrap(parser.description, width), ""]
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
        lines += [*s.section("Notes"), *(f"  {s.dim(line)}" for line in textwrap.wrap(parser.epilog, width - 2)), ""]
    if examples:
        lines += [*s.section("Examples"), *(f"  {s.link(e)}" for e in examples), ""]
    return "\n".join(lines).rstrip() + "\n"
