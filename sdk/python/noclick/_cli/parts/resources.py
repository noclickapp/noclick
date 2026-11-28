"""``noclick resources`` (``noclick ls``): what the account has, grouped by kind as the app's Resources page groups it,
each kind read from its own ``/v1`` list at once. A kind with nothing is left out; one that can't be read (a key
without that area's scope) says why after the rest, and the command exits 1 only when it could read no kind at all."""

from __future__ import annotations

import argparse
import asyncio
from typing import Any, Dict, List, Optional

from ..._client import default_client
from ..._scope import ALL_USERS
from ..._sync import run_sync
from ...exceptions import Error
from .. import exits, output as out, style
from ..screens import RESOURCE_KINDS

KINDS = [k["kind"] for k in RESOURCE_KINDS]
LIMIT = 100


def _field(item: Dict[str, Any], path: str) -> Any:
    value: Any = item
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def shown(value: Any, how: str) -> str:
    """A column's value as the table shows it."""
    if value is None or value == "":
        return "-"
    if how == "usd":
        return out.usd(float(value))
    if how == "bytes":
        return out.size(int(value))
    if how == "bool":
        return "yes" if value else "no"
    if how == "date":
        return str(value)[:10]
    return str(value)


async def _read(kinds: List[Dict[str, Any]], user: Optional[str]) -> Dict[str, Any]:
    client = default_client()

    async def one(kind: Dict[str, Any]) -> Any:
        query = {**kind.get("query", {}), "limit": LIMIT, **({} if user else {"user_id": ALL_USERS})}
        try:
            return await client.request("GET", kind["path"], params=query)
        except Error as err:
            return err

    async def spend() -> Any:
        try:
            return await client.request("GET", "/v1/usage", params={"group_by": "project"})
        except Error as err:
            return err

    wants_spend = any(c[1] == "$spend" for k in kinds for c in k["columns"])
    answers = await asyncio.gather(*(one(k) for k in kinds), *([spend()] if wants_spend else []))
    return {"lists": dict(zip((k["kind"] for k in kinds), answers)),
            "spend": answers[-1] if wants_spend else None}


def _exit(kinds: List[Dict[str, Any]], failed: Dict[str, Error]) -> int:
    """0 when it read any kind, whatever others it couldn't; 1 when it could read none."""
    return exits.FAILED if len(failed) == len(kinds) else exits.OK


def cmd_resources(args: argparse.Namespace) -> int:
    kinds = [k for k in RESOURCE_KINDS if not args.kind or k["kind"] in args.kind]
    read = run_sync(_read(kinds, getattr(args, "user", None)))
    spend = read["spend"]
    by_app = {g["id"]: g["usd"] for g in spend.get("groups", [])} if isinstance(spend, dict) else {}
    found: Dict[str, List[Dict[str, Any]]] = {}
    failed: Dict[str, Error] = {}
    for kind in kinds:
        answer = read["lists"][kind["kind"]]
        if isinstance(answer, Error):
            failed[kind["kind"]] = answer
        elif answer.get("data"):
            found[kind["kind"]] = answer["data"]
    if args.json:
        out.print_json({"kinds": found, "errors": {k: out.error_body(e) for k, e in failed.items()}})
        return _exit(kinds, failed)
    for kind in kinds:
        rows = found.get(kind["kind"])
        if not rows:
            continue
        if not style.OUT.on:
            print(f"{kind['title']} ({len(rows)})")
        out.table([c[0] for c in kind["columns"]],
                  [[shown(by_app.get(r.get("id")) if field == "$spend" else _field(r, field), how)
                    for _, field, how in kind["columns"]] for r in rows],
                  empty="", title=f"{kind['title']} ({len(rows)})")
        cursor = read["lists"][kind["kind"]].get("next_cursor")
        if cursor:
            out.note(f"The first {LIMIT}; the rest: noclick api GET {kind['path']} -q cursor={cursor}")
        print()
    for name, err in failed.items():
        out.note(f"{name}: unread ({err.message})")
    if not found and not failed:
        out.note("Nothing yet: no websites, machines, databases, buckets, repos, domains, numbers, inboxes, "
                 "sandboxes or volumes. Start one: noclick deploy")
    if isinstance(spend, Error) and "apps" in found:
        out.note(f"This month's spend is unread ({spend.message}).")
    return _exit(kinds, failed)


def register(kit: Any) -> None:
    listing = kit.command(kit.commands, "resources", cmd_resources,
                          "What your account has, by kind: websites, machines, databases, buckets, repos, domains, "
                          "numbers, inboxes, sandboxes and volumes, each with its cost where it has one.",
                          parents=[kit.as_json, kit.user])
    listing.add_argument("--kind", action="append", choices=KINDS, metavar="KIND",
                         help=f"Only this kind (repeat for more): {', '.join(KINDS)}.")
    listing.epilog = "noclick ls is the same command."
