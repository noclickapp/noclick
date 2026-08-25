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
    sanitize_volume_path,
    upload_url_path,
)
from utils.database_pool import DatabasePoolMixin
from wss.receiver.client_events import (
    AgentWorkspaceDeleteRequest,
    AgentWorkspaceListRequest,
)
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
            "agent_workspace:delete": self.delete_file,
        }

    async def _respond(self, sid: str, request_id: str, **data) -> None:
        await send_event(self.sio, sid, ResponseEvent(
            request_id=request_id or "", data=data,
        ))

    async def _authorize_and_resolve(self, sid: str, data):
        """Shared gate for every workspace event: authenticate, check workflow
        access, and resolve the workspace source from the STORED graph.

        Returns ``(source, access)`` on success — ``source`` is None for a
        conversation without a durable workspace. Returns ``(None, None)``
        when an error response has already been sent."""
        session = await self.sio.get_session(sid)
        user_id = session.get("user_id") if session else None
        if not user_id:
            await self._respond(sid, data.request_id, success=False, error="Not authenticated")
            return None, None

        pool = await self.get_pool()
        async with pool.acquire() as conn:
            access = await check_resource_access(
                conn, str(user_id), "workflow", data.workflow_id
            )
            if not access.has_access:
                await self._respond(sid, data.request_id, success=False, error="Access denied")
                return None, None
            row = await WorkflowRepo(pool).get_workflow_org_and_data(
                conn, uuid_module.UUID(data.workflow_id)
            )

        workflow = (row["workflow"] if row else None) or {}
        if isinstance(workflow, str):
            # Parse legacy string-scalar rows. A parse failure should surface
            # through the caller's error response rather than silently using
            # an empty graph.
            import json

            workflow = json.loads(workflow)
        source = resolve_workspace_source(
            data.workflow_id,
            data.node_id,
            data.conversation_key or None,
            workflow.get("nodes") or [],
            workflow.get("edges") or [],
        )
        return source, access

    async def list_files(self, sid: str, data: AgentWorkspaceListRequest) -> None:
        try:
            source, access = await self._authorize_and_resolve(sid, data)
            if access is None:
                return
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

    async def delete_file(self, sid: str, data: AgentWorkspaceDeleteRequest) -> None:
        try:
            source, access = await self._authorize_and_resolve(sid, data)
            if access is None:
                return
            if access.permission not in (Permission.EDIT, Permission.OWNER):
                await self._respond(
                    sid, data.request_id, success=False, error="Edit access required"
                )
                return
            if source is None:
                await self._respond(
                    sid, data.request_id, success=False,
                    error="No workspace for this conversation",
                )
                return
            rel = sanitize_volume_path(data.path)
            if not rel:
                await self._respond(sid, data.request_id, success=False, error="Invalid file path")
                return

            from utils.volume_backend import get_volume_backend

            await get_volume_backend().delete_file(source.volume_name, rel)
            await self._respond(sid, data.request_id, success=True, path=rel)
        except Exception as e:
            logger.error(f"[AgentWorkspace] delete failed: {e}", exc_info=True)
            await self._respond(
                sid, data.request_id, success=False, error="Failed to delete file"
            )
