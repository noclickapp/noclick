"""Public Shopify App Store grants must never call the legacy REST Admin API."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from coder.workflow.operation_catalog import get_operations_for_node_type
from nodes.core.base import iter_operation_definitions
from nodes.shopify_node import (
    OWN_APP_TIER,
    PUBLIC_APP_GRAPHQL_OPERATIONS,
    ShopifyCreateBlogArticleConfig,
    ShopifyGraphQLShopQueryConfig,
    ShopifyListProductsConfig,
    ShopifyNode,
    ShopifyNodeConfig,
    ShopifyOAuthCredential,
)

GENERATED_SCHEMA = (
    Path(__file__).resolve().parents[3] / "frontend/app/schemas/nodes/shopify.json"
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
async def test_public_app_allows_graphql_blog_operation():
    node = _node(
        ShopifyCreateBlogArticleConfig(
            blog_id="123",
            title="GraphQL migration",
            body_html="<p>Published through GraphQL.</p>",
        )
    )
    node._handle_create_blog_article = AsyncMock(
        return_value={"status": "success", "action": "create_blog_article"}
    )

    result = await node.execute({})

    assert result["status"] == "success"
    node._handle_create_blog_article.assert_awaited_once()


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


def _tier_split(schema):
    tiered, untiered = set(), set()
    for operation, definition in iter_operation_definitions(schema):
        (tiered if definition.get("x-requires-tier") else untiered).add(operation)
        if definition.get("x-requires-tier"):
            assert definition["x-requires-tier"] == OWN_APP_TIER
            assert definition.get("x-tier-label"), (
                f"{operation}: x-requires-tier without an x-tier-label renders "
                "no marker in the picker"
            )
        assert "x-requires-tier" not in definition["properties"]["operation"], (
            f"{operation}: the marker belongs on the config class, not the "
            "nested operation property the picker never reads"
        )
    return tiered, untiered


class _ReachedProvider(Exception):
    """Raised instead of any network call: the operation got past the gate."""


async def _refused_on_public_app(config_class) -> bool:
    """Run ``execute`` the way an App Store grant does and report whether the
    GraphQL-only gate refused it. Network helpers raise before any I/O, and a
    handler tripping over the unvalidated config also means the gate let it
    through."""
    node = _node(config_class.model_construct())
    node._make_request = AsyncMock(side_effect=_ReachedProvider)
    node._make_graphql_request = AsyncMock(side_effect=_ReachedProvider)
    try:
        await node.execute({})
    except ValueError as e:
        if "GraphQL Admin API operations only" in str(e):
            return True
    except Exception:
        pass
    return False


@pytest.fixture(scope="module")
def refused_operations():
    import asyncio

    operations = get_operations_for_node_type("automation-shopify")
    assert len(operations) > 50, "precondition: enumerated the Shopify union"

    async def judge():
        return {
            op.name
            for op in operations
            if await _refused_on_public_app(op.config_class)
        }

    return asyncio.run(judge())


@pytest.mark.parametrize(
    "schema",
    [
        pytest.param(ShopifyNode.get_config_schema, id="live"),
        pytest.param(lambda: json.loads(GENERATED_SCHEMA.read_text()), id="generated"),
    ],
)
def test_marker_matches_what_the_public_app_refuses(schema, refused_operations):
    """Exactly the operations ``execute`` refuses on an App Store grant carry
    ``x-requires-tier`` (which the picker, tool presets and templates read), in
    the live schema and in the generated file the frontend ships."""
    tiered, untiered = _tier_split(schema())

    assert tiered == refused_operations
    assert PUBLIC_APP_GRAPHQL_OPERATIONS <= untiered
    assert set(ShopifyNode._trigger_event_map) <= untiered
    assert "list_products" in tiered and "query_products_with_graphql" in untiered
