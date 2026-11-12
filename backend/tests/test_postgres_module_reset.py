"""The shared test database's reset between modules (tests/fixtures/postgres_fixtures.py)."""

import asyncio

import asyncpg
import pytest

from tests.fixtures import postgres_fixtures


async def _connect(container):
    return await asyncpg.connect(
        host=container.get_container_host_ip(), port=container.get_exposed_port(5432),
        user=container.username, password=container.password, database=container.dbname,
    )


async def test_a_connection_an_earlier_module_left_holding_a_lock_fails_the_reset_and_is_ended(
    postgres_container, monkeypatch,
):
    monkeypatch.setattr(postgres_fixtures, "RESET_LOCK_TIMEOUT", "200ms")
    leaked = await _connect(postgres_container)
    observer = None
    try:
        pid = leaked.get_server_pid()
        await leaked.execute("BEGIN")
        await leaked.execute("LOCK TABLE auth.users IN ACCESS SHARE MODE")
        with pytest.raises(RuntimeError, match="holding locks this module's reset needs") as refused:
            await postgres_fixtures.reset_database_data(postgres_container)
        assert "LOCK TABLE auth.users" in str(refused.value)
        observer = await _connect(postgres_container)
        # Ended by the server: asked of the server, since what the leaked
        # client makes of its own end depends on when it reads it.
        for _ in range(50):
            if not await observer.fetchval("SELECT count(*) FROM pg_stat_activity WHERE pid = $1", pid):
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail("the connection holding the lock was not ended")
    finally:
        leaked.terminate()
        if observer is not None:
            await observer.close()
    # The next module's reset goes through.
    await postgres_fixtures.reset_database_data(postgres_container)
