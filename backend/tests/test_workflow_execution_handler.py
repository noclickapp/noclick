"""
Test suite for WorkflowExecutionHandler.

Validates core workflow execution functionality:
- Topological sorting (execution order based on dependencies)
- Node execution with progress and completion events
- Error handling (cycle detection)
- Edge cases (empty, single node, disconnected)
- Reference resolution ({{nodeId.path}} syntax)
"""

import pytest
import pytest_asyncio
import asyncio
import os
import uuid
import json
from typing import List, Dict, Any
from unittest.mock import patch, AsyncMock, MagicMock

from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from wss.receiver.client_events import WorkflowExecuteRequest
from wss.sender import send_event
from wss.receiver.event_routing import Handler


def _wired(tool_params):
    """User-wired tools only — upload_file is ambient on every SDK agent."""
    return [p for p in tool_params if p["function"]["name"] != "upload_file"]


def _wired_cfg(tool_configs):
    return {k: v for k, v in tool_configs.items() if k != "upload_file"}


def test_user_stopped_completion_is_not_logged_as_error():
    with patch("wss.handlers.workflow_execution_handler.logger") as mock_logger:
        WorkflowExecutionHandler._log_execution_completion(
            False, 1.25, "Workflow execution was stopped by user"
        )

    mock_logger.info.assert_called_once_with(
        "[WorkflowExecution] Workflow execution stopped by user"
    )
    mock_logger.error.assert_not_called()


def test_failed_completion_remains_an_error():
    with patch("wss.handlers.workflow_execution_handler.logger") as mock_logger:
        WorkflowExecutionHandler._log_execution_completion(False, 1.25, "boom")

    mock_logger.error.assert_called_once_with(
        "[WorkflowExecution] Workflow failed: boom"
    )


def test_workflow_execute_request_accepts_distinct_replay_graph():
    request = WorkflowExecuteRequest(
        event_name="workflow:execute",
        request_id="req-replay-graph",
        workflow_id=str(uuid.uuid4()),
        nodes=[{"id": "slack-1", "type": "automation-slack", "config": {}}],
        edges=[],
        replay_nodes=[
            {"id": "slack-1", "type": "automation-slack", "config": {}},
            {"id": "app-1", "type": "interface-html-react", "config": {"jsx_source": "export default null;"}},
        ],
        replay_edges=[],
    )

    assert [node["id"] for node in request.nodes] == ["slack-1"]
    assert [node["id"] for node in request.replay_nodes or []] == ["slack-1", "app-1"]


class TestReferenceResolution:
    """
    Unit tests for reference resolution in workflow config fields.

    Tests the {{nodeId.path}} syntax that allows config fields to reference
    outputs from upstream nodes. These are pure unit tests - no database or
    socket infrastructure required.
    """

    @pytest.fixture
    def handler(self):
        """Create a handler instance for testing (sio not needed for resolution methods)."""
        return WorkflowExecutionHandler(sio=None)

    @pytest.fixture
    def node_outputs(self):
        """Sample node outputs for testing reference resolution."""
        return {
            "telegram-1": {
                "type": "telegram",
                "message": "Hello from Telegram",
                "chat_id": "123456",
                "metadata": {
                    "user": "john_doe",
                    "timestamp": 1234567890
                }
            },
            "agent-2": {
                "type": "agent",
                "response": "The answer is 42",
                "tokens": 150,
                "model": "gpt-4"
            },
            "data-node": {
                "items": ["apple", "banana", "cherry"],
                "count": 3,
                "nested": {
                    "deep": {
                        "value": "found it"
                    }
                }
            }
        }

    def test_simple_string_reference(self, handler, node_outputs):
        """Test resolving a simple string reference returns the actual value."""
        result = handler._resolve_references("{{telegram-1.message}}", node_outputs)
        assert result == "Hello from Telegram"

    def test_nested_path_reference(self, handler, node_outputs):
        """Test resolving deeply nested path references."""
        result = handler._resolve_references("{{telegram-1.metadata.user}}", node_outputs)
        assert result == "john_doe"

        result = handler._resolve_references("{{data-node.nested.deep.value}}", node_outputs)
        assert result == "found it"

    def test_type_preservation_for_single_reference(self, handler, node_outputs):
        """Test that single references preserve the original type (not stringified)."""
        # Number should stay number
        result = handler._resolve_references("{{agent-2.tokens}}", node_outputs)
        assert result == 150
        assert isinstance(result, int)

        # Nested number
        result = handler._resolve_references("{{telegram-1.metadata.timestamp}}", node_outputs)
        assert result == 1234567890
        assert isinstance(result, int)

    def test_mixed_text_converts_to_string(self, handler, node_outputs):
        """Test that references mixed with text are converted to strings."""
        result = handler._resolve_references(
            "User {{telegram-1.metadata.user}} sent: {{telegram-1.message}}",
            node_outputs
        )
        assert result == "User john_doe sent: Hello from Telegram"
        assert isinstance(result, str)

    def test_dict_recursion(self, handler, node_outputs):
        """Test that references in nested dicts are resolved recursively."""
        config = {
            "recipient": "{{telegram-1.metadata.user}}",
            "content": {
                "text": "{{agent-2.response}}",
                "source": "{{telegram-1.type}}"
            }
        }
        result = handler._resolve_references(config, node_outputs)

        assert result["recipient"] == "john_doe"
        assert result["content"]["text"] == "The answer is 42"
        assert result["content"]["source"] == "telegram"

    def test_list_recursion(self, handler, node_outputs):
        """Test that references in lists are resolved recursively."""
        config = ["{{telegram-1.message}}", "static", "{{agent-2.model}}"]
        result = handler._resolve_references(config, node_outputs)

        assert result == ["Hello from Telegram", "static", "gpt-4"]

    def test_unknown_node_preserves_reference(self, handler, node_outputs):
        """Test that references to unknown nodes are preserved as-is (e.g. JS object literals like {{ background: '#fff' }})."""
        result = handler._resolve_references("{{unknown-node.value}}", node_outputs)
        assert result == "{{unknown-node.value}}"

    def test_unknown_path_preserves_reference(self, handler, node_outputs):
        """Test that references to unknown paths are preserved as-is."""
        result = handler._resolve_references("{{telegram-1.nonexistent.path}}", node_outputs)
        assert result == "{{telegram-1.nonexistent.path}}"

    def test_mixed_text_unknown_ref_preserved(self, handler, node_outputs):
        """Test that unknown references in mixed text are preserved as-is."""
        result = handler._resolve_references(
            "Hello {{unknown-node.value}} world",
            node_outputs
        )
        assert result == "Hello {{unknown-node.value}} world"

    def test_no_references_unchanged(self, handler, node_outputs):
        """Test that values without references pass through unchanged."""
        # String
        assert handler._resolve_references("plain text", node_outputs) == "plain text"
        # Number
        assert handler._resolve_references(42, node_outputs) == 42
        # Bool
        assert handler._resolve_references(True, node_outputs) is True
        # None
        assert handler._resolve_references(None, node_outputs) is None

class TestPreloadExcludedNodeOutputs:
    """
    Unit tests for `_preload_excluded_node_outputs`.

    When `forward_only=True` with a `start_node_id`, predecessors of the start
    node are intentionally not re-executed — but downstream `{{node.path}}`
    references still need their outputs available. The preload helper loads
    those outputs from the workflow_node_outputs table so reference resolution
    doesn't return None and leak the literal template string.
    """

    @pytest.fixture
    def handler(self):
        return WorkflowExecutionHandler(sio=None)

    @pytest.mark.asyncio
    async def test_loads_outputs_only_for_excluded_nodes(self, handler):
        """The DB helper is called with the exact set of excluded node IDs."""
        all_nodes = [
            {"id": "trigger", "type": "trigger-cron"},
            {"id": "slack_fetch", "type": "automation-slack"},
            {"id": "formatter", "type": "automation-serverless-function"},
            {"id": "summarizer", "type": "agent"},
        ]
        # User clicked "run from here" on formatter with forward_only=True →
        # trigger and slack_fetch are excluded, formatter+summarizer included.
        executable_node_ids = {"formatter", "summarizer"}

        captured = {}
        async def fake_get_all(pool, wf_id, node_ids):
            captured['node_ids'] = list(node_ids)
            captured['workflow_id'] = wf_id
            return {
                "slack_fetch": {
                    "type": "slack",
                    "data": {"messages": [{"user": "U1", "text": "hi"}]},
                },
            }

        with patch(
            "utils.node_outputs.latest_outputs",
            new=fake_get_all,
        ):
            result = await handler._preload_excluded_node_outputs(
                pool=MagicMock(), workflow_id="wf-1",
                all_nodes=all_nodes, executable_node_ids=executable_node_ids,
            )

        # Only excluded nodes are queried — included nodes are about to run fresh
        assert set(captured['node_ids']) == {"trigger", "slack_fetch"}
        assert captured['workflow_id'] == "wf-1"
        # Returned outputs flow back unchanged
        assert "slack_fetch" in result
        assert result["slack_fetch"]["data"]["messages"][0]["text"] == "hi"

    @pytest.mark.asyncio
    async def test_no_excluded_nodes_skips_db_call(self, handler):
        """If everything is in the executable set, no DB call is made."""
        all_nodes = [
            {"id": "trigger", "type": "trigger-cron"},
            {"id": "node-a", "type": "agent"},
        ]
        executable_node_ids = {"trigger", "node-a"}

        called = False
        async def fake_get_all(*args, **kwargs):
            nonlocal called
            called = True
            return {}

        with patch(
            "utils.node_outputs.latest_outputs",
            new=fake_get_all,
        ):
            result = await handler._preload_excluded_node_outputs(
                pool=MagicMock(), workflow_id="wf-1",
                all_nodes=all_nodes, executable_node_ids=executable_node_ids,
            )

        assert called is False, "Should short-circuit when nothing is excluded"
        assert result == {}

    @pytest.mark.asyncio
    async def test_db_error_swallowed_returns_empty(self, handler):
        """A DB failure shouldn't break execution — it should degrade gracefully."""
        all_nodes = [
            {"id": "upstream", "type": "automation-slack"},
            {"id": "downstream", "type": "agent"},
        ]
        executable_node_ids = {"downstream"}

        async def boom(*args, **kwargs):
            raise RuntimeError("DB pool unavailable")

        with patch(
            "utils.node_outputs.latest_outputs",
            new=boom,
        ):
            result = await handler._preload_excluded_node_outputs(
                pool=MagicMock(), workflow_id="wf-1",
                all_nodes=all_nodes, executable_node_ids=executable_node_ids,
            )

        assert result == {}, "DB errors degrade to empty preload, not propagated"

    @pytest.mark.asyncio
    async def test_preloaded_output_resolves_function_inputs_reference(self, handler):
        """
        End-to-end of the bug fix: an excluded upstream node's stored output
        flows through preload → initial_outputs → state.node_outputs →
        _resolve_references → the function_inputs value gets the real array
        instead of the literal `{{slack_fetch.data.messages}}` string.

        This is the regression that caused the AI-builder Slack-summary run
        to keep posting `{{summarizer.response}}` to the user's channel.
        """
        all_nodes = [
            {"id": "slack_fetch", "type": "automation-slack"},
            {"id": "formatter", "type": "automation-serverless-function"},
        ]
        executable_node_ids = {"formatter"}

        async def fake_get_all(pool, wf_id, node_ids):
            return {
                "slack_fetch": {
                    "type": "slack",
                    "data": {
                        "messages": [
                            {"user": "U1", "text": "hello"},
                            {"user": "U2", "text": "world"},
                        ],
                    },
                },
            }

        with patch(
            "utils.node_outputs.latest_outputs",
            new=fake_get_all,
        ):
            preloaded = await handler._preload_excluded_node_outputs(
                pool=MagicMock(), workflow_id="wf-1",
                all_nodes=all_nodes, executable_node_ids=executable_node_ids,
            )

        # Simulate what _execute_nodes_concurrent does with initial_outputs
        node_outputs = dict(preloaded)

        formatter_config = {
            "function_body": "return inputs.messages.length;",
            "function_inputs": [
                {"name": "messages", "value": "{{slack_fetch.data.messages}}"},
            ],
        }
        resolved = handler._resolve_references(formatter_config, node_outputs)

        resolved_value = resolved["function_inputs"][0]["value"]
        # Before the fix: this was the literal string '{{slack_fetch.data.messages}}'
        # After the fix: it's the actual list of message dicts
        assert isinstance(resolved_value, list), (
            f"Expected list, got {type(resolved_value).__name__}: {resolved_value!r}"
        )
        assert len(resolved_value) == 2
        assert resolved_value[0]["text"] == "hello"


class TestTopologicalSort:
    """Unit tests for topological sort and loop-back edge detection."""

    @pytest.fixture
    def handler(self):
        return WorkflowExecutionHandler(sio=None)

    def test_transitive_loopback_not_detected_as_cycle(self, handler):
        """
        Multi-node loop body: iteration → A → B → iteration (loop-back from B).
        The loop-back edge from B should be filtered, not treated as a cycle.
        """
        nodes = [
            {"id": "trigger", "type": "trigger-cron"},
            {"id": "iter", "type": "iteration"},
            {"id": "body-A", "type": "automation-rss"},
            {"id": "body-B", "type": "agent"},
            {"id": "after-loop", "type": "automation-serverless-function"},
        ]
        edges = [
            {"source": "trigger", "target": "iter"},
            {"source": "iter", "target": "body-A", "sourceHandle": "loop"},
            {"source": "body-A", "target": "body-B"},
            {"source": "body-B", "target": "iter"},  # transitive loop-back
            {"source": "iter", "target": "after-loop", "sourceHandle": "done"},
        ]
        order = handler._topological_sort(nodes, edges)
        assert len(order) == len(nodes), f"Expected all {len(nodes)} nodes, got {len(order)} — false cycle detected"
        # trigger and iter must come before their dependents
        assert order.index("trigger") < order.index("iter")
        assert order.index("iter") < order.index("body-A")
        assert order.index("body-A") < order.index("body-B")
        assert order.index("iter") < order.index("after-loop")

    def test_direct_loopback_still_works(self, handler):
        """Single-node loop body: iteration → A → iteration (direct loop-back)."""
        nodes = [
            {"id": "iter", "type": "iteration"},
            {"id": "body-A", "type": "automation-rss"},
            {"id": "done", "type": "agent"},
        ]
        edges = [
            {"source": "iter", "target": "body-A", "sourceHandle": "loop"},
            {"source": "body-A", "target": "iter"},  # direct loop-back
            {"source": "iter", "target": "done", "sourceHandle": "done"},
        ]
        order = handler._topological_sort(nodes, edges)
        assert len(order) == len(nodes), "Direct loop-back should not cause cycle"

    def test_real_cycle_still_detected(self, handler):
        """Actual cycle (no iteration node) should still be caught."""
        nodes = [
            {"id": "A", "type": "agent"},
            {"id": "B", "type": "agent"},
            {"id": "C", "type": "agent"},
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
            {"source": "C", "target": "A"},
        ]
        order = handler._topological_sort(nodes, edges)
        assert order == [], "Real cycle should be detected"


class TestErrorOutputRouting:
    """
    Unit tests for the error-handle routing logic introduced alongside the
    _settings.onError = continueErrorOutput feature.

    These tests verify (a) _build_dependency_maps surfaces the per-edge
    sourceHandle, and (b) the live-edge predicate used by execute_single_node's
    cascade-skip check selects the right downstream nodes when a predecessor
    finishes via the error handle vs the success handle.
    """

    @pytest.fixture
    def handler(self):
        return WorkflowExecutionHandler(sio=None)

    def test_build_dependency_maps_returns_predecessor_edges_with_handle(self, handler):
        nodes = [
            {"id": "src", "type": "automation-slack"},
            {"id": "ok", "type": "automation-slack"},
            {"id": "err", "type": "automation-slack"},
        ]
        edges = [
            {"source": "src", "target": "ok"},
            {"source": "src", "target": "err", "sourceHandle": "error"},
        ]
        _preds, _node_by_id, _succs, predecessor_edges = handler._build_dependency_maps(nodes, edges)

        # (source, sourceHandle, targetHandle) — targetHandle distinguishes
        # bottom-handle tool wiring, which never counts for cascade liveness.
        assert predecessor_edges["ok"] == [("src", None, None)]
        assert predecessor_edges["err"] == [("src", "error", None)]
        # Source has no incoming edges
        assert predecessor_edges["src"] == []

    def test_state_has_error_continuations_set(self):
        from wss.handlers.workflow_execution_handler import ConcurrentExecutionState
        state = ConcurrentExecutionState()
        assert state.error_continuations == set()
        # Verify it's an independent set per instance (default_factory, not shared)
        state.error_continuations.add("foo")
        assert ConcurrentExecutionState().error_continuations == set()

    def test_edge_live_predicate_routes_success_when_predecessor_completed_normally(self):
        """
        Replicates the inlined _edge_live closure from execute_single_node.
        With a clean completion: success/default edges live, error edges dead.
        """
        from wss.handlers.workflow_execution_handler import ConcurrentExecutionState
        state = ConcurrentExecutionState()
        state.completed.add("src")  # Normal success

        def edge_live(pred_id, handle):
            if handle == "error":
                return pred_id in state.error_continuations
            return pred_id in state.completed and pred_id not in state.error_continuations

        assert edge_live("src", None) is True       # default success handle
        assert edge_live("src", "true") is True     # any non-error handle
        assert edge_live("src", "error") is False   # error handle dead on normal success

    def test_edge_live_predicate_routes_error_when_predecessor_error_continued(self):
        """When the predecessor finished via continueErrorOutput with a wired error
        edge, the success handle goes dead and the error handle goes live."""
        from wss.handlers.workflow_execution_handler import ConcurrentExecutionState
        state = ConcurrentExecutionState()
        state.completed.add("src")
        state.error_continuations.add("src")

        def edge_live(pred_id, handle):
            if handle == "error":
                return pred_id in state.error_continuations
            return pred_id in state.completed and pred_id not in state.error_continuations

        assert edge_live("src", None) is False       # default handle is now dead
        assert edge_live("src", "error") is True     # error handle is the only live route

    def test_edge_live_predicate_dead_when_predecessor_failed(self):
        """Predecessor that hit stopWorkflow (or any uncaught error) is in `failed`,
        so both success and error handles stay dead."""
        from wss.handlers.workflow_execution_handler import ConcurrentExecutionState
        state = ConcurrentExecutionState()
        state.failed.add("src")

        def edge_live(pred_id, handle):
            if handle == "error":
                return pred_id in state.error_continuations
            return pred_id in state.completed and pred_id not in state.error_continuations

        assert edge_live("src", None) is False
        assert edge_live("src", "error") is False

    def test_nodes_with_error_edge_set_membership(self, handler):
        """The handler precomputes which nodes have an outgoing error edge so the
        execution loop can gate the new routing path. Verify the set is built
        correctly from edge metadata (same one-liner the handler uses inline)."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "A", "target": "C", "sourceHandle": "error"},
            {"source": "B", "target": "D"},
            {"source": "B", "target": "E", "sourceHandle": "true"},  # not 'error'
        ]
        nodes_with_error_edge = {
            e["source"] for e in edges
            if e.get("source") and e.get("sourceHandle") == "error"
        }
        assert nodes_with_error_edge == {"A"}


# Enable fast test mode (no sleep delays in node execution)
os.environ['WORKFLOW_TEST_MODE'] = '1'


# LiteLLM mock fixture - ensures agent nodes don't make real API calls
@pytest.fixture(autouse=True)
def mock_litellm_api():
    """Mock LiteLLM to return default responses for agent nodes."""
    from tests.mocks.mock_litellm import configure_mock_llm_responses
    configure_mock_llm_responses(default="Mock agent response for workflow testing")
    yield


# Telegram API mock fixture - mocks all Telegram Bot API calls
@pytest.fixture(autouse=True)
def mock_telegram_api():
    """Mock Telegram Bot API sendMessage endpoint for all tests."""
    message_counter = [0]

    async def mock_post(url, json=None, **kwargs):
        """Mock httpx post that returns Telegram-like responses."""
        message_counter[0] += 1
        chat_id = json.get('chat_id', 'unknown') if json else 'unknown'
        text = json.get('text', 'Test message') if json else 'Test message'

        # Create a mock response object
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {
                "message_id": message_counter[0],
                "from": {"id": 123456789, "is_bot": True, "first_name": "TestBot"},
                "chat": {"id": chat_id, "type": "private"},
                "date": 1234567890,
                "text": text
            }
        }
        return mock_response

    # Patch the httpx.AsyncClient context manager
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client
        yield mock_client


class TestWorkflowExecutionHandler(BaseHandlerTest):
    """Test WorkflowExecutionHandler with various workflow configurations."""

    def get_session_data(self, sid: str):
        """Override to provide consistent test user ID."""
        return {
            'sid': sid,
            'user_id': '00000000-0000-4000-8000-000000000003',
            'email': 'workflow-exec-test@example.com',
        }

    async def create_test_user(self, real_database, user_id: str):
        """Helper to create a test user in the database."""
        await real_database.execute("""
            INSERT INTO auth.users (id, email)
            VALUES ($1, $2)
            ON CONFLICT (id) DO NOTHING
        """, user_id, 'workflow-exec-test@example.com')

    async def create_workflow_in_db(self, real_database, workflow_id: str, user_id: str):
        """Helper to create a workflow record in the database."""
        await real_database.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        """, workflow_id, user_id, "Test Workflow", "Test Description", {}, {})

    def wrap_node_data(self, node_type: str, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Wrap config data with credential for the new config structure.

        Args:
            node_type: Type of node (e.g., 'automation-telegram', 'agent')
            config_data: The config data (message, chatId, etc.)

        Returns:
            Dict with config and credential fields
        """
        # Define test credentials for each node type
        credentials = {
            'automation-telegram': {'token': 'test-telegram-token-12345678:ABCdefGHIjklMNOpqrsTUVwxyz'},
            'agent': {'api_key': 'sk-test-openai-key-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'}
        }

        return {
            'config': config_data,
            'credentials': credentials.get(node_type, {})
        }

    def create_workflow_request(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        request_id: str = "test-workflow-123",
        workflow_id: str = None
    ) -> WorkflowExecuteRequest:
        """Helper to create a workflow execution request."""
        if workflow_id is None:
            workflow_id = str(uuid.uuid4())
        return WorkflowExecuteRequest(
            event_name="workflow:execute",
            request_id=request_id,
            workflow_id=workflow_id,
            nodes=nodes,
            edges=edges
        )

    @pytest.mark.asyncio
    async def test_simple_linear_workflow(self, real_database, frontend_sio, sid):
        """Test linear workflow: A → B → C with correct execution order and events."""
        # Setup database
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000003'
        await self.create_test_user(real_database, user_id)
        await self.create_workflow_in_db(real_database, workflow_id, user_id)

        nodes = [
            {"id": "telegram-1", "type": "automation-telegram", "position": {"x": 0, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Test message", "chatId": "123456"})},
            {"id": "telegram-2", "type": "automation-telegram", "position": {"x": 100, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Test message", "chatId": "234567"})},
            {"id": "agent-1", "type": "agent", "position": {"x": 200, "y": 0}, "config": self.wrap_node_data("agent", {"system_prompt": "Process data", "message": "Process the input", "temperature": 0.5})},
        ]
        edges = [
            {"id": "e1", "source": "telegram-1", "target": "telegram-2"},
            {"id": "e2", "source": "telegram-2", "target": "agent-1"},
        ]

        workflow_request = self.create_workflow_request(nodes, edges, workflow_id=workflow_id)
        await send_event(frontend_sio, sid, workflow_request)
        await asyncio.sleep(0.2)

        # Verify execution order via state events
        state_events = self.get_main_api_emitted_events("workflow:node:state")
        # Each node should have 2 state events: running and completed (6 total)
        assert len(state_events) >= 6

        # Extract running state events
        running_events = [event for event in state_events if event[1]['state'] == 'running']
        assert len(running_events) == 3
        running_node_ids = [event[1]['node_id'] for event in running_events]
        assert running_node_ids == ["telegram-1", "telegram-2", "agent-1"], \
            "Nodes should execute in dependency order"

        # Verify all nodes completed successfully
        completed_events = [event for event in state_events if event[1]['state'] == 'completed']
        assert len(completed_events) == 3
        for event in completed_events:
            event_data = event[1]
            assert event_data.get('error') is None

        # Verify workflow completion
        workflow_complete_events = self.get_main_api_emitted_events("workflow:complete")
        assert len(workflow_complete_events) == 1
        completion_data = workflow_complete_events[0][1]
        assert completion_data['success'] is True
        assert completion_data['nodes_executed'] == 3
        assert completion_data['duration'] > 0
        assert completion_data.get('error') is None

    @pytest.mark.asyncio
    async def test_parallel_workflow(self, real_database, frontend_sio, sid):
        """Test parallel branching and convergence: A → [B,C,D] → E."""
        # Setup database
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000003'
        await self.create_test_user(real_database, user_id)
        await self.create_workflow_in_db(real_database, workflow_id, user_id)

        nodes = [
            {"id": "start", "type": "automation-telegram", "position": {"x": 0, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Start", "chatId": "123"})},
            {"id": "branch-1", "type": "automation-telegram", "position": {"x": 100, "y": -50}, "config": self.wrap_node_data("automation-telegram", {"message": "Branch 1", "chatId": "111"})},
            {"id": "branch-2", "type": "automation-telegram", "position": {"x": 100, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Branch 2", "chatId": "456"})},
            {"id": "branch-3", "type": "automation-telegram", "position": {"x": 100, "y": 50}, "config": self.wrap_node_data("automation-telegram", {"message": "Branch 3", "chatId": "222"})},
            {"id": "end", "type": "agent", "position": {"x": 200, "y": 0}, "config": self.wrap_node_data("agent", {"system_prompt": "End task", "message": "Process the final result", "temperature": 0.7})},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "branch-1"},
            {"id": "e2", "source": "start", "target": "branch-2"},
            {"id": "e3", "source": "start", "target": "branch-3"},
            {"id": "e4", "source": "branch-1", "target": "end"},
            {"id": "e5", "source": "branch-2", "target": "end"},
            {"id": "e6", "source": "branch-3", "target": "end"},
        ]

        workflow_request = self.create_workflow_request(nodes, edges, workflow_id=workflow_id)
        await send_event(frontend_sio, sid, workflow_request)
        await asyncio.sleep(0.2)

        # Verify execution order: start first, end last, branches in middle
        state_events = self.get_main_api_emitted_events("workflow:node:state")
        running_events = [event for event in state_events if event[1]['state'] == 'running']
        assert len(running_events) == 5
        running_node_ids = [event[1]['node_id'] for event in running_events]
        assert running_node_ids[0] == "start", "Start node must execute first"
        assert running_node_ids[-1] == "end", "End node must execute last"

        middle_nodes = set(running_node_ids[1:4])
        expected_middle = {"branch-1", "branch-2", "branch-3"}
        assert middle_nodes == expected_middle, "All branch nodes should execute"

        # Verify successful completion
        workflow_complete_events = self.get_main_api_emitted_events("workflow:complete")
        assert len(workflow_complete_events) == 1
        assert workflow_complete_events[0][1]['success'] is True
        assert workflow_complete_events[0][1]['nodes_executed'] == 5

    @pytest.mark.asyncio
    async def test_single_node_workflow(self, real_database, frontend_sio, sid):
        """Test workflow with just one node (no edges)."""
        # Setup database
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000003'
        await self.create_test_user(real_database, user_id)
        await self.create_workflow_in_db(real_database, workflow_id, user_id)

        nodes = [
            {"id": "solo", "type": "agent", "position": {"x": 0, "y": 0}, "config": self.wrap_node_data("agent", {"system_prompt": "Single task", "message": "Execute the task", "temperature": 0.7})}
        ]
        edges = []

        workflow_request = self.create_workflow_request(nodes, edges, workflow_id=workflow_id)
        await send_event(frontend_sio, sid, workflow_request)
        await asyncio.sleep(0.2)

        # Single node should execute
        state_events = self.get_main_api_emitted_events("workflow:node:state")
        running_events = [event for event in state_events if event[1]['state'] == 'running']
        assert len(running_events) == 1
        assert running_events[0][1]['node_id'] == "solo"

        completed_events = [event for event in state_events if event[1]['state'] == 'completed']
        assert len(completed_events) == 1
        assert completed_events[0][1].get('error') is None

        workflow_complete_events = self.get_main_api_emitted_events("workflow:complete")
        assert len(workflow_complete_events) == 1
        assert workflow_complete_events[0][1]['nodes_executed'] == 1

    @pytest.mark.asyncio
    async def test_empty_workflow(self, real_database, frontend_sio, sid):
        """Test workflow with no nodes."""
        # Setup database
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000003'
        await self.create_test_user(real_database, user_id)
        await self.create_workflow_in_db(real_database, workflow_id, user_id)

        workflow_request = self.create_workflow_request([], [], workflow_id=workflow_id)
        await send_event(frontend_sio, sid, workflow_request)
        await asyncio.sleep(0.2)

        # Should complete immediately with 0 nodes executed
        workflow_complete_events = self.get_main_api_emitted_events("workflow:complete")
        assert len(workflow_complete_events) == 1
        assert workflow_complete_events[0][1]['success'] is True
        assert workflow_complete_events[0][1]['nodes_executed'] == 0

        # No node events should be emitted
        progress_events = self.get_main_api_emitted_events("workflow:node:state")
        assert len(progress_events) == 0

    @pytest.mark.asyncio
    async def test_disconnected_nodes(self, real_database, frontend_sio, sid):
        """Test workflow with multiple disconnected components (no edges)."""
        # Setup database
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000003'
        await self.create_test_user(real_database, user_id)
        await self.create_workflow_in_db(real_database, workflow_id, user_id)

        nodes = [
            {"id": "island-1", "type": "automation-telegram", "position": {"x": 0, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Island 1", "chatId": "111"})},
            {"id": "island-2", "type": "automation-telegram", "position": {"x": 100, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Island 2", "chatId": "333"})},
            {"id": "island-3", "type": "agent", "position": {"x": 200, "y": 0}, "config": self.wrap_node_data("agent", {"system_prompt": "Island 3", "message": "Process island 3", "temperature": 0.7})},
        ]
        edges = []  # No connections

        workflow_request = self.create_workflow_request(nodes, edges, workflow_id=workflow_id)
        await send_event(frontend_sio, sid, workflow_request)
        await asyncio.sleep(0.2)

        # All nodes should execute (order doesn't matter)
        state_events = self.get_main_api_emitted_events("workflow:node:state")
        running_events = [event for event in state_events if event[1]['state'] == 'running']
        assert len(running_events) == 3
        executed_nodes = {event[1]['node_id'] for event in running_events}
        assert executed_nodes == {"island-1", "island-2", "island-3"}

        workflow_complete_events = self.get_main_api_emitted_events("workflow:complete")
        assert len(workflow_complete_events) == 1
        assert workflow_complete_events[0][1]['success'] is True
        assert workflow_complete_events[0][1]['nodes_executed'] == 3

    @pytest.mark.asyncio
    async def test_node_types_have_correct_output(self, real_database, frontend_sio, sid):
        """Test that different node types produce expected output structures."""
        # Setup database
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000003'
        await self.create_test_user(real_database, user_id)
        await self.create_workflow_in_db(real_database, workflow_id, user_id)

        nodes = [
            {"id": "telegram-node", "type": "automation-telegram", "position": {"x": 0, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Telegram test", "chatId": "789"})},
            {"id": "agent-node", "type": "agent", "position": {"x": 0, "y": 200}, "config": self.wrap_node_data("agent", {"system_prompt": "Analyze data", "message": "Analyze the provided data", "temperature": 0.8})},
        ]
        edges = []

        workflow_request = self.create_workflow_request(nodes, edges, workflow_id=workflow_id)
        await send_event(frontend_sio, sid, workflow_request)
        await asyncio.sleep(0.2)

        # Get output events (nodes emit their own outputs now)
        output_events = self.get_main_api_emitted_events("workflow:node:output")
        # Agent emits 2 outputs (thinking + completed), telegram emits 1
        assert len(output_events) >= 2

        # Validate telegram node output
        telegram_outputs = [e for e in output_events if e[1]['node_id'] == 'telegram-node']
        assert len(telegram_outputs) >= 1
        telegram_output = telegram_outputs[0][1]['output']
        assert telegram_output['type'] == 'telegram'
        assert 'message' in telegram_output
        assert 'chat_id' in telegram_output
        assert 'timestamp' in telegram_output

        # Validate agent node output (agent emits multiple outputs for streaming)
        agent_outputs = [e for e in output_events if e[1]['node_id'] == 'agent-node']
        assert len(agent_outputs) >= 1
        # Check final output (last one emitted)
        agent_output = agent_outputs[-1][1]['output']
        assert agent_output['type'] == 'agent'
        assert agent_output['status'] == 'completed'
        assert 'response' in agent_output
        assert agent_output['temperature'] == 0.8
        assert 'model' in agent_output

    @pytest.mark.asyncio
    async def test_complex_dag_workflow(self, real_database, frontend_sio, sid):
        """Test diamond pattern DAG: A → B → D and A → C → D."""
        # Setup database
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000003'
        await self.create_test_user(real_database, user_id)
        await self.create_workflow_in_db(real_database, workflow_id, user_id)

        nodes = [
            {"id": "A", "type": "automation-telegram", "position": {"x": 0, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Node A", "chatId": "A123"})},
            {"id": "B", "type": "automation-telegram", "position": {"x": 100, "y": -50}, "config": self.wrap_node_data("automation-telegram", {"message": "Node B", "chatId": "B456"})},
            {"id": "C", "type": "automation-telegram", "position": {"x": 100, "y": 50}, "config": self.wrap_node_data("automation-telegram", {"message": "Node C", "chatId": "C789"})},
            {"id": "D", "type": "agent", "position": {"x": 200, "y": 0}, "config": self.wrap_node_data("agent", {"system_prompt": "Node D", "message": "Process node D", "temperature": 0.7})},
        ]
        edges = [
            {"id": "e1", "source": "A", "target": "B"},
            {"id": "e2", "source": "A", "target": "C"},
            {"id": "e3", "source": "B", "target": "D"},
            {"id": "e4", "source": "C", "target": "D"},
        ]

        workflow_request = self.create_workflow_request(nodes, edges, workflow_id=workflow_id)
        await send_event(frontend_sio, sid, workflow_request)
        await asyncio.sleep(0.2)

        state_events = self.get_main_api_emitted_events("workflow:node:state")
        running_events = [event for event in state_events if event[1]['state'] == 'running']
        assert len(running_events) == 4
        running_node_ids = [event[1]['node_id'] for event in running_events]

        # A must be first
        assert running_node_ids[0] == "A"
        # B and C can be in any order but both must come before D
        assert set(running_node_ids[1:3]) == {"B", "C"}
        # D must be last
        assert running_node_ids[3] == "D"

        # Verify successful completion
        workflow_complete_events = self.get_main_api_emitted_events("workflow:complete")
        assert len(workflow_complete_events) == 1
        assert workflow_complete_events[0][1]['success'] is True
        assert workflow_complete_events[0][1]['nodes_executed'] == 4

    @pytest.mark.asyncio
    async def test_workflow_with_cycle_detection(self, real_database, frontend_sio, sid):
        """Test that workflows with cycles are detected and rejected."""
        # Setup database
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000003'
        await self.create_test_user(real_database, user_id)
        await self.create_workflow_in_db(real_database, workflow_id, user_id)

        # Create a cycle: A → B → C → A
        nodes = [
            {"id": "A", "type": "automation-telegram", "position": {"x": 0, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Cycle A", "chatId": "cycle-a"})},
            {"id": "B", "type": "automation-telegram", "position": {"x": 100, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Cycle B", "chatId": "cycle-b"})},
            {"id": "C", "type": "agent", "position": {"x": 200, "y": 0}, "config": self.wrap_node_data("agent", {"system_prompt": "Cycle C", "message": "Process cycle C", "temperature": 0.7})},
        ]
        edges = [
            {"id": "e1", "source": "A", "target": "B"},
            {"id": "e2", "source": "B", "target": "C"},
            {"id": "e3", "source": "C", "target": "A"},  # Creates cycle
        ]

        workflow_request = self.create_workflow_request(nodes, edges, workflow_id=workflow_id)
        await send_event(frontend_sio, sid, workflow_request)
        await asyncio.sleep(0.2)

        # Should fail with cycle detection
        workflow_complete_events = self.get_main_api_emitted_events("workflow:complete")
        assert len(workflow_complete_events) == 1

        completion_data = workflow_complete_events[0][1]
        assert completion_data['success'] is False, "Workflow with cycle should fail"
        assert completion_data['nodes_executed'] == 0, "No nodes should execute with cycle"
        assert 'error' in completion_data and completion_data['error'] is not None
        assert 'cycle' in completion_data.get('error', '').lower() or 'order' in completion_data.get('error', '').lower()

        # No nodes should have executed
        progress_events = self.get_main_api_emitted_events("workflow:node:state")
        assert len(progress_events) == 0

    @pytest.mark.asyncio
    async def test_config_union_type_discrimination(self, real_database, frontend_sio, sid):
        """
        Test that Union config types (oneOf) correctly discriminate between variants.

        Verifies that Pydantic correctly parses JSON into the appropriate subclass
        based on which fields are present (structural discrimination).

        Uses DummyNode to avoid coupling to production nodes that may change.
        """
        # Setup database
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000003'
        await self.create_test_user(real_database, user_id)
        await self.create_workflow_in_db(real_database, workflow_id, user_id)

        # Test all three dummy config variants in one workflow
        # Using flat config structure
        nodes = [
            {
                "id": "dummy-string",
                "type": "test-dummy",
                "position": {"x": 0, "y": 0},
                "config": {
                    "stringValue": "test string",
                    "optionalNumber": 99
                }
            },
            {
                "id": "dummy-number",
                "type": "test-dummy",
                "position": {"x": 100, "y": 0},
                "config": {
                    "numberValue": 42.5,
                    "optionalString": "custom"
                }
            },
            {
                "id": "dummy-boolean",
                "type": "test-dummy",
                "position": {"x": 200, "y": 0},
                "config": {
                    "booleanValue": True,
                    "metadata": "test metadata"
                }
            }
        ]
        edges = []

        workflow_request = self.create_workflow_request(nodes, edges, workflow_id=workflow_id)
        await send_event(frontend_sio, sid, workflow_request)
        await asyncio.sleep(0.2)

        # Verify each node parsed to correct subclass based on output
        # Each node emits output via self.emit() and workflow handler emits final output
        output_events = self.get_main_api_emitted_events("workflow:node:output")
        assert len(output_events) >= 3  # At least one per node

        # Check StringConfig variant
        string_output = [e for e in output_events if e[1]['node_id'] == 'dummy-string'][0][1]['output']
        assert string_output['config_type'] == 'string'
        assert string_output['stringValue'] == "test string"
        assert string_output['optionalNumber'] == 99

        # Check NumberConfig variant
        number_output = [e for e in output_events if e[1]['node_id'] == 'dummy-number'][0][1]['output']
        assert number_output['config_type'] == 'number'
        assert number_output['numberValue'] == 42.5
        assert number_output['optionalString'] == "custom"

        # Check BooleanConfig variant
        boolean_output = [e for e in output_events if e[1]['node_id'] == 'dummy-boolean'][0][1]['output']
        assert boolean_output['config_type'] == 'boolean'
        assert boolean_output['booleanValue'] is True
        assert boolean_output['metadata'] == "test metadata"

        # Verify all completed successfully
        workflow_complete_events = self.get_main_api_emitted_events("workflow:complete")
        assert workflow_complete_events[0][1]['success'] is True

    @pytest.mark.asyncio
    async def test_complete_workflow_with_mixed_configs(self, real_database, frontend_sio, sid):
        """
        Test complete workflow with all node types using proper configs.

        Simulates real-world workflow JSON from frontend with Telegram and Agent nodes.
        Verifies end-to-end config parsing and execution.
        """
        # Setup database
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000003'
        await self.create_test_user(real_database, user_id)
        await self.create_workflow_in_db(real_database, workflow_id, user_id)

        # Realistic workflow: Agent generates message → Telegram sends → Telegram backup
        nodes = [
            {
                "id": "agent-generator",
                "type": "agent",
                "position": {"x": 0, "y": 0},
                "config": self.wrap_node_data("agent", {"system_prompt": "Generate a welcome message", "message": "Generate a welcome message for new users", "temperature": 0.7})
            },
            {
                "id": "telegram-notify",
                "type": "automation-telegram",
                "position": {"x": 100, "y": 0},
                "config": self.wrap_node_data("automation-telegram", {"message": "Notification sent", "chatId": "987654"})
            },
            {
                "id": "telegram-backup",
                "type": "automation-telegram",
                "position": {"x": 200, "y": 0},
                "config": self.wrap_node_data("automation-telegram", {"message": "Backup notification", "chatId": "backup123"})
            }
        ]
        edges = [
            {"id": "e1", "source": "agent-generator", "target": "telegram-notify"},
            {"id": "e2", "source": "telegram-notify", "target": "telegram-backup"}
        ]

        workflow_request = self.create_workflow_request(nodes, edges, workflow_id=workflow_id)
        await send_event(frontend_sio, sid, workflow_request)
        await asyncio.sleep(0.3)

        # Verify all nodes executed with correct configs
        state_events = self.get_main_api_emitted_events("workflow:node:state")
        completed_events = [e for e in state_events if e[1]['state'] == 'completed']
        assert len(completed_events) == 3

        # Verify agent executed with correct config (check final output)
        output_events = self.get_main_api_emitted_events("workflow:node:output")
        agent_outputs = [e for e in output_events if e[1]['node_id'] == 'agent-generator']
        assert agent_outputs[-1][1]['output']['type'] == 'agent'
        assert agent_outputs[-1][1]['output']['status'] == 'completed'
        assert agent_outputs[-1][1]['output']['temperature'] == 0.7

        # Verify telegram used chatId method
        telegram_outputs = [e for e in output_events if e[1]['node_id'] == 'telegram-notify']
        assert telegram_outputs[0][1]['output']['method'] == 'chatId'
        assert telegram_outputs[0][1]['output']['chat_id'] == "987654"

        # Verify backup telegram also used chatId method
        telegram_backup_outputs = [e for e in output_events if e[1]['node_id'] == 'telegram-backup']
        assert telegram_backup_outputs[0][1]['output']['method'] == 'chatId'
        assert telegram_backup_outputs[0][1]['output']['chat_id'] == "backup123"

        # Verify workflow completed successfully
        workflow_complete_events = self.get_main_api_emitted_events("workflow:complete")
        assert workflow_complete_events[0][1]['success'] is True
        assert workflow_complete_events[0][1]['nodes_executed'] == 3

    @pytest.mark.asyncio
    async def test_invalid_config_handling(self, real_database, frontend_sio, sid):
        """
        Test that invalid configs cause workflow failure with clear error messages.

        Uses DummyNode to avoid coupling to production nodes that may change.
        """
        # Setup database
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000003'
        await self.create_test_user(real_database, user_id)
        await self.create_workflow_in_db(real_database, workflow_id, user_id)

        # Create node with incomplete config (doesn't match any Union variant)
        # Using nested config structure expected by NodeConfig-based nodes
        nodes = [
            {
                "id": "dummy-1",
                "type": "test-dummy",
                "position": {"x": 0, "y": 0},
                "config": {
                    "config": {
                        "invalidField": "this field doesn't exist in any variant"
                        # Missing stringValue, numberValue, AND booleanValue - doesn't match any variant!
                    }
                }
            }
        ]
        edges = []

        workflow_request = self.create_workflow_request(nodes, edges, workflow_id=workflow_id)
        await send_event(frontend_sio, sid, workflow_request)
        await asyncio.sleep(0.2)

        # Verify workflow failed
        workflow_complete_events = self.get_main_api_emitted_events("workflow:complete")
        assert len(workflow_complete_events) == 1
        completion_data = workflow_complete_events[0][1]
        assert completion_data['success'] is False
        assert 'error' in completion_data and completion_data['error'] is not None

        # Verify node state shows error with clear message
        state_events = self.get_main_api_emitted_events("workflow:node:state")
        error_events = [e for e in state_events if e[1].get('state') == 'error']
        assert len(error_events) >= 1
        error_message = error_events[0][1].get('error', '')
        assert 'Invalid configuration' in error_message
        # Should mention that fields are required
        assert 'stringValue' in error_message or 'numberValue' in error_message or 'booleanValue' in error_message


    # ─── Error-output handle routing ─────────────────────────────────────────
    #
    # These tests cover the end-to-end execution path for the
    # `_settings.onError = continueErrorOutput` feature: a failing node either
    # (a) routes its error payload exclusively through the wired `error` source
    # handle (success-branch downstream skipped), or (b) falls back to the legacy
    # behavior (no error edge wired ⇒ error payload flows through the default
    # success edge to keep pre-existing workflows working).
    #
    # The graph used:
    #     trigger ─► middle ──default──► success_log
    #                    └──error────► error_log
    # where the `middle` node is forced to raise via a monkeypatched
    # `_execute_node` so we don't need any specific node type to fail.

    @staticmethod
    def _dummy_config(string_value: str, settings: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Build the nested DummyNode config payload, with optional _settings."""
        cfg: Dict[str, Any] = {
            "config": {"stringValue": string_value},
        }
        if settings is not None:
            cfg["_settings"] = settings
        return cfg

    @staticmethod
    def _fail_only(target_node_id: str):
        """Return a replacement for `_execute_node` that raises only for one id.

        For every other node it delegates to the original implementation so we
        get realistic completion events for the surrounding graph.
        """
        original = WorkflowExecutionHandler._execute_node

        async def _patched(self, node, *args, **kwargs):
            if node.get('id') == target_node_id:
                raise RuntimeError(f"Deliberate test failure for node {target_node_id}")
            return await original(self, node, *args, **kwargs)

        return _patched

    @pytest.mark.asyncio
    async def test_error_handle_routes_to_error_branch_only_on_failure(
        self, real_database, frontend_sio, sid, monkeypatch
    ):
        """
        middle fails with continueErrorOutput + wired error edge:
          - middle should still report `completed` (error swallowed).
          - error_log should run (error edge is live).
          - success_log should be `skipped` (default edge dead because middle
            is in state.error_continuations).
        """
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000003'
        await self.create_test_user(real_database, user_id)
        await self.create_workflow_in_db(real_database, workflow_id, user_id)

        monkeypatch.setattr(WorkflowExecutionHandler, '_execute_node', self._fail_only('middle'))

        nodes = [
            {"id": "trigger",     "type": "test-dummy", "position": {"x": 0,   "y": 0},
             "config": self._dummy_config("trigger-ok")},
            {"id": "middle",      "type": "test-dummy", "position": {"x": 100, "y": 0},
             "config": self._dummy_config("middle-fails", settings={"onError": "continueErrorOutput"})},
            {"id": "success_log", "type": "test-dummy", "position": {"x": 200, "y": -50},
             "config": self._dummy_config("success-branch")},
            {"id": "error_log",   "type": "test-dummy", "position": {"x": 200, "y": 50},
             "config": self._dummy_config("error-branch")},
        ]
        edges = [
            {"id": "e1", "source": "trigger", "target": "middle"},
            {"id": "e2", "source": "middle",  "target": "success_log"},  # default handle
            {"id": "e3", "source": "middle",  "target": "error_log", "sourceHandle": "error"},
        ]

        await send_event(frontend_sio, sid, self.create_workflow_request(nodes, edges, workflow_id=workflow_id))
        await asyncio.sleep(0.3)

        state_events = self.get_main_api_emitted_events("workflow:node:state")
        # final state per node (running comes first, then a terminal state)
        # state_events are (event_name, payload, target) triples
        final: Dict[str, str] = {ev[1]['node_id']: ev[1]['state'] for ev in state_events}

        assert final.get('trigger')     == 'completed', f"trigger should complete: {final}"
        assert final.get('middle')      == 'completed', f"middle should complete via continueErrorOutput: {final}"
        assert final.get('error_log')   == 'completed', f"error_log should run via error handle: {final}"
        assert final.get('success_log') == 'skipped',   f"success_log should be skipped: {final}"

        # And the workflow as a whole should be reported as succeeded, since no
        # branch hit stopWorkflow. (workflow:complete payload at index [1].)
        completion = self.get_main_api_emitted_events("workflow:complete")
        assert len(completion) == 1, f"expected 1 workflow:complete event, got {len(completion)}"
        assert completion[0][1]['success'] is True, completion[0][1]

    @pytest.mark.asyncio
    async def test_continue_error_output_without_wired_edge_uses_legacy_default_path(
        self, real_database, frontend_sio, sid, monkeypatch
    ):
        """
        middle fails with continueErrorOutput but the user did NOT wire an
        error edge. Legacy behavior: the error payload flows through the
        default handle and downstream runs normally. This guarantees the new
        routing doesn't break workflows authored before the error handle was
        visible.
        """
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000003'
        await self.create_test_user(real_database, user_id)
        await self.create_workflow_in_db(real_database, workflow_id, user_id)

        monkeypatch.setattr(WorkflowExecutionHandler, '_execute_node', self._fail_only('middle'))

        nodes = [
            {"id": "trigger",    "type": "test-dummy", "position": {"x": 0,   "y": 0},
             "config": self._dummy_config("trigger-ok")},
            {"id": "middle",     "type": "test-dummy", "position": {"x": 100, "y": 0},
             "config": self._dummy_config("middle-fails", settings={"onError": "continueErrorOutput"})},
            {"id": "downstream", "type": "test-dummy", "position": {"x": 200, "y": 0},
             "config": self._dummy_config("downstream")},
        ]
        edges = [
            {"id": "e1", "source": "trigger", "target": "middle"},
            {"id": "e2", "source": "middle",  "target": "downstream"},  # default handle, no error edge anywhere
        ]

        await send_event(frontend_sio, sid, self.create_workflow_request(nodes, edges, workflow_id=workflow_id))
        await asyncio.sleep(0.3)

        state_events = self.get_main_api_emitted_events("workflow:node:state")
        final: Dict[str, str] = {ev[1]['node_id']: ev[1]['state'] for ev in state_events}

        assert final.get('trigger')    == 'completed'
        assert final.get('middle')     == 'completed'
        # Legacy fallback: downstream still runs even though middle errored —
        # it receives middle's error dict via the default handle, matching the
        # pre-routing behavior.
        assert final.get('downstream') == 'completed', f"legacy behavior should keep downstream running: {final}"

    @pytest.mark.asyncio
    async def test_stop_workflow_default_still_cascades_skip(
        self, real_database, frontend_sio, sid, monkeypatch
    ):
        """
        Sanity check that the default onError=stopWorkflow path is unchanged:
        middle raises, lands in state.failed, and downstream nodes are skipped
        — regardless of whether the user wired an error edge.
        """
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000003'
        await self.create_test_user(real_database, user_id)
        await self.create_workflow_in_db(real_database, workflow_id, user_id)

        monkeypatch.setattr(WorkflowExecutionHandler, '_execute_node', self._fail_only('middle'))

        nodes = [
            {"id": "trigger",   "type": "test-dummy", "position": {"x": 0,   "y": 0},
             "config": self._dummy_config("trigger-ok")},
            # No _settings → defaults to stopWorkflow
            {"id": "middle",    "type": "test-dummy", "position": {"x": 100, "y": 0},
             "config": self._dummy_config("middle-fails")},
            {"id": "success_log", "type": "test-dummy", "position": {"x": 200, "y": -50},
             "config": self._dummy_config("success-branch")},
            {"id": "error_log",   "type": "test-dummy", "position": {"x": 200, "y": 50},
             "config": self._dummy_config("error-branch")},
        ]
        edges = [
            {"id": "e1", "source": "trigger", "target": "middle"},
            {"id": "e2", "source": "middle",  "target": "success_log"},
            # Even with an error edge wired, stopWorkflow doesn't reach the
            # continueErrorOutput branch — the exception propagates out.
            {"id": "e3", "source": "middle",  "target": "error_log", "sourceHandle": "error"},
        ]

        await send_event(frontend_sio, sid, self.create_workflow_request(nodes, edges, workflow_id=workflow_id))
        await asyncio.sleep(0.3)

        state_events = self.get_main_api_emitted_events("workflow:node:state")
        final: Dict[str, str] = {ev[1]['node_id']: ev[1]['state'] for ev in state_events}

        assert final.get('trigger') == 'completed'
        assert final.get('middle')  == 'error'
        assert final.get('success_log') == 'skipped'
        assert final.get('error_log')   == 'skipped', "error handle should NOT fire under stopWorkflow"

        completion = self.get_main_api_emitted_events("workflow:complete")
        assert len(completion) == 1, f"expected 1 workflow:complete event, got {len(completion)}"
        assert completion[0][1]['success'] is False, completion[0][1]


@pytest.mark.asyncio
class TestWorkflowExecutionDatabasePersistence(BaseHandlerTest):
    """
    Integration tests for WorkflowExecutionHandler with real PostgreSQL database.

    Verifies that workflow executions are properly persisted to the database:
    - Execution records are created when workflows start
    - Status updates (running → completed/error) are persisted
    - Metadata (duration, nodes_executed, errors) is correctly stored
    """

    def get_session_data(self, sid: str):
        """Override to provide consistent test user ID."""
        return {
            'sid': sid,
            'user_id': '00000000-0000-4000-8000-000000000002',
            'email': 'workflow-test@example.com',
        }

    async def create_test_user(self, real_database, user_id: str):
        """Helper to create a test user in the database."""
        await real_database.execute("""
            INSERT INTO auth.users (id, email)
            VALUES ($1, $2)
            ON CONFLICT (id) DO NOTHING
        """, user_id, 'workflow-test@example.com')

    def wrap_node_data(self, node_type: str, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Wrap config data with credential for the new config structure.

        Args:
            node_type: Type of node (e.g., 'automation-telegram', 'agent')
            config_data: The config data (message, chatId, etc.)

        Returns:
            Dict with config and credential fields
        """
        # Define test credentials for each node type
        credentials = {
            'automation-telegram': {'token': 'test-telegram-token-12345678:ABCdefGHIjklMNOpqrsTUVwxyz'},
            'agent': {'api_key': 'sk-test-openai-key-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'}
        }

        return {
            'config': config_data,
            'credentials': credentials.get(node_type, {})
        }

    async def test_workflow_execution_creates_database_record(self, real_database, frontend_sio, sid):
        """
        Test that workflow execution creates a record in workflow_executions table.

        Verifies:
        - workflow_started event includes execution_id
        - Database record is created with correct initial state
        - Record contains workflow_id, user_id, status='running'
        """
        import uuid

        # Create a workflow first
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000002'

        # Create test user first
        await self.create_test_user(real_database, user_id)

        # Insert workflow into database
        await asyncio.sleep(0.1)  # Ensure connection is ready
        await real_database.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        """, workflow_id, user_id, "Test Workflow", "Test Description", {}, {})

        # Create simple workflow
        nodes = [
            {"id": "node-1", "type": "automation-telegram", "position": {"x": 0, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "DB test", "chatId": "db-123"})},
        ]
        edges = []

        workflow_request = self.create_workflow_request(nodes, edges)
        workflow_request.workflow_id = workflow_id

        await send_event(frontend_sio, sid, workflow_request)
        await asyncio.sleep(0.3)

        # Verify workflow:started event was emitted with execution_id
        started_events = self.get_main_api_emitted_events("workflow:started")
        assert len(started_events) == 1, "Should receive workflow:started event"

        started_data = started_events[0][1]
        execution_id = started_data.get('execution_id')
        assert execution_id is not None, "workflow:started should include execution_id"
        assert isinstance(uuid.UUID(execution_id), uuid.UUID), "execution_id should be valid UUID"

        # Verify database record was created
        execution_row = await real_database.fetchrow("""
            SELECT id, workflow_id, user_id, status, started_at, finished_at, nodes_executed, error
            FROM workflow_executions
            WHERE id = $1
        """, execution_id)

        assert execution_row is not None, "Execution record should exist in database"
        assert str(execution_row['workflow_id']) == workflow_id
        assert str(execution_row['user_id']) == user_id
        assert execution_row['status'] in ('running', 'completed'), "Status should be running or completed"
        assert execution_row['started_at'] is not None, "started_at should be set"

    async def test_workflow_completion_updates_database(self, real_database, frontend_sio, sid):
        """
        Test that workflow completion updates the database record.

        Verifies:
        - Status changes from 'running' to 'completed'
        - finished_at timestamp is set
        - nodes_executed count is correct
        - duration can be calculated from timestamps
        """
        import uuid

        # Create a workflow first
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000002'

        # Create test user first
        await self.create_test_user(real_database, user_id)

        await asyncio.sleep(0.1)
        await real_database.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        """, workflow_id, user_id, "Test Workflow", "Test Description", {}, {})

        # Create workflow with multiple nodes
        nodes = [
            {"id": "node-1", "type": "automation-telegram", "position": {"x": 0, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Completion test 1", "chatId": "comp-1"})},
            {"id": "node-2", "type": "automation-telegram", "position": {"x": 100, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Completion test 2", "chatId": "comp-2"})},
        ]
        edges = [
            {"id": "e1", "source": "node-1", "target": "node-2"},
        ]

        workflow_request = self.create_workflow_request(nodes, edges)
        workflow_request.workflow_id = workflow_id

        await send_event(frontend_sio, sid, workflow_request)
        await asyncio.sleep(0.3)

        # Get execution_id from workflow:started event
        started_events = self.get_main_api_emitted_events("workflow:started")
        execution_id = started_events[0][1]['execution_id']

        # Verify workflow completed
        complete_events = self.get_main_api_emitted_events("workflow:complete")
        assert len(complete_events) == 1
        assert complete_events[0][1]['success'] is True

        # Verify database record was updated
        execution_row = await real_database.fetchrow("""
            SELECT id, status, started_at, finished_at, nodes_executed, error
            FROM workflow_executions
            WHERE id = $1
        """, execution_id)

        assert execution_row is not None
        assert execution_row['status'] == 'completed', "Status should be 'completed'"
        assert execution_row['finished_at'] is not None, "finished_at should be set"
        assert execution_row['nodes_executed'] == 2, "Should have executed 2 nodes"
        assert execution_row['error'] is None, "Error should be None for successful execution"

        # Verify duration can be calculated
        duration = (execution_row['finished_at'] - execution_row['started_at']).total_seconds()
        assert duration >= 0, "Duration should be non-negative"

    async def test_workflow_error_recorded_in_database(self, real_database, frontend_sio, sid):
        """
        Test that workflow errors are properly recorded in the database.

        Verifies:
        - Status is set to 'error' when workflow fails
        - Error message is stored in error column
        - finished_at is still set even on failure
        """
        import uuid

        # Create a workflow first
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000002'

        # Create test user first
        await self.create_test_user(real_database, user_id)

        await asyncio.sleep(0.1)
        await real_database.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        """, workflow_id, user_id, "Test Workflow", "Test Description", {}, {})

        # Create workflow with cycle (will cause error)
        nodes = [
            {"id": "A", "type": "automation-telegram", "position": {"x": 0, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Error A", "chatId": "err-a"})},
            {"id": "B", "type": "automation-telegram", "position": {"x": 100, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Error B", "chatId": "err-b"})},
        ]
        edges = [
            {"id": "e1", "source": "A", "target": "B"},
            {"id": "e2", "source": "B", "target": "A"},  # Creates cycle
        ]

        workflow_request = self.create_workflow_request(nodes, edges)
        workflow_request.workflow_id = workflow_id

        await send_event(frontend_sio, sid, workflow_request)
        await asyncio.sleep(0.3)

        # Get execution_id from workflow:started event (if emitted)
        started_events = self.get_main_api_emitted_events("workflow:started")

        # Workflow might not emit started event if cycle is detected early
        execution_id = started_events[0][1]['execution_id']

        # Verify database record shows error
        execution_row = await real_database.fetchrow("""
            SELECT id, status, error, finished_at, nodes_executed
            FROM workflow_executions
            WHERE id = $1
        """, execution_id)

        assert execution_row is not None
        assert execution_row['status'] == 'error', "Status should be 'error'"
        assert execution_row['error'] is not None, "Error message should be recorded"
        assert 'cycle' in execution_row['error'].lower() or 'order' in execution_row['error'].lower()
        assert execution_row['finished_at'] is not None, "finished_at should be set even on error"
        assert execution_row['nodes_executed'] == 0, "No nodes should have executed"

    async def test_multiple_executions_create_separate_records(self, real_database, frontend_sio, sid):
        """
        Test that multiple executions of the same workflow create separate database records.

        Verifies:
        - Each execution gets unique execution_id
        - All executions are stored in database
        - Executions can be queried by workflow_id
        """
        import uuid

        # Create a workflow first
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000002'

        # Create test user first
        await self.create_test_user(real_database, user_id)

        await asyncio.sleep(0.1)
        await real_database.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        """, workflow_id, user_id, "Test Workflow", "Test Description", {}, {})

        # Run workflow 3 times
        execution_ids = []
        for i in range(3):
            nodes = [
                {"id": f"node-{i}", "type": "automation-telegram", "position": {"x": 0, "y": 0}, "config": {"message": f"Multi-exec {i}", "chatId": f"multi-{i}"}},
            ]
            edges = []

            workflow_request = self.create_workflow_request(nodes, edges, request_id=f"test-req-{i}")
            workflow_request.workflow_id = workflow_id

            await send_event(frontend_sio, sid, workflow_request)
            await asyncio.sleep(0.3)

            # Get execution_id
            started_events = self.get_main_api_emitted_events("workflow:started")
            execution_id = started_events[-1][1]['execution_id']
            execution_ids.append(execution_id)

        # Verify all execution_ids are unique
        assert len(execution_ids) == 3
        assert len(set(execution_ids)) == 3, "All execution_ids should be unique"

        # Verify all executions are in database
        executions = await real_database.fetch("""
            SELECT id, workflow_id, status
            FROM workflow_executions
            WHERE workflow_id = $1
            ORDER BY started_at DESC
        """, workflow_id)

        assert len(executions) >= 3, f"Should have at least 3 execution records, found {len(executions)}"

        # Verify all our execution_ids are in the results
        db_execution_ids = [str(row['id']) for row in executions]
        for exec_id in execution_ids:
            assert exec_id in db_execution_ids, f"Execution {exec_id} should be in database"

    def create_workflow_request(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        request_id: str = "test-workflow-123",
        workflow_id: str = None
    ) -> WorkflowExecuteRequest:
        """Helper to create a workflow execution request."""
        if workflow_id is None:
            workflow_id = str(uuid.uuid4())
        return WorkflowExecuteRequest(
            event_name="workflow:execute",
            request_id=request_id,
            workflow_id=workflow_id,
            nodes=nodes,
            edges=edges
        )


@pytest.mark.asyncio
class TestConcurrentExecution:
    """
    Unit tests for concurrent node execution.

    These tests verify that independent nodes run in parallel and dependent nodes
    wait for their predecessors. Uses synchronization primitives (barriers, events)
    instead of sleeps for deterministic testing.
    """

    @pytest.fixture
    def handler(self):
        """Create handler with mock sio for unit testing."""
        mock_sio = AsyncMock()
        mock_sio.emit = AsyncMock()
        return WorkflowExecutionHandler(sio=mock_sio)

    async def test_independent_nodes_run_concurrently(self, handler):
        """
        Test that nodes with no dependencies execute concurrently.

        Uses a barrier that requires all 3 nodes to arrive before any can proceed.
        If execution were sequential, the barrier would never complete (timeout).
        """
        barrier = asyncio.Barrier(3)
        execution_log = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            async with lock:
                execution_log.append(f"{node_id}:start")

            # All 3 nodes must reach this barrier before any can proceed
            # This proves they're running concurrently
            await asyncio.wait_for(barrier.wait(), timeout=1.0)

            async with lock:
                execution_log.append(f"{node_id}:end")
            return {"node_id": node_id, "status": "completed"}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "A", "type": "test", "config": {}},
            {"id": "B", "type": "test", "config": {}},
            {"id": "C", "type": "test", "config": {}},
        ]
        edges = []  # No dependencies - all can run in parallel

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(nodes, edges, "test-sid", "test-user-id", "test-workflow-id")

        assert error is None
        assert nodes_executed == 3
        # All nodes started before any ended (proves concurrency)
        start_indices = [i for i, log in enumerate(execution_log) if ":start" in log]
        end_indices = [i for i, log in enumerate(execution_log) if ":end" in log]
        assert max(start_indices) < min(end_indices), \
            f"All nodes should start before any ends. Log: {execution_log}"

    async def test_failed_trigger_skips_agent_despite_provider_edge(self, handler):
        """A failed trigger must skip its agent despite a completed provider edge.

        A bottom-handle tool provider is pure capability wiring and must not count
        as a live incoming dataflow edge.
        Provider edges are capability wiring: they gate ORDERING, never
        liveness."""
        executed = []

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            executed.append(node['id'])
            if node['id'] == "trigger":
                raise ValueError("credential dead")
            return {"node_id": node['id']}

        handler._execute_node = mock_execute_node
        nodes = [
            {"id": "trigger", "type": "test", "config": {}},
            {"id": "provider", "type": "test", "config": {"agent_tool_operations": ["create_draft"]}},
            {"id": "agent1", "type": "test", "config": {}},
        ]
        edges = [
            {"source": "trigger", "target": "agent1"},
            {"source": "provider", "target": "agent1",
             "sourceHandle": "top", "targetHandle": "bottom"},
        ]
        nodes_executed, error, _ = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )
        assert "agent1" not in executed, "agent must cascade-skip when its only dataflow predecessor failed"
        assert "provider" in executed  # capability wiring still executes (tool configs)
        assert error and "trigger" in error

    async def test_provider_only_agent_still_runs(self, handler):
        """The inverse guard: an agent whose ONLY incoming edges are tool
        providers (chat-style agent, no dataflow input) has no dataflow
        predecessors — it must run, not cascade-skip."""
        executed = []

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            executed.append(node['id'])
            return {"node_id": node['id']}

        handler._execute_node = mock_execute_node
        nodes = [
            {"id": "provider", "type": "test", "config": {"agent_tool_operations": ["send"]}},
            {"id": "agent1", "type": "test", "config": {}},
        ]
        edges = [
            {"source": "provider", "target": "agent1",
             "sourceHandle": "top", "targetHandle": "bottom"},
        ]
        nodes_executed, error, _ = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )
        assert error is None
        assert "agent1" in executed

    async def test_dependent_node_waits_for_predecessor(self, handler):
        """
        Test that a dependent node waits for its predecessor to complete.

        Uses events to coordinate and verify execution order without sleeps.
        """
        execution_order = []
        lock = asyncio.Lock()
        node_a_completed = asyncio.Event()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']

            if node_id == "B":
                # B should only run after A completes
                # If A hasn't completed, this would fail the test
                assert node_a_completed.is_set(), "B started before A completed!"

            async with lock:
                execution_order.append(f"{node_id}:start")

            # Simulate some work (instant in test)
            async with lock:
                execution_order.append(f"{node_id}:end")

            if node_id == "A":
                node_a_completed.set()

            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "A", "type": "test", "config": {}},
            {"id": "B", "type": "test", "config": {}},
        ]
        edges = [{"source": "A", "target": "B"}]  # B depends on A

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(nodes, edges, "test-sid", "test-user-id", "test-workflow-id")

        assert error is None
        assert nodes_executed == 2
        # A must complete before B starts
        a_end_idx = execution_order.index("A:end")
        b_start_idx = execution_order.index("B:start")
        assert a_end_idx < b_start_idx, \
            f"A should end before B starts. Order: {execution_order}"

    async def test_diamond_pattern_concurrent_middle_nodes(self, handler):
        """
        Test diamond pattern: A → [B, C] → D

        B and C should run concurrently after A completes.
        D should only start after both B and C complete.
        """
        execution_log = []
        lock = asyncio.Lock()
        middle_barrier = asyncio.Barrier(2)  # B and C must both reach this
        node_completions = {"A": asyncio.Event(), "B": asyncio.Event(), "C": asyncio.Event()}

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']

            async with lock:
                execution_log.append(f"{node_id}:start")

            if node_id in ("B", "C"):
                # B and C should reach barrier together (proves concurrency)
                await asyncio.wait_for(middle_barrier.wait(), timeout=1.0)

            if node_id == "D":
                # D should only run after both B and C completed
                assert node_completions["B"].is_set(), "D started before B completed!"
                assert node_completions["C"].is_set(), "D started before C completed!"

            async with lock:
                execution_log.append(f"{node_id}:end")

            if node_id in node_completions:
                node_completions[node_id].set()

            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "A", "type": "test", "config": {}},
            {"id": "B", "type": "test", "config": {}},
            {"id": "C", "type": "test", "config": {}},
            {"id": "D", "type": "test", "config": {}},
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "A", "target": "C"},
            {"source": "B", "target": "D"},
            {"source": "C", "target": "D"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(nodes, edges, "test-sid", "test-user-id", "test-workflow-id")

        assert error is None
        assert nodes_executed == 4

        # Verify order: A before B/C, B/C before D
        a_end = execution_log.index("A:end")
        b_start = execution_log.index("B:start")
        c_start = execution_log.index("C:start")
        d_start = execution_log.index("D:start")
        b_end = execution_log.index("B:end")
        c_end = execution_log.index("C:end")

        assert a_end < b_start and a_end < c_start, "A should complete before B and C start"
        assert b_end < d_start and c_end < d_start, "B and C should complete before D starts"

    async def test_cascade_failure_skips_downstream_nodes(self, handler):
        """
        Test that when a node fails, its downstream nodes are skipped.

        A → B → C: If B fails, C should be skipped (not executed).
        """
        execution_log = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            async with lock:
                execution_log.append(f"{node_id}:start")

            if node_id == "B":
                async with lock:
                    execution_log.append(f"{node_id}:fail")
                raise ValueError("Node B intentionally failed")

            async with lock:
                execution_log.append(f"{node_id}:end")
            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "A", "type": "test", "config": {}},
            {"id": "B", "type": "test", "config": {}},
            {"id": "C", "type": "test", "config": {}},
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(nodes, edges, "test-sid", "test-user-id", "test-workflow-id")

        assert nodes_executed == 1  # Only A completed
        assert error is not None
        assert "Node B failed" in error

        # C should never start (cascade skip)
        assert "C:start" not in execution_log, f"C should be skipped. Log: {execution_log}"
        assert "A:end" in execution_log
        assert "B:start" in execution_log
        assert "B:fail" in execution_log

    async def test_parallel_branches_one_fails_other_completes(self, handler):
        """
        Test parallel branches where one fails but the other can complete.

        A → [B, C] where B fails but C completes.
        Both branches are independent, so C should still complete.
        """
        execution_log = []
        lock = asyncio.Lock()
        both_started = asyncio.Barrier(2)

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            async with lock:
                execution_log.append(f"{node_id}:start")

            if node_id in ("B", "C"):
                # Wait for both to start (proves concurrency)
                await asyncio.wait_for(both_started.wait(), timeout=1.0)

            if node_id == "B":
                async with lock:
                    execution_log.append(f"{node_id}:fail")
                raise ValueError("Node B failed")

            async with lock:
                execution_log.append(f"{node_id}:end")
            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "A", "type": "test", "config": {}},
            {"id": "B", "type": "test", "config": {}},
            {"id": "C", "type": "test", "config": {}},
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "A", "target": "C"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(nodes, edges, "test-sid", "test-user-id", "test-workflow-id")

        # A and C completed, B failed
        assert nodes_executed == 2
        assert error is not None
        assert "Node B failed" in error

        # Both B and C should have started (concurrent after A)
        assert "B:start" in execution_log
        assert "C:start" in execution_log
        assert "C:end" in execution_log

    async def test_max_concurrency_limits_parallel_execution(self, handler):
        """
        Test that max_concurrency limits how many nodes run in parallel.

        With max_concurrency=2 and 4 independent nodes, at most 2 should run at once.
        """
        active_count = 0
        max_active_seen = 0
        lock = asyncio.Lock()
        proceed_events = [asyncio.Event() for _ in range(4)]
        started_events = [asyncio.Event() for _ in range(4)]

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            nonlocal active_count, max_active_seen
            node_idx = int(node['id'].split("-")[1])

            async with lock:
                active_count += 1
                max_active_seen = max(max_active_seen, active_count)

            started_events[node_idx].set()

            # Wait for test to release this node
            await proceed_events[node_idx].wait()

            async with lock:
                active_count -= 1

            return {"node_id": node['id']}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "node-0", "type": "test", "config": {}},
            {"id": "node-1", "type": "test", "config": {}},
            {"id": "node-2", "type": "test", "config": {}},
            {"id": "node-3", "type": "test", "config": {}},
        ]
        edges = []

        # Run with max_concurrency=2
        async def run_workflow():
            return await handler._execute_nodes_concurrent(nodes, edges, "test-sid", "test-user-id", "test-workflow-id", max_concurrency=2)

        task = asyncio.create_task(run_workflow())

        # Wait for first 2 nodes to start
        await asyncio.wait_for(started_events[0].wait(), timeout=1.0)
        await asyncio.wait_for(started_events[1].wait(), timeout=1.0)

        # Give a moment for any additional nodes to start (they shouldn't due to semaphore)
        await asyncio.sleep(0.01)

        # Verify only 2 are active
        async with lock:
            assert active_count == 2, f"Expected 2 active, got {active_count}"

        # Release first 2 nodes
        proceed_events[0].set()
        proceed_events[1].set()

        # Wait for next 2 to start
        await asyncio.wait_for(started_events[2].wait(), timeout=1.0)
        await asyncio.wait_for(started_events[3].wait(), timeout=1.0)

        # Release remaining nodes
        proceed_events[2].set()
        proceed_events[3].set()

        nodes_executed, error, _ = await task

        assert error is None
        assert nodes_executed == 4
        assert max_active_seen == 2, f"Max concurrency violated: saw {max_active_seen} active"

    async def test_disabled_nodes_cascade_skip_to_dependents(self, handler):
        """
        Test that disabled nodes cascade skip to their dependent nodes.

        A → B (disabled) → C: A executes, B is skipped (disabled), C is also skipped
        because its predecessor (B) was skipped. This prevents downstream nodes from
        executing with missing inputs when their dependencies are disabled.
        """
        execution_log = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            async with lock:
                execution_log.append(f"{node_id}:executed")
            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "A", "type": "test", "config": {}},
            {"id": "B", "type": "test", "config": {"disabled": True}},  # Disabled
            {"id": "C", "type": "test", "config": {}},
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(nodes, edges, "test-sid", "test-user-id", "test-workflow-id")

        assert error is None
        assert nodes_executed == 1  # Only A executed, B and C skipped

        # Only A should be executed
        assert "A:executed" in execution_log
        # B and C should not be executed (B is disabled, C skipped because B was skipped)
        assert "B:executed" not in execution_log
        assert "C:executed" not in execution_log

    async def test_disabled_node_diamond_pattern_alternate_path_executes(self, handler):
        """
        Test diamond pattern where node executes via alternate path.

        Graph:
            A → B (disabled) → D
            A → C → D

        D should execute because it has at least one valid path through C.
        Only nodes with ALL predecessors skipped/failed are skipped.
        """
        execution_log = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            async with lock:
                execution_log.append(f"{node_id}:executed")
            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "A", "type": "test", "config": {}},
            {"id": "B", "type": "test", "config": {"disabled": True}},  # Disabled
            {"id": "C", "type": "test", "config": {}},
            {"id": "D", "type": "test", "config": {}},
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "A", "target": "C"},
            {"source": "B", "target": "D"},
            {"source": "C", "target": "D"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(nodes, edges, "test-sid", "test-user-id", "test-workflow-id")

        assert error is None
        assert nodes_executed == 3  # A, C, D executed; B skipped

        assert "A:executed" in execution_log
        assert "C:executed" in execution_log
        assert "D:executed" in execution_log  # Executes via path through C
        assert "B:executed" not in execution_log  # Disabled

    async def test_trigger_and_disabled_node_both_point_to_target(self, handler):
        """
        Test that target executes when trigger is active even if another predecessor is disabled.

        Graph:
            Sheets (disabled) → Slack
            Webhook (trigger) → Slack

        Slack should execute because it has a valid path from the webhook trigger.
        This is a common pattern where a node has multiple inputs but not all are required.
        """
        execution_log = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            async with lock:
                execution_log.append(f"{node_id}:executed")
            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "sheets", "type": "automation-google-sheets", "config": {"disabled": True}},
            {"id": "webhook", "type": "trigger-webhook", "config": {}},
            {"id": "slack", "type": "automation-slack", "config": {"text": "static message"}},
        ]
        edges = [
            {"source": "sheets", "target": "slack"},
            {"source": "webhook", "target": "slack"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(nodes, edges, "test-sid", "test-user-id", "test-workflow-id")

        assert error is None
        assert nodes_executed == 2  # webhook and slack executed; sheets skipped

        assert "webhook:executed" in execution_log
        assert "slack:executed" in execution_log  # Executes via webhook path
        assert "sheets:executed" not in execution_log  # Disabled

    async def test_disabled_node_blocks_entire_branch(self, handler):
        """
        Test that disabled node blocks its entire downstream branch.

        Graph:
            A → B (disabled) → C → D
            A → E

        B, C, D should all be skipped. A and E should execute.
        """
        execution_log = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            async with lock:
                execution_log.append(f"{node_id}:executed")
            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "A", "type": "test", "config": {}},
            {"id": "B", "type": "test", "config": {"disabled": True}},  # Disabled
            {"id": "C", "type": "test", "config": {}},
            {"id": "D", "type": "test", "config": {}},
            {"id": "E", "type": "test", "config": {}},
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
            {"source": "C", "target": "D"},
            {"source": "A", "target": "E"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(nodes, edges, "test-sid", "test-user-id", "test-workflow-id")

        assert error is None
        assert nodes_executed == 2  # A and E executed

        assert "A:executed" in execution_log
        assert "E:executed" in execution_log
        # Entire branch B → C → D should be skipped
        assert "B:executed" not in execution_log
        assert "C:executed" not in execution_log
        assert "D:executed" not in execution_log

    async def test_multiple_disabled_nodes_in_parallel_branches(self, handler):
        """
        Test multiple disabled nodes in parallel branches.

        Graph:
            A → B (disabled) → D
            A → C (disabled) → E
            A → F → G

        Only A, F, G should execute. B, C, D, E should be skipped.
        """
        execution_log = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            async with lock:
                execution_log.append(f"{node_id}:executed")
            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "A", "type": "test", "config": {}},
            {"id": "B", "type": "test", "config": {"disabled": True}},
            {"id": "C", "type": "test", "config": {"disabled": True}},
            {"id": "D", "type": "test", "config": {}},
            {"id": "E", "type": "test", "config": {}},
            {"id": "F", "type": "test", "config": {}},
            {"id": "G", "type": "test", "config": {}},
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "A", "target": "C"},
            {"source": "A", "target": "F"},
            {"source": "B", "target": "D"},
            {"source": "C", "target": "E"},
            {"source": "F", "target": "G"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(nodes, edges, "test-sid", "test-user-id", "test-workflow-id")

        assert error is None
        assert nodes_executed == 3  # A, F, G executed

        assert "A:executed" in execution_log
        assert "F:executed" in execution_log
        assert "G:executed" in execution_log
        # Disabled branches should be skipped
        assert "B:executed" not in execution_log
        assert "C:executed" not in execution_log
        assert "D:executed" not in execution_log
        assert "E:executed" not in execution_log

    async def test_disabled_leaf_node_only_skips_itself(self, handler):
        """
        Test that disabled leaf node only skips itself, not upstream nodes.

        Graph:
            A → B → C (disabled)

        A and B should execute, only C is skipped.
        """
        execution_log = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            async with lock:
                execution_log.append(f"{node_id}:executed")
            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "A", "type": "test", "config": {}},
            {"id": "B", "type": "test", "config": {}},
            {"id": "C", "type": "test", "config": {"disabled": True}},  # Disabled leaf
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(nodes, edges, "test-sid", "test-user-id", "test-workflow-id")

        assert error is None
        assert nodes_executed == 2  # A and B executed, C skipped

        assert "A:executed" in execution_log
        assert "B:executed" in execution_log
        assert "C:executed" not in execution_log

    async def test_disabled_node_with_config_flag(self, handler):
        """
        Test that the config-level disabled flag is respected.

        The disabled flag lives at node["config"]["disabled"] — the flat wire/DB
        shape is the single source of truth (top-level node["disabled"] mirror
        was dropped when the shape was normalized).
        """
        execution_log = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            async with lock:
                execution_log.append(f"{node_id}:executed")
            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "A", "type": "test", "config": {}},
            {"id": "B", "type": "test", "config": {"disabled": True}},  # Config-level disabled
            {"id": "C", "type": "test", "config": {}},
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(nodes, edges, "test-sid", "test-user-id", "test-workflow-id")

        assert error is None
        assert nodes_executed == 1  # Only A executed

        assert "A:executed" in execution_log
        assert "B:executed" not in execution_log
        assert "C:executed" not in execution_log

    async def test_disabled_root_node_skips_entire_workflow(self, handler):
        """
        Test that disabled root node skips entire downstream workflow.

        Graph:
            A (disabled) → B → C
                         → D

        All nodes should be skipped since A is disabled and is the root.
        """
        execution_log = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            async with lock:
                execution_log.append(f"{node_id}:executed")
            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "A", "type": "test", "config": {"disabled": True}},  # Disabled root
            {"id": "B", "type": "test", "config": {}},
            {"id": "C", "type": "test", "config": {}},
            {"id": "D", "type": "test", "config": {}},
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
            {"source": "A", "target": "D"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(nodes, edges, "test-sid", "test-user-id", "test-workflow-id")

        assert error is None
        assert nodes_executed == 0  # No nodes executed

        assert "A:executed" not in execution_log
        assert "B:executed" not in execution_log
        assert "C:executed" not in execution_log
        assert "D:executed" not in execution_log

    async def test_complex_dag_with_multiple_convergence_points(self, handler):
        """
        Test complex DAG with multiple convergence points.

        Graph:
            A → B → D
            A → C → D
            D → E
            D → F → G
                C → G

        Verifies proper synchronization at multiple convergence points.
        """
        execution_log = []
        lock = asyncio.Lock()
        node_completions = {n: asyncio.Event() for n in ["A", "B", "C", "D", "E", "F"]}

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']

            async with lock:
                execution_log.append(f"{node_id}:start")

            # Verify dependencies are met
            deps = {
                "B": ["A"], "C": ["A"],
                "D": ["B", "C"],
                "E": ["D"], "F": ["D"],
                "G": ["F", "C"]
            }
            for dep in deps.get(node_id, []):
                assert node_completions[dep].is_set(), \
                    f"{node_id} started before {dep} completed!"

            async with lock:
                execution_log.append(f"{node_id}:end")

            if node_id in node_completions:
                node_completions[node_id].set()

            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": n, "type": "test", "config": {}}
            for n in ["A", "B", "C", "D", "E", "F", "G"]
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "A", "target": "C"},
            {"source": "B", "target": "D"},
            {"source": "C", "target": "D"},
            {"source": "D", "target": "E"},
            {"source": "D", "target": "F"},
            {"source": "F", "target": "G"},
            {"source": "C", "target": "G"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(nodes, edges, "test-sid", "test-user-id", "test-workflow-id")

        assert error is None
        assert nodes_executed == 7

        # Verify all nodes executed
        for node_id in ["A", "B", "C", "D", "E", "F", "G"]:
            assert f"{node_id}:end" in execution_log, f"Node {node_id} should have completed"

    async def test_tool_node_output_passed_to_agent_node(self, handler):
        """
        Test that ToolNode output is correctly passed to downstream AgentNode.

        This tests the critical path for custom tools:
        1. ToolNode executes and outputs tool_definition
        2. AgentNode receives tool_definition in its inputs
        3. AgentNode's _collect_tool_definitions should find the tool

        Graph: tool → agent

        This regression test ensures tool definitions flow correctly through
        the workflow execution system.
        """
        from nodes.tool_node import ToolNode, ToolNodeConfig, ToolConfig, ToolParameter

        # Track what inputs the agent receives
        agent_received_inputs = {}

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            node_type = node.get('type')

            if node_type == 'tool':
                # Create a real ToolNode to get realistic output
                tool_config = ToolNodeConfig(
                    config=ToolConfig(
                        tool_name="send_message",
                        tool_description="Send a message to telegram",
                        parameters=[
                            ToolParameter(name="message", type="string", description="The message to send", required=True),
                        ],
                    ),
                    credentials=None,
                )
                tool_node = ToolNode(
                    node_id=node_id,
                    node_type="tool",
                    node_data={},
                    config=tool_config,
                    sio=None,
                    sid=None,
                    workflow_id="test",
                )
                return await tool_node.execute({})

            elif node_type == 'agent':
                # Capture what inputs the agent receives
                nonlocal agent_received_inputs
                agent_received_inputs = dict(node_outputs)
                return {"type": "agent", "response": "test response"}

            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        # Workflow: tool_kh6d → agent_mhxu (matching the user's workflow structure)
        nodes = [
            {"id": "tool_kh6d", "type": "tool", "config": {}},
            {"id": "agent_mhxu", "type": "agent", "config": {}},
        ]
        edges = [
            {"source": "tool_kh6d", "target": "agent_mhxu"},
        ]

        nodes_executed, error, node_outputs = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        # Verify execution succeeded
        assert error is None
        assert nodes_executed == 2

        # CRITICAL: Verify agent received the tool output in its inputs
        assert "tool_kh6d" in agent_received_inputs, \
            "Agent should receive tool node output in its inputs"

        tool_output = agent_received_inputs["tool_kh6d"]
        assert tool_output.get("type") == "tool_definition", \
            f"Tool output should be a tool_definition, got: {tool_output.get('type')}"
        assert tool_output.get("tool_name") == "send_message", \
            f"Tool name should be 'send_message', got: {tool_output.get('tool_name')}"

        # Verify the tool can be collected by AgentNode._collect_tool_definitions
        from nodes.agent_node import AgentNode, AgentNodeConfig
        from nodes.agent.config import LLMAgentConfig

        agent_config = AgentNodeConfig(
            config=LLMAgentConfig(
                system_prompt="Test",
                message="Test",
                model="test",
            ),
            credentials=None,
        )
        agent = AgentNode(
            node_id="test-agent",
            node_type="agent",
            node_data={},
            config=agent_config,
            sio=None,
            sid=None,
            workflow_id="test",
        )

        tool_params, tool_configs, _ = agent._collect_tool_definitions(agent_received_inputs)

        assert len(_wired(tool_params)) == 1, \
            f"AgentNode should collect 1 tool from inputs, got {len(_wired(tool_params))}"
        assert _wired(tool_params)[0]["function"]["name"] == "send_message", \
            "Collected tool should have correct name"

    async def test_multiple_tools_to_single_agent(self, handler):
        """
        Test that multiple ToolNodes all pass their definitions to a single AgentNode.

        Graph:
            tool_a ──┐
            tool_b ──┼──→ agent
            tool_c ──┘
        """
        from nodes.tool_node import ToolNode, ToolNodeConfig, ToolConfig, ToolParameter

        agent_received_inputs = {}

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            node_type = node.get('type')

            if node_type == 'tool':
                # Create tool with name matching node_id suffix
                tool_name = f"tool_{node_id.split('_')[-1]}"
                tool_config = ToolNodeConfig(
                    config=ToolConfig(
                        tool_name=tool_name,
                        tool_description=f"Description for {tool_name}",
                        parameters=[],
                    ),
                    credentials=None,
                )
                tool_node = ToolNode(
                    node_id=node_id,
                    node_type="tool",
                    node_data={},
                    config=tool_config,
                    sio=None,
                    sid=None,
                    workflow_id="test",
                )
                return await tool_node.execute({})

            elif node_type == 'agent':
                nonlocal agent_received_inputs
                agent_received_inputs = dict(node_outputs)
                return {"type": "agent", "response": "test"}

            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "tool_a", "type": "tool", "config": {}},
            {"id": "tool_b", "type": "tool", "config": {}},
            {"id": "tool_c", "type": "tool", "config": {}},
            {"id": "agent_1", "type": "agent", "config": {}},
        ]
        edges = [
            {"source": "tool_a", "target": "agent_1"},
            {"source": "tool_b", "target": "agent_1"},
            {"source": "tool_c", "target": "agent_1"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None
        assert nodes_executed == 4

        # Verify all 3 tool outputs are in agent inputs
        assert len(agent_received_inputs) == 3
        for tool_id in ["tool_a", "tool_b", "tool_c"]:
            assert tool_id in agent_received_inputs
            assert agent_received_inputs[tool_id].get("type") == "tool_definition"

        # Verify AgentNode can collect all 3 tools
        from nodes.agent_node import AgentNode, AgentNodeConfig
        from nodes.agent.config import LLMAgentConfig

        agent = AgentNode(
            node_id="test",
            node_type="agent",
            node_data={},
            config=AgentNodeConfig(
                config=LLMAgentConfig(system_prompt="t", message="t", model="t"),
                credentials=None,
            ),
            sio=None,
            sid=None,
            workflow_id="test",
        )

        tool_params, _, _ = agent._collect_tool_definitions(agent_received_inputs)
        assert len(_wired(tool_params)) == 3
        tool_names = {tp["function"]["name"] for tp in _wired(tool_params)}
        assert tool_names == {"tool_a", "tool_b", "tool_c"}

    def test_get_reachable_nodes_excludes_upstream_tools(self, handler):
        """
        Upstream tool nodes are NOT in the execution set — their cached
        outputs are preloaded separately. Only forward + interface/state-manager
        backfill nodes are included.

        Graph: tool → agent → downstream
        Starting from agent should include agent + downstream, NOT tool.
        """
        nodes = [
            {"id": "tool_kh6d", "type": "tool"},
            {"id": "agent_mhxu", "type": "agent"},
            {"id": "telegram_25y8", "type": "automation-telegram"},
        ]
        edges = [
            {"source": "tool_kh6d", "target": "agent_mhxu"},
            {"source": "agent_mhxu", "target": "telegram_25y8"},
        ]

        reachable_nodes, reachable_edges = handler._get_reachable_nodes(
            "agent_mhxu", nodes, edges,
        )

        reachable_ids = {n["id"] for n in reachable_nodes}
        assert "tool_kh6d" not in reachable_ids, \
            "Upstream tool should NOT be in execution set (preloaded from cache)"
        assert reachable_ids == {"agent_mhxu", "telegram_25y8"}
        assert len(reachable_edges) == 1

    def test_get_reachable_nodes_backfills_interface_nodes(self, handler):
        """
        Upstream interface-* and state-manager nodes ARE backfilled into
        the execution set because they provide user-configured data.

        Graph:
            form ──┐
            tool ──┼──→ agent ──→ telegram
            state ─┘       └──→ email
        """
        nodes = [
            {"id": "form", "type": "interface-form"},
            {"id": "tool", "type": "tool"},
            {"id": "state", "type": "state-manager"},
            {"id": "agent", "type": "agent"},
            {"id": "telegram", "type": "automation-telegram"},
            {"id": "email", "type": "automation-gmail"},
        ]
        edges = [
            {"source": "form", "target": "agent"},
            {"source": "tool", "target": "agent"},
            {"source": "state", "target": "agent"},
            {"source": "agent", "target": "telegram"},
            {"source": "agent", "target": "email"},
        ]

        reachable_nodes, _ = handler._get_reachable_nodes(
            "agent", nodes, edges,
        )

        reachable_ids = {n["id"] for n in reachable_nodes}
        assert "form" in reachable_ids, "interface-form should be backfilled"
        assert "state" in reachable_ids, "state-manager should be backfilled"
        assert "tool" not in reachable_ids, "tool should NOT be backfilled"
        assert reachable_ids == {"form", "state", "agent", "telegram", "email"}

    def test_get_reachable_nodes_excludes_unrelated_predecessors(self, handler):
        """
        Unrelated nodes that share a downstream target are excluded.

        Graph:
            sheets ──→ slack
            webhook ─┘

        Starting from webhook should only include webhook and slack,
        NOT sheets.
        """
        nodes = [
            {"id": "sheets", "type": "automation-google-sheets"},
            {"id": "webhook", "type": "trigger-webhook"},
            {"id": "slack", "type": "automation-slack"},
        ]
        edges = [
            {"source": "sheets", "target": "slack"},
            {"source": "webhook", "target": "slack"},
        ]

        reachable_nodes, reachable_edges = handler._get_reachable_nodes(
            "webhook", nodes, edges,
        )

        reachable_ids = {n["id"] for n in reachable_nodes}
        assert reachable_ids == {"webhook", "slack"}

        assert len(reachable_edges) == 1
        assert reachable_edges[0]["source"] == "webhook"
        assert reachable_edges[0]["target"] == "slack"

    async def test_tool_downstream_nodes_not_executed_in_main_workflow(self, handler):
        """
        Test that tool implementation nodes (downstream of tool, not agent)
        are NOT executed during main workflow execution.

        They should only be executed when the agent calls the tool via
        _execute_workflow_tool.

        Graph:
            tool_kh6d ──→ agent_mhxu (definition edge - agent collects tool)
            tool_kh6d ──→ telegram_25y8 (implementation edge - telegram is tool's action)

        During main workflow execution:
        - tool_kh6d should execute (outputs definition)
        - agent_mhxu should execute (collects tool, calls LLM)
        - telegram_25y8 should NOT execute (it's tool implementation)

        telegram_25y8 should only execute when agent calls the tool.
        """
        from nodes.tool_node import ToolNode, ToolNodeConfig, ToolConfig, ToolParameter

        executed_nodes = []

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            node_type = node.get('type')
            executed_nodes.append(node_id)

            if node_type == 'tool':
                # Return tool definition
                return {
                    'type': 'tool_definition',
                    'tool_type': 'workflow',
                    'tool_name': 'send_message',
                    'tool_description': 'Send a message to telegram',
                    'parameters': [{'name': 'message', 'type': 'string', 'required': True}],
                }
            elif node_type == 'agent':
                return {'type': 'agent', 'response': 'test'}
            elif node_type == 'automation-telegram':
                # This should NOT be called during main workflow execution
                # If {{tool_kh6d.arguments.message}} is in config, it will be None
                # because tool output has no 'arguments' field
                message = node_outputs.get('tool_kh6d', {}).get('arguments', {}).get('message')
                if message is None:
                    raise ValueError("message is None - tool arguments not available in main workflow")
                return {'type': 'telegram', 'sent': True}

            return {'node_id': node_id}

        handler._execute_node = mock_execute_node

        # Exact workflow structure from user's JSON
        nodes = [
            {"id": "agent_mhxu", "type": "agent", "config": {}},
            {"id": "tool_kh6d", "type": "tool", "config": {}},
            {"id": "telegram_25y8", "type": "automation-telegram", "config": {
                "message": "{{tool_kh6d.arguments.message}}"
            }},
        ]
        edges = [
            {"source": "tool_kh6d", "target": "agent_mhxu"},  # tool → agent (definition)
            {"source": "tool_kh6d", "target": "telegram_25y8"},  # tool → telegram (implementation)
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        # telegram_25y8 should NOT be in executed_nodes
        # It should only execute when agent calls the tool
        assert "telegram_25y8" not in executed_nodes, \
            f"Tool implementation node should not execute during main workflow. Executed: {executed_nodes}"

        # tool and agent should have executed
        assert "tool_kh6d" in executed_nodes
        assert "agent_mhxu" in executed_nodes

        # No error should have occurred
        assert error is None, f"Unexpected error: {error}"

    @pytest.mark.asyncio
    async def test_tool_downstream_execution_complex_graph(self, handler):
        """
        COMPREHENSIVE TEST: Verify tool downstream execution handles complex graphs.

        This tests the execute_tool_downstream callback that AgentNode uses when
        the LLM calls a tool. It should:
        1. Execute ALL reachable downstream nodes (not just immediate children)
        2. Respect topological ordering (dependencies execute first)
        3. Pass tool arguments through for reference resolution
        4. Handle branches and joins correctly

        Graph structure:
            tool_node ──→ agent_node (definition edge - excluded from downstream)
            tool_node ──→ node_a ──→ node_c
                      └─→ node_b ───┘
                                    └─→ node_d

        When tool is called with arguments {message: "hello", count: 5}:
        - node_a, node_b should execute (immediate downstream, excluding agent)
        - node_c should execute (depends on node_a AND node_b joining)
        - node_d should execute (depends on node_c)
        - All nodes should have access to tool arguments via {{tool_node.message}}
        """
        from collections import deque

        # Track execution order and received arguments
        execution_order = []
        received_arguments = {}

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            node_type = node.get('type')
            execution_order.append(node_id)

            # Capture what tool arguments each node sees via node_outputs
            tool_output = node_outputs.get('tool_node', {})
            received_arguments[node_id] = {
                'message': tool_output.get('message'),
                'count': tool_output.get('count'),
            }

            if node_type == 'tool':
                return {
                    'type': 'tool_definition',
                    'tool_name': 'my_tool',
                    'tool_description': 'Test tool',
                    'parameters': [],
                }
            elif node_type == 'agent':
                return {'type': 'agent', 'response': 'test'}
            else:
                # Return the node's received message to verify reference resolution
                return {
                    'node_id': node_id,
                    'received_message': tool_output.get('message'),
                    'received_count': tool_output.get('count'),
                }

        handler._execute_node = mock_execute_node

        # Complex graph with branches and joins
        workflow_nodes = [
            {"id": "tool_node", "type": "tool", "config": {}},
            {"id": "agent_node", "type": "agent", "config": {}},
            {"id": "node_a", "type": "processor", "config": {"input": "{{tool_node.message}}"}},
            {"id": "node_b", "type": "processor", "config": {"input": "{{tool_node.count}}"}},
            {"id": "node_c", "type": "combiner", "config": {}},  # Joins node_a and node_b
            {"id": "node_d", "type": "final", "config": {}},  # After node_c
        ]
        workflow_edges = [
            {"source": "tool_node", "target": "agent_node"},  # Definition edge (excluded)
            {"source": "tool_node", "target": "node_a"},  # Downstream edge
            {"source": "tool_node", "target": "node_b"},  # Downstream edge
            {"source": "node_a", "target": "node_c"},  # node_c depends on node_a
            {"source": "node_b", "target": "node_c"},  # node_c depends on node_b (join)
            {"source": "node_c", "target": "node_d"},  # node_d depends on node_c
        ]

        # Simulate what happens when agent calls the tool
        # This is what execute_tool_downstream does internally
        tool_node_id = "tool_node"
        agent_node_id = "agent_node"
        tool_arguments = {"message": "hello world", "count": 5}

        # Build successors map (forward edges only)
        node_by_id = {n['id']: n for n in workflow_nodes}
        successors = {n['id']: [] for n in workflow_nodes}
        for edge in workflow_edges:
            source, target = edge.get('source'), edge.get('target')
            if source and target and source in successors:
                successors[source].append(target)

        # BFS to find all reachable downstream nodes (excluding agent)
        visited = set()
        queue = deque([tool_node_id])
        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            for succ in successors.get(nid, []):
                if succ not in visited and succ != agent_node_id:
                    queue.append(succ)

        # Remove tool node itself
        visited.discard(tool_node_id)

        # Get downstream nodes and edges
        downstream_nodes = [n for n in workflow_nodes if n['id'] in visited]
        downstream_edges = [
            e for e in workflow_edges
            if e.get('source') in visited and e.get('target') in visited
        ]

        # Prepare initial outputs with tool arguments
        initial_outputs = {
            tool_node_id: {
                'type': 'tool_call',
                'tool_name': tool_node_id,
                'arguments': tool_arguments,
                **tool_arguments  # Also at top level for simpler reference
            }
        }

        # Execute the downstream subgraph
        nodes_executed, error, downstream_outputs = await handler._execute_nodes_concurrent(
            downstream_nodes,
            downstream_edges,
            "test-sid",
            "test-user-id",
            "test-workflow-id",
            initial_outputs=initial_outputs
        )

        # === ASSERTIONS ===

        # 1. No errors
        assert error is None, f"Unexpected error: {error}"

        # 2. All 4 downstream nodes should have executed
        assert nodes_executed == 4, f"Expected 4 nodes executed, got {nodes_executed}"
        assert set(execution_order) == {"node_a", "node_b", "node_c", "node_d"}, \
            f"Wrong nodes executed: {execution_order}"

        # 3. Agent node should NOT be executed (it's excluded)
        assert "agent_node" not in execution_order, \
            "Agent node should not be in downstream execution"

        # 4. Topological ordering: node_c must come after both node_a and node_b
        idx_a = execution_order.index("node_a")
        idx_b = execution_order.index("node_b")
        idx_c = execution_order.index("node_c")
        idx_d = execution_order.index("node_d")

        assert idx_c > idx_a, f"node_c ({idx_c}) should execute after node_a ({idx_a})"
        assert idx_c > idx_b, f"node_c ({idx_c}) should execute after node_b ({idx_b})"
        assert idx_d > idx_c, f"node_d ({idx_d}) should execute after node_c ({idx_c})"

        # 5. Tool arguments should be available to all downstream nodes
        for node_id in ["node_a", "node_b", "node_c", "node_d"]:
            args = received_arguments.get(node_id, {})
            assert args.get('message') == "hello world", \
                f"Node {node_id} should receive message='hello world', got {args.get('message')}"
            assert args.get('count') == 5, \
                f"Node {node_id} should receive count=5, got {args.get('count')}"

        # 6. Downstream outputs should contain results from all nodes
        assert "node_a" in downstream_outputs
        assert "node_b" in downstream_outputs
        assert "node_c" in downstream_outputs
        assert "node_d" in downstream_outputs

        # 7. Each node's output should reflect it received the tool arguments
        assert downstream_outputs["node_a"]["received_message"] == "hello world"
        assert downstream_outputs["node_b"]["received_count"] == 5


class TestTriggerProviderEitherOr:
    """A provider-wired node that receives a trigger payload must NOT use it as
    output — provider mode wins (legacy-combo runtime guard; new combos are
    rejected at edit time by workflow_ops.trigger_provider_conflict)."""

    @pytest.fixture
    def handler(self):
        return WorkflowExecutionHandler(sio=None)

    @pytest.mark.asyncio
    async def test_trigger_payload_ignored_on_provider_wired_node(self, handler):
        executed_ids = []

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            executed_ids.append(node['id'])
            return {"type": "mock", "node_id": node['id']}

        handler._execute_node = mock_execute_node
        handler._emit_node_state = AsyncMock()
        handler._emit_node_output = AsyncMock()

        nodes = [
            {"id": "github", "type": "automation-github-rest",
             "config": {"_triggerPayload": {"action": "opened"},
                        "agent_tool_operations": ["create_pull_request"]}},
            {"id": "agent1", "type": "agent", "config": {}},
        ]
        edges = [{"source": "github", "target": "agent1",
                  "sourceHandle": "top", "targetHandle": "bottom"}]

        nodes_executed, error, outputs = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None, error
        # The payload must NOT have short-circuited the provider node: it fell
        # through to _execute_node (where provider mode produces tool metadata).
        assert "github" in executed_ids
        assert outputs["github"] == {"type": "mock", "node_id": "github"}

    @pytest.mark.asyncio
    async def test_trigger_payload_still_short_circuits_plain_trigger(self, handler):
        executed_ids = []

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            executed_ids.append(node['id'])
            return {"type": "mock", "node_id": node['id']}

        handler._execute_node = mock_execute_node
        handler._emit_node_state = AsyncMock()
        handler._emit_node_output = AsyncMock()

        payload = {"type": "webhook-trigger", "payload": {"a": 1}}
        nodes = [
            {"id": "trig1", "type": "trigger-webhook", "config": {"_triggerPayload": payload}},
            {"id": "agent1", "type": "agent", "config": {}},
        ]
        edges = [{"source": "trig1", "target": "agent1"}]

        nodes_executed, error, outputs = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None, error
        assert "trig1" not in executed_ids  # short-circuited, execute skipped
        assert outputs["trig1"] == payload


class TestNonPropagatingOutputs:
    @pytest.fixture
    def handler(self):
        return WorkflowExecutionHandler(sio=None)

    @pytest.mark.asyncio
    async def test_empty_google_drive_trigger_output_skips_downstream(self, handler):
        executed_ids = []

        async def mock_execute_node(
            node,
            node_outputs,
            sid,
            user_id,
            workflow_id,
            conversation_id=None,
            workflow_nodes=None,
            workflow_edges=None,
            workflow_org_id=None,
            execution_id=None,
        ):
            executed_ids.append(node["id"])
            if node["id"] == "drive-trigger":
                return {"changes": [], "change_count": 0}
            return {"status": "unexpected"}

        handler._execute_node = mock_execute_node
        handler._emit_node_state = AsyncMock()
        handler._emit_node_output = AsyncMock()

        nodes = [
            {
                "id": "drive-trigger",
                "type": "automation-google-drive",
                "config": {"operation": "on_file_changed"},
            },
            {
                "id": "downstream",
                "type": "automation-serverless-function",
                "config": {},
            },
        ]
        edges = [{"source": "drive-trigger", "target": "downstream"}]

        nodes_executed, error, outputs = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None
        assert executed_ids == ["drive-trigger"]
        assert nodes_executed == 0
        assert outputs["drive-trigger"]["change_count"] == 0

        emitted_states = [call.args[4] for call in handler._emit_node_state.await_args_list]
        assert "skipped" in emitted_states


class TestManualReplayCandidates:
    """Manual runs replay a pure event trigger's last persisted output instead
    of executing it (an event-less execution breaks every downstream
    {{ $('trigger').field }} reference)."""

    @pytest.fixture
    def handler(self):
        return WorkflowExecutionHandler(sio=None)

    def test_webhook_trigger_without_payload_is_candidate(self, handler):
        nodes = [{"id": "webhook", "type": "trigger-webhook", "config": {}}]
        assert [n["id"] for n in handler._manual_replay_candidates(nodes)] == ["webhook"]

    def test_inbound_email_trigger_is_candidate(self, handler):
        nodes = [{"id": "mail", "type": "trigger-inbound-email", "config": {}}]
        # Node type key per registry — resolve dynamically to avoid pinning a name.
        from nodes.core.registry import NODE_REGISTRY
        from nodes.inbound_email_trigger_node import InboundEmailTriggerNode
        type_key = next(k for k, v in NODE_REGISTRY.items() if v is InboundEmailTriggerNode)
        nodes[0]["type"] = type_key
        assert len(handler._manual_replay_candidates(nodes)) == 1

    def test_fired_trigger_payload_excludes(self, handler):
        nodes = [{"id": "webhook", "type": "trigger-webhook",
                  "config": {"_triggerPayload": {"x": 1}}}]
        assert handler._manual_replay_candidates(nodes) == []

    def test_mocked_output_excludes(self, handler):
        nodes = [{"id": "webhook", "type": "trigger-webhook",
                  "config": {"mockedOutput": {"x": 1}}}]
        assert handler._manual_replay_candidates(nodes) == []

    def test_non_replay_node_types_excluded(self, handler):
        nodes = [
            {"id": "cron", "type": "trigger-cron", "config": {}},
            {"id": "sheets", "type": "automation-google-sheets", "config": {}},
            {"id": "fn", "type": "automation-serverless-function", "config": {}},
        ]
        assert handler._manual_replay_candidates(nodes) == []

    def test_poll_triggers_never_replay(self):
        """Poll triggers fetch on demand — replaying would hide fresh data.
        Pins the invariant that no ScheduledPollTriggerMixin node sets the flag."""
        from nodes.core.registry import NODE_REGISTRY
        from nodes.core.poll_trigger import ScheduledPollTriggerMixin
        offenders = [
            key for key, cls in NODE_REGISTRY.items()
            if isinstance(cls, type)
            and issubclass(cls, ScheduledPollTriggerMixin)
            and getattr(cls, 'manual_run_replays_last_event', False)
        ]
        assert offenders == []
