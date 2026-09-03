"""
Feed handler — approval requests (the Dashboard tab's needs-you queue).

Handles listing/responding to approval requests and resuming workflow execution
after approval decisions. The activity-log and tool-call list events retired
with the Feed tab; the Dashboard reads tool calls through ``FeedRepo`` directly.
SQL lives in ``repositories/feed.py`` — this file is presentation only.
"""

import logging
import asyncio
import uuid as uuid_module
from typing import Dict, Callable, Any

from repositories.feed import FeedRepo, ApprovalRow
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
)

logger = logging.getLogger(__name__)



class FeedHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for feed operations — approvals, activity logs, and monitoring."""

    def __init__(self, sio):
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        return {
            "approval:list": self.handle_list,
            "approval:respond": self.handle_respond,
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
