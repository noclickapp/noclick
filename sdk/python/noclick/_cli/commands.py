"""The commands made from the spec: ``noclick <area> <command>`` for every ``/v1`` operation, ``noclick api``,
``noclick describe`` and ``noclick help --json``. Every call goes through the SDK's own client
(``Client.request``: the key, retries, typed errors), never a request of its own.

An area's commands are added to the parser only when the command line names that area (``add_areas``), so a
command that isn't one of them starts as fast as before. A name a command had still runs it, though no list shows it
(its ``aliases``), and a path argument naming something that has a name takes the name in place of its id
(``resolve_names``: an exact name, read from its list).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

from .._client import default_client
from .._sync import run_sync
from ..exceptions import InvalidRequest, NotFound
from . import exits, output, style
from .spec import Spec, load

# What every generated command takes besides its operation's own fields.
RESERVED = ("json", "data", "wait", "no_wait", "user", "timeout", "help", "profile", "version")
WAIT_WINDOW_S = 20
# The verbs a group lists first, in this order; its other commands follow.
COMMON_VERBS = ("list", "get", "create", "update", "delete")
# An id NoClick made: anything else given where one goes is a name, read from the list of what it names.
_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# How many pages of a list a name is looked for in, when the list can't be narrowed to the name.
LOOKUP_PAGES = 20


class UsageError(exits.Suggests, InvalidRequest):
    """A command the CLI can tell is wrong before calling anything: exit 2."""

    type = "invalid_request"


def flag_of(name: str) -> str:
    return "--" + (f"field-{name}" if name in RESERVED else name).replace("_", "-")


def commands_for(spec: Spec) -> output.Commands:
    return output.Commands(spec.for_call, spec.named, flag_of, curated=lambda path: next(
        (c for c in spec.commands if c["path"] == path), None), shadowed=shadowed)


# --- the parser ----------------------------------------------------------------------------------------------------


def add_areas(commands: Any, parents: Sequence[argparse.ArgumentParser], argv: Sequence[str]) -> None:
    """Add every area to ``commands`` (the top-level subparsers): the area named in ``argv`` with its operations, the
    rest as one line each, so ``noclick --help`` lists them all. An area a curated group already has (``agents``)
    gets its operations beside the curated commands, a curated name winning."""
    spec = load()
    wanted = _named_area(argv, spec)
    for area, ops in sorted(spec.areas().items()):
        existing = commands.choices.get(area)
        if existing is None:
            sub = commands.add_parser(area, help=f"{len(ops)} API operations: noclick {area} --help lists them.",
                                      description=f"The /v1 operations under {area}, one command each.")
            if area != wanted:
                sub.add_argument("rest", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
                sub.set_defaults(run=_area_help(area), auth=False)
                continue
            group = sub.add_subparsers(dest="operation", metavar="<command>", required=True)
        elif area != wanted:
            continue
        else:
            group = _subparsers_of(existing)
            if group is None:
                continue
        for op in ops:
            made = None if op["command"] in group.choices else add_operation(group, op, parents)
            for alias in op.get("aliases", ()):  # a name it had: it runs, but no list shows it
                if alias in group.choices:
                    continue
                if made is None:
                    made = add_operation(group, op, parents, name=alias, listed=False)
                else:
                    group._name_parser_map[alias] = made  # argparse keeps no public way to name a parser twice


# The global flags that take a value, so the word after one is never read as the area.
_VALUED_GLOBALS = ("--profile", "--color")


def _named_area(argv: Sequence[str], spec: Spec) -> Optional[str]:
    words = [a for i, a in enumerate(argv) if not a.startswith("-") and (i == 0 or argv[i - 1] not in _VALUED_GLOBALS)]
    return words[0] if words and words[0] in spec.areas() else None


def _subparsers_of(parser: argparse.ArgumentParser) -> Optional[Any]:
    for action in parser._actions:  # argparse keeps no public handle on a parser's subcommands
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _area_help(area: str) -> Any:
    def run(args: argparse.Namespace) -> int:  # only reached when the area wasn't the one named
        output.note(f"usage: noclick {area} <command>  (noclick {area} --help lists them)")
        return output.USAGE

    return run


def add_operation(group: Any, op: Dict[str, Any], parents: Sequence[argparse.ArgumentParser], *,
                  name: Optional[str] = None, listed: bool = True) -> argparse.ArgumentParser:
    """The command ``op`` is, under ``name`` (its command); ``listed=False`` leaves it out of the group's help."""
    shown = {"help": op["summary"] or op["name"]} if listed else {}  # argparse lists a parser only given its help
    sub = group.add_parser(name or op["command"], **shown,
                           description=f"{op['description']}\n\n{op['method']} {op['path']}  ({op['risk']})",
                           formatter_class=argparse.RawDescriptionHelpFormatter, parents=list(parents))
    sub.epilog = f"Its fields, risk and an example: noclick describe {op['area']} {op['command']}"
    for param in op["params"]:
        help_text = param.get("description") or ""
        if param["in"] == "path":
            sub.add_argument(param["name"], help=path_help(param))
            continue
        kwargs: Dict[str, Any] = {"dest": f"field__{param['name']}", "help": help_text, "default": None}
        kind = param["type"]
        if kind == "boolean":
            kwargs["action"] = argparse.BooleanOptionalAction
        elif kind == "list":
            kwargs["action"] = "append"
            kwargs["metavar"] = "VALUE"
        elif kind in ("integer", "number"):
            kwargs["type"] = int if kind == "integer" else float
        elif kind == "json":
            kwargs["metavar"] = "JSON"
        if param.get("choices") and kind not in ("boolean", "json"):
            kwargs["choices"] = param["choices"] if kind != "list" else None
            if kwargs["choices"] is None:
                del kwargs["choices"]
        sub.add_argument(flag_of(param["name"]), **kwargs)
    sub.add_argument("--data", metavar="JSON|@FILE|-",
                     help="The whole request body: JSON, @file or - for stdin (flags given beside it win).")
    if not any(p["name"] == "output" for p in op["params"]):  # a field of its own named output wins
        sub.add_argument("--output", dest="output_file", metavar="FILE", help=OUTPUT_HELP)
    sub.add_argument("--no-wait", action="store_true",
                     help="When it starts an operation, print its id instead of waiting for it.")
    sub.add_argument("--timeout", type=float, metavar="SECONDS",
                     help="Stop waiting after this long (exit 124; the operation keeps going).")
    sub.set_defaults(run=run_operation, operation_spec=op, auth=True)
    return sub


def path_help(param: Dict[str, Any]) -> str:
    """A path argument's help: what the API says of it, and that it takes a name where what it names has one."""
    said = param.get("description") or ""
    lookup = param.get("lookup")
    if not lookup:
        return said
    return " ".join(part for part in (said, f"The {lookup['noun']}'s name or id.") if part)


OUTPUT_HELP = "Save the answer to this file (a file's bytes as they are) instead of printing it."


def add_builtins(commands: Any, parents: Sequence[argparse.ArgumentParser]) -> None:
    """``noclick api``, ``noclick describe`` and ``noclick help``."""
    api = commands.add_parser("api", help="Call any /v1 route: the raw escape hatch.",
                              description="Call any /v1 route with your key, its answer printed as JSON.",
                              parents=list(parents))
    api.add_argument("--output", dest="output_file", metavar="FILE", help=OUTPUT_HELP)
    api.add_argument("--table", action="store_true",
                     help="Print the answer as rows (a list) or fields (an object) instead of JSON.")
    api.add_argument("method", type=str.upper, choices=("GET", "POST", "PUT", "PATCH", "DELETE"))
    api.add_argument("path", help="The path, like /v1/agents or /v1/agents/support?limit=5.")
    api.add_argument("--data", metavar="JSON|@FILE|-", help="The JSON body: JSON, @file or - for stdin.")
    api.add_argument("-q", "--query", action="append", default=[], metavar="KEY=VALUE",
                     help="A query parameter (repeat for more).")
    api.set_defaults(run=run_api, auth=True)

    describe = commands.add_parser(
        "describe", help="An API operation's fields, risk and an example.",
        description="Describe an operation: by its command (describe agents create), its name (describe "
                    "agents_create) or its route (describe POST /v1/agents).", parents=[p for p in parents])
    describe.add_argument("words", nargs="+", metavar="OPERATION")
    describe.set_defaults(run=run_describe, auth=False)

    help_ = commands.add_parser("help", help="Every command, its arguments and flags (--json for all of it).",
                                description="Every command: the curated ones and one per /v1 operation.",
                                parents=[p for p in parents])
    help_.add_argument("words", nargs="*", metavar="COMMAND", help="Only this command or area.")
    help_.set_defaults(run=run_help, auth=False)


# --- running -------------------------------------------------------------------------------------------------------


def _read_data(text: Optional[str]) -> Any:
    if text is None:
        return None
    if text == "-":
        text = sys.stdin.read()
    elif text.startswith("@"):
        text = Path(text[1:]).read_text()
    try:
        return json.loads(text)
    except ValueError as err:
        raise UsageError(f"--data isn't JSON: {err}.", next_step="Pass a JSON object, @file.json or - for stdin.")


def _field_value(param: Dict[str, Any], value: Any) -> Any:
    if param["type"] != "json" or not isinstance(value, str):
        return value
    if value.startswith("@"):
        value = Path(value[1:]).read_text()
    try:
        return json.loads(value)
    except ValueError:
        return value  # a plain string where the schema takes more than one shape


def request_of(op: Dict[str, Any], args: argparse.Namespace,
               ids: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """The call ``args`` make: its path, query and body (``--data``, then each flag given over it). ``ids``: the path
    arguments as ``resolve_names`` read them (a name given for an id, its id)."""
    data = _read_data(getattr(args, "data", None))
    body: Any = dict(data) if isinstance(data, dict) and op["body"] == "merge" else data
    query: Dict[str, Any] = {}
    path = op["path"]
    missing: List[str] = []
    for param in op["params"]:
        name = param["name"]
        if param["in"] == "path":
            value = (ids or {}).get(name, getattr(args, name))
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
            continue
        value = getattr(args, f"field__{name}", None)
        if value is None:
            given = isinstance(body, dict) and name in body
            if param.get("required") and not given:
                missing.append(flag_of(name))
            continue
        value = _field_value(param, value)
        if param["in"] == "query":
            query[name] = ",".join(map(str, value)) if isinstance(value, list) else value
        elif op["body"] == "wrap":
            body = value
        else:
            body = body if isinstance(body, dict) else {}
            body[name] = value
    if missing:
        raise UsageError(f"{op['area']} {op['command']} needs {', '.join(missing)}.",
                         next_step=f"noclick describe {op['area']} {op['command']}",
                         run=[f"noclick describe {op['area']} {op['command']}"])
    if op["method"] in ("POST", "PUT", "PATCH") and body is None and op["body"] == "merge":
        body = {}
    return {"method": op["method"], "path": path, "query": query, "body": body}


def call(method: str, path: str, *, query: Optional[Dict[str, Any]] = None, body: Any = None) -> Any:
    """The API's answer: its JSON, or the bytes of one that isn't JSON (a file read as it is)."""
    client = default_client()
    return run_sync(client.request(method, path, json=body, params=query or None, binary="auto"))


def run_operation(args: argparse.Namespace) -> int:
    op = args.operation_spec
    request = request_of(op, args, resolve_names(op, {p["name"]: str(getattr(args, p["name"]))
                                                      for p in op["params"] if p["in"] == "path"}))
    answer = call(request["method"], request["path"], query=request["query"], body=request["body"])
    return finish(answer, args)


def resolve_names(op: Dict[str, Any], given: Dict[str, str]) -> Dict[str, str]:
    """The path arguments ``given``, each name given for an id read as that id: an argument whose parameter says where
    its names are listed (``lookup``), given something that isn't an id NoClick made or a ref (``agent:support``)."""
    spec, ids = load(), {}
    for param in op["params"]:
        if param["in"] != "path":
            continue
        value = given[param["name"]]
        lookup = param.get("lookup")
        taken_as_is = not lookup or _ID.match(value) or ":" in value
        ids[param["name"]] = value if taken_as_is else _named(spec, lookup, value, ids)
    return ids


def _named(spec: Spec, lookup: Dict[str, Any], name: str, ids: Dict[str, str]) -> str:
    """The id of the one thing called ``name`` (or called so before a rename) in its list; none, or more than one,
    raises with the command that lists them."""
    listing = spec.named(lookup["list"])
    path = listing["path"]
    for param in listing["params"]:
        if param["in"] == "path":
            path = path.replace("{" + param["name"] + "}", quote(ids[param["name"]], safe=""))
    narrowed = {lookup["query"]: name} if lookup.get("query") else {}
    found: Dict[str, Dict[str, Any]] = {}
    cursor = None
    for _ in range(LOOKUP_PAGES):
        page = call("GET", path, query={**narrowed, **({"cursor": cursor} if cursor else {})})
        rows = page.get("data") if isinstance(page, dict) else page
        for row in rows or []:
            if isinstance(row, dict) and row.get("id") and (
                    row.get("name") == name or name in (row.get("former_names") or [])):
                found.setdefault(str(row["id"]), row)
        cursor = page.get("next_cursor") if isinstance(page, dict) else None
        if not cursor:
            break
    if len(found) == 1:
        return next(iter(found))
    listed = output.command_line(listing, path)
    if not found:
        raise output.run(NotFound(f"No {lookup['noun']} named '{name}'.", next_step=f"List them with {listed}.",
                                  details={"name": name}), [listed])
    matches = [{k: row.get(k) for k in ("id", "name", "status", "user_id") if row.get(k) is not None}
               for row in found.values()]
    said = ", ".join(f"{m['id']} ({m['status']})" if m.get("status") else m["id"] for m in matches)
    raise UsageError(f"{len(matches)} {lookup['plural']} are named '{name}': {said}.",
                     next_step="Pass the id of the one you mean.", details={"name": name, "matches": matches})


def run_api(args: argparse.Namespace) -> int:
    query: Dict[str, Any] = {}
    for pair in args.query:
        key, sep, value = pair.partition("=")
        if not sep:
            raise UsageError(f"--query {pair} isn't KEY=VALUE.", next_step="Pass --query limit=5.")
        query[key] = value
    path = args.path if args.path.startswith("/") else f"/{args.path}"
    answer = call(args.method, path, query=query, body=_read_data(args.data))
    args.json = not args.table  # the raw escape hatch prints the answer as it came, unless asked for rows
    return finish(answer, args)


def finish(answer: Any, args: argparse.Namespace) -> int:
    """Print an answer; an operation it started is waited on (unless ``--no-wait``), and one waiting on a person
    exits 3 with what it waits on."""
    as_json = getattr(args, "json", False)
    saved = getattr(args, "output_file", None)
    if isinstance(answer, bytes):
        return _write(answer, saved)
    if isinstance(answer, dict) and answer.get("object") == "operation" and not getattr(args, "no_wait", False):
        answer = wait_for(answer, timeout=getattr(args, "timeout", None))
    if saved:
        return _write(answer, saved)
    output.answer(answer, as_json=as_json)
    if isinstance(answer, dict):
        status = answer.get("status")
        if status in output.WAITING_STATUSES:
            if not as_json:
                output.note(f"waiting on a person ({status}): noclick wait {answer.get('id')} when done")
            return output.WAITING
        if answer.get("object") == "operation" and status == "failed":
            error = answer.get("error") or {}
            output.note(f"error: {error.get('message') or 'the operation failed'}")
            if error.get("next_step"):
                output.note(f"  next step: {commands_for(load()).translate(error['next_step'])}")
            return output.exit_code(error.get("type"))
    return output.OK


def _write(answer: Any, path: Optional[str]) -> int:
    """An answer written as it came: a body that isn't JSON as its bytes (text as it is), JSON as JSON; to stdout, or
    to ``path`` (``--output``), whose name is then stdout's last line."""
    data = answer if isinstance(answer, bytes) else (output.dumps(answer) + "\n").encode()
    if path is None:
        sys.stdout.flush()
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        return output.OK
    Path(path).write_bytes(data)
    output.note(f"Saved {output.size(len(data))} to {path}.")
    output.line(path)
    return output.OK


def wait_for(operation: Dict[str, Any], *, timeout: Optional[float]) -> Dict[str, Any]:
    """Wait on an operation through the SDK until it ends, or waits on a person; ``timeout`` raises."""
    from ..operation import TERMINAL, Operation
    from ..exceptions import Error, OperationTimeout

    deadline = None if timeout is None else time.monotonic() + timeout
    op = Operation.from_id(operation["id"])
    raw = operation
    while raw.get("status") not in TERMINAL and raw.get("status") not in output.WAITING_STATUSES:
        window = WAIT_WINDOW_S if deadline is None else min(WAIT_WINDOW_S, deadline - time.monotonic())
        if window <= 0:
            raise output.run(OperationTimeout(f"Operation {raw['id']} is still {raw.get('status')}.",
                                              next_step=f"noclick wait {raw['id']}",
                                              details={"operation_id": raw["id"]}), [f"noclick wait {raw['id']}"])
        try:
            op.wait(timeout=window)
        except OperationTimeout:
            pass
        except Error:
            pass  # a failed operation: its view below says how
        raw = output.plain(op)
    return raw


def run_describe(args: argparse.Namespace) -> int:
    spec = load()
    op = spec.lookup(args.words)
    if op is None:
        raise UsageError(f"No operation {' '.join(args.words)}.",
                         next_step="noclick help --json lists every command.", run=["noclick help --json"])
    if args.json:
        output.print_json({**op, "example": example(op)})
        return output.OK
    print(f"noclick {op['area']} {op['command']}   ({op['name']})")
    print(f"  {op['method']} {op['path']}   risk: {op['risk']}")
    if op["description"]:
        print(f"  {op['description']}")
    for param in op["params"]:
        shown = param["name"] if param["in"] == "path" else flag_of(param["name"])
        traits = [param["type"]] + (["its name or id"] if param.get("lookup") else []) \
            + (["required"] if param.get("required") else []) \
            + (["one of " + "|".join(map(str, param["choices"]))] if param.get("choices") else []) \
            + (["secret"] if param.get("secret") else [])
        print(f"  {shown}  ({', '.join(traits)})" + (f"  {param['description']}" if param.get("description") else ""))
    print(f"example: {example(op)}")
    return output.OK


def shadowed(op: Dict[str, Any]) -> bool:
    """Whether a curated command has the operation's name (``domains search``), or its area's (``status``, a command of
    its own): the name runs the curated one, and the operation is made with ``noclick api``."""
    return any(c["path"] in ([op["area"], op["command"]], [op["area"]]) for c in load().commands)


def example(op: Dict[str, Any]) -> str:
    """A command line making the call with its required fields."""
    if shadowed(op):
        path = op["path"]
        return f"noclick api {op['method']} " + path.replace("{", "<").replace("}", ">")
    words = ["noclick", op["area"], op["command"]]
    for param in op["params"]:
        if param["in"] == "path":
            words.append(f"<{param['name']}>")
        elif param.get("required"):
            value = {"integer": "1", "number": "1", "boolean": "", "json": "'{}'", "list": "<value>"}.get(
                param["type"], f"<{param['name']}>")
            if param.get("choices"):
                value = str(param["choices"][0])
            words.append(flag_of(param["name"]) + (f" {value}" if value else ""))
    return " ".join(words)


def listing(groups: Sequence[Sequence[Tuple[str, str]]], width: int, s: Optional[style.Style] = None) -> List[str]:
    """Groups of commands and what each does, a blank line between groups and every description in one column
    whatever a command's length: a command longer than the column has a line of its own, its description under the
    column. Descriptions wrap at ``width``."""
    rows = [row for group in groups for row in group]
    if not rows:
        return []
    s = s or style.Style()
    column = min(max(len(name) for name, _ in rows), max(width * 2 // 5, 20))
    room = max(width - column - 2, 30)
    out: List[str] = []
    for group in groups:
        if out and group:
            out.append("")
        for name, text in group:
            lines = textwrap.wrap(text, room, break_long_words=False, break_on_hyphens=False) or [""]
            if len(name) > column:
                out.append(s.accent(name))
            else:
                out.append(f"{s.accent(name.ljust(column))}  {s.dim(lines.pop(0))}".rstrip())
            out += [f"{' ' * (column + 2)}{s.dim(line)}" for line in lines]
    return out


def grouped(rows: Sequence[Tuple[str, str]]) -> List[List[Tuple[str, str]]]:
    """A group's commands: the common verbs first, in ``COMMON_VERBS``'s order, then the rest as they came."""
    verb = {row: row[0].split()[-1] for row in rows}
    common = sorted((row for row in rows if verb[row] in COMMON_VERBS), key=lambda row: COMMON_VERBS.index(verb[row]))
    rest = [row for row in rows if verb[row] not in COMMON_VERBS]
    return [group for group in (common, rest) if group]


def run_help(args: argparse.Namespace) -> int:
    spec = load()
    curated = [c for c in spec.commands if not args.words or c["path"][:len(args.words)] == args.words]
    generated = [op for op in spec.operations
                 if not args.words or [op["area"], op["command"]][:len(args.words)] == args.words]
    if args.json:
        output.print_json({
            "conventions": {"exit_codes": exits.MEANINGS,
                            "json": "--json prints the whole answer, errors as {\"error\": {...}}",
                            "last_line": "without --json, the useful value (a URL, else an id) is the last line"},
            "commands": curated,
            "operations": [{**op, "usage": example(op)} for op in generated],
        })
        return output.OK
    rows = [(f"noclick {' '.join(c['path'])}", c["summary"]) for c in curated]
    if args.words:
        shown = {name for name, _ in rows}
        rows += [(f"noclick {op['area']} {op['command']}", op["summary"]) for op in generated
                 if f"noclick {op['area']} {op['command']}" not in shown]
        groups = grouped(rows)
    else:
        areas = [(f"noclick {area}", f"{len(ops)} API operations") for area, ops in sorted(spec.areas().items())]
        groups = [rows, areas]
    for each in listing(groups, style.OUT.width(), style.OUT):
        output.line(each)
    output.line("Details: noclick <command> --help; every command as JSON: noclick help --json")
    return output.OK
