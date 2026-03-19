"""
Main SDK client. Connects to NoClick backend via Socket.IO.
"""

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

import socketio

from noclick.namespaces import (
    NodesNamespace,
    ExecutionNamespace,
    StateNamespace,
    AuthNamespace,
    ResourcesNamespace,
    DatasetNamespace,
    WorkflowNamespace,
)

logger = logging.getLogger("noclick")

DEFAULT_TIMEOUT = 30.0


class Client:
    """
    NoClick SDK client for Python.

    Connects to the NoClick backend via Socket.IO using an API key.
    Provides namespaced access to nodes, execution, state, auth, resources, and dataset APIs.
    """

    def __init__(
        self,
        api_key: str,
        url: str = "https://api.noclick.io",
        workflow_id: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.url = url
        self.api_key = api_key
        self.workflow_id = workflow_id
        self.timeout = timeout

        self._sio = socketio.AsyncClient(reconnection=True, reconnection_attempts=5)
        self._pending: Dict[str, asyncio.Future] = {}
        self._event_handlers: Dict[str, List[Any]] = {}

        # Register response handler
        self._sio.on("response", self._handle_response)
        self._sio.on("workflow:node:output", self._handle_node_output)
        self._sio.on("workflow:node:state", self._handle_node_state)
        self._sio.on("workflow:complete", self._handle_workflow_complete)

        # Namespaces
        self.nodes = NodesNamespace(self)
        self.execution = ExecutionNamespace(self)
        self.state = StateNamespace(self)
        self.auth = AuthNamespace(self)
        self.resources = ResourcesNamespace(self)
        self.dataset = DatasetNamespace(self)
        self.workflow = WorkflowNamespace(self)

    async def connect(self) -> None:
        """Connect to the NoClick backend."""
        logger.info(f"Connecting to {self.url}...")
        await self._sio.connect(
            self.url,
            auth={"api_key": self.api_key},
            transports=["websocket"],
        )
        logger.info("Connected")

    async def disconnect(self) -> None:
        """Disconnect from the backend."""
        await self._sio.disconnect()
        logger.info("Disconnected")

    async def send_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a socket event and wait for a response.

        Uses request_id correlation to match request → response.
        """
        request_id = f"py-{uuid.uuid4().hex[:12]}"
        data["request_id"] = request_id

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[request_id] = future

        await self._sio.emit(event, data)

        try:
            result = await asyncio.wait_for(future, timeout=self.timeout)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise TimeoutError(f"Request '{event}' timed out after {self.timeout}s")

    async def send_event_no_wait(self, event: str, data: Dict[str, Any]) -> None:
        """Send a socket event without waiting for a response."""
        request_id = f"py-{uuid.uuid4().hex[:12]}"
        data["request_id"] = request_id
        await self._sio.emit(event, data)

    def on_event(self, event: str, handler) -> None:
        """Subscribe to push events."""
        if event not in self._event_handlers:
            self._event_handlers[event] = []
        self._event_handlers[event].append(handler)

    def _handle_response(self, data: Any) -> None:
        """Handle response events, resolving pending futures."""
        if not isinstance(data, dict):
            return
        request_id = data.get("request_id")
        if not request_id:
            return
        future = self._pending.pop(request_id, None)
        if future and not future.done():
            if data.get("error"):
                future.set_exception(Exception(str(data["error"])))
            else:
                future.set_result(data.get("data", data))

    def _handle_node_output(self, data: Any) -> None:
        for handler in self._event_handlers.get("node:output", []):
            handler(data.get("node_id"), data.get("output"))

    def _handle_node_state(self, data: Any) -> None:
        for handler in self._event_handlers.get("node:state", []):
            handler(data.get("node_id"), data.get("state"))

    def _handle_workflow_complete(self, data: Any) -> None:
        for handler in self._event_handlers.get("workflow:complete", []):
            handler(data)
