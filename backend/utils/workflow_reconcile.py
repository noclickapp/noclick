"""What a change to a workflow's graph sets in motion outside the graph,
judged from the graph before and after it, for every writer (the graph
service's edits and restores, the canvas's save):

- a step removed tears down what it registered (schedules, provider webhooks,
  node state, published apps, conversations, volumes; ``cleanup_nodes_resources``,
  given the removed steps as they were) and gives back its inbound-email address.
  The canvas names the steps it deleted (``deleted``), and only those go: a
  closing tab's last save of a graph it loaded before another writer added a
  step must not take that step's resources;
- a step whose operation, connections or registration fields changed has its
  trigger registration reconciled (``WebhookManager``'s change hooks);
- a trigger with no webhook yet, or one whose registration failed, is
  provisioned once nothing it needs is missing, its webhook fields written
  into its config;
- a step that's back (a delete undone) registers again what it registered.

It makes provider round-trips, so writers run it after their write commits.
One workflow's reconciles run one at a time (a lock on the database, across
processes), each judged against the graph as it stands when it runs: a step a
later write brought back isn't torn down, nor one a later write removed
registered. Each part runs whatever another part did. Given the version the
write left, it returns the version its own writes (a trigger's webhook fields)
left the workflow at, so a writer hands back a version its caller can edit
from; another writer's change in between ends that chain."""

from __future__ import annotations

import asyncio
import logging
import weakref
from contextlib import asynccontextmanager
from typing import Any, Collection, List, Optional, Tuple

from utils.graph_nodes import graph_nodes, node_config

logger = logging.getLogger(__name__)


async def reconcile_graph_change(pool, workflow_id: str, user_id: str, old_graph: Any, new_graph: Any, *,
                                 version: Optional[int] = None,
                                 deleted: Optional[Collection[str]] = None) -> Optional[int]:
    from utils.webhook_manager import PATCH_MOVES

    workflow_id = str(workflow_id)
    moves: List[Tuple[int, int]] = []
    token = PATCH_MOVES.set(moves)
    try:
        async with _one_at_a_time(pool, workflow_id) as held:
            now = await held.fetchval("SELECT workflow FROM workflows WHERE id = $1::uuid", workflow_id)
            await _reconcile(pool, workflow_id, user_id, old_graph, new_graph, now, deleted)
    finally:
        PATCH_MOVES.reset(token)
    if version is None:
        return None
    following = dict(moves)
    while version in following:
        version = following.pop(version)
    return version


_IN_PROCESS: "weakref.WeakValueDictionary[str, asyncio.Lock]" = weakref.WeakValueDictionary()


@asynccontextmanager
async def _one_at_a_time(pool, workflow_id: str):
    """Hold the workflow's reconcile lock: one per process, then one on the database across processes, held by a
    transaction on a connection of its own (beside no row lock: the writes a reconcile makes lock the row
    themselves). A reconcile waiting on another's holds no connection."""
    lock = _IN_PROCESS.get(workflow_id)
    if lock is None:
        lock = _IN_PROCESS.setdefault(workflow_id, asyncio.Lock())
    key, delay = f"workflow-reconcile:{workflow_id}", 0.05
    async with lock:
        while True:
            async with pool.acquire() as conn:
                held = conn.transaction()
                await held.start()
                try:
                    if await conn.fetchval("SELECT pg_try_advisory_xact_lock(hashtextextended($1, 0))", key):
                        yield conn
                        return
                finally:
                    await held.rollback()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 1.0)


async def _reconcile(pool, workflow_id: str, user_id: str, old_graph: Any, new_graph: Any, now_graph: Any,
                     deleted: Optional[Collection[str]]) -> None:
    from utils.email_reservation_manager import EmailReservationManager
    from utils.webhook_manager import WebhookManager
    from utils.workflow_readiness import unbound_issues
    from utils.workflow_resource_manager import cleanup_nodes_resources

    old_nodes = {n.get("id"): n for n in graph_nodes(old_graph) if n.get("id")}
    new_nodes = {n.get("id"): n for n in graph_nodes(new_graph) if n.get("id")}
    now_ids = {n.get("id") for n in graph_nodes(now_graph) if n.get("id")}

    gone = [node_id for node_id in old_nodes if node_id not in new_nodes] if deleted is None else \
        [node_id for node_id in dict.fromkeys(deleted) if node_id and node_id not in new_nodes]
    removed = [node_id for node_id in gone if node_id not in now_ids]
    if removed:
        try:
            await cleanup_nodes_resources(pool=pool, workflow_id=workflow_id, node_ids=removed, background=True,
                                          old_nodes=[old_nodes[i] for i in removed if i in old_nodes],
                                          requesting_user_id=user_id)
        except Exception:
            logger.warning("[reconcile] cleanup of removed steps %s of %s failed", removed, workflow_id,
                           exc_info=True)
        try:
            await EmailReservationManager.release_many(pool, workflow_id, removed)
        except Exception:
            logger.warning("[reconcile] releasing the inboxes of %s of %s failed", removed, workflow_id,
                           exc_info=True)

    for node_id, node in new_nodes.items():
        old = old_nodes.get(node_id)
        if old is None or node_id not in now_ids:
            continue
        node_type = node.get("type", "")
        old_config, new_config = node_config(old), node_config(node)
        try:
            old_op, new_op = old_config.get("operation"), new_config.get("operation")
            if old_op and new_op and old_op != new_op:
                await WebhookManager.handle_operation_change(pool, node_type, workflow_id, node_id, old_op, new_op,
                                                             old_config=old_config, user_id=user_id)
            await WebhookManager.handle_credential_change(pool, node_type, workflow_id, node_id, old_config,
                                                          new_config, user_id)
            # Registration fields (PostHog's event_name, GitHub's repository) under the same operation and
            # connections: else the provider stays registered on the old value until the panel reopens.
            await WebhookManager.handle_registration_fields_change(pool, node_type, workflow_id, node_id,
                                                                   old_config, new_config, user_id=user_id)
        except Exception:
            logger.warning("[reconcile] change hooks of %s:%s failed", workflow_id, node_id, exc_info=True)

    # Triggers as they stand now: a later write's own reconcile judges what it changed.
    for trigger in graph_nodes(now_graph):
        config = node_config(trigger)
        kind, node_id = trigger.get("type"), trigger.get("id")
        if not node_id or config.get("disabled") in (True, "true"):
            continue
        if not WebhookManager.node_webhook_field_for(kind, config.get("operation")):
            continue
        if config.get("webhook_url") and not config.get("trigger_error"):
            continue
        try:
            if await unbound_issues(pool, workflow_id, now_graph, node_id):
                continue
            patch = await WebhookManager.provision_node_webhook(
                pool, user_id=user_id, workflow_id=workflow_id, node_id=node_id, node_type=kind,
                operation=config.get("operation"), config=config, workflow_graph=now_graph)
            if patch:
                await WebhookManager.merge_node_config_patch(pool, workflow_id, node_id, patch)
        except Exception:
            logger.warning("[reconcile] trigger activation of %s:%s failed", workflow_id, node_id, exc_info=True)

    back = [node_id for node_id in new_nodes if node_id not in old_nodes and node_id in now_ids]
    if back:
        try:
            await WebhookManager.register_node_webhooks(pool, workflow_id, user_id, node_ids=back)
        except Exception:
            logger.warning("[reconcile] re-registering %s of %s failed", back, workflow_id, exc_info=True)
