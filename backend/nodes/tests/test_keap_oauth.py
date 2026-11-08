"""Keap OAuth exchange and rotating refresh contracts; no live grant."""

import base64
from urllib.parse import parse_qs

import httpx
import pytest

from nodes.core.oauth_refresh import RotatedRefreshTokenMissing
from nodes.oauth.keap_oauth import OAUTH_PROVIDER, refresh_access_token


_ORIGINAL_CLIENT = httpx.AsyncClient


def _transport(monkeypatch, callback):
    monkeypatch.setattr(
        "nodes.core.oauth_provider.httpx.AsyncClient",
        lambda *args, **kwargs: _ORIGINAL_CLIENT(
            transport=httpx.MockTransport(callback)
        ),
    )


@pytest.mark.asyncio
async def test_exchange_uses_basic_auth_and_identifies_user(monkeypatch):
    monkeypatch.setenv("KEAP_CLIENT_ID", "client-id")
    monkeypatch.setenv("KEAP_CLIENT_SECRET", "client-secret")
    seen = []

    def callback(request):
        seen.append(request)
        if request.url.path == "/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access",
                    "refresh_token": "first-refresh",
                    "expires_in": 3600,
                },
            )
        return httpx.Response(200, json={"id": "u1", "email": "admin@noclick.com"})

    _transport(monkeypatch, callback)
    tokens, account_name = await OAUTH_PROVIDER.exchange(
        "code", "https://noclick.com/callback"
    )
    assert tokens.refresh_token == "first-refresh"
    assert tokens.expires_at
    assert account_name == "admin@noclick.com"
    assert parse_qs(seen[0].content.decode()) == {
        "grant_type": ["authorization_code"],
        "redirect_uri": ["https://noclick.com/callback"],
        "code": ["code"],
    }
    assert (
        seen[0].headers["content-type"].startswith("application/x-www-form-urlencoded")
    )
    assert seen[1].headers["Authorization"] == "Bearer access"
    assert seen[1].url.host == "api.keap.com"


@pytest.mark.asyncio
async def test_refresh_requires_rotation_and_basic_auth(monkeypatch):
    monkeypatch.setenv("KEAP_CLIENT_ID", "client-id")
    monkeypatch.setenv("KEAP_CLIENT_SECRET", "client-secret")
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            },
        )

    _transport(monkeypatch, callback)
    tokens = await refresh_access_token("old-refresh")
    assert tokens.refresh_token == "new-refresh"
    assert parse_qs(seen[0].content.decode()) == {
        "grant_type": ["refresh_token"],
        "refresh_token": ["old-refresh"],
    }
    expected = "Basic " + base64.b64encode(b"client-id:client-secret").decode()
    assert seen[0].headers["Authorization"] == expected

    _transport(
        monkeypatch, lambda request: httpx.Response(200, json={"access_token": "new"})
    )
    with pytest.raises(RotatedRefreshTokenMissing, match="refresh_token"):
        await refresh_access_token("old-refresh")
