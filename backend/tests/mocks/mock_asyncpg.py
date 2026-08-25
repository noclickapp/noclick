"""
Mock implementations for asyncpg components used in testing.

Installing this module replaces ``sys.modules['asyncpg']`` with a mock module
so unit tests never open real connections: ``utils.database_pool.
init_native_pool()``'s ``asyncpg.create_pool(...)`` call routes to
``mock_create_pool`` and yields a ``MockAsyncpgPool`` — a faithful double of
the native pool surface (pool-level verbs, ``acquire()`` context manager,
``conn.transaction()``).

For tests that patch the pool seam directly
(``patch("utils.database_pool.get_native_pool", return_value=pool)``), use
``MockNativePool`` — its verbs are per-instance ``AsyncMock``s so call
assertions (``pool.execute.await_args_list`` etc.) work out of the box.
"""

import sys
import logging
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

logger = logging.getLogger(__name__)

# Set DB URL env vars before any handler imports.
# POSTGRES_POOLER_URL is what backend runtime code reads via
# get_runtime_database_url(); POSTGRES_URL is what migrations / one-shot
# scripts and a few legacy tests still read directly.
#
# Note: since the 2026-07-01 native-pool refactor, `conftest.py`'s autouse
# fixture always overrides these URLs to a real local Postgres (or the
# per-test testcontainer via `real_database`). But we still set benign
# defaults here to catch the edge case where mock_asyncpg is imported for
# its side-effect (replacing sys.modules['asyncpg']) before conftest runs —
# without a URL asyncpg.create_pool raises on a URL parse error before the
# mock intercept fires.
import os
if "POSTGRES_POOLER_URL" not in os.environ:
    os.environ["POSTGRES_POOLER_URL"] = "postgresql://mock_user:mock_pass@localhost/mock_db"
if "POSTGRES_URL" not in os.environ:
    os.environ["POSTGRES_URL"] = "postgresql://mock_user:mock_pass@localhost/mock_db"

# Import the REAL asyncpg ONCE, before installing the mock, and reuse its
# exception classes. `except` matches on class IDENTITY, not name: aliasing
# these to bare Exception (or letting postgres_fixtures delete + re-import
# asyncpg into a second module object) makes `except asyncpg.UniqueViolationError`
# silently miss across modules that bound asyncpg at different collection
# times — an order-dependent suite flake (bit test_email_trigger when a new
# node import moved email_reservation_manager's binding earlier, 2026-06-11).
import asyncpg as _real_asyncpg
import asyncpg.exceptions as _real_exceptions

# Global state for configurable query responses
_mock_query_responses: Dict[str, Any] = {}
_mock_pool_available = True
_executed_queries: list[dict] = []


def configure_mock_pool_availability(available: bool = True):
    """
    Configure whether the database pool should appear available.

    Args:
        available: Whether pool creation should succeed
    """
    global _mock_pool_available
    _mock_pool_available = available
    logger.debug(f"Mock pool availability set to: {available}")


def configure_mock_query_responses(responses: Dict[str, Any] = None):
    """
    Configure database query responses for testing.

    Args:
        responses: Dict mapping query patterns to response data
                  e.g., {"SELECT * FROM apps": [{"id": "1", "title": "App"}]}
    """
    global _mock_query_responses
    _mock_query_responses = responses or {}
    logger.debug(f"Mock query responses configured: {len(_mock_query_responses)} patterns")


def get_executed_queries() -> list[dict]:
    """Return recorded execute() calls."""
    return list(_executed_queries)


def clear_executed_queries() -> None:
    """Clear recorded execute() calls."""
    _executed_queries.clear()


def _match_response(responses: Dict[str, Any], query: str):
    """First-substring-match lookup, raising configured Exceptions."""
    for pattern, response in responses.items():
        if pattern in query:
            if isinstance(response, Exception):
                raise response
            return response
    return None


class MockAsyncpgRecord:
    """Mock implementation of asyncpg.Record."""

    def __init__(self, data: Dict[str, Any]):
        self._data = data

    def __getitem__(self, key):
        return self._data.get(key)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __contains__(self, key):
        return key in self._data

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()


class MockAsyncpgTransaction:
    """Async CM returned by ``conn.transaction()`` (matches asyncpg's shape)."""

    def __init__(self, conn: "MockAsyncpgConnection"):
        self._conn = conn

    async def __aenter__(self):
        self._conn._transaction_active = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._conn._transaction_active = False
        return False


class _MockAcquireContext:
    """Dedicated per-acquire async CM so nested/concurrent acquires don't
    share ``__aexit__`` state on the pool object."""

    def __init__(self, conn: "MockAsyncpgConnection"):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


class MockAsyncpgConnection:
    """Mock implementation of asyncpg.Connection.

    Responses come from the module-global registry set via
    ``configure_mock_query_responses``; ``execute``/``executemany`` calls are
    recorded in the global ``_executed_queries`` list.
    """

    def __init__(self):
        self.closed = False
        self._transaction_active = False

    async def fetch(self, query: str, *args, timeout: Optional[float] = None):
        response = _match_response(_mock_query_responses, query)
        if isinstance(response, list):
            return [MockAsyncpgRecord(row) if isinstance(row, dict) else row
                    for row in response]
        return []

    async def fetchrow(self, query: str, *args, timeout: Optional[float] = None):
        response = _match_response(_mock_query_responses, query)
        if isinstance(response, dict):
            return MockAsyncpgRecord(response)
        if isinstance(response, list) and response:
            row = response[0]
            return MockAsyncpgRecord(row) if isinstance(row, dict) else row
        return None

    async def fetchval(self, query: str, *args, timeout: Optional[float] = None):
        response = _match_response(_mock_query_responses, query)
        if isinstance(response, (str, int, float, bool)):
            return response
        if isinstance(response, dict):
            return next(iter(response.values())) if response else None
        return None

    async def execute(self, query: str, *args, timeout: Optional[float] = None):
        logger.debug(f"Mock execute: {query[:50]}... with args: {args}")
        _executed_queries.append({"query": query, "args": args})
        response = _match_response(_mock_query_responses, query)
        return response if isinstance(response, str) else "EXECUTE 1"

    async def executemany(self, command: str, args, timeout: Optional[float] = None):
        arg_list = list(args)
        logger.debug(f"Mock executemany: {command[:50]}... with {len(arg_list)} arg tuples")
        _executed_queries.append({"query": command, "args": arg_list})
        _match_response(_mock_query_responses, command)  # raise if configured
        return None

    def transaction(self):
        """SYNC method returning an async CM — matches asyncpg, so
        ``async with conn.transaction():`` works."""
        return MockAsyncpgTransaction(self)

    async def close(self):
        self.closed = True


class MockAsyncpgPool:
    """Mock implementation of asyncpg.Pool — the native-pool double.

    Supports both access styles production code uses:
    - ``async with pool.acquire() as conn:`` (real per-acquire CM)
    - pool-level verbs (``fetch``/``fetchrow``/``fetchval``/``execute``/
      ``executemany``), delegating to the shared connection.
    """

    def __init__(self):
        self.closed = False
        self._conn = MockAsyncpgConnection()

    def acquire(self, *, timeout: Optional[float] = None):
        """Return a dedicated context manager that yields the connection."""
        return _MockAcquireContext(self._conn)

    async def fetch(self, query: str, *args, timeout: Optional[float] = None):
        return await self._conn.fetch(query, *args, timeout=timeout)

    async def fetchrow(self, query: str, *args, timeout: Optional[float] = None):
        return await self._conn.fetchrow(query, *args, timeout=timeout)

    async def fetchval(self, query: str, *args, timeout: Optional[float] = None):
        return await self._conn.fetchval(query, *args, timeout=timeout)

    async def execute(self, query: str, *args, timeout: Optional[float] = None):
        return await self._conn.execute(query, *args, timeout=timeout)

    async def executemany(self, command: str, args, timeout: Optional[float] = None):
        return await self._conn.executemany(command, args, timeout=timeout)

    async def close(self):
        self.closed = True
        logger.debug("Mock pool closed")

    def is_closing(self) -> bool:
        return self.closed

    def get_size(self) -> int:
        return 1

    def get_idle_size(self) -> int:
        return 1

    def get_max_size(self) -> int:
        return 1


async def mock_create_pool(*args, **kwargs):
    """Mock asyncpg.create_pool function."""
    if not _mock_pool_available:
        raise Exception("Mock database connection failed")

    logger.debug(f"Mock pool created with args: {args[:1]}...")  # Log just the connection string start
    return MockAsyncpgPool()


async def _mock_connect(*args, **kwargs):
    """Mock asyncpg.connect — yields a fresh mock connection."""
    if not _mock_pool_available:
        raise Exception("Mock database connection failed")
    return MockAsyncpgConnection()


# ── Patch-in double for utils.database_pool.get_native_pool ───────────────


class MockNativePoolConnection:
    """Connection double whose verbs ARE the owning pool's AsyncMocks, so a
    single assertion surface covers both ``pool.execute(...)`` and
    ``async with pool.acquire() as conn: conn.execute(...)``."""

    def __init__(self, pool: "MockNativePool"):
        self.fetch = pool.fetch
        self.fetchrow = pool.fetchrow
        self.fetchval = pool.fetchval
        self.execute = pool.execute
        self.executemany = pool.executemany

    def transaction(self):
        return MockAsyncpgTransaction(MockAsyncpgConnection())


class MockNativePool:
    """Constructible native-pool double for direct seam patching:

        pool = MockNativePool({"FROM workflows": {"id": "w1"}})
        with patch("utils.database_pool.get_native_pool", return_value=pool):
            ...

    Every verb is a per-instance ``AsyncMock`` (assert via
    ``pool.fetchrow.await_args_list`` / ``pool.conn.execute.await_args_list``);
    responses use the same substring-pattern semantics as
    ``configure_mock_query_responses`` but are instance-scoped.
    ``execute`` calls are also recorded in ``pool.executed_queries``.
    """

    def __init__(self, responses: Optional[Dict[str, Any]] = None):
        self.responses: Dict[str, Any] = dict(responses or {})
        self.executed_queries: list[dict] = []
        self.fetch = AsyncMock(side_effect=self._fetch)
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)
        self.fetchval = AsyncMock(side_effect=self._fetchval)
        self.execute = AsyncMock(side_effect=self._execute)
        self.executemany = AsyncMock(side_effect=self._executemany)
        self.conn = MockNativePoolConnection(self)

    def acquire(self, *, timeout: Optional[float] = None):
        return _MockAcquireContext(self.conn)

    async def _fetch(self, query: str, *args, timeout: Optional[float] = None):
        response = _match_response(self.responses, query)
        if isinstance(response, list):
            return [MockAsyncpgRecord(row) if isinstance(row, dict) else row
                    for row in response]
        return []

    async def _fetchrow(self, query: str, *args, timeout: Optional[float] = None):
        response = _match_response(self.responses, query)
        if isinstance(response, dict):
            return MockAsyncpgRecord(response)
        if isinstance(response, list) and response:
            row = response[0]
            return MockAsyncpgRecord(row) if isinstance(row, dict) else row
        return None

    async def _fetchval(self, query: str, *args, timeout: Optional[float] = None):
        response = _match_response(self.responses, query)
        if isinstance(response, (str, int, float, bool)):
            return response
        if isinstance(response, dict):
            return next(iter(response.values())) if response else None
        return None

    async def _execute(self, query: str, *args, timeout: Optional[float] = None):
        self.executed_queries.append({"query": query, "args": args})
        response = _match_response(self.responses, query)
        return response if isinstance(response, str) else "EXECUTE 1"

    async def _executemany(self, command: str, args, timeout: Optional[float] = None):
        self.executed_queries.append({"query": command, "args": list(args)})
        _match_response(self.responses, command)  # raise if configured
        return None

    async def close(self):
        pass


# ── sys.modules install ────────────────────────────────────────────────────

# Create mock asyncpg module to prevent real connections during unit tests
mock_asyncpg = MagicMock()
mock_asyncpg.create_pool = AsyncMock(side_effect=mock_create_pool)
mock_asyncpg.connect = AsyncMock(side_effect=_mock_connect)
mock_asyncpg.Record = MockAsyncpgRecord

# Mock exceptions submodule carrying the REAL exception classes.
mock_exceptions = MagicMock()
mock_exceptions.PostgresError = _real_exceptions.PostgresError
mock_exceptions.UniqueViolationError = _real_exceptions.UniqueViolationError
mock_exceptions.ForeignKeyViolationError = _real_exceptions.ForeignKeyViolationError
mock_exceptions.IntegrityConstraintViolationError = _real_exceptions.IntegrityConstraintViolationError
mock_asyncpg.exceptions = mock_exceptions

# Real asyncpg re-exports these at the package top level too (e.g.
# asyncpg.UniqueViolationError), so mirror them with the same real classes.
mock_asyncpg.PostgresError = _real_exceptions.PostgresError
mock_asyncpg.UniqueViolationError = _real_exceptions.UniqueViolationError
mock_asyncpg.ForeignKeyViolationError = _real_exceptions.ForeignKeyViolationError
mock_asyncpg.IntegrityConstraintViolationError = _real_exceptions.IntegrityConstraintViolationError

# Stash for postgres_fixtures to RESTORE (never delete + re-import: a re-import
# mints fresh exception classes and breaks identity for already-bound modules).
mock_asyncpg.__real_asyncpg__ = _real_asyncpg

sys.modules['asyncpg'] = mock_asyncpg
sys.modules['asyncpg.exceptions'] = mock_exceptions
