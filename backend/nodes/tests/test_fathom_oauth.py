from unittest.mock import AsyncMock

import pytest
from datetime import datetime, timedelta, timezone

from nodes.oauth.fathom_oauth import (
    exchange_code_for_tokens,
    is_token_expired,
    refresh_access_token,
)


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class _Client:
    def __init__(self, response):
        self.post = AsyncMock(return_value=response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_exchange_code_for_tokens_uses_expected_form_fields(monkeypatch):
    client = _Client(
        _Response(
            {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
                "scope": "public_api",
                "token_type": "Bearer",
            }
        )
    )
    monkeypatch.setenv("FATHOM_CLIENT_ID", "client-id")
    monkeypatch.setenv("FATHOM_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(
        "nodes.oauth.fathom_oauth.httpx.AsyncClient",
        lambda *args, **kwargs: client,
    )

    tokens, _ = await exchange_code_for_tokens(
        code="auth-code", redirect_uri="https://example.com/fathom/callback"
    )

    assert tokens.access_token == "new-access"
    assert tokens.refresh_token == "new-refresh"
    client.post.assert_awaited_once()
    assert client.post.await_args.args[0] == "https://fathom.video/external/v1/oauth2/token"
    assert client.post.await_args.kwargs["data"] == {
        "grant_type": "authorization_code",
        "code": "auth-code",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "redirect_uri": "https://example.com/fathom/callback",
    }


@pytest.mark.asyncio
async def test_refresh_access_token_preserves_rotated_refresh_token(monkeypatch):
    client = _Client(
        _Response(
            {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
                "scope": "public_api",
                "token_type": "Bearer",
            }
        )
    )
    monkeypatch.setenv("FATHOM_CLIENT_ID", "client-id")
    monkeypatch.setenv("FATHOM_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(
        "nodes.oauth.fathom_oauth.httpx.AsyncClient",
        lambda *args, **kwargs: client,
    )

    tokens = await refresh_access_token("old-refresh")

    assert tokens.access_token == "new-access"
    assert tokens.refresh_token == "new-refresh"
    client.post.assert_awaited_once()
    assert client.post.await_args.kwargs["data"]["refresh_token"] == "old-refresh"


def test_is_token_expired_supports_expired_vs_expires_soon():
    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    soon = (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    assert is_token_expired(future, buffer_minutes=0) is False
    assert is_token_expired(future, buffer_minutes=5) is False
    assert is_token_expired(soon, buffer_minutes=0) is False
    assert is_token_expired(soon, buffer_minutes=5) is True
    assert is_token_expired(past, buffer_minutes=0) is True
