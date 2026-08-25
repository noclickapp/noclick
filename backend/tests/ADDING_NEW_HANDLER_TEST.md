# Adding New Handler Tests

This guide explains how to add tests for new Socket.IO handlers in the NoClick backend, following established patterns and best practices.

## Overview

Handler tests in NoClick follow a consistent pattern using mock implementations to avoid external dependencies while preserving core logic. The testing architecture uses paired MockSocketIO instances to simulate bidirectional communication without actual network calls.

## Step-by-Step Guide

### 1. Create a Mock Handler Class

Create a mock version of your handler in `tests/mocks/mock_<handler_name>.py`:

```python
"""
Mock <HandlerName> for testing.

This mock handler extends the real <HandlerName> but patches
external dependencies to avoid actual [operations] while keeping core logic intact.
"""

# IMPORTANT: If your handler imports a module that requires authentication or 
# external resources at import time, you must mock it BEFORE importing the handler.
# Example: asyncpg or another optional SDK.
# from tests.mocks import mock_<dependency>

from wss.handlers.<handler_name> import <HandlerName>
from .<mock_dependency> import patch_<dependency>_components
import logging

logger = logging.getLogger(__name__)


class Mock<HandlerName>(<HandlerName>):
    """
    Mock version of <HandlerName> that patches external dependencies.
    
    This allows testing the full handler flow without [actual operations],
    while keeping all other logic intact.
    """
    
    def __init__(self, sio, **kwargs):
        """Initialize with patches applied."""
        super().__init__(sio, **kwargs)
        self._setup_patches()
    
    def _setup_patches(self):
        """Apply patches with default test-friendly configuration."""
        patch_<dependency>_components()
        logger.debug("<HandlerName> patches applied")
```

#### Important: Import-Time Mocking Pattern

Some dependencies need to be mocked **before** importing the handler to prevent import-time errors. This pattern is used when:
- The dependency requires authentication at import
- The dependency tries to connect to external services at import (e.g., database libraries)
- The dependency performs system checks at import

The mock module typically sets up a fake module in `sys.modules`:
```python
# In mock_external_service.py or mock_asyncpg.py
import sys

# Create mock module to prevent import errors
mock_module = MagicMock()
mock_module.SomeClass = MagicMock()
sys.modules['external_module'] = mock_module
```

This ensures the handler can import successfully without trying to connect to real services.

### 2. Create Mock Dependencies (if needed)

If your handler has external dependencies not already mocked, create a mock module in `tests/mocks/mock_<dependency>.py`:

```python
"""
Mock implementations for <Dependency> components used in testing.

This module provides test-friendly mocks for <Dependency> operations
to avoid actual [operations] during testing.
"""

import sys
import logging
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

logger = logging.getLogger(__name__)

# IMPORTANT: If the dependency is imported at module level and requires external resources,
# create a mock module in sys.modules BEFORE any other imports
# Example for a module that requires authentication or external connection:
mock_<dependency> = MagicMock()
mock_<dependency>.SomeClass = MagicMock()
mock_<dependency>.some_function = AsyncMock()
sys.modules['<dependency>'] = mock_<dependency>

# Global state for configurable responses
_mock_<operation>_responses: Dict[str, Any] = {}


def configure_mock_<operation>_responses(responses: Dict[str, Any] = None):
    """
    Configure <operation> responses for testing.
    
    Args:
        responses: Dict mapping patterns to response data
    """
    global _mock_<operation>_responses
    _mock_<operation>_responses = responses or {}
    logger.debug(f"Mock <operation> responses configured: {len(_mock_<operation>_responses)} patterns")


class Mock<Component>:
    """Mock implementation of <dependency>.<Component>."""
    
    # Implement mock methods matching the real component's interface
    async def <method>(self, *args, **kwargs):
        """Mock <method> implementation."""
        # Check configured responses
        for pattern, response in _mock_<operation>_responses.items():
            if pattern in str(args):
                return response
        
        # Default response
        return <default_value>


def patch_<dependency>_components():
    """
    Patch <Dependency> components with test-friendly mocks.
    
    Call this function in test setup to replace <Dependency> components
    with mocks that don't require actual [operations].
    """
    import <dependency_module>
    
    # Apply patches
    <dependency_module>.<Component> = Mock<Component>
    
    logger.debug("<Dependency> components patched for testing")
```

**Real Examples:**

**Generic import-time module pattern:**
```python
import sys
from unittest.mock import MagicMock

# Create a fake third-party module before importing the subject under test.
mock_external_service = MagicMock()
mock_external_service.Client = MagicMock()
sys.modules['external_service'] = mock_external_service
```

**mock_asyncpg.py pattern:**
```python
import sys
from unittest.mock import MagicMock, AsyncMock

# Create mock asyncpg module to prevent connection attempts.
# create_pool routes to a faithful MockAsyncpgPool double so
# init_native_pool() works transparently under the mock.
mock_asyncpg = MagicMock()
mock_asyncpg.create_pool = AsyncMock(side_effect=mock_create_pool)
mock_asyncpg.connect = AsyncMock(side_effect=_mock_connect)
sys.modules['asyncpg'] = mock_asyncpg
```

This `sys.modules` pattern is essential when:
- The module tries to authenticate or connect when imported
- The module is imported at the top level of the handler file
- You get import errors when trying to import the handler for testing

### 3. Register Mock Handler in MockSocketIOProxy

Update `tests/mocks/mock_receiver.py` to include your mock handler:

```python
def _create_handler_instances(self):
    """
    Create partially mocked handler instances for the current environment.
    """
    from tests.mocks.mock_agent_handler import MockAgentHandler
    from tests.mocks.mock_<handler_name> import Mock<HandlerName>  # Add this

    agent_handler = MockAgentHandler(self.sio)
    <handler_var> = Mock<HandlerName>(self.sio)  # Add this

    return {
        Handler.AGENT: agent_handler,
        Handler.<HANDLER_ENUM>: <handler_var>,  # Add this
    }
```

### 4. Create Test File

Create your test file in `tests/test_<handler_name>.py`:

```python
"""
Test suite for <HandlerName> with [operations].

Tests [functionality] with mocked [dependencies].
"""

import pytest
from unittest.mock import AsyncMock, patch

from tests.utils.base_handler_test import BaseHandlerTest
from tests.mocks.mock_<dependency> import configure_mock_<operation>_responses
from wss.receiver.client_events import <EventClasses>
from wss.sender import send_event


class Test<HandlerName>(BaseHandlerTest):
    """Test <HandlerName> with mocked [operations]."""
    
    @pytest.fixture(autouse=True)
    async def setup_mocks(self):
        """Set up test-specific mocks."""
        # Configure any additional mocks needed
        with patch("module.to.patch") as mock_obj:
            self.mock_obj = mock_obj
            yield
    
    @pytest.mark.asyncio
    async def test_<operation>_success(self, frontend_sio, sid):
        """Test successful [operation]."""
        # Configure mock responses
        configure_mock_<operation>_responses({
            "pattern": expected_response
        })
        
        # Send event
        request = <EventClass>(
            event_name="<event:name>",
            request_id="test-123",
            # ... other fields
        )
        await send_event(frontend_sio, sid, request)
        
        # Check response
        events = self.get_main_api_emitted_events("response")
        assert len(events) == 1
        
        response_data = events[0][1]['data']
        # Assert on response data
        assert 'expected_field' in response_data
    
    @pytest.mark.asyncio
    async def test_<operation>_error(self, frontend_sio, sid):
        """Test error handling for [operation]."""
        # Configure mock to fail
        configure_mock_<operation>_responses({
            "pattern": Exception("Mock error")
        })
        
        # Send event
        request = <EventClass>(
            event_name="<event:name>",
            request_id="test-456"
        )
        await send_event(frontend_sio, sid, request)
        
        # Check error response
        events = self.get_main_api_emitted_events("response")
        assert len(events) == 1
        
        response = events[0][1]
        assert 'error' in response
        assert 'Mock error' in response['error']
```

## Integration Tests with Real PostgreSQL

For handlers that interact with databases via DatabasePoolMixin, add integration tests that verify actual database behavior (schema, constraints, SQL queries).

### JSONB Handling

JSONB columns are automatically converted to/from Python dicts via `setup_asyncpg_codecs()` (registered in both production and tests). No manual `json.dumps()/json.loads()` needed:

```python
# ✅ GOOD: Pass dicts directly, codec handles encoding
await conn.execute(
    "INSERT INTO table (jsonb_col) VALUES ($1)",
    {"key": "value"}  # Codec automatically encodes to JSONB
)

# ✅ GOOD: Receive dicts automatically, codec handles decoding
row = await conn.fetchrow("SELECT jsonb_col FROM table")
assert isinstance(row['jsonb_col'], dict)  # Already a dict!

# ❌ BAD: Don't manually stringify
await conn.execute(
    "INSERT INTO table (jsonb_col) VALUES ($1::jsonb)",
    json.dumps({"key": "value"})  # Breaks codec, returns strings on fetch
)
```

### Quick Setup

```python
# postgres_container/postgres_db are registered once by tests/conftest.py.
from tests.fixtures.real_db_fixture import real_database, test_user_id  # noqa: F401

@pytest.mark.asyncio
class TestMyHandlerIntegration(BaseHandlerTest):

    # List real_database BEFORE frontend_sio so the native pool points at
    # the testcontainer before handler setup runs.
    async def test_with_real_db(self, real_database, frontend_sio, sid):
        """Test with real database."""
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.5)

        # Verify directly in database (async facade over the native pool)
        result = await real_database.fetchrow("SELECT * FROM table WHERE id = $1", id)
        assert result is not None
```

### How It Works

1. The `real_database` fixture (tests/fixtures/real_db_fixture.py) sets
   `POSTGRES_POOLER_URL` to the session-scoped Postgres testcontainer
   (migrations + seed applied), closes any stale native pool, and inits a
   fresh one on the test's event loop.
2. Handlers resolve the pool at call time (`get_native_pool()` /
   `self.get_pool()`), so everything they run lands on the container DB —
   no per-handler patching.
3. The yielded `RealDatabase` exposes ASYNC `execute`/`fetch`/`fetchrow`/
   `fetchval` over that same pool for test setup/verification, plus
   `conn_params`/`url` for helpers that need a direct asyncpg connection.

For unit tests (no `real_database`), the autouse `ensure_native_db_pool`
fixture in `tests/conftest.py` inits the pool against local Postgres — or,
when `tests/mocks/mock_asyncpg.py` has replaced `sys.modules['asyncpg']`,
against the in-memory `MockAsyncpgPool`. To stub the pool for a specific
test, patch the seam directly with `MockNativePool`:

```python
from tests.mocks.mock_asyncpg import MockNativePool

pool = MockNativePool({"FROM my_table": {"id": "row-1"}})
with patch("utils.database_pool.get_native_pool", return_value=pool):
    ...
assert pool.execute.await_count == 1  # per-verb AsyncMocks
```

See `tests/test_share_handler.py` for complete real-database examples.

## Best Practices and Patterns

### 1. Test Full Event Routing (Strong Preference)

- **ALWAYS PREFER**: Test the complete event flow through the registered
  receiver and target handler.
- **DO**: Send the public socket event instead of calling a handler's internals
  directly.
- **WHY**: This tests the real routing, validation, acknowledgement, and error
  behavior seen by a client.
- **EXAMPLE**: When testing a workflow update, send the update event and assert
  its acknowledgement rather than mocking the receiver.

```python
# GOOD: exercise the public event boundary
async def test_update_workflow_success(self, frontend_sio, sid):
    acknowledgement = await send_event(frontend_sio, sid, update_request)
    assert acknowledgement["success"] is True

# AVOID: bypassing the event boundary
async def test_update_workflow_success(self, frontend_sio, sid):
    self.mock_receiver.route_event.return_value = {"success": True}
```

### 2. Mock at the Right Level

- **DO**: Mock external dependencies (databases, APIs, file systems, processes)
- **DON'T**: Mock the handler's core logic or inter-handler communication
- **RATIONALE**: We want to test the handler's actual logic AND communication patterns while avoiding slow/flaky external operations

### 3. Use Configuration Functions

Always provide configuration functions for mock responses:

```python
def configure_mock_responses(responses: Dict[str, Any] = None):
    """Configure responses for different test scenarios."""
    global _mock_responses
    _mock_responses = responses or {}
```

This allows tests to easily set up different scenarios without modifying the mock itself.

### 4. Inherit from BaseHandlerTest

All handler tests should inherit from `BaseHandlerTest`:

```python
class TestMyHandler(BaseHandlerTest):
    """Test MyHandler functionality."""
```

This provides:
- Paired frontend/server sockets
- MockSocketIOProxy setup
- Session management with user_id
- Helper methods for checking emitted events

### 5. Use Fixtures for Test-Specific Setup

Use pytest fixtures for test-specific mock configuration:

```python
@pytest.fixture(autouse=True)
async def setup_mocks(self):
    """Set up mocks specific to this test class."""
    with patch("module.to.patch") as mock:
        self.mock = mock
        yield
```

### 6. Test Event Flow

Always test the complete event flow:

1. Configure mock responses
2. Send event via `frontend_sio`
3. Check responses via `get_main_api_emitted_events()`
4. Verify any side effects (e.g., other handler calls)

### 7. Test Both Success and Failure Cases

For each operation, test:
- **Success case**: Normal operation with expected data
- **Failure case**: Error handling (network errors, validation errors, etc.)
- **Edge cases**: Empty data, missing fields, unauthorized access
- **Rollback scenarios**: Operations that should undo on failure

### 8. Use Realistic Test Data

Create test data that matches the application's real schemas:

```python
from datetime import datetime, timezone

test_data = {
    'id': 'test-id-123',
    'created_at': datetime.now(timezone.utc),
    'updated_at': datetime.now(timezone.utc),
    # ... other fields matching actual schema
}
```

### 9. Test Authentication and Authorization

Always test that unauthenticated or unauthorized users are properly rejected:

```python
@pytest.mark.asyncio
async def test_unauthorized_access(self, frontend_sio, sid):
    """Test that unauthorized users cannot perform operations."""
    # Create socket without user_id or with wrong user_id
    # Verify error response
```

## Common Patterns

### Pattern 1: Database Operations

For handlers that interact with databases:

```python
# In mock file
class MockAsyncpgConnection:
    async def fetch(self, query: str, *args):
        # Return configured responses based on query pattern
        
# In test file
configure_mock_query_responses({
    "SELECT * FROM table": [{"id": 1, "name": "test"}]
})
```

### Pattern 2: File System Operations

For handlers that interact with files:

```python
# Use mock_system.py patterns
from tests.mocks.mock_system import patch_all_system_operations
patch_all_system_operations()
```

## File Structure

```
backend/tests/
├── mocks/
│   ├── mock_<handler_name>.py      # Mock handler implementation
│   ├── mock_<dependency>.py        # Mock external dependency
│   └── mock_receiver.py            # Updated with new handler
├── utils/
│   └── base_handler_test.py        # Base test class
└── test_<handler_name>.py          # Test file
```

## Running Tests

```bash
# Run specific test file
pytest backend/tests/test_<handler_name>.py

# Run specific test
pytest backend/tests/test_<handler_name>.py::Test<HandlerName>::test_<operation>_success

# Run with verbose output
pytest -xvs backend/tests/test_<handler_name>.py

# Run with coverage
pytest --cov=wss.handlers.<handler_name> backend/tests/test_<handler_name>.py
```

## Debugging Tips

1. **Use logging**: Add `logger.debug()` statements in mocks to trace execution
2. **Check event order**: Use `print(self.get_main_api_emitted_events())` to see all events
3. **Inspect mock calls**: Use `mock.call_args_list` to see all calls to a mock
4. **Test in isolation**: Run single tests with `-k test_name` to focus on specific issues
5. **Check fixture order**: Ensure fixtures are applied in the correct order with `autouse=True`

## Checklist for New Handler Tests

- [ ] Created mock handler class extending real handler
- [ ] Created mock dependencies (if needed)
- [ ] Added mock handler to `mock_receiver.py`
- [ ] Created test file inheriting from `BaseHandlerTest`
- [ ] Tested success cases for all operations
- [ ] Tested error cases and edge cases
- [ ] Tested authentication/authorization
- [ ] Tested rollback scenarios (if applicable)
- [ ] Used configuration functions for mock responses
- [ ] Followed naming conventions (`Mock<Name>`, `Test<Name>`, `test_<operation>_<scenario>`)
- [ ] Added docstrings to all classes and test methods
- [ ] Tests pass consistently without flakiness
