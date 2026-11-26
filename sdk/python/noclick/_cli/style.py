"""How the CLI looks to a person at a terminal: headings with a rule under them, dimmed descriptions, an accent, the
colours of a result (ok, warn, error) and bordered tables. Plain ANSI, no dependencies; the TypeScript CLI's
``style.ts`` draws the same.

Never for a machine: each stream is styled only when it's a terminal, never under ``NO_COLOR``, ``TERM=dumb`` or
``CI``, and ``--color always|never`` decides past all of that. Unstyled, every command prints exactly what it printed
before there were styles, so what a script or an agent reads never changes.

The colours are NoClick's own: the violet and blue of the one mark the product draws in colour (Automations'), its
zinc greys for what's quiet, and the status hues of the app (emerald, red; orange where the app has amber, no yellow).
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, TextIO, Tuple

MODES = ("auto", "always", "never")

# Each role's colour: 24-bit where the terminal says it takes it, else the nearest of the 256.
PALETTE: Dict[str, Tuple[Tuple[int, int, int], int]] = {
    "accent": ((180, 156, 255), 147),  # #b49cff, the mark's violet: headings, command names
    "link": ((127, 212, 255), 117),    # #7fd4ff, the mark's blue: URLs and commands to copy
    "dim": ((161, 161, 170), 248),     # zinc-400, the app's muted text: descriptions, notes
    "rule": ((82, 82, 91), 240),       # zinc-600: rules and table borders
    "ok": ((52, 211, 153), 79),        # emerald-400
    "warn": ((251, 146, 60), 209),     # orange-400
    "error": ((248, 113, 113), 210),   # red-400
}
ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
# A status screen's line, its label padded to 12; and the app's name and URL heading it.
_FIELD = re.compile(r"^( {0,2})([a-z][a-z ]{10}) (\S.*)$")
_HEAD = re.compile(r"^([\w.-]+)  (https?://\S+)$")
ELLIPSIS = "…"
# Columns whose cells are copied whole (an id, a commit, a key), cut only once nothing else can give.
KEPT_WHOLE = frozenset({"ID", "KEY", "COMMIT", "URL"})
# Notes that say something was done get a check; a step under way, a quiet arrow.
_DONE = re.compile(r"^(Ready:|Signed (in|up|out)|Set |Deleted |Linked |Unlinked |Made |Promoted |Rolled back |"
                   r"Bound |Added |Bought |Revoked )")
_STEP = re.compile(r"^(Deploying|Building|Shipping|Checking|Waiting|Stopping)\b")


def wanted(mode: str, stream: Any, env: Mapping[str, str]) -> bool:
    """Whether to style ``stream`` under ``--color mode``."""
    if mode == "always":
        return True
    if mode == "never" or env.get("NO_COLOR") or env.get("TERM") == "dumb" or env.get("CI"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


class Style:
    """One stream's styles; every method answers ``text`` as it is when the stream isn't styled."""

    def __init__(self, on: bool = False, *, truecolor: bool = False, width: Optional[int] = None):
        self.on = on
        self.truecolor = truecolor
        self._width = width

    def width(self) -> int:
        return self._width or shutil.get_terminal_size((100, 24)).columns

    def paint(self, text: str, role: Optional[str] = None, *, bold: bool = False) -> str:
        if not self.on or not text or not (role or bold):
            return text
        codes = ["1"] if bold else []
        if role:
            rgb, nearest = PALETTE[role]
            codes.append("38;2;%d;%d;%d" % rgb if self.truecolor else f"38;5;{nearest}")
        return f"\x1b[{';'.join(codes)}m{text}\x1b[0m"

    def bold(self, text: str) -> str:
        return self.paint(text, bold=True)

    def dim(self, text: str) -> str:
        return self.paint(text, "dim")

    def accent(self, text: str) -> str:
        return self.paint(text, "accent")

    def link(self, text: str) -> str:
        return self.paint(text, "link")

    def ok(self, text: str) -> str:
        return self.paint(text, "ok")

    def warn(self, text: str) -> str:
        return self.paint(text, "warn")

    def error(self, text: str) -> str:
        return self.paint(text, "error", bold=True)

    def section(self, title: str) -> List[str]:
        """A section's heading: bold in the accent, a thin rule under it as wide as the terminal allows."""
        if not self.on:
            return [f"{title}:"]
        return [self.paint(title, "accent", bold=True), self.paint("─" * min(self.width(), 100), "rule")]

    def note(self, text: str) -> str:
        """A note for a person: a check before what was done, an arrow before a step under way, the rest dimmed."""
        if not self.on:
            return text
        if _DONE.match(text):
            return f"{self.ok('✓')} {text}"
        if _STEP.match(text):
            return f"{self.accent('›')} {text}"
        return self.dim(text)

    def fields(self, lines: Sequence[str]) -> List[str]:
        """A screen of ``label  value`` lines (``noclick status``): labels dimmed, a status word in its colour, a URL in
        the link colour, the app's own name bold."""
        if not self.on:
            return list(lines)
        out = []
        for line in lines:
            head, field = _HEAD.match(line), _FIELD.match(line)
            if head:
                out.append(f"{self.bold(head.group(1))}  {self.link(head.group(2))}")
            elif field:
                indent, label, value = field.groups()
                word, space, rest = value.partition(" ")
                role = "warn" if word == "unread" else _status_role(word)
                out.append(f"{indent}{self.dim(label)} {self.paint(word, role)}{space}{rest}")
            else:
                out.append(line)
        return out

    def table(self, headers: Sequence[str], rows: Sequence[Sequence[str]], *, title: Optional[str] = None) -> List[str]:
        """Rows under bold headers in a box, its columns fitted to the terminal, a cell too long cut with "…"."""
        widths = fit([max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)],
                     [len(h) for h in headers], self.width(),
                     keep=[h.strip().upper() in KEPT_WHOLE for h in headers])
        edge = lambda left, mid, right: self.paint(left + mid.join("─" * (w + 2) for w in widths) + right, "rule")  # noqa: E731
        bar = self.paint("│", "rule")

        status = [h.strip().upper() in ("STATUS", "STATE", "AVAILABLE") for h in headers]

        def line(cells: Sequence[str], header: bool = False) -> str:
            shown = []
            for i, (c, w) in enumerate(zip(cells, widths)):
                text = clip(c, w).ljust(w)
                shown.append(self.bold(text) if header else self.paint(text, _status_role(c)) if status[i] else text)
            return bar + bar.join(f" {c} " for c in shown) + bar

        out: List[str] = []
        if title:
            total = sum(widths) + 3 * len(widths) + 1
            shown = clip(title, total)
            out.append(self.bold(" " * ((total - len(shown)) // 2) + shown))
        out += [edge("╭", "┬", "╮"), line(headers, True), edge("├", "┼", "┤")]
        out += [line(r) for r in rows]
        out.append(edge("╰", "┴", "╯"))
        return out


_STATUS = {"ok": {"ready", "live", "active", "available", "yes", "succeeded", "completed", "claimed", "running",
                  "confirmed", "done"},
           "warn": {"building", "queued", "pending", "deploying", "waiting", "unclaimed", "paused", "starting"},
           "error": {"failed", "error", "canceled", "cancelled", "expired", "no", "revoked", "stopped"}}


def _status_role(value: str) -> Optional[str]:
    return next((role for role, words in _STATUS.items() if value.strip().lower() in words), None)


def clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[:max(width - 1, 0)] + ELLIPSIS


def fit(widths: List[int], floors: List[int], total: int, *, keep: Optional[List[bool]] = None) -> List[int]:
    """Column widths narrowed, widest first, until the box (borders and padding included) fits ``total``; a column
    ``keep`` marks (an id to copy) only once nothing else can give."""
    widths = list(widths)
    floors = [min(max(f, 3), w) for f, w in zip(floors, widths)]
    keep = keep or [False] * len(widths)
    while sum(widths) + 3 * len(widths) + 1 > total:
        room = [i for i, w in enumerate(widths) if w > floors[i] and not keep[i]] or \
            [i for i, w in enumerate(widths) if w > floors[i]]
        if not room:
            break
        widest = max(room, key=lambda i: widths[i])
        widths[widest] -= 1
    return widths


def visible(text: str) -> str:
    return ESCAPE.sub("", text)


OUT = Style()
ERR = Style()


def configure(mode: str = "auto", *, stdout: Optional[TextIO] = None, stderr: Optional[TextIO] = None,
              env: Optional[Mapping[str, str]] = None) -> None:
    """Decide, once a command starts, whether its stdout and stderr are styled."""
    env = os.environ if env is None else env
    truecolor = env.get("COLORTERM") in ("truecolor", "24bit")
    OUT.__init__(wanted(mode, stdout or sys.stdout, env), truecolor=truecolor)
    ERR.__init__(wanted(mode, stderr or sys.stderr, env), truecolor=truecolor)


def mode_in(argv: Sequence[str]) -> str:
    """``--color``'s value among the flags before the command (``auto`` without one)."""
    words = iter(argv)
    for word in words:
        if not word.startswith("-"):
            break
        if word.startswith("--color="):
            return word.split("=", 1)[1]
        if word in ("--color", "--profile"):
            value = next(words, "auto")
            if word == "--color":
                return value
    return "auto"
