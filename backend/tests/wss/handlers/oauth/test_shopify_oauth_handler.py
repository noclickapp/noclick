from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from wss.handlers.oauth.shopify_oauth_handler import ShopifyOAuthHandler


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


@pytest.mark.asyncio
async def test_exchange_oauth_code_stores_store_name_and_credential_type(monkeypatch):
    sio = AsyncMock()
    sio.get_session = AsyncMock(return_value={
        "user_id": "user-1",
        "user_data": {"subscription_tier": "free"},
    })

    handler = ShopifyOAuthHandler(sio)

    captured_events = []
    captured_credential_payload = {}

    class _FakeEncryption:
        def encrypt_credential(self, data):
            captured_credential_payload.update(data)
            return "encrypted-credential"

    handler.encryption = _FakeEncryption()
    handler.get_pool = AsyncMock(return_value=_FakePool(conn=object()))

    async def _fake_send_event(_sio, _sid, response_event):
        captured_events.append(response_event)

    async def _fake_exchange_code_for_tokens(**_kwargs):
        tokens = SimpleNamespace(
            access_token="tok-123",
            scope="read_products",
            refresh_token="refresh-123",
            expires_at="2026-08-27T20:00:00Z",
            refresh_expires_at="2026-11-25T19:00:00Z",
        )
        shop_info = SimpleNamespace(
            id=123,
            name="My Store",
            domain="my-store.myshopify.com",
            shop_owner="Owner",
            email="owner@example.com",
        )
        return tokens, shop_info

    async def _fake_create_credential_with_limit_check(*_args, **_kwargs):
        return (
            {"id": "cred-1", "name": "My Store", "metadata": {}, "credential_type": "shopify_oauth"},
            None,
        )

    monkeypatch.setattr(
        "wss.handlers.oauth.shopify_oauth_handler.send_event",
        _fake_send_event,
    )
    monkeypatch.setattr(
        "wss.handlers.oauth.shopify_oauth_handler.exchange_code_for_tokens",
        _fake_exchange_code_for_tokens,
    )
    monkeypatch.setattr(
        "repositories.credentials.create_credential_with_limit_check",
        _fake_create_credential_with_limit_check,
    )
    monkeypatch.setenv("SHOPIFY_REDIRECT_URI", "https://example.com/api/auth/shopify/callback")

    request = SimpleNamespace(
        request_id="req-1",
        code="code-123",
        shop="my-store",
        redirect_uri="https://example.com/api/auth/shopify/callback",
        custom_client_id=None,
        custom_client_secret=None,
        scopes="read_products",
    )

    await handler.exchange_oauth_code("sid-1", request)

    assert captured_credential_payload["credential_type"] == "shopify_oauth"
    assert captured_credential_payload["store_name"] == "my-store"
    assert captured_credential_payload["refresh_token"] == "refresh-123"
    assert captured_credential_payload["expires_at"] == "2026-08-27T20:00:00Z"
    assert "shop_name" not in captured_credential_payload
    assert "shop_domain" not in captured_credential_payload

    assert captured_events, "Expected response event to be sent"
    data = captured_events[-1].data
    assert data["success"] is True


@pytest.mark.asyncio
async def test_exchange_oauth_code_rejects_redirect_uri_mismatch(monkeypatch):
    sio = AsyncMock()
    sio.get_session = AsyncMock(return_value={
        "user_id": "user-1",
        "user_data": {"subscription_tier": "free"},
    })

    handler = ShopifyOAuthHandler(sio)
    captured_events = []

    async def _fake_send_event(_sio, _sid, response_event):
        captured_events.append(response_event)

    monkeypatch.setattr(
        "wss.handlers.oauth.shopify_oauth_handler.send_event",
        _fake_send_event,
    )
    monkeypatch.setenv("SHOPIFY_REDIRECT_URI", "https://example.com/api/auth/shopify/callback")

    request = SimpleNamespace(
        request_id="req-2",
        code="code-123",
        shop="my-store",
        redirect_uri="https://evil.example/callback",
        custom_client_id=None,
        custom_client_secret=None,
        scopes="read_products",
    )

    await handler.exchange_oauth_code("sid-1", request)

    assert captured_events, "Expected failure event to be sent"
    data = captured_events[-1].data
    assert data["success"] is False
    assert data["message"] == "Invalid redirect URI"
