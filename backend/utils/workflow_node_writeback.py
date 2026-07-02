"""
Runtime writebacks from the agent execution path to a workflow's saved node
config — plus the matching live broadcast so open canvases (the owner's
frontends) reflect the change without a reload.

This is the home for "runtime-learned config mutations": today it's the
resource-scope auto-extend (when an agent successfully creates a new
resource via an allowlisted op, that resource's ID is appended to every
matching field_scopes entry on the same provider node). Future runtime
write-backs (observed schemas, learned defaults, etc.) belong here too —
keep the call site in tool_execution.py thin.

Concurrency: every writeback runs inside a transaction with
``SELECT ... FOR UPDATE`` on the workflows row. Two concurrent extensions
on the same workflow serialize cleanly; canvas saves racing with a runtime
writeback land in deterministic order with no read-modify-write loss.

Broadcast: rides ``MCPBuilderEvent`` (event_type="node_updated") via
``broadcast_to_user_safe``. The FE handler at hooks/useMCPBuilderEvents.ts
already deep-merges the config payload into the live canvas node, so this
helper inherits all of that plumbing for free.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from nodes.agent.node_op_tools import (
    normalize_allowed_operations,
    resource_field_index,
)
from utils.event_relay import broadcast_to_user_safe
from wss.sender.events import MCPBuilderEvent

logger = logging.getLogger(__name__)


async def extend_node_field_scopes(
    *,
    pool=None,
    workflow_id: str,
    provider_node_id: str,
    new_resource_ids_by_type: Dict[str, str],
) -> Optional[List[Any]]:
    """Append newly-created resource IDs to the provider node's
    ``agent_tool_operations`` field_scopes, persist the updated workflow,
    and broadcast a ``node_updated`` builder event to the owner.

    *new_resource_ids_by_type* is ``{resource_type: new_id}`` — each entry
    lands on every scopable field on the provider node whose
    ``x-resource-type`` matches. Only ops that already carry a
    ``field_scopes`` entry for that field are extended — unscoped ops stay
    unscoped (the runtime never CREATES a scope from nothing; it only
    expands one the user already established).

    Returns the updated ``agent_tool_operations`` list (so the caller can
    mutate live tool_configs in-place), or ``None`` if nothing changed
    (provider node missing, no scoped ops touch the resource type, IDs
    already present, etc.).
    """
    if not new_resource_ids_by_type:
        return None

    if pool is None:
        from utils.database_pool import get_native_pool

        pool = get_native_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT workflow, user_id FROM workflows WHERE id = $1 FOR UPDATE",
                uuid.UUID(workflow_id),
            )
            if not row:
                logger.info(
                    f"[ScopeWriteback] workflow {workflow_id} missing — auto-extend skipped"
                )
                return None

            workflow = row["workflow"] or {"nodes": [], "edges": []}
            nodes = workflow.get("nodes") or []
            owner_id = row["user_id"]

            target_idx = next(
                (i for i, n in enumerate(nodes) if n.get("id") == provider_node_id),
                None,
            )
            if target_idx is None:
                logger.info(
                    f"[ScopeWriteback] provider {provider_node_id} not on workflow "
                    f"{workflow_id} — auto-extend skipped"
                )
                return None

            target = nodes[target_idx]
            node_type = target.get("type") or ""
            target_config = target.get("config") or {}
            current_allowlist = target_config.get("agent_tool_operations") or []

            updated, changed = _extend_allowlist_in_place(
                node_type=node_type,
                allowlist=current_allowlist,
                new_resource_ids_by_type=new_resource_ids_by_type,
            )
            if not changed:
                return None

            target_config["agent_tool_operations"] = updated
            target["config"] = target_config
            nodes[target_idx] = target
            workflow["nodes"] = nodes

            await conn.execute(
                "UPDATE workflows SET workflow = $1, updated_at = NOW() WHERE id = $2",
                workflow,
                uuid.UUID(workflow_id),
            )

    # Broadcast OUTSIDE the txn so a slow relay can't hold a row lock.
    # FE's useMCPBuilderEvents -> 'node_updated' deep-merges `config` into
    # the live node via rawConfigToPayload/applyNodeUpdate — collaborators
    # of the owner see the new scope without a refresh.
    try:
        await broadcast_to_user_safe(
            owner_id,
            MCPBuilderEvent(
                workflow_id=workflow_id,
                event_type="node_updated",
                data={
                    "nodeId": provider_node_id,
                    "config": {"agent_tool_operations": updated},
                },
            ),
            workflow_id=workflow_id,
        )
    except Exception as e:
        # Broadcast failures must not fail the tool call. The DB write has
        # already landed; collaborators see the change on next workflow load.
        logger.warning(
            f"[ScopeWriteback] broadcast for {provider_node_id} failed: {e}"
        )
    logger.info(
        f"[ScopeWriteback] extended {provider_node_id} agent_tool_operations "
        f"with {list(new_resource_ids_by_type.items())} (workflow {workflow_id})"
    )
    return updated


def _extend_allowlist_in_place(
    *,
    node_type: str,
    allowlist: List[Any],
    new_resource_ids_by_type: Dict[str, str],
) -> Tuple[List[Any], bool]:
    """Return ``(new_allowlist, changed)``. Pure — no DB, no broadcast.

    Walks the existing allowlist, looks up each scoped op's field
    resource types via the cached schema introspection, and unions the
    matching new IDs onto each field's scope. Unscoped (string) entries
    are untouched.
    """
    # op -> field -> resource_type (only x-dynamic-options + x-resource-type fields)
    index_by_op: Dict[str, Dict[str, str]] = {}
    for op, field, rt in resource_field_index(node_type):
        index_by_op.setdefault(op, {})[field] = rt

    changed = False
    out: List[Any] = []
    for entry in allowlist:
        if isinstance(entry, str):
            out.append(entry)
            continue
        if not isinstance(entry, dict):
            # Garbage — drop silently; the runtime reader was already
            # tolerant. Treat as a no-op for change detection.
            continue
        op_name = entry.get("operation")
        raw_scopes = entry.get("field_scopes")
        if not isinstance(op_name, str) or not isinstance(raw_scopes, dict):
            out.append(entry)
            continue
        field_rt_map = index_by_op.get(op_name, {})
        new_scopes: Dict[str, List[str]] = {}
        for field, ids in raw_scopes.items():
            existing = [i for i in (ids or []) if isinstance(i, str) and i]
            rt = field_rt_map.get(field)
            new_id = new_resource_ids_by_type.get(rt) if rt else None
            if new_id and new_id not in existing:
                merged = [*existing, new_id]
                new_scopes[field] = merged
                changed = True
            else:
                new_scopes[field] = existing
        out.append({"operation": op_name, "field_scopes": new_scopes})
    return out, changed


def affected_scoped_fields(
    tool_configs: Dict[str, Dict[str, Any]],
    provider_node_id: str,
    new_resource_ids_by_type: Dict[str, str],
    node_type: str,
) -> Set[Tuple[str, str]]:
    """Tool-name + field pairs whose ``field_scopes`` should grow when the
    given resource IDs are appended. Used to mutate live tool_configs
    in-process so subsequent tool calls in THIS session pick up the new
    IDs (the DB writeback handles future sessions; this handles the
    current one)."""
    out: Set[Tuple[str, str]] = set()
    index_by_op: Dict[str, Dict[str, str]] = {}
    for op, field, rt in resource_field_index(node_type):
        index_by_op.setdefault(op, {})[field] = rt
    for tool_name, info in tool_configs.items():
        if info.get("node_id") != provider_node_id:
            continue
        if info.get("tool_type") != "node_op":
            continue
        op = info.get("operation")
        scopes = info.get("field_scopes")
        if not isinstance(op, str) or not isinstance(scopes, dict):
            continue
        for field in scopes:
            rt = index_by_op.get(op, {}).get(field)
            if rt and rt in new_resource_ids_by_type:
                out.add((tool_name, field))
    return out


def apply_new_id_to_live_tool_configs(
    tool_configs: Dict[str, Dict[str, Any]],
    provider_node_id: str,
    node_type: str,
    new_resource_ids_by_type: Dict[str, str],
) -> None:
    """Mutate the in-memory ``tool_configs`` dict so the live agent sees the
    extended scopes on its NEXT tool call this session. Mirrors the DB
    writeback's effect without re-reading the workflow row. Also bumps the
    matching ``__lookup_options`` tool's ``field_scopes`` (when locked) so
    a follow-up search includes the fresh ID.
    """
    affected = affected_scoped_fields(
        tool_configs, provider_node_id, new_resource_ids_by_type, node_type,
    )
    if not affected:
        return

    index_by_op: Dict[str, Dict[str, str]] = {}
    for op, field, rt in resource_field_index(node_type):
        index_by_op.setdefault(op, {})[field] = rt

    extended_fields: Set[str] = set()
    for tool_name, field in affected:
        info = tool_configs[tool_name]
        rt = index_by_op.get(info["operation"], {}).get(field)
        new_id = new_resource_ids_by_type.get(rt) if rt else None
        if not new_id:
            continue
        scopes = info.setdefault("field_scopes", {})
        existing = list(scopes.get(field) or [])
        if new_id not in existing:
            scopes[field] = [*existing, new_id]
            extended_fields.add(field)

    if not extended_fields:
        return

    # Update the lookup tool's per-field scope union too — only if it was
    # already locked (the unscoped collapse stays unscoped).
    for tool_name, info in tool_configs.items():
        if info.get("node_id") != provider_node_id:
            continue
        if info.get("tool_type") != "node_op_lookup":
            continue
        lookup_scopes = info.get("field_scopes")
        if not isinstance(lookup_scopes, dict):
            continue
        for field in extended_fields:
            existing = lookup_scopes.get(field)
            if not isinstance(existing, list) or not existing:
                continue
            # Find the new id for this field via any affected op.
            op_for_field = next(
                (op for op, fmap in index_by_op.items() if field in fmap),
                None,
            )
            rt = index_by_op.get(op_for_field or "", {}).get(field) if op_for_field else None
            new_id = new_resource_ids_by_type.get(rt) if rt else None
            if new_id and new_id not in existing:
                lookup_scopes[field] = [*existing, new_id]


__all__ = [
    "apply_new_id_to_live_tool_configs",
    "extend_node_field_scopes",
]
