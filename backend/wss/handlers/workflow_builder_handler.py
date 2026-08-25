"""
Workflow builder handler for AI-powered workflow editing.
Thin handler that delegates to AgenticBuilder and emits events via socket.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Dict, Callable, Any, ClassVar, Optional, List, Tuple

from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent, ConversationListEvent
from wss.receiver.client_events import (
    WorkflowBuilderEditRequest, WorkflowAutofillRequest,
    ListPendingBuilderRunsRequest,
    ListConversationsRequest, ResumeConversationRequest, DeleteConversationRequest,
    GetLatestConversationForWorkflowRequest, ListConversationsForAgentRequest,
)
from utils.database_pool import DatabasePoolMixin
from utils.credentials import get_workflow_owner_id, authorize_credentials_for_workflow
from coder.workflow.agentic import AgenticBuilder, AgenticBuilderConfig
from coder.workflow.agentic.commands import PlatformOps
from coder.workflow.agentic.name_generator import generate_workflow_name
from coder.workflow.workflow_ops import preserve_existing_credentials
from utils.cancellation import (
    CancelScope,
    register_builder_scope,
    unregister_builder_scope,
)
from coder.workflow import resume_checkpoint
from coder.workflow.builder_events import BuilderStreamEvent
from coder.workflow.agentic.builder import NODE_METADATA_KEYS, USER_INPUT_MARKER
from coder.workflow.agentic.state import PendingAsk
from coder.workflow.graph_state import GraphState



from utils.slack import send_activity_notification_background, extract_user_name
from utils.analytics import log_activity_background
from utils.analytics_events import Events
from repositories.workflow import WorkflowRepo
from repositories.organization import OrgRepo
from repositories.conversation import ConversationRepo

logger = logging.getLogger(__name__)

# How often the epoch-fence watch task polls Redis for supersession. One GET per
# interval per run — coarse enough to be cheap, fine enough that a superseded run
# stands down within a few seconds of the loop freeing up.
EPOCH_WATCH_INTERVAL_S = 4


def merge_builder_run_graph(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    graph_state: Optional[GraphState],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Overlay the builder's in-memory graph state onto the DB workflow
    snapshot and normalize edges for the execution handler (graph state uses
    sourceId/targetId, the executor expects source/target).

    The frontend auto-save is async, so the DB may lack nodes, config, or
    credentials the brain added this turn. Edge HANDLES must survive both the
    overlay and the normalization: targetHandle 'bottom' is what makes a node
    a tool provider (the executor's reachable-set backfill and AgentNode's
    edge scoping both key on it) and 'state' wires state nodes. Dropping it
    ran a freshly wired agent toolless while describe_workflow showed its
    providers (cleanup_agent, 2026-08-04)."""
    if graph_state is not None:
        db_node_map = {n.get("id"): n for n in nodes}
        for ns in graph_state.nodes.values():
            exec_config = ns.to_execution_config()
            if ns.id not in db_node_map:
                # New node not in DB yet
                nodes.append({"id": ns.id, "type": ns.type, "config": exec_config})
            else:
                # Existing node — merge graph state over DB config
                db_node = db_node_map[ns.id]
                db_config = db_node.get("config", {})
                merged = {**db_config, **exec_config}
                # Deep-merge credentialIds (additive — preserve DB creds
                # for other providers while adding new ones from graph state)
                db_cred_ids = db_config.get("credentialIds", {})
                gs_cred_ids = (ns.config or {}).get("credentialIds", {})
                if db_cred_ids or gs_cred_ids:
                    merged["credentialIds"] = {**db_cred_ids, **gs_cred_ids}
                db_node["config"] = merged
        db_edge_ids = {e.get("id") for e in edges}
        for es in graph_state.edges.values():
            if es.id not in db_edge_ids:
                edges.append(es.to_dict())

    normalized_edges = []
    for e in edges:
        ne = {
            "id": e.get("id"),
            "source": e.get("source") or e.get("sourceId"),
            "target": e.get("target") or e.get("targetId"),
        }
        if e.get("sourceHandle"):
            ne["sourceHandle"] = e["sourceHandle"]
        if e.get("targetHandle"):
            ne["targetHandle"] = e["targetHandle"]
        normalized_edges.append(ne)
    return nodes, normalized_edges


class WorkflowBuilderHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for AI-powered workflow editing via AgenticBuilder."""

    # Map active gen_id → originating ChatMessageRequest.request_id so that
    # text_chunk/status frames (which only know gen_id) can echo the
    # originating request_id for FE-side latency correlation. Bounded FIFO
    # to keep the map from growing if a gen never reaches terminal (process
    # crash, lost cancel, etc.). Cleared in _emit_active_gen_terminal.
    _GEN_REQUEST_ID_CAP: ClassVar[int] = 256

    def __init__(self, sio):
        super().__init__(sio)
        self._gen_to_request_id: Dict[str, str] = {}

    @staticmethod
    def _is_valid_uuid(value: str) -> bool:
        try:
            uuid.UUID(value)
            return True
        except (ValueError, AttributeError):
            return False


    def _create_platform_ops(self, user_id: str, sid: str, workflow_id: str | None = None) -> PlatformOps:
        """Create platform ops implementation with DB and socket access for the agentic builder."""
        handler = self
        wf_id = workflow_id  # Captured in closure — safe for concurrent edits

        class _HandlerPlatformOps:
            # Mutable reference to the builder's graph state.
            # Set by the builder after initialization so run_node can use
            # in-memory nodes that haven't been saved to the DB yet.
            _graph_state = None

            async def get_node_output(self, node_id: str) -> Optional[Any]:
                """Return {output, created_at} or None (latest output from CAS)."""
                pool = await handler.get_pool()
                if not pool or not wf_id:
                    return None
                from utils.node_outputs import latest_output_meta
                return await latest_output_meta(pool, wf_id, node_id)

            async def get_nodes_with_output(self, node_ids: List[str]) -> set:
                pool = await handler.get_pool()
                if not pool or not wf_id:
                    return set()
                from utils.node_outputs import nodes_with_output
                return await nodes_with_output(pool, wf_id, node_ids)

            async def fetch_credential_health(self, credential_ids: List[str]) -> Dict[str, Any]:
                pool = await handler.get_pool()
                if not pool:
                    return {}
                from utils.credential_health import fetch_credential_health_for_ids
                return await fetch_credential_health_for_ids(pool, credential_ids)


            async def run_node(self, node_id: str, include_downstream: bool = False) -> Dict[str, Any]:
                pool = await handler.get_pool()
                if not pool:
                    return {"error": "Database not available"}
                if not wf_id:
                    return {"error": "No workflow context"}
                try:
                    # Load saved workflow from DB as baseline
                    async with pool.acquire() as conn:
                        row = await WorkflowRepo(pool).get_workflow_for_builder_run_node(
                            conn, uuid.UUID(wf_id), uuid.UUID(user_id),
                        )
                    if not row:
                        return {"error": "Workflow not found"}
                    wf_data = row["workflow"] if isinstance(row["workflow"], dict) else json.loads(row["workflow"])
                    nodes, normalized_edges = merge_builder_run_graph(
                        wf_data.get("nodes", []),
                        wf_data.get("edges", []),
                        self._graph_state,
                    )

                    # Find target node
                    target = next((n for n in nodes if n.get("id") == node_id), None)
                    if not target:
                        return {"error": f"Node {node_id} not found in workflow"}

                    # Use the existing execution handler with start_node_id + forward_only
                    # This reuses the same "run from here" logic the frontend uses
                    from wss.receiver.client_events import WorkflowExecuteRequest
                    from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
                    exec_req = WorkflowExecuteRequest(
                        request_id=f"brain_exec_{uuid.uuid4()}",
                        workflow_id=wf_id,
                        nodes=nodes,
                        edges=normalized_edges,
                        start_node_id=node_id,
                        forward_only=True,
                    )
                    exec_handler = WorkflowExecutionHandler(handler.sio)
                    await exec_handler.handle_execute(sid, exec_req, caller_user_id=user_id)

                    # Check execution result — handle_execute runs to completion,
                    # so we can read the outcome from the DB immediately.
                    from utils.node_outputs import latest_output

                    async with pool.acquire() as conn:
                        exec_row = await WorkflowRepo(pool).get_latest_finished_execution_status(
                            conn, uuid.UUID(wf_id),
                        )

                    output = await latest_output(pool, wf_id, node_id)

                    # Target node's own output indicates an error → that's the real failure
                    if isinstance(output, dict) and output.get("error"):
                        return {"error": output["error"], "failed_node": node_id}

                    # Target produced output → success, regardless of downstream failures.
                    # forward_only=True means the executor runs the target *and* downstream;
                    # when include_downstream=False, downstream failures are not the caller's
                    # concern as long as the target itself succeeded.
                    if output is not None:
                        if include_downstream:
                            return {"success": True}
                        return {"success": True, "output": output}

                    # Target produced no output. Distinguish "target failed" vs
                    # "a different node failed and target never ran".
                    if exec_row and exec_row["status"] == "error":
                        err_msg = exec_row["error"] or "Execution failed"
                        target_prefix = f"Node {node_id} failed:"
                        if err_msg.startswith(target_prefix):
                            return {"error": err_msg, "failed_node": node_id}
                        # Error is from a different node — surface that explicitly so
                        # the brain doesn't think the target failed.
                        return {
                            "error": err_msg,
                            "failed_node": "other",
                            "target_node": node_id,
                        }

                    return {"error": f"Node {node_id} produced no output. Check that credentials are configured and the node config is valid."}
                except Exception as e:
                    logger.error(f"[PlatformOps] run_node error: {e}", exc_info=True)
                    return {"error": str(e)}

            async def search_credentials(self, credential_type: str, query: str, limit: int) -> List[Dict[str, Any]]:
                pool = await handler.get_pool()
                if not pool:
                    return []
                async with pool.acquire() as conn:
                    from wss.handlers.workflow_handler import get_user_org_context
                    org_id = await get_user_org_context(conn, user_id)
                    conditions = [
                        "(c.owner_id = $1 OR us.id IS NOT NULL OR ($2::uuid IS NOT NULL AND os.id IS NOT NULL))"
                    ]
                    params: list = [uuid.UUID(user_id), uuid.UUID(org_id) if org_id else None]
                    idx = 3
                    if credential_type:
                        conditions.append(f"c.credential_type = ${idx}")
                        params.append(credential_type)
                        idx += 1
                    if query:
                        conditions.append(f"(c.name ILIKE ${idx} OR c.metadata->>'email' ILIKE ${idx})")
                        params.append(f"%{query}%")
                        idx += 1
                    sql = f"""
                        SELECT DISTINCT ON (c.id) c.id, c.name, c.credential_type, c.metadata
                        FROM credentials c
                        LEFT JOIN resource_shares us
                            ON us.resource_type = 'credential' AND us.resource_id = c.id
                            AND us.target_type = 'user' AND us.target_user_id = $1
                        LEFT JOIN resource_shares os
                            ON os.resource_type = 'credential' AND os.resource_id = c.id
                            AND os.target_type = 'organization' AND os.target_org_id = $2
                        WHERE {' AND '.join(conditions)}
                        ORDER BY c.id, c.created_at DESC
                        LIMIT {min(limit, 50)}
                    """
                    rows = await conn.fetch(sql, *params)
                    return [
                        {"id": str(r["id"]), "name": r["name"], "credential_type": r["credential_type"], "metadata": r["metadata"] or {}}
                        for r in rows
                    ]

            async def authorize_credentials(self, credential_ids: List[str]) -> None:
                if not wf_id or not credential_ids:
                    return
                pool = await handler.get_pool()
                if not pool:
                    return
                # Owner-gated: only authorize when the builder actor owns the workflow.
                owner_id = await get_workflow_owner_id(pool, wf_id)
                if not owner_id or str(owner_id) != str(user_id):
                    return
                async with pool.acquire() as conn:
                    await authorize_credentials_for_workflow(conn, wf_id, owner_id, credential_ids)

            async def _settings_content_write(self, mutate) -> Dict[str, Any]:
                """Owner-gated read-modify-write of one workflows.settings key.

                `mutate(settings) -> (key, value)` computes the merged content;
                update_workflow_dynamic's top-level JSONB merge replaces only
                that key, so variables and rehearsal authoring can't clobber
                each other. Owner-only mirrors the socket path's settings gate
                (workflow:update), which the builder path otherwise bypasses.
                """
                if not wf_id:
                    return {"error": "No workflow context"}
                pool = await handler.get_pool()
                if not pool:
                    return {"error": "Database not available"}
                owner_id = await get_workflow_owner_id(pool, wf_id)
                if not owner_id or str(owner_id) != str(user_id):
                    return {"error": "Only the workflow owner can change workflow settings"}
                repo = WorkflowRepo(pool)
                async with pool.acquire() as conn:
                    row = await repo.get_workflow_data_and_settings(conn, uuid.UUID(wf_id))
                    if not row:
                        return {"error": "Workflow not found"}
                    settings = row["settings"]
                    if isinstance(settings, str):
                        settings = json.loads(settings)
                    key, value, extra = mutate(settings if isinstance(settings, dict) else {})
                    await repo.update_workflow_dynamic(
                        conn, uuid.UUID(wf_id), settings={key: value},
                    )
                return {"success": True, **extra}

            async def upsert_variable_definitions(self, definitions: List[Dict[str, Any]]) -> Dict[str, Any]:
                from coder.workflow.workflow_ops import upsert_variable_definitions

                def mutate(settings: Dict[str, Any]):
                    merged = upsert_variable_definitions(
                        settings.get("variable_definitions"), definitions,
                    )
                    return "variable_definitions", merged, {}

                try:
                    return await self._settings_content_write(mutate)
                except Exception as e:
                    logger.error(f"[PlatformOps] upsert_variable_definitions error: {e}", exc_info=True)
                    return {"error": str(e)}

            async def add_rehearsal_run(
                self, node_type: str, name: str, lead: Dict[str, Any], base_key: str,
            ) -> Dict[str, Any]:
                from coder.workflow.workflow_ops import append_rehearsal_run

                def mutate(settings: Dict[str, Any]):
                    authoring, slug = append_rehearsal_run(
                        settings.get("rehearsal_authoring"), node_type, name, lead, base_key,
                    )
                    return "rehearsal_authoring", authoring, {"slug": slug}

                try:
                    return await self._settings_content_write(mutate)
                except Exception as e:
                    logger.error(f"[PlatformOps] add_rehearsal_run error: {e}", exc_info=True)
                    return {"error": str(e)}

            async def list_workflows(self, query: str, limit: int) -> List[Dict[str, Any]]:
                pool = await handler.get_pool()
                if not pool:
                    return []
                async with pool.acquire() as conn:
                    from wss.handlers.workflow_handler import get_user_org_context
                    org_id = await get_user_org_context(conn, user_id)
                    rows = await WorkflowRepo(pool).list_workflows_builder(
                        conn,
                        user_id=uuid.UUID(user_id),
                        organization_id=uuid.UUID(org_id) if org_id else None,
                        query=query, limit=limit,
                    )
                    return [
                        {
                            "id": str(r["id"]),
                            "name": r["name"],
                            "description": r["description"] or "",
                            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                        }
                        for r in rows
                    ]

            async def open_workflow(self, workflow_id: str) -> Dict[str, Any]:
                if not handler._is_valid_uuid(workflow_id):
                    return {"error": f"Invalid workflow ID: '{workflow_id}'. Use <list_workflows> to find the correct ID."}
                pool = await handler.get_pool()
                if not pool:
                    return {"error": "Database not available"}
                async with pool.acquire() as conn:
                    from utils.access_control import check_resource_access
                    access = await check_resource_access(conn, user_id, "workflow", workflow_id)
                    if not access.has_access:
                        return {"error": f"Workflow not found or access denied: {workflow_id}"}
                return {"success": True, "workflow_id": workflow_id}

            async def create_workflow(self, name: str, description: str) -> Dict[str, Any]:
                pool = await handler.get_pool()
                if not pool:
                    return {"error": "Database not available"}
                async with pool.acquire() as conn:
                    from wss.handlers.workflow_handler import get_user_org_context
                    from billing.plan_limits import check_workflow_limit, get_user_tier_from_db
                    org_id = await get_user_org_context(conn, user_id)
                    user_tier = await get_user_tier_from_db(conn, user_id)
                    can_create, limit_error = await check_workflow_limit(conn, user_id, user_tier)
                    if not can_create:
                        return {"error": limit_error}
                    repo = WorkflowRepo(pool)
                    workflow_id = await repo.create_workflow_builder(
                        conn,
                        name=name,
                        description=description,
                        owner_id=uuid.UUID(user_id),
                        organization_id=uuid.UUID(org_id) if org_id else None,
                        workflow_data={"nodes": [], "edges": []},
                    )
                    wf_id_str = str(workflow_id)
                    # Share with org if in org context
                    if org_id:
                        await repo.insert_workflow_org_share(
                            conn,
                            workflow_id=workflow_id,
                            organization_id=uuid.UUID(org_id),
                            permission='edit',
                            shared_by=uuid.UUID(user_id),
                        )
                return {"success": True, "workflow_id": wf_id_str, "name": name}

            async def list_folders(self) -> List[Dict[str, Any]]:
                pool = await handler.get_pool()
                if not pool:
                    return []
                async with pool.acquire() as conn:
                    from wss.handlers.workflow_handler import get_user_org_context
                    org_id = await get_user_org_context(conn, user_id)
                    repo = WorkflowRepo(pool)
                    if org_id:
                        rows = await repo.list_builder_folders_org(
                            conn, uuid.UUID(org_id), uuid.UUID(user_id),
                        )
                    else:
                        rows = await repo.list_builder_folders_personal(
                            conn, uuid.UUID(user_id),
                        )
                    return [
                        {
                            "id": str(r["id"]),
                            "name": r["name"],
                            "parent_folder_id": str(r["parent_folder_id"]) if r["parent_folder_id"] else None,
                            "workflow_count": r["workflow_count"],
                        }
                        for r in rows
                    ]

            async def create_folder(self, name: str, parent_folder_id=None) -> Dict[str, Any]:
                pool = await handler.get_pool()
                if not pool:
                    return {"error": "Database not available"}
                async with pool.acquire() as conn:
                    from wss.handlers.workflow_handler import get_user_org_context
                    org_id = await get_user_org_context(conn, user_id)
                    repo = WorkflowRepo(pool)
                    if parent_folder_id:
                        has_access = await OrgRepo(pool).can_access_folder(
                            conn, uuid.UUID(user_id), uuid.UUID(parent_folder_id),
                        )
                        if not has_access:
                            return {"error": "Parent folder not found or access denied"}
                    folder_id = await repo.insert_folder_builder(
                        conn,
                        name=name,
                        owner_id=uuid.UUID(user_id),
                        organization_id=uuid.UUID(org_id) if org_id else None,
                        parent_folder_id=uuid.UUID(parent_folder_id) if parent_folder_id else None,
                    )
                return {"success": True, "folder_id": str(folder_id), "name": name}

            async def delete_folder(self, folder_id: str) -> Dict[str, Any]:
                if not handler._is_valid_uuid(folder_id):
                    return {"error": f"Invalid folder ID: '{folder_id}'. Use <list_folders> to find the correct ID."}
                pool = await handler.get_pool()
                if not pool:
                    return {"error": "Database not available"}
                async with pool.acquire() as conn:
                    repo = WorkflowRepo(pool)
                    row = await OrgRepo(pool).get_folder_owner_and_parent(
                        conn, uuid.UUID(folder_id),
                    )
                    if not row or str(row["owner_id"]) != user_id:
                        return {"error": "Folder not found or not owned by you"}
                    # Move workflows to parent folder, then delete
                    await repo.hoist_workflows_to_parent(
                        conn, uuid.UUID(folder_id), row["parent_folder_id"],
                    )
                    await repo.delete_folder(conn, uuid.UUID(folder_id))
                return {"success": True}

            async def move_workflow(self, workflow_id: str, folder_id=None) -> Dict[str, Any]:
                if not handler._is_valid_uuid(workflow_id):
                    return {"error": f"Invalid workflow ID: '{workflow_id}'. Use <list_workflows> to find the correct ID."}
                if folder_id and not handler._is_valid_uuid(folder_id):
                    return {"error": f"Invalid folder ID: '{folder_id}'. Use <list_folders> to find the correct ID."}
                pool = await handler.get_pool()
                if not pool:
                    return {"error": "Database not available"}
                async with pool.acquire() as conn:
                    from utils.access_control import check_resource_access
                    access = await check_resource_access(conn, user_id, "workflow", workflow_id)
                    if not access.has_access:
                        return {"error": "Workflow not found or access denied"}
                    repo = WorkflowRepo(pool)
                    if folder_id:
                        has_access = await OrgRepo(pool).can_access_folder(
                            conn, uuid.UUID(user_id), uuid.UUID(folder_id),
                        )
                        if not has_access:
                            return {"error": "Target folder not found or access denied"}
                    await repo.set_workflow_folder(
                        conn,
                        uuid.UUID(workflow_id),
                        uuid.UUID(folder_id) if folder_id else None,
                    )
                return {"success": True}

        return _HandlerPlatformOps()

    async def _generate_workflow_name_background(
        self,
        sid: str,
        user_id: str,
        workflow_id: str,
        prompt: str,
        placeholder_only: bool = False,
    ) -> None:
        """
        Generate a short name + description for a freshly-created empty workflow
        using a cheap LLM call, persist to the workflows row, and broadcast the
        rename to the initiating client.

        Fire-and-forget — any failure stays silent so the placeholder name
        (prompt slice written by WorkflowCreator) remains in place.

        placeholder_only: retry path for later turns (the first turn's naming
        call can blow its LLM budget and fail silently, stranding "Untitled"
        forever — a 2026-07 workflow-naming incident). The rename then only lands if
        the name is still a default placeholder, so a user-typed name wins.
        """
        try:
            result = await generate_workflow_name(prompt)
            if not result:
                return
            name, description = result

            pool = await self.get_pool()
            if not pool:
                logger.warning("[WorkflowBuilder:name] No DB pool; skipping rename")
                return

            row = await WorkflowRepo(pool).rename_workflow_if_owner(
                workflow_id, name, description, user_id,
                placeholder_only=placeholder_only,
            )
            if not row:
                logger.info(f"[WorkflowBuilder:name] No ownership row for {workflow_id}; skipping rename")
                return

            logger.info(f"[WorkflowBuilder:name] Renamed {workflow_id} → '{name}'")
            await self.sio.emit(
                'workflow:name_generated',
                {
                    'workflow_id': workflow_id,
                    'name': name,
                    'description': description,
                },
                to=sid,
            )
        except Exception as e:
            logger.warning(f"[WorkflowBuilder:name] Background rename failed for {workflow_id}: {e}")

    def _summarize_graph(self, graph: Dict[str, Any]) -> Dict[str, Any]:
        """Create a summary of a workflow graph for analytics storage."""
        nodes = graph.get('nodes', [])
        edges = graph.get('edges', [])

        # Extract node types
        node_types = []
        for node in nodes:
            node_type = node.get('type') or node.get('data', {}).get('type')
            if node_type:
                node_types.append(node_type)

        return {
            'node_count': len(nodes),
            'edge_count': len(edges),
            'node_types': list(set(node_types)),  # Deduplicate
        }

    async def _store_builder_usage_event(
        self,
        user_id: str,
        provider_cost: float,
        total_tokens: int,
        model: Optional[str],
        generation_id: str,
        sid: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> None:
        """Record one builder turn through the installation's usage-policy seam.

        The operator policy owns any adjustment and attribution. A missing
        value is skipped, while zero is retained as an auditable event.
        """
        try:
            from decimal import Decimal
            from billing.markup import apply_ai_builder_markup
            from billing.schema import UsageEventData
            from billing.usage_tracker import usage_tracker

            # Record-everything policy: only skip when the caller couldn't
            # determine a cost at all (None). A genuinely-zero cost still
            # gets a row — useful for audit ("this builder turn happened,
            # provider just didn't charge for it") and avoids the appearance
            # of silently dropping events. Negative is a data bug; log and
            # skip to keep the SUM safe.
            if provider_cost is None:
                return
            if provider_cost < 0:
                logger.warning(
                    f"[WorkflowBuilder] Negative provider_cost for user={user_id}, "
                    f"generation={generation_id}: {provider_cost}; skipping"
                )
                return

            total_cost = apply_ai_builder_markup(Decimal(str(provider_cost)))
            # Use a stable, provider-neutral subtype for aggregate reporting.
            event = UsageEventData(
                user_id=user_id,
                total_cost=total_cost,
                usage_type='ai_builder',
                usage_subtype='builder/turn',
                quantity=Decimal(str(total_tokens or 0)),
                unit_type='tokens',
                user_resource=False,  # installation-provided credentials
                organization_id=organization_id,
                metadata={
                    'generation_id': generation_id,
                    'model': model or 'unknown',
                },
            )
            await usage_tracker.track_usage_event(event, sio=self.sio, sid=sid)
            logger.info(
                f"[WorkflowBuilder] Recorded builder usage: user={user_id}, "
                f"value={total_cost:.6f}, model={model}"
            )
        except Exception as e:
            logger.warning(f"[WorkflowBuilder] Failed to record builder usage event: {e}")


    # Event types that represent graph mutations (for editSegments accumulation)
    _GRAPH_EVENT_TYPES = frozenset({
        'node_added', 'node_removed', 'node_updated', 'edge_added', 'edge_removed',
        'node_processing_start', 'node_operation_selected', 'node_config_filling',
    })

    # Subset of graph events to bridge to mcp:builder_event for useMCPBuilderEvents
    _MCP_BRIDGE_EVENT_TYPES = frozenset({
        'node_added', 'node_removed', 'node_updated', 'edge_added', 'edge_removed',
        'node_processing_start',
    })


    @staticmethod
    def _to_mcp_event(event) -> Optional[Dict[str, Any]]:
        """Convert an BuilderStreamEvent to mcp:builder_event payload.

        Keeps event names matching useMCPBuilderEvents expectations:
        - node_added → node_start (node creation with type/position)
        - node_updated → node_updated (config merge via applyNodeUpdate)
        - Others pass through with minimal field normalization.
        """
        t = event.type
        d = event.data
        if t == 'node_added':
            node = d.get('node', {})
            return {'event_type': 'node_start', 'data': {'node': {
                'id': node.get('id'),
                'type': node.get('type'),
                'label': node.get('label', ''),
                'goal': node.get('goal', ''),
                'operation': node.get('operation'),
                'position': node.get('position'),
                **(node.get('config') or {}),
            }}}
        if t == 'node_updated':
            # The FE consumer (useMCPBuilderEvents) expects a flat config blob
            # and routes top-level metadata (credentialIds, disabled, …) via
            # rawConfigToPayload. The agentic builder's _build_node_update_data
            # splits those metadata keys out to the top level of `d`, so we
            # re-flatten them into config here — otherwise <set_credentials>,
            # <disable_node>, <mock_node>, label/goal edits silently disappear
            # on the wire and never reach the canvas.
            config = dict(d.get('config') or {})
            if d.get('operation'):
                config['operation'] = d['operation']
            for key in NODE_METADATA_KEYS:
                if key in d:
                    config[key] = d[key]
            return {'event_type': 'node_updated', 'data': {
                'nodeId': d.get('nodeId'),
                'config': config,
            }}
        if t == 'node_removed':
            return {'event_type': 'node_removed', 'data': {'nodeId': d.get('nodeId')}}
        if t == 'edge_added':
            edge = d.get('edge', {})
            return {'event_type': 'edge_added', 'data': {'edge': {
                'id': edge.get('id'),
                'source': edge.get('sourceId') or edge.get('source'),
                'target': edge.get('targetId') or edge.get('target'),
                **(({'sourceHandle': edge['sourceHandle']} if edge.get('sourceHandle') else {})),
                **(({'targetHandle': edge['targetHandle']} if edge.get('targetHandle') else {})),
            }}}
        if t == 'edge_removed':
            return {'event_type': 'edge_removed', 'data': {'edgeId': d.get('edgeId')}}
        if t == 'node_processing_start':
            return {'event_type': 'node_processing_start', 'data': {'nodeId': d.get('nodeId')}}
        return None

    async def _load_conversation_history(self, conversation_id: str, user_id: str) -> List[Dict[str, str]]:
        """Load prior conversation turns and build LLM message history.

        Uses raw LLM messages (with XML commands and execution results) when
        available, falling back to summarized edit_segments for older conversations.
        """
        repo = ConversationRepo(await self.get_pool())
        events = await repo.get_events_active(conversation_id, user_id)
        if events is None or not events:
            return []

        history: List[Dict[str, str]] = []
        for msg in events:
            role = msg.get("role")
            if role == "user":
                history.append({"role": "user", "content": msg.get("message", "")})
            elif role == "assistant":
                # Prefer raw LLM messages (includes XML commands + execution results)
                llm_messages = msg.get("llm_messages")
                if llm_messages:
                    history.extend(llm_messages)
                else:
                    # Fallback: summarize edit_segments for older conversations
                    summary = self._summarize_assistant_turn(msg)
                    if summary:
                        history.append({"role": "assistant", "content": summary})
        return history

    @staticmethod
    def _summarize_assistant_turn(msg: Dict[str, Any]) -> str:
        """Convert stored assistant message (with edit_segments) into compact text for LLM context."""
        parts: List[str] = []

        # Include top-level message text if present
        if msg.get("message"):
            parts.append(msg["message"])

        segments = msg.get("edit_segments", [])
        for segment in segments:
            if segment.get("type") == "text" and segment.get("text"):
                parts.append(segment["text"])
            elif segment.get("type") == "events":
                for event in segment.get("events", []):
                    event_type = event.get("type", "")
                    if event_type == "node_added":
                        label = event.get("nodeLabel") or event.get("node", {}).get("label", "")
                        ntype = event.get("nodeType") or event.get("node", {}).get("type", "")
                        parts.append(f"[Added node: {label} ({ntype})]")
                    elif event_type == "node_removed":
                        parts.append(f"[Removed node: {event.get('nodeId', '')}]")
                    elif event_type == "node_updated":
                        parts.append(f"[Updated node: {event.get('nodeId', '')}]")
                    elif event_type == "edge_added":
                        parts.append(f"[Added edge: {event.get('sourceNodeLabel', '')} → {event.get('targetNodeLabel', '')}]")
                    elif event_type == "edge_removed":
                        parts.append(f"[Removed edge: {event.get('edgeId', '')}]")

        return "\n".join(parts)

    async def _ensure_conversation_row(
        self,
        conversation_id: str,
        user_id: str,
        prompt: str,
        workflow_id: Optional[str] = None,
    ) -> None:
        """
        Guarantee a conversations-table row exists for this edit so paused
        runs (which never reach _save_conversation in _finalize_run_complete)
        still show up in the chat history dropdown. Idempotent: if a row
        already exists, only bumps last_activity — preserves events/title.

        workflow_id is what `conversation:get_latest_for_workflow` keys off, so
        it's important to stamp it on first insert. ON CONFLICT preserves an
        existing value (we never want to overwrite with NULL); the COALESCE
        guards the rare case where an earlier insert without workflow_id is
        upgraded by a later edit that knows it.
        """
        repo = ConversationRepo(await self.get_pool())
        await repo.ensure_stub(conversation_id, user_id, prompt, workflow_id)

    @staticmethod
    def _is_pending_assistant(msg: Dict[str, Any]) -> bool:
        """True iff an assistant message has an unanswered pending_ask field.

        With <ask/> as a turn boundary, this is the only "non-final" assistant
        shape: the turn it produced is complete (it has llm_messages, edit_segments,
        edit_steps), but the conversation is awaiting a user answer to the ask.
        Cancelled assistants are also final and never get replaced.
        """
        return (
            msg.get("role") == "assistant"
            and msg.get("pending_ask") is not None
        )

    def _strip_trailing_pending_pair(
        self,
        events: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Strip the trailing [user, assistant_with_pending_ask] pair so the
        next save (resumed turn that completed the ask) replaces it instead
        of stacking on top.
        """
        if len(events) < 2:
            return events
        if (
            events[-2].get("role") == "user"
            and self._is_pending_assistant(events[-1])
        ):
            return events[:-2]
        return events

    async def _read_conversation_events(
        self, conversation_id: str, user_id: str,
    ) -> List[Dict[str, Any]]:
        """Read the events JSONB array for a conversation, normalized to a list."""
        repo = ConversationRepo(await self.get_pool())
        return await repo.read_events(conversation_id, user_id)

    async def _save_conversation(
        self,
        conversation_id: str,
        user_id: str,
        new_messages: List[Dict[str, Any]],
        *,
        title: Optional[str] = None,
        workflow_id: Optional[str] = None,
        replace_pending: bool = False,
        cost_delta: float = 0.0,
        token_delta: int = 0,
        turn_delta: int = 0,
    ) -> List[Dict[str, Any]]:
        """Single persistence path for ALL turn outcomes — complete, paused, cancelled.

        Appends `new_messages` to events; when `replace_pending=True`, strips
        the trailing [user, assistant_with_pending_ask] pair first (used when
        a paused turn is being resumed and the new completed turn replaces
        the snapshot).

        Maintains the denormalized `pending_ask` column on conversations so
        `get_latest_for_workflow` and `list_pending` don't need to peek into
        the events JSONB array.

        Bumps billing accumulators by the supplied per-turn deltas (cost,
        tokens, turn_count). Caller passes the delta for THIS turn only — the
        SQL adds it to the existing column value, so cross-resume totals
        accumulate naturally without us round-tripping the row.
        """
        preview = ""
        for msg in new_messages:
            if msg.get("role") == "user" and msg.get("message"):
                preview = msg["message"][:100]
                break
        title = title or preview[:50] or "Workflow Edit"

        # The trailing assistant decides whether the conversation is paused.
        new_pending_ask = None
        for msg in reversed(new_messages):
            if msg.get("role") == "assistant":
                new_pending_ask = msg.get("pending_ask")
                break

        existing = await self._read_conversation_events(conversation_id, user_id)
        if replace_pending:
            # If the trailing pair is paused-on-ask AND the incoming
            # messages match its user prompt, MERGE the new assistant's
            # content into the prior assistant instead of replacing.
            # This is what keeps Skip All / credential-submit feeling
            # like the same bubble continuing rather than a fresh turn.
            #
            # Falls back to plain replace when the new prompt doesn't
            # match (e.g. the user submitted a different prompt while a
            # paused conv was open — that's a real new turn).
            if (len(existing) >= 2
                and existing[-2].get("role") == "user"
                and self._is_pending_assistant(existing[-1])
                and len(new_messages) >= 2
                and new_messages[0].get("role") == "user"
                and new_messages[1].get("role") == "assistant"
                and existing[-2].get("message") == new_messages[0].get("message")):
                prior_user = existing[-2]
                prior_asst = dict(existing[-1])
                new_asst = new_messages[1]
                prior_asst["edit_segments"] = list(prior_asst.get("edit_segments") or []) + list(new_asst.get("edit_segments") or [])
                prior_asst["edit_steps"] = list(prior_asst.get("edit_steps") or []) + list(new_asst.get("edit_steps") or [])
                prior_asst["llm_messages"] = list(prior_asst.get("llm_messages") or []) + list(new_asst.get("llm_messages") or [])
                prior_asst["message"] = (prior_asst.get("message") or "") + (new_asst.get("message") or "")
                # Terminal flags from the new turn determine the final state.
                # pending_ask: if new turn paused again, carry the new ask;
                # otherwise the merge is exiting the paused state.
                if new_asst.get("pending_ask"):
                    prior_asst["pending_ask"] = new_asst["pending_ask"]
                else:
                    prior_asst.pop("pending_ask", None)
                if new_asst.get("cancelled"):
                    prior_asst["cancelled"] = True
                else:
                    prior_asst.pop("cancelled", None)
                existing = existing[:-2]
                new_messages = [prior_user, prior_asst]
            else:
                existing = self._strip_trailing_pending_pair(existing)
        merged = existing + list(new_messages)

        repo = ConversationRepo(await self.get_pool())
        await repo.upsert_events(
            conversation_id=conversation_id,
            user_id=user_id,
            workflow_id=workflow_id,
            title=title,
            preview=preview,
            events=merged,
            pending_ask=new_pending_ask or None,
            cost_delta=cost_delta,
            token_delta=token_delta,
            turn_delta=turn_delta,
        )

        # Return the merged events array so callers can include it in their
        # active_gen:terminal emit (saves the FE a refetch round-trip).
        return merged

    def get_events(self) -> Dict[str, Callable]:
        """Register workflow builder and conversation management events."""
        return {
            "workflow:builder:edit": self.edit_workflow,
            "workflow:builder:autofill": self.autofill_node,
            "workflow:builder:input_response": self.handle_input_response,
            "workflow:builder:list_pending": self.handle_list_pending,
            "workflow:builder:share_ask": self.handle_share_ask,
            "workflow:builder:usage": self.get_credit_usage,
            "conversations:list": self.handle_list_conversations,
            "conversation:resume": self.handle_resume_conversation,
            "conversation:delete": self.handle_delete_conversation,
            "conversation:get_latest_for_workflow": self.handle_get_latest_for_workflow,
            "conversation:list_for_agent": self.handle_list_conversations_for_agent,
        }


    async def handle_input_response(
        self, sid: str, data: dict, caller_user_id: Optional[str] = None,
    ) -> None:
        """Public entry — runs the resume turn inline on the asyncio loop.

        Mirrors edit_workflow: the resume runs the same AgenticBuilder
        builder, just seeded with the user's <ask/> answer.
        ``caller_user_id`` is the HEADLESS identity override (same seam as
        edit_workflow) — the builder input bridge resumes a parked run as the
        workflow owner with an empty sid; empty-sid emits are dropped by
        send_event's falsy-sid guard, user_id-routed events still land.
        """
        try:
            await self._handle_input_response_impl(sid, data, caller_user_id=caller_user_id)
        except Exception as e:
            logger.exception("[BuilderHandler] inline input_response failed: %s", e)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=data.get('request_id'),
                data={'success': False},
                error=f"Input response failed: {e}",
            ))

    async def _handle_input_response_impl(
        self, sid: str, data: dict, caller_user_id: Optional[str] = None,
    ) -> None:
        """Run the resume builder in the current process.

        ONLY called from inside an input_response_worker subprocess via
        workers.input_response_worker._run_input_response. The public
        handle_input_response() always dispatches; never call this directly
        from the parent's request-handling path.
        """
        conversation_id = data.get('conversation_id')
        ask_id = data.get('ask_id')
        values = data.get('values', {})
        # Free-form answer typed in the chatbox instead of the <ask/> form
        # (e.g. "don't have a credential yet, proceed without it"). Takes
        # precedence over `values` when set.
        message = (data.get('message') or '').strip()
        dismissed = data.get('dismissed', False)
        if not conversation_id:
            # Backwards-compat: older FE payloads sent generation_id and we
            # used builder_generations to find the conversation. With the
            # collapse we need conversation_id directly. The FE has been
            # updated in the same PR.
            logger.warning("[WorkflowBuilder] input_response missing conversation_id")
            return

        # Headless callers (bridge resume, empty sid) supply the identity and
        # have NO session — later session reads must tolerate None.
        session = None
        user_id = caller_user_id
        if not user_id:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id') if session else None
        if not user_id:
            logger.warning("[WorkflowBuilder] input_response without authenticated session")
            return

        # Generated upfront so the limit-error response can address both keys
        # the FE listens on (request_id for the synth response, generation_id
        # for the active-gen stream). Re-assigned below from data if the FE
        # supplied one.
        generation_id = data.get('generation_id') or str(uuid.uuid4())
        request_id = data.get('request_id')

        # Gate the resume against the AI builder cap — resuming a paused-on-ask
        # conversation drives a full builder turn, so it must consume a credit.
        try:
            pool = await self.get_pool()
            if pool:
                async with pool.acquire() as conn:
                    from billing.plan_limits import check_ai_builder_limit
                    can_use, limit_error = await check_ai_builder_limit(conn, user_id)
                    if not can_use:
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request_id,
                            data={'success': False},
                            error=limit_error,
                        ))
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=generation_id,
                            data={'success': False, 'event_type': 'error'},
                            error=limit_error,
                        ))
                        user_data = session.get('user_data', {}) if session else {}
                        pass
                        return
        except Exception as e:
            logger.warning(f"[WorkflowBuilder] AI builder limit check failed, proceeding: {e}")

        # Load the conversation row + the trailing pending assistant.
        events = await self._read_conversation_events(conversation_id, user_id)
        if not events:
            logger.warning(f"[WorkflowBuilder] input_response: no events for conv {conversation_id}")
            return
        last_asst = events[-1]
        if not self._is_pending_assistant(last_asst):
            logger.info(
                f"[WorkflowBuilder] input_response for conv {conversation_id} "
                f"but no pending_ask on trailing assistant — already resumed?"
            )
            return
        persisted_pending = last_asst.get("pending_ask") or {}
        if ask_id and persisted_pending.get("ask_id") != ask_id:
            logger.info(
                f"[WorkflowBuilder] ask_id mismatch for conv {conversation_id} "
                f"({ask_id} vs {persisted_pending.get('ask_id')}) — ignoring"
            )
            return

        # This ask is being consumed (drawer answer or bridge submit) — expire
        # every still-pending bridge link for it so the shared page stops
        # resolving. Best-effort; the resume must not fail on it.
        try:
            from repositories.builder_bridge import BuilderBridgeRepo

            await BuilderBridgeRepo(await self.get_pool()).void_pending_links_for_ask(
                conversation_id, persisted_pending.get("ask_id") or "",
            )
        except Exception:
            logger.warning("[WorkflowBuilder] bridge-link voiding failed", exc_info=True)

        # Look up workflow_id and the original first-turn prompt for the synth request.
        _conv_repo = ConversationRepo(await self.get_pool())
        workflow_id = await _conv_repo.get_workflow_id(conversation_id, user_id)
        original_prompt = ""
        for msg in events:
            if msg.get("role") == "user" and msg.get("message"):
                original_prompt = msg["message"]
                break

        # Fetch the current workflow graph so the brain's system prompt
        # reflects the post-pause state (nodes the brain added in the prior
        # turn are persisted to public.workflows, not just to the LLM
        # history). Without this, builder.edit(current_graph={}) tells the
        # brain "you have no nodes" while the conversation history shows it
        # just added some — the brain re-tries the same ops, re-emits the
        # same <ask/>, and the run loops indefinitely on the same ask.
        current_graph: Dict[str, Any] = {}
        client_graph = data.get('current_graph')
        if isinstance(client_graph, dict) and client_graph.get('nodes'):
            # Freshest source: the live canvas graph the FE sent with the answer.
            # The brain's just-added nodes may not have reached the debounced
            # auto-save in public.workflows yet, so the DB read below would be
            # stale and the brain would re-add the nodes it already created (B8).
            current_graph = client_graph
        elif workflow_id:
            wf_pool = await self.get_pool()
            wf_row = None
            if wf_pool:
                async with wf_pool.acquire() as _wf_conn:
                    wf_row = await WorkflowRepo(wf_pool).get_workflow_data(
                        _wf_conn, uuid.UUID(workflow_id),
                    )
            if wf_row and wf_row.get("workflow"):
                wf = wf_row["workflow"]
                if isinstance(wf, str):
                    try:
                        wf = json.loads(wf)
                    except Exception:
                        wf = {}
                if isinstance(wf, dict):
                    current_graph = wf

        # Hydrate the brain's prior context from all completed turns.
        # _load_conversation_history walks events and pulls llm_messages off
        # each completed assistant — exactly the messages the brain saw last.
        conversation_history = await self._load_conversation_history(conversation_id, user_id)

        start_time = time.time()
        agentic_config = AgenticBuilderConfig()
        model_used = agentic_config.brain_model
        # generation_id was resolved at the top of this method (before the cap
        # check) so the limit-error response can address it. The FE keys live
        # response listeners on it for THIS resume only.
        platform_ops = self._create_platform_ops(
            user_id, sid, workflow_id=workflow_id,
        ) if user_id else None

        cancel_scope = CancelScope()
        builder = AgenticBuilder(
            config=agentic_config,
            generation_id=generation_id,
            platform_ops=platform_ops,
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            user_id=user_id,
            cancel_scope=cancel_scope,
        )
        register_builder_scope(conversation_id, cancel_scope)

        # Active-gen lifecycle: a resume IS a fresh gen (per-resume gen_id).
        # The FE store registers it; deltas patch it; terminal evicts it.
        # prompt='' signals "no new user bubble" — the resume continues
        # the prior conversation; the user's ask answer (or skip) is
        # handled inline as a system message, not a chat-visible turn.
        await self._emit_active_gen_started(
            sid,
            gen_id=generation_id,
            workflow_id=workflow_id,
            conversation_id=conversation_id,
            prompt='',
            user_id=user_id,
            request_id=data.get('request_id'),
        )

        # Inject the user's answer (or skip notice) as the next user-role
        # message. With replace_pending=True on the pause path, a re-asking
        # brain can no longer stack pairs — but we still want the dismiss
        # prompt to be strongly worded so the brain doesn't waste a turn
        # immediately re-asking for the same thing.
        if dismissed:
            answer_content = (
                "[System: Input Request Dismissed]\n"
                "The user declined to provide this input. Do NOT re-ask for "
                "the same information. Either continue the workflow without "
                "what was asked for (skipping the affected step if necessary), "
                "or finalize with a brief explanation of what couldn't be "
                "completed."
            )
        else:
            # Render the answered fields so the brain can attribute and apply
            # each one without guessing the opaque positional ask_i (B6) —
            # field-bound and credential answers carry the exact mutation
            # command. Fold in any free-form reply the user typed in the chatbox
            # (or chose via a field affordance): a partial form submit plus a
            # typed reply surfaces BOTH, so the user never repeats an answer they
            # already gave in the form.
            answer_content = self._format_input_response_content(
                values, persisted_pending, message=message,
            )

        # Agent-originated runs: restore the return address the synth request
        # would otherwise lose — the newest bridge link row is the durable
        # record (minted when the run first parked). Without this a resumed
        # run's completion/second-ask never reaches the agent's conversation.
        resumed_user_context: Dict[str, Any] = {'workflow_id': workflow_id, 'has_workflow': True}
        try:
            from repositories.builder_bridge import BuilderBridgeRepo

            origin = await BuilderBridgeRepo(await self.get_pool()).load_origin(conversation_id)
            if origin:
                resumed_user_context.update({
                    'source': 'agent_prompt_builder',
                    'agent_conversation_id': origin['agent_conversation_id'],
                    'agent_node_id': origin['agent_node_id'],
                })
        except Exception:
            logger.warning("[WorkflowBuilder] agent-origin restore failed", exc_info=True)

        # Seed the builder with: system + history + the answer as the next user msg.
        await builder.edit(
            current_graph=current_graph,
            edit_prompt=answer_content,
            target_node_ids=None,
            selected_node_id=None,
            conversation_history=conversation_history or None,
            silent=False,
            user_context=resumed_user_context,
            viewport_width=None,
            viewport_height=None,
            n8n_workflow=None,
            edit_scope=None,
        )

        synth_request = WorkflowBuilderEditRequest(
            request_id=data.get('request_id') or generation_id,
            generation_id=generation_id,
            edit_prompt=original_prompt,
            current_graph=current_graph,
            conversation_id=conversation_id,
            user_context=resumed_user_context,
            silent=False,
        )
        current_graph_summary = self._summarize_graph(current_graph)

        try:
            await self._drive_builder_and_terminate(
                sid, builder,
                request=synth_request,
                user_id=user_id,
                session=session or {},
                start_time=start_time,
                model_used=model_used,
                current_graph_summary=current_graph_summary,
                # The full prior conversation is in conversation_history, so
                # the offset for the new turn's llm_messages slice points
                # past system + history + user_answer.
                conversation_history_len=len(conversation_history) if conversation_history else 0,
                generation_id=generation_id,
                log_context="resuming after <ask/>",
            )
        finally:
            unregister_builder_scope(conversation_id, cancel_scope)

    async def handle_share_ask(self, sid: str, data) -> None:
        """Mint (or reuse) a public input-bridge link for the caller's builder
        run paused on an <ask/> — the drawer's share button, so a MANUAL build
        can hand its questions to someone without a NoClick account (the same
        links agent-initiated runs mint automatically). Idempotent per
        (conversation, ask): re-clicks return the same URL. The conversation
        read is user-scoped, so only the run's owner can share it — and the
        resume charges that owner, same as answering in the drawer."""
        from repositories.builder_bridge import BuilderBridgeRepo
        from utils.builder_bridge import bridge_url, create_bridge_link_for_ask

        async def respond(**payload):
            await send_event(self.sio, sid, ResponseEvent(
                request_id=data.request_id, data=payload,
            ))

        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id') if session else None
            if not user_id:
                await respond(success=False, error="Not authenticated")
                return

            events = await self._read_conversation_events(data.conversation_id, user_id)
            last = events[-1] if events else None
            pending = (last or {}).get("pending_ask") or {}
            if not (self._is_pending_assistant(last or {}) and pending.get("ask_id") == data.ask_id):
                await respond(success=False, error="This run is no longer waiting on that question")
                return

            pool = await self.get_pool()
            repo = BuilderBridgeRepo(pool)
            existing = await repo.find_pending_for_ask(data.conversation_id, data.ask_id)
            if existing:
                await respond(success=True, url=bridge_url(existing), link_id=existing)
                return

            conv_repo = ConversationRepo(pool)
            workflow_id = await conv_repo.get_workflow_id(data.conversation_id, user_id)
            if not workflow_id:
                await respond(success=False, error="This conversation has no workflow")
                return
            async with pool.acquire() as conn:
                workflow_name = await conn.fetchval(
                    "SELECT name FROM workflows WHERE id = $1::uuid", workflow_id
                )
            link = await create_bridge_link_for_ask(
                pool,
                user_id=str(user_id),
                workflow_id=str(workflow_id),
                builder_conversation_id=data.conversation_id,
                ask_id=data.ask_id,
                inputs=pending.get("inputs") or [],
                agent_conversation_id=None,  # manual share — no agent return address
                agent_node_id=None,
                workflow_name=workflow_name,
            )
            if not link:
                await respond(success=False, error="Failed to create the link")
                return
            await respond(success=True, url=link["url"], link_id=link["link_id"])
        except Exception as e:
            logger.error(f"[WorkflowBuilder] share_ask failed: {e}", exc_info=True)
            await respond(success=False, error="Failed to create the link")

    async def handle_list_pending(self, sid: str, data: ListPendingBuilderRunsRequest) -> None:
        """Return conversations paused on <ask/> for the current user.

        Reads the denormalized `pending_ask` column on conversations (fast
        index lookup via idx_conversations_paused) instead of the old
        builder_generations status filter.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id') if session else None
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=data.request_id, data={'runs': []},
                ))
                return

            repo = ConversationRepo(await self.get_pool())
            rows = await repo.list_pending_asks(user_id, data.workflow_id)

            runs = []
            for row in rows:
                pending = row["pending_ask"]
                if isinstance(pending, str):
                    try:
                        pending = json.loads(pending)
                    except Exception:
                        continue
                runs.append({
                    "conversation_id": row["conversation_id"],
                    "workflow_id": row.get("workflow_id"),
                    "pending_ask": pending,
                    "turn_count": row.get("turn_count", 0),
                    "updated_at": row["last_activity"].isoformat() if row.get("last_activity") else None,
                })

            await send_event(self.sio, sid, ResponseEvent(
                request_id=data.request_id, data={'runs': runs},
            ))
        except Exception as e:
            logger.error(f"[WorkflowBuilder] Error listing pending runs: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=data.request_id, data={'runs': []},
                error=str(e),
            ))

    async def autofill_node(self, sid: str, request: WorkflowAutofillRequest) -> None:
        """
        Run the node drafter on a single node and stream events back.

        Reuses the node drafter (the agentic builder's config engine) so
        the events are shape-compatible with the existing canvas-edit handler.
        """
        from coder.workflow.graph_state import GraphState
        from coder.workflow.node_drafter import create_node_drafter
        from coder.workflow.session_logger import SessionLogger

        generation_id = request.generation_id or str(uuid.uuid4())
        session = await self.sio.get_session(sid)

        if request.mode not in ('full', 'operation', 'fields', 'single_field'):
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={'success': False},
                error=f"Invalid autofill mode: {request.mode}",
            ))
            return
        if request.mode == 'single_field' and not request.target_field:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={'success': False},
                error="target_field is required when mode='single_field'",
            ))
            return

        graph_state = GraphState.from_dict(request.current_graph)
        node = graph_state.get_node(request.node_id)
        if not node:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={'success': False},
                error=f"Node {request.node_id} not found in current graph",
            ))
            return

        processor = create_node_drafter(
            generation_id=generation_id,
        )
        processor.graph_state = graph_state
        if request.user_prompt:
            processor.user_prompt = request.user_prompt
        else:
            processor.user_prompt = processor.autofill_prompt(
                request.node_id, request.mode, request.target_field,
            ) or node.goal or node.label or ""

        # Write a session JSONL so session viewer can replay this autofill
        # alongside full builder edits. Use the actual node drafting config from
        # the node drafter; AgenticBuilderConfig can diverge between
        # deployments and is not needed for single-node autofill.
        autofill_workflow_id = (request.current_graph or {}).get('workflow_id')
        session_log = SessionLogger(
            generation_id,
            workflow_id=autofill_workflow_id,
            user_id=session.get('user_id') if session else None,
        )
        drafter_model = getattr(processor.config, 'model', '(installation default)')
        session_log.log_session_start(
            mode=f"autofill_{request.mode}",
            prompt=processor.user_prompt or f"Autofill {request.mode} on {request.node_id}",
            brain_model="(none — single-node autofill)",
            node_drafter_model=drafter_model,
            max_turns=1,
            workflow_id=autofill_workflow_id,
        )
        processor.session_log = session_log

        try:
            autofill_error: Optional[str] = None
            async for event in processor.autofill_node(
                request.node_id,
                mode=request.mode,
                target_field=request.target_field,
            ):
                # Stream every event (errors included) on generation_id so the
                # canvas-edit hook's response handler sees them — that's where
                # toast surfacing + state cleanup live.
                event_data = {'event_type': event.type, **event.data}
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=generation_id,
                    data=event_data,
                ))
                if event.type == 'error':
                    autofill_error = event.data.get('error', 'Autofill error')
                    break

            # Always close out the generation_id stream so phase resets to 'idle'.
            await send_event(self.sio, sid, ResponseEvent(
                request_id=generation_id,
                data={'event_type': 'generation_complete'},
            ))

            if autofill_error:
                await session_log.log_session_end(
                    success=False, total_cost=processor.get_total_cost(),
                    total_tokens=processor.get_total_tokens(),
                    node_count=len(graph_state.nodes), edge_count=len(graph_state.edges),
                    turn_count=1,
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={'success': False},
                    error=autofill_error,
                ))
                return

            await session_log.log_session_end(
                success=True, total_cost=processor.get_total_cost(),
                total_tokens=processor.get_total_tokens(),
                node_count=len(graph_state.nodes), edge_count=len(graph_state.edges),
                turn_count=1,
            )

            updated_node = graph_state.get_node(request.node_id)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={
                    'success': True,
                    'generation_id': generation_id,
                    'node': updated_node.to_dict() if updated_node else None,
                },
            ))

            # Slack activity notification (threaded to the user's activity post)
            if session:
                user_data = session.get('user_data', {})
                slack_thread_ts = session.get('slack_thread_ts')
                details = {
                    "Mode": request.mode,
                    "Node": f"{updated_node.label or request.node_id} ({updated_node.type})" if updated_node else request.node_id,
                }
                if request.target_field:
                    details["Field"] = request.target_field
                send_activity_notification_background(
                    extract_user_name(user_data),
                    user_data.get('email', 'unknown@example.com'),
                    "✨  Autofill",
                    details=details,
                    thread_ts=slack_thread_ts,
                )
        except Exception as e:
            logger.error(f"[WorkflowBuilder] Autofill failed for {request.node_id}: {e}", exc_info=True)
            session_log.log_error("autofill", str(e))
            await session_log.log_session_end(
                success=False, total_cost=processor.get_total_cost(),
                total_tokens=processor.get_total_tokens(),
                node_count=len(graph_state.nodes), edge_count=len(graph_state.edges),
                turn_count=1,
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=generation_id,
                data={'event_type': 'error', 'error': str(e), 'nodeId': request.node_id},
            ))
            await send_event(self.sio, sid, ResponseEvent(
                request_id=generation_id,
                data={'event_type': 'generation_complete'},
            ))
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={'success': False},
                error=str(e),
            ))

    async def get_credit_usage(self, sid: str, data: dict) -> None:
        """Return the credit accounting for the chip / dashboard.

        Sums credit-chargeable usage events (ai_builder + ai_usage) from
        user_usage_events, converts $ → credits, and frames the payload to
        match the frontend's expected shape:
          - used/limit  → daily counters (only meaningful when daily_credit_cap
                          is set, i.e. free tier; null on plus/pro)
          - monthly_used/monthly_cap → monthly counters (set on free/plus/pro)
          - period      → 'day' when daily cap applies, 'month' otherwise
        Enterprise users see used=0/limit=null/monthly_cap=null and the FE
        banner renders nothing.

        Org owner routing: when the caller is acting inside an org workspace
        (FE sends `organization_id` in `data`) and isn't the owner themselves,
        we resolve and return the OWNER's credit pool. This matches the
        per-node pre-flight gate (usage_tracker.enforce_credit_gate, used by the
        agent hook + image/video/kling/imagen/cli/apify handlers), which already
        debits the owner — without this routing the chip would show the member's
        untouched personal pool while spends silently came out of the owner's.
        Falls back to the caller on lookup failure so the
        chip never blanks. `is_org_credits` lets the FE swap to the
        org-indicator styling without re-deriving the routing.
        """
        session = await self.sio.get_session(sid)
        user_id = session.get('user_id') if session else None
        request_id = data.get('request_id') if data else None
        if not user_id:
            return

        organization_id = data.get('organization_id') if data else None
        billing_user_id = user_id
        is_org_credits = False
        if organization_id:
            try:
                from billing.usage_tracker import usage_tracker
                owner_id = await usage_tracker.get_org_owner_id(organization_id)
                if owner_id and owner_id != user_id:
                    billing_user_id = owner_id
                    is_org_credits = True
            except Exception as e:
                logger.warning(f"[WorkflowBuilder] Org owner lookup failed for {organization_id}: {e}")

        try:
            pool = await self.get_pool()
            if not pool:
                return
            async with pool.acquire() as conn:
                from billing.plan_limits import get_credit_usage
                usage = await get_credit_usage(conn, billing_user_id)

            daily_cap = usage['daily_credit_cap']
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'used': usage['daily_credits_used'],
                    'limit': daily_cap,
                    'period': 'day' if daily_cap is not None else 'month',
                    'monthly_used': usage['monthly_credits_used'],
                    'monthly_cap': usage['monthly_credit_cap'],
                    # Server-provided next refresh for the primary credit window.
                    # ISO 8601 when configured, otherwise None.
                    'next_refresh_at': usage.get('plan_credits_period_end'),
                    # Exact start of the current monthly plan window — the usage
                    # popover's period range can't derive it from the end alone
                    # (day-clamping on 29-31 billing anchors isn't invertible).
                    'plan_window_start': usage.get('plan_window_start'),
                    # Live policy tier from the backend. Consumers may use it to
                    # reconcile a stale tier claim in the current auth token.
                    'effective_tier': usage['tier'],
                    # True when the numbers above reflect the org owner's
                    # pool rather than the caller's personal pool. Echoed
                    # so the chip can switch to the org-indicator styling.
                    'is_org_credits': is_org_credits,
                    'organization_id': organization_id if is_org_credits else None,
                    # The user whose pool these numbers describe (= the billing
                    # entity get_credit_usage summed: org owner under the configured attribution policy,
                    # else the caller). The chip matches live usage:event
                    # billing_user_id against this to deduct only charges that
                    # hit the displayed pool — including someone else's org pool.
                    'pool_user_id': billing_user_id,
                },
            ))
        except Exception as e:
            logger.warning(f"[WorkflowBuilder] Failed to fetch credit usage: {e}")


    # ── Active-generation channel ────────────────────────────────────────
    #
    # The FE activeGenStore + event relay mirror consume a per-event stream
    # keyed on generation_id. These emits run in parallel with the legacy
    # per-gen ResponseEvent path until consumers migrate (Turn 3).

    async def _emit_active_gen_started(
        self,
        sid: str,
        *,
        gen_id: str,
        workflow_id: Optional[str],
        conversation_id: str,
        prompt: str,
        user_id: Optional[str],
        request_id: Optional[str] = None,
    ) -> None:
        if not user_id:
            return
        # Register gen → request_id so text_chunk/status frames (which only
        # carry gen_id) can echo it back for FE latency correlation.
        if request_id:
            # Bounded FIFO: pop the oldest entry if we hit the cap.
            if len(self._gen_to_request_id) >= self._GEN_REQUEST_ID_CAP:
                oldest_key = next(iter(self._gen_to_request_id))
                self._gen_to_request_id.pop(oldest_key, None)
            self._gen_to_request_id[gen_id] = request_id
        from wss.sender.events import ActiveGenStartedEvent
        try:
            await send_event(
                self.sio, sid,
                ActiveGenStartedEvent(
                    gen_id=gen_id,
                    workflow_id=workflow_id,
                    conversation_id=conversation_id,
                    prompt=prompt,
                    started_at=time.time(),
                    request_id=request_id,
                ),
                user_id=user_id,
            )
        except Exception as e:
            logger.warning(f"[WorkflowBuilder] active_gen:started emit failed: {e}")

    async def _emit_active_gen_event(
        self,
        sid: str,
        event,
        *,
        generation_id: str,
        user_id: str,
    ) -> None:
        """Translate an BuilderStreamEvent into the matching active-gen frame."""
        from wss.sender.events import (
            ActiveGenTextChunkEvent,
            ActiveGenStatusEvent,
            ActiveGenTokenProgressEvent,
            ActiveGenGraphEventEvent,
            ActiveGenEditStepEvent,
        )
        request_id = self._gen_to_request_id.get(generation_id)
        try:
            if event.type == 'text_chunk':
                text = event.data.get('text') or ''
                if text:
                    await send_event(
                        self.sio, sid,
                        ActiveGenTextChunkEvent(
                            gen_id=generation_id,
                            delta=text,
                            request_id=request_id,
                        ),
                        user_id=user_id,
                    )
            elif event.type == 'status':
                status = event.data.get('status') or ''
                if status:
                    # Status events double as edit_step entries — the FE
                    # accumulates them into the reasoning log.
                    await send_event(
                        self.sio, sid,
                        ActiveGenStatusEvent(gen_id=generation_id, status=status),
                        user_id=user_id,
                    )
                    await send_event(
                        self.sio, sid,
                        ActiveGenEditStepEvent(gen_id=generation_id, step=status),
                        user_id=user_id,
                    )
            elif event.type == 'token_progress':
                # Ephemeral live counter — absolute cumulative heuristic, no
                # persistence. FE overwrites its displayed value per frame.
                total_tokens = int(event.data.get('total_tokens') or 0)
                if total_tokens > 0:
                    await send_event(
                        self.sio, sid,
                        ActiveGenTokenProgressEvent(gen_id=generation_id, total_tokens=total_tokens),
                        user_id=user_id,
                    )
            elif event.type in self._GRAPH_EVENT_TYPES:
                payload = {"type": event.type, **event.data}
                await send_event(
                    self.sio, sid,
                    ActiveGenGraphEventEvent(gen_id=generation_id, event=payload),
                    user_id=user_id,
                )
        except Exception as e:
            logger.warning(f"[WorkflowBuilder] active_gen:* emit failed for {event.type}: {e}")

    async def _emit_active_gen_terminal(
        self,
        sid: str,
        *,
        gen_id: str,
        outcome: str,
        committed_conversation_id: Optional[str],
        committed_messages: List[Dict[str, Any]],
        user_id: Optional[str],
        error: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        """Tell the FE store to drop this gen and patch persistedMessages.

        Outcome ∈ {'complete', 'paused', 'cancelled', 'failed', 'interrupted'}.
        'interrupted' (container drain) is the SAME signal the event relay sends:
        the FE keeps the gen and auto-resumes from the checkpoint instead of
        evicting. committed_messages carries the new full conversations.events
        array (empty for 'interrupted' — the FE ignores it for that outcome).
        """
        # Prefer the explicit request_id from the caller; fall back to the
        # one we registered on started so callers that didn't thread it (the
        # input-response resume path) still emit a correlated terminal.
        effective_request_id = request_id or self._gen_to_request_id.pop(gen_id, None)
        if request_id:
            # If caller passed it explicitly, evict any cached entry too so
            # we don't leak the map on long-lived processes.
            self._gen_to_request_id.pop(gen_id, None)
        if not user_id:
            return
        from wss.sender.events import ActiveGenTerminalEvent
        try:
            await send_event(
                self.sio, sid,
                ActiveGenTerminalEvent(
                    gen_id=gen_id,
                    outcome=outcome,
                    committed_conversation_id=committed_conversation_id,
                    committed_messages=committed_messages,
                    error=error,
                    request_id=effective_request_id,
                ),
                user_id=user_id,
            )
        except Exception as e:
            logger.warning(f"[WorkflowBuilder] active_gen:terminal emit failed: {e}")

    # ── Turn-driven execution helpers ────────────────────────────────────

    async def _emit_builder_event(
        self,
        sid: str,
        event,
        *,
        segments: List[Dict[str, Any]],
        pending_text: str,
        generation_id: str,
        user_context: Optional[Dict[str, Any]],
        session_log,
        edit_steps: Optional[List[str]] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """Emit one BuilderStreamEvent to the client, update segments, and return new pending_text."""
        if event.type == 'text_chunk':
            pending_text += event.data.get('text', '')
        elif event.type == 'status' and edit_steps is not None:
            # Mirror the FE's editSteps accumulator (NoClick.tsx 'status' case)
            # so the expandable reasoning log persists across resume / refresh.
            status_text = event.data.get('status') or ''
            if status_text and (not edit_steps or edit_steps[-1] != status_text):
                edit_steps.append(status_text)
        elif event.type in self._GRAPH_EVENT_TYPES:
            if pending_text:
                segments.append({"type": "text", "text": pending_text})
                pending_text = ""
            entry = {"type": event.type, "status": "completed", **event.data}
            if segments and segments[-1].get("type") == "events":
                segments[-1]["events"].append(entry)
            else:
                segments.append({"type": "events", "events": [entry]})

        event_data = {'event_type': event.type, **event.data}
        logger.debug(f"[WorkflowBuilder:edit] Sending event: {event.type}")
        # Route through event relay when we have user_id so cross-container events
        # reach the browser; Socket.IO direct for SDK/headless flows.
        if user_id:
            await send_event(
                self.sio, sid,
                ResponseEvent(request_id=generation_id, data=event_data),
                user_id=user_id,
            )
        else:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=generation_id,
                data=event_data,
            ))

        # Parallel emit for the active-gen channel: the FE activeGenStore
        # consumes these to maintain its in-memory mirror without polling.
        # The existing ResponseEvent emit above is kept until Turn 3
        # migrates the remaining consumers (canvas hook, headless builder)
        # off the per-gen socket subscription path.
        if user_id:
            await self._emit_active_gen_event(
                sid, event, generation_id=generation_id, user_id=user_id,
            )

        mcp_payload = None
        if event.type in self._MCP_BRIDGE_EVENT_TYPES:
            mcp_payload = self._to_mcp_event(event)
            wf_id = (user_context or {}).get('workflow_id', '')
            # sid guard: to="" would BROADCAST graph mutations to every client
            # on the container (python-socketio coalesces falsy to → room=None).
            # Headless runs (agent prompt_builder) have no sid; their canvas
            # updates reach the owner via the workflow's collaborative sync.
            if mcp_payload and wf_id and sid:
                await self.sio.emit('mcp:builder_event', {
                    'workflow_id': wf_id,
                    **mcp_payload,
                }, to=sid)

        if event.type in self._GRAPH_EVENT_TYPES and session_log is not None:
            mcp_with_wf = None
            if mcp_payload:
                wf_id_for_log = (user_context or {}).get('workflow_id', '')
                mcp_with_wf = {'workflow_id': wf_id_for_log, **mcp_payload}
            session_log.log_frontend_event(
                event_type=event.type,
                payload={'response_data': event_data, 'mcp_data': mcp_with_wf},
            )

        return pending_text

    async def _run_builder_turns(
        self,
        sid: str,
        builder: AgenticBuilder,
        *,
        segments: List[Dict[str, Any]],
        pending_text: str,
        user_context: Optional[Dict[str, Any]],
        edit_steps: Optional[List[str]] = None,
    ) -> tuple:
        """
        Drive run_one_turn() until the brain emits <ask/>, finishes, or hits the
        max-turns ceiling. Returns (TurnResult, pending_text).

        With <ask/> as a turn boundary, persistence happens only at terminal
        events (complete/cancel/ask), not mid-stream. A hard refresh during
        streaming therefore loses up to one turn's worth of partial text —
        bounded and acceptable, given the alternative was 0.5s polling and a
        coordinated read across two tables.
        """
        # Interruption resume: a checkpoint survives ONLY when the prior turn
        # never reached a terminal (container died mid-turn — every clean
        # terminal clears it). If one exists AND its prompt matches this run's
        # (a genuine resume of the same intent, not a new edit that happens to
        # share the conversation), replay the plan and skip the ~50s brain turn.
        # Missing/mismatched/Redis-down all fall through to a normal brain run.
        checkpoint = await resume_checkpoint.load_checkpoint(builder.conversation_id)
        if checkpoint is not None and checkpoint.get('prompt') == builder._user_prompt:
            # Resume: KEEP the checkpoint (don't consume-clear). The cursor
            # advances as we fill (mark_node_completed, shared with real runs)
            # and the terminal finalizers clear it — epoch-gated. So a resume
            # that ITSELF dies is re-resumable from the further-advanced
            # checkpoint, handled identically to the original's death. Refresh
            # the TTL so a long resume chain can't let it lapse mid-flight.
            await resume_checkpoint.refresh_checkpoint_ttl(builder.conversation_id)
            logger.info(
                f"[resume] resuming from checkpoint, skipping brain — "
                f"conv={builder.conversation_id} gen={builder.generation_id} "
                f"already_completed={len(checkpoint.get('completed_node_ids') or [])}"
            )
            async for event in builder.replay_checkpoint(
                checkpoint.get('ops') or [],
                checkpoint.get('completed_node_ids') or [],
            ):
                pending_text = await self._emit_builder_event(
                    sid, event,
                    segments=segments,
                    pending_text=pending_text,
                    generation_id=builder.generation_id,
                    user_context=user_context,
                    session_log=builder.session_log,
                    edit_steps=edit_steps,
                    user_id=builder.user_id,
                )
            result = builder.last_turn_result()
            if result.next_action in ('ask', 'done', 'incomplete', 'cancelled'):
                return result, pending_text
        elif checkpoint is not None:
            # Stale checkpoint from a DIFFERENT prompt (a new intent on the same
            # conversation) → drop it and run the brain on the new prompt.
            logger.info(
                f"[resume] checkpoint prompt mismatch — dropping stale checkpoint "
                f"for conv={builder.conversation_id}"
            )
            await self._clear_checkpoint_if_current(builder)

        while builder._turn_count < builder.config.max_turns:
            async for event in builder.run_one_turn():
                if event.type == 'run_test':
                    # The rehearsal fetches the SAVED graph the moment the FE
                    # receives this event, and normal persistence only happens
                    # at terminal events — so same-turn edits (the tool
                    # allowlist set alongside the closing demo) must hit the DB
                    # first, or the demo runs against a stale graph (the
                    # missing slack send tool, 2026-08-10).
                    await self._persist_builder_graph_for(
                        user_context.get('workflow_id') if user_context else None,
                        builder,
                        builder.user_id,
                    )
                pending_text = await self._emit_builder_event(
                    sid, event,
                    segments=segments,
                    pending_text=pending_text,
                    generation_id=builder.generation_id,
                    user_context=user_context,
                    session_log=builder.session_log,
                    edit_steps=edit_steps,
                    user_id=builder.user_id,
                )

            result = builder.last_turn_result()
            if result.next_action in ('ask', 'done', 'incomplete', 'cancelled'):
                return result, pending_text

        logger.info(f"[WorkflowBuilder] Max turns ({builder.config.max_turns}) reached for {builder.generation_id}")
        from coder.workflow.agentic.state import TurnResult as _TR
        return _TR(
            next_action='incomplete',
            incomplete_reason='max_turns_without_explicit_done',
        ), pending_text

    def _new_turn_llm_messages(
        self,
        builder: AgenticBuilder,
        conversation_history_len: int,
        persisted_user_message: Optional[str],
    ) -> List[Dict[str, Any]]:
        """The brain messages produced THIS turn, for persistence into the
        assistant turn's ``llm_messages`` (raw brain context — NOT chat-rendered).

        ``builder.messages`` is ``[system, *history, current_user, assistant,
        exec, ...]``. We normally skip ``current_user`` here because it is also
        persisted as the visible ``user`` event. But the resume-after-ask path
        injects the user's answer (``[System: User Input Response]``) as
        ``current_user`` while persisting the ORIGINAL prompt as the visible
        event — so that answer is captured by neither the visible event nor the
        old ``+1`` slice, and the brain loses every prior answer on the next
        resume (B2). Detect this by comparing ``current_user`` to the visible
        message and include it only when they differ, so it lands in brain
        history without becoming a duplicate (normal edit) or a chat bubble.
        """
        msgs = builder.messages or []
        cur_idx = 1 + conversation_history_len
        if cur_idx >= len(msgs):
            return list(msgs[cur_idx:])
        cur = msgs[cur_idx]
        content = cur.get("content") or ""
        # Normal edits put the visible user message (`persisted_user_message`)
        # into current_user verbatim — possibly with an appended selected-node
        # context suffix — so a prefix match means it is already captured by the
        # visible event and must be skipped here. The resume-after-ask path
        # injects an answer that does NOT start with the persisted ORIGINAL
        # prompt, so it falls through and IS included (the B2 fix). The empty
        # guard means a missing visible prompt never silently drops the answer.
        already_persisted = (
            cur.get("role") == "user"
            and bool(persisted_user_message)
            and content.startswith(persisted_user_message)
        )
        start = cur_idx + 1 if already_persisted else cur_idx
        return list(msgs[start:])

    @staticmethod
    def _format_input_response_content(
        values: Optional[Dict[str, Any]],
        persisted_pending: Dict[str, Any],
        message: str = "",
    ) -> str:
        """Render the user's <ask/> answers as the `[System: User Input Response]`
        message the brain sees on resume.

        The user can answer via the form (``values``), a free-form chatbox reply
        (``message``), or BOTH — a partial form submit plus a typed reply. All
        surface here so the user never has to repeat an answer they already gave
        in the form.

        The brain emits asks by label and never sees the positional ``ask_i`` id
        the system assigns, so echoing ``- ask_0: <value>`` forces it to guess
        which question an answer belongs to — the source of misattributed values
        and re-asks. Instead, name the target (node + field, or the question
        label) and, for field-bound and credential answers, hand the brain the
        exact mutation command so the value can't be dropped or applied to the
        wrong field. Auto-injected credential pickers (``auto_cred_*``) resolve
        via their persisted input the same way.
        """
        inputs_by_id: Dict[str, Dict[str, Any]] = {
            inp.get('id'): inp
            for inp in (persisted_pending.get('inputs') or [])
            if isinstance(inp, dict) and inp.get('id')
        }
        lines: List[str] = []
        for k, v in (values or {}).items():
            if not v:
                continue
            inp = inputs_by_id.get(k) or {}
            node_id = inp.get('nodeId')
            field_key = inp.get('fieldKey')
            label = inp.get('label')
            if field_key == 'env' and node_id:
                # Env answer already resolved to an agent_env credential id (the
                # bridge/FE minted it from the key/values). Attach it like any
                # credential — node_accepted_credential_types permits agent_env,
                # and set_credentials re-keys it under 'agent_env'.
                lines.append(
                    f'- Environment variables for node "{node_id}" (agent_env): {v} '
                    f'— attach with <set_credentials node="{node_id}" id="{v}" />'
                )
            elif field_key == 'credential' and node_id:
                cred_type = inp.get('credentialType') or ''
                type_hint = f" ({cred_type})" if cred_type else ''
                lines.append(
                    f'- Credential for node "{node_id}"{type_hint}: {v} '
                    f'— attach with <set_credentials node="{node_id}" id="{v}" />'
                )
            elif node_id and field_key:
                label_hint = f" ({label})" if label else ""
                lines.append(
                    f'- Field "{field_key}" on node "{node_id}"{label_hint}: {v} '
                    f'— apply with <field node="{node_id}" name="{field_key}" value="{v}" />'
                )
            elif label:
                lines.append(f"- {label}: {v}")
            else:
                lines.append(f"- {k}: {v}")
        parts: List[str] = []
        if lines:
            parts.append("\n".join(lines))
        if message:
            # Free-form reply alongside (or instead of) the form answers.
            parts.append(f"The user also replied: {message}" if lines else message)
            parts.append("Honor this reply and continue the workflow.")
        return f"{USER_INPUT_MARKER}\n" + "\n".join(parts)

    async def _clear_checkpoint_if_current(self, builder: Optional[AgenticBuilder]) -> None:
        """Clear the resume checkpoint at a terminal — but ONLY if this run still
        holds the latest epoch. A superseded run (a resume took over) must NOT
        wipe the checkpoint its successor owns; epoch-gating is what makes resumes
        re-resumable. Fail-open-to-keep on a Redis error (TTL reaps a leftover)."""
        if builder is None or not builder.conversation_id:
            return
        cid = builder.conversation_id
        my_attempt = getattr(builder, '_attempt', None)
        if await resume_checkpoint.is_current_attempt(cid, my_attempt):
            await resume_checkpoint.clear_checkpoint(cid)
        else:
            logger.info(
                f"[epoch] superseded run kept checkpoint for its successor — "
                f"conv={cid} gen={builder.generation_id} attempt={my_attempt}"
            )

    async def _persist_builder_graph(
        self,
        request: WorkflowBuilderEditRequest,
        builder: AgenticBuilder,
        user_id: Optional[str],
    ) -> None:
        """Persist the builder's mutated graph to ``public.workflows`` so the DB
        is the authoritative source at this turn boundary.

        The builder — not the frontend — owns persistence of its own mutations.
        The FE only auto-saves builder output when the canvas is mounted, and it
        NEVER saves on an ``<ask/>`` pause; a headless run that paused for input
        therefore left the DB at its pre-edit state, so the resumed run
        rehydrated an empty graph and every node lookup failed ("node not
        found"). Persisting here makes the resume-after-ask DB read (and any
        later read) see exactly what the brain built.

        ``builder.graph_state`` holds the COMPLETE post-edit graph (it was loaded
        from ``current_graph`` then mutated), so this writes the whole blob —
        same completeness as the FE's ``_saveWorkflow``. Unconditional write: the
        builder is the authoritative writer for its own run; the ``graph_version``
        bump makes any racing canvas ``fireSave`` cleanly CAS-rebase. Best-effort
        — a persistence failure is logged loudly but must not abort the turn's
        conversation finalization (the conversation row is the resume anchor).
        """
        workflow_id = (
            request.user_context.get('workflow_id') if request.user_context else None
        )
        await self._persist_builder_graph_for(workflow_id, builder, user_id)

    async def _persist_builder_graph_for(
        self,
        workflow_id: Optional[str],
        builder: AgenticBuilder,
        user_id: Optional[str],
    ) -> None:
        """Request-free persist seam — the run_test intercept in the turn loop
        has no request in scope, only the workflow id."""
        if not workflow_id or not user_id:
            return
        # Nothing built (pure <list_workflows>/<open_workflow> flow) — don't
        # clobber an existing workflow's graph with an empty one.
        if not builder.graph_state.nodes:
            return
        try:
            pool = await self.get_pool()
            if not pool:
                return
            workflow_data = builder.graph_state.to_workflow_data()
            async with pool.acquire() as conn:
                # This write is unconditional and whole-blob, so a client that
                # handed us a graph missing a credential would DELETE it from
                # the DB. Carry stored credentialIds forward — no DSL op
                # removes a credential, so absent always means "this writer
                # didn't know", never "the user detached it" (2026-08-02).
                # Best-effort by design: a failed pre-read must not block the
                # persist itself, which is what makes resume-after-ask work.
                try:
                    existing = await conn.fetchrow(
                        "SELECT workflow FROM workflows WHERE id = $1", uuid.UUID(workflow_id)
                    )
                    old = (existing or {})["workflow"] if existing else None
                    if isinstance(old, str):
                        old = json.loads(old)
                    if old:
                        preserve_existing_credentials(
                            workflow_data.get("nodes") or [], old.get("nodes") or []
                        )
                except Exception:
                    logger.warning(
                        "[WorkflowBuilder] credential-preserve pre-read failed for %s "
                        "— persisting the client graph as-is",
                        workflow_id, exc_info=True,
                    )
                saved = await WorkflowRepo(pool).update_workflow_dynamic(
                    conn, uuid.UUID(workflow_id), workflow_data=workflow_data,
                )
            if saved is None:
                logger.warning(
                    "[WorkflowBuilder] graph persist matched no row for workflow %s",
                    workflow_id,
                )
        except Exception:
            logger.error(
                "[WorkflowBuilder] failed to persist builder graph for workflow %s",
                workflow_id, exc_info=True,
            )

    async def _finalize_run_complete(
        self,
        sid: str,
        builder: AgenticBuilder,
        *,
        request: WorkflowBuilderEditRequest,
        segments: List[Dict[str, Any]],
        pending_text: str,
        conversation_history_len: int,
        user_id: Optional[str],
        session: Dict[str, Any],
        start_time: float,
        model_used: str,
        current_graph_summary: Dict[str, Any],
        edit_steps: Optional[List[str]] = None,
    ) -> None:
        """Emit terminal events, persist conversation, fire analytics. Called when run completes."""
        # Post-turn fallback: brain produced no user-facing text. The message is
        # GRAPH-AWARE — a non-empty graph means we DID build something (a bare
        # <done/> summary turn, a brain that errored after building, or the resume
        # summary path), so claiming "I wasn't able to complete this" would be a
        # lie. Only the truly-empty case keeps the rephrase prompt.
        if not builder.emitted_text:
            if builder.graph_state.nodes:
                fallback_text = (
                    f"Done. Your workflow now has {len(builder.graph_state.nodes)} "
                    f"node{'s' if len(builder.graph_state.nodes) != 1 else ''}."
                )
            else:
                fallback_text = (
                    "I wasn't able to complete this request. "
                    "Could you provide more details or try rephrasing?"
                )
            fallback = BuilderStreamEvent(
                type='text_chunk',
                data={'text': fallback_text},
            )
            pending_text = await self._emit_builder_event(
                sid, fallback,
                segments=segments,
                pending_text=pending_text,
                generation_id=builder.generation_id,
                user_context=request.user_context,
                session_log=builder.session_log,
                edit_steps=edit_steps,
                user_id=builder.user_id,
            )

        # generation_complete carries the title/summary for the canvas.
        complete_event = BuilderStreamEvent(
            type='generation_complete',
            data={
                'name': builder.graph_state.workflow_name or "Untitled Workflow",
                'summary': builder.graph_state.summary or f"Workflow with {len(builder.graph_state.nodes)} nodes",
            },
        )
        pending_text = await self._emit_builder_event(
            sid, complete_event,
            segments=segments,
            pending_text=pending_text,
            generation_id=builder.generation_id,
            user_context=request.user_context,
            session_log=builder.session_log,
            edit_steps=edit_steps,
            user_id=builder.user_id,
        )

        await builder.log_session_end(success=True, terminal_reason='explicit_done')
        # Persist the final graph so the DB is authoritative on completion too.
        # (The FE also saves on complete when a live canvas/headless session is
        # driving, but the backend owning it keeps the DB correct regardless.)
        await self._persist_builder_graph(request, builder, user_id)
        # Reached a terminal → drop the resume checkpoint. Clearing on EVERY
        # terminal makes "checkpoint present" mean exactly "the prior turn was
        # interrupted" (no terminal ran), which is what the resume branch keys on.
        await self._clear_checkpoint_if_current(builder)

        if pending_text:
            segments.append({"type": "text", "text": pending_text})

        result = builder.get_result_dict()
        await send_event(self.sio, sid, ResponseEvent(
            request_id=request.request_id,
            data={
                'success': True,
                'generation_id': builder.generation_id,
                'terminal_reason': 'explicit_done',
                'effects': builder.effect_summary(),
                **result,
            },
        ))

        if user_id and request.conversation_id and segments:
            raw_llm_messages = self._new_turn_llm_messages(
                builder, conversation_history_len, request.edit_prompt,
            )
            assistant_msg: Dict[str, Any] = {
                "role": "assistant",
                "message": "",
                "edit_segments": segments,
                "llm_messages": raw_llm_messages,
            }
            if edit_steps:
                # Defensive copy: edit_steps is the live list still owned by the
                # outer run loop; we don't want a later mutation to corrupt the
                # serialized conversation row.
                assistant_msg["edit_steps"] = list(edit_steps)
            new_messages = [
                {"role": "user", "message": request.edit_prompt},
                assistant_msg,
            ]
            # replace_pending=True handles the resume-after-ask case: when
            # this completion follows a paused turn, the pending [user, asst_paused]
            # pair gets replaced rather than appended on top of (which would
            # double the user message).
            committed = await self._save_conversation(
                request.conversation_id, user_id, new_messages,
                workflow_id=request.user_context.get('workflow_id') if request.user_context else None,
                replace_pending=True,
                cost_delta=builder._total_cost,
                token_delta=builder._total_tokens,
                turn_delta=builder._turn_count,
            )
            await self._emit_active_gen_terminal(
                sid,
                gen_id=builder.generation_id,
                outcome='complete',
                committed_conversation_id=request.conversation_id,
                committed_messages=committed,
                user_id=user_id,
                request_id=request.request_id,
            )

        if user_id:
            duration_ms = int((time.time() - start_time) * 1000)
            result_summary = self._summarize_graph(result)
            pass
            await self._store_builder_usage_event(
                user_id=user_id,
                provider_cost=builder._total_cost,
                total_tokens=builder._total_tokens,
                model=model_used,
                generation_id=builder.generation_id,
                sid=sid,
            )

            user_data = session.get('user_data', {}) if session else {}
            user_name = extract_user_name(user_data)
            user_email = user_data.get('email', 'unknown@example.com')
            slack_thread_ts = session.get('slack_thread_ts') if session else None
            node_count = len(result.get('nodes', []))
            send_activity_notification_background(
                user_name, user_email, "✏️  Edited Workflow",
                details={
                    "Prompt": request.edit_prompt,
                    "Nodes": str(node_count),
                    "Model": model_used,
                },
                thread_ts=slack_thread_ts,
            )

        # Agent-originated run: relay what the builder actually did to the
        # agent's conversation (delivered on the agent's next turn).
        await self._maybe_notify_agent_result(
            request=request, user_id=user_id, builder=builder, segments=segments,
        )

    async def _finalize_run_paused_for_ask(
        self,
        sid: str,
        builder: AgenticBuilder,
        pending_ask: PendingAsk,
        *,
        request_id: str,
        request: WorkflowBuilderEditRequest,
        user_id: Optional[str],
        segments: List[Dict[str, Any]],
        pending_text: str,
        conversation_history_len: int,
        edit_steps: Optional[List[str]] = None,
    ) -> None:
        """Treat <ask/> as a turn boundary — persist a complete [user, assistant]
        pair where the assistant carries the pending_ask payload. The next
        run (started by handle_input_response) will pick up via the standard
        multi-turn context loader, no special pause/resume serialization
        needed.

        This is the unified replacement for the old pause-then-snapshot flow:
        the conversation row is the only persistent state, the pending_ask
        column on conversations drives "is paused?" lookups, and
        handle_input_response builds a fresh AgenticBuilder from the LLM
        messages array stored on the assistant.
        """
        if pending_text:
            segments = list(segments) + [{"type": "text", "text": pending_text}]

        if user_id and request.conversation_id:
            # Persist the graph BEFORE the conversation write so the invariant
            # holds: whenever pending_ask is durable, public.workflows already
            # contains every node the brain built this turn — the resumed run
            # reads it back (in headless mode the FE never saves on a pause).
            await self._persist_builder_graph(request, builder, user_id)
            raw_llm_messages = self._new_turn_llm_messages(
                builder, conversation_history_len, request.edit_prompt,
            )
            assistant_msg: Dict[str, Any] = {
                "role": "assistant",
                "message": "",
                "edit_segments": segments,
                "llm_messages": raw_llm_messages,
                "pending_ask": pending_ask.to_dict(),
            }
            if edit_steps:
                assistant_msg["edit_steps"] = list(edit_steps)
            new_messages = [
                {"role": "user", "message": request.edit_prompt},
                assistant_msg,
            ]
            # replace_pending=True so resume-then-pause replaces the prior
            # pending pair rather than appending. Without this, a brain that
            # emits ask after ask (each with a fresh ask_id) accumulates one
            # paused pair per cycle — observed: 11 stacked pairs in a single
            # conversation. First pause is a no-op for the strip (nothing to
            # replace), so True is safe in both first-pause and resume-pause.
            committed = await self._save_conversation(
                request.conversation_id, user_id, new_messages,
                workflow_id=(request.user_context.get('workflow_id') if request.user_context else None),
                replace_pending=True,
                cost_delta=builder._total_cost,
                token_delta=builder._total_tokens,
                turn_delta=builder._turn_count,
            )
            await self._emit_active_gen_terminal(
                sid,
                gen_id=builder.generation_id,
                outcome='paused',
                committed_conversation_id=request.conversation_id,
                committed_messages=committed,
                user_id=user_id,
                request_id=request.request_id,
            )

            # Count the paused turn against the cap — the brain consumed LLM
            # tokens up to the <ask/>, so the credit is owed even though the
            # run didn't complete. Without this, a user could cycle through
            # ask/answer/ask/answer indefinitely without ever being gated.
            pass
            await self._store_builder_usage_event(
                user_id=user_id,
                provider_cost=builder._total_cost,
                total_tokens=builder._total_tokens,
                model=builder.config.brain_model if builder.config else None,
                generation_id=builder.generation_id,
                sid=sid,
            )

        # End this generation's session row (is_active=false). The run paused and
        # will resume under a NEW generation_id, so leaving it active makes the
        # row indistinguishable from a hung/zombie run (B5). success=None records
        # "ended, neither completed nor failed".
        await builder.log_session_end(success=None)
        # Clean terminal (paused on <ask/>) → drop the checkpoint; the answer-
        # resume runs a fresh brain turn, it must not replay this plan.
        await self._clear_checkpoint_if_current(builder)

        # Route via the event relay (user_id) so the paused signal reaches the
        # browser cross-container / after a socket reconnect, instead of a bare
        # sio emit to a possibly-stale sid (B4). The drawer itself is surfaced by
        # the active_gen:terminal above (B3); this just confirms the response.
        # user_id=None (headless/SDK) falls back to the direct sid emit.
        await send_event(self.sio, sid, ResponseEvent(
            request_id=request_id,
            data={
                'success': True,
                'paused': True,
                'generation_id': builder.generation_id,
                'ask_id': pending_ask.ask_id,
            },
        ), user_id=user_id)

        # Agent-originated run parked on questions: mint the public input-bridge
        # link and hand it to the agent's conversation — the agent forwards it
        # through its channels so anyone can answer without a NoClick login.
        await self._maybe_notify_agent_ask(
            request=request, user_id=user_id, builder=builder, pending_ask=pending_ask,
        )

    async def _maybe_notify_agent_ask(
        self, *, request: WorkflowBuilderEditRequest, user_id: Optional[str],
        builder: AgenticBuilder, pending_ask: PendingAsk,
    ) -> None:
        """Bridge-link mint + builder_ask relay for HEADLESS agent-originated
        runs (user_context.source == 'agent_prompt_builder'). Best-effort —
        the run is already durably parked either way."""
        ctx = request.user_context or {}
        agent_cid = ctx.get('agent_conversation_id')
        if ctx.get('source') != 'agent_prompt_builder' or not (user_id and agent_cid):
            return
        try:
            from utils.builder_bridge import (
                append_agent_builder_event,
                create_bridge_link_for_ask,
            )

            pool = await self.get_pool()
            ask = pending_ask.to_dict()
            workflow_id = ctx.get('workflow_id')
            link = await create_bridge_link_for_ask(
                pool,
                user_id=user_id,
                workflow_id=workflow_id,
                builder_conversation_id=request.conversation_id,
                ask_id=ask.get('ask_id') or '',
                inputs=ask.get('inputs') or [],
                agent_conversation_id=agent_cid,
                agent_node_id=ctx.get('agent_node_id'),
                workflow_name=builder.graph_state.workflow_name,
            )
            if not link:
                return
            await append_agent_builder_event(
                pool,
                agent_conversation_id=agent_cid,
                user_id=user_id,
                workflow_id=workflow_id,
                node_id=ctx.get('agent_node_id'),
                kind="builder_ask",
                payload={
                    "relay_id": link["link_id"],
                    "ask_id": ask.get('ask_id') or '',
                    "questions": link["questions"],
                    "inputs": link.get("inputs") or [],
                    "bridge_url": link["url"],
                },
            )
            # Push: wake the agent NOW so it can answer design asks itself or
            # forward the link through its channels — off the finalize path.
            from utils.async_helpers import spawn
            from utils.builder_bridge import fire_agent_wake_turn

            spawn(
                fire_agent_wake_turn(
                    pool, user_id=user_id, workflow_id=workflow_id,
                    node_id=ctx.get('agent_node_id'),
                    agent_conversation_id=agent_cid,
                ),
                name=f"builder-wake:{agent_cid}",
            )
        except Exception:
            logger.error("[WorkflowBuilder] agent ask notify failed", exc_info=True)

    async def _maybe_notify_agent_result(
        self, *, request: WorkflowBuilderEditRequest, user_id: Optional[str],
        builder: AgenticBuilder, segments: List[Dict[str, Any]],
        success: bool = True, error: Optional[str] = None,
    ) -> None:
        """builder_result relay for HEADLESS agent-originated runs — the agent
        learns what the builder actually did on its next turn."""
        ctx = request.user_context or {}
        agent_cid = ctx.get('agent_conversation_id')
        if ctx.get('source') != 'agent_prompt_builder' or not (user_id and agent_cid):
            return
        try:
            import uuid as _uuid

            from utils.builder_bridge import append_agent_builder_event

            final_text = "\n".join(
                s.get("text", "") for s in segments if s.get("type") == "text"
            ).strip()
            if success:
                summary = (final_text or builder.graph_state.summary or "Run completed.")[:1500]
            else:
                # Earlier streamed prose may be a promise to build — the exact
                # misleading text this protocol catches. Never relay that to
                # the parent agent as the outcome of an incomplete run.
                summary = (error or "Builder run ended incomplete.")[:1500]
            pool = await self.get_pool()
            await append_agent_builder_event(
                pool,
                agent_conversation_id=agent_cid,
                user_id=user_id,
                workflow_id=ctx.get('workflow_id'),
                node_id=ctx.get('agent_node_id'),
                kind="builder_result",
                payload={
                    "relay_id": _uuid.uuid4().hex[:12],
                    "summary": summary,
                    "workflow_name": builder.graph_state.workflow_name,
                    "success": success,
                    "error": error,
                },
            )
            from utils.async_helpers import spawn
            from utils.builder_bridge import fire_agent_wake_turn

            spawn(
                fire_agent_wake_turn(
                    pool, user_id=user_id, workflow_id=ctx.get('workflow_id'),
                    node_id=ctx.get('agent_node_id'),
                    agent_conversation_id=agent_cid,
                ),
                name=f"builder-wake:{agent_cid}",
            )
        except Exception:
            logger.error("[WorkflowBuilder] agent result notify failed", exc_info=True)

    async def _finalize_run_cancelled(
        self,
        sid: str,
        builder: AgenticBuilder,
        *,
        request: WorkflowBuilderEditRequest,
        generation_id: str,
        segments: Optional[List[Dict[str, Any]]] = None,
        pending_text: str = "",
        edit_steps: Optional[List[str]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Mark a user-cancelled run as cancelled and tell the client.

        The builder already rolled back the in-flight turn's messages on its
        side (run_one_turn snapshots message-list length pre-turn and resets
        on CancelledByUser).

        Persists the user prompt (and any assistant segments collected
        before the cancel) into conversations.events so the interrupted run
        shows up in get_latest_for_workflow — without this write, cancelled
        runs leave only the empty stub from _ensure_conversation_row and
        the FE silently restores an older conversation instead.

        ``pending_text`` is the un-flushed brain output from the in-flight
        turn — without flushing it into segments here, the restored bubble
        renders empty (no text, no events) even though the user saw the
        partial response stream live.
        """
        if user_id and request.conversation_id:
            final_segments: List[Dict[str, Any]] = list(segments) if segments else []
            if pending_text:
                final_segments.append({"type": "text", "text": pending_text})
            assistant_msg: Dict[str, Any] = {
                "role": "assistant",
                "message": "",
                "edit_segments": final_segments,
                "cancelled": True,
            }
            if edit_steps:
                assistant_msg["edit_steps"] = list(edit_steps)
            new_messages = [
                {"role": "user", "message": request.edit_prompt},
                assistant_msg,
            ]
            # If the cancel happened during a paused-on-ask resume, the prior
            # pending pair is still in events — replace it so we don't end up
            # with [user, asst_paused, user, asst_cancelled].
            committed = await self._save_conversation(
                request.conversation_id, user_id, new_messages,
                workflow_id=request.user_context.get('workflow_id') if request.user_context else None,
                replace_pending=True,
                cost_delta=builder._total_cost,
                token_delta=builder._total_tokens,
                turn_delta=builder._turn_count,
            )
            await self._emit_active_gen_terminal(
                sid,
                gen_id=builder.generation_id,
                outcome='cancelled',
                committed_conversation_id=request.conversation_id,
                committed_messages=committed,
                user_id=user_id,
                request_id=request.request_id,
            )

            # Count the cancelled turn against the cap — the brain has already
            # consumed LLM tokens before the user hit Stop, so the credit is
            # owed. Without this, a user could spam start-then-cancel to burn
            # provider tokens with no consumption against their plan.
            pass
            await self._store_builder_usage_event(
                user_id=user_id,
                provider_cost=builder._total_cost,
                total_tokens=builder._total_tokens,
                model=builder.config.brain_model if builder.config else None,
                generation_id=builder.generation_id,
                sid=sid,
            )
        await send_event(self.sio, sid, ResponseEvent(
            request_id=generation_id,
            data={'event_type': 'generation_complete', 'cancelled': True},
        ))
        await send_event(self.sio, sid, ResponseEvent(
            request_id=request.request_id,
            data={
                'success': False,
                'cancelled': True,
                'generation_id': generation_id,
            },
        ))
        await builder.log_session_end(success=False)
        # User cancelled → drop the checkpoint so it isn't auto-resumed.
        await self._clear_checkpoint_if_current(builder)

    async def _finalize_run_interrupted(
        self,
        sid: str,
        builder: AgenticBuilder,
        *,
        request: WorkflowBuilderEditRequest,
        generation_id: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Container drain (cancel reason='shutdown') → RECOVERABLE interrupt.

        Distinct from _finalize_run_cancelled (user Stop). A drain is NoClick's
        fault, not the user's, so this:
          - emits active_gen:terminal outcome='interrupted' (the SAME signal the
            event relay broadcasts when it observes the producer drop) so the FE
            sets gen.interrupted → InterruptedRunBanner auto-resumes via
            replay_checkpoint;
          - does NOT commit a cancelled:true assistant turn (no "Response
            interrupted by user" bubble) and does NOT emit the cancelled
            generation_complete / ResponseEvent frames;
          - KEEPS the resume checkpoint (no _clear_checkpoint_if_current) so the
            auto-resume has a plan to replay;
          - ends the session row is_active=FALSE with success=None ("ended,
            neither completed nor failed") so it isn't mistaken for a zombie —
            disambiguated from a user cancel (success=False) by checkpoint
            presence, exactly like the paused-on-ask path.

        The partial brain cost is still recorded: the tokens were genuinely
        consumed before the drain (same rationale as the cancelled path), and the
        record-everything billing policy requires the row.
        """
        await self._emit_active_gen_terminal(
            sid,
            gen_id=builder.generation_id,
            outcome='interrupted',
            committed_conversation_id=request.conversation_id,
            committed_messages=[],
            user_id=user_id,
            request_id=request.request_id,
        )
        if user_id:
            pass
            await self._store_builder_usage_event(
                user_id=user_id,
                provider_cost=builder._total_cost,
                total_tokens=builder._total_tokens,
                model=builder.config.brain_model if builder.config else None,
                generation_id=builder.generation_id,
                sid=sid,
            )
        # Persist whatever the brain built before the interruption so a resumed
        # or reopened run doesn't lose those nodes (the checkpoint drives resume,
        # but the graph blob is what the canvas + next turn actually read).
        await self._persist_builder_graph(request, builder, user_id)
        # is_active=FALSE so the drained row isn't a zombie; success=None records
        # "ended, neither completed nor failed". The checkpoint (kept) is what
        # actually drives the auto-resume.
        await builder.log_session_end(success=None)

    async def _finalize_run_incomplete(
        self,
        sid: str,
        builder: AgenticBuilder,
        *,
        request: WorkflowBuilderEditRequest,
        reason: Optional[str],
        segments: List[Dict[str, Any]],
        pending_text: str,
        conversation_history_len: int,
        edit_steps: Optional[List[str]],
        user_id: Optional[str],
        start_time: float,
        model_used: str,
        current_graph_summary: Dict[str, Any],
    ) -> None:
        """Finish a protocol/turn-limit stop without reporting false success.

        Unlike an exception, an incomplete run may contain valid graph changes
        and user-visible reasoning from earlier turns. Preserve both, but do
        not emit ``generation_complete`` or mark the build request successful.
        """
        reason = reason or 'incomplete_without_explicit_done'
        if reason == 'max_turns_without_explicit_done':
            error_msg = (
                "The AI builder reached its turn limit before explicitly confirming "
                "completion. No completed build was recorded; any partial changes "
                "were preserved."
            )
        else:
            error_msg = (
                "The AI builder stopped without explicitly confirming completion. "
                "No completed build was recorded; any partial changes were preserved."
            )

        final_segments = list(segments)
        if pending_text:
            final_segments.append({"type": "text", "text": pending_text})

        # Partial mutations are still valuable and already streamed to the
        # canvas. Make the backend graph authoritative before ending the run.
        await self._persist_builder_graph(request, builder, user_id)
        result_graph = builder.get_result_dict()
        committed: List[Dict[str, Any]] = []
        if user_id and request.conversation_id:
            raw_llm_messages = self._new_turn_llm_messages(
                builder, conversation_history_len, request.edit_prompt,
            )
            assistant_msg: Dict[str, Any] = {
                "role": "assistant",
                "message": "",
                "edit_segments": final_segments,
                "llm_messages": raw_llm_messages,
                "incomplete": True,
                "incomplete_reason": reason,
            }
            if edit_steps:
                assistant_msg["edit_steps"] = list(edit_steps)
            committed = await self._save_conversation(
                request.conversation_id,
                user_id,
                [
                    {"role": "user", "message": request.edit_prompt},
                    assistant_msg,
                ],
                workflow_id=(
                    request.user_context.get('workflow_id')
                    if request.user_context else None
                ),
                replace_pending=True,
                cost_delta=builder._total_cost,
                token_delta=builder._total_tokens,
                turn_delta=builder._turn_count,
            )

        await send_event(self.sio, sid, ResponseEvent(
            request_id=request.request_id,
            data={
                'success': False,
                'incomplete': True,
                'incomplete_reason': reason,
                'generation_id': builder.generation_id,
                'effects': builder.effect_summary(),
                **result_graph,
            },
            error=error_msg,
        ))
        await self._emit_active_gen_terminal(
            sid,
            gen_id=builder.generation_id,
            outcome='failed',
            committed_conversation_id=request.conversation_id,
            committed_messages=committed,
            user_id=user_id,
            error=error_msg,
            request_id=request.request_id,
        )

        if user_id:
            pass
            await self._store_builder_usage_event(
                user_id=user_id,
                provider_cost=builder._total_cost,
                total_tokens=builder._total_tokens,
                model=model_used,
                generation_id=builder.generation_id,
                sid=sid,
            )

        await builder.log_session_end(success=False, terminal_reason=reason)
        await self._clear_checkpoint_if_current(builder)
        await self._maybe_notify_agent_result(
            request=request,
            user_id=user_id,
            builder=builder,
            segments=final_segments,
            success=False,
            error=error_msg,
        )

    async def _finalize_run_failed(
        self,
        sid: str,
        builder: Optional[AgenticBuilder],
        *,
        request: WorkflowBuilderEditRequest,
        error_msg: str,
        user_id: Optional[str],
        start_time: float,
        model_used: str,
        current_graph_summary: Dict[str, Any],
        generation_id: str,
    ) -> None:
        """Emit error response, mark generation as failed, record a failed build request."""
        await send_event(self.sio, sid, ResponseEvent(
            request_id=request.request_id,
            data={'success': False},
            error=error_msg,
        ))
        # Drop the failed gen from the FE active map. No conversation
        # commit on failure — events array unchanged.
        await self._emit_active_gen_terminal(
            sid,
            gen_id=generation_id,
            outcome='failed',
            committed_conversation_id=request.conversation_id,
            committed_messages=[],
            user_id=user_id,
            error=error_msg,
            request_id=request.request_id,
        )
        if user_id:
            duration_ms = int((time.time() - start_time) * 1000)
            pass
            # Cost-bearing failures still consumed tokens before the exception.
            # builder may be None for failures that occur before the builder
            # is instantiated — those have no cost to record.
            if builder is not None:
                await self._store_builder_usage_event(
                    user_id=user_id,
                    provider_cost=builder._total_cost,
                    total_tokens=builder._total_tokens,
                    model=model_used,
                    generation_id=generation_id,
                    sid=sid,
                )

        # End the failed generation's session row (is_active=false) so it isn't
        # left looking like a zombie. builder is None for pre-construction
        # failures, which never wrote a session row.
        if builder is not None:
            await builder.log_session_end(success=False)
            await self._clear_checkpoint_if_current(builder)

    async def _drive_builder_and_terminate(
        self,
        sid: str,
        builder: AgenticBuilder,
        *,
        request: WorkflowBuilderEditRequest,
        user_id: Optional[str],
        session: Dict[str, Any],
        start_time: float,
        model_used: str,
        current_graph_summary: Dict[str, Any],
        conversation_history_len: int,
        generation_id: str,
        log_context: str,
        seed_edit_steps: Optional[List[str]] = None,
    ) -> None:
        """
        Run the turn loop to a terminal state and dispatch the right side-effect:
        <ask/> → pause; explicit done → full finalize; missing terminal / max
        turns → incomplete failure; exception → mark failed.
        Shared between initial edit_workflow and handle_input_response (resume).

        ``seed_edit_steps`` carries pre-pause status texts forward when this is
        a resume — without it, the post-resume reasoning log would only contain
        events emitted after the user answered the <ask/>.
        """
        segments: List[Dict[str, Any]] = []
        edit_steps: List[str] = list(seed_edit_steps) if seed_edit_steps else []
        pending_text = ""

        # Epoch fence: claim this run's attempt BEFORE _run_builder_turns loads
        # the checkpoint, and watch for supersession. If a newer attempt (a
        # resume) takes over, the watch task flips this run's cancel scope so it
        # stands down — bounding a noisy-neighbor double-run. Stored on the
        # builder for the epoch-gated checkpoint clear in the finalizers.
        builder._attempt = await resume_checkpoint.claim_attempt(builder.conversation_id)
        epoch_watch = asyncio.create_task(self._epoch_watch(builder))
        try:
            # Honor an early pause: if stop arrived during the setup window
            # (limit check / history load / builder construction), the
            # cancel_scope is already flipped — finalize before spinning up
            # turns. A drain caught in this window is a recoverable interrupt
            # (KEEP the checkpoint), a user Stop is a terminal cancel.
            if builder.cancel_scope.cancelled:
                if builder.cancel_scope.reason == 'shutdown':
                    await self._finalize_run_interrupted(
                        sid, builder, request=request,
                        generation_id=generation_id, user_id=user_id,
                    )
                else:
                    await self._finalize_run_cancelled(
                        sid, builder, request=request, generation_id=generation_id,
                        segments=segments, pending_text=pending_text,
                        edit_steps=edit_steps, user_id=user_id,
                    )
                return
            result, pending_text = await self._run_builder_turns(
                sid, builder,
                segments=segments,
                pending_text=pending_text,
                user_context=request.user_context,
                edit_steps=edit_steps,
            )
            if result.next_action == 'ask':
                await self._finalize_run_paused_for_ask(
                    sid, builder, result.pending_ask,
                    request_id=request.request_id,
                    request=request,
                    user_id=user_id,
                    segments=segments,
                    pending_text=pending_text,
                    conversation_history_len=conversation_history_len,
                    edit_steps=edit_steps,
                )
                return
            if result.next_action == 'cancelled':
                # A container drain ("shutdown") is a recoverable interrupt:
                # KEEP the checkpoint so InterruptedRunBanner auto-resumes. A
                # user Stop ("user", or None) is a terminal cancel.
                if result.cancel_reason == 'shutdown':
                    await self._finalize_run_interrupted(
                        sid, builder,
                        request=request,
                        generation_id=generation_id,
                        user_id=user_id,
                    )
                else:
                    await self._finalize_run_cancelled(
                        sid, builder,
                        request=request,
                        generation_id=generation_id,
                        segments=segments,
                        pending_text=pending_text,
                        edit_steps=edit_steps,
                        user_id=user_id,
                    )
                return
            if result.next_action == 'incomplete':
                await self._finalize_run_incomplete(
                    sid,
                    builder,
                    request=request,
                    reason=result.incomplete_reason,
                    segments=segments,
                    pending_text=pending_text,
                    conversation_history_len=conversation_history_len,
                    edit_steps=edit_steps,
                    user_id=user_id,
                    start_time=start_time,
                    model_used=model_used,
                    current_graph_summary=current_graph_summary,
                )
                return
            await self._finalize_run_complete(
                sid, builder,
                request=request,
                segments=segments,
                pending_text=pending_text,
                conversation_history_len=conversation_history_len,
                user_id=user_id,
                session=session,
                start_time=start_time,
                model_used=model_used,
                current_graph_summary=current_graph_summary,
                edit_steps=edit_steps,
            )
        except Exception as e:
            logger.error(f"[WorkflowBuilder] Error {log_context}: {e}", exc_info=True)
            await self._finalize_run_failed(
                sid, builder,
                request=request,
                error_msg=str(e),
                user_id=user_id,
                start_time=start_time,
                model_used=model_used,
                current_graph_summary=current_graph_summary,
                generation_id=generation_id,
            )
        finally:
            epoch_watch.cancel()
            try:
                await epoch_watch
            except (asyncio.CancelledError, Exception):
                pass

    async def _epoch_watch(self, builder: AgenticBuilder) -> None:
        """Background epoch fence: poll for supersession and, if a newer attempt
        has claimed this conversation, cancel this run's scope so it stands down.
        The existing per-chunk check_cancelled() in the builder loops does the
        actual teardown — this just flips the scope. One Redis GET per interval;
        fail-open (is_superseded never reports True on a Redis error)."""
        my_attempt = getattr(builder, '_attempt', None)
        if my_attempt is None:
            return  # epoch unavailable (Redis down at claim) → fencing off
        cid = builder.conversation_id
        while not builder.cancel_scope.cancelled:
            await asyncio.sleep(EPOCH_WATCH_INTERVAL_S)
            if builder.cancel_scope.cancelled:
                return
            if await resume_checkpoint.is_superseded(cid, my_attempt):
                logger.info(
                    f"[epoch] run superseded (attempt {my_attempt} no longer current) — "
                    f"standing down: conv={cid} gen={builder.generation_id}"
                )
                builder.cancel_scope.cancel("superseded")
                return

    async def edit_workflow(
        self, sid: str, request: WorkflowBuilderEditRequest,
        caller_user_id: Optional[str] = None,
    ) -> None:
        """Public entry — runs the AgenticBuilder + the node drafter
        inline on the asyncio loop. Failures are surfaced to the client via
        a ResponseEvent with success=False so the UI doesn't hang.

        ``caller_user_id`` is the HEADLESS identity override (same pattern as
        WorkflowExecutionHandler.handle_execute): server-side callers with no
        socket session — the agent's prompt_builder tool — pass the workflow
        owner here and an empty sid. Empty-sid emits are DROPPED by
        send_event's falsy-sid guard (an unguarded to="" would broadcast to
        every client — python-socketio coalesces it to room=None);
        user_id-routed events still reach the owner's event relay.
        """
        try:
            await self._edit_workflow_impl(sid, request, caller_user_id=caller_user_id)
        except Exception as e:
            logger.exception("[BuilderHandler] inline edit_workflow failed: %s", e)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={'success': False},
                error=f"Edit failed: {e}",
            ))

    async def _edit_workflow_impl(
        self, sid: str, request: WorkflowBuilderEditRequest,
        caller_user_id: Optional[str] = None,
    ) -> None:
        """Run the builder edit builder in the current process.

        ONLY called from inside an edit-worker subprocess (via
        workers.builder_edit_worker._run_edit). The public edit_workflow()
        always dispatches to a worker; never call this directly from the
        parent's request-handling path.
        """
        generation_id = request.generation_id or str(uuid.uuid4())
        start_time = time.time()

        # Create + register the cancel scope BEFORE any awaits so a user-pause
        # arriving during the limit-check / history-load / builder-construction
        # window is captured. Without this, an early stop click would race with
        # registration and be lost (handle_pause finds no scope, no agent).
        # Late wiring of cancel_scope into the AgenticBuilder still works — the
        # scope is created once and passed in below.
        cancel_scope = CancelScope()
        conv_id_for_pause = getattr(request, 'conversation_id', None)
        if conv_id_for_pause:
            register_builder_scope(conv_id_for_pause, cancel_scope)

        # Get user_id from session for analytics; headless callers (empty sid)
        # supply it directly and have NO session — every later `session` read
        # must tolerate None (an unconditional read crashed all headless runs).
        session = None
        user_id = caller_user_id
        if not user_id:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id') if session else None

        # Ensure the conversation exists in the chat history dropdown from the
        # first moment of the edit — paused runs never reach the completion
        # path that writes it, so without this they're invisible in history.
        if user_id and request.conversation_id:
            await self._ensure_conversation_row(
                request.conversation_id, user_id, request.edit_prompt,
                workflow_id=request.user_context.get('workflow_id') if request.user_context else None,
            )

        # Active-gen lifecycle: announce the run so the FE store registers
        # an in-flight gen for this workflow. Subsequent text_chunk / status
        # / graph_event frames patch it; the matching terminal emit (in
        # _finalize_run_*) drops it from the active map.
        if user_id and request.conversation_id:
            await self._emit_active_gen_started(
                sid,
                gen_id=generation_id,
                workflow_id=(request.user_context or {}).get('workflow_id') if request.user_context else None,
                conversation_id=request.conversation_id,
                prompt=request.edit_prompt,
                user_id=user_id,
                request_id=request.request_id,
            )

        # Fire BUILDER_PROMPT_SUBMITTED before the gate check so we capture intent
        # even for users who are blocked by the daily limit (needed to size the
        # gated cohort vs. the completion funnel).
        existing_node_count = len(request.current_graph.get('nodes') or []) if request.current_graph else 0
        agentic_config = AgenticBuilderConfig()
        model_used = agentic_config.brain_model
        log_activity_background(Events.BUILDER_PROMPT_SUBMITTED, user_id, {
            "generation_id": generation_id,
            "mode": "edit" if existing_node_count > 0 else "generate",
            "brain_model": model_used,
            "prompt_len": len(request.edit_prompt or ''),
            "existing_node_count": existing_node_count,
            "conversation_id": request.conversation_id,
        })

        # Check daily AI builder limit
        if user_id:
            try:
                pool = await self.get_pool()
                if pool:
                    async with pool.acquire() as conn:
                        from billing.plan_limits import check_ai_builder_limit
                        can_use, limit_error = await check_ai_builder_limit(conn, user_id)
                        if not can_use:
                            # Send error with both request_id (for sendEventAsync callback)
                            # and generation_id (for canvas edit response handler)
                            await send_event(self.sio, sid, ResponseEvent(
                                request_id=request.request_id,
                                data={'success': False},
                                error=limit_error
                            ))
                            await send_event(self.sio, sid, ResponseEvent(
                                request_id=generation_id,
                                data={'success': False, 'event_type': 'error'},
                                error=limit_error
                            ))
                            user_data = (session or {}).get('user_data', {})
                            pass
                            if conv_id_for_pause:
                                unregister_builder_scope(conv_id_for_pause, cancel_scope)
                            return
            except Exception as e:
                logger.warning(f"[WorkflowBuilder] AI builder limit check failed, proceeding: {e}")

        # Create summary of current graph for analytics
        current_graph_summary = self._summarize_graph(request.current_graph)


        # Use AgenticBuilder for multi-turn conversational editing
        logger.info(f"[WorkflowBuilder] Starting agentic edit {generation_id} with brain model {model_used}")

        # Load conversation history for multi-turn context
        conversation_history: List[Dict[str, str]] = []
        if request.conversation_id and user_id:
            conversation_history = await self._load_conversation_history(request.conversation_id, user_id)
            if conversation_history:
                logger.info(f"[WorkflowBuilder] Loaded {len(conversation_history)} history messages for conversation {request.conversation_id}")

        edit_workflow_id = (request.user_context or {}).get('workflow_id') if request.user_context else None

        # Fire-and-forget: if the workflow is empty — or its name is still a
        # default placeholder (a prior turn's naming call failed silently) —
        # generate a real title and description with a cheap model in the
        # background and broadcast the rename to the frontend. The main brain
        # loop runs unblocked. The retry path is placeholder-gated in SQL so
        # it can never clobber a name the user typed between turns.
        graph_nodes = request.current_graph.get('nodes') if request.current_graph else None
        graph_is_empty = not graph_nodes  # None or [] → empty
        ctx_workflow_name = (
            (request.user_context or {}).get('workflow_name') or ''
        ).strip()
        name_is_placeholder = ctx_workflow_name in ('', 'Untitled', 'Untitled Workflow')
        if (graph_is_empty or name_is_placeholder) and edit_workflow_id and user_id:
            from utils.async_helpers import spawn
            spawn(
                self._generate_workflow_name_background(
                    sid=sid,
                    user_id=user_id,
                    workflow_id=edit_workflow_id,
                    prompt=request.edit_prompt,
                    placeholder_only=not graph_is_empty,
                ),
                name=f"workflow-name-gen:{edit_workflow_id}",
            )

        platform_ops = self._create_platform_ops(user_id, sid, workflow_id=edit_workflow_id) if user_id else None

        builder = AgenticBuilder(
            config=agentic_config,
            generation_id=generation_id,
            platform_ops=platform_ops,
            conversation_id=getattr(request, 'conversation_id', None),
            workflow_id=(request.user_context or {}).get('workflow_id') if request.user_context else None,
            user_id=user_id,
            cancel_scope=cancel_scope,
        )
        # Seed builder state (system prompt + messages + graph_state). The turn
        # loop now lives in this handler, not inside builder.edit().
        await builder.edit(
            current_graph=request.current_graph,
            edit_prompt=request.edit_prompt,
            target_node_ids=request.target_node_ids,
            selected_node_id=request.selected_node_id,
            conversation_history=conversation_history or None,
            silent=request.silent,
            user_context=request.user_context,
            viewport_width=request.viewport_width,
            viewport_height=request.viewport_height,
            n8n_workflow=request.n8n_workflow,
            edit_scope=request.edit_scope,
        )

        try:
            await self._drive_builder_and_terminate(
                sid, builder,
                request=request,
                user_id=user_id,
                session=session or {},
                start_time=start_time,
                model_used=model_used,
                current_graph_summary=current_graph_summary,
                conversation_history_len=len(conversation_history) if conversation_history else 0,
                generation_id=generation_id,
                log_context="editing workflow",
            )
        finally:
            if conv_id_for_pause:
                unregister_builder_scope(conv_id_for_pause, cancel_scope)

    # ── Conversation management ──────────────────────────────────────────

    async def handle_list_conversations(self, sid: str, data: ListConversationsRequest) -> None:
        """List all conversations for the current user."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id') if session else None
            if not user_id:
                await send_event(self.sio, sid, ConversationListEvent(
                    request_id=data.request_id, conversations=[]))
                return

            # Builder chats only; per-agent AgentChatBlock threads have node_id set.
            repo = ConversationRepo(await self.get_pool())
            rows = await repo.list_builder_conversations(user_id)

            conversations = [
                {
                    "conversation_id": row["conversation_id"],
                    "title": row["title"] or "Untitled Conversation",
                    "preview": row["preview"] or "",
                    "last_activity": row["last_activity"].isoformat() if row["last_activity"] else "",
                    "created_at": row["created_at"].isoformat() if row["created_at"] else "",
                    "app_id": row.get("app_id"),
                    "app_name": row.get("app_name"),
                }
                for row in rows
            ]

            await send_event(self.sio, sid, ConversationListEvent(
                request_id=data.request_id, conversations=conversations))

        except Exception as e:
            logger.error(f"[WorkflowBuilder] Error listing conversations: {e}", exc_info=True)
            await send_event(self.sio, sid, ConversationListEvent(
                request_id=data.request_id, conversations=[]))

    async def handle_resume_conversation(self, sid: str, data: ResumeConversationRequest) -> None:
        """Resume a conversation — returns stored messages + workflow_id."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id') if session else None
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=data.request_id,
                    data={"session_id": data.session_id, "messages": [], "workflow_id": None}))
                return

            repo = ConversationRepo(await self.get_pool())
            row = await repo.get_for_resume(data.session_id, user_id)

            if row is None:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=data.request_id,
                    data={"session_id": data.session_id, "messages": [], "workflow_id": None}))
                return

            events_json = row["events"]

            # Interface-chat threads (ck-form ids) can wedge on a turn whose
            # backing run died without terminal evidence — same self-heal the
            # share page's resume runs; the chat block's reconciler polls this
            # endpoint while streaming and adopts the persisted interruption.
            if (
                events_json
                and (events_json[-1] or {}).get("role") == "user"
                and row.get("workflow_id") and row.get("node_id")
            ):
                ck_prefix = f"ck:{row['workflow_id']}:{row['node_id']}:"
                if data.session_id.startswith(ck_prefix):
                    # A run that died before writing any terminal evidence
                    # leaves the composer waiting forever; heal it on read.
                    from nodes.agent.interrupted_turns import resolve_interrupted_chat_turn

                    healed = await resolve_interrupted_chat_turn(
                        await self.get_pool(),
                        conversation_id=data.session_id,
                        workflow_id=str(row["workflow_id"]),
                        node_id=str(row["node_id"]),
                        conversation_key=data.session_id[len(ck_prefix):],
                        owner_user_id=user_id,
                    )
                    if healed:
                        row = await repo.get_for_resume(data.session_id, user_id) or row
                        events_json = row["events"]

            await send_event(self.sio, sid, ResponseEvent(
                request_id=data.request_id,
                data={
                    "session_id": data.session_id,
                    "messages": events_json,
                    "workflow_id": row.get("workflow_id"),
                }))

            logger.info(f"[WorkflowBuilder] Restored {len(events_json)} messages for {data.session_id}")

        except Exception as e:
            logger.error(f"[WorkflowBuilder] Error resuming conversation: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=data.request_id,
                data={"session_id": data.session_id, "messages": []}))

    async def handle_get_latest_for_workflow(
        self, sid: str, data: GetLatestConversationForWorkflowRequest
    ) -> None:
        """
        Return the most-recent conversation tied to a workflow plus enough
        metadata for the FE to decide between auto-restore and offering a
        "Resume previous" pill, all in one round-trip.

        Two distinct event shapes can land in conversations.events depending on
        which code path wrote them:
          • OpenHands chat: {action: "message", source|_source: "user", args:{content}}
          • WorkflowBuilder edit: {role: "user", message: "..."}
        has_user_messages must accept either shape.
        """
        # Wrap the payload in ResponseEvent so sendEventAsync's request_id
        # correlation (which only listens on the generic `response` channel)
        # actually resolves. The data shape mirrors LatestConversationForWorkflowEvent.
        request_id = data.request_id or str(uuid.uuid4())
        empty_payload = {
            "workflow_id": data.workflow_id,
            "conversation_id": None,
            "has_user_messages": False,
            "active_generation_id": None,
            "has_pending_ask": False,
        }
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id') if session else None
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id, data=empty_payload))
                return

            # Pull the top-N most-recent rows for this workflow. Empty stub
            # conversations get auto-created on every workflow open via
            # _ensure_conversation_row, so the most-recent row is frequently
            # an empty placeholder. Walk the candidates and prefer the first
            # one with pending_ask, else the first with user messages, else
            # the most-recent overall.
            # workflow_id and user_id are UUID columns; FE arguments arrive as
            # plain strings, so cast both sides explicitly.
            # Builder chats only (same rationale as handle_list_conversations).
            repo = ConversationRepo(await self.get_pool())
            rows = await repo.list_recent_for_workflow(user_id, data.workflow_id)

            if not rows:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id, data=empty_payload))
                return

            def _row_has_user_messages(r) -> bool:
                evs = r["events"]
                if isinstance(evs, str):
                    try:
                        evs = json.loads(evs)
                    except Exception:
                        return False
                if not isinstance(evs, list):
                    return False
                for ev in evs:
                    if not isinstance(ev, dict):
                        continue
                    if ev.get("role") == "user" and ev.get("message"):
                        return True
                    if ev.get("action") == "message" and (
                        ev.get("source") == "user" or ev.get("_source") == "user"
                    ):
                        return True
                return False

            # Selection priority:
            #   1. Most-recent row with pending_ask (paused on <ask/>).
            #      A paused conversation is always more important than a
            #      completed one — without this, a fresh completion on the
            #      same workflow shadows the still-paused conversation and
            #      the user can't get back to the ask drawer.
            #   2. Most-recent row with actual user messages (skips empty
            #      stubs from _ensure_conversation_row).
            #   3. Otherwise, the most-recent row.
            row = (
                next((r for r in rows if r.get("pending_ask")), None)
                or next((r for r in rows if _row_has_user_messages(r)), None)
                or rows[0]
            )
            has_user_messages = _row_has_user_messages(row)

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    "workflow_id": data.workflow_id,
                    "conversation_id": row["conversation_id"],
                    "has_user_messages": has_user_messages,
                    "has_pending_ask": row.get("pending_ask") is not None,
                    # active_generation_id retained as null for FE compat —
                    # callers can drop the field once the FE update lands.
                    "active_generation_id": None,
                },
            ))
        except Exception as e:
            logger.error(
                f"[WorkflowBuilder] Error fetching latest conversation for workflow "
                f"{data.workflow_id}: {e}",
                exc_info=True,
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id, data=empty_payload))

    async def handle_delete_conversation(self, sid: str, data: DeleteConversationRequest) -> None:
        """Soft-delete a conversation."""
        request_id = data.request_id or str(uuid.uuid4())
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id') if session else None
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={"success": False}, error="User not authenticated"))
                return

            repo = ConversationRepo(await self.get_pool())
            deleted_id = await repo.soft_delete(data.conversation_id, user_id)

            if deleted_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={"success": True, "conversation_id": data.conversation_id}))
                logger.info(f"[WorkflowBuilder] Deleted conversation {data.conversation_id}")
            else:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={"success": False}, error="Conversation not found"))

        except Exception as e:
            logger.error(f"[WorkflowBuilder] Error deleting conversation: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={"success": False}, error=str(e)))

    async def handle_list_conversations_for_agent(
        self, sid: str, data: ListConversationsForAgentRequest,
    ) -> None:
        """List every conversation belonging to the user that's scoped to a
        specific agent node (workflow_id + node_id).

        Two filters in play:
          • workflow_id / node_id columns — populated for newly-saved rows
            (idx_conversations_workflow_id covers this).
          • conversation_id LIKE 'ck:{wf}:{node}:%' — covers older rows where
            workflow_id/node_id columns weren't yet written, and is the
            canonical pattern agent_node.py uses to derive the id.

        Union of both keeps us correct across the migration boundary.
        Returns: { conversations: [{conversation_id, conversation_key, title,
        preview, last_activity, created_at, turn_count}] } ordered by
        last_activity DESC, newest first.
        """
        request_id = data.request_id or str(uuid.uuid4())
        empty_payload = {"conversations": []}
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id') if session else None
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id, data=empty_payload))
                return

            ck_prefix = f"ck:{data.workflow_id}:{data.node_id}:"
            # Fallback for pre-fix rows whose title/preview were never written.
            repo = ConversationRepo(await self.get_pool())
            rows = await repo.list_for_agent(
                user_id,
                data.workflow_id,
                data.node_id,
                ck_prefix + '%',
            )

            conversations = []
            for row in rows:
                conv_id = row["conversation_id"]
                # Extract just the user-facing conversation_key (the suffix
                # after the prefix); for rows that don't fit the pattern,
                # fall back to the full id.
                key = conv_id[len(ck_prefix):] if conv_id.startswith(ck_prefix) else conv_id
                conversations.append({
                    "conversation_id": conv_id,
                    "conversation_key": key,
                    "title": row["title"] or "",
                    "preview": row["preview"] or "",
                    "agent_model": row.get("agent_model"),
                    "last_activity": row["last_activity"].isoformat() if row["last_activity"] else "",
                    "created_at": row["created_at"].isoformat() if row["created_at"] else "",
                    "turn_count": row.get("turn_count") or 0,
                    # Visitor threads from the agent's public share link
                    # (conversation_key = share:{link}:{visitor}:{chat_key}).
                    "shared": key.startswith("share:"),
                })

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={"conversations": conversations}))
        except Exception as e:
            logger.error(
                f"[WorkflowBuilder] Error listing conversations for agent "
                f"{data.workflow_id}/{data.node_id}: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id, data=empty_payload, error=str(e)))
