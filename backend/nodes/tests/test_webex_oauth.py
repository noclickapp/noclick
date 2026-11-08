"""Webex OAuth exchange, identity, and refresh contracts."""

import httpx
import pytest

from nodes.oauth.webex_oauth import OAUTH_PROVIDER, refresh_access_token


def _transport(monkeypatch, callback):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.core.oauth_provider.httpx.AsyncClient",
        lambda *args, **kwargs: original(transport=httpx.MockTransport(callback)),
    )


@pytest.mark.asyncio
async def test_exchange_reads_webex_identity(monkeypatch):
    monkeypatch.setenv("WEBEX_CLIENT_ID", "client-id")
    monkeypatch.setenv("WEBEX_CLIENT_SECRET", "client-secret")
    seen = []

    def callback(request):
        seen.append(request)
        if request.url.path == "/v1/access_token":
            return httpx.Response(200, json={
                "access_token": "access", "refresh_token": "refresh", "expires_in": 3600,
            })
        return httpx.Response(200, json={
            "id": "person-1", "displayName": "Alex", "emails": ["alex@example.com"],
        })

    _transport(monkeypatch, callback)
    tokens, name = await OAUTH_PROVIDER.exchange("code", "https://www.noclick.com/api/auth/webex/callback")
    assert tokens.expires_at
    assert name == "Alex"
    assert seen[0].url.host == "webexapis.com"
    assert b"grant_type=authorization_code" in seen[0].content
    assert b"client_secret=client-secret" in seen[0].content
    assert seen[1].headers["Authorization"] == "Bearer access"


@pytest.mark.asyncio
async def test_refresh_accepts_rotating_refresh_token(monkeypatch):
    monkeypatch.setenv("WEBEX_CLIENT_ID", "client-id")
    monkeypatch.setenv("WEBEX_CLIENT_SECRET", "client-secret")

    def callback(request):
        assert b"grant_type=refresh_token" in request.content
        assert b"refresh_token=old-refresh" in request.content
        return httpx.Response(200, json={
            "access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 600,
        })

    _transport(monkeypatch, callback)
    tokens = await refresh_access_token("old-refresh")
    assert tokens.access_token == "new-access"
    assert tokens.refresh_token == "new-refresh"


@pytest.mark.asyncio
async def test_exchange_rejects_missing_identity(monkeypatch):
    monkeypatch.setenv("WEBEX_CLIENT_ID", "client-id")
    monkeypatch.setenv("WEBEX_CLIENT_SECRET", "client-secret")

    def callback(request):
        if request.url.path == "/v1/access_token":
            return httpx.Response(200, json={
                "access_token": "access", "refresh_token": "refresh", "expires_in": 3600,
            })
        return httpx.Response(200, json={"id": "person-1", "displayName": ""})

    _transport(monkeypatch, callback)
    with pytest.raises(ValueError, match="returned no account name"):
        await OAUTH_PROVIDER.exchange("code", "https://www.noclick.com/api/auth/webex/callback")
