"""
Unit tests for Reddit node.
Tests the Reddit node functionality with mocked API responses.
All 68 operations are tested covering users, subreddits, posts, comments,
flair, multireddits, messages, wiki, live threads, and awards.
"""

import pytest
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock

from nodes.reddit_node import (
    RedditNode,
    RedditNodeConfig,
    RedditOAuthCredential,
    RedditScriptCredential,
    # User configs
    RedditGetMeConfig,
    RedditGetUserConfig,
    RedditGetUserPostsConfig,
    RedditGetUserCommentsConfig,
    RedditGetUserSavedConfig,
    RedditGetTrophiesConfig,
    RedditBlockUserConfig,
    RedditGetFriendsConfig,
    RedditGetKarmaConfig,
    RedditGetPreferencesConfig,
    RedditCheckUsernameConfig,
    RedditReportUserConfig,
    # Subreddit configs
    RedditGetSubredditPostsConfig,
    RedditGetSubredditInfoConfig,
    RedditGetSubredditRulesConfig,
    RedditGetMySubredditsConfig,
    RedditSubscribeConfig,
    RedditSearchSubredditsConfig,
    RedditGetSubredditModeratorsConfig,
    RedditGetRandomSubredditConfig,
    RedditGetPopularSubredditsConfig,
    RedditGetNewSubredditsConfig,
    RedditGetSubredditCommentsConfig,
    # Post configs
    RedditGetPostConfig,
    RedditGetPostCommentsConfig,
    RedditGetDuplicatesConfig,
    RedditSubmitTextPostConfig,
    RedditSubmitLinkPostConfig,
    RedditCrosspostConfig,
    RedditHideConfig,
    RedditReportConfig,
    RedditMarkNsfwConfig,
    RedditMarkSpoilerConfig,
    RedditGetRandomSubmissionConfig,
    # Comment configs
    RedditSubmitCommentConfig,
    # Common action configs
    RedditVoteConfig,
    RedditEditConfig,
    RedditDeleteConfig,
    RedditSaveConfig,
    # Flair configs
    RedditGetLinkFlairConfig,
    RedditSetLinkFlairConfig,
    RedditGetUserFlairConfig,
    RedditSetUserFlairConfig,
    # Listings/Feeds configs
    RedditGetBestConfig,
    RedditGetGildedConfig,
    # Search configs
    RedditSearchConfig,
    # Multireddit configs
    RedditGetMultiredditConfig,
    RedditGetMyMultiredditsConfig,
    RedditGetMultiredditPostsConfig,
    RedditCreateMultiredditConfig,
    RedditDeleteMultiredditConfig,
    RedditUpdateMultiredditConfig,
    RedditAddSubredditToMultiConfig,
    RedditRemoveSubredditFromMultiConfig,
    # Message configs
    RedditSendMessageConfig,
    RedditGetInboxConfig,
    RedditMarkMessagesReadConfig,
    RedditDeleteMessageConfig,
    RedditReplyMessageConfig,
    RedditMarkAllMessagesReadConfig,
    RedditUnreadMessageConfig,
    # Wiki configs
    RedditGetWikiPagesConfig,
    RedditGetWikiPageConfig,
    RedditGetWikiRevisionsConfig,
    # Live Thread configs
    RedditCreateLiveThreadConfig,
    RedditGetLiveThreadConfig,
    RedditGetLiveThreadUpdatesConfig,
    RedditUpdateLiveThreadConfig,
    RedditCloseLiveThreadConfig,
    # Award configs
    RedditGiveAwardConfig,
    # Additional API configs
    RedditGetInfoConfig,
    RedditGetMoreCommentsConfig,
    RedditLockConfig,
    RedditApproveConfig,
    RedditRemoveConfig,
    RedditDistinguishConfig,
    RedditStickyPostConfig,
    RedditSetContestModeConfig,
    RedditSetSuggestedSortConfig,
    RedditSendRepliesConfig,
    RedditGetDefaultSubredditsConfig,
    RedditGetBlockedUsersConfig,
    RedditUnblockUserConfig,
    RedditGetSubredditTrafficConfig,
    RedditIgnoreReportsConfig,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_credentials():
    """Create mock OAuth credentials."""
    return RedditOAuthCredential(
        access_token="mock_access_token",
        refresh_token="mock_refresh_token",
        expires_at="2099-12-31T23:59:59Z",
        username="test_user",
    )


@pytest.fixture
def mock_httpx_response():
    """Factory for creating mock httpx responses."""

    def _create_response(status_code: int, json_data: dict = None, text: str = ""):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = json_data or {}
        mock_resp.text = text or str(json_data)
        return mock_resp

    return _create_response


def create_node(config, credentials):
    """Helper to create a Reddit node with config."""
    node_config = RedditNodeConfig(config=config, credentials=credentials)
    node = RedditNode(
        node_id="test_reddit_node",
        node_type="automation-reddit",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    node.emit = AsyncMock()
    return node


# ============================================================================
# User Operations Tests
# ============================================================================


class TestGetMeOperation:
    @pytest.mark.asyncio
    async def test_get_me_success(self, mock_credentials, mock_httpx_response):
        """Test getting authenticated user info."""
        config = RedditGetMeConfig()
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "name": "test_user",
                "id": "abc123",
                "link_karma": 1000,
                "comment_karma": 500,
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "user" in result
        assert result["user"]["name"] == "test_user"


class TestGetUserOperation:
    @pytest.mark.asyncio
    async def test_get_user_success(self, mock_credentials, mock_httpx_response):
        """Test getting a specific user's info."""
        config = RedditGetUserConfig(username="other_user")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "name": "other_user",
                    "id": "xyz789",
                    "link_karma": 2000,
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "user" in result
        assert result["user"]["name"] == "other_user"


class TestGetUserPostsOperation:
    @pytest.mark.asyncio
    async def test_get_user_posts_success(self, mock_credentials, mock_httpx_response):
        """Test getting a user's posts."""
        config = RedditGetUserPostsConfig(username="test_user", sort="new", limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"id": "post1", "title": "Test Post 1"}},
                        {"data": {"id": "post2", "title": "Test Post 2"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "posts" in result
        assert result["count"] == 2


class TestGetUserCommentsOperation:
    @pytest.mark.asyncio
    async def test_get_user_comments_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting a user's comments."""
        config = RedditGetUserCommentsConfig(username="test_user", limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"id": "comment1", "body": "Test comment 1"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "comments" in result
        assert result["count"] == 1


class TestGetUserSavedOperation:
    @pytest.mark.asyncio
    async def test_get_user_saved_success(self, mock_credentials, mock_httpx_response):
        """Test getting a user's saved items."""
        config = RedditGetUserSavedConfig(limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"id": "saved1", "title": "Saved Post"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "items" in result
        assert result["count"] == 1


class TestGetTrophiesOperation:
    @pytest.mark.asyncio
    async def test_get_trophies_success(self, mock_credentials, mock_httpx_response):
        """Test getting a user's trophies."""
        config = RedditGetTrophiesConfig()
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "trophies": [
                        {"data": {"name": "Verified Email", "icon_70": "url"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "trophies" in result
        assert result["count"] == 1


class TestBlockUserOperation:
    @pytest.mark.asyncio
    async def test_block_user_success(self, mock_credentials, mock_httpx_response):
        """Test blocking a user."""
        config = RedditBlockUserConfig(username="spam_user")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["blocked"] == "spam_user"


class TestGetFriendsOperation:
    @pytest.mark.asyncio
    async def test_get_friends_success(self, mock_credentials, mock_httpx_response):
        """Test getting friends list."""
        config = RedditGetFriendsConfig()
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"name": "friend1"},
                        {"name": "friend2"},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "friends" in result
        assert result["count"] == 2


# ============================================================================
# Subreddit Operations Tests
# ============================================================================


class TestGetSubredditPostsOperation:
    def test_legacy_rss_operation_alias_maps_to_canonical_config(self):
        """Legacy RSS op should parse as the canonical public-feed config."""
        node_config = RedditNodeConfig(
            config={
                "operation": "get_subreddit_posts_via_rss",
                "subreddit": "python",
                "sort": "new",
                "limit": 10,
            },
            credentials=None,
        )

        assert isinstance(node_config.config, RedditGetSubredditPostsConfig)
        assert node_config.config.operation == "get_subreddit_posts"
        assert node_config.config.subreddit == "python"

    def test_legacy_subreddit_top_alias_maps_to_canonical_config(self):
        """Legacy subreddit-top op should parse as canonical subreddit posts."""
        node_config = RedditNodeConfig(
            config={
                "operation": "get_subreddit_top_posts",
                "subreddit": "python",
                "time": "month",
                "limit": 10,
            },
            credentials=None,
        )

        assert isinstance(node_config.config, RedditGetSubredditPostsConfig)
        assert node_config.config.operation == "get_subreddit_posts"
        assert node_config.config.sort == "top"
        assert node_config.config.time == "month"
        assert node_config.config.subreddit == "python"

    def test_legacy_rising_alias_maps_to_canonical_config(self):
        """Legacy rising op should parse as canonical subreddit posts."""
        node_config = RedditNodeConfig(
            config={
                "operation": "get_rising_posts",
                "subreddit": "python",
                "limit": 10,
            },
            credentials=None,
        )

        assert isinstance(node_config.config, RedditGetSubredditPostsConfig)
        assert node_config.config.operation == "get_subreddit_posts"
        assert node_config.config.sort == "rising"
        assert node_config.config.subreddit == "python"

    def test_legacy_controversial_alias_maps_to_canonical_config(self):
        """Legacy controversial op should parse as canonical subreddit posts."""
        node_config = RedditNodeConfig(
            config={
                "operation": "get_controversial_posts",
                "subreddit": "python",
                "time": "week",
                "limit": 10,
            },
            credentials=None,
        )

        assert isinstance(node_config.config, RedditGetSubredditPostsConfig)
        assert node_config.config.operation == "get_subreddit_posts"
        assert node_config.config.sort == "controversial"
        assert node_config.config.time == "week"
        assert node_config.config.subreddit == "python"

    @pytest.mark.asyncio
    async def test_get_subreddit_posts_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting posts from a subreddit."""
        config = RedditGetSubredditPostsConfig(subreddit="python", sort="hot", limit=10)
        node = create_node(config, mock_credentials)
        node._fetch_public_subreddit_posts = AsyncMock(return_value={
            "posts": [
                {"post_id": "post1", "title": "Python question"},
                {"post_id": "post2", "title": "Django help"},
            ],
            "count": 2,
            "subreddit": "python",
            "source": "public_feed",
            "sort": "hot",
        })

        result = await node.execute({})

        assert "posts" in result
        assert result["count"] == 2
        assert result["subreddit"] == "python"
        assert result["source"] == "public_feed"

    @pytest.mark.asyncio
    async def test_get_subreddit_posts_public_feed_without_credentials(self):
        """Test subreddit-post operation without credentials."""
        config = RedditGetSubredditPostsConfig(
            subreddit="python",
            sort="new",
            limit=10,
        )
        node = create_node(config, None)
        node._fetch_public_subreddit_posts = AsyncMock(return_value={
            "posts": [{"post_id": "abc123", "title": "Test Feed Post"}],
            "count": 1,
            "subreddit": "python",
            "source": "public_feed",
            "sort": "new",
        })

        result = await node.execute({})

        node._fetch_public_subreddit_posts.assert_awaited_once()
        assert result["source"] == "public_feed"
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_get_subreddit_posts_stays_public_when_credentials_present(
        self, mock_credentials
    ):
        """Credentials should not change the public subreddit-post fetch path."""
        config = RedditGetSubredditPostsConfig(
            subreddit="python",
            sort="top",
            time="month",
            limit=10,
        )
        node = create_node(config, mock_credentials)
        node._fetch_public_subreddit_posts = AsyncMock(return_value={
            "posts": [{"post_id": "feed1", "title": "Public feed listing"}],
            "count": 1,
            "subreddit": "python",
            "source": "public_feed",
            "sort": "top",
            "time_period": "month",
        })

        result = await node.execute({})

        node._fetch_public_subreddit_posts.assert_awaited_once_with(
            subreddit="python",
            sort="top",
            time_period="month",
            limit=10,
            fetch_comments="false",
            use_proxy="auto",
            content_mode="fast",
        )
        assert result["source"] == "public_feed"
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_get_subreddit_posts_defaults_to_public_feed(
        self, mock_credentials
    ):
        """Fast mode should use the public RSS feed before any vendor scraper."""
        config = RedditGetSubredditPostsConfig(
            subreddit="python",
            sort="hot",
            limit=10,
        )
        node = create_node(config, mock_credentials)
        node._fetch_rss_feed = AsyncMock(return_value={
            "posts": [{"post_id": "feed1", "title": "Feed listing"}],
            "proxy_stats": {
                "mode": "auto",
                "direct_requests": 1,
                "proxy_requests": 0,
                "total_requests": 1,
            },
        })
        node._fetch_public_subreddit_posts_via_brightdata = AsyncMock()

        result = await node.execute({})

        node._fetch_rss_feed.assert_awaited_once_with(
            "python",
            sort="hot",
            time_param=None,
            limit=10,
            proxy_mode="auto",
        )
        node._fetch_public_subreddit_posts_via_brightdata.assert_not_called()
        assert result["source"] == "public_feed"
        assert result["content_mode"] == "fast"
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_fetch_public_subreddit_posts_via_brightdata_builds_expected_input(
        self, monkeypatch, mock_credentials
    ):
        """Bright Data scraping should trigger a subreddit snapshot and normalize posts."""
        node = create_node(
            RedditGetSubredditPostsConfig(subreddit="python", sort="top", time="week", limit=5),
            mock_credentials,
        )
        monkeypatch.setattr("nodes.reddit_node._get_brightdata_api_token", lambda: "bd-token")

        calls = []

        class FakeResponse:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self._payload = payload
                self.text = str(payload)

            def json(self):
                return self._payload

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                self.headers = kwargs.get("headers")

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, params=None, json=None):
                calls.append({"method": "post", "url": url, "params": params, "json": json})
                return FakeResponse(200, {"snapshot_id": "snap123"})

            async def get(self, url, params=None):
                calls.append({"method": "get", "url": url, "params": params})
                if url.endswith("/progress/snap123"):
                    return FakeResponse(200, {"status": "ready", "records": 1})
                return FakeResponse(
                    200,
                    [
                        {
                            "post_id": "t3_abc123",
                            "url": "https://www.reddit.com/r/python/comments/abc123/first_post/",
                            "user_posted": "author_one",
                            "title": "First post",
                            "community_name": "python",
                            "description": "Hello",
                            "num_upvotes": 42,
                            "num_comments": 1,
                            "date_posted": "2026-06-08T10:00:00.000Z",
                            "comments": [
                                {
                                    "comment": "First comment",
                                    "url": "https://www.reddit.com/r/python/comments/abc123/comment/def456/",
                                    "user_commenting": "commenter_one",
                                    "date_of_comment": "2026-06-08T10:05:00.000Z",
                                    "num_upvotes": 3,
                                    "num_replies": 0,
                                    "replies": [],
                                }
                            ],
                        }
                    ],
                )

        monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)
        node._check_brightdata_credits_or_raise = AsyncMock()
        node._track_brightdata_reddit_usage = AsyncMock()

        result = await node._fetch_public_subreddit_posts_via_brightdata(
            subreddit="r/python",
            sort="top",
            limit=5,
            fetch_comments="true",
        )

        assert calls[0] == {
            "method": "post",
            "url": "https://api.brightdata.com/datasets/v3/trigger",
            "params": {
                "dataset_id": "gd_lvz8ah06191smkebj4",
                "type": "discover_new",
                "discover_by": "subreddit_url",
                "include_errors": "true",
                "format": "json",
                "limit_per_input": "5",
            },
            "json": {
                "input": [
                    {
                        "url": "https://www.reddit.com/r/python/",
                        "sort_by": "Top",
                    }
                ]
            },
        }
        assert result["source"] == "brightdata_reddit_scraper"
        assert result["posts"][0]["post_id"] == "abc123"
        assert result["posts"][0]["comments"][0]["comment_id"] == "def456"
        assert result["posts"][0]["comments"][0]["score"] == 3
        node._check_brightdata_credits_or_raise.assert_called_once()
        node._track_brightdata_reddit_usage.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_track_brightdata_usage_applies_platform_markup(
        self, monkeypatch, mock_credentials
    ):
        """Bright Data scraper usage is recorded with the platform floor markup
        applied — three times raw vendor cost where a platform sets one."""
        node = create_node(
            RedditGetSubredditPostsConfig(subreddit="python", sort="hot", limit=5),
            mock_credentials,
        )
        node.user_id = "1069e27a-e9d5-4054-9525-0bea774912e9"
        tracked_events = []

        def fake_track_usage_event(event, sio=None, sid=None, loop=None):
            tracked_events.append(event)

        from billing.usage_tracker import usage_tracker
        monkeypatch.setattr(usage_tracker, "track_usage_event", fake_track_usage_event)

        await node._track_brightdata_reddit_usage(
            raw_cost=Decimal("0.015"),
            item_count=10,
            snapshot_id="snap123",
            operation="get_subreddit_posts",
        )

        assert len(tracked_events) == 1
        event = tracked_events[0]
        from billing.markup import PLATFORM_MIN_MARKUP

        assert event.total_cost == Decimal("0.015") * PLATFORM_MIN_MARKUP
        assert event.quantity == Decimal("10")
        assert event.usage_subtype == "reddit/get_subreddit_posts"
        assert event.metadata["provider"] == "brightdata"
        assert event.metadata["raw_cost_usd"] == 0.015
        assert event.metadata["charged_cost_usd"] == float(
            Decimal("0.015") * PLATFORM_MIN_MARKUP
        )

    @pytest.mark.asyncio
    async def test_get_subreddit_posts_with_comments_uses_public_feed_by_default(
        self, mock_credentials
    ):
        """Comments do not force the slower Bright Data path in fast mode."""
        config = RedditGetSubredditPostsConfig(
            subreddit="python",
            sort="hot",
            limit=10,
            fetch_comments="true",
            use_proxy="never",
        )
        node = create_node(config, mock_credentials)
        node._fetch_rss_feed = AsyncMock(return_value={
            "posts": [{"post_id": "feed1", "title": "Feed listing"}],
            "proxy_stats": {
                "mode": "never",
                "direct_requests": 1,
                "proxy_requests": 0,
                "total_requests": 1,
            },
        })
        node._attach_public_feed_comments = AsyncMock()
        node._fetch_public_subreddit_posts_via_brightdata = AsyncMock()

        result = await node.execute({})

        node._fetch_rss_feed.assert_awaited_once_with(
            "python",
            sort="hot",
            time_param=None,
            limit=10,
            proxy_mode="never",
        )
        node._attach_public_feed_comments.assert_awaited_once()
        node._fetch_public_subreddit_posts_via_brightdata.assert_not_called()
        assert result["source"] == "public_feed"
        assert result["comments_fetched"] is True

    @pytest.mark.asyncio
    async def test_get_subreddit_posts_falls_back_to_brightdata_when_feed_fails(
        self, mock_credentials
    ):
        """Fast mode should use Bright Data only as the vendor fallback layer."""
        config = RedditGetSubredditPostsConfig(
            subreddit="python",
            sort="hot",
            limit=10,
            use_proxy="never",
        )
        node = create_node(config, mock_credentials)
        node._fetch_rss_feed = AsyncMock(side_effect=ValueError("feed blocked"))
        node._fetch_public_subreddit_posts_via_brightdata = AsyncMock(return_value={
            "posts": [{"post_id": "bright1", "title": "Scraper listing"}],
            "count": 1,
            "subreddit": "python",
            "source": "brightdata_reddit_scraper",
            "content_mode": "rich",
        })

        result = await node.execute({})

        node._fetch_rss_feed.assert_awaited_once_with(
            "python",
            sort="hot",
            time_param=None,
            limit=10,
            proxy_mode="never",
        )
        node._fetch_public_subreddit_posts_via_brightdata.assert_awaited_once_with(
            subreddit="python",
            sort="hot",
            limit=10,
            fetch_comments="false",
        )
        assert result["source"] == "brightdata_reddit_scraper"
        assert result["fallback_reason"] == "public_feed_failed"
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_get_subreddit_posts_rich_content_uses_brightdata_first(
        self, mock_credentials
    ):
        """Rich content is opt-in and should use Bright Data directly."""
        config = RedditGetSubredditPostsConfig(
            subreddit="python",
            sort="hot",
            limit=10,
            content_mode="rich",
        )
        node = create_node(config, mock_credentials)
        node._fetch_public_subreddit_posts_via_brightdata = AsyncMock(return_value={
            "posts": [{"post_id": "bright1", "title": "Scraper listing"}],
            "count": 1,
            "subreddit": "python",
            "source": "brightdata_reddit_scraper",
            "content_mode": "rich",
        })
        node._fetch_rss_feed = AsyncMock()

        result = await node.execute({})

        node._fetch_public_subreddit_posts_via_brightdata.assert_awaited_once_with(
            subreddit="python",
            sort="hot",
            limit=10,
            fetch_comments="false",
        )
        node._fetch_rss_feed.assert_not_called()
        assert result["source"] == "brightdata_reddit_scraper"
        assert result["content_mode"] == "rich"

    @pytest.mark.asyncio
    async def test_reddit_get_retries_403_block_page_through_proxy(
        self, monkeypatch, mock_credentials
    ):
        """A Reddit 403 block page should trigger the auto-proxy retry path."""
        node = create_node(
            RedditGetSubredditPostsConfig(subreddit="python", sort="hot", limit=10),
            mock_credentials,
        )

        direct_response = MagicMock()
        direct_response.status_code = 403
        direct_response.text = "You've been blocked by network security."

        proxied_response = MagicMock()
        proxied_response.status_code = 200
        proxied_response.text = "ok"

        calls = []

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                self.proxy = kwargs.get("proxy")

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None, timeout=None):
                calls.append({"url": url, "proxy": self.proxy})
                return proxied_response if self.proxy else direct_response

        monkeypatch.setattr("nodes.reddit_node._get_brightdata_proxy_url", lambda: "http://proxy.example")
        monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

        response, used_proxy = await node._reddit_get("https://www.reddit.com/r/python/hot.rss")

        assert response is proxied_response
        assert used_proxy is True
        assert calls == [
            {"url": "https://www.reddit.com/r/python/hot.rss", "proxy": None},
            {"url": "https://www.reddit.com/r/python/hot.rss", "proxy": "http://proxy.example"},
        ]

    @pytest.mark.asyncio
    async def test_fetch_rss_feed_parses_atom_feed(self, mock_credentials):
        """Public subreddit feed should use the Atom/RSS parser path."""
        node = create_node(
            RedditGetSubredditPostsConfig(subreddit="python", sort="hot", limit=2),
            mock_credentials,
        )

        atom_feed = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>First post</title>
    <link href="https://www.reddit.com/r/python/comments/abc123/first_post/" />
    <author><name>author_one</name></author>
    <category term="python" />
    <updated>2026-06-08T10:00:00+00:00</updated>
    <content type="html">&lt;p&gt;Hello&lt;/p&gt;</content>
  </entry>
  <entry>
    <title>Second post</title>
    <link href="https://www.reddit.com/r/python/comments/def456/second_post/" />
    <author><name>author_two</name></author>
    <category term="python" />
    <published>2026-06-08T11:00:00+00:00</published>
    <summary>World</summary>
  </entry>
</feed>"""

        response = MagicMock()
        response.status_code = 200
        response.content = atom_feed
        response.text = atom_feed.decode()

        node._fetch_page_with_retry = AsyncMock(return_value=(response, False))

        result = await node._fetch_rss_feed("python", sort="hot", limit=2, proxy_mode="auto")

        node._fetch_page_with_retry.assert_awaited_once()
        assert result["proxy_stats"]["direct_requests"] == 1
        assert result["proxy_stats"]["proxy_requests"] == 0
        assert len(result["posts"]) == 2
        assert result["posts"][0]["title"] == "First post"
        assert result["posts"][0]["post_id"] == "abc123"
        assert result["posts"][1]["title"] == "Second post"
        assert result["posts"][1]["post_id"] == "def456"

    @pytest.mark.asyncio
    async def test_fetch_post_comments_uses_public_comment_feed(self, mock_credentials):
        """Public comment fetch should parse Reddit's Atom comment feed, not JSON."""
        node = create_node(
            RedditGetSubredditPostsConfig(subreddit="python", sort="hot", limit=2),
            mock_credentials,
        )

        atom_feed = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>First post</title>
    <link href="https://www.reddit.com/r/python/comments/abc123/first_post/" />
    <author><name>/u/post_author</name></author>
    <updated>2026-06-08T10:00:00+00:00</updated>
    <content type="html">&lt;p&gt;Post body&lt;/p&gt;</content>
  </entry>
  <entry>
    <title>/u/commenter_one on First post</title>
    <link href="https://www.reddit.com/r/python/comments/abc123/first_post/def456/" />
    <author><name>/u/commenter_one</name></author>
    <updated>2026-06-08T10:05:00+00:00</updated>
    <content type="html">&lt;p&gt;First comment&lt;/p&gt;</content>
  </entry>
  <entry>
    <title>/u/commenter_two on First post</title>
    <link href="https://www.reddit.com/r/python/comments/abc123/first_post/ghi789/" />
    <author><name>/u/commenter_two</name></author>
    <published>2026-06-08T10:10:00+00:00</published>
    <summary>&lt;p&gt;Second comment&lt;/p&gt;</summary>
  </entry>
</feed>"""

        response = MagicMock()
        response.status_code = 200
        response.content = atom_feed
        response.text = atom_feed.decode()
        node._reddit_get = AsyncMock(return_value=(response, False))

        comments = await node._fetch_post_comments("abc123", "python", limit=2, proxy_mode="auto")

        node._reddit_get.assert_awaited_once_with(
            "https://www.reddit.com/r/python/comments/abc123/.rss",
            proxy_mode="auto",
        )
        assert len(comments) == 2
        assert comments[0]["comment_id"] == "def456"
        assert comments[0]["author"] == "/u/commenter_one"
        assert comments[0]["body"] == "First comment"
        assert comments[1]["comment_id"] == "ghi789"
        assert comments[1]["body"] == "Second comment"

    @pytest.mark.asyncio
    async def test_normalize_brightdata_post_keeps_post_and_comments_together(
        self, mock_credentials
    ):
        """Bright Data rows should normalize into the node's existing post/comment shape."""
        node = create_node(
            RedditGetSubredditPostsConfig(subreddit="python", sort="hot", limit=2),
            mock_credentials,
        )
        result = node._normalize_brightdata_post(
            item={
                "post_id": "t3_abc123",
                "url": "https://www.reddit.com/r/python/comments/abc123/first_post/",
                "user_posted": "author_one",
                "title": "First post",
                "community_name": "python",
                "description": "Hello",
                "num_upvotes": 42,
                "num_comments": 1,
                "date_posted": "2026-06-08T10:00:00.000Z",
                "timestamp": "2026-06-08T10:00:05.000Z",
                "comments": [
                    {
                        "comment": "First comment",
                        "url": "https://www.reddit.com/r/python/comments/abc123/comment/def456/",
                        "user_commenting": "commenter_one",
                        "date_of_comment": "2026-06-08T10:05:00.000Z",
                        "num_upvotes": 3,
                        "num_replies": 0,
                    }
                ],
            },
            should_fetch_comments=True,
        )

        assert result["post_id"] == "abc123"
        assert result["score"] == 42
        assert result["comments"][0]["comment_id"] == "def456"
        assert result["comments"][0]["score"] == 3


class TestGetSubredditInfoOperation:
    @pytest.mark.asyncio
    async def test_get_subreddit_info_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting subreddit info."""
        config = RedditGetSubredditInfoConfig(subreddit="python")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "display_name": "python",
                    "subscribers": 1000000,
                    "public_description": "News about Python",
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "subreddit" in result
        assert result["subreddit"]["display_name"] == "python"


class TestGetSubredditRulesOperation:
    @pytest.mark.asyncio
    async def test_get_subreddit_rules_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting subreddit rules."""
        config = RedditGetSubredditRulesConfig(subreddit="python")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "rules": [
                    {"short_name": "Rule 1", "description": "Be nice"},
                    {"short_name": "Rule 2", "description": "No spam"},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "rules" in result
        assert result["count"] == 2
        assert result["subreddit"] == "python"


class TestGetMySubredditsOperation:
    @pytest.mark.asyncio
    async def test_get_my_subreddits_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting subscribed subreddits."""
        config = RedditGetMySubredditsConfig(where="subscriber", limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"display_name": "python"}},
                        {"data": {"display_name": "programming"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "subreddits" in result
        assert result["count"] == 2


class TestSubscribeOperation:
    @pytest.mark.asyncio
    async def test_subscribe_success(self, mock_credentials, mock_httpx_response):
        """Test subscribing to a subreddit."""
        config = RedditSubscribeConfig(subreddit="python")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["subreddit"] == "python"
        assert result["action"] == "subscribed"

    @pytest.mark.asyncio
    async def test_unsubscribe_success(self, mock_credentials, mock_httpx_response):
        """Test unsubscribing from a subreddit."""
        config = RedditSubscribeConfig(subreddit="python", unsubscribe=True)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "unsubscribed"


class TestSearchSubredditsOperation:
    @pytest.mark.asyncio
    async def test_search_subreddits_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test searching for subreddits."""
        config = RedditSearchSubredditsConfig(query="python", limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"display_name": "python"}},
                        {"data": {"display_name": "learnpython"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "subreddits" in result
        assert result["count"] == 2
        assert result["query"] == "python"


# ============================================================================
# Post Operations Tests
# ============================================================================


class TestGetPostOperation:
    @pytest.mark.asyncio
    async def test_get_post_success(self, mock_credentials, mock_httpx_response):
        """Test getting a specific post."""
        config = RedditGetPostConfig(post_id="abc123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {
                            "data": {
                                "id": "abc123",
                                "title": "Test Post",
                                "selftext": "Content",
                            }
                        }
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "post" in result
        assert result["post"]["id"] == "abc123"


class TestGetPostCommentsOperation:
    @pytest.mark.asyncio
    async def test_get_post_comments_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting comments on a post."""
        config = RedditGetPostCommentsConfig(post_id="abc123", limit=10)
        node = create_node(config, mock_credentials)

        # Reddit returns [post, comments] for comments endpoint
        mock_response = mock_httpx_response(
            200,
            [
                {"data": {"children": [{"data": {"id": "abc123", "title": "Test"}}]}},
                {
                    "data": {
                        "children": [
                            {"data": {"id": "c1", "body": "Comment 1"}},
                            {"data": {"id": "c2", "body": "Comment 2"}},
                        ]
                    }
                },
            ],
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "comments" in result
        assert result["count"] == 2


class TestGetDuplicatesOperation:
    @pytest.mark.asyncio
    async def test_get_duplicates_success(self, mock_credentials, mock_httpx_response):
        """Test getting duplicate posts."""
        config = RedditGetDuplicatesConfig(post_id="abc123", limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            [
                {"data": {"children": [{"data": {"id": "abc123"}}]}},
                {
                    "data": {
                        "children": [
                            {"data": {"id": "dup1", "title": "Crosspost 1"}},
                        ]
                    }
                },
            ],
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "duplicates" in result
        assert result["count"] == 1


class TestSubmitTextPostOperation:
    @pytest.mark.asyncio
    async def test_submit_text_post_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test submitting a text post."""
        config = RedditSubmitTextPostConfig(
            subreddit="test", title="Test Post", text="This is a test post."
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "json": {
                    "data": {
                        "id": "newpost123",
                        "name": "t3_newpost123",
                        "url": "https://reddit.com/r/test/comments/newpost123",
                    }
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["id"] == "newpost123"


class TestSubmitLinkPostOperation:
    @pytest.mark.asyncio
    async def test_submit_link_post_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test submitting a link post."""
        config = RedditSubmitLinkPostConfig(
            subreddit="test", title="Check this out", url="https://example.com"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "json": {
                    "data": {
                        "id": "linkpost123",
                        "name": "t3_linkpost123",
                        "url": "https://reddit.com/r/test/comments/linkpost123",
                    }
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["id"] == "linkpost123"


class TestCrosspostOperation:
    @pytest.mark.asyncio
    async def test_crosspost_success(self, mock_credentials, mock_httpx_response):
        """Test crossposting a post."""
        config = RedditCrosspostConfig(
            thing_id="t3_original123",
            subreddit="othersub",
            title="Crosspost: Original Title",
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "json": {
                    "data": {
                        "id": "crosspost123",
                        "name": "t3_crosspost123",
                        "url": "https://reddit.com/r/othersub/comments/crosspost123",
                    }
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["id"] == "crosspost123"
        assert result["crossposted_from"] == "t3_original123"


class TestHideOperation:
    @pytest.mark.asyncio
    async def test_hide_post_success(self, mock_credentials, mock_httpx_response):
        """Test hiding a post."""
        config = RedditHideConfig(thing_id="t3_abc123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "hidden"

    @pytest.mark.asyncio
    async def test_unhide_post_success(self, mock_credentials, mock_httpx_response):
        """Test unhiding a post."""
        config = RedditHideConfig(thing_id="t3_abc123", unhide=True)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "unhidden"


class TestReportOperation:
    @pytest.mark.asyncio
    async def test_report_success(self, mock_credentials, mock_httpx_response):
        """Test reporting a post."""
        config = RedditReportConfig(thing_id="t3_abc123", reason="spam")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["reason"] == "spam"


# ============================================================================
# Comment Operations Tests
# ============================================================================


class TestSubmitCommentOperation:
    @pytest.mark.asyncio
    async def test_submit_comment_success(self, mock_credentials, mock_httpx_response):
        """Test submitting a comment."""
        config = RedditSubmitCommentConfig(thing_id="t3_abc123", text="Great post!")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "json": {
                    "data": {
                        "things": [
                            {"data": {"id": "comment123", "name": "t1_comment123"}}
                        ]
                    }
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["id"] == "comment123"


# ============================================================================
# Common Action Tests
# ============================================================================


class TestVoteOperation:
    @pytest.mark.asyncio
    async def test_upvote_success(self, mock_credentials, mock_httpx_response):
        """Test upvoting."""
        config = RedditVoteConfig(thing_id="t3_abc123", direction="up")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["vote"] == "up"

    @pytest.mark.asyncio
    async def test_downvote_success(self, mock_credentials, mock_httpx_response):
        """Test downvoting."""
        config = RedditVoteConfig(thing_id="t3_abc123", direction="down")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["vote"] == "down"


class TestEditOperation:
    @pytest.mark.asyncio
    async def test_edit_success(self, mock_credentials, mock_httpx_response):
        """Test editing content."""
        config = RedditEditConfig(thing_id="t3_abc123", text="Updated content")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "json": {
                    "data": {
                        "things": [{"data": {"id": "abc123", "name": "t3_abc123"}}]
                    }
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True


class TestDeleteOperation:
    @pytest.mark.asyncio
    async def test_delete_success(self, mock_credentials, mock_httpx_response):
        """Test deleting content."""
        config = RedditDeleteConfig(thing_id="t3_abc123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["deleted"] is True


class TestSaveOperation:
    @pytest.mark.asyncio
    async def test_save_success(self, mock_credentials, mock_httpx_response):
        """Test saving content."""
        config = RedditSaveConfig(thing_id="t3_abc123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "saved"

    @pytest.mark.asyncio
    async def test_unsave_success(self, mock_credentials, mock_httpx_response):
        """Test unsaving content."""
        config = RedditSaveConfig(thing_id="t3_abc123", unsave=True)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "unsaved"


# ============================================================================
# Flair Operations Tests
# ============================================================================


class TestGetLinkFlairOperation:
    @pytest.mark.asyncio
    async def test_get_link_flair_success(self, mock_credentials, mock_httpx_response):
        """Test getting link flair options."""
        config = RedditGetLinkFlairConfig(subreddit="python")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            [
                {"id": "flair1", "text": "Question"},
                {"id": "flair2", "text": "Discussion"},
            ],
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "flairs" in result
        assert result["count"] == 2
        assert result["subreddit"] == "python"


class TestSetLinkFlairOperation:
    @pytest.mark.asyncio
    async def test_set_link_flair_success(self, mock_credentials, mock_httpx_response):
        """Test setting link flair."""
        config = RedditSetLinkFlairConfig(
            thing_id="t3_abc123", flair_template_id="flair1", text="Question"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True


# ============================================================================
# Search Tests
# ============================================================================


class TestSearchOperation:
    @pytest.mark.asyncio
    async def test_search_success(self, mock_credentials, mock_httpx_response):
        """Test searching Reddit."""
        config = RedditSearchConfig(query="python tutorial", limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"id": "result1", "title": "Python Tutorial"}},
                        {"data": {"id": "result2", "title": "Learn Python"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "results" in result
        assert result["count"] == 2
        assert result["query"] == "python tutorial"

    @pytest.mark.asyncio
    async def test_search_in_subreddit_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test searching within a subreddit."""
        config = RedditSearchConfig(query="help", subreddit="python", limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"id": "result1", "title": "Need help"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "results" in result
        assert result["count"] == 1


# ============================================================================
# Multireddit Operations Tests
# ============================================================================


class TestGetMultiredditOperation:
    @pytest.mark.asyncio
    async def test_get_multireddit_success(self, mock_credentials, mock_httpx_response):
        """Test getting a multireddit."""
        config = RedditGetMultiredditConfig(
            username="test_user", multiname="programming"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "name": "programming",
                    "display_name": "programming",
                    "subreddits": [{"name": "python"}, {"name": "javascript"}],
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "multireddit" in result


class TestGetMyMultiredditsOperation:
    @pytest.mark.asyncio
    async def test_get_my_multireddits_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting user's multireddits."""
        config = RedditGetMyMultiredditsConfig()
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            [
                {"data": {"name": "multi1", "display_name": "Multi 1"}},
                {"data": {"name": "multi2", "display_name": "Multi 2"}},
            ],
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "multireddits" in result
        assert result["count"] == 2


class TestGetMultiredditPostsOperation:
    @pytest.mark.asyncio
    async def test_get_multireddit_posts_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting posts from a multireddit."""
        config = RedditGetMultiredditPostsConfig(
            username="test_user", multiname="programming", sort="hot", limit=10
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"id": "post1", "title": "Multi Post 1"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "posts" in result
        assert result["count"] == 1


# ============================================================================
# Message Operations Tests
# ============================================================================


class TestSendMessageOperation:
    @pytest.mark.asyncio
    async def test_send_message_success(self, mock_credentials, mock_httpx_response):
        """Test sending a private message."""
        config = RedditSendMessageConfig(
            to="other_user", subject="Hello", text="How are you?"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {"json": {"errors": []}})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["to"] == "other_user"


class TestGetInboxOperation:
    @pytest.mark.asyncio
    async def test_get_inbox_success(self, mock_credentials, mock_httpx_response):
        """Test getting inbox messages."""
        config = RedditGetInboxConfig(where="inbox", limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"id": "msg1", "subject": "Message 1"}},
                        {"data": {"id": "msg2", "subject": "Message 2"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "messages" in result
        assert result["count"] == 2


class TestMarkMessagesReadOperation:
    @pytest.mark.asyncio
    async def test_mark_messages_read_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test marking messages as read."""
        config = RedditMarkMessagesReadConfig(thing_ids="t4_msg1,t4_msg2")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert len(result["marked_read"]) == 2


class TestDeleteMessageOperation:
    @pytest.mark.asyncio
    async def test_delete_message_success(self, mock_credentials, mock_httpx_response):
        """Test deleting a message."""
        config = RedditDeleteMessageConfig(thing_id="t4_msg1")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["deleted"] == "t4_msg1"


class TestReplyMessageOperation:
    @pytest.mark.asyncio
    async def test_reply_message_success(self, mock_credentials, mock_httpx_response):
        """Test replying to a message."""
        config = RedditReplyMessageConfig(
            thing_id="t4_msg1", text="Thanks for the message!"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "json": {
                    "data": {
                        "things": [{"data": {"id": "reply123", "name": "t4_reply123"}}]
                    }
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True


# ============================================================================
# Award Operations Tests
# ============================================================================


class TestGiveAwardOperation:
    @pytest.mark.asyncio
    async def test_give_award_success(self, mock_credentials, mock_httpx_response):
        """Test giving an award."""
        config = RedditGiveAwardConfig(thing_id="t3_abc123", gild_type="gid_2")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["award_type"] == "gid_2"


# ============================================================================
# Additional User Operations Tests
# ============================================================================


class TestGetKarmaOperation:
    @pytest.mark.asyncio
    async def test_get_karma_success(self, mock_credentials, mock_httpx_response):
        """Test getting karma breakdown."""
        config = RedditGetKarmaConfig()
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": [
                    {"sr": "python", "link_karma": 100, "comment_karma": 50},
                    {"sr": "programming", "link_karma": 200, "comment_karma": 100},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "karma" in result
        assert result["count"] == 2


class TestGetPreferencesOperation:
    @pytest.mark.asyncio
    async def test_get_preferences_success(self, mock_credentials, mock_httpx_response):
        """Test getting user preferences."""
        config = RedditGetPreferencesConfig()
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "over_18": False,
                "email_messages": True,
                "lang": "en",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "preferences" in result


class TestCheckUsernameOperation:
    @pytest.mark.asyncio
    async def test_check_username_success(self, mock_credentials, mock_httpx_response):
        """Test checking username availability."""
        config = RedditCheckUsernameConfig(username="new_user_123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, True)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["username"] == "new_user_123"
        assert "available" in result


class TestReportUserOperation:
    @pytest.mark.asyncio
    async def test_report_user_success(self, mock_credentials, mock_httpx_response):
        """Test reporting a user."""
        config = RedditReportUserConfig(username="bad_user", reason="spam")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["reported"] == "bad_user"


# ============================================================================
# Additional Subreddit Operations Tests
# ============================================================================


class TestGetSubredditModeratorsOperation:
    @pytest.mark.asyncio
    async def test_get_subreddit_moderators_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting subreddit moderators."""
        config = RedditGetSubredditModeratorsConfig(subreddit="python")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"name": "mod1"},
                        {"name": "mod2"},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "moderators" in result
        assert result["count"] == 2


class TestGetRandomSubredditOperation:
    @pytest.mark.asyncio
    async def test_get_random_subreddit_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting a random subreddit."""
        config = RedditGetRandomSubredditConfig()
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            [
                {
                    "data": {
                        "children": [
                            {"data": {"subreddit": "randomsub", "id": "post1"}}
                        ]
                    }
                }
            ],
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "subreddit" in result
        assert "posts" in result


class TestGetPopularSubredditsOperation:
    @pytest.mark.asyncio
    async def test_get_popular_subreddits_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting popular subreddits."""
        config = RedditGetPopularSubredditsConfig(limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"display_name": "AskReddit"}},
                        {"data": {"display_name": "funny"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "subreddits" in result
        assert result["count"] == 2


class TestGetNewSubredditsOperation:
    @pytest.mark.asyncio
    async def test_get_new_subreddits_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting new subreddits."""
        config = RedditGetNewSubredditsConfig(limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"display_name": "newsub1"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "subreddits" in result
        assert result["count"] == 1


class TestGetSubredditCommentsOperation:
    @pytest.mark.asyncio
    async def test_get_subreddit_comments_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting subreddit comments."""
        config = RedditGetSubredditCommentsConfig(subreddit="python", limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"id": "c1", "body": "Comment 1"}},
                        {"data": {"id": "c2", "body": "Comment 2"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "comments" in result
        assert result["count"] == 2
        assert result["subreddit"] == "python"

# ============================================================================
# Post Moderation Operations Tests
# ============================================================================


class TestMarkNsfwOperation:
    @pytest.mark.asyncio
    async def test_mark_nsfw_success(self, mock_credentials, mock_httpx_response):
        """Test marking a post as NSFW."""
        config = RedditMarkNsfwConfig(thing_id="t3_abc123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "marked_nsfw"

    @pytest.mark.asyncio
    async def test_unmark_nsfw_success(self, mock_credentials, mock_httpx_response):
        """Test unmarking a post as NSFW."""
        config = RedditMarkNsfwConfig(thing_id="t3_abc123", unmark=True)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "unmarked_nsfw"


class TestMarkSpoilerOperation:
    @pytest.mark.asyncio
    async def test_mark_spoiler_success(self, mock_credentials, mock_httpx_response):
        """Test marking a post as spoiler."""
        config = RedditMarkSpoilerConfig(thing_id="t3_abc123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "marked_spoiler"


class TestGetRandomSubmissionOperation:
    @pytest.mark.asyncio
    async def test_get_random_submission_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting a random submission."""
        config = RedditGetRandomSubmissionConfig(subreddit="python")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            [
                {
                    "data": {
                        "children": [
                            {"data": {"id": "random123", "title": "Random Post"}}
                        ]
                    }
                }
            ],
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "post" in result


# ============================================================================
# User Flair Operations Tests
# ============================================================================


class TestGetUserFlairOperation:
    @pytest.mark.asyncio
    async def test_get_user_flair_success(self, mock_credentials, mock_httpx_response):
        """Test getting user flair options."""
        config = RedditGetUserFlairConfig(subreddit="python")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            [
                {"id": "flair1", "text": "Beginner"},
                {"id": "flair2", "text": "Expert"},
            ],
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "flairs" in result
        assert result["count"] == 2


class TestSetUserFlairOperation:
    @pytest.mark.asyncio
    async def test_set_user_flair_success(self, mock_credentials, mock_httpx_response):
        """Test setting user flair."""
        config = RedditSetUserFlairConfig(
            subreddit="python", flair_template_id="flair1", text="Python Dev"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["subreddit"] == "python"


# ============================================================================
# Listings/Feeds Operations Tests
# ============================================================================


class TestGetBestOperation:
    @pytest.mark.asyncio
    async def test_get_best_success(self, mock_credentials, mock_httpx_response):
        """Test getting best posts."""
        config = RedditGetBestConfig(limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"id": "best1", "title": "Best Post 1"}},
                        {"data": {"id": "best2", "title": "Best Post 2"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "posts" in result
        assert result["count"] == 2


class TestGetGildedOperation:
    @pytest.mark.asyncio
    async def test_get_gilded_success(self, mock_credentials, mock_httpx_response):
        """Test getting gilded content."""
        config = RedditGetGildedConfig(subreddit="python", limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"id": "gilded1", "title": "Gilded Post"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "items" in result
        assert result["count"] == 1


# ============================================================================
# Additional Message Operations Tests
# ============================================================================


class TestMarkAllMessagesReadOperation:
    @pytest.mark.asyncio
    async def test_mark_all_messages_read_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test marking all messages as read."""
        config = RedditMarkAllMessagesReadConfig()
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "marked_all_read"


class TestUnreadMessageOperation:
    @pytest.mark.asyncio
    async def test_unread_message_success(self, mock_credentials, mock_httpx_response):
        """Test marking messages as unread."""
        config = RedditUnreadMessageConfig(thing_ids="t4_msg1,t4_msg2")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert len(result["marked_unread"]) == 2


# ============================================================================
# Wiki Operations Tests
# ============================================================================


class TestGetWikiPagesOperation:
    @pytest.mark.asyncio
    async def test_get_wiki_pages_success(self, mock_credentials, mock_httpx_response):
        """Test listing wiki pages."""
        config = RedditGetWikiPagesConfig(subreddit="python")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {"data": ["index", "faq", "rules"]})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "pages" in result
        assert result["count"] == 3


class TestGetWikiPageOperation:
    @pytest.mark.asyncio
    async def test_get_wiki_page_success(self, mock_credentials, mock_httpx_response):
        """Test getting a wiki page."""
        config = RedditGetWikiPageConfig(subreddit="python", page="faq")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "content_md": "# FAQ\n\nFrequently asked questions",
                    "content_html": "<h1>FAQ</h1>",
                    "revision_by": {"data": {"name": "mod1"}},
                    "revision_date": 1609459200,
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "content" in result
        assert result["page"] == "faq"


class TestGetWikiRevisionsOperation:
    @pytest.mark.asyncio
    async def test_get_wiki_revisions_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting wiki revisions."""
        config = RedditGetWikiRevisionsConfig(subreddit="python", page="faq", limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"id": "rev1", "author": "mod1"}},
                        {"data": {"id": "rev2", "author": "mod2"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "revisions" in result
        assert result["count"] == 2


# ============================================================================
# Live Thread Operations Tests
# ============================================================================


class TestCreateLiveThreadOperation:
    @pytest.mark.asyncio
    async def test_create_live_thread_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test creating a live thread."""
        config = RedditCreateLiveThreadConfig(
            title="Breaking News", description="Live updates"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {"json": {"data": {"id": "live123"}}})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["id"] == "live123"


class TestGetLiveThreadOperation:
    @pytest.mark.asyncio
    async def test_get_live_thread_success(self, mock_credentials, mock_httpx_response):
        """Test getting live thread info."""
        config = RedditGetLiveThreadConfig(thread_id="live123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"data": {"id": "live123", "title": "Breaking News", "state": "live"}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "thread" in result


class TestGetLiveThreadUpdatesOperation:
    @pytest.mark.asyncio
    async def test_get_live_thread_updates_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting live thread updates."""
        config = RedditGetLiveThreadUpdatesConfig(thread_id="live123", limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"id": "update1", "body": "First update"}},
                        {"data": {"id": "update2", "body": "Second update"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "updates" in result
        assert result["count"] == 2


class TestUpdateLiveThreadOperation:
    @pytest.mark.asyncio
    async def test_update_live_thread_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test posting an update to a live thread."""
        config = RedditUpdateLiveThreadConfig(thread_id="live123", body="New update!")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"json": {"data": {"name": "update456"}}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["thread_id"] == "live123"


class TestCloseLiveThreadOperation:
    @pytest.mark.asyncio
    async def test_close_live_thread_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test closing a live thread."""
        config = RedditCloseLiveThreadConfig(thread_id="live123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "closed"


# ============================================================================
# Additional Multireddit Operations Tests
# ============================================================================


class TestCreateMultiredditOperation:
    @pytest.mark.asyncio
    async def test_create_multireddit_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test creating a multireddit."""
        config = RedditCreateMultiredditConfig(
            name="programming",
            subreddits="python,javascript,golang",
            visibility="private",
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"data": {"name": "programming", "display_name": "programming"}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["name"] == "programming"


class TestDeleteMultiredditOperation:
    @pytest.mark.asyncio
    async def test_delete_multireddit_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test deleting a multireddit."""
        config = RedditDeleteMultiredditConfig(multiname="programming")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["deleted"] == "programming"


class TestUpdateMultiredditOperation:
    @pytest.mark.asyncio
    async def test_update_multireddit_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test updating a multireddit."""
        config = RedditUpdateMultiredditConfig(
            multiname="programming",
            description="Updated description",
            visibility="public",
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {"data": {"name": "programming"}})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True


class TestAddSubredditToMultiOperation:
    @pytest.mark.asyncio
    async def test_add_subreddit_to_multi_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test adding a subreddit to a multireddit."""
        config = RedditAddSubredditToMultiConfig(
            multiname="programming", subreddit="rust"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["added"] == "rust"


class TestRemoveSubredditFromMultiOperation:
    @pytest.mark.asyncio
    async def test_remove_subreddit_from_multi_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test removing a subreddit from a multireddit."""
        config = RedditRemoveSubredditFromMultiConfig(
            multiname="programming", subreddit="rust"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["removed"] == "rust"


# ============================================================================
# Additional API Operations Tests
# ============================================================================


class TestGetInfoOperation:
    @pytest.mark.asyncio
    async def test_get_info_success(self, mock_credentials, mock_httpx_response):
        """Test getting info about things by fullname."""
        config = RedditGetInfoConfig(ids="t3_abc123,t1_def456")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"id": "abc123", "name": "t3_abc123"}},
                        {"data": {"id": "def456", "name": "t1_def456"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "items" in result
        assert result["count"] == 2


class TestGetMoreCommentsOperation:
    @pytest.mark.asyncio
    async def test_get_more_comments_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test loading more comments."""
        config = RedditGetMoreCommentsConfig(
            link_id="t3_abc123", children="comment1,comment2"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "json": {
                    "data": {
                        "things": [
                            {"kind": "t1", "data": {"id": "comment1"}},
                            {"kind": "t1", "data": {"id": "comment2"}},
                        ]
                    }
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "comments" in result
        assert result["count"] == 2


class TestLockOperation:
    @pytest.mark.asyncio
    async def test_lock_success(self, mock_credentials, mock_httpx_response):
        """Test locking a post."""
        config = RedditLockConfig(thing_id="t3_abc123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "locked"

    @pytest.mark.asyncio
    async def test_unlock_success(self, mock_credentials, mock_httpx_response):
        """Test unlocking a post."""
        config = RedditLockConfig(thing_id="t3_abc123", unlock=True)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "unlocked"


class TestApproveOperation:
    @pytest.mark.asyncio
    async def test_approve_success(self, mock_credentials, mock_httpx_response):
        """Test approving a post."""
        config = RedditApproveConfig(thing_id="t3_abc123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "approved"


class TestRemoveOperation:
    @pytest.mark.asyncio
    async def test_remove_success(self, mock_credentials, mock_httpx_response):
        """Test removing a post."""
        config = RedditRemoveConfig(thing_id="t3_abc123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "removed"


class TestDistinguishOperation:
    @pytest.mark.asyncio
    async def test_distinguish_success(self, mock_credentials, mock_httpx_response):
        """Test distinguishing a comment as mod."""
        config = RedditDistinguishConfig(thing_id="t1_abc123", how="yes")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["how"] == "yes"


class TestStickyPostOperation:
    @pytest.mark.asyncio
    async def test_sticky_post_success(self, mock_credentials, mock_httpx_response):
        """Test stickying a post."""
        config = RedditStickyPostConfig(thing_id="t3_abc123", state=True, num=1)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "stickied"


class TestSetContestModeOperation:
    @pytest.mark.asyncio
    async def test_set_contest_mode_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test setting contest mode."""
        config = RedditSetContestModeConfig(thing_id="t3_abc123", state=True)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["contest_mode"] is True


class TestSetSuggestedSortOperation:
    @pytest.mark.asyncio
    async def test_set_suggested_sort_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test setting suggested sort."""
        config = RedditSetSuggestedSortConfig(thing_id="t3_abc123", sort="top")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["suggested_sort"] == "top"


class TestSendRepliesOperation:
    @pytest.mark.asyncio
    async def test_send_replies_success(self, mock_credentials, mock_httpx_response):
        """Test toggling inbox replies."""
        config = RedditSendRepliesConfig(thing_id="t3_abc123", state=False)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["send_replies"] is False


class TestGetDefaultSubredditsOperation:
    @pytest.mark.asyncio
    async def test_get_default_subreddits_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting default subreddits."""
        config = RedditGetDefaultSubredditsConfig(limit=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"data": {"display_name": "announcements"}},
                        {"data": {"display_name": "funny"}},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "subreddits" in result
        assert result["count"] == 2


class TestGetBlockedUsersOperation:
    @pytest.mark.asyncio
    async def test_get_blocked_users_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting blocked users."""
        config = RedditGetBlockedUsersConfig()
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "data": {
                    "children": [
                        {"name": "blocked_user1"},
                        {"name": "blocked_user2"},
                    ]
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "blocked_users" in result
        assert result["count"] == 2


class TestUnblockUserOperation:
    @pytest.mark.asyncio
    async def test_unblock_user_success(self, mock_credentials, mock_httpx_response):
        """Test unblocking a user."""
        config = RedditUnblockUserConfig(username="blocked_user")
        node = create_node(config, mock_credentials)

        # First call gets user info, second call unblocks
        mock_user_response = mock_httpx_response(200, {"data": {"id": "abc123"}})
        mock_unblock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                side_effect=[mock_user_response, mock_unblock_response]
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["unblocked"] == "blocked_user"


class TestGetSubredditTrafficOperation:
    @pytest.mark.asyncio
    async def test_get_subreddit_traffic_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test getting subreddit traffic."""
        config = RedditGetSubredditTrafficConfig(subreddit="python")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "day": [[1609459200, 100, 50]],
                "hour": [[1609459200, 10, 5]],
                "month": [[1609459200, 3000, 1500]],
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert "day" in result
        assert "hour" in result
        assert "month" in result
        assert result["subreddit"] == "python"


class TestIgnoreReportsOperation:
    @pytest.mark.asyncio
    async def test_ignore_reports_success(self, mock_credentials, mock_httpx_response):
        """Test ignoring reports on a post."""
        config = RedditIgnoreReportsConfig(thing_id="t3_abc123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "ignored_reports"

    @pytest.mark.asyncio
    async def test_unignore_reports_success(
        self, mock_credentials, mock_httpx_response
    ):
        """Test unignoring reports on a post."""
        config = RedditIgnoreReportsConfig(thing_id="t3_abc123", unignore=True)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

        assert result["success"] is True
        assert result["action"] == "unignored_reports"


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_missing_credentials(self, mock_httpx_response):
        """Test error when credentials are missing."""
        config = RedditGetMeConfig()
        node_config = RedditNodeConfig(config=config, credentials=None)
        node = RedditNode(
            node_id="test_reddit_node",
            node_type="automation-reddit",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )
        node.emit = AsyncMock()

        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_api_error(self, mock_credentials, mock_httpx_response):
        """Test handling of API errors."""
        config = RedditGetMeConfig()
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            401, {"error": "unauthorized"}, "Unauthorized"
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )
            with pytest.raises(ValueError, match="Reddit API error"):
                await node.execute({})


# ============================================================================
# Schema Tests
# ============================================================================


class TestSchemaGeneration:
    def test_config_schema_generated(self):
        """Test that config schema can be generated."""
        schema = RedditNodeConfig.model_json_schema()
        assert "$defs" in schema
        assert len(schema["$defs"]) >= 83  # All config types

    def test_all_operations_in_schema(self):
        """Test that all operations are in the schema."""
        schema = RedditNodeConfig.model_json_schema()
        defs = schema.get("$defs", {})

        expected_configs = [
            # User operations (12)
            "RedditGetMeConfig",
            "RedditGetUserConfig",
            "RedditGetUserPostsConfig",
            "RedditGetUserCommentsConfig",
            "RedditGetUserSavedConfig",
            "RedditGetTrophiesConfig",
            "RedditBlockUserConfig",
            "RedditGetFriendsConfig",
            "RedditGetKarmaConfig",
            "RedditGetPreferencesConfig",
            "RedditCheckUsernameConfig",
            "RedditReportUserConfig",
            # Subreddit operations (11)
            "RedditGetSubredditPostsConfig",
            "RedditGetSubredditInfoConfig",
            "RedditGetSubredditRulesConfig",
            "RedditGetMySubredditsConfig",
            "RedditSubscribeConfig",
            "RedditSearchSubredditsConfig",
            "RedditGetSubredditModeratorsConfig",
            "RedditGetRandomSubredditConfig",
            "RedditGetPopularSubredditsConfig",
            "RedditGetNewSubredditsConfig",
            "RedditGetSubredditCommentsConfig",
            # Post operations (11)
            "RedditGetPostConfig",
            "RedditGetPostCommentsConfig",
            "RedditGetDuplicatesConfig",
            "RedditSubmitTextPostConfig",
            "RedditSubmitLinkPostConfig",
            "RedditCrosspostConfig",
            "RedditHideConfig",
            "RedditReportConfig",
            "RedditMarkNsfwConfig",
            "RedditMarkSpoilerConfig",
            "RedditGetRandomSubmissionConfig",
            # Comment operations (1)
            "RedditSubmitCommentConfig",
            # Common actions (4)
            "RedditVoteConfig",
            "RedditEditConfig",
            "RedditDeleteConfig",
            "RedditSaveConfig",
            # Flair operations (4)
            "RedditGetLinkFlairConfig",
            "RedditSetLinkFlairConfig",
            "RedditGetUserFlairConfig",
            "RedditSetUserFlairConfig",
            # Listings/Feeds (2)
            "RedditGetBestConfig",
            "RedditGetGildedConfig",
            # Search (1)
            "RedditSearchConfig",
            # Multireddits (8)
            "RedditGetMultiredditConfig",
            "RedditGetMyMultiredditsConfig",
            "RedditGetMultiredditPostsConfig",
            "RedditCreateMultiredditConfig",
            "RedditDeleteMultiredditConfig",
            "RedditUpdateMultiredditConfig",
            "RedditAddSubredditToMultiConfig",
            "RedditRemoveSubredditFromMultiConfig",
            # Messages (7)
            "RedditSendMessageConfig",
            "RedditGetInboxConfig",
            "RedditMarkMessagesReadConfig",
            "RedditDeleteMessageConfig",
            "RedditReplyMessageConfig",
            "RedditMarkAllMessagesReadConfig",
            "RedditUnreadMessageConfig",
            # Wiki (3)
            "RedditGetWikiPagesConfig",
            "RedditGetWikiPageConfig",
            "RedditGetWikiRevisionsConfig",
            # Live Threads (5)
            "RedditCreateLiveThreadConfig",
            "RedditGetLiveThreadConfig",
            "RedditGetLiveThreadUpdatesConfig",
            "RedditUpdateLiveThreadConfig",
            "RedditCloseLiveThreadConfig",
            # Awards (1)
            "RedditGiveAwardConfig",
            # Additional API operations (15)
            "RedditGetInfoConfig",
            "RedditGetMoreCommentsConfig",
            "RedditLockConfig",
            "RedditApproveConfig",
            "RedditRemoveConfig",
            "RedditDistinguishConfig",
            "RedditStickyPostConfig",
            "RedditSetContestModeConfig",
            "RedditSetSuggestedSortConfig",
            "RedditSendRepliesConfig",
            "RedditGetDefaultSubredditsConfig",
            "RedditGetBlockedUsersConfig",
            "RedditUnblockUserConfig",
            "RedditGetSubredditTrafficConfig",
            "RedditIgnoreReportsConfig",
        ]

        for config_name in expected_configs:
            assert config_name in defs, f"Missing {config_name} in schema"


# ============================================================================
# Script Credential Tests
# ============================================================================


class TestScriptCredentials:
    """Tests for Reddit Script (user-provided) credentials."""

    @pytest.fixture
    def mock_script_credentials(self):
        """Create mock Script credentials."""
        return RedditScriptCredential(
            client_id="test_client_id",
            client_secret="test_client_secret",
            username="test_user",
            password="test_password",
        )

    def create_node_with_script_creds(self, config, credentials):
        """Helper to create a Reddit node with script credentials."""
        node_config = RedditNodeConfig(config=config, credentials=credentials)
        node = RedditNode(
            node_id="test_reddit_node",
            node_type="automation-reddit",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )
        node.emit = AsyncMock()
        # The production cache is process-global; isolate every test without
        # replacing it with an un-expiring plain dict.
        RedditNode._script_token_cache.clear()
        return node

    @pytest.mark.asyncio
    async def test_script_credential_token_fetch(
        self, mock_script_credentials, mock_httpx_response
    ):
        """Test that script credentials fetch an access token."""
        config = RedditGetMeConfig()
        node = self.create_node_with_script_creds(config, mock_script_credentials)

        # Mock token response
        mock_token_response = MagicMock()
        mock_token_response.status_code = 200
        mock_token_response.json.return_value = {
            "access_token": "fetched_token",
            "token_type": "bearer",
        }

        # Mock API response
        mock_api_response = mock_httpx_response(
            200,
            {
                "name": "test_user",
                "id": "abc123",
                "link_karma": 1000,
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            # First call is token fetch, second is API call
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_token_response
            )
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_api_response
            )
            result = await node.execute({})

        assert "user" in result
        assert result["user"]["name"] == "test_user"

    @pytest.mark.asyncio
    async def test_script_credential_token_caching(
        self, mock_script_credentials, mock_httpx_response
    ):
        """Exact script credentials reuse a token without exposing raw secrets."""
        config = RedditGetMeConfig()
        node = self.create_node_with_script_creds(config, mock_script_credentials)

        mock_token_response = MagicMock()
        mock_token_response.status_code = 200
        mock_token_response.json.return_value = {
            "access_token": "cached_token",
        }
        refreshed_token_response = MagicMock()
        refreshed_token_response.status_code = 200
        refreshed_token_response.json.return_value = {
            "access_token": "fallback-expiry-refreshed-token",
        }

        mock_api_response = mock_httpx_response(
            200,
            {
                "name": "test_user",
                "id": "abc123",
            },
        )

        now = [1000.0]
        with patch("httpx.AsyncClient") as mock_client, patch(
            "nodes.reddit_node.time.monotonic", side_effect=lambda: now[0]
        ):
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_api_response
            )
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=[mock_token_response, refreshed_token_response]
            )
            first = await node.execute({})
            second = await node.execute({})
            now[0] = 1240.0
            third = await node.execute({})

        assert "user" in first
        assert "user" in second
        assert "user" in third
        assert mock_client.return_value.__aenter__.return_value.post.await_count == 2
        cache_key = next(iter(RedditNode._script_token_cache.keys()))
        assert len(cache_key) == 64
        assert mock_script_credentials.client_secret not in cache_key
        assert mock_script_credentials.password not in cache_key

    @pytest.mark.parametrize("changed_secret", ["client_secret", "password"])
    @pytest.mark.asyncio
    async def test_same_public_script_fields_with_different_secret_do_not_share_token(
        self, mock_script_credentials, changed_secret
    ):
        config = RedditGetMeConfig()
        node = self.create_node_with_script_creds(config, mock_script_credentials)
        other_credentials = mock_script_credentials.model_copy(
            update={changed_secret: f"different-{changed_secret}"}
        )
        first_response = MagicMock(status_code=200)
        first_response.json.return_value = {
            "access_token": "first-token",
            "expires_in": 3600,
        }
        second_response = MagicMock(status_code=200)
        second_response.json.return_value = {
            "access_token": "second-token",
            "expires_in": 3600,
        }

        with patch("httpx.AsyncClient") as mock_client, patch(
            "nodes.reddit_node.time.monotonic", return_value=1000.0
        ):
            post = AsyncMock(side_effect=[first_response, second_response])
            mock_client.return_value.__aenter__.return_value.post = post

            first = await node._fetch_script_token(mock_script_credentials)
            second = await node._fetch_script_token(other_credentials)

        assert first == "first-token"
        assert second == "second-token"
        assert post.await_count == 2

    @pytest.mark.asyncio
    async def test_expired_script_token_is_refreshed(self, mock_script_credentials):
        config = RedditGetMeConfig()
        node = self.create_node_with_script_creds(config, mock_script_credentials)
        first_response = MagicMock(status_code=200)
        first_response.json.return_value = {
            "access_token": "short-token",
            "expires_in": 120,
        }
        second_response = MagicMock(status_code=200)
        second_response.json.return_value = {
            "access_token": "refreshed-token",
            "expires_in": 120,
        }
        now = [1000.0]

        with patch("httpx.AsyncClient") as mock_client, patch(
            "nodes.reddit_node.time.monotonic", side_effect=lambda: now[0]
        ):
            post = AsyncMock(side_effect=[first_response, second_response])
            mock_client.return_value.__aenter__.return_value.post = post

            first = await node._fetch_script_token(mock_script_credentials)
            now[0] = 1060.0
            second = await node._fetch_script_token(mock_script_credentials)

        assert first == "short-token"
        assert second == "refreshed-token"
        assert post.await_count == 2

    @pytest.mark.asyncio
    async def test_script_credential_auth_failure(self, mock_script_credentials):
        """Test error handling when script credential authentication fails."""
        config = RedditGetMeConfig()
        node = self.create_node_with_script_creds(config, mock_script_credentials)

        # Mock failed token response
        mock_token_response = MagicMock()
        mock_token_response.status_code = 401
        mock_token_response.text = "Invalid credentials"

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_token_response
            )
            with pytest.raises(ValueError, match="Failed to authenticate with Reddit"):
                await node.execute({})

    def test_script_credential_model(self):
        """Test Script credential model validation."""
        cred = RedditScriptCredential(
            client_id="my_client_id",
            client_secret="my_secret",
            username="myuser",
            password="mypassword",
        )
        assert cred.credential_type == "reddit_script"
        assert cred.client_id == "my_client_id"
        assert cred.client_secret == "my_secret"
        assert cred.username == "myuser"
        assert cred.password == "mypassword"

    def test_oauth_credential_model(self):
        """Test OAuth credential model has credential_type field."""
        cred = RedditOAuthCredential(
            access_token="token",
            refresh_token="refresh",
            expires_at="2099-12-31T23:59:59Z",
            username="user",
        )
        assert cred.credential_type == "reddit_oauth"
        assert cred.access_token == "token"

    def test_schema_includes_both_credential_types(self):
        """Test that schema includes both OAuth and Script credentials."""
        schema = RedditNodeConfig.model_json_schema()
        defs = schema.get("$defs", {})

        # Both credential types should be in schema
        assert (
            "RedditOAuthCredential" in defs
        ), "Missing RedditOAuthCredential in schema"
        assert (
            "RedditScriptCredential" in defs
        ), "Missing RedditScriptCredential in schema"

        # Script credential should have required fields
        script_cred = defs["RedditScriptCredential"]
        script_props = script_cred.get("properties", {})
        assert "client_id" in script_props
        assert "client_secret" in script_props
        assert "username" in script_props
        assert "password" in script_props
