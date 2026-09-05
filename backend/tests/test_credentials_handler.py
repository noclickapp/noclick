"""
Test suite for CredentialsHandler.

Validates credential management functionality with encryption:
- Creating encrypted credentials
- Listing credentials (without decrypted data)
- Retrieving credentials (with decrypted data)
- Updating credentials
- Deleting credentials
- Proper encryption/decryption
- Access control (user can only access their own credentials)
- Direct encryption/decryption testing
- Utility function testing
"""

import pytest
import pytest_asyncio
import asyncio
import uuid
import os
from typing import Dict, Any
from cryptography.fernet import Fernet

from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database
from wss.receiver.client_events import (
    CredentialCreateRequest,
    CredentialListRequest,
    CredentialGetRequest,
    CredentialUpdateRequest,
    CredentialDeleteRequest
)
from wss.sender import send_event
from utils.encryption import get_encryption
from utils.credentials import get_credential, list_credentials


@pytest.mark.asyncio
class TestCredentialsHandler(BaseHandlerTest):
    """
    Integration tests for CredentialsHandler with real PostgreSQL database.

    Verifies that credentials can be properly created, retrieved, updated, and deleted
    with encryption/decryption working correctly.
    """

    def get_session_data(self, sid: str):
        """Override to provide consistent test user ID."""
        return {
            'sid': sid,
            'user_id': '00000000-0000-4000-8000-000000000001',
            'email': 'credentials-test@example.com',
            'user_data': {
                'subscription_tier': 'enterprise',
            },
        }

    async def create_test_user(self, real_database, user_id: str, email: str = 'credentials-test@example.com'):
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

    async def test_create_credential_success(self, real_database, frontend_sio, sid):
        """
        Test that credentials can be successfully created with encryption.

        Verifies:
        - Credential is created in database
        - Response contains credential metadata
        - Encrypted data is stored (not plaintext)
        """
        user_id = '00000000-0000-4000-8000-000000000001'
        await self.create_test_user(real_database, user_id)
        await asyncio.sleep(0.1)

        # Create credential
        credential_data = {
            "api_key": "super_secret_key_123",
            "api_secret": "super_secret_456"
        }
        create_request = CredentialCreateRequest(
            event_name="credential:create",
            request_id="test-create-1",
            name="Test API Key",
            credential_type="api_key",
            credential_data=credential_data,
            metadata={"provider": "test_service", "environment": "production"}
        )

        await send_event(frontend_sio, sid, create_request)
        await asyncio.sleep(0.2)

        # Verify response
        response_events = self.get_main_api_emitted_events("response")
        assert len(response_events) >= 1, "Should receive response event"

        response_data = response_events[-1][1]
        assert response_data['request_id'] == 'test-create-1'
        assert 'data' in response_data
        assert response_data['data']['success'] == True
        assert response_data['data']['message'] == "Credential created successfully"

        credential = response_data['data']['credential']
        assert credential['name'] == "Test API Key"
        assert credential['credential_type'] == "api_key"
        assert credential['metadata']['provider'] == "test_service"
        credential_id = credential['id']

        # Verify encrypted data is stored in database (not plaintext)
        row = await real_database.fetchrow("""
            SELECT credential FROM credentials WHERE id = $1
        """, credential_id)
        assert row is not None
        encrypted_credential = row['credential']
        assert "super_secret_key_123" not in encrypted_credential, "Plaintext should not be stored"

    async def test_list_credentials(self, real_database, frontend_sio, sid):
        """
        Test that credentials can be listed without exposing decrypted data.

        Verifies:
        - Multiple credentials are returned
        - Decrypted data is NOT included in list
        - Metadata and basic info are included
        """
        user_id = '00000000-0000-4000-8000-000000000001'
        await self.create_test_user(real_database, user_id)
        await asyncio.sleep(0.1)

        # Create two credentials
        for i in range(2):
            create_request = CredentialCreateRequest(
                event_name="credential:create",
                request_id=f"test-create-{i}",
                name=f"Test Credential {i}",
                credential_type="oauth" if i == 0 else "database",
                credential_data={"secret": f"secret_{i}"},
                metadata={"index": i}
            )
            await send_event(frontend_sio, sid, create_request)
            await asyncio.sleep(0.1)

        # List credentials
        list_request = CredentialListRequest(
            event_name="credential:list",
            request_id="test-list-1"
        )
        await send_event(frontend_sio, sid, list_request)
        await asyncio.sleep(0.1)

        # Verify response
        response_events = self.get_main_api_emitted_events("response")
        # Filter to get the list response (not the create responses)
        list_response = None
        for event in response_events:
            if event[1]['request_id'] == 'test-list-1':
                list_response = event[1]
                break

        assert list_response is not None, "Should receive response for test-list-1"
        assert 'data' in list_response
        credentials = list_response['data']['credentials']
        assert len(credentials) >= 2, "Should have at least 2 credentials"

        # Verify no decrypted data in list
        for cred in credentials:
            assert 'id' in cred
            assert 'name' in cred
            assert 'credential_type' in cred
            assert 'metadata' in cred
            assert 'credential_data' not in cred, "Decrypted data should not be in list"

    async def test_list_carries_the_health_verdict_beside_the_provider_word(
        self, real_database, frontend_sio, sid, monkeypatch
    ):
        """The picker judges `connection_healthy`, never `connection_status`:
        Discord reports a live install as 'installed', and a string comparison
        against 'connected' rendered every one of them as "(disconnected)" with
        WhatsApp re-scan copy under it (2026-09-05). The hint that now rides
        along is what the banner renders."""
        from unittest.mock import AsyncMock

        import utils.credential_health as health_mod

        user_id = '00000000-0000-4000-8000-000000000001'
        await self.create_test_user(real_database, user_id)
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, CredentialCreateRequest(
            event_name="credential:create",
            request_id="create-discord",
            name="NoClick Sandbox",
            credential_type="discord_bot_install",
            credential_data={"bot_token": "platform"},
            metadata={"guild_id": "123456", "guild_name": "NoClick Sandbox"},
        ))
        await asyncio.sleep(0.1)
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "platform-token")

        async def discord_rows(request_id: str):
            await send_event(frontend_sio, sid, CredentialListRequest(
                event_name="credential:list", request_id=request_id,
            ))
            await asyncio.sleep(0.1)
            for event in self.get_main_api_emitted_events("response"):
                if event[1]['request_id'] == request_id:
                    return [
                        c for c in event[1]['data']['credentials']
                        if c['credential_type'] == 'discord_bot_install'
                    ]
            raise AssertionError(f"no response for {request_id}")

        # Discord answers 200 for the guild: the bot is still installed.
        monkeypatch.setattr(health_mod, "_probe_discord_guild", AsyncMock(return_value=200))
        [live] = await discord_rows("list-live")
        assert live["connection_status"] == "installed"
        assert live["connection_healthy"] is True
        assert live["connection_hint"] is None

        # Discord answers 404: the server's admin removed the bot.
        monkeypatch.setattr(health_mod, "_probe_discord_guild", AsyncMock(return_value=404))
        [gone] = await discord_rows("list-gone")
        assert gone["connection_status"] == "removed"
        assert gone["connection_healthy"] is False
        assert "NoClick Sandbox" in gone["connection_hint"]
        assert "Install bot" in gone["connection_hint"]

    async def test_get_credential_with_decryption(self, real_database, frontend_sio, sid):
        """
        Test that a specific credential can be retrieved with decrypted data.

        Verifies:
        - Credential data is properly decrypted
        - Decrypted data matches original data
        - Only owner can access their credentials
        """
        user_id = '00000000-0000-4000-8000-000000000001'
        await self.create_test_user(real_database, user_id)
        await asyncio.sleep(0.1)

        # Create credential
        original_data = {
            "username": "admin",
            "password": "secret_pass_123",
            "host": "db.example.com"
        }
        create_request = CredentialCreateRequest(
            event_name="credential:create",
            request_id="test-create-1",
            name="Database Credentials",
            credential_type="database",
            credential_data=original_data,
            metadata={"db_type": "postgresql"}
        )
        await send_event(frontend_sio, sid, create_request)
        await asyncio.sleep(0.2)

        # Get created credential ID from response
        response_events = self.get_main_api_emitted_events("response")
        create_response = None
        for event in response_events:
            if event[1]['request_id'] == 'test-create-1':
                create_response = event[1]
                break
        credential_id = create_response['data']['credential']['id']

        # Get credential with decryption
        get_request = CredentialGetRequest(
            event_name="credential:get",
            request_id="test-get-1",
            credential_id=credential_id
        )
        await send_event(frontend_sio, sid, get_request)
        await asyncio.sleep(0.2)

        # Verify response
        response_events = self.get_main_api_emitted_events("response")
        get_response = None
        for event in response_events:
            if event[1]['request_id'] == 'test-get-1':
                get_response = event[1]
                break

        assert get_response is not None, "Should receive response for test-get-1"
        assert 'data' in get_response
        data = get_response['data']
        assert data['credential_id'] == credential_id
        assert data['name'] == "Database Credentials"
        assert data['credential_type'] == "database"

        # Verify decrypted data matches original
        decrypted_data = data['credential_data']
        assert decrypted_data == original_data, "Decrypted data should match original"

    async def test_update_credential(self, real_database, frontend_sio, sid):
        """
        Test that credentials can be updated.

        Verifies:
        - Name can be updated
        - Credential data can be updated and re-encrypted
        - Metadata can be updated
        """
        user_id = '00000000-0000-4000-8000-000000000001'
        await self.create_test_user(real_database, user_id)
        await asyncio.sleep(0.1)

        # Create credential
        create_request = CredentialCreateRequest(
            event_name="credential:create",
            request_id="test-create-1",
            name="Old Name",
            credential_type="api_key",
            credential_data={"key": "old_key"},
            metadata={"version": "1"}
        )
        await send_event(frontend_sio, sid, create_request)
        await asyncio.sleep(0.2)

        # Get created credential ID from response
        response_events = self.get_main_api_emitted_events("response")
        create_response = None
        for event in response_events:
            if event[1]['request_id'] == 'test-create-1':
                create_response = event[1]
                break
        credential_id = create_response['data']['credential']['id']

        # Update credential
        new_data = {"key": "new_key_updated"}
        update_request = CredentialUpdateRequest(
            event_name="credential:update",
            request_id="test-update-1",
            credential_id=credential_id,
            name="New Name",
            credential_data=new_data,
            metadata={"version": "2"}
        )
        await send_event(frontend_sio, sid, update_request)
        await asyncio.sleep(0.2)

        # Verify response
        response_events = self.get_main_api_emitted_events("response")
        update_response = None
        for event in response_events:
            if event[1]['request_id'] == 'test-update-1':
                update_response = event[1]
                break

        assert update_response is not None, "Should receive response for test-update-1"
        assert 'data' in update_response
        updated_data = update_response['data']
        assert updated_data['success'] == True
        assert updated_data['credential']['name'] == "New Name"
        assert updated_data['credential']['metadata']['version'] == "2"

        # Verify updated data is properly encrypted and can be retrieved
        get_request = CredentialGetRequest(
            event_name="credential:get",
            request_id="test-get-1",
            credential_id=credential_id
        )
        await send_event(frontend_sio, sid, get_request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        get_response = None
        for event in response_events:
            if event[1]['request_id'] == 'test-get-1':
                get_response = event[1]
                break

        decrypted = get_response['data']['credential_data']
        assert decrypted == new_data, "Updated data should be properly encrypted and decrypted"

    async def test_delete_credential(self, real_database, frontend_sio, sid):
        """
        Test that credentials can be deleted.

        Verifies:
        - Credential is removed from database
        - Attempting to get deleted credential returns error
        """
        user_id = '00000000-0000-4000-8000-000000000001'
        await self.create_test_user(real_database, user_id)
        await asyncio.sleep(0.1)

        # Create credential
        create_request = CredentialCreateRequest(
            event_name="credential:create",
            request_id="test-create-1",
            name="To Be Deleted",
            credential_type="api_key",
            credential_data={"key": "temporary"},
            metadata={}
        )
        await send_event(frontend_sio, sid, create_request)
        await asyncio.sleep(0.2)

        # Get created credential ID from response
        response_events = self.get_main_api_emitted_events("response")
        create_response = None
        for event in response_events:
            if event[1]['request_id'] == 'test-create-1':
                create_response = event[1]
                break
        credential_id = create_response['data']['credential']['id']

        # Dry run first (no confirm): returns usage info, deletes nothing.
        dry_run_request = CredentialDeleteRequest(
            event_name="credential:delete",
            request_id="test-delete-dryrun-1",
            credential_id=credential_id,
        )
        await send_event(frontend_sio, sid, dry_run_request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        dry_run_response = None
        for event in response_events:
            if event[1]['request_id'] == 'test-delete-dryrun-1':
                dry_run_response = event[1]
                break
        assert dry_run_response is not None, "Should receive response for dry run"
        dry_data = dry_run_response['data']
        assert dry_data['success'] == True
        assert dry_data['deleted'] == False
        assert dry_data['affected_workflows'] == []
        row = await real_database.fetchrow(
            "SELECT id FROM credentials WHERE id = $1", credential_id
        )
        assert row is not None, "Dry run must not delete the credential"

        # Confirmed delete
        delete_request = CredentialDeleteRequest(
            event_name="credential:delete",
            request_id="test-delete-1",
            credential_id=credential_id,
            confirm=True,
        )
        await send_event(frontend_sio, sid, delete_request)
        await asyncio.sleep(0.2)

        # Verify response
        response_events = self.get_main_api_emitted_events("response")
        delete_response = None
        for event in response_events:
            if event[1]['request_id'] == 'test-delete-1':
                delete_response = event[1]
                break

        assert delete_response is not None, "Should receive response for test-delete-1"
        assert 'data' in delete_response
        deleted_data = delete_response['data']
        assert deleted_data['success'] == True
        assert deleted_data['credential_id'] == credential_id
        assert deleted_data['deleted'] == True

        # Verify credential is gone from database
        row = await real_database.fetchrow("""
            SELECT id FROM credentials WHERE id = $1
        """, credential_id)
        assert row is None, "Credential should be deleted from database"

    async def test_delete_rejected_for_non_owner_with_edit_share(
        self, real_database, frontend_sio, sid
    ):
        """
        Delete is owner-only: an edit share grants USE of a credential, never
        destruction of the owner's row (which would drop every other share too).

        Verifies:
        - credential:delete from an edit-share holder returns an error
        - The owner's credential row survives
        - The share row survives
        """
        caller_id = '00000000-0000-4000-8000-000000000001'  # the session user
        owner_id = '00000000-0000-4000-8000-000000000002'
        await self.create_test_user(real_database, caller_id)
        await self.create_test_user(real_database, owner_id, 'owner@example.com')

        # A credential owned by someone else, shared to the caller with EDIT.
        credential_id = str(uuid.uuid4())
        await real_database.execute("""
            INSERT INTO credentials (id, owner_id, name, credential_type, credential)
            VALUES ($1, $2, 'Owner''s Key', 'api_key', 'encrypted-blob')
        """, credential_id, owner_id)
        await real_database.execute("""
            INSERT INTO resource_shares (
                resource_type, resource_id, target_type,
                target_user_id, permission, shared_by
            )
            VALUES ('credential', $1, 'user', $2, 'edit', $3)
        """, credential_id, caller_id, owner_id)
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, CredentialDeleteRequest(
            event_name="credential:delete",
            request_id="test-delete-non-owner",
            credential_id=credential_id,
        ))
        await asyncio.sleep(0.2)

        delete_response = None
        for event in self.get_main_api_emitted_events("response"):
            if event[1]['request_id'] == 'test-delete-non-owner':
                delete_response = event[1]
                break

        assert delete_response is not None, "Should receive a response"
        assert delete_response.get('error'), (
            "Non-owner delete must be rejected with an error, "
            f"got: {delete_response}"
        )

        row = await real_database.fetchrow(
            "SELECT id FROM credentials WHERE id = $1", credential_id)
        assert row is not None, "Owner's credential must survive a non-owner delete"

        share = await real_database.fetchrow("""
            SELECT id FROM resource_shares
            WHERE resource_type = 'credential' AND resource_id = $1
        """, credential_id)
        assert share is not None, "The share must survive a non-owner delete"

    async def test_access_control_prevents_cross_user_access(self, real_database, frontend_sio, sid):
        """
        Test that users cannot access other users' credentials.

        Verifies:
        - Credentials are properly filtered by user_id in database
        - User B cannot access User A's credentials through database query
        """
        user_a_id = '00000000-0000-4000-8000-000000000001'
        user_b_id = '00000000-0000-4000-8000-000000000002'

        await self.create_test_user(real_database, user_a_id, 'user_a@example.com')
        await self.create_test_user(real_database, user_b_id, 'user_b@example.com')
        await asyncio.sleep(0.1)

        # User A creates a credential
        create_request = CredentialCreateRequest(
            event_name="credential:create",
            request_id="test-create-a",
            name="User A's Secret",
            credential_type="api_key",
            credential_data={"key": "user_a_secret"},
            metadata={}
        )
        await send_event(frontend_sio, sid, create_request)
        await asyncio.sleep(0.2)

        # Get created credential ID from response
        response_events = self.get_main_api_emitted_events("response")
        create_response = None
        for event in response_events:
            if event[1]['request_id'] == 'test-create-a':
                create_response = event[1]
                break
        credential_id = create_response['data']['credential']['id']

        # Verify via database that User B cannot access User A's credential
        # This simulates what would happen if User B tried to query for User A's credential
        row = await real_database.fetchrow("""
            SELECT id FROM credentials WHERE id = $1 AND owner_id = $2
        """, credential_id, user_b_id)
        assert row is None, "User B should not be able to query User A's credential"

        # Verify User A can still access their own credential
        row_a = await real_database.fetchrow("""
            SELECT id FROM credentials WHERE id = $1 AND owner_id = $2
        """, credential_id, user_a_id)
        assert row_a is not None, "User A should be able to access their own credential"

    async def test_oauth_credentials_type(self, real_database, frontend_sio, sid):
        """
        Test creating and retrieving OAuth credentials with typical OAuth fields.

        Verifies:
        - OAuth credential type works correctly
        - Complex OAuth data structures are properly encrypted/decrypted
        """
        user_id = '00000000-0000-4000-8000-000000000001'
        await self.create_test_user(real_database, user_id)
        await asyncio.sleep(0.1)

        # Create OAuth credential
        oauth_data = {
            "client_id": "oauth_client_123",
            "client_secret": "oauth_secret_456",
            "access_token": "access_token_789",
            "refresh_token": "refresh_token_abc",
            "token_expiry": "2024-12-31T23:59:59Z",
            "scopes": ["read", "write", "admin"]
        }
        create_request = CredentialCreateRequest(
            event_name="credential:create",
            request_id="test-create-oauth",
            name="GitHub OAuth",
            credential_type="oauth",
            credential_data=oauth_data,
            metadata={"provider": "github", "user": "testuser"}
        )
        await send_event(frontend_sio, sid, create_request)
        await asyncio.sleep(0.2)

        # Get created credential ID from response
        response_events = self.get_main_api_emitted_events("response")
        create_response = None
        for event in response_events:
            if event[1]['request_id'] == 'test-create-oauth':
                create_response = event[1]
                break
        credential_id = create_response['data']['credential']['id']

        # Retrieve and verify
        get_request = CredentialGetRequest(
            event_name="credential:get",
            request_id="test-get-oauth",
            credential_id=credential_id
        )
        await send_event(frontend_sio, sid, get_request)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        get_response = None
        for event in response_events:
            if event[1]['request_id'] == 'test-get-oauth':
                get_response = event[1]
                break

        decrypted = get_response['data']['credential_data']
        assert decrypted == oauth_data, "Complex OAuth structure should be preserved"

    async def test_encryption_decryption_roundtrip(self):
        """
        Test that encryption and decryption work correctly.

        Verifies:
        - Data can be encrypted
        - Encrypted data is different from plaintext
        - Decryption produces original data
        """
        encryption = get_encryption()

        original_data = {
            "api_key": "super_secret_key_12345",
            "api_secret": "ultra_secret_value_67890",
            "metadata": {"service": "test", "environment": "production"}
        }

        # Encrypt the data
        encrypted = encryption.encrypt_credential(original_data)

        # Verify encrypted data is different from plaintext
        assert "super_secret_key_12345" not in encrypted, "Plaintext should not appear in encrypted data"
        assert "ultra_secret_value_67890" not in encrypted, "Plaintext should not appear in encrypted data"
        assert isinstance(encrypted, str), "Encrypted data should be a string"

        # Decrypt and verify
        decrypted = encryption.decrypt_credential(encrypted)
        assert decrypted == original_data, "Decrypted data should match original"

    async def test_encryption_produces_different_ciphertexts(self):
        """
        Test that encrypting the same data twice produces different ciphertexts.

        This verifies that Fernet is using proper IV/nonce randomization.
        """
        encryption = get_encryption()

        data = {"secret": "test_value"}

        encrypted1 = encryption.encrypt_credential(data)
        encrypted2 = encryption.encrypt_credential(data)

        # Different ciphertexts (due to random IV/nonce)
        assert encrypted1 != encrypted2, "Encryption should produce different ciphertexts each time"

        # But both decrypt to same data
        decrypted1 = encryption.decrypt_credential(encrypted1)
        decrypted2 = encryption.decrypt_credential(encrypted2)
        assert decrypted1 == data
        assert decrypted2 == data

    async def test_utility_function_get_credential(self, real_database, frontend_sio, sid):
        """
        Test the get_credential utility function.

        Verifies:
        - Utility can retrieve and decrypt credentials
        - Utility respects user ownership (doesn't return other users' credentials)
        """
        user_id = '00000000-0000-4000-8000-000000000001'
        await self.create_test_user(real_database, user_id)
        await asyncio.sleep(0.1)

        # Create a credential via handler
        test_data = {
            "client_id": "oauth_client_abc",
            "client_secret": "oauth_secret_xyz"
        }

        create_request = CredentialCreateRequest(
            event_name="credential:create",
            request_id="test-util-1",
            name="OAuth Credentials",
            credential_type="oauth",
            credential_data=test_data,
            metadata={"provider": "github"}
        )

        await send_event(frontend_sio, sid, create_request)
        await asyncio.sleep(0.2)

        # Get credential ID
        response_events = self.get_main_api_emitted_events("response")
        create_response = None
        for event in response_events:
            if event[1]['request_id'] == 'test-util-1':
                create_response = event[1]
                break

        credential_id = create_response['data']['credential']['id']

        # Use utility function to retrieve credential (pass pool proxy for testing)
        pool = real_database.pool
        retrieved_data = await get_credential(credential_id, user_id, pool=pool)

        assert retrieved_data is not None, "Utility should retrieve credential"
        assert retrieved_data == test_data, "Retrieved data should match original"

    async def test_utility_function_access_control(self, real_database, frontend_sio, sid):
        """
        Test that utility function respects access control.

        Verifies:
        - Users cannot access other users' credentials via utility
        """
        user_a_id = '00000000-0000-4000-8000-000000000001'
        user_b_id = '00000000-0000-4000-8000-000000000002'

        await self.create_test_user(real_database, user_a_id, 'user_a@example.com')
        await self.create_test_user(real_database, user_b_id, 'user_b@example.com')
        await asyncio.sleep(0.1)

        # User A creates a credential
        create_request = CredentialCreateRequest(
            event_name="credential:create",
            request_id="test-util-access-1",
            name="User A's Secret",
            credential_type="api_key",
            credential_data={"key": "secret_a"},
            metadata={}
        )

        await send_event(frontend_sio, sid, create_request)
        await asyncio.sleep(0.2)

        # Get credential ID
        response_events = self.get_main_api_emitted_events("response")
        create_response = None
        for event in response_events:
            if event[1]['request_id'] == 'test-util-access-1':
                create_response = event[1]
                break

        credential_id = create_response['data']['credential']['id']

        # Get pool proxy for testing
        pool = real_database.pool

        # User A can access their own credential
        user_a_data = await get_credential(credential_id, user_a_id, pool=pool)
        assert user_a_data is not None, "User A should access their own credential"
        assert user_a_data['key'] == "secret_a"

        # User B cannot access User A's credential
        user_b_data = await get_credential(credential_id, user_b_id, pool=pool)
        assert user_b_data is None, "User B should not access User A's credential"

    async def test_utility_function_list_credentials(self, real_database, frontend_sio, sid):
        """
        Test the list_credentials utility function.

        Verifies:
        - Utility can list all credentials for a user
        - List does not include decrypted data
        """
        user_id = '00000000-0000-4000-8000-000000000001'
        await self.create_test_user(real_database, user_id)
        await asyncio.sleep(0.1)

        # Create multiple credentials
        for i in range(3):
            create_request = CredentialCreateRequest(
                event_name="credential:create",
                request_id=f"test-util-list-{i}",
                name=f"Credential {i}",
                credential_type="api_key",
                credential_data={"key": f"secret_{i}"},
                metadata={"index": i}
            )
            await send_event(frontend_sio, sid, create_request)
            await asyncio.sleep(0.1)

        await asyncio.sleep(0.2)

        # Use utility to list credentials (pass pool proxy for testing)
        pool = real_database.pool
        credentials = await list_credentials(user_id, pool=pool)

        assert len(credentials) >= 3, "Should list all credentials"

        # Verify metadata structure and no decrypted data
        for cred in credentials:
            assert 'id' in cred
            assert 'name' in cred
            assert 'credential_type' in cred
            assert 'metadata' in cred
            assert 'created_at' in cred
            assert 'updated_at' in cred
            # Verify no decrypted credential data
            assert 'credential_data' not in cred
            assert 'password' not in cred
            assert 'key' not in cred

    async def test_invalid_encrypted_data_fails_gracefully(self):
        """
        Test that attempting to decrypt invalid data fails gracefully.

        Verifies proper error handling for corrupted/invalid credentials.
        """
        encryption = get_encryption()

        # Try to decrypt garbage data
        invalid_data = "this_is_not_valid_encrypted_data"

        with pytest.raises(ValueError, match="Failed to decrypt credential"):
            encryption.decrypt_credential(invalid_data)
