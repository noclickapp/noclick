"""What ``workflow_node_output_schemas`` says taught each shape, and what its reads serve, against real Postgres."""

import pytest

from utils import node_schema_tracker
from utils.node_schema_tracker import (
    compute_schema_hash,
    extract_schema,
    get_all_schemas_for_node,
    get_schema_for_node,
    get_schema_with_suggestions,
    track_node_schema,
)

TRIGGER = ("automation-exa", "on_monitor_results")
ACTION = ("automation-exa", "search")


@pytest.fixture
async def pool(postgres_db, postgres_container, monkeypatch):
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password, database=postgres_container.dbname,
        min_size=1, max_size=2, init=setup_asyncpg_codecs,
    )
    monkeypatch.setattr(node_schema_tracker, "get_native_pool", lambda: pool)

    async def no_refs(*args, **kwargs):
        return None  # suggested references would ask a model

    monkeypatch.setattr(node_schema_tracker, "_generate_suggested_refs", no_refs)
    await pool.execute("DELETE FROM workflow_node_output_schemas WHERE node_type = 'automation-exa'")
    try:
        yield pool
    finally:
        await pool.execute("DELETE FROM workflow_node_output_schemas WHERE node_type = 'automation-exa'")
        await pool.close()


async def _row_from_before_it_was_recorded(pool, key, output, count=100):
    """A row as they all stood before ``taught_by``: nothing says what taught it."""
    schema = extract_schema(output)
    await pool.execute(
        "INSERT INTO workflow_node_output_schemas (node_type, node_operation, output_schema, schema_hash, "
        "occurrence_count) VALUES ($1, $2, $3, $4, $5)",
        *key, schema, compute_schema_hash(*key, schema), count)


async def _taught_by(pool, key, output):
    return await pool.fetchval("SELECT taught_by FROM workflow_node_output_schemas WHERE schema_hash = $1",
                               compute_schema_hash(*key, extract_schema(output)))


async def test_a_row_says_what_taught_it_and_a_delivery_stands(pool):
    output = {"type": "monitor.run.completed"}
    await track_node_schema(*TRIGGER, output)
    assert await _taught_by(pool, TRIGGER, output) == "run"
    await track_node_schema(*TRIGGER, output, delivered=True)
    assert await _taught_by(pool, TRIGGER, output) == "delivery"
    # A later run of the same shape never takes it back.
    await track_node_schema(*TRIGGER, output)
    assert await _taught_by(pool, TRIGGER, output) == "delivery"


async def test_a_triggers_row_from_before_is_served_only_once_it_is_taught_again(pool):
    polluted = {"status": "success", "data": {"another_accounts_step": {"its_field": "x"}}}
    await _row_from_before_it_was_recorded(pool, TRIGGER, polluted)
    assert await get_schema_for_node(*TRIGGER) is None
    assert await get_schema_with_suggestions(*TRIGGER) is None
    assert await get_all_schemas_for_node(*TRIGGER) == []

    # Nothing copies inputs now, so a row like that is never taught again. One that a real event has is.
    real = {"rows": [{"id": 1}]}
    await _row_from_before_it_was_recorded(pool, TRIGGER, real, count=1)
    await track_node_schema(*TRIGGER, real)
    assert await get_schema_for_node(*TRIGGER) == extract_schema(real)
    assert (await get_schema_with_suggestions(*TRIGGER))["schema"] == extract_schema(real)
    assert [r["output_schema"] for r in await get_all_schemas_for_node(*TRIGGER)] == [extract_schema(real)]


async def test_a_steps_row_from_before_is_still_served(pool):
    """Only a trigger's rows could hold what a manual run copied: the builder keeps every action's shape."""
    output = {"results": [{"url": "x"}]}
    await _row_from_before_it_was_recorded(pool, ACTION, output)
    assert await get_schema_for_node(*ACTION) == extract_schema(output)
    assert (await get_schema_with_suggestions(*ACTION))["schema"] == extract_schema(output)
