"""
Tests for OrgRepo.resolve_scope_org_id — the explicit browser-scope resolver that
makes workflow:list / workflow_folder:get_tree immune to the is_primary org-switch
race. The browser switches orgs optimistically (context flips before the
organization:switch round-trip lands), so a data request fired right after a switch
would otherwise read a stale active context and serve the previous org's folders /
workflows into the new scope's cache. Passing the scope explicitly fixes it by
construction. See frontend/app/lib/workflowBrowserStore.ts.
"""

import pytest
import uuid
from unittest.mock import AsyncMock

from repositories.organization import OrgRepo


def _conn(*, primary_org=None, is_member=False):
    conn = AsyncMock()
    conn.fetchrow.return_value = {'organization_id': primary_org} if primary_org else None
    conn.fetchval.return_value = 1 if is_member else None
    return conn


@pytest.mark.asyncio
async def test_none_falls_back_to_active_context():
    """scope_org_id=None → non-browser/legacy caller: use the active (is_primary) org."""
    org = uuid.uuid4()
    repo = OrgRepo(AsyncMock())
    assert await repo.resolve_scope_org_id(_conn(primary_org=org), str(uuid.uuid4()), None) == str(org)


@pytest.mark.asyncio
async def test_empty_string_is_explicit_personal():
    """scope_org_id='' → personal context, WITHOUT ever reading the active context."""
    repo = OrgRepo(AsyncMock())
    conn = _conn(primary_org=uuid.uuid4())  # a primary org exists...
    assert await repo.resolve_scope_org_id(conn, str(uuid.uuid4()), "") is None  # ...but personal is explicit
    conn.fetchrow.assert_not_called()  # never consulted is_primary


@pytest.mark.asyncio
async def test_org_uuid_with_membership_returns_that_org_regardless_of_active():
    """scope_org_id='<uuid>' + member → that org even when the active context is a DIFFERENT org."""
    org = str(uuid.uuid4())
    repo = OrgRepo(AsyncMock())
    conn = _conn(primary_org=uuid.uuid4(), is_member=True)  # active context is some other org
    assert await repo.resolve_scope_org_id(conn, str(uuid.uuid4()), org) == org


@pytest.mark.asyncio
async def test_non_member_scope_falls_back_to_active_context_not_raise():
    """A stale/forged org scope must NOT read that org's data — but it also must NOT
    raise (the client persists org_context in IndexedDB, so a user removed from an
    org legitimately requests a stale scope on the next load; erroring blanked the
    whole browser). It resolves as the active context instead."""
    repo = OrgRepo(AsyncMock())
    # non-member + no active org → personal (None), NOT the requested org, NOT an error
    assert await repo.resolve_scope_org_id(_conn(is_member=False), str(uuid.uuid4()), str(uuid.uuid4())) is None
    # non-member but a valid active org exists → that active org, never the requested one
    active = uuid.uuid4()
    got = await repo.resolve_scope_org_id(_conn(primary_org=active, is_member=False), str(uuid.uuid4()), str(uuid.uuid4()))
    assert got == str(active)
