"""Releasing a native pool connection costs no round trip of its own: asyncpg's
default reset sent ``pg_advisory_unlock_all(); CLOSE ALL; UNLISTEN *; RESET ALL``
on every release (about half a simple query's time through the pooler), which
does nothing under transaction pooling. An open transaction is still rolled back."""

import asyncpg
import pytest

from tests.fixtures.real_db_fixture import real_database
from utils import database_pool

pytestmark = pytest.mark.asyncio


@pytest.fixture
def sent(monkeypatch):
    statements = []
    execute = asyncpg.connection.Connection.execute

    async def spy(self, query, *args, **kwargs):
        statements.append(query)
        return await execute(self, query, *args, **kwargs)

    monkeypatch.setattr(asyncpg.connection.Connection, "execute", spy)
    return statements


async def test_a_release_sends_nothing(real_database, sent):
    pool = database_pool.get_native_pool()
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT 1") == 1
    assert await pool.fetchval("SELECT 2") == 2
    assert sent == []


async def test_a_transaction_left_open_is_rolled_back_on_release(real_database, sent):
    pool = database_pool.get_native_pool()
    async with pool.acquire() as conn:
        await conn.execute("BEGIN")
        held = conn._con
    assert sent == ["BEGIN", "ROLLBACK"]
    async with pool.acquire() as conn:
        assert conn._con is held and not conn.is_in_transaction()
