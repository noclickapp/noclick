"""Validates the CAS migration applies cleanly and the schema behaves.

Runs against the real testcontainer (which applies ALL migrations in order), so
this booting at all proves 20260602000000_execution_log_cas.sql is valid SQL and
ordered correctly relative to workflows / workflow_executions.
"""

import uuid

import pytest


TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def _make_workflow(conn) -> uuid.UUID:
    wid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO workflows (id, owner_id, name) VALUES ($1, $2, $3)",
        wid, TEST_USER_ID, "cas test",
    )
    return wid


@pytest.mark.asyncio
class TestCasMigration:
    async def test_cas_tables_exist(self, postgres_db):
        expected = {"cas_blobs", "cas_refs", "cas_manifests",
                    "cas_storage_stats", "workflow_run_totals"}
        rows = await postgres_db.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
            "AND tablename = ANY($1)",
            list(expected),
        )
        assert {r["tablename"] for r in rows} == expected

    async def test_new_columns_and_defaults(self, postgres_db):
        wid = await _make_workflow(postgres_db)
        eid = uuid.uuid4()
        await postgres_db.execute(
            "INSERT INTO workflow_executions (id, workflow_id, user_id, status) "
            "VALUES ($1, $2, $3, 'completed')",
            eid, wid, TEST_USER_ID,
        )
        row = await postgres_db.fetchrow(
            "SELECT graph_hash, trigger_source FROM workflow_executions WHERE id=$1", eid)
        assert row["graph_hash"] is None
        assert row["trigger_source"] == "manual"

    async def test_trigger_source_check_rejects_bad_value(self, postgres_db):
        wid = await _make_workflow(postgres_db)
        with pytest.raises(Exception):
            await postgres_db.execute(
                "INSERT INTO workflow_executions "
                "(id, workflow_id, user_id, status, trigger_source) "
                "VALUES ($1, $2, $3, 'completed', 'bogus')",
                uuid.uuid4(), wid, TEST_USER_ID,
            )

    async def test_legacy_node_outputs_dropped(self, postgres_db):
        """The final cutover migration removed the legacy table + opt-in flag."""
        table = await postgres_db.fetchval(
            "SELECT to_regclass('public.workflow_node_outputs')")
        assert table is None, "workflow_node_outputs table should be dropped"
        col = await postgres_db.fetchval(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='workflows' AND column_name='cas_enabled'")
        assert col is None, "workflows.cas_enabled column should be dropped"

    async def test_cas_rows_insert_and_workflow_delete_cascade(self, postgres_db):
        wid = await _make_workflow(postgres_db)
        eid = uuid.uuid4()
        h = "a" * 64
        await postgres_db.execute(
            "INSERT INTO cas_blobs (hash, size_bytes) VALUES ($1, 10)", h)
        await postgres_db.execute(
            "INSERT INTO cas_refs (workflow_id, execution_id, node_id, chunk_hash) "
            "VALUES ($1, $2, 'n1', $3)", wid, eid, h)
        await postgres_db.execute(
            "INSERT INTO cas_manifests (workflow_id, execution_id, node_id, manifest) "
            "VALUES ($1, $2, 'n1', $3::jsonb)", wid, eid, '{"$cas":"%s"}' % h)

        # Deleting the workflow cascades refs + manifests; the blob survives
        # (shared/global) for GC Phase B to reclaim.
        await postgres_db.execute("DELETE FROM workflows WHERE id=$1", wid)
        assert (await postgres_db.fetchval(
            "SELECT count(*) FROM cas_refs WHERE workflow_id=$1", wid)) == 0
        assert (await postgres_db.fetchval(
            "SELECT count(*) FROM cas_manifests WHERE workflow_id=$1", wid)) == 0
        assert (await postgres_db.fetchval(
            "SELECT count(*) FROM cas_blobs WHERE hash=$1", h)) == 1
