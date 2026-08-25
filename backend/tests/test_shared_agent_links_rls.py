"""
RLS / grant regression tests for shared_agent_links
(migration 20260710000000_shared_agent_links).

The row id IS the public capability for /a/{link_id} agent chat pages, so the
table must be backend-only: RLS enabled with NO policies + all API-role grants
revoked. A PostgREST-readable row id
would let anyone enumerate live share links. Also pins the widened
workflow_executions.trigger_source CHECK ('shared_agent').
"""

import uuid
import pytest



@pytest.mark.asyncio
async def test_api_role_grants_revoked(postgres_db):
    """Neither anon nor authenticated may touch shared_agent_links at all —
    the capability id must never be readable through PostgREST."""
    conn = postgres_db
    for role in ("anon", "authenticated"):
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            allowed = await conn.fetchval(
                "SELECT has_table_privilege($1, 'public.shared_agent_links', $2)",
                role, priv,
            )
            assert allowed is False, f"{priv} must be revoked from {role}"


@pytest.mark.asyncio
async def test_rls_enabled_with_no_policies(postgres_db):
    """RLS on + zero policies: even a re-added grant would deny by default."""
    conn = postgres_db
    rls_on = await conn.fetchval(
        "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.shared_agent_links'::regclass"
    )
    assert rls_on is True
    policy_count = await conn.fetchval(
        "SELECT count(*) FROM pg_policies WHERE schemaname = 'public' AND tablename = 'shared_agent_links'"
    )
    assert policy_count == 0, "capability table must have NO RLS policies"


@pytest.mark.asyncio
async def test_backend_mint_is_idempotent_per_node(postgres_db):
    """UNIQUE(workflow_id, node_id): a second mint conflicts onto the same row
    (same capability id), matching SharedAgentLinkRepo.get_or_create."""
    conn = postgres_db
    owner = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    await conn.execute(
        "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
        owner, f"owner-{owner}@example.com",
    )
    await conn.execute(
        "INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at) "
        "VALUES ($1, $2, 'Agent Flow', '', '{}'::jsonb, '{}'::jsonb, NOW(), NOW())",
        workflow_id, owner,
    )
    first = await conn.fetchval(
        "INSERT INTO shared_agent_links (user_id, workflow_id, node_id) VALUES ($1, $2, 'agent-1') RETURNING id",
        owner, workflow_id,
    )
    second = await conn.fetchval(
        "INSERT INTO shared_agent_links (user_id, workflow_id, node_id) VALUES ($1, $2, 'agent-1') "
        "ON CONFLICT (workflow_id, node_id) DO UPDATE SET node_id = EXCLUDED.node_id RETURNING id",
        owner, workflow_id,
    )
    assert str(first) == str(second), "re-mint must return the existing capability"


@pytest.mark.asyncio
async def test_trigger_source_check_accepts_shared_agent(postgres_db):
    """The widened CHECK admits 'shared_agent' (and still rejects junk)."""
    conn = postgres_db
    owner = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    await conn.execute(
        "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
        owner, f"owner-{owner}@example.com",
    )
    await conn.execute(
        "INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at) "
        "VALUES ($1, $2, 'Agent Flow', '', '{}'::jsonb, '{}'::jsonb, NOW(), NOW())",
        workflow_id, owner,
    )
    await conn.execute(
        "INSERT INTO workflow_executions (id, workflow_id, user_id, status, trigger_source) "
        "VALUES ($1, $2, $3, 'running', 'shared_agent')",
        str(uuid.uuid4()), workflow_id, owner,
    )
    with pytest.raises(Exception, match="trigger_source"):
        await conn.execute(
            "INSERT INTO workflow_executions (id, workflow_id, user_id, status, trigger_source) "
            "VALUES ($1, $2, $3, 'running', 'bogus_source')",
            str(uuid.uuid4()), workflow_id, owner,
        )
