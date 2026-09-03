"""
Workflow Execution Handler

Handles workflow execution by processing nodes in topological order based on their connections.
Sends progress updates as nodes execute and final completion event when workflow finishes.
Creates and updates execution records in the database for observability.
"""

import logging
import asyncio
import gc
import os
import time
import re
import json
import threading
import tracemalloc
from datetime import datetime, timezone
from typing import Callable, Dict, List, Any, Union, Tuple, Optional, Set
from collections import defaultdict, deque
from dataclasses import dataclass, field
from utils.async_helpers import spawn
from utils.process_stats import get_rss_mb
from utils.database_pool import DatabasePoolMixin
from utils.credentials import (
    extract_credential_ids,
    get_credential_name,
    get_workflow_owner_id,
    pick_credential_id,
    resolve_credential_with_owner_fallback,
)
from utils.access_control import check_resource_access, Permission
from utils.node_schema_tracker import track_node_schema
from wss.schema import SocketIOHandler
from wss.sender import send_event, is_sdk_client, WorkflowNodeStateEvent, WorkflowNodeOutputEvent, WorkflowStartedEvent, WorkflowCompleteEvent, ResponseEvent, CreditsExhaustedEvent
from wss.receiver.client_events import WorkflowExecuteRequest
from nodes import NodeFactory
from nodes.core.strategy_registry import StrategyRegistry
from nodes.core.execution_strategy import ExecutionContext
from nodes.core.suspend_strategy import SUSPENDED_STATUSES
from nodes.agent.provider_errors import action_for_error_text, describe_failure
from utils.slack import send_activity_notification_background, extract_user_name
from utils.analytics import log_activity_background, set_person_properties_background
from utils.analytics_events import Events
from repositories.workflow import WorkflowRepo
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Node types that are visual-only and should not be executed
# These nodes are filtered out before workflow execution
NON_EXECUTABLE_NODE_TYPES = frozenset([
    'stickyNote',  # Visual annotations/notes on the canvas
])

# Default max concurrent node executions
DEFAULT_MAX_CONCURRENCY = 15
USER_STOPPED_ERROR = "Workflow execution was stopped by user"


@dataclass
class ConcurrentExecutionState:
    """Shared state for concurrent node execution."""
    node_outputs: Dict[str, Any] = field(default_factory=dict)
    completed: Set[str] = field(default_factory=set)
    failed: Set[str] = field(default_factory=set)
    skipped: Set[str] = field(default_factory=set)
    # Nodes that finished via _settings.onError == 'continueErrorOutput' and have a
    # wired error edge (sourceHandle == 'error'). These nodes are still in `completed`
    # (so cascade rules see them as terminal), but downstream routing diverges:
    # edges from the success/default handle are dead, edges from the 'error' handle
    # are live. Nodes whose error handle isn't wired stay out of this set so the
    # legacy "swallow the error, fall through default handle" behavior is preserved.
    error_continuations: Set[str] = field(default_factory=set)
    first_error: Optional[str] = None
    # Per-node error messages (node_id -> message) for nodes in `failed`, so the
    # persisted last-run record can show why a specific node failed, not just the
    # workflow-level first error.
    node_errors: Dict[str, str] = field(default_factory=dict)
    last_output_node_id: Optional[str] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def tag_config_validation_failure(exc: BaseException, node_id: str, node_type: Optional[str]) -> bool:
    """Stamp the active span when a node died on ConfigValidationError — a
    deterministic build→run config-contract defect, distinct from transient
    run failures. Queryable as config_validation_error=true so deterministic
    build-to-run contract defects can be alerted on directly. Best-effort;
    returns whether the exception was that class."""
    from nodes.core.base import ConfigValidationError

    if not isinstance(exc, ConfigValidationError):
        return False
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        span.set_attribute("config_validation_error", True)
        span.set_attribute("config_validation.node_id", node_id)
        span.set_attribute("config_validation.node_type", node_type or "")
    except Exception:
        pass
    return True


def build_node_run_statuses(
    completed: Set[str],
    failed: Set[str],
    skipped: Set[str],
    node_errors: Dict[str, str],
) -> Dict[str, Dict[str, Any]]:
    """Build the per-node last-run record persisted to the CAS (cas_manifests).

    Returns {node_id: {"status": "completed"|"error"|"skipped", "error": <msg|None>}}.
    The finish timestamp is the row's created_at, so it isn't carried here. Pure
    function so it can be unit-tested without a DB. completed/failed are disjoint;
    skipped won't clobber a terminal status.
    """
    statuses: Dict[str, Dict[str, Any]] = {}
    for node_id in completed:
        statuses[node_id] = {"status": "completed", "error": None}
    for node_id in failed:
        err = node_errors.get(node_id)
        statuses[node_id] = {"status": "error", "error": str(err)[:2000] if err else None}
    for node_id in skipped:
        statuses.setdefault(node_id, {"status": "skipped", "error": None})
    return statuses


@dataclass
class WorkflowExecutionResult:
    execution_id: str
    workflow_id: str
    success: bool
    nodes_executed: int
    duration: float
    error: Optional[str]
    node_outputs: Dict[str, Any] = field(default_factory=dict)
    last_output_node_id: Optional[str] = None
    suspended: bool = False


class WorkflowExecutionHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for workflow execution operations"""

    def __init__(self, sio):
        """Initialize the WorkflowExecutionHandler"""
        super().__init__(sio)
        # Track active workflow executions for cancellation support
        # Maps execution_id -> asyncio.Event (set when cancellation requested)
        # Per-execution WebSocket relay connections to workflow relay
        self._execution_relays: Dict[str, Any] = {}  # execution_id -> ExecutionRelay
        # Per-execution last-run node status, built when the executor finishes and
        # consumed (popped) by _persist_node_outputs so headless/webhook runs persist
        # each node's completed/error/skipped status into the CAS (cas_manifests'
        # last_run_status; the timestamp comes from the row's created_at, not this dict).
        # {execution_id: {node_id: {"status", "error"}}}
        self._execution_node_statuses: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # Cache of workflow_id -> owner_id. A workflow's node credentials are
        # resolved as the OWNER at execution (so collaborators can run a shared
        # flow with the owner's credentials without those credentials being shared
        # into their account). Owner is effectively immutable, so caching is safe.
        self._workflow_owner_cache: Dict[str, Optional[str]] = {}

    def get_events(self) -> Dict[str, Callable]:
        """Register which events this handler processes"""
        return {
            "workflow:execute": self.handle_execute,
        }

    async def _emit_node_state(
        self, sid: str, workflow_id: str, node_id: str, node_type: str,
        state: str, error: Optional[str], execution_id: Optional[str],
        error_action: Optional[Dict[str, str]] = None,
    ) -> None:
        """Send node state event to frontend via workflow relay.

        ``error_action`` is the one thing the user can do about this failure
        (see provider_errors._action_for), rendered as a button beside the
        error. Absent when there is nothing useful to click.

        Derived from the error text when the caller didn't supply one, because
        this is the single point every node-error emit passes through and the
        callers are not uniform: an agent reports provider failures IN its
        output (AgentExecutionStrategy), never as a raised exception, so
        deriving it only where exceptions are caught missed the node type that
        produces these errors most."""
        if error_action is None and state == 'error':
            error_action = action_for_error_text(error, node_type=node_type)
        relay = self._execution_relays.get(execution_id) if execution_id else None
        await send_event(self.sio, sid, WorkflowNodeStateEvent(
            workflow_id=workflow_id, node_id=node_id, node_type=node_type,
            state=state, error=error, execution_id=execution_id,
            error_action=error_action,
        ), workflow_id=workflow_id, execution_relay=relay)

    async def _emit_node_output(
        self,
        sid: str,
        workflow_id: str,
        node_id: str,
        node_type: str,
        output: Dict[str, Any],
    ) -> None:
        await send_event(self.sio, sid, WorkflowNodeOutputEvent(
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node_type,
            output=output,
        ), workflow_id=workflow_id)

    async def setup_user(self, sid: str) -> None:
        # Suppress unused parameter warning
        _ = sid

    @staticmethod
    def _log_execution_completion(
        success: bool, duration: float, error_msg: Optional[str]
    ) -> None:
        if success:
            logger.info(
                f"[WorkflowExecution] Workflow completed successfully in {duration:.2f}s"
            )
        elif error_msg == USER_STOPPED_ERROR:
            logger.info("[WorkflowExecution] Workflow execution stopped by user")
        else:
            logger.error(f"[WorkflowExecution] Workflow failed: {error_msg}")

    async def _get_user_id(self, sid: str, request) -> Optional[str]:
        """
        Get user_id from request (injected by MCP transport) or session.

        The MCP transport layer injects _user_id for authenticated requests.
        For non-MCP requests (direct frontend socket events), falls back to session.
        """
        # MCP transport layer injects _user_id for authenticated requests
        if hasattr(request, '_user_id') and request._user_id:
            return request._user_id

        # Fall back to session lookup for non-MCP requests
        try:
            session = await self.sio.get_session(sid)
            return session.get('user_id')
        except Exception as e:
            logger.warning(f"Failed to get session for sid {sid}: {e}")
            return None

    @staticmethod
    def _defined_variable_values(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Author-declared variables (settings.variable_definitions) as a value
        map — the BASE layer under runtime-written blob variables. Definitions
        live in settings deliberately: settings merges shallowly on update, so
        the graph autosave (which replaces the blob wholesale, variables
        included) can never clobber them. A definition with no value declares
        intent without providing it — the Setup tab turns exactly those into
        steps."""
        out: Dict[str, Any] = {}
        for d in (settings or {}).get("variable_definitions") or []:
            if not isinstance(d, dict):
                continue
            name = d.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            value = d.get("value")
            if value is not None and value != "":
                out[name.strip()] = value
        return out

    @staticmethod
    def _load_set_variable_outputs(workflow_variables: Dict[str, Any], db_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Augment workflow_variables with outputs stored in set-variable nodes (node.config.output).

        Set-variable nodes compute runtime values (e.g. row numbers from spreadsheets) that are
        persisted to node.config.output after each run. When a subsequent execution does not include
        those set-variable nodes (e.g. a single-node run that only traces direct predecessors),
        {{vars.X}} references would silently resolve to empty. This method pre-populates
        workflow_variables from the stored outputs so downstream nodes always see the latest values.

        Setup-flow variables (already in workflow_variables) are preserved as-is; set-variable
        node outputs are merged in on top.
        """
        result = dict(workflow_variables)
        for node in db_nodes:
            if node.get('type') == 'set-variable':
                stored_output = node.get('config', {}).get('output')
                if isinstance(stored_output, dict):
                    assignments = stored_output.get('assignments', [])
                    if not assignments and stored_output.get('variable_name'):
                        assignments = [{'variable_name': stored_output['variable_name'], 'value': stored_output.get('value')}]
                    for assignment in assignments:
                        var_name = assignment.get('variable_name', '')
                        if var_name:
                            result[var_name] = assignment.get('value')
        return result

    async def _fetch_workflow(
        self, workflow_id: str, user_id: str
    ) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str], Dict[str, Any], Dict[str, Any]]]:
        """
        Fetch workflow nodes, edges, organization_id, variables, and settings from database.

        Args:
            workflow_id: UUID of the workflow
            user_id: UUID of the user (for access verification)

        Returns:
            Tuple of (nodes, edges, organization_id, variables, settings) or None if not found/access denied
        """
        import uuid as uuid_module
        pool = await self.get_pool()
        if not pool:
            logger.error("[WorkflowExecution] No database pool available")
            return None

        try:
            workflow_uuid = uuid_module.UUID(workflow_id)
        except ValueError as e:
            logger.error(f"[WorkflowExecution] Invalid UUID format: {e}")
            return None

        async with pool.acquire() as conn:
            # Check access (owner, org member, or shared)
            access = await check_resource_access(
                conn, user_id, "workflow", workflow_id
            )

            if not access.has_access:
                logger.error(f"[WorkflowExecution] Workflow {workflow_id} access denied for user {user_id}")
                return None

            row = await WorkflowRepo(pool).get_workflow_execution_context(
                conn, workflow_uuid,
            )

            if not row:
                logger.error(f"[WorkflowExecution] Workflow {workflow_id} not found")
                return None

            workflow_data = row['workflow'] or {"nodes": [], "edges": []}
            nodes = workflow_data.get("nodes", [])
            edges = workflow_data.get("edges", [])
            organization_id = str(row['organization_id']) if row['organization_id'] else None
            settings = row.get('settings') or {}
            variables = {
                **self._defined_variable_values(settings),
                **self._load_set_variable_outputs(
                    workflow_data.get("variables", {}),
                    nodes
                ),
            }

            logger.info(f"[WorkflowExecution] Fetched workflow {workflow_id} with {len(nodes)} nodes and {len(edges)} edges (org: {organization_id})")
            return nodes, edges, organization_id, variables, settings

    def _find_input_node(
        self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]], start_node_id: Optional[str]
    ) -> Optional[str]:
        """
        Find the appropriate node to inject inputs into.

        Priority:
        1. start_node_id if provided
        2. Trigger nodes (trigger-webhook, trigger-cron, etc.)
        3. First node with no predecessors

        Args:
            nodes: List of workflow nodes
            edges: List of workflow edges
            start_node_id: Optional explicit starting node

        Returns:
            Node ID to inject inputs into, or None if no suitable node found
        """
        if start_node_id:
            return start_node_id

        # Build set of nodes that have incoming edges
        nodes_with_predecessors = {e.get('target') for e in edges if e.get('target')}

        # Check for run trigger first (highest priority entry point)
        for node in nodes:
            if node.get('type') == 'trigger-run':
                return node.get('id')

        # Find other trigger nodes (interface-form is the unified form node —
        # legacy trigger-form-input resolves to it via the registry aliases)
        from nodes.core.registry import resolve_node_type
        trigger_types = {'trigger-webhook', 'trigger-cron', 'trigger-manual', 'interface-form'}

        for node in nodes:
            node_id = node.get('id')
            node_type = resolve_node_type(node.get('type', ''))

            if node_type in trigger_types:
                return node_id

        # Fall back to first node with no predecessors
        for node in nodes:
            node_id = node.get('id')
            if node_id not in nodes_with_predecessors:
                return node_id

        return None

    def _inject_inputs(
        self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]],
        start_node_id: Optional[str], inputs: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Inject inputs into the appropriate node by setting its mockedOutput.

        The node's mockedOutput will be used as its output without executing the node,
        allowing downstream nodes to reference the inputs via {{nodeId.field}}.

        Args:
            nodes: List of workflow nodes (modified in place after deepcopy in caller)
            edges: List of workflow edges
            start_node_id: Optional explicit target node
            inputs: Input data to inject

        Returns:
            Modified nodes list
        """
        target_node_id = self._find_input_node(nodes, edges, start_node_id)

        if not target_node_id:
            logger.warning("[WorkflowExecution] No suitable node found for input injection")
            return nodes

        # Find and update the target node
        node_found = False
        for node in nodes:
            if node.get('id') == target_node_id:
                if 'config' not in node:
                    node['config'] = {}
                node['config']['mockedOutput'] = inputs
                logger.info(f"[WorkflowExecution] Injected inputs into node {target_node_id}")
                node_found = True
                break

        if not node_found:
            logger.warning(f"[WorkflowExecution] Target node {target_node_id} not found in workflow nodes")

        return nodes

    async def handle_execute(
        self, sid: str, request: WorkflowExecuteRequest, execution_id: Optional[str] = None,
        caller_user_id: Optional[str] = None
    ) -> WorkflowExecutionResult:
        """Public entry for workflow execution. Runs inline on the asyncio loop.

        All four trigger paths (socket / webhook / MCP / inner-from-edit)
        converge here. CPU-blocky nodes (javascript_node via QuickJS) route
        themselves to the JS thread pool internally; everything else is
        I/O-bound and runs directly on this loop.

        Synthetic WorkflowCompleteEvent(success=False) is emitted on any
        uncaught exception so the client sees the failure rather than hanging.

        Args:
            sid: Socket session ID
            request: Workflow execution request
            execution_id: Optional pre-created execution ID (from MCP run_workflow).
                         If not provided, creates a new execution record.
            caller_user_id: Optional user ID for external callers (webhooks/MCP).
        """
        try:
            return await self._handle_execute_impl(sid, request, execution_id, caller_user_id)
        except Exception as e:
            logger.exception("[WorkflowExecution] inline execute failed: %s", e)
            payload = WorkflowCompleteEvent(
                execution_id=execution_id or 'unknown',
                workflow_id=request.workflow_id,
                success=False,
                nodes_executed=0,
                duration=0,
                error=f"Execution failed: {e}",
            ).model_dump(mode='json', exclude_none=True)
            try:
                await self.sio.emit(WorkflowCompleteEvent.event_name, payload, to=sid)
            except Exception as emit_err:
                logger.warning("[WorkflowExecution] synthetic completion emit failed: %s", emit_err)
            return WorkflowExecutionResult(
                execution_id=execution_id or 'unknown',
                workflow_id=request.workflow_id,
                success=False,
                nodes_executed=0,
                duration=0,
                error=f"Execution failed: {e}",
            )

    async def _handle_execute_impl(
        self, sid: str, request: WorkflowExecuteRequest, execution_id: Optional[str] = None,
        caller_user_id: Optional[str] = None
    ) -> WorkflowExecutionResult:
        """Run the execution orchestrator in the current process.

        ONLY called from inside an execute-worker subprocess (via
        workers.execute_worker._run_execute). The public handle_execute()
        always dispatches; never call this directly from the parent's
        request-handling path.
        """
        start_time = time.time()
        completion_event_sent = False
        last_output_node_id: Optional[str] = None

        def _result(
            *,
            success: bool,
            nodes_executed: int,
            error: Optional[str],
            node_outputs: Optional[Dict[str, Any]] = None,
            suspended: bool = False,
        ) -> WorkflowExecutionResult:
            return WorkflowExecutionResult(
                execution_id=execution_id or "unknown",
                workflow_id=request.workflow_id,
                success=success,
                nodes_executed=nodes_executed,
                duration=time.time() - start_time,
                error=error,
                node_outputs=node_outputs or {},
                last_output_node_id=last_output_node_id,
                suspended=suspended,
            )

        # Pre-bind so the outer except (which alerts on headless failures) can
        # read it even when _get_user_id itself raised.
        user_id: Optional[str] = caller_user_id

        try:
            # Get user_id - use caller_user_id if provided (webhook mode), otherwise from session
            if not user_id:
                user_id = await self._get_user_id(sid, request)

            if not user_id:
                logger.error("[WorkflowExecution] User not authenticated")
                return _result(success=False, nodes_executed=0, error="User not authenticated")

            pool = await self.get_pool()
            if not pool:
                logger.error("[WorkflowExecution] Database connection not available")
                return _result(success=False, nodes_executed=0, error="Database connection not available")

            # Get nodes and edges - either from request or fetch from DB
            workflow_org_id: Optional[str] = None
            workflow_variables: Dict[str, Any] = {}
            workflow_settings: Dict[str, Any] = {}
            if request.nodes is not None and request.edges is not None:
                # Frontend provided nodes/edges directly
                nodes = request.nodes
                edges = request.edges
                # Fetch the workflow's organization_id, variables, and settings
                async with pool.acquire() as conn:
                    import uuid as uuid_module
                    try:
                        workflow_uuid = uuid_module.UUID(request.workflow_id)
                        row = await WorkflowRepo(pool).get_workflow_org_and_data(
                            conn, workflow_uuid,
                        )
                        if row and row['organization_id']:
                            workflow_org_id = str(row['organization_id'])
                        if row:
                            workflow_settings = row.get('settings') or {}
                        if row and row['workflow']:
                            workflow_variables = {
                                **self._defined_variable_values(workflow_settings),
                                **self._load_set_variable_outputs(
                                    row['workflow'].get('variables', {}),
                                    row['workflow'].get('nodes', [])
                                ),
                            }
                    except (ValueError, Exception) as e:
                        logger.warning(f"[WorkflowExecution] Could not fetch workflow org_id: {e}")
            else:
                # Template/app mode - fetch from database
                result = await self._fetch_workflow(request.workflow_id, user_id)
                if not result:
                    logger.error(f"[WorkflowExecution] Failed to fetch workflow {request.workflow_id}")
                    await send_event(self.sio, sid, WorkflowCompleteEvent(
                        execution_id="unknown",
                        workflow_id=request.workflow_id,
                        success=False,
                        nodes_executed=0,
                        duration=time.time() - start_time,
                        error="Workflow not found or access denied"
                    ), workflow_id=request.workflow_id)
                    return _result(success=False, nodes_executed=0, error="Workflow not found or access denied")
                nodes, edges, workflow_org_id, workflow_variables, workflow_settings = result

            use_execution_graph_for_snapshot = not (
                request.replay_nodes is not None and request.replay_edges is not None
            )
            snapshot_nodes = nodes if use_execution_graph_for_snapshot else request.replay_nodes
            snapshot_edges = edges if use_execution_graph_for_snapshot else request.replay_edges

            # Workflow-level minimum credits check (replaces the legacy
            # min_required_balance $-pre-flight). The setting name stays
            # the same in workflow_settings for backward compat but the
            # value is now interpreted as credits.
            min_required_credits = workflow_settings.get('min_required_credits') or workflow_settings.get('min_required_balance')
            if min_required_credits and float(min_required_credits) > 0:
                from billing.exceptions import insufficient_credits_message
                from billing.usage_tracker import usage_tracker as _usage_tracker
                remaining = await _usage_tracker.check_credit_balance(user_id)
                required = float(min_required_credits)
                # remaining is None on Enterprise (unlimited) — skip the check.
                if remaining is not None and remaining < required:
                    gate_error = insufficient_credits_message(remaining, required)
                    logger.warning(f"[WorkflowExecution] {gate_error}")
                    # Route the policy event to the user-scoped bus. Sending it with
                    # workflow_id would make it exclusive to the workflow relay relay,
                    # while account-level usage consumers subscribe by user_id.
                    await send_event(self.sio, sid, CreditsExhaustedEvent(
                        credits_remaining=remaining,
                        credits_required=required,
                        message=f"This workflow requires at least {required:.0f} credits to run. You have {remaining:.0f} remaining.",
                    ), user_id=user_id)
                    await send_event(self.sio, sid, WorkflowCompleteEvent(
                        execution_id=execution_id or "unknown",
                        workflow_id=request.workflow_id,
                        success=False,
                        nodes_executed=0,
                        duration=time.time() - start_time,
                        error=gate_error,
                    ), workflow_id=request.workflow_id)
                    return _result(success=False, nodes_executed=0, error=gate_error)

            # Apply per-node config overrides supplied by SDK clients
            if request.config_overrides:
                import copy
                nodes = copy.deepcopy(nodes)
                if use_execution_graph_for_snapshot:
                    snapshot_nodes = nodes
                else:
                    snapshot_nodes = copy.deepcopy(snapshot_nodes)

                def _apply_config_overrides(target_nodes: List[Dict[str, Any]]) -> None:
                    for node in target_nodes:
                        overrides = request.config_overrides.get(node.get('id', ''))
                        if overrides:
                            node.setdefault('config', {}).update(overrides)

                _apply_config_overrides(nodes)
                _apply_config_overrides(snapshot_nodes)

            # Inject inputs if provided (for template/app use)
            if request.inputs:
                import copy
                nodes = copy.deepcopy(nodes)  # Don't modify original
                nodes = self._inject_inputs(nodes, edges, request.start_node_id, request.inputs)
                if use_execution_graph_for_snapshot:
                    snapshot_nodes = nodes
                else:
                    snapshot_nodes = copy.deepcopy(snapshot_nodes)
                    snapshot_nodes = self._inject_inputs(
                        snapshot_nodes, snapshot_edges, request.start_node_id, request.inputs
                    )

            logger.info(f"[WorkflowExecution] Starting workflow {request.workflow_id} with {len(nodes)} nodes and {len(edges)} edges")

            # Filter out non-executable nodes (visual-only annotations like sticky notes)
            executable_nodes = [n for n in nodes if n.get('type') not in NON_EXECUTABLE_NODE_TYPES]
            executable_node_ids = {n['id'] for n in executable_nodes}

            # Also filter edges that connect to/from non-executable nodes
            executable_edges = [
                e for e in edges
                if e.get('source') in executable_node_ids and e.get('target') in executable_node_ids
            ]

            excluded_count = len(nodes) - len(executable_nodes)
            if excluded_count > 0:
                logger.info(f"[WorkflowExecution] Filtered to {len(executable_nodes)} executable nodes (excluded {excluded_count} non-executable nodes)")

            # Extract the on-error subgraph BEFORE start_node filtering, since the
            # on-error node is disconnected from the main workflow graph and would be
            # dropped by reachability filtering from a trigger node.
            on_error_subgraph_nodes: List[Dict[str, Any]] = []
            on_error_subgraph_edges: List[Dict[str, Any]] = []
            on_error_nodes = [n for n in executable_nodes if n.get('type') == 'on-error']
            # When the request explicitly starts FROM an on-error node (cross-workflow
            # error handler runs do this), treat it as a regular trigger node — skip
            # extraction so it stays in executable_nodes and runs.
            explicit_on_error_start = bool(request.start_node_id) and any(
                n['id'] == request.start_node_id for n in on_error_nodes
            )
            if on_error_nodes and not explicit_on_error_start:
                on_error_subgraph_ids: Set[str] = set()
                for on_error_node in on_error_nodes:
                    on_error_id = on_error_node['id']
                    reachable, reachable_edges = self._get_reachable_nodes(
                        on_error_id, executable_nodes, executable_edges,
                    )
                    on_error_subgraph_ids.update(n['id'] for n in reachable)
                    on_error_subgraph_nodes = reachable
                    on_error_subgraph_edges = reachable_edges
                executable_nodes = [n for n in executable_nodes if n['id'] not in on_error_subgraph_ids]
                executable_node_ids = {n['id'] for n in executable_nodes}
                executable_edges = [
                    e for e in executable_edges
                    if e.get('source') in executable_node_ids and e.get('target') in executable_node_ids
                ]
                logger.info(f"[WorkflowExecution] Excluded {len(on_error_subgraph_ids)} on-error subgraph nodes from normal execution")

            # If a specific start_node_id is provided (e.g., webhook trigger), only execute
            # nodes reachable from that starting point. This ensures webhooks only trigger
            # their connected workflow, not unrelated nodes on the same canvas.
            #
            # For manual runs (no start_node_id), execute ALL nodes - the topological sort
            # handles execution order, and disconnected components should all run.
            if request.start_node_id:
                # Always traverse forward-only from the start node. Upstream
                # predecessors are never re-executed — their cached outputs are
                # preloaded so {{node.path}} references resolve correctly.
                executable_nodes, executable_edges = self._get_reachable_nodes(
                    request.start_node_id, executable_nodes, executable_edges,
                )
                logger.info(f"[WorkflowExecution] Starting from node {request.start_node_id}, {len(executable_nodes)} reachable nodes")

            # Create execution record if not provided (e.g., from frontend)
            if not execution_id:
                async with pool.acquire() as conn:
                    execution_id = await WorkflowRepo(pool).create_execution(
                        conn,
                        workflow_id=request.workflow_id,
                        user_id=user_id,
                        trigger_source=getattr(request, 'trigger_source', None) or 'manual',
                    )
                    logger.info(f"[WorkflowExecution] Created execution record {execution_id}")
            else:
                logger.info(f"[WorkflowExecution] Using pre-created execution record {execution_id}")

            # CAS: snapshot the run's graph once at start (whole-blob, deduped).
            # snapshot_graph short-circuits on resume (existing graph_hash), so the
            # snapshot is the run-start graph, never a post-edit one.
            # Best-effort — a snapshot failure must never block execution.
            try:
                from utils.database_pool import get_native_pool
                from utils.node_outputs import snapshot_graph
                # CAS writes need a native asyncpg pool (transaction + executemany);
                await snapshot_graph(
                    get_native_pool(), workflow_id=request.workflow_id, execution_id=execution_id,
                    graph={"nodes": snapshot_nodes, "edges": snapshot_edges},
                )
            except Exception as e:
                logger.error(f"[WorkflowExecution] CAS graph snapshot failed: {e}", exc_info=True)

            cancellation_event = asyncio.Event()

            # Connect to workflow relay in the background: the relay queues
            # events from start() (one writer drains one FIFO, so in-order
            # delivery holds), letting node execution overlap the relay handshake
            # instead of blocking behind it. A failed handshake aborts the run
            # through the same cancellation machinery stop signals use — the
            # fail-loud outcome of the old blocking connect, without its
            # head-of-line latency.
            from utils.execution_relay import create_execution_relay
            from wss.sender import _active_execution_relay

            execution_task = None  # read by the failure callback once created below

            def _abort_on_relay_failure() -> None:
                cancellation_event.set()
                if execution_task is not None and not execution_task.done():
                    execution_task.cancel()

            # Real runs keep the fail-loud abort: without the workflow relay the
            # user can neither watch nor stop the run. A REHEARSAL uses neither
            # capability — progress rides its own rehearsal:progress channel
            # and the Test Run screen offers no stop — so the relay is not part
            # of its contract, and a relay outage must not kill the run (a
            # flaky relay connection ended a test 3 tool-calls in, 2026-08-10).
            from nodes.agent.rehearsal import is_rehearsal_conversation
            _is_rehearsal_run = is_rehearsal_conversation(request.conversation_id or '')

            relay = create_execution_relay(
                request.workflow_id, execution_id, user_id,
                on_connect_failure=None if _is_rehearsal_run else _abort_on_relay_failure,
            )
            relay.start()
            self._execution_relays[execution_id] = relay
            _active_execution_relay.set(relay)
            # Will be set once the execution subtask is created
            relay_stop_task = None

            # Send workflow started event
            await send_event(self.sio, sid, WorkflowStartedEvent(
                execution_id=execution_id,
                workflow_id=request.workflow_id,
                background=bool(request.background),
            ), workflow_id=request.workflow_id, execution_relay=relay)

            # Capture user info for Slack notification at end (only for non-relay/non-webhook executions).
            # SDK/API-key clients are excluded: they have no login thread (synthetic `sdk:<key>`
            # identity, never post a login message), so their runs would land as orphan top-level
            # messages in the human activity channel instead of threaded under a login.
            slack_user_name = None
            slack_user_email = None
            slack_thread_ts = None
            if not caller_user_id and not is_sdk_client(sid):
                try:
                    session = await self.sio.get_session(sid)
                    if session:
                        user_data = session.get('user_data', {})
                        slack_user_name = extract_user_name(user_data)
                        slack_user_email = user_data.get('email', 'unknown@example.com')
                        slack_thread_ts = session.get('slack_thread_ts')
                except Exception as e:
                    logger.debug(f"[WorkflowExecution] Failed to get user info for Slack: {e}")

            # Handle empty workflow (no executable nodes)
            if len(executable_nodes) == 0:
                logger.info("[WorkflowExecution] Empty workflow - completing immediately")

                # Update execution record
                async with pool.acquire() as conn:
                    await WorkflowRepo(pool).mark_execution_completed_empty(
                        conn, execution_id,
                    )

                await send_event(self.sio, sid, WorkflowCompleteEvent(
                    execution_id=execution_id,
                    workflow_id=request.workflow_id,
                    success=True,
                    nodes_executed=0,
                    duration=time.time() - start_time,
                    error=None
                ), workflow_id=request.workflow_id)
                return _result(success=True, nodes_executed=0, error=None)

            # Validate DAG structure using topological sort (detects cycles)
            if not self._topological_sort(executable_nodes, executable_edges):
                cycle_hint = self._describe_cycle(executable_nodes, executable_edges)
                error_msg = (
                    "Failed to determine execution order — the workflow contains a cycle. "
                    f"{cycle_hint} "
                    "Iteration nodes have a 'done' output handle that runs AFTER the loop "
                    "completes; do NOT wire 'done' back to a node upstream of the iteration "
                    "(that creates a cycle). To re-process data, restructure with a fresh "
                    "downstream node instead."
                )
                logger.error(f"[WorkflowExecution] {error_msg}")

                # Update execution record
                async with pool.acquire() as conn:
                    await WorkflowRepo(pool).mark_execution_error_at_startup(
                        conn, execution_id, error_msg,
                    )

                await send_event(self.sio, sid, WorkflowCompleteEvent(
                    execution_id=execution_id,
                    workflow_id=request.workflow_id,
                    success=False,
                    nodes_executed=0,
                    duration=time.time() - start_time,
                    error=error_msg
                ), workflow_id=request.workflow_id)
                self._maybe_alert_run_failure(
                    request, execution_id, user_id, error_msg,
                    organization_id=workflow_org_id,
                )
                return _result(success=False, nodes_executed=0, error=error_msg)

            logger.info(f"[WorkflowExecution] Executing {len(executable_nodes)} nodes concurrently (max parallelism: {DEFAULT_MAX_CONCURRENCY})")

            # Preload stored outputs for nodes excluded from this execution slice.
            # Upstream predecessors are never re-executed — but downstream
            # {{node.path}} references still need their outputs available or they
            # resolve to None and the literal template string leaks through.
            # Recompute the ids from the CURRENT executable set: the reachability
            # filter above reassigns executable_nodes without refreshing
            # executable_node_ids, and the stale set made the excluded list empty,
            # hiding restored trigger snapshots from forward-only runs.
            preloaded_outputs: Dict[str, Any] = {}
            if request.start_node_id:
                preloaded_outputs = await self._preload_excluded_node_outputs(
                    pool, request.workflow_id, nodes,
                    {n['id'] for n in executable_nodes},
                )

            # Manual runs re-execute the workflow's trigger, but a pure event
            # trigger (webhook, inbound email) has no event to produce — it
            # outputs an empty payload and every downstream
            # {{ $('trigger').field }} breaks, forcing users to fire a real
            # event per iteration. Replay the trigger's last persisted output
            # instead: pull it out of the execution slice and feed the stored
            # event to downstream refs. A trigger that never fired (no stored
            # output) executes as before.
            if (getattr(request, 'trigger_source', None) or 'manual') == 'manual':
                replay_candidates = self._manual_replay_candidates(executable_nodes)
                if replay_candidates:
                    replayed = await self._preload_excluded_node_outputs(
                        pool, request.workflow_id, replay_candidates, set(),
                    )
                    if replayed:
                        preloaded_outputs.update(replayed)
                        executable_nodes = [
                            n for n in executable_nodes if n['id'] not in replayed
                        ]
                        executable_edges = [
                            e for e in executable_edges
                            if e.get('source') not in replayed and e.get('target') not in replayed
                        ]
                        logger.info(
                            f"[WorkflowExecution] Manual run: replaying last event for "
                            f"trigger node(s) {sorted(replayed.keys())} instead of executing"
                        )
                        # Surface the replayed event on the canvas — the run
                        # reset wiped the trigger's displayed output, and
                        # downstream data appearing from nowhere reads as a bug.
                        for rn in replay_candidates:
                            if rn['id'] not in replayed:
                                continue
                            await self._emit_node_state(
                                sid, request.workflow_id, rn['id'],
                                rn.get('type', ''), 'completed', None, execution_id,
                            )
                            await self._emit_node_output(
                                sid, request.workflow_id, rn['id'],
                                rn.get('type', ''), replayed[rn['id']],
                            )

            # A headless Drive/Calendar trigger wakes on every drive change (the
            # watch is drive-global); non-matching wake-ups return change_count=0.
            # Mark such a start node so a no-op wake-up is hidden (no empty output,
            # no surfaced execution) rather than flashing on every unrelated change.
            _trigger_src = getattr(request, 'trigger_source', None) or 'manual'
            _start_node = (
                next((n for n in executable_nodes if n.get('id') == request.start_node_id), None)
                if request.start_node_id else None
            )
            noop_silent_node_id = (
                request.start_node_id
                if (request.start_node_id and _trigger_src != 'manual'
                    and (_start_node or {}).get('type') in ('automation-google-drive', 'automation-google-calendar'))
                else None
            )

            # Run execution as a subtask so stop can cancel it instantly
            async def _run_execution():
                return await self._execute_nodes_concurrent(
                    executable_nodes, executable_edges, sid, user_id, request.workflow_id,
                    execution_id=execution_id,
                    conversation_id=request.conversation_id,
                    workflow_org_id=workflow_org_id,
                    cancellation_event=cancellation_event,
                    workflow_variables=workflow_variables,
                    initial_outputs=preloaded_outputs or None,
                    include_last_output_node_id=True,
                    noop_silent_node_id=noop_silent_node_id,
                )

            execution_task = asyncio.create_task(_run_execution())
            # Start stop listener with reference to the execution task for instant cancellation
            relay_stop_task = asyncio.create_task(
                relay.listen_for_stop(cancellation_event, execution_task=execution_task)
            )

            try:
                nodes_executed, error_msg, node_outputs, last_output_node_id = await execution_task
            except asyncio.CancelledError:
                # Either a user stop (via the relay) or the relay handshake failing —
                # the latter carries its cause in connect_error.
                logger.info(f"[WorkflowExecution] Execution cancelled for {execution_id[:8]}")
                nodes_executed = 0
                error_msg = relay.connect_error or USER_STOPPED_ERROR
                node_outputs = {}
                last_output_node_id = None

            duration = time.time() - start_time
            success = error_msg is None

            # A headless Drive/Calendar trigger wake-up that matched nothing (no
            # node propagated) is a drive-global-watch no-op, not a real fire.
            # Hide it: skip the completion event/analytics and delete the
            # execution record. The trigger advanced its cursor during execute().
            is_noop_trigger_run = bool(noop_silent_node_id) and success and nodes_executed == 0

            # Check if a suspending node (approval, delay) halted execution — its
            # strategy already set the execution status and the node handled its
            # own side effects. We just need to persist outputs for resume, emit
            # completion, and return early.
            if success and await self._is_execution_suspended(execution_id):
                if node_outputs or execution_id in self._execution_node_statuses:
                    spawn(
                        self._persist_node_outputs(
                            request.workflow_id, user_id, node_outputs,
                            execution_id=execution_id,
                            executable_nodes=executable_nodes,
                        ),
                        name=f"persist-node-outputs-suspended:{execution_id}",
                    )
                await send_event(self.sio, sid, WorkflowCompleteEvent(
                    execution_id=execution_id,
                    workflow_id=request.workflow_id,
                    success=True,
                    nodes_executed=nodes_executed,
                    duration=duration,
                    error=None,
                    suspended=True,
                ), workflow_id=request.workflow_id)
                return _result(
                    success=True,
                    nodes_executed=nodes_executed,
                    error=None,
                    node_outputs=node_outputs,
                    suspended=True,
                )

            # Execute on-error subgraph if the workflow failed and an on-error node exists
            if not success and on_error_subgraph_nodes:
                logger.info(f"[WorkflowExecution] Workflow failed — executing on-error subgraph ({len(on_error_subgraph_nodes)} nodes)")
                try:
                    # Inject error details into the on-error node's data so its execute()
                    # returns them as output for downstream nodes to reference
                    on_error_node = next(n for n in on_error_subgraph_nodes if n.get('type') == 'on-error')
                    import copy
                    on_error_subgraph_nodes = copy.deepcopy(on_error_subgraph_nodes)
                    for n in on_error_subgraph_nodes:
                        if n['id'] == on_error_node['id']:
                            # _execute_node reads from node['config'], which becomes
                            # node_data in the WorkflowNode constructor
                            n.setdefault('config', {})['_error_inputs'] = {
                                'error': error_msg,
                                'workflow_id': request.workflow_id,
                                'execution_id': execution_id,
                                'nodes_executed': nodes_executed,
                                'duration': round(duration, 2),
                            }
                            break

                    await self._execute_nodes_concurrent(
                        on_error_subgraph_nodes, on_error_subgraph_edges,
                        sid, user_id, request.workflow_id,
                        execution_id=execution_id,
                        conversation_id=request.conversation_id,
                        workflow_org_id=workflow_org_id,
                        workflow_variables=workflow_variables
                    )
                    logger.info("[WorkflowExecution] On-error subgraph execution completed")
                except Exception as on_error_exc:
                    logger.error(f"[WorkflowExecution] On-error subgraph failed: {on_error_exc}", exc_info=True)

            # Email alert for failed HEADLESS runs — webhook/cron/email/mcp/api
            # runs have no canvas in front of the user, so without this the
            # failure is silent. A user-initiated stop is not a failure worth
            # emailing. Read the failing node's identity BEFORE
            # _persist_node_outputs pops the status record below.
            user_stopped = error_msg == USER_STOPPED_ERROR
            if not success and not user_stopped:
                failed_node_label = failed_node_type = node_error = None
                statuses = self._execution_node_statuses.get(execution_id) or {}
                failed_id = next(
                    (nid for nid, s in statuses.items() if s.get('status') == 'error'), None,
                )
                if failed_id:
                    node_error = statuses[failed_id].get('error')
                    failed_node = next(
                        (n for n in executable_nodes if n.get('id') == failed_id), None,
                    )
                    if failed_node:
                        failed_node_type = failed_node.get('type')
                        failed_node_label = failed_node.get('label') or failed_node_type
                self._maybe_alert_run_failure(
                    request, execution_id, user_id, node_error or error_msg,
                    node_label=failed_node_label, node_type=failed_node_type,
                    duration=duration, organization_id=workflow_org_id,
                )
                # Cross-workflow error routing — fire the picked workflow's
                # on-error node (see WorkflowSettingsDialog). Sibling to the
                # alert: independently fire-and-forget on every failure path,
                # including manual canvas runs (the local on-error subgraph
                # above is the in-workflow analogue; this is the cross-workflow
                # extension of the same idea).
                self._maybe_dispatch_error_handler(
                    request, execution_id, user_id, error_msg,
                    nodes_executed=nodes_executed, duration=duration,
                    workflow_settings=workflow_settings,
                )

            # Persist node outputs to the workflow database (fire-and-forget — outputs
            # are already available in the UI via YJS; this is for history/MCP readback).
            # Also runs when there are no outputs but a last-run status to persist (e.g.
            # a failure that produced no output) so the status survives reload.
            if node_outputs or execution_id in self._execution_node_statuses:
                spawn(
                    self._persist_node_outputs(
                        request.workflow_id, user_id, node_outputs,
                        execution_id=execution_id,
                        executable_nodes=executable_nodes,
                    ),
                    name=f"persist-node-outputs:{execution_id}",
                )

            # Send completion event to frontend FIRST so the UI unblocks immediately,
            # then update the execution record (which can be slow due to transient DB issues).
            self._log_execution_completion(success, duration, error_msg)

            # Tool-health stamp: a run can appear complete while every agent tool
            # call inside it failed. Stamp per-run counts so telemetry can alert on
            # run.tool_calls.all_failed = true; indexed single-row aggregate.
            if success and nodes_executed > 0 and not is_noop_trigger_run:
                try:
                    async with pool.acquire() as conn:
                        tc = await conn.fetchrow(
                            """
                            SELECT count(*) AS total,
                                   count(*) FILTER (WHERE result_status = 'error') AS failed
                            FROM tool_call_events WHERE execution_id = $1
                            """,
                            execution_id,
                        )
                    tc_total = int(tc["total"] or 0)
                    tc_failed = int(tc["failed"] or 0)
                    if tc_total > 0:
                        from opentelemetry import trace as _trace
                        _span = _trace.get_current_span()
                        _span.set_attribute("run.tool_calls.total", tc_total)
                        _span.set_attribute("run.tool_calls.failed", tc_failed)
                        _span.set_attribute(
                            "run.tool_calls.all_failed", tc_failed == tc_total
                        )
                except Exception as e:
                    logger.warning(f"[WorkflowExecution] tool-health stamp failed: {e}")

            relay = self._execution_relays.get(execution_id)
            # No-op trigger wake-up: don't surface a completion event (would show
            # the run as fired). Mark sent so the fallback emitter stays quiet.
            if not is_noop_trigger_run:
                await send_event(self.sio, sid, WorkflowCompleteEvent(
                    execution_id=execution_id,
                    workflow_id=request.workflow_id,
                    success=success,
                    nodes_executed=nodes_executed,
                    duration=duration,
                    error=error_msg,
                ), workflow_id=request.workflow_id, execution_relay=relay)
            completion_event_sent = True

            analytics_props = {
                "workflow_id": request.workflow_id,
                "execution_id": str(execution_id) if execution_id else None,
                "nodes_executed": nodes_executed,
                "duration_s": round(duration, 3),
                "trigger": getattr(request, 'trigger', None) or 'manual',
            }
            if success and not is_noop_trigger_run:
                log_activity_background(Events.WORKFLOW_RUN_COMPLETED, user_id, analytics_props)
                # Activation milestone: first successful run is the "got value" moment.
                # set_once pins activated/activated_at to that first run, so with
                # person-on-events any event (and the signup cohort) is sliceable by
                # whether — and when — the user activated.
                set_person_properties_background(user_id, {
                    "activated": True,
                    "activated_at": datetime.now(timezone.utc).isoformat(),
                }, set_once=True)
            else:
                log_activity_background(Events.WORKFLOW_EXECUTION_FAILED, user_id, {
                    **analytics_props,
                    "error": (error_msg or '')[:500],
                })

            # Update execution record (non-blocking — UI already notified)
            try:
                async with pool.acquire() as conn:
                    repo = WorkflowRepo(pool)
                    if is_noop_trigger_run:
                        # Drop the record entirely so a global-watch no-op never
                        # appears in run history.
                        await repo.delete_execution(conn, execution_id)
                    elif success:
                        await repo.mark_execution_completed(
                            conn, execution_id, nodes_executed,
                        )
                    else:
                        await repo.mark_execution_error(
                            conn, execution_id, nodes_executed, error_msg,
                        )
            except Exception as db_err:
                logger.error(f"[WorkflowExecution] Failed to update execution record: {db_err}")

            # Retention is owned solely by the CAS GC cron (Phase A): a per-node
            # keep-20 prune here would delete shared CAS chunks. No inline cleanup.

            # Send Slack notification with execution results
            if slack_user_name and slack_user_email:
                if success:
                    send_activity_notification_background(
                        slack_user_name, slack_user_email, "✅ Executed Workflow",
                        details={
                            "Workflow ID": request.workflow_id,
                            "Nodes executed": str(nodes_executed),
                            "Duration": f"{duration:.1f}s",
                        },
                        thread_ts=slack_thread_ts
                    )
                else:
                    send_activity_notification_background(
                        slack_user_name, slack_user_email, "❌ Failed Workflow",
                        details={
                            "Workflow ID": request.workflow_id,
                            "Error": error_msg,
                        },
                        thread_ts=slack_thread_ts
                    )

            return _result(
                success=success,
                nodes_executed=nodes_executed,
                error=error_msg,
                node_outputs=node_outputs,
            )

        except Exception as e:
            logger.error(f"[WorkflowExecution] Error handling workflow execution: {e}", exc_info=True)

            # Update execution record if it was created
            if execution_id:
                try:
                    pool = await self.get_pool()
                    if pool:
                        async with pool.acquire() as conn:
                            await WorkflowRepo(pool).mark_execution_error_simple(
                                conn, execution_id, str(e),
                            )
                except Exception as db_error:
                    logger.error(f"[WorkflowExecution] Failed to update execution record: {db_error}")

            if not completion_event_sent:
                await send_event(self.sio, sid, WorkflowCompleteEvent(
                    execution_id=execution_id if execution_id else "unknown",
                    workflow_id=request.workflow_id if hasattr(request, 'workflow_id') else "unknown",
                    success=False,
                    nodes_executed=0,
                    duration=time.time() - start_time,
                    error=str(e)
                ), workflow_id=request.workflow_id if hasattr(request, 'workflow_id') else None)
            if hasattr(request, 'workflow_id'):
                self._maybe_alert_run_failure(request, execution_id, user_id, str(e))
            return _result(success=False, nodes_executed=0, error=str(e))

        finally:
            # Shield cleanup from cancellation — these must complete
            try:
                # Close the execution relay WebSocket
                if execution_id and execution_id in self._execution_relays:
                    relay = self._execution_relays.pop(execution_id)
                    _active_execution_relay.set(None)
                    if relay_stop_task:
                        relay_stop_task.cancel()
                    try:
                        await asyncio.shield(relay.close())
                    except (Exception, asyncio.CancelledError):
                        pass
            except asyncio.CancelledError:
                pass  # Swallow — cleanup must not be interrupted

    def _maybe_alert_run_failure(
        self,
        request,
        execution_id: Optional[str],
        user_id: Optional[str],
        error_msg: Optional[str],
        *,
        node_label: Optional[str] = None,
        node_type: Optional[str] = None,
        duration: float = 0.0,
        organization_id: Optional[str] = None,
    ) -> None:
        """Fire-and-forget failure email for HEADLESS runs only. Manual runs
        show the error live on the canvas; webhook/cron/email/mcp/api runs are
        otherwise invisible. Per-workflow suppression lives in the alert
        itself (utils/notifications.py) so repeated cron failures fold into
        one email — and credit-exhaustion failures delegate to the credits
        alert there with this run's context. Best-effort: never raises into
        the execution path."""
        trigger_source = getattr(request, 'trigger_source', None) or 'manual'
        # builder_event = internal wake-turn plumbing (fire_agent_wake_turn):
        # the next-user-message relay is its backstop, so a failure here is
        # recoverable noise, not a broken user workflow — never email it.
        if trigger_source in ('manual', 'builder_event') or not user_id:
            return
        try:
            from utils.notifications import send_run_failure_alert
            spawn(
                send_run_failure_alert(
                    user_id=user_id,
                    workflow_id=request.workflow_id,
                    execution_id=execution_id or "unknown",
                    trigger_source=trigger_source,
                    error=error_msg,
                    node_label=node_label,
                    node_type=node_type,
                    duration_s=duration,
                    organization_id=organization_id,
                ),
                name=f"run-failure-alert:{execution_id}",
            )
        except Exception as e:
            logger.warning(f"[WorkflowExecution] failed to queue run-failure alert: {e}")

    def _maybe_dispatch_error_handler(
        self,
        request,
        execution_id: Optional[str],
        user_id: Optional[str],
        error_msg: Optional[str],
        *,
        nodes_executed: int,
        duration: float,
        workflow_settings: Dict[str, Any],
    ) -> None:
        """Fire the configured error-handler workflow's on-error node with this
        run's error payload. Fire-and-forget; never raises into the execution
        path. Guards: must have a target, target != source, the failing run
        wasn't itself an error-handler run (recursion stop)."""
        target_id = workflow_settings.get('error_handler_workflow_id')
        if not target_id or not user_id:
            return
        target_id = str(target_id).strip()
        if not target_id or target_id == request.workflow_id:
            return
        trigger_source = getattr(request, 'trigger_source', None) or 'manual'
        # An error-handler run failing must not trigger another error-handler
        # run, even if the target is a different workflow — one hop only.
        if trigger_source == 'error_handler':
            return
        spawn(
            self._dispatch_error_handler_workflow(
                target_workflow_id=target_id,
                source_workflow_id=request.workflow_id,
                source_execution_id=execution_id,
                user_id=user_id,
                error=error_msg,
                nodes_executed=nodes_executed,
                duration=duration,
            ),
            name=f"error-handler-dispatch:{execution_id}",
        )

    async def _dispatch_error_handler_workflow(
        self,
        *,
        target_workflow_id: str,
        source_workflow_id: str,
        source_execution_id: Optional[str],
        user_id: str,
        error: Optional[str],
        nodes_executed: int,
        duration: float,
    ) -> None:
        """Load the target workflow, find its on-error node, inject the source
        run's error payload, and call ``handle_execute`` with that node as
        ``start_node_id``. The handler's on-error-subgraph extractor skips
        extraction when start_node_id explicitly points at an on-error node, so
        the node executes via the normal trigger path. Logs and swallows every
        failure — error routing must never raise into the source run's
        completion path."""
        try:
            fetched = await self._fetch_workflow(target_workflow_id, user_id)
            if not fetched:
                logger.warning(
                    f"[ErrorRouting] Target workflow {target_workflow_id} not found / no access "
                    f"for user {user_id} (source={source_workflow_id})"
                )
                return
            target_nodes, target_edges, target_org_id, _variables, _settings = fetched
            on_error_node = next(
                (n for n in target_nodes if n.get('type') == 'on-error'), None
            )
            if not on_error_node:
                logger.info(
                    f"[ErrorRouting] Target workflow {target_workflow_id} has no on-error node — "
                    f"skipping dispatch from source {source_workflow_id}"
                )
                return

            import copy
            target_nodes = copy.deepcopy(target_nodes)
            on_error_id = on_error_node['id']
            for n in target_nodes:
                if n['id'] == on_error_id:
                    # Mirror the in-workflow on-error injection shape so the
                    # node's execute() surfaces these as output. workflow_id /
                    # execution_id refer to the SOURCE run by design — that's
                    # what the handler needs to act on.
                    n.setdefault('config', {})['_error_inputs'] = {
                        'error': error,
                        'workflow_id': source_workflow_id,
                        'execution_id': source_execution_id,
                        'nodes_executed': nodes_executed,
                        'duration': round(duration, 2),
                    }
                    break

            error_request = WorkflowExecuteRequest(
                event_name="workflow:execute",
                request_id=f"error-handler-{source_execution_id or 'unknown'}",
                workflow_id=target_workflow_id,
                nodes=target_nodes,
                edges=target_edges,
                start_node_id=on_error_id,
                trigger_source='error_handler',
            )
            logger.info(
                f"[ErrorRouting] Dispatching error handler: source={source_workflow_id} "
                f"target={target_workflow_id} on_error_node={on_error_id} "
                f"target_org={target_org_id}"
            )
            await self.handle_execute(
                sid="",
                request=error_request,
                caller_user_id=user_id,
            )
        except Exception as e:
            logger.error(
                f"[ErrorRouting] Failed to dispatch error handler workflow "
                f"{target_workflow_id} from {source_workflow_id}: {e}",
                exc_info=True,
            )

    async def _is_execution_suspended(self, execution_id: Optional[str]) -> bool:
        """True if the execution row is in a suspended (awaiting_*) status.

        A suspending node's strategy (approval, delay) writes the suspended
        status synchronously before the run loop returns, so the completion
        path can read it back here to decide whether the run paused vs ended.
        """
        if not execution_id:
            return False
        pool = await self.get_pool()
        if not pool:
            return False
        import uuid as _uuid
        async with pool.acquire() as conn:
            status = await WorkflowRepo(pool).get_execution_status(
                conn, _uuid.UUID(execution_id),
            )
        return status is not None and status in SUSPENDED_STATUSES

    # ------------------------------------------------------------------
    # Suspend/resume — partial-subgraph execution after a paused run is
    # resumed (a human responds to an approval, or a delay timer fires).
    # Mirrors handle_execute's worker-dispatch shape so isolation
    # guarantees apply to this path too.
    # ------------------------------------------------------------------

    async def handle_resume(
        self,
        sid: str,
        data: dict,
        caller_user_id: Optional[str] = None,
    ) -> None:
        """Public entry — runs the resume inline on the asyncio loop.

        Resumes a workflow that paused on a suspending node. Computes the
        downstream subgraph and runs only those nodes (the suspending node
        itself uses its prior output as a mockedOutput so downstream
        predecessors fire normally).

        ``data`` shape:
            execution_id          original paused execution UUID (str)
            workflow_id           workflow UUID (str)
            workflow_org_id       optional org UUID (str)
            resume_node_id        the suspending node's id (str)
            from_status           the suspended status to transition away
                                  from ('awaiting_approval' / 'awaiting_delay')
            decision              chosen output handle name (str), or None for
                                  non-conditional resume (delay) — None means
                                  follow all successors
            edited_values         dict of values the approver edited (optional)
        """
        try:
            await self._handle_resume_impl(sid, data, caller_user_id)
        except Exception as e:
            logger.exception("[WorkflowExecution] inline resume failed: %s", e)
            payload = WorkflowCompleteEvent(
                execution_id=str(data.get('execution_id') or 'unknown'),
                workflow_id=str(data.get('workflow_id') or 'unknown'),
                success=False,
                nodes_executed=0,
                duration=0,
                error=f"Resume failed: {e}",
            ).model_dump(mode='json', exclude_none=True)
            try:
                await self.sio.emit(WorkflowCompleteEvent.event_name, payload, to=sid)
            except Exception as emit_err:
                logger.warning("[WorkflowExecution] synthetic resume completion emit failed: %s", emit_err)

    async def _handle_resume_impl(
        self,
        sid: str,
        data: dict,
        caller_user_id: Optional[str],
    ) -> None:
        """Run the resume orchestrator in the current process.

        ONLY called from inside a resume_worker subprocess via
        workers.resume_worker._run_resume. The public handle_resume()
        always dispatches; never call this directly from the parent's
        request-handling path.

        Computes the downstream subgraph from the suspending node, creates a
        new execution record, sets up the relay, runs nodes via
        _execute_nodes_concurrent, persists outputs, and updates the original
        execution row to no-longer-suspended.

        When ``decision`` is set (approval), only edges from the chosen output
        handle are followed. When it is None (delay), all successors run.
        """
        import uuid as uuid_module
        from utils.node_outputs import execution_outputs
        from utils.execution_relay import create_execution_relay
        from wss.sender import _active_execution_relay

        start_time = time.time()
        execution_id = data['execution_id']
        workflow_id = data['workflow_id']
        workflow_org_id = data.get('workflow_org_id')
        resume_node_id = data['resume_node_id']
        from_status = data['from_status']
        decision = data.get('decision')
        edited_values = data.get('edited_values')
        context = data.get('_context') or {}
        user_id = caller_user_id or context.get('user_id')

        if not user_id:
            logger.error("[resume] missing user_id; cannot resume")
            return

        pool = await self.get_pool()
        if not pool:
            logger.error("[resume] DB pool unavailable")
            return

        # 1. Load all node outputs from the original execution
        initial_outputs = await execution_outputs(pool, execution_id)
        if not initial_outputs:
            logger.error(f"[resume] no outputs for execution {execution_id}")
            return

        # 2. Restore the suspending node's output. For a conditional resume
        #    (approval) set the chosen output_handle for branch routing.
        resume_output = initial_outputs.get(resume_node_id, {})
        if not isinstance(resume_output, dict):
            resume_output = {}
        if decision is not None:
            resume_output["isConditionalNode"] = True
            resume_output["output_handle"] = decision
            resume_output["status"] = decision
            if edited_values is not None:
                resume_output["values"] = edited_values
        initial_outputs[resume_node_id] = resume_output

        # 3. Fetch the workflow's current nodes and edges
        async with pool.acquire() as conn:
            row = await WorkflowRepo(pool).get_workflow_data_and_settings(
                conn, uuid_module.UUID(workflow_id),
            )
        if not row or not row["workflow"]:
            logger.error(f"[resume] workflow {workflow_id} not found")
            return

        workflow_data = row["workflow"]
        all_nodes = workflow_data.get("nodes", [])
        all_edges = workflow_data.get("edges", [])
        workflow_variables = {
            **self._defined_variable_values(row.get("settings") or {}),
            **workflow_data.get("variables", {}),
        }

        # 4. Build adjacency and compute downstream subgraph from the suspending
        #    node. For a conditional resume only the chosen output handle's
        #    edges count; otherwise every successor runs.
        successors: Dict[str, set] = {}
        for edge in all_edges:
            src = edge.get("source")
            tgt = edge.get("target")
            if src and tgt:
                successors.setdefault(src, set()).add(tgt)

        start_successors: set = set()
        for edge in all_edges:
            if edge.get("source") != resume_node_id:
                continue
            if decision is not None:
                handle = edge.get("sourceHandle") or "default"
                if handle != decision:
                    continue
            target = edge.get("target")
            if target:
                start_successors.add(target)

        downstream_ids: set = set()
        queue = list(start_successors)
        while queue:
            nid = queue.pop()
            if nid in downstream_ids:
                continue
            downstream_ids.add(nid)
            queue.extend(successors.get(nid, set()))

        if not downstream_ids:
            logger.info(f"[resume] no downstream nodes for node '{resume_node_id}'")
            async with pool.acquire() as conn:
                await WorkflowRepo(pool).complete_no_downstream_resume(
                    conn, uuid_module.UUID(execution_id), from_status,
                )
            return

        # 5. Filter to subgraph; include the suspending node itself with
        #    mockedOutput so downstream nodes see a node_done event for it.
        node_by_id = {n["id"]: n for n in all_nodes}
        execution_ids = downstream_ids | {resume_node_id}
        downstream_nodes = []
        for nid in execution_ids:
            node = node_by_id.get(nid)
            if not node:
                continue
            if nid == resume_node_id:
                import copy as _copy
                node = _copy.deepcopy(node)
                node.setdefault("config", {})["mockedOutput"] = resume_output
            downstream_nodes.append(node)
        downstream_edges = [
            e for e in all_edges
            if e.get("source") in execution_ids and e.get("target") in execution_ids
        ]

        # 6. Resume the ORIGINAL execution row in place — one logical run is
        #    one execution record. Flip it back to running. Outputs from before
        #    the suspension already live under this execution_id.
        async with pool.acquire() as conn:
            await WorkflowRepo(pool).resume_execution_running(
                conn, uuid_module.UUID(execution_id),
            )

        # 7. Connect to workflow relay relay. Declared up-front so the finally
        # block below can release it on any exit path. Pre-2026-05-25 the
        # cleanup at the end of this method lived outside a finally, so any
        # raise between relay creation and the end leaked the relay + its
        # WebSocket + its background listen_for_stop task — caught by the
        # per-event resource delta alert showing conversation:resume averaging
        # +0.2 threads / +1.6 MB per call.
        relay = create_execution_relay(workflow_id, execution_id, user_id)
        if not await relay.connect():
            logger.error("[resume] failed to connect to workflow relay relay")
            return

        relay_stop_task: Optional[asyncio.Task] = None
        try:
            # 8. Started event through relay — carries the ORIGINAL execution_id and
            #    resumed=True so the client updates the existing run's log line.
            await send_event(self.sio, sid, WorkflowStartedEvent(
                execution_id=execution_id,
                workflow_id=workflow_id,
                resumed=True,
            ), workflow_id=workflow_id, execution_relay=relay)

            cancellation_event = asyncio.Event()
            self._execution_relays[execution_id] = relay
            _active_execution_relay.set(relay)

            async def _run_resume():
                return await self._execute_nodes_concurrent(
                    downstream_nodes,
                    downstream_edges,
                    sid,
                    user_id,
                    workflow_id,
                    execution_id=execution_id,
                    initial_outputs=initial_outputs,
                    workflow_org_id=workflow_org_id,
                    workflow_variables=workflow_variables,
                    cancellation_event=cancellation_event,
                    include_last_output_node_id=True,
                )

            execution_task = asyncio.create_task(_run_resume())
            relay_stop_task = asyncio.create_task(
                relay.listen_for_stop(cancellation_event, execution_task=execution_task)
            )

            try:
                nodes_executed, error_msg, node_outputs, _last_output_node_id = await execution_task
            except asyncio.CancelledError:
                logger.info(f"[resume] cancelled by user for {execution_id[:8]}")
                nodes_executed = 0
                error_msg = USER_STOPPED_ERROR
                node_outputs = {}

            duration = time.time() - start_time
            success = error_msg is None

            # 9. Persist outputs and finish the (single) execution row.
            if node_outputs:
                spawn(
                    self._persist_node_outputs(
                        workflow_id, user_id, node_outputs,
                        execution_id=execution_id,
                        executable_nodes=downstream_nodes,
                    ),
                    name=f"persist-node-outputs-resume:{execution_id}",
                )

            # If the resumed run hit another suspending node (e.g. a second delay),
            # it re-suspended — leave the row in its new awaiting_* status rather
            # than overwriting it with completed.
            re_suspended = success and await self._is_execution_suspended(execution_id)

            if not re_suspended:
                async with pool.acquire() as conn:
                    repo = WorkflowRepo(pool)
                    if success:
                        await repo.finalize_resume_completed(
                            conn, uuid_module.UUID(execution_id), nodes_executed,
                        )
                    else:
                        await repo.finalize_resume_error(
                            conn, uuid_module.UUID(execution_id),
                            nodes_executed, error_msg,
                        )

            await send_event(self.sio, sid, WorkflowCompleteEvent(
                execution_id=execution_id,
                workflow_id=workflow_id,
                success=success,
                nodes_executed=nodes_executed,
                duration=duration,
                error=error_msg,
                suspended=re_suspended,
            ), workflow_id=workflow_id, execution_relay=relay)

            logger.info(
                f"[resume] resumed workflow {workflow_id} "
                f"({nodes_executed} nodes, {'success' if success else 'error'}, {duration:.2f}s)"
            )
        finally:
            # 10. Clean up relay + background task — must run on every exit path,
            # including exceptions inside the body, cancellation, and DB-error
            # raises during the completion writes.
            if relay_stop_task is not None:
                relay_stop_task.cancel()
            self._execution_relays.pop(execution_id, None)
            _active_execution_relay.set(None)
            try:
                await relay.close()
            except Exception:
                pass

    @staticmethod
    def _find_iteration_reachable_nodes(
        iteration_node_ids: Set[str], edges: List[Dict[str, Any]]
    ) -> Dict[str, Set[str]]:
        """
        For each iteration node, find all nodes in its loop body — i.e., nodes
        reachable from the iteration node via the "loop" output handle (or
        null/undefined sourceHandle for back-compat), transitively forward.

        IMPORTANT: only the "loop" handle's subgraph counts as the body. Nodes
        connected via the "done" handle run AFTER the loop completes; they're
        peer-of-the-loop, not body. If the brain (or a user) wires a "done"
        edge back to an upstream node, that's a real cycle in the broader
        graph, NOT a loop-back to filter — letting the topo sort detect it
        produces a clear cycle error instead of a misleading reference-failure.
        """
        # Build forward adjacency list from all edges
        forward: Dict[str, Set[str]] = defaultdict(set)
        for edge in edges:
            source, target = edge.get('source'), edge.get('target')
            if source and target:
                forward[source].add(target)

        reachable: Dict[str, Set[str]] = {}
        for it_id in iteration_node_ids:
            # Seed BFS only with direct successors via the "loop" handle (or
            # null/undefined for back-compat). Done-handle successors are peers
            # of the loop, not body, so we don't walk into them.
            loop_seeds: Set[str] = set()
            for edge in edges:
                if edge.get('source') != it_id:
                    continue
                handle = edge.get('sourceHandle')
                if handle == 'done':
                    continue
                target = edge.get('target')
                if target:
                    loop_seeds.add(target)

            visited: Set[str] = set()
            queue = deque(loop_seeds)
            while queue:
                nid = queue.popleft()
                if nid == it_id or nid in visited:
                    continue
                visited.add(nid)
                queue.extend(forward.get(nid, set()) - visited)
            reachable[it_id] = visited
        return reachable

    def _describe_cycle(self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> str:
        """Best-effort identification of the cycle for error messages.

        Runs Kahn's algorithm; nodes left with non-zero in-degree are in (or
        downstream of) at least one cycle. Walk one such node forward to
        recover an example cycle path. Returns a human-readable hint.
        """
        forward: Dict[str, List[str]] = defaultdict(list)
        in_degree: Dict[str, int] = {n['id']: 0 for n in nodes}
        for e in edges:
            s, t = e.get('source'), e.get('target')
            if s and t and s in in_degree and t in in_degree:
                forward[s].append(t)
                in_degree[t] += 1

        queue = deque(nid for nid, d in in_degree.items() if d == 0)
        while queue:
            nid = queue.popleft()
            for nxt in forward[nid]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)

        leftover = {nid for nid, d in in_degree.items() if d > 0}
        if not leftover:
            return ""

        # Try DFS from each leftover node to find an actual back-edge that
        # closes a cycle. Walking from a node downstream of (but not in) the
        # cycle dead-ends without revisiting — so try every starting node.
        for start in leftover:
            path: List[str] = []
            on_path: Set[str] = set()

            def dfs(node: str) -> Optional[List[str]]:
                if node in on_path:
                    idx = path.index(node)
                    return path[idx:] + [node]
                if node not in leftover:
                    return None
                path.append(node)
                on_path.add(node)
                for nxt in forward[node]:
                    found = dfs(nxt)
                    if found:
                        return found
                path.pop()
                on_path.discard(node)
                return None

            cycle = dfs(start)
            if cycle:
                return f"Cycle: {' → '.join(cycle)}."

        return f"Nodes involved in the cycle: {', '.join(sorted(leftover))}."

    def _topological_sort(self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[str]:
        """
        Build execution order using topological sort (Kahn's algorithm).
        Returns list of node IDs in execution order, or empty list if cycle detected.

        Loop-back edges (from body nodes back to iteration nodes) are filtered out
        as they are metadata for aggregation, not real dependencies.
        """
        # Build adjacency list and in-degree count
        graph = defaultdict(list)
        in_degree = defaultdict(int)

        # Initialize all nodes with 0 in-degree
        node_ids = {n['id'] for n in nodes}
        for node_id in node_ids:
            in_degree[node_id] = 0

        # Identify iteration nodes and all nodes reachable from them (transitive body nodes)
        iteration_node_ids = {n['id'] for n in nodes if n.get('type') == 'iteration'}
        iteration_reachable = self._find_iteration_reachable_nodes(iteration_node_ids, edges)

        # Build graph from edges, filtering out loop-back edges
        for edge in edges:
            source = edge.get('source')
            target = edge.get('target')

            # DANGLING edges (an endpoint references a node not in this run —
            # e.g. a deleted node whose edge survived in stale canvas state)
            # are data noise, not dependencies. Counting one bumps the
            # target's in-degree with a source that never executes, which
            # reads as a FALSE cycle ("processed N-1 of N") with an empty
            # cycle hint. Skip and log instead.
            if source and target and (source not in node_ids or target not in node_ids):
                logger.warning(
                    f"[WorkflowExecution] Ignoring dangling edge {edge.get('id', '?')} "
                    f"({source} -> {target}): endpoint not in execution set"
                )
                continue

            if source and target:
                # Skip loop-back edges: edges from any reachable body node back to its iteration node
                is_loopback = (
                    target in iteration_node_ids and
                    source in iteration_reachable.get(target, set())
                )
                if is_loopback:
                    logger.debug(f"[WorkflowExecution] Topological sort skipping loop-back edge {source} -> {target}")
                    continue

                graph[source].append(target)
                in_degree[target] += 1

        # Find all nodes with no incoming edges (starting points)
        queue = deque([node_id for node_id in in_degree if in_degree[node_id] == 0])
        execution_order = []

        while queue:
            # Process node with no dependencies
            node_id = queue.popleft()
            execution_order.append(node_id)

            # Reduce in-degree for all neighbors
            for neighbor in graph[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # If we couldn't process all nodes, there's a cycle
        if len(execution_order) != len(nodes):
            # Dump the offending graph — cycle reports have repeatedly turned
            # out to be stale/foreign graph state (dangling edges, ghost
            # nodes), and without the actual node/edge sets they're
            # undiagnosable from logs alone.
            stuck = sorted(node_ids - set(execution_order))
            edge_dump = [
                f"{e.get('id', '?')}:{e.get('source')}->{e.get('target')}" for e in edges
            ]
            logger.error(
                f"[WorkflowExecution] Cycle detected! Processed {len(execution_order)} of "
                f"{len(nodes)} nodes; stuck={stuck}; nodes={sorted(node_ids)}; edges={edge_dump}"
            )
            return []

        return execution_order

    def _get_reachable_nodes(
        self,
        start_node_id: str,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Get all nodes and edges reachable forward from a starting node,
        plus upstream interface/state-manager data providers.

        Phase 1: BFS forward from start_node_id (downstream dependents).
        Phase 2: Walk backward to find interface-* and state-manager nodes
                 that feed data into the forward-reachable set. Other
                 upstream node types are traversed but not added — their
                 cached outputs are preloaded separately.

        Returns:
            Tuple of (reachable_nodes, reachable_edges)
        """
        node_by_id = {n['id']: n for n in nodes}

        successors: Dict[str, List[str]] = {n['id']: [] for n in nodes}
        predecessors: Dict[str, List[str]] = {n['id']: [] for n in nodes}
        for edge in edges:
            source, target = edge.get('source'), edge.get('target')
            if source and target:
                is_state_edge = edge.get('targetHandle') == 'state'
                if source in successors and not is_state_edge:
                    successors[source].append(target)
                if target in predecessors:
                    predecessors[target].append(source)

        # Phase 1: BFS forward from start node
        visited: Set[str] = set()
        queue = deque([start_node_id])

        while queue:
            node_id = queue.popleft()
            if node_id in visited:
                continue
            visited.add(node_id)
            for successor in successors.get(node_id, []):
                if successor not in visited:
                    queue.append(successor)

        # Phase 2: Backfill upstream data-provider nodes (config forms,
        # state managers, and agent TOOL providers) that feed into the
        # forward-reachable set. Tool providers (any bottom-handle edge:
        # tool/mcp/alarm/filesystem/node_op integration providers) must
        # re-execute in triggered runs — without this they're excluded, the
        # provider→agent edge is filtered out, and the agent's edge-scoped
        # tool collection sees no tools (or only stale preloaded outputs).
        bottom_edge_sources: Dict[str, Set[str]] = {}
        for edge in edges:
            if edge.get('targetHandle') == 'bottom' and edge.get('source') and edge.get('target'):
                bottom_edge_sources.setdefault(edge['target'], set()).add(edge['source'])

        backfill_queue = deque(visited)
        backfill_seen = set(visited)
        while backfill_queue:
            node_id = backfill_queue.popleft()
            for pred_id in predecessors.get(node_id, []):
                if pred_id in backfill_seen:
                    continue
                backfill_seen.add(pred_id)
                pred_node = node_by_id.get(pred_id)
                if not pred_node:
                    continue
                # Canonical type: legacy graphs still carry pre-merge strings
                # (trigger-form-input / interface-config-form → interface-form),
                # and a legacy-typed form store must backfill like the real one.
                from nodes.core.registry import resolve_node_type
                pred_type = resolve_node_type(pred_node.get('type', '')) or ''
                if pred_type.startswith('trigger-'):
                    continue
                if (
                    pred_type.startswith('interface-')
                    or pred_type == 'state-manager'
                    or pred_id in bottom_edge_sources.get(node_id, set())
                ):
                    visited.add(pred_id)
                backfill_queue.append(pred_id)

        reachable_nodes = [n for n in nodes if n['id'] in visited]
        reachable_edges = [
            e for e in edges
            if e.get('source') in visited and e.get('target') in visited
        ]

        return reachable_nodes, reachable_edges

    def _build_dependency_maps(
        self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]
    ) -> Tuple[
        Dict[str, Set[str]],
        Dict[str, Dict[str, Any]],
        Dict[str, Set[str]],
        Dict[str, List[Tuple[str, Optional[str]]]],
    ]:
        """
        Build predecessor map, successors map, node lookup, and per-target predecessor
        edge list (with sourceHandle) from nodes and edges.

        Loop-back edges (edges from body nodes back to iteration nodes) are filtered out
        from the dependency maps to avoid cycles. These edges are metadata for the iteration
        strategy to determine which body node's output to aggregate, not real dependencies.

        Returns:
            Tuple of (predecessors map, node_by_id lookup, successors map,
                     predecessor_edges map of target_id -> [(source_id, sourceHandle, targetHandle), ...])
        """
        node_by_id = {n['id']: n for n in nodes}
        predecessors: Dict[str, Set[str]] = {n['id']: set() for n in nodes}
        successors: Dict[str, Set[str]] = {n['id']: set() for n in nodes}
        predecessor_edges: Dict[str, List[Tuple[str, Optional[str]]]] = {n['id']: [] for n in nodes}

        # Identify iteration nodes and all nodes reachable from them (transitive body nodes)
        iteration_node_ids = {n['id'] for n in nodes if n.get('type') == 'iteration'}
        iteration_reachable = self._find_iteration_reachable_nodes(iteration_node_ids, edges)

        for edge in edges:
            source, target = edge.get('source'), edge.get('target')
            # Dangling edges: a ghost TARGET would KeyError below; a ghost
            # SOURCE would park the target behind a dependency that never
            # completes (concurrent executor waits forever). Same skip as
            # _topological_sort.
            if source and target and (source not in node_by_id or target not in node_by_id):
                logger.warning(
                    f"[WorkflowExecution] Ignoring dangling edge {edge.get('id', '?')} "
                    f"({source} -> {target}): endpoint not in execution set"
                )
                continue
            if source and target:
                # Skip loop-back edges: edges from any reachable body node back to its iteration node
                # These are metadata for aggregation, not real dependencies
                is_loopback = (
                    target in iteration_node_ids and
                    source in iteration_reachable.get(target, set())
                )
                if is_loopback:
                    logger.debug(f"[WorkflowExecution] Skipping loop-back edge {source} -> {target}")
                    continue

                if target in predecessors:
                    predecessors[target].add(source)
                    predecessor_edges[target].append(
                        (source, edge.get('sourceHandle'), edge.get('targetHandle'))
                    )
                if source in successors:
                    successors[source].add(target)

        return predecessors, node_by_id, successors, predecessor_edges

    def _create_mark_completed_callback(
        self, state: ConcurrentExecutionState
    ) -> Callable[[str, Any], Any]:
        """Create a callback for marking a node as completed."""
        async def mark_completed(node_id: str, output: Any) -> None:
            async with state.lock:
                state.node_outputs[node_id] = output
                state.completed.add(node_id)
                state.last_output_node_id = node_id
        return mark_completed

    def _create_mark_failed_callback(
        self, state: ConcurrentExecutionState
    ) -> Callable[[str, str], Any]:
        """Create a callback for marking a node as failed."""
        async def mark_failed(node_id: str, error_msg: str) -> None:
            async with state.lock:
                state.failed.add(node_id)
                state.node_errors[node_id] = error_msg
                if state.first_error is None:
                    state.first_error = error_msg
        return mark_failed

    def _create_mark_skipped_callback(
        self, state: ConcurrentExecutionState
    ) -> Callable[[str], Any]:
        """Create a callback for marking a node as skipped (e.g., inactive conditional branch)."""
        async def mark_skipped(node_id: str) -> None:
            async with state.lock:
                state.skipped.add(node_id)
        return mark_skipped

    def _check_output_for_error(self, output: Any) -> Optional[str]:
        """Error indicator carried in a node's output — shared definition in
        nodes/core/execution_strategy.py so strategies (which bypass this
        loop) run the SAME check."""
        from nodes.core.execution_strategy import check_output_error

        return check_output_error(output)

    async def _execute_nodes_concurrent(
        self,
        executable_nodes: List[Dict[str, Any]],
        executable_edges: List[Dict[str, Any]],
        sid: str,
        user_id: str,
        workflow_id: str,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        execution_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        initial_outputs: Optional[Dict[str, Any]] = None,
        workflow_org_id: Optional[str] = None,
        cancellation_event: Optional[asyncio.Event] = None,
        workflow_variables: Optional[Dict[str, Any]] = None,
        include_last_output_node_id: bool = False,
        noop_silent_node_id: Optional[str] = None,
    ) -> Union[
        Tuple[int, Optional[str], Dict[str, Any]],
        Tuple[int, Optional[str], Dict[str, Any], Optional[str]],
    ]:
        """
        Execute workflow nodes concurrently based on dependency graph.

        Nodes execute as soon as all their predecessors complete. Uses asyncio.Event
        for dependency coordination and asyncio.Semaphore for concurrency limiting.
        On node failure, downstream nodes are skipped (cascade failure).

        Sets the billing workflow-attribution contextvar for the whole run:
        per-node tasks created below inherit it, so every usage event written
        during execution carries metadata.workflow_id (see usage_tracker).

        Args:
            executable_nodes: List of node definitions
            executable_edges: List of edges defining dependencies
            sid: Session ID for sending events
            user_id: User ID for credential resolution
            workflow_id: Workflow ID for event emission
            max_concurrency: Maximum number of nodes executing in parallel
            conversation_id: Optional conversation ID for agent memory persistence (workflow chat)
            initial_outputs: Optional pre-populated node outputs (e.g., tool arguments)
            workflow_org_id: Optional organization ID of the workflow (for credential access control)

        Returns:
            Tuple of `(nodes_executed_count, error_message or None, node_outputs dict)`.
            When `include_last_output_node_id=True`, appends `last_output_node_id`.
        """
        if not executable_nodes:
            if include_last_output_node_id:
                return 0, None, {}, None
            return 0, None, {}

        # Billing attribution: child tasks (one per node, created in the gather
        # below) copy this context, so every usage event a node writes carries
        # the workflow id without per-call-site plumbing.
        from billing.usage_tracker import CURRENT_WORKFLOW_ID
        CURRENT_WORKFLOW_ID.set(workflow_id)

        predecessors, node_by_id, successors, predecessor_edges = self._build_dependency_maps(executable_nodes, executable_edges)

        # Per-node: does the node have any outgoing edge wired to its error handle?
        # This gates the new per-handle routing — if a node uses continueErrorOutput
        # without an actual error edge wired, we fall back to legacy behavior so
        # pre-existing workflows (where the handle was invisible) keep working.
        nodes_with_error_edge: Set[str] = {
            e['source'] for e in executable_edges
            if e.get('source') and e.get('sourceHandle') == 'error'
        }
        state = ConcurrentExecutionState()

        # Pre-populate with initial outputs (e.g., tool arguments for downstream execution)
        if initial_outputs:
            state.node_outputs.update(initial_outputs)

        # Inject workflow variables as a synthetic 'vars' entry so {{vars.key}} resolves
        if workflow_variables:
            state.node_outputs['vars'] = workflow_variables

        semaphore = asyncio.Semaphore(max_concurrency)

        # Track which nodes are handled by an explicit iteration node's body (the
        # iteration strategy executes them per-item and reports them back, so the
        # main loop skips them). There is no implicit [] auto-iteration.
        nodes_in_iteration: Set[str] = set()

        # Identify "tool implementation nodes" - downstream of tool nodes, but NOT agent nodes
        # These nodes should NOT execute during main workflow - they execute when agent calls the tool
        tool_implementation_nodes: Set[str] = set()
        tool_node_ids = {n['id'] for n in executable_nodes if n.get('type') == 'tool'}
        for tool_id in tool_node_ids:
            for successor_id in successors.get(tool_id, set()):
                successor_node = node_by_id.get(successor_id)
                if successor_node and successor_node.get('type') != 'agent':
                    # This is a tool implementation node (not an agent receiving the definition)
                    tool_implementation_nodes.add(successor_id)
                    logger.debug(f"[WorkflowExecution] Node {successor_id} is tool implementation for {tool_id}, will skip in main execution")

        # Event per node - set when node reaches terminal state (completed/failed/skipped)
        node_done: Dict[str, asyncio.Event] = {n['id']: asyncio.Event() for n in executable_nodes}

        async def execute_single_node(node_id: str) -> None:
            """Execute a single node after waiting for all predecessors."""
            nonlocal workflow_variables
            node = node_by_id[node_id]
            node_type = node.get('type', 'unknown')

            # Wait for all predecessors to complete first
            for pred_id in predecessors[node_id]:
                await node_done[pred_id].wait()

            # Check for cancellation request
            if cancellation_event and cancellation_event.is_set():
                logger.info(f"[WorkflowExecution] Execution cancelled, skipping node {node_id}")
                async with state.lock:
                    state.skipped.add(node_id)
                    if state.first_error is None:
                        state.first_error = USER_STOPPED_ERROR
                node_done[node_id].set()
                return

            # Skip nodes already handled by a strategy (iteration, conditional, switch)
            # Check both the nodes_in_iteration set AND the state sets, because there's a
            # race window between signal_done in a strategy's finally block and the main
            # loop updating nodes_in_iteration after the strategy returns
            async with state.lock:
                if node_id in nodes_in_iteration:
                    return
                if node_id in state.completed or node_id in state.skipped:
                    # Already handled by a strategy (e.g., switch/conditional executed or skipped this node)
                    return

            # Skip tool implementation nodes - they only execute when agent calls the tool
            # These are nodes downstream of tool nodes that are NOT agent nodes
            if node_id in tool_implementation_nodes:
                logger.info(f"[WorkflowExecution] Skipping tool implementation node {node_id} - will be executed when tool is called")
                node_done[node_id].set()
                return

            # Check if there is any LIVE incoming edge - cascade skip if none.
            #
            # An edge (p -> node_id, handle) is live iff:
            #   - handle == 'error': predecessor finished via continueErrorOutput AND had a wired
            #     error edge (i.e., p in state.error_continuations).
            #   - otherwise (success/default handle, or any non-'error' handle such as the
            #     conditional 'true'/'false' branches): predecessor completed normally
            #     (p in state.completed) AND did NOT divert to the error handle
            #     (p not in state.error_continuations).
            #
            # Failed/skipped predecessors are not in `completed` so all their edges are dead,
            # preserving the original cascade-skip semantics for back-compat.
            should_cascade_skip = False
            async with state.lock:
                # Tool-surface wiring (targetHandle 'bottom': node_op providers,
                # alarm/filesystem/mcp/tool nodes into an agent) is capability
                # plumbing, not dataflow. Providers always complete (pure config
                # derivation), so counting their edges as liveness made an agent
                # with any wired tool immune to cascade-skip, even when the fired
                # trigger failed. Provider edges still
                # gate ORDERING via `predecessors` (tool configs ride
                # node_outputs); they just can't keep a dead branch alive.
                node_pred_edges = [
                    (p, h) for p, h, th in predecessor_edges[node_id] if th != 'bottom'
                ]
                if node_pred_edges:  # Only check if node has incoming DATAFLOW edges
                    def _edge_live(pred_id: str, handle: Optional[str]) -> bool:
                        if handle == 'error':
                            return pred_id in state.error_continuations
                        return (
                            pred_id in state.completed
                            and pred_id not in state.error_continuations
                        )
                    if not any(_edge_live(p, h) for p, h in node_pred_edges):
                        state.skipped.add(node_id)
                        should_cascade_skip = True
            if should_cascade_skip:
                logger.info(
                    f"[WorkflowExecution] Skipping node {node_id} - "
                    f"no live incoming edges (all predecessors failed/skipped or routed to a different handle)"
                )
                # Emit a 'skipped' state event so the frontend can render the
                # skip visually — important for the error-handle case where the
                # user expects to see the success branch greyed out.
                await self._emit_node_state(
                    sid, workflow_id, node_id, node_type, 'skipped', None, execution_id
                )
                node_done[node_id].set()
                return

            # Handle disabled nodes (read from the flat config blob)
            node_disabled = node.get('config', {}).get('disabled', False)
            if node_disabled:
                logger.info(f"[WorkflowExecution] Skipping disabled node {node_id} ({node_type})")
                await self._emit_node_state(
                    sid, workflow_id, node_id, node_type, 'skipped', None, execution_id
                )
                async with state.lock:
                    state.skipped.add(node_id)
                node_done[node_id].set()
                return


            # Handle webhook trigger payload — let the node decide whether
            # the payload is the final output or just a wake-up signal.
            node_config = node.get('config', {})
            trigger_payload = node_config.get('_triggerPayload')
            if trigger_payload is not None:
                # Either-or guard: trigger + provider on ONE node is rejected at
                # edit time (trigger_provider_conflict), but legacy workflows may
                # still carry the combo. Provider mode wins — the agent keeps its
                # tools; the event is dropped with a loud log.
                from nodes.agent.node_op_tools import is_node_op_provider
                if is_node_op_provider(node_id, node_type, executable_nodes, executable_edges):
                    logger.warning(
                        f"[WorkflowExecution] Node {node_id} ({node_type}) is provider-wired "
                        f"but received a trigger payload — ignoring the payload (a node "
                        f"cannot be both a trigger and an agent tool provider; use a "
                        f"separate node per role)"
                    )
                    trigger_payload = None
            if trigger_payload is not None:
                from nodes.core.registry import NODE_REGISTRY
                node_cls = NODE_REGISTRY.get(node_type)
                resolved = node_cls.resolve_trigger_payload(trigger_payload, node_config) if node_cls else trigger_payload
                if resolved is not None:
                    logger.info(f"[WorkflowExecution] Using trigger payload as output for node {node_id} ({node_type})")
                    await self._emit_node_state(
                        sid, workflow_id, node_id, node_type, 'running', None, execution_id
                    )
                    async with state.lock:
                        state.node_outputs[node_id] = resolved
                        state.completed.add(node_id)
                        state.last_output_node_id = node_id
                    await self._emit_node_output(
                        sid, workflow_id, node_id, node_type, resolved
                    )
                    await self._emit_node_state(
                        sid, workflow_id, node_id, node_type, 'completed', None, execution_id
                    )
                    node_done[node_id].set()
                    # Record the trigger's output shape so the builder can surface a
                    # fields/suggestions view. resolve_trigger_payload short-circuits
                    # execute(), where track_node_schema normally runs — without this a
                    # push-fired trigger (webhook/cron/email) is never observed, so a
                    # trigger that only ever fires via push gets no schema / suggested refs.
                    # node_done is already set, so this records concurrently with downstream.
                    try:
                        await track_node_schema(
                            node_type=node_type,
                            node_operation=node_config.get('operation') or 'default',
                            output=resolved,
                            # Strip runtime _-prefixed keys before recording — _triggerPayload
                            # holds the raw inbound payload (e.g. the full email content), which
                            # must not be persisted as sample_config.
                            config={k: v for k, v in node_config.items() if not k.startswith('_')},
                        )
                    except Exception as e:
                        logger.warning(f"[WorkflowExecution] track_node_schema (trigger) failed for {node_id}: {e}")
                    return
                else:
                    logger.info(f"[WorkflowExecution] Node {node_id} ({node_type}) opted to execute despite trigger payload")

            # Handle mocked output (user-initiated mocking, not webhook triggers)
            # Note: Iteration nodes handle mocked output specially in their strategy
            # to still iterate over mocked items and execute body nodes
            mocked_output = node_config.get('mockedOutput')
            if mocked_output is not None:
                # Tool-provider nodes ignore mocks: their output is derived
                # purely from current config (operation allowlist + credential
                # binding), so replaying a stale mock would hand the agent an
                # outdated credential_id/allowlist. Fall through to the live
                # provider short-circuit in _execute_node instead.
                from nodes.agent.node_op_tools import is_node_op_provider
                if is_node_op_provider(node_id, node_type, list(node_by_id.values()), executable_edges):
                    logger.info(
                        f"[WorkflowExecution] Ignoring mocked output for tool-provider node {node_id}"
                    )
                    mocked_output = None
            if mocked_output is not None and node_type not in ('iteration', 'noclick'):
                logger.info(f"[WorkflowExecution] Using mocked output for node {node_id} ({node_type})")
                # Send running state first so frontend shows spinner
                await self._emit_node_state(
                    sid, workflow_id, node_id, node_type, 'running', None, execution_id
                )
                async with state.lock:
                    state.node_outputs[node_id] = mocked_output
                    state.completed.add(node_id)
                    state.last_output_node_id = node_id
                await self._emit_node_output(
                    sid, workflow_id, node_id, node_type, mocked_output
                )
                await self._emit_node_state(
                    sid, workflow_id, node_id, node_type, 'completed', None, execution_id
                )
                node_done[node_id].set()
                return

            # A test never acts on a real account. The agent's tool calls are
            # answered by the fabricated world (tool_execution/run_op gates);
            # this covers the rest of the reachable graph — a send node wired
            # after the agent, a sub-workflow — which would otherwise execute
            # for real, credentials and all. Tool providers pass through: they
            # short-circuit to config-derived tool metadata in _execute_node
            # and never touch the provider.
            from nodes.agent.rehearsal import (
                is_rehearsal_conversation,
                rehearsal_excluded_node_types,
            )
            if (
                is_rehearsal_conversation(conversation_id)
                and node_type in rehearsal_excluded_node_types()
            ):
                from nodes.agent.node_op_tools import is_node_op_provider
                if not is_node_op_provider(node_id, node_type, executable_nodes, executable_edges):
                    logger.info(
                        f"[WorkflowExecution] Rehearsal: skipping {node_id} ({node_type}) — "
                        f"acts on a real account, not executed in a test"
                    )
                    await self._emit_node_state(
                        sid, workflow_id, node_id, node_type, 'skipped', None, execution_id
                    )
                    async with state.lock:
                        state.skipped.add(node_id)
                    node_done[node_id].set()
                    return

            # Check if a strategy handles this node type (e.g., iteration, conditional)
            strategy = StrategyRegistry.get_strategy(node_type)
            if strategy:
                # try/finally so node_done is set no matter how the branch
                # exits — a strategy that raises out (or a ctx construction
                # error) must never strand successors waiting on node_done,
                # which hangs the gather and leaves the execution row
                # 'running' forever.
                try:
                    # Create execution context with callbacks
                    ctx = ExecutionContext(
                        node_id=node_id,
                        node=node,
                        workflow_id=workflow_id,
                        node_outputs=state.node_outputs,
                        node_by_id=node_by_id,
                        successors=successors,
                        predecessors=predecessors,
                        edges=executable_edges,
                        sid=sid,
                        user_id=user_id,
                        organization_id=workflow_org_id,
                        execution_id=execution_id,
                        semaphore=semaphore,
                        execute_node=lambda n, outputs: self._execute_node(
                            n, outputs, sid, user_id, workflow_id, conversation_id,
                            executable_nodes, executable_edges, workflow_org_id, execution_id
                        ),
                        emit_state=lambda nid, ntype, st, err: self._emit_node_state(
                            sid, workflow_id, nid, ntype, st, err, execution_id
                        ),
                        emit_output=lambda nid, ntype, out: self._emit_node_output(
                            sid, workflow_id, nid, ntype, out
                        ),
                        mark_completed=self._create_mark_completed_callback(state),
                        mark_failed=self._create_mark_failed_callback(state),
                        mark_skipped=self._create_mark_skipped_callback(state),
                        signal_done=lambda nid: node_done[nid].set() if nid in node_done else None,
                    )

                    result = await strategy.execute(ctx)

                    # Mark body nodes as handled so main loop skips them
                    async with state.lock:
                        nodes_in_iteration.update(result.body_nodes_handled)

                    # Mark loop body nodes as completed and emit state
                    # (the iteration strategy updates outputs but doesn't call mark_completed to avoid re-execution)
                    for body_node_id in result.body_nodes_handled:
                        if body_node_id in state.node_outputs:
                            body_node = node_by_id.get(body_node_id)
                            if body_node:
                                await self._emit_node_state(
                                    sid, workflow_id, body_node_id,
                                    body_node.get('type', 'unknown'),
                                    'completed', None, execution_id
                                )
                finally:
                    node_done[node_id].set()

                return

            # Acquire semaphore and execute (regular nodes)
            async with semaphore:
                await self._emit_node_state(
                    sid, workflow_id, node_id, node_type, 'running', None, execution_id
                )

                try:
                    rss_before = get_rss_mb()
                    threads_before = threading.active_count()
                    node_label = node.get('label', node_type)

                    # Per-node execution settings (retry, error handling, output options)
                    _settings = (node.get('config') or {}).get('_settings') or {}
                    _retry_on_fail = _settings.get('retryOnFail') == 'true'
                    _max_tries = max(1, min(5, int(_settings.get('maxTries') or 2))) if _retry_on_fail else 1
                    _wait_ms = max(0, min(5000, int(_settings.get('waitBetweenTries') or 1000)))
                    _on_error = _settings.get('onError') or 'stopWorkflow'
                    _always_output_data = _settings.get('alwaysOutputData') == 'true'
                    _execute_once = _settings.get('executeOnce') == 'true'

                    # executeOnce: only pass data from the first upstream source
                    _effective_node_outputs = state.node_outputs
                    if _execute_once and _effective_node_outputs:
                        _first_key = next(iter(_effective_node_outputs))
                        _effective_node_outputs = {_first_key: _effective_node_outputs[_first_key]}

                    _last_error = None
                    output = None
                    for _attempt in range(_max_tries):
                        try:
                            output = await self._execute_node(
                                node, _effective_node_outputs, sid, user_id, workflow_id, conversation_id,
                                executable_nodes, executable_edges, workflow_org_id, execution_id
                            )
                            _last_error = None
                            break
                        except Exception as _exc:
                            _last_error = _exc
                            if _attempt < _max_tries - 1 and _wait_ms > 0:
                                await asyncio.sleep(_wait_ms / 1000)

                    # Track whether this node's output should be routed via the 'error' handle
                    # (only true when the user wired an error edge AND the node failed with
                    # continueErrorOutput). Used after success/error_check to mark the node
                    # in state.error_continuations so downstream routing skips its default handle.
                    _route_via_error_handle = False

                    if _last_error is not None:
                        if _on_error == 'continueRegularOutput':
                            output = {}
                            logger.warning(f"[Execution] Node {node_id} failed after {_max_tries} tries (continueRegularOutput): {_last_error}")
                        elif _on_error == 'continueErrorOutput':
                            output = {'error': str(_last_error), 'error_type': type(_last_error).__name__}
                            logger.warning(f"[Execution] Node {node_id} failed after {_max_tries} tries (continueErrorOutput): {_last_error}")
                            # Only opt into the new per-handle routing if the user actually wired
                            # an error edge. Otherwise, fall back to legacy behavior (downstream
                            # default-handle edges receive the error dict) so workflows authored
                            # before the error handle was visible keep behaving the same.
                            if node_id in nodes_with_error_edge:
                                _route_via_error_handle = True
                        else:
                            raise _last_error

                    if _always_output_data and not output:
                        output = {}

                    rss_after = get_rss_mb()

                    # Reclaim fragmented glibc arena pages when RSS is high
                    if rss_after > 3000:
                        gc.collect()
                        try:
                            import ctypes
                            ctypes.CDLL("libc.so.6").malloc_trim(0)
                        except (OSError, AttributeError):
                            pass
                        rss_after = get_rss_mb()

                    threads_after = threading.active_count()
                    rss_delta = rss_after - rss_before

                    # On large spike: auto-capture tracemalloc top allocators
                    if rss_delta > 50 and tracemalloc.is_tracing():
                        snapshot = tracemalloc.take_snapshot()
                        snapshot = snapshot.filter_traces([
                            tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
                            tracemalloc.Filter(False, "<frozen importlib._bootstrap_external>"),
                        ])
                        top_stats = snapshot.statistics("lineno")[:10]
                        lines = [f"  {s.traceback[0].filename}:{s.traceback[0].lineno} → {s.size / 1024 / 1024:.1f}MB ({s.count} allocs)" for s in top_stats]
                        logger.warning(
                            f"[MEMORY] tracemalloc top allocators after {node_id} \"{node_label}\":\n" + "\n".join(lines)
                        )


                    # Check for error indicators in output (e.g., serverless function exit_code != 0)
                    output_error = self._check_output_for_error(output)
                    if output_error:
                        # Node returned output with error indicator - treat as failure
                        async with state.lock:
                            state.node_outputs[node_id] = output
                            state.failed.add(node_id)
                            state.node_errors[node_id] = output_error
                            if state.first_error is None:
                                state.first_error = f"Node {node_id} failed: {output_error}"
                            state.last_output_node_id = node_id

                        await self._emit_node_output(
                            sid, workflow_id, node_id, node_type, output
                        )
                        await self._emit_node_state(
                            sid, workflow_id, node_id, node_type, 'error', output_error, execution_id
                        )
                        logger.error(f"[WorkflowExecution] Node {node_id} ({node_type}) failed: {output_error}")
                    elif isinstance(output, dict) and output.pop('_halt_downstream', False):
                        # Poll trigger found no new data: mark it skipped
                        # (not completed) so the existing no-live-edge cascade halts
                        # every downstream node. The node ran fine — it just has no
                        # event to deliver — so this is a quiet no-op, not an error.
                        async with state.lock:
                            state.node_outputs[node_id] = output
                            state.skipped.add(node_id)
                        await self._emit_node_state(
                            sid, workflow_id, node_id, node_type, 'skipped', None, execution_id
                        )
                        logger.info(
                            f"[WorkflowExecution] Poll trigger {node_id} ({node_type}) found no "
                            f"new data — halting downstream (no nodes will run)"
                        )
                    else:
                        from nodes.core.registry import NODE_REGISTRY

                        node_cls = NODE_REGISTRY.get(node_type)
                        should_propagate = (
                            node_cls.should_propagate_output(output, node_config)
                            if node_cls is not None
                            else True
                        )
                        async with state.lock:
                            state.node_outputs[node_id] = output
                            if should_propagate:
                                state.completed.add(node_id)
                            else:
                                state.skipped.add(node_id)
                            if should_propagate and _route_via_error_handle:
                                state.error_continuations.add(node_id)
                            state.last_output_node_id = node_id

                        # A Google Drive/Calendar trigger watches the whole drive,
                        # so every change wakes every such trigger; the ones whose
                        # filter doesn't match return change_count=0. For a headless
                        # wake-up that's a no-op (this node, no actionable output),
                        # suppress the empty output so it doesn't surface as a fire.
                        suppress_noop = (not should_propagate) and node_id == noop_silent_node_id
                        if not suppress_noop:
                            await self._emit_node_output(
                                sid, workflow_id, node_id, node_type, output
                            )
                        await self._emit_node_state(
                            sid,
                            workflow_id,
                            node_id,
                            node_type,
                            'completed' if should_propagate else 'skipped',
                            None,
                            execution_id,
                        )
                        if should_propagate:
                            logger.info(
                                f"[WorkflowExecution] Node {node_id} ({node_type}) completed successfully"
                                + (" (routed via error handle)" if _route_via_error_handle else "")
                            )
                            # Fire-and-forget per-node analytics (the blocking flush is
                            # offloaded off the critical path by log_activity_background).
                            log_activity_background(Events.NODE_EXECUTED_SUCCESSFULLY, user_id, {
                                "node_id": node_id,
                                "node_type": node_type,
                                "workflow_id": workflow_id,
                            })
                        else:
                            logger.info(
                                f"[WorkflowExecution] Node {node_id} ({node_type}) produced no actionable output; downstream propagation skipped"
                            )

                        # Set-variable nodes: update workflow variables for downstream reference
                        if node_type == 'set-variable' and isinstance(output, dict):
                            assignments = output.get('assignments', [])
                            # Backward compat: legacy single variable_name/value output
                            if not assignments and output.get('variable_name'):
                                assignments = [{"variable_name": output['variable_name'], "value": output.get('value')}]
                            for assignment in assignments:
                                var_name = assignment.get('variable_name', '')
                                if var_name:
                                    if workflow_variables is None:
                                        workflow_variables = {}
                                    workflow_variables[var_name] = assignment.get('value')
                            if workflow_variables is not None:
                                async with state.lock:
                                    state.node_outputs['vars'] = workflow_variables

                except Exception as e:
                    # A model provider's billing/auth rejection is rewritten
                    # into something the user can act on — raw text like
                    # "litellm.AuthenticationError … OpenrouterException" names
                    # a library they have never heard of and no next step.
                    # describe_failure scopes itself by node_type: only agent
                    # failures classify, everything else passes verbatim.
                    node_error, error_action = describe_failure(
                        e, node_type=node_type
                    )
                    error_msg = f"Node {node_id} failed: {node_error}"
                    logger.error(f"[WorkflowExecution] {error_msg}")
                    tag_config_validation_failure(e, node_id, node_type)

                    async with state.lock:
                        state.failed.add(node_id)
                        state.node_errors[node_id] = node_error
                        if state.first_error is None:
                            state.first_error = error_msg

                    await self._emit_node_state(
                        sid, workflow_id, node_id, node_type, 'error', node_error,
                        execution_id, error_action=error_action,
                    )

                finally:
                    node_done[node_id].set()

        # Launch all nodes concurrently - they coordinate via events
        await asyncio.gather(*(execute_single_node(nid) for nid in node_by_id))

        # Build the per-node last-run record for persistence (popped by
        # _persist_node_outputs). Merge so an on-error subgraph run that reuses
        # this execution_id adds its nodes without clobbering the main run's.
        if execution_id:
            async with state.lock:
                statuses = build_node_run_statuses(
                    state.completed, state.failed, state.skipped, state.node_errors,
                )
            self._execution_node_statuses.setdefault(execution_id, {}).update(statuses)

        result = (len(state.completed), state.first_error, dict(state.node_outputs))
        if include_last_output_node_id:
            return (*result, state.last_output_node_id)
        return result

    def _manual_replay_candidates(
        self, executable_nodes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Pure event triggers in the execution slice with no fired payload and
        no mock — a manual run replays their last persisted output instead of
        executing them (executing produces an empty event and breaks every
        downstream ``{{ $('trigger').field }}`` ref). Gated by the node class
        flag ``manual_run_replays_last_event``; poll triggers deliberately
        don't set it (their execute() fetches on demand)."""
        from nodes.core.registry import NODE_REGISTRY

        candidates = []
        for n in executable_nodes:
            node_cls = NODE_REGISTRY.get(n.get('type', ''))
            if not getattr(node_cls, 'manual_run_replays_last_event', False):
                continue
            config = n.get('config') or {}
            if config.get('_triggerPayload') is None and config.get('mockedOutput') is None:
                candidates.append(n)
        return candidates

    async def _preload_excluded_node_outputs(
        self,
        pool,
        workflow_id: str,
        all_nodes: List[Dict[str, Any]],
        executable_node_ids: Set[str],
    ) -> Dict[str, Any]:
        """
        Load latest stored outputs for nodes excluded from the execution slice.

        Used when ``forward_only=True`` + ``start_node_id`` causes upstream
        predecessors to be skipped — downstream ``{{node.path}}`` references
        would otherwise resolve to None and the literal ``{{...}}`` token would
        leak into the resolved config. Preloading their last-persisted outputs
        preserves the user's expectation that "run from here" sees the
        previously-computed upstream data.

        An excluded node with a ``mockedOutput`` preloads the MOCK, not the DB —
        the mock contract is "used as the node's output without executing", and
        it must hold whether the node is inside or outside the execution slice.
        This is also how an alarm fire restores its trigger snapshot: the webhook
        path plants the alarm payload's ``upstream_node_outputs`` as mockedOutput
        on the upstream trigger (``webhook_routes._restore_upstream_context``),
        reachability then excludes that trigger (it's neither downstream of the
        alarm nor a backfilled provider), and the snapshot flows in here.

        Returns ``{}`` on DB error or when there is nothing to preload.
        """
        outputs: Dict[str, Any] = {}
        db_node_ids: List[str] = []
        for n in all_nodes:
            nid = n.get('id')
            if not nid or nid in executable_node_ids:
                continue
            mocked = (n.get('config') or {}).get('mockedOutput')
            if mocked is not None:
                outputs[nid] = mocked
            else:
                db_node_ids.append(nid)
        if outputs:
            logger.info(
                f"[WorkflowExecution] Preloaded {len(outputs)} excluded node outputs "
                f"from mockedOutput"
            )
        if not db_node_ids:
            return outputs
        try:
            from utils.node_outputs import latest_outputs
            db_outputs = await latest_outputs(
                pool, workflow_id, db_node_ids,
            )
            if db_outputs:
                logger.info(
                    f"[WorkflowExecution] Preloaded {len(db_outputs)} upstream node outputs "
                    f"from DB for forward-only run"
                )
                outputs.update(db_outputs)
        except Exception as e:
            logger.warning(f"[WorkflowExecution] Failed to preload upstream outputs: {e}")
        return outputs

    def _resolve_references(self, value: Any, node_outputs: Dict[str, Any]) -> Any:
        """
        Recursively resolve references in config values.

        References follow the pattern: {{nodeId.path.to.field}}
        Examples:
            - {{node-1.output.message}} -> Gets 'message' from node-1's output
            - {{telegram-123.output.data.text}} -> Gets nested 'data.text' from output

        Args:
            value: The config value (can be string, dict, list, or primitive)
            node_outputs: Dict mapping node IDs to their output data

        Returns:
            The value with all references resolved
        """
        if isinstance(value, str):
            return self._resolve_string_references(value, node_outputs)
        elif isinstance(value, dict):
            return {k: self._resolve_references(v, node_outputs) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._resolve_references(item, node_outputs) for item in value]
        else:
            # Primitives (int, float, bool, None) - return as-is
            return value

    def _resolve_string_references(self, value: str, node_outputs: Dict[str, Any]) -> Union[str, Any]:
        """
        Resolve references in a string value.

        If the entire string is a single reference, returns the actual value (preserving type).
        If the string contains references mixed with text, returns a string with references substituted.

        Args:
            value: The string potentially containing references
            node_outputs: Dict mapping node IDs to their output data

        Returns:
            The resolved value (may be any type if entire string was a reference)
        """
        # Pattern to match references: {{nodeId.path.to.field}}
        reference_pattern = r'\{\{([^}]+)\}\}'

        # Check if the entire string is exactly one reference
        full_match = re.fullmatch(reference_pattern, value.strip())
        if full_match:
            # Return the actual value (preserving type), or preserve original if unresolvable
            resolved = self._resolve_single_reference(full_match.group(1), node_outputs)
            return value if resolved is None else resolved

        # Multiple references or mixed with text - substitute as strings
        def replace_reference(match):
            ref_path = match.group(1)
            resolved = self._resolve_single_reference(ref_path, node_outputs)
            # Convert to string for substitution
            if resolved is None:
                # Preserve unresolvable references as-is (e.g. JS object literals
                # like {{ background: '#fff' }} that aren't actual node references)
                return match.group(0)
            return str(resolved)

        return re.sub(reference_pattern, replace_reference, value)

    def _resolve_single_reference(self, ref_path: str, node_outputs: Dict[str, Any]) -> Any:
        """
        Resolve a single reference path like 'nodeId.output.field' or 'nodeId.files[4].name'.
        Also supports referencing entire node output with just 'nodeId'.

        '[]' maps over an array and returns the resulting LIST value
        ('nodeId.items[].title' -> [item['title'] for item in items]). It does
        NOT loop — looping is only done by an explicit iteration node.

        Args:
            ref_path: The reference path (without {{ }})
            node_outputs: Dict mapping node IDs to their output data

        Returns:
            The resolved value, or None if not found
        """
        # '[]' resolves to the mapped array value (no looping).
        if '[]' in ref_path:
            return self._resolve_mapped_array_reference(ref_path, node_outputs)

        parts = ref_path.split('.')

        # Allow single-part references to return entire node output
        if len(parts) < 1:
            logger.warning(f"[WorkflowExecution] Invalid reference format: {ref_path}")
            return None

        node_id = parts[0]
        path = parts[1:] if len(parts) > 1 else []

        # Diagnostic logging for debugging reference resolution
        logger.debug(f"[WorkflowExecution][RefResolve] Resolving reference: {{{{  {ref_path} }}}}")
        logger.debug(f"[WorkflowExecution][RefResolve]   Node ID: {node_id}")
        logger.debug(f"[WorkflowExecution][RefResolve]   Path: {path}")
        logger.debug(f"[WorkflowExecution][RefResolve]   Available nodes: {list(node_outputs.keys())}")

        if node_id not in node_outputs:
            logger.debug(f"[WorkflowExecution][RefResolve] Reference to unknown node: {node_id}")
            logger.debug(f"[WorkflowExecution][RefResolve] Available nodes: {list(node_outputs.keys())}")
            return None

        # Log iteration node references for debugging
        if 'iteration' in node_id and 'item' in path:
            logger.debug(f"[WorkflowExecution] Resolving iteration reference: {ref_path}")
            logger.debug(f"[WorkflowExecution] Iteration node output keys: {list(node_outputs[node_id].keys()) if isinstance(node_outputs[node_id], dict) else type(node_outputs[node_id])}")

        # Log the node's output structure
        node_output = node_outputs[node_id]
        logger.debug(f"[WorkflowExecution][RefResolve]   Node output type: {type(node_output)}")
        if isinstance(node_output, dict):
            logger.debug(f"[WorkflowExecution][RefResolve]   Node output keys: {list(node_output.keys())}")

        # If no path specified, return entire node output
        if not path:
            logger.debug(f"[WorkflowExecution][RefResolve] Returning entire node output")
            return node_outputs[node_id]

        # Navigate the path through the node's output
        current = node_outputs[node_id]
        for i, part in enumerate(path):
            # Handle parts with array indices like "files[4]" or just "[4]"
            # Parse out the key name (if any) and all array indices
            key_match = re.match(r'^([^\[]*)((?:\[\d+\])*)$', part)
            if not key_match:
                logger.warning(f"[WorkflowExecution] Invalid path part '{part}' in reference: {ref_path}")
                return None

            key_name = key_match.group(1)  # e.g., "files" or "" for pure index
            indices_str = key_match.group(2)  # e.g., "[4]" or "[0][1]" or ""

            # First, access the key if there is one
            if key_name:
                logger.debug(f"[WorkflowExecution][RefResolve]     Step {i+1}: Accessing key '{key_name}'")
                logger.debug(f"[WorkflowExecution][RefResolve]     Current type: {type(current)}")
                if isinstance(current, dict):
                    logger.debug(f"[WorkflowExecution][RefResolve]     Available keys: {list(current.keys())}")
                if isinstance(current, dict) and key_name in current:
                    current = current[key_name]
                    logger.debug(f"[WorkflowExecution][RefResolve]     Found '{key_name}', type: {type(current)}")
                else:
                    logger.debug(f"[WorkflowExecution][RefResolve]     Key '{key_name}' not found in reference: {ref_path}")
                    return None

            # Then, apply any array indices
            if indices_str:
                for index_match in re.finditer(r'\[(\d+)\]', indices_str):
                    index = int(index_match.group(1))
                    logger.debug(f"[WorkflowExecution][RefResolve]     Accessing array index [{index}]")
                    if isinstance(current, list) and 0 <= index < len(current):
                        current = current[index]
                        logger.debug(f"[WorkflowExecution][RefResolve]     Found index {index}, type: {type(current)}")
                    else:
                        logger.debug(f"[WorkflowExecution][RefResolve]     Array index {index} out of bounds in reference: {ref_path}")
                        return None

        logger.debug(f"[WorkflowExecution][RefResolve] Final resolved value type: {type(current)}")
        if isinstance(current, str):
            logger.debug(f"[WorkflowExecution][RefResolve] Final resolved string length: {len(current)}")
        elif current is None:
            logger.debug(f"[WorkflowExecution][RefResolve] Final resolved value is None")
        return current

    def _resolve_mapped_array_reference(self, ref_path: str, node_outputs: Dict[str, Any]) -> Any:
        """Resolve a '[]' reference to the MAPPED ARRAY value — no looping.

        'nodeId.items[].title' resolves nodeId.items to a list, then maps the
        remainder ('title') over each element, returning [el['title'], ...].
        Nested '[]' fan out into nested lists. Looping over items is done only
        by an explicit iteration node, never implicitly by a reference.
        """
        idx = ref_path.index('[]')
        source_path = ref_path[:idx].rstrip('.')
        remainder = ref_path[idx + 2:].lstrip('.')

        array_value = self._resolve_single_reference(source_path, node_outputs)
        if not isinstance(array_value, list):
            return None
        if not remainder:
            return array_value
        return [self._navigate_value(item, remainder) for item in array_value]

    def _navigate_value(self, value: Any, path: str) -> Any:
        """Navigate a resolved value through a dotted path.

        Supports nested '[]' (fan-out / map) and '[N]' numeric indices. Returns
        None for any missing key, out-of-range index, or type mismatch.
        """
        if '[]' in path:
            idx = path.index('[]')
            before = path[:idx].rstrip('.')
            after = path[idx + 2:].lstrip('.')
            arr = self._navigate_value(value, before) if before else value
            if not isinstance(arr, list):
                return None
            if not after:
                return arr
            return [self._navigate_value(item, after) for item in arr]

        current = value
        for part in path.split('.'):
            if not part:
                continue
            key_match = re.match(r'^([^\[]*)((?:\[\d+\])*)$', part)
            if not key_match:
                return None
            key_name = key_match.group(1)
            indices_str = key_match.group(2)
            if key_name:
                if isinstance(current, dict) and key_name in current:
                    current = current[key_name]
                else:
                    return None
            if indices_str:
                for index_match in re.finditer(r'\[(\d+)\]', indices_str):
                    index = int(index_match.group(1))
                    if isinstance(current, list) and 0 <= index < len(current):
                        current = current[index]
                    else:
                        return None
        return current

    async def _get_workflow_owner_id(self, workflow_id: str) -> Optional[str]:
        """Cached wrapper over utils.credentials.get_workflow_owner_id (owner is
        effectively immutable). Only SUCCESSFUL resolutions are cached — a transient
        None (DB blip) is re-tried rather than permanently disabling the fallback."""
        if workflow_id in self._workflow_owner_cache:
            return self._workflow_owner_cache[workflow_id]
        owner_id = await get_workflow_owner_id(await self.get_pool(), workflow_id)
        if owner_id:
            self._workflow_owner_cache[workflow_id] = owner_id
        return owner_id

    async def _resolve_credentials(
        self, node_config: Dict[str, Any], user_id: str, org_id: Optional[str] = None, workflow_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Resolve credential IDs to actual credential data and restructure node_config.

        Transforms flat node_config from frontend/database:
            { config_field1: "value1", credentialIds: { type: "cred-id" } }

        Into structured format expected by Pydantic models:
            { config: { config_field1: "value1" }, credentials: { actual_cred_data } }

        Also accepts already-structured config (for testing):
            { config: { ... }, credentials: { ... } }

        Args:
            node_config: Raw node config from frontend or pre-structured config
            user_id: UUID of the user executing the workflow
            org_id: Optional organization ID of the workflow (for credential access control)

        Returns:
            Restructured node config with resolved credentials
        """
        # Check if config is already in the expected nested format (e.g., from tests).
        # Only take the early-return path when there are NO credentialIds to resolve —
        # the frontend always uses the flat format with credentialIds, but also writes
        # a mirrored nested `config` sub-key via handleNodeDataUpdate.
        if 'config' in node_config and isinstance(node_config.get('config'), dict):
            # Flatten nested config, preserving outer fields (they're more recent
            # from MCP/UI and override inner values like 'operation').
            # This applies regardless of whether credentialIds are present — outer
            # fields (e.g. 'model' from the AI Agent visual dropdown) must always
            # override stale values in the mirrored nested config sub-object.
            inner = node_config['config']
            flat = dict(inner)
            for k, v in node_config.items():
                if k not in ('config', 'credentials'):
                    flat[k] = v
            if not node_config.get('credentialIds'):
                # No credentials to resolve — return early with merged config
                result = {
                    'config': {k: v for k, v in flat.items() if k not in ('credentialIds', 'credential_ids', 'credential_id', 'credentialId', '__state_input__')},
                    'credentials': node_config.get('credentials')
                }
                if '__state_input__' in node_config or '__state_input__' in flat:
                    result['__state_input__'] = node_config.get('__state_input__') or flat.get('__state_input__')
                return result
            # Fallback: check inner for credentialIds if outer doesn't have it
            if not flat.get('credentialIds') and isinstance(inner.get('credentialIds'), dict):
                flat['credentialIds'] = inner['credentialIds']
            node_config = flat
            # Fall through to normal flat processing below

        # Frontend format: flat config with credentialIds
        # { spreadsheet_id: "...", credentialIds: { google_sheets_oauth: "cred-uuid" } }
        credential_ids = extract_credential_ids(node_config)
        # Fallback for payloads where credential IDs are nested under mirrored config.
        if not credential_ids and isinstance(node_config.get('config'), dict):
            credential_ids = extract_credential_ids(node_config['config'])

        # Separate config fields from metadata (credentialIds and __state_input__)
        # __state_input__ is injected for state manager connections and must be preserved separately
        state_input = node_config.get('__state_input__')
        metadata_keys = {
            'credentialIds',
            'credential_ids',
            'credential_id',
            'credentialId',
            '__state_input__',
        }
        config_data = {k: v for k, v in node_config.items() if k not in metadata_keys}

        # Clean up config data: remove empty strings and convert them to None
        # This prevents Pydantic validation errors for optional fields.
        # Shared with the builder's validate_node_config so build-time
        # validation judges exactly what this path parses.
        from nodes.core.base import clean_config_empty_strings
        config_data = clean_config_empty_strings(config_data)

        # If no credentials required, return restructured config without credentials
        if not credential_ids:
            # Last-resort compatibility: some paths may provide fully expanded credentials
            # inline (instead of a credential ID map). If present, pass through.
            inline_credentials = node_config.get('credentials')
            if isinstance(inline_credentials, dict) and inline_credentials.get('access_token'):
                result = {
                    'config': config_data,
                    'credentials': inline_credentials,
                }
                if state_input:
                    result['__state_input__'] = state_input
                return result
            result = {
                'config': config_data,
                'credentials': None
            }
            if state_input:
                result['__state_input__'] = state_input
            return result

        credential_id = pick_credential_id(credential_ids)
        if not credential_id:
            # Non-primary types only (e.g. an agent with env vars but no model
            # credential): no primary credential to decrypt, but the map still
            # rides along so the node can resolve its secondary credentials.
            result = {
                'config': config_data,
                'credentials': None,
                'credentialIds': credential_ids,
            }
            if state_input:
                result['__state_input__'] = state_input
            return result

        # Fetch and decrypt via the SHARED owner-fallback policy (runner first,
        # then the workflow owner gated by workflow_authorized_credentials —
        # see utils.credentials.resolve_credential_with_owner_fallback for the
        # full rationale). Injects this handler's cached owner resolver.
        pool = await self.get_pool()
        credential_data = await resolve_credential_with_owner_fallback(
            credential_id,
            user_id,
            pool,
            org_id=org_id,
            workflow_id=workflow_id,
            get_owner_id=self._get_workflow_owner_id,
        )

        if not credential_data:
            raise ValueError(f"Failed to resolve credential {credential_id}")

        # Restructure into { config: {...}, credentials: {...}, credential_id: "..." }.
        # credentialIds rides along (ids only, no secrets) so a node can resolve
        # SECONDARY credentials itself — the handler decrypts exactly one, the
        # primary, and pick_credential_id can only ever return that one.
        result = {
            'config': config_data,
            'credentials': credential_data,
            'credential_id': credential_id,
            'credentialIds': credential_ids,
        }
        if state_input:
            result['__state_input__'] = state_input
        return result

    async def _execute_node(
        self,
        node: Dict[str, Any],
        node_outputs: Dict[str, Any],
        sid: str,
        user_id: str,
        workflow_id: str,
        conversation_id: Optional[str] = None,
        workflow_nodes: Optional[List[Dict[str, Any]]] = None,
        workflow_edges: Optional[List[Dict[str, Any]]] = None,
        workflow_org_id: Optional[str] = None,
        execution_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute a single node using the NodeFactory.

        Args:
            node: Node definition from workflow JSON
            node_outputs: Outputs from previously executed nodes
            sid: Session ID for sending events to client
            user_id: User ID for credential resolution
            workflow_id: UUID of the workflow for event routing
            conversation_id: Optional conversation ID for agent memory persistence (workflow chat)
            workflow_nodes: Optional list of all workflow nodes (for agent tool execution)
            workflow_edges: Optional list of all workflow edges (for agent tool execution)
            workflow_org_id: Optional organization ID of the workflow (for credential access control)

        Returns:
            Dict containing the node's output data

        Raises:
            ValueError: If node type is not registered
            Exception: If node execution fails
        """
        node_id = node['id']
        node_type = node.get('type', 'unknown')
        node_config = node.get('config', {})

        # Evaluate inline JS expressions ({{ $('node').x.split(',') }})
        # BEFORE plain-path reference resolution. Only `$`-accessor blocks are
        # evaluated here; legacy {{nodeId.path}} refs and literal {{ }} passthroughs
        # are left untouched for _resolve_references below. $json maps to the single
        # direct upstream output. A failed expression raises and surfaces as the
        # node's error via the try/except wrapping _execute_node.
        from utils.expression_evaluator import evaluate_expressions
        _incoming = [
            e.get('source') for e in (workflow_edges or [])
            if e.get('target') == node_id and e.get('source')
        ]
        _primary_input = node_outputs.get(_incoming[0]) if len(_incoming) == 1 else None
        # Feed the evaluated config into the resolver; keep `node_config` raw so the
        # state-injection path below still substring-matches its un-evaluated refs.
        evaluated_config = await evaluate_expressions(
            node_config, node_outputs, workflow_nodes=workflow_nodes, primary_input=_primary_input
        )

        # Resolve references in config values (e.g., {{nodeId.output.field}})
        # This allows config fields to reference outputs from upstream nodes
        resolved_config = self._resolve_references(evaluated_config, node_outputs)
        logger.debug(f"[WorkflowExecution] Node {node_id} config after reference resolution: {resolved_config}")

        # Integration node wired to an agent's bottom handle acts as a TOOL
        # PROVIDER: it publishes its allowlisted operations as node_op tools
        # instead of running one. Short-circuits BEFORE credential resolution
        # and NodeFactory because provider-mode config holds an operation
        # allowlist, not a runnable single-operation config.
        from nodes.agent.node_op_tools import is_node_op_provider, build_provider_output
        if is_node_op_provider(node_id, node_type, workflow_nodes, workflow_edges):
            output = build_provider_output(node_type, resolved_config)
            # Credential display name (no secret) — together with the node
            # label it's what lets the agent tell same-type providers apart.
            if output.get("credential_id"):
                pool = await self.get_pool()
                if pool:
                    output["credential_label"] = await get_credential_name(
                        pool, output["credential_id"]
                    )
            logger.info(
                f"[WorkflowExecution] Node {node_id} ({node_type}) is an agent tool provider "
                f"({len(output['allowed_operations'])} operation(s) allowlisted)"
            )
            return output

        # Second mirror of the runner's rehearsal skip, for callers that reach
        # _execute_node directly (iteration bodies). Raising is deliberate: a
        # send inside a loop body must fail the test loudly, never silently
        # reach a real account.
        from nodes.agent.rehearsal import is_rehearsal_conversation, rehearsal_excluded_node_types
        if is_rehearsal_conversation(conversation_id) and node_type in rehearsal_excluded_node_types():
            raise RuntimeError(
                f"{node_type} acts on a real account and is not executed during a test"
            )

        # State injection for serverless function nodes
        # When a State Manager is connected to the code node's bottom 'state' handle,
        # inject the state so the code can use and mutate it
        if node_type == 'automation-serverless-function' and workflow_edges:
            state_edge = next(
                (e for e in workflow_edges
                 if e.get('target') == node_id and e.get('targetHandle') == 'state'),
                None
            )
            if state_edge:
                state_source_id = state_edge.get('source')
                state_source_output = node_outputs.get(state_source_id, {})
                if isinstance(state_source_output, dict) and 'state' in state_source_output:
                    # Determine the variable name for state:
                    # Check if a function_input references this state manager (user chose the name)
                    # Fall back to 'state' if no function input references it
                    variable_name = 'state'
                    func_input_name = None

                    # Search original (pre-resolved) function_inputs for a reference to this state node
                    raw_func_inputs = node_config.get('function_inputs') or []
                    if not raw_func_inputs:
                        # Check nested config structures
                        inner = node_config.get('config', {})
                        if isinstance(inner, dict):
                            raw_func_inputs = inner.get('function_inputs') or inner.get('config', {}).get('function_inputs') or []

                    for fi in raw_func_inputs:
                        if isinstance(fi, dict):
                            val = fi.get('value', '')
                            if isinstance(val, str) and state_source_id in val:
                                func_input_name = fi.get('name')
                                break

                    if func_input_name:
                        variable_name = func_input_name
                        logger.info(f"[WorkflowExecution] Function input '{func_input_name}' references state manager {state_source_id}")

                    # Inject state info for the serverless function to use
                    resolved_config['__state_input__'] = {
                        'node_id': state_source_id,
                        'state': state_source_output['state'],
                        'variable_name': variable_name,
                        'from_function_input': func_input_name is not None,
                    }
                    logger.info(f"[WorkflowExecution] Injected state from {state_source_id} into {node_id} as '{variable_name}'")

        # Resolve credentials and restructure node_config (user_id passed from caller)
        resolved_node_data = await self._resolve_credentials(resolved_config, user_id, workflow_org_id, workflow_id)
        logger.debug(f"[WorkflowExecution] Node {node_id} config after credential resolution: {resolved_node_data.keys()}")

        # Create node instance using factory with sio/sid for event emission
        try:
            node_instance = NodeFactory.create_node(node_id, node_type, resolved_node_data, self.sio, sid, workflow_id, user_id, conversation_id, workflow_org_id, execution_id)
        except ValueError as e:
            logger.error(f"[WorkflowExecution] Failed to create node {node_id}: {e}")
            raise

        # For agent nodes, set workflow context for tool execution
        # This allows agents to execute downstream nodes when tools are called
        if node_type == 'agent' and workflow_nodes and workflow_edges:
            # Create a callback that executes the full downstream subgraph of a tool
            async def execute_tool_downstream(
                tool_node_id: str,
                arguments: Dict[str, Any],
                agent_node_id: str
            ) -> Dict[str, Any]:
                """
                Execute all downstream nodes of a tool with proper subgraph execution.

                This handles:
                - Finding all reachable downstream nodes (forward only)
                - Topological ordering
                - Concurrent execution with dependency coordination
                - Injecting tool arguments into node_outputs for reference resolution
                """
                # Find downstream nodes - forward traversal only, excluding the agent
                node_by_id = {n['id']: n for n in workflow_nodes}
                successors: Dict[str, List[str]] = {n['id']: [] for n in workflow_nodes}
                for edge in workflow_edges:
                    source, target = edge.get('source'), edge.get('target')
                    if source and target and source in successors:
                        successors[source].append(target)

                # BFS to find all reachable downstream nodes
                visited: Set[str] = set()
                queue = deque([tool_node_id])
                while queue:
                    nid = queue.popleft()
                    if nid in visited:
                        continue
                    visited.add(nid)
                    for succ in successors.get(nid, []):
                        if succ not in visited and succ != agent_node_id:
                            queue.append(succ)

                # Remove the tool node itself - we only want its downstream
                visited.discard(tool_node_id)

                if not visited:
                    logger.info(f"[WorkflowExecution] Tool {tool_node_id} has no downstream nodes")
                    return {
                        'success': True,
                        'message': "Tool executed (no downstream actions)"
                    }

                # Get downstream nodes and edges
                downstream_nodes = [n for n in workflow_nodes if n['id'] in visited]
                downstream_edges = [
                    e for e in workflow_edges
                    if e.get('source') in visited and e.get('target') in visited
                ]

                logger.info(f"[WorkflowExecution] Executing {len(downstream_nodes)} downstream nodes for tool {tool_node_id}")

                # Inject tool arguments as the tool node's output
                tool_output = {
                    'type': 'tool_call',
                    'tool_name': tool_node_id,
                    'arguments': arguments,
                    # Also expose arguments at top level for simpler reference syntax
                    **arguments
                }

                # Execute the downstream subgraph concurrently
                # Start with tool output pre-populated so references resolve
                initial_outputs = {tool_node_id: tool_output}

                nodes_executed, error_msg, downstream_outputs, _last_output_node_id = await self._execute_nodes_concurrent(
                    downstream_nodes,
                    downstream_edges,
                    sid,
                    user_id,
                    workflow_id,
                    max_concurrency=DEFAULT_MAX_CONCURRENCY,
                    conversation_id=conversation_id,
                    initial_outputs=initial_outputs,
                    workflow_org_id=workflow_org_id,
                    include_last_output_node_id=True,
                )

                if error_msg:
                    return {
                        'success': False,
                        'error': error_msg,
                        'nodes_executed': nodes_executed,
                        'downstream_results': downstream_outputs
                    }

                return {
                    'success': True,
                    'nodes_executed': nodes_executed,
                    'downstream_results': downstream_outputs
                }

            node_instance.set_workflow_context(execute_tool_downstream, workflow_nodes, workflow_edges)

        # Execute the node with outputs from upstream nodes. Wrap in caller_path_scope
        # so any OAuth refresh triggered by this node's _ensure_fresh_token is tagged
        # 'execute' in the oauth.refresh span / operator refresh audit audit row.
        logger.info(f"[WorkflowExecution] Executing {node_type} node {node_id}")
        from nodes.core.oauth_audit import caller_path_scope
        with caller_path_scope("execute"):
            output = await node_instance.run(node_outputs)

        # Track output schema for workflow builder hints. Awaited inline so the
        # curated suggested-references list is built on first observation of a
        # new shape (subsequent cache-hit observations skip the LLM call).
        node_operation = node_config.get('operation') or 'default'
        await track_node_schema(
            node_type=node_type,
            node_operation=node_operation,
            output=output,
            config=node_config,
        )

        # A poll trigger whose poll found no new data should not run downstream
        # nodes (e.g. an agent) — the empty envelope is not an event, and firing
        # downstream on it wastes runs/credits/agent turns. Applies to EVERY run
        # source: scheduled ticks (the cron POST is only a wake-up) and manual
        # runs alike — the old manual-run exemption delivered
        # {responses: [], new_response_count: 0} into an agent as a turn
        # (2026-08-04). Testing downstream without new data is what mockedOutput
        # is for. Signalled via an internal output key the concurrent runner
        # strips and acts on.
        #
        # The positive counterpart: a poll that DID emit fresh items is a FIRED
        # trigger regardless of run source. Stamp the in-run graph config so a
        # directly-wired agent delivers the emission as its trigger event
        # (_find_fired_trigger accepts _pollFired next to _triggerPayload) —
        # a manual run's fresh poll used to run the agent with no event at all
        # ("no payload was available", 2026-08-04). Stamping only ever happens
        # right after execute(), so preloaded outputs from previous runs can
        # never masquerade as a fresh event.
        if isinstance(output, dict):
            if node_instance.trigger_produced_no_event(output):
                output['_halt_downstream'] = True
            elif node_instance.trigger_emitted_event(output):
                node_config['_pollFired'] = True

        return output

    async def _persist_node_outputs(
        self,
        workflow_id: str,
        user_id: str,
        node_outputs: Dict[str, Any],
        execution_id: Optional[str] = None,
        executable_nodes: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Persist a run's node outputs + per-node terminal status to the CAS
        (the sole node-output store; large outputs are chunked there, no local
        cache markers). Set-variable nodes additionally mirror their computed
        assignments into workflows.workflow->variables so {{vars.X}} resolves in
        later / partial runs — the one JSONB write that survives the CAS cutover.

        Args:
            workflow_id: UUID of the workflow
            user_id: UUID of the user
            node_outputs: Dict mapping node_id to output data
            execution_id: UUID of the execution (CAS key)
            executable_nodes: List of node dicts with id/type (set-variable detect)
        """
        # Per-node last-run status built by the executor — pop so it's recorded
        # exactly once and the map doesn't leak. Stored as the CAS manifest's
        # last_run_status/error; the frontend hydrates it from node_statuses on load.
        node_statuses = self._execution_node_statuses.pop(execution_id, None) if execution_id else None
        if not node_outputs and not node_statuses:
            return

        try:
            pool = await self.get_pool()
            if not pool:
                logger.warning("[WorkflowExecution] No database pool available to persist outputs")
                return

            if execution_id:
                from utils.database_pool import get_native_pool
                from utils.node_outputs import persist_outputs
                # CAS persist needs a native asyncpg pool (transaction + executemany);
                await persist_outputs(
                    get_native_pool(), workflow_id=workflow_id, execution_id=execution_id,
                    node_outputs=node_outputs, node_statuses=node_statuses,
                )

            if node_outputs:
                await self._persist_set_variables(
                    pool, workflow_id, user_id, node_outputs, executable_nodes)
        except Exception as e:
            logger.error(f"[WorkflowExecution] Failed to persist node outputs: {e}", exc_info=True)

    async def _persist_set_variables(
        self,
        pool,
        workflow_id: str,
        user_id: str,
        node_outputs: Dict[str, Any],
        executable_nodes: Optional[List[Dict[str, Any]]],
    ) -> None:
        """Mirror set-variable nodes' computed assignments into
        workflows.workflow->variables so {{vars.X}} resolves in later runs and
        single-node runs where the set-variable node is not re-executed. This is
        the only workflow-JSONB write left after the CAS cutover; it touches just
        the `variables` key (jsonb_set), so it never clobbers concurrent edits."""
        import json
        import uuid as uuid_module

        set_var_ids = {
            n["id"] for n in (executable_nodes or []) if n.get("type") == "set-variable"
        }
        if not set_var_ids:
            return

        var_updates: Dict[str, Any] = {}
        for node_id in set_var_ids:
            output = node_outputs.get(node_id)
            if not isinstance(output, dict):
                continue
            assignments = output.get("assignments", [])
            # Backward compat: legacy single variable_name/value output
            if not assignments and output.get("variable_name"):
                assignments = [{"variable_name": output["variable_name"], "value": output.get("value")}]
            for assignment in assignments:
                var_name = assignment.get("variable_name", "")
                if var_name:
                    var_updates[var_name] = assignment.get("value")
        if not var_updates:
            return

        async with pool.acquire() as conn:
            access = await check_resource_access(conn, user_id, "workflow", workflow_id)
            if not access.has_access or access.permission not in (Permission.EDIT, Permission.OWNER):
                logger.warning(f"[WorkflowExecution] No edit access to workflow {workflow_id} for set-variable persistence")
                return
            await WorkflowRepo(pool).merge_workflow_variables(
                conn, uuid_module.UUID(workflow_id), var_updates,
            )
