"""
Mock tests for RSS node operations that can't be safely integration tested.

This file covers:
- Write operations (create, update, delete feeds/subscriptions)
- Operations requiring valid credentials for all services
- Operations that would modify user data
- Import/export operations requiring file handling

Uses unittest.mock to verify routing and logic without making real API calls.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from nodes.rss_node import (
    RSSNode,
    RSSNodeConfig,
    # Credentials
    RSSDirectCredential,
    RSSMinifluxCredential,
    RSSFeedlyCredential,
    RSSFreshRSSCredential,
    RSSAppCredential,
    # Direct parsing
    RSSParseFeedConfig,
    # Miniflux write operations
    MinifluxCreateFeedConfig,
    MinifluxUpdateFeedConfig,
    MinifluxDeleteFeedConfig,
    MinifluxRefreshFeedConfig,
    MinifluxCreateCategoryConfig,
    MinifluxUpdateCategoryConfig,
    MinifluxDeleteCategoryConfig,
    MinifluxToggleBookmarkConfig,
    MinifluxMarkEntriesReadConfig,
    MinifluxImportOPMLConfig,
    MinifluxExportOPMLConfig,
    # Miniflux read operations (for mocking credential-required tests)
    MinifluxGetFeedsConfig,
    # Feedly write operations
    FeedlySubscribeFeedConfig,
    FeedlyUnsubscribeFeedConfig,
    FeedlyMarkArticlesReadConfig,
    # Feedly read operations (for mocking credential-required tests)
    FeedlyGetSubscriptionsConfig,
    # FreshRSS write operations
    FreshRSSSubscribeFeedConfig,
    FreshRSSUnsubscribeFeedConfig,
    FreshRSSMarkAsReadConfig,
    # FreshRSS read operations (for mocking credential-required tests)
    FreshRSSGetSubscriptionsConfig,
    # RSS.app write operations
    RSSAppCreateFeedConfig,
    RSSAppUpdateFeedConfig,
    RSSAppDeleteFeedConfig,
)


def create_mock_node_direct(config) -> RSSNode:
    """Create an RSSNode with direct feed credential."""
    credential = RSSDirectCredential(auth_type="none")
    node_config = RSSNodeConfig(config=config, credentials=credential)
    return RSSNode(
        node_id="mock-node",
        node_type="automation-rss",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="mock-workflow",
    )


def create_mock_node_miniflux(config) -> RSSNode:
    """Create an RSSNode with Miniflux credential."""
    credential = RSSMinifluxCredential(
        server_url="https://miniflux.example.com", api_token="test-token-123"
    )
    node_config = RSSNodeConfig(config=config, credentials=credential)
    return RSSNode(
        node_id="mock-node",
        node_type="automation-rss",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="mock-workflow",
    )


def create_mock_node_feedly(config) -> RSSNode:
    """Create an RSSNode with Feedly credential."""
    credential = RSSFeedlyCredential(access_token="test-token-123")
    node_config = RSSNodeConfig(config=config, credentials=credential)
    return RSSNode(
        node_id="mock-node",
        node_type="automation-rss",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="mock-workflow",
    )


def create_mock_node_freshrss(config) -> RSSNode:
    """Create an RSSNode with FreshRSS credential."""
    credential = RSSFreshRSSCredential(
        server_url="https://freshrss.example.com",
        username="testuser",
        api_password="testpass",
    )
    node_config = RSSNodeConfig(config=config, credentials=credential)
    return RSSNode(
        node_id="mock-node",
        node_type="automation-rss",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="mock-workflow",
    )


def create_mock_node_rssapp(config) -> RSSNode:
    """Create an RSSNode with RSS.app credential."""
    credential = RSSAppCredential(api_key="test-api-key", secret_key="test-secret-key")
    node_config = RSSNodeConfig(config=config, credentials=credential)
    return RSSNode(
        node_id="mock-node",
        node_type="automation-rss",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="mock-workflow",
    )


class TestDirectFeedParsingMock:
    """Mock tests for direct RSS feed parsing."""

    @pytest.mark.asyncio
    @patch("nodes.rss_node.parse_rss_feed_direct")
    async def test_parse_feed_with_auth(self, mock_parse):
        """Test parsing feed with authentication using mock."""
        mock_parse.return_value = {
            "feed": {"title": "Test Feed"},
            "entries": [{"title": "Entry 1"}],
        }

        config = RSSParseFeedConfig(feed_url="https://example.com/feed.xml")
        node = create_mock_node_direct(config)
        result = await node.execute({})

        assert result["action"] == "parse_rss_atom_feed"
        mock_parse.assert_called_once()


class TestMinifluxWriteOperationsMock:
    """Mock tests for Miniflux write operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    async def test_create_feed(self, mock_post):
        """Test creating a feed in Miniflux."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 123, "title": "New Feed"}
        mock_post.return_value = mock_response

        config = MinifluxCreateFeedConfig(
            feed_url="https://example.com/feed.xml", category_id=1
        )
        node = create_mock_node_miniflux(config)
        result = await node.execute({})

        assert result["action"] == "create_miniflux_feed_subscription"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.put")
    async def test_update_feed(self, mock_put):
        """Test updating a feed in Miniflux."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 123, "title": "Updated Feed"}
        mock_put.return_value = mock_response

        config = MinifluxUpdateFeedConfig(feed_id=123, title="Updated Feed")
        node = create_mock_node_miniflux(config)
        result = await node.execute({})

        assert result["action"] == "update_miniflux_feed_settings"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.delete")
    async def test_delete_feed(self, mock_delete):
        """Test deleting a feed in Miniflux."""
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_delete.return_value = mock_response

        config = MinifluxDeleteFeedConfig(feed_id=123)
        node = create_mock_node_miniflux(config)
        result = await node.execute({})

        assert result["action"] == "delete_miniflux_feed_subscription"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.put")
    async def test_refresh_feed(self, mock_put):
        """Test refreshing a feed in Miniflux."""
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_put.return_value = mock_response

        config = MinifluxRefreshFeedConfig(feed_id=123)
        node = create_mock_node_miniflux(config)
        result = await node.execute({})

        assert result["action"] == "refresh_miniflux_feed"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    async def test_create_category(self, mock_post):
        """Test creating a category in Miniflux."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 5, "title": "New Category"}
        mock_post.return_value = mock_response

        config = MinifluxCreateCategoryConfig(title="New Category")
        node = create_mock_node_miniflux(config)
        result = await node.execute({})

        assert result["action"] == "create_miniflux_category"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.put")
    async def test_update_category(self, mock_put):
        """Test updating a category in Miniflux."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 5, "title": "Updated Category"}
        mock_put.return_value = mock_response

        config = MinifluxUpdateCategoryConfig(category_id=5, title="Updated Category")
        node = create_mock_node_miniflux(config)
        result = await node.execute({})

        assert result["action"] == "update_miniflux_category"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.delete")
    async def test_delete_category(self, mock_delete):
        """Test deleting a category in Miniflux."""
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_delete.return_value = mock_response

        config = MinifluxDeleteCategoryConfig(category_id=5)
        node = create_mock_node_miniflux(config)
        result = await node.execute({})

        assert result["action"] == "delete_miniflux_category"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.put")
    async def test_mark_entries_read(self, mock_put):
        """Test marking entries as read in Miniflux."""
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_put.return_value = mock_response

        config = MinifluxMarkEntriesReadConfig(entry_ids=[1, 2, 3])
        node = create_mock_node_miniflux(config)
        result = await node.execute({})

        assert result["action"] == "mark_miniflux_entries_read"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.put")
    async def test_toggle_bookmark(self, mock_put):
        """Test toggling bookmark on entry in Miniflux."""
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_put.return_value = mock_response

        config = MinifluxToggleBookmarkConfig(entry_id=123)
        node = create_mock_node_miniflux(config)
        result = await node.execute({})

        assert result["action"] == "toggle_miniflux_entry_bookmark"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_export_opml(self, mock_get):
        """Test exporting OPML from Miniflux."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '<?xml version="1.0"?><opml version="2.0"></opml>'
        mock_get.return_value = mock_response

        config = MinifluxExportOPMLConfig()
        node = create_mock_node_miniflux(config)
        result = await node.execute({})

        assert result["action"] == "export_miniflux_subscriptions_as_opml"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    async def test_import_opml(self, mock_post):
        """Test importing OPML to Miniflux."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"message": "Imported successfully"}
        mock_post.return_value = mock_response

        config = MinifluxImportOPMLConfig(
            opml_content='<?xml version="1.0"?><opml version="2.0"></opml>'
        )
        node = create_mock_node_miniflux(config)
        result = await node.execute({})

        assert result["action"] == "import_miniflux_subscriptions_from_opml"

    @pytest.mark.asyncio
    async def test_get_feeds(self):
        """Test getting all feeds from Miniflux (mocked to avoid credential requirement)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": 1, "title": "Feed 1", "feed_url": "https://example1.com/feed.xml"},
            {"id": 2, "title": "Feed 2", "feed_url": "https://example2.com/feed.xml"},
        ]

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            config = MinifluxGetFeedsConfig()
            node = create_mock_node_miniflux(config)
            result = await node.execute({})

            assert result["action"] == "get_miniflux_feeds"
            assert result["status"] == "success"


class TestFeedlyWriteOperationsMock:
    """Mock tests for Feedly write operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    async def test_subscribe_feed(self, mock_post):
        """Test subscribing to a feed in Feedly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "feed/123"}
        mock_post.return_value = mock_response

        config = FeedlySubscribeFeedConfig(
            feed_id="feed/https://example.com/feed.xml", title="Test Feed"
        )
        node = create_mock_node_feedly(config)
        result = await node.execute({})

        assert result["action"] == "subscribe_to_feedly_feed"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.delete")
    async def test_unsubscribe_feed(self, mock_delete):
        """Test unsubscribing from a feed in Feedly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_delete.return_value = mock_response

        config = FeedlyUnsubscribeFeedConfig(
            feed_id="feed/https://example.com/feed.xml"
        )
        node = create_mock_node_feedly(config)
        result = await node.execute({})

        assert result["action"] == "unsubscribe_from_feedly_feed"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    async def test_mark_articles_read(self, mock_post):
        """Test marking articles as read in Feedly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        config = FeedlyMarkArticlesReadConfig(entry_ids=["entry1", "entry2"])
        node = create_mock_node_feedly(config)
        result = await node.execute({})

        assert result["action"] == "mark_feedly_articles_read"

    @pytest.mark.asyncio
    async def test_get_subscriptions(self):
        """Test getting subscriptions from Feedly (mocked to avoid credential requirement)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": "feed/123", "title": "Feed 1", "website": "https://example1.com"},
            {"id": "feed/456", "title": "Feed 2", "website": "https://example2.com"},
        ]

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            config = FeedlyGetSubscriptionsConfig()
            node = create_mock_node_feedly(config)
            result = await node.execute({})

            assert result["action"] == "get_feedly_subscriptions"
            assert result["status"] == "success"


class TestFreshRSSWriteOperationsMock:
    """Mock tests for FreshRSS write operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    async def test_subscribe_feed(self, mock_post):
        """Test subscribing to a feed in FreshRSS."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_post.return_value = mock_response

        config = FreshRSSSubscribeFeedConfig(feed_url="https://example.com/feed.xml")
        node = create_mock_node_freshrss(config)
        result = await node.execute({})

        assert result["action"] == "subscribe_to_freshrss_feed"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    async def test_unsubscribe_feed(self, mock_post):
        """Test unsubscribing from a feed in FreshRSS."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_post.return_value = mock_response

        config = FreshRSSUnsubscribeFeedConfig(feed_id="feed/123")
        node = create_mock_node_freshrss(config)
        result = await node.execute({})

        assert result["action"] == "unsubscribe_from_freshrss_feed"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    async def test_mark_as_read(self, mock_post):
        """Test marking items as read in FreshRSS."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_post.return_value = mock_response

        config = FreshRSSMarkAsReadConfig(item_ids=["item123", "item456"])
        node = create_mock_node_freshrss(config)
        result = await node.execute({})

        assert result["action"] == "mark_freshrss_articles_read"

    @pytest.mark.asyncio
    async def test_get_subscriptions(self):
        """Test getting subscriptions from FreshRSS (mocked to avoid credential requirement)."""
        # Mock auth response
        mock_auth_response = MagicMock()
        mock_auth_response.status_code = 200
        mock_auth_response.text = "Auth=test-auth-token"

        # Mock subscriptions response
        mock_subs_response = MagicMock()
        mock_subs_response.status_code = 200
        mock_subs_response.json.return_value = {
            "subscriptions": [
                {
                    "id": "feed/123",
                    "title": "Feed 1",
                    "htmlUrl": "https://example1.com",
                },
                {
                    "id": "feed/456",
                    "title": "Feed 2",
                    "htmlUrl": "https://example2.com",
                },
            ]
        }

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_auth_response)
        mock_client.get = AsyncMock(return_value=mock_subs_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            config = FreshRSSGetSubscriptionsConfig()
            node = create_mock_node_freshrss(config)
            result = await node.execute({})

            assert result["action"] == "get_freshrss_subscriptions"
            assert result["status"] == "success"


class TestRSSAppWriteOperationsMock:
    """Mock tests for RSS.app write operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    async def test_create_feed(self, mock_post):
        """Test creating a feed in RSS.app."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"feed_id": "feed-123"}
        mock_post.return_value = mock_response

        config = RSSAppCreateFeedConfig(
            url="https://example.com", feed_name="Test Feed"
        )
        node = create_mock_node_rssapp(config)
        result = await node.execute({})

        assert result["action"] == "create_rssapp_feed"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.put")
    async def test_update_feed(self, mock_put):
        """Test updating a feed in RSS.app."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"feed_id": "feed-123"}
        mock_put.return_value = mock_response

        config = RSSAppUpdateFeedConfig(feed_id="feed-123", feed_name="Updated Feed")
        node = create_mock_node_rssapp(config)
        result = await node.execute({})

        assert result["action"] == "update_rssapp_feed"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.delete")
    async def test_delete_feed(self, mock_delete):
        """Test deleting a feed in RSS.app."""
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_delete.return_value = mock_response

        config = RSSAppDeleteFeedConfig(feed_id="feed-123")
        node = create_mock_node_rssapp(config)
        result = await node.execute({})

        assert result["action"] == "delete_rssapp_feed"


class TestErrorHandlingMock:
    """Mock tests for error handling."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_network_error(self, mock_get):
        """Test handling of network errors."""
        mock_get.side_effect = Exception("Network error")

        config = RSSParseFeedConfig(feed_url="https://example.com/feed.xml")
        node = create_mock_node_direct(config)
        result = await node.execute({})

        assert result["status"] == "error"
        assert result["action"] == "parse_rss_atom_feed"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_http_error_404(self, mock_get):
        """Test handling of HTTP 404 errors."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = Exception("404 Not Found")
        mock_get.return_value = mock_response

        config = RSSParseFeedConfig(feed_url="https://example.com/nonexistent-feed.xml")
        node = create_mock_node_direct(config)
        result = await node.execute({})

        assert result["action"] == "parse_rss_atom_feed"


class TestRSSOnlyNewItemsFilter:
    """RSS "only new items" is an on-demand ACTION: the first run returns ALL
    entries (no baseline), later runs return only entries not seen before. Dedup
    state is CAS'd in node state (via _update_node_state), not config."""

    @staticmethod
    def _bind(node, initial=None):
        store = dict(initial or {})

        async def _update(mutator, *, max_retries=4, skip_result=None):
            new_state, result = mutator(dict(store))
            if new_state is not None:
                store.clear()
                store.update(new_state)
            return result

        node._update_node_state = _update
        return store

    @pytest.mark.asyncio
    async def test_first_run_returns_all_entries(self):
        node = create_mock_node_direct(
            RSSParseFeedConfig(feed_url="https://example.com/feed.xml")
        )
        store = self._bind(node)
        out = await node._filter_new_items({"entries": [{"id": "a"}, {"id": "b"}]})
        # On-demand action: first run returns everything (no baseline).
        assert [e["id"] for e in out["entries"]] == ["a", "b"]
        assert out["entry_count"] == 2
        assert set(store["seen_item_ids"]) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_second_run_returns_only_new(self):
        node = create_mock_node_direct(
            RSSParseFeedConfig(feed_url="https://example.com/feed.xml")
        )
        store = self._bind(node, {"seen_item_ids": ["a", "b"]})
        out = await node._filter_new_items(
            {"entries": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}
        )
        assert [e["id"] for e in out["entries"]] == ["c"]
        assert set(store["seen_item_ids"]) == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_nothing_new_no_rewrite(self):
        node = create_mock_node_direct(
            RSSParseFeedConfig(feed_url="https://example.com/feed.xml")
        )
        store = self._bind(node, {"seen_item_ids": ["a"]})
        out = await node._filter_new_items({"entries": [{"id": "a"}]})
        assert out["entries"] == []
        assert store == {"seen_item_ids": ["a"]}  # untouched
