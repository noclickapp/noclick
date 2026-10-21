"""The workflow MCP server's ``list_workflows`` against real PostgreSQL: the
workflows the caller owns (``workflows.owner_id``), never another account's or
a trashed one, narrowed by a search (a name, or a workflow's id) and a folder."""

import uuid

import pytest

from repositories.workflow import WorkflowRepo

pytestmark = pytest.mark.asyncio


async def _user(conn) -> str:
    return str(await conn.fetchval(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES ($1, '{}'::jsonb) RETURNING id",
        f"{uuid.uuid4().hex[:8]}@example.com"))


async def _workflow(conn, owner: str, name: str, *, folder_id=None, trashed=False) -> str:
    return str(await conn.fetchval(
        "INSERT INTO workflows (owner_id, name, workflow, folder_id, deleted_at) "
        "VALUES ($1::uuid, $2, $3, $4::uuid, CASE WHEN $5 THEN now() END) RETURNING id",
        owner, name, {"nodes": [], "edges": []}, folder_id, trashed))


async def test_lists_the_callers_own_workflows(postgres_db):
    conn = postgres_db
    owner, other = await _user(conn), await _user(conn)
    folder = str(await conn.fetchval(
        "INSERT INTO workflow_folders (owner_id, name) VALUES ($1::uuid, 'Billing') RETURNING id", owner))
    digest = await _workflow(conn, owner, "Orders digest", folder_id=folder)
    invoices = await _workflow(conn, owner, "Invoices")
    await _workflow(conn, owner, "Old orders", trashed=True)
    theirs = await _workflow(conn, other, "Orders digest")
    repo = WorkflowRepo(None)

    async def listed(user_id, query=None, folder_id=None):
        rows = await repo.list_workflows_mcp(conn, user_id=user_id, query=query, folder_id=folder_id, limit=10)
        return {str(row["id"]) for row in rows}

    assert await listed(owner) == {digest, invoices}
    assert await listed(other) == {theirs}
    assert await listed(owner, query="digest") == {digest}
    assert await listed(owner, query=invoices) == {invoices}
    assert await listed(owner, query=theirs) == set()
    assert await listed(owner, folder_id=folder) == {digest}
    assert await listed(owner, folder_id="") == {invoices}
