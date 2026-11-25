"""Keep the CLI's manifest (noclick/_cli/spec/manifest.json) to the curated commands the Python CLI has.

    python scripts/cli_manifest.py            # exit 1 naming what differs
    python scripts/cli_manifest.py --write    # rewrite it from the parser, keeping each command's examples

The manifest is what both CLIs run from: the TypeScript CLI builds its curated commands' arguments from it, and
``noclick help --json`` lists them. A curated command's arguments, flags and summary are its parser's; its
``examples`` are written in the manifest by hand.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from noclick import cli  # noqa: E402

MANIFEST = ROOT / "noclick" / "_cli" / "spec" / "manifest.json"
# Every command's own, said once in the manifest's ``globals`` rather than on each command.
GLOBAL_DESTS = ("help",)


def _type(action: argparse.Action) -> str:
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction, argparse.BooleanOptionalAction)):
        return "bool"
    if isinstance(action, argparse._AppendAction):
        return "list"
    if action.type is int:
        return "integer"
    if action.type is float:
        return "number"
    return "string"


def _option(action: argparse.Action) -> Dict[str, Any]:
    longs = [o for o in action.option_strings if o.startswith("--")]
    shorts = [o for o in action.option_strings if not o.startswith("--")]
    found: Dict[str, Any] = {"flag": longs[0] if longs else shorts[0], "dest": action.dest, "type": _type(action)}
    if shorts and longs:
        found["short"] = shorts[0]
    if action.choices:
        found["choices"] = list(action.choices)
    if action.required:
        found["required"] = True
    if action.metavar and not isinstance(action.metavar, tuple):
        found["metavar"] = action.metavar
    if action.help and action.help != argparse.SUPPRESS:
        found["help"] = action.help
    return found


def _argument(action: argparse.Action) -> Dict[str, Any]:
    found: Dict[str, Any] = {"name": action.dest}
    if action.nargs in ("?", "*"):
        found["optional"] = True
    if action.nargs in ("+", "*", argparse.REMAINDER):
        found["many"] = True
    if action.choices:
        found["choices"] = list(action.choices)
    if action.help and action.help != argparse.SUPPRESS:
        found["help"] = action.help
    return found


def commands_of(parser: argparse.ArgumentParser, path: List[str], summary: str) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    sub = next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)
    if sub is not None:
        helps = {a.dest: a.help for a in sub._choices_actions}
        for name, child in sub.choices.items():
            found.extend(commands_of(child, [*path, name], helps.get(name) or ""))
        return found
    groups = [[a.dest for a in g._group_actions] for g in parser._mutually_exclusive_groups]
    required = [g.required for g in parser._mutually_exclusive_groups]
    command: Dict[str, Any] = {
        "path": path,
        "summary": summary,
        "auth": bool(parser.get_default("auth")),
        "args": [_argument(a) for a in parser._actions if not a.option_strings and a.help != argparse.SUPPRESS],
        "flags": [_option(a) for a in parser._actions if a.option_strings and a.dest not in GLOBAL_DESTS],
    }
    if groups:
        command["one_of"] = [{"dests": g, "required": r} for g, r in zip(groups, required)]
    if parser.epilog:
        command["notes"] = parser.epilog
    return [command]


def manifest(existing: Dict[str, Any]) -> Dict[str, Any]:
    examples = {tuple(c["path"]): c.get("examples") for c in existing.get("commands", [])}
    parser = cli.build_parser(areas=False)
    commands = commands_of(parser, [], "")
    for command in commands:
        if examples.get(tuple(command["path"])):
            command["examples"] = examples[tuple(command["path"])]
    return {
        "format": 1,
        "globals": [_option(a) for a in parser._actions if a.option_strings and a.dest not in GLOBAL_DESTS],
        "commands": commands,
    }


def render(existing: Dict[str, Any]) -> str:
    return json.dumps(manifest(existing), indent=1, ensure_ascii=False) + "\n"


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help="Rewrite the manifest from the parser.")
    args = parser.parse_args(argv)
    existing = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    want = render(existing)
    if args.write:
        MANIFEST.write_text(want)
        return 0
    if not MANIFEST.exists() or MANIFEST.read_text() != want:
        print(f"{MANIFEST.name} isn't the parser's curated commands: run python scripts/cli_manifest.py --write",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
