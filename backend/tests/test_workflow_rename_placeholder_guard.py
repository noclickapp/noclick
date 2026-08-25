"""rename_workflow_if_owner placeholder gating.

The builder's background naming call fails silently on an LLM blip; the retry
now fires on later turns whenever the name is still a default placeholder
(2026-07 workflow-naming incident: one openrouter timeout stranded "Untitled"
forever). The retry passes placeholder_only=True, so it must never clobber a
name the user typed between turns — that guard lives in the SQL and is what
these tests pin.
"""

import uuid

import pytest

from repositories.workflow import WorkflowRepo

TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


class _ConnPool:
    """Pool-shaped wrapper over the fixture connection (repo acquires from a pool)."""

    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


async def _make_workflow(conn, name: str) -> str:
    wid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1, $2, $3, $4)",
        wid, TEST_USER_ID, name, {"nodes": [], "edges": []},
    )
    return str(wid)


@pytest.mark.asyncio
class TestRenamePlaceholderGuard:
    async def test_placeholder_only_renames_untitled(self, postgres_db):
        wid = await _make_workflow(postgres_db, "Untitled")
        repo = WorkflowRepo(_ConnPool(postgres_db))
        row = await repo.rename_workflow_if_owner(
            wid, "UGC Creator Portfolio", "Animated portfolio site",
            str(TEST_USER_ID), placeholder_only=True,
        )
        assert row and row["name"] == "UGC Creator Portfolio"

    async def test_placeholder_only_never_clobbers_user_name(self, postgres_db):
        wid = await _make_workflow(postgres_db, "My Precious Workflow")
        repo = WorkflowRepo(_ConnPool(postgres_db))
        row = await repo.rename_workflow_if_owner(
            wid, "Generated Name", "desc", str(TEST_USER_ID),
            placeholder_only=True,
        )
        assert row is None
        name = await postgres_db.fetchval(
            "SELECT name FROM workflows WHERE id = $1", uuid.UUID(wid)
        )
        assert name == "My Precious Workflow"

    async def test_first_turn_path_renames_prompt_slice_placeholder(self, postgres_db):
        # WorkflowCreator seeds a slice of the prompt as the name — the
        # empty-graph path replaces it unconditionally (existing behavior).
        wid = await _make_workflow(postgres_db, "build me an AI agent that can spy on")
        repo = WorkflowRepo(_ConnPool(postgres_db))
        row = await repo.rename_workflow_if_owner(
            wid, "Reddit Keyword Tracker", "desc", str(TEST_USER_ID),
        )
        assert row and row["name"] == "Reddit Keyword Tracker"

    async def test_owner_gate_still_applies(self, postgres_db):
        wid = await _make_workflow(postgres_db, "Untitled")
        repo = WorkflowRepo(_ConnPool(postgres_db))
        row = await repo.rename_workflow_if_owner(
            wid, "Hijacked", "desc", str(OTHER_USER_ID), placeholder_only=True,
        )
        assert row is None
