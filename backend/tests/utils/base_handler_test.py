"""
Simplified base class for testing Socket.IO handlers.

Provides minimal setup with paired frontend/server sockets and MockSocketIOProxy.
"""
import pytest
import pytest_asyncio
from typing import Dict, Any, List
# Install the asyncpg mock EAGERLY, before any test file's postgres_fixtures
# import. Real-DB test files import base_handler_test first and
# postgres_fixtures second, so the restore always wins there; a lazy first
# import (e.g. from teardown_method) would re-mock asyncpg MID-session and
# break later direct connects to the testcontainer.
import tests.mocks.mock_asyncpg  # noqa: F401
from tests.mocks.mock_socketio import MockSocketIO
from tests.mocks.mock_receiver import MockSocketIOProxy
from tests.mocks.mock_usage_tracker import configure_credits_remaining
from wss.receiver.event_routing import Handler


class BaseHandlerTest:
    """
    Minimal base class for testing Socket.IO handlers.

    Provides:
    - Paired frontend/server sockets
    - Configurable SocketIO proxy (MockSocketIOProxy by default)
    - Session with user_id for handlers

    Subclasses should use frontend_sio to emit events.

    To use a different proxy class, override get_proxy_class().
    """

    @pytest_asyncio.fixture
    async def sid(self):
        # Generate unique sid per test to ensure test isolation
        import uuid
        return f"test-sid-{uuid.uuid4()}"

    @pytest.fixture(autouse=True)
    def configure_mcp(self):
        """
        Configure MCP (Model Context Protocol) for tests.

        By default, MCP is DISABLED for tests to avoid connection errors.
        Override this fixture in subclasses to enable MCP for specific tests.
        """
        import os
        # Disable MCP by default for all tests
        os.environ["ENABLE_MCP"] = "false"
        yield
        # Clean up after test
        os.environ.pop("ENABLE_MCP", None)

    def get_proxy_class(self):
        """
        Get the SocketIO proxy class to use for testing.

        Override this method to use a different proxy class.
        Default is MockSocketIOProxy.

        Returns:
            The proxy class to instantiate
        """
        return MockSocketIOProxy

    @pytest_asyncio.fixture
    async def frontend_sio(self, sid):
        """
        Create frontend socket paired with a server socket that has MockSocketIOProxy.

        Returns the frontend socket that tests can use to emit events.
        The server socket is automatically connected to MockSocketIOProxy.

        Real-DB test classes list ``real_database`` BEFORE ``frontend_sio``
        in their test signatures so the native pool points at the
        testcontainer before handler setup runs.
        """
        # Clear credit-usage cache from previous tests
        from billing.usage_tracker import CREDIT_USAGE_CACHE
        CREDIT_USAGE_CACHE.clear()

        # Configure default credit balance — plenty of headroom so handler
        # tests aren't accidentally blocked by the credit-cap pre-flight.
        configure_credits_remaining(100.0)

        # Create paired sockets
        frontend_sio, self.main_api_sio = MockSocketIO.create_socketio_connection()

        # Get session data with the unique sid from fixture
        session_data = self.get_session_data(sid)

        # Create session on main_api_sio so handlers can get user_id, etc
        self.main_api_sio.create_session(**session_data)

        # Create proxy with the server socket using configurable proxy class
        proxy_class = self.get_proxy_class()
        self.proxy = proxy_class(sio=self.main_api_sio)

        self.handlers = self.proxy.handler_instances

        # Call setup_user to initialize handlers
        await self.proxy.setup_user(sid)

        return frontend_sio

    @pytest.fixture(autouse=True)
    def mock_execution_relay(self, monkeypatch):
        """
        Mock the ExecutionRelay so execution events routed through the WebSocket relay
        are captured in main_api_sio.emitted_events, just like direct Socket.IO emissions.
        Patches both the class (so execute_workflow creates the mock) and the context variable
        (so send_event routes through it).
        """
        test_self = self

        class MockExecutionRelay:
            connected = True
            connect_error = None
            def __init__(self, *args, **kwargs):
                pass
            def start(self_relay):
                pass
            async def send_event(self_relay, data):
                event_name = data.get('type', 'unknown')
                if hasattr(test_self, 'main_api_sio'):
                    test_self.main_api_sio.emitted_events.append((event_name, data, None))
            async def connect(self_relay, timeout=10.0):
                return True
            async def listen_for_stop(self_relay, cancellation_event, execution_task=None):
                pass
            async def close(self_relay):
                pass

        # Patch the class so execute_workflow creates a mock instead of a real relay
        monkeypatch.setattr("utils.execution_relay.ExecutionRelay", MockExecutionRelay)

        # Also set the context variable so send_event picks up the mock
        from wss.sender import _active_execution_relay
        _active_execution_relay.set(MockExecutionRelay())

    @pytest.fixture(autouse=True)
    def _bypass_failure_wrapper(self, monkeypatch):
        """Route public handler entrypoints to their ``_*_impl`` bodies so
        builder exceptions propagate to the test instead of being
        swallowed by the public wrapper's try/except (which converts them
        to a synthetic ``WorkflowCompleteEvent`` / ``ResponseEvent`` and
        returns normally — fine for prod UX, useless for pytest.raises).
        """
        from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
        from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

        monkeypatch.setattr(
            WorkflowExecutionHandler, "handle_execute",
            WorkflowExecutionHandler._handle_execute_impl,
        )
        monkeypatch.setattr(
            WorkflowExecutionHandler, "handle_resume",
            WorkflowExecutionHandler._handle_resume_impl,
        )
        monkeypatch.setattr(
            WorkflowBuilderHandler, "edit_workflow",
            WorkflowBuilderHandler._edit_workflow_impl,
        )
        monkeypatch.setattr(
            WorkflowBuilderHandler, "handle_input_response",
            WorkflowBuilderHandler._handle_input_response_impl,
        )

    def get_main_api_emitted_events(self, event_name=None):
        return self.main_api_sio.get_emitted_events(event_name)

    def reassemble_if_chunked(self, response_data):
        """Reassemble a chunked+compressed response payload from the captured
        ``__chunk__`` events (mirrors the frontend's chunk-receiver). Large
        responses (e.g. search_nodes over the full node list) exceed the 1 MB
        chunk threshold and come back as a ``{__chunked: True, ...}`` wrapper
        with the real payload split across ``__chunk__`` events. Returns the
        payload unchanged when it wasn't chunked."""
        if not (isinstance(response_data, dict) and response_data.get("__chunked")):
            return response_data
        import base64
        import json
        import zlib

        chunk_id = response_data.get("__chunk_id")
        total = response_data.get("__chunk_total", 0)
        by_index = {}
        for _name, data, *_ in self.get_main_api_emitted_events("__chunk__"):
            if isinstance(data, dict) and data.get("__chunk_id") == chunk_id:
                by_index[data["__chunk_index"]] = data["__chunk_data"]
        raw = b"".join(base64.b64decode(by_index[i]) for i in range(total))
        if response_data.get("__compressed"):
            raw = zlib.decompress(raw)
        return json.loads(raw.decode("utf-8"))

    async def wait_for_main_api_events(self, event_name, *, count=1, timeout=2.0):
        """Poll until ``count`` events named ``event_name`` have been emitted.

        Use instead of a fixed ``asyncio.sleep(...)`` after sending a request:
        fixed sleeps race the socket round-trip on a busy loop — the dominant
        full-suite flake shape. Returns the events seen at success or timeout;
        the caller's own assertions decide pass/fail.
        """
        import asyncio
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            events = self.get_main_api_emitted_events(event_name)
            if len(events) >= count:
                return events
            await asyncio.sleep(0.01)
        return self.get_main_api_emitted_events(event_name)
    
    def get_session_data(self, sid: str) -> Dict[str, Any]:
        """
        Get session data for the authenticated user.
        Override this to customize session information.

        Args:
            sid: Session ID to use for this test

        Returns:
            Dict with session data
        """
        return {
            'sid': sid,
            'user_id': 'uuid-test-user',
            'email': 'test@test.com',
        }
    
    def teardown_method(self):
        """
        Clean up after each test method to prevent state leakage.
        """
        # Clean up LiteLLM mocks
        from tests.mocks.mock_litellm import cleanup_litellm_mocks
        cleanup_litellm_mocks()
        
        # Clean up subprocess mocks
        from tests.mocks.mock_system import reset_subprocess_mocks
        reset_subprocess_mocks()
        
        # Clean up S3 mocks
        from tests.mocks.mock_boto3 import configure_mock_s3_responses
        configure_mock_s3_responses({})  # Reset to empty
        
        # Clean up database mocks
        from tests.mocks.mock_asyncpg import configure_mock_query_responses, clear_executed_queries
        configure_mock_query_responses({})  # Reset to empty
        clear_executed_queries()  # Clear query execution history

        # Clear subprocess call history (for git operations, etc.)
        from tests.mocks.mock_system import clear_subprocess_history
        clear_subprocess_history()

        # Note: PostgresStore cleanup is now handled globally in backend/tests/conftest.py
