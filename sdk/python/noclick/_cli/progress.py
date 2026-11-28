"""A release as it happens (``noclick deploy``, ``rollback``, ``promote``): each stage with a spinner and its time, the
work's own lines (a build's log) as they come, then a tick or a cross. The TypeScript CLI's ``progress.ts`` draws the
same, line for line (``tests/cli_progress_cases.json`` holds both to it).

At a terminal (stderr styled, ``style.ERR.on``) the stage under way is one line drawn again in place; anywhere else
(piped, ``CI``, ``NO_COLOR``) each stage's start and end is a plain line of its own, so a log reads top to bottom.

The operation is followed through its own long-poll: each read of ``GET /v1/operations/{id}/wait`` names the
``updated_at`` it last saw (``changed_since``), so the server answers as soon as anything moves, one request per
change, never a page read on a timer. Ctrl-C stops following; the work goes on.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Set

from . import style

SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
TICK_S = 0.1
# A stage's name as a person reads it, by the name the operation reports it under.
NAMES = {"Queued": "Queue", "Building": "Build", "Shipping": "Release", "Live": "Health check"}
_PAD = 12
TERMINAL = frozenset({"succeeded", "failed", "canceled", "expired"})
# The longest one read lets the server hold it (the server caps it near this).
WINDOW_S = 50


def took(seconds: float) -> str:
    """``3.4s`` under a minute, ``2m 05s`` past it (cut to tenths, never rounded, as the TypeScript CLI cuts)."""
    tenths = max(math.floor(seconds * 10 + 1e-9), 0)
    if tenths < 600:
        return f"{tenths // 10}.{tenths % 10}s"
    whole = tenths // 10
    return f"{whole // 60}m {whole % 60:02d}s"


class Steps:
    """Stages and the lines between them, written to ``write``: drawn in place when ``live``, else a line each."""

    def __init__(self, write: Optional[Callable[[str], None]] = None, *, live: Optional[bool] = None,
                 clock: Callable[[], float] = time.monotonic, paint: Optional[style.Style] = None,
                 ticker: bool = True) -> None:
        """``ticker``: a thread turns the spinner while a stage is under way (a test turns it with ``tick``)."""
        self._write = write or _stderr
        self.live = style.ERR.on if live is None else live
        self.clock = clock
        self.paint = paint or style.ERR
        self.current: Optional[str] = None
        self.since = 0.0
        self.frame = 0
        self.drawn = False
        self.printed_lines = 0
        self.ticker = ticker
        self._lock = threading.RLock()
        self._ticking: Optional[threading.Event] = None

    def start(self, name: str) -> None:
        """Start a stage (the one under way, if any, ends first)."""
        self.end(True)
        with self._lock:
            self.current, self.since = name, self.clock()
            if self.live:
                self._draw()
            else:
                self._write(f"{name}…\n")
        if self.live and self.ticker and self._ticking is None:
            stop = self._ticking = threading.Event()
            threading.Thread(target=self._tick_until, args=(stop,), daemon=True).start()

    def end(self, ok: bool = True, *, seconds: Optional[float] = None) -> None:
        """End the stage under way; ``seconds`` is how long it took where the work says, else the time seen here."""
        with self._lock:
            if self.current is None:
                return
            name, spent = self.current, took(self.clock() - self.since if seconds is None else seconds)
            self.current = None
            self._stop_ticking()
            if self.live:
                self._clear()
                mark = self.paint.ok("✓") if ok else self.paint.error("✗")
                self._write(f"{mark} {name.ljust(_PAD)} {self.paint.dim(spent)}\n")
            else:
                self._write(f"{name}: {spent}\n" if ok else f"{name}: failed after {spent}\n")

    def line(self, text: str) -> None:
        with self._lock:
            self.printed_lines += 1
            if self.live:
                self._clear()
                self._write(f"  {self.paint.dim(text)}\n")
                self._draw()
            else:
                self._write(f"  {text}\n")

    def tick(self) -> None:
        with self._lock:
            self.frame += 1
            self._draw()

    def close(self) -> None:
        """Stop drawing: the line in place is cleared, the stage left as it was."""
        with self._lock:
            self._stop_ticking()
            self._clear()

    def _stop_ticking(self) -> None:
        if self._ticking is not None:
            self._ticking.set()
            self._ticking = None

    def _tick_until(self, stop: threading.Event) -> None:
        while not stop.wait(TICK_S):
            self.tick()

    def _draw(self) -> None:
        if not self.live or self.current is None:
            return
        spin = self.paint.accent(SPIN[self.frame % len(SPIN)])
        self._write(f"\r\x1b[2K{spin} {self.current.ljust(_PAD)} {self.paint.dim(took(self.clock() - self.since))}")
        self.drawn = True

    def _clear(self) -> None:
        if self.drawn:
            self._write("\r\x1b[2K")
            self.drawn = False


def _stderr(text: str) -> None:
    sys.stderr.write(text)
    sys.stderr.flush()


def _seconds(stage: Dict[str, Any]) -> Optional[float]:
    """How long a stage took, by the work's own clock (Python 3.10 reads no ``Z``)."""
    try:
        start, end = (datetime.fromisoformat(str(stage[k]).replace("Z", "+00:00")) for k in ("started_at", "ended_at"))
    except (KeyError, TypeError, ValueError):
        return None
    return (end - start).total_seconds()


class Follower:
    """What an operation's reads say, as stages and lines: each read its ``progress`` (stages, the last lines and how
    many there have been), only what's new drawn."""

    def __init__(self, steps: Steps, *, single: Optional[str] = None) -> None:
        """``single``: the one stage shown for work that reports none (a promote)."""
        self.steps, self.single = steps, single
        self.shown = 0
        self.started: Set[str] = set()

    def apply(self, raw: Dict[str, Any]) -> None:
        """A read's new lines go under the stage that was under way before it (they're what it printed until it
        moved on: a build's last lines come with the move to its release); the first read's, and those read as it
        leaves the queue (which prints nothing), under the stage it's at."""
        progress = raw.get("progress") or {}
        if self.steps.current in (None, NAMES["Queued"]):
            self._stages(raw, progress)
            self._lines(progress)
        else:
            self._lines(progress)
            self._stages(raw, progress)
        if raw.get("status") in TERMINAL:
            self.steps.end(raw.get("status") == "succeeded")

    def _lines(self, progress: Dict[str, Any]) -> None:
        lines, count = progress.get("lines") or [], progress.get("line_count") or 0
        fresh = min(count - self.shown, len(lines))
        for text in lines[len(lines) - fresh:] if fresh > 0 else []:
            self.steps.line(text)
        self.shown = max(self.shown, count)

    def _stages(self, raw: Dict[str, Any], progress: Dict[str, Any]) -> None:
        stages = progress.get("stages") or []
        for stage in stages:
            name = NAMES.get(stage.get("name"), stage.get("name") or "")
            if stage.get("status") in ("current", "done") and name not in self.started:
                self.steps.start(name)
                self.started.add(name)
            if stage.get("status") == "done" and self.steps.current == name:
                self.steps.end(True, seconds=_seconds(stage))
        if not stages and self.single and self.single not in self.started:
            self.steps.start(self.single)
            self.started.add(self.single)


Read = Callable[[str, int, Optional[str]], Dict[str, Any]]


def follow(op_id: str, raw: Dict[str, Any], steps: Steps, read: Read, *, timeout: Optional[float] = None,
           single: Optional[str] = None, clock: Callable[[], float] = time.monotonic) -> Optional[Dict[str, Any]]:
    """Follow the operation from ``raw`` (as it stands) until it ends or ``timeout`` passes, drawing it; ``read(id,
    window, changed_since)`` is one long-poll. The operation as last read, or None once Ctrl-C stopped following.
    A read that fails ends the stage under way with a cross, and raises."""
    follower = Follower(steps, single=single)
    deadline = None if timeout is None else clock() + timeout
    try:
        follower.apply(raw)
        while raw.get("status") not in TERMINAL:
            window = WINDOW_S
            if deadline is not None:
                left = deadline - clock()
                if left <= 0:
                    break
                window = min(WINDOW_S, max(1, math.ceil(left)))
            raw = read(op_id, window, raw.get("updated_at"))
            follower.apply(raw)
    except KeyboardInterrupt:
        steps.close()
        return None
    except BaseException:
        steps.end(False)
        raise
    return raw


__all__ = ["Follower", "NAMES", "SPIN", "Steps", "follow", "took"]
