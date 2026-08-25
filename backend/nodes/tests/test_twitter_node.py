"""
Mock unit tests for Twitter/X REST API v2 node.

Run: pytest backend/nodes/tests/test_twitter_node.py

No real API calls — all HTTP requests are mocked. Safe to run without credentials.
"""

import httpx
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from nodes.twitter_node import (
    TwitterNode,
    TwitterNodeConfig,
    TwitterOAuthCredential,
    TwitterBearerTokenCredential,
    TwitterCreateTweetConfig,
    TwitterDeleteTweetConfig,
    TwitterGetTweetConfig,
    TwitterSearchRecentTweetsConfig,
    TwitterGetMeConfig,
    TwitterGetTweetCountsRecentConfig,
    TwitterGetRetweetsConfig,
    TwitterGetUsersByUsernamesConfig,
    TwitterGetStreamRulesConfig,
    TwitterAddStreamRulesConfig,
    TwitterDeleteStreamRulesConfig,
    TwitterGetTrendsByWOEIDConfig,
    TwitterSearchNewsConfig,
    TwitterGetUsageConfig,
    TwitterSearchCommunitiesConfig,
    TwitterListComplianceJobsConfig,
    # Tweet extras
    TwitterSearchAllTweetsConfig,
    TwitterGetTweetCountsAllConfig,
    TwitterGetTweetAnalyticsConfig,
    # User extras
    TwitterSearchUsersConfig,
    # DM extras
    TwitterDeleteDMEventConfig,
    TwitterGetDMEventConfig,
    TwitterBlockDMsConfig,
    TwitterUnblockDMsConfig,
    # List extras
    TwitterGetListFollowersConfig,
    TwitterGetFollowedListsConfig,
    TwitterFollowListConfig,
    TwitterUnfollowListConfig,
    # Space extras
    TwitterSearchSpacesConfig,
    TwitterGetSpaceTweetsConfig,
    TwitterGetSpaceBuyersConfig,
    # Bookmark extras
    TwitterGetBookmarkFoldersConfig,
    # Media extras
    TwitterGetMediaUploadStatusConfig,
    TwitterCreateMediaMetadataConfig,
    TwitterCreateMediaSubtitlesConfig,
    TwitterDeleteMediaSubtitlesConfig,
    TwitterGetMediaAnalyticsConfig,
    # Streams
    TwitterGetFilteredStreamConfig,
    TwitterGetStreamRuleCountsConfig,
    TwitterGetSampledStreamConfig,
    TwitterGetSampled10StreamConfig,
    # Trends/News
    TwitterGetPersonalizedTrendsConfig,
    TwitterGetNewsByIdConfig,
    # Communities
    TwitterGetCommunityConfig,
    # Community Notes
    TwitterCreateNoteConfig,
    TwitterDeleteNoteConfig,
    TwitterEvaluateNoteConfig,
    TwitterGetNotesWrittenConfig,
    TwitterGetPostsEligibleForNotesConfig,
    # Compliance
    TwitterCreateComplianceJobConfig,
    TwitterGetComplianceJobConfig,
    # Webhooks
    TwitterCreateWebhookConfig,
    TwitterDeleteWebhookConfig,
    TwitterGetWebhookConfig,
    TwitterValidateWebhookConfig,
    TwitterCreateStreamLinkConfig,
    TwitterDeleteStreamLinkConfig,
    TwitterGetStreamLinksConfig,
    TwitterCreateWebhookReplayConfig,
    # Account Activity
    TwitterCreateSubscriptionConfig,
    TwitterDeleteSubscriptionConfig,
    TwitterGetSubscriptionsConfig,
    TwitterGetSubscriptionCountConfig,
    TwitterValidateSubscriptionConfig,
    TwitterCreateSubscriptionReplayConfig,
    # Connections
    TwitterGetConnectionsConfig,
    TwitterTerminateAllConnectionsConfig,
    TwitterTerminateConnectionsByEndpointConfig,
    TwitterTerminateConnectionConfig,
)


# ============================================================================
# Pytest Mock Tests — Run with: pytest nodes/tests/test_twitter_node.py
# ============================================================================


def make_mock_oauth() -> TwitterOAuthCredential:
    return TwitterOAuthCredential(
        access_token="mock-token-oauth", user_id="mock-user-id"
    )


def make_mock_bearer() -> TwitterBearerTokenCredential:
    return TwitterBearerTokenCredential(bearer_token="mock-bearer")


def make_node(config, credentials) -> TwitterNode:
    node_config = TwitterNodeConfig(config=config, credentials=credentials)
    return TwitterNode(
        node_id="test",
        node_type="automation-twitter",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test",
    )


def mock_success_response(data: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = b"content"
    resp.json.return_value = data
    resp.headers = {}
    return resp


@pytest.fixture
def oauth_cred():
    return make_mock_oauth()


@pytest.fixture
def bearer_cred():
    return make_mock_bearer()


@pytest.mark.asyncio
class TestTwitterNodeMock:
    """Unit tests using mocked HTTP responses — no real API calls."""

    async def _run(
        self, config, credentials, response_data: dict, status_code: int = 200
    ):
        node = make_node(config, credentials)
        mock_resp = mock_success_response(response_data, status_code)
        with patch(
            "httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp
        ):
            return await node.execute({})

    # ── Tweets ───────────────────────────────────────────────────────────────

    async def test_mock_create_tweet(self, oauth_cred):
        result = await self._run(
            TwitterCreateTweetConfig(text="Hello world"),
            oauth_cred,
            {"data": {"id": "123", "text": "Hello world"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_tweet"

    async def test_mock_search_recent_tweets(self, bearer_cred):
        result = await self._run(
            TwitterSearchRecentTweetsConfig(query="python"),
            bearer_cred,
            {
                "data": [{"id": "1", "text": "python is great"}],
                "meta": {"result_count": 1},
            },
        )
        assert result["status"] == "success"
        assert result["data"]["meta"]["result_count"] == 1

    async def test_mock_get_tweet_counts_recent(self, bearer_cred):
        result = await self._run(
            TwitterGetTweetCountsRecentConfig(query="python", granularity="day"),
            bearer_cred,
            {
                "data": [
                    {
                        "start": "2024-01-01T00:00:00Z",
                        "end": "2024-01-02T00:00:00Z",
                        "tweet_count": 42,
                    }
                ],
                "meta": {"total_tweet_count": 42},
            },
        )
        assert result["status"] == "success"
        assert result["action"] == "get_tweet_counts_recent"

    async def test_mock_get_retweets(self, bearer_cred):
        result = await self._run(
            TwitterGetRetweetsConfig(tweet_id="20", max_results=5),
            bearer_cred,
            {"data": [{"id": "99", "text": "RT @jack first tweet"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_tweet_retweets"

    async def test_mock_get_users_by_usernames(self, bearer_cred):
        result = await self._run(
            TwitterGetUsersByUsernamesConfig(usernames="twitter,x"),
            bearer_cred,
            {"data": [{"id": "783214", "username": "Twitter"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_users_by_usernames"

    # ── Streams ──────────────────────────────────────────────────────────────

    async def test_mock_get_stream_rules(self, bearer_cred):
        result = await self._run(
            TwitterGetStreamRulesConfig(),
            bearer_cred,
            {"data": [{"id": "rule-1", "value": "python lang:en", "tag": "py"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_stream_filter_rules"

    async def test_mock_add_stream_rules(self, bearer_cred):
        result = await self._run(
            TwitterAddStreamRulesConfig(rules="python lang:en", tags="py-tag"),
            bearer_cred,
            {"data": [{"id": "rule-1", "value": "python lang:en", "tag": "py-tag"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "add_stream_filter_rules"

    async def test_mock_delete_stream_rules(self, bearer_cred):
        result = await self._run(
            TwitterDeleteStreamRulesConfig(rule_ids="rule-1,rule-2"),
            bearer_cred,
            {"meta": {"summary": {"deleted": 2, "not_deleted": 0}}},
        )
        assert result["status"] == "success"
        assert result["action"] == "delete_stream_filter_rules"

    # ── Trends ───────────────────────────────────────────────────────────────

    async def test_mock_get_trends_by_woeid(self, bearer_cred):
        result = await self._run(
            TwitterGetTrendsByWOEIDConfig(woeid="1"),
            bearer_cred,
            {"data": [{"trend_name": "#Python", "tweet_count": 10000}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_trending_topics_by_woeid"

    # ── News ─────────────────────────────────────────────────────────────────

    async def test_mock_search_news(self, bearer_cred):
        result = await self._run(
            TwitterSearchNewsConfig(query="AI", max_results=5),
            bearer_cred,
            {"data": [{"id": "news-1", "title": "AI is transforming tech"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "search_news_articles"

    # ── Usage ─────────────────────────────────────────────────────────────────

    async def test_mock_get_usage(self, bearer_cred):
        result = await self._run(
            TwitterGetUsageConfig(days=7),
            bearer_cred,
            {
                "data": {
                    "cap_reset_day": 1,
                    "daily_project_usage": [],
                    "project_cap": 500000,
                }
            },
        )
        assert result["status"] == "success"
        assert result["action"] == "get_api_usage"

    # ── Communities ──────────────────────────────────────────────────────────

    async def test_mock_search_communities(self, bearer_cred):
        result = await self._run(
            TwitterSearchCommunitiesConfig(query="developers"),
            bearer_cred,
            {"data": [{"id": "comm-1", "name": "Python Developers"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "search_communities"

    # ── Compliance ───────────────────────────────────────────────────────────

    async def test_mock_list_compliance_jobs(self, bearer_cred):
        result = await self._run(
            TwitterListComplianceJobsConfig(),
            bearer_cred,
            {"data": [{"id": "job-1", "type": "tweets", "status": "complete"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_compliance_jobs"

    # ── Error Handling ────────────────────────────────────────────────────────

    async def test_mock_api_error_returns_error_status(self, bearer_cred):
        """API errors should return status='error', not raise."""
        node = make_node(TwitterSearchRecentTweetsConfig(query="test"), bearer_cred)
        mock_resp = mock_success_response({"errors": [{"message": "Forbidden"}]}, 403)
        with patch(
            "httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await node.execute({})
        assert result["status"] == "error"
        assert "Forbidden" in result["error"]

    async def test_mock_user_resource_flag_no_markup_on_custom_creds(self):
        """Custom client_id credentials should be user_resource=True."""
        cred = TwitterOAuthCredential(
            access_token="tok", client_id="my-client-id", client_secret="my-secret"
        )
        node = make_node(TwitterCreateTweetConfig(text="test"), cred)
        assert node._is_user_resource(cred) is True

    async def test_mock_noclick_oauth_is_platform_resource(self):
        """No custom client_id → user_resource=False (NoClick pays X)."""
        cred = TwitterOAuthCredential(access_token="tok")
        node = make_node(TwitterCreateTweetConfig(text="test"), cred)
        assert node._is_user_resource(cred) is False

    async def test_mock_bearer_is_user_resource(self):
        """Bearer token always counts as user_resource=True."""
        cred = TwitterBearerTokenCredential(bearer_token="bearer")
        node = make_node(TwitterGetTweetConfig(tweet_id="20"), cred)
        assert node._is_user_resource(cred) is True

    # ── Billing Operation Inference ───────────────────────────────────────────

    async def test_infer_post_create(self, oauth_cred):
        node = make_node(TwitterCreateTweetConfig(text="x"), oauth_cred)
        assert node._infer_x_operation("POST", "/tweets") == "post_create"

    async def test_infer_post_read_search(self, bearer_cred):
        node = make_node(TwitterSearchRecentTweetsConfig(query="x"), bearer_cred)
        assert node._infer_x_operation("GET", "/tweets/search/recent") == "post_read"

    async def test_infer_user_lookup(self, bearer_cred):
        node = make_node(TwitterGetMeConfig(), bearer_cred)
        assert node._infer_x_operation("GET", "/users/me") == "user_lookup"

    async def test_infer_user_interaction_like(self, oauth_cred):
        node = make_node(TwitterCreateTweetConfig(text="x"), oauth_cred)
        assert node._infer_x_operation("POST", "/users/123/likes") == "user_interaction"

    async def test_infer_dm_create(self, oauth_cred):
        node = make_node(TwitterCreateTweetConfig(text="x"), oauth_cred)
        assert (
            node._infer_x_operation("POST", "/dm_conversations/with/123/messages")
            == "dm_create"
        )

    async def test_infer_delete_not_billed(self, oauth_cred):
        node = make_node(TwitterDeleteTweetConfig(tweet_id="1"), oauth_cred)
        assert node._infer_x_operation("DELETE", "/tweets/1") is None

    async def test_count_resources_post_create_always_1(self, oauth_cred):
        node = make_node(TwitterCreateTweetConfig(text="x"), oauth_cred)
        assert node._count_x_resources("post_create", {"data": {"id": "1"}}) == 1

    async def test_count_resources_list_response(self, bearer_cred):
        node = make_node(TwitterSearchRecentTweetsConfig(query="x"), bearer_cred)
        assert (
            node._count_x_resources("post_read", {"data": [{"id": "1"}, {"id": "2"}]})
            == 2
        )

    async def test_count_resources_empty_list(self, bearer_cred):
        node = make_node(TwitterSearchRecentTweetsConfig(query="x"), bearer_cred)
        assert node._count_x_resources("post_read", {"data": []}) == 0

    # ── Stream helper ─────────────────────────────────────────────────────────

    async def _run_stream(self, config, credentials, lines=None):
        """Mock httpx streaming for filtered/sampled stream endpoints."""

        async def fake_aiter_lines():
            for line in lines or ['{"data": {"id": "1", "text": "stream tweet"}}']:
                yield line

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.aiter_lines = fake_aiter_lines

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_resp
        mock_cm.__aexit__.return_value = None

        node = make_node(config, credentials)
        with patch.object(httpx.AsyncClient, "stream", return_value=mock_cm):
            return await node.execute({})

    # ── Tweet extras ──────────────────────────────────────────────────────────

    async def test_mock_search_all_tweets(self, bearer_cred):
        result = await self._run(
            TwitterSearchAllTweetsConfig(query="python"),
            bearer_cred,
            {"data": [{"id": "1", "text": "python"}], "meta": {"result_count": 1}},
        )
        assert result["status"] == "success"
        assert result["action"] == "search_all_tweets_full_archive"

    async def test_mock_get_tweet_counts_all(self, bearer_cred):
        result = await self._run(
            TwitterGetTweetCountsAllConfig(query="python"),
            bearer_cred,
            {"data": [{"tweet_count": 100}], "meta": {"total_tweet_count": 100}},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_tweet_counts_full_archive"

    async def test_mock_get_tweet_analytics(self, bearer_cred):
        result = await self._run(
            TwitterGetTweetAnalyticsConfig(tweet_ids="123,456"),
            bearer_cred,
            {"data": [{"id": "123", "impression_count": 500}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_tweet_analytics"

    # ── User extras ───────────────────────────────────────────────────────────

    async def test_mock_search_users(self, bearer_cred):
        result = await self._run(
            TwitterSearchUsersConfig(query="python developers"),
            bearer_cred,
            {"data": [{"id": "1", "username": "pythondev"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "search_users"

    # ── DM extras ────────────────────────────────────────────────────────────

    async def test_mock_get_dm_event(self, oauth_cred):
        result = await self._run(
            TwitterGetDMEventConfig(event_id="ev-1"),
            oauth_cred,
            {"data": {"id": "ev-1", "event_type": "MessageCreate"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_direct_message_event_by_id"

    async def test_mock_delete_dm_event(self, oauth_cred):
        result = await self._run(
            TwitterDeleteDMEventConfig(event_id="ev-1"),
            oauth_cred,
            {"data": {"deleted": True}},
        )
        assert result["status"] == "success"
        assert result["action"] == "delete_direct_message_event"

    async def test_mock_block_dms(self, oauth_cred):
        result = await self._run(
            TwitterBlockDMsConfig(target_user_id="99"),
            oauth_cred,
            {"data": {"blocking": True}},
        )
        assert result["status"] == "success"
        assert result["action"] == "block_user_dms"

    async def test_mock_unblock_dms(self, oauth_cred):
        result = await self._run(
            TwitterUnblockDMsConfig(target_user_id="99"),
            oauth_cred,
            {"data": {"blocking": False}},
        )
        assert result["status"] == "success"
        assert result["action"] == "unblock_user_dms"

    # ── List extras ───────────────────────────────────────────────────────────

    async def test_mock_get_list_followers(self, bearer_cred):
        result = await self._run(
            TwitterGetListFollowersConfig(list_id="list-1"),
            bearer_cred,
            {"data": [{"id": "1", "username": "follower"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_list_followers"

    async def test_mock_get_followed_lists(self, bearer_cred):
        result = await self._run(
            TwitterGetFollowedListsConfig(user_id="u-1"),
            bearer_cred,
            {"data": [{"id": "list-1", "name": "My List"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_lists_followed_by_user"

    async def test_mock_follow_list(self, oauth_cred):
        result = await self._run(
            TwitterFollowListConfig(list_id="list-1"),
            oauth_cred,
            {"data": {"following": True}},
        )
        assert result["status"] == "success"
        assert result["action"] == "follow_list"

    async def test_mock_unfollow_list(self, oauth_cred):
        result = await self._run(
            TwitterUnfollowListConfig(list_id="list-1"),
            oauth_cred,
            {"data": {"following": False}},
        )
        assert result["status"] == "success"
        assert result["action"] == "unfollow_list"

    # ── Space extras ──────────────────────────────────────────────────────────

    async def test_mock_search_spaces(self, bearer_cred):
        result = await self._run(
            TwitterSearchSpacesConfig(query="AI"),
            bearer_cred,
            {"data": [{"id": "sp-1", "title": "AI Discussion"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "search_spaces"

    async def test_mock_get_space_tweets(self, bearer_cred):
        result = await self._run(
            TwitterGetSpaceTweetsConfig(space_id="sp-1"),
            bearer_cred,
            {"data": [{"id": "t-1", "text": "great space!"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_tweets_from_space"

    async def test_mock_get_space_buyers(self, bearer_cred):
        result = await self._run(
            TwitterGetSpaceBuyersConfig(space_id="sp-1"),
            bearer_cred,
            {"data": [{"id": "u-1", "username": "buyer"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_space_ticket_holders"

    # ── Bookmark extras ───────────────────────────────────────────────────────

    async def test_mock_get_bookmark_folders(self, oauth_cred):
        result = await self._run(
            TwitterGetBookmarkFoldersConfig(),
            oauth_cred,
            {"data": [{"id": "folder-1", "name": "Tech"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_bookmark_folders"

    # ── Media extras ──────────────────────────────────────────────────────────

    async def test_mock_get_media_upload_status(self, oauth_cred):
        result = await self._run(
            TwitterGetMediaUploadStatusConfig(media_id="m-1"),
            oauth_cred,
            {"processing_info": {"state": "succeeded", "progress_percent": 100}},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_media_upload_status"

    async def test_mock_create_media_metadata(self, oauth_cred):
        result = await self._run(
            TwitterCreateMediaMetadataConfig(media_id="m-1"), oauth_cred, {}
        )
        assert result["status"] == "success"
        assert result["action"] == "create_media_metadata"

    async def test_mock_create_media_subtitles(self, oauth_cred):
        result = await self._run(
            TwitterCreateMediaSubtitlesConfig(
                media_id="m-1",
                subtitle_data="WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello",
                language_code="en",
            ),
            oauth_cred,
            {"data": {"media_id": "m-1"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_media_subtitles"

    async def test_mock_delete_media_subtitles(self, oauth_cred):
        result = await self._run(
            TwitterDeleteMediaSubtitlesConfig(media_id="m-1", language_code="en"),
            oauth_cred,
            {},
        )
        assert result["status"] == "success"
        assert result["action"] == "delete_media_subtitles"

    async def test_mock_get_media_analytics(self, bearer_cred):
        result = await self._run(
            TwitterGetMediaAnalyticsConfig(media_keys="mk-1,mk-2"),
            bearer_cred,
            {"data": [{"media_key": "mk-1", "view_count": 1000}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_media_analytics"

    # ── Streams ───────────────────────────────────────────────────────────────

    async def test_mock_get_filtered_stream(self, bearer_cred):
        result = await self._run_stream(TwitterGetFilteredStreamConfig(), bearer_cred)
        assert result["status"] == "success"
        assert result["action"] == "collect_filtered_stream_tweets"
        assert result["data"]["meta"]["result_count"] == 1

    async def test_mock_get_stream_rule_counts(self, bearer_cred):
        result = await self._run(
            TwitterGetStreamRuleCountsConfig(),
            bearer_cred,
            {"data": {"rule_count": 5, "cap": 25}},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_stream_rule_counts"

    async def test_mock_get_sampled_stream(self, bearer_cred):
        result = await self._run_stream(TwitterGetSampledStreamConfig(), bearer_cred)
        assert result["status"] == "success"
        assert result["action"] == "collect_sampled_stream_tweets"

    async def test_mock_get_sampled10_stream(self, bearer_cred):
        result = await self._run_stream(
            TwitterGetSampled10StreamConfig(partition=1), bearer_cred
        )
        assert result["status"] == "success"
        assert result["action"] == "collect_10_percent_sampled_stream_tweets"

    # ── Trends / News ─────────────────────────────────────────────────────────

    async def test_mock_get_personalized_trends(self, oauth_cred):
        result = await self._run(
            TwitterGetPersonalizedTrendsConfig(),
            oauth_cred,
            {"data": [{"trend_name": "#AI", "tweet_count": 50000}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_personalized_trending_topics"

    async def test_mock_get_news_by_id(self, bearer_cred):
        result = await self._run(
            TwitterGetNewsByIdConfig(news_id="news-1"),
            bearer_cred,
            {"data": {"id": "news-1", "title": "AI breakthrough"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_news_article_by_id"

    # ── Communities ───────────────────────────────────────────────────────────

    async def test_mock_get_community(self, bearer_cred):
        result = await self._run(
            TwitterGetCommunityConfig(community_id="c-1"),
            bearer_cred,
            {"data": {"id": "c-1", "name": "Python Devs"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_community_by_id"

    # ── Community Notes ───────────────────────────────────────────────────────

    async def test_mock_create_note(self, oauth_cred):
        result = await self._run(
            TwitterCreateNoteConfig(
                tweet_id="t-1", note_text="This tweet contains misinformation."
            ),
            oauth_cred,
            {"data": {"id": "note-1", "tweet_id": "t-1"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_community_note_on_tweet"

    async def test_mock_delete_note(self, oauth_cred):
        result = await self._run(
            TwitterDeleteNoteConfig(note_id="note-1"),
            oauth_cred,
            {"data": {"deleted": True}},
        )
        assert result["status"] == "success"
        assert result["action"] == "delete_community_note"

    async def test_mock_evaluate_note(self, oauth_cred):
        result = await self._run(
            TwitterEvaluateNoteConfig(note_id="note-1"),
            oauth_cred,
            {"data": {"note_id": "note-1", "classification": "helpful"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "evaluate_community_note"

    async def test_mock_get_notes_written(self, oauth_cred):
        result = await self._run(
            TwitterGetNotesWrittenConfig(),
            oauth_cred,
            {"data": [{"id": "note-1", "tweet_id": "t-1"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_community_notes_written"

    async def test_mock_get_posts_eligible_for_notes(self, bearer_cred):
        result = await self._run(
            TwitterGetPostsEligibleForNotesConfig(),
            bearer_cred,
            {"data": [{"id": "t-1", "text": "eligible tweet"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_posts_eligible_for_community_notes"

    # ── Compliance ────────────────────────────────────────────────────────────

    async def test_mock_create_compliance_job(self, bearer_cred):
        result = await self._run(
            TwitterCreateComplianceJobConfig(type="tweets"),
            bearer_cred,
            {"data": {"id": "job-1", "type": "tweets", "status": "created"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_compliance_job"

    async def test_mock_get_compliance_job(self, bearer_cred):
        result = await self._run(
            TwitterGetComplianceJobConfig(job_id="job-1"),
            bearer_cred,
            {"data": {"id": "job-1", "type": "tweets", "status": "complete"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_compliance_job_by_id"

    # ── Webhooks ──────────────────────────────────────────────────────────────

    async def test_mock_create_webhook(self, oauth_cred):
        result = await self._run(
            TwitterCreateWebhookConfig(url="https://example.com/webhook"),
            oauth_cred,
            {"data": {"id": "wh-1", "url": "https://example.com/webhook"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_webhook"

    async def test_mock_delete_webhook(self, oauth_cred):
        result = await self._run(
            TwitterDeleteWebhookConfig(webhook_id="wh-1"), oauth_cred, {}
        )
        assert result["status"] == "success"
        assert result["action"] == "delete_webhook"

    async def test_mock_get_webhook(self, oauth_cred):
        result = await self._run(
            TwitterGetWebhookConfig(webhook_id="wh-1"),
            oauth_cred,
            {"data": {"id": "wh-1", "url": "https://example.com/webhook"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_webhook_by_id"

    async def test_mock_validate_webhook(self, oauth_cred):
        result = await self._run(
            TwitterValidateWebhookConfig(webhook_id="wh-1"),
            oauth_cred,
            {"data": {"valid": True}},
        )
        assert result["status"] == "success"
        assert result["action"] == "validate_webhook"

    async def test_mock_create_stream_link(self, oauth_cred):
        result = await self._run(
            TwitterCreateStreamLinkConfig(webhook_id="wh-1"),
            oauth_cred,
            {"data": {"id": "sl-1", "webhook_id": "wh-1"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_webhook_stream_link"

    async def test_mock_delete_stream_link(self, oauth_cred):
        result = await self._run(
            TwitterDeleteStreamLinkConfig(webhook_id="wh-1", stream_link_id="sl-1"),
            oauth_cred,
            {},
        )
        assert result["status"] == "success"
        assert result["action"] == "delete_webhook_stream_link"

    async def test_mock_get_stream_links(self, oauth_cred):
        result = await self._run(
            TwitterGetStreamLinksConfig(webhook_id="wh-1"),
            oauth_cred,
            {"data": [{"id": "sl-1", "webhook_id": "wh-1"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_webhook_stream_links"

    async def test_mock_create_webhook_replay(self, oauth_cred):
        result = await self._run(
            TwitterCreateWebhookReplayConfig(webhook_id="wh-1"),
            oauth_cred,
            {"data": {"id": "replay-1"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_webhook_replay"

    # ── Account Activity Subscriptions ────────────────────────────────────────

    async def test_mock_create_subscription(self, oauth_cred):
        result = await self._run(
            TwitterCreateSubscriptionConfig(webhook_id="wh-1"), oauth_cred, {}
        )
        assert result["status"] == "success"
        assert result["action"] == "create_account_activity_subscription"

    async def test_mock_delete_subscription(self, oauth_cred):
        result = await self._run(
            TwitterDeleteSubscriptionConfig(webhook_id="wh-1"), oauth_cred, {}
        )
        assert result["status"] == "success"
        assert result["action"] == "delete_account_activity_subscription"

    async def test_mock_get_subscriptions(self, oauth_cred):
        result = await self._run(
            TwitterGetSubscriptionsConfig(webhook_id="wh-1"),
            oauth_cred,
            {"data": [{"id": "sub-1"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_account_activity_subscriptions"

    async def test_mock_get_subscription_count(self, bearer_cred):
        result = await self._run(
            TwitterGetSubscriptionCountConfig(),
            bearer_cred,
            {
                "data": {
                    "subscriptions_count_all": 10,
                    "subscriptions_count_direct_messages": 5,
                }
            },
        )
        assert result["status"] == "success"
        assert result["action"] == "get_account_activity_subscription_count"

    async def test_mock_validate_subscription(self, oauth_cred):
        result = await self._run(
            TwitterValidateSubscriptionConfig(), oauth_cred, {"data": {"valid": True}}
        )
        assert result["status"] == "success"
        assert result["action"] == "validate_account_activity_subscription"

    async def test_mock_create_subscription_replay(self, oauth_cred):
        result = await self._run(
            TwitterCreateSubscriptionReplayConfig(webhook_id="wh-1"),
            oauth_cred,
            {"data": {"id": "replay-sub-1"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_account_activity_subscription_replay"

    # ── Connections ───────────────────────────────────────────────────────────

    async def test_mock_get_connections(self, bearer_cred):
        result = await self._run(
            TwitterGetConnectionsConfig(),
            bearer_cred,
            {"data": [{"id": "conn-1", "endpoint": "/tweets/search/stream"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_all_streaming_connections"

    async def test_mock_terminate_all_connections(self, bearer_cred):
        result = await self._run(
            TwitterTerminateAllConnectionsConfig(),
            bearer_cred,
            {"data": {"terminated_count": 3}},
        )
        assert result["status"] == "success"
        assert result["action"] == "terminate_all_streaming_connections"

    async def test_mock_terminate_connections_by_endpoint(self, bearer_cred):
        result = await self._run(
            TwitterTerminateConnectionsByEndpointConfig(
                endpoint_type="filtered_stream"
            ),
            bearer_cred,
            {"data": {"terminated_count": 1}},
        )
        assert result["status"] == "success"
        assert result["action"] == "terminate_streaming_connections_by_endpoint_type"

    async def test_mock_terminate_connection(self, bearer_cred):
        result = await self._run(
            TwitterTerminateConnectionConfig(connection_id="conn-1"),
            bearer_cred,
            {"data": {"terminated": True}},
        )
        assert result["status"] == "success"
        assert result["action"] == "terminate_streaming_connection"


# ============================================================================
# Token Refresh Tests
# ============================================================================

from datetime import datetime, timedelta, timezone
from nodes.oauth.twitter_oauth import TwitterTokenResponse
import nodes.twitter_node as twitter_node_module


def _make_expires_at(minutes_from_now: int) -> str:
    """Create an ISO 8601 timestamp relative to now."""
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)
    return dt.isoformat().replace("+00:00", "Z")


def _make_oauth_with_expiry(
    expires_in_minutes: int, **kwargs
) -> TwitterOAuthCredential:
    """Create OAuth credential with a specific expiry time."""
    return TwitterOAuthCredential(
        access_token="old-token",
        refresh_token="refresh-tok",
        expires_at=_make_expires_at(expires_in_minutes),
        user_id="uid-123",
        **kwargs,
    )


def _make_node_with_data(config, credentials, node_data=None) -> TwitterNode:
    """Create a node with custom node_data (for credential_id etc.)."""
    node_config = TwitterNodeConfig(config=config, credentials=credentials)
    return TwitterNode(
        node_id="test",
        node_type="automation-twitter",
        node_data=node_data or {},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test",
    )


@pytest.mark.asyncio
class TestTokenAutoRefresh:
    """Tests for the P0 auto-refresh mechanism in _get_access_token."""

    async def test_bearer_token_returned_immediately(self):
        """Bearer tokens bypass all refresh logic."""
        cred = TwitterBearerTokenCredential(bearer_token="my-bearer")
        node = _make_node_with_data(TwitterGetMeConfig(), cred)
        token = await node._get_access_token(cred)
        assert token == "my-bearer"

    async def test_valid_oauth_token_returned_without_refresh(self):
        """Non-expired OAuth token is returned without calling refresh."""
        cred = _make_oauth_with_expiry(60)  # expires in 60 min
        node = _make_node_with_data(TwitterGetMeConfig(), cred)
        with patch(
            "nodes.twitter_node.refresh_access_token", new_callable=AsyncMock
        ) as mock_refresh:
            token = await node._get_access_token(cred)
        assert token == "old-token"
        mock_refresh.assert_not_called()

    async def test_expired_token_triggers_refresh(self):
        """Expired token triggers refresh and returns new token."""
        cred = _make_oauth_with_expiry(-10)  # expired 10 min ago
        node = _make_node_with_data(TwitterGetMeConfig(), cred)

        new_tokens = TwitterTokenResponse(
            access_token="new-token",
            token_type="bearer",
            expires_in=7200,
            expires_at=_make_expires_at(120),
            refresh_token="new-refresh",
            scope="tweet.read",
        )

        with patch(
            "nodes.twitter_node.refresh_access_token",
            new_callable=AsyncMock,
            return_value=new_tokens,
        ) as mock_refresh, patch(
            "nodes.twitter_node.update_credential_data",
            new_callable=AsyncMock,
            return_value=True,
        ):
            token = await node._get_access_token(cred)

        assert token == "new-token"
        mock_refresh.assert_called_once_with(
            "refresh-tok",
            client_id=None,
            client_secret=None,
        )

    async def test_expiring_soon_triggers_refresh(self):
        """Token expiring within 5 min buffer triggers refresh."""
        cred = _make_oauth_with_expiry(3)  # expires in 3 min (within 5 min buffer)
        node = _make_node_with_data(TwitterGetMeConfig(), cred)

        new_tokens = TwitterTokenResponse(
            access_token="refreshed-token",
            token_type="bearer",
            expires_in=7200,
            expires_at=_make_expires_at(120),
            refresh_token="refreshed-refresh",
        )

        with patch(
            "nodes.twitter_node.refresh_access_token",
            new_callable=AsyncMock,
            return_value=new_tokens,
        ) as mock_refresh, patch(
            "nodes.twitter_node.update_credential_data",
            new_callable=AsyncMock,
            return_value=True,
        ):
            token = await node._get_access_token(cred)

        assert token == "refreshed-token"
        mock_refresh.assert_called_once()

    async def test_no_refresh_token_raises(self):
        """An expired token with no refresh_token raises rather than returning
        a stale token that would 401 — refresh now routes through the shared
        ensure_fresh_oauth_token helper."""
        cred = TwitterOAuthCredential(
            access_token="expired-tok",
            refresh_token=None,
            expires_at=_make_expires_at(-10),
        )
        node = _make_node_with_data(TwitterGetMeConfig(), cred)

        with pytest.raises(ValueError, match="no refresh token"):
            await node._get_access_token(cred)

    async def test_no_expires_at_returns_token_immediately(self):
        """If expires_at is None, return token without checking refresh."""
        cred = TwitterOAuthCredential(access_token="tok-no-expiry", expires_at=None)
        node = _make_node_with_data(TwitterGetMeConfig(), cred)

        with patch(
            "nodes.twitter_node.refresh_access_token", new_callable=AsyncMock
        ) as mock_refresh:
            token = await node._get_access_token(cred)

        assert token == "tok-no-expiry"
        mock_refresh.assert_not_called()

    async def test_refresh_failure_raises_value_error(self):
        """If refresh fails, raise ValueError (not silently return old token)."""
        cred = _make_oauth_with_expiry(-10)
        node = _make_node_with_data(TwitterGetMeConfig(), cred)

        with patch(
            "nodes.twitter_node.refresh_access_token",
            new_callable=AsyncMock,
            side_effect=ValueError("invalid_grant"),
        ):
            with pytest.raises(ValueError, match="refresh failed"):
                await node._get_access_token(cred)

    async def test_custom_client_credentials_passed_to_refresh(self):
        """Custom client_id/secret are forwarded to refresh_access_token."""
        cred = _make_oauth_with_expiry(
            -10, client_id="custom-id", client_secret="custom-secret"
        )
        node = _make_node_with_data(TwitterGetMeConfig(), cred)

        new_tokens = TwitterTokenResponse(
            access_token="new-token",
            token_type="bearer",
            expires_in=7200,
            expires_at=_make_expires_at(120),
            refresh_token="new-refresh",
        )

        with patch(
            "nodes.twitter_node.refresh_access_token",
            new_callable=AsyncMock,
            return_value=new_tokens,
        ) as mock_refresh, patch(
            "nodes.twitter_node.update_credential_data",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await node._get_access_token(cred)

        mock_refresh.assert_called_once_with(
            "refresh-tok",
            client_id="custom-id",
            client_secret="custom-secret",
        )

    async def test_refreshed_tokens_persisted_to_db(self):
        """After refresh, update_credential_data is called with new tokens."""
        cred = _make_oauth_with_expiry(-10)
        node = _make_node_with_data(
            TwitterGetMeConfig(),
            cred,
            node_data={"credential_id": "cred-uuid-123"},
        )
        node.user_id = "user-uuid-456"

        new_expires_at = _make_expires_at(120)
        new_tokens = TwitterTokenResponse(
            access_token="persisted-token",
            token_type="bearer",
            expires_in=7200,
            expires_at=new_expires_at,
            refresh_token="persisted-refresh",
        )

        with patch(
            "nodes.twitter_node.refresh_access_token",
            new_callable=AsyncMock,
            return_value=new_tokens,
        ), patch(
            "utils.credential_loader.load_credential",
            new_callable=AsyncMock,
            return_value={
                "access_token": "old-token",
                "refresh_token": "refresh-tok",
                "expires_at": _make_expires_at(-10),
            },
        ), patch(
            "utils.credentials.update_credential_data_detailed",
            new_callable=AsyncMock,
            return_value=(1, None),
        ) as mock_update:
            token = await node._get_access_token(cred)

        assert token == "persisted-token"
        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args
        assert call_kwargs[1]["credential_id"] == "cred-uuid-123"
        assert call_kwargs[1]["user_id"] == "user-uuid-456"
        assert call_kwargs[1]["new_data"]["access_token"] == "persisted-token"
        assert call_kwargs[1]["new_data"]["refresh_token"] == "persisted-refresh"
        assert "last_refreshed_at" in call_kwargs[1]["metadata_updates"]

    async def test_in_memory_credentials_updated_after_refresh(self):
        """After refresh, the in-memory credential object is updated."""
        cred = _make_oauth_with_expiry(-10)
        node = _make_node_with_data(TwitterGetMeConfig(), cred)

        new_tokens = TwitterTokenResponse(
            access_token="memory-token",
            token_type="bearer",
            expires_in=7200,
            expires_at=_make_expires_at(120),
            refresh_token="memory-refresh",
        )

        with patch(
            "nodes.twitter_node.refresh_access_token",
            new_callable=AsyncMock,
            return_value=new_tokens,
        ), patch(
            "nodes.twitter_node.update_credential_data",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await node._get_access_token(cred)

        assert cred.access_token == "memory-token"
        assert cred.refresh_token == "memory-refresh"
        assert cred.expires_at == new_tokens.expires_at

    async def test_skips_refresh_when_db_already_fresh(self):
        """Concurrency safety: refresh routes through the shared
        ensure_fresh_oauth_token helper, which re-reads the credential under a
        per-credential lock. If the DB already holds a fresh token (another run
        refreshed), the node adopts it without issuing a second refresh — which
        matters because Twitter rotates refresh tokens."""
        cred = _make_oauth_with_expiry(-10)
        node = _make_node_with_data(
            TwitterGetMeConfig(),
            cred,
            node_data={"credential_id": "cred-x"},
        )
        node.user_id = "user-x"

        with patch(
            "nodes.twitter_node.refresh_access_token", new_callable=AsyncMock
        ) as mock_refresh, patch(
            "utils.credential_loader.load_credential",
            new_callable=AsyncMock,
            return_value={
                "access_token": "db-fresh-token",
                "refresh_token": "db-refresh",
                "expires_at": _make_expires_at(120),
            },
        ):
            token = await node._get_access_token(cred)

        assert token == "db-fresh-token"
        mock_refresh.assert_not_called()

    async def test_db_persist_failure_still_returns_token(self):
        """If DB persist fails, token is still returned (logged as warning)."""
        cred = _make_oauth_with_expiry(-10)
        node = _make_node_with_data(
            TwitterGetMeConfig(),
            cred,
            node_data={"credential_id": "persist-fail"},
        )

        new_tokens = TwitterTokenResponse(
            access_token="good-token",
            token_type="bearer",
            expires_in=7200,
            expires_at=_make_expires_at(120),
            refresh_token="new-refresh",
        )

        with patch(
            "nodes.twitter_node.refresh_access_token",
            new_callable=AsyncMock,
            return_value=new_tokens,
        ), patch(
            "nodes.twitter_node.update_credential_data",
            new_callable=AsyncMock,
            return_value=False,
        ):
            token = await node._get_access_token(cred)

        assert token == "good-token"

    async def test_end_to_end_make_request_with_refresh(self):
        """Full flow: _make_request with expired token triggers refresh, then API call succeeds."""
        cred = _make_oauth_with_expiry(-10)
        node = _make_node_with_data(
            TwitterGetMeConfig(),
            cred,
            node_data={"credential_id": "e2e-cred"},
        )

        new_tokens = TwitterTokenResponse(
            access_token="e2e-fresh-token",
            token_type="bearer",
            expires_in=7200,
            expires_at=_make_expires_at(120),
            refresh_token="e2e-fresh-refresh",
        )

        mock_resp = mock_success_response({"data": {"id": "123", "username": "test"}})

        with patch(
            "nodes.twitter_node.refresh_access_token",
            new_callable=AsyncMock,
            return_value=new_tokens,
        ), patch(
            "nodes.twitter_node.update_credential_data",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_req:
            result = await node._make_request(
                "GET", "/users/me", cred, action_name="get_authenticated_user"
            )

        assert result["status"] == "success"
        # Verify the API call used the refreshed token
        call_kwargs = mock_req.call_args
        assert "e2e-fresh-token" in call_kwargs[1]["headers"]["Authorization"]


# ============================================================================
# Twitter OAuth Utility Tests
# ============================================================================

from nodes.oauth.twitter_oauth import (
    exchange_code_for_tokens,
    refresh_access_token as oauth_refresh_access_token,
    revoke_token,
    is_token_expired,
    calculate_expires_at,
)


@pytest.mark.asyncio
class TestTwitterOAuthUtils:
    """Tests for the twitter_oauth.py utility functions."""

    async def test_exchange_client_id_in_body(self):
        """Token exchange must send client_id in the POST body — required for X PKCE flows."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"ok"
        mock_resp.json.return_value = {
            "access_token": "tok",
            "token_type": "bearer",
            "expires_in": 7200,
            "refresh_token": "ref",
        }

        user_info_resp = MagicMock()
        user_info_resp.status_code = 200
        user_info_resp.json.return_value = {
            "data": {"id": "1", "name": "Test", "username": "test"}
        }

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_post, patch(
            "httpx.AsyncClient.get", new_callable=AsyncMock, return_value=user_info_resp
        ), patch(
            "nodes.oauth.twitter_oauth.TWITTER_CLIENT_ID", "cid"
        ), patch(
            "nodes.oauth.twitter_oauth.TWITTER_CLIENT_SECRET", "csec"
        ):
            await exchange_code_for_tokens("code", "https://redir", "verifier")

        post_kwargs = mock_post.call_args
        body_data = post_kwargs[1]["data"]
        assert body_data["client_id"] == "cid"
        assert body_data["grant_type"] == "authorization_code"
        assert body_data["code_verifier"] == "verifier"
        assert post_kwargs[1]["auth"] == ("cid", "csec")

    async def test_refresh_client_id_in_body(self):
        """Token refresh must send client_id in the POST body — required for X PKCE flows."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"ok"
        mock_resp.json.return_value = {
            "access_token": "new",
            "token_type": "bearer",
            "expires_in": 7200,
            "refresh_token": "new-ref",
        }

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_post, patch(
            "nodes.oauth.twitter_oauth.TWITTER_CLIENT_ID", "cid"
        ), patch(
            "nodes.oauth.twitter_oauth.TWITTER_CLIENT_SECRET", "csec"
        ):
            await oauth_refresh_access_token("old-refresh")

        body_data = mock_post.call_args[1]["data"]
        assert body_data["client_id"] == "cid"
        assert body_data["grant_type"] == "refresh_token"
        assert body_data["refresh_token"] == "old-refresh"
        assert mock_post.call_args[1]["auth"] == ("cid", "csec")

    async def test_refresh_with_custom_credentials(self):
        """Custom client_id/secret override env defaults."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"ok"
        mock_resp.json.return_value = {
            "access_token": "new",
            "token_type": "bearer",
            "expires_in": 7200,
            "refresh_token": "new-ref",
        }

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_post:
            await oauth_refresh_access_token(
                "ref-tok", client_id="my-cid", client_secret="my-csec"
            )

        body_data = mock_post.call_args[1]["data"]
        assert body_data["client_id"] == "my-cid"
        assert mock_post.call_args[1]["auth"] == ("my-cid", "my-csec")

    async def test_revoke_client_id_in_body(self):
        """Token revocation must send client_id in the POST body."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_post, patch(
            "nodes.oauth.twitter_oauth.TWITTER_CLIENT_ID", "cid"
        ), patch(
            "nodes.oauth.twitter_oauth.TWITTER_CLIENT_SECRET", "csec"
        ):
            await revoke_token("tok-to-revoke", token_type_hint="refresh_token")

        body_data = mock_post.call_args[1]["data"]
        assert body_data["client_id"] == "cid"
        assert body_data["token"] == "tok-to-revoke"
        assert mock_post.call_args[1]["auth"] == ("cid", "csec")

    def test_is_token_expired_future(self):
        """Token expiring far in the future is not expired."""
        assert not is_token_expired(_make_expires_at(60))

    def test_is_token_expired_past(self):
        """Token in the past is expired."""
        assert is_token_expired(_make_expires_at(-10))

    def test_is_token_expired_within_buffer(self):
        """Token expiring within 5 min buffer is considered expired."""
        assert is_token_expired(_make_expires_at(3), buffer_minutes=5)

    def test_is_token_expired_outside_buffer(self):
        """Token expiring in 10 min is not expired with 5 min buffer."""
        assert not is_token_expired(_make_expires_at(10), buffer_minutes=5)

    def test_is_token_expired_invalid_format(self):
        """Invalid format returns True (fail safe)."""
        assert is_token_expired("not-a-date")

    def test_calculate_expires_at_format(self):
        """calculate_expires_at returns ISO 8601 with Z suffix."""
        result = calculate_expires_at(7200)
        assert result.endswith("Z")
        # Should be parseable
        dt = datetime.fromisoformat(result.replace("Z", "+00:00"))
        assert dt > datetime.now(timezone.utc)


# ============================================================================
# Credential Deletion Revocation Tests
# ============================================================================


@pytest.mark.asyncio
class TestCredentialDeletionRevocation:
    """Test that Twitter token is revoked when credential is deleted."""

    async def test_revoke_twitter_token_import(self):
        """Verify revoke_twitter_token is importable from credentials_handler."""
        from wss.handlers.credentials_handler import revoke_twitter_token

        assert callable(revoke_twitter_token)
