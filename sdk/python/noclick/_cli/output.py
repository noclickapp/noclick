"""How every ``noclick`` command answers: one convention both CLIs (Python's and TypeScript's ``output.ts``) follow.

- **Exit codes** are ``exits``': 0 done, 1 failed, 2 usage, 3 waiting on a person, 4 refused by a limit, a price or
  a policy, 124 a wait ran out, 130 Ctrl-C.
- **Output.** Short and human by default, on stdout; notes and progress on stderr. ``--json`` prints the whole answer
  as JSON on stdout, errors included (``{"error": {...}}``), and nothing else there.
- **The last line.** Without ``--json``, the value an agent wants next (a URL, else an id) is stdout's last line, alone.
- **Errors say the next command.** An error's ``next_step`` is printed, then each command it suggests after ``run:``.
  Those come from fields, never out of its words: the commands the CLI's own error names (``run``, set where it's
  raised: ``CommandError(..., run=[...])`` or ``output.run(err, [...])``), the API's own (``details.run``), and the
  command that makes each API route its next step names (``GET /v1/agents``), from the spec.
  The next step's own words say each API call and operation it names as the ``noclick`` command that makes it.
  A link only a person can open is printed after ``open:``; an error that waits on a person is said as
  ``waiting on a person:``, not ``error:``.
- **Flushed.** Every line is flushed as it's printed, so each reaches a pipe (``| grep``, ``> file``) at once.
"""

from __future__ import annotations

import json
from decimal import Decimal
import re
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl

from . import style
from .exits import (  # noqa: F401  (the codes, read through output by the commands)
    FAILED, INTERRUPTED, OK, REFUSED, TIMED_OUT, USAGE, WAITING, WAITING_STATUSES, code_for, exit_code,
)

_CALL = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/v1/[^\s,;)`'\"]*[^\s,;.)`'\"])")
_LINK = re.compile(r"https?://[^\s)`'\"]+[^\s.,;)`'\"]")
_NAME = re.compile(r"`?\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b`?")
_LAST_KEYS = ("url", "live_url", "preview_url", "approve_url", "connect_url", "link", "id")
_SHELL_SAFE = re.compile(r"[\w@%+=:,./-]+")


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


def number(value: float) -> str:
    """A number as JSON writes it in JavaScript (``JSON.stringify``), the one rule both CLIs print numbers by: a whole
    float as an integer (``25.0`` is ``25``), else the shortest digits that read back as it, with an exponent past
    ``1e21`` or under ``1e-6`` (``1e-7``, ``1e+21``)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(value)
    if isinstance(value, int):
        return str(value)
    if value != value or value in (float("inf"), float("-inf")):
        return "null"
    if value == int(value) and abs(value) < 1e21:
        return str(int(value))
    sign, digits, exponent = Decimal(repr(abs(value))).normalize().as_tuple()
    text, k = "".join(map(str, digits)), len(digits)
    n = exponent + k  # the decimal point's place after the first digit, as ECMAScript's Number::toString counts it
    if k <= n <= 21:
        shown = text + "0" * (n - k)
    elif 0 < n <= 21:
        shown = f"{text[:n]}.{text[n:]}"
    elif -6 < n <= 0:
        shown = f"0.{'0' * -n}{text}"
    else:
        shown = f"{text[0]}{'.' + text[1:] if k > 1 else ''}e{'+' if n - 1 >= 0 else '-'}{abs(n - 1)}"
    return f"-{shown}" if value < 0 else shown


def dumps(value: Any, *, indent: Optional[int] = 2, ascii: bool = True) -> str:
    """``value`` as JSON exactly as the npm CLI writes it (``JSON.stringify(value, null, indent)``): numbers by
    ``number``, ``ascii`` escaping every character past ASCII as ``--json`` does (a person's lines keep them)."""
    def text(item: Any, depth: int) -> str:
        if item is None or isinstance(item, bool):
            return json.dumps(item)
        if isinstance(item, (int, float)):
            return number(item)
        if isinstance(item, str):
            return json.dumps(item, ensure_ascii=ascii)
        if isinstance(item, dict):
            pairs = [(json.dumps(str(k), ensure_ascii=ascii), v) for k, v in item.items()]
            if not pairs:
                return "{}"
            if indent is None:
                return "{" + ",".join(f"{k}:{text(v, depth + 1)}" for k, v in pairs) + "}"
            inner, outer = " " * (indent * (depth + 1)), " " * (indent * depth)
            return "{\n" + ",\n".join(f"{inner}{k}: {text(v, depth + 1)}" for k, v in pairs) + f"\n{outer}}}"
        if isinstance(item, (list, tuple)):
            if not item:
                return "[]"
            if indent is None:
                return "[" + ",".join(text(v, depth + 1) for v in item) + "]"
            inner, outer = " " * (indent * (depth + 1)), " " * (indent * depth)
            return "[\n" + ",\n".join(f"{inner}{text(v, depth + 1)}" for v in item) + f"\n{outer}]"
        return json.dumps(str(item), ensure_ascii=ascii)

    return text(plain(value), 0)


def scalar(value: Any) -> str:
    """One value on a person's line (``key: value``): text as it is, everything else as JSON writes it."""
    return value if isinstance(value, str) else dumps(value, indent=None, ascii=False)


def print_json(value: Any) -> None:
    print(dumps(value), flush=True)


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
    """The ``noclick`` command that makes an API route (``METHOD /v1/...``) or an operation (by its name), from the
    generated spec (``spec.Spec``); ``flag`` names a query parameter's flag."""

    def __init__(self, by_call: Callable[[str, str], Optional[Dict[str, Any]]],
                 by_name: Callable[[str], Optional[Dict[str, Any]]] = lambda name: None,
                 flag: Optional[Callable[[str], str]] = None, *,
                 curated: Callable[[List[str]], Optional[Dict[str, Any]]] = lambda path: None,
                 shadowed: Callable[[Dict[str, Any]], bool] = lambda op: False):
        self._by_call = by_call
        self._by_name = by_name
        self._flag = flag
        self._curated = curated
        self._shadowed = shadowed

    def for_call(self, method: str, path: str) -> str:
        op = self._by_call(method, path)
        if op is None:
            return f"noclick api {method} {path}"
        if not self._shadowed(op):
            return command_line(op, path, self._flag)
        # A curated command has its name (``domains search``): that one, with the arguments it needs, else the call.
        command = self._curated([op["area"], op["command"]])
        if command is None:
            return f"noclick api {method} {path}"
        return " ".join(["noclick", *command["path"],
                         *(f"<{a['name']}>" for a in command["args"] if not a.get("optional"))])

    def translate(self, text: Optional[str]) -> Optional[str]:
        """``text`` (an error's ``next_step``) with each API call and operation it names said as the command that
        makes it: "List agents with GET /v1/agents." is "List agents with noclick agents list."."""
        if not text:
            return text
        text = _CALL.sub(lambda m: self.for_call(m.group(1), m.group(2)), text)

        def named(m: "re.Match[str]") -> str:
            op = self._by_name(m.group(1))
            return m.group(0).replace(m.group(1), command_line(op, op["path"])) if op else m.group(0)

        return _NAME.sub(named, text)

    def routes(self, text: Optional[str]) -> List[str]:
        """The command for each API route and each operation ``text`` (an error's ``next_step``) names, in order."""
        found = [self.for_call(method, path) for method, path in _CALL.findall(text or "")]
        for name in _NAME.findall(text or ""):
            op = self._by_name(name)
            if op is not None:
                found.append(command_line(op, op["path"]))
        return list(dict.fromkeys(found))


def run(error: Any, commands: Sequence[str]) -> Any:
    """``error`` suggesting ``commands`` (each a whole ``noclick`` command line), printed after ``run:``."""
    error.run = list(commands)
    return error


def suggested(error: Any, commands: Optional[Commands] = None, *, step: Optional[str] = None,
              also: Sequence[str] = ()) -> List[str]:
    """The commands an error suggests: ``also`` (the command line's own wording of the API's step), the ones it was
    raised with (``run``), the API's (``details.run``), then the command for each route its ``step`` names."""
    details = getattr(error, "details", None) or {}
    given = details.get("run")
    found = [*also, *(getattr(error, "run", None) or []), *(given if isinstance(given, list) else [])]
    if commands is not None:
        found += commands.routes(step)
    return list(dict.fromkeys(c for c in found if isinstance(c, str) and c))


def command_line(op: Dict[str, Any], path: str, flag: Optional[Callable[[str], str]] = None) -> str:
    """``noclick <area> <command>`` with the path's parameters: a concrete path's values, else ``<name>``; given
    ``flag``, the query parameters the path carries as the flags that set them (``--limit 5``)."""
    path, _, query = path.partition("?")
    template = op["path"].strip("/").split("/")
    given = path.strip("/").split("/")
    values: Dict[str, str] = {}
    if len(template) == len(given):
        for t, g in zip(template, given):
            if t.startswith("{") and not (g.startswith("{") or g == "..."):
                values[t[1:-1]] = g
    args = [values.get(p["name"], f"<{p['name']}>") for p in op["params"] if p["in"] == "path"]
    taken = {p["name"] for p in op["params"] if p["in"] == "query"}
    flags = [f"{flag(k)} {_quoted(v)}" for k, v in parse_qsl(query) if flag and k in taken]
    return " ".join(["noclick", op["area"], op["command"], *args, *flags])


def _quoted(value: str) -> str:
    """``value`` as a shell reads it back: as it is when it's safe there, else in single quotes."""
    return value if _SHELL_SAFE.fullmatch(value) else "'" + value.replace("'", "'\\''") + "'"


def error_body(error: Any, commands: Optional[Commands] = None, *,
               said: Optional[Tuple[str, Optional[str], Sequence[str]]] = None) -> Dict[str, Any]:
    """An error as ``--json`` prints it: the API's fields, its exit code, and the commands it suggests."""
    details = dict(getattr(error, "details", None) or {})
    details.pop("run", None)
    message, step, also = said or (getattr(error, "message", None) or str(error), getattr(error, "next_step", None), ())
    body: Dict[str, Any] = {
        "type": getattr(error, "type", None) or "error",
        "message": message,
        "next_step": step,
        "exit_code": code_for(error),
    }
    if getattr(error, "usage", None):
        body["usage"] = error.usage
    found = suggested(error, commands, step=step, also=also)
    if found:
        body["commands"] = found
    if commands is not None and body["next_step"]:
        body["next_step"] = commands.translate(body["next_step"])
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
           said: Optional[Tuple[str, Optional[str], Sequence[str]]] = None) -> int:
    """Print an error the convention's way and return its exit code. ``said`` is its message, next step and the
    commands that take it as the command line words them, in place of the API's."""
    body = error_body(error, commands, said=said)
    if as_json:
        print_json({"error": body})
    else:
        waiting = body["exit_code"] == WAITING
        s = style.ERR
        said = s.warn("waiting on a person:") if waiting else s.error("error:")
        _say(f"{said} {s.bold(body['message']) if s.on else body['message']}")
        if body.get("usage"):
            _say(f"  {s.dim('usage:')} {body['usage']}")
        if body["next_step"]:
            _say(f"  {s.dim('next step:')} {body['next_step']}")
        for line in body.get("commands", []):
            if not (body["next_step"] or "").rstrip(". ").endswith(line):  # said once: a step ending in it
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
            yield f"{indent}{key}: {scalar(item)}"  # a list or object whole: a cut value reads as another
        return
    if value is not None:
        yield scalar(value)


def _rows(items: Sequence[Any]) -> Iterable[str]:
    if not items:
        yield "Nothing to show."
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
    return scalar(value)


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
