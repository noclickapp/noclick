"""
Real-DB tests for shared Test Run links: SharedRunLinkRepo + GET
/api/public/run-link/{link_id} (utils/public_routes).

The link id is the capability and the endpoint is unauthenticated, so the
tests pin the 404 matrix (bad id, missing row, inactive link, deleted
workflow, ownership transfer) and the response shape — the snapshot must come
back as the dict that went in (jsonb codec round trip), never a string.
"""

import uuid
import pytest
from fastapi import HTTPException, Response

from tests.fixtures.real_db_fixture import real_database, test_user_id  # noqa: F401

SNAPSHOT = {
    "version": 1,
    "scenario": {
        "slug": "whatsapp",
        "name": "Direct lead",
        "nodeName": "WhatsApp",
        "provider": "whatsapp",
        "lead": {"title": "Casey Example", "meta": "message", "body": "hey — pricing?"},
        "events": [],
        "artifacts": None,
        "key": "whatsapp:direct-lead",
    },
    "rows": [
        {"kind": "tool", "id": "s1", "at": 0, "text": "Read the thread",
         "provider": "whatsapp", "status": "completed", "elapsed": 900},
    ],
    "artifacts": [{"provider": "whatsapp", "to": "Casey Example", "text": "Here's our pricing…"}],
    "failed": False,
    "providers": ["whatsapp"],
}


async def _seed(db, *, is_active=True, owner_still_owns=True):
    owner = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO auth.users (id, email, raw_user_meta_data) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
        owner, f"owner-{owner}@example.com", {"name": "Example Owner"},
    )
    row_owner = owner if owner_still_owns else str(uuid.uuid4())
    if not owner_still_owns:
        await db.execute(
            "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
            row_owner, f"new-{row_owner}@example.com",
        )
    await db.execute(
        "INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at) "
        "VALUES ($1, $2, 'Lead Flow', '', '{}'::jsonb, '{}'::jsonb, NOW(), NOW())",
        workflow_id, row_owner,
    )
    link_id = await db.fetchval(
        "INSERT INTO shared_run_links (user_id, workflow_id, title, snapshot, is_active) "
        "VALUES ($1, $2, 'Direct lead', $3, $4) RETURNING id",
        owner, workflow_id, SNAPSHOT, is_active,
    )
    return str(link_id), workflow_id, owner


async def _expect_404(link_id):
    from utils.public_routes import get_run_link

    with pytest.raises(HTTPException) as exc:
        await get_run_link(link_id, Response())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_happy_path_round_trip(real_database):
    from utils.public_routes import get_run_link

    link_id, _, _ = await _seed(real_database)
    resp = Response()
    payload = await get_run_link(link_id, resp)

    assert payload["title"] == "Direct lead"
    assert payload["workflow_name"] == "Lead Flow"
    assert payload["created_at"]
    # jsonb codec round trip: the snapshot is the DICT that went in.
    assert payload["snapshot"] == SNAPSHOT
    assert isinstance(payload["snapshot"]["rows"], list)
    # Capability URL — never cacheable.
    assert resp.headers["Cache-Control"] == "no-store"
    # Nothing id-shaped leaves the endpoint.
    assert set(payload.keys()) == {"title", "workflow_name", "created_at", "snapshot"}


@pytest.mark.asyncio
async def test_not_found_matrix(real_database):
    # Garbage id and unknown UUID.
    await _expect_404("not-a-uuid")
    await _expect_404(str(uuid.uuid4()))

    # Inactive link.
    inactive, _, _ = await _seed(real_database, is_active=False)
    await _expect_404(inactive)

    # Minting user no longer owns the workflow (ownership-transfer defense).
    transferred, _, _ = await _seed(real_database, owner_still_owns=False)
    await _expect_404(transferred)

    # Deleted workflow.
    gone, workflow_id, _ = await _seed(real_database)
    await real_database.execute(
        "UPDATE workflows SET deleted_at = NOW() WHERE id = $1", workflow_id
    )
    await _expect_404(gone)


@pytest.mark.asyncio
async def test_repo_create_stores_dict_snapshot(real_database):
    """SharedRunLinkRepo.create must land jsonb an OBJECT at rest — a
    double-encoded string scalar is the the structured-value regression fix corruption class."""
    from repositories.shared_run_link import SharedRunLinkRepo

    link_id, workflow_id, owner = await _seed(real_database)
    repo = SharedRunLinkRepo(real_database.pool)
    new_id = await repo.create(owner, workflow_id, "Second share", SNAPSHOT)
    jtype = await real_database.fetchval(
        "SELECT jsonb_typeof(snapshot) FROM shared_run_links WHERE id = $1",
        uuid.UUID(new_id),
    )
    assert jtype == "object"

    loaded = await repo.load_for_view(new_id)
    assert loaded is not None
    assert loaded["title"] == "Second share"
