"""
Tests for workflow node state persistence.
Verifies that state is correctly saved and loaded from the workflow_node_state table.
"""

import os
import pytest
import uuid
from unittest.mock import MagicMock, patch, AsyncMock

# Set test database URLs if not set. Backend runtime reads POSTGRES_POOLER_URL
# only; POSTGRES_URL is kept for migrations/scripts/legacy paths.
if 'POSTGRES_POOLER_URL' not in os.environ:
    os.environ['POSTGRES_POOLER_URL'] = 'postgresql://postgres:postgres@127.0.0.1:54322/postgres'
if 'POSTGRES_URL' not in os.environ:
    os.environ['POSTGRES_URL'] = 'postgresql://postgres:postgres@127.0.0.1:54322/postgres'


class TestStateManagerNode:
    """Test StateManagerNode state loading and saving."""

    @pytest.fixture
    def mock_pool(self):
        """Pool double for the native seam (per-verb AsyncMocks)."""
        from tests.mocks.mock_asyncpg import MockNativePool
        return MockNativePool()

    def test_load_node_state_empty(self, mock_pool):
        """Test loading state when none exists returns empty dict."""
        from nodes.state_manager_node import StateManagerNode

        # Patch at the point of import in the module that uses it
        with patch('utils.database_pool.get_native_pool', return_value=mock_pool):
            node = StateManagerNode(
                node_id='test-node',
                node_type='state-manager',
                node_data={},
                sio=None,
                sid=None,
                workflow_id='test-workflow',
                user_id='test-user'
            )

            import asyncio
            state = asyncio.get_event_loop().run_until_complete(node._load_node_state())

            assert state == {}
            mock_pool.fetchrow.assert_awaited_once()

    def test_load_node_state_with_data(self, mock_pool):
        """Test loading state returns stored data."""
        from nodes.state_manager_node import StateManagerNode

        stored_state = {'counter': 5, 'items': ['a', 'b']}
        mock_pool.responses["workflow_node_state"] = {'state': stored_state}

        with patch('utils.database_pool.get_native_pool', return_value=mock_pool):
            node = StateManagerNode(
                node_id='test-node',
                node_type='state-manager',
                node_data={},
                sio=None,
                sid=None,
                workflow_id='test-workflow',
                user_id='test-user'
            )

            import asyncio
            state = asyncio.get_event_loop().run_until_complete(node._load_node_state())

            assert state == stored_state

    def test_save_node_state(self, mock_pool):
        """Test saving state calls database correctly."""
        from nodes.state_manager_node import StateManagerNode

        with patch('utils.database_pool.get_native_pool', return_value=mock_pool):
            node = StateManagerNode(
                node_id='test-node',
                node_type='state-manager',
                node_data={},
                sio=None,
                sid=None,
                workflow_id='test-workflow',
                user_id='test-user'
            )

            test_state = {'counter': 10}
            import asyncio
            asyncio.get_event_loop().run_until_complete(node._save_node_state(test_state))

            # Verify the INSERT landed on the pool with the correct SQL pattern
            mock_pool.execute.assert_awaited_once()
            call_args = mock_pool.execute.await_args
            assert 'INSERT INTO workflow_node_state' in call_args[0][0]
            assert 'ON CONFLICT' in call_args[0][0]


class TestServerlessFunctionStateInjection:
    """Test state injection and persistence in ServerlessFunctionNode."""

    @pytest.fixture
    def mock_pool(self):
        """Pool double for the native seam (per-verb AsyncMocks)."""
        from tests.mocks.mock_asyncpg import MockNativePool
        return MockNativePool()

    def test_state_persistence_after_execution(self, mock_pool):
        """Test that mutated state is persisted after code execution."""
        from nodes.serverless_function_node import ServerlessFunctionNode

        with patch('utils.database_pool.get_native_pool', return_value=mock_pool):
            node = ServerlessFunctionNode(
                node_id='code-node',
                node_type='serverless-function',
                node_data={
                    '__state_input__': {
                        'node_id': 'state-manager-1',
                        'state': {'counter': 0}
                    }
                },
                sio=None,
                sid=None,
                workflow_id='test-workflow',
                user_id='test-user'
            )

            mutated_state = {'counter': 1}
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                node._persist_state_to_manager('state-manager-1', mutated_state)
            )

            # Verify database was called
            mock_pool.execute.assert_awaited_once()
            call_args = mock_pool.execute.await_args

            # Check SQL query
            assert 'INSERT INTO workflow_node_state' in call_args[0][0]
            assert 'ON CONFLICT' in call_args[0][0]

            # Check parameters (workflow_id, node_id, state)
            assert call_args[0][1] == 'test-workflow'
            assert call_args[0][2] == 'state-manager-1'
            assert call_args[0][3] == mutated_state


class TestWorkflowExecutionStateFlow:
    """Test the full state flow during workflow execution."""

    def test_state_injection_from_edge(self):
        """Test that state is injected when state edge exists."""
        from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

        # Create handler with mocked dependencies
        handler = WorkflowExecutionHandler.__new__(WorkflowExecutionHandler)
        handler.sio = MagicMock()

        # Simulate state edge detection
        workflow_edges = [
            {'source': 'state-manager-1', 'target': 'code-node-1', 'targetHandle': 'state'}
        ]

        node_outputs = {
            'state-manager-1': {
                'type': 'state_manager',
                'status': 'success',
                'state': {'counter': 5}
            }
        }

        # Find the state edge
        node_id = 'code-node-1'
        state_edge = next(
            (e for e in workflow_edges
             if e.get('target') == node_id and e.get('targetHandle') == 'state'),
            None
        )

        assert state_edge is not None
        assert state_edge['source'] == 'state-manager-1'

        # Get state from source output
        state_source_output = node_outputs.get(state_edge['source'], {})
        assert 'state' in state_source_output
        assert state_source_output['state'] == {'counter': 5}
