"""The interchange as a command — what runs inside a harness sandbox, and
what you run by hand to look at a store.

    python -m interchange move --source-harness … --target-harness … --cwd …
    python -m interchange inspect --harness codex --home ~/.codex --cwd .
    python -m interchange formats
    python -m interchange copy --harness … --source-home … --target-home … --cwd … [--before … | --turns N]
    python -m interchange undo --spec edits.json --cwd …

Every command prints ONE JSON document on stdout and exits 0: the caller
judges the verdict, and a crash is a verdict too (``translator_crashed``).
Stdlib only — the package is shipped into sandboxes as files.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .engine import copy_thread, inspect_store, move_thread
from .formats import InterchangeError, describe_formats
from .ir import INTERCHANGE_VERSION, StoreRef, TargetIdentity
from .undo import undo_edits


def _store(prefix: str, a: argparse.Namespace, *, cwd: Optional[str] = None) -> StoreRef:
    get = lambda name: getattr(a, f"{prefix}_{name}", None)  # noqa: E731
    return StoreRef(
        harness=get("harness"), home=Path(get("home")), cwd=Path(cwd or get("cwd") or a.cwd),
        pointer=Path(get("pointer")) if get("pointer") else None, session_id=get("session_id"),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="interchange")
    sub = ap.add_subparsers(dest="command", required=True)

    mv = sub.add_parser("move", help="move this conversation's thread from one harness's store into another's")
    mv.add_argument("--source-harness", required=True)
    mv.add_argument("--source-home", required=True)
    mv.add_argument("--source-cwd")
    mv.add_argument("--source-pointer")
    mv.add_argument("--source-session-id")
    mv.add_argument("--target-harness", required=True)
    mv.add_argument("--target-home", required=True)
    mv.add_argument("--target-pointer")
    mv.add_argument("--target-session-id", help="the id the target runner resumes by, where the harness needs one")
    mv.add_argument("--cwd", required=True, help="the working directory the target thread runs under")
    mv.add_argument("--target-cli-version")
    mv.add_argument("--target-model-provider")
    mv.add_argument("--target-model")

    ins = sub.add_parser("inspect", help="what a store holds for a conversation, without moving anything")
    ins.add_argument("--harness", required=True)
    ins.add_argument("--home", required=True)
    ins.add_argument("--cwd", required=True)
    ins.add_argument("--pointer")
    ins.add_argument("--session-id")

    sub.add_parser("formats", help="the harness formats this build knows")

    cp = sub.add_parser("copy", help="copy a conversation's thread, cut, into an empty store of the same harness")
    for side in ("source", "target"):
        cp.add_argument(f"--{side}-home", required=True)
        cp.add_argument(f"--{side}-pointer")
        cp.add_argument(f"--{side}-session-id")
    cp.add_argument("--harness", required=True)
    cp.add_argument("--source-cwd")
    cp.add_argument("--cwd", required=True)
    cp.add_argument("--before", help="cut at the last user message holding this text")
    cp.add_argument("--turns", type=int, help="else keep this many user messages")
    cp.add_argument("--target-cli-version")
    cp.add_argument("--target-model-provider")
    cp.add_argument("--target-model")

    un = sub.add_parser("undo", help="put files back as edits left them, newest edit first (a revert)")
    un.add_argument("--spec", required=True, help="a JSON file: [{path, change, diff}]")
    un.add_argument("--cwd", required=True)

    a = ap.parse_args(argv)
    try:
        if a.command == "formats":
            out: Dict[str, Any] = {"ok": True, "interchange_version": INTERCHANGE_VERSION, "formats": describe_formats()}
        elif a.command == "copy":
            source = StoreRef(a.harness, Path(a.source_home), Path(a.source_cwd or a.cwd),
                              pointer=Path(a.source_pointer) if a.source_pointer else None, session_id=a.source_session_id)
            target = StoreRef(a.harness, Path(a.target_home), Path(a.cwd),
                              pointer=Path(a.target_pointer) if a.target_pointer else None, session_id=a.target_session_id)
            identity = TargetIdentity(cli_version=a.target_cli_version, model_provider=a.target_model_provider, model=a.target_model)
            out = copy_thread(source, target, identity, before=a.before, turns=a.turns).as_dict()
        elif a.command == "undo":
            out = {"ok": True, "files": undo_edits(json.loads(Path(a.spec).read_text()), Path(a.cwd))}
        elif a.command == "inspect":
            out = {"ok": True, **inspect_store(StoreRef(a.harness, Path(a.home), Path(a.cwd),
                                                        pointer=Path(a.pointer) if a.pointer else None, session_id=a.session_id))}
        else:
            source = StoreRef(a.source_harness, Path(a.source_home), Path(a.source_cwd or a.cwd),
                              pointer=Path(a.source_pointer) if a.source_pointer else None, session_id=a.source_session_id)
            target = StoreRef(a.target_harness, Path(a.target_home), Path(a.cwd),
                              pointer=Path(a.target_pointer) if a.target_pointer else None, session_id=a.target_session_id)
            identity = TargetIdentity(cli_version=a.target_cli_version, model_provider=a.target_model_provider, model=a.target_model)
            out = move_thread(source, target, identity).as_dict()
    except InterchangeError as e:
        out = {"ok": False, "reason": e.reason, "detail": e.detail}
    except Exception:
        out = {"ok": False, "reason": "translator_crashed", "detail": traceback.format_exc()[-1500:]}
    sys.stdout.write(json.dumps(out) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
