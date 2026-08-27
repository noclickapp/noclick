"""Public Shopify App Store grants must never call the legacy REST Admin API."""

from unittest.mock import AsyncMock

import pytest

from nodes.shopify_node import (
    ShopifyGraphQLShopQueryConfig,
    ShopifyListProductsConfig,
    ShopifyNode,
    ShopifyNodeConfig,
    ShopifyOAuthCredential,
)


def _node(config):
    return ShopifyNode(
        node_id="shopify-public-test",
        node_type="automation-shopify",
        node_data={},
        config=ShopifyNodeConfig(
            config=config,
            credentials=ShopifyOAuthCredential(
                store_name="review-store",
                access_token="test-token",
                installation_source="shopify_app_store",
            ),
        ),
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


@pytest.mark.asyncio
async def test_public_app_rejects_legacy_rest_operation():
    node = _node(ShopifyListProductsConfig(limit=5))

    with pytest.raises(ValueError, match="GraphQL Admin API operations only"):
        await node.execute({})


@pytest.mark.asyncio
async def test_public_app_allows_graphql_operation():
    node = _node(ShopifyGraphQLShopQueryConfig())
    node._handle_graphql_shop = AsyncMock(
        return_value={"status": "success", "action": "get_shop_with_graphql"}
    )

    result = await node.execute({})

    assert result["status"] == "success"
    node._handle_graphql_shop.assert_awaited_once()


@pytest.mark.asyncio
async def test_public_app_registers_webhooks_through_graphql(monkeypatch):
    register_graphql = AsyncMock(return_value="gid://shopify/WebhookSubscription/1")
    register_rest = AsyncMock()
    unregister_graphql = AsyncMock()
    unregister_rest = AsyncMock()
    monkeypatch.setattr(
        "nodes.shopify_node.register_shopify_webhook_graphql", register_graphql
    )
    monkeypatch.setattr("nodes.shopify_node.register_shopify_webhook", register_rest)
    monkeypatch.setattr(
        "nodes.shopify_node.unregister_shopify_webhook_graphql",
        unregister_graphql,
    )
    monkeypatch.setattr(
        "nodes.shopify_node.unregister_shopify_webhook", unregister_rest
    )
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "public-secret")

    result = await ShopifyNode._register_external_webhook(
        webhook_url="https://hooks.hooks.example.test/shopify",
        credential={
            "credential_type": "shopify_oauth",
            "store_name": "review-store",
            "access_token": "test-token",
        },
        config={
            "operation": "on_order_created",
            "external_webhook_id": "gid://shopify/WebhookSubscription/old",
        },
        node_id="shopify-trigger",
    )

    assert result["external_webhook_id"].startswith("gid://shopify/")
    register_graphql.assert_awaited_once()
    register_rest.assert_not_awaited()
    unregister_graphql.assert_awaited_once()
    unregister_rest.assert_not_awaited()
