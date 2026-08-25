"""
Test suite for WorkflowHandler.

Validates workflow execution logging and listing functionality:
- Execution logs are properly persisted with correct status
- Listing execution logs via workflow:list_executions event
- Status transitions are tracked correctly in database
- Response format matches WorkflowExecutionInfo schema
"""

import pytest
import pytest_asyncio
import asyncio
import uuid
from typing import List, Dict, Any
from unittest.mock import patch, AsyncMock, MagicMock

from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from wss.receiver.client_events import WorkflowExecuteRequest, WorkflowExecutionListRequest, WorkflowExecutionCountsRequest
from wss.sender import send_event


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


@pytest.mark.asyncio
class TestWorkflowExecutionListing(BaseHandlerTest):
    """
    Integration tests for WorkflowHandler execution listing with real PostgreSQL database.

    Verifies that workflow execution logs can be properly listed and queried:
    - Execution logs are retrievable via workflow:list_executions
    - Response format matches WorkflowExecutionListResponse schema
    - Status updates are reflected in listed executions
    - Multiple executions are properly returned
    """

    def get_session_data(self, sid: str):
        """Override to provide consistent test user ID."""
        return {
            'sid': sid,
            'user_id': '00000000-0000-4000-8000-000000000001',
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

    async def test_list_executions_returns_empty_for_new_workflow(self, real_database, frontend_sio, sid):
        """
        Test that listing executions for a workflow with no executions returns empty list.

        Verifies:
        - workflow:list_executions returns empty executions array
        - No errors are raised for workflows without executions
        """
        # Create a workflow
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000001'

        # Create test user first
        await self.create_test_user(real_database, user_id)

        await asyncio.sleep(0.1)
        await real_database.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        """, workflow_id, user_id, "Test Workflow", "Test Description", {}, {})

        # Request execution list
        list_request = WorkflowExecutionListRequest(
            event_name="workflow:list_executions",
            request_id="test-list-1",
            workflow_id=workflow_id
        )

        await send_event(frontend_sio, sid, list_request)
        await asyncio.sleep(0.2)

        # Verify response
        response_events = self.get_main_api_emitted_events("response")
        matching_responses = [e for e in response_events if e[1].get('request_id') == 'test-list-1']
        assert len(matching_responses) == 1, "Should receive one response"

        response_data = matching_responses[0][1]['data']
        assert 'executions' in response_data
        assert response_data['executions'] == [], "Should return empty list for workflow with no executions"

    async def test_list_executions_returns_completed_execution(self, real_database, frontend_sio, sid):
        """
        Test that completed executions are properly returned by workflow:list_executions.

        Verifies:
        - Execution appears in list after workflow completes
        - Response data matches WorkflowExecutionInfo schema
        - Status, timestamps, and metadata are correct
        """
        # Create a workflow
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000001'

        # Create test user first
        await self.create_test_user(real_database, user_id)

        await asyncio.sleep(0.1)
        await real_database.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        """, workflow_id, user_id, "Test Workflow", "Test Description", {}, {})

        # Execute workflow
        nodes = [
            {"id": "node-1", "type": "automation-telegram", "position": {"x": 0, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Test execution", "chatId": "exec-123"})},
        ]
        edges = []

        workflow_request = WorkflowExecuteRequest(
            event_name="workflow:execute",
            request_id="test-exec-1",
            workflow_id=workflow_id,
            nodes=nodes,
            edges=edges
        )

        await send_event(frontend_sio, sid, workflow_request)
        await asyncio.sleep(0.3)

        # Get execution_id from workflow:started event
        started_events = self.get_main_api_emitted_events("workflow:started")
        assert len(started_events) >= 1
        execution_id = started_events[-1][1]['execution_id']

        # Verify workflow completed
        complete_events = self.get_main_api_emitted_events("workflow:complete")
        assert len(complete_events) >= 1
        assert complete_events[-1][1]['success'] is True

        # Request execution list
        list_request = WorkflowExecutionListRequest(
            event_name="workflow:list_executions",
            request_id="test-list-2",
            workflow_id=workflow_id
        )

        await send_event(frontend_sio, sid, list_request)
        await asyncio.sleep(0.2)

        # Verify response
        response_events = self.get_main_api_emitted_events("response")
        matching_responses = [e for e in response_events if e[1].get('request_id') == 'test-list-2']
        assert len(matching_responses) == 1

        response_data = matching_responses[0][1]['data']
        assert 'executions' in response_data
        assert len(response_data['executions']) >= 1, "Should return at least one execution"

        # Find our execution in the list
        our_execution = None
        for execution in response_data['executions']:
            if execution['id'] == execution_id:
                our_execution = execution
                break

        assert our_execution is not None, f"Execution {execution_id} should be in list"

        # Verify execution data matches WorkflowExecutionInfo schema
        assert our_execution['workflow_id'] == workflow_id
        assert our_execution['user_id'] == user_id
        assert our_execution['status'] == 'completed', "Status should be 'completed'"
        assert 'started_at' in our_execution and our_execution['started_at'] is not None
        assert 'finished_at' in our_execution and our_execution['finished_at'] is not None
        assert our_execution['nodes_executed'] == 1, "Should have executed 1 node"
        assert our_execution.get('error') is None, "Error should be None for successful execution"

    async def test_list_executions_returns_error_execution(self, real_database, frontend_sio, sid):
        """
        Test that failed executions are properly returned with error information.

        Verifies:
        - Failed execution appears in list with status='error'
        - Error message is included in response
        - finished_at is set even for failed executions
        """
        # Create a workflow
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000001'

        # Create test user first
        await self.create_test_user(real_database, user_id)

        await asyncio.sleep(0.1)
        await real_database.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        """, workflow_id, user_id, "Test Workflow", "Test Description", {}, {})

        # Execute workflow with cycle (will cause error)
        nodes = [
            {"id": "A", "type": "automation-telegram", "position": {"x": 0, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Error A", "chatId": "err-a"})},
            {"id": "B", "type": "automation-telegram", "position": {"x": 100, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Error B", "chatId": "err-b"})},
        ]
        edges = [
            {"id": "e1", "source": "A", "target": "B"},
            {"id": "e2", "source": "B", "target": "A"},  # Creates cycle
        ]

        workflow_request = WorkflowExecuteRequest(
            event_name="workflow:execute",
            request_id="test-exec-error",
            workflow_id=workflow_id,
            nodes=nodes,
            edges=edges
        )

        await send_event(frontend_sio, sid, workflow_request)
        await asyncio.sleep(0.3)

        # Get execution_id if workflow:started was emitted
        started_events = self.get_main_api_emitted_events("workflow:started")

        # If workflow:started was emitted, verify error is in execution list
        if len(started_events) > 0:
            execution_id = started_events[-1][1]['execution_id']

            # Request execution list
            list_request = WorkflowExecutionListRequest(
                event_name="workflow:list_executions",
                request_id="test-list-error",
                workflow_id=workflow_id
            )

            await send_event(frontend_sio, sid, list_request)
            await asyncio.sleep(0.2)

            # Verify response
            response_events = self.get_main_api_emitted_events("response")
            matching_responses = [e for e in response_events if e[1].get('request_id') == 'test-list-error']
            assert len(matching_responses) == 1

            response_data = matching_responses[0][1]['data']
            assert len(response_data['executions']) >= 1

            # Find our execution in the list
            our_execution = None
            for execution in response_data['executions']:
                if execution['id'] == execution_id:
                    our_execution = execution
                    break

            assert our_execution is not None
            assert our_execution['status'] == 'error', "Status should be 'error'"
            assert our_execution['error'] is not None, "Error message should be present"
            assert 'cycle' in our_execution['error'].lower() or 'order' in our_execution['error'].lower()
            assert our_execution['finished_at'] is not None, "finished_at should be set even for errors"
            assert our_execution['nodes_executed'] == 0, "No nodes should have executed"

    async def test_list_executions_returns_multiple_executions(self, real_database, frontend_sio, sid):
        """
        Test that multiple executions are properly returned in order.

        Verifies:
        - Multiple executions are all returned
        - Executions are ordered by started_at DESC (newest first)
        - Each execution has unique execution_id
        """
        # Create a workflow
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000001'

        # Create test user first
        await self.create_test_user(real_database, user_id)

        await asyncio.sleep(0.1)
        await real_database.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        """, workflow_id, user_id, "Test Workflow", "Test Description", {}, {})

        # Execute workflow 3 times
        execution_ids = []
        for i in range(3):
            nodes = [
                {"id": f"node-{i}", "type": "automation-telegram", "position": {"x": 0, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": f"Multi test {i}", "chatId": f"multi-{i}"})},
            ]
            edges = []

            workflow_request = WorkflowExecuteRequest(
                event_name="workflow:execute",
                request_id=f"test-exec-{i}",
                workflow_id=workflow_id,
                nodes=nodes,
                edges=edges
            )

            await send_event(frontend_sio, sid, workflow_request)
            await asyncio.sleep(0.3)

            # Get execution_id
            started_events = self.get_main_api_emitted_events("workflow:started")
            execution_id = started_events[-1][1]['execution_id']
            execution_ids.append(execution_id)

        # Request execution list
        list_request = WorkflowExecutionListRequest(
            event_name="workflow:list_executions",
            request_id="test-list-multiple",
            workflow_id=workflow_id
        )

        await send_event(frontend_sio, sid, list_request)
        await asyncio.sleep(0.2)

        # Verify response
        response_events = self.get_main_api_emitted_events("response")
        matching_responses = [e for e in response_events if e[1].get('request_id') == 'test-list-multiple']
        assert len(matching_responses) == 1

        response_data = matching_responses[0][1]['data']
        assert len(response_data['executions']) >= 3, "Should return at least 3 executions"

        # Verify all our execution_ids are in the response
        returned_ids = [exec['id'] for exec in response_data['executions']]
        for exec_id in execution_ids:
            assert exec_id in returned_ids, f"Execution {exec_id} should be in list"

        # Verify executions are ordered by started_at DESC (newest first)
        # The last execution we created should appear first in the list
        assert response_data['executions'][0]['id'] == execution_ids[-1], \
            "Executions should be ordered by started_at DESC (newest first)"

    async def test_list_executions_respects_limit_parameter(self, real_database, frontend_sio, sid):
        """
        Test that the limit parameter properly restricts returned executions.

        Verifies:
        - Limit parameter restricts number of returned executions
        - Most recent executions are returned when limit is applied
        """
        # Create a workflow
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000001'

        # Create test user first
        await self.create_test_user(real_database, user_id)

        await asyncio.sleep(0.1)
        await real_database.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        """, workflow_id, user_id, "Test Workflow", "Test Description", {}, {})

        # Execute workflow 5 times
        execution_ids = []
        for i in range(5):
            nodes = [
                {"id": f"node-{i}", "type": "automation-telegram", "position": {"x": 0, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": f"Limit test {i}", "chatId": f"limit-{i}"})},
            ]
            edges = []

            workflow_request = WorkflowExecuteRequest(
                event_name="workflow:execute",
                request_id=f"test-exec-limit-{i}",
                workflow_id=workflow_id,
                nodes=nodes,
                edges=edges
            )

            await send_event(frontend_sio, sid, workflow_request)
            await asyncio.sleep(0.3)

            # Get execution_id
            started_events = self.get_main_api_emitted_events("workflow:started")
            execution_id = started_events[-1][1]['execution_id']
            execution_ids.append(execution_id)

        # Request execution list with limit=2
        list_request = WorkflowExecutionListRequest(
            event_name="workflow:list_executions",
            request_id="test-list-limit",
            workflow_id=workflow_id,
            limit=2
        )

        await send_event(frontend_sio, sid, list_request)
        await asyncio.sleep(0.2)

        # Verify response
        response_events = self.get_main_api_emitted_events("response")
        matching_responses = [e for e in response_events if e[1].get('request_id') == 'test-list-limit']
        assert len(matching_responses) == 1

        response_data = matching_responses[0][1]['data']
        # Should return at most 2 executions (or fewer if database has fewer)
        # But we know we created 5, so should get exactly 2
        assert len(response_data['executions']) == 2, "Should respect limit parameter and return 2 executions"

        # Verify the 2 most recent executions are returned
        returned_ids = [exec['id'] for exec in response_data['executions']]
        # Last 2 executions we created should be in the response
        assert execution_ids[-1] in returned_ids, "Most recent execution should be included"
        assert execution_ids[-2] in returned_ids, "Second most recent execution should be included"

    async def test_list_executions_tracks_status_transitions(self, real_database, frontend_sio, sid):
        """
        Test that status transitions from running to completed are properly tracked.

        Verifies:
        - Execution starts with status='running' (or transitions to it)
        - After completion, status is updated to 'completed'
        - Listed execution shows final status
        """
        # Create a workflow
        workflow_id = str(uuid.uuid4())
        user_id = '00000000-0000-4000-8000-000000000001'

        # Create test user first
        await self.create_test_user(real_database, user_id)

        await asyncio.sleep(0.1)
        await real_database.execute("""
            INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        """, workflow_id, user_id, "Test Workflow", "Test Description", {}, {})

        # Execute workflow with multiple nodes to have some execution time
        nodes = [
            {"id": "node-1", "type": "automation-telegram", "position": {"x": 0, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Status test 1", "chatId": "status-1"})},
            {"id": "node-2", "type": "automation-telegram", "position": {"x": 100, "y": 0}, "config": self.wrap_node_data("automation-telegram", {"message": "Status test 2", "chatId": "status-2"})},
        ]
        edges = [
            {"id": "e1", "source": "node-1", "target": "node-2"},
        ]

        workflow_request = WorkflowExecuteRequest(
            event_name="workflow:execute",
            request_id="test-exec-status",
            workflow_id=workflow_id,
            nodes=nodes,
            edges=edges
        )

        await send_event(frontend_sio, sid, workflow_request)

        # Get execution_id from workflow:started event
        await asyncio.sleep(0.1)
        started_events = self.get_main_api_emitted_events("workflow:started")
        assert len(started_events) >= 1
        execution_id = started_events[-1][1]['execution_id']

        # Check database status immediately after start (might be 'running')
        initial_row = await real_database.fetchrow("""
            SELECT status FROM workflow_executions WHERE id = $1
        """, execution_id)

        # Wait for completion
        await asyncio.sleep(0.3)

        # Verify workflow completed
        complete_events = self.get_main_api_emitted_events("workflow:complete")
        assert len(complete_events) >= 1
        assert complete_events[-1][1]['success'] is True

        # Check database status after completion
        final_row = await real_database.fetchrow("""
            SELECT status FROM workflow_executions WHERE id = $1
        """, execution_id)

        assert final_row is not None
        assert final_row['status'] == 'completed', "Final status should be 'completed'"

        # Request execution list to verify status is reflected
        list_request = WorkflowExecutionListRequest(
            event_name="workflow:list_executions",
            request_id="test-list-status",
            workflow_id=workflow_id
        )

        await send_event(frontend_sio, sid, list_request)
        await asyncio.sleep(0.2)

        # Verify response shows completed status
        response_events = self.get_main_api_emitted_events("response")
        matching_responses = [e for e in response_events if e[1].get('request_id') == 'test-list-status']
        assert len(matching_responses) == 1

        response_data = matching_responses[0][1]['data']
        our_execution = None
        for execution in response_data['executions']:
            if execution['id'] == execution_id:
                our_execution = execution
                break

        assert our_execution is not None
        assert our_execution['status'] == 'completed', "Listed execution should show 'completed' status"
        assert our_execution['nodes_executed'] == 2, "Should have executed 2 nodes"


# ──────────────────────────────────────────────────────────────────────────
# Pagination + filtering + counts (added 2026-06-03)
#
# These tests poke the SQL directly through the real_db pool fixture rather
# than driving the full socket path, so we can seed deterministic rows for
# every combination (statuses, triggers, error text, cursor boundaries) and
# verify the handler's filter/cursor wiring without standing up workflows
# that actually run nodes.
# ──────────────────────────────────────────────────────────────────────────


def _make_handler_with_pool(real_database):
    """Build a WorkflowHandler whose get_pool() returns the test DB pool.

    Mirrors the wiring the live socket layer provides. We also stub the access
    check so the tests don't need to fully set up share rows; the focus here
    is on the SQL/handler interaction, not the access-control branch (covered
    elsewhere)."""
    from wss.handlers.workflow_handler import WorkflowHandler
    sio = MagicMock()
    sio.get_session = AsyncMock(return_value={'user_id': '00000000-0000-4000-8000-000000000001'})
    sio.emit = AsyncMock()
    h = WorkflowHandler(sio=sio)
    h.get_pool = AsyncMock(return_value=real_database.pool)
    return h, sio


def _captured_response_data(sio):
    """Last response event's data dict — the test asserts directly on it."""
    for call in reversed(sio.emit.call_args_list):
        args = call.args
        if len(args) >= 2 and args[0] == 'response':
            return args[1].get('data', {})
    return None


async def _seed_executions(real_database, workflow_id, user_id, rows):
    """Insert one row per spec into workflow_executions. rows is a list of
    (status, trigger_source, error, started_at_offset_seconds) — started_at
    is computed as NOW() - offset so the most-recent row has offset 0."""
    for status, trigger, error, offset in rows:
        await real_database.execute(
            "INSERT INTO workflow_executions "
            "(id, workflow_id, user_id, status, started_at, finished_at, nodes_executed, error, trigger_source) "
            "VALUES ($1, $2, $3, $4, NOW() - ($5 * INTERVAL '1 second'), NOW(), 1, $6, $7)",
            str(uuid.uuid4()), workflow_id, user_id, status, offset, error, trigger,
        )


@pytest.mark.asyncio
class TestWorkflowExecutionPaginationFiltersCounts(BaseHandlerTest):
    """Pagination, filtering, search, and the new counts endpoint."""

    def get_session_data(self, sid: str):
        return {'sid': sid, 'user_id': '00000000-0000-4000-8000-000000000001', 'email': 'workflow-test@example.com'}

    async def _setup_workflow(self, real_database):
        user_id = '00000000-0000-4000-8000-000000000001'
        await real_database.execute(
            "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
            user_id, 'workflow-test@example.com',
        )
        workflow_id = str(uuid.uuid4())
        await real_database.execute(
            "INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())",
            workflow_id, user_id, "Pagination Test", "", {}, {},
        )
        return workflow_id, user_id

    async def test_status_filter_returns_only_matching_statuses(self, real_database):
        workflow_id, user_id = await self._setup_workflow(real_database)
        await _seed_executions(real_database, workflow_id, user_id, [
            ('completed', 'manual', None, 30),
            ('error', 'manual', 'boom', 20),
            ('completed', 'cron', None, 10),
        ])
        handler, sio = _make_handler_with_pool(real_database)
        await handler.list_executions('sid', WorkflowExecutionListRequest(
            request_id='r-status', workflow_id=workflow_id, status=['error'],
        ))
        data = _captured_response_data(sio)
        assert data is not None and len(data['executions']) == 1
        assert data['executions'][0]['status'] == 'error'
        assert data['next_cursor_started_at'] is None  # page wasn't full

    async def test_trigger_filter_returns_only_matching_triggers(self, real_database):
        workflow_id, user_id = await self._setup_workflow(real_database)
        await _seed_executions(real_database, workflow_id, user_id, [
            ('completed', 'manual', None, 30),
            ('completed', 'manual', None, 20),
            ('completed', 'cron', None, 10),
        ])
        handler, sio = _make_handler_with_pool(real_database)
        await handler.list_executions('sid', WorkflowExecutionListRequest(
            request_id='r-trig', workflow_id=workflow_id, trigger_source=['cron'],
        ))
        data = _captured_response_data(sio)
        assert len(data['executions']) == 1
        assert data['executions'][0]['trigger_source'] == 'cron'

    async def test_search_matches_error_substring_case_insensitive(self, real_database):
        workflow_id, user_id = await self._setup_workflow(real_database)
        await _seed_executions(real_database, workflow_id, user_id, [
            ('error', 'manual', 'Connection TIMEOUT on slack', 30),
            ('error', 'manual', 'Rate limit hit', 20),
            ('completed', 'manual', None, 10),
        ])
        handler, sio = _make_handler_with_pool(real_database)
        await handler.list_executions('sid', WorkflowExecutionListRequest(
            request_id='r-search', workflow_id=workflow_id, search='timeout',
        ))
        data = _captured_response_data(sio)
        assert len(data['executions']) == 1
        assert 'TIMEOUT' in data['executions'][0]['error']

    async def test_cursor_pagination_returns_disjoint_pages(self, real_database):
        """Two consecutive pages cover the seeded rows exactly once each, in
        started_at-desc order. The cursor returned by page 1 is the started_at
        of page 1's last row."""
        workflow_id, user_id = await self._setup_workflow(real_database)
        # 7 rows, newest first. We page with limit=3 → expect 3 + 3 + 1.
        await _seed_executions(real_database, workflow_id, user_id, [
            ('completed', 'manual', None, i) for i in range(7)
        ])
        handler, sio = _make_handler_with_pool(real_database)

        await handler.list_executions('sid', WorkflowExecutionListRequest(
            request_id='r-p1', workflow_id=workflow_id, limit=3,
        ))
        page1 = _captured_response_data(sio)
        assert len(page1['executions']) == 3
        assert page1['next_cursor_started_at'] is not None
        assert page1['next_cursor_id'] is not None

        sio.emit.reset_mock()
        await handler.list_executions('sid', WorkflowExecutionListRequest(
            request_id='r-p2', workflow_id=workflow_id, limit=3,
            cursor_started_at=page1['next_cursor_started_at'],
            cursor_id=page1['next_cursor_id'],
        ))
        page2 = _captured_response_data(sio)
        assert len(page2['executions']) == 3
        # Disjoint sets
        ids1 = {e['id'] for e in page1['executions']}
        ids2 = {e['id'] for e in page2['executions']}
        assert ids1.isdisjoint(ids2), "Pages must not share rows"

        sio.emit.reset_mock()
        await handler.list_executions('sid', WorkflowExecutionListRequest(
            request_id='r-p3', workflow_id=workflow_id, limit=3,
            cursor_started_at=page2['next_cursor_started_at'],
            cursor_id=page2['next_cursor_id'],
        ))
        page3 = _captured_response_data(sio)
        assert len(page3['executions']) == 1
        assert page3['next_cursor_started_at'] is None, "Last page should not advance the cursor"

    async def test_counts_returns_total_and_groupings(self, real_database):
        workflow_id, user_id = await self._setup_workflow(real_database)
        await _seed_executions(real_database, workflow_id, user_id, [
            ('completed', 'manual', None, 50),
            ('completed', 'manual', None, 40),
            ('completed', 'cron', None, 30),
            ('error', 'webhook', 'boom', 20),
            ('running', 'manual', None, 10),
        ])
        handler, sio = _make_handler_with_pool(real_database)
        await handler.get_execution_counts('sid', WorkflowExecutionCountsRequest(
            request_id='r-counts', workflow_id=workflow_id,
        ))
        data = _captured_response_data(sio)
        assert data['total'] == 5
        assert data['by_status'] == {'completed': 3, 'error': 1, 'running': 1}
        assert data['by_trigger'] == {'manual': 3, 'cron': 1, 'webhook': 1}
