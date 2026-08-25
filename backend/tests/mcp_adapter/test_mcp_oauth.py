"""
Basic tests for MCP OAuth authentication.

Tests token issuance/verification, OAuth storage, and endpoints.
"""

import pytest
import asyncio
import hashlib
import base64
import secrets
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import jwt


class TestMCPTokens:
    """Test MCP JWT token issuance and verification."""

    def test_issue_and_verify_token(self):
        """Test that issued tokens can be verified."""
        from mcp_adapter.auth.tokens import issue_mcp_token, verify_mcp_token

        # Issue a token
        token = issue_mcp_token(
            user_id="test-user-123",
            client_id="test-client-456",
            scopes=["mcp:tools"],
        )

        assert token is not None
        assert isinstance(token, str)
        assert token.count(".") == 2  # JWT format

        # Verify the token
        payload = verify_mcp_token(token)

        assert payload["sub"] == "test-user-123"
        assert payload["client_id"] == "test-client-456"
        assert payload["scope"] == "mcp:tools"
        assert payload["aud"] == "noclick-mcp"
        assert payload["iss"] == "noclick"

    def test_token_expiry(self):
        """Test that token expiry is set correctly."""
        from mcp_adapter.auth.tokens import issue_mcp_token, verify_mcp_token

        # Issue token with 1 hour expiry
        token = issue_mcp_token(
            user_id="test-user",
            client_id="test-client",
            scopes=["mcp:tools"],
            expiry_hours=1,
        )

        payload = verify_mcp_token(token)

        # Check expiry is roughly 1 hour from now
        exp = payload["exp"]
        iat = payload["iat"]
        assert exp - iat == 3600  # 1 hour in seconds

    def test_invalid_token_rejected(self):
        """Test that invalid tokens are rejected."""
        from mcp_adapter.auth.tokens import verify_mcp_token

        with pytest.raises(jwt.InvalidTokenError):
            verify_mcp_token("invalid.token.here")

    def test_wrong_audience_rejected(self):
        """Test that tokens with wrong audience are rejected."""
        from mcp_adapter.auth.tokens import verify_mcp_token, get_mcp_signing_key

        # Create token with wrong audience
        wrong_token = jwt.encode(
            {
                "sub": "user",
                "client_id": "client",
                "scope": "mcp:tools",
                "aud": "wrong-audience",
                "iss": "noclick",
                "exp": datetime.now(timezone.utc).timestamp() + 3600,
            },
            get_mcp_signing_key(),
            algorithm="HS256",
        )

        with pytest.raises(jwt.InvalidAudienceError):
            verify_mcp_token(wrong_token)

    def test_extract_bearer_token(self):
        """Test bearer token extraction from header."""
        from mcp_adapter.auth.tokens import extract_bearer_token

        # Valid bearer token
        assert extract_bearer_token("Bearer abc123") == "abc123"
        assert extract_bearer_token("bearer ABC") == "ABC"

        # Invalid formats
        assert extract_bearer_token(None) is None
        assert extract_bearer_token("") is None
        assert extract_bearer_token("Basic abc123") is None
        assert extract_bearer_token("Bearerabc123") is None


class TestPKCE:
    """Test PKCE verification."""

    def test_pkce_verification(self):
        """Test PKCE S256 verification."""
        from mcp_adapter.auth.endpoints import verify_pkce

        # Generate code_verifier
        code_verifier = secrets.token_urlsafe(32)

        # Compute code_challenge (S256)
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

        # Verify
        assert verify_pkce(code_verifier, code_challenge) is True

        # Wrong verifier should fail
        assert verify_pkce("wrong-verifier", code_challenge) is False


class TestOAuthModels:
    """Test OAuth Pydantic models."""

    def test_protected_resource_metadata(self):
        """Test protected resource metadata model."""
        from mcp_adapter.auth.models import ProtectedResourceMetadata

        metadata = ProtectedResourceMetadata(
            resource="https://api.example.com/mcp",
            authorization_servers=["https://api.example.com"],
        )

        assert metadata.resource == "https://api.example.com/mcp"
        assert "https://api.example.com" in metadata.authorization_servers
        assert "mcp:tools" in metadata.scopes_supported

    def test_client_registration_request(self):
        """Test client registration request model."""
        from mcp_adapter.auth.models import ClientRegistrationRequest

        request = ClientRegistrationRequest(
            client_name="Test Client",
            redirect_uris=["http://localhost:3000/callback"],
        )

        assert request.client_name == "Test Client"
        assert request.redirect_uris == ["http://localhost:3000/callback"]
        assert request.grant_types == ["authorization_code"]
        assert request.token_endpoint_auth_method == "none"

    def test_authorization_request_validation(self):
        """Test authorization request validation."""
        from mcp_adapter.auth.models import AuthorizationRequest
        from pydantic import ValidationError

        # Valid request
        request = AuthorizationRequest(
            client_id="client123",
            redirect_uri="http://localhost:3000/callback",
            state="abc123",
            code_challenge="challenge",
        )
        assert request.response_type == "code"
        assert request.code_challenge_method == "S256"

        # Invalid response_type
        with pytest.raises(ValidationError):
            AuthorizationRequest(
                client_id="client123",
                redirect_uri="http://localhost:3000/callback",
                state="abc123",
                code_challenge="challenge",
                response_type="token",  # Invalid
            )


class TestOAuthStorage:
    """Test OAuth Redis storage."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        mock = AsyncMock()
        mock.setex = AsyncMock(return_value=True)
        mock.get = AsyncMock(return_value=None)
        mock.delete = AsyncMock(return_value=1)
        mock.pipeline = MagicMock()
        return mock

    @pytest.mark.asyncio
    async def test_store_client(self, mock_redis):
        """Test storing a client registration."""
        from mcp_adapter.auth.storage import MCPOAuthStorage
        from mcp_adapter.auth.models import StoredClient

        storage = MCPOAuthStorage(redis_client=mock_redis)

        client = StoredClient(
            client_id="test-client",
            client_name="Test Client",
            redirect_uris=["http://localhost:3000/callback"],
            grant_types=["authorization_code"],
            token_endpoint_auth_method="none",
            created_at=datetime.now(timezone.utc),
        )

        result = await storage.store_client(client)

        assert result is True
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_client(self, mock_redis):
        """Test retrieving a client registration."""
        from mcp_adapter.auth.storage import MCPOAuthStorage
        from mcp_adapter.auth.models import StoredClient

        # Setup mock to return client data
        client = StoredClient(
            client_id="test-client",
            client_name="Test Client",
            redirect_uris=["http://localhost:3000/callback"],
            grant_types=["authorization_code"],
            token_endpoint_auth_method="none",
            created_at=datetime.now(timezone.utc),
        )
        mock_redis.get = AsyncMock(return_value=client.model_dump_json().encode())

        storage = MCPOAuthStorage(redis_client=mock_redis)
        result = await storage.get_client("test-client")

        assert result is not None
        assert result.client_id == "test-client"
        assert result.client_name == "Test Client"

    @pytest.mark.asyncio
    async def test_store_and_consume_auth_code(self, mock_redis):
        """Test authorization code storage and consumption."""
        from mcp_adapter.auth.storage import MCPOAuthStorage
        from mcp_adapter.auth.models import StoredAuthorizationCode
        from datetime import timedelta

        # Setup mock pipeline for atomic get-and-delete
        now = datetime.now(timezone.utc)
        auth_code = StoredAuthorizationCode(
            code="test-code",
            client_id="client",
            user_id="user",
            redirect_uri="http://localhost/callback",
            scope="mcp:tools",
            code_challenge="challenge",
            created_at=now,
            expires_at=now + timedelta(minutes=10),
        )

        pipe_mock = AsyncMock()
        pipe_mock.get = MagicMock()
        pipe_mock.delete = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[auth_code.model_dump_json().encode(), 1])
        pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
        pipe_mock.__aexit__ = AsyncMock(return_value=None)
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)

        storage = MCPOAuthStorage(redis_client=mock_redis)
        result = await storage.consume_authorization_code("test-code")

        assert result is not None
        assert result.code == "test-code"
        assert result.user_id == "user"


class TestOAuthEndpoints:
    """Test OAuth HTTP endpoints."""

    @pytest.fixture
    def test_client(self):
        """Create FastAPI test client with OAuth routes."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from mcp_adapter.auth.endpoints import create_mcp_oauth_router

        app = FastAPI()
        router = create_mcp_oauth_router()
        app.include_router(router)

        return TestClient(app)

    def test_protected_resource_metadata_endpoint(self, test_client):
        """Test /.well-known/oauth-protected-resource endpoint."""
        response = test_client.get("/.well-known/oauth-protected-resource")

        assert response.status_code == 200
        data = response.json()
        assert "resource" in data
        assert "authorization_servers" in data
        assert "scopes_supported" in data
        assert "mcp:tools" in data["scopes_supported"]

    def test_authorization_server_metadata_endpoint(self, test_client):
        """Test /.well-known/oauth-authorization-server endpoint."""
        response = test_client.get("/.well-known/oauth-authorization-server")

        assert response.status_code == 200
        data = response.json()
        assert "issuer" in data
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "registration_endpoint" in data
        assert "code_challenge_methods_supported" in data
        assert "S256" in data["code_challenge_methods_supported"]

    def test_client_registration_endpoint(self):
        """Test /mcp/register endpoint."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from mcp_adapter.auth.endpoints import create_mcp_oauth_router

        # Create mock storage that returns success
        mock_storage = AsyncMock()
        mock_storage.store_client = AsyncMock(return_value=True)
        mock_storage.find_client_by_redirect_uris = AsyncMock(return_value=None)
        mock_storage.deterministic_client_id = MagicMock(return_value="test-client-id")

        # Create app with mock storage passed to router
        app = FastAPI()
        router = create_mcp_oauth_router(storage=mock_storage)
        app.include_router(router)
        test_client = TestClient(app)

        response = test_client.post(
            "/mcp/register",
            json={
                "client_name": "Test Client",
                "redirect_uris": ["http://localhost:3000/callback"],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "client_id" in data
        assert data["client_name"] == "Test Client"
        assert data["redirect_uris"] == ["http://localhost:3000/callback"]
        assert "client_id_issued_at" in data

    def test_token_endpoint_missing_params(self, test_client):
        """Test /mcp/token endpoint with missing parameters."""
        response = test_client.post(
            "/mcp/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "test-client",
                # Missing code, redirect_uri, code_verifier
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "invalid_request"

    def test_token_endpoint_invalid_grant_type(self, test_client):
        """Test /mcp/token endpoint with invalid grant_type."""
        response = test_client.post(
            "/mcp/token",
            data={
                "grant_type": "password",  # Invalid
                "client_id": "test-client",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "unsupported_grant_type"


class TestRedirectUriValidation:
    """redirect_uri validation: exact match OR same https origin.

    ChatGPT reuses the client_id from its original DCR but rotates its
    callback path per connector/app version — the 2026-08-22 plugin
    submission presented /connector/oauth/{id} against a client registered
    with /connector_platform_oauth_redirect and bricked on exact match.
    """

    CHATGPT_URIS = [
        "https://chatgpt.com/connector_platform_oauth_redirect",
        "https://platform.openai.com/apps-manage/oauth",
    ]

    def _client(self, uris):
        from mcp_adapter.auth.models import StoredClient

        return StoredClient(
            client_id="eWOVhYeAoF6OKqMYSUUuUw",
            client_name="ChatGPT",
            redirect_uris=uris,
            grant_types=["authorization_code", "refresh_token"],
            token_endpoint_auth_method="none",
            created_at=datetime.now(timezone.utc),
        )

    def test_exact_match_allowed(self):
        from mcp_adapter.auth.endpoints import redirect_uri_allowed

        client = self._client(self.CHATGPT_URIS)
        assert redirect_uri_allowed(client, self.CHATGPT_URIS[0])

    def test_same_origin_new_path_allowed(self):
        from mcp_adapter.auth.endpoints import redirect_uri_allowed

        client = self._client(self.CHATGPT_URIS)
        assert redirect_uri_allowed(
            client, "https://chatgpt.com/connector/oauth/IVdRGfaTmNHA"
        )

    def test_different_host_rejected(self):
        from mcp_adapter.auth.endpoints import redirect_uri_allowed

        client = self._client(self.CHATGPT_URIS)
        assert not redirect_uri_allowed(client, "https://evil.com/callback")
        # Subdomain and suffix look-alikes are different origins
        assert not redirect_uri_allowed(client, "https://evil.chatgpt.com/cb")
        assert not redirect_uri_allowed(client, "https://chatgpt.com.evil.com/cb")

    def test_http_downgrade_rejected(self):
        from mcp_adapter.auth.endpoints import redirect_uri_allowed

        client = self._client(self.CHATGPT_URIS)
        assert not redirect_uri_allowed(client, "http://chatgpt.com/connector/oauth/x")

    def test_port_variant_rejected(self):
        from mcp_adapter.auth.endpoints import redirect_uri_allowed

        client = self._client(self.CHATGPT_URIS)
        assert not redirect_uri_allowed(client, "https://chatgpt.com:8443/cb")

    def test_localhost_client_stays_exact_match(self):
        from mcp_adapter.auth.endpoints import redirect_uri_allowed

        client = self._client(["http://localhost:3000/callback"])
        assert redirect_uri_allowed(client, "http://localhost:3000/callback")
        # http origins get no relaxation — only the registered URI verbatim
        assert not redirect_uri_allowed(client, "http://localhost:3000/other")

    def test_authorize_endpoint_accepts_rotated_chatgpt_path(self):
        """End-to-end: the exact failing request now reaches consent (302)."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from mcp_adapter.auth.endpoints import create_mcp_oauth_router

        mock_storage = AsyncMock()
        mock_storage.get_client = AsyncMock(return_value=self._client(self.CHATGPT_URIS))

        app = FastAPI()
        app.include_router(create_mcp_oauth_router(storage=mock_storage))
        test_client = TestClient(app)

        response = test_client.get(
            "/mcp/authorize",
            params={
                "response_type": "code",
                "client_id": "eWOVhYeAoF6OKqMYSUUuUw",
                "redirect_uri": "https://chatgpt.com/connector/oauth/IVdRGfaTmNHA",
                "scope": "mcp:tools",
                "code_challenge": "4sPHfjgQprJPzQ2GSwVctBaffjHz6ZpslppzXAIOCM8",
                "code_challenge_method": "S256",
                "state": "test-state",
            },
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert "/mcp/consent" in response.headers["location"]

    def test_authorize_endpoint_still_rejects_foreign_redirect(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from mcp_adapter.auth.endpoints import create_mcp_oauth_router

        mock_storage = AsyncMock()
        mock_storage.get_client = AsyncMock(return_value=self._client(self.CHATGPT_URIS))

        app = FastAPI()
        app.include_router(create_mcp_oauth_router(storage=mock_storage))
        test_client = TestClient(app)

        response = test_client.get(
            "/mcp/authorize",
            params={
                "response_type": "code",
                "client_id": "eWOVhYeAoF6OKqMYSUUuUw",
                "redirect_uri": "https://attacker.example/cb",
                "scope": "mcp:tools",
                "code_challenge": "4sPHfjgQprJPzQ2GSwVctBaffjHz6ZpslppzXAIOCM8",
                "code_challenge_method": "S256",
                "state": "test-state",
            },
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert "Invalid redirect_uri" in response.text

    def _endpoint_client(self, stored_client):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from mcp_adapter.auth.endpoints import create_mcp_oauth_router

        mock_storage = AsyncMock()
        mock_storage.get_client = AsyncMock(return_value=stored_client)
        app = FastAPI()
        app.include_router(create_mcp_oauth_router(storage=mock_storage))
        return TestClient(app)

    def _authorize_params(self, redirect_uri, **overrides):
        params = {
            "response_type": "code",
            "client_id": "eWOVhYeAoF6OKqMYSUUuUw",
            "redirect_uri": redirect_uri,
            "scope": "mcp:tools",
            "code_challenge": "4sPHfjgQprJPzQ2GSwVctBaffjHz6ZpslppzXAIOCM8",
            "code_challenge_method": "S256",
            "state": "opaque&next=https://attacker.example",
        }
        params.update(overrides)
        return params

    def test_unknown_client_never_redirects_to_presented_uri(self):
        client = self._endpoint_client(None)
        response = client.get(
            "/mcp/authorize",
            params=self._authorize_params("https://attacker.example/callback"),
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert "location" not in response.headers

    def test_invalid_protocol_error_redirect_requires_allowed_uri(self):
        stored = self._client(self.CHATGPT_URIS)
        client = self._endpoint_client(stored)
        response = client.get(
            "/mcp/authorize",
            params=self._authorize_params(
                "https://attacker.example/callback", response_type="token"
            ),
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert "location" not in response.headers

    def test_allowed_error_redirect_encodes_state_as_one_parameter(self):
        from urllib.parse import parse_qs, urlsplit

        redirect_uri = self.CHATGPT_URIS[0] + "?existing=1"
        stored = self._client([redirect_uri])
        client = self._endpoint_client(stored)
        response = client.get(
            "/mcp/authorize",
            params=self._authorize_params(redirect_uri, response_type="token"),
            follow_redirects=False,
        )

        assert response.status_code in (302, 307)
        location = urlsplit(response.headers["location"])
        assert location.hostname == "chatgpt.com"
        assert parse_qs(location.query) == {
            "existing": ["1"],
            "error": ["unsupported_response_type"],
            "state": ["opaque&next=https://attacker.example"],
        }

    def test_denied_consent_rejects_foreign_redirect_before_returning_url(self):
        stored = self._client(self.CHATGPT_URIS)
        client = self._endpoint_client(stored)
        response = client.post(
            "/mcp/authorize/consent",
            data={
                "client_id": stored.client_id,
                "redirect_uri": "https://attacker.example/callback",
                "state": "state",
                "code_challenge": "challenge",
                "scope": "mcp:tools",
                "action": "deny",
                "access_token": "unused",
            },
        )

        assert response.status_code == 400
        assert "redirect_url" not in response.json()
