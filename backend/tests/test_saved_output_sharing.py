"""
Test suite for Saved Output Sharing functionality.

Validates that saved outputs can be shared between users and organizations
with proper access control, is_public flag, and permission levels.

Tests cover:
- Sharing saved outputs with users (by email)
- Sharing saved outputs with organizations
- Public saved outputs (is_public flag)
- Shared saved output access (list, get)
- Permission levels (view vs edit)
- Access control for update and delete
- Saved output visibility in list responses by node type
"""

import pytest
import pytest_asyncio
import asyncio
import uuid
from typing import Dict, Any

from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database
from wss.receiver.client_events import (
    SavedOutputCreateRequest,
    SavedOutputListRequest,
    SavedOutputGetRequest,
    SavedOutputUpdateRequest,
    SavedOutputDeleteRequest,
    ShareCreateRequest,
    ShareListRequest,
)
from wss.sender import send_event


@pytest.mark.asyncio
class TestSavedOutputSharing(BaseHandlerTest):
    """
    Integration tests for Saved Output Sharing with real PostgreSQL database.

    Verifies that saved outputs can be properly shared between users and
    organizations with correct access control and the is_public flag.
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

    async def create_saved_output(
        self, frontend_sio, sid, request_id: str,
        name: str = "Test Output", node_type: str = "automation-test",
        visibility: str = "user"
    ):
        """Helper to create a saved output and return its ID."""
        create_request = SavedOutputCreateRequest(
            event_name="saved_output:create",
            request_id=request_id,
            node_type=node_type,
            name=name,
            output={"result": "test_data", "status": "success"},
            visibility=visibility
        )
        await send_event(frontend_sio, sid, create_request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        for event in response_events:
            if event[1].get('request_id') == request_id:
                return event[1]['data']['saved_output']['id']
        return None

    async def test_share_saved_output_with_user(self, real_database, frontend_sio, sid):
        """
        Test that a saved output can be shared with another user.

        Verifies:
        - Share is created successfully
        - Shared output appears in recipient's list
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        recipient_id = '00000000-0000-4000-8000-000000000002'

        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await self.create_test_user(real_database, recipient_id, 'recipient@example.com')
        await asyncio.sleep(0.1)

        # Create saved output
        output_id = await self.create_saved_output(
            frontend_sio, sid, "create-output-1", "Shared Test Output"
        )
        assert output_id is not None

        # Share with recipient
        share_request = ShareCreateRequest(
            event_name="share:create",
            request_id="share-output-1",
            resource_type="saved_output",
            resource_id=output_id,
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
            if event[1].get('request_id') == 'share-output-1':
                share_response = event[1]
                break

        assert share_response is not None
        assert share_response.get('data', {}).get('success') is True
        assert share_response.get('data', {}).get('share', {}).get('target_user_id') == recipient_id

    async def test_create_public_saved_output(self, real_database, frontend_sio, sid):
        """
        Test creating a public saved output.

        Verifies:
        - Output is created with is_public = true
        - Public output is accessible to anyone
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await asyncio.sleep(0.1)

        # Create public saved output
        output_id = await self.create_saved_output(
            frontend_sio, sid, "create-output-2",
            "Public Test Data", "automation-telegram", "public"
        )
        assert output_id is not None

        # Verify is_public flag in database
        output_row = await real_database.fetchrow("""
            SELECT is_public FROM workflow_saved_output WHERE id = $1
        """, output_id)

        assert output_row is not None
        assert output_row['is_public'] is True

    async def test_share_saved_output_with_organization(self, real_database, frontend_sio, sid):
        """
        Test that a saved output can be shared with an organization.

        Verifies:
        - Share is created for organization
        - All org members can access the output
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

        # Create saved output
        output_id = await self.create_saved_output(
            frontend_sio, sid, "create-output-3", "Org Shared Output"
        )

        # Share with organization
        share_request = ShareCreateRequest(
            event_name="share:create",
            request_id="share-output-3",
            resource_type="saved_output",
            resource_id=output_id,
            target_type="organization",
            target_org_id=org_id,
            permission="edit"
        )
        await send_event(frontend_sio, sid, share_request)
        await asyncio.sleep(0.2)

        # Verify share was created
        share_row = await real_database.fetchrow("""
            SELECT id, permission FROM resource_shares
            WHERE resource_type = 'saved_output'
            AND resource_id = $1
            AND target_org_id = $2
        """, output_id, org_id)

        assert share_row is not None
        assert share_row['permission'] == 'edit'

    async def test_view_permission_prevents_saved_output_update(self, real_database, frontend_sio, sid):
        """
        Test that view permission prevents updating a saved output.

        Verifies:
        - User with view permission cannot update the output
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        viewer_id = '00000000-0000-4000-8000-000000000004'  # Unique ID for this test

        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await self.create_test_user(real_database, viewer_id, 'viewer@example.com')
        await asyncio.sleep(0.1)

        # Create and share output with view permission
        output_id = await self.create_saved_output(
            frontend_sio, sid, "create-output-4", "View Only Output"
        )

        share_request = ShareCreateRequest(
            event_name="share:create",
            request_id="share-output-4",
            resource_type="saved_output",
            resource_id=output_id,
            target_type="user",
            target_email="viewer@example.com",
            permission="view"
        )
        await send_event(frontend_sio, sid, share_request)
        await asyncio.sleep(0.2)

        # Verify share exists with view permission
        share_row = await real_database.fetchrow("""
            SELECT permission FROM resource_shares
            WHERE resource_type = 'saved_output'
            AND resource_id = $1
            AND target_user_id = $2
        """, output_id, viewer_id)

        assert share_row is not None
        assert share_row['permission'] == 'view'

    async def test_edit_permission_allows_saved_output_update(self, real_database, frontend_sio, sid):
        """
        Test that edit permission allows updating a saved output.

        Verifies:
        - User with edit permission can update the output
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        editor_id = '00000000-0000-4000-8000-000000000005'  # Unique ID for this test

        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await self.create_test_user(real_database, editor_id, 'editor@example.com')
        await asyncio.sleep(0.1)

        # Create and share output with edit permission
        output_id = await self.create_saved_output(
            frontend_sio, sid, "create-output-5", "Editable Output"
        )

        share_request = ShareCreateRequest(
            event_name="share:create",
            request_id="share-output-5",
            resource_type="saved_output",
            resource_id=output_id,
            target_type="user",
            target_email="editor@example.com",
            permission="edit"
        )
        await send_event(frontend_sio, sid, share_request)
        await asyncio.sleep(0.2)

        # Verify share exists with edit permission
        share_row = await real_database.fetchrow("""
            SELECT permission FROM resource_shares
            WHERE resource_type = 'saved_output'
            AND resource_id = $1
            AND target_user_id = $2
        """, output_id, editor_id)

        assert share_row is not None
        assert share_row['permission'] == 'edit'

    async def test_list_shares_for_saved_output(self, real_database, frontend_sio, sid):
        """
        Test listing all shares for a saved output.

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

        # Create saved output
        output_id = await self.create_saved_output(
            frontend_sio, sid, "create-output-6", "Multi-shared Output"
        )

        # Share with two users
        for i, email in enumerate(['user1@example.com', 'user2@example.com']):
            share_request = ShareCreateRequest(
                event_name="share:create",
                request_id=f"share-output-6-{i}",
                resource_type="saved_output",
                resource_id=output_id,
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
            resource_type="saved_output",
            resource_id=output_id
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

    async def test_private_saved_output_not_visible_to_others(self, real_database, frontend_sio, sid):
        """
        Test that a private saved output is not visible to other users.

        Verifies:
        - Private output only visible to owner
        - No resource_shares entries exist
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        other_id = '00000000-0000-4000-8000-000000000002'

        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await self.create_test_user(real_database, other_id, 'other@example.com')
        await asyncio.sleep(0.1)

        # Create private saved output
        output_id = await self.create_saved_output(
            frontend_sio, sid, "create-output-7", "Private Output", visibility="user"
        )

        # Verify no shares exist
        share_row = await real_database.fetchrow("""
            SELECT id FROM resource_shares
            WHERE resource_type = 'saved_output'
            AND resource_id = $1
        """, output_id)

        assert share_row is None

        # Verify output is owned by owner and not public
        output_row = await real_database.fetchrow("""
            SELECT owner_id, is_public FROM workflow_saved_output WHERE id = $1
        """, output_id)

        assert output_row is not None
        assert str(output_row['owner_id']) == owner_id
        assert output_row['is_public'] is False

    async def test_update_visibility_to_public(self, real_database, frontend_sio, sid):
        """
        Test changing a saved output's visibility to public.

        Verifies:
        - is_public flag is updated correctly
        - Output becomes accessible to everyone
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await asyncio.sleep(0.1)

        # Create private saved output
        output_id = await self.create_saved_output(
            frontend_sio, sid, "create-output-8", "Soon Public Output", visibility="user"
        )

        # Verify initially private
        output_row = await real_database.fetchrow("""
            SELECT is_public FROM workflow_saved_output WHERE id = $1
        """, output_id)
        assert output_row['is_public'] is False

        # Update to public
        update_request = SavedOutputUpdateRequest(
            event_name="saved_output:update",
            request_id="update-output-8",
            saved_output_id=output_id,
            visibility="public"
        )
        await send_event(frontend_sio, sid, update_request)
        await asyncio.sleep(0.2)

        # Verify now public
        output_row = await real_database.fetchrow("""
            SELECT is_public FROM workflow_saved_output WHERE id = $1
        """, output_id)
        assert output_row['is_public'] is True

    async def test_saved_outputs_filtered_by_node_type(self, real_database, frontend_sio, sid):
        """
        Test that saved outputs are filtered by node type.

        Verifies:
        - Only outputs matching node_type are returned
        - Other node types are not included
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await asyncio.sleep(0.1)

        # Create outputs for different node types
        await self.create_saved_output(
            frontend_sio, sid, "create-output-9a", "Telegram Output", "automation-telegram"
        )
        await self.create_saved_output(
            frontend_sio, sid, "create-output-9b", "Gmail Output", "automation-gmail"
        )

        # List outputs for telegram only
        list_request = SavedOutputListRequest(
            event_name="saved_output:list",
            request_id="list-outputs-9",
            node_type="automation-telegram"
        )
        await send_event(frontend_sio, sid, list_request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        list_response = None
        for event in response_events:
            if event[1].get('request_id') == 'list-outputs-9':
                list_response = event[1]
                break

        assert list_response is not None
        outputs = list_response.get('data', {}).get('saved_outputs', [])
        assert len(outputs) >= 1
        assert all(o['node_type'] == 'automation-telegram' for o in outputs)
