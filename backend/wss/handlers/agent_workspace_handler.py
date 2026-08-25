"""Agent workspace file view: list the files on a conversation's workspace
volume for the chat UI.

One event — agent_workspace:list — anyone with workflow access (the same
people who can use the agent chat) gets the listing plus short-lived signed
read URLs; editors and owners also get a volume-scoped upload URL. Both are
served by utils/agent_workspace_routes.py. The workspace source (per-CK
default volume vs. a wired FilesystemNode) resolves from the stored graph via
utils/agent_workspace.resolve_workspace_source, so what the viewer shows is
exactly what the sandbox mounts.
"""
import logging
import uuid as uuid_module
from typing import Callable, Dict

from repositories.workflow import WorkflowRepo
from utils.access_control import Permission, check_resource_access
from utils.agent_workspace import (
    file_url_path,
    list_workspace_files,
    resolve_workspace_source,
    upload_url_path,
)
from utils.database_pool import DatabasePoolMixin
from wss.receiver.client_events import AgentWorkspaceListRequest
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent

logger = logging.getLogger(__name__)


class AgentWorkspaceHandler(DatabasePoolMixin, SocketIOHandler):
    """File listing for a conversation workspace, plus editor-only upload."""

    def __init__(self, sio):
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        return {
            "agent_workspace:list": self.list_files,
        }

    async def _respond(self, sid: str, request_id: str, **data) -> None:
        await send_event(self.sio, sid, ResponseEvent(
            request_id=request_id or "", data=data,
        ))

    async def list_files(self, sid: str, data: AgentWorkspaceListRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id") if session else None
            if not user_id:
                await self._respond(sid, data.request_id, success=False, error="Not authenticated")
                return

            pool = await self.get_pool()
            async with pool.acquire() as conn:
                access = await check_resource_access(
                    conn, str(user_id), "workflow", data.workflow_id
                )
                if not access.has_access:
                    await self._respond(sid, data.request_id, success=False, error="Access denied")
                    return
                row = await WorkflowRepo(pool).get_workflow_org_and_data(
                    conn, uuid_module.UUID(data.workflow_id)
                )

            workflow = (row["workflow"] if row else None) or {}
            if isinstance(workflow, str):
                # jsonb string-scalar corruption is a documented prod reality
                # on this table (the structured-value regression fix audit) — parse it, and let a parse
                # FAILURE raise into the handler's success=False response
                # rather than silently serving a listing off an empty graph.
                import json

                workflow = json.loads(workflow)
            source = resolve_workspace_source(
                data.workflow_id,
                data.node_id,
                data.conversation_key or None,
                workflow.get("nodes") or [],
                workflow.get("edges") or [],
            )
            if source is None:
                # ck-less one-off — the sandbox mounts no durable workspace.
                await self._respond(
                    sid, data.request_id, success=True,
                    workspace=None, files=[], exists=False, truncated=False,
                )
                return

            listing = await list_workspace_files(source.volume_name)
            files = [
                {**f, "url_path": file_url_path(source.volume_name, f["path"])}
                for f in listing["files"]
            ]
            response = {
                "success": True,
                "workspace": source.mount_path,
                "exists": listing["exists"],
                "truncated": listing["truncated"],
                "files": files,
            }
            # VIEW access can inspect the workspace, but only collaborators who
            # may edit the workflow receive a reusable write capability.
            if access.permission in (Permission.EDIT, Permission.OWNER):
                response["upload_url_path"] = upload_url_path(source.volume_name)
            await self._respond(sid, data.request_id, **response)
        except Exception as e:
            logger.error(f"[AgentWorkspace] list failed: {e}", exc_info=True)
            await self._respond(
                sid, data.request_id, success=False, error="Failed to list workspace files"
            )
