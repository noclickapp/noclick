"""CAS on workflows.graph_version — trigger + update_workflow_dynamic guard.

The 20260713000000 migration adds a graph_version column bumped by a DB
trigger whenever the workflow blob changes (any writer: FE autosave, MCP,
builder, restores). update_workflow_dynamic's expected_graph_version turns
the FE autosave into a compare-and-swap so a stale snapshot loses cleanly
(conflict + client rebase) instead of clobbering a newer save.
"""

import uuid

import pytest

from repositories.workflow import WorkflowRepo

TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def _make_workflow(conn) -> uuid.UUID:
    wid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1, $2, $3, $4)",
        wid, TEST_USER_ID, "cas test",
        {"nodes": [{"id": "n1", "type": "automation-slack", "position": {"x": 0, "y": 0}, "config": {}}], "edges": []},
    )
    return wid


async def _version(conn, wid) -> int:
    return await conn.fetchval("SELECT graph_version FROM workflows WHERE id = $1", wid)


@pytest.mark.asyncio
class TestGraphVersionTrigger:
    async def test_blob_change_bumps_metadata_change_does_not(self, postgres_db):
        wid = await _make_workflow(postgres_db)
        assert await _version(postgres_db, wid) == 1

        await postgres_db.execute(
            "UPDATE workflows SET workflow = $2 WHERE id = $1",
            wid, {"nodes": [], "edges": []},
        )
        assert await _version(postgres_db, wid) == 2

        await postgres_db.execute(
            "UPDATE workflows SET name = 'renamed' WHERE id = $1", wid,
        )
        assert await _version(postgres_db, wid) == 2


@pytest.mark.asyncio
class TestUpdateWorkflowDynamicCas:
    async def test_matching_version_writes_and_returns_bumped_version(self, postgres_db):
        wid = await _make_workflow(postgres_db)
        repo = WorkflowRepo(None)
        row = await repo.update_workflow_dynamic(
            postgres_db, wid,
            workflow_data={"nodes": [], "edges": []},
            expected_graph_version=1,
        )
        assert row is not None
        assert row["graph_version"] == 2
        assert row["workflow"]["nodes"] == []

    async def test_stale_version_matches_zero_rows_and_preserves_content(self, postgres_db):
        wid = await _make_workflow(postgres_db)
        repo = WorkflowRepo(None)
        # A concurrent writer lands first (bumps 1 → 2).
        await postgres_db.execute(
            "UPDATE workflows SET workflow = $2 WHERE id = $1",
            wid, {"nodes": [], "edges": [], "winner": True},
        )
        # The stale client (still holding version 1) must lose cleanly.
        row = await repo.update_workflow_dynamic(
            postgres_db, wid,
            workflow_data={"nodes": [{"id": "stale", "type": "x", "position": {"x": 0, "y": 0}, "config": {}}], "edges": []},
            expected_graph_version=1,
        )
        assert row is None
        current = await postgres_db.fetchrow(
            "SELECT workflow, graph_version FROM workflows WHERE id = $1", wid
        )
        assert current["graph_version"] == 2
        assert current["workflow"].get("winner") is True  # not clobbered

    async def test_no_expected_version_writes_unconditionally(self, postgres_db):
        wid = await _make_workflow(postgres_db)
        repo = WorkflowRepo(None)
        await postgres_db.execute(
            "UPDATE workflows SET workflow = $2 WHERE id = $1",
            wid, {"nodes": [], "edges": []},
        )
        # Legacy / MCP / builder writers send no version — always land.
        row = await repo.update_workflow_dynamic(
            postgres_db, wid,
            workflow_data={"nodes": [], "edges": [], "unconditional": True},
        )
        assert row is not None
        assert row["workflow"].get("unconditional") is True
        assert row["graph_version"] == 3

    async def test_metadata_only_update_ignores_stale_version(self, postgres_db):
        # The guard is scoped to workflow_data writes: a rename must never
        # conflict, even if the caller passes a stale version alongside it.
        wid = await _make_workflow(postgres_db)
        repo = WorkflowRepo(None)
        await postgres_db.execute(
            "UPDATE workflows SET workflow = $2 WHERE id = $1",
            wid, {"nodes": [], "edges": []},
        )
        row = await repo.update_workflow_dynamic(
            postgres_db, wid,
            name="renamed",
            expected_graph_version=1,  # stale, but no workflow_data → ignored
        )
        assert row is not None
        assert row["name"] == "renamed"
        assert row["graph_version"] == 2  # untouched by the rename
