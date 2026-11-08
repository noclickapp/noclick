"""Crowdin OAuth exchange and rotation contracts (no live OAuth grant)."""

import base64
import json
from urllib.parse import parse_qs

import httpx
import pytest

from nodes.core.oauth_refresh import RotatedRefreshTokenMissing
from nodes.oauth.crowdin_oauth import OAUTH_PROVIDER, refresh_access_token

_ORIGINAL_ASYNC_CLIENT = httpx.AsyncClient


def _jwt(domain: str) -> str:
    payload = (
        base64.urlsafe_b64encode(json.dumps({"organization_domain": domain}).encode())
        .decode()
        .rstrip("=")
    )
    return f"header.{payload}.signature"


def _transport(monkeypatch, callback):
    monkeypatch.setattr(
        "nodes.core.oauth_provider.httpx.AsyncClient",
        lambda *args, **kwargs: _ORIGINAL_ASYNC_CLIENT(
            transport=httpx.MockTransport(callback)
        ),
    )


@pytest.mark.asyncio
async def test_exchange_uses_pkce_and_identifies_user(monkeypatch):
    monkeypatch.setenv("CROWDIN_CLIENT_ID", "client-id")
    monkeypatch.setenv("CROWDIN_CLIENT_SECRET", "client-secret")
    seen = []

    def callback(request):
        seen.append(request)
        if request.url.path == "/oauth/token":
            return httpx.Response(
                200,
                json={
                    "access_token": _jwt("team"),
                    "refresh_token": "first-refresh",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": 42,
                    "username": "admin",
                    "email": "admin@noclick.com",
                }
            },
        )

    _transport(monkeypatch, callback)
    tokens, name = await OAUTH_PROVIDER.exchange(
        "code", "https://noclick.com/callback", "v" * 43
    )
    assert tokens.refresh_token == "first-refresh"
    assert tokens.expires_at
    assert name == "admin"
    assert {k: v[0] for k, v in parse_qs(seen[0].content.decode()).items()} == {
        "grant_type": "authorization_code",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "redirect_uri": "https://noclick.com/callback",
        "code": "code",
        "code_verifier": "v" * 43,
    }
    assert str(seen[1].url) == "https://api.crowdin.com/api/v2/user"


@pytest.mark.asyncio
async def test_refresh_requires_rotated_token(monkeypatch):
    monkeypatch.setenv("CROWDIN_CLIENT_ID", "client-id")
    monkeypatch.setenv("CROWDIN_CLIENT_SECRET", "client-secret")
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "opaque",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            },
        )

    _transport(monkeypatch, callback)
    tokens = await refresh_access_token("old-refresh")
    assert tokens.refresh_token == "new-refresh"
    assert parse_qs(seen[0].content.decode())["refresh_token"] == ["old-refresh"]

    def no_rotation(request):
        return httpx.Response(200, json={"access_token": "opaque"})

    _transport(monkeypatch, no_rotation)
    with pytest.raises(RotatedRefreshTokenMissing, match="refresh_token"):
        await refresh_access_token("old-refresh")
