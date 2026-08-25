"""
Global pytest configuration and fixtures for all tests.

This module provides fixtures that run for ALL tests to ensure proper cleanup
and test isolation, regardless of which base class they inherit from.
"""
# Eager import: authlib's AsyncOAuth2Client subclasses httpx.AsyncClient at
# module load time. Several test files (e.g. test_workflow_execution_handler)
# autouse-patch httpx.AsyncClient before tests run; if mcp_adapter (or anything
# else that pulls in authlib's httpx OAuth client) imports it for the first
# time *while* the patch is active, the subclass line bombs with "metaclass
# conflict" because MagicMock's metaclass isn't compatible. Importing it here
# locks the class definition in before any fixture has a chance to monkeypatch
# httpx, so the patched test path becomes a no-op for the already-defined class.
import authlib.integrations.httpx_client.oauth2_client  # noqa: F401

import pytest
import pytest_asyncio
import asyncio
import logging
import os
import sys
from cryptography.fernet import Fernet

pytest_plugins = ("tests.fixtures.postgres_fixtures",)

logger = logging.getLogger(__name__)

# Modules that build absolute URLs at import time need deterministic,
# non-routable endpoints during collection. Individual tests can override them.
os.environ.setdefault("FRONTEND_URL", "https://frontend.example.test")
os.environ.setdefault("MCP_BASE_URL", "https://api.example.test")
os.environ.setdefault("PUBLIC_API_URL", "https://api.example.test")
# Inbound email is off until an operator names a domain, so the address
# validator refuses everything without this — including the inputs its own
# tests call valid.
os.environ.setdefault("INBOUND_EMAIL_DOMAIN", "inbound.example.test")

_pool_init_warned = False
_postgres_test_module_paths: set[str] = set()


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    """Keep each container-bound test family on one xdist worker.

    A session-scoped fixture is session-scoped per worker, so unconstrained
    distribution starts one pgvector container in every worker that happens to
    receive a database-backed test. Grouping the complete fixture closure
    preserves parallelism for unit tests while limiting the suite to one
    Postgres test container.
    """
    _postgres_test_module_paths.update(
        str(item.path)
        for item in items
        if "postgres_container" in item.fixturenames
    )

    for item in items:
        # The reset fixture is module-scoped, so every item from a DB-backed
        # module must land on the Postgres worker (including pure helper tests
        # in the same file). Otherwise each worker would instantiate the
        # module-autouse fixture and start its own container.
        if str(item.path) in _postgres_test_module_paths:
            item.add_marker(pytest.mark.xdist_group(name="postgres"))
        elif item.path.name == "test_mock_server.py":
            # This module intentionally exercises fixed ports (8080/8081 and
            # 8443/8444). Its tests cannot safely run on separate workers.
            item.add_marker(pytest.mark.xdist_group(name="mock-server"))


@pytest.fixture(scope="module", autouse=True)
def reset_shared_postgres_between_modules(request):
    """Reset the one shared Postgres container before each DB-backed module."""
    if str(request.node.path) not in _postgres_test_module_paths:
        yield
        return

    postgres_container = request.getfixturevalue("postgres_container")
    from tests.fixtures.postgres_fixtures import reset_database_data

    asyncio.run(reset_database_data(postgres_container))
    yield


@pytest.fixture(autouse=True, scope='session')
def setup_encryption_key():
    """
    Ensure encryption key is set for all tests.

    This fixture runs once per test session and sets up a test encryption key
    if one is not already configured. This prevents tests from failing due to
    the hard requirement for CREDENTIALS_ENCRYPTION_KEY in production code.
    """
    if not os.environ.get('CREDENTIALS_ENCRYPTION_KEY'):
        test_key = Fernet.generate_key()
        os.environ['CREDENTIALS_ENCRYPTION_KEY'] = test_key.decode()
    yield


@pytest_asyncio.fixture(autouse=True)
async def ensure_native_db_pool():
    """Ensure the native asyncpg pool is initialized on the test's event loop.

    In production the pool is created in ``app_lifespan`` startup. Tests
    never run the lifespan, so any handler that hits ``get_pool()`` would
    trip the fail-fast "pool not initialized" guard.
    pytest-asyncio uses a per-test event loop, so the pool must be bound to
    THIS test's loop. If a prior test left a pool on a stale loop, close it
    before initing a fresh one on ``asyncio.get_running_loop()``.
    """
    # tests/mocks/mock_asyncpg.py sets a "mock_user:mock_pass@localhost"
    # stub URL at import time so URL parsing never precedes the sys.modules
    # asyncpg mock. The native pool would try to actually connect to it, so
    # override with the real local Postgres unless the env already set one.
    _url = os.environ.get("POSTGRES_POOLER_URL", "")
    if (not _url) or "mock_user:mock_pass" in _url:
        os.environ["POSTGRES_POOLER_URL"] = (
            "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
        )
    import asyncio as _asyncio
    from utils import database_pool as _db
    current = _asyncio.get_running_loop()
    if _db._native_pool_loop is not None and _db._native_pool_loop is not current:
        try:
            await _db.close_native_pool()
        except Exception as e:
            logger.debug("[test] close_native_pool on stale loop failed: %s", e)
    if _db._native_pool is None:
        try:
            await _db.init_native_pool()
        except Exception as e:
            # Pure-unit tests with no DB don't need the pool; anything that
            # does will fail loudly via get_native_pool(). Warn ONCE so a
            # misconfigured URL is diagnosable from the log, not just from a
            # downstream "pool not initialized" error.
            global _pool_init_warned
            if not _pool_init_warned:
                logger.warning("[test] init_native_pool failed (%s) — DB-backed tests will fail fast", e)
                _pool_init_warned = True
    try:
        yield
    finally:
        # A function-scoped pytest-asyncio loop is closed after every test.
        # Finish/cancel one-shot work while its owning loop and DB pool are
        # still alive, then close the pool on that same loop.  Closing it at
        # the start of the *next* test is too late: close_native_pool() clears
        # the global before asyncpg discovers the cross-loop close, leaking
        # the old pool's sockets (eventually leaving the xdist worker unable
        # to shut down after the suite).
        try:
            from utils.async_helpers import drain_spawned_tasks

            await drain_spawned_tasks(timeout=0)
        except Exception as e:
            logger.debug("[test] background-task drain failed: %s", e)

        if _db._native_pool is not None and _db._native_pool_loop is current:
            try:
                await _asyncio.wait_for(_db.close_native_pool(), timeout=2)
            except Exception as e:
                logger.debug("[test] close_native_pool on owning loop failed: %s", e)


@pytest.fixture(autouse=True)
def cleanup_postgres_store_state(request):
    """
    Clean up PostgresStore class-level state after EVERY test.

    This autouse fixture ensures that PostgresStore background tasks and queues
    are cleaned up after each test, preventing test isolation issues.

    Runs for all tests, not just those inheriting from BaseHandlerTest.
    """
    test_name = f"{request.node.parent.name}::{request.node.name}" if request.node.parent else request.node.name

    # Yield to let the test run first
    yield

    # Cleanup AFTER test completes
    _cleanup_postgres_store(test_name)


@pytest_asyncio.fixture(autouse=True)
async def cleanup_database_state(request):
    """
    Clean up database tables after tests that use real PostgreSQL.

    This prevents database state contamination between tests when PostgresStore
    background tasks create connections outside the test transaction.
    """
    # Yield to let the test run first
    yield

    # Only cleanup if test uses real database
    if 'postgres_container' in request.fixturenames:
        postgres_container = request.getfixturevalue('postgres_container')
        try:
            # Create a separate connection OUTSIDE the test transaction
            # to clean up data written by PostgresStore background tasks
            import asyncpg
            conn = await asyncpg.connect(
                host=postgres_container.get_container_host_ip(),
                port=postgres_container.get_exposed_port(5432),
                user=postgres_container.username,
                password=postgres_container.password,
                database=postgres_container.dbname,
            )

            try:
                # Truncate tables that PostgresStore writes to
                # Use CASCADE to handle foreign key constraints
                await conn.execute("TRUNCATE TABLE conversation_events CASCADE")
                await conn.execute("TRUNCATE TABLE conversations CASCADE")
            finally:
                await conn.close()
        except Exception:
            # Silently ignore errors (e.g., if tables don't exist)
            pass


def _cleanup_postgres_store(test_name):
    """Helper function to clean up PostgresStore state after tests.

    PostgresStore uses synchronous DB writes with no background tasks,
    so cleanup is minimal — just clear any in-memory misc files.
    """
    pass  # No background tasks to clean up — PostgresStore uses synchronous writes


@pytest_asyncio.fixture
async def setup_users_table_for_folder_tests(postgres_db, request):
    """Create users table and test user for folder tests."""
    # Only run for folder tests
    if 'test_folder_handler' not in str(request.node.fspath):
        return

    # Create users table if it doesn't exist
    await postgres_db.execute("""
        CREATE TABLE IF NOT EXISTS public.users (
            id UUID PRIMARY KEY,
            email TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    # Insert test user
    await postgres_db.execute("""
        INSERT INTO public.users (id, email, created_at)
        VALUES ('00000000-0000-0000-0000-000000000001', 'test@example.com', NOW())
        ON CONFLICT (id) DO NOTHING
    """)




@pytest.fixture(autouse=True)
def _reset_runtime_backend_registries():
    """Reset process-cached runtime registries before each test.

    This keeps local backend selection deterministic regardless of import order.
    """
    import nodes.core.code_runtime as _code_rt
    import utils.volume_backend as _vol
    from coder.openai_agent import sandbox as _sbx

    _code_rt.clear()
    _vol.clear()
    _sbx.clear()
    pass
    yield
