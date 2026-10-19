"""The builder names only a workflow nobody named.

Its background naming call names a workflow still called a placeholder
(``PLACEHOLDER_WORKFLOW_NAMES``): one made unnamed, or one a prior turn's
naming call failed to name (2026-07 workflow-naming incident: one openrouter
timeout stranded "Untitled" forever, so every later turn tries again). A name
its creator gave, through the platform API or the app, is never replaced, on
the first turn or any other, and no naming call is paid for; a name the user
types while one runs wins. Real PostgreSQL.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from repositories.workflow import WorkflowRepo
from wss.handlers import workflow_builder_handler as wbh

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


async def _name_of(conn, wid: str) -> str:
    return await conn.fetchval("SELECT name FROM workflows WHERE id = $1", uuid.UUID(wid))


@pytest.mark.asyncio
class TestRenamePlaceholderGuard:
    @pytest.mark.parametrize("placeholder", ["Untitled", "Untitled Workflow", "New workflow", ""])
    async def test_a_placeholder_is_renamed(self, postgres_db, placeholder):
        wid = await _make_workflow(postgres_db, placeholder)
        repo = WorkflowRepo(_ConnPool(postgres_db))
        assert await repo.has_placeholder_name(wid, str(TEST_USER_ID))
        row = await repo.rename_workflow_if_owner(
            wid, "UGC Creator Portfolio", "Animated portfolio site", str(TEST_USER_ID),
        )
        assert row and row["name"] == "UGC Creator Portfolio"

    async def test_a_given_name_is_never_clobbered(self, postgres_db):
        wid = await _make_workflow(postgres_db, "e2e-agents-wf2")
        repo = WorkflowRepo(_ConnPool(postgres_db))
        assert not await repo.has_placeholder_name(wid, str(TEST_USER_ID))
        assert await repo.rename_workflow_if_owner(wid, "Return Fixed Answer", "desc", str(TEST_USER_ID)) is None
        assert await _name_of(postgres_db, wid) == "e2e-agents-wf2"

    async def test_owner_gate_still_applies(self, postgres_db):
        wid = await _make_workflow(postgres_db, "Untitled")
        repo = WorkflowRepo(_ConnPool(postgres_db))
        assert not await repo.has_placeholder_name(wid, str(OTHER_USER_ID))
        assert await repo.rename_workflow_if_owner(wid, "Hijacked", "desc", str(OTHER_USER_ID)) is None


@pytest.mark.asyncio
class TestBuilderNaming:
    """The builder's background naming over the real row: what the first turn on an empty graph runs."""

    @pytest.fixture
    def naming(self, postgres_db, monkeypatch):
        model = AsyncMock(return_value=("Return Fixed Answer", "Returns a fixed answer."))
        monkeypatch.setattr(wbh, "generate_workflow_name", model)
        handler = wbh.WorkflowBuilderHandler(MagicMock(emit=AsyncMock()))
        handler.get_pool = AsyncMock(return_value=_ConnPool(postgres_db))
        return handler, model

    async def test_a_workflow_its_creator_named_keeps_its_name_and_pays_for_no_naming(self, postgres_db, naming):
        handler, model = naming
        wid = await _make_workflow(postgres_db, "e2e-agents-wf2")
        await handler._generate_workflow_name_background("", str(TEST_USER_ID), wid, "Return a fixed answer")
        assert await _name_of(postgres_db, wid) == "e2e-agents-wf2"
        model.assert_not_awaited()

    async def test_an_unnamed_workflow_is_named(self, postgres_db, naming):
        handler, model = naming
        wid = await _make_workflow(postgres_db, "New workflow")
        await handler._generate_workflow_name_background("", str(TEST_USER_ID), wid, "Return a fixed answer")
        assert await _name_of(postgres_db, wid) == "Return Fixed Answer"
        model.assert_awaited_once()
