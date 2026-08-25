"""
Workflow Checkpoint handler for managing workflow version control.
Allows users to save snapshots of their workflows and restore them later,
enabling version history and rollback functionality.
"""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from wss.sender.responses import (
    CheckpointInfo,
    WorkflowCheckpointListResponse,
    WorkflowCheckpointCreateResponse,
    WorkflowCheckpointRestoreResponse,
    WorkflowCheckpointDeleteResponse,
)
from wss.receiver.client_events import (
    WorkflowCheckpointCreateRequest,
    WorkflowCheckpointListRequest,
    WorkflowCheckpointRestoreRequest,
    WorkflowCheckpointDeleteRequest,
)
from utils.access_control import check_resource_access, Permission
from repositories.workflow import WorkflowRepo

logger = logging.getLogger(__name__)


class WorkflowCheckpointHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for workflow checkpoint operations with direct socket.io communication"""

    def __init__(self, sio):
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        """Register workflow checkpoint operation events"""
        return {
            "workflow:checkpoint:create": self.create_checkpoint,
            "workflow:checkpoint:list": self.list_checkpoints,
            "workflow:checkpoint:restore": self.restore_checkpoint,
            "workflow:checkpoint:delete": self.delete_checkpoint,
        }

    async def setup_user(self, sid: str) -> None:
        """Initialize database connection pool on user setup - non-blocking"""
        _ = sid  # Suppress unused parameter warning

    async def create_checkpoint(self, sid: str, request: WorkflowCheckpointCreateRequest) -> None:
        """Create a new checkpoint for a workflow"""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            async with pool.acquire() as conn:
                # Check access (owner, org member, or shared)
                access = await check_resource_access(
                    conn, user_id, "workflow", str(request.workflow_id)
                )

                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Workflow not found or access denied"
                    ))
                    return

                # Check checkpoint limit per workflow
                from billing.plan_limits import check_checkpoint_limit
                user_data = session.get('user_data', {})
                user_tier = user_data.get('subscription_tier', 'free')
                can_create, limit_error = await check_checkpoint_limit(
                    conn, user_id, user_tier, request.workflow_id
                )
                if not can_create:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error=limit_error
                    ))
                    return

                # Get the current workflow data
                repo = WorkflowRepo(pool)
                workflow_row = await repo.get_workflow_data(conn, request.workflow_id)

                if not workflow_row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Workflow not found"
                    ))
                    return

                workflow_data = workflow_row['workflow'] or {}

                # Create the checkpoint
                row = await repo.create_checkpoint(
                    conn,
                    user_id=user_id,
                    workflow_id=request.workflow_id,
                    name=request.name,
                    description=request.description or '',
                    workflow_data=workflow_data,
                )

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Failed to create checkpoint"
                    ))
                    return

                checkpoint = CheckpointInfo(
                    id=str(row['id']),
                    workflow_id=str(row['workflow_id']),
                    name=row['name'],
                    description=row['description'] or '',
                    created_at=row['created_at'].isoformat() if row.get('created_at') else ''
                )

                response = WorkflowCheckpointCreateResponse(
                    success=True,
                    checkpoint=checkpoint,
                    message="Checkpoint created successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"Error creating checkpoint: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def list_checkpoints(self, sid: str, request: WorkflowCheckpointListRequest) -> None:
        """List all checkpoints for a workflow, ordered by creation time (most recent first)"""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            async with pool.acquire() as conn:
                # Check access (owner, org member, or shared)
                access = await check_resource_access(
                    conn, user_id, "workflow", str(request.workflow_id)
                )

                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Workflow not found or access denied"
                    ))
                    return

                # Get all checkpoints for this workflow (all users' checkpoints if shared)
                rows = await WorkflowRepo(pool).list_checkpoints(conn, request.workflow_id)

            checkpoints = []
            for row in rows:
                checkpoints.append(CheckpointInfo(
                    id=str(row['id']),
                    workflow_id=str(row['workflow_id']),
                    name=row['name'],
                    description=row['description'] or '',
                    created_at=row['created_at'].isoformat() if row.get('created_at') else ''
                ))

            response = WorkflowCheckpointListResponse(checkpoints=checkpoints)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error listing checkpoints: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def restore_checkpoint(self, sid: str, request: WorkflowCheckpointRestoreRequest) -> None:
        """
        Restore a workflow to a specific checkpoint state.

        This performs a full restore including:
        - Updating the workflow in the database
        - Cleaning up webhooks/crons for nodes that are being removed
        - Re-registering webhooks and cron schedules for nodes that are being restored
        """
        from utils.workflow_resource_manager import cleanup_nodes_resources, restore_nodes_resources

        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            async with pool.acquire() as conn:
                # Check edit access (owner, org member, or shared with edit permission)
                access = await check_resource_access(
                    conn, user_id, "workflow", str(request.workflow_id)
                )

                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Workflow not found or access denied"
                    ))
                    return

                if access.permission not in (Permission.EDIT, Permission.OWNER):
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="You don't have permission to restore this workflow"
                    ))
                    return

                # Get checkpoint data and current workflow state
                repo = WorkflowRepo(pool)
                row = await repo.get_checkpoint_and_current(
                    conn, request.checkpoint_id, request.workflow_id,
                )

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Checkpoint not found"
                    ))
                    return

                checkpoint_workflow = row['checkpoint_workflow'] or {}
                current_workflow = row['current_workflow'] or {}

            # conn released — the resource cleanup/restore below calls the
            # external scheduler and webhook relay; those HTTP waits must not
            # hold a pinned pool connection.

            # Extract node IDs from both states
            checkpoint_nodes = checkpoint_workflow.get('nodes', [])
            current_nodes = current_workflow.get('nodes', [])

            checkpoint_node_ids = {node.get('id') for node in checkpoint_nodes if node.get('id')}
            current_node_ids = {node.get('id') for node in current_nodes if node.get('id')}

            # Calculate diff
            deleted_node_ids = list(current_node_ids - checkpoint_node_ids)  # Nodes being removed
            restored_node_ids = checkpoint_node_ids - current_node_ids  # Nodes being restored

            logger.info(f"[CHECKPOINT] Restoring workflow {request.workflow_id}: "
                       f"deleting {len(deleted_node_ids)} nodes, restoring {len(restored_node_ids)} nodes")

            # Clean up resources for nodes being removed (background for
            # fast restore). Pass the removed nodes' dicts: after the blob
            # update below, the live workflow no longer carries their
            # config (external_webhook_id etc.) needed for deregistration.
            if deleted_node_ids:
                _removed = set(deleted_node_ids)
                await cleanup_nodes_resources(
                    pool=pool,
                    workflow_id=request.workflow_id,
                    node_ids=deleted_node_ids,
                    background=True,
                    old_nodes=[n for n in current_nodes if n.get('id') in _removed],
                    requesting_user_id=user_id,
                )

            # Update the workflow in the database with checkpoint data
            async with pool.acquire() as conn:
                await repo.restore_workflow_from_checkpoint(
                    conn, request.workflow_id, checkpoint_workflow,
                )

            # Restore resources for restored nodes AFTER the blob update —
            # provider re-registration patches fresh webhook fields into
            # the blob's node configs, which the update would overwrite.
            # Spawned: provider API calls must not block the restore ack.
            if restored_node_ids:
                from utils.async_helpers import spawn
                spawn(
                    restore_nodes_resources(
                        pool=pool,
                        user_id=user_id,
                        workflow_id=request.workflow_id,
                        nodes=checkpoint_nodes,
                        node_ids_to_restore=restored_node_ids,
                    ),
                    name=f"checkpoint-restore-resources:{request.workflow_id}",
                )

            response = WorkflowCheckpointRestoreResponse(
                success=True,
                workflow=checkpoint_workflow,
                message="Checkpoint restored successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error restoring checkpoint: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def delete_checkpoint(self, sid: str, request: WorkflowCheckpointDeleteRequest) -> None:
        """Delete a checkpoint"""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            async with pool.acquire() as conn:
                # Only owner can delete (verified via user_id on checkpoint)
                result = await WorkflowRepo(pool).delete_checkpoint(
                    conn, request.checkpoint_id, user_id,
                )

                if result == "DELETE 0":
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Checkpoint not found or access denied"
                    ))
                    return

                response = WorkflowCheckpointDeleteResponse(
                    success=True,
                    message="Checkpoint deleted successfully",
                    checkpoint_id=request.checkpoint_id
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"Error deleting checkpoint: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))
