"""An automation's tables through their one seam (``utils.dataset_store``),
against real Postgres: rows in order with ids of their own, pages with the
table's total, appends after the last row (appends at once never share a
position), objects replaced whole, deletes
counted, ``metadata.row_count`` in step, values kept exactly, and the limits.

Each test runs on the store this instance registers (hosted: each
automation's own database, here on the database Worker's fake; the open
edition: Postgres) and on the engine's own Postgres store."""

import asyncio
import uuid

import pytest

from repositories.datasets import PostgresDatasets
from repositories.resources import ResourceRepo
from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from utils import dataset_store
from utils.dataset_store import MAX_PAGE_ROWS, MAX_ROW_BYTES, DatasetError

pytestmark = pytest.mark.asyncio


@pytest.fixture(params=["registered", "postgres"])
def store(request, monkeypatch):
    if request.param == "postgres":
        monkeypatch.setattr(dataset_store, "_factory", PostgresDatasets)
    return request.param


async def _table(db, name="Leads"):
    owner = str(uuid.uuid4())
    await db.execute("INSERT INTO auth.users (id, email) VALUES ($1, $2)", owner, f"{owner}@example.com")
    workflow = await db.fetchval("INSERT INTO workflows (owner_id, name) VALUES ($1, 'Booking') RETURNING id", owner)
    repo = ResourceRepo(db.pool)
    made = await repo.create_resource(owner_id=owner, organization_id=None, workflow_id=str(workflow), node_id=None,
                                      resource_type="dataset", name=name, mime_type=None, size_bytes=0,
                                      storage_ref=None, metadata={})
    await dataset_store.create_dataset(db.pool, made)
    return await repo.get_resource(str(made["id"]))


async def _fresh(db, resource):
    return await ResourceRepo(db.pool).get_resource(str(resource["id"]))


async def test_rows_keep_their_order_ids_and_positions(real_database, store):
    table = await _table(real_database)
    added = await dataset_store.append_rows(real_database.pool, table, [{"n": "a"}, {"n": "b"}, {"n": "c"}])
    assert added == 3

    page, total = await dataset_store.read_rows(real_database.pool, table, limit=2, offset=1)
    assert total == 3
    assert [(r["row_index"], r["data"]) for r in page] == [(1, {"n": "b"}), (2, {"n": "c"})]
    everything, _ = await dataset_store.read_rows(real_database.pool, table, limit=10)
    assert len({r["id"] for r in everything}) == 3
    assert all(r["created_at"] for r in everything)
    assert (await _fresh(real_database, table))["metadata"]["row_count"] == 3


async def test_a_new_row_goes_after_the_last_and_appends_at_once_never_share_a_position(real_database, store):
    table = await _table(real_database)
    await dataset_store.append_rows(real_database.pool, table, [{"n": i} for i in range(3)])
    rows, _ = await dataset_store.read_rows(real_database.pool, table, limit=10)
    assert await dataset_store.delete_rows(real_database.pool, table, [rows[1]["id"]]) == 1
    await dataset_store.append_rows(real_database.pool, table, [{"n": "after"}])
    rows, _ = await dataset_store.read_rows(real_database.pool, table, limit=10)
    assert [(r["row_index"], r["data"]["n"]) for r in rows] == [(0, 0), (2, 2), (3, "after")]

    await asyncio.gather(*(dataset_store.append_rows(real_database.pool, table, [{"burst": b, "i": i} for i in range(3)])
                           for b in range(5)))
    rows, total = await dataset_store.read_rows(real_database.pool, table, limit=100)
    assert total == len(rows) == 18
    assert len({r["row_index"] for r in rows}) == 18
    assert (await _fresh(real_database, table))["metadata"]["row_count"] == 18


async def test_an_update_replaces_the_object_and_misses_an_unknown_row(real_database, store):
    table = await _table(real_database)
    await dataset_store.append_rows(real_database.pool, table, [{"name": "Ada", "age": 30, "tags": ["x"]}])
    [row], _ = await dataset_store.read_rows(real_database.pool, table)
    assert await dataset_store.update_row(real_database.pool, table, row["id"], {"name": "Ada"}) is True
    [after], _ = await dataset_store.read_rows(real_database.pool, table)
    assert after["data"] == {"name": "Ada"} and after["id"] == row["id"] and after["row_index"] == 0
    assert await dataset_store.update_row(real_database.pool, table, str(uuid.uuid4()), {"x": 1}) is False


async def test_deletes_count_what_was_there(real_database, store):
    table = await _table(real_database)
    await dataset_store.append_rows(real_database.pool, table, [{"n": i} for i in range(4)])
    rows, _ = await dataset_store.read_rows(real_database.pool, table)
    gone = await dataset_store.delete_rows(real_database.pool, table, [rows[0]["id"], rows[1]["id"], str(uuid.uuid4())])
    assert gone == 2
    left, total = await dataset_store.read_rows(real_database.pool, table)
    assert total == 2 and [r["data"]["n"] for r in left] == [2, 3]
    assert (await _fresh(real_database, table))["metadata"]["row_count"] == 2


async def test_values_come_back_exactly(real_database, store):
    table = await _table(real_database)
    value = {"big": 2 ** 60, "float": 0.1, "neg": -3, "yes": True, "no": False, "none": None, "text": "café — ✓ \"q\"",
             "nested": {"list": [1, "2", {"3": [None]}], "empty": {}}, "": "blank key"}
    await dataset_store.append_rows(real_database.pool, table, [value])
    [row], _ = await dataset_store.read_rows(real_database.pool, table)
    assert row["data"] == value


async def test_a_page_of_large_rows_reads_back_whole(real_database, store):
    """Twelve rows near the row limit pass what one read of the database carries; the page still holds them all."""
    table = await _table(real_database)
    rows = [{"i": i, "blob": "x" * (MAX_ROW_BYTES - 100)} for i in range(12)]
    await dataset_store.append_rows(real_database.pool, table, rows)
    page, total = await dataset_store.read_rows(real_database.pool, table, limit=20)
    assert total == 12 and [r["data"]["i"] for r in page] == list(range(12))
    assert all(len(r["data"]["blob"]) == MAX_ROW_BYTES - 100 for r in page)


async def test_the_limits(real_database, store):
    table = await _table(real_database)
    with pytest.raises(DatasetError, match="at most"):
        await dataset_store.append_rows(real_database.pool, table, [{"blob": "x" * MAX_ROW_BYTES}])
    with pytest.raises(DatasetError, match="isn't an object"):
        await dataset_store.append_rows(real_database.pool, table, [[1, 2]])
    for limit in (0, MAX_PAGE_ROWS + 1):
        with pytest.raises(DatasetError, match="limit"):
            await dataset_store.read_rows(real_database.pool, table, limit=limit)
    file = dict(table, resource_type="file")
    with pytest.raises(DatasetError, match="Resource is not a dataset"):
        await dataset_store.read_rows(real_database.pool, file)
    assert (await dataset_store.read_rows(real_database.pool, table))[1] == 0
