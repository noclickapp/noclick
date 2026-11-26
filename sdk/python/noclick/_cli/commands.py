"""The commands made from the spec: ``noclick <area> <command>`` for every ``/v1`` operation, ``noclick api``,
``noclick describe`` and ``noclick help --json``. Every call goes through the SDK's own client
(``Client.request``: the key, retries, typed errors), never a request of its own.

An area's commands are added to the parser only when the command line names that area (``add_areas``), so a
command that isn't one of them starts as fast as before.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote

from .._client import default_client
from .._sync import run_sync
from ..exceptions import InvalidRequest
from . import exits, output
from .spec import Spec, load

# What every generated command takes besides its operation's own fields.
RESERVED = ("json", "data", "wait", "no_wait", "user", "timeout", "help", "profile", "version")
WAIT_WINDOW_S = 20


class UsageError(InvalidRequest):
    """A command the CLI can tell is wrong before calling anything: exit 2."""

    type = "invalid_request"


def flag_of(name: str) -> str:
    return "--" + (f"field-{name}" if name in RESERVED else name).replace("_", "-")


def commands_for(spec: Spec) -> output.Commands:
    return output.Commands(spec.for_call, spec.named)


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
            if op["command"] in group.choices:
                continue
            add_operation(group, op, parents)


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


def add_operation(group: Any, op: Dict[str, Any], parents: Sequence[argparse.ArgumentParser]) -> None:
    sub = group.add_parser(op["command"], help=op["summary"] or op["name"],
                           description=f"{op['summary']}\n\n{op['method']} {op['path']}  ({op['risk']})",
                           formatter_class=argparse.RawDescriptionHelpFormatter, parents=list(parents))
    sub.epilog = f"Its fields, risk and an example: noclick describe {op['area']} {op['command']}"
    for param in op["params"]:
        help_text = param.get("description") or ""
        if param["in"] == "path":
            sub.add_argument(param["name"], help=help_text)
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
    sub.add_argument("--no-wait", action="store_true",
                     help="When it starts an operation, print its id instead of waiting for it.")
    sub.add_argument("--timeout", type=float, metavar="SECONDS",
                     help="Stop waiting after this long (exit 124; the operation keeps going).")
    sub.set_defaults(run=run_operation, operation_spec=op, auth=True)


def add_builtins(commands: Any, parents: Sequence[argparse.ArgumentParser]) -> None:
    """``noclick api``, ``noclick describe`` and ``noclick help``."""
    api = commands.add_parser("api", help="Call any /v1 route: the raw escape hatch.",
                              description="Call any /v1 route with your key, its answer printed as JSON.",
                              parents=list(parents))
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


def request_of(op: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    """The call ``args`` make: its path, query and body (``--data``, then each flag given over it)."""
    data = _read_data(getattr(args, "data", None))
    body: Any = dict(data) if isinstance(data, dict) and op["body"] == "merge" else data
    query: Dict[str, Any] = {}
    path = op["path"]
    missing: List[str] = []
    for param in op["params"]:
        name = param["name"]
        if param["in"] == "path":
            path = path.replace("{" + name + "}", quote(str(getattr(args, name)), safe=""))
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
                         next_step=f"noclick describe {op['area']} {op['command']}")
    if op["method"] in ("POST", "PUT", "PATCH") and body is None and op["body"] == "merge":
        body = {}
    return {"method": op["method"], "path": path, "query": query, "body": body}


def call(method: str, path: str, *, query: Optional[Dict[str, Any]] = None, body: Any = None) -> Any:
    client = default_client()
    return run_sync(client.request(method, path, json=body, params=query or None))


def run_operation(args: argparse.Namespace) -> int:
    request = request_of(args.operation_spec, args)
    answer = call(request["method"], request["path"], query=request["query"], body=request["body"])
    return finish(answer, args)


def run_api(args: argparse.Namespace) -> int:
    query: Dict[str, Any] = {}
    for pair in args.query:
        key, sep, value = pair.partition("=")
        if not sep:
            raise UsageError(f"--query {pair} isn't KEY=VALUE.", next_step="Pass --query limit=5.")
        query[key] = value
    path = args.path if args.path.startswith("/") else f"/{args.path}"
    answer = call(args.method, path, query=query, body=_read_data(args.data))
    return finish(answer, args)


def finish(answer: Any, args: argparse.Namespace) -> int:
    """Print an answer; an operation it started is waited on (unless ``--no-wait``), and one waiting on a person
    exits 3 with what it waits on."""
    as_json = getattr(args, "json", False)
    if isinstance(answer, dict) and answer.get("object") == "operation" and not getattr(args, "no_wait", False):
        answer = wait_for(answer, timeout=getattr(args, "timeout", None))
    output.answer(answer, as_json=as_json)
    if isinstance(answer, dict):
        status = answer.get("status")
        if status in output.WAITING_STATUSES:
            if not as_json:
                output.note(f"waiting on a person ({status}): noclick ops wait {answer.get('id')} when done")
            return output.WAITING
        if answer.get("object") == "operation" and status == "failed":
            error = answer.get("error") or {}
            output.note(f"error: {error.get('message') or 'the operation failed'}")
            if error.get("next_step"):
                output.note(f"  next step: {error['next_step']}")
            return output.exit_code(error.get("type"))
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
            raise OperationTimeout(f"Operation {raw['id']} is still {raw.get('status')}.",
                                   next_step=f"noclick ops wait {raw['id']}",
                                   details={"operation_id": raw["id"]})
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
                         next_step="noclick help --json lists every command.")
    if args.json:
        output.print_json({**op, "example": example(op)})
        return output.OK
    print(f"noclick {op['area']} {op['command']}   ({op['name']})")
    print(f"  {op['method']} {op['path']}   risk: {op['risk']}")
    if op["summary"]:
        print(f"  {op['summary']}")
    for param in op["params"]:
        shown = param["name"] if param["in"] == "path" else flag_of(param["name"])
        traits = [param["type"]] + (["required"] if param.get("required") else []) \
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
    for command in curated:
        print(f"noclick {' '.join(command['path']):<28} {command['summary']}")
    if args.words:
        for op in generated:
            print(f"noclick {op['area']} {op['command']:<20} {op['summary']}")
    else:
        for area, ops in sorted(spec.areas().items()):
            print(f"noclick {area:<28} {len(ops)} API operations")
    print("Details: noclick <command> --help; every command as JSON: noclick help --json")
    return output.OK
