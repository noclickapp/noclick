"""WebSocket routes serving the event-relay protocols in the local edition.

Mounted only when NOCLICK_LOCAL=1 (server.py). The browser's user-event and
workflow-room clients connect here when VITE_RELAY_URL points at
ws://<backend>/relay. Message shapes follow the shared relay contract; see
utils.local_relay for the in-process hub.
"""

import json
import logging
import os
import time

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from utils.local_relay import UserConn, get_local_relay_hub

logger = logging.getLogger(__name__)

router = APIRouter()

# Viewer fan-out vocabulary (workflow relay parity): inbound type → payload keys
# copied through. Everything broadcasts to the OTHER viewers with the sender's
# userId stamped; unknown keys are dropped so a client can't inject fields.
_VIEWER_FANOUT: dict[str, tuple[str, ...]] = {
    "presence:cursor": ("x", "y"),
    "presence:cursor:clear": (),
    "presence:selection": ("nodeIds",),
    "node:drag": ("nodeId", "position"),
    "node:add": ("node",),
    "node:remove": ("nodeId",),
    "node:update": ("nodeId", "data"),
    "edge:add": ("edge",),
    "edge:remove": ("edgeId",),
    "ai:editing:start": ("nodeIds",),
    "ai:editing:update": ("nodeId", "info"),
    "ai:editing:end": (),
}


def _verify_workflow_token(token: str, workflow_id: str) -> dict:
    secret = os.environ.get("WORKFLOW_JWT_SECRET", "")
    if not secret:
        raise ValueError("WORKFLOW_JWT_SECRET not configured")
    payload = jwt.decode(token, secret, algorithms=["HS256"])
    if payload.get("workflowId") != workflow_id:
        raise ValueError("Token workflow mismatch")
    return payload


@router.websocket("/relay/workflow/{workflow_id}")
async def workflow_room(websocket: WebSocket, workflow_id: str):
    """workflow relay: collaborative presence + execution events + stop signals."""
    hub = get_local_relay_hub()
    await websocket.accept()
    await websocket.send_json({"type": "auth:required"})

    conn = None
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue
            mtype = msg.get("type")

            if mtype == "auth":
                try:
                    payload = _verify_workflow_token(msg.get("token", ""), workflow_id)
                except Exception as e:
                    await websocket.send_json({"type": "auth:error", "message": str(e) or "Invalid token"})
                    await websocket.close(code=4401)
                    return
                if payload.get("role") == "executor":
                    # Local executors publish in-process (LocalExecutionRelay) —
                    # nothing should connect here as executor.
                    await websocket.send_json({"type": "auth:error", "message": "Executor WS not supported locally"})
                    await websocket.close(code=4401)
                    return
                conn = hub.register_workflow_conn(
                    workflow_id, websocket,
                    user_id=payload.get("sub", ""),
                    name=payload.get("name", "Anonymous"),
                    avatar_url=payload.get("avatarUrl"),
                )
                await websocket.send_json({
                    "type": "auth:success",
                    "collaborators": hub.collaborators(workflow_id, exclude=conn),
                })
                await hub.broadcast_to_workflow(
                    workflow_id,
                    {"type": "collaborator:join", "collaborator": conn.collaborator},
                    exclude=conn,
                )
                continue

            if conn is None:
                await websocket.send_json({"type": "error", "message": "Not authenticated"})
                continue

            if mtype == "ping":
                await websocket.send_json({"type": "pong", "timestamp": int(time.time() * 1000)})
            elif mtype == "get:execution_state":
                await websocket.send_json(hub.execution_state_snapshot(workflow_id))
            elif mtype == "execution:stop":
                if msg.get("executionId"):
                    hub.fire_stop(str(msg["executionId"]))
            elif mtype in _VIEWER_FANOUT:
                out = {"type": mtype, "userId": conn.collaborator["id"]}
                for key in _VIEWER_FANOUT[mtype]:
                    out[key] = msg.get(key)
                await hub.broadcast_to_workflow(workflow_id, out, exclude=conn)
    except WebSocketDisconnect:
        pass
    finally:
        if conn is not None:
            hub.unregister_workflow_conn(conn)
            await hub.broadcast_to_workflow(
                workflow_id,
                {"type": "collaborator:leave", "userId": conn.collaborator["id"]},
            )


@router.websocket("/relay/{user_id}")
async def user_room(websocket: WebSocket, user_id: str):
    """event relay: broadcast channel for webhook/cron/builder events + mcp requests."""
    hub = get_local_relay_hub()
    await websocket.accept()
    conn = UserConn(
        socket=websocket,
        user_id=user_id,
        workflow_id=websocket.query_params.get("workflowId") or None,
    )
    count = hub.register_user_conn(conn)
    await websocket.send_json({
        "type": "connected",
        "connectionCount": count,
        "timestamp": int(time.time() * 1000),
    })

    try:
        while True:
            raw = await websocket.receive_text()
            # Keepalive is raw text, not JSON (relay auto-response parity).
            if raw == "ping":
                await websocket.send_text("pong")
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid message format"})
                continue
            mtype = msg.get("type")

            if mtype == "subscribe":
                if msg.get("workflowId"):
                    conn.workflow_id = str(msg["workflowId"])
                    await websocket.send_json({"type": "subscribed", "workflowId": conn.workflow_id})
            elif mtype == "unsubscribe":
                conn.workflow_id = None
                await websocket.send_json({"type": "unsubscribed"})
            elif mtype == "mcp_response":
                hub.resolve_frontend_response(
                    str(msg.get("request_id", "")), msg.get("data"), msg.get("error") or None,
                )
            else:
                await websocket.send_json({"type": "echo", "received": msg, "timestamp": int(time.time() * 1000)})
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister_user_conn(conn)
