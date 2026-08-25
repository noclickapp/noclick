"""
Test suite for ShareHandler with real PostgreSQL database.

Validates resource sharing functionality including:
- Creating shares for users (existing and pending invites)
- Creating shares for organizations
- Upsert behavior when share already exists
- Listing shares for a resource
- Updating share permissions
- Deleting shares
- Listing resources shared with the current user
- Permission checks (only owner/admin can manage shares)
"""

import pytest
import pytest_asyncio
import asyncio
import uuid
from typing import Dict, Any

from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database
from wss.receiver.client_events import (
    ShareCreateRequest,
    ShareListRequest,
    ShareUpdateRequest,
    ShareDeleteRequest,
    ShareListSharedWithMeRequest,
    ResourceForkRequest,
)
from wss.sender import send_event


@pytest.mark.asyncio
class TestShareHandler(BaseHandlerTest):
    """
    Integration tests for ShareHandler with real PostgreSQL database.

    Tests the complete share lifecycle: create, list, update, delete.
    Uses real database to verify schema constraints and SQL queries.
    """

    def get_session_data(self, sid: str) -> Dict[str, Any]:
        """Override to provide consistent test user ID and email."""
        return {
            'sid': sid,
            'user_id': '00000000-0000-4000-8000-000000000001',
            'email': 'share-test@example.com',
            'user_data': {
                'email': 'share-test@example.com',
                'subscription_tier': 'enterprise',
            },
        }

    async def create_test_user(self, real_database, user_id: str, email: str):
        """Helper to create a test user in the database."""
        await real_database.execute("""
            INSERT INTO auth.users (id, email)
            VALUES ($1, $2)
            ON CONFLICT (id) DO NOTHING
        """, user_id, email)

    async def create_test_organization(self, real_database, org_id: str, name: str, owner_id: str):
        """Helper to create a test organization with owner."""
        # Create org
        await real_database.execute("""
            INSERT INTO organizations (id, name, slug)
            VALUES ($1, $2, $3)
            ON CONFLICT (id) DO NOTHING
        """, org_id, name, name.lower().replace(' ', '-'))

        # Add owner membership
        await real_database.execute("""
            INSERT INTO organization_members (organization_id, user_id, role)
            VALUES ($1, $2, 'owner')
            ON CONFLICT (organization_id, user_id) DO NOTHING
        """, org_id, owner_id)

    async def create_test_workflow(self, real_database, workflow_id: str, owner_id: str, name: str, org_id: str = None):
        """Helper to create a test workflow."""
        await real_database.execute("""
            INSERT INTO workflows (id, owner_id, organization_id, name, description, workflow, permissions, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
            ON CONFLICT (id) DO NOTHING
        """, workflow_id, owner_id, org_id, name, "Test workflow", {}, {})

    async def create_test_folder(self, real_database, folder_id: str, owner_id: str, name: str, org_id: str = None):
        """Helper to create a test workflow folder."""
        await real_database.execute("""
            INSERT INTO workflow_folders (id, owner_id, organization_id, name, description, path, depth, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, 0, NOW(), NOW())
            ON CONFLICT (id) DO NOTHING
        """, folder_id, owner_id, org_id, name, "Test folder", f"/{folder_id}/")

    async def create_test_database(self, real_database, table_id: str, owner_id: str, title: str, org_id: str = None, create_table: bool = False):
        """Helper to create a test database/table.

        Args:
            create_table: If True, also creates the actual table in user_tables schema with a 'name' column for testing.
        """
        schema_def = {"columns": [{"name": "name", "type": "text"}]} if create_table else {"columns": []}

        await real_database.execute("""
            INSERT INTO user_tables_metadata (id, owner_id, organization_id, title, description, virtual_table_name, schema_definition, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
            ON CONFLICT (id) DO NOTHING
        """, table_id, owner_id, org_id, title, "Test database", f"table_{table_id[:8]}", schema_def)

        if create_table:
            # Also create the actual table in user_tables schema
            await real_database.execute(f"""
                CREATE TABLE IF NOT EXISTS user_tables."{table_id}" (
                    id SERIAL PRIMARY KEY,
                    name TEXT
                )
            """)

    # ==================== CREATE SHARE TESTS ====================

    async def test_share_workflow_with_existing_user(self, real_database, frontend_sio, sid):
        """
        Test sharing a workflow with a user who already has an account.

        Verifies:
        - Share is created with target_user_id set
        - Response includes correct ShareInfo
        - Share can be found in database
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        target_id = '00000000-0000-4000-8000-000000000002'
        workflow_id = str(uuid.uuid4())

        # Create test data
        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_user(real_database, target_id, 'target@example.com')
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Shared Workflow")

        await asyncio.sleep(0.1)

        # Create share
        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-create-1",
            resource_type="workflow",
            resource_id=workflow_id,
            target_type="user",
            target_email="target@example.com",
            permission="edit",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        # Verify response
        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-create-1']
        assert len(matching) == 1, "Should receive one response"

        response_data = matching[0][1]['data']
        assert response_data.get('success') is True
        assert 'share' in response_data

        share = response_data['share']
        assert share['resource_type'] == 'workflow'
        assert share['resource_id'] == workflow_id
        assert share['target_type'] == 'user'
        assert share['target_user_id'] == target_id
        assert share['permission'] == 'edit'
        assert share['is_pending'] is False

        # Verify in database
        db_share = await real_database.fetchrow(
            "SELECT * FROM resource_shares WHERE id = $1",
            share['id']
        )
        assert db_share is not None
        assert str(db_share['target_user_id']) == target_id

    async def test_share_workflow_with_pending_invite(self, real_database, frontend_sio, sid):
        """
        Test sharing a workflow with a user who doesn't have an account yet.

        Verifies:
        - Share is created with target_email set (pending invite)
        - target_user_id is NULL
        - is_pending flag is True
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Shared Workflow")

        await asyncio.sleep(0.1)

        # Create share for non-existent user
        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-pending-1",
            resource_type="workflow",
            resource_id=workflow_id,
            target_type="user",
            target_email="newuser@example.com",
            permission="view",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        # Verify response
        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-pending-1']
        assert len(matching) == 1

        response_data = matching[0][1]['data']
        assert response_data.get('success') is True

        share = response_data['share']
        assert share['target_type'] == 'user'
        assert share['target_user_id'] is None
        assert share['target_email'] == 'newuser@example.com'
        assert share['is_pending'] is True
        assert share['permission'] == 'view'

    async def test_share_workflow_with_organization(self, real_database, frontend_sio, sid):
        """
        Test sharing a workflow with an organization.

        Verifies:
        - Share is created with target_org_id set
        - target_org_name is included in response
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        org_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_organization(real_database, org_id, "Test Org", owner_id)
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Shared Workflow")

        await asyncio.sleep(0.1)

        # Create org share
        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-org-1",
            resource_type="workflow",
            resource_id=workflow_id,
            target_type="organization",
            target_org_id=org_id,
            permission="edit",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        # Verify response
        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-org-1']
        assert len(matching) == 1

        response_data = matching[0][1]['data']
        assert response_data.get('success') is True

        share = response_data['share']
        assert share['target_type'] == 'organization'
        assert share['target_org_id'] == org_id
        assert share['target_org_name'] == 'Test Org'
        assert share['permission'] == 'edit'

    async def test_share_database_with_user(self, real_database, frontend_sio, sid):
        """
        Test sharing a database with a user.

        Verifies database resources can be shared like workflows.
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        target_id = '00000000-0000-4000-8000-000000000002'
        table_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_user(real_database, target_id, 'target@example.com')
        await self.create_test_database(real_database, table_id, owner_id, "Shared Database")

        await asyncio.sleep(0.1)

        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-db-1",
            resource_type="database",
            resource_id=table_id,
            target_type="user",
            target_email="target@example.com",
            permission="view",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-db-1']
        assert len(matching) == 1

        response_data = matching[0][1]['data']
        assert response_data.get('success') is True
        assert response_data['share']['resource_type'] == 'database'

    async def test_share_upsert_updates_permission(self, real_database, frontend_sio, sid):
        """
        Test that sharing with an already-shared user updates the permission.

        Verifies upsert behavior: same user gets permission updated, not duplicated.
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        target_id = '00000000-0000-4000-8000-000000000002'
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_user(real_database, target_id, 'target@example.com')
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Shared Workflow")

        await asyncio.sleep(0.1)

        # First share with view permission
        request1 = ShareCreateRequest(
            event_name="share:create",
            request_id="test-upsert-1",
            resource_type="workflow",
            resource_id=workflow_id,
            target_type="user",
            target_email="target@example.com",
            permission="view",
        )

        await send_event(frontend_sio, sid, request1)
        await asyncio.sleep(0.2)

        response1 = [e for e in self.get_main_api_emitted_events("response")
                     if e[1].get('request_id') == 'test-upsert-1'][0][1]['data']
        first_share_id = response1['share']['id']
        assert response1['share']['permission'] == 'view'

        # Second share with edit permission (should update, not create new)
        request2 = ShareCreateRequest(
            event_name="share:create",
            request_id="test-upsert-2",
            resource_type="workflow",
            resource_id=workflow_id,
            target_type="user",
            target_email="target@example.com",
            permission="edit",
        )

        await send_event(frontend_sio, sid, request2)
        await asyncio.sleep(0.2)

        response2 = [e for e in self.get_main_api_emitted_events("response")
                     if e[1].get('request_id') == 'test-upsert-2'][0][1]['data']

        # Should be same share ID with updated permission
        assert response2['share']['id'] == first_share_id
        assert response2['share']['permission'] == 'edit'

        # Verify only one share exists
        shares = await real_database.fetch(
            "SELECT * FROM resource_shares WHERE resource_id = $1",
            workflow_id
        )
        assert len(shares) == 1

    async def test_share_permission_denied_non_owner(self, real_database, frontend_sio, sid):
        """
        Test that non-owners cannot create shares.

        Verifies permission check rejects non-owners.
        """
        owner_id = '00000000-0000-4000-8000-000000000099'  # Different from session user
        workflow_id = str(uuid.uuid4())

        # Session user
        await self.create_test_user(real_database, '00000000-0000-4000-8000-000000000001', 'share-test@example.com')
        # Workflow owner (different user)
        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Not My Workflow")

        await asyncio.sleep(0.1)

        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-denied-1",
            resource_type="workflow",
            resource_id=workflow_id,
            target_type="user",
            target_email="someone@example.com",
            permission="view",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-denied-1']
        assert len(matching) == 1

        response = matching[0][1]
        assert 'error' in response
        assert 'permission' in response['error'].lower()

    # ==================== LIST SHARES TESTS ====================

    async def test_list_shares_returns_all_shares(self, real_database, frontend_sio, sid):
        """
        Test listing all shares for a resource.

        Verifies multiple shares are returned correctly.
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        target1_id = '00000000-0000-4000-8000-000000000002'
        target2_id = '00000000-0000-4000-8000-000000000003'
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_user(real_database, target1_id, 'target1@example.com')
        await self.create_test_user(real_database, target2_id, 'target2@example.com')
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Shared Workflow")

        # Create two shares
        await real_database.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('workflow', $1, 'user', $2, 'view', $3)
        """, workflow_id, target1_id, owner_id)

        await real_database.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('workflow', $1, 'user', $2, 'edit', $3)
        """, workflow_id, target2_id, owner_id)

        await asyncio.sleep(0.1)

        # List shares
        request = ShareListRequest(
            event_name="share:list",
            request_id="test-list-1",
            resource_type="workflow",
            resource_id=workflow_id,
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-list-1']
        assert len(matching) == 1

        response_data = matching[0][1]['data']
        assert 'shares' in response_data
        assert len(response_data['shares']) == 2

        # Verify both shares are included
        permissions = {s['permission'] for s in response_data['shares']}
        assert permissions == {'view', 'edit'}

    async def test_list_shares_empty_for_unshared_resource(self, real_database, frontend_sio, sid):
        """
        Test listing shares returns empty list for unshared resource.
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Unshared Workflow")

        await asyncio.sleep(0.1)

        request = ShareListRequest(
            event_name="share:list",
            request_id="test-list-empty",
            resource_type="workflow",
            resource_id=workflow_id,
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-list-empty']

        response_data = matching[0][1]['data']
        assert response_data['shares'] == []

    # ==================== UPDATE SHARE TESTS ====================

    async def test_update_share_permission(self, real_database, frontend_sio, sid):
        """
        Test updating a share's permission.
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        target_id = '00000000-0000-4000-8000-000000000002'
        workflow_id = str(uuid.uuid4())
        share_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_user(real_database, target_id, 'target@example.com')
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Shared Workflow")

        # Create initial share
        await real_database.execute("""
            INSERT INTO resource_shares (id, resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ($1, 'workflow', $2, 'user', $3, 'view', $4)
        """, share_id, workflow_id, target_id, owner_id)

        await asyncio.sleep(0.1)

        # Update permission
        request = ShareUpdateRequest(
            event_name="share:update",
            request_id="test-update-1",
            share_id=share_id,
            permission="edit",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-update-1']
        assert len(matching) == 1

        response_data = matching[0][1]['data']
        assert response_data.get('success') is True
        assert response_data['share']['permission'] == 'edit'

        # Verify in database
        db_share = await real_database.fetchrow(
            "SELECT permission FROM resource_shares WHERE id = $1",
            share_id
        )
        assert db_share['permission'] == 'edit'

    async def test_update_share_not_found(self, real_database, frontend_sio, sid):
        """
        Test updating a non-existent share returns error.
        """
        await self.create_test_user(real_database, '00000000-0000-4000-8000-000000000001', 'share-test@example.com')

        request = ShareUpdateRequest(
            event_name="share:update",
            request_id="test-update-notfound",
            share_id=str(uuid.uuid4()),  # Non-existent
            permission="edit",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-update-notfound']

        response = matching[0][1]
        assert 'error' in response
        assert 'not found' in response['error'].lower()

    # ==================== DELETE SHARE TESTS ====================

    async def test_delete_share_success(self, real_database, frontend_sio, sid):
        """
        Test deleting a share.
        """
        owner_id = '00000000-0000-4000-8000-000000000001'
        target_id = '00000000-0000-4000-8000-000000000002'
        workflow_id = str(uuid.uuid4())
        share_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_user(real_database, target_id, 'target@example.com')
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Shared Workflow")

        # Create share to delete
        await real_database.execute("""
            INSERT INTO resource_shares (id, resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ($1, 'workflow', $2, 'user', $3, 'view', $4)
        """, share_id, workflow_id, target_id, owner_id)

        await asyncio.sleep(0.1)

        # Delete share
        request = ShareDeleteRequest(
            event_name="share:delete",
            request_id="test-delete-1",
            share_id=share_id,
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-delete-1']
        assert len(matching) == 1

        response_data = matching[0][1]['data']
        assert response_data.get('success') is True
        assert response_data['share_id'] == share_id

        # Verify deleted from database
        db_share = await real_database.fetchrow(
            "SELECT * FROM resource_shares WHERE id = $1",
            share_id
        )
        assert db_share is None

    async def test_delete_share_not_found(self, real_database, frontend_sio, sid):
        """
        Test deleting a non-existent share returns error.
        """
        await self.create_test_user(real_database, '00000000-0000-4000-8000-000000000001', 'share-test@example.com')

        request = ShareDeleteRequest(
            event_name="share:delete",
            request_id="test-delete-notfound",
            share_id=str(uuid.uuid4()),
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-delete-notfound']

        response = matching[0][1]
        assert 'error' in response
        assert 'not found' in response['error'].lower()

    # ==================== LIST SHARED WITH ME TESTS ====================

    async def test_list_shared_with_me_direct_share(self, real_database, frontend_sio, sid):
        """
        Test listing resources shared directly with the user.
        """
        owner_id = '00000000-0000-4000-8000-000000000099'
        my_id = '00000000-0000-4000-8000-000000000001'  # Session user
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await self.create_test_user(real_database, my_id, 'share-test@example.com')
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Shared With Me")

        # Create direct share to session user
        await real_database.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('workflow', $1, 'user', $2, 'edit', $3)
        """, workflow_id, my_id, owner_id)

        await asyncio.sleep(0.1)

        request = ShareListSharedWithMeRequest(
            event_name="share:list_shared_with_me",
            request_id="test-shared-me-1",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-shared-me-1']
        assert len(matching) == 1

        response_data = matching[0][1]['data']
        assert 'resources' in response_data
        assert len(response_data['resources']) >= 1

        # Find our workflow
        workflow = next((r for r in response_data['resources'] if r['resource_id'] == workflow_id), None)
        assert workflow is not None
        assert workflow['resource_name'] == 'Shared With Me'
        assert workflow['permission'] == 'edit'
        assert workflow['shared_by_email'] == 'owner@example.com'

    async def test_list_shared_with_me_via_organization(self, real_database, frontend_sio, sid):
        """
        Test listing resources shared via organization membership.
        """
        owner_id = '00000000-0000-4000-8000-000000000099'
        my_id = '00000000-0000-4000-8000-000000000001'
        org_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await self.create_test_user(real_database, my_id, 'share-test@example.com')
        await self.create_test_organization(real_database, org_id, "My Org", owner_id)

        # Add session user as org member
        await real_database.execute("""
            INSERT INTO organization_members (organization_id, user_id, role)
            VALUES ($1, $2, 'member')
            ON CONFLICT (organization_id, user_id) DO NOTHING
        """, org_id, my_id)

        await self.create_test_workflow(real_database, workflow_id, owner_id, "Org Shared Workflow")

        # Create org share
        await real_database.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_org_id, permission, shared_by)
            VALUES ('workflow', $1, 'organization', $2, 'view', $3)
        """, workflow_id, org_id, owner_id)

        await asyncio.sleep(0.1)

        request = ShareListSharedWithMeRequest(
            event_name="share:list_shared_with_me",
            request_id="test-shared-org-1",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-shared-org-1']

        response_data = matching[0][1]['data']
        assert 'resources' in response_data

        # Find org-shared workflow
        workflow = next((r for r in response_data['resources'] if r['resource_id'] == workflow_id), None)
        assert workflow is not None
        assert workflow['resource_name'] == 'Org Shared Workflow'
        assert workflow['permission'] == 'view'

    async def test_list_shared_with_me_filter_by_type(self, real_database, frontend_sio, sid):
        """
        Test filtering shared resources by type.
        """
        owner_id = '00000000-0000-4000-8000-000000000099'
        my_id = '00000000-0000-4000-8000-000000000001'
        workflow_id = str(uuid.uuid4())
        table_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'owner@example.com')
        await self.create_test_user(real_database, my_id, 'share-test@example.com')
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Shared Workflow")
        await self.create_test_database(real_database, table_id, owner_id, "Shared Database")

        # Share both resources
        await real_database.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('workflow', $1, 'user', $2, 'edit', $3)
        """, workflow_id, my_id, owner_id)

        await real_database.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('database', $1, 'user', $2, 'view', $3)
        """, table_id, my_id, owner_id)

        await asyncio.sleep(0.1)

        # Filter by workflow type
        request = ShareListSharedWithMeRequest(
            event_name="share:list_shared_with_me",
            request_id="test-filter-1",
            resource_type="workflow",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-filter-1']

        response_data = matching[0][1]['data']

        # Should only include workflows
        for resource in response_data['resources']:
            assert resource['resource_type'] == 'workflow'

    async def test_list_shared_with_me_excludes_own_resources(self, real_database, frontend_sio, sid):
        """
        Test that user's own resources are excluded from shared-with-me list.
        """
        my_id = '00000000-0000-4000-8000-000000000001'
        other_id = '00000000-0000-4000-8000-000000000002'
        my_workflow_id = str(uuid.uuid4())
        other_workflow_id = str(uuid.uuid4())
        org_id = str(uuid.uuid4())

        await self.create_test_user(real_database, my_id, 'share-test@example.com')
        await self.create_test_user(real_database, other_id, 'other@example.com')
        await self.create_test_organization(real_database, org_id, "Shared Org", my_id)

        # Add other user to org
        await real_database.execute("""
            INSERT INTO organization_members (organization_id, user_id, role)
            VALUES ($1, $2, 'member')
            ON CONFLICT DO NOTHING
        """, org_id, other_id)

        # My workflow (should be excluded even if org-shared)
        await self.create_test_workflow(real_database, my_workflow_id, my_id, "My Workflow")
        # Other's workflow (should be included)
        await self.create_test_workflow(real_database, other_workflow_id, other_id, "Other Workflow")

        # Share both to org
        await real_database.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_org_id, permission, shared_by)
            VALUES ('workflow', $1, 'organization', $2, 'edit', $3)
        """, my_workflow_id, org_id, my_id)

        await real_database.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_org_id, permission, shared_by)
            VALUES ('workflow', $1, 'organization', $2, 'edit', $3)
        """, other_workflow_id, org_id, other_id)

        await asyncio.sleep(0.1)

        request = ShareListSharedWithMeRequest(
            event_name="share:list_shared_with_me",
            request_id="test-exclude-own",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-exclude-own']

        response_data = matching[0][1]['data']
        resource_ids = [r['resource_id'] for r in response_data['resources']]

        # My workflow should be excluded
        assert my_workflow_id not in resource_ids
        # Other's workflow should be included
        assert other_workflow_id in resource_ids

    # ==================== ORG ADMIN CAN MANAGE SHARES ====================

    async def test_org_admin_can_manage_shares(self, real_database, frontend_sio, sid):
        """
        Test that org admins can manage shares for org resources.
        """
        owner_id = '00000000-0000-4000-8000-000000000088'  # Unique ID for this test
        admin_id = '00000000-0000-4000-8000-000000000001'  # Session user is admin
        target_id = '00000000-0000-4000-8000-000000000087'  # Unique ID for this test
        org_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'orgowner@example.com')
        await self.create_test_user(real_database, admin_id, 'share-test@example.com')
        await self.create_test_user(real_database, target_id, 'orgtarget@example.com')
        await self.create_test_organization(real_database, org_id, "Admin Test Org", owner_id)

        # Make session user an admin
        await real_database.execute("""
            INSERT INTO organization_members (organization_id, user_id, role)
            VALUES ($1, $2, 'admin')
            ON CONFLICT (organization_id, user_id) DO UPDATE SET role = 'admin'
        """, org_id, admin_id)

        # Create workflow owned by owner but in org
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Org Workflow", org_id)

        await asyncio.sleep(0.1)

        # Admin should be able to share with anyone (even outside org)
        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-admin-share",
            resource_type="workflow",
            resource_id=workflow_id,
            target_type="user",
            target_email="orgtarget@example.com",
            permission="view",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-admin-share']

        response_data = matching[0][1]['data']
        assert response_data.get('success') is True

    # ==================== MEMBER SHARING RESTRICTIONS ====================

    async def test_member_can_share_with_org_member(self, real_database, frontend_sio, sid):
        """
        Test that org members can share with other members of the same org.
        """
        owner_id = '00000000-0000-4000-8000-000000000070'
        member_id = '00000000-0000-4000-8000-000000000001'  # Session user is member
        target_id = '00000000-0000-4000-8000-000000000071'
        org_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'member-owner@example.com')
        await self.create_test_user(real_database, member_id, 'share-test@example.com')
        await self.create_test_user(real_database, target_id, 'member-target@example.com')
        await self.create_test_organization(real_database, org_id, "Member Test Org", owner_id)

        # Add session user as member
        await real_database.execute("""
            INSERT INTO organization_members (organization_id, user_id, role)
            VALUES ($1, $2, 'member')
            ON CONFLICT (organization_id, user_id) DO NOTHING
        """, org_id, member_id)

        # Add target as member of same org
        await real_database.execute("""
            INSERT INTO organization_members (organization_id, user_id, role)
            VALUES ($1, $2, 'member')
            ON CONFLICT (organization_id, user_id) DO NOTHING
        """, org_id, target_id)

        # Create workflow in org owned by session user (member)
        await self.create_test_workflow(real_database, workflow_id, member_id, "Member Workflow", org_id)

        await asyncio.sleep(0.1)

        # Member should be able to share with another org member
        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-member-share-allowed",
            resource_type="workflow",
            resource_id=workflow_id,
            target_type="user",
            target_email="member-target@example.com",
            permission="view",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-member-share-allowed']

        response_data = matching[0][1]['data']
        assert response_data.get('success') is True

    async def test_member_cannot_share_with_non_member(self, real_database, frontend_sio, sid):
        """
        Test that org members CANNOT share with users outside their org.
        """
        owner_id = '00000000-0000-4000-8000-000000000060'
        member_id = '00000000-0000-4000-8000-000000000001'  # Session user is member
        outside_id = '00000000-0000-4000-8000-000000000061'  # Not in org
        org_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'restrict-owner@example.com')
        await self.create_test_user(real_database, member_id, 'share-test@example.com')
        await self.create_test_user(real_database, outside_id, 'outside-user@example.com')
        await self.create_test_organization(real_database, org_id, "Restrict Test Org", owner_id)

        # Add session user as member
        await real_database.execute("""
            INSERT INTO organization_members (organization_id, user_id, role)
            VALUES ($1, $2, 'member')
            ON CONFLICT (organization_id, user_id) DO NOTHING
        """, org_id, member_id)

        # outside_id is NOT added to org

        # Create workflow in org owned by session user (member)
        await self.create_test_workflow(real_database, workflow_id, member_id, "Restricted Workflow", org_id)

        await asyncio.sleep(0.1)

        # Member should NOT be able to share with user outside org
        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-member-share-denied",
            resource_type="workflow",
            resource_id=workflow_id,
            target_type="user",
            target_email="outside-user@example.com",
            permission="view",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-member-share-denied']

        response = matching[0][1]
        assert 'error' in response
        assert 'members' in response['error'].lower() or 'organization' in response['error'].lower()

    async def test_member_cannot_share_with_other_org(self, real_database, frontend_sio, sid):
        """
        Test that org members CANNOT share with other organizations.
        """
        owner_id = '00000000-0000-4000-8000-000000000050'
        member_id = '00000000-0000-4000-8000-000000000001'  # Session user is member
        org_id = str(uuid.uuid4())
        other_org_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'org-restrict-owner@example.com')
        await self.create_test_user(real_database, member_id, 'share-test@example.com')
        await self.create_test_organization(real_database, org_id, "My Org Restrict", owner_id)
        await self.create_test_organization(real_database, other_org_id, "Other Org", owner_id)

        # Add session user as member of first org
        await real_database.execute("""
            INSERT INTO organization_members (organization_id, user_id, role)
            VALUES ($1, $2, 'member')
            ON CONFLICT (organization_id, user_id) DO NOTHING
        """, org_id, member_id)

        # Create workflow in first org
        await self.create_test_workflow(real_database, workflow_id, member_id, "My Org Workflow", org_id)

        await asyncio.sleep(0.1)

        # Member should NOT be able to share with other org
        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-member-org-share-denied",
            resource_type="workflow",
            resource_id=workflow_id,
            target_type="organization",
            target_org_id=other_org_id,
            permission="view",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-member-org-share-denied']

        response = matching[0][1]
        assert 'error' in response
        assert 'members' in response['error'].lower() or 'organization' in response['error'].lower()

    async def test_member_can_share_with_own_org(self, real_database, frontend_sio, sid):
        """
        Test that org members CAN share with their own organization.
        """
        owner_id = '00000000-0000-4000-8000-000000000040'
        member_id = '00000000-0000-4000-8000-000000000001'  # Session user is member
        org_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'own-org-owner@example.com')
        await self.create_test_user(real_database, member_id, 'share-test@example.com')
        await self.create_test_organization(real_database, org_id, "Own Org Share", owner_id)

        # Add session user as member
        await real_database.execute("""
            INSERT INTO organization_members (organization_id, user_id, role)
            VALUES ($1, $2, 'member')
            ON CONFLICT (organization_id, user_id) DO NOTHING
        """, org_id, member_id)

        # Create workflow in org
        await self.create_test_workflow(real_database, workflow_id, member_id, "Own Org Workflow", org_id)

        await asyncio.sleep(0.1)

        # Member should be able to share with their own org
        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-member-own-org-share",
            resource_type="workflow",
            resource_id=workflow_id,
            target_type="organization",
            target_org_id=org_id,
            permission="view",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-member-own-org-share']

        response_data = matching[0][1]['data']
        assert response_data.get('success') is True

    async def test_member_cannot_create_pending_invite(self, real_database, frontend_sio, sid):
        """
        Test that org members CANNOT create pending invites for non-existent users.
        """
        owner_id = '00000000-0000-4000-8000-000000000030'
        member_id = '00000000-0000-4000-8000-000000000001'  # Session user is member
        org_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'pending-owner@example.com')
        await self.create_test_user(real_database, member_id, 'share-test@example.com')
        await self.create_test_organization(real_database, org_id, "Pending Test Org", owner_id)

        # Add session user as member
        await real_database.execute("""
            INSERT INTO organization_members (organization_id, user_id, role)
            VALUES ($1, $2, 'member')
            ON CONFLICT (organization_id, user_id) DO NOTHING
        """, org_id, member_id)

        # Create workflow in org
        await self.create_test_workflow(real_database, workflow_id, member_id, "Pending Workflow", org_id)

        await asyncio.sleep(0.1)

        # Member should NOT be able to create pending invite (user doesn't exist)
        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-member-pending-denied",
            resource_type="workflow",
            resource_id=workflow_id,
            target_type="user",
            target_email="nonexistent-user@example.com",
            permission="view",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-member-pending-denied']

        response = matching[0][1]
        assert 'error' in response
        assert 'existing members' in response['error'].lower()

    async def test_admin_can_share_outside_org(self, real_database, frontend_sio, sid):
        """
        Test that org admins CAN share with users outside the org.
        """
        owner_id = '00000000-0000-4000-8000-000000000020'
        admin_id = '00000000-0000-4000-8000-000000000001'  # Session user is admin
        outside_id = '00000000-0000-4000-8000-000000000021'  # Not in org
        org_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'admin-test-owner@example.com')
        await self.create_test_user(real_database, admin_id, 'share-test@example.com')
        await self.create_test_user(real_database, outside_id, 'admin-outside@example.com')
        await self.create_test_organization(real_database, org_id, "Admin Share Org", owner_id)

        # Add session user as admin
        await real_database.execute("""
            INSERT INTO organization_members (organization_id, user_id, role)
            VALUES ($1, $2, 'admin')
            ON CONFLICT (organization_id, user_id) DO UPDATE SET role = 'admin'
        """, org_id, admin_id)

        # Create workflow in org
        await self.create_test_workflow(real_database, workflow_id, admin_id, "Admin Workflow", org_id)

        await asyncio.sleep(0.1)

        # Admin should be able to share with user outside org
        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-admin-outside-share",
            resource_type="workflow",
            resource_id=workflow_id,
            target_type="user",
            target_email="admin-outside@example.com",
            permission="view",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-admin-outside-share']

        response_data = matching[0][1]['data']
        assert response_data.get('success') is True

    async def test_owner_can_share_outside_org(self, real_database, frontend_sio, sid):
        """
        Test that org owners CAN share with users outside the org.
        Owners have unrestricted sharing permissions like admins.
        """
        org_owner_id = '00000000-0000-4000-8000-000000000001'  # Session user is org owner
        outside_id = '00000000-0000-4000-8000-000000000025'  # Not in org
        org_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, org_owner_id, 'share-test@example.com')
        await self.create_test_user(real_database, outside_id, 'owner-outside@example.com')
        await self.create_test_organization(real_database, org_id, "Owner Share Org", org_owner_id)

        # Clear any existing primary org for session user, then set this one as primary
        await real_database.execute("""
            UPDATE organization_members SET is_primary = false WHERE user_id = $1
        """, org_owner_id)
        await real_database.execute("""
            UPDATE organization_members SET is_primary = true
            WHERE organization_id = $1 AND user_id = $2
        """, org_id, org_owner_id)

        # Create workflow in org
        await self.create_test_workflow(real_database, workflow_id, org_owner_id, "Owner Workflow", org_id)

        await asyncio.sleep(0.1)

        # Owner should be able to share with user outside org
        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-owner-outside-share",
            resource_type="workflow",
            resource_id=workflow_id,
            target_type="user",
            target_email="owner-outside@example.com",
            permission="view",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-owner-outside-share']

        response_data = matching[0][1]['data']
        assert response_data.get('success') is True

    async def test_personal_resource_no_restrictions(self, real_database, frontend_sio, sid):
        """
        Test that personal resources (not in any org) have no sharing restrictions.
        """
        owner_id = '00000000-0000-4000-8000-000000000001'  # Session user owns personal resource
        target_id = '00000000-0000-4000-8000-000000000010'
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_user(real_database, target_id, 'personal-target@example.com')

        # Create personal workflow (no org)
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Personal Workflow")

        await asyncio.sleep(0.1)

        # Should be able to share with anyone
        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-personal-share",
            resource_type="workflow",
            resource_id=workflow_id,
            target_type="user",
            target_email="personal-target@example.com",
            permission="edit",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-personal-share']

        response_data = matching[0][1]['data']
        assert response_data.get('success') is True

    # ==================== LIST VISIBILITY TESTS ====================
    # These tests verify that shared resources appear in list endpoints
    # with correct permission levels

    async def test_shared_workflow_appears_in_org_member_list(self, real_database, frontend_sio, sid):
        """
        Test that a workflow shared with an org appears in org member's workflow:list.
        Verifies is_owner=False and user_permission='view'.
        """
        from wss.receiver.client_events import WorkflowListRequest

        owner_id = '00000000-0000-4000-8000-000000000081'
        member_id = '00000000-0000-4000-8000-000000000001'  # Session user
        org_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'wf-share-owner@example.com')
        await self.create_test_user(real_database, member_id, 'share-test@example.com')
        await self.create_test_organization(real_database, org_id, "WF List Test Org", owner_id)

        # Clear any existing primary org for session user, then add new one
        await real_database.execute("""
            UPDATE organization_members SET is_primary = false WHERE user_id = $1
        """, member_id)
        await real_database.execute("""
            INSERT INTO organization_members (organization_id, user_id, role, is_primary)
            VALUES ($1, $2, 'member', true)
            ON CONFLICT (organization_id, user_id) DO UPDATE SET is_primary = true
        """, org_id, member_id)

        # Create workflow owned by owner
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Shared WF", org_id)

        # Share workflow with org (view permission)
        await real_database.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_org_id, permission, shared_by)
            VALUES ('workflow', $1, 'organization', $2, 'view', $3)
        """, workflow_id, org_id, owner_id)

        await asyncio.sleep(0.1)

        # List workflows as org member
        request = WorkflowListRequest(
            event_name="workflow:list",
            request_id="test-list-shared-wf",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-list-shared-wf']
        assert len(matching) == 1

        response_data = matching[0][1]['data']
        assert 'workflows' in response_data

        # Find the shared workflow
        shared_wf = next((w for w in response_data['workflows'] if w['id'] == workflow_id), None)
        assert shared_wf is not None, "Shared workflow should appear in list"
        assert shared_wf.get('is_owner') is False, "Session user is not owner"
        assert shared_wf.get('user_permission') == 'view', "Permission should be 'view'"

    async def test_view_permission_prevents_edit(self, real_database, frontend_sio, sid):
        """
        Test that view-only permission is correctly reflected and can be used
        to check access before attempting edits.
        """
        from wss.receiver.client_events import WorkflowListRequest

        owner_id = '00000000-0000-4000-8000-000000000083'
        member_id = '00000000-0000-4000-8000-000000000001'  # Session user
        org_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'viewonly-owner@example.com')
        await self.create_test_user(real_database, member_id, 'share-test@example.com')
        await self.create_test_organization(real_database, org_id, "View Only Test Org", owner_id)

        # Clear any existing primary org for session user, then add new one
        await real_database.execute("""
            UPDATE organization_members SET is_primary = false WHERE user_id = $1
        """, member_id)
        await real_database.execute("""
            INSERT INTO organization_members (organization_id, user_id, role, is_primary)
            VALUES ($1, $2, 'member', true)
            ON CONFLICT (organization_id, user_id) DO UPDATE SET is_primary = true
        """, org_id, member_id)

        # Create workflow and share with VIEW only
        await self.create_test_workflow(real_database, workflow_id, owner_id, "View Only WF", org_id)

        await real_database.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_org_id, permission, shared_by)
            VALUES ('workflow', $1, 'organization', $2, 'view', $3)
        """, workflow_id, org_id, owner_id)

        await asyncio.sleep(0.1)

        request = WorkflowListRequest(
            event_name="workflow:list",
            request_id="test-list-viewonly-wf",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-list-viewonly-wf']

        response_data = matching[0][1]['data']
        shared_wf = next((w for w in response_data['workflows'] if w['id'] == workflow_id), None)

        assert shared_wf is not None
        assert shared_wf.get('user_permission') == 'view', "Permission should be 'view'"
        # Frontend can use this to disable edit buttons/features

    # =========================================================================
    # Fork Tests
    # =========================================================================

    async def test_fork_workflow_to_personal(self, real_database, frontend_sio, sid):
        """
        Test forking a shared workflow to personal workspace.
        Creates an independent copy owned by the user.
        """
        owner_id = '00000000-0000-4000-8000-000000000090'
        forker_id = '00000000-0000-4000-8000-000000000001'  # Session user
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'fork-owner@example.com')
        await self.create_test_user(real_database, forker_id, 'share-test@example.com')

        # Create workflow owned by someone else
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Workflow to Fork")

        # Share with the forker (view permission)
        await real_database.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('workflow', $1, 'user', $2, 'view', $3)
        """, workflow_id, forker_id, owner_id)

        # Create resource_forks table if it doesn't exist (for test isolation)
        await real_database.execute("""
            CREATE TABLE IF NOT EXISTS public.resource_forks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                resource_type TEXT NOT NULL,
                source_id UUID NOT NULL,
                forked_id UUID NOT NULL,
                forked_by UUID NOT NULL,
                forked_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT unique_fork UNIQUE (resource_type, source_id, forked_id)
            )
        """)

        await asyncio.sleep(0.1)

        request = ResourceForkRequest(
            event_name="resource:fork",
            request_id="test-fork-workflow-personal",
            resource_type="workflow",
            resource_id=workflow_id,
            destination_type="personal",
            new_name="My Forked Workflow",
        )

        self.main_api_sio.clear_emitted_events()
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-fork-workflow-personal']
        assert len(matching) == 1

        response_data = matching[0][1]
        assert 'error' not in response_data, f"Fork should succeed: {response_data.get('error')}"
        assert response_data['data']['success'] is True

        forked = response_data['data']['forked_resource']
        assert forked['name'] == "My Forked Workflow"
        assert forked['resource_type'] == "workflow"
        assert forked['owner_id'] == forker_id
        # Personal forks go into the user's current primary org (personal workspace org)
        primary_org = await real_database.fetchrow(
            """SELECT organization_id FROM organization_members
               WHERE user_id = $1 AND is_primary = true""",
            forker_id,
        )
        assert forked['organization_id'] == str(primary_org['organization_id'])
        assert forked['forked_from_id'] == workflow_id
        assert forked['forked_from_name'] == "Workflow to Fork"

        # Verify the workflow was actually created
        new_wf = await real_database.fetchrow(
            "SELECT * FROM workflows WHERE id = $1",
            forked['id']
        )
        assert new_wf is not None
        assert new_wf['name'] == "My Forked Workflow"
        assert str(new_wf['owner_id']) == forker_id

        # Verify fork relationship was recorded
        fork_record = await real_database.fetchrow(
            "SELECT * FROM resource_forks WHERE forked_id = $1",
            forked['id']
        )
        assert fork_record is not None
        assert str(fork_record['source_id']) == workflow_id
        assert str(fork_record['forked_by']) == forker_id

    async def test_fork_workflow_to_organization(self, real_database, frontend_sio, sid):
        """
        Test forking a workflow to an organization.
        Creates a copy in the org and gives the forker edit access.
        """
        owner_id = '00000000-0000-4000-8000-000000000091'
        forker_id = '00000000-0000-4000-8000-000000000001'  # Session user
        org_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'fork-org-owner@example.com')
        await self.create_test_user(real_database, forker_id, 'share-test@example.com')
        await self.create_test_organization(real_database, org_id, "Fork Destination Org", owner_id)

        # Add forker as member of the org
        await real_database.execute("""
            INSERT INTO organization_members (organization_id, user_id, role)
            VALUES ($1, $2, 'member')
            ON CONFLICT (organization_id, user_id) DO NOTHING
        """, org_id, forker_id)

        # Create workflow owned by someone else
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Org Fork Source WF")

        # Share with the forker
        await real_database.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('workflow', $1, 'user', $2, 'view', $3)
        """, workflow_id, forker_id, owner_id)

        # Create resource_forks table if it doesn't exist
        await real_database.execute("""
            CREATE TABLE IF NOT EXISTS public.resource_forks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                resource_type TEXT NOT NULL,
                source_id UUID NOT NULL,
                forked_id UUID NOT NULL,
                forked_by UUID NOT NULL,
                forked_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT unique_fork UNIQUE (resource_type, source_id, forked_id)
            )
        """)

        await asyncio.sleep(0.1)

        request = ResourceForkRequest(
            event_name="resource:fork",
            request_id="test-fork-workflow-org",
            resource_type="workflow",
            resource_id=workflow_id,
            destination_type="organization",
            destination_org_id=org_id,
        )

        self.main_api_sio.clear_emitted_events()
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-fork-workflow-org']
        assert len(matching) == 1

        response_data = matching[0][1]
        assert 'error' not in response_data, f"Fork should succeed: {response_data.get('error')}"
        assert response_data['data']['success'] is True

        forked = response_data['data']['forked_resource']
        assert forked['name'] == "Copy of Org Fork Source WF"  # Default name
        assert forked['organization_id'] == org_id
        assert forked['owner_id'] == forker_id  # Workflows always have an owner (the forker)

        # Forker is the owner, so no separate share is needed (owner has full access)

    async def test_fork_database_to_personal(self, real_database, frontend_sio, sid):
        """
        Test forking a database to personal workspace.
        Should copy schema but not data by default.
        """
        owner_id = '00000000-0000-4000-8000-000000000092'
        forker_id = '00000000-0000-4000-8000-000000000001'  # Session user
        table_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'fork-db-owner@example.com')
        await self.create_test_user(real_database, forker_id, 'share-test@example.com')

        # Create database owned by someone else (with actual table for data insertion)
        await self.create_test_database(real_database, table_id, owner_id, "DB to Fork", create_table=True)

        # Add some data to the source table
        await real_database.execute(f"""
            INSERT INTO user_tables."{table_id}" (name) VALUES ('Test Row 1'), ('Test Row 2')
        """)

        # Share with the forker
        await real_database.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('database', $1, 'user', $2, 'view', $3)
        """, table_id, forker_id, owner_id)

        # Create resource_forks table if it doesn't exist
        await real_database.execute("""
            CREATE TABLE IF NOT EXISTS public.resource_forks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                resource_type TEXT NOT NULL,
                source_id UUID NOT NULL,
                forked_id UUID NOT NULL,
                forked_by UUID NOT NULL,
                forked_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT unique_fork UNIQUE (resource_type, source_id, forked_id)
            )
        """)

        await asyncio.sleep(0.1)

        request = ResourceForkRequest(
            event_name="resource:fork",
            request_id="test-fork-db-personal",
            resource_type="database",
            resource_id=table_id,
            destination_type="personal",
            new_name="My Forked Database",
            include_data=False,
        )

        self.main_api_sio.clear_emitted_events()
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-fork-db-personal']
        assert len(matching) == 1

        response_data = matching[0][1]
        assert 'error' not in response_data, f"Fork should succeed: {response_data.get('error')}"
        assert response_data['data']['success'] is True

        forked = response_data['data']['forked_resource']
        assert forked['name'] == "My Forked Database"
        assert forked['resource_type'] == "database"
        assert forked['owner_id'] == forker_id
        assert forked['forked_from_id'] == table_id

        # Verify the table was created with schema but no data
        row_count = await real_database.fetchval(
            f'SELECT COUNT(*) FROM user_tables."{forked["id"]}"'
        )
        assert row_count == 0, "Data should not be copied by default"

    async def test_fork_database_with_data(self, real_database, frontend_sio, sid):
        """
        Test forking a database with include_data=True.
        Should copy both schema and data.
        """
        owner_id = '00000000-0000-4000-8000-000000000093'
        forker_id = '00000000-0000-4000-8000-000000000001'  # Session user
        table_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'fork-data-owner@example.com')
        await self.create_test_user(real_database, forker_id, 'share-test@example.com')

        # Create database owned by someone else (with actual table for data insertion)
        await self.create_test_database(real_database, table_id, owner_id, "DB with Data", create_table=True)

        # Add some data to the source table
        await real_database.execute(f"""
            INSERT INTO user_tables."{table_id}" (name) VALUES ('Row A'), ('Row B'), ('Row C')
        """)

        # Share with the forker
        await real_database.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('database', $1, 'user', $2, 'view', $3)
        """, table_id, forker_id, owner_id)

        # Create resource_forks table if it doesn't exist
        await real_database.execute("""
            CREATE TABLE IF NOT EXISTS public.resource_forks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                resource_type TEXT NOT NULL,
                source_id UUID NOT NULL,
                forked_id UUID NOT NULL,
                forked_by UUID NOT NULL,
                forked_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT unique_fork UNIQUE (resource_type, source_id, forked_id)
            )
        """)

        await asyncio.sleep(0.1)

        request = ResourceForkRequest(
            event_name="resource:fork",
            request_id="test-fork-db-with-data",
            resource_type="database",
            resource_id=table_id,
            destination_type="personal",
            include_data=True,
        )

        self.main_api_sio.clear_emitted_events()
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-fork-db-with-data']
        assert len(matching) == 1

        response_data = matching[0][1]
        assert 'error' not in response_data, f"Fork should succeed: {response_data.get('error')}"
        assert response_data['data']['success'] is True

        forked = response_data['data']['forked_resource']

        # Verify the data was copied
        row_count = await real_database.fetchval(
            f'SELECT COUNT(*) FROM user_tables."{forked["id"]}"'
        )
        assert row_count == 3, "All 3 rows should be copied"

        # Verify data values
        rows = await real_database.fetch(f'SELECT name FROM user_tables."{forked["id"]}" ORDER BY name')
        names = [r['name'] for r in rows]
        assert names == ['Row A', 'Row B', 'Row C']

    async def test_fork_without_access_fails(self, real_database, frontend_sio, sid):
        """
        Test that forking fails if user doesn't have access to the source resource.
        """
        owner_id = '00000000-0000-4000-8000-000000000094'
        forker_id = '00000000-0000-4000-8000-000000000001'  # Session user
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'no-access-owner@example.com')
        await self.create_test_user(real_database, forker_id, 'share-test@example.com')

        # Create workflow but DON'T share it
        await self.create_test_workflow(real_database, workflow_id, owner_id, "Unshared WF")

        await asyncio.sleep(0.1)

        request = ResourceForkRequest(
            event_name="resource:fork",
            request_id="test-fork-no-access",
            resource_type="workflow",
            resource_id=workflow_id,
            destination_type="personal",
        )

        self.main_api_sio.clear_emitted_events()
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-fork-no-access']
        assert len(matching) == 1

        response_data = matching[0][1]
        assert 'error' in response_data
        assert "don't have access" in response_data['error']

    async def test_fork_to_non_member_org_fails(self, real_database, frontend_sio, sid):
        """
        Test that forking to an organization fails if user is not a member.
        """
        owner_id = '00000000-0000-4000-8000-000000000095'
        forker_id = '00000000-0000-4000-8000-000000000001'  # Session user
        org_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'non-member-owner@example.com')
        await self.create_test_user(real_database, forker_id, 'share-test@example.com')
        await self.create_test_organization(real_database, org_id, "Non-Member Org", owner_id)
        # Note: forker is NOT added as a member

        # Create and share workflow
        await self.create_test_workflow(real_database, workflow_id, owner_id, "WF to Fork")
        await real_database.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('workflow', $1, 'user', $2, 'view', $3)
        """, workflow_id, forker_id, owner_id)

        await asyncio.sleep(0.1)

        request = ResourceForkRequest(
            event_name="resource:fork",
            request_id="test-fork-non-member-org",
            resource_type="workflow",
            resource_id=workflow_id,
            destination_type="organization",
            destination_org_id=org_id,
        )

        self.main_api_sio.clear_emitted_events()
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-fork-non-member-org']
        assert len(matching) == 1

        response_data = matching[0][1]
        assert 'error' in response_data
        assert "must be a member" in response_data['error']

    # ─── workflow_folder sharing tests ────────────────────────────────────────

    async def test_share_folder_with_user(self, real_database, frontend_sio, sid):
        """Test sharing a personal folder with another user (personal→personal)."""
        owner_id = '00000000-0000-4000-8000-000000000001'
        target_id = '00000000-0000-4000-8000-000000000002'
        folder_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_user(real_database, target_id, 'target@example.com')
        await self.create_test_folder(real_database, folder_id, owner_id, "My Folder")

        await asyncio.sleep(0.1)

        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-folder-user-1",
            resource_type="workflow_folder",
            resource_id=folder_id,
            target_type="user",
            target_email="target@example.com",
            permission="view",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-folder-user-1']
        assert len(matching) == 1

        response_data = matching[0][1]['data']
        assert response_data.get('success') is True, f"Expected success, got: {response_data.get('error')}"

        share = response_data['share']
        assert share['resource_type'] == 'workflow_folder'
        assert share['target_user_id'] == target_id
        assert share['permission'] == 'view'

    async def test_share_folder_with_organization(self, real_database, frontend_sio, sid):
        """Test sharing a personal folder with an organization (personal→org)."""
        owner_id = '00000000-0000-4000-8000-000000000001'
        org_id = str(uuid.uuid4())
        folder_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_organization(real_database, org_id, 'Target Org', owner_id)
        await self.create_test_folder(real_database, folder_id, owner_id, "Personal Folder")

        await asyncio.sleep(0.1)

        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-folder-org-1",
            resource_type="workflow_folder",
            resource_id=folder_id,
            target_type="organization",
            target_org_id=org_id,
            permission="view",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-folder-org-1']
        assert len(matching) == 1

        response_data = matching[0][1]['data']
        assert response_data.get('success') is True, f"Expected success, got: {response_data.get('error')}"

        share = response_data['share']
        assert share['resource_type'] == 'workflow_folder'
        assert share['target_type'] == 'organization'
        assert share['target_org_id'] == org_id
        assert share['permission'] == 'view'

    async def test_share_org_folder_with_external_user_blocked(self, real_database, frontend_sio, sid):
        """Test that sharing an org folder with a non-org user is blocked."""
        owner_id = '00000000-0000-4000-8000-000000000001'
        target_id = str(uuid.uuid4())
        target_email = f'external-{target_id[:8]}@example.com'
        org_id = str(uuid.uuid4())
        folder_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_user(real_database, target_id, target_email)
        await self.create_test_organization(real_database, org_id, f"Folder Test Org {org_id[:8]}", owner_id)
        await self.create_test_folder(real_database, folder_id, owner_id, "Org Folder", org_id=org_id)

        await asyncio.sleep(0.1)

        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-folder-org-user-1",
            resource_type="workflow_folder",
            resource_id=folder_id,
            target_type="user",
            target_email=target_email,
            permission="edit",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-folder-org-user-1']
        assert len(matching) == 1

        response = matching[0][1]
        assert response.get('error') is not None, "Sharing org folder with external user should be blocked"
        assert 'Organization folders' in response['error']

    async def test_list_folder_shares(self, real_database, frontend_sio, sid):
        """Test listing all shares for a workflow folder."""
        owner_id = '00000000-0000-4000-8000-000000000001'
        target_id = '00000000-0000-4000-8000-000000000002'
        folder_id = str(uuid.uuid4())
        share_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_user(real_database, target_id, 'target@example.com')
        await self.create_test_folder(real_database, folder_id, owner_id, "Folder To List")

        await real_database.execute("""
            INSERT INTO resource_shares (id, resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ($1, 'workflow_folder', $2, 'user', $3, 'view', $4)
        """, share_id, folder_id, target_id, owner_id)

        await asyncio.sleep(0.1)

        request = ShareListRequest(
            event_name="share:list",
            request_id="test-folder-list-1",
            resource_type="workflow_folder",
            resource_id=folder_id,
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-folder-list-1']
        assert len(matching) == 1

        response_data = matching[0][1]['data']
        assert 'shares' in response_data
        assert len(response_data['shares']) >= 1
        share = next((s for s in response_data['shares'] if s.get('id') == share_id), None)
        assert share is not None
        assert share['permission'] == 'view'

    async def test_update_folder_share_permission(self, real_database, frontend_sio, sid):
        """Test updating permission on a folder share."""
        owner_id = '00000000-0000-4000-8000-000000000001'
        target_id = '00000000-0000-4000-8000-000000000002'
        folder_id = str(uuid.uuid4())
        share_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_user(real_database, target_id, 'target@example.com')
        await self.create_test_folder(real_database, folder_id, owner_id, "Folder To Update")

        await real_database.execute("""
            INSERT INTO resource_shares (id, resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ($1, 'workflow_folder', $2, 'user', $3, 'view', $4)
        """, share_id, folder_id, target_id, owner_id)

        await asyncio.sleep(0.1)

        request = ShareUpdateRequest(
            event_name="share:update",
            request_id="test-folder-update-1",
            share_id=share_id,
            permission="edit",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-folder-update-1']
        assert len(matching) == 1

        response_data = matching[0][1]['data']
        assert response_data.get('success') is True
        assert response_data['share']['permission'] == 'edit'

    async def test_delete_folder_share(self, real_database, frontend_sio, sid):
        """Test deleting a folder share."""
        owner_id = '00000000-0000-4000-8000-000000000001'
        target_id = '00000000-0000-4000-8000-000000000002'
        folder_id = str(uuid.uuid4())
        share_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_user(real_database, target_id, 'target@example.com')
        await self.create_test_folder(real_database, folder_id, owner_id, "Folder To Delete Share")

        await real_database.execute("""
            INSERT INTO resource_shares (id, resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ($1, 'workflow_folder', $2, 'user', $3, 'view', $4)
        """, share_id, folder_id, target_id, owner_id)

        await asyncio.sleep(0.1)

        request = ShareDeleteRequest(
            event_name="share:delete",
            request_id="test-folder-delete-1",
            share_id=share_id,
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-folder-delete-1']
        assert len(matching) == 1

        response_data = matching[0][1]['data']
        assert response_data.get('success') is True

        remaining = await real_database.fetch(
            "SELECT * FROM resource_shares WHERE resource_id = $1 AND resource_type = 'workflow_folder'",
            folder_id
        )
        assert len(remaining) == 0

    async def test_share_folder_permission_denied_non_owner(self, real_database, frontend_sio, sid):
        """Test that non-owners cannot share a folder."""
        owner_id = '00000000-0000-4000-8000-000000000099'
        session_user = '00000000-0000-4000-8000-000000000001'
        target_id = '00000000-0000-4000-8000-000000000002'
        folder_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'other-owner@example.com')
        await self.create_test_user(real_database, session_user, 'share-test@example.com')
        await self.create_test_user(real_database, target_id, 'target@example.com')
        await self.create_test_folder(real_database, folder_id, owner_id, "Someone Else's Folder")

        await asyncio.sleep(0.1)

        request = ShareCreateRequest(
            event_name="share:create",
            request_id="test-folder-denied-1",
            resource_type="workflow_folder",
            resource_id=folder_id,
            target_type="user",
            target_email="target@example.com",
            permission="view",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-folder-denied-1']
        assert len(matching) == 1

        response_data = matching[0][1]
        assert 'error' in response_data or response_data.get('data', {}).get('success') is not True

    async def test_folder_share_upsert_updates_permission(self, real_database, frontend_sio, sid):
        """Test that sharing a folder twice upserts (updates) the permission."""
        owner_id = '00000000-0000-4000-8000-000000000001'
        target_id = '00000000-0000-4000-8000-000000000002'
        folder_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'share-test@example.com')
        await self.create_test_user(real_database, target_id, 'target@example.com')
        await self.create_test_folder(real_database, folder_id, owner_id, "Upsert Folder")

        await asyncio.sleep(0.1)

        for perm, req_id in [("view", "test-folder-upsert-1"), ("edit", "test-folder-upsert-2")]:
            request = ShareCreateRequest(
                event_name="share:create",
                request_id=req_id,
                resource_type="workflow_folder",
                resource_id=folder_id,
                target_type="user",
                target_email="target@example.com",
                permission=perm,
            )
            await send_event(frontend_sio, sid, request)
            await asyncio.sleep(0.2)

        shares = await real_database.fetch(
            "SELECT * FROM resource_shares WHERE resource_id = $1 AND resource_type = 'workflow_folder'",
            folder_id
        )
        assert len(shares) == 1
        assert shares[0]['permission'] == 'edit'

    async def test_list_shared_with_me_includes_folders(self, real_database, frontend_sio, sid):
        """Test that list_shared_with_me returns workflow_folder resources."""
        owner_id = '00000000-0000-4000-8000-000000000099'
        recipient_id = '00000000-0000-4000-8000-000000000001'  # Session user
        folder_id = str(uuid.uuid4())
        share_id = str(uuid.uuid4())

        await self.create_test_user(real_database, owner_id, 'folder-owner@example.com')
        await self.create_test_user(real_database, recipient_id, 'share-test@example.com')
        await self.create_test_folder(real_database, folder_id, owner_id, "Shared With Me Folder")

        await real_database.execute("""
            INSERT INTO resource_shares (id, resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ($1, 'workflow_folder', $2, 'user', $3, 'view', $4)
        """, share_id, folder_id, recipient_id, owner_id)

        await asyncio.sleep(0.1)

        request = ShareListSharedWithMeRequest(
            event_name="share:list_shared_with_me",
            request_id="test-folder-shared-with-me-1",
            resource_type="workflow_folder",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        matching = [e for e in response_events if e[1].get('request_id') == 'test-folder-shared-with-me-1']
        assert len(matching) == 1

        response_data = matching[0][1]['data']
        assert 'resources' in response_data
        resources = response_data['resources']
        assert len(resources) >= 1

        folder_resource = next((r for r in resources if r.get('resource_id') == folder_id), None)
        assert folder_resource is not None, "Shared folder should appear in shared-with-me list"
        assert folder_resource['permission'] == 'view'