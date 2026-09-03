"""
Workflow handler for managing user workflows.
Handles workflow creation, listing, updating, and deletion.
"""

import asyncio
import json
import logging
from typing import Dict, Callable, Optional, Any
from utils.database_pool import DatabasePoolMixin
from utils.credentials import collect_node_credential_uuids, authorize_credentials_for_workflow
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from wss.sender.responses import (
    WorkflowInfo,
    WorkflowListResponse,
    WorkflowGetResponse,
    WorkflowCreateResponse,
    WorkflowUpdateResponse,
    WorkflowDeleteResponse,
    WorkflowRestoreResponse,
    WorkflowTrashInfo,
    WorkflowListTrashResponse,
    WorkflowPermanentDeleteResponse,
    WorkflowExecutionInfo,
    WorkflowExecutionListResponse,
    WorkflowExecutionCountsResponse,
    WorkflowNodeConfigSchemaResponse,
    WorkflowNodeValidateConfigResponse,
    WorkflowNodeLoadOptionsResponse,
    CredentialTestConnectionResponse,
    RehearsalRunResponse,
    RehearsalScenariosResponse,
    EvidenceSampleModel,
    WorkflowNodeLoadValueResponse,
    WorkflowCollabTokenResponse,
    FieldOption,
)
from wss.receiver.client_events import (
    WorkflowCreateRequest,
    WorkflowListRequest,
    WorkflowGetRequest,
    WorkflowUpdateRequest,
    WorkflowDeleteRequest,
    WorkflowRestoreRequest,
    WorkflowListTrashRequest,
    WorkflowPermanentDeleteRequest,
    WorkflowExecutionListRequest,
    WorkflowExecutionCountsRequest,
    WorkflowCollabTokenRequest,
    WorkflowNodeConfigSchemaRequest,
    WorkflowNodeValidateConfigRequest,
    WorkflowNodeEvaluateExpressionRequest,
    WorkflowNodeLoadOptionsRequest,
    CredentialTestConnectionRequest,
    RehearsalRunRequest,
    RehearsalScenariosRequest,
    WorkflowNodeLoadValueRequest,
    WorkflowClearNodeStateRequest,
    WorkflowSaveNodeStateRequest,
    WorkflowLoadNodeStateRequest,
    WebhookRelayReconnectRequest,
    NodeOutputSchemaRequest,
)
from utils.node_schema_tracker import get_schema_with_suggestions
from utils.encryption import get_encryption
from utils.workflow_resource_manager import cleanup_nodes_resources, cleanup_workflow_resources, cleanup_workflow_operational_resources
from utils.webhook_manager import WebhookManager
from utils.access_control import check_resource_access, Permission
from utils.slack import send_activity_notification_background, send_workflow_update_notification_background, extract_user_name
from utils.analytics import log_activity_background
from utils.analytics_events import Events
from repositories.workflow import WorkflowRepo
from repositories.organization import OrgRepo, PRIMARY_ORG_SQL
from repositories.credentials import credential_access_predicate
from nodes.agent.provider_errors import action_for_error_text

logger = logging.getLogger(__name__)


def _filter_input_nodes(outputs: dict, statuses: dict) -> list:
    """Build the input-node list for one delivery execution the run-results rail shows.

    Two guards:
    - IDOR: read_execution_outputs reads cas_manifests by execution_id ONLY, so gate
      every node on ``statuses`` — the set scoped to (execution_id, workflow_id). A
      foreign execution id (with the caller's own workflow_id passing the access check)
      yields an empty ``statuses``, so nothing leaks.
    - Plumbing: drop the agent's own 'awaiting_agent_turn' delivery marker and
      tool-provider metadata (node_op_tool_provider[_bundle]) — they rode the delivery
      execution but didn't feed the response.
    Restored context never reaches here: a delivery persists only what it ran
    (``workflow_execution_handler.outputs_to_persist``).
    """
    def _is_plumbing(out) -> bool:
        return isinstance(out, dict) and (
            out.get("status") == "awaiting_agent_turn"
            or out.get("type") in ("node_op_tool_provider", "node_op_tool_provider_bundle")
        )

    return [
        {"node_id": nid, "status": statuses[nid], "output": out}
        for nid, out in outputs.items()
        if nid in statuses and not _is_plumbing(out)
    ]


async def get_user_org_context(conn, user_id: str) -> Optional[str]:
    """
    Get the user's current organization context.

    Returns:
        The organization_id if user has an active org context (is_primary=true),
        or None if user is in personal context.
    """
    row = await conn.fetchrow(PRIMARY_ORG_SQL, user_id)
    return str(row["organization_id"]) if row else None


class WorkflowHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for workflow operations with direct socket.io communication"""

    def __init__(self, sio):
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        """Register workflow operation events"""
        return {
            "workflow:create": self.create_workflow,
            "workflow:list": self.list_workflows,
            "workflow:get": self.get_workflow,
            "workflow:update": self.update_workflow,
            "workflow:node:set_config": self.set_node_config,
            "workflow:node:get_config": self.get_node_config,
            "workflow:delete": self.delete_workflow,
            "workflow:restore": self.restore_workflow,
            "workflow:list_trash": self.list_trash_workflows,
            "workflow:permanent_delete": self.permanent_delete_workflow,
            "workflow:list_executions": self.list_executions,
            "workflow:get_execution_counts": self.get_execution_counts,
            "workflow:get_execution_detail": self.get_execution_detail,
            "workflow:get_node_output": self.get_node_output,
            "workflow:get_agent_inputs": self.get_agent_inputs,
            "workflow:collab_token": self.get_collab_token,
            "workflow:node:get_config_schema": self.get_node_config_schema,
            "workflow:node:validate_config": self.validate_node_config,
            "workflow:node:evaluate_expression": self.evaluate_expression,
            "workflow:node:load_options": self.load_node_options,
            "credential:test_connection": self.test_credential_connection,
            "rehearsal:run": self.run_rehearsal,
            "rehearsal:scenarios": self.list_rehearsal_scenarios,
            "workflow:node:load_value": self.load_node_value,
            "workflow:node:schema": self.get_node_output_schema,
            "workflow:clear_node_state": self.clear_node_state,
            "workflow:save_node_state": self.save_node_state,
            "workflow:load_node_state": self.load_node_state,
            "workflow:state:get": self.state_get,
            "workflow:state:set": self.state_set,
            "workflow:state:keys": self.state_keys,
            "webhook:relay:reconnect": self.reconnect_webhook_relay,
            "email:check_local_part": self.check_email_local_part,
            "email:reserve_address": self.reserve_email_address,
        }

    async def check_email_local_part(self, sid: str, data: dict) -> None:
        """Live availability check for an inbound-email local-part (email trigger node)."""
        request_id = data.get('request_id')
        try:
            from utils.email_reservation_manager import (
                EmailReservationManager, build_email_address, validate_local_part,
            )
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id, data={}, error="User not authenticated"))
                return

            local_part = (data.get('local_part') or '').strip().lower()
            is_valid, error_msg = validate_local_part(local_part)
            if not is_valid:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={'available': False, 'local_part': local_part, 'error': error_msg}))
                return

            pool = await self.get_pool()
            available = await EmailReservationManager.is_available(
                pool, local_part,
                exclude_workflow_id=data.get('workflow_id'),
                exclude_node_id=data.get('node_id'),
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'available': available,
                    'local_part': local_part,
                    'email_address': build_email_address(local_part),
                }))
        except Exception as e:
            logger.error(f"[Workflow] check_email_local_part error: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id, data={}, error=str(e)))

    async def reserve_email_address(self, sid: str, data: dict) -> None:
        """Reserve an inbound-email address for a workflow node (commit from the email trigger UI)."""
        request_id = data.get('request_id')
        try:
            from utils.email_reservation_manager import EmailReservationManager
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id, data={}, error="User not authenticated"))
                return

            workflow_id = data.get('workflow_id')
            node_id = data.get('node_id')
            local_part = (data.get('local_part') or '').strip().lower()
            if not workflow_id or not node_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id, data={}, error="workflow_id and node_id are required"))
                return

            pool = await self.get_pool()
            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", str(workflow_id))
            if not access.has_access:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id, data={}, error="Workflow not found or access denied"))
                return

            try:
                reserved = await EmailReservationManager.reserve(
                    pool, user_id, workflow_id, node_id, local_part)
            except ValueError as ve:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id, data={'success': False, 'error': str(ve)}))
                return

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'success': True,
                    'local_part': reserved['local_part'],
                    'email_address': reserved['email_address'],
                    'reservation_id': reserved['reservation_id'],
                }))
        except Exception as e:
            logger.error(f"[Workflow] reserve_email_address error: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id, data={}, error=str(e)))

    async def setup_user(self, sid: str) -> None:
        """Initialize database connection pool on user setup - non-blocking"""
        # Suppress unused parameter warning
        _ = sid

    async def create_workflow(self, sid: str, request: WorkflowCreateRequest) -> None:
        """Create a new workflow with visibility control (personal or organization)"""
        try:
            # Get user session
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

            # Use default permissions if not provided
            default_permissions = {"public": [], "shared_with": {}}
            permissions = request.permissions if request.permissions else default_permissions

            async with pool.acquire() as conn:
                # Get user's current organization context
                org_id = await get_user_org_context(conn, user_id)

                # Check workflow count limit
                from billing.plan_limits import check_workflow_limit
                user_data = session.get('user_data', {})
                user_tier = user_data.get('subscription_tier', 'free')
                can_create, limit_error = await check_workflow_limit(conn, user_id, user_tier)
                if not can_create:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error=limit_error
                    ))
                    from utils.capabilities import PLAN_GATE_ALERT, capability
                    alert_plan_gate = capability(PLAN_GATE_ALERT)
                    if alert_plan_gate is not None:
                        alert_plan_gate(user_data, "Workflow Limit Hit")
                    return

                repo = WorkflowRepo(pool)

                # Validate folder access if folder_id is provided
                if request.folder_id:
                    has_access = await OrgRepo(pool).can_access_folder(
                        conn, user_id, request.folder_id,
                    )

                    if not has_access:
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request.request_id,
                            data={},
                            error="Invalid folder or access denied"
                        ))
                        return

                # Insert workflow into database
                # When in org context, always set organization_id to keep resource in org
                # The visibility setting controls whether other org members can see it (via resource_shares)
                row = await repo.create_workflow(
                    conn,
                    owner_id=user_id,
                    organization_id=org_id,
                    folder_id=request.folder_id,
                    name=request.name,
                    description=request.description or '',
                    workflow_data=request.workflow_data or {},
                    permissions=permissions,
                )

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Failed to create workflow"
                    ))
                    return

                workflow_id = row['id']

                # If sharing with organization, create a resource_shares entry
                if request.visibility == 'organization' and org_id:
                    # Default to 'edit' permission if not specified
                    org_permission = request.organization_permission or 'edit'
                    if org_permission not in ('view', 'edit'):
                        org_permission = 'edit'

                    await repo.insert_workflow_org_share(
                        conn,
                        workflow_id=workflow_id,
                        organization_id=org_id,
                        permission=org_permission,
                        shared_by=user_id,
                    )

                # Convert to WorkflowInfo
                workflow = WorkflowInfo(
                    id=str(row['id']),
                    name=row['name'],
                    description=row['description'] or '',
                    workflow_data=row['workflow'] or {},
                    permissions=row['permissions'] or {"public": [], "shared_with": {}},
                    created_at=row['created_at'].isoformat() if row.get('created_at') else '',
                    updated_at=row['updated_at'].isoformat() if row.get('updated_at') else ''
                )

                # Send success response
                response = WorkflowCreateResponse(
                    success=True,
                    workflow=workflow,
                    message="Workflow created successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

                # Post-response telemetry: fire-and-forget so the blocking
                # PostHog flush never pins this pool connection (was a ~5s
                # connection-starvation stall on every create).
                log_activity_background(Events.WORKFLOW_CREATED, user_id, {
                    "workflow_id": str(workflow_id),
                    "organization_id": str(org_id) if org_id else None,
                    "visibility": request.visibility or "personal",
                    "has_folder": bool(request.folder_id),
                    "has_initial_data": bool(request.workflow_data),
                })

        except Exception as e:
            logger.error(f"Error creating workflow: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def list_workflows(self, sid: str, request: WorkflowListRequest) -> None:
        """List workflows based on user's organization context"""
        try:
            # Get user session
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
                # Scope from the request (browser passes it explicitly), falling
                # back to the active context for non-browser callers. Explicit
                # scoping is immune to the is_primary org-switch race.
                org_id = await OrgRepo(pool).resolve_scope_org_id(conn, user_id, request.scope_org_id)

                repo = WorkflowRepo(pool)
                if org_id:
                    # In org context: show user's private org workflows + workflows shared with this org.
                    # - Private org workflows: organization_id = org AND owner_id = user (no share needed)
                    # - Shared org workflows: any resource shared with this org (via resource_shares)
                    # folder_id filter semantics: None = show all, "" = root-level only, uuid = that folder.
                    rows = await repo.list_workflows_org(
                        conn, organization_id=org_id, user_id=user_id,
                        folder_id=request.folder_id,
                    )
                else:
                    # Personal context: owned personal + shared-with-user + shared-folder descendants.
                    # Same folder_id sentinel rules as the org branch.
                    rows = await repo.list_workflows_personal(
                        conn, user_id=user_id, folder_id=request.folder_id,
                    )

                # Tier lookup lives inside the acquire block. Prior to the
                # 2026-07-01 native-pool refactor, the non-pinning proxy
                # would silently re-acquire per method call, so this worked
                # dedented outside the block; native asyncpg correctly
                # invalidates conn after __aexit__, so it must be in-scope.
                from billing.plan_limits import get_context_tier, get_limit
                tier = await get_context_tier(conn, user_id)

            # Convert to WorkflowInfo objects
            workflows = []
            for row in rows:
                owner_id = str(row['owner_id']) if row.get('owner_id') else None
                is_owner = owner_id == user_id
                share_permission = row.get('share_permission')
                # Determine user's permission level
                if is_owner:
                    user_permission = 'owner'
                elif share_permission:
                    user_permission = share_permission  # 'edit' or 'view'
                else:
                    user_permission = None
                workflows.append(WorkflowInfo(
                    id=str(row['id']),
                    name=row['name'],
                    description=row['description'] or '',
                    workflow_data=row['workflow'] or {},
                    permissions=row['permissions'] or {"public": [], "shared_with": {}},
                    created_at=row['created_at'].isoformat() if row.get('created_at') else '',
                    updated_at=row['updated_at'].isoformat() if row.get('updated_at') else '',
                    display_metadata=row['display_metadata'] or {},
                    folder_id=str(row['share_target_folder_id']) if not is_owner and row.get('share_target_folder_id') else (str(row['folder_id']) if row.get('folder_id') else None),
                    is_owner=is_owner,
                    user_permission=user_permission,
                    owner_name=row.get('owner_display_name') if not is_owner else None
                ))

            # Enforce combined workflow cap: personal shown first, shared fills remaining slots
            hidden_shared_count = 0
            cap = get_limit(tier, 'workflows')
            if cap is not None:
                owned = [w for w in workflows if w.is_owner]
                shared = [w for w in workflows if not w.is_owner]
                shared_slots = max(0, cap - len(owned))
                if len(shared) > shared_slots:
                    hidden_shared_count = len(shared) - shared_slots
                    shared = shared[:shared_slots]
                workflows = owned + shared

            # Send response
            response = WorkflowListResponse(
                workflows=workflows,
                hidden_shared_count=hidden_shared_count,
                subscription_tier=tier,
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error listing workflows: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def get_workflow(self, sid: str, request: WorkflowGetRequest) -> None:
        """Get a specific workflow by ID (supports shared access)"""
        try:
            # Get user session
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
                # Check access (owner, direct share, or org share)
                access = await check_resource_access(
                    conn, user_id, "workflow", request.workflow_id
                )

                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Workflow not found or access denied"
                    ))
                    return

                # Fetch the workflow row and the per-node last-run status concurrently.
                # The status query is keyed by workflow_id (doesn't need the row first)
                # and hits its own pooled connection, so it runs in parallel and its
                # latency hides under the workflow fetch. It's enrichment, not load-
                # critical: a failure degrades to "no chips", never a failed open.
                async def _fetch_node_statuses() -> Dict[str, Any]:
                    try:
                        from utils import node_outputs
                        return await node_outputs.latest_statuses(pool, request.workflow_id)
                    except Exception as e:
                        logger.warning(f"[WorkflowGet] node status fetch failed (non-fatal): {e}", exc_info=True)
                        return {}

                repo = WorkflowRepo(pool)
                row, node_statuses = await asyncio.gather(
                    repo.get_workflow_full(conn, request.workflow_id),
                    _fetch_node_statuses(),
                )

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Workflow not found"
                    ))
                    return

                # Convert to WorkflowInfo with access info
                workflow = WorkflowInfo(
                    id=str(row['id']),
                    name=row['name'],
                    description=row['description'] or '',
                    workflow_data=row['workflow'] or {},
                    permissions=row['permissions'] or {"public": [], "shared_with": {}},
                    created_at=row['created_at'].isoformat() if row.get('created_at') else '',
                    updated_at=row['updated_at'].isoformat() if row.get('updated_at') else '',
                    display_metadata=row['display_metadata'] or {},
                    user_permission=access.permission.value,
                    is_owner=access.permission == Permission.OWNER,
                    settings=row.get('settings') or {},
                    graph_version=row.get('graph_version'),
                )

                # Send response — node_statuses rides along so the chips render in
                # the same paint as the graph (no second round-trip / pop-in).
                response = WorkflowGetResponse(workflow=workflow, node_statuses=node_statuses)
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"Error getting workflow: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def set_node_config(self, sid: str, request) -> None:
        """Merge config fields into a single node's config in the database."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="User not authenticated"))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="Database connection not available"))
                return

            async with pool.acquire() as conn:
                from utils.access_control import check_resource_access, Permission
                access = await check_resource_access(conn, user_id, "workflow", request.workflow_id)
                if not access.has_access or access.permission not in (Permission.EDIT, Permission.OWNER):
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error="No edit access"))
                    return

                # Strip internal runtime fields that SDK clients should not write
                _INTERNAL_FIELDS = {
                    'output', 'outputTimestamp', 'executionState', 'error',
                    'configValid', '_executionId', '_outputStoredLocally',
                    '_lastRunStatus', '_lastRunAt', '_lastRunError',
                }
                clean_config = {k: v for k, v in request.config.items() if k not in _INTERNAL_FIELDS}
                if not clean_config:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={"success": True}))
                    return

                repo = WorkflowRepo(pool)

                # Check if the incoming config changes the operation discriminator.
                # If so, read the old operation + node type so we can clean up
                # orphaned webhook/cron resources after the merge.
                old_operation = None
                node_type = None
                new_operation = clean_config.get("operation")
                if new_operation:
                    row = await repo.get_node_type_and_operation(
                        conn, request.workflow_id, request.node_id,
                    )
                    if row:
                        node_type = row["node_type"]
                        old_operation = row["old_operation"]

                # Atomically merge config fields into the target node using jsonb.
                # Uses a CTE to find the node index, then jsonb_set to merge config
                # in a single UPDATE — no read-modify-write race with frontend autosave.
                result = await repo.merge_node_config(
                    conn, request.workflow_id, request.node_id, clean_config,
                )

                if result == 'UPDATE 0':
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=f"Node {request.node_id} not found"))
                    return

                # Authorize credentials the OWNER set on this node for the run-as-owner
                # execution fallback. This is the SDK path (workflow:node:set_config is
                # SDK-only) — payload-scoped (only THIS request's credentialIds) and
                # owner-gated, so a collaborator can never authorize a new credential.
                if access.permission == Permission.OWNER and isinstance(clean_config.get('credentialIds'), dict):
                    try:
                        cred_ids = collect_node_credential_uuids(
                            {"nodes": [{"config": {"credentialIds": clean_config['credentialIds']}}]}
                        )
                        await authorize_credentials_for_workflow(
                            conn, request.workflow_id, user_id, cred_ids)
                    except Exception as e:
                        logger.warning(f"[Workflow] Failed to authorize owner credentials (set_node_config) for {request.workflow_id}: {e}")

            # Clean up orphaned webhook/cron if operation changed away from
            # one that required them (runs outside the connection context to
            # avoid holding the pool slot during external calls).
            if old_operation and new_operation and old_operation != new_operation and node_type:
                try:
                    from utils.webhook_manager import WebhookManager, _WEBHOOK_CONFIG_FIELDS
                    cleaned = await WebhookManager.handle_operation_change(
                        pool, node_type, request.workflow_id, request.node_id,
                        old_operation, new_operation, user_id=user_id,
                    )
                    # Strip only when the new op needs no webhook: a trigger→
                    # trigger change re-registers inside handle_operation_change
                    # and patches fresh webhook fields into the config — the
                    # strip would erase them.
                    if cleaned and not WebhookManager.operation_requires_webhook(node_type, new_operation):
                        # Strip stale poll-trigger fields from the config blob.
                        async with pool.acquire() as conn:
                            await WorkflowRepo(pool).strip_node_config_keys(
                                conn, request.workflow_id, request.node_id,
                                list(_WEBHOOK_CONFIG_FIELDS),
                            )
                except Exception as e:
                    logger.warning(f"[Workflow] Operation change cleanup error for {request.node_id}: {e}")

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={"success": True}))

        except Exception as e:
            logger.error(f"[Workflow] Error in set_node_config: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)))

    async def get_node_config(self, sid: str, request) -> None:
        """Get a single node's config from the database."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="User not authenticated"))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="Database connection not available"))
                return

            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", request.workflow_id)
                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error="Access denied"))
                    return

                row = await WorkflowRepo(pool).get_workflow_data(conn, request.workflow_id)
                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error="Workflow not found"))
                    return

                import json
                workflow = row['workflow']
                if isinstance(workflow, str):
                    workflow = json.loads(workflow)

                # Internal runtime fields that should not be exposed via SDK
                _INTERNAL_FIELDS = {
                    'output', 'outputTimestamp', 'executionState', 'error',
                    'configValid', '_executionId', '_outputStoredLocally',
                    '_lastRunStatus', '_lastRunAt', '_lastRunError',
                }

                for node in workflow.get('nodes', []):
                    if node.get('id') == request.node_id:
                        raw = node.get('config', {})
                        if isinstance(raw, dict):
                            config = {k: v for k, v in raw.items() if k not in _INTERNAL_FIELDS}
                        else:
                            config = {}
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request.request_id, data={"config": config}))
                        return

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error=f"Node {request.node_id} not found"))

        except Exception as e:
            logger.error(f"[Workflow] Error in get_node_config: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)))

    async def update_workflow(self, sid: str, request: WorkflowUpdateRequest) -> None:
        """Update a workflow's data or metadata (supports shared edit access)"""
        try:
            # Get user session
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
                # Check edit access (owner or edit permission)
                access = await check_resource_access(
                    conn, user_id, "workflow", request.workflow_id
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
                        error="You don't have permission to edit this workflow"
                    ))
                    return

                # Only owners can update permissions or settings
                if request.permissions is not None and access.permission != Permission.OWNER:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Only the owner can update sharing permissions"
                    ))
                    return

                if request.settings is not None and access.permission != Permission.OWNER:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Only the owner can update workflow settings"
                    ))
                    return

                # No updatable fields → surface distinct error before hitting SQL.
                has_updates = any(v is not None for v in (
                    request.name, request.description, request.workflow_data,
                    request.permissions, request.display_metadata, request.settings,
                ))
                if not has_updates:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="No updates specified"
                    ))
                    return

                # Dynamic UPDATE + CTE to capture old (name, workflow) in one query so
                # the caller can compute the Slack delta without a second read.
                repo = WorkflowRepo(pool)
                row = await repo.update_workflow_dynamic(
                    conn, request.workflow_id,
                    name=request.name,
                    description=request.description,
                    workflow_data=request.workflow_data,
                    permissions=request.permissions,
                    display_metadata=request.display_metadata,
                    settings=request.settings,
                    expected_graph_version=request.expected_graph_version,
                )

                # CAS miss: the row exists but another writer bumped
                # graph_version since this client loaded. Return the current
                # blob + version so the client rebases instead of clobbering.
                if (
                    not row
                    and request.workflow_data is not None
                    and request.expected_graph_version is not None
                ):
                    current = await repo.get_workflow_full(conn, request.workflow_id)
                    if current:
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request.request_id,
                            data={
                                "conflict": True,
                                "graph_version": current.get('graph_version'),
                                "workflow_data": current['workflow'] or {},
                            },
                        ))
                        return
            # conn released above — the tail below does provider/webhook HTTP
            # and R2 cleanup, which must never hold a pinned pool connection.

            if not row:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Workflow not found or update failed"
                ))
                return

            # Convert to WorkflowInfo with access info
            # Only include workflow_data in response if it was actually updated
            # This prevents stale data from overwriting frontend state during metadata-only updates
            workflow = WorkflowInfo(
                id=str(row['id']),
                name=row['name'],
                description=row['description'] or '',
                workflow_data=row['workflow'] or {} if request.workflow_data is not None else None,
                permissions=row['permissions'] or {"public": [], "shared_with": {}},
                created_at=row['created_at'].isoformat() if row.get('created_at') else '',
                updated_at=row['updated_at'].isoformat() if row.get('updated_at') else '',
                display_metadata=row['display_metadata'] or {},
                user_permission=access.permission.value,
                is_owner=access.permission == Permission.OWNER,
                settings=row.get('settings') or {},
                graph_version=row.get('graph_version'),
            )

            # Cleanup resources for deleted nodes (fire-and-forget).
            # Pass the OLD node dicts: this UPDATE already persisted the
            # node-less workflow, so the live blob no longer carries the
            # deleted nodes' external_webhook_id needed to deregister.
            if request.deleted_node_ids:
                old_deleted_nodes = None
                if row.get('old_workflow'):
                    try:
                        _ow = row['old_workflow'] if isinstance(row['old_workflow'], dict) else json.loads(row['old_workflow'])
                        _targets = set(request.deleted_node_ids)
                        old_deleted_nodes = [
                            n for n in _ow.get('nodes', []) if n.get('id') in _targets
                        ]
                    except Exception as e:
                        logger.warning(f"[Workflow] Could not extract old deleted-node configs: {e}")
                # background=True: provider deregistration (credential
                # decrypt + OAuth freshen + HTTP) must not block the save
                # ack nor pin a pool connection.
                await cleanup_nodes_resources(
                    pool=pool,
                    workflow_id=request.workflow_id,
                    node_ids=request.deleted_node_ids,
                    background=True,
                    old_nodes=old_deleted_nodes,
                    requesting_user_id=user_id,
                )
                # Release inbound-email reservations held by removed nodes
                try:
                    from utils.email_reservation_manager import EmailReservationManager
                    await EmailReservationManager.release_many(
                        pool, request.workflow_id, request.deleted_node_ids
                    )
                except Exception as e:
                    logger.warning(f"[Workflow] Failed to release email reservations for deleted nodes: {e}")

            # Detect operation changes and credential swaps, cleaning up
            # any provider-side webhook registrations against the OLD
            # operation / OLD credential. Without the credential branch,
            # swapping the credential on a trigger node leaks an active
            # provider config on the previous connection — every event
            # that arrives on that connection still fans out to the
            # orphan and produces a duplicate workflow run. (Verified
            # 2026-06-25 against a WhatsApp/WAHooks user whose group
            # chats hit both old and new connections.)
            # Spawned: the handlers make provider API calls (teardown +
            # self-heal re-registration) that must not block the save ack
            # or pin a pool connection.
            if request.workflow_data is not None and row.get('old_workflow'):
                try:
                    from utils.async_helpers import spawn
                    old_wf = row['old_workflow'] if isinstance(row['old_workflow'], dict) else json.loads(row['old_workflow'])
                    new_wf = row['workflow'] if isinstance(row['workflow'], dict) else json.loads(row['workflow'])

                    async def _handle_config_changes(
                        _pool=pool, _wid=request.workflow_id, _uid=user_id,
                        _old_wf=old_wf, _new_wf=new_wf,
                    ):
                        from utils.webhook_manager import WebhookManager
                        old_nodes = {n.get('id'): n for n in _old_wf.get('nodes', [])}
                        new_node_ids = set()
                        for new_node in _new_wf.get('nodes', []):
                            nid = new_node.get('id')
                            new_node_ids.add(nid)
                            old_node = old_nodes.get(nid)
                            if not old_node:
                                continue
                            old_cfg = old_node.get('config', {})
                            new_cfg = new_node.get('config', {})
                            if isinstance(old_node.get('data'), dict):
                                old_cfg = old_node['data'].get('config', old_cfg)
                            if isinstance(new_node.get('data'), dict):
                                new_cfg = new_node['data'].get('config', new_cfg)
                            old_op = old_cfg.get('operation')
                            new_op = new_cfg.get('operation')
                            n_type = new_node.get('type', '')
                            if old_op and new_op and old_op != new_op:
                                await WebhookManager.handle_operation_change(
                                    _pool, n_type, _wid, nid,
                                    old_op, new_op,
                                    old_config=old_cfg, user_id=_uid,
                                )
                            await WebhookManager.handle_credential_change(
                                _pool, n_type, _wid, nid,
                                old_cfg, new_cfg, _uid,
                            )
                            # Registration-relevant field edits (PostHog
                            # event_name, GitHub repository) with the same
                            # op/credentials reconcile too — otherwise the
                            # provider registration silently stays on the
                            # OLD value until a panel reopen.
                            await WebhookManager.handle_registration_fields_change(
                                _pool, n_type, _wid, nid,
                                old_cfg, new_cfg, user_id=_uid,
                            )
                        # Re-added nodes (canvas undo of a delete): their
                        # rows were deactivated at delete time; re-register
                        # the previously-registered triggers among them.
                        readded = [
                            nid for nid in new_node_ids
                            if nid and nid not in old_nodes
                        ]
                        if readded:
                            await WebhookManager.register_node_webhooks(
                                _pool, _wid, _uid, node_ids=readded
                            )

                    spawn(
                        _handle_config_changes(),
                        name=f"workflow-config-change-hooks:{request.workflow_id}",
                    )
                except Exception as e:
                    logger.warning(f"[Workflow] Operation/credential change detection error: {e}")

            # NOTE: credentials are deliberately NOT authorized for run-as-owner
            # resolution here. This save persists the full workflow blob, which is
            # presence-tainted: a collaborator with edit access can inject arbitrary
            # credentialIds onto the owner's in-memory graph via the workflow relay
            # presence channel, and the owner's autosave would then persist them.
            # Authorizing off this blob (even the delta vs the prior blob) would let
            # a collaborator-injected owner-credential ride into the authorized set.
            # Authorization comes only from trusted, owner-attributed signals:
            #   - the explicit owner-pick event (credential:authorize_for_workflow)
            #   - the SDK set_node_config path (owner-gated, payload-scoped)
            #   - the external MCP server + internal builder (server-attributed)

            # Send success response
            response = WorkflowUpdateResponse(
                success=True,
                workflow=workflow,
                message="Workflow updated successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))

            # Send Slack notification for meaningful workflow changes
            if request.workflow_data is not None:
                user_data = session.get('user_data', {})
                user_name = extract_user_name(user_data)
                user_email = user_data.get('email', 'unknown@example.com')
                slack_thread_ts = session.get('slack_thread_ts')
                send_workflow_update_notification_background(
                    user_name, user_email,
                    workflow_name=row['name'] or row['old_name'] or 'Untitled',
                    old_workflow=row['old_workflow'],
                    new_workflow=request.workflow_data,
                    deleted_node_ids=request.deleted_node_ids,
                    thread_ts=slack_thread_ts
                )

        except Exception as e:
            logger.error(f"Error updating workflow: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def delete_workflow(self, sid: str, request: WorkflowDeleteRequest) -> None:
        """Delete a workflow"""
        try:
            # Get user session
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

            # Verify workflow exists and belongs to user before cleanup
            repo = WorkflowRepo(pool)
            async with pool.acquire() as conn:
                exists = await repo.workflow_exists_for_owner(
                    conn, request.workflow_id, user_id,
                )

            if not exists:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Workflow not found"
                ))
                return

            # Cleanup operational resources (cron + webhooks) before trashing,
            # but preserve R2 storage, node state, and workflow_resources for
            # restore. Runs connection-free: it calls the external scheduler /
            # relay and must not hold a pinned pool connection.
            await cleanup_workflow_operational_resources(
                pool=pool,
                workflow_id=request.workflow_id
            )

            # Soft-delete: move to trash instead of permanent deletion
            async with pool.acquire() as conn:
                await repo.soft_delete_workflow(conn, request.workflow_id, user_id)

            response = WorkflowDeleteResponse(
                success=True,
                message="Workflow moved to trash",
                workflow_id=request.workflow_id
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error deleting workflow: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def list_trash_workflows(self, sid: str, request: WorkflowListTrashRequest) -> None:
        """List all soft-deleted (trashed) workflows for the current user"""
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
                rows = await WorkflowRepo(pool).list_trash(conn, user_id)

            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            workflows = []
            for row in rows:
                deleted_at = row['deleted_at']
                days_elapsed = (now - deleted_at).days
                days_remaining = max(0, 30 - days_elapsed)
                workflows.append(WorkflowTrashInfo(
                    id=str(row['id']),
                    name=row['name'],
                    description=row['description'] or "",
                    deleted_at=deleted_at.isoformat(),
                    days_remaining=days_remaining,
                ))

            response = WorkflowListTrashResponse(workflows=workflows)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error listing trashed workflows: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def restore_workflow(self, sid: str, request: WorkflowRestoreRequest) -> None:
        """Restore a soft-deleted workflow from trash"""
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
                result = await WorkflowRepo(pool).restore_workflow(
                    conn, request.workflow_id, user_id,
                )

                if result == 'UPDATE 0':
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Workflow not found in trash"
                    ))
                    return

            # Restore cron schedules and re-register external webhooks (Stripe, Linear, etc.)
            # in the background so restore response isn't blocked by provider API calls.
            try:
                async with pool.acquire() as conn:
                    wf_row = await conn.fetchrow(
                        "SELECT workflow FROM workflows WHERE id = $1", request.workflow_id
                    )
                if wf_row:
                    nodes = (wf_row["workflow"] or {}).get("nodes", [])
                    from utils.async_helpers import spawn
                    from utils.workflow_resource_manager import restore_nodes_resources

                    # restore_nodes_resources re-activates simple trigger rows,
                    # restores cron schedules, AND re-registers provider-side
                    # webhooks for previously-registered trigger nodes.
                    spawn(
                        restore_nodes_resources(
                            pool=pool, user_id=user_id,
                            workflow_id=str(request.workflow_id), nodes=nodes,
                        ),
                        name=f"workflow-restore:{request.workflow_id}",
                    )
            except Exception as e:
                logger.warning(f"[Workflow] Failed to spawn restore resource job: {e}")

            response = WorkflowRestoreResponse(
                success=True,
                message="Workflow restored successfully",
                workflow_id=request.workflow_id,
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error restoring workflow: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def permanent_delete_workflow(self, sid: str, request: WorkflowPermanentDeleteRequest) -> None:
        """Permanently delete a trashed workflow (no recovery)"""
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
                # Verify ownership and that it's in trash
                exists = await WorkflowRepo(pool).workflow_in_trash_for_owner(
                    conn, request.workflow_id, user_id,
                )

                if not exists:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Workflow not found in trash"
                    ))
                    return

            # A run may have started before the workflow was moved to trash and
            # may live on another managed worker. Stop it through workflow relay
            # and wait for its DB row to become terminal before deleting parent
            # rows/resources. If it cannot stop promptly, leave the workflow in
            # trash and let the user retry instead of racing its side effects.
            from utils.execution_stop import stop_running_workflow_executions
            remaining = await stop_running_workflow_executions(
                pool, request.workflow_id, user_id,
            )
            if remaining:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=(
                        "Workflow still has an active execution. It was asked to "
                        "stop; wait a moment and try permanent deletion again."
                    ),
                ))
                return

            # Full resource cleanup (R2 + everything)
            await cleanup_workflow_resources(
                pool=pool,
                workflow_id=request.workflow_id
            )

            async with pool.acquire() as conn:
                deleted = await WorkflowRepo(pool).hard_delete_workflow(
                    conn, request.workflow_id, user_id,
                )
            if not deleted:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=(
                        "Workflow could not be permanently deleted because an "
                        "execution is still active. Try again shortly."
                    ),
                ))
                return

            response = WorkflowPermanentDeleteResponse(
                success=True,
                message="Workflow permanently deleted",
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error permanently deleting workflow: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def list_executions(self, sid: str, request: WorkflowExecutionListRequest) -> None:
        """List one page of execution logs for a workflow.

        Filters (status, trigger_source, search-on-error), cursor pagination
        keyed on ``(started_at, id)``, and access check. The single SELECT is
        served by ``idx_workflow_executions_workflow_started`` — an index-range
        scan over the workflow's slice in started_at-desc order, so each page
        costs ~one probe regardless of total table size."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="User not authenticated"))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="Database connection not available"))
                return

            from datetime import datetime
            import uuid
            limit = max(1, min(int(request.limit or 50), 200))
            status_filter = list(request.status) if request.status else None
            trigger_filter = list(request.trigger_source) if request.trigger_source else None
            search = (request.search or '').strip() or None
            # Parse cursor — both fields must be present for it to apply.
            cursor_ts = None
            cursor_id = None
            if request.cursor_started_at and request.cursor_id:
                try:
                    cursor_ts = datetime.fromisoformat(request.cursor_started_at.replace('Z', '+00:00'))
                    cursor_id = uuid.UUID(request.cursor_id)
                except Exception:
                    # Invalid cursor — treat as "fetch first page" rather than failing.
                    cursor_ts, cursor_id = None, None

            async with pool.acquire() as conn:
                access = await check_resource_access(
                    conn, user_id, "workflow", request.workflow_id
                )
                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={},
                        error="Workflow not found or access denied"))
                    return

                rows = await WorkflowRepo(pool).list_executions(
                    conn,
                    workflow_id=request.workflow_id,
                    status_filter=status_filter,
                    trigger_filter=trigger_filter,
                    search=search,
                    cursor_ts=cursor_ts,
                    cursor_id=cursor_id,
                    limit=limit,
                )

            executions = []
            for row in rows:
                executions.append(WorkflowExecutionInfo(
                    id=str(row['id']),
                    workflow_id=str(row['workflow_id']),
                    user_id=str(row['user_id']),
                    status=row['status'],
                    started_at=row['started_at'].isoformat() if row.get('started_at') else '',
                    finished_at=row['finished_at'].isoformat() if row.get('finished_at') else None,
                    nodes_executed=row['nodes_executed'] or 0,
                    error=row['error'],
                    trigger_source=row.get('trigger_source'),
                    has_graph=bool(row.get('graph_hash')),
                ))

            # Cursor for the next page = the LAST row's (started_at, id). Null
            # when the page wasn't full (caller knows it's the last one).
            next_started_at = None
            next_id = None
            if len(executions) == limit and rows:
                last = rows[-1]
                next_started_at = last['started_at'].isoformat() if last.get('started_at') else None
                next_id = str(last['id'])

            response = WorkflowExecutionListResponse(
                executions=executions,
                next_cursor_started_at=next_started_at,
                next_cursor_id=next_id,
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()))

        except Exception as e:
            logger.error(f"Error listing workflow executions: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)))

    async def get_execution_counts(self, sid: str, request: WorkflowExecutionCountsRequest) -> None:
        """Return per-status / per-trigger / total counts for a workflow.

        Single GROUPING SETS query — served as an Index-Only Scan over the
        workflow's slice of idx_workflow_executions_workflow_started (status +
        trigger_source live in the index's INCLUDE clause, so at prod scale
        this aggregate never touches the heap)."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="User not authenticated"))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="Database connection not available"))
                return

            async with pool.acquire() as conn:
                access = await check_resource_access(
                    conn, user_id, "workflow", request.workflow_id
                )
                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={},
                        error="Workflow not found or access denied"))
                    return

                # GROUPING SETS: one query returns three logical aggregates.
                #   gid bitmask (status_grouped, trigger_grouped):
                #     0b11=3 → total (both columns grouped out)
                #     0b10=2 → per-trigger row (status is NULL/grouped, trigger is value)
                #     0b01=1 → per-status row (status is value, trigger is NULL/grouped)
                rows = await WorkflowRepo(pool).execution_counts(
                    conn, request.workflow_id,
                )

            total = 0
            by_status: Dict[str, int] = {}
            by_trigger: Dict[str, int] = {}
            for row in rows:
                gid = row['gid']
                n = int(row['n'])
                if gid == 3:
                    total = n
                elif gid == 2 and row['trigger_source'] is not None:
                    # status grouped out → per-trigger count. (trigger_source is
                    # NOT NULL in the table; the None check is defensive.)
                    by_trigger[row['trigger_source']] = n
                elif gid == 1 and row['status'] is not None:
                    # trigger grouped out → per-status count.
                    by_status[row['status']] = n

            response = WorkflowExecutionCountsResponse(
                total=total, by_status=by_status, by_trigger=by_trigger,
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()))

        except Exception as e:
            logger.error(f"Error getting workflow execution counts: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)))

    async def get_execution_detail(self, sid: str, request: "WorkflowExecutionDetailRequest") -> None:
        """Return one past run's graph snapshot + per-node status/error metadata
        (node outputs fetched lazily via workflow:get_node_output). CAS-backed."""
        import uuid as uuid_module
        from utils.cas import store as cas_store
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            pool = await self.get_pool()
            if not user_id or not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={},
                    error="User not authenticated" if not user_id else "Database connection not available"))
                return
            try:
                ex = uuid_module.UUID(request.execution_id)
                wf = uuid_module.UUID(request.workflow_id)
            except (ValueError, TypeError):
                # Non-UUID id (e.g. an optimistic "run-<ts>" entry that never resolved
                # to a real execution) — no such run; return empty, don't error.
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id, data={}))
                return
            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", request.workflow_id)
                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={},
                        error="Workflow not found or access denied"))
                    return
                repo = WorkflowRepo(pool)
                exec_row = await repo.get_execution_detail(conn, ex, wf)
                if not exec_row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error="Execution not found"))
                    return
                node_rows = await repo.list_cas_manifest_status(conn, ex, wf)
                # Agent tool calls made during this run (recorded at
                # tool_execution.execute_tool) — lets the log viewer show
                # exactly which tools ran, with which credential, how long.
                tool_call_rows = await repo.list_tool_calls_for_execution(conn, ex)

            graph = await cas_store.read_graph(pool, execution_id=ex)
            execution = WorkflowExecutionInfo(
                id=str(exec_row['id']), workflow_id=str(exec_row['workflow_id']),
                user_id=str(exec_row['user_id']), status=exec_row['status'],
                started_at=exec_row['started_at'].isoformat() if exec_row.get('started_at') else '',
                finished_at=exec_row['finished_at'].isoformat() if exec_row.get('finished_at') else None,
                nodes_executed=exec_row['nodes_executed'] or 0, error=exec_row['error'],
                trigger_source=exec_row.get('trigger_source'),
                has_graph=bool(exec_row.get('graph_hash')),
            )
            # Re-derive the actionable button for stored failures, so browsing a
            # past run offers the same fix the live one did. Derivation rather
            # than storage: the persisted message already carries the provider's
            # verbatim text after "Provider message:", so it re-classifies to
            # the same (provider, kind) — and asking for the ACTION never
            # rewrites, so a message cannot get wrapped a second time. Node
            # types come from the run's graph snapshot: provider-branded
            # actions need model-provider provenance (a pruned/missing graph
            # degrades to platform-tier actions only).
            node_types = {
                n.get("id"): n.get("type")
                for n in (graph.get("nodes", []) if isinstance(graph, dict) else [])
            }
            node_results = [{
                "node_id": r["node_id"],
                "last_run_status": r["last_run_status"],
                "last_run_error": r["last_run_error"],
                "last_run_error_action": action_for_error_text(
                    r["last_run_error"], node_type=node_types.get(r["node_id"])),
                "has_output": r["has_output"],
            } for r in node_rows]
            tool_calls = [{
                "agent_node_id": r["agent_node_id"],
                "tool_name": r["tool_name"],
                "tool_type": r["tool_type"],
                "provider_node_id": r["provider_node_id"],
                "operation": r["operation"],
                "credential_id": str(r["credential_id"]) if r["credential_id"] else None,
                "arguments": r["arguments"],
                "result_status": r["result_status"],
                "error": r["error"],
                "result_preview": r["result_preview"],
                "duration_ms": r["duration_ms"],
                "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
            } for r in tool_call_rows]
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"execution": execution.model_dump(), "graph": graph,
                      "node_results": node_results, "tool_calls": tool_calls}))
        except Exception as e:
            logger.error(f"Error getting execution detail: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)))

    async def get_agent_inputs(self, sid: str, request: "WorkflowAgentInputsRequest") -> None:
        """Resolve the delivery executions an agent response consumed (its
        `input_execution_ids`) into the nodes that ran per delivery, for the run-results
        inputs rail. Those runs are hidden plumbing (status 'delivered', never listed),
        so this reads their CAS outputs directly by execution id. Capped: a flood agent
        can consume many events; the popup shows the true total separately and only
        needs the recent ones to drill into."""
        import uuid as uuid_module

        from utils.cas import store as cas_store

        _MAX_INPUTS = 15
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            pool = await self.get_pool()
            if not user_id or not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={},
                    error="User not authenticated" if not user_id else "Database connection not available"))
                return
            try:
                wf = uuid_module.UUID(request.workflow_id)
            except (ValueError, TypeError):
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id, data={"inputs": []}))
                return
            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", request.workflow_id)
                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error="Workflow not found or access denied"))
                    return

            inputs = []
            # The most RECENT deliveries (the list is chronological, oldest→newest) —
            # those are what a user drills into; inputs_total shows the true count.
            for raw in request.execution_ids[-_MAX_INPUTS:]:
                try:
                    ex = uuid_module.UUID(str(raw))
                except (ValueError, TypeError):
                    continue
                async with pool.acquire() as conn:
                    status_rows = await conn.fetch(
                        "SELECT node_id, last_run_status FROM cas_manifests "
                        "WHERE execution_id = $1 AND workflow_id = $2", ex, wf)
                statuses = {r["node_id"]: r["last_run_status"] for r in status_rows}
                outputs = await cas_store.read_execution_outputs(pool, ex)
                # Workflow-scope (IDOR) guard + plumbing filter — see _filter_input_nodes.
                nodes = _filter_input_nodes(outputs, statuses)
                if nodes:
                    inputs.append({"execution_id": str(raw), "nodes": nodes})
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={"inputs": inputs}))
        except Exception as e:
            logger.error(f"Error resolving agent inputs: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)))

    async def get_node_output(self, sid: str, request: "WorkflowNodeOutputRequest") -> None:
        """Lazily reassemble one node's output for a past run (CAS-backed,
        workflow-scoped). A pruned chunk renders as 'output no longer retained'."""
        from utils.cas import store as cas_store
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            pool = await self.get_pool()
            if not user_id or not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={},
                    error="User not authenticated" if not user_id else "Database connection not available"))
                return
            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", request.workflow_id)
            if not access.has_access:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={},
                    error="Workflow not found or access denied"))
                return
            output = await cas_store.read_node_output(
                pool, execution_id=request.execution_id, node_id=request.node_id,
                workflow_id=request.workflow_id)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"node_id": request.node_id, "output": output}))
        except Exception as e:
            logger.error(f"Error getting node output: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)))

    async def get_collab_token(self, sid: str, request: WorkflowCollabTokenRequest) -> None:
        """Generate a JWT token for workflow relay collaborative presence.

        The token is used to authenticate with the configured workflow relay
        for real-time cursor/selection sharing between users editing the same workflow.
        """
        import os
        import time
        import jwt

        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            user_data = session.get('user_data', {})
            # Extract name from user_metadata (Supabase stores it there)
            user_metadata = user_data.get('user_metadata', {})
            user_name = (
                user_metadata.get('full_name') or
                user_metadata.get('name') or
                user_data.get('email', '').split('@')[0] or
                'Anonymous'
            )
            avatar_url = user_metadata.get('avatar_url') or user_metadata.get('picture')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowCollabTokenResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            # Verify user has access to this workflow
            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowCollabTokenResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            async with pool.acquire() as conn:
                # Check access (owner, direct share, or org share)
                access = await check_resource_access(
                    conn, user_id, "workflow", request.workflow_id
                )

                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=WorkflowCollabTokenResponse(
                            success=False,
                            message="Workflow not found or access denied"
                        ).model_dump()
                    ))
                    return

            # Generate JWT token
            jwt_secret = os.environ.get('WORKFLOW_JWT_SECRET')
            if not jwt_secret:
                logger.error("WORKFLOW_JWT_SECRET not configured")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowCollabTokenResponse(
                        success=False,
                        message="Collaboration not configured"
                    ).model_dump()
                ))
                return

            now = int(time.time())
            expires_at = now + 3600  # 1 hour expiry

            payload = {
                "sub": user_id,
                "workflowId": request.workflow_id,
                "name": user_name,
                "avatarUrl": avatar_url,
                "iat": now,
                "exp": expires_at,
            }

            token = jwt.encode(payload, jwt_secret, algorithm="HS256")

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WorkflowCollabTokenResponse(
                    success=True,
                    token=token,
                    expires_at=expires_at
                ).model_dump()
            ))

        except Exception as e:
            logger.error(f"Error generating collab token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WorkflowCollabTokenResponse(
                    success=False,
                    message=str(e)
                ).model_dump()
            ))

    async def get_node_config_schema(self, sid: str, request: WorkflowNodeConfigSchemaRequest) -> None:
        """Get configuration schema for a node type (returns JSON Schema)"""
        try:
            # Import node factory to get node class
            from nodes.core.registry import NODE_REGISTRY

            # Get node class from registry
            node_class = NODE_REGISTRY.get(request.node_type)
            if not node_class:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=f"Unknown node type: {request.node_type}"
                ))
                return

            # Get JSON schema from node class. Off-loop: get_config_schema runs
            # Pydantic json_schema generation, heavy pure CPU for large
            # discriminated-union nodes (e.g. Slack, ~231 members), which
            # otherwise blocks the event loop and starves co-resident handlers.
            schema = await asyncio.to_thread(node_class.get_config_schema)

            if not schema:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=f"No schema defined for node type: {request.node_type}"
                ))
                return

            # Send response with full JSON Schema
            response = WorkflowNodeConfigSchemaResponse(
                node_type=request.node_type,
                config_schema=schema
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error getting node config schema: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def validate_node_config(self, sid: str, request: WorkflowNodeValidateConfigRequest) -> None:
        """Validate a node's configuration"""
        try:
            # Import node factory to get node class
            from nodes.core.registry import NODE_REGISTRY

            # Get node class from registry
            node_class = NODE_REGISTRY.get(request.node_type)
            if not node_class:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=f"Unknown node type: {request.node_type}"
                ))
                return

            # Frontend sends flat config (schema fields only); validate_saved_config
            # wraps it into the NodeConfig shape when the model expects it.
            # Off-loop: validate_config -> Pydantic validate_python is heavy pure CPU
            # for large discriminated-union nodes (e.g. Slack, ~231 members) and
            # otherwise blocks the event loop, starving co-resident handlers.
            validation_result = await asyncio.to_thread(
                node_class.validate_saved_config, request.config_data
            )

            # Send response
            response = WorkflowNodeValidateConfigResponse(
                valid=validation_result["valid"],
                errors=validation_result["errors"],
                satisfied_set=validation_result["satisfied_set"]
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error validating node config: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def evaluate_expression(self, sid: str, request: WorkflowNodeEvaluateExpressionRequest) -> None:
        """Evaluate a single inline expression for the editor's live preview, against
        the connected nodes' sample outputs the client supplies. Stateless — runs the
        same sandboxed evaluator the runtime uses; returns the computed value or the
        error message. QuickJS is heavy pure CPU, so dispatch off the event loop."""
        try:
            from utils.expression_evaluator import (
                evaluate_single_expression,
                ExpressionEvaluationError,
                format_preview,
                format_preview_tokens,
            )

            try:
                result = await evaluate_single_expression(
                    request.expression,
                    request.sample_outputs or {},
                    workflow_nodes=request.workflow_nodes,
                    primary_input=request.primary_input,
                )
                # Send the value's KIND + object KEYS (so the builder can offer Fields and
                # type-appropriate transforms) plus a compact, clipped PREVIEW string (so a
                # big output isn't dumped or shipped whole over the socket each keystroke).
                if isinstance(result, dict):
                    kind, keys = "object", list(result.keys())[:50]
                elif isinstance(result, bool):
                    kind, keys = "boolean", None
                elif isinstance(result, list):
                    kind, keys = "array", None
                elif isinstance(result, (int, float)):
                    kind, keys = "number", None
                elif result is None:
                    kind, keys = "null", None
                else:
                    kind, keys = "string", None
                data = {
                    "ok": True,
                    "kind": kind,
                    "keys": keys,
                    "preview": format_preview(result),
                    "preview_tokens": format_preview_tokens(result),
                }
            except ExpressionEvaluationError as eval_err:
                data = {"ok": False, "error": eval_err.js_error}

            await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id, data=data))
        except Exception as e:
            logger.error(f"Error evaluating expression: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def list_rehearsal_scenarios(self, sid: str, request: RehearsalScenariosRequest) -> None:
        """What this workflow can rehearse, from its saved graph."""
        from nodes.agent.rehearsal_scenarios import staged_for_graph

        session = await self.sio.get_session(sid)
        user_id = session.get('user_id')
        if not user_id:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=RehearsalScenariosResponse(success=False, message="User not authenticated").model_dump(),
            ))
            return

        from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

        fetched = await WorkflowExecutionHandler(self.sio)._fetch_workflow(request.workflow_id, user_id)
        if not fetched:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=RehearsalScenariosResponse(success=False, message="Workflow not found").model_dump(),
            ))
            return
        nodes, edges = fetched[0], fetched[1]

        try:
            staged = staged_for_graph(nodes, edges)
            payload = RehearsalScenariosResponse(success=True, triggers=staged).model_dump()
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=payload,
            ))
            logger.info(
                f"[rehearsal] scenarios responded: {len(staged)} trigger group(s) "
                f"for {request.workflow_id}"
            )
        except Exception:
            logger.exception("[rehearsal] scenarios response failed")
            raise

    async def run_rehearsal(self, sid: str, request: RehearsalRunRequest) -> None:
        """Run the workflow's agent against a staged world.

        Thin: session resolution + ack. The staging, gates, dispatch and
        teardown live in nodes/agent/rehearsal_launch.launch_rehearsal — the
        ONE implementation shared with the public template page's anonymous
        test runs.
        """
        from nodes.agent.rehearsal_launch import launch_rehearsal

        session = await self.sio.get_session(sid)
        user_id = session.get('user_id')
        if not user_id:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=RehearsalRunResponse(success=False, message="User not authenticated").model_dump(),
            ))
            return

        conversation_id, error = await launch_rehearsal(
            workflow_id=request.workflow_id,
            scenario_key=request.scenario,
            lead_patch=request.lead_patch,
            user_id=str(user_id),
            sid=sid,
        )
        await send_event(self.sio, sid, ResponseEvent(
            request_id=request.request_id,
            data=RehearsalRunResponse(
                success=error is None,
                conversation_id=conversation_id,
                message=error,
            ).model_dump(),
        ))
    async def test_credential_connection(self, sid: str, request: CredentialTestConnectionRequest) -> None:
        """Ask a provider to prove a credential works, in the user's own nouns.

        Thin by design: `collect_evidence` owns classification and never raises,
        so this only resolves the session and shapes the reply. In particular it
        does NOT invent a verdict when the probe cannot judge — `reachable=None`
        travels to the client intact and renders as unverified, because telling
        someone to reconnect a working account is worse than saying nothing.
        """
        from nodes.core.connection_evidence import collect_evidence
        from nodes.core.registry import NODE_REGISTRY
        from utils.database_pool import get_native_pool

        session = await self.sio.get_session(sid)
        user_id = session.get('user_id')
        if not user_id:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=CredentialTestConnectionResponse(
                    reachable=None, error="User not authenticated"
                ).model_dump()
            ))
            return

        result = await collect_evidence(
            node_type=request.node_type,
            credential_id=request.credential_id,
            user_id=user_id,
            pool=get_native_pool(),
            organization_id=request.organization_id,
            workflow_id=request.workflow_id,
        )
        node_class = NODE_REGISTRY.get(request.node_type)
        spec = getattr(node_class, 'connection_evidence', None)

        await send_event(self.sio, sid, ResponseEvent(
            request_id=request.request_id,
            data=CredentialTestConnectionResponse(
                reachable=result.reachable,
                samples=[
                    EvidenceSampleModel(label=s.label, value=s.value)
                    for s in result.samples
                ],
                noun=result.noun,
                total=result.total,
                account_label=result.account_label,
                answers_field=result.answers_field,
                proves=getattr(spec, 'proves', 'account'),
                error=result.error,
            ).model_dump()
        ))

    async def load_node_options(self, sid: str, request: WorkflowNodeLoadOptionsRequest) -> None:
        """
        Load dynamic options for a node field.

        This enables dropdowns like "select spreadsheet" to be populated
        by calling the node's load_field_options method with the user's credentials.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowNodeLoadOptionsResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            # Get node class from registry
            from nodes.core.registry import NODE_REGISTRY
            node_class = NODE_REGISTRY.get(request.node_type)

            if not node_class:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowNodeLoadOptionsResponse(
                        success=False,
                        message=f"Unknown node type: {request.node_type}"
                    ).model_dump()
                ))
                return

            # Check if node supports dynamic options
            if not hasattr(node_class, 'load_field_options'):
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowNodeLoadOptionsResponse(
                        success=False,
                        message=f"Node type {request.node_type} does not support dynamic options"
                    ).model_dump()
                ))
                return

            # Fetch and decrypt credential (if provided)
            # Some nodes (like serverless function) don't require credentials
            credential_data = {}
            if request.credential_id:
                pool = await self.get_pool()
                if not pool:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=WorkflowNodeLoadOptionsResponse(
                            success=False,
                            message="Database connection not available"
                        ).model_dump()
                    ))
                    return

                async with pool.acquire() as conn:
                    # Get user's current org context
                    org_id = await get_user_org_context(conn, user_id)

                    # Check if user has access (owner, user share, or org share in current context)
                    row = await conn.fetchrow(f"""
                        SELECT c.credential
                        FROM credentials c
                        WHERE c.id = $1
                          AND {credential_access_predicate()}
                    """, request.credential_id, user_id, org_id)

                    if not row:
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request.request_id,
                            data=WorkflowNodeLoadOptionsResponse(
                                success=False,
                                message="Credential not found or access denied"
                            ).model_dump()
                        ))
                        return

                    # Decrypt credential
                    try:
                        encryption = get_encryption()
                        credential_data = encryption.decrypt_credential(row['credential'])
                    except Exception as e:
                        logger.error(f"Error decrypting credential: {e}")
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request.request_id,
                            data=WorkflowNodeLoadOptionsResponse(
                                success=False,
                                message="Failed to decrypt credential"
                            ).model_dump()
                        ))
                        return

            # Call node's load_field_options method
            try:
                # Inject user_id into context for credential-less nodes (e.g., resource picker)
                context = dict(request.context or {})
                context['_user_id'] = user_id

                # Trim once here so every per-node helper can treat empty /
                # whitespace-only search as the single "no filter" sentinel.
                from nodes.core.dynamic_options import normalize_search

                # Refresh expiring OAuth tokens at load so option queries never
                # hit the provider with a stale token (no-op for nodes that
                # don't override freshen_credential).
                if request.credential_id and credential_data:
                    from nodes.core.oauth_audit import caller_path_scope
                    with caller_path_scope("dropdown"):
                        credential_data = await node_class.freshen_credential(
                            credential_data,
                            pool=pool,
                            user_id=user_id,
                            credential_id=request.credential_id,
                        )

                result = await node_class.load_field_options(
                    field_name=request.field_name,
                    credential_data=credential_data,
                    context=context,
                    page_token=request.page_token,
                    search=normalize_search(request.search),
                )

                # Handle both old format (list) and new format (dict with options and next_page_token)
                if isinstance(result, dict):
                    options = result.get('options', [])
                    next_page_token = result.get('next_page_token')
                else:
                    # Backwards compatibility with old format (list of options)
                    options = result
                    next_page_token = None

                # Convert to FieldOption models
                field_options = [
                    FieldOption(
                        value=opt['value'],
                        label=opt['label'],
                        metadata=opt.get('metadata')
                    )
                    for opt in options
                ]

                response = WorkflowNodeLoadOptionsResponse(
                    success=True,
                    options=field_options,
                    next_page_token=next_page_token
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                logger.info(f"Loaded {len(field_options)} options for {request.node_type}.{request.field_name}, has_more={next_page_token is not None}")

            except Exception as e:
                logger.error(f"Error loading field options: {e}", exc_info=True)
                # Loaders raise ValueError with a user-facing message (missing
                # credential, API error). Surface it verbatim; wrap only
                # unexpected exceptions so a real bug still reads as a failure.
                message = str(e) if isinstance(e, ValueError) else f"Failed to load options: {str(e)}"
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowNodeLoadOptionsResponse(
                        success=False,
                        message=message
                    ).model_dump()
                ))

        except Exception as e:
            logger.error(f"Error in load_node_options: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def load_node_value(self, sid: str, request: WorkflowNodeLoadValueRequest) -> None:
        """
        Load a computed/generated value for a node field.

        This is used for readonly fields that need to be computed on the backend.
        Supports schema-driven webhook fields (ui:widget="webhook") automatically,
        and falls back to node-specific load_field_value for other fields.
        """
        import uuid as uuid_module

        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowNodeLoadValueResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            # Get node class from registry
            from nodes.core.registry import NODE_REGISTRY
            node_class = NODE_REGISTRY.get(request.node_type)

            if not node_class:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowNodeLoadValueResponse(
                        success=False,
                        message=f"Unknown node type: {request.node_type}"
                    ).model_dump()
                ))
                return

            # Get database pool
            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowNodeLoadValueResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Convert workflow_id to UUID
            try:
                workflow_uuid = uuid_module.UUID(request.workflow_id)
            except ValueError:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowNodeLoadValueResponse(
                        success=False,
                        message="Invalid workflow_id format"
                    ).model_dump()
                ))
                return

            # Verify workflow access (owner or shared)
            async with pool.acquire() as conn:
                access = await check_resource_access(
                    conn, user_id, "workflow", str(workflow_uuid)
                )

            if not access.has_access:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowNodeLoadValueResponse(
                        success=False,
                        message="Workflow not found or access denied"
                    ).model_dump()
                ))
                return

            # Check if this is a webhook field (schema-driven primitive).
            # Off-loop: _is_webhook_field calls get_config_schema (heavy pure-CPU
            # Pydantic json_schema generation) and does no async work, so running
            # it on the loop blocks co-resident handlers.
            is_webhook_field = await asyncio.to_thread(
                self._is_webhook_field, node_class, request.field_name, request.context
            )

            try:
                # Priority 1: Node-specific load_field_value method
                # This allows nodes like TelegramTriggerNode to handle webhook fields with custom logic
                # (e.g., also calling Telegram's setWebhook API)
                if hasattr(node_class, 'load_field_value'):
                    result = await node_class.load_field_value(
                        field_name=request.field_name,
                        user_id=user_id,
                        workflow_id=workflow_uuid,
                        node_id=request.node_id,
                        pool=pool,
                        context=request.context,
                        credential_ids=request.credential_ids,
                    )

                    # Result can be a single value or a dict of values
                    if isinstance(result, dict) and 'values' in result:
                        response = WorkflowNodeLoadValueResponse(
                            success=True,
                            values=result['values']
                        )
                    elif isinstance(result, dict) and 'value' in result:
                        response = WorkflowNodeLoadValueResponse(
                            success=True,
                            value=result['value']
                        )
                    else:
                        response = WorkflowNodeLoadValueResponse(
                            success=True,
                            value=result
                        )
                    logger.info(f"Loaded value for {request.node_type}.{request.field_name}")

                elif is_webhook_field:
                    # Priority 2: Generic webhook handling via WebhookManager
                    # Used by nodes like webhook-trigger that don't have custom load_field_value
                    from utils.webhook_manager import WebhookManager
                    webhook_data = await WebhookManager.get_or_create_webhook(
                        pool=pool,
                        user_id=user_id,
                        workflow_id=workflow_uuid,
                        node_id=request.node_id,
                    )
                    response = WorkflowNodeLoadValueResponse(
                        success=True,
                        values=webhook_data
                    )
                    logger.info(f"Loaded webhook for {request.node_type}.{request.field_name}")

                else:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=WorkflowNodeLoadValueResponse(
                            success=False,
                            message=f"Node type {request.node_type} does not support computed field values"
                        ).model_dump()
                    ))
                    return

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

            except Exception as e:
                logger.error(f"Error loading field value: {e}", exc_info=True)
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowNodeLoadValueResponse(
                        success=False,
                        message=f"Failed to load value: {str(e)}"
                    ).model_dump()
                ))

        except Exception as e:
            logger.error(f"Error in load_node_value: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    def _resolve_ref(self, schema: Dict[str, Any], ref: str) -> Dict[str, Any]:
        """Resolve a $ref reference within the schema."""
        if not ref.startswith("#/"):
            return {}
        parts = ref[2:].split("/")  # Remove "#/" and split
        result = schema
        for part in parts:
            if isinstance(result, dict):
                result = result.get(part, {})
            else:
                return {}
        return result if isinstance(result, dict) else {}

    def _is_webhook_field(
        self,
        node_class,
        field_name: str,
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Check if a field is a webhook field based on schema markers.

        Looks for ui:widget="webhook" in the field's JSON schema.
        Handles discriminated unions by checking the current operation's schema.

        Args:
            node_class: The node class from registry
            field_name: Name of the field being loaded
            context: Optional context with current operation value

        Returns:
            True if field has ui:widget="webhook"
        """
        try:
            # Get the node's JSON schema
            schema = node_class.get_config_schema()
            if not schema:
                return False

            # Get config schema (may be nested under properties.config)
            config_schema = schema.get("properties", {}).get("config", schema)

            # Resolve $ref if present (Pydantic uses $ref for nested models)
            if "$ref" in config_schema:
                config_schema = self._resolve_ref(schema, config_schema["$ref"])

            # Handle discriminated unions (anyOf/oneOf)
            options = config_schema.get("anyOf") or config_schema.get("oneOf")
            if options and context:
                # Find the current operation's schema
                operation = context.get("operation")
                if operation:
                    from utils.webhook_manager import WebhookManager
                    operation_schema = WebhookManager.get_operation_schema(
                        schema, operation, "operation"
                    )
                    if operation_schema:
                        config_schema = operation_schema

            # Check if field has ui:widget="webhook"
            properties = config_schema.get("properties", {})
            field_schema = properties.get(field_name, {})
            return field_schema.get("ui:widget") == "webhook"

        except Exception as e:
            logger.debug(f"Error checking webhook field: {e}")
            return False

    async def reconnect_webhook_relay(self, sid: str, request: WebhookRelayReconnectRequest) -> None:
        """
        Reconnect the webhook relay client.

        Only meaningful where a relay client is registered (a developer's
        backend); a directly reachable backend has nothing to reconnect.
        """
        try:
            from utils.webhook_delivery import reconnect_relay_client, relay_in_use

            if not relay_in_use():
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={
                        "success": True,
                        "message": "Deliveries reach this backend directly - no relay to reconnect"
                    }
                ))
                return

            # Attempt reconnection
            logger.info("[WorkflowHandler] Attempting webhook relay reconnection...")
            success = await reconnect_relay_client()

            if success:
                logger.info("[WorkflowHandler] Webhook relay reconnected successfully")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={
                        "success": True,
                        "message": "Webhook relay reconnected successfully"
                    }
                ))
            else:
                logger.warning("[WorkflowHandler] Failed to reconnect webhook relay")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={
                        "success": False,
                        "message": "Failed to reconnect webhook relay"
                    }
                ))

        except Exception as e:
            logger.error(f"Error reconnecting webhook relay: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={
                    "success": False,
                    "message": f"Error: {str(e)}"
                }
            ))

    async def get_node_output_schema(self, sid: str, request: NodeOutputSchemaRequest) -> None:
        """
        Get the expected output schema and curated suggested references for a
        node type and operation.

        ``suggested_refs`` is ``null`` while the LLM curation hasn't produced
        a valid result yet — the frontend treats that as a loading state.
        ``schema`` is ``null`` if no execution has ever been observed.
        """
        try:
            row = await get_schema_with_suggestions(request.node_type, request.node_operation)
            schema = row["schema"] if row else None
            suggested_refs = row["suggested_refs"] if row else None

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={
                    "success": True,
                    "schema": schema,
                    "suggested_refs": suggested_refs,
                    "node_type": request.node_type,
                    "node_operation": request.node_operation,
                }
            ))

        except Exception as e:
            logger.error(f"Error fetching node output schema: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"success": False},
                error=str(e)
            ))

    async def clear_node_state(self, sid: str, request: WorkflowClearNodeStateRequest) -> None:
        """
        Clear persistent state for a workflow node.

        This deletes the state record from workflow_node_state table for the specified
        node, effectively resetting any stateful behavior (e.g., RSS seen items, State Manager state).
        """
        import uuid as uuid_module

        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                logger.warning("[WorkflowHandler] clear_node_state: User not authenticated")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={"success": False},
                    error="User not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                logger.error("[WorkflowHandler] clear_node_state: Database pool not available")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={"success": False},
                    error="Database connection not available"
                ))
                return

            async with pool.acquire() as conn:
                # Check access to the workflow
                access = await check_resource_access(
                    conn, user_id, "workflow", request.workflow_id
                )

                if not access.has_access:
                    logger.warning(f"[WorkflowHandler] clear_node_state: Access denied for user {user_id} to workflow {request.workflow_id}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={"success": False},
                        error="Access denied"
                    ))
                    return

                # Delete the node state record
                state_rows_deleted = await WorkflowRepo(pool).delete_node_state(
                    conn, uuid_module.UUID(request.workflow_id), request.node_id,
                )

                # Delete conversation history for this node (agent nodes).
                # conversations SQL stays inline — owned by ConversationRepo.
                conv_result = await conn.execute("""
                    DELETE FROM conversations
                    WHERE workflow_id = $1 AND node_id = $2
                """, request.workflow_id, request.node_id)
                conv_rows_deleted = int(conv_result.split()[-1]) if conv_result else 0

                logger.info(f"[WorkflowHandler] Cleared state for node {request.node_id} in workflow {request.workflow_id} (state: {state_rows_deleted}, conversations: {conv_rows_deleted})")

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={
                        "success": True,
                        "message": f"State cleared for node {request.node_id}",
                        "rows_deleted": state_rows_deleted,
                        "conversations_deleted": conv_rows_deleted,
                    }
                ))

        except Exception as e:
            logger.error(f"[WorkflowHandler] Error clearing node state: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"success": False},
                error=str(e)
            ))

    async def save_node_state(self, sid: str, request: WorkflowSaveNodeStateRequest) -> None:
        """
        Save persistent state for a workflow node (used by the SDK state.set).
        Upserts the provided values into workflow_node_state.
        """
        import uuid as uuid_module
        import json

        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={"success": False},
                    error="User not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={"success": False},
                    error="Database connection not available"
                ))
                return

            async with pool.acquire() as conn:
                access = await check_resource_access(
                    conn, user_id, "workflow", request.workflow_id
                )
                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={"success": False},
                        error="Access denied"
                    ))
                    return

                workflow_uuid = uuid_module.UUID(request.workflow_id)

                # Upsert state into workflow_node_state
                await WorkflowRepo(pool).upsert_node_state(
                    conn, workflow_uuid, request.node_id, request.values,
                )

                logger.info(f"[WorkflowHandler] Saved state for node {request.node_id} in workflow {request.workflow_id}")

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={"success": True}
                ))

        except Exception as e:
            logger.error(f"[WorkflowHandler] Error saving node state: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"success": False},
                error=str(e)
            ))

    async def load_node_state(self, sid: str, request: WorkflowLoadNodeStateRequest) -> None:
        """Load persistent state for a workflow node."""
        import uuid as uuid_module
        import json

        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={"success": False, "values": {}},
                    error="User not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={"success": False, "values": {}},
                    error="Database connection not available"
                ))
                return

            async with pool.acquire() as conn:
                access = await check_resource_access(
                    conn, user_id, "workflow", request.workflow_id
                )
                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={"success": False, "values": {}},
                        error="Access denied"
                    ))
                    return

                raw = await WorkflowRepo(pool).get_node_state(
                    conn, uuid_module.UUID(request.workflow_id), request.node_id,
                )
                # asyncpg returns jsonb columns as strings; parse to dict
                if isinstance(raw, str):
                    values = json.loads(raw)
                elif raw is None:
                    values = {}
                else:
                    values = raw

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={"success": True, "values": values}
                ))

        except Exception as e:
            logger.error(f"[WorkflowHandler] Error loading node state: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"success": False, "values": {}},
                error=str(e)
            ))

    async def _find_state_manager_node(self, conn, workflow_id: str, node_id: str = None) -> str | None:
        """Find the state-manager node ID in a workflow. Uses explicit node_id if provided."""
        if node_id:
            return node_id
        import json
        row = await WorkflowRepo(await self.get_pool()).get_workflow_data(conn, workflow_id)
        if not row:
            return None
        wd = row['workflow']
        if isinstance(wd, str):
            wd = json.loads(wd)
        for node in wd.get('nodes', []):
            if node.get('type') == 'state-manager':
                return node['id']
        return None

    async def state_get(self, sid: str, request) -> None:
        """Get a state value by key, auto-resolving the state-manager node."""
        import uuid as uuid_module
        import json
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="User not authenticated"))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="Database connection not available"))
                return

            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", request.workflow_id)
                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error="Access denied"))
                    return

                sm_node_id = await self._find_state_manager_node(conn, request.workflow_id, getattr(request, 'node_id', None))
                if not sm_node_id:
                    # No state-manager node — return undefined (not an error)
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={"value": None}))
                    return

                raw = await WorkflowRepo(pool).get_node_state(
                    conn, uuid_module.UUID(request.workflow_id), sm_node_id,
                )

                state = {}
                if raw is not None:
                    parsed = json.loads(raw) if isinstance(raw, str) else (raw or {})
                    state = parsed if isinstance(parsed, dict) else {}

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={"value": state.get(request.key)}))

        except Exception as e:
            logger.error(f"[WorkflowHandler] Error in state_get: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)))

    async def state_set(self, sid: str, request) -> None:
        """Set a state value by key, auto-resolving the state-manager node."""
        import uuid as uuid_module
        import json
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="User not authenticated"))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="Database connection not available"))
                return

            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", request.workflow_id)
                if not access.has_access or access.permission not in (Permission.EDIT, Permission.OWNER):
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error="No edit access"))
                    return

                sm_node_id = await self._find_state_manager_node(conn, request.workflow_id, getattr(request, 'node_id', None))
                if not sm_node_id:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error="No state-manager node found in workflow"))
                    return

                wf_uuid = uuid_module.UUID(request.workflow_id)

                repo = WorkflowRepo(pool)
                if request.value is None:
                    # A null value deletes the key (SDK state.delete maps here). Use the
                    # JSONB minus operator so keys() no longer lists it — a plain merge
                    # would store {key: null}, leaving a tombstone the SDK still sees.
                    await repo.delete_state_key(conn, wf_uuid, sm_node_id, request.key)
                else:
                    # Atomic upsert: merge single key into existing state without read-modify-write.
                    # Pass the value as a dict so asyncpg's jsonb codec handles serialization.
                    await repo.merge_state_key(
                        conn, wf_uuid, sm_node_id, {request.key: request.value},
                    )

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={"success": True}))

                # Notify other SDK clients connected to the same workflow
                from wss.sender import get_sdk_sids_for_workflow
                from wss.sender.events import StateChangedEvent
                change_event = StateChangedEvent(key=request.key, value=request.value)
                for other_sid in get_sdk_sids_for_workflow(request.workflow_id, exclude_sid=sid):
                    try:
                        await send_event(self.sio, other_sid, change_event)
                    except Exception:
                        pass  # Best-effort notification

        except Exception as e:
            logger.error(f"[WorkflowHandler] Error in state_set: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)))

    async def state_keys(self, sid: str, request) -> None:
        """List all state keys, auto-resolving the state-manager node."""
        import uuid as uuid_module
        import json
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="User not authenticated"))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="Database connection not available"))
                return

            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", request.workflow_id)
                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error="Access denied"))
                    return

                sm_node_id = await self._find_state_manager_node(conn, request.workflow_id, getattr(request, 'node_id', None))
                if not sm_node_id:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={"keys": []}))
                    return

                raw = await WorkflowRepo(pool).get_node_state(
                    conn, uuid_module.UUID(request.workflow_id), sm_node_id,
                )

                state = {}
                if raw is not None:
                    parsed = json.loads(raw) if isinstance(raw, str) else (raw or {})
                    state = parsed if isinstance(parsed, dict) else {}

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={"keys": list(state.keys())}))

        except Exception as e:
            logger.error(f"[WorkflowHandler] Error in state_keys: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)))
