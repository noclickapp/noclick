"""One write path for a workflow's definition (docs/engineering/sdk-handles-and-deploy.md §1–§4).

``apply`` takes typed ops (``graph_edits``) and, in one transaction: locks the
workflow, refuses a stale ``if_version`` with the version and graph as they
stand, applies the ops in order (a batch lands whole or not at all), writes the
graph and the workflow's own fields and records a version. The version moves
with the graph (the ``workflows_graph_version_bump`` trigger) and with a change
to the workflow's name, description or settings. After the commit it reconciles
what the change sets in motion outside the graph (``utils.workflow_reconcile``),
whose own writes (a trigger's webhook fields) move the version on: the version
handed back is the one they left, so a caller edits on from it. Then it tells
whoever watches, once: the owner's open pages (the ``WORKFLOW_GRAPH_CHANGED``
capability) and every canvas open on the workflow (its room on the relay, a
``workflow:graph_changed`` event). ``restore`` writes a version back the same
way.

A version (``workflow_versions``) holds the definition whole: the graph, the
name, the description and the settings a client may write (never NoClick's own,
``utils.system_workflows``), so a restore puts all of it back. It's keyed by
the ``graph_version`` its write produced. Writes by one author from one source
within ``JOIN_S`` of the last are one version (a canvas session is one, not five
hundred); a restore never joins another. A write that only moved things
(layout) is no version. A workflow's first version is what it was before
(``baseline``), so its first change can be undone. The canvas's save records
through ``record_save``: a graph save as any write; a change to only the
workflow's own fields moves no version (the canvas's next save mustn't conflict
with its own rename), so it joins the author's own canvas version or is carried
by the next one.

Reads (``read``, ``versions``, ``version``) never carry a secret
(``graph_secrets``): a setting its schema or name marks as one, at any depth,
and a header or row named like one, is withheld (``withheld`` names each by
step and path); connections are by reference (``credentialIds``). A write that
sends settings back without a withheld value keeps it.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from utils.graph_nodes import graph_edges, graph_nodes, node_config, node_operation, node_type, parse_graph

logger = logging.getLogger(__name__)

Source = Literal["canvas", "api", "builder", "mcp", "coordinator", "deploy", "restore"]
JOIN_S = 300
# What a run leaves on a node, never what the node is.
RUN_STATE_FIELDS = frozenset({"output", "outputTimestamp", "executionState", "error", "configValid"})
GRAPH_CHANGED_EVENT = "workflow:graph_changed"
_FIELDS = ("name", "description", "settings")


@dataclass(frozen=True)
class Author:
    """Who writes: the user access is judged for, the API key or grant that acted for them, and whether that
    acts for the whole account (``whole_account``: else, as a user's key, an app's code or an agent's own tools,
    it adds no connection the workflow doesn't already hold, so nobody reaches another user's accounts)."""

    user_id: str
    key_id: Optional[str] = None
    whole_account: bool = True


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
    """What a write did: the workflow's ``version`` (its CAS token, what ``if_version`` names) once it and its
    reconcile were written, whether its definition ``changed``, the version of its history it landed in
    (``history_version``, which reads and restores name it by; None for a layout-only write or none), each op's
    ``results`` and each touched step's verdict (``steps``); ``definition``: the workflow as ``read`` shows it,
    when asked for."""

    workflow_id: str
    version: int
    changed: bool
    history_version: Optional[int]
    summary: str
    results: List[Dict[str, Any]] = field(default_factory=list)
    steps: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    definition: Optional[Dict[str, Any]] = None


def definition(graph: Any, name: Optional[str], description: Optional[str], settings: Any) -> Dict[str, Any]:
    """A workflow's definition as a version keeps it: its graph (no runtime key), name, description and the
    settings a client may write."""
    from utils.runtime_keys import graph_without_runtime_keys
    from utils.system_workflows import client_settings

    if isinstance(settings, str):
        settings = json.loads(settings)
    return {"graph": graph_without_runtime_keys(parse_graph(graph)), "name": name or "",
            "description": description or "", "settings": client_settings(settings)}


def _of(row: Dict[str, Any]) -> Dict[str, Any]:
    return definition(row["workflow"], row["name"], row["description"], row["settings"])


def _fields(state: Dict[str, Any]) -> tuple:
    return tuple(state[f] for f in _FIELDS)


# ── what a reader sees ──────────────────────────────────────────────────────

def _shown(config: Any, kind: str, operation: Optional[str]) -> tuple:
    from .graph_secrets import withhold

    if not isinstance(config, dict):
        return config, []
    return withhold({k: v for k, v in config.items() if k not in RUN_STATE_FIELDS}, kind, operation)


def public_graph(graph: Any) -> Dict[str, Any]:
    """A stored graph as a reader sees it: no runtime keys, no run state, no secret (``withheld``: the paths left
    out, by step id)."""
    from utils.runtime_keys import graph_without_runtime_keys

    shown = graph_without_runtime_keys(parse_graph(graph))
    withheld: Dict[str, List[str]] = {}
    nodes = []
    for node in graph_nodes(shown):
        kind, operation = node_type(node), node_operation(node)
        node, paths = dict(node), set()
        if isinstance(node.get("config"), dict):
            node["config"], hidden = _shown(node["config"], kind, operation)
            paths.update(hidden)
        if isinstance(node.get("data"), dict):
            data = {k: v for k, v in node["data"].items() if k not in RUN_STATE_FIELDS}
            if isinstance(data.get("config"), dict):
                data["config"], hidden = _shown(data["config"], kind, operation)
                paths.update(hidden)
            node["data"] = data
        if paths:
            withheld[str(node.get("id"))] = sorted(paths)
        nodes.append(node)
    view = {**shown, "nodes": nodes, "withheld": withheld}
    # The graph's own variables' values, which fields bound to ``{{vars.x}}`` take: withheld, named.
    variables = view.pop("variables", None)
    if isinstance(variables, dict) and variables:
        view["variables_withheld"] = sorted(variables)
    return view


def public_settings(settings: Any) -> tuple:
    """A workflow's settings as a reader sees them, and the paths of the secrets left out."""
    from .graph_secrets import withhold

    return withhold(definition(None, None, None, settings)["settings"], None, None)


def _definition_view(state: Dict[str, Any]) -> Dict[str, Any]:
    settings, hidden = public_settings(state["settings"])
    return {"name": state["name"], "description": state["description"] or None, "settings": settings,
            "settings_withheld": hidden, "graph": public_graph(state["graph"])}


def _version_view(workflow_id: str, row: Dict[str, Any], *,
                  whole: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A version as a reader sees it, with ``whole``: its definition (``definition``)."""
    from .graph_edits import summary

    changes = list(row["changes"] or [])
    view = {
        "object": "workflow_version", "workflow_id": str(workflow_id), "history_version": row["history_version"],
        "version": row["version"], "source": row["source"],
        "author": ({"user_id": str(row["author_user_id"]), "key_id": row["author_key_id"]}
                   if row["author_user_id"] else None),
        "summary": summary(changes) if row["source"] != "baseline" else "As it was before its history began.",
        "changes": changes, "restored_from": row["restored_from"],
        "created_at": row["created_at"].isoformat(), "updated_at": row["updated_at"].isoformat(),
    }
    if whole is not None:
        view.update(_definition_view(whole))
    return view


def _state_of(version_row: Dict[str, Any], workflow_row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A version's definition: its own once closed; the workflow's as it stands while it's open (the newest)."""
    if version_row["graph"] is not None:
        return definition(version_row["graph"], version_row["name"], version_row["description"],
                          version_row["settings"])
    return _of(workflow_row) if workflow_row is not None else None


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
    """The workflow's definition as stored (no secret), with its version."""
    from repositories.workflow import WorkflowRepo

    workflow_id = _uuid(workflow_id)
    async with pool.acquire() as conn:
        await _access(conn, author, workflow_id, edit=False)
        row = await WorkflowRepo(pool).read_graph(conn, workflow_id)
    if row is None:
        raise GraphError("not_found", f"No workflow '{workflow_id}' this account can open.")
    return {"object": "workflow_graph", "workflow_id": workflow_id, "version": row["graph_version"],
            **_definition_view(_of(row))}


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
    from repositories.workflow import WorkflowRepo

    workflow_id = _uuid(workflow_id)
    async with pool.acquire() as conn:
        await _access(conn, author, workflow_id, edit=False)
        row = await workflow_versions.get(conn, workflow_id, number)
        current = await WorkflowRepo(pool).read_graph(conn, workflow_id) if row and row["graph"] is None else None
    state = _state_of(row, current) if row is not None else None
    if state is None:
        raise GraphError("not_found", f"This workflow has no version {number}.")
    return _version_view(workflow_id, row, whole=state)


# ── writes ──────────────────────────────────────────────────────────────────

def describe(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    """What a write changed of a definition, one line each (none for a write that only moved things)."""
    from .graph_edits import describe_changes, describe_fields

    return describe_changes(before["graph"], after["graph"]) + describe_fields(before, after)


async def _joinable(conn, workflow_id: str, author: Optional[Author], source: str) -> Optional[Dict[str, Any]]:
    """The version a write by ``author`` from ``source`` joins: their newest from that source, begun less than
    ``JOIN_S`` ago (another author's versions in between or not); never for a restore."""
    from repositories import workflow_versions

    if source == "restore":
        return None
    user_id, key_id = (author.user_id, author.key_id) if author else (None, None)
    theirs = await workflow_versions.newest_by(conn, workflow_id, source=source, author_user_id=user_id,
                                               author_key_id=key_id)
    return theirs if theirs is not None and theirs["age"].total_seconds() < JOIN_S else None


async def record_version(conn, workflow_id: str, *, author: Optional[Author], source: str, before_version: int,
                         before: Dict[str, Any], version: int, after: Dict[str, Any], changes: Sequence[str],
                         restored_from: Optional[int] = None) -> int:
    """Record a write of definition ``after`` (``definition``) as a version, inside the transaction that wrote it:
    it joins the version ``_joinable`` names, else starts one. Either is open, the newest: the version open before
    it is closed with ``before``, unless it's the one joined. The first write of a workflow with no history records
    what it was before as a ``baseline`` first. Returns the ``history_version`` it landed in."""
    from repositories import workflow_versions

    from .graph_edits import merge_changes

    joined = await _joinable(conn, workflow_id, author, source)
    newest = await workflow_versions.newest(conn, workflow_id)
    if newest is None:
        await workflow_versions.insert(conn, workflow_id=workflow_id, version=before_version, state=before,
                                       source="baseline", author_user_id=None, author_key_id=None, changes=[])
    elif joined is None or joined["history_version"] != newest["history_version"]:
        await workflow_versions.close(conn, workflow_id, before)
    if joined is not None:
        await workflow_versions.join(conn, workflow_id=workflow_id, history_version=joined["history_version"],
                                     version=version, changes=merge_changes(joined["changes"] or [], changes))
        return joined["history_version"]
    user_id, key_id = (author.user_id, author.key_id) if author else (None, None)
    return await workflow_versions.insert(conn, workflow_id=workflow_id, version=version, source=source,
                                          author_user_id=user_id, author_key_id=key_id, changes=list(changes),
                                          restored_from=restored_from)


async def record_save(conn, workflow_id: str, author: Author, *, source: Source, before: Dict[str, Any],
                      after: Dict[str, Any], version: int) -> Optional[int]:
    """A whole-definition save (the canvas's ``workflow:update``) as a version, inside its transaction: what it
    changed, or no version for a save that changed nothing but where things sit. A save of the graph moved it one
    version on; a save of only the workflow's own fields moved none, so it joins the author's own version from the
    same source at ``version`` and is otherwise carried by the next version recorded."""
    from repositories import workflow_versions

    from .graph_edits import merge_changes

    workflow_id = str(workflow_id)
    changes = describe(before, after)
    if not changes:
        return None
    if after["graph"] != before["graph"]:
        return await record_version(conn, workflow_id, author=author, source=source, before_version=version - 1,
                                    before=before, version=version, after=after, changes=changes)
    joined = await _joinable(conn, workflow_id, author, source)
    if joined is None or joined["version"] != version:
        return None
    await workflow_versions.join(conn, workflow_id=workflow_id, history_version=joined["history_version"],
                                 version=version, changes=merge_changes(joined["changes"] or [], changes))
    return joined["history_version"]


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


async def _write(conn, repo, workflow_id: str, row: Dict[str, Any], before: Dict[str, Any],
                 after: Dict[str, Any], *, settings: Optional[Dict[str, Any]], replace_settings: bool = False) -> int:
    """Write ``after`` over the locked ``row``; its version moves once, with the graph or else with the fields."""
    graph_moved = after["graph"] != before["graph"]
    return await repo.write_graph(
        conn, workflow_id, after["graph"],
        name=after["name"] if after["name"] != before["name"] else None,
        description=after["description"] if after["description"] != before["description"] else None,
        settings=settings, replace_settings=replace_settings,
        bump=not graph_moved and _fields(after) != _fields(before))


async def apply(pool, author: Author, workflow_id: str, ops: Sequence[Any], *, if_version: Optional[int] = None,
                source: Source = "api", include_graph: bool = False) -> Edited:
    """Apply ``ops`` to the workflow in one transaction, then reconcile and tell whoever watches."""
    from repositories.workflow import WorkflowRepo
    from utils.access_control import Permission
    from utils.credentials import authorize_credentials_for_workflow, resolve_accessible_credential_types

    from .graph_edits import EditContext, EditRefused, SetConnection, apply_ops, describe_changes, parse_ops, summary
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
    if not author.whole_account:
        _adds_no_connection(typed, stored["workflow"] if stored else None)
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
        before = _of(row)
        stored_settings = row["settings"] if isinstance(row["settings"], dict) else {}
        after = definition(editor.graph, editor.name if editor.name is not None else row["name"],
                           editor.description if editor.description is not None else row["description"],
                           {**stored_settings, **editor.settings})
        wrote = after != before
        version = row["graph_version"]
        if wrote:
            version = await _write(conn, repo, workflow_id, row, before, after, settings=editor.settings or None)
        if editor.connections and is_owner:
            await authorize_credentials_for_workflow(conn, workflow_id, author.user_id, editor.connections)
        changes = describe(before, after)
        recorded = None
        if changes:
            recorded = await record_version(conn, workflow_id, author=author, source=source,
                                            before_version=row["graph_version"], before=before, version=version,
                                            after=after, changes=changes)
    now = after
    if wrote:
        version, now = await _settle(pool, row["owner_id"], workflow_id, author, before, after, version,
                                     reconcile=bool(describe_changes(before["graph"], after["graph"])))
    return Edited(workflow_id, version, wrote, recorded, summary(changes), editor.results, editor.steps,
                  definition=_definition_view(now) if include_graph else None)


def _adds_no_connection(typed: Sequence[Any], graph: Any) -> None:
    """Refuse a connection the workflow doesn't already hold, for a caller that doesn't act for the whole
    account (``Author.whole_account``)."""
    from utils.credentials import extract_credential_ids

    from .graph_edits import SetConnection

    held = {str(c) for n in graph_nodes(graph) for c in extract_credential_ids(node_config(n)).values() if c}
    for index, op in enumerate(typed):
        if isinstance(op, SetConnection) and op.connection and str(op.connection) not in held:
            raise GraphError("invalid", "Only a key acting for your whole account gives a step a connection this "
                                        "workflow doesn't already use.", op=index, field="connection")


async def _claim_inboxes(conn, author: Author, workflow_id: str, before: Dict[str, Any],
                         after: Dict[str, Any]) -> None:
    """An inbox a restore brings back comes with its address: claimed again in the restore's transaction (its
    config takes the address as claimed), or the restore is refused when another step holds it now."""
    from utils.email_reservation_manager import EmailReservationManager, get_inbound_email_domain

    had = {n.get("id") for n in graph_nodes(before["graph"])}
    for node in graph_nodes(after["graph"]):
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        config = node.get("config") if isinstance(node.get("config"), dict) else data.get("config")
        if not isinstance(config, dict):
            continue
        if node.get("type") != "trigger-email" or node.get("id") in had or not config.get("local_part"):
            continue
        if get_inbound_email_domain() is None:
            return
        try:
            config.update(await EmailReservationManager.reserve_from_config(
                None, author.user_id, workflow_id, node["id"], config, conn=conn))
        except ValueError as e:
            raise GraphError("invalid", f"The inbox '{config['local_part']}' it brings back can't be claimed: {e}. "
                                        "Restore another version, or free that address first.") from None


async def restore(pool, author: Author, workflow_id: str, number: int, *,
                  if_version: Optional[int] = None) -> Edited:
    """Write the version ``number`` (a ``history_version``) back whole: its graph, name, description and settings
    (NoClick's own settings stay as they are), an inbox it brings back claimed again; as a new version
    (``restore``), itself undoable."""
    from repositories import workflow_versions
    from repositories.workflow import WorkflowRepo
    from utils.system_workflows import client_settings

    from .graph_edits import describe_changes, summary

    workflow_id = _uuid(workflow_id)
    repo = WorkflowRepo(pool)
    async with pool.acquire() as conn, conn.transaction():
        _, row = await _locked(conn, repo, author, workflow_id, if_version)
        target = await workflow_versions.get(conn, workflow_id, number)
        if target is None:
            raise GraphError("not_found", f"This workflow has no version {number}.")
        before = _of(row)
        after = _state_of(target, row)
        if after == before:
            return Edited(workflow_id, row["graph_version"], False, None, "")
        await _claim_inboxes(conn, author, workflow_id, before, after)
        stored = row["settings"] if isinstance(row["settings"], dict) else {}
        own = {k: v for k, v in stored.items() if k not in client_settings(stored)}
        version = await _write(conn, repo, workflow_id, row, before, after, settings={**own, **after["settings"]},
                               replace_settings=True)
        changes = [f"restored version {number}"]
        recorded = await record_version(conn, workflow_id, author=author, source="restore",
                                        before_version=row["graph_version"], before=before, version=version,
                                        after=after, changes=changes, restored_from=number)
    version, _ = await _settle(pool, row["owner_id"], workflow_id, author, before, after, version,
                               reconcile=bool(describe_changes(before["graph"], after["graph"])))
    return Edited(workflow_id, version, True, recorded, summary(changes))


# ── after the commit ────────────────────────────────────────────────────────

async def _settle(pool, owner_id, workflow_id: str, author: Author, before: Dict[str, Any],
                  after: Dict[str, Any], version: int, *, reconcile: bool) -> Tuple[int, Dict[str, Any]]:
    """Reconcile what the write changed, then (spawned, off the answer's path) show the canvases open on it what
    changed (``canvas_events``) and tell whoever watches once, at the version the reconcile's own writes left (the
    write's own when it wrote none, or when another writer's came in between). Returns that version and the
    definition at it."""
    from repositories.workflow import WorkflowRepo
    from utils.async_helpers import spawn
    from utils.workflow_reconcile import reconcile_graph_change

    if reconcile:
        try:
            version = await reconcile_graph_change(pool, workflow_id, author.user_id, before["graph"],
                                                   after["graph"], version=version)
        except Exception:
            logger.error("[graph] reconciling %s after its write failed", workflow_id, exc_info=True)
    async with pool.acquire() as conn:
        row = await WorkflowRepo(pool).read_graph(conn, workflow_id)
    now = _of(row) if row is not None and row["graph_version"] == version else after
    spawn(_notify(str(owner_id), author.user_id, workflow_id, before, now, version),
          name=f"workflow-graph-notify:{workflow_id}")
    return version, now


async def _notify(owner_id: str, user_id: str, workflow_id: str, before: Dict[str, Any], after: Dict[str, Any],
                  version: int) -> None:
    """Off the answer's path, as best effort is: the canvases first, then the one notice."""
    await show_canvases({owner_id, user_id}, workflow_id, before, after)
    await tell(owner_id, workflow_id, version)


def canvas_events(before: Dict[str, Any], after: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """A write as the events an open canvas applies to its own copy (``useMCPBuilderEvents``, which the workflow
    MCP and the builder drive too): steps added, changed (each changed setting, a removed one as null), removed,
    edges added and removed, steps moved, settings changed. Applied, the canvas's next save carries the write
    rather than undoing it."""
    old = {n.get("id"): n for n in graph_nodes(before["graph"]) if n.get("id")}
    new = {n.get("id"): n for n in graph_nodes(after["graph"]) if n.get("id")}

    def edges(graph):
        found = {}
        for e in graph_edges(graph):
            source, target = e.get("source") or e.get("sourceId"), e.get("target") or e.get("targetId")
            found[e.get("id") or f"{source}-{target}"] = {**e, "source": source, "target": target}
        return found

    old_edges, new_edges = edges(before["graph"]), edges(after["graph"])
    events: List[Tuple[str, Dict[str, Any]]] = []
    for node_id in [i for i in old if i not in new]:
        events.append(("node_removed", {"nodeId": node_id, "removedEdgeIds": [
            k for k, e in old_edges.items() if node_id in (e["source"], e["target"])]}))
    for node_id, node in new.items():
        config, position = node_config(node), node.get("position") or {"x": 0, "y": 0}
        if node_id not in old:
            shown = {k: config[k] for k in ("label", "operation", "goal", "content", "color") if k in config}
            events.append(("node_start", {"node": {"id": node_id, "type": node.get("type"), "position": position,
                                                    **shown}}))
            events.append(("node_updated", {"nodeId": node_id, "type": node.get("type"), "position": position,
                                            "config": config}))
            continue
        prior = node_config(old[node_id])
        changed = {k: config.get(k) for k in set(prior) | set(config) if prior.get(k) != config.get(k)}
        if changed:
            events.append(("node_updated", {"nodeId": node_id, "config": changed}))
    gone = {i for i in old if i not in new}
    events += [("edge_removed", {"edgeId": k}) for k, e in old_edges.items()
               if k not in new_edges and not gone & {e["source"], e["target"]}]
    events += [("edge_added", {"edge": {"id": k, "source": e["source"], "target": e["target"],
                                        **{h: e[h] for h in ("sourceHandle", "targetHandle") if e.get(h)}}})
               for k, e in new_edges.items() if k not in old_edges]
    moved = {i: n.get("position") for i, n in new.items()
             if i in old and n.get("position") and n.get("position") != old[i].get("position")}
    if moved:
        events.append(("layout_applied", {"positions": moved}))
    if before["settings"] != after["settings"]:
        events.append(("settings_updated", {}))
    return events


async def show_canvases(users, workflow_id: str, before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """Send ``users``' open canvases of the workflow what a write changed (``canvas_events``). Best effort, as the
    relay is."""
    from utils.event_relay import broadcast_to_user_safe
    from wss.sender.events import MCPBuilderEvent

    for event_type, data in canvas_events(before, after):
        for user_id in users:
            try:
                await broadcast_to_user_safe(user_id, MCPBuilderEvent(workflow_id=workflow_id, event_type=event_type,
                                                                      data=data), workflow_id=workflow_id)
            except Exception:
                logger.warning("[graph] showing %s's canvases a change to %s failed", user_id, workflow_id,
                               exc_info=True)


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
