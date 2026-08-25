"""
MCP workflow handler for AI agent workflow operations.

This handler enables AI agents to build and manipulate workflows through MCP tools.

Architecture:
- Backend-only operations: get_node_output, get_node_input, run_workflow, run_node
  These work directly with the database and don't require a frontend connection.
  Connected frontends receive dual-delivery events for real-time UI updates.

- Frontend-required operations: get_selected_node, open_workflow
  These use bidirectional communication to query UI state or trigger navigation.

- Workflow mutation (add/remove nodes, edges, config updates) is handled by the
  update_workflow XML tool in mcp_server.py, not by individual socket handlers.
"""

import asyncio
import uuid
import time
import logging
import xml.etree.ElementTree as ET
from typing import Dict, Any, Callable, Optional, Union, List, Tuple, Annotated, get_args, get_origin
from pydantic import BaseModel, TypeAdapter

from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent, WorkflowMCPRequestEvent
from wss.sender.responses import (
    WorkflowMCPNodeInfo,
    WorkflowMCPDeleteWorkflowResponse,
    WorkflowMCPUpdateWorkflowMetadataResponse,
    WorkflowMCPCreateWorkflowResponse,
    WorkflowMCPGetNodeConfigResponse,
    WorkflowMCPUpdateInterfaceResponse,
    InterfaceBlockInfo,
)
from wss.receiver.client_events import (
    WorkflowMCPResponseRequest,
    WorkflowMCPSearchNodesRequest,
    WorkflowMCPGetNodeConfigSchemaRequest,
    WorkflowMCPGetSelectedNodeRequest,
    WorkflowMCPGetOpenWorkflowRequest,
    WorkflowMCPGetNodeOutputRequest,
    WorkflowMCPGetNodeInputRequest,
    WorkflowMCPRunWorkflowRequest,
    WorkflowMCPCreateWorkflowRequest,
    WorkflowMCPOpenWorkflowRequest,
    WorkflowMCPListWorkflowsRequest,
    WorkflowMCPDeleteWorkflowRequest,
    WorkflowMCPUpdateWorkflowMetadataRequest,
    WorkflowMCPListSavedOutputsRequest,
    WorkflowMCPRunNodeRequest,
    WorkflowMCPGetExecutionStatusRequest,
    WorkflowMCPListCredentialsRequest,
    WorkflowMCPLoadFieldOptionsRequest,
    WorkflowMCPGetNodeConfigRequest,
    WorkflowMCPUpdateInterfaceRequest,
    WorkflowExecuteRequest,
    WorkflowGetNodeOutputsRequest,
    WorkflowGetNodeOutputHistoryRequest,
)
from utils.database_pool import DatabasePoolMixin
from utils.access_control import check_resource_access, Permission
from wss.handlers.workflow_handler import get_user_org_context
from nodes.core.registry import NODE_REGISTRY
from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
from repositories.workflow import WorkflowRepo
from repositories.organization import OrgRepo
from repositories.credentials import credential_access_predicate

logger = logging.getLogger(__name__)

# Upper bound for client-supplied output-history limits. The socket event is
# reachable by API-key SDK clients (utils/sdk_permissions.py), so the value is
# untrusted; read_node_output_history binds it into both the per-key LATERAL and
# the outer LIMIT, then reassembles one R2 object graph per row. 200 leaves 10x
# headroom over every in-repo caller (all send 20) while bounding the fan-out.
MAX_OUTPUT_HISTORY_LIMIT = 200


class WorkflowMCPHandler(DatabasePoolMixin, SocketIOHandler):
    """
    Handler for MCP workflow tools.

    Enables AI agents to query and manipulate workflows through a bidirectional
    communication pattern with the frontend.
    """

    def __init__(self, sio):
        super().__init__(sio)
        # Pending requests awaiting frontend response, keyed by request_id
        self._pending_requests: Dict[str, asyncio.Future] = {}

    def get_events(self) -> Dict[str, Callable]:
        """Register workflow MCP event handlers."""
        return {
            "workflow:mcp:response": self.handle_frontend_response,
            "workflow:mcp:search_nodes": self.search_nodes,
            "workflow:mcp:get_node_config_schema": self.get_node_config_schema,
            "workflow:mcp:get_selected_node": self.get_selected_node,
            "workflow:mcp:get_open_workflow": self.get_open_workflow,
            "workflow:mcp:get_node_output": self.get_node_output,
            "workflow:mcp:get_node_input": self.get_node_input,
            "workflow:mcp:run_workflow": self.run_workflow,
            "workflow:mcp:create_workflow": self.create_workflow,
            "workflow:mcp:open_workflow": self.open_workflow,
            "workflow:mcp:list_workflows": self.list_workflows,
            "workflow:mcp:delete_workflow": self.delete_workflow,
            "workflow:mcp:update_workflow_metadata": self.update_workflow_metadata,
            "workflow:mcp:list_saved_outputs": self.list_saved_outputs,
            "workflow:mcp:run_node": self.run_node,
            "workflow:mcp:get_execution_status": self.get_execution_status,
            "workflow:mcp:list_credentials": self.list_credentials,
            "workflow:mcp:load_field_options": self.load_field_options,
            "workflow:mcp:get_node_config": self.get_node_config,
            "workflow:mcp:update_interface": self.update_interface,
            "workflow:get_node_outputs": self.get_node_outputs,
            "workflow:get_node_output_history": self.get_node_output_history,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid  # Suppress unused parameter warning

    # =========================================================================
    # Bidirectional Communication
    # =========================================================================

    async def _request_frontend(
        self,
        sid: str,
        request_type: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 10
    ) -> Any:
        """
        Send a request to the frontend and await response.

        For OAuth virtual sids (format "oauth:{user_id}"), this method routes
        the request to the user's real frontend socket connection.

        Args:
            sid: Socket session ID (can be real or OAuth virtual sid)
            request_type: Type of request (e.g., 'get_state', 'get_selected', 'add_node')
            params: Request-specific parameters
            timeout: Timeout in seconds

        Returns:
            Response data from the frontend

        Raises:
            asyncio.TimeoutError: If frontend doesn't respond within timeout
            RuntimeError: If frontend returns an error or no frontend connected
        """
        # Resolve the target sid(s) - for OAuth virtual sids, find all real frontends
        # TODO: Improve frontend detection - see WORKFLOW_MCP_FRONTEND_DETECTION.md
        # Current approach broadcasts to all sessions which is problematic for
        # destructive operations like open_workflow that affect all tabs.
        target_sids = [sid]
        logger.info(f"[WorkflowMCP] _request_frontend called: sid={sid}, request_type={request_type}")
        if sid.startswith("oauth:"):
            from wss.receiver.receiver import get_receiver_instance
            receiver = get_receiver_instance()
            logger.info(f"[WorkflowMCP] OAuth sid detected, receiver={receiver is not None}")
            if receiver:
                frontend_sids = receiver.get_frontend_sids_from_oauth_sid(sid)
                logger.info(f"[WorkflowMCP] frontend_sids for OAuth user: {frontend_sids}")
                if frontend_sids:
                    target_sids = frontend_sids  # Broadcast to ALL frontends
                    logger.info(f"[WorkflowMCP] Broadcasting to {len(target_sids)} frontend sessions")
                else:
                    raise RuntimeError(
                        "No frontend connected. Please open the workflow editor in your browser."
                    )
            else:
                raise RuntimeError("Receiver not initialized")

        request_id = f"mcp_{uuid.uuid4()}"
        future: asyncio.Future = asyncio.Future()

        # Determine validity checker based on request type
        # For get_selected: valid if a node is actually selected (not None)
        # For open_workflow: valid if success is True
        is_valid_response = self._get_validity_checker(request_type)

        self._pending_requests[request_id] = {
            'future': future,
            'is_valid': is_valid_response,
            'fallback_response': None,
            'response_count': 0,
            'expected_count': len(target_sids),
        }

        try:
            # Broadcast to all frontend sessions - first VALID response wins
            for target_sid in target_sids:
                logger.info(f"[WorkflowMCP] Sending request to frontend sid: {target_sid}")
                await send_event(self.sio, target_sid, WorkflowMCPRequestEvent(
                    request_id=request_id,
                    request_type=request_type,
                    params=params or {}
                ))
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            # Check if we have a fallback response from an "invalid" responder
            pending = self._pending_requests.get(request_id)
            if pending and pending.get('fallback_response') is not None:
                logger.info(f"[WorkflowMCP] Timeout but returning fallback response")
                return pending['fallback_response']
            raise
        finally:
            self._pending_requests.pop(request_id, None)

    def _get_validity_checker(self, request_type: str) -> Optional[Callable[[Any], bool]]:
        """
        Get a validity checker function for a request type.

        Returns a function that checks if a response is "valid" (should win over others).
        For example, for get_selected, a response with an actual selected node is
        preferred over one that says no node is selected.
        """
        if request_type == 'get_selected':
            # Valid if a node is actually selected
            return lambda data: data is not None
        elif request_type == 'open_workflow':
            # Valid if navigation succeeded
            return lambda data: data.get('success', False) if isinstance(data, dict) else False
        # Default: any response is valid
        return None

    async def handle_frontend_response(
        self, sid: str, request: WorkflowMCPResponseRequest
    ) -> None:
        """
        Handle response from frontend to a pending MCP request.

        Uses validity checking to prefer "valid" responses over invalid ones.
        For example, for get_selected, a response with an actual node selected
        is preferred over one that says no node is selected.
        """
        _ = sid  # Response doesn't need to send anything back
        pending = self._pending_requests.get(request.request_id)

        if not pending:
            logger.warning(f"[WorkflowMCP] No pending request for response: {request.request_id}")
            return

        future = pending['future']
        if future.done():
            logger.debug(f"[WorkflowMCP] Future already completed for: {request.request_id}")
            return

        # Handle errors - always complete immediately with error
        if request.error:
            future.set_exception(RuntimeError(request.error))
            return

        # Check validity
        is_valid = pending.get('is_valid')
        if is_valid is None or is_valid(request.data):
            # Valid response - complete immediately
            logger.info(f"[WorkflowMCP] Valid response received, completing future")
            future.set_result(request.data)
        else:
            # Invalid response - store as fallback
            logger.info(f"[WorkflowMCP] Invalid response received, storing as fallback")
            pending['fallback_response'] = request.data
            pending['response_count'] = pending.get('response_count', 0) + 1

            # If all frontends have responded with invalid responses, complete with fallback
            if pending['response_count'] >= pending.get('expected_count', 1):
                logger.info(f"[WorkflowMCP] All frontends responded with invalid, using fallback")
                future.set_result(pending['fallback_response'])

    # =========================================================================
    # Database Helpers for Backend-Only Operations
    # =========================================================================

    async def _get_user_id(self, sid: str, request: BaseModel) -> Optional[str]:
        """
        Get user_id from request (injected by MCP transport) or session.

        The MCP transport layer injects _user_id for all authenticated requests,
        regardless of transport mode (OAuth, Cookie, Sandbox). Handlers use this
        uniformly without needing to know about transport details.

        For non-MCP requests (direct frontend socket events), falls back to session.

        Args:
            sid: Socket session ID
            request: The request object (may have _user_id from MCP transport)

        Returns:
            user_id string if found, None otherwise
        """
        # MCP transport layer injects _user_id for authenticated requests
        if hasattr(request, '_user_id') and request._user_id:
            return request._user_id

        # Fall back to session lookup for non-MCP requests (direct frontend events)
        try:
            session = await self.sio.get_session(sid)
            return session.get('user_id')
        except Exception as e:
            logger.warning(f"Failed to get session for sid {sid}: {e}")
            return None

    async def _load_workflow(
        self, user_id: str, workflow_id: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Load workflow from database.

        Returns:
            Tuple of (workflow_data, error_message)
            workflow_data contains 'nodes' and 'edges' lists
        """
        pool = await self.get_pool()
        if not pool:
            return None, "Database connection not available"

        try:
            async with pool.acquire() as conn:
                # Check access (owner, org member, or shared)
                access = await check_resource_access(
                    conn, user_id, "workflow", workflow_id
                )

                if not access.has_access:
                    return None, f"Workflow not found or access denied: {workflow_id}"

                row = await WorkflowRepo(pool).get_workflow_for_mcp_load(
                    conn, uuid.UUID(workflow_id),
                )

                if not row:
                    return None, f"Workflow not found: {workflow_id}"

                workflow_data = row['workflow'] or {"nodes": [], "edges": []}
                # Ensure nodes and edges exist
                if "nodes" not in workflow_data:
                    workflow_data["nodes"] = []
                if "edges" not in workflow_data:
                    workflow_data["edges"] = []

                return workflow_data, None

        except Exception as e:
            logger.error(f"Error loading workflow: {e}", exc_info=True)
            return None, str(e)

    async def _save_workflow(
        self, user_id: str, workflow_id: str, workflow_data: Dict[str, Any]
    ) -> Optional[str]:
        """
        Save workflow to database.

        Returns:
            Error message if failed, None if successful
        """
        pool = await self.get_pool()
        if not pool:
            return "Database connection not available"

        try:
            async with pool.acquire() as conn:
                # Check edit access (owner, org member, or shared with edit permission)
                access = await check_resource_access(
                    conn, user_id, "workflow", workflow_id
                )

                if not access.has_access:
                    return f"Workflow not found or access denied: {workflow_id}"

                if access.permission not in (Permission.EDIT, Permission.OWNER):
                    return "You don't have permission to edit this workflow"

                result = await WorkflowRepo(pool).replace_workflow_data(
                    conn, uuid.UUID(workflow_id), workflow_data,
                )

                if result == "UPDATE 0":
                    return f"Workflow not found: {workflow_id}"

                return None

        except Exception as e:
            logger.error(f"Error saving workflow: {e}", exc_info=True)
            return str(e)

    def _create_node(
        self,
        node_type: str,
        config: Dict[str, Any],
        position: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Create a new node structure for the workflow.

        Creates nodes in the standard format used throughout the system:
        - node.config contains the config fields directly (flat format)
        - Credentials use credentialIds: { type: id } format
        - This matches how frontend saves nodes and how execution handler expects them

        Args:
            node_type: Type of node (e.g., 'automation-google-sheets')
            config: Flat config with credentialIds (e.g., {spreadsheet_id: "...", credentialIds: {...}})
            position: {x, y} position on canvas

        Returns:
            Node dictionary ready to be added to workflow_data.nodes
        """
        node_id = f"{node_type}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"

        flat_config = dict(config) if config else {}
        # Ensure flat format defaults are present
        flat_config.setdefault('configValid', False)
        flat_config.setdefault('credentialIds', {})

        return {
            "id": node_id,
            "type": node_type,
            "position": position,
            "config": flat_config,
        }

    def _find_node_position(
        self,
        nodes: List[Dict[str, Any]],
        prev_node_id: Optional[str]
    ) -> Dict[str, float]:
        """
        Calculate position for a new node.

        If prev_node_id is provided, positions to the right of that node.
        Otherwise, uses a default position or positions after the last node.
        """
        if prev_node_id:
            for node in nodes:
                if node.get("id") == prev_node_id:
                    return {
                        "x": node.get("position", {}).get("x", 0) + 300,
                        "y": node.get("position", {}).get("y", 0)
                    }

        # Default position, or to the right of the last node
        if nodes:
            last_node = nodes[-1]
            return {
                "x": last_node.get("position", {}).get("x", 0) + 300,
                "y": last_node.get("position", {}).get("y", 150)
            }

        return {"x": 250, "y": 150}

    def _prepare_nodes_for_execution(
        self, nodes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Transform stored nodes to execution format.

        Handles two storage formats:
        - React Flow format: { id, type, position, data: { config: {...}, mockedOutput, disabled, ... } }
        - Direct format: { id, type, position, config: {...}, mockedOutput, disabled, ... }

        Execution format: { id, type, config: { ...config, mockedOutput, disabled } }

        The workflow execution handler expects config at the top level.
        """
        execution_nodes = []
        for node in nodes:
            # Wire shape is flat: node["config"] holds every field including
            # mockedOutput and disabled. (See frontend buildSaveConfig: it
            # spreads PERSISTED_TOP_LEVEL_NAMES INTO the config blob.)
            exec_config = dict(node.get("config", {}) or {})

            execution_nodes.append({
                "id": node["id"],
                "type": node.get("type", "unknown"),
                "config": exec_config
            })

        return execution_nodes

    async def _get_available_mocks_preview(
        self,
        user_id: str,
        node_type: str,
        limit: int = 5
    ) -> Optional[Dict[str, Any]]:
        """
        Get a preview of available mock outputs for a node type.

        Returns a limited list with total count and fetch_more hint to reduce
        context usage while providing useful information.

        Returns:
            Dict with items, total, has_more, and fetch_more hint, or None if error
        """
        try:
            # Inside the try: this preview is best-effort by contract, so a
            # pool-lifecycle failure degrades to no-preview like any DB error
            # instead of turning the enclosing response into an error.
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                # Get total count first
                count_row = await conn.fetchrow("""
                    SELECT COUNT(*) as total
                    FROM workflow_saved_output
                    WHERE node_type = $1
                      AND (user_id = $2 OR visibility = 'public')
                """, node_type, user_id)

                total = count_row['total'] if count_row else 0

                if total == 0:
                    return None

                # Get limited preview
                rows = await conn.fetch("""
                    SELECT id, name, visibility
                    FROM workflow_saved_output
                    WHERE node_type = $1
                      AND (user_id = $2 OR visibility = 'public')
                    ORDER BY updated_at DESC
                    LIMIT $3
                """, node_type, user_id, limit)

                items = [
                    {
                        "id": str(row['id']),
                        "name": row['name'],
                        "visibility": row['visibility'],
                    }
                    for row in rows
                ]

                return {
                    "items": items,
                    "total": total,
                    "has_more": total > limit,
                    "fetch_more": f"list_saved_outputs('{node_type}')" if total > limit else None,
                    "node_type": node_type
                }

        except Exception as e:
            logger.warning(f"Error fetching mock outputs preview: {e}")
            return None

    async def _get_credential_status_for_node(
        self,
        user_id: str,
        node_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Check if the user has the required credential for a node type.

        Returns:
            Dict with type, required, available, credential_id, or None if no credential needed
        """
        # Get node class and determine credential type
        node_class = NODE_REGISTRY.get(node_type)
        if not node_class:
            return None

        config_model = node_class.get_config_model()
        if not config_model or not hasattr(config_model, 'model_fields'):
            return None

        credentials_field = config_model.model_fields.get('credentials')
        if not credentials_field or not credentials_field.annotation:
            return None

        credential_type = self._extract_credential_type(credentials_field.annotation)
        if not credential_type:
            return None

        # Check if user has this credential type
        pool = await self.get_pool()
        if not pool:
            return {
                "type": credential_type,
                "required": not credentials_field.is_required(),
                "available": False,
                "credential_id": None
            }

        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT id, name
                    FROM credentials
                    WHERE owner_id = $1 AND credential_type = $2
                    ORDER BY created_at DESC
                    LIMIT 1
                """, user_id, credential_type)

                return {
                    "type": credential_type,
                    "required": credentials_field.is_required(),
                    "available": row is not None,
                    "credential_id": str(row['id']) if row else None,
                    "credential_name": row['name'] if row else None
                }

        except Exception as e:
            logger.warning(f"Error checking credential status: {e}")
            return {
                "type": credential_type,
                "required": credentials_field.is_required(),
                "available": False,
                "credential_id": None
            }

    async def _prefetch_dynamic_fields(
        self,
        user_id: str,
        node_type: str,
        credential_id: Optional[str] = None,
        limit: int = 10
    ) -> Optional[Dict[str, Any]]:
        """
        Prefetch options for dynamic fields in a node's config.

        Only fetches top-level dynamic fields (not dependent ones).
        Returns limited options with pagination info.

        Returns:
            Dict of {field_name: {options, total, has_more}} or None if error
        """
        node_class = NODE_REGISTRY.get(node_type)
        if not node_class:
            return None

        # Check if node supports dynamic options
        if not hasattr(node_class, 'load_field_options'):
            return None

        # Get config schema to find dynamic fields
        config_model = node_class.get_config_model()
        if not config_model:
            return None

        # Find fields with x-dynamic-options that don't have depends_on
        dynamic_fields = {}
        try:
            schema = config_model.model_json_schema()
            # Look for x-dynamic-options in nested config properties
            config_props = schema.get('properties', {}).get('config', {})
            if '$ref' in config_props:
                # Handle discriminated unions - just get the first one
                defs = schema.get('$defs', {})
                for def_name, def_schema in defs.items():
                    if 'properties' in def_schema:
                        for field_name, field_schema in def_schema['properties'].items():
                            if 'x-dynamic-options' in field_schema:
                                opts = field_schema['x-dynamic-options']
                                if not opts.get('depends_on'):
                                    dynamic_fields[field_name] = opts
                        break  # Only process first config type for prefetch
        except Exception as e:
            logger.warning(f"Error parsing config schema for dynamic fields: {e}")
            return None

        if not dynamic_fields:
            return None

        # Get credential if needed
        if not credential_id:
            cred_status = await self._get_credential_status_for_node(user_id, node_type)
            if cred_status and cred_status.get('available'):
                credential_id = cred_status.get('credential_id')

        if not credential_id:
            return None

        # Decrypt credential
        pool = await self.get_pool()
        if not pool:
            return None

        try:
            async with pool.acquire() as conn:
                # Get user's current org context
                org_id = await get_user_org_context(conn, user_id)

                # Check if user has access (owner, user share, or org share in current context)
                row = await conn.fetchrow(f"""
                    SELECT c.credential
                    FROM credentials c
                    WHERE c.id = $1
                      AND {credential_access_predicate()}
                """, credential_id, user_id, org_id)

                if not row:
                    return None

                from utils.encryption import get_encryption
                encryption = get_encryption()
                credential_data = encryption.decrypt_credential(row['credential'])

            # Fetch options for each dynamic field
            result = {}
            for field_name, field_opts in dynamic_fields.items():
                try:
                    options = await node_class.load_field_options(
                        field_name=field_name,
                        credential_data=credential_data,
                        context={}
                    )

                    total = len(options)
                    limited_options = options[:limit]

                    result[field_name] = {
                        "options": [
                            {"value": opt['value'], "label": opt['label']}
                            for opt in limited_options
                        ],
                        "total": total,
                        "has_more": total > limit
                    }

                except Exception as e:
                    logger.warning(f"Error prefetching options for {field_name}: {e}")
                    continue

            return result if result else None

        except Exception as e:
            logger.warning(f"Error prefetching dynamic fields: {e}")
            return None

    def _find_predecessors(
        self,
        node_id: str,
        edges: List[Dict[str, Any]],
        all_node_ids: set
    ) -> set:
        """Delegate to shared find_predecessors in workflow_ops."""
        from coder.workflow.workflow_ops import find_predecessors
        return find_predecessors(node_id, edges, all_node_ids)

    # =========================================================================
    # Backend-Only Tools (Node Discovery)
    # =========================================================================

    async def search_nodes(
        self, sid: str, request: WorkflowMCPSearchNodesRequest
    ) -> None:
        """
        Search available workflow node types.

        Returns summaries of available nodes including type, label, description,
        available config types, and required credentials. Does NOT include full
        JSON schemas - use get_node_config_schema for that.
        """
        try:
            query = request.query.lower() if request.query else None
            results = []

            for node_type, node_class in NODE_REGISTRY.items():
                # Skip test nodes
                if node_type.startswith('test-'):
                    continue

                # Extract metadata from node class
                summary = self._get_node_summary(node_type, node_class)

                # Filter by query if provided
                if query:
                    searchable = f"{summary['type']} {summary['label']} {summary['description']}".lower()
                    if query not in searchable:
                        continue

                results.append(summary)

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"nodes": results}
            ))

        except Exception as e:
            logger.error(f"Error searching nodes: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    def _get_node_summary(self, node_type: str, node_class) -> Dict[str, Any]:
        """
        Extract a summary for a node type including available config types.
        """
        # Extract label and description from class name/docstring
        label = node_class.__name__.replace('Node', '').replace('_', ' ')
        description = node_class.__doc__ or ""
        if description:
            # Get first line of docstring
            description = description.strip().split('\n')[0].strip()

        # Determine category from node type
        if node_type.startswith('automation-'):
            category = 'automation'
        elif node_type == 'agent':
            category = 'ai'
        else:
            category = 'other'

        # Get available config types from Union
        config_types = self._get_config_type_summaries(node_class)

        # Determine required credential type
        credential_type = None
        config_model = node_class.get_config_model()
        if config_model and hasattr(config_model, 'model_fields'):
            credentials_field = config_model.model_fields.get('credentials')
            if credentials_field and credentials_field.annotation:
                credential_type = self._extract_credential_type(credentials_field.annotation)

        return {
            "type": node_type,
            "label": label,
            "description": description,
            "category": category,
            "config_types": config_types,
            "credential_type": credential_type
        }

    def _get_config_type_summaries(self, node_class) -> list:
        """
        Get summaries of available config types for a node.

        For Union types, this returns info about each variant.
        """
        config_model = node_class.get_config_model()
        if not config_model:
            return []

        # Check if config model has a 'config' field that's a Union
        if hasattr(config_model, 'model_fields'):
            config_field = config_model.model_fields.get('config')
            if config_field and config_field.annotation:
                return self._extract_union_summaries(config_field.annotation)

        return []

    def _extract_union_summaries(self, annotation) -> list:
        """
        Extract summaries from a Union type annotation.

        Includes required_fields to help agent understand what's needed
        without calling get_node_config_schema.
        """
        summaries = []
        origin = get_origin(annotation)

        if origin is Union:
            for variant in get_args(annotation):
                if variant is type(None):
                    continue
                if hasattr(variant, '__name__'):
                    summary = {
                        "name": variant.__name__,
                        "description": variant.__doc__.strip().split('\n')[0] if variant.__doc__ else "",
                        "required_fields": self._get_required_fields(variant)
                    }
                    summaries.append(summary)
        elif hasattr(annotation, '__name__'):
            # Single config type
            summaries.append({
                "name": annotation.__name__,
                "description": annotation.__doc__.strip().split('\n')[0] if annotation.__doc__ else "",
                "required_fields": self._get_required_fields(annotation)
            })

        return summaries

    def _get_required_fields(self, model_class) -> List[str]:
        """
        Extract required field names from a Pydantic model.

        Returns list of field names that must be provided (no default value).
        """
        required = []
        if not hasattr(model_class, 'model_fields'):
            return required

        for field_name, field_info in model_class.model_fields.items():
            # Field is required if it has no default and no default_factory
            if field_info.is_required():
                required.append(field_name)

        return required

    def _extract_credential_type(self, annotation) -> Optional[str]:
        """
        Extract the credential type name from a type annotation.

        Handles Optional[CredentialType] by extracting the non-None type
        and normalizes the name to snake_case without 'Credential' suffix.

        Examples:
            Optional[GoogleSheetsOAuthCredential] -> "google_sheets_oauth"
            Optional[TelegramBotTokenCredential] -> "telegram_bot_token"
        """
        import re

        # Handle Optional[X] which is Union[X, None]
        origin = get_origin(annotation)
        if origin is Union:
            args = get_args(annotation)
            for arg in args:
                if arg is not type(None):
                    # Found the non-None type
                    if hasattr(arg, '__name__'):
                        return self._normalize_credential_name(arg.__name__)
            return None

        # Direct type (not Optional)
        if hasattr(annotation, '__name__'):
            return self._normalize_credential_name(annotation.__name__)

        return None

    def _normalize_credential_name(self, name: str) -> str:
        """
        Normalize credential class name to a standard snake_case format.

        Examples:
            GoogleSheetsOAuthCredential -> google_sheets_oauth
            TelegramBotTokenCredential -> telegram_bot_token
            SlackAPICredential -> slack_api
        """
        import re
        # Remove 'Credential' suffix
        name = re.sub(r'Credential$', '', name)
        # Simple CamelCase to snake_case
        name = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
        # Fix common acronyms that get incorrectly split
        name = name.replace('_o_auth', '_oauth')
        name = name.replace('_a_p_i', '_api')
        # Handle acronyms at start of name
        if name.startswith('o_auth'):
            name = 'oauth' + name[6:]
        if name.startswith('a_p_i'):
            name = 'api' + name[5:]
        return name

    async def _resolve_node_id(
        self, sid: str, node_id: Optional[str], workflow_id: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolve node_id, defaulting to the selected node if not provided.

        Args:
            sid: Socket session ID
            node_id: Explicitly provided node_id (may be None or "null" string from MCP)
            workflow_id: Workflow ID for context in error messages

        Returns:
            Tuple of (resolved_node_id, error_message)
            If error_message is set, resolved_node_id will be None
        """
        # Treat empty string or "null" string as None (MCP may pass "null" as string)
        if node_id and node_id.lower() != "null":
            return node_id, None

        # Query frontend for selected node
        try:
            result = await self._request_frontend(sid, 'get_selected')
            if result and isinstance(result, dict) and result.get("id"):
                return result["id"], None
            else:
                return None, "No node_id provided and no node is currently selected"
        except asyncio.TimeoutError:
            return None, "No node_id provided and frontend did not respond"
        except RuntimeError as e:
            return None, f"No node_id provided and could not get selected node: {str(e)}"

    def _deep_merge_config(
        self, base: Dict[str, Any], updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Deep merge two config dictionaries.

        For each key in updates:
        - If both values are dicts, recursively merge them
        - Otherwise, the update value replaces the base value

        This enables partial updates where only changed fields need to be specified.
        """
        result = dict(base)
        for key, update_value in updates.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(update_value, dict)
            ):
                # Both are dicts - recursively merge
                result[key] = self._deep_merge_config(result[key], update_value)
            else:
                # Replace value
                result[key] = update_value
        return result

    async def get_node_config_schema(
        self, sid: str, request: WorkflowMCPGetNodeConfigSchemaRequest
    ) -> None:
        """
        Get the full JSON schema for a specific node config type.

        This is more detailed than search_nodes and returns the complete
        JSON Schema for a specific configuration variant.
        """
        try:
            # Get node class from registry
            node_class = NODE_REGISTRY.get(request.node_type)
            if not node_class:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=f"Unknown node type: {request.node_type}"
                ))
                return

            # Get config model
            config_model = node_class.get_config_model()
            if not config_model:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=f"No config model for node type: {request.node_type}"
                ))
                return

            # Find the specific config type within the Union. Off-loop: this
            # builds a fresh Pydantic TypeAdapter and runs json_schema()
            # generation, heavy pure CPU for large discriminated-union nodes,
            # which otherwise blocks the event loop and starves co-resident
            # handlers (mirrors WorkflowHandler.get_node_config_schema).
            schema = await asyncio.to_thread(
                self._get_specific_config_schema, config_model, request.config_type
            )

            if not schema:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=f"Config type '{request.config_type}' not found for {request.node_type}"
                ))
                return

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={
                    "node_type": request.node_type,
                    "config_type": request.config_type,
                    "schema": schema
                }
            ))

        except Exception as e:
            logger.error(f"Error getting node config schema: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    def _get_specific_config_schema(
        self, config_model, config_type_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get the JSON schema for a specific config type within a Union.
        """
        # Check for config field that's typically a Union
        if not hasattr(config_model, 'model_fields'):
            return None

        config_field = config_model.model_fields.get('config')
        if not config_field or not config_field.annotation:
            return None

        annotation = config_field.annotation
        origin = get_origin(annotation)

        # Handle Annotated types (e.g., Annotated[Union[...], Field(discriminator='...')])
        # The first arg of Annotated is the actual type
        if origin is Annotated:
            args = get_args(annotation)
            if args:
                annotation = args[0]  # Extract the Union from Annotated
                origin = get_origin(annotation)

        if origin is Union:
            # Find the matching variant
            for variant in get_args(annotation):
                if variant is type(None):
                    continue
                if hasattr(variant, '__name__') and variant.__name__ == config_type_name:
                    # Generate schema for this specific variant
                    adapter = TypeAdapter(variant)
                    return adapter.json_schema(mode='validation')
        elif hasattr(annotation, '__name__') and annotation.__name__ == config_type_name:
            # Single config type
            adapter = TypeAdapter(annotation)
            return adapter.json_schema(mode='validation')

        return None

    # =========================================================================
    # Frontend Query Tools
    # =========================================================================

    async def get_selected_node(
        self, sid: str, request: WorkflowMCPGetSelectedNodeRequest
    ) -> None:
        """
        Get the currently selected node in the workflow canvas.

        Returns null if no node is selected. If a node is selected, also
        prefetches available mock outputs for that node type.
        """
        try:
            result = await self._request_frontend(sid, 'get_selected')

            response_data = {"selected_node": result}

            # If a node is selected, prefetch available mocks for convenience
            if result and isinstance(result, dict) and result.get("type"):
                node_type = result.get("type")
                user_id = await self._get_user_id(sid, request)

                if user_id:
                    available_mocks = await self._get_available_mocks_preview(
                        user_id, node_type, limit=5
                    )
                    if available_mocks:
                        response_data["available_mocks"] = available_mocks

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response_data
            ))
        except asyncio.TimeoutError:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error="Frontend did not respond in time"
            ))
        except RuntimeError as e:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))
        except Exception as e:
            logger.error(f"Error getting selected node: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def get_open_workflow(
        self, sid: str, request: WorkflowMCPGetOpenWorkflowRequest
    ) -> None:
        """
        Get the currently open workflow in the editor.

        Returns the workflow_id, nodes summary, and running state.
        Returns null if no workflow is open in the frontend.
        """
        try:
            result = await self._request_frontend(sid, 'get_state')

            if not result or not result.get("workflowId"):
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={"workflow": None, "message": "No workflow is currently open"}
                ))
                return

            # Return a summary of the open workflow
            # If include_configs is True, include full node data
            if request.include_configs:
                nodes_data = [
                    {
                        "id": n.get("id"),
                        "type": n.get("type"),
                        "position": n.get("position"),
                        "config": n.get("data", {}),
                    }
                    for n in result.get("nodes", [])
                ]
            else:
                nodes_data = [
                    {
                        "id": n.get("id"),
                        "type": n.get("type"),
                    }
                    for n in result.get("nodes", [])
                ]

            workflow_summary = {
                "workflow_id": result.get("workflowId"),
                "node_count": len(result.get("nodes", [])),
                "edge_count": len(result.get("edges", [])),
                "is_running": result.get("isRunning", False),
                "selected_node_id": result.get("selectedNodeId"),
                "nodes": nodes_data,
            }

            # Include edges if configs requested (more detailed view)
            if request.include_configs:
                workflow_summary["edges"] = [
                    {
                        "id": e.get("id"),
                        "source": e.get("source"),
                        "target": e.get("target"),
                    }
                    for e in result.get("edges", [])
                ]

            # Include interface block layout info if available
            interface_data = result.get("interface")
            if interface_data:
                layout_by_id = {item["i"]: item for item in interface_data.get("layout", [])}
                workflow_summary["interface"] = {
                    "blocks": [
                        {
                            "id": b["id"],
                            "type": b["type"],
                            **{k: layout_by_id.get(b["id"], {}).get(k) for k in ("x", "y", "w", "h")}
                        }
                        for b in interface_data.get("blocks", [])
                        if b["id"] in layout_by_id
                    ]
                }

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"workflow": workflow_summary}
            ))
        except asyncio.TimeoutError:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"workflow": None},
                error="Frontend did not respond in time. User may not have a workflow open."
            ))
        except RuntimeError as e:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"workflow": None},
                error=str(e)
            ))
        except Exception as e:
            logger.error(f"Error getting open workflow: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"workflow": None},
                error=str(e)
            ))

    async def get_node_output(
        self, sid: str, request: WorkflowMCPGetNodeOutputRequest
    ) -> None:
        """
        Get the execution output of a workflow node (backend-only, database-backed).

        Returns the node's output data, or mockedOutput if set.
        """
        try:
            # Get user_id (injected by MCP transport or from session)
            user_id = await self._get_user_id(sid, request)

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            # Load workflow from database
            workflow_data, error = await self._load_workflow(user_id, request.workflow_id)
            if error:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=error
                ))
                return

            nodes = workflow_data.get("nodes", [])

            # Find the node
            target_node = None
            for node in nodes:
                if node.get("id") == request.node_id:
                    target_node = node
                    break

            if not target_node:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=f"Node not found: {request.node_id}"
                ))
                return

            # Get output - prefer mockedOutput if set, otherwise use actual output
            _config = target_node.get("config", {}) or {}

            # 1. mockedOutput takes priority
            output = _config.get("mockedOutput")
            is_mocked = output is not None

            if not is_mocked:
                # 2. Latest output from the content-addressed store (sole store).
                try:
                    from utils.node_outputs import latest_output
                    pool = await self.get_pool()
                    if pool:
                        output = await latest_output(pool, request.workflow_id, request.node_id)
                except Exception as e:
                    logger.debug(f"[MCP] Failed to read node output from CAS: {e}")

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={
                    "node_id": request.node_id,
                    "output": output,
                    "is_mocked": is_mocked,
                    "status": _config.get("status", "idle")
                }
            ))

        except Exception as e:
            logger.error(f"Error getting node output: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def get_node_input(
        self, sid: str, request: WorkflowMCPGetNodeInputRequest
    ) -> None:
        """
        Get the input data flowing into a node (backend-only, database-backed).

        Returns outputs from all connected upstream nodes.
        """
        try:
            # Get user_id (injected by MCP transport or from session)
            user_id = await self._get_user_id(sid, request)

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            # Load workflow from database
            workflow_data, error = await self._load_workflow(user_id, request.workflow_id)
            if error:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=error
                ))
                return

            nodes = workflow_data.get("nodes", [])
            edges = workflow_data.get("edges", [])

            # Check if target node exists
            target_exists = any(n.get("id") == request.node_id for n in nodes)
            if not target_exists:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=f"Node not found: {request.node_id}"
                ))
                return

            # Find all edges targeting this node
            incoming_edges = [e for e in edges if e.get("target") == request.node_id]
            source_ids = [e.get("source") for e in incoming_edges if e.get("source")]
            node_by_id = {n.get("id"): n for n in nodes}

            # mockedOutput (a config field, still stored in the graph) takes
            # priority; otherwise the source node's latest real output comes from
            # the CAS (the sole output store — never the graph JSONB).
            pool = await self.get_pool()
            from utils.node_outputs import latest_outputs
            cas_outputs = (
                await latest_outputs(pool, request.workflow_id, source_ids)
                if pool and source_ids else {}
            )

            inputs = {}
            for source_id in source_ids:
                node = node_by_id.get(source_id)
                mocked = (node.get("config", {}) or {}).get("mockedOutput") if node else None
                output = mocked if mocked is not None else cas_outputs.get(source_id)
                if output is not None:
                    inputs[source_id] = output

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={
                    "node_id": request.node_id,
                    "inputs": inputs,
                    "source_node_ids": [e.get("source") for e in incoming_edges]
                }
            ))

        except Exception as e:
            logger.error(f"Error getting node input: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    # =========================================================================
    # Workflow Execution Tools
    # =========================================================================

    async def run_workflow(
        self, sid: str, request: WorkflowMCPRunWorkflowRequest
    ) -> None:
        """
        Execute a workflow (backend-only, database-backed).

        Loads the workflow from the database and executes it without
        requiring a frontend connection. Returns immediately after
        starting execution - use get_node_output() to wait for results.
        """
        try:
            # Get user_id (injected by MCP transport or from session)
            user_id = await self._get_user_id(sid, request)

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            # Load workflow from database
            workflow_data, error = await self._load_workflow(user_id, request.workflow_id)
            if error:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=error
                ))
                return

            nodes = workflow_data.get("nodes", [])
            edges = workflow_data.get("edges", [])

            # Transform nodes to execution format (move data to config)
            execution_nodes = self._prepare_nodes_for_execution(nodes)

            # Create execution record upfront so we can return execution_id immediately
            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            async with pool.acquire() as conn:
                execution_id = await WorkflowRepo(pool).create_execution(
                    conn,
                    workflow_id=request.workflow_id,
                    user_id=user_id,
                    trigger_source='mcp',
                )

            # Create workflow execute request
            execute_request = WorkflowExecuteRequest(
                request_id=f"mcp_exec_{uuid.uuid4()}",
                workflow_id=request.workflow_id,
                nodes=execution_nodes,
                edges=edges
            )
            # Copy _user_id from original request (for MCP OAuth contexts)
            if hasattr(request, '_user_id') and request._user_id:
                execute_request._user_id = request._user_id

            # Return immediately with execution_id for tracking
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={
                    "execution_id": execution_id,
                    "workflow_id": request.workflow_id,
                    "status": "running",
                    "node_count": len(nodes)
                }
            ))

            # Execute workflow using the execution handler (runs in background)
            from utils.async_helpers import spawn
            execution_handler = WorkflowExecutionHandler(self.sio)
            spawn(
                execution_handler.handle_execute(sid, execute_request, execution_id),
                name=f"mcp-workflow-execute:{execution_id}",
            )

        except Exception as e:
            logger.error(f"Error running workflow: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def create_workflow(
        self, sid: str, request: WorkflowMCPCreateWorkflowRequest
    ) -> None:
        """
        Create a new workflow and open it in the editor.

        Creates the workflow in the database and notifies the frontend to
        navigate to it.
        """
        try:
            # Get user_id (injected by MCP transport or from session)
            user_id = await self._get_user_id(sid, request)

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

            # Create workflow in database
            default_permissions = {"public": [], "shared_with": {}}
            async with pool.acquire() as conn:
                # Check workflow limit
                from billing.plan_limits import check_workflow_limit
                session = await self.sio.get_session(sid)
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free') if session else 'free'
                can_create, limit_error = await check_workflow_limit(conn, user_id, user_tier)
                if not can_create:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error=limit_error
                    ))
                    return

                repo = WorkflowRepo(pool)

                # Validate folder access if folder_id is provided
                folder_id = getattr(request, 'folder_id', None)
                if folder_id:
                    has_access = await OrgRepo(pool).can_access_folder(conn, user_id, folder_id)
                    if not has_access:
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request.request_id,
                            data={},
                            error="Invalid folder or access denied"
                        ))
                        return

                row = await repo.create_workflow_mcp(
                    conn,
                    owner_id=user_id,
                    name=request.name,
                    description=request.description or '',
                    workflow_data={},
                    permissions=default_permissions,
                    folder_id=folder_id,
                )

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Failed to create workflow"
                    ))
                    return

                workflow_id = str(row['id'])

            # Notify frontend to navigate to the new workflow
            await self._request_frontend(
                sid,
                'open_workflow',
                params={"workflow_id": workflow_id}
            )

            # Send response with dual-delivery so workflow browser updates
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WorkflowMCPCreateWorkflowResponse(
                    success=True,
                    workflow_id=workflow_id,
                    name=row['name'],
                    description=row['description'] or None,
                    message="Workflow created successfully"
                )
            ))

        except asyncio.TimeoutError:
            # Even if frontend navigation times out, workflow was created
            # Still send dual-delivery response so workflow browser updates
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WorkflowMCPCreateWorkflowResponse(
                    success=True,
                    workflow_id=workflow_id,
                    name=request.name,
                    description=request.description,
                    message="Workflow created but frontend navigation timed out"
                )
            ))
        except Exception as e:
            logger.error(f"Error creating workflow: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def open_workflow(
        self, sid: str, request: WorkflowMCPOpenWorkflowRequest
    ) -> None:
        """
        Open an existing workflow in the editor.

        Navigates the frontend to display the specified workflow.
        """
        try:
            # Request frontend to navigate to the workflow
            result = await self._request_frontend(
                sid,
                'open_workflow',
                params={"workflow_id": request.workflow_id}
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"workflow_id": request.workflow_id, "success": True}
            ))
        except asyncio.TimeoutError:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error="Frontend did not respond in time"
            ))
        except RuntimeError as e:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))
        except Exception as e:
            logger.error(f"Error opening workflow: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def list_workflows(
        self, sid: str, request: WorkflowMCPListWorkflowsRequest
    ) -> None:
        """
        List available workflows owned by the user.

        Optionally filters by search query on name and description.
        """
        try:
            # Get user_id (injected by MCP transport or from session)
            user_id = await self._get_user_id(sid, request)

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
                rows = await WorkflowRepo(pool).list_workflows_mcp(
                    conn,
                    user_id=user_id,
                    query=request.query,
                    folder_id=getattr(request, 'folder_id', None),
                    limit=request.limit,
                )

                workflows = [
                    {
                        "id": str(row['id']),
                        "name": row['name'],
                        "description": row['description'] or "",
                        "folder_id": str(row['folder_id']) if row['folder_id'] else None,
                        "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                        "updated_at": row['updated_at'].isoformat() if row['updated_at'] else None,
                    }
                    for row in rows
                ]

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"workflows": workflows}
            ))

        except Exception as e:
            logger.error(f"Error listing workflows: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def delete_workflow(
        self, sid: str, request: WorkflowMCPDeleteWorkflowRequest
    ) -> None:
        """
        Delete a workflow from the database.

        Permanently removes the workflow and all its nodes/edges.
        """
        try:
            # Get user_id (injected by MCP transport or from session)
            user_id = await self._get_user_id(sid, request)

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowMCPDeleteWorkflowResponse(
                        success=False,
                        workflow_id=request.workflow_id,
                        message="User not authenticated"
                    )
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowMCPDeleteWorkflowResponse(
                        success=False,
                        workflow_id=request.workflow_id,
                        message="Database connection not available"
                    )
                ))
                return

            async with pool.acquire() as conn:
                # Only owners can delete workflows
                access = await check_resource_access(
                    conn, user_id, "workflow", request.workflow_id
                )

                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=WorkflowMCPDeleteWorkflowResponse(
                            success=False,
                            workflow_id=request.workflow_id,
                            message="Workflow not found or access denied"
                        )
                    ))
                    return

                if access.permission != Permission.OWNER:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=WorkflowMCPDeleteWorkflowResponse(
                            success=False,
                            workflow_id=request.workflow_id,
                            message="Only the owner can delete this workflow"
                        )
                    ))
                    return

                # Cleanup operational resources (cron + webhooks) before trashing
                from utils.workflow_resource_manager import cleanup_workflow_operational_resources
                await cleanup_workflow_operational_resources(
                    pool=pool,
                    workflow_id=request.workflow_id
                )

                # Soft-delete: move to trash
                await WorkflowRepo(pool).soft_delete_workflow_by_id(
                    conn, uuid.UUID(request.workflow_id),
                )

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WorkflowMCPDeleteWorkflowResponse(
                    success=True,
                    workflow_id=request.workflow_id,
                    message="Workflow moved to trash"
                )
            ))

        except Exception as e:
            logger.error(f"Error deleting workflow: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WorkflowMCPDeleteWorkflowResponse(
                    success=False,
                    workflow_id=request.workflow_id,
                    message=str(e)
                )
            ))

    async def update_workflow_metadata(
        self, sid: str, request: WorkflowMCPUpdateWorkflowMetadataRequest
    ) -> None:
        """
        Update a workflow's metadata (name and description).

        Only updates fields that are provided; others remain unchanged.
        """
        try:
            # Get user_id (injected by MCP transport or from session)
            user_id = await self._get_user_id(sid, request)

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowMCPUpdateWorkflowMetadataResponse(
                        success=False,
                        workflow_id=request.workflow_id,
                        message="User not authenticated"
                    )
                ))
                return

            if request.name is None and request.description is None:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowMCPUpdateWorkflowMetadataResponse(
                        success=False,
                        workflow_id=request.workflow_id,
                        message="No fields to update (provide name or description)"
                    )
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowMCPUpdateWorkflowMetadataResponse(
                        success=False,
                        workflow_id=request.workflow_id,
                        message="Database connection not available"
                    )
                ))
                return

            async with pool.acquire() as conn:
                # Check edit access (owner, org member, or shared with edit permission)
                access = await check_resource_access(
                    conn, user_id, "workflow", request.workflow_id
                )

                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=WorkflowMCPUpdateWorkflowMetadataResponse(
                            success=False,
                            workflow_id=request.workflow_id,
                            message="Workflow not found or access denied"
                        )
                    ))
                    return

                if access.permission not in (Permission.EDIT, Permission.OWNER):
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=WorkflowMCPUpdateWorkflowMetadataResponse(
                            success=False,
                            workflow_id=request.workflow_id,
                            message="You don't have permission to edit this workflow"
                        )
                    ))
                    return

                # Dynamic UPDATE via repo (columns allowlist enforced there).
                update_dict: Dict[str, Any] = {}
                if request.name is not None:
                    update_dict["name"] = request.name
                if request.description is not None:
                    update_dict["description"] = request.description

                row = await WorkflowRepo(pool).update_workflow_metadata(
                    conn, uuid.UUID(request.workflow_id), update_dict,
                )

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=WorkflowMCPUpdateWorkflowMetadataResponse(
                            success=False,
                            workflow_id=request.workflow_id,
                            message="Workflow not found"
                        )
                    ))
                    return

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WorkflowMCPUpdateWorkflowMetadataResponse(
                    success=True,
                    workflow_id=request.workflow_id,
                    name=row['name'],
                    description=row['description'],
                    message="Workflow updated successfully"
                )
            ))

        except Exception as e:
            logger.error(f"Error updating workflow metadata: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WorkflowMCPUpdateWorkflowMetadataResponse(
                    success=False,
                    workflow_id=request.workflow_id,
                    message=str(e)
                )
            ))

    async def list_saved_outputs(
        self, sid: str, request: WorkflowMCPListSavedOutputsRequest
    ) -> None:
        """
        List saved mock outputs for a node type.

        Returns outputs that can be used to mock node execution.
        """
        try:
            # Get user_id (injected by MCP transport or from session)
            user_id = await self._get_user_id(sid, request)

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
                # Get saved outputs visible to user (own + public)
                rows = await conn.fetch("""
                    SELECT id, name, node_type, output, visibility, created_at, updated_at
                    FROM workflow_saved_output
                    WHERE node_type = $1
                      AND (user_id = $2 OR visibility = 'public')
                    ORDER BY updated_at DESC
                """, request.node_type, user_id)

                saved_outputs = [
                    {
                        "id": str(row['id']),
                        "name": row['name'],
                        "node_type": row['node_type'],
                        "output": row['output'],
                        "visibility": row['visibility'],
                        "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                        "updated_at": row['updated_at'].isoformat() if row['updated_at'] else None,
                    }
                    for row in rows
                ]

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"saved_outputs": saved_outputs, "node_type": request.node_type}
            ))

        except Exception as e:
            logger.error(f"Error listing saved outputs: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def run_node(
        self, sid: str, request: WorkflowMCPRunNodeRequest
    ) -> None:
        """
        Execute a single node (backend-only, database-backed).

        Uses outputs from predecessor nodes as mocked inputs.
        All predecessor nodes must have output data available (either
        from prior execution or explicit mocked data).
        """
        try:
            # Get user_id (injected by MCP transport or from session)
            user_id = await self._get_user_id(sid, request)

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            # Load workflow from database
            workflow_data, error = await self._load_workflow(user_id, request.workflow_id)
            if error:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=error
                ))
                return

            nodes = workflow_data.get("nodes", [])
            edges = workflow_data.get("edges", [])

            # Find the target node
            target_node = None
            for node in nodes:
                if node.get("id") == request.node_id:
                    target_node = node
                    break

            if not target_node:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=f"Node not found: {request.node_id}"
                ))
                return

            # Find all predecessor nodes
            all_node_ids = {n.get("id") for n in nodes}
            predecessor_ids = self._find_predecessors(request.node_id, edges, all_node_ids)

            # Build nodes lookup for easy access
            nodes_by_id = {n.get("id"): n for n in nodes}

            # Verify all predecessors have output data and build mock nodes
            missing_outputs = []
            execution_nodes = []

            for pred_id in predecessor_ids:
                pred_node = nodes_by_id.get(pred_id)
                if not pred_node:
                    continue

                _pred_config = pred_node.get("config", {}) or {}
                # Get output - prefer mockedOutput if set, otherwise use actual output
                output = _pred_config.get("mockedOutput") or _pred_config.get("output")

                if output is None:
                    missing_outputs.append(pred_id)
                else:
                    # Create a mock node that will immediately return its output
                    pred_config = dict(_pred_config)
                    pred_config["mockedOutput"] = output

                    execution_nodes.append({
                        "id": pred_id,
                        "type": pred_node.get("type", "unknown"),
                        "config": pred_config
                    })

            if missing_outputs:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=f"Predecessor nodes missing output: {', '.join(missing_outputs)}"
                ))
                return

            # Add the target node (without mocking - it will execute normally)
            _target_config = target_node.get("config", {}) or {}
            target_config = dict(_target_config)
            # Don't include mockedOutput for target - we want it to execute
            if _target_config.get("disabled"):
                target_config["disabled"] = True

            execution_nodes.append({
                "id": request.node_id,
                "type": target_node.get("type", "unknown"),
                "config": target_config
            })

            # Build subset edges (only edges between nodes we're executing)
            execution_node_ids = {n["id"] for n in execution_nodes}
            execution_edges = [
                e for e in edges
                if e.get("source") in execution_node_ids and e.get("target") in execution_node_ids
            ]

            # Create workflow execute request
            execute_request = WorkflowExecuteRequest(
                request_id=f"mcp_node_exec_{uuid.uuid4()}",
                workflow_id=request.workflow_id,
                nodes=execution_nodes,
                edges=execution_edges
            )
            # Copy _user_id from original request (for MCP OAuth contexts)
            if hasattr(request, '_user_id') and request._user_id:
                execute_request._user_id = request._user_id

            # Return immediately - execution is async
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={
                    "node_id": request.node_id,
                    "started": True,
                    "predecessor_count": len(predecessor_ids)
                }
            ))

            # Execute using the execution handler (runs in background)
            from utils.async_helpers import spawn
            execution_handler = WorkflowExecutionHandler(self.sio)
            spawn(
                execution_handler.handle_execute(sid, execute_request),
                name="mcp-node-execute",
            )

        except Exception as e:
            logger.error(f"Error running node: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def get_execution_status(
        self, sid: str, request: "WorkflowMCPGetExecutionStatusRequest"
    ) -> None:
        """
        Get the status of a workflow execution.

        Use this after run_workflow to check if execution completed,
        failed with an error, or is still running.
        """
        try:
            # Get user_id (injected by MCP transport or from session)
            user_id = await self._get_user_id(sid, request)

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            # Must have either execution_id or workflow_id
            if not request.execution_id and not request.workflow_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Either execution_id or workflow_id is required"
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
                repo = WorkflowRepo(pool)
                if request.execution_id:
                    row = await repo.get_execution_by_id_and_user(
                        conn, request.execution_id, user_id,
                    )
                else:
                    row = await repo.get_latest_execution_by_workflow_and_user(
                        conn, request.workflow_id, user_id,
                    )

            if not row:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Execution not found"
                ))
                return

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={
                    "execution_id": str(row['id']),
                    "workflow_id": str(row['workflow_id']),
                    "status": row['status'],
                    "started_at": row['started_at'].isoformat() if row['started_at'] else None,
                    "finished_at": row['finished_at'].isoformat() if row['finished_at'] else None,
                    "nodes_executed": row['nodes_executed'],
                    "error": row['error']
                }
            ))

        except Exception as e:
            logger.error(f"Error getting execution status: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def list_credentials(
        self, sid: str, request: "WorkflowMCPListCredentialsRequest"
    ) -> None:
        """
        List available credentials for the user.

        Optionally filter by credential_type to find credentials for specific node types.
        """
        try:
            user_id = await self._get_user_id(sid, request)
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
                if request.credential_type:
                    rows = await conn.fetch("""
                        SELECT id, name, credential_type, metadata, created_at, updated_at
                        FROM credentials
                        WHERE owner_id = $1 AND credential_type = $2
                        ORDER BY created_at DESC
                    """, user_id, request.credential_type)
                else:
                    rows = await conn.fetch("""
                        SELECT id, name, credential_type, metadata, created_at, updated_at
                        FROM credentials
                        WHERE owner_id = $1
                        ORDER BY created_at DESC
                    """, user_id)

                credentials = []
                for row in rows:
                    credentials.append({
                        "id": str(row['id']),
                        "name": row['name'],
                        "credential_type": row['credential_type'],
                        "metadata": row['metadata'],
                        "created_at": row['created_at'].isoformat(),
                        "updated_at": row['updated_at'].isoformat()
                    })

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={
                        "credentials": credentials,
                        "total": len(credentials)
                    }
                ))
                logger.info(f"[WorkflowMCPHandler] Listed {len(credentials)} credentials for user")

        except Exception as e:
            logger.error(f"Error listing credentials: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def load_field_options(
        self, sid: str, request: "WorkflowMCPLoadFieldOptionsRequest"
    ) -> None:
        """
        Load dynamic options for a node configuration field.

        Supports searching/filtering options and pagination.
        """
        try:
            user_id = await self._get_user_id(sid, request)
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            # Get node class from registry
            node_class = NODE_REGISTRY.get(request.node_type)
            if not node_class:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=f"Unknown node type: {request.node_type}"
                ))
                return

            # Check if node supports dynamic options
            if not hasattr(node_class, 'load_field_options'):
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=f"Node type {request.node_type} does not support dynamic options"
                ))
                return

            # Get credential type for this node
            credential_type = None
            config_model = node_class.get_config_model()
            if config_model and hasattr(config_model, 'model_fields'):
                credentials_field = config_model.model_fields.get('credentials')
                if credentials_field and credentials_field.annotation:
                    credential_type = self._extract_credential_type(credentials_field.annotation)

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            async with pool.acquire() as conn:
                # Find credential - either by ID or first matching type
                if request.credential_id:
                    row = await conn.fetchrow("""
                        SELECT id, credential
                        FROM credentials
                        WHERE id = $1 AND owner_id = $2
                    """, request.credential_id, user_id)
                elif credential_type:
                    row = await conn.fetchrow("""
                        SELECT id, credential
                        FROM credentials
                        WHERE owner_id = $1 AND credential_type = $2
                        ORDER BY created_at DESC
                        LIMIT 1
                    """, user_id, credential_type)
                else:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="No credential_id provided and could not determine credential type for node"
                    ))
                    return

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error=f"No credential found. Please connect a {credential_type or 'required'} account first."
                    ))
                    return

                # Decrypt credential
                from utils.encryption import get_encryption
                try:
                    encryption = get_encryption()
                    credential_data = encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"Error decrypting credential: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Failed to decrypt credential"
                    ))
                    return

            # Call node's load_field_options method
            try:
                # Refresh expiring OAuth tokens at load so option queries never
                # hit the provider with a stale token (no-op for nodes that
                # don't override freshen_credential).
                if credential_data:
                    from nodes.core.oauth_audit import caller_path_scope
                    with caller_path_scope("dropdown"):
                        credential_data = await node_class.freshen_credential(
                            credential_data,
                            pool=pool,
                            user_id=user_id,
                            credential_id=str(row['id']),
                        )

                options = await node_class.load_field_options(
                    field_name=request.field_name,
                    credential_data=credential_data,
                    context=request.depends_on or {}
                )

                # Apply search filter if provided
                if request.search_query:
                    search_lower = request.search_query.lower()
                    options = [
                        opt for opt in options
                        if search_lower in opt.get('label', '').lower()
                        or search_lower in opt.get('value', '').lower()
                    ]

                # Get total before pagination
                total = len(options)

                # Apply pagination
                options = options[request.offset:request.offset + request.limit]

                # Format response
                formatted_options = [
                    {
                        "value": opt['value'],
                        "label": opt['label'],
                        "metadata": opt.get('metadata')
                    }
                    for opt in options
                ]

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={
                        "options": formatted_options,
                        "total": total,
                        "has_more": request.offset + len(options) < total,
                        "credential_id": str(row['id'])
                    }
                ))
                logger.info(f"[WorkflowMCPHandler] Loaded {len(formatted_options)} options for {request.node_type}.{request.field_name}")

            except Exception as e:
                logger.error(f"Error loading field options: {e}", exc_info=True)
                # Loaders raise ValueError with a user-facing message (missing
                # credential, API error). Surface it verbatim; wrap only
                # unexpected exceptions so a real bug still reads as a failure.
                message = str(e) if isinstance(e, ValueError) else f"Failed to load options: {str(e)}"
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=message
                ))

        except Exception as e:
            logger.error(f"Error in load_field_options: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def get_node_config(
        self, sid: str, request: WorkflowMCPGetNodeConfigRequest
    ) -> None:
        """
        Get a specific node's configuration by ID.

        Returns the full node data including type, position, and config.
        """
        try:
            user_id = await self._get_user_id(sid, request)
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowMCPGetNodeConfigResponse(
                        success=False,
                        workflow_id=request.workflow_id,
                        node_id=request.node_id,
                        message="User not authenticated"
                    )
                ))
                return

            workflow_data, error = await self._load_workflow(user_id, request.workflow_id)
            if error:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowMCPGetNodeConfigResponse(
                        success=False,
                        workflow_id=request.workflow_id,
                        node_id=request.node_id,
                        message=error
                    )
                ))
                return

            nodes = workflow_data.get("nodes", [])
            target_node = None
            for node in nodes:
                if node.get("id") == request.node_id:
                    target_node = node
                    break

            if not target_node:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowMCPGetNodeConfigResponse(
                        success=False,
                        workflow_id=request.workflow_id,
                        node_id=request.node_id,
                        message=f"Node {request.node_id} not found"
                    )
                ))
                return

            _config = target_node.get("config", {}) or {}

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WorkflowMCPGetNodeConfigResponse(
                    success=True,
                    workflow_id=request.workflow_id,
                    node_id=request.node_id,
                    node_type=target_node.get("type"),
                    position=target_node.get("position"),
                    config=_config
                )
            ))

        except Exception as e:
            logger.error(f"Error getting node config: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WorkflowMCPGetNodeConfigResponse(
                    success=False,
                    workflow_id=request.workflow_id,
                    node_id=request.node_id,
                    message=str(e)
                )
            ))

    # =========================================================================
    # Interface Layout
    # =========================================================================

    GRID_COLS = 12
    _DEFAULT_LAYOUT = {"defaultW": 6, "defaultH": 4, "minW": 3, "minH": 2}

    @staticmethod
    def _get_interface_block_constraints() -> Dict[str, Dict[str, int]]:
        """Build block constraints from NODE_REGISTRY at runtime."""
        constraints: Dict[str, Dict[str, int]] = {}
        for node_type, node_cls in NODE_REGISTRY.items():
            if not node_type.startswith("interface-"):
                continue
            block_type = node_type[len("interface-"):]
            layout = getattr(node_cls, "grid_layout", None)
            if layout:
                constraints[block_type] = layout
        return constraints

    @staticmethod
    def _derive_block_type(node_type: str) -> Optional[str]:
        """Derive block type from interface node type (e.g. 'interface-markdown' -> 'markdown')."""
        if not node_type.startswith("interface-"):
            return None
        return node_type[len("interface-"):]

    @staticmethod
    def _check_overlaps(layout: List[Dict[str, Any]]) -> Optional[str]:
        """Check for overlapping blocks in the layout. Returns error message or None."""
        for i, a in enumerate(layout):
            for b in layout[i + 1:]:
                if (a["x"] < b["x"] + b["w"] and a["x"] + a["w"] > b["x"] and
                        a["y"] < b["y"] + b["h"] and a["y"] + a["h"] > b["y"]):
                    return f"Blocks {a['i']} and {b['i']} overlap"
        return None

    @staticmethod
    def _auto_layout(
        layout_by_id: Dict[str, Dict[str, Any]],
        blocks_by_id: Dict[str, Dict[str, Any]],
        interface_nodes: Dict[str, str],
        constraints: Dict[str, Dict[str, int]],
        strategy: str = "grid",
    ) -> None:
        """Auto-arrange blocks in the layout. Mutates layout_by_id in place."""
        block_ids = list(layout_by_id.keys())
        if not block_ids:
            return

        if strategy == "stack":
            # Single column vertical stack
            y = 0
            for bid in block_ids:
                block_type = interface_nodes.get(bid, "")
                c = constraints.get(block_type, {"defaultW": 6, "defaultH": 4})
                w = min(c["defaultW"], 12)
                h = c["defaultH"]
                layout_by_id[bid] = {"i": bid, "x": 0, "y": y, "w": w, "h": h}
                y += h
        else:
            # 2-column balanced grid (left col x=0..5, right col x=6..11)
            left_y = 0
            right_y = 0
            for bid in block_ids:
                block_type = interface_nodes.get(bid, "")
                c = constraints.get(block_type, {"defaultW": 6, "defaultH": 4})
                w = min(c["defaultW"], 6)
                h = c["defaultH"]
                # Place in the column with less height
                if left_y <= right_y:
                    layout_by_id[bid] = {"i": bid, "x": 0, "y": left_y, "w": w, "h": h}
                    left_y += h
                else:
                    layout_by_id[bid] = {"i": bid, "x": 6, "y": right_y, "w": w, "h": h}
                    right_y += h

    async def update_interface(
        self, sid: str, request: WorkflowMCPUpdateInterfaceRequest
    ) -> None:
        """
        Update the interface layout for a workflow.

        Parses XML commands to position/resize interface blocks on the 12-column grid.
        """
        try:
            user_id = await self._get_user_id(sid, request)
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowMCPUpdateInterfaceResponse(
                        success=False, workflow_id=request.workflow_id,
                        message="User not authenticated"
                    )
                ))
                return

            workflow_data, error = await self._load_workflow(user_id, request.workflow_id)
            if error:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowMCPUpdateInterfaceResponse(
                        success=False, workflow_id=request.workflow_id,
                        message=error
                    )
                ))
                return

            nodes = workflow_data.get("nodes", [])
            interface = workflow_data.get("interface") or {"layout": [], "blocks": []}
            constraints = self._get_interface_block_constraints()

            # Build interface_nodes map: node_id -> block_type
            interface_nodes: Dict[str, str] = {}
            for node in nodes:
                node_type = node.get("type", "")
                block_type = self._derive_block_type(node_type)
                if block_type is not None:
                    interface_nodes[node["id"]] = block_type

            # Index current layout and blocks
            layout_by_id: Dict[str, Dict[str, Any]] = {
                item["i"]: item for item in interface.get("layout", [])
            }
            blocks_by_id: Dict[str, Dict[str, Any]] = {
                b["id"]: b for b in interface.get("blocks", [])
            }

            # Auto-create blocks/layout for interface nodes not yet on the grid
            bottom_y = max((item["y"] + item["h"] for item in layout_by_id.values()), default=0)
            for nid, btype in interface_nodes.items():
                if nid not in layout_by_id:
                    c = constraints.get(btype, self._DEFAULT_LAYOUT)
                    layout_by_id[nid] = {
                        "i": nid, "x": 0, "y": bottom_y,
                        "w": c["defaultW"], "h": c["defaultH"],
                    }
                    bottom_y += c["defaultH"]
                if nid not in blocks_by_id:
                    blocks_by_id[nid] = {"id": nid, "type": btype, "config": {"label": btype.capitalize()}}

            # Parse XML commands
            try:
                root = ET.fromstring(f"<root>{request.updates_xml}</root>")
            except ET.ParseError as e:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowMCPUpdateInterfaceResponse(
                        success=False, workflow_id=request.workflow_id,
                        message=f"Invalid XML: {e}"
                    )
                ))
                return

            # Process commands
            for elem in root:
                tag = elem.tag

                if tag == "set_block_layout":
                    block_id = elem.get("id", "")
                    if block_id not in interface_nodes:
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request.request_id,
                            data=WorkflowMCPUpdateInterfaceResponse(
                                success=False, workflow_id=request.workflow_id,
                                message=f"'{block_id}' is not an interface node"
                            )
                        ))
                        return

                    x = int(elem.get("x", "0"))
                    y = int(elem.get("y", "0"))
                    w = int(elem.get("w", str(layout_by_id.get(block_id, {}).get("w", 6))))
                    h = int(elem.get("h", str(layout_by_id.get(block_id, {}).get("h", 4))))

                    # Validate bounds
                    btype = interface_nodes[block_id]
                    c = constraints.get(btype, self._DEFAULT_LAYOUT)
                    if x < 0 or y < 0:
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request.request_id,
                            data=WorkflowMCPUpdateInterfaceResponse(
                                success=False, workflow_id=request.workflow_id,
                                message=f"Block {block_id}: x and y must be >= 0"
                            )
                        ))
                        return
                    if x + w > self.GRID_COLS:
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request.request_id,
                            data=WorkflowMCPUpdateInterfaceResponse(
                                success=False, workflow_id=request.workflow_id,
                                message=f"Block {block_id}: x({x}) + w({w}) exceeds grid width ({self.GRID_COLS})"
                            )
                        ))
                        return
                    if w < c.get("minW", 1):
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request.request_id,
                            data=WorkflowMCPUpdateInterfaceResponse(
                                success=False, workflow_id=request.workflow_id,
                                message=f"Block {block_id}: w({w}) < minW({c['minW']}) for type '{btype}'"
                            )
                        ))
                        return
                    if h < c.get("minH", 1):
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request.request_id,
                            data=WorkflowMCPUpdateInterfaceResponse(
                                success=False, workflow_id=request.workflow_id,
                                message=f"Block {block_id}: h({h}) < minH({c['minH']}) for type '{btype}'"
                            )
                        ))
                        return

                    layout_by_id[block_id] = {"i": block_id, "x": x, "y": y, "w": w, "h": h}

                elif tag == "remove_block":
                    block_id = elem.get("id", "")
                    layout_by_id.pop(block_id, None)
                    blocks_by_id.pop(block_id, None)

                elif tag == "auto_layout":
                    strategy = elem.get("strategy", "grid")
                    self._auto_layout(layout_by_id, blocks_by_id, interface_nodes, constraints, strategy)

                else:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=WorkflowMCPUpdateInterfaceResponse(
                            success=False, workflow_id=request.workflow_id,
                            message=f"Unknown command: <{tag}>"
                        )
                    ))
                    return

            # Check for overlaps
            final_layout = list(layout_by_id.values())
            overlap_err = self._check_overlaps(final_layout)
            if overlap_err:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowMCPUpdateInterfaceResponse(
                        success=False, workflow_id=request.workflow_id,
                        message=f"Overlap detected: {overlap_err}"
                    )
                ))
                return

            # Build final state
            interface_state = {
                "layout": final_layout,
                "blocks": list(blocks_by_id.values()),
            }
            workflow_data["interface"] = interface_state

            # Save to database
            save_err = await self._save_workflow(user_id, request.workflow_id, workflow_data)
            if save_err:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WorkflowMCPUpdateInterfaceResponse(
                        success=False, workflow_id=request.workflow_id,
                        message=save_err
                    )
                ))
                return

            # Build block info for response (include minW/minH so agent has constraints)
            block_infos = []
            for item in final_layout:
                bid = item["i"]
                btype = interface_nodes.get(bid, blocks_by_id.get(bid, {}).get("type", "unknown"))
                c = constraints.get(btype, self._DEFAULT_LAYOUT)
                block_infos.append(InterfaceBlockInfo(
                    id=bid, type=btype,
                    x=item["x"], y=item["y"], w=item["w"], h=item["h"],
                    minW=c.get("minW", 2), minH=c.get("minH", 2),
                ))

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WorkflowMCPUpdateInterfaceResponse(
                    success=True,
                    workflow_id=request.workflow_id,
                    blocks=block_infos,
                    interface_state=interface_state,
                )
            ))

        except Exception as e:
            logger.error(f"Error updating interface: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WorkflowMCPUpdateInterfaceResponse(
                    success=False, workflow_id=request.workflow_id,
                    message=str(e)
                )
            ))

    # ------------------------------------------------------------------
    # Fetch node outputs from the dedicated table
    # ------------------------------------------------------------------

    async def get_node_outputs(
        self, sid: str, request: WorkflowGetNodeOutputsRequest
    ) -> None:
        """Return node outputs from the content-addressed store (the sole
        node-output store): per-execution when execution_id is given, else the
        latest output per node across executions."""
        try:
            user_id = await self._get_user_id(sid, request)
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

            # Validate VIEW+ access
            async with pool.acquire() as conn:
                access = await check_resource_access(
                    conn, user_id, "workflow", request.workflow_id
                )
            if not access.has_access:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="No access to workflow"
                ))
                return

            import uuid as _uuid

            from utils.node_outputs import execution_outputs, latest_outputs

            if request.execution_id:
                try:
                    _uuid.UUID(str(request.execution_id))
                except (ValueError, TypeError):
                    # Non-UUID id (optimistic "run-<ts>" entry) — no such run; empty.
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={"outputs": {}}))
                    return
                outputs = await execution_outputs(pool, request.execution_id, request.node_ids)
            else:
                # Per-node latest: the most recent output for each node across
                # all executions (aligned with CAS retention).
                outputs = await latest_outputs(pool, request.workflow_id, request.node_ids)

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"outputs": outputs}
            ))

        except Exception as e:
            logger.error(f"Error fetching node outputs: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def get_node_output_history(
        self, sid: str, request: WorkflowGetNodeOutputHistoryRequest
    ) -> None:
        """Return historical outputs for a specific node across executions."""
        try:
            user_id = await self._get_user_id(sid, request)
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
                access = await check_resource_access(
                    conn, user_id, "workflow", request.workflow_id
                )
            if not access.has_access:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="No access to workflow"
                ))
                return

            from utils.node_outputs import output_history
            history = await output_history(
                pool, request.workflow_id, request.node_id,
                max(1, min(request.limit, MAX_OUTPUT_HISTORY_LIMIT)),
            )

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"history": history}
            ))

        except Exception as e:
            logger.error(f"Error fetching node output history: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))
