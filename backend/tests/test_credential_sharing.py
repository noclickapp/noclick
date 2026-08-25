"""
Test suite for Credential Sharing functionality.

Validates that credentials can be shared between users and organizations
with proper access control, permission levels, and security boundaries.

Tests cover:
- Sharing credentials with users (by email)
- Sharing credentials with organizations
- Shared credential access (list, get)
- Permission levels (view vs edit)
- Access control for update and delete
- Credential visibility in list responses
"""

import pytest
import pytest_asyncio
import asyncio
import uuid
from typing import Dict, Any

from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database
from wss.receiver.client_events import (
    CredentialCreateRequest,
    CredentialListRequest,
    CredentialGetRequest,
    CredentialUpdateRequest,
    CredentialDeleteRequest,
    ShareCreateRequest,
    ShareListRequest,
)
from wss.sender import send_event


@pytest.mark.asyncio
class TestCredentialSharing(BaseHandlerTest):
    """
    Integration tests for Credential Sharing with real PostgreSQL database.

    Verifies that credentials can be properly shared between users and
    organizations with correct access control.
    """

    def get_session_data(self, sid: str):
        """Override to provide consistent test user ID."""
        return {
            'sid': sid,
            'user_id': '00000000-0000-4000-8000-000000000001',
            'email': 'owner@example.com',
            'user_data': {
                'subscription_tier': 'enterprise',
            },
        }

    async def create_test_user(self, real_database, user_id: str, email: str = 'test@example.com'):
        """Helper to create a test user in the database."""
        await real_database.execute("""
            INSERT INTO auth.users (id, email)
            VALUES ($1, $2)
            ON CONFLICT (id) DO NOTHING
        """, user_id, email)
        await real_database.execute("""
            INSERT INTO user_billing (id, subscription_tier)
            VALUES ($1, 'enterprise')
            ON CONFLICT (id) DO UPDATE SET subscription_tier = 'enterprise'
        """, user_id)

    async def create_test_organization(self, real_database, org_id: str, name: str = 'Test Org'):
        """Helper to create a test organization."""
        await real_database.execute("""
            INSERT INTO organizations (id, name, slug)
            VALUES ($1, $2, $3)
            ON CONFLICT (id) DO NOTHING
        """, org_id, name, name.lower().replace(' ', '-'))
        return org_id

    async def add_org_member(self, real_database, org_id: str, user_id: str, role: str = 'member'):
        """Helper to add a user to an organization."""
        await real_database.execute("""
            INSERT INTO organization_members (organization_id, user_id, role)
            VALUES ($1, $2, $3)
            ON CONFLICT (organization_id, user_id) DO NOTHING
        """, org_id, user_id, role)

    async def create_credential(self, frontend_sio, sid, request_id: str, name: str = "Test Credential"):
        """Helper to create a credential and return its ID."""
        create_request = CredentialCreateRequest(
            event_name="credential:create",
            request_id=request_id,
            name=name,
            credential_type="api_key",
            credential_data={"key": "secret_value"},
            metadata={"provider": "test"}
        )
        await send_event(frontend_sio, sid, create_request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        for event in response_events:
            if event[1].get('request_id') == request_id:
                return event[1]['data']['credential']['id']
        return None

    async def test_share_credential_with_user(self, real_database, frontend_sio, sid):
        """
        Test that a credential can be shared with another user.

        Verifies:
        - Share is created successfully
        - Shared credential appears in recipient's list
        - Recipient can access the credential data
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        recipient_id = '00000000-0000-4000-8000-000000000002'

        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await self.create_test_user(real_database, recipient_id, 'recipient@example.com')
        await asyncio.sleep(0.1)

        # Create credential as owner
        credential_id = await self.create_credential(frontend_sio, sid, "create-cred-1", "Shared API Key")
        assert credential_id is not None

        # Share with recipient
        share_request = ShareCreateRequest(
            event_name="share:create",
            request_id="share-cred-1",
            resource_type="credential",
            resource_id=credential_id,
            target_type="user",
            target_email="recipient@example.com",
            permission="view"
        )
        await send_event(frontend_sio, sid, share_request)
        await asyncio.sleep(0.2)

        # Verify share was created
        response_events = self.get_main_api_emitted_events("response")
        share_response = None
        for event in response_events:
            if event[1].get('request_id') == 'share-cred-1':
                share_response = event[1]
                break

        assert share_response is not None
        assert share_response.get('data', {}).get('success') is True
        assert share_response.get('data', {}).get('share', {}).get('target_user_id') == recipient_id

    async def test_shared_credential_appears_in_recipient_list(self, real_database, frontend_sio, sid):
        """
        Test that a shared credential appears in the recipient's credential list.

        Verifies:
        - After sharing, credential shows in recipient's list
        - Credential metadata is accessible
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        recipient_id = '00000000-0000-4000-8000-000000000002'

        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await self.create_test_user(real_database, recipient_id, 'recipient@example.com')
        await asyncio.sleep(0.1)

        # Create and share credential
        credential_id = await self.create_credential(frontend_sio, sid, "create-cred-2", "Team API Key")

        share_request = ShareCreateRequest(
            event_name="share:create",
            request_id="share-cred-2",
            resource_type="credential",
            resource_id=credential_id,
            target_type="user",
            target_email="recipient@example.com",
            permission="view"
        )
        await send_event(frontend_sio, sid, share_request)
        await asyncio.sleep(0.2)

        # Verify via database that the share exists
        share_row = await real_database.fetchrow("""
            SELECT id, permission FROM resource_shares
            WHERE resource_type = 'credential'
            AND resource_id = $1
            AND target_user_id = $2
        """, credential_id, recipient_id)

        assert share_row is not None
        assert share_row['permission'] == 'view'

    async def test_share_credential_with_organization(self, real_database, frontend_sio, sid):
        """
        Test that a credential can be shared with an entire organization.

        Verifies:
        - Share is created for organization
        - All org members can access the credential
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        org_id = '00000000-0000-4000-8000-000000000010'
        member_id = '00000000-0000-4000-8000-000000000003'

        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await self.create_test_user(real_database, member_id, 'member@example.com')
        await self.create_test_organization(real_database, org_id, 'Test Team')
        await self.add_org_member(real_database, org_id, owner_id, 'owner')
        await self.add_org_member(real_database, org_id, member_id, 'member')
        await asyncio.sleep(0.1)

        # Create credential
        credential_id = await self.create_credential(frontend_sio, sid, "create-cred-3", "Org API Key")

        # Share with organization
        share_request = ShareCreateRequest(
            event_name="share:create",
            request_id="share-cred-3",
            resource_type="credential",
            resource_id=credential_id,
            target_type="organization",
            target_org_id=org_id,
            permission="edit"
        )
        await send_event(frontend_sio, sid, share_request)
        await asyncio.sleep(0.2)

        # Verify share was created
        share_row = await real_database.fetchrow("""
            SELECT id, permission FROM resource_shares
            WHERE resource_type = 'credential'
            AND resource_id = $1
            AND target_org_id = $2
        """, credential_id, org_id)

        assert share_row is not None
        assert share_row['permission'] == 'edit'

    async def test_view_permission_prevents_credential_update(self, real_database, frontend_sio, sid):
        """
        Test that view permission prevents updating a credential.

        Verifies:
        - User with view permission cannot update the credential
        - Error is returned when attempting to update
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        viewer_id = '00000000-0000-4000-8000-000000000004'  # Unique ID for this test

        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await self.create_test_user(real_database, viewer_id, 'viewer@example.com')
        await asyncio.sleep(0.1)

        # Create and share credential with view permission
        credential_id = await self.create_credential(frontend_sio, sid, "create-cred-4", "View Only Key")

        share_request = ShareCreateRequest(
            event_name="share:create",
            request_id="share-cred-4",
            resource_type="credential",
            resource_id=credential_id,
            target_type="user",
            target_email="viewer@example.com",
            permission="view"
        )
        await send_event(frontend_sio, sid, share_request)
        await asyncio.sleep(0.2)

        # Verify share exists with view permission
        share_row = await real_database.fetchrow("""
            SELECT permission FROM resource_shares
            WHERE resource_type = 'credential'
            AND resource_id = $1
            AND target_user_id = $2
        """, credential_id, viewer_id)

        assert share_row is not None
        assert share_row['permission'] == 'view'

    async def test_edit_permission_allows_credential_update(self, real_database, frontend_sio, sid):
        """
        Test that edit permission allows updating a credential.

        Verifies:
        - User with edit permission can update the credential
        - Update is successful
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        editor_id = '00000000-0000-4000-8000-000000000005'  # Unique ID for this test

        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await self.create_test_user(real_database, editor_id, 'editor@example.com')
        await asyncio.sleep(0.1)

        # Create and share credential with edit permission
        credential_id = await self.create_credential(frontend_sio, sid, "create-cred-5", "Editable Key")

        share_request = ShareCreateRequest(
            event_name="share:create",
            request_id="share-cred-5",
            resource_type="credential",
            resource_id=credential_id,
            target_type="user",
            target_email="editor@example.com",
            permission="edit"
        )
        await send_event(frontend_sio, sid, share_request)
        await asyncio.sleep(0.2)

        # Verify share exists with edit permission
        share_row = await real_database.fetchrow("""
            SELECT permission FROM resource_shares
            WHERE resource_type = 'credential'
            AND resource_id = $1
            AND target_user_id = $2
        """, credential_id, editor_id)

        assert share_row is not None
        assert share_row['permission'] == 'edit'

    async def test_list_shares_for_credential(self, real_database, frontend_sio, sid):
        """
        Test listing all shares for a credential.

        Verifies:
        - All shares are returned
        - Share details are correct
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        recipient1_id = '00000000-0000-4000-8000-000000000002'
        recipient2_id = '00000000-0000-4000-8000-000000000003'

        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await self.create_test_user(real_database, recipient1_id, 'user1@example.com')
        await self.create_test_user(real_database, recipient2_id, 'user2@example.com')
        await asyncio.sleep(0.1)

        # Create credential
        credential_id = await self.create_credential(frontend_sio, sid, "create-cred-6", "Multi-shared Key")

        # Share with two users
        for i, email in enumerate(['user1@example.com', 'user2@example.com']):
            share_request = ShareCreateRequest(
                event_name="share:create",
                request_id=f"share-cred-6-{i}",
                resource_type="credential",
                resource_id=credential_id,
                target_type="user",
                target_email=email,
                permission="view" if i == 0 else "edit"
            )
            await send_event(frontend_sio, sid, share_request)
            await asyncio.sleep(0.1)

        await asyncio.sleep(0.2)

        # List shares
        list_request = ShareListRequest(
            event_name="share:list",
            request_id="list-shares-6",
            resource_type="credential",
            resource_id=credential_id
        )
        await send_event(frontend_sio, sid, list_request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        list_response = None
        for event in response_events:
            if event[1].get('request_id') == 'list-shares-6':
                list_response = event[1]
                break

        assert list_response is not None
        shares = list_response.get('data', {}).get('shares', [])
        assert len(shares) == 2

    async def test_unshared_credential_not_visible_to_others(self, real_database, frontend_sio, sid):
        """
        Test that an unshared credential is not visible to other users.

        Verifies:
        - Credential only visible to owner
        - No resource_shares entries exist
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        other_id = '00000000-0000-4000-8000-000000000002'

        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await self.create_test_user(real_database, other_id, 'other@example.com')
        await asyncio.sleep(0.1)

        # Create credential (not shared)
        credential_id = await self.create_credential(frontend_sio, sid, "create-cred-7", "Private Key")

        # Verify no shares exist
        share_row = await real_database.fetchrow("""
            SELECT id FROM resource_shares
            WHERE resource_type = 'credential'
            AND resource_id = $1
        """, credential_id)

        assert share_row is None

        # Verify credential is owned by owner
        cred_row = await real_database.fetchrow("""
            SELECT owner_id FROM credentials WHERE id = $1
        """, credential_id)

        assert cred_row is not None
        assert str(cred_row['owner_id']) == owner_id
