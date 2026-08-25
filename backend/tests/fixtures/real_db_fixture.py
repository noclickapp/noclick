"""
Real-database fixture for integration testing (native asyncpg pool).

``real_database`` points the NATIVE pool (``utils.database_pool``) at the
test's Postgres testcontainer, so handlers under test hit real SQL through
the exact production seam (``get_native_pool()`` / ``self.get_pool()``).
The yielded ``RealDatabase`` is a thin async facade over that same pool for
test setup/verification queries.
"""

import logging
from typing import Any, Dict, List, Optional

import pytest
import pytest_asyncio

from tests.fixtures.postgres_fixtures import _initialize_database_once

logger = logging.getLogger(__name__)


class RealDatabase:
    """Async facade over the native pool for test setup/verification.

    The pool is resolved at call time via ``get_native_pool()`` so the facade
    always targets the pool the fixture initialized — the same one production
    code under test uses. ``conn_params`` supports helpers that need their own
    direct asyncpg connection (e.g. auto-commit DirectDB helpers).
    """

    def __init__(self, conn_params: Dict[str, Any], url: str):
        self.conn_params = conn_params
        self.url = url

    @property
    def pool(self):
        from utils.database_pool import get_native_pool
        return get_native_pool()

    async def execute(self, query: str, *args, timeout: Optional[float] = None) -> str:
        return await self.pool.execute(query, *args, timeout=timeout)

    async def fetch(self, query: str, *args, timeout: Optional[float] = None) -> List[Any]:
        return await self.pool.fetch(query, *args, timeout=timeout)

    async def fetchrow(self, query: str, *args, timeout: Optional[float] = None) -> Any:
        return await self.pool.fetchrow(query, *args, timeout=timeout)

    async def fetchval(self, query: str, *args, timeout: Optional[float] = None) -> Any:
        return await self.pool.fetchval(query, *args, timeout=timeout)


@pytest.fixture
def test_user_id():
    """
    Provides a consistent test user ID for integration tests.
    """
    return '00000000-0000-4000-8000-000000000000'


@pytest_asyncio.fixture
async def real_database(postgres_container, monkeypatch):
    """
    Point the native asyncpg pool at the test's Postgres testcontainer.

    Sets POSTGRES_POOLER_URL to the container's dynamic URL, tears down any
    stale native pool from a previous test (wrong URL or a dead event loop),
    and inits a fresh pool bound to the current test's loop. Production code
    resolves the pool at call time, so everything it runs lands on the
    container DB. The next test's autouse ``ensure_native_db_pool``
    (tests/conftest.py) closes this pool when the loop cycles — mirroring the
    pre-rewrite lifecycle — so no teardown close is needed here.
    """
    from utils import database_pool as _db

    # Migrations + seed, once per session-scoped container.
    await _initialize_database_once(postgres_container)

    host = postgres_container.get_container_host_ip()
    port = postgres_container.get_exposed_port(5432)
    user = postgres_container.username
    password = postgres_container.password
    database = postgres_container.dbname
    container_url = f"postgresql://{user}:{password}@{host}:{port}/{database}"
    monkeypatch.setenv("POSTGRES_POOLER_URL", container_url)

    if _db._native_pool is not None:
        try:
            await _db.close_native_pool()
        except Exception as e:
            logger.debug("[real_database] close stale pool: %s", e)
    # Reset the cached URL-logged flag so init logs the new host.
    _db._runtime_url_logged = False
    await _db.init_native_pool()

    logger.info("[real_database] Native pool ready against testcontainer @ %s:%s", host, port)
    yield RealDatabase(
        {"host": host, "port": port, "user": user, "password": password, "database": database},
        container_url,
    )
