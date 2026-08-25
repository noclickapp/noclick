"""
Test suite for credential request functionality.

Tests the full flow of requesting credentials from external users:
- Creating credential requests via WebSocket
- Listing credential requests
- Cancelling credential requests
- HTTP API for external credential provision (GET details, POST provide)
- Email notifications
- Rate limiting and expiration
"""

import pytest
import pytest_asyncio
import asyncio
from unittest.mock import ANY, patch, AsyncMock

from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database
from wss.receiver.client_events import (
    CredentialRequestCreateRequest,
    CredentialRequestListRequest,
    CredentialRequestCancelRequest,
)
from wss.sender import send_event


TEST_USER_ID = '00000000-0000-4000-8000-000000000001'
TEST_USER_EMAIL = 'requester@example.com'
TARGET_EMAIL = 'provider@example.com'


@pytest.mark.asyncio
class TestCredentialRequestHandler(BaseHandlerTest):
    """
    Integration tests for credential request WebSocket events.
    Tests create, list, and cancel operations.
    """

    def get_session_data(self, sid: str):
        return {
            'sid': sid,
            'user_id': TEST_USER_ID,
            'email': TEST_USER_EMAIL,
            'user_data': {
                'email': TEST_USER_EMAIL,
                'user_metadata': {'name': 'Test Requester'},
            },
        }

    async def create_test_user(self, real_database):
        await real_database.execute(
            "INSERT INTO auth.users (id, email, raw_user_meta_data) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            TEST_USER_ID, TEST_USER_EMAIL, {'name': 'Test Requester'},
        )

    async def ensure_credential_requests_table(self, real_database):
        """Ensure the credential_requests table exists for testing."""
        await real_database.execute("""
            CREATE TABLE IF NOT EXISTS credential_requests (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                requester_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
                target_email TEXT NOT NULL,
                credential_type TEXT NOT NULL,
                message TEXT,
                token TEXT UNIQUE NOT NULL DEFAULT encode(gen_random_bytes(32), 'hex'),
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'fulfilled', 'expired', 'cancelled')),
                credential_id UUID REFERENCES credentials(id) ON DELETE SET NULL,
                expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '7 days',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                fulfilled_at TIMESTAMPTZ,
                provision_attempts INT NOT NULL DEFAULT 0,
                CONSTRAINT unique_pending_request UNIQUE(requester_id, target_email, credential_type)
            )
        """)

    @patch('utils.email.send_credential_request_email', new_callable=AsyncMock, return_value=True)
    async def test_create_credential_request(self, mock_send_email, real_database, frontend_sio, sid):
        """Test creating a credential request sends email and returns request info."""
        await self.create_test_user(real_database)
        await self.ensure_credential_requests_table(real_database)
        await asyncio.sleep(0.1)

        request = CredentialRequestCreateRequest(
            request_id="test-req-create-1",
            target_email=TARGET_EMAIL,
            credential_type="google_sheets_oauth",
            message="Need your Google Sheets access for the report workflow",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        response_events = self.get_main_api_emitted_events("response")
        assert len(response_events) >= 1

        response_data = response_events[-1][1]
        assert response_data['request_id'] == 'test-req-create-1'
        assert response_data['data']['success'] is True
        assert response_data['data']['request']['target_email'] == TARGET_EMAIL
        assert response_data['data']['request']['credential_type'] == 'google_sheets_oauth'
        assert response_data['data']['request']['status'] == 'pending'

        # Verify email was called
        mock_send_email.assert_called_once()
        call_kwargs = mock_send_email.call_args
        assert call_kwargs[1]['to_email'] == TARGET_EMAIL or call_kwargs[0][0] == TARGET_EMAIL

    @patch('utils.email.send_credential_request_email', new_callable=AsyncMock, return_value=True)
    async def test_create_credential_request_link_mode(self, mock_send_email, real_database, frontend_sio, sid):
        """An empty target_email creates a shareable link and sends no email."""
        await self.create_test_user(real_database)
        await self.ensure_credential_requests_table(real_database)
        await asyncio.sleep(0.1)

        request = CredentialRequestCreateRequest(
            request_id="test-req-link-1",
            target_email="",
            credential_type="openai_api_key",
            frontend_url="https://app.example.com",
        )

        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        response_events = self.get_main_api_emitted_events("response")
        response_data = next(
            (e[1] for e in response_events if e[1].get('request_id') == 'test-req-link-1'),
            None,
        )
        assert response_data is not None
        assert response_data['data']['success'] is True
        # A copy-link provision URL is returned and points at the provide route
        provide_url = response_data['data']['provide_url']
        assert provide_url.startswith('https://app.example.com/credential/provide/')
        # No email is sent for link-mode requests
        mock_send_email.assert_not_called()

        # The persisted row stores an empty target_email
        row = await real_database.fetchrow(
            "SELECT target_email, status FROM credential_requests WHERE requester_id = $1 AND credential_type = $2",
            TEST_USER_ID, 'openai_api_key',
        )
        assert row['target_email'] == ''
        assert row['status'] == 'pending'

    @patch('utils.email.send_credential_request_email', new_callable=AsyncMock, return_value=True)
    async def test_list_credential_requests(self, mock_send_email, real_database, frontend_sio, sid):
        """Test listing credential requests returns all user's requests."""
        await self.create_test_user(real_database)
        await self.ensure_credential_requests_table(real_database)
        await asyncio.sleep(0.1)

        # Create two requests
        for email in [TARGET_EMAIL, 'other@example.com']:
            create_req = CredentialRequestCreateRequest(
                request_id=f"test-create-{email}",
                target_email=email,
                credential_type="openai_api_key",
            )
            await send_event(frontend_sio, sid, create_req)
            await asyncio.sleep(0.2)

        # List requests
        list_req = CredentialRequestListRequest(request_id="test-list-1")
        await send_event(frontend_sio, sid, list_req)
        await asyncio.sleep(0.2)

        response_events = self.get_main_api_emitted_events("response")
        list_response = next(
            (e[1] for e in response_events if e[1].get('request_id') == 'test-list-1'),
            None,
        )
        assert list_response is not None
        assert len(list_response['data']['requests']) >= 2

    @patch('utils.email.send_credential_request_email', new_callable=AsyncMock, return_value=True)
    async def test_cancel_credential_request(self, mock_send_email, real_database, frontend_sio, sid):
        """Test cancelling a pending credential request."""
        await self.create_test_user(real_database)
        await self.ensure_credential_requests_table(real_database)
        await asyncio.sleep(0.1)

        # Create request
        create_req = CredentialRequestCreateRequest(
            request_id="test-create-cancel",
            target_email=TARGET_EMAIL,
            credential_type="slack_oauth",
        )
        await send_event(frontend_sio, sid, create_req)
        await asyncio.sleep(0.2)

        # Get the request ID
        response_events = self.get_main_api_emitted_events("response")
        create_response = next(
            (e[1] for e in response_events if e[1].get('request_id') == 'test-create-cancel'),
            None,
        )
        assert create_response is not None
        request_id = create_response['data']['request']['id']

        # Cancel request
        cancel_req = CredentialRequestCancelRequest(
            request_id="test-cancel-1",
            credential_request_id=request_id,
        )
        await send_event(frontend_sio, sid, cancel_req)
        await asyncio.sleep(0.2)

        cancel_response = next(
            (e[1] for e in self.get_main_api_emitted_events("response") if e[1].get('request_id') == 'test-cancel-1'),
            None,
        )
        assert cancel_response is not None
        assert cancel_response['data']['success'] is True

        # Verify status in DB
        row = await real_database.fetchrow(
            "SELECT status FROM credential_requests WHERE id = $1",
            request_id,
        )
        assert row['status'] == 'cancelled'


PROVIDER_USER_ID = '00000000-0000-4000-8000-000000000002'


def _direct_db_helper(conn_params: dict):
    """Create a helper that executes queries via separate auto-commit connections.

    This bypasses the postgres_db transaction wrapper, so data is visible
    to all connections (including those created by route functions in threads).
    """
    import threading
    import asyncpg as _asyncpg

    class DirectDB:
        def _run(self, coro_factory):
            result_container = [None]
            exc_container = [None]

            def _thread():
                loop = asyncio.new_event_loop()
                conn = None
                try:
                    conn = loop.run_until_complete(
                        _asyncpg.connect(**{k: v for k, v in conn_params.items() if v is not None})
                    )
                    from utils.database_pool import setup_asyncpg_codecs
                    loop.run_until_complete(setup_asyncpg_codecs(conn))
                    result_container[0] = loop.run_until_complete(coro_factory(conn))
                except Exception as e:
                    exc_container[0] = e
                finally:
                    if conn:
                        loop.run_until_complete(conn.close())
                    loop.close()

            t = threading.Thread(target=_thread)
            t.start()
            t.join(timeout=30)
            if exc_container[0]:
                raise exc_container[0]
            return result_container[0]

        def execute(self, query, *args):
            return self._run(lambda c: c.execute(query, *args))

        def fetchrow(self, query, *args):
            return self._run(lambda c: c.fetchrow(query, *args))

        def fetch(self, query, *args):
            return self._run(lambda c: c.fetch(query, *args))

    return DirectDB()


@pytest.mark.asyncio
class TestCredentialRequestHTTPAPI:
    """
    Tests for the HTTP API endpoints used by external users to provide credentials.
    These endpoints don't require authentication.

    Uses DirectDB for data setup/verification so that all operations go through
    auto-commit connections, matching the route functions' thread-based path.
    """

    @pytest.fixture
    def db(self, real_database):
        """Provide a DirectDB that uses auto-commit connections for setup/verification."""
        return _direct_db_helper(real_database.conn_params)

    @pytest.fixture
    def setup_db(self, db):
        """Set up test data in the database."""
        db.execute("DELETE FROM resource_shares WHERE resource_type = 'credential'")
        db.execute("DELETE FROM credential_requests")

        db.execute(
            "INSERT INTO auth.users (id, email, raw_user_meta_data) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            TEST_USER_ID, TEST_USER_EMAIL, {'name': 'Test Requester'},
        )

        row = db.fetchrow("""
            INSERT INTO credential_requests (requester_id, target_email, credential_type, message)
            VALUES ($1, $2, $3, $4)
            RETURNING id, token
        """, TEST_USER_ID, TARGET_EMAIL, 'openai_api_key', 'Need your OpenAI key')

        yield {'request_id': str(row['id']), 'token': row['token']}

        # Explicit cleanup (no transaction rollback for auto-commit connections)
        db.execute("DELETE FROM resource_shares WHERE resource_type = 'credential'")
        db.execute("DELETE FROM credential_requests")
        db.execute("DELETE FROM credentials WHERE credential_type = 'openai_api_key'")

    async def test_get_request_details(self, real_database, setup_db):
        """Test GET /api/credential-request/{token} returns request details."""
        from utils.credential_request_routes import get_credential_request

        details = await get_credential_request(setup_db['token'])
        assert details.credential_type == 'openai_api_key'
        assert details.requester_name == 'Test Requester'
        assert details.requester_email == TEST_USER_EMAIL
        assert details.message == 'Need your OpenAI key'
        assert details.is_oauth is False
        assert details.status == 'pending'

    async def test_get_request_details_not_found(self, real_database, setup_db):
        """Test GET with invalid token returns 404."""
        from utils.credential_request_routes import get_credential_request
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_credential_request('nonexistent_token')
        assert exc_info.value.status_code == 404

    @patch('utils.credential_request_routes.send_credential_fulfilled_email', new_callable=AsyncMock, return_value=True)
    async def test_provide_api_key_credential(self, mock_send_email, real_database, db, setup_db):
        """Test POST /api/credential-request/{token}/provide with API key."""
        from utils.credential_request_routes import provide_credential, ProvideCredentialBody

        body = ProvideCredentialBody(
            credential_data={'api_key': 'sk-test-key-12345'},
        )

        result = await provide_credential(setup_db['token'], body)
        assert result['status'] == 'success'

        # Verify credential was created and encrypted
        row = db.fetchrow(
            "SELECT owner_id, credential_type, credential FROM credentials ORDER BY created_at DESC LIMIT 1"
        )
        assert row is not None
        assert str(row['owner_id']) == TEST_USER_ID
        assert row['credential_type'] == 'openai_api_key'
        assert 'sk-test-key-12345' not in row['credential']  # Should be encrypted

        # Verify request was marked as fulfilled
        req_row = db.fetchrow(
            "SELECT status, credential_id FROM credential_requests WHERE id = $1",
            setup_db['request_id'],
        )
        assert req_row['status'] == 'fulfilled'
        assert req_row['credential_id'] is not None

        # Verify notification email was sent
        mock_send_email.assert_called_once()

    @patch('utils.credential_request_routes.send_credential_fulfilled_email', new_callable=AsyncMock, return_value=True)
    async def test_agent_llm_credential_request(self, mock_send_email, real_database, db):
        """agent_<provider> requests resolve the provider's API-key field and store
        the nested {credentials: {...}} shape + provider metadata the agent runtime
        expects — even though agent credentials aren't tied to a node schema."""
        import json
        from utils.credential_request_routes import (
            get_credential_request, provide_credential, ProvideCredentialBody,
        )
        from utils.encryption import get_encryption

        db.execute(
            "INSERT INTO auth.users (id, email, raw_user_meta_data) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            TEST_USER_ID, TEST_USER_EMAIL, {'name': 'Test Requester'},
        )
        db.execute("DELETE FROM credentials WHERE credential_type = 'agent_anthropic'")
        db.execute("DELETE FROM credential_requests WHERE credential_type = 'agent_anthropic'")
        # Empty target_email → a copy-link (no-email) request, the agent-node case.
        row = db.fetchrow("""
            INSERT INTO credential_requests (requester_id, target_email, credential_type)
            VALUES ($1, $2, $3)
            RETURNING id, token
        """, TEST_USER_ID, '', 'agent_anthropic')
        token = row['token']

        try:
            # GET resolves the provider's API-key field (not OAuth, not a node schema)
            details = await get_credential_request(token)
            assert details.is_oauth is False
            assert [f.name for f in details.credential_fields] == ['ANTHROPIC_API_KEY']
            assert details.credential_fields[0].type == 'password'
            assert details.credential_fields[0].label == 'Anthropic API Key'

            # Provide stores the nested agent blob + provider metadata
            body = ProvideCredentialBody(credential_data={'ANTHROPIC_API_KEY': 'sk-ant-test-999'})
            result = await provide_credential(token, body)
            assert result['status'] == 'success'

            cred = db.fetchrow(
                "SELECT credential, metadata FROM credentials "
                "WHERE credential_type = 'agent_anthropic' ORDER BY created_at DESC LIMIT 1"
            )
            assert cred is not None
            meta = cred['metadata']
            meta = json.loads(meta) if isinstance(meta, str) else meta
            assert meta['provider'] == 'anthropic'
            decrypted = get_encryption().decrypt_credential(cred['credential'])
            assert decrypted == {'credentials': {'ANTHROPIC_API_KEY': 'sk-ant-test-999'}}
        finally:
            db.execute("DELETE FROM credentials WHERE credential_type = 'agent_anthropic'")
            db.execute("DELETE FROM credential_requests WHERE credential_type = 'agent_anthropic'")


    async def test_oauth_method_advertises_connect_requirements(self, real_database, db):
        """The provide link must advertise the SAME OAuth pre-connect requirements the in-app
        UI reads from the schema, so a provider that needs an extra input (custom client)
        works on the link too. Shopify → supports_custom_client; GBP → requires_custom_client."""
        from utils.credential_request_routes import get_credential_request

        db.execute(
            "INSERT INTO auth.users (id, email, raw_user_meta_data) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            TEST_USER_ID, TEST_USER_EMAIL, {'name': 'Test Requester'},
        )
        for cred_type in ('shopify_oauth', 'google_business_profile_oauth'):
            db.execute("DELETE FROM credential_requests WHERE credential_type = $1", cred_type)
        try:
            shop_token = db.fetchrow(
                "INSERT INTO credential_requests (requester_id, target_email, credential_type) "
                "VALUES ($1, '', 'shopify_oauth') RETURNING token",
                TEST_USER_ID,
            )['token']
            shop = await get_credential_request(shop_token)
            shop_oauth = next(m for m in shop.available_methods if m.credential_type == 'shopify_oauth')
            assert shop_oauth.supports_custom_client is True
            assert shop_oauth.requires_custom_client is False

            gbp_token = db.fetchrow(
                "INSERT INTO credential_requests (requester_id, target_email, credential_type) "
                "VALUES ($1, '', 'google_business_profile_oauth') RETURNING token",
                TEST_USER_ID,
            )['token']
            gbp = await get_credential_request(gbp_token)
            # Single-method (no sibling) OAuth type still advertises its connect flags.
            gbp_method = next(m for m in gbp.available_methods if m.credential_type == 'google_business_profile_oauth')
            assert gbp_method.requires_custom_client is True
        finally:
            for cred_type in ('shopify_oauth', 'google_business_profile_oauth'):
                db.execute("DELETE FROM credential_requests WHERE credential_type = $1", cred_type)

    async def test_multi_method_node_advertises_all_siblings(self, real_database, db):
        """A request for ONE credential type of a multi-auth node (http_api_key) must
        advertise ALL sibling methods with their real fields — matching the node panel,
        not collapsing to a single generic 'Credential Value' box. Regression guard for
        the frontend deriving the wrong credential_type (raw title vs schema const)."""
        from utils.credential_request_routes import get_credential_request

        db.execute(
            "INSERT INTO auth.users (id, email, raw_user_meta_data) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            TEST_USER_ID, TEST_USER_EMAIL, {'name': 'Test Requester'},
        )
        db.execute("DELETE FROM credential_requests WHERE credential_type = 'http_api_key'")
        try:
            token = db.fetchrow(
                "INSERT INTO credential_requests (requester_id, target_email, credential_type) "
                "VALUES ($1, '', 'http_api_key') RETURNING token",
                TEST_USER_ID,
            )['token']
            details = await get_credential_request(token)
            method_types = {m.credential_type for m in details.available_methods}
            assert {'http_api_key', 'http_bearer_token', 'http_basic_auth',
                    'http_oauth2_client_credentials'} <= method_types
            # The API-key method exposes its real fields (not a generic paste box)
            apikey = next(m for m in details.available_methods if m.credential_type == 'http_api_key')
            assert any(f.name == 'api_key' for f in apikey.credential_fields)
        finally:
            db.execute("DELETE FROM credential_requests WHERE credential_type = 'http_api_key'")

    @patch('utils.credential_request_routes.send_credential_fulfilled_email', new_callable=AsyncMock, return_value=True)
    async def test_agent_oauth_device_code_stores_credential(self, mock_email, real_database, db):
        """The public device-code endpoints mint + store an agent OAuth credential for
        the requester and fulfil the request (Codex/ChatGPT flow, provider mocked)."""
        import httpx
        import respx
        from utils.credential_request_routes import (
            agent_oauth_start, agent_oauth_complete,
            AgentOAuthStartBody, AgentOAuthCompleteBody,
        )
        from nodes.agent.harness_oauth_flows import CODEX_ISSUER
        from utils.encryption import get_encryption

        db.execute(
            "INSERT INTO auth.users (id, email, raw_user_meta_data) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            TEST_USER_ID, TEST_USER_EMAIL, {'name': 'Test Requester'},
        )
        db.execute("DELETE FROM credentials WHERE credential_type = 'agent_codex_oauth'")
        db.execute("DELETE FROM credential_requests WHERE credential_type = 'agent_codex'")
        req = db.fetchrow(
            "INSERT INTO credential_requests (requester_id, target_email, credential_type) "
            "VALUES ($1, '', 'agent_codex') RETURNING id, token",
            TEST_USER_ID,
        )
        token = req['token']
        oauth_type = 'agent_codex_oauth'

        try:
            with respx.mock:
                respx.post(f"{CODEX_ISSUER}/api/accounts/deviceauth/usercode").mock(
                    return_value=httpx.Response(200, json={
                        "user_code": "ABCD-1234", "device_auth_id": "dev-9", "interval": 5,
                    })
                )
                # 1st poll pending, 2nd poll approved
                respx.post(f"{CODEX_ISSUER}/api/accounts/deviceauth/token").mock(side_effect=[
                    httpx.Response(403, json={}),
                    httpx.Response(200, json={"authorization_code": "authz", "code_verifier": "ver"}),
                ])
                respx.post(f"{CODEX_ISSUER}/oauth/token").mock(
                    return_value=httpx.Response(200, json={
                        "access_token": "acc-tok", "refresh_token": "ref-tok", "id_token": "id-tok", "expires_in": 3600,
                    })
                )

                start = await agent_oauth_start(token, AgentOAuthStartBody(credential_type=oauth_type))
                assert start['kind'] == 'device_code'
                assert start['display']['user_code'] == "ABCD-1234"

                pending = await agent_oauth_complete(
                    token, AgentOAuthCompleteBody(credential_type=oauth_type, poll=start['poll'])
                )
                assert pending['status'] == 'pending'

                done = await agent_oauth_complete(
                    token, AgentOAuthCompleteBody(credential_type=oauth_type, poll=start['poll'])
                )
                assert done['status'] == 'success'

            cred = db.fetchrow(
                "SELECT credential, metadata FROM credentials "
                "WHERE credential_type = 'agent_codex_oauth' ORDER BY created_at DESC LIMIT 1"
            )
            assert cred is not None
            meta = cred['metadata']
            meta = json.loads(meta) if isinstance(meta, str) else meta
            assert meta['provider'] == 'codex'
            decrypted = get_encryption().decrypt_credential(cred['credential'])
            assert decrypted['credentials']['CODEX_ACCESS_TOKEN'] == 'acc-tok'
            assert decrypted['credentials']['CODEX_REFRESH_TOKEN'] == 'ref-tok'

            req_row = db.fetchrow("SELECT status FROM credential_requests WHERE id = $1", req['id'])
            assert req_row['status'] == 'fulfilled'
        finally:
            db.execute("DELETE FROM credentials WHERE credential_type = 'agent_codex_oauth'")
            db.execute("DELETE FROM credential_requests WHERE credential_type = 'agent_codex'")


    async def test_provide_credential_expired(self, real_database, db, setup_db):
        """Test that expired requests are rejected."""
        from utils.credential_request_routes import provide_credential, ProvideCredentialBody
        from fastapi import HTTPException

        # Expire the request
        db.execute(
            "UPDATE credential_requests SET expires_at = NOW() - INTERVAL '1 day' WHERE id = $1",
            setup_db['request_id'],
        )

        body = ProvideCredentialBody(credential_data={'api_key': 'test'})

        with pytest.raises(HTTPException) as exc_info:
            await provide_credential(setup_db['token'], body)
        assert exc_info.value.status_code == 410

    async def test_provide_credential_rate_limited(self, real_database, db, setup_db):
        """Test that requests with too many attempts are rejected."""
        from utils.credential_request_routes import provide_credential, ProvideCredentialBody, MAX_PROVISION_ATTEMPTS
        from fastapi import HTTPException

        # Set attempts to max
        db.execute(
            "UPDATE credential_requests SET provision_attempts = $1 WHERE id = $2",
            MAX_PROVISION_ATTEMPTS, setup_db['request_id'],
        )

        body = ProvideCredentialBody(credential_data={'api_key': 'test'})

        with pytest.raises(HTTPException) as exc_info:
            await provide_credential(setup_db['token'], body)
        assert exc_info.value.status_code == 429

    async def test_provide_credential_already_fulfilled(self, real_database, db, setup_db):
        """Test that already-fulfilled requests are rejected."""
        from utils.credential_request_routes import provide_credential, ProvideCredentialBody
        from fastapi import HTTPException

        # Mark as fulfilled
        db.execute(
            "UPDATE credential_requests SET status = 'fulfilled' WHERE id = $1",
            setup_db['request_id'],
        )

        body = ProvideCredentialBody(credential_data={'api_key': 'test'})

        with pytest.raises(HTTPException) as exc_info:
            await provide_credential(setup_db['token'], body)
        assert exc_info.value.status_code == 410


@pytest.mark.asyncio
class TestCredentialOwnershipTransfer:
    """
    Tests for credential ownership transfer when the provider has or gets
    a NoClick account. Ensures the provider becomes the owner and the
    requester gets a share record.

    Uses DirectDB for data setup/verification so that all operations go through
    auto-commit connections, matching the route functions' thread-based path.
    """

    @pytest.fixture
    def db(self, real_database):
        """Provide a DirectDB that uses auto-commit connections for setup/verification."""
        return _direct_db_helper(real_database.conn_params)

    @pytest.fixture
    def setup_db(self, db):
        """Set up credential_requests table, test users, and a pending request."""
        # Clean up leftover data (including provider user from prior tests)
        db.execute("DELETE FROM resource_shares WHERE resource_type = 'credential'")
        db.execute("DELETE FROM credential_requests")
        db.execute("DELETE FROM credentials WHERE credential_type = 'openai_api_key'")
        db.execute("DELETE FROM auth.users WHERE id = $1", PROVIDER_USER_ID)

        # Create requester user
        db.execute(
            "INSERT INTO auth.users (id, email, raw_user_meta_data) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            TEST_USER_ID, TEST_USER_EMAIL, {'name': 'Test Requester'},
        )

        # Create a pending credential request
        row = db.fetchrow("""
            INSERT INTO credential_requests (requester_id, target_email, credential_type, message)
            VALUES ($1, $2, $3, $4)
            RETURNING id, token
        """, TEST_USER_ID, TARGET_EMAIL, 'openai_api_key', 'Need your key')

        yield {'request_id': str(row['id']), 'token': row['token']}

        # Explicit cleanup
        db.execute("DELETE FROM resource_shares WHERE resource_type = 'credential'")
        db.execute("DELETE FROM credential_requests")
        db.execute("DELETE FROM credentials WHERE credential_type = 'openai_api_key'")
        db.execute("DELETE FROM auth.users WHERE id = $1", PROVIDER_USER_ID)

    @patch('utils.credential_request_routes.send_credential_fulfilled_email', new_callable=AsyncMock, return_value=True)
    async def test_immediate_transfer_when_provider_has_account(self, mock_email, real_database, db, setup_db):
        """When the provider already has an account, the credential should be
        owned by the provider and the requester should get an edit share."""
        from utils.credential_request_routes import provide_credential, ProvideCredentialBody

        # Create the provider user BEFORE they provide the credential
        db.execute(
            "INSERT INTO auth.users (id, email, raw_user_meta_data) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            PROVIDER_USER_ID, TARGET_EMAIL, {'name': 'Provider User'},
        )

        body = ProvideCredentialBody(credential_data={'api_key': 'sk-provider-key'})
        result = await provide_credential(setup_db['token'], body)
        assert result['status'] == 'success'

        # Credential should be owned by the provider, not the requester
        cred_row = db.fetchrow(
            "SELECT owner_id, credential_type FROM credentials ORDER BY created_at DESC LIMIT 1"
        )
        assert cred_row is not None
        assert str(cred_row['owner_id']) == PROVIDER_USER_ID

        # Requester should have an edit share
        share_row = db.fetchrow(
            """SELECT target_user_id, permission, shared_by
               FROM resource_shares
               WHERE resource_type = 'credential' AND resource_id = (
                   SELECT credential_id FROM credential_requests WHERE id = $1
               )""",
            setup_db['request_id'],
        )
        assert share_row is not None
        assert str(share_row['target_user_id']) == TEST_USER_ID
        assert share_row['permission'] == 'edit'
        assert str(share_row['shared_by']) == PROVIDER_USER_ID

    @patch('utils.credential_request_routes.send_credential_fulfilled_email', new_callable=AsyncMock, return_value=True)
    async def test_no_transfer_when_provider_has_no_account(self, mock_email, real_database, db, setup_db):
        """When the provider has no account, the credential should stay
        owned by the requester with no share record."""
        from utils.credential_request_routes import provide_credential, ProvideCredentialBody

        body = ProvideCredentialBody(credential_data={'api_key': 'sk-some-key'})
        result = await provide_credential(setup_db['token'], body)
        assert result['status'] == 'success'

        # Credential should be owned by the requester
        cred_row = db.fetchrow(
            "SELECT owner_id FROM credentials ORDER BY created_at DESC LIMIT 1"
        )
        assert str(cred_row['owner_id']) == TEST_USER_ID

        # No share records should exist for this credential
        share_count = db.fetchrow(
            """SELECT COUNT(*) as cnt FROM resource_shares
               WHERE resource_type = 'credential' AND resource_id = (
                   SELECT credential_id FROM credential_requests WHERE id = $1
               )""",
            setup_db['request_id'],
        )
        assert share_count['cnt'] == 0

    @patch('utils.credential_request_routes.send_credential_fulfilled_email', new_callable=AsyncMock, return_value=True)
    async def test_deferred_transfer_on_setup_user(self, mock_email, real_database, db, setup_db):
        """When the provider signs up AFTER providing the credential, ownership
        should transfer during setup_user()."""
        from utils.credential_request_routes import provide_credential, ProvideCredentialBody
        from wss.handlers.credentials_handler import CredentialsHandler

        # Provide credential while provider has no account
        body = ProvideCredentialBody(credential_data={'api_key': 'sk-deferred-key'})
        await provide_credential(setup_db['token'], body)

        # Verify credential is owned by requester
        cred_row = db.fetchrow(
            "SELECT id, owner_id FROM credentials ORDER BY created_at DESC LIMIT 1"
        )
        assert str(cred_row['owner_id']) == TEST_USER_ID
        credential_id = str(cred_row['id'])

        # Now the provider signs up
        db.execute(
            "INSERT INTO auth.users (id, email, raw_user_meta_data) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            PROVIDER_USER_ID, TARGET_EMAIL, {'name': 'Provider User'},
        )

        # Simulate the background transfer directly (setup_user fires it as a task)
        mock_sio = AsyncMock()
        mock_sio.get_session = AsyncMock(return_value={
            'user_id': PROVIDER_USER_ID,
            'user_data': {'email': TARGET_EMAIL},
        })
        handler = CredentialsHandler(mock_sio)
        await handler._transfer_provided_credentials('test-sid')

        # Credential should now be owned by the provider
        cred_row = db.fetchrow(
            "SELECT owner_id FROM credentials WHERE id = $1", credential_id,
        )
        assert str(cred_row['owner_id']) == PROVIDER_USER_ID

        # Requester should have an edit share
        share_row = db.fetchrow(
            """SELECT target_user_id, permission
               FROM resource_shares
               WHERE resource_type = 'credential' AND resource_id = $1""",
            credential_id,
        )
        assert share_row is not None
        assert str(share_row['target_user_id']) == TEST_USER_ID
        assert share_row['permission'] == 'edit'

    @patch('utils.credential_request_routes.send_credential_fulfilled_email', new_callable=AsyncMock, return_value=True)
    async def test_deferred_transfer_is_idempotent(self, mock_email, real_database, db, setup_db):
        """Running setup_user() multiple times should not create duplicate shares."""
        from utils.credential_request_routes import provide_credential, ProvideCredentialBody
        from wss.handlers.credentials_handler import CredentialsHandler

        # Provide credential, then sign up
        body = ProvideCredentialBody(credential_data={'api_key': 'sk-idempotent'})
        await provide_credential(setup_db['token'], body)

        db.execute(
            "INSERT INTO auth.users (id, email, raw_user_meta_data) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            PROVIDER_USER_ID, TARGET_EMAIL, {'name': 'Provider User'},
        )

        mock_sio = AsyncMock()
        mock_sio.get_session = AsyncMock(return_value={
            'user_id': PROVIDER_USER_ID,
            'user_data': {'email': TARGET_EMAIL},
        })
        handler = CredentialsHandler(mock_sio)

        # Call the transfer method twice directly
        await handler._transfer_provided_credentials('test-sid')
        await handler._transfer_provided_credentials('test-sid')

        # Should still have exactly one share
        share_count = db.fetchrow(
            """SELECT COUNT(*) as cnt FROM resource_shares
               WHERE resource_type = 'credential' AND resource_id = (
                   SELECT credential_id FROM credential_requests WHERE id = $1
               )""",
            setup_db['request_id'],
        )
        assert share_count['cnt'] == 1


@pytest.mark.asyncio
class TestWhatsAppQRProvideLink:
    """The public WhatsApp QR scan over a credential-provide link.

    Pins the two properties the standardized dispatcher depends on:
      1. A whatsapp_qr request advertises a `qr_scan` method with NO leaked
         `connection_id` field (the acute bug: the link asked users to *type* a
         Connection ID instead of scanning).
      2. The /qr/{start,status} endpoints gate to whatsapp_qr, bind the
         connection to the REQUESTER, and fulfil the request on connect.
    The binding-safety internals (reservation + unique index + charge) live in
    the shared core and are pinned by test_whatsapp_qr_bind_guard.py; here the
    core is mocked so the endpoint contract is tested in isolation.
    """

    @pytest.fixture
    def db(self, real_database):
        return _direct_db_helper(real_database.conn_params)

    @pytest.fixture
    def setup_db(self, db):
        db.execute("DELETE FROM credential_requests WHERE credential_type = 'whatsapp_qr'")
        db.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")
        db.execute(
            "INSERT INTO auth.users (id, email, raw_user_meta_data) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            TEST_USER_ID, TEST_USER_EMAIL, {'name': 'Test Requester'},
        )
        # Copy-link (no target email) — the common provide-link case.
        row = db.fetchrow("""
            INSERT INTO credential_requests (requester_id, target_email, credential_type)
            VALUES ($1, '', 'whatsapp_qr')
            RETURNING id, token
        """, TEST_USER_ID)
        yield {'request_id': str(row['id']), 'token': row['token']}
        db.execute("DELETE FROM credential_requests WHERE credential_type = 'whatsapp_qr'")
        db.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")

    async def test_qr_request_advertises_qr_scan_method_without_connection_id(self, real_database, setup_db):
        """GET returns a qr_scan method (no connection_id field) — the acute fix."""
        from utils.credential_request_routes import get_credential_request

        details = await get_credential_request(setup_db['token'])
        assert details.credential_type == 'whatsapp_qr'
        qr = next((m for m in details.available_methods if m.credential_type == 'whatsapp_qr'), None)
        assert qr is not None, "whatsapp_qr method must be advertised"
        assert qr.method_kind == 'qr_scan'
        # The internal connection_id must never surface as a typed field.
        assert all(f.name != 'connection_id' for f in qr.credential_fields)

    async def test_qr_start_gated_to_whatsapp_qr_type(self, real_database, db):
        """/qr/start on a non-QR request is rejected (400)."""
        from utils.credential_request_routes import qr_start
        from fastapi import HTTPException

        db.execute("DELETE FROM credential_requests WHERE credential_type = 'openai_api_key'")
        token = db.fetchrow(
            "INSERT INTO credential_requests (requester_id, target_email, credential_type) "
            "VALUES ($1, '', 'openai_api_key') RETURNING token",
            TEST_USER_ID,
        )['token']
        try:
            with pytest.raises(HTTPException) as exc:
                await qr_start(token)
            assert exc.value.status_code == 400
        finally:
            db.execute("DELETE FROM credential_requests WHERE credential_type = 'openai_api_key'")

    @patch('utils.whatsapp_qr.start_qr_connection', new_callable=AsyncMock)
    async def test_qr_start_binds_connection_to_requester(self, mock_start, real_database, setup_db):
        """/qr/start delegates to the core with owner_id = the requester."""
        from utils.credential_request_routes import qr_start

        mock_start.return_value = {
            'success': True, 'connection_id': 'conn-xyz', 'qr_code': 'QR==', 'message': 'scan',
        }
        result = await qr_start(setup_db['token'])
        assert result['connection_id'] == 'conn-xyz'
        assert result['qr_code'] == 'QR=='
        mock_start.assert_awaited_once_with(ANY, owner_id=TEST_USER_ID)

    @patch('utils.credential_request_routes.send_credential_fulfilled_email', new_callable=AsyncMock, return_value=True)
    @patch('utils.whatsapp_qr.finalize_qr_connection', new_callable=AsyncMock)
    async def test_qr_status_fulfills_request_for_requester(self, mock_finalize, mock_email, real_database, db, setup_db):
        """On connect, /qr/status binds via the core (owner = requester) and CAS-fulfils
        the request with the minted credential; copy-link requests send no email."""
        from utils.credential_request_routes import qr_status, QRStatusBody

        # A real whatsapp_qr credential (the FK target of credential_requests.credential_id),
        # owned by the requester — what the core would have minted.
        cred_id = str(db.fetchrow("""
            INSERT INTO credentials (owner_id, name, credential_type, credential, metadata)
            VALUES ($1, 'WhatsApp (QR)', 'whatsapp_qr', 'enc', $2)
            RETURNING id
        """, TEST_USER_ID, {'provider': 'wahooks', 'connection_id': 'conn-xyz'})['id'])

        mock_finalize.return_value = {
            'success': True, 'status': 'connected', 'credential_id': cred_id,
            'credential_name': 'WhatsApp (QR)', 'phone_number': '+123', 'created': True,
            'message': 'WhatsApp connected successfully!',
        }

        result = await qr_status(setup_db['token'], QRStatusBody(connection_id='conn-xyz'))
        assert result['status'] == 'connected'
        assert result['credential_id'] == cred_id

        # Core was invoked bound to the requester as owner.
        assert mock_finalize.await_args.kwargs['owner_id'] == TEST_USER_ID
        assert mock_finalize.await_args.kwargs['connection_id'] == 'conn-xyz'

        # Request is fulfilled with that credential.
        req = db.fetchrow(
            "SELECT status, credential_id FROM credential_requests WHERE id = $1",
            setup_db['request_id'],
        )
        assert req['status'] == 'fulfilled'
        assert str(req['credential_id']) == cred_id
        # Copy-link request (empty target_email) → no fulfillment email.
        mock_email.assert_not_called()

    @patch('utils.whatsapp_qr.start_qr_connection', new_callable=AsyncMock)
    async def test_qr_start_rate_limited_per_token(self, mock_start, monkeypatch, real_database, setup_db):
        """Public /qr/start is capped per token so a leaked link can't mint/hold connections
        on the shared WAHooks account without bound. Over the cap → 429."""
        import utils.credential_request_routes as routes
        from utils import redis_client
        from fastapi import HTTPException

        class _FakeRedis:
            def __init__(self):
                self.store = {}

            async def set(self, key, value, ex=None, nx=False):
                if nx and key in self.store:
                    return None
                self.store[key] = value
                return True

            async def incr(self, key):
                self.store[key] = int(self.store.get(key, 0)) + 1
                return self.store[key]

        monkeypatch.setattr(redis_client, "_client", _FakeRedis())
        monkeypatch.setattr(routes, "QR_START_MAX", 2)
        mock_start.return_value = {'success': True, 'connection_id': 'c', 'qr_code': 'q', 'message': ''}

        await routes.qr_start(setup_db['token'])
        await routes.qr_start(setup_db['token'])
        with pytest.raises(HTTPException) as exc:
            await routes.qr_start(setup_db['token'])
        assert exc.value.status_code == 429

    @patch('utils.whatsapp_qr.finalize_qr_connection', new_callable=AsyncMock)
    async def test_qr_status_pending_does_not_fulfill(self, mock_finalize, real_database, db, setup_db):
        """A still-scanning poll leaves the request pending."""
        from utils.credential_request_routes import qr_status, QRStatusBody

        mock_finalize.return_value = {'success': True, 'status': 'pending', 'message': 'Waiting…'}
        result = await qr_status(setup_db['token'], QRStatusBody(connection_id='conn-xyz'))
        assert result['status'] == 'pending'

        req = db.fetchrow("SELECT status FROM credential_requests WHERE id = $1", setup_db['request_id'])
        assert req['status'] == 'pending'


@pytest.mark.asyncio
class TestCredentialTypeOverride:
    """Tests for providing a credential with a sibling credential_type override."""

    @pytest.fixture
    def db(self, real_database):
        return _direct_db_helper(real_database.conn_params)

    @pytest.fixture
    def setup_db(self, db):
        db.execute("DELETE FROM resource_shares WHERE resource_type = 'credential'")
        db.execute("DELETE FROM credential_requests")
        db.execute("DELETE FROM credentials WHERE credential_type IN ('openai_api_key', 'slack_bot_token')")

        db.execute(
            "INSERT INTO auth.users (id, email, raw_user_meta_data) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            TEST_USER_ID, TEST_USER_EMAIL, {'name': 'Test Requester'},
        )

        row = db.fetchrow("""
            INSERT INTO credential_requests (requester_id, target_email, credential_type, message)
            VALUES ($1, $2, $3, $4)
            RETURNING id, token
        """, TEST_USER_ID, TARGET_EMAIL, 'openai_api_key', 'Need your key')

        yield {'request_id': str(row['id']), 'token': row['token']}

        db.execute("DELETE FROM resource_shares WHERE resource_type = 'credential'")
        db.execute("DELETE FROM credential_requests")
        db.execute("DELETE FROM credentials WHERE credential_type IN ('openai_api_key', 'slack_bot_token')")

    async def test_invalid_credential_type_override_rejected(self, real_database, setup_db):
        """Overriding with a non-sibling credential_type should be rejected."""
        from utils.credential_request_routes import provide_credential, ProvideCredentialBody
        from fastapi import HTTPException

        body = ProvideCredentialBody(
            credential_type='slack_bot_token',  # Not a sibling of openai_api_key
            credential_data={'bot_token': 'xoxb-fake'},
        )

        with pytest.raises(HTTPException) as exc_info:
            await provide_credential(setup_db['token'], body)
        assert exc_info.value.status_code == 400
        assert 'Invalid credential type override' in str(exc_info.value.detail)

    @patch('utils.credential_request_routes.send_credential_fulfilled_email', new_callable=AsyncMock, return_value=True)
    @patch('utils.credential_request_routes._get_sibling_methods')
    async def test_valid_credential_type_override_accepted(self, mock_siblings, mock_email, real_database, db, setup_db):
        """Overriding with a valid sibling credential_type should use the override."""
        from utils.credential_request_routes import provide_credential, ProvideCredentialBody

        # Mock siblings to include both types
        mock_siblings.return_value = [
            {'credential_type': 'openai_api_key'},
            {'credential_type': 'slack_bot_token'},
        ]

        body = ProvideCredentialBody(
            credential_type='slack_bot_token',
            credential_data={'bot_token': 'xoxb-override-test'},
        )

        result = await provide_credential(setup_db['token'], body)
        assert result['status'] == 'success'

        # The credential should be stored with the overridden type
        cred_row = db.fetchrow(
            "SELECT credential_type FROM credentials ORDER BY created_at DESC LIMIT 1"
        )
        assert cred_row['credential_type'] == 'slack_bot_token'
