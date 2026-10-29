"""One write path for a workflow's graph (docs/engineering/sdk-handles-and-deploy.md §1–§4).

``apply`` takes typed ops (``graph_edits``) and, in one transaction: locks the
workflow, refuses a stale ``if_version`` with the version and graph as they
stand, applies the ops in order (a batch lands whole or not at all), writes
the graph (the ``workflows_graph_version_bump`` trigger moves its version) and
records a version. After the commit it reconciles what the change sets in
motion outside the graph (``utils.workflow_reconcile``) and tells whoever
watches: the owner's open pages (the ``WORKFLOW_GRAPH_CHANGED`` capability) and
every canvas open on the workflow (its room on the relay, a
``workflow:graph_changed`` event). ``restore`` writes a version's graph back
the same way.

Versions (``workflow_versions``) are keyed by the ``graph_version`` a write
produced. Writes by one author from one source within ``JOIN_S`` of the last
are one version (a canvas session is one, not five hundred); a restore never
joins another. A write that only moved things (layout) is no version, nor is
one that changed only the workflow's name, description or settings, which
aren't in the graph. A workflow's first version is the graph it had before
(``baseline``), so its first change can be undone. The canvas's whole-graph
save records its versions through ``record_version`` too.

Reads (``read``, ``versions``, ``version``) never carry a secret: a setting a
step's schema or name marks as one is withheld (``withheld`` names them), and
connections are by reference (``credentialIds``).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Literal, Optional, Sequence

from utils.graph_nodes import graph_nodes, node_config, node_operation, node_type, parse_graph

logger = logging.getLogger(__name__)

Source = Literal["canvas", "api", "builder", "mcp", "coordinator", "deploy", "restore"]
JOIN_S = 300
# What a run leaves on a node's config, never what the node is.
RUN_STATE_FIELDS = frozenset({"output", "outputTimestamp", "executionState", "error", "configValid"})
GRAPH_CHANGED_EVENT = "workflow:graph_changed"


@dataclass(frozen=True)
class Author:
    """Who writes: the user access is judged for, and the API key or grant that acted for them."""

    user_id: str
    key_id: Optional[str] = None


class GraphError(Exception):
    """Why a read or write was refused: ``kind`` is ``not_found``, ``forbidden``, ``stale`` (``version`` and
    ``graph`` are the workflow's as they stand) or ``invalid`` (``op`` is the refused op's index)."""

    def __init__(self, kind: str, message: str, **details: Any):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.details = details


@dataclass
class Edited:
    """What a write did: the workflow's ``version`` after it, whether its graph ``changed`` and the version row
    it landed in (``recorded``, None for a layout-only write or none), each op's ``results``, each touched step's
    verdict (``steps``), and the after-commit work (``settled``: the reconcile and the notices)."""

    workflow_id: str
    version: int
    changed: bool
    recorded: Optional[int]
    summary: str
    results: List[Dict[str, Any]] = field(default_factory=list)
    steps: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    graph: Optional[Dict[str, Any]] = None
    settled: Optional[asyncio.Task] = None


# ── what a reader sees ──────────────────────────────────────────────────────

@lru_cache(maxsize=1024)
def settings_properties(kind: str, operation: Optional[str]) -> Optional[Dict[str, Any]]:
    """The properties of a step's settings, by name; None when its schema isn't known."""
    from pydantic import TypeAdapter

    from .operation_catalog import get_operation_config_class

    found = get_operation_config_class(kind, operation or "default")
    if found is None:
        return None
    try:
        return TypeAdapter(found).json_schema().get("properties") or {}
    except Exception:  # a schema the adapter can't render: judge secrets by name alone
        return None


def is_secret_field(name: str, prop: Optional[Dict[str, Any]]) -> bool:
    """A setting no read shows: its name or its schema marks it as a secret."""
    from nodes.core.credential_fields import looks_like_secret_field

    prop = prop or {}
    return (looks_like_secret_field(name) or prop.get("writeOnly") is True or prop.get("format") == "password"
            or prop.get("ui:widget") == "password")


def public_graph(graph: Any) -> Dict[str, Any]:
    """A stored graph as a reader sees it: no runtime keys, no run state, no secret (``withheld``: the settings
    left out, by step id)."""
    from utils.runtime_keys import graph_without_runtime_keys

    shown = graph_without_runtime_keys(parse_graph(graph))
    withheld: Dict[str, List[str]] = {}
    nodes = []
    for node in graph_nodes(shown):
        props = settings_properties(node_type(node), node_operation(node)) or {}
        hidden = sorted(k for k in node_config(node) if k in RUN_STATE_FIELDS
                        or (k != "credentialIds" and is_secret_field(k, props.get(k))))
        secrets = [k for k in hidden if k not in RUN_STATE_FIELDS]
        if secrets:
            withheld[str(node.get("id"))] = secrets
        if hidden:
            node = dict(node)
            if isinstance(node.get("config"), dict):
                node["config"] = {k: v for k, v in node["config"].items() if k not in hidden}
            if isinstance(node.get("data"), dict) and isinstance(node["data"].get("config"), dict):
                node["data"] = {**node["data"], "config": {k: v for k, v in node["data"]["config"].items()
                                                           if k not in hidden}}
        nodes.append(node)
    return {**shown, "nodes": nodes, "withheld": withheld}


def _version_view(workflow_id: str, row: Dict[str, Any], *, with_graph: bool = False) -> Dict[str, Any]:
    from .graph_edits import summary

    changes = list(row["changes"] or [])
    view = {
        "object": "workflow_version", "workflow_id": str(workflow_id), "version": row["version"],
        "source": row["source"],
        "author": ({"user_id": str(row["author_user_id"]), "key_id": row["author_key_id"]}
                   if row["author_user_id"] else None),
        "summary": summary(changes) if row["source"] != "baseline" else "As it was before its history began.",
        "changes": changes, "restored_from": row["restored_from"],
        "created_at": row["created_at"].isoformat(), "updated_at": row["updated_at"].isoformat(),
    }
    if with_graph:
        view["graph"] = public_graph(row["graph"])
    return view


# ── access ──────────────────────────────────────────────────────────────────

async def _access(conn, author: Author, workflow_id: str, *, edit: bool):
    from utils.access_control import Permission, check_resource_access

    access = await check_resource_access(conn, author.user_id, "workflow", workflow_id)
    if not access.has_access:
        raise GraphError("not_found", f"No workflow '{workflow_id}' this account can open.")
    if edit and access.permission not in (Permission.EDIT, Permission.OWNER):
        raise GraphError("forbidden", access.edit_refusal("This account can read this workflow but not edit it."))
    return access


def _uuid(workflow_id: str) -> str:
    try:
        return str(uuid.UUID(str(workflow_id)))
    except (TypeError, ValueError):
        raise GraphError("not_found", f"No workflow '{workflow_id}' this account can open.") from None


# ── reads ───────────────────────────────────────────────────────────────────

async def read(pool, author: Author, workflow_id: str) -> Dict[str, Any]:
    """The workflow's graph as stored (no secret), with its version and own fields."""
    from repositories.workflow import WorkflowRepo
    from utils.system_workflows import client_settings

    workflow_id = _uuid(workflow_id)
    async with pool.acquire() as conn:
        await _access(conn, author, workflow_id, edit=False)
        row = await WorkflowRepo(pool).read_graph(conn, workflow_id)
    if row is None:
        raise GraphError("not_found", f"No workflow '{workflow_id}' this account can open.")
    return {"object": "workflow_graph", "workflow_id": workflow_id, "version": row["graph_version"],
            "name": row["name"], "description": row["description"] or None,
            "settings": client_settings(row["settings"]), "graph": public_graph(row["workflow"])}


async def versions(pool, author: Author, workflow_id: str, *, limit: int,
                   before: Optional[int] = None) -> Dict[str, Any]:
    """Its versions, newest first (``before``: those older than a version)."""
    from repositories import workflow_versions

    workflow_id = _uuid(workflow_id)
    async with pool.acquire() as conn:
        await _access(conn, author, workflow_id, edit=False)
        rows = await workflow_versions.page(conn, workflow_id, limit=limit, before=before)
    page = rows[:limit]
    return {"object": "list", "data": [_version_view(workflow_id, r) for r in page],
            "next_cursor": str(page[-1]["version"]) if len(rows) > limit else None}


async def version(pool, author: Author, workflow_id: str, number: int) -> Dict[str, Any]:
    from repositories import workflow_versions

    workflow_id = _uuid(workflow_id)
    async with pool.acquire() as conn:
        await _access(conn, author, workflow_id, edit=False)
        row = await workflow_versions.get(conn, workflow_id, number)
    if row is None:
        raise GraphError("not_found", f"This workflow has no version {number}.")
    return _version_view(workflow_id, row, with_graph=True)


# ── writes ──────────────────────────────────────────────────────────────────

async def record_version(conn, workflow_id: str, *, author: Optional[Author], source: str, before_version: int,
                         before_graph: Any, version: int, graph: Any, changes: Sequence[str],
                         restored_from: Optional[int] = None) -> int:
    """Record a write as a version, inside the transaction that wrote it: it joins the newest version when that
    is the same author's, from the same source, written within ``JOIN_S`` (never a restore); the first write of
    a workflow with no history records the graph it had before as a ``baseline`` first. Returns the version it
    landed in."""
    from repositories import workflow_versions

    from .graph_edits import merge_changes

    newest = await workflow_versions.newest(conn, workflow_id)
    if newest is None and graph_nodes(before_graph):
        await workflow_versions.insert(conn, workflow_id=workflow_id, version=before_version, graph=before_graph,
                                       source="baseline", author_user_id=None, author_key_id=None, changes=[])
    user_id, key_id = (author.user_id, author.key_id) if author else (None, None)
    if (newest is not None and source != "restore" and newest["source"] == source
            and str(newest["author_user_id"] or "") == str(user_id or "") and newest["author_key_id"] == key_id
            and newest["age"].total_seconds() < JOIN_S):
        await workflow_versions.join(conn, workflow_id=workflow_id, version=version, into=newest["version"],
                                     graph=graph, changes=merge_changes(newest["changes"] or [], changes))
    else:
        await workflow_versions.insert(conn, workflow_id=workflow_id, version=version, graph=graph, source=source,
                                       author_user_id=user_id, author_key_id=key_id, changes=list(changes),
                                       restored_from=restored_from)
    return version


async def record_save(conn, workflow_id: str, author: Author, *, source: Source, before: Any, graph: Any,
                      version: int) -> Optional[int]:
    """A whole-graph save (the canvas's) as a version, inside its transaction: what it changed, or no version for
    a save that changed nothing but where things sit. The save moved the graph one version on."""
    from .graph_edits import describe_changes

    before, graph = parse_graph(before), parse_graph(graph)
    changes = describe_changes(before, graph)
    if not changes:
        return None
    return await record_version(conn, str(workflow_id), author=author, source=source, before_version=version - 1,
                                before_graph=before, version=version, graph=graph, changes=changes)


async def _locked(conn, repo, author: Author, workflow_id: str, if_version: Optional[int]):
    """(access, the workflow's row locked for the transaction), once the author may edit it and it's still at
    ``if_version`` when one is given."""
    access = await _access(conn, author, workflow_id, edit=True)
    row = await repo.read_graph(conn, workflow_id, lock=True)
    if row is None:
        raise GraphError("not_found", f"No workflow '{workflow_id}' this account can open.")
    if if_version is not None and if_version != row["graph_version"]:
        raise GraphError("stale", f"The workflow is at version {row['graph_version']}, not {if_version}: "
                                  "it changed since it was read.",
                         version=row["graph_version"], graph=public_graph(row["workflow"]))
    return access, row


async def apply(pool, author: Author, workflow_id: str, ops: Sequence[Any], *, if_version: Optional[int] = None,
                source: Source = "api", include_graph: bool = False) -> Edited:
    """Apply ``ops`` to the workflow's graph in one transaction, then reconcile and notify (``Edited.settled``)."""
    from repositories.workflow import WorkflowRepo
    from utils.access_control import Permission
    from utils.credentials import authorize_credentials_for_workflow, resolve_accessible_credential_types
    from utils.runtime_keys import graph_without_runtime_keys

    from .graph_edits import (
        EditContext, EditRefused, SetConnection, apply_ops, describe_changes, parse_ops, summary,
    )
    from .workflow_ops import read_model_catalog

    workflow_id = _uuid(workflow_id)
    try:
        typed = parse_ops(ops)
    except EditRefused as e:
        raise GraphError("invalid", e.message, op=e.index, field=e.field) from None
    wanted = [o.connection for o in typed if isinstance(o, SetConnection) and o.connection]
    usable = await resolve_accessible_credential_types(wanted, author.user_id, pool=pool) if wanted else {}
    repo = WorkflowRepo(pool)
    async with pool.acquire() as conn:
        stored = await repo.read_graph(conn, workflow_id)
    await read_model_catalog(graph_nodes(stored["workflow"] if stored else None), [
        (getattr(o, "settings", None) or {}).get(f) for o in typed for f in ("model", "opencode_model")])

    async with pool.acquire() as conn, conn.transaction():
        access, row = await _locked(conn, repo, author, workflow_id, if_version)
        is_owner = access.permission == Permission.OWNER
        try:
            editor = await apply_ops(row["workflow"], typed, name=row["name"], settings=row["settings"],
                                     context=EditContext(workflow_id, author.user_id, is_owner,
                                                         credential_types=usable, conn=conn))
        except EditRefused as e:
            raise GraphError("invalid", e.message, op=e.index, field=e.field) from None
        before = parse_graph(row["workflow"])
        after = graph_without_runtime_keys(editor.graph)
        changed = after != before
        named = editor.name is not None and editor.name != row["name"]
        wrote = changed or named or editor.description is not None or bool(editor.settings)
        version = row["graph_version"]
        if wrote:
            version = await repo.write_graph(conn, workflow_id, after, name=editor.name if named else None,
                                             description=editor.description, settings=editor.settings or None)
        if editor.connections and is_owner:
            await authorize_credentials_for_workflow(conn, workflow_id, author.user_id, editor.connections)
        changes = describe_changes(before, after) if changed else []
        recorded = None
        if changes:
            recorded = await record_version(conn, workflow_id, author=author, source=source,
                                            before_version=row["graph_version"], before_graph=before,
                                            version=version, graph=after, changes=changes)
    edited = Edited(workflow_id, version, changed, recorded, summary(changes), editor.results, editor.steps,
                    graph=public_graph(after) if include_graph else None)
    if wrote:
        edited.settled = _after_write(pool, row["owner_id"], workflow_id, author.user_id, before, after, version,
                                      reconcile=bool(changes))
    return edited


async def restore(pool, author: Author, workflow_id: str, number: int, *,
                  if_version: Optional[int] = None) -> Edited:
    """Write version ``number``'s graph back as a new version (``restore``), itself undoable."""
    from repositories import workflow_versions
    from repositories.workflow import WorkflowRepo
    from utils.runtime_keys import graph_without_runtime_keys

    from .graph_edits import describe_changes, summary

    workflow_id = _uuid(workflow_id)
    repo = WorkflowRepo(pool)
    async with pool.acquire() as conn, conn.transaction():
        _, row = await _locked(conn, repo, author, workflow_id, if_version)
        target = await workflow_versions.get(conn, workflow_id, number)
        if target is None:
            raise GraphError("not_found", f"This workflow has no version {number}.")
        before, after = parse_graph(row["workflow"]), graph_without_runtime_keys(parse_graph(target["graph"]))
        if after == before:
            return Edited(workflow_id, row["graph_version"], False, None, "")
        version = await repo.write_graph(conn, workflow_id, after)
        changes = [f"restored version {number}"]
        await record_version(conn, workflow_id, author=author, source="restore",
                             before_version=row["graph_version"], before_graph=before, version=version,
                             graph=after, changes=changes, restored_from=number)
    edited = Edited(workflow_id, version, True, version, summary(changes))
    edited.settled = _after_write(pool, row["owner_id"], workflow_id, author.user_id, before, after, version,
                                  reconcile=bool(describe_changes(before, after)))
    return edited


# ── after the commit ────────────────────────────────────────────────────────

def _after_write(pool, owner_id, workflow_id: str, user_id: str, before: Any, after: Any, version: int, *,
                 reconcile: bool) -> asyncio.Task:
    from utils.async_helpers import spawn

    return spawn(_settle(pool, str(owner_id), workflow_id, user_id, before, after, version, reconcile=reconcile),
                 name=f"workflow-graph-settle:{workflow_id}")


async def _settle(pool, owner_id: str, workflow_id: str, user_id: str, before: Any, after: Any, version: int, *,
                  reconcile: bool) -> None:
    """Tell whoever watches, then reconcile the change; tell them again when the reconcile wrote its own mirrors
    into the graph (a trigger's webhook fields), so they read the version that has them."""
    from repositories.workflow import WorkflowRepo
    from utils.workflow_reconcile import reconcile_graph_change

    await tell(owner_id, workflow_id, version)
    if not reconcile:
        return
    await reconcile_graph_change(pool, workflow_id, user_id, before, after)
    async with pool.acquire() as conn:
        now = await WorkflowRepo(pool).graph_version(conn, workflow_id)
    if now is not None and now != version:
        await tell(owner_id, workflow_id, now)


async def tell(owner_id: str, workflow_id: str, version: int) -> None:
    """The workflow is at ``version`` now: its owner's open pages read it again, and so does every canvas open on
    it (its room on the relay). Best effort, as the relay is."""
    from utils.capabilities import WORKFLOW_GRAPH_CHANGED, capability
    from utils.execution_relay import create_execution_relay

    told = capability(WORKFLOW_GRAPH_CHANGED)
    if told is not None:
        try:
            await told(owner_id, workflow_id, version)
        except Exception:
            logger.warning("[graph] telling %s's pages about %s failed", owner_id, workflow_id, exc_info=True)
    relay = create_execution_relay(workflow_id, f"graph-{uuid.uuid4()}", owner_id)
    try:
        relay.start()
        await relay.send_event({"type": GRAPH_CHANGED_EVENT, "workflow_id": workflow_id, "version": version})
    except Exception:
        logger.warning("[graph] notice to the canvases of %s failed", workflow_id, exc_info=True)
    finally:
        await relay.close()
