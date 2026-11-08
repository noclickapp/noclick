"""Mural's authorization code and 15-minute token refresh contracts."""

from urllib.parse import parse_qs

import httpx
import pytest
from nodes.core import oauth_provider

from nodes.oauth import mural_oauth

REAL_CLIENT = httpx.AsyncClient


@pytest.mark.asyncio
async def test_exchange_posts_form_and_reads_profile(monkeypatch):
    monkeypatch.setenv("MURAL_CLIENT_ID", "app-id")
    monkeypatch.setenv("MURAL_CLIENT_SECRET", "app-secret")
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/token"):
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["authorization_code"]
            assert form["redirect_uri"] == ["https://noclick.com/api/auth/mural/callback"]
            assert form["client_secret"] == ["app-secret"]
            assert form["code_verifier"] == ["a" * 43]
            return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh", "expires_in": 900})
        assert request.url.path.endswith("/users/me")
        assert request.headers["authorization"] == "Bearer access"
        return httpx.Response(200, json={"value": {"id": "u-1", "firstName": "John", "lastName": "Smith", "email": "user@example.com"}})

    monkeypatch.setattr(oauth_provider.httpx, "AsyncClient",
                        lambda **kwargs: REAL_CLIENT(transport=httpx.MockTransport(handle)))
    tokens, user = await mural_oauth.OAUTH_PROVIDER.exchange(
        "code", "https://noclick.com/api/auth/mural/callback", "a" * 43)
    assert len(calls) == 2
    assert tokens.refresh_token == "refresh"
    assert tokens.expires_at is not None
    assert user == "John"


@pytest.mark.asyncio
async def test_refresh_reuses_existing_refresh_token_when_provider_omits_it(monkeypatch):
    monkeypatch.setenv("MURAL_CLIENT_ID", "app-id")
    monkeypatch.setenv("MURAL_CLIENT_SECRET", "app-secret")

    def handle(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["refresh_token"]
        assert form["refresh_token"] == ["existing"]
        return httpx.Response(200, json={"access_token": "new", "expires_in": 900})

    monkeypatch.setattr(oauth_provider.httpx, "AsyncClient",
                        lambda **kwargs: REAL_CLIENT(transport=httpx.MockTransport(handle)))
    token = await mural_oauth.refresh_access_token("existing")
    assert token.access_token == "new"
    assert token.refresh_token is None  # The shared refresh path preserves the reusable token.
