"""Shared fixtures for CAS tests that need COMMITTED cross-connection state.

GC / handler integration tests span connections (writer vs GC vs reader), so they
cannot use the rolled-back ``postgres_db`` connection — they need a committed pool.
Teardown TRUNCATEs the CAS tables + deletes the test user's workflows so committed
rows never leak into the rolled-back unit tests (which assert global CAS counts).
"""

import uuid

import asyncpg
import pytest_asyncio

TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest_asyncio.fixture
async def cas_pool(postgres_container, postgres_db):  # postgres_db forces migrations
    dsn = (
        f"postgresql://{postgres_container.username}:{postgres_container.password}"
        f"@{postgres_container.get_container_host_ip()}"
        f":{postgres_container.get_exposed_port(5432)}/{postgres_container.dbname}"
    )
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)

    async def _truncate():
        async with pool.acquire() as c:
            await c.execute(
                "TRUNCATE cas_blobs, cas_refs, cas_manifests, "
                "cas_storage_stats, workflow_run_totals CASCADE")
            await c.execute("DELETE FROM workflow_executions WHERE user_id=$1", TEST_USER_ID)
            await c.execute("DELETE FROM workflows WHERE owner_id=$1", TEST_USER_ID)

    await _truncate()
    try:
        yield pool
    finally:
        await _truncate()
        await pool.close()


@pytest_asyncio.fixture
async def codec_pool(postgres_container, postgres_db):  # postgres_db forces migrations
    """Codec-enabled pool over the same test DB, mirroring production's
    self.get_pool() (the native pool, which registers the jsonb codec). Handler
    writes routed through get_pool() — e.g. the set-variable variables mirror —
    must use this so the test exercises the same dict->jsonb encoding as prod; the
    non-codec cas_pool rejects a raw dict ("expected str, got dict")."""
    from utils.database_pool import setup_asyncpg_codecs
    dsn = (
        f"postgresql://{postgres_container.username}:{postgres_container.password}"
        f"@{postgres_container.get_container_host_ip()}"
        f":{postgres_container.get_exposed_port(5432)}/{postgres_container.dbname}"
    )
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2, init=setup_asyncpg_codecs)
    try:
        yield pool
    finally:
        await pool.close()


async def make_workflow(pool):
    wid = uuid.uuid4()
    async with pool.acquire() as c:
        await c.execute(
            "INSERT INTO workflows (id, owner_id, name) VALUES ($1,$2,'cas')",
            wid, TEST_USER_ID)
    return wid


async def make_execution(pool, wid, *, status="completed", started_at=None):
    eid = uuid.uuid4()
    async with pool.acquire() as c:
        if started_at is None:
            await c.execute(
                "INSERT INTO workflow_executions (id, workflow_id, user_id, status) "
                "VALUES ($1,$2,$3,$4)", eid, wid, TEST_USER_ID, status)
        else:
            await c.execute(
                "INSERT INTO workflow_executions (id, workflow_id, user_id, status, started_at) "
                "VALUES ($1,$2,$3,$4,$5)", eid, wid, TEST_USER_ID, status, started_at)
    return eid
