"""How every ``noclick`` command answers: one convention both CLIs (Python's and TypeScript's ``output.ts``) follow.

- **Exit codes** are ``exits``': 0 done, 1 failed, 2 usage, 3 waiting on a person, 4 refused by a limit, a price or
  a policy, 124 a wait ran out, 130 Ctrl-C.
- **Output.** Short and human by default, on stdout; notes and progress on stderr. ``--json`` prints the whole answer
  as JSON on stdout, errors included (``{"error": {...}}``), and nothing else there.
- **The last line.** Without ``--json``, the value an agent wants next (a URL, else an id) is stdout's last line, alone.
- **Errors say the next command.** An error's ``next_step`` is printed, and where it names an API call (``GET
  /v1/agents``) or an operation (``agents_list``), the ``noclick`` command that makes it is printed after ``run:``.
  A link only a person can open is printed after ``open:``; an error that waits on a person is said as
  ``waiting on a person:``, not ``error:``.
- **Flushed.** Every line is flushed as it's printed, so each reaches a pipe (``| grep``, ``> file``) at once.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from . import style
from .exits import (  # noqa: F401  (the codes, read through output by the commands)
    FAILED, INTERRUPTED, OK, REFUSED, TIMED_OUT, USAGE, WAITING, WAITING_STATUSES, code_for, exit_code,
)

_CALL = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/v1/[^\s,;)`'\"]*[^\s,;.)`'\"])")
_LINK = re.compile(r"https?://[^\s)`'\"]+[^\s.,;)`'\"]")
_CLI = re.compile(r"\bnoclick(?:[ \t]+(?:[a-z][\w.:/@<>=-]*|--[\w-]+))+")
_NAME = re.compile(r"`?\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b`?")
_LAST_KEYS = ("url", "live_url", "preview_url", "approve_url", "connect_url", "link", "id")


def plain(value: Any) -> Any:
    """``value`` as JSON can hold it: dataclasses and SDK objects (their ``raw``) as dicts, times as ISO text."""
    if is_dataclass(value) and not isinstance(value, type):
        raw = getattr(value, "raw", None)
        return plain(raw if isinstance(raw, dict) else asdict(value))
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    for name in ("raw", "_raw"):
        raw = getattr(value, name, None)
        if isinstance(raw, dict):
            return plain(raw)
    return value


def print_json(value: Any) -> None:
    print(json.dumps(plain(value), indent=2, default=str), flush=True)


def note(text: str) -> None:
    """A line for a person: stderr, never in the way of what a script reads."""
    print(style.ERR.note(text), file=sys.stderr, flush=True)


def _say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def last_value(value: Any) -> Optional[str]:
    """The value an agent wants next from an answer: its URL, else its id (an operation's: its result's, if any)."""
    if isinstance(value, dict) and value.get("object") == "operation" and isinstance(value.get("result"), dict):
        found = last_value(value["result"])
        if found and found != value["result"].get("id"):
            return found
    if isinstance(value, dict):
        for key in _LAST_KEYS:
            found = value.get(key)
            if isinstance(found, str) and found:
                return found
    return None


class Commands:
    """Turns what an error says into commands: a ``METHOD /v1/...`` call or an operation's name into the ``noclick``
    command that makes it, from the generated spec (``spec.Spec``)."""

    def __init__(self, by_call: Callable[[str, str], Optional[Dict[str, Any]]],
                 by_name: Callable[[str], Optional[Dict[str, Any]]]):
        self._by_call = by_call
        self._by_name = by_name

    def for_call(self, method: str, path: str) -> str:
        op = self._by_call(method, path)
        if op is None:
            return f"noclick api {method} {path}"
        return command_line(op, path)

    def runnable(self, text: Optional[str]) -> List[str]:
        """The commands ``text`` (an error's ``next_step``) names, in order."""
        found: List[str] = [m.group(0).rstrip(".") for m in _CLI.finditer(text or "")]
        for method, path in _CALL.findall(text or ""):
            found.append(self.for_call(method, path))
        for name in _NAME.findall(text or ""):
            op = self._by_name(name)
            if op is not None:
                found.append(command_line(op, op["path"]))
        return list(dict.fromkeys(found))


def command_line(op: Dict[str, Any], path: str) -> str:
    """``noclick <area> <command>`` with the path's parameters: a concrete path's values, else ``<name>``."""
    template = op["path"].strip("/").split("/")
    given = path.strip("/").split("/")
    values: Dict[str, str] = {}
    if len(template) == len(given):
        for t, g in zip(template, given):
            if t.startswith("{") and not (g.startswith("{") or g == "..."):
                values[t[1:-1]] = g
    args = [values.get(p["name"], f"<{p['name']}>") for p in op["params"] if p["in"] == "path"]
    return " ".join(["noclick", op["area"], op["command"], *args])


def error_body(error: Any, commands: Optional[Commands] = None, *,
               said: Optional[Tuple[str, Optional[str]]] = None) -> Dict[str, Any]:
    """An error as ``--json`` prints it: the API's fields, its exit code, and the commands its next step names."""
    details = dict(getattr(error, "details", None) or {})
    message, step = said or (getattr(error, "message", None) or str(error), getattr(error, "next_step", None))
    body: Dict[str, Any] = {
        "type": getattr(error, "type", None) or "error",
        "message": message,
        "next_step": step,
        "exit_code": code_for(error),
    }
    if commands is not None and body["next_step"]:
        body["commands"] = commands.runnable(body["next_step"])
    links = links_of(error)
    if links:
        body["links"] = links
    if getattr(error, "request_id", None):
        body["request_id"] = error.request_id
    if details:
        body["details"] = plain(details)
    return body


def links_of(error: Any) -> List[str]:
    """What only a person can open: an approval's page, a payment link, a sign-in, and links its next step names."""
    details = getattr(error, "details", None) or {}
    found: List[str] = []
    for key in ("link", "approve_url", "answer_url", "url", "connect_url", "payment_url", "checkout_url"):
        value = details.get(key)
        if isinstance(value, str) and value.startswith("http"):
            found.append(value)
    for offer in details.get("offers") or []:
        if isinstance(offer, dict) and isinstance(offer.get("url"), str):
            found.append(offer["url"])
    found.extend(_LINK.findall(getattr(error, "next_step", None) or ""))
    return list(dict.fromkeys(found))


def report(error: Any, *, as_json: bool, commands: Optional[Commands] = None,
           said: Optional[Tuple[str, Optional[str]]] = None) -> int:
    """Print an error the convention's way and return its exit code. ``said`` is its message and next step as the
    command line words them, in place of the API's."""
    body = error_body(error, commands, said=said)
    if as_json:
        print_json({"error": body})
    else:
        waiting = body["exit_code"] == WAITING
        s = style.ERR
        said = s.warn("waiting on a person:") if waiting else s.error("error:")
        _say(f"{said} {s.bold(body['message']) if s.on else body['message']}")
        if body["next_step"]:
            _say(f"  {s.dim('next step:')} {body['next_step']}")
        for line in body.get("commands", []):
            _say(f"  {s.dim('run:')} {s.link(line)}")
        for link in body.get("links", []):
            _say(f"  {s.dim('open:')} {s.link(link)}")
        if body.get("request_id"):
            _say(f"  {s.dim('request id:')} {s.dim(body['request_id'])}")
    return body["exit_code"]


def human(value: Any, *, indent: str = "") -> Iterable[str]:
    """An answer as short lines for a person: a dict's scalar fields, a list's items one a line."""
    value = plain(value)
    if isinstance(value, dict) and isinstance(value.get("data"), list):
        yield from _rows(value["data"])
        if value.get("next_cursor"):
            yield f"{indent}(more: add --cursor {value['next_cursor']})"
        return
    if isinstance(value, list):
        yield from _rows(value)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if item is None or item == [] or item == {}:
                continue
            if isinstance(item, (dict, list)):
                shown = json.dumps(item, default=str)
                item = shown if len(shown) <= 100 else f"{shown[:97]}..."
            yield f"{indent}{key}: {item}"
        return
    if value is not None:
        yield str(value)


def _rows(items: Sequence[Any]) -> Iterable[str]:
    if not items:
        yield "(none)"
        return
    if style.OUT.on and all(isinstance(item, dict) for item in items):
        rows = [[cell(item.get("id")), cell(_label(item)), cell(item.get("status") or item.get("state"))]
                for item in items]
        yield from style.OUT.table(["ID", "NAME", "STATUS"], rows)
        return
    for item in items:
        if isinstance(item, dict):
            label = _label(item)
            status = item.get("status") or item.get("state") or ""
            yield "  ".join(str(p) for p in (item.get("id", ""), label, status) if p != "")
        else:
            yield str(item)


def _label(item: Dict[str, Any]) -> str:
    return item.get("name") or item.get("title") or item.get("email") or item.get("summary") or ""


def answer(value: Any, *, as_json: bool) -> None:
    """Print a command's answer: whole as JSON, or short with its useful value last and alone."""
    if as_json:
        print_json(value)
        return
    for each in human(value):
        line(each)
    value_last(last_value(plain(value)))


def line(text: str) -> None:
    """One line of a result, flushed: through a pipe each arrives as it's printed."""
    print(text, flush=True)


def value_last(value: Optional[str]) -> None:
    """The command's one useful value (a URL, an id) as stdout's last line, so ``x=$(noclick ...)`` captures it."""
    if value:
        line(value)


def cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, datetime):
        return value.astimezone().strftime("%Y-%m-%d %H:%M")
    return str(value)


def table(headers: Sequence[str], rows: Iterable[Sequence[Any]], *, empty: str, title: Optional[str] = None) -> None:
    """Rows under headers: at a terminal a bordered table (``title`` above it), else columns lined up."""
    cells = [[cell(v) for v in row] for row in rows]
    if not cells:
        note(empty)
        return
    if style.OUT.on:
        for each in style.OUT.table([h or " " for h in headers], cells, title=title):
            print(each)
        sys.stdout.flush()
        return
    widths = [max(len(h), *(len(row[i]) for row in cells)) for i, h in enumerate(headers)]
    for row in [list(headers), *cells]:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip())
    sys.stdout.flush()


def size(n: Optional[int]) -> str:
    if n is None:
        return "-"
    amount = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1000 or unit == "TB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1000
    return str(n)


def usd(value: Optional[float]) -> str:
    return "-" if value is None else f"${value:,.2f}"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"
