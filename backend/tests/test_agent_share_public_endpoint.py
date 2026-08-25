"""
Real-DB tests for GET /api/public/agent-link/{link_id} (utils/public_routes)
and SharedAgentLinkRepo.load_for_visit.

The endpoint is unauthenticated and the link id is the capability, so the
tests pin the 404 matrix (every not-found-equivalent state) and the response
allowlist — nothing credential- or config-shaped may leave this endpoint.
"""

import json
import uuid
import pytest
from fastapi import HTTPException, Response

from tests.fixtures.real_db_fixture import real_database, test_user_id  # noqa: F401

AGENT_NODE_ID = "agent-1"

GRAPH = {
    "nodes": [
        {
            "id": AGENT_NODE_ID,
            "type": "agent",
            "data": {"label": "Support Bot"},
            "config": {"model": "opencode", "api_key": "sk-super-secret-value", "system_prompt": "be nice"},
        },
        {"id": "tool-1", "type": "tool", "data": {"label": "Calculator"}, "config": {}},
        {"id": "tool-2", "type": "tool", "data": {"label": "Disabled Tool", "disabled": True}, "config": {}},
        {"id": "http-1", "type": "automation-http", "config": {}},
    ],
    "edges": [
        {"source": "tool-1", "target": AGENT_NODE_ID, "targetHandle": "bottom"},
        {"source": "tool-2", "target": AGENT_NODE_ID, "targetHandle": "bottom"},
        # Dataflow edge (no bottom handle) — must NOT appear as a tool.
        {"source": "http-1", "target": AGENT_NODE_ID},
    ],
}


async def _seed_link(db, *, graph=GRAPH, is_active=True):
    owner = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO auth.users (id, email, raw_user_meta_data) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
        owner, f"owner-{owner}@example.com", {"name": "Alex Example"},
    )
    await db.execute(
        "INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at) "
        "VALUES ($1, $2, 'Agent Flow', '', $3, '{}'::jsonb, NOW(), NOW())",
        workflow_id, owner, graph,
    )
    link_id = await db.fetchval(
        "INSERT INTO shared_agent_links (user_id, workflow_id, node_id, is_active) "
        "VALUES ($1, $2, $3, $4) RETURNING id",
        owner, workflow_id, AGENT_NODE_ID, is_active,
    )
    return str(link_id), workflow_id, owner


async def _expect_404(link_id):
    from utils.public_routes import get_agent_link_preview

    with pytest.raises(HTTPException) as exc:
        await get_agent_link_preview(link_id, Response())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_happy_path_allowlist_and_sanitization(real_database):
    from utils.public_routes import get_agent_link_preview

    link_id, workflow_id, _owner = await _seed_link(real_database)
    response = Response()
    data = await get_agent_link_preview(link_id, response)

    # Exact response allowlist — adding a key here is a review event.
    assert set(data.keys()) == {
        "workflow_name", "owner_name", "agent", "tools", "conversation_prefix", "is_active",
    }
    assert data["workflow_name"] == "Agent Flow"
    assert data["owner_name"] == "Alex Example"
    assert data["agent"] == {"label": "Support Bot", "model": "opencode"}
    assert data["conversation_prefix"] == f"ck:{workflow_id}:{AGENT_NODE_ID}:share:{link_id}"
    assert data["is_active"] is True

    # Tools: bottom-handle providers only; disabled + dataflow nodes excluded.
    assert {"node_type": "tool", "label": "Calculator"} in data["tools"]
    labels = [t["label"] for t in data["tools"]]
    assert "Disabled Tool" not in labels
    assert all(t["node_type"] != "automation-http" for t in data["tools"])

    # Nothing secret- or config-shaped leaves the endpoint.
    payload = json.dumps(data)
    assert "sk-super-secret-value" not in payload
    assert "system_prompt" not in payload
    assert "api_key" not in payload

    # Capability URL: revocation must apply immediately.
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_404_matrix(real_database):
    db = real_database

    # Bad / unknown uuid.
    await _expect_404("not-a-uuid")
    await _expect_404(str(uuid.uuid4()))

    # Inactive link.
    inactive_id, _, _ = await _seed_link(db, is_active=False)
    await _expect_404(inactive_id)

    # Minting user no longer owns the workflow (ownership-transfer defense).
    link_id, workflow_id, _ = await _seed_link(db)
    new_owner = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
        new_owner, f"o-{new_owner}@example.com",
    )
    await db.execute("UPDATE workflows SET owner_id = $1 WHERE id = $2", new_owner, workflow_id)
    await _expect_404(link_id)

    # Trashed workflow.
    link_id2, workflow_id2, _ = await _seed_link(db)
    await db.execute("UPDATE workflows SET deleted_at = NOW() WHERE id = $1", workflow_id2)
    await _expect_404(link_id2)

    # Agent node no longer in the graph (removed after minting).
    graph_without_agent = {"nodes": [{"id": "other", "type": "automation-http", "config": {}}], "edges": []}
    link_id3, _, _ = await _seed_link(db, graph=graph_without_agent)
    await _expect_404(link_id3)


@pytest.mark.asyncio
async def test_load_for_visit_matches_endpoint_semantics(real_database):
    """The repo's not-found predicate is the single resolution rule shared by
    connect / send / resume — pin it directly too."""
    from repositories.shared_agent_link import SharedAgentLinkRepo
    from utils.database_pool import get_native_pool

    repo = SharedAgentLinkRepo(get_native_pool())
    link_id, workflow_id, owner = await _seed_link(real_database)

    row = await repo.load_for_visit(link_id)
    assert row is not None
    assert str(row["user_id"]) == owner
    assert str(row["workflow_id"]) == workflow_id
    assert row["node_id"] == AGENT_NODE_ID

    assert await repo.load_for_visit("junk") is None
    assert await repo.load_for_visit(str(uuid.uuid4())) is None

    await real_database.execute(
        "UPDATE shared_agent_links SET is_active = false WHERE id = $1", link_id)
    assert await repo.load_for_visit(link_id) is None
