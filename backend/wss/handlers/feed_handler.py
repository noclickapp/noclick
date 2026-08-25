"""
Feed handler — approval requests, activity logs, and workflow monitoring.

Handles listing/responding to approval requests, resuming workflow execution
after approval decisions, and listing activity log entries from log nodes.
SQL lives in ``repositories/feed.py`` — this file is presentation only.
"""

import logging
import asyncio
import uuid as uuid_module
from typing import Dict, Callable, Any

from repositories.feed import FeedRepo, ApprovalRow, ToolCallRow
from utils.database_pool import DatabasePoolMixin
from wss.schema import SocketIOHandler
from wss.sender import (
    send_event,
    ResponseEvent,
    ApprovalRequestResolvedEvent,
    WorkflowStartedEvent,  # noqa: F401 — re-exported historically
    WorkflowCompleteEvent,  # noqa: F401 — re-exported historically
)
from wss.receiver.client_events import (
    ApprovalListRequest,
    ApprovalRespondRequest,
    ActivityListRequest,
    ToolCallListRequest,
)

logger = logging.getLogger(__name__)


def _node_meta_map(graph: Any) -> Dict[str, Dict[str, str]]:
    """Map node id -> {label, type, model} from a stored workflow graph.

    Labels live top-level on node.data and the ReactFlow `type` (e.g.
    'automation-linear') is the registry key the frontend resolves to a brand
    icon. The graph JSON can come back from asyncpg as a dict or a string.
    """
    import json as _json

    if isinstance(graph, str):
        try:
            graph = _json.loads(graph)
        except (ValueError, TypeError):
            return {}
    if not isinstance(graph, dict):
        return {}

    meta: Dict[str, Dict[str, str]] = {}
    for node in graph.get("nodes", []) or []:
        node_id = node.get("id")
        if not node_id:
            continue
        data = node.get("data") or {}
        config = data.get("config") or {}
        meta[str(node_id)] = {
            "label": data.get("label") or "",
            "type": node.get("type") or "",
            # Agent node's selected model / harness (e.g. 'codex', 'opencode',
            # 'claude-opus-4-8'); empty for non-agent nodes.
            "model": config.get("model") or data.get("model") or "",
        }
    return meta


class FeedHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for feed operations — approvals, activity logs, and monitoring."""

    def __init__(self, sio):
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        return {
            "approval:list": self.handle_list,
            "approval:respond": self.handle_respond,
            "activity:list": self.handle_activity_list,
            "tool_calls:list": self.handle_tool_call_list,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def _get_repo(self):
        """Instantiate the repo on the current pool, or None if unavailable."""
        pool = await self.get_pool()
        if not pool:
            return None
        return FeedRepo(pool)

    # ------------------------------------------------------------------
    # approval:list — Fetch pending approval requests for the user / org
    # ------------------------------------------------------------------

    async def handle_list(self, sid: str, request: ApprovalListRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=[], error="User not authenticated",
                ))
                return

            repo = await self._get_repo()
            if repo is None:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=[], error="Database connection not available",
                ))
                return

            org_id = await repo.get_primary_org_id(user_id)
            org_uuid = uuid_module.UUID(org_id) if org_id else None

            pending_rows, resolved_rows = await repo.list_approvals(
                user_id=user_id, org_uuid=org_uuid,
            )

            def row_to_dict(row: ApprovalRow) -> Dict[str, Any]:
                # Parse form data from JSON content column
                content_raw = row.content or "{}"
                try:
                    import json as _json
                    form_data = _json.loads(content_raw) if isinstance(content_raw, str) else content_raw
                except (ValueError, TypeError):
                    form_data = {}

                d: Dict[str, Any] = {
                    "id": str(row.id),
                    "workflow_id": str(row.workflow_id),
                    "execution_id": str(row.execution_id),
                    "node_id": row.node_id,
                    "title": row.title,
                    "fields": form_data.get("fields", []),
                    "values": form_data.get("values", {}),
                    "status": row.status,
                    "created_at": row.created_at.isoformat(),
                    "workflow_name": row.workflow_name or "Untitled Workflow",
                }
                if row.decided_by:
                    d["decided_by"] = str(row.decided_by)
                    d["decided_by_email"] = row.decided_by_email or "unknown"
                if row.decided_at:
                    d["decided_at"] = row.decided_at.isoformat()
                return d

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={
                    "pending": [row_to_dict(r) for r in pending_rows],
                    "resolved": [row_to_dict(r) for r in resolved_rows],
                },
            ))

        except Exception as e:
            logger.error(f"[FeedHandler] Error listing approvals: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=[], error=str(e),
            ))

    # ------------------------------------------------------------------
    # activity:list — Fetch recent activity log entries
    # ------------------------------------------------------------------

    async def handle_activity_list(self, sid: str, request: ActivityListRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=[], error="User not authenticated",
                ))
                return

            repo = await self._get_repo()
            if repo is None:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=[], error="Database connection not available",
                ))
                return

            org_id = await repo.get_primary_org_id(user_id)
            org_uuid = uuid_module.UUID(org_id) if org_id else None

            rows = await repo.list_activity(
                user_id=user_id, org_uuid=org_uuid, limit=request.limit,
            )

            entries = [
                {
                    "id": str(row.id),
                    "workflow_id": str(row.workflow_id),
                    "execution_id": str(row.execution_id),
                    "node_id": row.node_id,
                    "message": row.message,
                    "level": row.level,
                    "created_at": row.created_at.isoformat(),
                    "workflow_name": row.workflow_name or "Untitled Workflow",
                }
                for row in rows
            ]

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=entries,
            ))

        except Exception as e:
            logger.error(f"[FeedHandler] Error listing activity logs: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=[], error=str(e),
            ))

    # ------------------------------------------------------------------
    # tool_calls:list — Fetch recent agent tool-call events
    # ------------------------------------------------------------------

    async def handle_tool_call_list(self, sid: str, request: ToolCallListRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=[], error="User not authenticated",
                ))
                return

            repo = await self._get_repo()
            if repo is None:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=[], error="Database connection not available",
                ))
                return

            org_id = await repo.get_primary_org_id(user_id)
            org_uuid = uuid_module.UUID(org_id) if org_id else None

            rows, graph_by_wf_id = await repo.list_tool_calls(
                user_id=user_id, org_uuid=org_uuid, limit=request.limit,
            )

            # Resolve agent/provider node labels from each referenced
            # workflow's graph. The repo already fetched the raw graphs in
            # one round trip — build the label maps on the presentation side.
            meta_maps: Dict[str, Dict[str, Dict[str, str]]] = {
                wf_id: _node_meta_map(graph) for wf_id, graph in graph_by_wf_id.items()
            }

            import json as _json

            # Final agent response per run — workflow executions persist the
            # agent node's output (its 'response' text) to the CAS, keyed by
            # (execution_id, node_id). Chat-only runs have no execution_id, so
            # no entry here. Bounded so the feed load stays light.
            responses: Dict[str, str] = {}
            run_keys: list = []
            seen_runs: set = set()
            for row in rows:
                ex_id = str(row.execution_id) if row.execution_id else None
                node_id = row.agent_node_id
                if not ex_id or not node_id or ex_id in seen_runs:
                    continue
                seen_runs.add(ex_id)
                run_keys.append((ex_id, node_id, str(row.workflow_id) if row.workflow_id else None))
                if len(run_keys) >= 30:
                    break

            if run_keys:
                from utils.cas import store as cas_store
                from utils.database_pool import get_native_pool
                cas_pool = get_native_pool()

                async def _resolve_response(ex_id, node_id, wf_id):
                    try:
                        out = await cas_store.read_node_output(
                            cas_pool, execution_id=ex_id, node_id=node_id, workflow_id=wf_id)
                    except Exception:
                        return None
                    if isinstance(out, dict):
                        text = out.get("response")
                        if isinstance(text, str) and text.strip():
                            return ex_id, text.strip()[:4000]
                    return None

                for resolved in await asyncio.gather(*[_resolve_response(*k) for k in run_keys]):
                    if resolved:
                        responses[resolved[0]] = resolved[1]

            def row_to_dict(row: ToolCallRow) -> Dict[str, Any]:
                wf_id = str(row.workflow_id) if row.workflow_id else None
                node_meta = meta_maps.get(wf_id, {}) if wf_id else {}
                agent_meta = node_meta.get(row.agent_node_id or "", {})
                provider_meta = node_meta.get(row.provider_node_id or "", {})
                args = row.arguments
                if isinstance(args, str):
                    try:
                        args = _json.loads(args)
                    except (ValueError, TypeError):
                        args = None
                return {
                    "id": str(row.id),
                    "workflow_id": wf_id,
                    "execution_id": str(row.execution_id) if row.execution_id else None,
                    "conversation_id": row.conversation_id,
                    "agent_node_id": row.agent_node_id,
                    "agent_node_label": (agent_meta.get("label") or None),
                    "agent_node_type": (agent_meta.get("type") or None),
                    # Prefer the runtime model recorded per call; the agent
                    # node's config.model isn't persisted for default models.
                    "agent_model": (row.model or agent_meta.get("model") or None),
                    "tool_name": row.tool_name,
                    "tool_type": row.tool_type,
                    "provider_node_id": row.provider_node_id,
                    "provider_node_label": (provider_meta.get("label") or None),
                    "provider_node_type": (provider_meta.get("type") or None),
                    "operation": row.operation,
                    "credential_id": str(row.credential_id) if row.credential_id else None,
                    "credential_name": row.credential_name,
                    "credential_type": row.credential_type,
                    "arguments": args,
                    "result_status": row.result_status,
                    "error": row.error,
                    "result_preview": row.result_preview,
                    "duration_ms": row.duration_ms,
                    "created_at": row.created_at.isoformat(),
                    "workflow_name": row.workflow_name or "Untitled Workflow",
                }

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"entries": [row_to_dict(r) for r in rows], "responses": responses},
            ))

        except Exception as e:
            logger.error(f"[FeedHandler] Error listing tool calls: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=[], error=str(e),
            ))

    # ------------------------------------------------------------------
    # approval:respond — Approve or reject, then resume workflow execution
    # ------------------------------------------------------------------

    async def handle_respond(self, sid: str, request: ApprovalRespondRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="User not authenticated",
                ))
                return

            if request.decision not in ("approved", "rejected"):
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={},
                    error="Decision must be 'approved' or 'rejected'",
                ))
                return

            repo = await self._get_repo()
            if repo is None:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="Database connection not available",
                ))
                return

            decision = await repo.resolve_approval(
                approval_id=uuid_module.UUID(request.approval_id),
                decision=request.decision,
                decided_by_user_id=user_id,
                values=request.values,
            )

            if decision is None:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={},
                    error="Approval request not found or already resolved",
                ))
                return

            workflow_id = str(decision.workflow_id)
            execution_id = str(decision.execution_id)
            approval_node_id = decision.node_id
            workflow_owner_id = str(decision.user_id)
            workflow_org_id = str(decision.organization_id) if decision.organization_id else None

            logger.info(
                f"[FeedHandler] Approval {request.approval_id} {request.decision} "
                f"by {user_id} — resuming workflow {workflow_id}"
            )

            # 2. Notify connected clients that the request is resolved
            await send_event(self.sio, sid, ApprovalRequestResolvedEvent(
                approval_id=request.approval_id,
                workflow_id=workflow_id,
                status=request.decision,
                decided_by=user_id,
            ))

            # 3. Send immediate response so the UI updates
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"status": request.decision, "approval_id": request.approval_id},
            ))

            # 4. Resume workflow execution via the WorkflowExecutionHandler's
            #    public resume entry. That always dispatches to a
            #    separately spawned execution worker with the same isolation
            #    guarantees as a fresh execute. Fire-and-forget so
            #    the socket response above isn't held up by the resume.
            from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
            from utils.async_helpers import spawn
            exec_handler = WorkflowExecutionHandler(self.sio)
            spawn(
                exec_handler.handle_resume(
                    sid=sid,
                    data={
                        'execution_id': execution_id,
                        'workflow_id': workflow_id,
                        'workflow_org_id': workflow_org_id,
                        'resume_node_id': approval_node_id,
                        'from_status': 'awaiting_approval',
                        'decision': request.decision,
                        'edited_values': request.values,
                    },
                    caller_user_id=workflow_owner_id,
                ),
                name=f"feed-approval-resume:{execution_id}",
            )

        except Exception as e:
            logger.error(f"[FeedHandler] Error responding to approval: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e),
            ))
