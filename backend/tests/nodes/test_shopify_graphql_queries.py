"""Regression tests for Shopify's pre-built GraphQL query handlers."""

from unittest.mock import AsyncMock

import pytest

from nodes.shopify_node import (
    ShopifyGraphQLCollectionsQueryConfig,
    ShopifyGraphQLCustomersQueryConfig,
    ShopifyGraphQLFulfillmentOrdersQueryConfig,
    ShopifyGraphQLInventoryQueryConfig,
    ShopifyGraphQLOrdersQueryConfig,
    ShopifyGraphQLProductsQueryConfig,
    ShopifyNode,
    ShopifyOAuthCredential,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "config", "action_name"),
    [
        (
            "_handle_graphql_products",
            ShopifyGraphQLProductsQueryConfig(first=5, query_filter="vendor:NoClick"),
            "query_products_with_graphql",
        ),
        (
            "_handle_graphql_orders",
            ShopifyGraphQLOrdersQueryConfig(first=6, query_filter="status:OPEN"),
            "query_orders_with_graphql",
        ),
        (
            "_handle_graphql_customers",
            ShopifyGraphQLCustomersQueryConfig(first=7, query_filter="tag:VIP"),
            "query_customers_with_graphql",
        ),
        (
            "_handle_graphql_collections",
            ShopifyGraphQLCollectionsQueryConfig(first=8, query_filter="title:Sale"),
            "query_collections_with_graphql",
        ),
        (
            "_handle_graphql_inventory",
            ShopifyGraphQLInventoryQueryConfig(first=9),
            "query_inventory_with_graphql",
        ),
        (
            "_handle_graphql_fulfillment_orders",
            ShopifyGraphQLFulfillmentOrdersQueryConfig(first=10),
            "query_fulfillment_orders_with_graphql",
        ),
    ],
)
async def test_prebuilt_graphql_queries_forward_query_filter(
    handler_name: str, config: object, action_name: str
) -> None:
    """Handlers must use the schema's query_filter field, not a missing query field."""
    node = object.__new__(ShopifyNode)
    node._make_graphql_request = AsyncMock(return_value={"status": "success"})
    credentials = ShopifyOAuthCredential(
        store_name="review-store", access_token="test-token"
    )

    result = await getattr(node, handler_name)(config, credentials)

    assert result == {"status": "success"}
    node._make_graphql_request.assert_awaited_once()
    call = node._make_graphql_request.await_args
    assert call.kwargs["variables"] == {
        "first": config.first,
        "query": getattr(config, "query_filter", None),
    }
    assert call.kwargs["action_name"] == action_name
