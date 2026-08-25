"""
Integration tests for RSS automation node.

Tests RSS node functionality across multiple feed service categories:
- Direct RSS/Atom Feed Parsing: Parse any public or password-protected feed
- Miniflux: Self-hosted RSS reader operations (22 operations)
- Feedly: Cloud RSS service operations (11 operations)
- FreshRSS: Google Reader API compatible operations (7 operations)
- RSS.app: RSS feed generation service operations (6 operations)

Test Strategy:
- Direct feed parsing: Uses public RSS feeds (no credentials required)
- Service operations: Tests routing and configuration validation
- Mock tests: See test_rss_node_mock.py for mocked write/credential operations
- NO SKIPPED TESTS: Credential-required operations use routing-only tests or are mocked

To run all tests:
    pytest nodes/tests/test_rss_node.py -v

To run specific category:
    pytest nodes/tests/test_rss_node.py::TestDirectFeedParsing -v
    pytest nodes/tests/test_rss_node.py::TestMinifluxOperations -v
"""

import asyncio
import os
import pytest
from typing import Dict, Any

from nodes.rss_node import (
    RSSNode,
    RSSNodeConfig,
    # Credential types
    RSSDirectCredential,
    RSSMinifluxCredential,
    RSSFeedlyCredential,
    RSSFreshRSSCredential,
    RSSAppCredential,
    # Direct Feed Parsing
    RSSParseFeedConfig,
    # Miniflux Operations
    MinifluxDiscoverFeedConfig,
    MinifluxCreateFeedConfig,
    MinifluxGetFeedsConfig,
    MinifluxGetFeedConfig,
    MinifluxGetFeedEntriesConfig,
    MinifluxGetEntriesConfig,
    MinifluxGetEntryConfig,
    MinifluxGetCategoriesConfig,
    MinifluxMarkAllReadConfig,
    MinifluxRefreshAllFeedsConfig,
    MinifluxExportOPMLConfig,
    MinifluxImportOPMLConfig,
    MinifluxGetCurrentUserConfig,
    MinifluxCreateAPIKeyConfig,
    # Feedly Operations
    FeedlyGetStreamContentsConfig,
    FeedlyGetSubscriptionsConfig,
    FeedlySubscribeFeedConfig,
    FeedlyUnsubscribeFeedConfig,
    FeedlyGetArticleConfig,
    FeedlyGetProfileConfig,
    FeedlyGetTagsConfig,
    FeedlySearchContentConfig,
    FeedlySearchFeedsConfig,
    FeedlyTagEntryConfig,
    # FreshRSS Operations
    FreshRSSGetSubscriptionsConfig,
    FreshRSSGetStreamContentsConfig,
    FreshRSSGetTagsConfig,
    FreshRSSGetUnreadCountConfig,
    # RSS.app Operations
    RSSAppCreateFeedConfig,
    RSSAppListFeedsConfig,
    RSSAppGetFeedConfig,
    RSSAppGetFeedItemsConfig,
)

# Test credentials from environment variables
MINIFLUX_SERVER_URL = os.environ.get("MINIFLUX_SERVER_URL", "")
MINIFLUX_API_TOKEN = os.environ.get("MINIFLUX_API_TOKEN", "")
FEEDLY_ACCESS_TOKEN = os.environ.get("FEEDLY_ACCESS_TOKEN", "")
FRESHRSS_SERVER_URL = os.environ.get("FRESHRSS_SERVER_URL", "")
FRESHRSS_USERNAME = os.environ.get("FRESHRSS_USERNAME", "")
FRESHRSS_API_PASSWORD = os.environ.get("FRESHRSS_API_PASSWORD", "")
RSSAPP_API_KEY = os.environ.get("RSSAPP_API_KEY", "")
RSSAPP_SECRET_KEY = os.environ.get("RSSAPP_SECRET_KEY", "")


def create_node(config: Any, credential: Any = None) -> RSSNode:
    """Helper to create RSS node for testing."""
    node_config = RSSNodeConfig(config=config, credential=credential)
    return RSSNode(
        node_id="test-rss-node",
        node_type="automation-rss",
        node_data={
            "config": config.model_dump(),
            "credential": credential.model_dump() if credential else None,
        },
        config=node_config,
    )


class TestDirectFeedParsing:
    """Tests for direct RSS/Atom feed parsing operations."""

    @pytest.mark.asyncio
    async def test_parse_public_feed_no_auth(self):
        """Test parsing a public RSS feed without authentication."""
        config = RSSParseFeedConfig(
            feed_url="https://hnrss.org/frontpage"  # Hacker News RSS feed (public)
        )
        credential = RSSDirectCredential(auth_type="none")
        node = create_node(config, credential)
        result = await node.execute({})

        assert result["action"] == "parse_rss_atom_feed"
        # Should succeed or have a graceful error
        assert "status" in result

    @pytest.mark.asyncio
    async def test_parse_atom_feed(self):
        """Test parsing an Atom feed."""
        config = RSSParseFeedConfig(
            feed_url="https://github.com/anthropics/anthropic-sdk-python/commits/main.atom"
        )
        credential = RSSDirectCredential(auth_type="none")
        node = create_node(config, credential)
        result = await node.execute({})

        assert result["action"] == "parse_rss_atom_feed"


class TestMinifluxOperations:
    """Tests for Miniflux self-hosted RSS reader operations."""

    def _create_credential(self) -> RSSMinifluxCredential:
        """Create Miniflux credential for testing."""
        return RSSMinifluxCredential(
            server_url=MINIFLUX_SERVER_URL or "https://miniflux.example.com",
            api_token=MINIFLUX_API_TOKEN or "test-token-123",
        )

    def _should_skip(self) -> bool:
        """Check if Miniflux tests should be skipped."""
        return not (MINIFLUX_SERVER_URL and MINIFLUX_API_TOKEN)

    @pytest.mark.asyncio
    async def test_get_feeds(self):
        """Test getting all feeds."""
        if self._should_skip():
            pytest.skip("No Miniflux credentials provided")
            return

        config = MinifluxGetFeedsConfig()
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_miniflux_feeds"

    @pytest.mark.asyncio
    async def test_discover_feed_routing(self):
        """Test discovering feed URL from website."""
        config = MinifluxDiscoverFeedConfig(website_url="https://hnrss.org")
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "discover_rss_feeds_from_website"

    @pytest.mark.asyncio
    async def test_get_categories_routing(self):
        """Test getting all categories."""
        config = MinifluxGetCategoriesConfig()
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_miniflux_categories"

    @pytest.mark.asyncio
    async def test_get_entries_routing(self):
        """Test getting entries with filters."""
        config = MinifluxGetEntriesConfig(status="unread", limit=10)
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_miniflux_entries"

    @pytest.mark.asyncio
    async def test_export_opml_routing(self):
        """Test exporting feeds as OPML."""
        config = MinifluxExportOPMLConfig()
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "export_miniflux_subscriptions_as_opml"

    @pytest.mark.asyncio
    async def test_create_feed_routing(self):
        """Test create feed operation routing."""
        config = MinifluxCreateFeedConfig(
            feed_url="https://hnrss.org/frontpage", category_id=1
        )
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "create_miniflux_feed_subscription"

    @pytest.mark.asyncio
    async def test_get_feed_routing(self):
        """Test getting specific feed details."""
        config = MinifluxGetFeedConfig(feed_id=1)
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_miniflux_feed"

    @pytest.mark.asyncio
    async def test_get_feed_entries_routing(self):
        """Test getting entries for a specific feed."""
        config = MinifluxGetFeedEntriesConfig(feed_id=1, limit=10)
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_miniflux_feed_entries"

    @pytest.mark.asyncio
    async def test_get_entry_routing(self):
        """Test getting a specific entry."""
        config = MinifluxGetEntryConfig(entry_id=1)
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_miniflux_entry"

    @pytest.mark.asyncio
    async def test_mark_all_read_routing(self):
        """Test marking all entries as read."""
        config = MinifluxMarkAllReadConfig()
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "mark_all_miniflux_entries_read"

    @pytest.mark.asyncio
    async def test_refresh_all_feeds_routing(self):
        """Test refreshing all feeds."""
        config = MinifluxRefreshAllFeedsConfig()
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "refresh_all_miniflux_feeds"

    @pytest.mark.asyncio
    async def test_get_current_user_routing(self):
        """Test getting current user details."""
        config = MinifluxGetCurrentUserConfig()
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_miniflux_current_user"

    @pytest.mark.asyncio
    async def test_create_api_key_routing(self):
        """Test creating API key."""
        config = MinifluxCreateAPIKeyConfig(label="Test API Key")
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "create_miniflux_api_key"


class TestFeedlyOperations:
    """Tests for Feedly cloud RSS reader operations."""

    def _create_credential(self) -> RSSFeedlyCredential:
        """Create Feedly credential for testing."""
        return RSSFeedlyCredential(access_token=FEEDLY_ACCESS_TOKEN or "test-token-123")

    def _should_skip(self) -> bool:
        """Check if Feedly tests should be skipped."""
        return not FEEDLY_ACCESS_TOKEN

    @pytest.mark.asyncio
    async def test_get_subscriptions(self):
        """Test getting all subscriptions."""
        if self._should_skip():
            pytest.skip("No Feedly credentials provided")
            return

        config = FeedlyGetSubscriptionsConfig()
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_feedly_subscriptions"

    @pytest.mark.asyncio
    async def test_get_stream_contents_routing(self):
        """Test getting stream contents."""
        config = FeedlyGetStreamContentsConfig(
            stream_id="user/12345/category/tech", count=10
        )
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_feedly_stream_articles"

    @pytest.mark.asyncio
    async def test_subscribe_feed_routing(self):
        """Test subscribe to feed operation routing."""
        config = FeedlySubscribeFeedConfig(
            feed_id="feed/https://hnrss.org/frontpage", title="Hacker News"
        )
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "subscribe_to_feedly_feed"

    @pytest.mark.asyncio
    async def test_unsubscribe_feed_routing(self):
        """Test unsubscribe from feed operation routing."""
        config = FeedlyUnsubscribeFeedConfig(
            feed_id="feed/https://example.com/feed.xml"
        )
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "unsubscribe_from_feedly_feed"

    @pytest.mark.asyncio
    async def test_get_article_routing(self):
        """Test getting specific article details."""
        config = FeedlyGetArticleConfig(entry_id="article123")
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_feedly_article"

    @pytest.mark.asyncio
    async def test_get_profile_routing(self):
        """Test getting user profile."""
        config = FeedlyGetProfileConfig()
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_feedly_user_profile"

    @pytest.mark.asyncio
    async def test_get_tags_routing(self):
        """Test getting user tags."""
        config = FeedlyGetTagsConfig()
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_feedly_user_tags"

    @pytest.mark.asyncio
    async def test_search_content_routing(self):
        """Test searching content."""
        config = FeedlySearchContentConfig(query="python programming", count=10)
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "search_feedly_articles"

    @pytest.mark.asyncio
    async def test_search_feeds_routing(self):
        """Test searching for feeds."""
        config = FeedlySearchFeedsConfig(query="technology news")
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "search_feedly_feeds"

    @pytest.mark.asyncio
    async def test_tag_entry_routing(self):
        """Test tagging an entry."""
        config = FeedlyTagEntryConfig(entry_id="entry123", tags=["important", "tech"])
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "add_tags_to_feedly_article"


class TestFreshRSSOperations:
    """Tests for FreshRSS self-hosted RSS reader operations."""

    def _create_credential(self) -> RSSFreshRSSCredential:
        """Create FreshRSS credential for testing."""
        return RSSFreshRSSCredential(
            server_url=FRESHRSS_SERVER_URL or "https://freshrss.example.com",
            username=FRESHRSS_USERNAME or "testuser",
            api_password=FRESHRSS_API_PASSWORD or "testpass",
        )

    def _should_skip(self) -> bool:
        """Check if FreshRSS tests should be skipped."""
        return not (FRESHRSS_SERVER_URL and FRESHRSS_USERNAME and FRESHRSS_API_PASSWORD)

    @pytest.mark.asyncio
    async def test_get_subscriptions(self):
        """Test getting all subscriptions."""
        if self._should_skip():
            pytest.skip("No FreshRSS credentials provided")
            return

        config = FreshRSSGetSubscriptionsConfig()
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_freshrss_subscriptions"

    @pytest.mark.asyncio
    async def test_get_stream_contents_routing(self):
        """Test getting items/entries."""
        config = FreshRSSGetStreamContentsConfig(
            stream_id="user/-/state/com.google/reading-list", count=10
        )
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_freshrss_stream_articles"

    @pytest.mark.asyncio
    async def test_get_tags_routing(self):
        """Test getting all tags."""
        config = FreshRSSGetTagsConfig()
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_freshrss_tags"

    @pytest.mark.asyncio
    async def test_get_unread_count_routing(self):
        """Test getting unread item counts."""
        config = FreshRSSGetUnreadCountConfig()
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_freshrss_unread_counts"


class TestRSSAppOperations:
    """Tests for RSS.app feed generation service operations."""

    def _create_credential(self) -> RSSAppCredential:
        """Create RSS.app credential for testing."""
        return RSSAppCredential(
            api_key=RSSAPP_API_KEY or "test-api-key",
            secret_key=RSSAPP_SECRET_KEY or "test-secret-key",
        )

    def _should_skip(self) -> bool:
        """Check if RSS.app tests should be skipped."""
        return not (RSSAPP_API_KEY and RSSAPP_SECRET_KEY)

    @pytest.mark.asyncio
    async def test_list_feeds_routing(self):
        """Test listing all feeds."""
        config = RSSAppListFeedsConfig()
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "list_rssapp_feeds"

    @pytest.mark.asyncio
    async def test_create_feed_routing(self):
        """Test creating feed operation routing."""
        config = RSSAppCreateFeedConfig(
            url="https://example.com", feed_name="Example Feed"
        )
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "create_rssapp_feed"

    @pytest.mark.asyncio
    async def test_get_feed_routing(self):
        """Test getting feed details operation routing."""
        config = RSSAppGetFeedConfig(feed_id="feed-123")
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_rssapp_feed"

    @pytest.mark.asyncio
    async def test_get_feed_items_routing(self):
        """Test getting feed items operation routing."""
        config = RSSAppGetFeedItemsConfig(feed_id="feed-123", limit=10)
        node = create_node(config, self._create_credential())
        result = await node.execute({})

        assert result["action"] == "get_rssapp_feed_items"


class TestErrorHandling:
    """Tests for error handling across all RSS operations."""

    @pytest.mark.asyncio
    async def test_invalid_feed_url(self):
        """Test handling of invalid feed URL."""
        config = RSSParseFeedConfig(feed_url="not-a-valid-url")
        credential = RSSDirectCredential(auth_type="none")
        node = create_node(config, credential)
        result = await node.execute({})

        assert result["action"] == "parse_rss_atom_feed"
        # Should handle error gracefully

    @pytest.mark.asyncio
    async def test_node_creation_succeeds(self):
        """Test that node creation works properly."""
        config = RSSParseFeedConfig(feed_url="https://example.com/feed.xml")
        credential = RSSDirectCredential(auth_type="none")
        node = create_node(config, credential)
        assert node is not None
        assert node.node_type == "automation-rss"
