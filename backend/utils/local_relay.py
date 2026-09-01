"""In-process event relay for the local edition (NOCLICK_LOCAL=1).

Provides the self-hosted installation's user and workflow relay channels
through one in-process hub. The browser connects to
the same two WebSocket protocols it uses against the hosted relay — served by
utils.local_relay_routes on this backend — and the server-side producers
(ExecutionRelay, broadcast_to_user_safe) publish straight into the hub instead
of over the network. Single-process only: the local edition runs one backend,
so "cross-container delivery" degenerates to an in-memory fan-out.

Protocol parity is deliberate and exact (message shapes mirror user-room.ts /
workflow-room.ts) so the frontend needs no local-mode branches beyond pointing
VITE_RELAY_URL at this backend.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Set

logger = logging.getLogger(__name__)

# Mirrors workflow-room.ts: execution state older than this is stale.
EXECUTION_STATE_TTL_S = 5 * 60

# Collaborator color palette shared across relay implementations.
_COLORS = [
    "#F87171", "#FB923C", "#FBBF24", "#A3E635", "#34D399",
    "#22D3EE", "#60A5FA", "#A78BFA", "#F472B6", "#E879F9",
]


class RelaySocket(Protocol):
    """What the hub needs from a connection — satisfied by starlette WebSocket."""

    async def send_json(self, data: Any) -> None: ...


@dataclass(eq=False)
class UserConn:
    """One browser viewer on the user-events channel (useEventRelay)."""
    socket: RelaySocket
    user_id: str
    workflow_id: Optional[str] = None  # optional subscription filter


@dataclass(eq=False)
class WorkflowConn:
    """One authenticated browser viewer on a workflow room (presence service)."""
    socket: RelaySocket
    workflow_id: str
    collaborator: Dict[str, Any]  # {id, name, avatarUrl, color, connectedAt}


@dataclass
class _ExecutionState:
    execution_id: str
    last_updated: float
    node_states: Dict[str, str] = field(default_factory=dict)
    node_outputs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _StopHandle:
    cancellation_event: asyncio.Event
    execution_task: Optional[asyncio.Task]
    done: asyncio.Event


@dataclass
class _PendingRequest:
    future: "asyncio.Future[dict]"
    collect_ms: int
    client_count: int
    responses: List[dict] = field(default_factory=list)
    collect_timer: Optional[asyncio.TimerHandle] = None


# The presence re-broadcast cadence. Short enough that a dropped clear delta
# heals well inside the frontend's staleness window; long enough to be noise-free.
PRESENCE_REBROADCAST_S = 20.0


class LocalRelayHub:
    """Singleton in-memory fan-out providing both relay channels."""

    def __init__(self) -> None:
        self._user_conns: Dict[str, Set[UserConn]] = {}
        self._workflow_conns: Dict[str, Set[WorkflowConn]] = {}
        self._color_index: Dict[str, int] = {}
        # workflow_id → execution_id → live state (the reconnect-recovery buffer)
        self._executions: Dict[str, Dict[str, _ExecutionState]] = {}
        self._stop_handles: Dict[str, _StopHandle] = {}
        # Stops that arrived before the executor registered its handle.
        self._pending_stops: Set[str] = set()
        self._pending_requests: Dict[str, _PendingRequest] = {}
        # Live agent presence per workflow, keyed (node_id, conversation_key) —
        # the canvas badge / working-indicator signal (relay wire parity).
        self._agent_presence: Dict[str, Dict[tuple, Dict[str, Any]]] = {}
        # Presence deltas are fire-and-forget; the re-broadcast loop is their
        # backstop (see _ensure_presence_rebroadcast).
        self._presence_rebroadcast_task: Optional[asyncio.Task] = None
        self._presence_trailing: Dict[str, int] = {}

    # ── user-events channel (event relay parity) ────────────────────────────

    def register_user_conn(self, conn: UserConn) -> int:
        conns = self._user_conns.setdefault(conn.user_id, set())
        conns.add(conn)
        return len(conns)

    def unregister_user_conn(self, conn: UserConn) -> None:
        conns = self._user_conns.get(conn.user_id)
        if conns:
            conns.discard(conn)
            if not conns:
                self._user_conns.pop(conn.user_id, None)

    async def publish_user_event(
        self, user_id: str, event: Dict[str, Any], workflow_id: Optional[str] = None,
    ) -> int:
        """Fan an event out to the user's connected frontends.

        Mirrors event relay.broadcast: a workflow-tagged event skips viewers
        subscribed to a DIFFERENT workflow; unsubscribed viewers get everything.
        """
        sent = 0
        for conn in list(self._user_conns.get(user_id, ())):
            if workflow_id and conn.workflow_id and conn.workflow_id != workflow_id:
                continue
            if await self._send(conn.socket, event, conn):
                sent += 1
        return sent

    async def request_frontend(
        self, user_id: str, request_type: str, params: dict,
        timeout: float = 10.0, collect_ms: int = 0,
    ) -> dict:
        """Request/response to the user's frontends (event relay /request parity).

        Sends an mcp_request frame to every viewer and awaits mcp_response.
        collect_ms > 0 switches to multi-response collection: resolve with
        {"responses": [...]} once all clients answered or the window elapses.
        """
        conns = list(self._user_conns.get(user_id, ()))
        if not conns:
            return {"error": "No browser sessions connected"}

        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        pending = _PendingRequest(
            future=loop.create_future(), collect_ms=collect_ms, client_count=len(conns),
        )
        self._pending_requests[request_id] = pending

        frame = {
            "type": "mcp_request",
            "request_id": request_id,
            "request_type": request_type,
            "params": params,
        }
        for conn in conns:
            await self._send(conn.socket, frame, conn)

        try:
            return await asyncio.wait_for(pending.future, timeout=timeout)
        except asyncio.TimeoutError:
            return {"error": f"Request timed out after {timeout}s"}
        finally:
            if pending.collect_timer is not None:
                pending.collect_timer.cancel()
            self._pending_requests.pop(request_id, None)

    def resolve_frontend_response(
        self, request_id: str, data: Any, error: Optional[str],
    ) -> None:
        """Called by the WS route when a viewer sends an mcp_response frame."""
        pending = self._pending_requests.get(request_id)
        if pending is None or pending.future.done():
            return
        if pending.collect_ms:
            pending.responses.append({"data": data, "error": error})
            if len(pending.responses) >= pending.client_count:
                pending.future.set_result({"responses": pending.responses})
            elif pending.collect_timer is None:
                loop = asyncio.get_running_loop()
                pending.collect_timer = loop.call_later(
                    pending.collect_ms / 1000,
                    lambda: (
                        pending.future.set_result({"responses": pending.responses})
                        if not pending.future.done() else None
                    ),
                )
        else:
            pending.future.set_result({"data": data, "error": error})

    # ── workflow rooms (workflow relay parity) ─────────────────────────────

    def register_workflow_conn(
        self, workflow_id: str, socket: RelaySocket,
        user_id: str, name: str, avatar_url: Optional[str],
    ) -> WorkflowConn:
        idx = self._color_index.get(workflow_id, 0)
        self._color_index[workflow_id] = idx + 1
        conn = WorkflowConn(
            socket=socket,
            workflow_id=workflow_id,
            collaborator={
                "id": user_id,
                "name": name,
                "avatarUrl": avatar_url,
                "color": _COLORS[idx % len(_COLORS)],
                "connectedAt": int(time.time() * 1000),
            },
        )
        self._workflow_conns.setdefault(workflow_id, set()).add(conn)
        return conn

    def unregister_workflow_conn(self, conn: WorkflowConn) -> None:
        conns = self._workflow_conns.get(conn.workflow_id)
        if conns:
            conns.discard(conn)
            if not conns:
                self._workflow_conns.pop(conn.workflow_id, None)

    def collaborators(
        self, workflow_id: str, exclude: Optional[WorkflowConn] = None,
    ) -> List[Dict[str, Any]]:
        return [
            c.collaborator
            for c in self._workflow_conns.get(workflow_id, ())
            if c is not exclude
        ]

    async def broadcast_to_workflow(
        self, workflow_id: str, event: Dict[str, Any],
        exclude: Optional[WorkflowConn] = None,
    ) -> int:
        sent = 0
        for conn in list(self._workflow_conns.get(workflow_id, ())):
            if conn is exclude:
                continue
            if await self._send(conn.socket, event, conn):
                sent += 1
        return sent

    # ── execution events + recovery buffer ───────────────────────────────

    async def publish_execution_event(
        self, workflow_id: str, event: Dict[str, Any],
    ) -> None:
        self._update_execution_state(workflow_id, event)
        await self.broadcast_to_workflow(workflow_id, event)

    def _update_execution_state(self, workflow_id: str, event: Dict[str, Any]) -> None:
        exec_id = event.get("execution_id")
        etype = event.get("type")
        if not exec_id:
            return
        states = self._executions.setdefault(workflow_id, {})
        if etype == "workflow:started":
            states[exec_id] = _ExecutionState(execution_id=exec_id, last_updated=time.time())
        elif etype == "workflow:node:state":
            state = states.get(exec_id)
            if state and event.get("node_id"):
                state.node_states[event["node_id"]] = event.get("state", "")
                state.last_updated = time.time()
        elif etype == "workflow:node:output":
            state = states.get(exec_id)
            if state and event.get("node_id") and event.get("output") is not None:
                state.node_outputs[event["node_id"]] = event["output"]
                state.last_updated = time.time()
        elif etype == "workflow:complete":
            states.pop(exec_id, None)
            if not states:
                self._executions.pop(workflow_id, None)

    def execution_state_snapshot(self, workflow_id: str) -> Dict[str, Any]:
        """The get:execution_state response, agent presence included — a
        mounting viewer gets the live set with zero extra requests."""
        states = self._executions.get(workflow_id, {})
        now = time.time()
        for exec_id in [i for i, s in states.items() if now - s.last_updated > EXECUTION_STATE_TTL_S]:
            states.pop(exec_id)
        return {
            "type": "execution_state",
            "executions": [
                {
                    "executionId": s.execution_id,
                    "nodeStates": s.node_states,
                    "nodeOutputs": s.node_outputs,
                }
                for s in states.values()
            ],
            "agents": self._agents_wire(workflow_id),
        }

    # ── agent presence (canvas badge / working indicator) ────────────────

    def _agents_wire(self, workflow_id: str) -> List[Dict[str, Any]]:
        return [
            {"nodeId": k[0], "conversationKey": k[1], "userId": p["user_id"], "busy": p["busy"]}
            for k, p in self._agent_presence.get(workflow_id, {}).items()
        ]

    async def set_agent_presence(
        self, workflow_id: str, node_id: str, conversation_key: str,
        user_id: str, busy: bool,
    ) -> None:
        """Upsert one agent's presence; broadcast a delta only on change
        (a steady refresh beat is silent — relay parity)."""
        agents = self._agent_presence.setdefault(workflow_id, {})
        key = (node_id, conversation_key)
        prev = agents.get(key)
        agents[key] = {"user_id": user_id, "busy": busy}
        self._presence_trailing.pop(workflow_id, None)
        self._ensure_presence_rebroadcast()
        if prev is None or prev["busy"] != busy:
            await self.broadcast_to_workflow(
                workflow_id, {"type": "agent:presence", "agents": self._agents_wire(workflow_id)},
            )

    async def clear_agent_presence(
        self, workflow_id: str, node_id: str, conversation_key: str,
    ) -> None:
        agents = self._agent_presence.get(workflow_id)
        if agents and agents.pop((node_id, conversation_key), None) is not None:
            if not agents:
                self._agent_presence.pop(workflow_id, None)
                # A couple of trailing empty snapshots so a lost clear delta
                # still heals; the loop stops once they are spent.
                self._presence_trailing[workflow_id] = 2
                self._ensure_presence_rebroadcast()
            await self.broadcast_to_workflow(
                workflow_id, {"type": "agent:presence", "agents": self._agents_wire(workflow_id)},
            )

    def _ensure_presence_rebroadcast(self) -> None:
        """Presence deltas ride one fire-and-forget websocket send; a lost
        CLEAR used to leave every viewer's working indicator lit forever —
        there is no heartbeat backstop here (2026-09-01 stuck orb). While any
        agent is busy, and for a couple of trailing ticks after the last one
        clears, the full snapshot re-broadcasts: a dropped delta heals in
        seconds, and the frontend's presence-freshness clock keeps ticking
        through genuinely long turns instead of going stale mid-run."""
        task = self._presence_rebroadcast_task
        if task is None or task.done():
            self._presence_rebroadcast_task = asyncio.create_task(
                self._presence_rebroadcast_loop()
            )

    async def _presence_rebroadcast_loop(self) -> None:
        while True:
            await asyncio.sleep(PRESENCE_REBROADCAST_S)
            live = set(self._agent_presence)
            trailing = set(self._presence_trailing) - live
            if not live and not trailing:
                return
            for wf in live | trailing:
                await self.broadcast_to_workflow(
                    wf, {"type": "agent:presence", "agents": self._agents_wire(wf)},
                )
            for wf in trailing:
                left = self._presence_trailing.get(wf, 0) - 1
                if left <= 0:
                    self._presence_trailing.pop(wf, None)
                else:
                    self._presence_trailing[wf] = left

    def has_live_execution(self, workflow_id: str, execution_id: str) -> bool:
        return execution_id in self._executions.get(workflow_id, {})

    # ── stop signals ─────────────────────────────────────────────────────

    def register_stop_handle(
        self, execution_id: str,
        cancellation_event: asyncio.Event,
        execution_task: Optional[asyncio.Task],
    ) -> _StopHandle:
        handle = _StopHandle(
            cancellation_event=cancellation_event,
            execution_task=execution_task,
            done=asyncio.Event(),
        )
        self._stop_handles[execution_id] = handle
        # A viewer's stop can land before the executor registers (sub-second
        # window between run start and the listen task spawning) — honor it now.
        if execution_id in self._pending_stops:
            self._pending_stops.discard(execution_id)
            self.fire_stop(execution_id)
        return handle

    def unregister_stop_handle(self, execution_id: str) -> None:
        handle = self._stop_handles.pop(execution_id, None)
        if handle:
            handle.done.set()
        self._pending_stops.discard(execution_id)

    def fire_stop(self, execution_id: str) -> bool:
        handle = self._stop_handles.get(execution_id)
        if handle is None:
            self._pending_stops.add(execution_id)
            return False
        logger.info(f"[LocalRelay] Stop signal for execution {execution_id[:8]}")
        handle.cancellation_event.set()
        if handle.execution_task is not None and not handle.execution_task.done():
            handle.execution_task.cancel()
        handle.done.set()
        return True

    # ── internals ────────────────────────────────────────────────────────

    async def _send(self, socket: RelaySocket, data: Dict[str, Any], conn: Any) -> bool:
        try:
            await socket.send_json(data)
            return True
        except Exception:
            # Dead socket — drop the registration so we stop retrying it.
            if isinstance(conn, UserConn):
                self.unregister_user_conn(conn)
            elif isinstance(conn, WorkflowConn):
                self.unregister_workflow_conn(conn)
            return False


_hub: Optional[LocalRelayHub] = None


def get_local_relay_hub() -> LocalRelayHub:
    global _hub
    if _hub is None:
        _hub = LocalRelayHub()
    return _hub


class LocalExecutionRelay:
    """Drop-in for utils.execution_relay.ExecutionRelay in the local edition.

    Same duck-typed surface (connected / start / connect / ready / send_event /
    listen_for_stop / close / connect_error), but events go straight into the
    in-process hub — no WebSocket, no handshake, so it can never fail to
    connect and on_connect_failure never fires.
    """

    def __init__(
        self,
        workflow_id: str,
        execution_id: str,
        user_id: str,
        on_connect_failure=None,  # accepted for signature parity; unused
    ):
        self.workflow_id = workflow_id
        self.execution_id = execution_id
        self.user_id = user_id
        self.connect_error: Optional[str] = None
        self._active = False
        self._hub = get_local_relay_hub()

    @property
    def connected(self) -> bool:
        return self._active

    def start(self) -> None:
        self._active = True

    async def connect(self, timeout: float = 10.0) -> bool:
        self.start()
        return True

    async def ready(self) -> bool:
        return self._active

    async def send_event(self, event: dict) -> None:
        if not self._active:
            return
        # The relay stamps the executor's execution_id onto every event (events
        # like workflow:node:output omit it in their schema) — mirror that so
        # the recovery buffer and multi-execution FE disambiguation work.
        event["execution_id"] = self.execution_id
        await self._hub.publish_execution_event(self.workflow_id, event)

    async def listen_for_stop(
        self,
        cancellation_event: asyncio.Event,
        execution_task: Optional[asyncio.Task] = None,
    ) -> None:
        handle = self._hub.register_stop_handle(
            self.execution_id, cancellation_event, execution_task,
        )
        await handle.done.wait()

    async def close(self) -> None:
        self._active = False
        self._hub.unregister_stop_handle(self.execution_id)
        # relay parity: an executor vanishing with live execution state means the
        # run never sent workflow:complete — tell viewers it died.
        if self._hub.has_live_execution(self.workflow_id, self.execution_id):
            await self._hub.publish_execution_event(self.workflow_id, {
                "type": "workflow:complete",
                "execution_id": self.execution_id,
                "workflow_id": self.workflow_id,
                "success": False,
                "nodes_executed": 0,
                "duration": 0,
                "error": "Execution ended unexpectedly",
            })
