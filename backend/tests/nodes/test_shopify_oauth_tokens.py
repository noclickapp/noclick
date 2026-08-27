"""Shopify expiring offline-token OAuth regression tests."""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx
import pytest

from nodes.oauth import shopify_oauth


def _client_factory(monkeypatch, handler):
    async_client_class = httpx.AsyncClient

    def factory(*_args, **_kwargs):
        return async_client_class(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(shopify_oauth.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_authorization_code_exchange_requests_expiring_offline_token(
    monkeypatch,
):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/admin/oauth/access_token":
            return httpx.Response(
                200,
                json={
                    "access_token": "shpat_access",
                    "scope": "read_products",
                    "expires_in": 3600,
                    "refresh_token": "shprt_refresh",
                    "refresh_token_expires_in": 7776000,
                },
            )
        return httpx.Response(
            200,
            json={
                "shop": {
                    "id": 42,
                    "name": "Review Store",
                    "email": "owner@example.com",
                    "shop_owner": "Owner",
                    "domain": "review-store.myshopify.com",
                }
            },
        )

    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "client-secret")
    _client_factory(monkeypatch, handler)

    tokens, shop = await shopify_oauth.exchange_code_for_tokens(
        code="authorization-code",
        shop="review-store",
        redirect_uri="https://www.noclick.com/api/auth/shopify/callback",
    )

    token_form = parse_qs(requests[0].content.decode())
    assert token_form["expiring"] == ["1"]
    assert tokens.refresh_token == "shprt_refresh"
    assert tokens.expires_at is not None
    assert tokens.refresh_expires_at is not None
    assert shop.name == "Review Store"


@pytest.mark.asyncio
async def test_refresh_rotates_shopify_offline_tokens(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(parse_qs(request.content.decode()))
        return httpx.Response(
            200,
            json={
                "access_token": "shpat_new",
                "expires_in": 3600,
                "refresh_token": "shprt_rotated",
                "refresh_token_expires_in": 7776000,
            },
        )

    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "client-secret")
    _client_factory(monkeypatch, handler)

    tokens = await shopify_oauth.refresh_access_token(
        "shprt_current", shop="review-store"
    )

    assert captured == {
        "grant_type": ["refresh_token"],
        "client_id": ["client-id"],
        "client_secret": ["client-secret"],
        "refresh_token": ["shprt_current"],
    }
    assert tokens.access_token == "shpat_new"
    assert tokens.refresh_token == "shprt_rotated"
    assert tokens.expires_at is not None


def test_shopify_expiry_uses_refresh_buffer():
    future = datetime.now(timezone.utc) + timedelta(minutes=20)
    soon = datetime.now(timezone.utc) + timedelta(minutes=2)

    assert shopify_oauth.is_token_expired(future.isoformat()) is False
    assert shopify_oauth.is_token_expired(soon.isoformat()) is True
    assert shopify_oauth.is_token_expired("not-a-timestamp") is True
    assert shopify_oauth.is_token_expired(None) is False
