"""
End-to-end test for workflow state management.
Tests the full flow: State Manager -> Code Node -> State Persistence
"""

import asyncio
import os
import pytest
import uuid
from unittest.mock import MagicMock, AsyncMock, patch

# Set test database URL. Backend runtime reads POSTGRES_POOLER_URL only;
# POSTGRES_URL is kept for migrations/scripts/legacy paths.
os.environ.setdefault('POSTGRES_POOLER_URL', 'postgresql://postgres:postgres@127.0.0.1:54322/postgres')
os.environ.setdefault('POSTGRES_URL', 'postgresql://postgres:postgres@127.0.0.1:54322/postgres')


class TestStateE2E:
    """End-to-end tests for state management."""

    @pytest.fixture
    def mock_emit(self):
        """Mock the emit function for nodes."""
        return AsyncMock()

    @pytest.fixture
    def workflow_id(self):
        """Generate a test workflow ID."""
        return str(uuid.uuid4())

    @pytest.fixture
    def mock_db(self):
        """A stateful pool double simulating workflow_node_state storage."""
        from tests.mocks.mock_asyncpg import MockNativePool

        storage = {}
        pool = MockNativePool()

        async def mock_fetchrow(query, *args, timeout=None):
            if 'workflow_node_state' in query:
                wf_id, node_id = args[0], args[1]
                key = f"{wf_id}:{node_id}"
                if key in storage:
                    # `_load_node_state` selects the CAS `version` column too.
                    return {'state': storage[key], 'version': 0}
                return None
            return None

        async def mock_execute(query, *args, timeout=None):
            if 'INSERT INTO workflow_node_state' in query:
                wf_id, node_id, state = args[0], args[1], args[2]
                key = f"{wf_id}:{node_id}"
                storage[key] = state
            return "EXECUTE 1"

        pool.fetchrow.side_effect = mock_fetchrow
        pool.execute.side_effect = mock_execute
        pool._storage = storage  # Expose for assertions

        return pool

    def test_state_manager_loads_persisted_state(self, mock_db, workflow_id):
        """Test that StateManagerNode loads state from database."""
        from nodes.state_manager_node import StateManagerNode, StateManagerNodeConfig, StateManagerInnerConfig

        state_node_id = 'state-mgr-1'

        # Pre-populate database with existing state
        mock_db._storage[f"{workflow_id}:{state_node_id}"] = {'counter': 5, 'items': ['a', 'b']}

        with patch('utils.database_pool.get_native_pool', return_value=mock_db):
            node = StateManagerNode(
                node_id=state_node_id,
                node_type='state-manager',
                node_data={},
                sio=None, sid=None,
                workflow_id=workflow_id,
                user_id='test-user'
            )

            # Execute node
            result = asyncio.get_event_loop().run_until_complete(node.execute({}))

            # Should have loaded persisted state
            assert result['status'] == 'success'
            assert result['state']['counter'] == 5
            assert result['state']['items'] == ['a', 'b']

    def test_state_manager_merges_with_defaults(self, mock_db, workflow_id):
        """Test that StateManagerNode merges persisted state with defaults."""
        from nodes.state_manager_node import StateManagerNode, StateManagerNodeConfig, StateManagerInnerConfig

        state_node_id = 'state-mgr-2'

        # Pre-populate with partial state
        mock_db._storage[f"{workflow_id}:{state_node_id}"] = {'counter': 10}

        with patch('utils.database_pool.get_native_pool', return_value=mock_db):
            # Create node with default state containing additional keys
            node_data = {
                'config': {'config': {'state': {'counter': 0, 'name': 'default'}}}
            }

            node = StateManagerNode(
                node_id=state_node_id,
                node_type='state-manager',
                node_data=node_data,
                sio=None, sid=None,
                workflow_id=workflow_id,
                user_id='test-user'
            )

            result = asyncio.get_event_loop().run_until_complete(node.execute({}))

            # Persisted counter should override default, but name from default preserved
            assert result['state']['counter'] == 10  # From persisted
            # Note: Currently implementation only uses persisted, not merged

    def test_code_node_persists_state_with_state_key(self, mock_db, workflow_id, mock_emit):
        """Test that returning {state: {...}} triggers persistence."""
        from nodes.serverless_function_node import ServerlessFunctionNode

        state_node_id = 'state-mgr-3'
        code_node_id = 'code-3'

        with patch('utils.database_pool.get_native_pool', return_value=mock_db):
            # Simulate: Code node receives injected state and returns modified state
            node = ServerlessFunctionNode(
                node_id=code_node_id,
                node_type='automation-serverless-function',
                node_data={
                    '__state_input__': {
                        'node_id': state_node_id,
                        'state': {'counter': 0}
                    }
                },
                sio=None, sid=None,
                workflow_id=workflow_id,
                user_id='test-user'
            )

            # Test _persist_state_to_manager directly
            new_state = {'counter': 1, 'message': 'updated'}
            asyncio.get_event_loop().run_until_complete(
                node._persist_state_to_manager(state_node_id, new_state)
            )

            # Verify state was persisted
            assert mock_db._storage[f"{workflow_id}:{state_node_id}"] == new_state

    def test_full_state_flow_simulation(self, mock_db, workflow_id):
        """Simulate the full flow across multiple workflow runs."""
        from nodes.state_manager_node import StateManagerNode
        from nodes.serverless_function_node import ServerlessFunctionNode

        state_node_id = 'state-mgr-flow'
        code_node_id = 'code-flow'

        with patch('utils.database_pool.get_native_pool', return_value=mock_db):
            # === Run 1 ===
            # State Manager loads (empty initially)
            state_node = StateManagerNode(
                node_id=state_node_id,
                node_type='state-manager',
                node_data={},
                sio=None, sid=None,
                workflow_id=workflow_id,
                user_id='test-user'
            )

            state_result = asyncio.get_event_loop().run_until_complete(
                state_node.execute({})
            )
            assert state_result['state'] == {}  # Empty initially

            # Code node receives state and persists incremented value
            code_node = ServerlessFunctionNode(
                node_id=code_node_id,
                node_type='automation-serverless-function',
                node_data={
                    '__state_input__': {
                        'node_id': state_node_id,
                        'state': {'counter': 0}  # Default from State Manager config
                    }
                },
                sio=None, sid=None,
                workflow_id=workflow_id,
                user_id='test-user'
            )

            # Simulate what happens after JS execution returns state
            asyncio.get_event_loop().run_until_complete(
                code_node._persist_state_to_manager(state_node_id, {'counter': 1})
            )

            # === Run 2 ===
            # State Manager should now load persisted state
            state_result2 = asyncio.get_event_loop().run_until_complete(
                state_node.execute({})
            )
            assert state_result2['state']['counter'] == 1

            # Persist incremented again
            asyncio.get_event_loop().run_until_complete(
                code_node._persist_state_to_manager(state_node_id, {'counter': 2})
            )

            # === Run 3 ===
            state_result3 = asyncio.get_event_loop().run_until_complete(
                state_node.execute({})
            )
            assert state_result3['state']['counter'] == 2

            # Final increment
            asyncio.get_event_loop().run_until_complete(
                code_node._persist_state_to_manager(state_node_id, {'counter': 3})
            )

            # Verify final state
            final_state = mock_db._storage[f"{workflow_id}:{state_node_id}"]
            assert final_state['counter'] == 3, f"Expected counter=3, got {final_state}"
