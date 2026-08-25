"""
Tests for the run trigger node implementation.

Validates RunTriggerNode execution, registration, and priority behavior
in _find_input_node() to ensure it acts as the highest-priority entry point.
"""

import pytest
from unittest.mock import AsyncMock

from nodes.run_trigger_node import RunTriggerNode
from nodes.core.registry import NODE_REGISTRY
from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler


class TestRunTriggerNodeExecution:
    """Test the execute method."""

    @pytest.mark.asyncio
    async def test_execute_outputs_trigger_metadata(self):
        """Should output run-trigger metadata with correct structure."""
        node = RunTriggerNode(
            node_id='run_node_1',
            node_type='trigger-run',
            node_data={},
            config=None,
            sio=None,
            sid=None,
            workflow_id='wf_123'
        )

        node.emit = AsyncMock()

        result = await node.execute({})

        assert result['type'] == 'run-trigger'
        assert result['status'] == 'triggered'
        assert 'timestamp' in result
        assert 'payload' not in result

        node.emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_does_not_store_inputs(self):
        """Output must NOT include inputs to avoid circular references.

        The execution handler passes node_outputs (dict of all prior outputs) as inputs.
        If execute() stores that dict in its output, a circular reference forms when
        node_outputs[this_node_id] = output — because output would contain node_outputs itself.
        """
        node = RunTriggerNode(
            node_id='run_node_1',
            node_type='trigger-run',
            node_data={},
            config=None,
            sio=None,
            sid=None,
            workflow_id='wf_123'
        )

        node.emit = AsyncMock()

        # Simulate node_outputs dict that the execution handler passes
        node_outputs = {
            'other-node': {'some': 'data'},
        }

        result = await node.execute(node_outputs)

        # Output must not reference node_outputs to avoid circular refs
        assert 'payload' not in result
        assert result['type'] == 'run-trigger'
        assert result['status'] == 'triggered'

    @pytest.mark.asyncio
    async def test_output_is_json_serializable(self):
        """Output should always be safely JSON-serializable (no circular refs)."""
        import json

        node = RunTriggerNode(
            node_id='run_node_1',
            node_type='trigger-run',
            node_data={},
            config=None,
            sio=None,
            sid=None,
            workflow_id='wf_123'
        )

        node.emit = AsyncMock()

        # Simulate what the execution handler does: pass node_outputs, store result back
        node_outputs = {}
        result = await node.execute(node_outputs)
        node_outputs['run_node_1'] = result

        # Must not raise ValueError: Circular reference detected
        serialized = json.dumps(node_outputs)
        assert '"run-trigger"' in serialized

    @pytest.mark.asyncio
    async def test_execute_emits_output(self):
        """Should emit the same output dict it returns."""
        node = RunTriggerNode(
            node_id='run_node_1',
            node_type='trigger-run',
            node_data={},
            config=None,
            sio=None,
            sid=None,
            workflow_id='wf_123'
        )

        node.emit = AsyncMock()

        result = await node.execute({})

        emitted = node.emit.call_args[0][0]
        assert emitted == result


class TestRunTriggerNodeRegistration:
    """Test node registration in registry."""

    def test_node_is_registered(self):
        """Should be registered in NODE_REGISTRY as trigger-run."""
        assert 'trigger-run' in NODE_REGISTRY
        assert NODE_REGISTRY['trigger-run'] == RunTriggerNode

    def test_no_config_model(self):
        """Should have no config model (simplest trigger)."""
        model = RunTriggerNode.get_config_model()
        assert model is None


class TestFindInputNodePriority:
    """Test that trigger-run is the highest-priority entry point in _find_input_node."""

    @pytest.fixture
    def handler(self):
        return WorkflowExecutionHandler(sio=None)

    def test_run_trigger_chosen_over_webhook(self, handler):
        """trigger-run should be chosen over trigger-webhook."""
        nodes = [
            {"id": "webhook-1", "type": "trigger-webhook"},
            {"id": "run-1", "type": "trigger-run"},
        ]
        edges = []

        result = handler._find_input_node(nodes, edges, start_node_id=None)
        assert result == "run-1"

    def test_run_trigger_chosen_over_cron(self, handler):
        """trigger-run should be chosen over trigger-cron."""
        nodes = [
            {"id": "cron-1", "type": "trigger-cron"},
            {"id": "run-1", "type": "trigger-run"},
        ]
        edges = []

        result = handler._find_input_node(nodes, edges, start_node_id=None)
        assert result == "run-1"

    def test_run_trigger_chosen_over_form_input(self, handler):
        """trigger-run should be chosen over the unified form node."""
        nodes = [
            {"id": "form-1", "type": "interface-form"},
            {"id": "run-1", "type": "trigger-run"},
        ]
        edges = []

        result = handler._find_input_node(nodes, edges, start_node_id=None)
        assert result == "run-1"

    def test_run_trigger_chosen_over_all_triggers(self, handler):
        """trigger-run should be chosen even with all other trigger types present."""
        nodes = [
            {"id": "webhook-1", "type": "trigger-webhook"},
            {"id": "cron-1", "type": "trigger-cron"},
            # Legacy pre-merge form type — pins alias resolution in _find_input_node.
            {"id": "form-1", "type": "trigger-form-input"},
            {"id": "run-1", "type": "trigger-run"},
        ]
        edges = []

        result = handler._find_input_node(nodes, edges, start_node_id=None)
        assert result == "run-1"

    def test_run_trigger_chosen_regardless_of_order(self, handler):
        """trigger-run should win even when listed last in nodes array."""
        nodes = [
            {"id": "agent-1", "type": "agent"},
            {"id": "telegram-1", "type": "automation-telegram"},
            {"id": "webhook-1", "type": "trigger-webhook"},
            {"id": "run-1", "type": "trigger-run"},
        ]
        edges = []

        result = handler._find_input_node(nodes, edges, start_node_id=None)
        assert result == "run-1"

    def test_run_trigger_chosen_when_first_in_list(self, handler):
        """trigger-run should win when listed first too (no regression)."""
        nodes = [
            {"id": "run-1", "type": "trigger-run"},
            {"id": "webhook-1", "type": "trigger-webhook"},
            {"id": "agent-1", "type": "agent"},
        ]
        edges = []

        result = handler._find_input_node(nodes, edges, start_node_id=None)
        assert result == "run-1"

    def test_explicit_start_node_overrides_run_trigger(self, handler):
        """Explicit start_node_id should still override trigger-run."""
        nodes = [
            {"id": "run-1", "type": "trigger-run"},
            {"id": "agent-1", "type": "agent"},
        ]
        edges = []

        result = handler._find_input_node(nodes, edges, start_node_id="agent-1")
        assert result == "agent-1"

    def test_fallback_to_webhook_without_run_trigger(self, handler):
        """Without trigger-run, should fall back to other trigger types."""
        nodes = [
            {"id": "agent-1", "type": "agent"},
            {"id": "webhook-1", "type": "trigger-webhook"},
        ]
        edges = []

        result = handler._find_input_node(nodes, edges, start_node_id=None)
        assert result == "webhook-1"

    def test_fallback_to_form_without_run_trigger(self, handler):
        """Without trigger-run, the unified form node is a trigger entry point."""
        nodes = [
            {"id": "agent-1", "type": "agent"},
            {"id": "form-1", "type": "interface-form"},
        ]
        edges = []

        result = handler._find_input_node(nodes, edges, start_node_id=None)
        assert result == "form-1"

    def test_fallback_to_no_predecessors_without_triggers(self, handler):
        """Without any triggers, should fall back to first node with no predecessors."""
        nodes = [
            {"id": "agent-1", "type": "agent"},
            {"id": "agent-2", "type": "agent"},
        ]
        edges = [
            {"source": "agent-1", "target": "agent-2"},
        ]

        result = handler._find_input_node(nodes, edges, start_node_id=None)
        assert result == "agent-1"

    def test_returns_none_for_empty_nodes(self, handler):
        """Should return None when no nodes provided."""
        result = handler._find_input_node([], [], start_node_id=None)
        assert result is None

    def test_run_trigger_with_edges(self, handler):
        """trigger-run should be selected even when it has outgoing edges."""
        nodes = [
            {"id": "run-1", "type": "trigger-run"},
            {"id": "agent-1", "type": "agent"},
            {"id": "agent-2", "type": "agent"},
        ]
        edges = [
            {"source": "run-1", "target": "agent-1"},
            {"source": "agent-1", "target": "agent-2"},
        ]

        result = handler._find_input_node(nodes, edges, start_node_id=None)
        assert result == "run-1"

    def test_run_trigger_in_disconnected_subworkflows(self, handler):
        """trigger-run in one subworkflow should be the entry point, ignoring the other."""
        nodes = [
            # Subworkflow A (no run trigger)
            {"id": "a-start", "type": "agent"},
            {"id": "a-end", "type": "automation-telegram"},
            # Subworkflow B (has run trigger)
            {"id": "run-1", "type": "trigger-run"},
            {"id": "b-end", "type": "automation-telegram"},
        ]
        edges = [
            {"source": "a-start", "target": "a-end"},
            {"source": "run-1", "target": "b-end"},
        ]

        result = handler._find_input_node(nodes, edges, start_node_id=None)
        assert result == "run-1"


class TestRunTriggerInTopologicalSort:
    """Test that trigger-run works correctly in topological sorting."""

    @pytest.fixture
    def handler(self):
        return WorkflowExecutionHandler(sio=None)

    def test_run_trigger_in_linear_workflow(self, handler):
        """trigger-run should appear first in topological order when it's the root."""
        nodes = [
            {"id": "run-1", "type": "trigger-run"},
            {"id": "agent-1", "type": "agent"},
            {"id": "agent-2", "type": "agent"},
        ]
        edges = [
            {"source": "run-1", "target": "agent-1"},
            {"source": "agent-1", "target": "agent-2"},
        ]

        order = handler._topological_sort(nodes, edges)
        assert len(order) == 3
        assert order[0] == "run-1"
        assert order.index("agent-1") < order.index("agent-2")

    def test_run_trigger_in_branching_workflow(self, handler):
        """trigger-run should be first when it fans out to multiple branches."""
        nodes = [
            {"id": "run-1", "type": "trigger-run"},
            {"id": "branch-a", "type": "agent"},
            {"id": "branch-b", "type": "automation-telegram"},
            {"id": "merge", "type": "agent"},
        ]
        edges = [
            {"source": "run-1", "target": "branch-a"},
            {"source": "run-1", "target": "branch-b"},
            {"source": "branch-a", "target": "merge"},
            {"source": "branch-b", "target": "merge"},
        ]

        order = handler._topological_sort(nodes, edges)
        assert len(order) == 4
        assert order[0] == "run-1"
        assert order[-1] == "merge"


class TestRunTriggerReachableNodes:
    """Test that _get_reachable_nodes works correctly with trigger-run."""

    @pytest.fixture
    def handler(self):
        return WorkflowExecutionHandler(sio=None)

    def test_only_downstream_nodes_reachable_from_run_trigger(self, handler):
        """Since trigger-run starts with 'trigger-', only forward traversal should happen."""
        nodes = [
            # Subworkflow A (disconnected)
            {"id": "a-start", "type": "agent"},
            {"id": "a-end", "type": "automation-telegram"},
            # Subworkflow B (connected to run trigger)
            {"id": "run-1", "type": "trigger-run"},
            {"id": "b-mid", "type": "agent"},
            {"id": "b-end", "type": "automation-telegram"},
        ]
        edges = [
            {"source": "a-start", "target": "a-end"},
            {"source": "run-1", "target": "b-mid"},
            {"source": "b-mid", "target": "b-end"},
        ]

        reachable_nodes, reachable_edges = handler._get_reachable_nodes(
            "run-1", nodes, edges        )

        reachable_ids = {n['id'] for n in reachable_nodes}
        assert reachable_ids == {"run-1", "b-mid", "b-end"}
        # Subworkflow A should NOT be included
        assert "a-start" not in reachable_ids
        assert "a-end" not in reachable_ids

    def test_run_trigger_standalone(self, handler):
        """A run trigger with no downstream nodes should still be reachable."""
        nodes = [
            {"id": "run-1", "type": "trigger-run"},
        ]
        edges = []

        reachable_nodes, reachable_edges = handler._get_reachable_nodes(
            "run-1", nodes, edges        )

        reachable_ids = {n['id'] for n in reachable_nodes}
        assert reachable_ids == {"run-1"}


class TestRunTriggerIsTriggerType:
    """Test that trigger-run is correctly identified as a trigger type in execution logic."""

    def test_starts_with_trigger_prefix(self):
        """The node type 'trigger-run' should match the 'trigger-' prefix check."""
        node_type = 'trigger-run'
        assert node_type.startswith('trigger-')

    def test_not_in_non_executable_types(self):
        """trigger-run should NOT be in NON_EXECUTABLE_NODE_TYPES."""
        from wss.handlers.workflow_execution_handler import NON_EXECUTABLE_NODE_TYPES
        assert 'trigger-run' not in NON_EXECUTABLE_NODE_TYPES
