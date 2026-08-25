"""
RLS / grant regression tests for resource_shares write hardening
(migration 20260604000000_harden_resource_shares_writes).

The pre-existing INSERT policy let any `authenticated` user (the role a browser Supabase
client runs as) forge a self-grant share row for a resource they don't own — a privilege
escalation amplified to credential exfiltration by run-as-owner. The fix REVOKES
INSERT/UPDATE/DELETE from `authenticated` and drops the permissive write policies; all
legitimate writes go through the backend service-role/postgres connection (which bypasses
RLS). These tests assert the grant/policy state directly (deterministic) and that the
backend write path still works.

We assert grant state via has_table_privilege rather than SET ROLE + a live INSERT: the
session-scoped test container's role membership is shared across the whole suite, which
makes runtime role-switching non-deterministic. has_table_privilege reads the catalog
and is the precise ground truth for what the migration changed.
"""

import uuid
import pytest



@pytest.mark.asyncio
async def test_authenticated_write_grants_revoked(postgres_db):
    """`authenticated` (the browser/PostgREST role) can no longer INSERT/UPDATE/DELETE
    resource_shares — closing the self-grant forgery. SELECT is intentionally kept."""
    conn = postgres_db
    has = lambda priv: conn.fetchval(
        "SELECT has_table_privilege('authenticated', 'public.resource_shares', $1)", priv
    )
    assert await has('INSERT') is False, "INSERT must be revoked from authenticated"
    assert await has('UPDATE') is False, "UPDATE must be revoked from authenticated"
    assert await has('DELETE') is False, "DELETE must be revoked from authenticated"
    assert await has('SELECT') is True, "SELECT must remain granted to authenticated"


@pytest.mark.asyncio
async def test_permissive_write_policies_dropped(postgres_db):
    """The old permissive write policies are gone, so RLS denies writes by default even
    if the grant were ever re-added."""
    conn = postgres_db
    rows = await conn.fetch(
        "SELECT policyname FROM pg_policies WHERE schemaname = 'public' AND tablename = 'resource_shares'"
    )
    names = {r["policyname"] for r in rows}
    assert "Users can create shares" not in names
    assert "Users can update own shares" not in names
    assert "Users can delete own shares" not in names
    # The service-role full-access policy is retained (backend writes).
    assert any("Service role" in n for n in names), f"service-role policy should remain: {names}"


@pytest.mark.asyncio
async def test_backend_role_can_still_create_shares(postgres_db):
    """The backend (postgres/service-role, bypassing RLS) can still create a legitimate
    share — the owner sharing their workflow with another user."""
    conn = postgres_db
    owner = str(uuid.uuid4())
    target = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    await conn.execute(
        "INSERT INTO auth.users (id, email) VALUES ($1, $2), ($3, $4) ON CONFLICT (id) DO NOTHING",
        owner, f"owner-{owner}@example.com", target, f"target-{target}@example.com",
    )
    await conn.execute(
        "INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at) "
        "VALUES ($1, $2, 'Owner Flow', '', '{}'::jsonb, '{}'::jsonb, NOW(), NOW())",
        workflow_id, owner,
    )
    await conn.execute(
        "INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by) "
        "VALUES ('workflow', $1, 'user', $2, 'edit', $3)",
        workflow_id, target, owner,
    )
    row = await conn.fetchrow(
        "SELECT permission FROM resource_shares WHERE resource_id = $1 AND target_user_id = $2",
        workflow_id, target,
    )
    assert row is not None and row["permission"] == "edit", "owner-created share must persist"
