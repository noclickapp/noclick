"""What ``workflow_node_output_schemas`` says taught each shape, what its reads serve, and what each account keeps as
its own (``account_node_output_schemas``), against real Postgres."""

import uuid

import pytest

from repositories import node_output_schemas
from utils import node_schema_tracker
from utils.node_schema_tracker import (
    compute_schema_hash,
    extract_schema,
    get_all_schemas_for_node,
    get_own_schema_with_suggestions,
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

    async def clean():
        await pool.execute("DELETE FROM workflow_node_output_schemas WHERE node_type = 'automation-exa'")
        await pool.execute("DELETE FROM account_node_output_schemas WHERE node_type = 'automation-exa'")

    await clean()
    try:
        yield pool
    finally:
        await clean()
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


async def _account(pool) -> tuple:
    """An account and a workflow of its."""
    user_id = str(await pool.fetchval(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES ($1, '{}'::jsonb) RETURNING id",
        f"{uuid.uuid4().hex[:10]}@example.com"))
    workflow_id = str(await pool.fetchval(
        "INSERT INTO workflows (owner_id, name) VALUES ($1::uuid, 'Theirs') RETURNING id", user_id))
    return user_id, workflow_id


CUSTOM = {"results": [{"url": "x", "acme_renewal_tier": "gold"}]}


async def test_an_account_keeps_its_own_shapes_and_reads_no_others(pool):
    a, a_workflow = await _account(pool)
    b, _ = await _account(pool)
    await track_node_schema(*ACTION, CUSTOM, workflow_id=a_workflow)

    assert (await get_own_schema_with_suggestions(a, *ACTION))["schema"] == extract_schema(CUSTOM)
    assert await get_own_schema_with_suggestions(b, *ACTION) is None
    # The pool holds it, unchanged, for NoClick's own models.
    assert await get_schema_for_node(*ACTION) == extract_schema(CUSTOM)

    # The most seen of the account's own leads, however often other accounts saw another.
    plain = {"results": [{"url": "x"}]}
    await _row_from_before_it_was_recorded(pool, ACTION, plain, count=100000)
    for _ in range(2):
        await track_node_schema(*ACTION, {"found": 1}, workflow_id=a_workflow)
    assert (await get_own_schema_with_suggestions(a, *ACTION))["schema"] == {"found": "integer"}


async def test_an_own_shape_carries_the_references_curated_for_it(pool):
    a, a_workflow = await _account(pool)
    await track_node_schema(*ACTION, CUSTOM, workflow_id=a_workflow)
    refs = [{"path": "results[].url", "label": "URL", "description": "The result's address."}]
    await pool.execute("UPDATE workflow_node_output_schemas SET suggested_refs = $1 WHERE schema_hash = $2",
                       refs, compute_schema_hash(*ACTION, extract_schema(CUSTOM)))
    assert (await get_own_schema_with_suggestions(a, *ACTION))["suggested_refs"] == refs


async def test_a_delivery_stands_on_an_accounts_own_row_and_a_run_never_counts_as_one(pool):
    a, a_workflow = await _account(pool)
    await track_node_schema(*TRIGGER, {"made_by_a_run": "x"}, workflow_id=a_workflow)
    delivered = {"type": "monitor.run.completed"}
    await track_node_schema(*TRIGGER, delivered, delivered=True, workflow_id=a_workflow)
    await track_node_schema(*TRIGGER, delivered, workflow_id=a_workflow)

    rows = await node_output_schemas.delivered_shapes(pool, a, TRIGGER[0], [TRIGGER[1]], limit=10)
    assert [r["output_schema"] for r in rows] == [extract_schema(delivered)]
    assert await node_output_schemas.delivered_shapes(pool, str(uuid.uuid4()), TRIGGER[0], [TRIGGER[1]], limit=10) == []


async def test_a_workflow_nothing_holds_teaches_no_account_and_the_pool_still_learns(pool):
    await track_node_schema(*ACTION, CUSTOM, workflow_id=str(uuid.uuid4()))
    await track_node_schema(*ACTION, {"not_a_uuid": 1}, workflow_id="wf-1")  # swallowed, as any failure to track
    assert await pool.fetchval("SELECT count(*) FROM account_node_output_schemas WHERE node_type = $1 "
                               "AND node_operation = $2 AND output_schema::text LIKE '%acme_renewal_tier%'",
                               *ACTION) == 0
    assert await get_schema_for_node(*ACTION) == extract_schema(CUSTOM)
