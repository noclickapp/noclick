"""What a change to a workflow's graph sets in motion outside the graph,
judged from the graph before and after it, for every writer (the graph
service's edits and restores, the canvas's save):

- a step removed tears down what it registered (schedules, provider webhooks,
  node state, published apps; ``cleanup_nodes_resources``, given the removed
  steps as they were) and gives back its inbound-email address;
- a step whose operation, connections or registration fields changed has its
  trigger registration reconciled (``WebhookManager``'s change hooks);
- a trigger with no webhook yet, or one whose registration failed, is
  provisioned once nothing it needs is missing, its webhook fields written
  into its config;
- a step that's back (a delete undone) registers again what it registered.

It makes provider round-trips, so writers run it after their write commits and
off the response path. Each part runs whatever another part did."""

from __future__ import annotations

import logging
from typing import Any

from utils.graph_nodes import graph_nodes, node_config

logger = logging.getLogger(__name__)


async def reconcile_graph_change(pool, workflow_id: str, user_id: str, old_graph: Any, new_graph: Any) -> None:
    from utils.email_reservation_manager import EmailReservationManager
    from utils.webhook_manager import WebhookManager
    from utils.workflow_readiness import unbound_issues
    from utils.workflow_resource_manager import cleanup_nodes_resources

    workflow_id = str(workflow_id)
    old_nodes = {n.get("id"): n for n in graph_nodes(old_graph) if n.get("id")}
    new_nodes = {n.get("id"): n for n in graph_nodes(new_graph) if n.get("id")}

    removed = [node_id for node_id in old_nodes if node_id not in new_nodes]
    if removed:
        try:
            await cleanup_nodes_resources(pool=pool, workflow_id=workflow_id, node_ids=removed, background=True,
                                          old_nodes=[old_nodes[i] for i in removed], requesting_user_id=user_id)
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
        if old is None:
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

    for trigger in graph_nodes(new_graph):
        config = node_config(trigger)
        kind, node_id = trigger.get("type"), trigger.get("id")
        if not node_id or config.get("disabled") in (True, "true"):
            continue
        if not WebhookManager.node_webhook_field_for(kind, config.get("operation")):
            continue
        if config.get("webhook_url") and not config.get("trigger_error"):
            continue
        try:
            if await unbound_issues(pool, workflow_id, new_graph, node_id):
                continue
            patch = await WebhookManager.provision_node_webhook(
                pool, user_id=user_id, workflow_id=workflow_id, node_id=node_id, node_type=kind,
                operation=config.get("operation"), config=config, workflow_graph=new_graph)
            if patch:
                await WebhookManager.merge_node_config_patch(pool, workflow_id, node_id, patch)
        except Exception:
            logger.warning("[reconcile] trigger activation of %s:%s failed", workflow_id, node_id, exc_info=True)

    back = [node_id for node_id in new_nodes if node_id not in old_nodes]
    if back:
        try:
            await WebhookManager.register_node_webhooks(pool, workflow_id, user_id, node_ids=back)
        except Exception:
            logger.warning("[reconcile] re-registering %s of %s failed", back, workflow_id, exc_info=True)
