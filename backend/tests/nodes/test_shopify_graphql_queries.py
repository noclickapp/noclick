"""Regression tests for Shopify's pre-built GraphQL handlers."""

import json
from unittest.mock import AsyncMock

import pytest
from pydantic import TypeAdapter

from nodes.shopify_node import (
    ShopifyConfig,
    ShopifyCreateBlogArticleConfig,
    ShopifyDeleteBlogArticleConfig,
    ShopifyGraphQLCollectionsQueryConfig,
    ShopifyGraphQLCustomersQueryConfig,
    ShopifyGraphQLFulfillmentOrdersQueryConfig,
    ShopifyGraphQLInventoryQueryConfig,
    ShopifyGraphQLOrdersQueryConfig,
    ShopifyGraphQLProductsQueryConfig,
    ShopifyListBlogArticlesConfig,
    ShopifyListBlogsConfig,
    ShopifyNode,
    ShopifyOAuthCredential,
    ShopifyUpdateBlogArticleConfig,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "config", "action_name"),
    [
        (
            "_handle_graphql_products",
            ShopifyGraphQLProductsQueryConfig(
                first=5,
                query_filter="vendor:NoClick",
                after="products-cursor",
            ),
            "query_products_with_graphql",
        ),
        (
            "_handle_graphql_orders",
            ShopifyGraphQLOrdersQueryConfig(
                first=6,
                query_filter="status:OPEN",
                after="orders-cursor",
            ),
            "query_orders_with_graphql",
        ),
        (
            "_handle_graphql_customers",
            ShopifyGraphQLCustomersQueryConfig(
                first=7,
                query_filter="tag:VIP",
                after="customers-cursor",
            ),
            "query_customers_with_graphql",
        ),
        (
            "_handle_graphql_collections",
            ShopifyGraphQLCollectionsQueryConfig(
                first=8,
                query_filter="title:Sale",
                after="collections-cursor",
            ),
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
    expected_variables = {
        "first": config.first,
        "query": getattr(config, "query_filter", None),
    }
    if hasattr(config, "after"):
        expected_variables["after"] = config.after
        assert "$after: String" in call.kwargs["query"]
        assert "after: $after" in call.kwargs["query"]
        assert "pageInfo" in call.kwargs["query"]
        assert "endCursor" in call.kwargs["query"]
    assert call.kwargs["variables"] == expected_variables
    assert call.kwargs["action_name"] == action_name


def _graphql_node() -> ShopifyNode:
    node = object.__new__(ShopifyNode)
    node._make_graphql_request = AsyncMock(return_value={"status": "success"})
    return node


def _credentials() -> ShopifyOAuthCredential:
    return ShopifyOAuthCredential(store_name="review-store", access_token="test-token")


@pytest.mark.asyncio
async def test_blog_list_handlers_use_graphql_and_convert_legacy_ids() -> None:
    node = _graphql_node()

    await node._handle_list_blogs(
        ShopifyListBlogsConfig(limit=5, since_id="gid://shopify/Blog/10"),
        _credentials(),
    )
    blogs_call = node._make_graphql_request.await_args
    assert "blogs(first: $first" in blogs_call.kwargs["query"]
    assert blogs_call.kwargs["variables"] == {"first": 5, "query": "id:>10"}

    node._make_graphql_request.reset_mock()
    await node._handle_list_blog_articles(
        ShopifyListBlogArticlesConfig(
            blog_id="20",
            limit=6,
            since_id="30",
            tag='launch "day"',
            published_status="published",
        ),
        _credentials(),
    )
    articles_call = node._make_graphql_request.await_args
    assert "articles(first: $first, query: $query)" in articles_call.kwargs["query"]
    assert articles_call.kwargs["variables"] == {
        "first": 6,
        "query": (
            'blog_id:20 AND id:>30 AND tag:"launch \\"day\\"" '
            "AND published_status:published"
        ),
    }


@pytest.mark.asyncio
async def test_blog_mutations_use_graphql_inputs_and_surface_user_errors() -> None:
    node = _graphql_node()
    create_config = ShopifyCreateBlogArticleConfig(
        blog_id="20",
        title="New post",
        body_html="<p>Hello</p>",
        author="Ada",
        tags="launch, news",
        summary_html="<p>Summary</p>",
        published="false",
        image_src="https://example.com/image.jpg",
        image_alt="Launch",
    )

    await node._handle_create_blog_article(create_config, _credentials())

    create_call = node._make_graphql_request.await_args
    assert "articleCreate(article: $article)" in create_call.kwargs["query"]
    assert create_call.kwargs["variables"] == {
        "article": {
            "blogId": "gid://shopify/Blog/20",
            "title": "New post",
            "body": "<p>Hello</p>",
            "author": {"name": "Ada"},
            "tags": ["launch", "news"],
            "summary": "<p>Summary</p>",
            "isPublished": False,
            "image": {
                "url": "https://example.com/image.jpg",
                "altText": "Launch",
            },
        }
    }

    node._make_graphql_request.return_value = {
        "status": "success",
        "data": {
            "articleUpdate": {
                "article": None,
                "userErrors": [{"field": ["article", "title"], "message": "Bad title"}],
            }
        },
    }
    result = await node._handle_update_blog_article(
        ShopifyUpdateBlogArticleConfig(blog_id="20", article_id="40", title="Rejected"),
        _credentials(),
    )

    update_call = node._make_graphql_request.await_args
    assert "articleUpdate(id: $id, article: $article)" in update_call.kwargs["query"]
    assert update_call.kwargs["variables"]["id"] == "gid://shopify/Article/40"
    assert result["status"] == "error"
    assert result["error"] == "Bad title"

    node._make_graphql_request.return_value = {"status": "success", "data": {}}
    await node._handle_delete_blog_article(
        ShopifyDeleteBlogArticleConfig(blog_id="20", article_id="40"),
        _credentials(),
    )
    delete_call = node._make_graphql_request.await_args
    assert "articleDelete(id: $id)" in delete_call.kwargs["query"]
    assert delete_call.kwargs["variables"] == {"id": "gid://shopify/Article/40"}


def test_unapproved_scope_operations_are_absent_from_node_schema() -> None:
    schema = json.dumps(TypeAdapter(ShopifyConfig).json_schema())
    removed_operations = {
        "list_price_rules",
        "get_price_rule_by_id",
        "create_price_rule",
        "update_price_rule",
        "delete_price_rule",
        "list_discount_codes",
        "create_discount_code",
        "delete_discount_code",
        "list_gift_cards",
        "get_gift_card_by_id",
        "create_gift_card",
        "update_gift_card",
        "disable_gift_card",
        "create_draft_order_with_graphql",
    }

    assert not any(operation in schema for operation in removed_operations)
    assert "create_blog_article" in schema
