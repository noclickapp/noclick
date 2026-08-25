"""
Centralized manager for workflow resource lifecycle (webhooks, cron schedules, etc.).

Provides unified cleanup and restoration functions used by workflow handlers
and checkpoint handlers to ensure consistent resource management across the codebase.
"""

import logging
from typing import List, Dict, Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# Node types that require external resource registration (webhooks, schedules, etc.)
RESOURCE_NODE_TYPES = {'trigger-webhook', 'trigger-cron'}




async def cleanup_nodes_resources(
    pool,
    workflow_id: str,
    node_ids: List[str],
    background: bool = False,
    old_nodes: Optional[List[Dict[str, Any]]] = None,
    requesting_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Clean up all resources associated with the specified nodes.

    This includes:
    - Cron schedules (external Cloudflare scheduler)
    - Provider-side webhook deregistration (Stripe, Linear, …)

    ``old_nodes`` carries the deleted nodes' dicts (with config) when the caller
    has already overwritten the workflow blob — the canvas node-delete path saves
    the node-less workflow before this runs, so the live blob no longer carries
    the ``external_webhook_id`` needed to deregister. Pass the pre-delete node
    dicts here so deregistration uses the OLD config.

    The internal ``webhooks`` DB row is deliberately NOT deleted on node removal —
    it is deactivated (by the deregister path) so the URL/UUID survives an undo or
    checkpoint restore. The row is only hard-deleted on full workflow deletion.

    Args:
        pool: Database connection pool
        workflow_id: The workflow ID
        node_ids: List of node IDs to clean up
        background: If True, external service calls run in background for faster return

    Returns:
        Dict with cleanup results for each resource type
    """
    from utils.cron_scheduler_client import delete_schedules_for_nodes
    from utils.webhook_manager import WebhookManager

    if not node_ids:
        return {'cron': {'deleted': 0}, 'webhooks': {'deleted': 0}}

    results = {}

    # Cleanup cron schedules
    if background:
        # Fire-and-forget: run in background
        from utils.async_helpers import spawn
        spawn(
            delete_schedules_for_nodes(workflow_id=workflow_id, node_ids=node_ids),
            name=f"workflow-cleanup-schedules:{workflow_id}",
        )
        results['cron'] = {'background': True}
    else:
        try:
            cron_result = await delete_schedules_for_nodes(
                workflow_id=workflow_id,
                node_ids=node_ids
            )
            results['cron'] = cron_result
            logger.info(f"[WorkflowResourceManager] Cleaned up cron schedules for {len(node_ids)} nodes in workflow {workflow_id}")
        except Exception as e:
            logger.warning(f"[WorkflowResourceManager] Failed to cleanup cron schedules: {e}")
            results['cron'] = {'error': str(e)}

    # Deregister from external services (Stripe, Linear, WhatsApp, watch
    # channels, …) via the choke point, which also DEACTIVATES (not deletes)
    # the internal webhooks row so the URL/UUID survives an undo —
    # re-registration on restore reuses it. We pass ``old_nodes`` because the
    # canvas save already removed these nodes from the live workflow blob,
    # taking their external_webhook_id with them. ``background=True`` spawns
    # the provider round-trips (credential decrypt + OAuth freshen + HTTP) off
    # the caller's ack path.
    if background:
        from utils.async_helpers import spawn
        spawn(
            WebhookManager.deregister_node_webhooks(
                pool, workflow_id, node_ids,
                node_overrides=old_nodes,
                requesting_user_id=requesting_user_id,
            ),
            name=f"workflow-cleanup-webhooks:{workflow_id}",
        )
        results['webhooks'] = {'background': True, 'preserved': True}
    else:
        try:
            unreg = await WebhookManager.deregister_node_webhooks(
                pool, workflow_id, node_ids,
                node_overrides=old_nodes,
                requesting_user_id=requesting_user_id,
            )
            results['webhooks'] = {**unreg, 'preserved': True}
            logger.info(
                f"[WorkflowResourceManager] Deregistered+preserved webhooks for "
                f"{len(node_ids)} nodes in workflow {workflow_id}: {unreg}"
            )
        except Exception as e:
            logger.warning(f"[WorkflowResourceManager] Failed to deregister external webhooks for nodes: {e}")
            results['webhooks'] = {'error': str(e)}

    # Cleanup node state (for State Manager nodes)
    try:
        deleted_count = await pool.execute("""
            DELETE FROM workflow_node_state
            WHERE workflow_id = $1 AND node_id = ANY($2)
        """, workflow_id, node_ids)
        results['node_state'] = {'deleted': deleted_count}
        if deleted_count and deleted_count != 'DELETE 0':
            logger.info(f"[WorkflowResourceManager] Cleaned up node state for workflow {workflow_id}: {deleted_count}")
    except Exception as e:
        logger.warning(f"[WorkflowResourceManager] Failed to cleanup node state: {e}")
        results['node_state'] = {'error': str(e)}

    # Note: workflow_resources (datasets, blobs) are NOT cleaned up on node deletion
    # to support undo, version history, and checkpoint restore. They are only cleaned
    # up when the entire workflow is deleted (via cleanup_workflow_resources).

    # Cleanup managed workspace volumes for any deleted filesystem nodes
    try:
        await _cleanup_filesystem_volumes(pool, workflow_id, node_ids)
        results['workspace_volumes'] = {'cleaned': True}
    except Exception as e:
        logger.warning(f"[WorkflowResourceManager] Failed to cleanup managed workspace volumes for nodes: {e}")
        results['workspace_volumes'] = {'error': str(e)}


    # Cleanup agent-chat conversations scoped to deleted nodes (soft-delete to
    # match the rest of the conversation lifecycle — the AgentChatBlock's
    # per-agent history list filters on deleted_at IS NULL). Covers both the
    # canonical conversation_id pattern `ck:{wf}:{node}:%` and the populated
    # workflow_id+node_id columns.
    try:
        like_patterns = [f"ck:{workflow_id}:{nid}:%" for nid in node_ids]
        conv_result = await pool.execute(
            """
            UPDATE conversations
            SET deleted_at = NOW()
            WHERE deleted_at IS NULL
              AND (
                (workflow_id = $1 AND node_id = ANY($2))
                OR conversation_id LIKE ANY($3)
              )
            """,
            workflow_id, node_ids, like_patterns,
        )
        results['conversations'] = {'deleted': conv_result}
        if conv_result and conv_result != 'UPDATE 0':
            logger.info(
                f"[WorkflowResourceManager] Soft-deleted agent-chat conversations "
                f"for {len(node_ids)} nodes in workflow {workflow_id}: {conv_result}")
    except Exception as e:
        logger.warning(f"[WorkflowResourceManager] Failed to cleanup node conversations: {e}")
        results['conversations'] = {'error': str(e)}

    return results


async def cleanup_workflow_resources(
    pool,
    workflow_id: str,
) -> Dict[str, Any]:
    """
    Clean up all resources associated with an entire workflow.

    This includes:
    - All cron schedules for the workflow
    - All webhook entries for the workflow

    Args:
        pool: Database connection pool
        workflow_id: The workflow ID

    Returns:
        Dict with cleanup results for each resource type
    """
    from utils.cron_scheduler_client import delete_schedules_for_workflow
    from utils.webhook_manager import WebhookManager

    results = {}

    # Cleanup all cron schedules for workflow
    try:
        cron_result = await delete_schedules_for_workflow(workflow_id=workflow_id)
        results['cron'] = cron_result
        logger.info(f"[WorkflowResourceManager] Cleaned up all cron schedules for workflow {workflow_id}")
    except Exception as e:
        logger.warning(f"[WorkflowResourceManager] Failed to cleanup cron schedules for workflow: {e}")
        results['cron'] = {'error': str(e)}

    # Deregister from external services first (handles restore→permanent-delete path
    # where provider endpoints were re-registered but not yet cleaned up).
    # manage_rows=False: the rows are hard-deleted wholesale right below.
    try:
        await WebhookManager.deregister_node_webhooks(pool, workflow_id, manage_rows=False)
    except Exception as e:
        logger.warning(f"[WorkflowResourceManager] Failed to deregister external webhooks for workflow: {e}")

    # Cleanup all webhook DB records for workflow (permanent delete only)
    try:
        webhook_result = await WebhookManager.delete_webhooks_for_workflow(
            pool=pool,
            workflow_id=workflow_id
        )
        results['webhooks'] = {'deleted': webhook_result}
        logger.info(f"[WorkflowResourceManager] Cleaned up all webhooks for workflow {workflow_id}")
    except Exception as e:
        logger.warning(f"[WorkflowResourceManager] Failed to cleanup webhooks for workflow: {e}")
        results['webhooks'] = {'error': str(e)}

    # Cleanup all node state for workflow
    try:
        deleted_count = await pool.execute("""
            DELETE FROM workflow_node_state
            WHERE workflow_id = $1
        """, workflow_id)
        results['node_state'] = {'deleted': deleted_count}
        if deleted_count and deleted_count != 'DELETE 0':
            logger.info(f"[WorkflowResourceManager] Cleaned up all node state for workflow {workflow_id}: {deleted_count}")
    except Exception as e:
        logger.warning(f"[WorkflowResourceManager] Failed to cleanup node state for workflow: {e}")
        results['node_state'] = {'error': str(e)}

    # Cleanup all workflow resources (datasets, blobs) for the workflow.
    # ON DELETE CASCADE on workflow_id handles DB cleanup when the workflow row
    # is deleted, but R2 blobs are external storage and need explicit deletion.
    # DB reads/writes stay in one short pinned block; the R2 delete runs after
    # release so external-storage latency never holds a pool connection.
    try:
        async with pool.acquire() as conn:
            blob_rows = await conn.fetch("""
                SELECT storage_ref FROM workflow_resources
                WHERE workflow_id = $1 AND storage_ref IS NOT NULL
            """, workflow_id)
            # Delete rows explicitly in case this is called independently of a
            # workflow-row delete (where CASCADE would handle it).
            wr_result = await conn.execute("""
                DELETE FROM workflow_resources WHERE workflow_id = $1
            """, workflow_id)

        if blob_rows:
            from utils.r2_cloudflare import delete_files_from_r2_async
            storage_refs = [r['storage_ref'] for r in blob_rows]
            try:
                await delete_files_from_r2_async("workflow-resources", "", storage_refs)
            except Exception as e:
                logger.warning(f"[WorkflowResourceManager] Failed to delete R2 blobs for workflow: {e}")

        results['workflow_resources'] = {'deleted': wr_result}
        if wr_result and wr_result != 'DELETE 0':
            logger.info(f"[WorkflowResourceManager] Cleaned up all workflow resources for workflow {workflow_id}: {wr_result}")
    except Exception as e:
        logger.warning(f"[WorkflowResourceManager] Failed to cleanup workflow resources for workflow: {e}")
        results['workflow_resources'] = {'error': str(e)}

    # CAS node-output storage: cas_refs/cas_manifests cascade-delete with the
    # workflow (FK ON DELETE CASCADE), and the GC cron's Phase B reclaims the
    # now-orphaned blobs + their R2 objects. Before the cascade removes this
    # workflow's executions, fold its lifetime run count into the global ledger
    # so platform totals survive the deletion.
    try:
        from utils.cas.gc import rollup_workflow_totals
        await rollup_workflow_totals(pool, workflow_id)
        results['node_outputs'] = {'cas_totals_rolled_up': True}
    except Exception as e:
        logger.warning(f"[WorkflowResourceManager] Failed to roll up CAS totals: {e}")
        results['node_outputs'] = {'error': str(e)}

    # Delete all conversations associated with this workflow. Two filters
    # cover the migration boundary: the workflow_id column (populated for
    # newer rows) and the canonical conversation_id prefix `ck:{wf}:%`
    # (covers older rows + the AgentChatBlock per-agent threads).
    try:
        conv_result = await pool.execute(
            """
            DELETE FROM conversations
            WHERE workflow_id = $1
               OR conversation_id LIKE $2
            """,
            workflow_id, f"ck:{workflow_id}:%",
        )
        results['conversations'] = {'deleted': conv_result}
        if conv_result and conv_result != 'DELETE 0':
            logger.info(f"[WorkflowResourceManager] Deleted conversations for workflow {workflow_id}: {conv_result}")
    except Exception as e:
        logger.warning(f"[WorkflowResourceManager] Failed to cleanup conversations for workflow: {e}")
        results['conversations'] = {'error': str(e)}

    # Delete EVERY managed workspace volume belonging to this workflow — FilesystemNode
    # volumes (common + per-ck, including nodes long removed from the graph),
    # per-conversation agent workspaces (noclick-ws-*), and all CLI-harness
    # session volumes — via the naming convention every family shares.
    # PERMANENT-DELETE ONLY: soft-delete/trash must never reach this, so a
    # restore brings the agent workspaces back intact.
    try:
        deleted = await _cleanup_workflow_volumes(workflow_id)
        results['workspace_volumes'] = {'deleted': deleted}
    except Exception as e:
        logger.warning(f"[WorkflowResourceManager] Failed to cleanup managed workspace volumes: {e}")
        results['workspace_volumes'] = {'error': str(e)}


    return results


async def cleanup_workflow_operational_resources(
    pool,
    workflow_id: str,
) -> Dict[str, Any]:
    """
    Clean up only operational resources for a workflow (cron schedules, webhooks).

    Unlike cleanup_workflow_resources(), this preserves node state, R2 storage,
    and workflow_resources rows so the workflow can be restored from trash.

    Args:
        pool: Database connection pool
        workflow_id: The workflow ID

    Returns:
        Dict with cleanup results for each resource type
    """
    from utils.cron_scheduler_client import delete_schedules_for_workflow
    from utils.webhook_manager import WebhookManager

    results = {}

    # Cleanup all cron schedules for workflow
    try:
        cron_result = await delete_schedules_for_workflow(workflow_id=workflow_id)
        results['cron'] = cron_result
        logger.info(f"[WorkflowResourceManager] Cleaned up all cron schedules for workflow {workflow_id}")
    except Exception as e:
        logger.warning(f"[WorkflowResourceManager] Failed to cleanup cron schedules for workflow: {e}")
        results['cron'] = {'error': str(e)}

    # Deregister from external services (Stripe, Linear, WhatsApp, watch
    # channels, …) but keep the webhook DB records so the UUID/URL is preserved
    # for restore. The choke point deactivates the rows; they're only
    # hard-deleted on permanent delete (cleanup_workflow_resources).
    # on_trash=True: classes with preserve_registration_on_trash (inbound
    # email's address reservation) are skipped so trash stays reversible.
    try:
        unreg = await WebhookManager.deregister_node_webhooks(pool, workflow_id, on_trash=True)
        results['webhooks'] = {**unreg, 'preserved': True}
    except Exception as e:
        logger.warning(f"[WorkflowResourceManager] Failed to deregister external webhooks for workflow: {e}")
        results['webhooks'] = {'error': str(e)}

    return results


async def restore_nodes_resources(
    pool,
    user_id: str,
    workflow_id: str,
    nodes: List[Dict[str, Any]],
    node_ids_to_restore: Optional[set] = None,
) -> Dict[str, Any]:
    """
    Restore resources for nodes that require external registrations.

    Handles:
    - trigger-webhook: re-activates the webhook entry
    - trigger-cron: re-activates the webhook entry + registers the cron schedule
    - external-webhook trigger nodes (Stripe, Linear, …): re-registers the
      provider-side endpoint via WebhookManager.register_node_webhooks, which
      acts only on inactive rows carrying the registered_operation marker —
      action nodes and never-registered triggers are untouched.

    Args:
        pool: Database connection pool
        user_id: The user ID
        workflow_id: The workflow ID
        nodes: List of node objects from the workflow
        node_ids_to_restore: Optional set of specific node IDs to restore.
                            If None, restores all applicable nodes in the list.

    Returns:
        Dict with restoration results
    """
    from utils.webhook_manager import WebhookManager

    results = {'restored': [], 'errors': []}

    for node in nodes:
        node_id = node.get('id')
        node_type = node.get('type')

        # Skip if not a node type that requires resource registration
        if node_type not in RESOURCE_NODE_TYPES:
            continue

        # Skip if we have a specific list and this node isn't in it
        if node_ids_to_restore is not None and node_id not in node_ids_to_restore:
            continue

        try:
            # Create/restore webhook for all trigger nodes
            # Use background_relay=True for fast restore - relay registration happens async
            webhook_data = await WebhookManager.get_or_create_webhook(
                pool=pool,
                user_id=user_id,
                workflow_id=UUID(workflow_id),
                node_id=node_id,
                background_relay=True
            )
            logger.info(f"[WorkflowResourceManager] Restored webhook for node {node_id}")

            # For cron nodes, restore the schedules through THE reconciler:
            # multi-schedule + timezone + window aware, deterministic ids
            # (the old hand-rolled single create here minted a random-id row
            # the deterministic-id prune never matched, and read the legacy
            # singular `schedule` key — truncating multi-schedule configs).
            if node_type == 'trigger-cron':
                # nodes_override: desired state comes from the restored node
                # itself, independent of whether the graph save landed yet.
                reconcile = await WebhookManager.reconcile_node(
                    pool, str(workflow_id), node_id, user_id=user_id,
                    nodes_override=[{
                        'id': node_id,
                        'type': node_type,
                        'config': node.get('config', {}),
                    }],
                )
                if reconcile.get('state') == 'failed':
                    logger.warning(
                        f"[WorkflowResourceManager] Failed to restore cron schedule: {reconcile.get('error')}"
                    )
                    results['errors'].append({
                        'node_id': node_id,
                        'resource': 'cron',
                        'error': reconcile.get('error'),
                    })
                else:
                    logger.info(f"[WorkflowResourceManager] Restored cron schedule for node {node_id}")

            results['restored'].append({
                'node_id': node_id,
                'node_type': node_type,
                'webhook_id': webhook_data.get('webhook_id')
            })

        except Exception as e:
            logger.warning(f"[WorkflowResourceManager] Failed to restore trigger node {node_id}: {e}")
            results['errors'].append({
                'node_id': node_id,
                'node_type': node_type,
                'error': str(e)
            })

    # Re-register provider-side endpoints for restored external-webhook
    # triggers. Failures leave the row inactive (deliveries 410) and the next
    # config-panel open retries with the error surfaced.
    try:
        reregistered = await WebhookManager.register_node_webhooks(
            pool, workflow_id, user_id,
            nodes=nodes,
            node_ids=list(node_ids_to_restore) if node_ids_to_restore is not None else None,
        )
        if reregistered:
            results['reregistered'] = reregistered
    except Exception as e:
        logger.warning(
            f"[WorkflowResourceManager] Provider re-registration failed for workflow {workflow_id}: {e}"
        )
        results['errors'].append({'resource': 'external_webhooks', 'error': str(e)})

    return results


def is_workflow_volume(name: str, workflow_id: str) -> bool:
    """Whether a volume belongs to this workflow, by the naming
    convention every agent volume family shares:
    ``noclick-{family}-{workflow_id}[-...]`` — families are single tokens
    (``ws``/``fs``/``cxsess``/``ccsess``/``ocsess``/``oclsess``/``hsess``) and
    the workflow id sits early enough to survive the 64-char name cap. Shape-
    matched (never a bare substring) so an id embedded elsewhere, or an id
    that PREFIXES another (``wf1`` vs ``wf12``), can never cross-delete."""
    import re

    return bool(re.match(
        rf"^noclick-[a-z0-9]+-{re.escape(workflow_id)}(-|$)", name
    ))


async def _cleanup_workflow_volumes(workflow_id: str) -> int:
    """Delete every volume whose name marks it as this workflow's, in one
    list pass. Per-volume failures are logged and skipped — a miss just
    leaves an orphan, and blocking the workflow deletion on it would be worse.
    Returns the number of volumes deleted."""
    from utils.volume_backend import get_volume_backend

    backend = get_volume_backend()
    deleted = 0
    for name in await backend.list_volume_names():
        if not is_workflow_volume(name, workflow_id):
            continue
        try:
            await backend.delete_volume(name)
            deleted += 1
            logger.info(f"[WorkflowResourceManager] Deleted volume {name}")
        except Exception as e:
            logger.warning(f"[WorkflowResourceManager] Volume {name} delete failed (orphaned): {e}")
    return deleted


async def _cleanup_filesystem_volumes(pool, workflow_id: str, node_ids: Optional[List[str]] = None) -> None:
    """
    Delete volumes associated with filesystem nodes.

    If node_ids is provided, only cleans up volumes for those specific nodes.
    Otherwise cleans up all filesystem node volumes for the workflow.
    """
    import json as _json

    from nodes.filesystem_node import get_volume_name
    from utils.volume_backend import get_volume_backend

    backend = get_volume_backend()

    # Find filesystem node IDs from the workflow data
    if node_ids is None:
        row = await pool.fetchrow("SELECT data FROM workflows WHERE id = $1", workflow_id)
        if not row or not row['data']:
            return
        data = _json.loads(row['data']) if isinstance(row['data'], str) else row['data']
        fs_node_ids = [n['id'] for n in data.get('nodes', []) if n.get('type') == 'filesystem']
    else:
        fs_node_ids = node_ids

    if not fs_node_ids:
        return

    deleted_count = 0
    for fs_node_id in fs_node_ids:
        common_name = get_volume_name(workflow_id, fs_node_id, "common")
        try:
            if await backend.delete_volume(common_name):
                deleted_count += 1
                logger.info(f"[WorkflowResourceManager] Deleted volume {common_name}")
        except Exception as e:
            logger.debug(f"[WorkflowResourceManager] Volume {common_name} delete skipped: {e}")

        # Delete per-conversation-key volumes by prefix match over the listing.
        try:
            prefix = common_name + "-"
            for name in await backend.list_volume_names():
                if name.startswith(prefix):
                    try:
                        await backend.delete_volume(name)
                        deleted_count += 1
                        logger.info(f"[WorkflowResourceManager] Deleted per-ck volume {name}")
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"[WorkflowResourceManager] Error listing volumes for cleanup: {e}")

    if deleted_count > 0:
        logger.info(f"[WorkflowResourceManager] Deleted {deleted_count} volume(s) for workflow {workflow_id}")


async def cleanup_expired_trashed_workflows(pool, retention_days: int = 30) -> Dict[str, int]:
    """
    Permanently delete workflows that have been in trash longer than retention_days.

    For each expired workflow, performs full resource cleanup (R2, node state,
    webhooks, cron, node outputs) before deleting the database row.

    Args:
        pool: Database connection pool (asyncpg)
        retention_days: Number of days to keep trashed workflows before permanent deletion

    Returns:
        Dict with 'deleted' count and 'total_found' count
    """
    rows = await pool.fetch("""
        SELECT id FROM workflows w
        WHERE deleted_at < NOW() - INTERVAL '1 day' * $1
          AND NOT EXISTS (
              SELECT 1 FROM workflow_executions e
              WHERE e.workflow_id = w.id
                AND e.status = 'running'
                AND e.finished_at IS NULL
          )
    """, retention_days)

    deleted_count = 0
    for row in rows:
        workflow_id = str(row['id'])
        try:
            await cleanup_workflow_resources(pool=pool, workflow_id=workflow_id)
            result = await pool.execute("""
                DELETE FROM workflows w
                WHERE id = $1
                  AND NOT EXISTS (
                      SELECT 1 FROM workflow_executions e
                      WHERE e.workflow_id = w.id
                        AND e.status = 'running'
                        AND e.finished_at IS NULL
                  )
            """, row['id'])
            if result == "DELETE 1":
                deleted_count += 1
                logger.info(f"[TrashCleanup] Permanently deleted workflow {workflow_id}")
            else:
                logger.info(
                    f"[TrashCleanup] Deferred workflow {workflow_id}; execution became active"
                )
        except Exception as e:
            logger.warning(f"[TrashCleanup] Failed to delete workflow {workflow_id}: {e}")

    logger.info(f"[TrashCleanup] Done: {deleted_count}/{len(rows)} workflows permanently deleted")
    return {"deleted": deleted_count, "total_found": len(rows)}
