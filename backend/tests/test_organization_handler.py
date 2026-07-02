"""
Tests for OrganizationHandler — specifically the is_primary context fixes.

Verifies that create_organization, accept_invite, and remove_member all
correctly manage the is_primary flag so users land in the right billing context
and are not incorrectly subject to free-tier plan limits.
"""

import pytest
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch


def _make_pool(conn):
    """Build a pool mock where `async with pool.acquire() as c` yields conn."""
    pool = MagicMock()

    @asynccontextmanager
    async def fake_acquire():
        yield conn

    pool.acquire = fake_acquire
    return pool


@asynccontextmanager
async def _fake_transaction():
    yield


def _conn_with_side_effects(fetchrow_values, fetchval_values=None):
    """Build an AsyncMock conn with preset fetchrow/fetchval sequences."""
    conn = AsyncMock()
    conn.fetchrow.side_effect = list(fetchrow_values)
    if fetchval_values is not None:
        conn.fetchval.side_effect = list(fetchval_values)
    # asyncpg's transaction() is SYNC and returns an async CM.
    conn.transaction = MagicMock(side_effect=_fake_transaction)
    return conn


class TestCreateOrganizationIsPrimary:
    """create_organization must switch the creator's primary context to the new org."""

    @pytest.mark.asyncio
    async def test_create_org_sets_is_primary_on_new_org(self):
        """Creator's existing is_primary is cleared and the new org is set as primary."""
        from wss.handlers.organization_handler import OrganizationHandler

        user_id = str(uuid.uuid4())
        org_id = uuid.uuid4()

        org_row = {
            'id': org_id, 'name': 'Test Org', 'slug': 'test-org',
            'subscription_tier': 'enterprise', 'sso_enabled': False,
            'sso_domain': None, 'created_at': None, 'updated_at': None,
        }

        conn = _conn_with_side_effects(
            fetchrow_values=[org_row],       # INSERT organizations RETURNING
            fetchval_values=[None],          # slug uniqueness check
        )

        pool = _make_pool(conn)

        sio = AsyncMock()
        sio.get_session = AsyncMock(return_value={
            'user_id': user_id,
            'user_data': {'subscription_tier': 'free'},
        })

        handler = OrganizationHandler(sio)

        # Patch check_organization_limit so we don't need to mock its DB calls
        with patch('wss.handlers.organization_handler.check_organization_limit',
                   return_value=(True, None)):
            with patch.object(handler, 'get_pool', return_value=pool):
                await handler.create_organization('sid', {
                    'request_id': 'req-1',
                    'name': 'Test Org',
                })

        executed = [str(c.args[0]) for c in conn.execute.call_args_list]

        # Must clear previous is_primary flags
        assert any(
            'is_primary = false' in q.lower() and 'organization_members' in q.lower()
            for q in executed
        ), f"Expected is_primary clear. Got queries: {executed}"

        # Must insert with is_primary = true
        inserts = [q for q in executed if 'insert into organization_members' in q.lower()]
        assert inserts, f"No INSERT into organization_members found. Queries: {executed}"
        assert 'is_primary' in inserts[0].lower(), \
            f"INSERT must include is_primary. Got: {inserts[0]}"

    @pytest.mark.asyncio
    async def test_create_org_returns_new_org_id(self):
        """Response includes the new org's id on success."""
        from wss.handlers.organization_handler import OrganizationHandler

        user_id = str(uuid.uuid4())
        org_id = uuid.uuid4()
        org_row = {
            'id': org_id, 'name': 'My Org', 'slug': 'my-org',
            'subscription_tier': 'free', 'sso_enabled': False,
            'sso_domain': None, 'created_at': None, 'updated_at': None,
        }

        conn = _conn_with_side_effects(fetchrow_values=[org_row], fetchval_values=[None])
        pool = _make_pool(conn)

        sio = AsyncMock()
        sio.get_session = AsyncMock(return_value={
            'user_id': user_id,
            'user_data': {'subscription_tier': 'free'},
        })

        handler = OrganizationHandler(sio)
        with patch('wss.handlers.organization_handler.check_organization_limit',
                   return_value=(True, None)):
            with patch.object(handler, 'get_pool', return_value=pool):
                await handler.create_organization('sid', {'request_id': 'r2', 'name': 'My Org'})

        sio.emit.assert_called_once()
        emit_data = sio.emit.call_args[0][1]
        assert emit_data.get('error') is None, f"Unexpected error: {emit_data.get('error')}"
        assert emit_data['data']['organization']['id'] == str(org_id)


class TestAcceptInviteIsPrimary:
    """accept_invite must switch the accepted user to the joined org context."""

    @pytest.mark.asyncio
    async def test_accept_invite_sets_is_primary_on_joined_org(self):
        """Existing is_primary is cleared and the joined org is set as primary."""
        from wss.handlers.organization_handler import OrganizationHandler

        user_id = str(uuid.uuid4())
        org_id = uuid.uuid4()
        invite_row = {
            'id': uuid.uuid4(),
            'organization_id': org_id,
            'email': 'test@example.com',
            'role': 'member',
            'org_name': 'Enterprise Org',
        }
        limit_row = {
            'subscription_tier': 'enterprise',
            'is_personal_workspace': False,
            'member_count': 2,
            'pending_invite_count': 0,
        }

        conn = _conn_with_side_effects(
            fetchrow_values=[
                invite_row,   # get invite by token
                limit_row,    # _check_member_limit
            ],
            fetchval_values=[None],  # existing membership check (None = not a member)
        )
        pool = _make_pool(conn)

        sio = AsyncMock()
        sio.get_session = AsyncMock(return_value={
            'user_id': user_id,
            'user_data': {'email': 'test@example.com', 'subscription_tier': 'free'},
        })

        handler = OrganizationHandler(sio)
        with patch.object(handler, 'get_pool', return_value=pool):
            await handler.accept_invite('sid', {'request_id': 'req-3', 'token': 'tok-abc'})

        executed = [str(c.args[0]) for c in conn.execute.call_args_list]

        assert any(
            'is_primary = false' in q.lower() and 'organization_members' in q.lower()
            for q in executed
        ), f"Expected is_primary clear. Got queries: {executed}"

        inserts = [q for q in executed if 'insert into organization_members' in q.lower()]
        assert inserts, f"No INSERT into organization_members found. Queries: {executed}"
        assert 'is_primary' in inserts[0].lower(), \
            f"INSERT must include is_primary. Got: {inserts[0]}"

    @pytest.mark.asyncio
    async def test_accept_invite_returns_org_id(self):
        """Response includes the joined org id and success flag."""
        from wss.handlers.organization_handler import OrganizationHandler

        user_id = str(uuid.uuid4())
        org_id = uuid.uuid4()
        invite_row = {
            'id': uuid.uuid4(), 'organization_id': org_id,
            'email': 'user@example.com', 'role': 'member', 'org_name': 'Acme',
        }
        limit_row = {
            'subscription_tier': 'enterprise', 'is_personal_workspace': False,
            'member_count': 1, 'pending_invite_count': 0,
        }

        conn = _conn_with_side_effects(
            fetchrow_values=[invite_row, limit_row],
            fetchval_values=[None],  # existing membership check
        )
        pool = _make_pool(conn)

        sio = AsyncMock()
        sio.get_session = AsyncMock(return_value={
            'user_id': user_id,
            'user_data': {'email': 'user@example.com', 'subscription_tier': 'free'},
        })

        handler = OrganizationHandler(sio)
        with patch.object(handler, 'get_pool', return_value=pool):
            await handler.accept_invite('sid', {'request_id': 'req-4', 'token': 'tok'})

        sio.emit.assert_called_once()
        emit_data = sio.emit.call_args[0][1]
        assert emit_data.get('error') is None, f"Unexpected error: {emit_data.get('error')}"
        assert emit_data['data']['success'] is True
        assert emit_data['data']['organization_id'] == str(org_id)


class TestRemoveMemberIsPrimary:
    """remove_member must restore personal workspace as primary when the removed user's
    primary org was the one they're being removed from."""

    @pytest.mark.asyncio
    async def test_remove_member_restores_personal_workspace_primary(self):
        """After removal, an UPDATE restores is_primary on the user's personal workspace
        (conditional — only if no primary exists)."""
        from wss.handlers.organization_handler import OrganizationHandler

        admin_id = str(uuid.uuid4())
        target_id = str(uuid.uuid4())
        org_id = str(uuid.uuid4())

        conn = _conn_with_side_effects(fetchrow_values=[
            # _get_user_org_membership for admin check
            {'id': uuid.uuid4(), 'role': 'admin', 'joined_via': 'invite', 'created_at': None},
            # _get_user_org_membership for target
            {'id': uuid.uuid4(), 'role': 'member', 'joined_via': 'invite', 'created_at': None},
        ])
        pool = _make_pool(conn)

        sio = AsyncMock()
        sio.get_session = AsyncMock(return_value={
            'user_id': admin_id,
            'user_data': {'subscription_tier': 'enterprise'},
        })

        handler = OrganizationHandler(sio)
        with patch.object(handler, 'get_pool', return_value=pool):
            await handler.remove_member('sid', {
                'request_id': 'req-5',
                'organization_id': org_id,
                'user_id': target_id,   # handler reads data.get('user_id')
            })

        executed = [str(c.args[0]) for c in conn.execute.call_args_list]

        assert any('delete from organization_members' in q.lower() for q in executed), \
            f"Must delete membership. Got: {executed}"

        restore = [
            q for q in executed
            if 'is_primary = true' in q.lower() and 'is_personal_workspace' in q.lower()
        ]
        assert restore, \
            f"Must restore personal workspace as primary. Got queries: {executed}"

    @pytest.mark.asyncio
    async def test_remove_member_returns_success(self):
        """remove_member sends a success response."""
        from wss.handlers.organization_handler import OrganizationHandler

        admin_id = str(uuid.uuid4())
        target_id = str(uuid.uuid4())
        org_id = str(uuid.uuid4())

        conn = _conn_with_side_effects(fetchrow_values=[
            {'id': uuid.uuid4(), 'role': 'owner', 'joined_via': 'creator', 'created_at': None},
            {'id': uuid.uuid4(), 'role': 'member', 'joined_via': 'invite', 'created_at': None},
        ])
        pool = _make_pool(conn)

        sio = AsyncMock()
        sio.get_session = AsyncMock(return_value={
            'user_id': admin_id,
            'user_data': {'subscription_tier': 'enterprise'},
        })

        handler = OrganizationHandler(sio)
        with patch.object(handler, 'get_pool', return_value=pool):
            await handler.remove_member('sid', {
                'request_id': 'req-6',
                'organization_id': org_id,
                'user_id': target_id,
            })

        sio.emit.assert_called_once()
        emit_data = sio.emit.call_args[0][1]
        assert emit_data.get('error') is None, f"Unexpected error: {emit_data.get('error')}"
        assert emit_data['data']['success'] is True
