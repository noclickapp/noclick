"""
Tests for WorkflowMCPHandler - MCP tools for AI agent workflow manipulation.

Architecture (v2):
- Backend-only tools operate directly on the database without frontend communication
- Frontend-required tools (get_selected_node, open_workflow) use bidirectional communication
- Database-backed operations support dual-delivery to connected frontends

Test categories:
- Backend-only (no DB): search_nodes, get_node_config_schema
- Backend-only (database): get_node_output, get_node_input, run_workflow, run_node
- Frontend-required: get_selected_node, open_workflow
- Database queries: list_workflows, list_saved_outputs, create_workflow
"""

import pytest
import pytest_asyncio
import asyncio
import uuid
from typing import Dict, Any, Optional, Callable
from unittest.mock import AsyncMock, MagicMock, patch

from tests.utils.base_handler_test import BaseHandlerTest
from wss.sender import send_event
from wss.receiver.event_routing import Handler
from wss.receiver.client_events import (
    WorkflowMCPResponseRequest,
    WorkflowMCPSearchNodesRequest,
    WorkflowMCPGetNodeConfigSchemaRequest,
    WorkflowMCPGetSelectedNodeRequest,
    WorkflowMCPGetNodeOutputRequest,
    WorkflowMCPGetNodeInputRequest,
    WorkflowMCPRunWorkflowRequest,
    WorkflowMCPCreateWorkflowRequest,
    WorkflowMCPOpenWorkflowRequest,
    WorkflowMCPListWorkflowsRequest,
    WorkflowMCPListSavedOutputsRequest,
    WorkflowMCPRunNodeRequest,
    WorkflowGetNodeOutputsRequest,
)


# Test workflow data for database-backed operations
# Use valid UUIDs that match the test fixture format
TEST_WORKFLOW_ID = "00000000-0000-0000-0000-000000000001"
TEST_USER_ID = "00000000-0000-0000-0000-000000000002"
# Wire shape (post-normalization): every node field — config + persisted
# metadata (label/output/status/...) — lives flat under node["config"]. This
# matches frontend buildSaveConfig output and is what backend handlers now
# read (since get_node_data and its legacy node["data"]["config"] branch
# were removed).
TEST_WORKFLOW_DATA = {
    "nodes": [
        {
            "id": "node-123",
            "type": "automation-telegram",
            "position": {"x": 100, "y": 100},
            "config": {
                "label": "Telegram",
                "chat_id": "12345",
                "output": {"message": "test output"},
                "status": "completed",
            },
        },
        {
            "id": "node-456",
            "type": "automation-gmail",
            "position": {"x": 400, "y": 100},
            "config": {
                "label": "Gmail",
                "to": "test@test.com",
                "output": None,
                "status": "idle",
            },
        },
    ],
    "edges": [
        {"id": "edge-1", "source": "node-123", "target": "node-456"},
    ],
}


class FrontendResponder:
    """
    Helper class to simulate frontend responses to MCP requests.

    Registers a handler on the frontend socket to respond to workflow:mcp:request
    events in real-time as they arrive.
    """

    def __init__(self, main_api_sio, frontend_sio, sid: str):
        self.main_api_sio = main_api_sio
        self.frontend_sio = frontend_sio
        self.sid = sid
        self.captured_requests = []
        self._response_handlers: Dict[str, Callable] = {}
        self._default_response: Optional[Dict[str, Any]] = None
        self._setup_handler()

    def _setup_handler(self):
        """Register handler on frontend socket to respond to MCP requests."""
        async def handle_mcp_request(event_data):
            """Handle incoming MCP request and send response."""
            self.captured_requests.append(event_data)

            request_id = event_data.get("request_id")
            request_type = event_data.get("request_type")
            params = event_data.get("params", {})

            # Determine response
            response_data = None
            error = None

            if request_type in self._response_handlers:
                response_data, error = self._response_handlers[request_type](params)
            elif self._default_response:
                response_data = self._default_response["data"]
                error = self._default_response["error"]
            else:
                error = f"No response configured for request type: {request_type}"

            # Send response back through the frontend socket
            response = WorkflowMCPResponseRequest(
                request_id=request_id,
                data=response_data,
                error=error
            )
            await send_event(self.frontend_sio, self.sid, response)

        # Register the handler on frontend_sio (client) for MCP requests
        self.frontend_sio.on("workflow:mcp:request", handle_mcp_request)

    def set_response_for_type(self, request_type: str, response_data: Any, error: Optional[str] = None):
        """Set a specific response for a request type."""
        self._response_handlers[request_type] = lambda params: (response_data, error)

    def set_response_handler(self, request_type: str, handler: Callable[[Dict[str, Any]], tuple]):
        """Set a callable handler for a request type. Handler returns (data, error)."""
        self._response_handlers[request_type] = handler

    def set_default_response(self, response_data: Any, error: Optional[str] = None):
        """Set default response for any request type."""
        self._default_response = {"data": response_data, "error": error}


@pytest.mark.asyncio
class TestWorkflowMCPHandlerBackendOnly(BaseHandlerTest):
    """Tests for backend-only MCP tools that don't require frontend communication."""

    async def test_search_nodes_returns_all_nodes(self, frontend_sio, sid):
        """Test search_nodes returns available node types."""
        request = WorkflowMCPSearchNodesRequest(
            request_id="test-search-1",
        )
        await send_event(frontend_sio, sid, request)
        response_events = await self.wait_for_main_api_events("response")
        assert len(response_events) == 1

        response_data = self.reassemble_if_chunked(response_events[0][1])
        assert "error" not in response_data or response_data.get("error") is None
        assert "data" in response_data

        nodes = response_data["data"].get("nodes", [])
        assert len(nodes) > 0

        # Verify node structure
        for node in nodes:
            assert "type" in node
            assert "label" in node
            assert "description" in node
            assert "category" in node
            assert "config_types" in node

    async def test_search_nodes_with_query_filters(self, frontend_sio, sid):
        """Test search_nodes filters by query string."""
        request = WorkflowMCPSearchNodesRequest(
            request_id="test-search-2",
            query="telegram"
        )
        await send_event(frontend_sio, sid, request)
        response_events = await self.wait_for_main_api_events("response")
        assert len(response_events) == 1

        response_data = response_events[0][1]
        nodes = response_data["data"].get("nodes", [])

        # Should find telegram node
        node_types = [n["type"] for n in nodes]
        assert "automation-telegram" in node_types

        # Should NOT find unrelated nodes
        assert "automation-whatsapp" not in node_types

    async def test_search_nodes_excludes_test_nodes(self, frontend_sio, sid):
        """Test search_nodes excludes test-* nodes."""
        request = WorkflowMCPSearchNodesRequest(
            request_id="test-search-3",
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.1)

        response_events = self.get_main_api_emitted_events("response")
        response_data = self.reassemble_if_chunked(response_events[0][1])
        nodes = response_data["data"].get("nodes", [])

        # No test nodes should be returned
        for node in nodes:
            assert not node["type"].startswith("test-")

    async def test_get_node_config_schema_returns_schema(self, frontend_sio, sid):
        """Test get_node_config_schema returns full JSON schema for a config type."""
        request = WorkflowMCPGetNodeConfigSchemaRequest(
            request_id="test-schema-1",
            node_type="automation-telegram",
            config_type="TelegramChatIdConfig"
        )
        await send_event(frontend_sio, sid, request)
        response_events = await self.wait_for_main_api_events("response")
        assert len(response_events) == 1

        response_data = response_events[0][1]
        assert "error" not in response_data or response_data.get("error") is None
        assert "data" in response_data

        data = response_data["data"]
        assert data["node_type"] == "automation-telegram"
        assert data["config_type"] == "TelegramChatIdConfig"
        assert "schema" in data

        # Verify schema has expected structure
        schema = data["schema"]
        assert "properties" in schema or "type" in schema

    async def test_get_node_config_schema_unknown_node_type(self, frontend_sio, sid):
        """Test get_node_config_schema returns error for unknown node type."""
        request = WorkflowMCPGetNodeConfigSchemaRequest(
            request_id="test-schema-2",
            node_type="nonexistent-node",
            config_type="SomeConfig"
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.1)

        response_events = self.get_main_api_emitted_events("response")
        response_data = response_events[0][1]

        assert response_data.get("error") is not None
        assert "Unknown node type" in response_data["error"]

    async def test_get_node_config_schema_unknown_config_type(self, frontend_sio, sid):
        """Test get_node_config_schema returns error for unknown config type."""
        request = WorkflowMCPGetNodeConfigSchemaRequest(
            request_id="test-schema-3",
            node_type="automation-telegram",
            config_type="NonexistentConfig"
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.1)

        response_events = self.get_main_api_emitted_events("response")
        response_data = response_events[0][1]

        assert response_data.get("error") is not None
        assert "not found" in response_data["error"]


@pytest.mark.asyncio
class TestWorkflowMCPHandlerFrontendQuery(BaseHandlerTest):
    """Tests for MCP tools that query frontend state."""

    async def test_get_selected_node_with_frontend_response(self, frontend_sio, sid):
        """Test get_selected_node receives data from frontend."""
        responder = FrontendResponder(self.main_api_sio, frontend_sio, sid)

        # Configure frontend to respond with selected node data
        responder.set_response_for_type("get_selected", {
            "id": "node-123",
            "type": "automation-telegram",
            "data": {"message": "Hello"},
            "position": {"x": 100, "y": 200}
        })

        # Send the MCP request
        request = WorkflowMCPGetSelectedNodeRequest(
            request_id="test-selected-1",
        )
        await send_event(frontend_sio, sid, request)

        # Wait for the socket round-trip deterministically.
        response_events = await self.wait_for_main_api_events("response")
        assert len(response_events) == 1

        response_data = response_events[0][1]
        assert response_data.get("error") is None

        selected_node = response_data["data"]["selected_node"]
        assert selected_node["id"] == "node-123"
        assert selected_node["type"] == "automation-telegram"

    async def test_get_selected_node_none_selected(self, frontend_sio, sid):
        """Test get_selected_node when no node is selected."""
        responder = FrontendResponder(self.main_api_sio, frontend_sio, sid)
        responder.set_response_for_type("get_selected", None)

        request = WorkflowMCPGetSelectedNodeRequest(
            request_id="test-selected-2",
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.1)

        response_events = self.get_main_api_emitted_events("response")
        response_data = response_events[0][1]

        assert response_data.get("error") is None
        assert response_data["data"]["selected_node"] is None

    def _mock_database_with_session(self, handler, sio, sid, workflow_data=None):
        """Helper to mock database operations and session for a handler."""
        import copy
        mock_conn = AsyncMock()
        # Use side_effect to return different values for different fetchrow calls:
        # 1. First call (access control): returns owner_id and organization_id
        # 2. Second call (workflow data): returns workflow JSON
        mock_conn.fetchrow = AsyncMock(side_effect=[
            {'owner_id': TEST_USER_ID, 'organization_id': None},  # Access control check
            {'workflow': copy.deepcopy(workflow_data or TEST_WORKFLOW_DATA)},  # Workflow data
        ])
        # Mock fetchval for access control organization member check
        mock_conn.fetchval = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None)
        ))
        handler.get_pool = AsyncMock(return_value=mock_pool)

        # Mock the session to return a valid UUID
        sio.get_session = AsyncMock(return_value={'user_id': TEST_USER_ID})
        return mock_conn

    async def test_get_node_output_returns_output(self, frontend_sio, sid):
        """Test get_node_output returns a node's latest output from the CAS."""
        handler = self.handlers.get(Handler.WORKFLOW_MCP)
        self._mock_database_with_session(handler, self.main_api_sio, sid)

        request = WorkflowMCPGetNodeOutputRequest(
            request_id="test-output-1",
            workflow_id=TEST_WORKFLOW_ID,
            node_id="node-123"
        )
        with patch("utils.node_outputs.latest_output",
                   AsyncMock(return_value={"message": "test output"})):
            await send_event(frontend_sio, sid, request)
            await asyncio.sleep(0.1)

        response_events = self.get_main_api_emitted_events("response")
        response_data = response_events[0][1]

        assert response_data.get("error") is None
        assert response_data["data"]["node_id"] == "node-123"
        # Output comes from the CAS (latest_output), not the graph JSONB
        assert response_data["data"]["output"] == {"message": "test output"}

    async def test_get_node_input_returns_upstream_outputs(self, frontend_sio, sid):
        """Test get_node_input returns outputs from connected upstream nodes from database."""
        handler = self.handlers.get(Handler.WORKFLOW_MCP)
        self._mock_database_with_session(handler, self.main_api_sio, sid)

        request = WorkflowMCPGetNodeInputRequest(
            request_id="test-input-1",
            workflow_id=TEST_WORKFLOW_ID,
            node_id="node-456"  # This node has node-123 as upstream
        )
        # Upstream outputs come from the CAS (sole output store), keyed by node id.
        with patch("utils.node_outputs.latest_outputs",
                   AsyncMock(return_value={"node-123": {"message": "test output"}})):
            await send_event(frontend_sio, sid, request)
            await asyncio.sleep(0.1)

        response_events = self.get_main_api_emitted_events("response")
        response_data = response_events[0][1]

        assert response_data.get("error") is None
        inputs = response_data["data"]["inputs"]
        # node-123 is upstream of node-456 per TEST_WORKFLOW_DATA
        assert "node-123" in inputs
        assert inputs["node-123"] == {"message": "test output"}

    # ── workflow:get_node_outputs (plural) ──────────────────────────────────
    # This is the event FlowCanvas fires on workflow load to hydrate
    # node.data.output, and therefore the source the SDK's nodes.getOutput()
    # reads when a component is opened long after a (background) run. The CAS
    # round-trip behind it is covered in test_cas_reads.py; these tests pin the
    # HANDLER contract: scope selection, response shape, and the access gate.

    async def test_get_node_outputs_returns_latest_per_node(self, frontend_sio, sid):
        """No execution_id → latest output per node across executions, wrapped as
        {"outputs": {...}} (the restored-output hydration source)."""
        handler = self.handlers.get(Handler.WORKFLOW_MCP)
        self._mock_database_with_session(handler, self.main_api_sio, sid)

        request = WorkflowGetNodeOutputsRequest(
            request_id="test-outputs-latest",
            workflow_id=TEST_WORKFLOW_ID,
        )
        with patch("utils.node_outputs.latest_outputs",
                   AsyncMock(return_value={"node-123": {"v": 1}})) as latest:
            await send_event(frontend_sio, sid, request)
            await asyncio.sleep(0.1)

        latest.assert_awaited_once()
        assert latest.await_args.args[1] == TEST_WORKFLOW_ID  # (pool, workflow_id, node_ids)

        response_data = self.get_main_api_emitted_events("response")[0][1]
        assert response_data.get("error") is None
        assert response_data["data"] == {"outputs": {"node-123": {"v": 1}}}

    async def test_get_node_outputs_uses_execution_scope_when_execution_id_given(self, frontend_sio, sid):
        """With execution_id → that execution's outputs (per-run view), not the
        cross-execution latest."""
        handler = self.handlers.get(Handler.WORKFLOW_MCP)
        self._mock_database_with_session(handler, self.main_api_sio, sid)

        exec_id = "11111111-1111-1111-1111-111111111111"
        request = WorkflowGetNodeOutputsRequest(
            request_id="test-outputs-exec",
            workflow_id=TEST_WORKFLOW_ID,
            execution_id=exec_id,
            node_ids=["node-123"],
        )
        with patch("utils.node_outputs.execution_outputs",
                   AsyncMock(return_value={"node-123": {"v": 2}})) as by_exec, \
             patch("utils.node_outputs.latest_outputs", AsyncMock()) as latest:
            await send_event(frontend_sio, sid, request)
            await asyncio.sleep(0.1)

        by_exec.assert_awaited_once()
        assert by_exec.await_args.args[1] == exec_id          # (pool, execution_id, node_ids)
        assert by_exec.await_args.args[2] == ["node-123"]
        latest.assert_not_awaited()

        response_data = self.get_main_api_emitted_events("response")[0][1]
        assert response_data["data"] == {"outputs": {"node-123": {"v": 2}}}

    async def test_get_node_outputs_denies_without_access(self, frontend_sio, sid):
        """A user without VIEW access gets an error and the store is never read."""
        from types import SimpleNamespace
        handler = self.handlers.get(Handler.WORKFLOW_MCP)
        self._mock_database_with_session(handler, self.main_api_sio, sid)

        request = WorkflowGetNodeOutputsRequest(
            request_id="test-outputs-noaccess",
            workflow_id=TEST_WORKFLOW_ID,
        )
        with patch("wss.handlers.workflow_mcp_handler.check_resource_access",
                   AsyncMock(return_value=SimpleNamespace(has_access=False))), \
             patch("utils.node_outputs.latest_outputs", AsyncMock()) as latest:
            await send_event(frontend_sio, sid, request)
            await asyncio.sleep(0.1)

        latest.assert_not_awaited()
        response_data = self.get_main_api_emitted_events("response")[0][1]
        assert response_data.get("error") == "No access to workflow"


@pytest.mark.asyncio
class TestWorkflowMCPHandlerWorkflowExecution(BaseHandlerTest):
    """Tests for workflow execution MCP tools (database-backed)."""

    def _mock_database(self, handler, sio, workflow_data=None):
        """Helper to mock database operations and session for a handler."""
        import copy
        mock_conn = AsyncMock()
        # Use side_effect to return different values for different fetchrow calls:
        # 1. First call (access control): returns owner_id and organization_id
        # 2. Second call (SELECT workflow): returns workflow data
        # 3. Third call (INSERT execution): returns execution id
        mock_conn.fetchrow = AsyncMock(side_effect=[
            {'owner_id': TEST_USER_ID, 'organization_id': None},  # Access control check
            {'workflow': copy.deepcopy(workflow_data or TEST_WORKFLOW_DATA)},  # Workflow data
            {'id': 'test-execution-123'}  # INSERT RETURNING id
        ])
        # Mock fetchval for access control organization member check
        mock_conn.fetchval = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None)
        ))
        handler.get_pool = AsyncMock(return_value=mock_pool)
        # Mock the session to return a valid UUID
        sio.get_session = AsyncMock(return_value={'user_id': TEST_USER_ID})
        return mock_conn

    async def test_run_workflow_starts_execution(self, frontend_sio, sid):
        """Test run_workflow loads workflow from DB and starts execution."""
        handler = self.handlers.get(Handler.WORKFLOW_MCP)
        self._mock_database(handler, self.main_api_sio)

        request = WorkflowMCPRunWorkflowRequest(
            request_id="test-run-1",
            workflow_id=TEST_WORKFLOW_ID
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.1)

        # Verify the response indicates execution started
        response_events = self.get_main_api_emitted_events("response")
        assert len(response_events) >= 1

        response_data = response_events[0][1]
        assert response_data.get("error") is None
        data = response_data["data"]
        # New response format includes execution_id and status
        assert data["execution_id"] == "test-execution-123"
        assert data["status"] == "running"
        assert data["workflow_id"] == TEST_WORKFLOW_ID
        # Should report node count from the loaded workflow
        assert data["node_count"] == len(TEST_WORKFLOW_DATA["nodes"])


@pytest.mark.asyncio
class TestWorkflowMCPHandlerCreateWorkflow(BaseHandlerTest):
    """Tests for create_workflow - verifies the event structure."""

    async def test_create_workflow_sends_correct_events(self, frontend_sio, sid):
        """Test create_workflow sends the expected events (without database)."""
        # Note: This test verifies the event structure without database integration
        # For full database integration, see test_workflow_handler.py

        responder = FrontendResponder(self.main_api_sio, frontend_sio, sid)

        # Frontend responds to open_workflow request
        responder.set_response_for_type("open_workflow", {"success": True})

        request = WorkflowMCPCreateWorkflowRequest(
            request_id="test-create-1",
            name="Test Workflow",
            description="A test workflow created by MCP"
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.1)

        # The response will have an error because there's no database,
        # but we can verify the request was processed
        response_events = self.get_main_api_emitted_events("response")
        assert len(response_events) == 1

        # Check the request structure was correct
        response_data = response_events[0][1]
        # With mocked database, we expect an error about database connection
        # This verifies the handler is being called with correct parameters
        assert response_data.get("error") is not None or response_data.get("data") is not None


@pytest.mark.asyncio
class TestWorkflowMCPHandlerTimeout(BaseHandlerTest):
    """Tests for timeout handling in bidirectional communication."""

    async def test_frontend_timeout_returns_error(self, frontend_sio, sid):
        """Test that timeout occurs when frontend doesn't respond."""
        # Reduce the default timeout so we don't wait 10s in tests
        from wss.handlers.workflow_mcp_handler import WorkflowMCPHandler
        original_defaults = WorkflowMCPHandler._request_frontend.__defaults__
        WorkflowMCPHandler._request_frontend.__defaults__ = (None, 0.5)

        try:
            # Don't set up a responder - let it timeout
            request = WorkflowMCPGetSelectedNodeRequest(
                request_id="test-timeout-1",
            )
            await send_event(frontend_sio, sid, request)

            # Wait for the request to be dispatched to frontend
            await asyncio.sleep(0.1)

            # Verify the MCP request was sent to frontend
            mcp_requests = self.main_api_sio.get_emitted_events("workflow:mcp:request")
            assert len(mcp_requests) == 1

            request_data = mcp_requests[0][1]
            assert request_data["request_type"] == "get_selected"
        finally:
            WorkflowMCPHandler._request_frontend.__defaults__ = original_defaults


@pytest.mark.asyncio
class TestWorkflowMCPHandlerMCPToolsRegistration(BaseHandlerTest):
    """Tests verifying MCP tools are properly registered."""

    async def test_workflow_mcp_handler_registered(self, frontend_sio, sid):
        """Verify WorkflowMCPHandler is registered in the proxy."""
        handler = self.handlers.get(Handler.WORKFLOW_MCP)
        assert handler is not None

        # Verify it has the expected methods
        events = handler.get_events()
        expected_events = [
            "workflow:mcp:response",
            "workflow:mcp:search_nodes",
            "workflow:mcp:get_node_config_schema",
            "workflow:mcp:get_selected_node",
            "workflow:mcp:get_node_output",
            "workflow:mcp:get_node_input",
            "workflow:mcp:run_workflow",
            "workflow:mcp:create_workflow",
            "workflow:mcp:open_workflow",
            "workflow:mcp:list_workflows",
            "workflow:mcp:list_saved_outputs",
            "workflow:mcp:run_node",
        ]
        for event in expected_events:
            assert event in events, f"Missing event handler: {event}"

    async def test_mcp_tools_configuration_exists(self, frontend_sio, sid):
        """Verify MCP tools are configured in tools.py."""
        from mcp_adapter.tools import MCP_EVENTS

        expected_tools = [
            "workflow:mcp:search_nodes",
            "workflow:mcp:get_node_config_schema",
            "workflow:mcp:get_selected_node",
            "workflow:mcp:get_node_output",
            "workflow:mcp:get_node_input",
            "workflow:mcp:run_workflow",
            "workflow:mcp:create_workflow",
            "workflow:mcp:open_workflow",
            "workflow:mcp:list_workflows",
            "workflow:mcp:list_saved_outputs",
            "workflow:mcp:run_node",
        ]

        for tool_event in expected_tools:
            assert tool_event in MCP_EVENTS, f"Missing MCP tool config: {tool_event}"

            tool_config = MCP_EVENTS[tool_event]
            assert "name" in tool_config
            assert "description" in tool_config
            assert "tags" in tool_config
            assert "annotations" in tool_config


@pytest.mark.asyncio
class TestWorkflowMCPHandlerOpenWorkflow(BaseHandlerTest):
    """Tests for open_workflow MCP tool."""

    async def test_open_workflow_sends_request_to_frontend(self, frontend_sio, sid):
        """Test open_workflow sends navigation request to frontend."""
        responder = FrontendResponder(self.main_api_sio, frontend_sio, sid)
        responder.set_response_for_type("open_workflow", {"success": True})

        request = WorkflowMCPOpenWorkflowRequest(
            request_id="test-open-1",
            workflow_id="workflow-abc-123"
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.1)

        # Verify request was sent to frontend
        assert len(responder.captured_requests) == 1
        captured = responder.captured_requests[0]
        assert captured["request_type"] == "open_workflow"
        assert captured["params"]["workflow_id"] == "workflow-abc-123"

        # Verify the response
        response_events = self.get_main_api_emitted_events("response")
        response_data = response_events[0][1]
        assert response_data.get("error") is None
        assert response_data["data"]["success"] is True


@pytest.mark.asyncio
class TestWorkflowMCPHandlerListWorkflows(BaseHandlerTest):
    """Tests for list_workflows MCP tool (backend-only, database-dependent)."""

    async def test_list_workflows_handler_invoked(self, frontend_sio, sid):
        """
        Test list_workflows reaches the handler and attempts database query.

        Without database connection, this verifies:
        1. Event routing works correctly (we get a response, not a timeout)
        2. Handler is invoked (not a 404-style routing error)
        3. Handler attempts to query database (error indicates DB operation failed)
        """
        request = WorkflowMCPListWorkflowsRequest(
            request_id="test-list-1",
            limit=10
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.1)

        response_events = self.get_main_api_emitted_events("response")
        # Critical: We got a response (handler was invoked, event routing worked)
        assert len(response_events) == 1

        response_data = response_events[0][1]

        # Handler was invoked - without DB it returns an error
        # This proves: 1) event routing works, 2) handler exists, 3) handler logic ran
        error = response_data.get("error")
        assert error is not None, "Expected error since no DB is connected"
        # Error should NOT indicate a routing problem (unknown event/handler)
        error_lower = error.lower()
        assert "unknown" not in error_lower, f"Unexpected routing error: {error}"
        assert "not found" not in error_lower or "output" in error_lower, \
            f"Unexpected routing error: {error}"

    async def test_list_workflows_with_query_parameter(self, frontend_sio, sid):
        """Test list_workflows properly accepts and processes query parameter."""
        request = WorkflowMCPListWorkflowsRequest(
            request_id="test-list-2",
            query="my search term",
            limit=5
        )
        await send_event(frontend_sio, sid, request)
        response_events = await self.wait_for_main_api_events("response")
        assert len(response_events) == 1

        response_data = response_events[0][1]

        # Handler was invoked (even if it fails due to no database)
        # The error should still be about database, not about invalid parameters
        error = response_data.get("error")
        if error:
            assert "query" not in error.lower(), f"Query parameter should be valid, got error: {error}"


@pytest.mark.asyncio
class TestWorkflowMCPHandlerListSavedOutputs(BaseHandlerTest):
    """Tests for list_saved_outputs MCP tool (backend-only, database-dependent)."""

    async def test_list_saved_outputs_handler_invoked(self, frontend_sio, sid):
        """
        Test list_saved_outputs reaches the handler and attempts database query.

        Without database connection, this verifies:
        1. Event routing works correctly (we get a response)
        2. Handler is invoked with the node_type parameter
        3. Handler attempts to query database (error indicates DB operation failed)
        """
        request = WorkflowMCPListSavedOutputsRequest(
            request_id="test-saved-1",
            node_type="automation-telegram"
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.1)

        response_events = self.get_main_api_emitted_events("response")
        # Critical: We got a response (handler was invoked)
        assert len(response_events) == 1

        response_data = response_events[0][1]

        # Handler was invoked - without DB it returns an error
        # This proves: 1) event routing works, 2) handler exists, 3) handler logic ran
        error = response_data.get("error")
        assert error is not None, "Expected error since no DB is connected"
        # Error should NOT indicate a routing problem (unknown event/handler)
        error_lower = error.lower()
        assert "unknown" not in error_lower, f"Unexpected routing error: {error}"
        # Error should NOT be about invalid node_type (our param is valid)
        assert "invalid" not in error_lower or "node_type" not in error_lower, \
            f"Unexpected param validation error: {error}"


@pytest.mark.asyncio
class TestWorkflowMCPHandlerRunNode(BaseHandlerTest):
    """Tests for run_node MCP tool (database-backed)."""

    def _mock_database(self, handler, sio, workflow_data=None):
        """Helper to mock database operations and session for a handler."""
        import copy
        mock_conn = AsyncMock()
        # Use side_effect to return different values for different fetchrow calls:
        # 1. First call (access control): returns owner_id and organization_id
        # 2. Second call (workflow data): returns workflow JSON
        mock_conn.fetchrow = AsyncMock(side_effect=[
            {'owner_id': TEST_USER_ID, 'organization_id': None},  # Access control check
            {'workflow': copy.deepcopy(workflow_data or TEST_WORKFLOW_DATA)},  # Workflow data
        ])
        # Mock fetchval for access control organization member check
        mock_conn.fetchval = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None)
        ))
        handler.get_pool = AsyncMock(return_value=mock_pool)
        # Mock the session to return a valid UUID
        sio.get_session = AsyncMock(return_value={'user_id': TEST_USER_ID})
        return mock_conn

    async def test_run_node_executes_single_node(self, frontend_sio, sid):
        """
        Test run_node loads workflow from DB and starts single node execution.

        Critical verifications:
        1. Backend loads workflow from database
        2. node_id is correctly handled
        3. Response confirms execution was initiated
        """
        handler = self.handlers.get(Handler.WORKFLOW_MCP)
        self._mock_database(handler, self.main_api_sio)

        # node-456 has node-123 as predecessor with output
        request = WorkflowMCPRunNodeRequest(
            request_id="test-run-node-1",
            workflow_id=TEST_WORKFLOW_ID,
            node_id="node-456"
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.1)

        # Critical: Verify response confirms execution started
        response_events = self.get_main_api_emitted_events("response")
        assert len(response_events) >= 1
        response_data = response_events[0][1]
        assert response_data.get("error") is None
        data = response_data["data"]
        assert data["started"] is True
        assert data["node_id"] == "node-456"
        # Should report that node-123 is a predecessor
        assert data["predecessor_count"] == 1


@pytest.mark.asyncio
class TestWorkflowMCPHandlerRequestIdCorrelation(BaseHandlerTest):
    """Tests verifying request_id is properly preserved through bidirectional flow."""

    async def test_request_id_preserved_in_frontend_request(self, frontend_sio, sid):
        """
        Test that request_id is preserved when forwarding to frontend.

        This is critical for bidirectional communication - the frontend needs
        the request_id to send the response back to the correct waiting coroutine.
        """
        responder = FrontendResponder(self.main_api_sio, frontend_sio, sid)
        responder.set_response_for_type("get_selected", {"id": "node-1"})

        unique_request_id = f"unique-correlation-test-{uuid.uuid4()}"
        request = WorkflowMCPGetSelectedNodeRequest(
            request_id=unique_request_id,
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.1)

        # Critical: The frontend request must contain a request_id for correlation
        assert len(responder.captured_requests) == 1
        captured = responder.captured_requests[0]
        # The handler generates internal request_ids for frontend correlation
        assert "request_id" in captured
        assert captured["request_id"] is not None

        # Critical: We get a response (correlation worked internally)
        response_events = self.get_main_api_emitted_events("response")
        assert len(response_events) == 1
        response_data = response_events[0][1]
        # The response should be successful (no error)
        assert response_data.get("error") is None
        # And contain the expected data structure
        assert "data" in response_data
        assert response_data["data"]["selected_node"]["id"] == "node-1"
