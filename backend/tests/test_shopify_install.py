from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from starlette.requests import Request

from utils.shopify_install import (
    ShopifyInstallExchangeRequest,
    ensure_app_uninstalled_webhook,
    exchange_public_install,
)


_TEST_WEBHOOK_URI = "https://hooks.example.test/webhook/shopify/lifecycle"


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


def _request():
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/credential-request/shopify/install/exchange",
            "headers": [(b"authorization", b"Bearer verified-token")],
        }
    )


@pytest.mark.asyncio
async def test_public_install_upserts_canonical_shop_credential(monkeypatch):
    credential_id = uuid.uuid4()
    captured = {}

    class Conn:
        async def fetchrow(self, sql, *args):
            if "SELECT id" in sql:
                captured["lookup"] = args
                return {"id": credential_id}
            raise AssertionError(sql)

    async def exchange(**kwargs):
        captured["exchange"] = kwargs
        return (
            SimpleNamespace(
                access_token="shpat_secret",
                scope="read_orders",
                refresh_token="shprt_secret",
                expires_at="2026-08-27T20:00:00Z",
                refresh_expires_at="2026-11-25T19:00:00Z",
            ),
            SimpleNamespace(
                id=12,
                name="Acme",
                domain="acme.example",
                shop_owner="Owner",
                email="owner@example.com",
            ),
        )

    async def update_credential(**kwargs):
        captured["update"] = kwargs
        return 1, None

    monkeypatch.setenv(
        "SHOPIFY_REDIRECT_URI", "https://www.noclick.com/api/auth/shopify/callback"
    )
    monkeypatch.setattr(
        "utils.shopify_install.verify_token",
        AsyncMock(
            return_value={
                "sub": "11111111-1111-1111-1111-111111111111",
                "subscription_tier": "plus",
            }
        ),
    )
    monkeypatch.setattr("utils.shopify_install.exchange_code_for_tokens", exchange)
    lifecycle_webhook = AsyncMock(return_value="gid://shopify/WebhookSubscription/123")
    monkeypatch.setattr(
        "utils.shopify_install.ensure_app_uninstalled_webhook", lifecycle_webhook
    )
    monkeypatch.setattr(
        "utils.shopify_install.update_credential_data_detailed", update_credential
    )

    result = await exchange_public_install(
        _request(),
        ShopifyInstallExchangeRequest(
            code="code",
            shop="acme.myshopify.com",
            redirect_uri="https://www.noclick.com/api/auth/shopify/callback",
            scopes="read_orders,write_orders",
        ),
        pool=_Pool(Conn()),
    )

    assert result["shop"] == "acme.myshopify.com"
    assert result["credential_id"] == str(credential_id)
    assert captured["update"]["new_data"]["store_name"] == "acme"
    assert captured["update"]["new_data"]["refresh_token"] == "shprt_secret"
    assert captured["update"]["new_data"]["expires_at"] == "2026-08-27T20:00:00Z"
    assert captured["update"]["new_data"]["installation_source"] == "shopify_app_store"
    assert captured["lookup"][1] == "acme.myshopify.com"
    assert captured["update"]["credential_name"] == "Acme"
    metadata = captured["update"]["metadata_updates"]
    assert metadata["myshopify_domain"] == "acme.myshopify.com"
    assert metadata["installation_source"] == "shopify_app_store"
    assert metadata["scopes"] == ["read_orders"]
    lifecycle_webhook.assert_awaited_once_with("acme", "shpat_secret")


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _HttpClient:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(self.payloads.pop(0))


@pytest.mark.asyncio
async def test_uninstall_webhook_reuses_matching_subscription(monkeypatch):
    monkeypatch.setenv("SHOPIFY_UNINSTALL_WEBHOOK_URI", _TEST_WEBHOOK_URI)
    client = _HttpClient(
        {
            "data": {
                "webhookSubscriptions": {
                    "nodes": [
                        {
                            "id": "gid://shopify/WebhookSubscription/7",
                            "uri": _TEST_WEBHOOK_URI,
                        }
                    ]
                }
            }
        }
    )

    webhook_id = await ensure_app_uninstalled_webhook(
        "acme.myshopify.com", "token", client=client
    )

    assert webhook_id == "gid://shopify/WebhookSubscription/7"
    assert len(client.calls) == 1
    assert "APP_UNINSTALLED" in client.calls[0][1]["json"]["query"]


@pytest.mark.asyncio
async def test_uninstall_webhook_creates_missing_subscription(monkeypatch):
    monkeypatch.setenv("SHOPIFY_UNINSTALL_WEBHOOK_URI", _TEST_WEBHOOK_URI)
    client = _HttpClient(
        {"data": {"webhookSubscriptions": {"nodes": []}}},
        {
            "data": {
                "webhookSubscriptionCreate": {
                    "webhookSubscription": {
                        "id": "gid://shopify/WebhookSubscription/8"
                    },
                    "userErrors": [],
                }
            }
        },
    )

    webhook_id = await ensure_app_uninstalled_webhook("acme", "token", client=client)

    assert webhook_id == "gid://shopify/WebhookSubscription/8"
    assert len(client.calls) == 2
    variables = client.calls[1][1]["json"]["variables"]
    assert variables["subscription"]["format"] == "JSON"
    assert variables["subscription"]["uri"] == _TEST_WEBHOOK_URI
