"""Authenticated RSS feeds bind secret headers to one exact origin."""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from nodes.rss_node import RSSDirectCredential, parse_rss_feed_direct


class _ClientContext:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_authenticated_rss_credential_requires_bound_origin():
    with pytest.raises(ValueError, match="Allowed Feed Origin"):
        RSSDirectCredential(api_key="secret")


def test_authenticated_rss_credential_canonicalizes_bound_origin():
    credential = RSSDirectCredential(
        api_key="secret",
        allowed_origin="https://FEEDS.EXAMPLE.COM/",
    )
    assert credential.allowed_origin == "https://feeds.example.com"


@pytest.mark.asyncio
async def test_authenticated_rss_rejects_initial_cross_origin_before_request():
    with patch(
        "nodes.rss_node.guarded_async_client",
        side_effect=AssertionError("HTTP client must not be created"),
    ) as client_factory:
        with pytest.raises(ValueError, match="outside"):
            await parse_rss_feed_direct(
                "https://attacker.example/feed.xml",
                api_key="secret",
                allowed_origin="https://feeds.example.com",
            )
    client_factory.assert_not_called()


@pytest.mark.asyncio
async def test_authenticated_rss_rejects_cross_origin_redirect_without_second_request():
    first = httpx.Response(
        302,
        headers={"location": "https://attacker.example/collect"},
        request=httpx.Request("GET", "https://feeds.example.com/start"),
    )
    client = Mock()
    client.get = AsyncMock(return_value=first)

    with patch(
        "nodes.rss_node.guarded_async_client",
        return_value=_ClientContext(client),
    ):
        with pytest.raises(ValueError, match="outside"):
            await parse_rss_feed_direct(
                "https://feeds.example.com/start",
                api_key="secret",
                allowed_origin="https://feeds.example.com",
            )

    assert client.get.await_count == 1
    assert client.get.await_args.kwargs["headers"]["Authorization"] == "Bearer secret"


@pytest.mark.asyncio
async def test_authenticated_rss_allows_same_origin_relative_redirect():
    first = httpx.Response(
        302,
        headers={"location": "/final.xml"},
        request=httpx.Request("GET", "https://feeds.example.com/start"),
    )
    second = httpx.Response(
        200,
        text=(
            '<?xml version="1.0"?>'
            '<rss version="2.0"><channel><title>Safe</title>'
            '<item><title>One</title><link>https://example.com/one</link></item>'
            "</channel></rss>"
        ),
        request=httpx.Request("GET", "https://feeds.example.com/final.xml"),
    )
    client = Mock()
    client.get = AsyncMock(side_effect=[first, second])

    with patch(
        "nodes.rss_node.guarded_async_client",
        return_value=_ClientContext(client),
    ):
        result = await parse_rss_feed_direct(
            "https://feeds.example.com/start",
            custom_headers={"X-Feed-Key": "secret"},
            allowed_origin="https://feeds.example.com",
        )

    assert result["feed"]["title"] == "Safe"
    assert client.get.await_count == 2
    assert client.get.await_args_list[1].args[0] == "https://feeds.example.com/final.xml"
    assert client.get.await_args_list[1].kwargs["headers"]["X-Feed-Key"] == "secret"


@pytest.mark.asyncio
async def test_authenticated_rss_rejects_host_header_override():
    with pytest.raises(ValueError, match="must not override Host"):
        await parse_rss_feed_direct(
            "https://feeds.example.com/feed.xml",
            custom_headers={"Host": "attacker.example", "X-Key": "secret"},
            allowed_origin="https://feeds.example.com",
        )
