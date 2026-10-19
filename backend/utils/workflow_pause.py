"""Pausing a workflow: each trigger that's on is switched off with who paused it
and why (``paused_by``, ``paused_reason``: the Dashboard shows a switched-off
trigger by its reason), then reconciled, so its schedules and provider webhooks
stop. Resuming switches back on only what a pause switched off, never a trigger
someone turned off by hand or the schedule breaker paused."""

import uuid
from typing import Callable, Dict, List, Optional

from utils.graph_nodes import graph_nodes, is_trigger_node, node_config, node_disabled, node_label

MAX_REASON = 300


async def _set(pool, workflow_id: str, owner_id: str, pick: Callable[[Dict], bool], patch: Dict) -> List[str]:
    from utils.webhook_manager import WebhookManager

    graph = await pool.fetchval("SELECT workflow FROM workflows WHERE id = $1::uuid AND deleted_at IS NULL",
                                str(workflow_id))
    changed = []
    for node in graph_nodes(graph):
        if pick(node):
            await WebhookManager.merge_node_config_patch(pool, uuid.UUID(str(workflow_id)), node["id"], patch)
            await WebhookManager.reconcile_node(pool, str(workflow_id), node["id"], user_id=owner_id)
            changed.append(node_label(node) or node["id"])
    return changed


async def pause_triggers(pool, workflow_id: str, owner_id: str, *, by: str, reason: str) -> List[str]:
    """Switch off each trigger that's on; the names of the ones switched off."""
    return await _set(pool, workflow_id, owner_id, lambda n: is_trigger_node(n) and not node_disabled(n),
                      {"disabled": True, "paused_by": by, "paused_reason": reason[:MAX_REASON]})


async def resume_triggers(pool, workflow_id: str, owner_id: str, *, by: Optional[str] = None) -> List[str]:
    """Switch back on what a pause switched off (``by``: only that one's pauses);
    the names of the ones switched on."""
    return await _set(pool, workflow_id, owner_id,
                      lambda n: bool(node_config(n).get("paused_by")) and by in (None, node_config(n)["paused_by"]),
                      {"disabled": False, "paused_by": None, "paused_reason": None})
