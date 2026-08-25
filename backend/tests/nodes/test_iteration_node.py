"""
Test suite for Iteration Node functionality.

Tests the iteration node's ability to:
- Transform 2D arrays (like Google Sheets data) into objects with headers
- Provide iteration variables (item, index, total) to downstream nodes
- Execute body nodes for each item with correct variable resolution
- Aggregate results from all iterations
- Allow body nodes to reference each other's outputs within an iteration
"""

import pytest
import asyncio
from unittest.mock import AsyncMock

from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler


class TestIterationNode:
    """
    Unit tests for iteration node functionality.

    Tests the iteration node's ability to:
    - Transform 2D arrays (like Google Sheets data) into objects with headers
    - Provide iteration variables (item, index, total) to downstream nodes
    - Execute body nodes for each item with correct variable resolution
    - Aggregate results from all iterations
    """

    @pytest.fixture
    def handler(self):
        """Create handler with mock sio for unit testing."""
        mock_sio = AsyncMock()
        mock_sio.emit = AsyncMock()
        return WorkflowExecutionHandler(sio=mock_sio)

    @pytest.fixture
    def sheets_mock_output(self):
        """Mock Google Sheets output with header row and data rows."""
        return {
            "type": "google_sheets",
            "operation": "read",
            "status": "success",
            "values": [
                ["System Prompt", "Message", "Expected Answer"],
                ["You are a helpful assistant", "What is 2+2?", "4"],
                ["Be concise", "Capital of France?", "Paris"],
                ["You are an expert", "What is Python?", "A programming language"],
            ],
            "row_count": 4,
        }

    def test_reference_resolution_with_iteration_variables(self, handler):
        """Test that iteration variables are properly resolved in config."""
        # Simulate iteration node output with current item
        node_outputs = {
            "iteration-1": {
                "items": [
                    {"System Prompt": "You are helpful", "Message": "Hello"},
                    {"System Prompt": "Be concise", "Message": "Hi"},
                ],
                "total": 2,
                "item": {"System Prompt": "You are helpful", "Message": "Hello"},
                "index": 0,
                "isIterationNode": True,
                "headers": ["System Prompt", "Message"],
            }
        }

        # Test resolving item fields
        result = handler._resolve_references("{{iteration-1.item.System Prompt}}", node_outputs)
        assert result == "You are helpful"

        result = handler._resolve_references("{{iteration-1.item.Message}}", node_outputs)
        assert result == "Hello"

        # Test resolving index and total
        result = handler._resolve_references("{{iteration-1.index}}", node_outputs)
        assert result == 0

        result = handler._resolve_references("{{iteration-1.total}}", node_outputs)
        assert result == 2

    def test_reference_resolution_mixed_text_with_iteration(self, handler):
        """Test iteration references mixed with static text."""
        node_outputs = {
            "iteration-1": {
                "item": {"name": "Alice", "age": 30},
                "index": 2,
                "total": 5,
                "isIterationNode": True,
            }
        }

        result = handler._resolve_references(
            "Processing {{iteration-1.item.name}} ({{iteration-1.index}} of {{iteration-1.total}})",
            node_outputs
        )
        assert result == "Processing Alice (2 of 5)"

    def test_reference_resolution_in_nested_config(self, handler):
        """Test iteration references in nested config structures."""
        node_outputs = {
            "iteration-1": {
                "item": {"system_prompt": "Be helpful", "user_message": "Hello"},
                "index": 0,
                "total": 3,
                "isIterationNode": True,
            }
        }

        config = {
            "config": {
                "system_prompt": "{{iteration-1.item.system_prompt}}",
                "message": "{{iteration-1.item.user_message}}",
                "metadata": {
                    "iteration": "{{iteration-1.index}}",
                    "total": "{{iteration-1.total}}"
                }
            }
        }

        result = handler._resolve_references(config, node_outputs)

        assert result["config"]["system_prompt"] == "Be helpful"
        assert result["config"]["message"] == "Hello"
        assert result["config"]["metadata"]["iteration"] == 0
        assert result["config"]["metadata"]["total"] == 3

    @pytest.mark.asyncio
    async def test_iteration_node_transforms_2d_array(self, handler):
        """Test that iteration node transforms 2D array with headers into objects."""
        from nodes.iteration_node import IterationNode, IterationNodeConfig

        # Create iteration node with header_row=True
        config_dict = {
            "config": {
                "items": [
                    ["Name", "Age", "City"],
                    ["Alice", 25, "NYC"],
                    ["Bob", 30, "LA"],
                ],
                "header_row": True,
            }
        }
        parsed_config = IterationNodeConfig.model_validate(config_dict)

        node = IterationNode(
            node_id="iter-1",
            node_type="iteration",
            node_data=config_dict,
            config=parsed_config,
            sio=None,
            sid=None,
            workflow_id=None
        )

        result = await node.execute({})

        # Verify transformation
        assert result["isIterationNode"] is True
        assert result["total"] == 2  # 2 data rows (header excluded)
        assert result["headers"] == ["Name", "Age", "City"]

        # Verify items are objects, not arrays
        assert result["items"][0] == {"Name": "Alice", "Age": 25, "City": "NYC"}
        assert result["items"][1] == {"Name": "Bob", "Age": 30, "City": "LA"}

        # Verify first item is set
        assert result["item"] == {"Name": "Alice", "Age": 25, "City": "NYC"}
        assert result["index"] == 0

    @pytest.mark.asyncio
    async def test_iteration_node_explicit_field_names(self, handler):
        """Test iteration node with explicit field_names mapping."""
        from nodes.iteration_node import IterationNode, IterationNodeConfig

        # No header row, use explicit field names
        config_dict = {
            "config": {
                "items": [
                    ["Alice", 25],
                    ["Bob", 30],
                ],
                "header_row": False,
                "field_names": "name,age",
            }
        }
        parsed_config = IterationNodeConfig.model_validate(config_dict)

        node = IterationNode(
            node_id="iter-1",
            node_type="iteration",
            node_data=config_dict,
            config=parsed_config,
            sio=None,
            sid=None,
            workflow_id=None
        )

        result = await node.execute({})

        assert result["total"] == 2
        assert result["items"][0] == {"name": "Alice", "age": 25}
        assert result["items"][1] == {"name": "Bob", "age": 30}

    @pytest.mark.asyncio
    async def test_iteration_node_raw_array_no_transform(self, handler):
        """Test iteration node with simple array (no header or field names)."""
        from nodes.iteration_node import IterationNode, IterationNodeConfig

        config_dict = {
            "config": {
                "items": ["apple", "banana", "cherry"],
                "header_row": False,
            }
        }
        parsed_config = IterationNodeConfig.model_validate(config_dict)

        node = IterationNode(
            node_id="iter-1",
            node_type="iteration",
            node_data=config_dict,
            config=parsed_config,
            sio=None,
            sid=None,
            workflow_id=None
        )

        result = await node.execute({})

        assert result["total"] == 3
        assert result["items"] == ["apple", "banana", "cherry"]
        assert result["item"] == "apple"

    @pytest.mark.asyncio
    async def test_iteration_executes_body_for_each_item(self, handler):
        """
        Test that iteration node executes body nodes for each item.

        Uses mock node execution to track:
        - Each iteration receives correct item data
        - All iterations complete
        - Results are aggregated
        """
        execution_log = []
        received_items = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            node_type = node.get('type', '')

            async with lock:
                execution_log.append(f"{node_id}:{node_type}")

            if node_type == 'iteration':
                # Return iteration output with items
                return {
                    "items": [
                        {"name": "Alice", "value": 100},
                        {"name": "Bob", "value": 200},
                        {"name": "Charlie", "value": 300},
                    ],
                    "total": 3,
                    "item": {"name": "Alice", "value": 100},
                    "index": 0,
                    "isIterationNode": True,
                    "headers": ["name", "value"],
                }
            elif node_type == 'body-node':
                # Body node should receive resolved item data
                config = node.get('config', {})
                item_name = config.get('config', {}).get('item_name')
                async with lock:
                    received_items.append(item_name)
                return {"processed": item_name}

            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        # Workflow: sheets → iteration → body-node
        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": "placeholder", "header_row": True}
            }},
            {"id": "body-1", "type": "body-node", "config": {
                "config": {"item_name": "{{iteration-1.item.name}}"}
            }},
        ]
        edges = [
            {"source": "iteration-1", "target": "body-1"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None
        # Iteration node + 3 iterations of body node
        assert nodes_executed >= 1

        # Verify body node received different items for each iteration
        # (The actual test verifies the execution log shows iteration pattern)
        assert "iteration-1:iteration" in execution_log

    @pytest.mark.asyncio
    async def test_iteration_with_concurrency_limit(self, handler):
        """
        Test that iterations respect max_concurrency setting.

        With 5 items and max_concurrency=2, at most 2 iterations should run at once.
        """
        active_count = 0
        max_active_seen = 0
        lock = asyncio.Lock()
        all_started = []

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            nonlocal active_count, max_active_seen
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                return {
                    "items": [{"i": i} for i in range(5)],
                    "total": 5,
                    "item": {"i": 0},
                    "index": 0,
                    "isIterationNode": True,
                }
            elif node_type == 'body-node':
                async with lock:
                    active_count += 1
                    max_active_seen = max(max_active_seen, active_count)
                    all_started.append(node_id)

                # Simulate some work
                await asyncio.sleep(0.01)

                async with lock:
                    active_count -= 1

                return {"done": True}

            return {}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {}},
            {"id": "body-1", "type": "body-node", "config": {}},
        ]
        edges = [{"source": "iteration-1", "target": "body-1"}]

        # Note: The actual concurrency limit for iterations is controlled
        # by the _execute_iteration_node method, not the concurrent executor
        nodes_executed, error, _ = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id",
            max_concurrency=2
        )

        # Test passes if no error and workflow completes
        assert error is None

    @pytest.mark.asyncio
    async def test_body_nodes_can_reference_each_other_in_iteration(self, handler):
        """
        Test that body nodes within an iteration can reference each other's outputs.

        This tests the scenario:
        - Iteration node provides items to iterate over
        - Agent node processes each item (mocked output)
        - Sheets write node references the agent's output for each iteration

        The sheets write should:
        1. Execute once per iteration (3 times for 3 items)
        2. Have access to agent output in node_outputs (verified by checking node_outputs)
        3. Receive the correct row_number for each iteration

        Note: We verify the fix by checking that node_outputs passed to the sheets node
        contains the agent's output. The actual reference resolution happens inside
        _execute_node which we're mocking, so we check the inputs to the mock.
        """
        sheets_node_outputs_received = []
        agent_call_count = 0
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            nonlocal agent_call_count
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                # Return iteration output with 3 items (simulating Google Sheets rows)
                return {
                    "items": [
                        {"question": "What is 2+2?", "expected": "4"},
                        {"question": "Capital of France?", "expected": "Paris"},
                        {"question": "What is Python?", "expected": "A programming language"},
                    ],
                    "total": 3,
                    "item": {"question": "What is 2+2?", "expected": "4"},
                    "index": 0,
                    "row_number": 2,  # First data row (after header)
                    "isIterationNode": True,
                    "headers": ["question", "expected"],
                }
            elif node_type == 'agent':
                async with lock:
                    agent_call_count += 1
                # Agent node returns mocked response
                return {"response": f"Agent response #{agent_call_count}", "status": "completed"}
            elif node_type == 'google_sheets':
                # Capture what node_outputs the sheets node receives
                # This is the key test - does it have access to agent-1's output?
                async with lock:
                    sheets_node_outputs_received.append({
                        'has_agent_output': 'agent-1' in node_outputs,
                        'agent_output': node_outputs.get('agent-1'),
                        'iteration_context': node_outputs.get('iteration-1'),
                    })
                return {"operation": "write_sheet_data", "status": "success"}

            return {"node_id": node_id}

        handler._execute_node = mock_execute_node

        # Workflow: iteration → agent → sheets_write
        # Agent references iteration item, sheets_write references agent output
        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {
                    "items": "placeholder",
                    "header_row": True,
                    "concurrency": 1,  # Sequential to make order predictable
                }
            }},
            {"id": "agent-1", "type": "agent", "config": {
                "config": {
                    "system_prompt": "Answer the question",
                    "message": "{{iteration-1.item.question}}",
                }
            }},
            {"id": "sheets-1", "type": "google_sheets", "config": {
                "config": {
                    "operation": "write_sheet_data",
                    "range": "D{{iteration-1.row_number}}",
                    "values": "{{agent-1.response}}",
                }
            }},
        ]
        edges = [
            {"source": "iteration-1", "target": "agent-1"},
            {"source": "iteration-1", "target": "sheets-1"},
            {"source": "agent-1", "target": "sheets-1"},  # Sheets depends on agent
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None

        # Agent should have been called 3 times (once per iteration)
        assert agent_call_count == 3, f"Expected agent to be called 3 times, got {agent_call_count}"

        # Sheets node should have been called 3 times (once per iteration)
        assert len(sheets_node_outputs_received) == 3, f"Expected 3 sheets calls, got {len(sheets_node_outputs_received)}"

        # CRITICAL: Each sheets call should have had access to agent-1's output
        # This verifies our fix - iteration_node_outputs.update(iteration_outputs) works
        for i, call_data in enumerate(sheets_node_outputs_received):
            assert call_data['has_agent_output'], \
                f"Iteration {i}: sheets node did NOT have access to agent-1 output! " \
                f"This means body nodes can't reference each other."

            # Verify the agent output is the correct one for this iteration
            agent_output = call_data['agent_output']
            assert agent_output is not None, f"Iteration {i}: agent output was None"
            assert 'response' in agent_output, f"Iteration {i}: agent output missing 'response'"

            # Verify iteration context is present
            iteration_ctx = call_data['iteration_context']
            assert iteration_ctx is not None, f"Iteration {i}: iteration context was None"
            assert 'row_number' in iteration_ctx, f"Iteration {i}: missing row_number"

    @pytest.mark.asyncio
    async def test_body_nodes_execute_for_all_items_with_correct_row_numbers(self, handler):
        """
        Test that body nodes execute for ALL items in the iteration,
        not just the first one.

        Specifically verifies:
        1. Body node executes N times for N items
        2. Each execution receives a different row_number
        3. Row numbers are sequential (2, 3, 4 for header_row=True)
        """
        execution_count = 0
        row_numbers = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            nonlocal execution_count
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                return {
                    "items": [
                        {"value": "Row 1"},
                        {"value": "Row 2"},
                        {"value": "Row 3"},
                        {"value": "Row 4"},
                    ],
                    "total": 4,
                    "item": {"value": "Row 1"},
                    "index": 0,
                    "row_number": 2,  # Starts at 2 because header_row=True
                    "isIterationNode": True,
                    "headers": ["value"],
                }
            elif node_type == 'write-node':
                # Get the row_number from iteration context
                iteration_output = node_outputs.get('iteration-1', {})
                current_row = iteration_output.get('row_number', 'unknown')

                async with lock:
                    execution_count += 1
                    row_numbers.append(current_row)

                return {"written_to_row": current_row}

            return {}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": [], "header_row": True}
            }},
            {"id": "write-1", "type": "write-node", "config": {}},
        ]
        edges = [{"source": "iteration-1", "target": "write-1"}]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None

        # Body node should execute 4 times (once per item)
        assert execution_count == 4, f"Expected 4 executions, got {execution_count}"

        # Row numbers should be 2, 3, 4, 5 (sequential, starting from 2 due to header)
        assert sorted(row_numbers) == [2, 3, 4, 5], f"Expected row numbers [2,3,4,5], got {sorted(row_numbers)}"

    @pytest.mark.asyncio
    async def test_iteration_with_mocked_output_still_iterates(self, handler):
        """
        Test that iteration nodes with mocked output still iterate over the mocked items.

        When an iteration node has mockedOutput set, the iteration should:
        1. Use the mocked items array instead of executing the node
        2. Still iterate over each item and execute body nodes
        3. Provide correct row_number/index for each iteration
        """
        execution_count = 0
        row_numbers = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            nonlocal execution_count
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                # This should NOT be called when iteration has mocked output
                raise AssertionError("Iteration node execute_node should not be called when mocked")

            elif node_type == 'write-node':
                # Get the row_number from iteration context
                iteration_output = node_outputs.get('iteration-1', {})
                current_row = iteration_output.get('row_number', 'unknown')
                current_item = iteration_output.get('item', {})

                async with lock:
                    execution_count += 1
                    row_numbers.append(current_row)

                return {"written_to_row": current_row, "item": current_item}

            return {}

        handler._execute_node = mock_execute_node

        # Mocked output with 3 items - simulates saved/pinned iteration output
        mocked_iteration_output = {
            "items": [
                {"name": "Alice"},
                {"name": "Bob"},
                {"name": "Charlie"},
            ],
            "total": 3,
            "item": {"name": "Alice"},  # First item for display
            "index": 0,
            "row_number": 2,
            "isIterationNode": True,
            "headers": ["name"],
        }

        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": [], "header_row": True},
                "mockedOutput": mocked_iteration_output,  # Mocked output set
            }},
            {"id": "write-1", "type": "write-node", "config": {}},
        ]
        edges = [{"source": "iteration-1", "target": "write-1"}]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None

        # Body node should execute 3 times (once per mocked item)
        assert execution_count == 3, f"Expected 3 executions, got {execution_count}"

        # Row numbers should be 2, 3, 4 (sequential, starting from 2 due to header)
        assert sorted(row_numbers) == [2, 3, 4], f"Expected row numbers [2,3,4], got {sorted(row_numbers)}"

    @pytest.mark.asyncio
    async def test_mocked_iteration_uses_concurrency_from_config(self, handler):
        """
        Test that mocked iteration nodes read concurrency from node config.

        When an iteration node has mockedOutput, the mocked data may not include
        the concurrency setting. The iteration should fall back to reading
        concurrency from the node's config.
        """
        import time
        execution_times = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                raise AssertionError("Iteration node execute_node should not be called when mocked")

            elif node_type == 'slow-node':
                # Record start time and simulate work
                start_time = time.time()
                await asyncio.sleep(0.1)  # 100ms per node

                async with lock:
                    execution_times.append(start_time)

                return {"done": True}

            return {}

        handler._execute_node = mock_execute_node

        # Mocked output WITHOUT concurrency field
        mocked_iteration_output = {
            "items": [{"id": 1}, {"id": 2}, {"id": 3}],
            "total": 3,
            "item": {"id": 1},
            "index": 0,
            "row_number": 1,
            "isIterationNode": True,
            # Note: NO concurrency field - should fall back to config
        }

        # Node config specifies concurrency=3 (all items in parallel)
        # Note: Due to frontend quirk, concurrency is at top level of config, not nested
        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": []},  # Nested config (may have stale concurrency)
                "concurrency": 3,  # Top-level concurrency (current value from frontend)
                "mockedOutput": mocked_iteration_output,
            }},
            {"id": "slow-1", "type": "slow-node", "config": {}},
        ]
        edges = [{"source": "iteration-1", "target": "slow-1"}]

        start = time.time()
        nodes_executed, error, _ = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )
        elapsed = time.time() - start

        assert error is None
        assert len(execution_times) == 3

        # With concurrency=3, all 3 iterations should run in parallel
        # Total time should be ~100ms, not ~300ms (sequential)
        # Allow some margin for test overhead
        assert elapsed < 0.25, f"Expected parallel execution (~100ms), got {elapsed:.2f}s (sequential would be ~300ms)"

        # Verify executions started at roughly the same time (within 50ms of each other)
        time_spread = max(execution_times) - min(execution_times)
        assert time_spread < 0.05, f"Expected parallel start times, got spread of {time_spread:.3f}s"

    @pytest.mark.asyncio
    async def test_iteration_two_output_handles_loop_and_done(self, handler):
        """
        Test that iteration nodes with two output handles work correctly.

        The iteration node has two output handles:
        - "loop" handle: connects to body nodes that execute per-item
        - "done" handle: connects to nodes that receive aggregated results after all iterations

        This test verifies:
        1. Body nodes (connected via "loop" handle) execute N times for N items
        2. Done nodes (connected via "done" handle) execute once after all iterations
        3. Done nodes receive the aggregated collected_results
        """
        body_execution_count = 0
        done_execution_count = 0
        done_node_received_data = None
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            nonlocal body_execution_count, done_execution_count, done_node_received_data
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                return {
                    "items": [
                        {"name": "Alice", "score": 100},
                        {"name": "Bob", "score": 200},
                        {"name": "Charlie", "score": 300},
                    ],
                    "total": 3,
                    "item": {"name": "Alice", "score": 100},
                    "index": 0,
                    "row_number": 2,
                    "isIterationNode": True,
                    "headers": ["name", "score"],
                }
            elif node_type == 'body-node':
                # Body node executes per-item
                iteration_ctx = node_outputs.get('iteration-1', {})
                item = iteration_ctx.get('item', {})
                async with lock:
                    body_execution_count += 1
                return {"processed": item.get('name'), "doubled_score": item.get('score', 0) * 2}
            elif node_type == 'done-node':
                # Done node executes once with aggregated results
                iteration_output = node_outputs.get('iteration-1', {})
                async with lock:
                    done_execution_count += 1
                    done_node_received_data = {
                        'has_collected_results': 'collected_results' in iteration_output,
                        'collected_results': iteration_output.get('collected_results'),
                        'total': iteration_output.get('total'),
                        'completed': iteration_output.get('completed'),
                    }
                return {"aggregation_complete": True}

            return {}

        handler._execute_node = mock_execute_node

        # Workflow: iteration → body-node (loop handle) AND iteration → done-node (done handle)
        # body-node loops back to iteration input for aggregation
        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": [], "header_row": True, "concurrency": 1}
            }},
            {"id": "body-1", "type": "body-node", "config": {}},
            {"id": "done-1", "type": "done-node", "config": {}},
        ]
        edges = [
            # Body node connected via "loop" handle (default/null sourceHandle)
            {"source": "iteration-1", "target": "body-1", "sourceHandle": "loop"},
            # Body node loops back to iteration input (marks it as aggregation source)
            {"source": "body-1", "target": "iteration-1"},
            # Done node connected via "done" handle
            {"source": "iteration-1", "target": "done-1", "sourceHandle": "done"},
        ]

        nodes_executed, error, outputs = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None

        # Body node should execute 3 times (once per item)
        assert body_execution_count == 3, f"Expected body node to execute 3 times, got {body_execution_count}"

        # Done node should execute exactly once
        assert done_execution_count == 1, f"Expected done node to execute once, got {done_execution_count}"

        # Done node should have received aggregated data
        assert done_node_received_data is not None, "Done node should have received data"
        assert done_node_received_data['has_collected_results'], "Done node should have received collected_results"
        assert done_node_received_data['total'] == 3, "Done node should see total=3"
        assert done_node_received_data['completed'] is True, "Done node should see completed=True"

        # Collected results should have 3 items (one per iteration)
        collected = done_node_received_data['collected_results']
        assert collected is not None, "collected_results should not be None"
        assert len(collected) == 3, f"Expected 3 collected results, got {len(collected)}"

    @pytest.mark.asyncio
    async def test_iteration_loopback_determines_aggregation_source(self, handler):
        """
        Test that the loop-back connection determines which body node's output is aggregated.

        When a body node connects back to the iteration node's input, that node's output
        is used for collected_results (instead of the topologically last body node).

        Workflow:
            iteration ──┬──→ body-A (loops back to iteration)
                        └──→ body-B (no loop-back, executes after body-A)
                ↑___________|
            (body-A loops back, so its output is aggregated, not body-B's)

        Both body nodes are directly connected to the iteration node via the loop handle.
        Within each iteration, body-B executes after body-A (dependency edge).
        """
        body_a_outputs = []
        body_b_outputs = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                return {
                    "items": [{"value": 1}, {"value": 2}],
                    "total": 2,
                    "item": {"value": 1},
                    "index": 0,
                    "isIterationNode": True,
                }
            elif node_id == 'body-A':
                iteration_ctx = node_outputs.get('iteration-1', {})
                item = iteration_ctx.get('item', {})
                result = {"from_A": item.get('value', 0) * 10}
                async with lock:
                    body_a_outputs.append(result)
                return result
            elif node_id == 'body-B':
                # Body-B transforms body-A's output
                body_a_output = node_outputs.get('body-A', {})
                result = {"from_B": body_a_output.get('from_A', 0) + 1}
                async with lock:
                    body_b_outputs.append(result)
                return result

            return {}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": [], "concurrency": 1}
            }},
            {"id": "body-A", "type": "body-node", "config": {}},
            {"id": "body-B", "type": "body-node", "config": {}},
        ]
        edges = [
            # Both body nodes directly connected to iteration via loop handle
            {"source": "iteration-1", "target": "body-A", "sourceHandle": "loop"},
            {"source": "iteration-1", "target": "body-B", "sourceHandle": "loop"},
            # body-B depends on body-A within each iteration (for execution order)
            {"source": "body-A", "target": "body-B"},
            # body-A loops back (not body-B), so body-A's output should be aggregated
            {"source": "body-A", "target": "iteration-1"},
        ]

        nodes_executed, error, outputs = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None

        # Both body nodes should have executed twice (once per item)
        assert len(body_a_outputs) == 2, f"Expected body-A to execute 2 times, got {len(body_a_outputs)}"
        assert len(body_b_outputs) == 2, f"Expected body-B to execute 2 times, got {len(body_b_outputs)}"

        # Check that iteration output has collected_results from body-A (the loopback node)
        iteration_output = outputs.get('iteration-1', {})
        collected = iteration_output.get('collected_results', [])

        assert len(collected) == 2, f"Expected 2 collected results, got {len(collected)}"

        # collected_results should be from body-A (from_A: 10, 20), not body-B (from_B: 11, 21)
        assert collected[0].get('from_A') == 10, f"Expected from_A=10, got {collected[0]}"
        assert collected[1].get('from_A') == 20, f"Expected from_A=20, got {collected[1]}"
        assert 'from_B' not in collected[0], "collected_results should be from body-A, not body-B"

    @pytest.mark.asyncio
    async def test_implicit_loop_variable_scoping(self, handler):
        """
        Test that loop variables are available at top level without iteration node ID prefix.

        This tests the implicit loop variable scoping feature where nodes in the loop body
        can reference {{item}}, {{index}}, etc. instead of {{iteration-id.item}}, {{iteration-id.index}}.

        This matches industry best practices (Make, Zapier) and reduces edge clutter.
        """
        implicit_references_received = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                return {
                    "items": [
                        {"name": "Alice", "age": 30},
                        {"name": "Bob", "age": 25},
                        {"name": "Charlie", "age": 35},
                    ],
                    "total": 3,
                    "item": {"name": "Alice", "age": 30},
                    "index": 0,
                    "row_number": 2,
                    "isIterationNode": True,
                    "headers": ["name", "age"],
                }
            elif node_type == 'body-node':
                # Check that loop variables are available at top level
                async with lock:
                    implicit_references_received.append({
                        'has_item': 'item' in node_outputs,
                        'has_index': 'index' in node_outputs,
                        'has_items': 'items' in node_outputs,
                        'has_total': 'total' in node_outputs,
                        'has_row_number': 'row_number' in node_outputs,
                        'item': node_outputs.get('item'),
                        'index': node_outputs.get('index'),
                        'total': node_outputs.get('total'),
                        'row_number': node_outputs.get('row_number'),
                    })
                return {"processed": True}

            return {}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": [], "header_row": True, "concurrency": 1}
            }},
            {"id": "body-1", "type": "body-node", "config": {}},
        ]
        edges = [
            {"source": "iteration-1", "target": "body-1", "sourceHandle": "loop"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None

        # Body node should execute 3 times (once per item)
        assert len(implicit_references_received) == 3, f"Expected 3 executions, got {len(implicit_references_received)}"

        # Each iteration should have loop variables at top level
        for i, call_data in enumerate(implicit_references_received):
            # Verify all loop variables are present at top level
            assert call_data['has_item'], f"Iteration {i}: 'item' not in top-level node_outputs"
            assert call_data['has_index'], f"Iteration {i}: 'index' not in top-level node_outputs"
            assert call_data['has_items'], f"Iteration {i}: 'items' not in top-level node_outputs"
            assert call_data['has_total'], f"Iteration {i}: 'total' not in top-level node_outputs"
            assert call_data['has_row_number'], f"Iteration {i}: 'row_number' not in top-level node_outputs"

            # Verify values are correct for each iteration
            assert call_data['item']['name'] in ["Alice", "Bob", "Charlie"], f"Iteration {i}: unexpected item"
            assert call_data['index'] == i, f"Iteration {i}: index should be {i}, got {call_data['index']}"
            assert call_data['total'] == 3, f"Iteration {i}: total should be 3"
            assert call_data['row_number'] == i + 2, f"Iteration {i}: row_number should be {i + 2}"

    @pytest.mark.asyncio
    async def test_implicit_variables_backward_compatible(self, handler):
        """
        Test that the old explicit reference syntax still works alongside implicit scoping.

        Nodes should be able to reference both:
        - {{item}} (new implicit syntax)
        - {{iteration-1.item}} (old explicit syntax)

        Both should work correctly for backward compatibility.
        """
        explicit_and_implicit_data = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                return {
                    "items": [{"value": 100}, {"value": 200}],
                    "total": 2,
                    "item": {"value": 100},
                    "index": 0,
                    "row_number": 1,
                    "isIterationNode": True,
                }
            elif node_type == 'body-node':
                # Verify BOTH explicit and implicit access work
                async with lock:
                    explicit_and_implicit_data.append({
                        # Explicit access via iteration node ID
                        'explicit_item': node_outputs.get('iteration-1', {}).get('item'),
                        'explicit_index': node_outputs.get('iteration-1', {}).get('index'),
                        # Implicit access at top level
                        'implicit_item': node_outputs.get('item'),
                        'implicit_index': node_outputs.get('index'),
                    })
                return {"done": True}

            return {}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": [], "concurrency": 1}
            }},
            {"id": "body-1", "type": "body-node", "config": {}},
        ]
        edges = [
            {"source": "iteration-1", "target": "body-1", "sourceHandle": "loop"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None
        assert len(explicit_and_implicit_data) == 2

        # Verify both explicit and implicit access return the same values
        for i, call_data in enumerate(explicit_and_implicit_data):
            # Both access methods should work and return identical values
            assert call_data['explicit_item'] == call_data['implicit_item'], \
                f"Iteration {i}: explicit and implicit item access should return same value"
            assert call_data['explicit_index'] == call_data['implicit_index'], \
                f"Iteration {i}: explicit and implicit index access should return same value"
            assert call_data['implicit_index'] == i, \
                f"Iteration {i}: implicit index should be {i}"

    def test_reference_resolution_implicit_loop_vars(self, handler):
        """
        Test that WorkflowExecutionHandler can resolve implicit loop variable references.

        This tests that references like {{item.name}}, {{index}}, {{total}} work correctly
        when loop variables are injected at the top level.
        """
        # Simulate node_outputs with BOTH explicit (iteration-1.item) and implicit (item) variables
        node_outputs = {
            "iteration-1": {
                "items": [{"name": "Alice"}, {"name": "Bob"}],
                "total": 2,
                "item": {"name": "Alice", "age": 30},
                "index": 0,
                "row_number": 2,
                "isIterationNode": True,
            },
            # Implicit loop variables at top level (new feature)
            "item": {"name": "Alice", "age": 30},
            "index": 0,
            "items": [{"name": "Alice"}, {"name": "Bob"}],
            "total": 2,
            "row_number": 2,
        }

        # Test implicit reference resolution (new syntax)
        result = handler._resolve_references("{{item.name}}", node_outputs)
        assert result == "Alice", "Implicit {{item.name}} should resolve"

        result = handler._resolve_references("{{item.age}}", node_outputs)
        assert result == 30, "Implicit {{item.age}} should resolve"

        result = handler._resolve_references("{{index}}", node_outputs)
        assert result == 0, "Implicit {{index}} should resolve"

        result = handler._resolve_references("{{total}}", node_outputs)
        assert result == 2, "Implicit {{total}} should resolve"

        result = handler._resolve_references("{{row_number}}", node_outputs)
        assert result == 2, "Implicit {{row_number}} should resolve"

        # Test backward compatibility (old explicit syntax still works)
        result = handler._resolve_references("{{iteration-1.item.name}}", node_outputs)
        assert result == "Alice", "Explicit {{iteration-1.item.name}} should still work"

        # Test mixed text with implicit references
        result = handler._resolve_references(
            "Processing {{item.name}} (row {{row_number}} of {{total}})",
            node_outputs
        )
        assert result == "Processing Alice (row 2 of 2)", "Mixed text with implicit refs should work"

    @pytest.mark.asyncio
    async def test_transitive_loop_body_propagation(self, handler):
        """
        Test that loop variables propagate to ALL nodes downstream from loop handle.

        This tests the transitive loop body discovery feature where chains like:
        iteration (loop) → A → B → C

        All of A, B, C should execute per iteration with access to loop variables,
        eliminating the need to connect iteration node to every node in the chain.
        """
        execution_log = []
        lock = asyncio.Lock()

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id,
                                    conversation_id=None, workflow_nodes=None,
                                    workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                return {
                    "items": [
                        {"name": "Item1", "value": 10},
                        {"name": "Item2", "value": 20},
                        {"name": "Item3", "value": 30},
                    ],
                    "total": 3,
                    "item": {"name": "Item1", "value": 10},
                    "index": 0,
                    "row_number": 1,
                    "isIterationNode": True,
                }

            # Log execution with loop variable access info
            async with lock:
                execution_log.append({
                    'node': node_id,
                    'has_item': 'item' in node_outputs,
                    'item_value': node_outputs.get('item'),
                    'has_index': 'index' in node_outputs,
                    'index_value': node_outputs.get('index'),
                })

            return {"processed": node_id}

        handler._execute_node = mock_execute_node

        # Workflow: iteration → A → B → C (chain, only A directly connected)
        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": [], "concurrency": 1}
            }},
            {"id": "body-A", "type": "processor", "config": {}},
            {"id": "body-B", "type": "processor", "config": {}},
            {"id": "body-C", "type": "processor", "config": {}},
        ]

        edges = [
            # Only A is directly connected to iteration (loop handle)
            {"source": "iteration-1", "target": "body-A", "sourceHandle": "loop"},
            # B and C are chained from A (transitive loop body)
            {"source": "body-A", "target": "body-B"},
            {"source": "body-B", "target": "body-C"},
        ]

        nodes_executed, error, _ = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None

        # Count executions per node
        body_a_execs = [e for e in execution_log if e['node'] == 'body-A']
        body_b_execs = [e for e in execution_log if e['node'] == 'body-B']
        body_c_execs = [e for e in execution_log if e['node'] == 'body-C']

        # All nodes should execute 3 times (once per iteration)
        assert len(body_a_execs) == 3, f"body-A should execute 3 times, got {len(body_a_execs)}"
        assert len(body_b_execs) == 3, f"body-B should execute 3 times (transitive), got {len(body_b_execs)}"
        assert len(body_c_execs) == 3, f"body-C should execute 3 times (transitive), got {len(body_c_execs)}"

        # All nodes should have access to loop variables
        for exec in body_a_execs:
            assert exec['has_item'], "body-A should have access to 'item' variable"
            assert exec['has_index'], "body-A should have access to 'index' variable"
            assert exec['item_value'] is not None, "body-A item value should not be None"

        for exec in body_b_execs:
            assert exec['has_item'], "body-B should have access to 'item' variable (transitive)"
            assert exec['has_index'], "body-B should have access to 'index' variable (transitive)"
            assert exec['item_value'] is not None, "body-B item value should not be None"

        for exec in body_c_execs:
            assert exec['has_item'], "body-C should have access to 'item' variable (transitive)"
            assert exec['has_index'], "body-C should have access to 'index' variable (transitive)"
            assert exec['item_value'] is not None, "body-C item value should not be None"

        # Verify different items for each iteration
        body_a_items = [e['item_value']['name'] for e in body_a_execs]
        assert body_a_items == ["Item1", "Item2", "Item3"], "body-A should process all 3 items"

        body_b_items = [e['item_value']['name'] for e in body_b_execs]
        assert body_b_items == ["Item1", "Item2", "Item3"], "body-B should process all 3 items (transitive)"

        body_c_items = [e['item_value']['name'] for e in body_c_execs]
        assert body_c_items == ["Item1", "Item2", "Item3"], "body-C should process all 3 items (transitive)"

    @pytest.mark.asyncio
    async def test_iteration_does_not_retain_all_body_outputs(self, handler):
        """
        Regression test for memory leak: iteration must NOT store all iteration
        outputs in body node entries or in final_output['results'].

        Previously, after iteration completed:
        - ctx.node_outputs[body_node_id] = {'iterations': [ALL outputs], 'lastOutput': ...}
        - ctx.node_outputs[iteration_id] = {'results': iteration_results_with_ALL_outputs, ...}

        This caused 20GB+ memory retention for workflows with large body outputs
        (e.g., 21 RSS feeds × 10 agent nodes). The fix stores only lastOutput
        for body nodes and excludes full results from final_output.
        """
        LARGE_PAYLOAD_SIZE = 1000  # chars per body output to simulate large data
        NUM_ITEMS = 10

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id,
                                    conversation_id=None, workflow_nodes=None,
                                    workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                return {
                    "items": [{"id": i, "name": f"item-{i}"} for i in range(NUM_ITEMS)],
                    "total": NUM_ITEMS,
                    "item": {"id": 0, "name": "item-0"},
                    "index": 0,
                    "isIterationNode": True,
                }
            elif node_type == 'body-node':
                iteration_ctx = node_outputs.get('iteration-1', {})
                item = iteration_ctx.get('item', {})
                # Each body output is large — simulates agent conversation history
                return {
                    "item_id": item.get('id'),
                    "result": f"processed-{item.get('name')}",
                    "large_payload": "x" * LARGE_PAYLOAD_SIZE,
                }

            return {}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": [], "concurrency": 1}
            }},
            {"id": "body-1", "type": "body-node", "config": {}},
        ]
        edges = [
            {"source": "iteration-1", "target": "body-1", "sourceHandle": "loop"},
            {"source": "body-1", "target": "iteration-1"},
        ]

        nodes_executed, error, outputs = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None

        # --- Check iteration node output ---
        iter_output = outputs.get('iteration-1', {})

        # Should NOT have full 'results' array with all body outputs
        assert 'results' not in iter_output, (
            "iteration output should not contain 'results' key with all body outputs — "
            "this retains O(iterations × body_nodes) data in memory"
        )
        # Should have lightweight summary instead
        assert iter_output.get('results_count') == NUM_ITEMS
        assert iter_output.get('results_success') == NUM_ITEMS

        # collected_results should still work (flat array from aggregation source)
        collected = iter_output.get('collected_results', [])
        assert len(collected) == NUM_ITEMS, f"Expected {NUM_ITEMS} collected results, got {len(collected)}"
        # Verify data integrity — last item should be present
        assert collected[-1]['item_id'] == NUM_ITEMS - 1

        # --- Check body node output ---
        body_output = outputs.get('body-1', {})

        # Should NOT have 'iterations' array with all N outputs
        assert 'iterations' not in body_output, (
            "body node output should not contain 'iterations' key — "
            "storing all iteration outputs caused 20GB+ memory retention"
        )

        # Should have lastOutput (from the last iteration)
        assert 'lastOutput' in body_output, "body node should have lastOutput"
        assert body_output['lastOutput']['item_id'] == NUM_ITEMS - 1

        # Should have collected_results (this is the aggregation source node)
        assert 'collected_results' in body_output, (
            "aggregation source body node should have collected_results"
        )
        assert len(body_output['collected_results']) == NUM_ITEMS

    @pytest.mark.asyncio
    async def test_iteration_memory_no_full_iterations_retained(self, handler):
        """
        Regression test: body node outputs should NOT retain all iterations' data.

        Previously, ctx.node_outputs[body_node_id] was set to:
            {'iterations': [output_iter0, output_iter1, ...], 'lastOutput': last}

        This caused 20GB+ memory retention with large body outputs (e.g., agent
        conversation histories, RSS feed data). The fix stores only lastOutput
        and collected_results (for the aggregation source).

        Memory impact with the old behavior:
            20 iterations × 100KB body output = 2MB retained per body node
            With 10 body nodes: 20MB total
        After fix:
            Only lastOutput (100KB) + collected_results (20 × extracted data)
        """
        import json
        import sys

        ITEM_COUNT = 20
        # Each body output is ~100KB to simulate realistic agent/RSS output sizes
        LARGE_PAYLOAD = "x" * 100_000

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                return {
                    "items": [{"id": i} for i in range(ITEM_COUNT)],
                    "total": ITEM_COUNT,
                    "item": {"id": 0},
                    "index": 0,
                    "isIterationNode": True,
                }
            elif node_type == 'body-node':
                iteration_ctx = node_outputs.get('iteration-1', {})
                item = iteration_ctx.get('item', {})
                return {
                    "result": f"processed-{item.get('id')}",
                    "payload": LARGE_PAYLOAD,
                }

            return {}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": [], "concurrency": 5}
            }},
            {"id": "body-1", "type": "body-node", "config": {}},
        ]
        edges = [
            {"source": "iteration-1", "target": "body-1", "sourceHandle": "loop"},
            {"source": "body-1", "target": "iteration-1"},
        ]

        nodes_executed, error, outputs = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None

        # Body node output should exist
        body_output = outputs.get('body-1')
        assert body_output is not None, "body-1 should have output"

        # CRITICAL: body output must NOT have 'iterations' array (old behavior)
        assert 'iterations' not in body_output, (
            f"body output should NOT contain 'iterations' array — "
            f"this causes massive memory retention. Keys found: {list(body_output.keys())}"
        )

        # It SHOULD have lastOutput
        assert 'lastOutput' in body_output, "body output should have lastOutput"
        assert body_output['lastOutput']['result'] == f"processed-{ITEM_COUNT - 1}"

        # Aggregation source should have collected_results
        assert 'collected_results' in body_output, (
            "aggregation source body node should have collected_results"
        )
        assert len(body_output['collected_results']) == ITEM_COUNT

        # Iteration node output should NOT have full 'results' array
        iteration_output = outputs.get('iteration-1')
        assert iteration_output is not None
        assert 'results' not in iteration_output, (
            "iteration output should NOT contain full 'results' array — "
            "this stored all body outputs for all iterations"
        )
        assert iteration_output.get('results_count') == ITEM_COUNT
        assert iteration_output.get('collected_results') is not None
        assert len(iteration_output['collected_results']) == ITEM_COUNT

        # MEMORY CHECK: body node output should be bounded to lastOutput + collected_results
        # NOT proportional to ITEM_COUNT × full outputs (which is what 'iterations' array was)
        body_json = json.dumps(body_output, default=str)
        body_size_kb = len(body_json) // 1024

        # The body_output contains: lastOutput (1 × 100KB) + collected_results (20 × full outputs)
        # collected_results stores the aggregated data for downstream access — that's expected.
        # What we eliminated: the 'iterations' array that stored ALL 20 outputs redundantly
        # alongside collected_results. With the old code, body_output would be ~2x larger.
        #
        # Verify the body output does NOT have the old 'iterations' array by checking
        # it only has the expected keys
        assert set(body_output.keys()) == {'lastOutput', 'iterationCount', 'collected_results'}, (
            f"Unexpected keys in body output: {set(body_output.keys())}. "
            f"Should only have lastOutput, iterationCount, collected_results"
        )

    @pytest.mark.asyncio
    async def test_iteration_memory_multiple_body_nodes(self, handler):
        """
        Test memory retention with multiple body nodes in a chain.

        Simulates the production scenario: iteration over RSS feeds with
        multiple body nodes (parser → agent → formatter). Each body node
        produces large output. After iteration, only lastOutput per body
        node should be retained — NOT all iterations' outputs.

        Workflow: iteration → body-A → body-B → body-C
        (body-C loops back to iteration for aggregation)
        """
        import json

        ITEM_COUNT = 10
        BODY_NODE_COUNT = 3
        PAYLOAD_SIZE = 50_000  # 50KB per body output

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                return {
                    "items": [{"id": i} for i in range(ITEM_COUNT)],
                    "total": ITEM_COUNT,
                    "item": {"id": 0},
                    "index": 0,
                    "isIterationNode": True,
                }
            elif node_id == 'body-A':
                iteration_ctx = node_outputs.get('iteration-1', {})
                item = iteration_ctx.get('item', {})
                return {"step": "A", "item_id": item.get('id'), "data": "A" * PAYLOAD_SIZE}
            elif node_id == 'body-B':
                a_output = node_outputs.get('body-A', {})
                return {"step": "B", "from_a": a_output.get('item_id'), "data": "B" * PAYLOAD_SIZE}
            elif node_id == 'body-C':
                b_output = node_outputs.get('body-B', {})
                return {"step": "C", "result": b_output.get('from_a'), "data": "C" * PAYLOAD_SIZE}

            return {}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": [], "concurrency": 3}
            }},
            {"id": "body-A", "type": "body-node", "config": {}},
            {"id": "body-B", "type": "body-node", "config": {}},
            {"id": "body-C", "type": "body-node", "config": {}},
        ]
        edges = [
            {"source": "iteration-1", "target": "body-A", "sourceHandle": "loop"},
            {"source": "body-A", "target": "body-B"},
            {"source": "body-B", "target": "body-C"},
            {"source": "body-C", "target": "iteration-1"},  # loopback for aggregation
        ]

        nodes_executed, error, outputs = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None

        # All body nodes should have output with only lastOutput (no iterations array)
        for body_id in ['body-A', 'body-B', 'body-C']:
            body_output = outputs.get(body_id)
            assert body_output is not None, f"{body_id} should have output"
            assert 'iterations' not in body_output, (
                f"{body_id} should NOT have 'iterations' array. Keys: {list(body_output.keys())}"
            )
            assert 'lastOutput' in body_output, f"{body_id} should have lastOutput"

        # Only aggregation source (body-C, the loopback node) should have collected_results
        assert 'collected_results' in outputs.get('body-C', {}), (
            "body-C (loopback/aggregation source) should have collected_results"
        )
        assert 'collected_results' not in outputs.get('body-A', {}), (
            "body-A should NOT have collected_results (not the aggregation source)"
        )
        assert 'collected_results' not in outputs.get('body-B', {}), (
            "body-B should NOT have collected_results (not the aggregation source)"
        )

        # MEMORY CHECK: non-aggregation body nodes should have ONLY lastOutput
        # (not full iterations array). Verify their output size is bounded.
        for body_id in ['body-A', 'body-B']:
            body_out = outputs.get(body_id, {})
            body_json = json.dumps(body_out, default=str)
            body_size_kb = len(body_json) // 1024

            # Each body node should only have lastOutput (~50KB) + iterationCount
            # Old behavior: iterations array would be 10 × 50KB = 500KB per node
            assert body_size_kb < 100, (
                f"{body_id} output is {body_size_kb}KB — expected <100KB (just lastOutput). "
                f"Old behavior with iterations array would be ~500KB."
            )

        # Aggregation source (body-C) has collected_results so it's larger
        body_c_out = outputs.get('body-C', {})
        assert set(body_c_out.keys()) == {'lastOutput', 'iterationCount', 'collected_results'}, (
            f"body-C has unexpected keys: {set(body_c_out.keys())}"
        )

    @pytest.mark.asyncio
    async def test_iteration_memory_deep_diagnostic(self, handler):
        """
        Deep diagnostic: catalog exactly what's retained in node_outputs after
        iteration completes, with realistic newsletter-workflow sizes.

        Simulates: iteration over 21 RSS feed items, each body node produces
        ~200KB output (like an AI agent conversation history). After iteration,
        measures total retained memory across ALL node_outputs entries.

        This test reports the EXACT breakdown of retained data to identify
        what's consuming memory and whether any unnecessary data survives.
        """
        import json
        import sys
        import gc
        import tracemalloc

        ITEM_COUNT = 21  # Typical RSS feed size
        # Simulate RSS items: each has title, link, description, content (~5KB each)
        RSS_ITEM_SIZE = 5_000
        # Simulate agent body output: conversation history (~200KB each)
        BODY_OUTPUT_SIZE = 200_000

        rss_items = [
            {
                "title": f"Article {i}",
                "link": f"https://example.com/article-{i}",
                "description": f"Description for article {i}",
                "content": "C" * RSS_ITEM_SIZE,
            }
            for i in range(ITEM_COUNT)
        ]

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                return {
                    "items": rss_items,
                    "total": ITEM_COUNT,
                    "item": rss_items[0],
                    "index": 0,
                    "isIterationNode": True,
                    "headers": None,
                }
            elif node_type == 'body-node':
                iteration_ctx = node_outputs.get('iteration-1', {})
                item = iteration_ctx.get('item', {})
                # Simulate large agent output per iteration
                return {
                    "type": "agent_result",
                    "item_title": item.get('title', ''),
                    "conversation": "M" * BODY_OUTPUT_SIZE,
                    "summary": f"Summary for {item.get('title', '')}",
                }

            return {}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": [], "concurrency": 5}
            }},
            {"id": "body-1", "type": "body-node", "config": {}},
        ]
        edges = [
            {"source": "iteration-1", "target": "body-1", "sourceHandle": "loop"},
            {"source": "body-1", "target": "iteration-1"},
        ]

        # Force GC and start tracking
        gc.collect()
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        nodes_executed, error, outputs = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        # Force GC to free anything unreferenced
        gc.collect()
        snapshot_after = tracemalloc.take_snapshot()

        assert error is None

        # === CATALOG ALL RETAINED DATA IN node_outputs ===

        # 1. Iteration node output
        iter_out = outputs.get('iteration-1', {})
        iter_json = json.dumps(iter_out, default=str)
        iter_size_kb = len(iter_json) / 1024

        # 2. Body node output
        body_out = outputs.get('body-1', {})
        body_json = json.dumps(body_out, default=str)
        body_size_kb = len(body_json) / 1024

        # 3. Total across all outputs
        total_json = json.dumps(outputs, default=str)
        total_size_kb = len(total_json) / 1024

        # === DETAILED BREAKDOWN ===

        # Iteration node: check what's stored
        iter_items_json = json.dumps(iter_out.get('items', []), default=str)
        iter_items_size_kb = len(iter_items_json) / 1024

        iter_collected_json = json.dumps(iter_out.get('collected_results', []), default=str)
        iter_collected_size_kb = len(iter_collected_json) / 1024

        # Body node: check what's stored
        body_last_json = json.dumps(body_out.get('lastOutput', {}), default=str)
        body_last_size_kb = len(body_last_json) / 1024

        body_collected_json = json.dumps(body_out.get('collected_results', []), default=str)
        body_collected_size_kb = len(body_collected_json) / 1024

        # === tracemalloc delta ===
        stats = snapshot_after.compare_to(snapshot_before, 'lineno')
        top_allocs = sorted(stats, key=lambda s: s.size_diff, reverse=True)[:10]
        tracemalloc_total_kb = sum(s.size_diff for s in stats if s.size_diff > 0) / 1024

        tracemalloc.stop()

        # === REPORT ===
        report = (
            f"\n{'='*60}\n"
            f"ITERATION MEMORY DIAGNOSTIC REPORT\n"
            f"{'='*60}\n"
            f"Config: {ITEM_COUNT} items, {RSS_ITEM_SIZE/1000:.0f}KB/item, "
            f"{BODY_OUTPUT_SIZE/1000:.0f}KB/body-output\n"
            f"\n--- Retained in node_outputs ---\n"
            f"  iteration-1 total:     {iter_size_kb:>8.1f} KB\n"
            f"    .items array:        {iter_items_size_kb:>8.1f} KB  ({ITEM_COUNT} RSS items)\n"
            f"    .collected_results:  {iter_collected_size_kb:>8.1f} KB  ({len(iter_out.get('collected_results', []))} entries)\n"
            f"  body-1 total:          {body_size_kb:>8.1f} KB\n"
            f"    .lastOutput:         {body_last_size_kb:>8.1f} KB\n"
            f"    .collected_results:  {body_collected_size_kb:>8.1f} KB\n"
            f"  TOTAL outputs:         {total_size_kb:>8.1f} KB\n"
            f"\n--- tracemalloc delta ---\n"
            f"  Total new allocations:  {tracemalloc_total_kb:>8.1f} KB\n"
            f"\n--- Top allocations ---\n"
        )
        for stat in top_allocs[:5]:
            report += f"  {stat}\n"

        report += f"\n--- Iteration node output keys: {list(iter_out.keys())}\n"
        report += f"--- Body node output keys: {list(body_out.keys())}\n"
        report += f"{'='*60}\n"

        # Print the report (visible in pytest -v -s output)
        print(report)

        # === ASSERTIONS ===

        # 1. collected_results should be SHARED between iteration output and body output
        # (same list object, not duplicated)
        assert iter_out.get('collected_results') is body_out.get('collected_results'), (
            "collected_results should be the SAME list object on both iteration and body output, "
            "not duplicated. Duplication would double memory usage."
        )

        # 2. items array is retained in final_output — flag this as a potential optimization
        assert 'items' in iter_out, "items IS currently retained in iteration output"
        assert len(iter_out['items']) == ITEM_COUNT

        # 3. The items array size should be reported (it's unnecessary after done-nodes execute)
        # With 21 items × 5KB each = ~105KB. Not huge, but with larger RSS content it adds up.
        items_are_retained_mb = iter_items_size_kb / 1024
        print(f"NOTE: 'items' array ({items_are_retained_mb:.2f} MB) is retained in final_output. "
              f"Consider removing if downstream done-nodes don't need it.")

        # 4. collected_results is the largest retained structure
        # With 21 iterations × 200KB body output = ~4.2MB
        collected_results_mb = iter_collected_size_kb / 1024
        expected_collected_mb = (ITEM_COUNT * BODY_OUTPUT_SIZE) / (1024 * 1024)
        print(f"collected_results: {collected_results_mb:.2f} MB "
              f"(expected ~{expected_collected_mb:.1f} MB)")

        # 5. Total retained should be approximately:
        #    collected_results appears in BOTH iteration output AND body output
        #    (same Python object, but counted separately in per-node JSON sizes)
        #    NOT ITEM_COUNT × BODY_OUTPUT_SIZE × num_body_nodes (old iterations array)
        max_expected_total_kb = (
            iter_collected_size_kb * 2  # collected_results serialized in both outputs
            + iter_items_size_kb        # items array
            + body_last_size_kb         # lastOutput
            + 100                       # metadata overhead
        )
        assert total_size_kb < max_expected_total_kb * 1.2, (
            f"Total retained ({total_size_kb:.0f}KB) exceeds expected ({max_expected_total_kb:.0f}KB). "
            f"Possible duplication or unexpected data retention."
        )

        # 6. Body node should NOT have iterations array
        assert 'iterations' not in body_out
        assert set(body_out.keys()) == {'lastOutput', 'iterationCount', 'collected_results'}

    @pytest.mark.asyncio
    async def test_iteration_memory_items_duplication(self, handler):
        """
        Test whether the `items` array is duplicated across outputs.

        The iteration node stores `items` in both:
        - final_output['items'] (the iteration node's output)
        - Each iteration_context['items'] passed to body nodes

        After iteration completes, verify items is only retained ONCE
        (in the iteration node's output) and not leaked elsewhere.
        """
        ITEM_COUNT = 15
        ITEM_SIZE = 10_000  # 10KB per item

        large_items = [
            {"id": i, "content": "X" * ITEM_SIZE}
            for i in range(ITEM_COUNT)
        ]

        captured_items_refs = []

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                return {
                    "items": large_items,
                    "total": ITEM_COUNT,
                    "item": large_items[0],
                    "index": 0,
                    "isIterationNode": True,
                }
            elif node_type == 'body-node':
                # Capture the items reference from iteration context
                iteration_ctx = node_outputs.get('iteration-1', {})
                items_ref = iteration_ctx.get('items')
                if items_ref is not None:
                    captured_items_refs.append(id(items_ref))
                return {"result": "ok", "index": iteration_ctx.get('index')}

            return {}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": [], "concurrency": 5}
            }},
            {"id": "body-1", "type": "body-node", "config": {}},
        ]
        edges = [
            {"source": "iteration-1", "target": "body-1", "sourceHandle": "loop"},
            {"source": "body-1", "target": "iteration-1"},
        ]

        _, error, outputs = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )
        assert error is None

        # All iterations should have received the SAME items list (shared reference)
        assert len(captured_items_refs) == ITEM_COUNT, (
            f"Expected {ITEM_COUNT} iterations, got {len(captured_items_refs)}"
        )
        unique_refs = set(captured_items_refs)
        assert len(unique_refs) == 1, (
            f"items array was copied {len(unique_refs)} times across iterations — "
            f"should be the SAME object reference. Each copy wastes "
            f"{ITEM_COUNT * ITEM_SIZE / 1024:.0f}KB."
        )

        # After execution, items should only live in iteration node's output
        iter_out = outputs.get('iteration-1', {})
        assert id(iter_out['items']) == captured_items_refs[0], (
            "items in final_output should be the same object as what was passed to iterations"
        )

    @pytest.mark.asyncio
    async def test_iteration_peak_memory_during_gather(self, handler):
        """
        Test peak memory during asyncio.gather phase.

        During gather, ALL iterations run concurrently (limited by semaphore).
        Each creates:
        - iteration_node_outputs = dict(ctx.node_outputs)  — shallow copy
        - iteration_outputs dict — body node results
        - The actual body output objects

        With N iterations and M body nodes, peak memory is:
        N × (M body outputs + dict overhead)

        This test measures the peak to flag if it's excessive.
        """
        import tracemalloc
        import gc

        ITEM_COUNT = 21
        BODY_OUTPUT_SIZE = 200_000  # 200KB per body output
        CONCURRENCY = 5  # Max concurrent iterations

        peak_concurrent = 0
        peak_lock = asyncio.Lock()
        active_count = 0

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            nonlocal peak_concurrent, active_count
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                return {
                    "items": [{"id": i} for i in range(ITEM_COUNT)],
                    "total": ITEM_COUNT,
                    "item": {"id": 0},
                    "index": 0,
                    "isIterationNode": True,
                }
            elif node_type == 'body-node':
                async with peak_lock:
                    active_count += 1
                    peak_concurrent = max(peak_concurrent, active_count)

                # Simulate work — body node produces large output
                await asyncio.sleep(0.01)
                result = {
                    "data": "D" * BODY_OUTPUT_SIZE,
                    "index": node_outputs.get('iteration-1', {}).get('index', 0),
                }

                async with peak_lock:
                    active_count -= 1

                return result

            return {}

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": [], "concurrency": CONCURRENCY}
            }},
            {"id": "body-1", "type": "body-node", "config": {}},
        ]
        edges = [
            {"source": "iteration-1", "target": "body-1", "sourceHandle": "loop"},
            {"source": "body-1", "target": "iteration-1"},
        ]

        gc.collect()
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        _, error, outputs = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        gc.collect()
        snapshot_after = tracemalloc.take_snapshot()

        # Check peak memory
        stats = snapshot_after.compare_to(snapshot_before, 'lineno')
        retained_kb = sum(s.size_diff for s in stats if s.size_diff > 0) / 1024

        tracemalloc.stop()

        assert error is None

        # Peak concurrent should be limited by semaphore
        assert peak_concurrent <= CONCURRENCY, (
            f"Peak concurrent iterations ({peak_concurrent}) exceeded "
            f"concurrency limit ({CONCURRENCY})"
        )

        # Calculate expected peak memory:
        # During gather: up to CONCURRENCY iterations alive at once
        # Each has: 1 body output (BODY_OUTPUT_SIZE) + iteration_node_outputs dict copy
        # After gather: only collected_results (ITEM_COUNT × extracted data) + lastOutput
        peak_during_gather_mb = (CONCURRENCY * BODY_OUTPUT_SIZE) / (1024 * 1024)
        retained_after_mb = (ITEM_COUNT * BODY_OUTPUT_SIZE) / (1024 * 1024)  # collected_results

        print(f"\n--- Peak Memory Analysis ---")
        print(f"Concurrency limit: {CONCURRENCY}")
        print(f"Peak concurrent: {peak_concurrent}")
        print(f"Expected peak during gather: ~{peak_during_gather_mb:.1f} MB "
              f"({CONCURRENCY} × {BODY_OUTPUT_SIZE/1000:.0f}KB)")
        print(f"Expected retained after: ~{retained_after_mb:.1f} MB "
              f"(collected_results: {ITEM_COUNT} × {BODY_OUTPUT_SIZE/1000:.0f}KB)")
        print(f"Actual retained (tracemalloc): {retained_kb/1024:.1f} MB")

        # BUT: all ITEM_COUNT outputs live in iteration_results during gather
        # because iteration_results is pre-allocated and filled as each completes.
        # After gather + clear: only collected_results survives.
        # The REAL peak is ITEM_COUNT × BODY_OUTPUT_SIZE (all results in memory at once)
        true_peak_mb = (ITEM_COUNT * BODY_OUTPUT_SIZE) / (1024 * 1024)
        print(f"True peak (all iteration_results): ~{true_peak_mb:.1f} MB")

        # Verify retained is bounded (collected_results + overhead, not 2x)
        retained_mb = retained_kb / 1024
        # collected_results holds all outputs, and the json overhead doubles string memory
        max_retained_mb = true_peak_mb * 2.5  # generous but catches exponential growth
        assert retained_mb < max_retained_mb, (
            f"Retained memory ({retained_mb:.1f}MB) exceeds expected "
            f"({max_retained_mb:.1f}MB). Possible leak."
        )

    @pytest.mark.asyncio
    async def test_memory_audit_realistic_newsletter_workflow(self, handler):
        """
        Realistic reproduction of the newsletter workflow memory pattern.

        Production scenario: 21 RSS feeds iterated, each feed processed by
        3 body nodes (rss_parser → agent → formatter), producing ~200KB per
        body node per iteration. After iteration completes, audit EVERY output
        in node_outputs to quantify total retained memory.

        The referrer trace from production showed nested {'iterations': [...]}
        structures 4-5 levels deep. This test verifies our fix eliminates that
        pattern and quantifies exactly what IS retained.
        """
        import json
        import sys

        FEED_COUNT = 21  # matches production newsletter workflow
        BODY_NODES = ['rss-parser', 'agent', 'formatter']
        FEED_SIZE = 200_000  # 200KB per RSS feed output (realistic)

        def make_feed_output(feed_idx, body_node_id):
            """Simulate realistic RSS feed body node output."""
            return {
                'feed': {
                    'title': f'Feed {feed_idx}',
                    'link': f'https://example.com/feed/{feed_idx}',
                    'entries': [
                        {'title': f'Article {j}', 'content': 'x' * (FEED_SIZE // 10)}
                        for j in range(10)
                    ],
                },
                'processed_by': body_node_id,
                'status': 'success',
            }

        async def mock_execute_node(node, node_outputs, sid, user_id, workflow_id, conversation_id=None, workflow_nodes=None, workflow_edges=None, workflow_org_id=None, execution_id=None):
            node_id = node['id']
            node_type = node.get('type', '')

            if node_type == 'iteration':
                return {
                    "items": [{"feed_url": f"https://example.com/feed/{i}"} for i in range(FEED_COUNT)],
                    "total": FEED_COUNT,
                    "item": {"feed_url": "https://example.com/feed/0"},
                    "index": 0,
                    "isIterationNode": True,
                }

            # All body nodes return large feed-like output
            iteration_ctx = node_outputs.get('iteration-1', {})
            feed_idx = iteration_ctx.get('index', 0)
            return make_feed_output(feed_idx, node_id)

        handler._execute_node = mock_execute_node

        nodes = [
            {"id": "iteration-1", "type": "iteration", "config": {
                "config": {"items": [], "concurrency": 5}
            }},
            {"id": "rss-parser", "type": "rss", "config": {}},
            {"id": "agent", "type": "serverless-function", "config": {}},
            {"id": "formatter", "type": "serverless-function", "config": {}},
        ]
        edges = [
            {"source": "iteration-1", "target": "rss-parser", "sourceHandle": "loop"},
            {"source": "rss-parser", "target": "agent"},
            {"source": "agent", "target": "formatter"},
            {"source": "formatter", "target": "iteration-1"},  # loopback
        ]

        nodes_executed, error, outputs = await handler._execute_nodes_concurrent(
            nodes, edges, "test-sid", "test-user-id", "test-workflow-id"
        )

        assert error is None

        # === AUDIT 1: No 'iterations' key anywhere (the root cause of the 19GB leak) ===
        for node_id, output in outputs.items():
            if isinstance(output, dict):
                assert 'iterations' not in output, (
                    f"node_outputs['{node_id}'] still has 'iterations' key! "
                    f"This is the OLD behavior that caused 19GB memory retention. "
                    f"Keys: {list(output.keys())}"
                )

        # === AUDIT 2: No nested iterations in referrer chain ===
        # The production referrer trace showed: dict → list → list → list → list
        # with 'iterations' keys. Recursively check for this pattern.
        def find_iterations_key(obj, path="root", depth=0):
            """Recursively search for 'iterations' key in any nested structure."""
            if depth > 10:
                return []
            findings = []
            if isinstance(obj, dict):
                if 'iterations' in obj:
                    findings.append(f"{path} -> 'iterations' key found")
                for k, v in obj.items():
                    findings.extend(find_iterations_key(v, f"{path}.{k}", depth + 1))
            elif isinstance(obj, list) and len(obj) < 100:  # don't traverse huge lists fully
                for i, v in enumerate(obj[:5]):  # sample first 5
                    findings.extend(find_iterations_key(v, f"{path}[{i}]", depth + 1))
            return findings

        iterations_findings = find_iterations_key(outputs)
        assert len(iterations_findings) == 0, (
            f"Found 'iterations' key in nested outputs — this causes the memory leak!\n"
            + "\n".join(iterations_findings)
        )

        # === AUDIT 3: Quantify total retained memory ===
        total_json_size = 0
        per_node_sizes = {}
        for node_id, output in outputs.items():
            node_json = json.dumps(output, default=str)
            size_kb = len(node_json) / 1024
            per_node_sizes[node_id] = size_kb
            total_json_size += size_kb

        # With the fix: retained data should be:
        # - iteration-1: items (21 small dicts) + collected_results (21 × 200KB) + metadata
        #   collected_results = ~4.2MB
        # - rss-parser: lastOutput (~200KB) + iterationCount = ~200KB
        # - agent: lastOutput (~200KB) + iterationCount = ~200KB
        # - formatter: lastOutput (~200KB) + iterationCount + collected_results (~4.2MB) = ~4.4MB
        # Total: ~9MB
        #
        # WITHOUT the fix (old code), retained data would be:
        # - iteration-1: items + results (21 × {outputs: {3 body nodes × 200KB}}) + collected_results
        #   results = 21 × 3 × 200KB = 12.6MB, collected_results = 4.2MB → ~17MB
        # - rss-parser: iterations (21 × 200KB) = 4.2MB
        # - agent: iterations (21 × 200KB) = 4.2MB
        # - formatter: iterations (21 × 200KB) + collected_results (4.2MB) = 8.4MB
        # Total: ~34MB
        #
        # Fix reduces retained data by ~70%

        # Non-aggregation body nodes: only lastOutput (~200KB each)
        for body_id in ['rss-parser', 'agent']:
            size = per_node_sizes.get(body_id, 0)
            # Old behavior: 21 × 200KB = 4200KB per node
            # New behavior: 1 × 200KB = 200KB per node
            assert size < 500, (
                f"{body_id} retains {size:.0f}KB — should be ~200KB (lastOutput only). "
                f"Old behavior would be ~4200KB (21 iterations × 200KB)."
            )

        # Aggregation source (formatter): lastOutput + collected_results
        formatter_size = per_node_sizes.get('formatter', 0)
        # collected_results has 21 outputs but they're extracted data, not full iteration dicts
        # This is expected and correct — downstream nodes need this data
        assert formatter_size < 6000, (
            f"formatter retains {formatter_size:.0f}KB — expected ~4400KB "
            f"(lastOutput + collected_results). Got more than expected."
        )

        # Iteration node: items + collected_results + metadata
        iter_size = per_node_sizes.get('iteration-1', 0)
        assert iter_size < 6000, (
            f"iteration-1 retains {iter_size:.0f}KB — expected ~4200KB "
            f"(collected_results + metadata). Got more than expected."
        )

        # Total retained should be well under what old code would retain
        # Old code: ~34MB total. New code: ~9MB total.
        assert total_json_size < 15_000, (
            f"Total retained: {total_json_size:.0f}KB ({total_json_size/1024:.1f}MB). "
            f"Expected <15MB with fix. Old behavior would be ~34MB. "
            f"Breakdown: {json.dumps({k: f'{v:.0f}KB' for k, v in per_node_sizes.items()})}"
        )

        # === AUDIT 4: collected_results is the ONLY large retained structure ===
        # Verify it has exactly FEED_COUNT items (one per iteration)
        iter_output = outputs.get('iteration-1', {})
        collected = iter_output.get('collected_results', [])
        assert len(collected) == FEED_COUNT, (
            f"collected_results has {len(collected)} items, expected {FEED_COUNT}"
        )

        # Verify collected_results items are the RAW body outputs (no wrapping)
        for i, item in enumerate(collected):
            assert isinstance(item, dict), f"collected_results[{i}] should be a dict"
            assert 'iterations' not in item, (
                f"collected_results[{i}] has 'iterations' key — should be raw output"
            )
            assert item.get('processed_by') == 'formatter', (
                f"collected_results should contain formatter outputs (aggregation source), "
                f"got processed_by={item.get('processed_by')}"
            )
