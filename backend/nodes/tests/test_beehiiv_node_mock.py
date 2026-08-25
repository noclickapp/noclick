"""
Mock tests for the beehiiv REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Publications: list, get
- Subscriptions: list, create, get by email, get by id, update (PUT), delete, bulk, tag
- Posts: list, get, create, update (PATCH), delete, stats
- Segments: list, get, list subscribers (/members), delete
- Custom Fields: list, create, delete
- Automations: list, get, add to journey
- Tiers / Referral / Newsletter Lists / Polls (list, get, responses)
- Webhooks: list, get, create, delete
- Trigger: on_beehiiv_event passthrough, webhook registration/deregistration,
  signature verification
- Error handling: API errors, missing credentials
- Dynamic options: publication dropdown
"""

import hashlib
import hmac

import pytest
from unittest.mock import Mock, patch

from nodes.beehiiv_node import (
    BeehiivNode,
    BeehiivNodeConfig,
    BeehiivApiKeyCredential,
    BeehiivListPublicationsConfig,
    BeehiivGetPublicationConfig,
    BeehiivListSubscriptionsConfig,
    BeehiivCreateSubscriptionConfig,
    BeehiivGetSubscriptionByEmailConfig,
    BeehiivGetSubscriptionConfig,
    BeehiivUpdateSubscriptionConfig,
    BeehiivDeleteSubscriptionConfig,
    BeehiivBulkCreateSubscriptionsConfig,
    BeehiivAddSubscriptionTagConfig,
    BeehiivListPostsConfig,
    BeehiivGetPostConfig,
    BeehiivCreatePostConfig,
    BeehiivUpdatePostConfig,
    BeehiivDeletePostConfig,
    BeehiivGetPostStatsConfig,
    BeehiivListSegmentsConfig,
    BeehiivGetSegmentConfig,
    BeehiivListSegmentSubscribersConfig,
    BeehiivDeleteSegmentConfig,
    BeehiivListCustomFieldsConfig,
    BeehiivCreateCustomFieldConfig,
    BeehiivDeleteCustomFieldConfig,
    BeehiivListAutomationsConfig,
    BeehiivGetAutomationConfig,
    BeehiivAddToAutomationConfig,
    BeehiivListTiersConfig,
    BeehiivGetReferralProgramConfig,
    BeehiivListNewsletterListsConfig,
    BeehiivListPollsConfig,
    BeehiivGetPollConfig,
    BeehiivGetPollResponsesConfig,
    BeehiivGetWebhookConfig,
    BeehiivListWebhooksConfig,
    BeehiivCreateWebhookConfig,
    BeehiivDeleteWebhookConfig,
    BeehiivTriggerConfig,
)

PUB = "pub_test_123"


@pytest.fixture
def api_key_credentials():
    return BeehiivApiKeyCredential(api_key="test_beehiiv_key")


def create_beehiiv_node(config):
    return BeehiivNode(
        node_id="test-beehiiv-node",
        node_type="automation-beehiiv",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


def _envelope(data):
    """beehiiv v2 wraps results in {data: ...}."""
    return {"data": data}


async def _run(node, status_code, json_data):
    mock_client = create_mock_client(status_code, json_data)
    with patch("nodes.beehiiv_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


# ============================================================================
# Publications
# ============================================================================


class TestBeehiivPublicationsMock:
    @pytest.mark.asyncio
    async def test_list_publications(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivListPublicationsConfig(limit="10"), credentials=api_key_credentials
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope([{"id": "pub_1"}, {"id": "pub_2"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_publications"
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_get_publication(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivGetPublicationConfig(publication_id=PUB, expand="stats"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope({"id": PUB, "name": "My Newsletter"}))
        assert result["status"] == "success"
        assert result["action"] == "get_publication"
        assert result["data"]["id"] == PUB


# ============================================================================
# Subscriptions
# ============================================================================


class TestBeehiivSubscriptionsMock:
    @pytest.mark.asyncio
    async def test_list_subscriptions(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivListSubscriptionsConfig(publication_id=PUB, status="active", limit="10"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope([{"id": "sub_1"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_subscriptions"
        assert len(result["data"]) == 1

    @pytest.mark.asyncio
    async def test_create_subscription(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivCreateSubscriptionConfig(
                publication_id=PUB,
                email="ada@example.com",
                send_welcome_email="true",
                custom_fields='[{"name":"First Name","value":"Ada"}]',
            ),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 201, _envelope({"id": "sub_new", "email": "ada@example.com"}))
        assert result["status"] == "success"
        assert result["action"] == "create_subscription"
        assert result["data"]["id"] == "sub_new"

    @pytest.mark.asyncio
    async def test_get_subscription_by_email(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivGetSubscriptionByEmailConfig(publication_id=PUB, email="ada@example.com"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope({"id": "sub_1", "email": "ada@example.com"}))
        assert result["status"] == "success"
        assert result["action"] == "get_subscription_by_email"
        assert result["data"]["email"] == "ada@example.com"

    @pytest.mark.asyncio
    async def test_get_subscription(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivGetSubscriptionConfig(publication_id=PUB, subscription_id="sub_1"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope({"id": "sub_1"}))
        assert result["status"] == "success"
        assert result["action"] == "get_subscription"
        assert result["data"]["id"] == "sub_1"

    @pytest.mark.asyncio
    async def test_update_subscription(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivUpdateSubscriptionConfig(
                publication_id=PUB, subscription_id="sub_1", tier="premium"
            ),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope({"id": "sub_1", "tier": "premium"}))
        assert result["status"] == "success"
        assert result["action"] == "update_subscription"
        assert result["data"]["tier"] == "premium"

    @pytest.mark.asyncio
    async def test_update_subscription_uses_put(self, api_key_credentials):
        """beehiiv update subscription endpoint requires PUT, not PATCH."""
        config = BeehiivNodeConfig(
            config=BeehiivUpdateSubscriptionConfig(
                publication_id=PUB, subscription_id="sub_1", unsubscribe="true"
            ),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        captured_method = {}

        async def capture_request(*args, **kwargs):
            captured_method["method"] = args[0] if args else kwargs.get("method")
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.json = lambda: {"data": {"id": "sub_1"}}
            return mock_resp

        mock_client = Mock()
        mock_client.request = capture_request

        async def aenter(self):
            return mock_client

        async def aexit(self, *args):
            return None

        mock_client.__aenter__ = aenter
        mock_client.__aexit__ = aexit

        with patch("nodes.beehiiv_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert captured_method["method"] == "PUT"

    @pytest.mark.asyncio
    async def test_delete_subscription(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivDeleteSubscriptionConfig(publication_id=PUB, subscription_id="sub_1"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 204, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_subscription"

    @pytest.mark.asyncio
    async def test_bulk_create_subscriptions(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivBulkCreateSubscriptionsConfig(
                publication_id=PUB,
                subscriptions='[{"email":"a@x.com"},{"email":"b@x.com"}]',
            ),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 201, _envelope({"id": "bulk_job_1", "status": "processing"}))
        assert result["status"] == "success"
        assert result["action"] == "bulk_create_subscriptions"

    @pytest.mark.asyncio
    async def test_add_subscription_tag(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivAddSubscriptionTagConfig(
                publication_id=PUB, subscription_id="sub_1", tags="vip, beta"
            ),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope({"id": "sub_1", "tags": ["vip", "beta"]}))
        assert result["status"] == "success"
        assert result["action"] == "add_subscription_tag"


# ============================================================================
# Posts
# ============================================================================


class TestBeehiivPostsMock:
    @pytest.mark.asyncio
    async def test_list_posts(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivListPostsConfig(publication_id=PUB, status="confirmed", limit="10"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope([{"id": "post_1"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_posts"

    @pytest.mark.asyncio
    async def test_get_post(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivGetPostConfig(publication_id=PUB, post_id="post_1", expand="stats"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope({"id": "post_1", "title": "Issue #1"}))
        assert result["status"] == "success"
        assert result["action"] == "get_post"
        assert result["data"]["id"] == "post_1"

    @pytest.mark.asyncio
    async def test_create_post(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivCreatePostConfig(
                publication_id=PUB, title="Hello", body_content="<p>Hi</p>", status="draft"
            ),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 201, _envelope({"id": "post_new", "status": "draft"}))
        assert result["status"] == "success"
        assert result["action"] == "create_post"
        assert result["data"]["id"] == "post_new"

    @pytest.mark.asyncio
    async def test_update_post(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivUpdatePostConfig(publication_id=PUB, post_id="post_1", title="Updated"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope({"id": "post_1", "title": "Updated"}))
        assert result["status"] == "success"
        assert result["action"] == "update_post"

    @pytest.mark.asyncio
    async def test_delete_post(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivDeletePostConfig(publication_id=PUB, post_id="post_1"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 204, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_post"

    @pytest.mark.asyncio
    async def test_get_post_stats(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivGetPostStatsConfig(publication_id=PUB, post_id="post_1"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope({"open_rate": 0.5, "click_rate": 0.1}))
        assert result["status"] == "success"
        assert result["action"] == "get_post_stats"
        assert result["data"]["open_rate"] == 0.5


# ============================================================================
# Segments
# ============================================================================


class TestBeehiivSegmentsMock:
    @pytest.mark.asyncio
    async def test_list_segments(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivListSegmentsConfig(publication_id=PUB, limit="10"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope([{"id": "seg_1"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_segments"

    @pytest.mark.asyncio
    async def test_get_segment(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivGetSegmentConfig(publication_id=PUB, segment_id="seg_1"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope({"id": "seg_1", "name": "Power users"}))
        assert result["status"] == "success"
        assert result["action"] == "get_segment"
        assert result["data"]["id"] == "seg_1"

    @pytest.mark.asyncio
    async def test_list_segment_subscribers(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivListSegmentSubscribersConfig(
                publication_id=PUB, segment_id="seg_1", limit="10"
            ),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope([{"id": "sub_1"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_segment_subscribers"

    @pytest.mark.asyncio
    async def test_list_segment_subscribers_uses_members_path(self, api_key_credentials):
        """beehiiv segment subscriber listing uses /members not /results."""
        config = BeehiivNodeConfig(
            config=BeehiivListSegmentSubscribersConfig(
                publication_id=PUB, segment_id="seg_1", limit="5"
            ),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        with patch(
            "nodes.beehiiv_node._beehiiv_request",
            return_value={"status": "success", "data": [], "status_code": 200, "action": "list_segment_subscribers", "timing_ms": {}},
        ) as mock_req:
            await node.execute({})
        called_endpoint = mock_req.call_args.args[2]
        assert called_endpoint.endswith("/members"), f"Expected /members path, got: {called_endpoint}"
        assert "/results" not in called_endpoint

    @pytest.mark.asyncio
    async def test_delete_segment(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivDeleteSegmentConfig(publication_id=PUB, segment_id="seg_1"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 204, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_segment"


# ============================================================================
# Custom Fields
# ============================================================================


class TestBeehiivCustomFieldsMock:
    @pytest.mark.asyncio
    async def test_list_custom_fields(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivListCustomFieldsConfig(publication_id=PUB),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope([{"id": "cf_1", "display": "First Name"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_custom_fields"

    @pytest.mark.asyncio
    async def test_create_custom_field(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivCreateCustomFieldConfig(
                publication_id=PUB, display="Birthday", kind="date"
            ),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 201, _envelope({"id": "cf_new", "display": "Birthday"}))
        assert result["status"] == "success"
        assert result["action"] == "create_custom_field"

    @pytest.mark.asyncio
    async def test_delete_custom_field(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivDeleteCustomFieldConfig(publication_id=PUB, field_id="cf_1"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 204, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_custom_field"


# ============================================================================
# Automations
# ============================================================================


class TestBeehiivAutomationsMock:
    @pytest.mark.asyncio
    async def test_list_automations(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivListAutomationsConfig(publication_id=PUB, limit="10"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope([{"id": "aut_1"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_automations"

    @pytest.mark.asyncio
    async def test_get_automation(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivGetAutomationConfig(publication_id=PUB, automation_id="aut_1"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope({"id": "aut_1", "name": "Welcome flow"}))
        assert result["status"] == "success"
        assert result["action"] == "get_automation"
        assert result["data"]["id"] == "aut_1"

    @pytest.mark.asyncio
    async def test_add_to_automation(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivAddToAutomationConfig(
                publication_id=PUB, automation_id="aut_1", email="ada@example.com"
            ),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 201, _envelope({"id": "journey_1", "status": "active"}))
        assert result["status"] == "success"
        assert result["action"] == "add_to_automation"

    @pytest.mark.asyncio
    async def test_add_to_automation_requires_target(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivAddToAutomationConfig(publication_id=PUB, automation_id="aut_1"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        with pytest.raises(ValueError, match="Email or a Subscription ID"):
            await node.execute({})


# ============================================================================
# Tiers / Referral / Lists / Polls
# ============================================================================


class TestBeehiivMiscMock:
    @pytest.mark.asyncio
    async def test_list_tiers(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivListTiersConfig(publication_id=PUB), credentials=api_key_credentials
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope([{"id": "tier_1"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_tiers"

    @pytest.mark.asyncio
    async def test_get_referral_program(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivGetReferralProgramConfig(publication_id=PUB),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope({"milestones": []}))
        assert result["status"] == "success"
        assert result["action"] == "get_referral_program"

    @pytest.mark.asyncio
    async def test_list_newsletter_lists(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivListNewsletterListsConfig(publication_id=PUB),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope([{"id": "list_1"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_newsletter_lists"

    @pytest.mark.asyncio
    async def test_list_polls(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivListPollsConfig(publication_id=PUB, limit="10"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope([{"id": "poll_1"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_polls"

    @pytest.mark.asyncio
    async def test_get_poll(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivGetPollConfig(publication_id=PUB, poll_id="poll_1"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope({"id": "poll_1", "question": "How are you?"}))
        assert result["status"] == "success"
        assert result["action"] == "get_poll"
        assert result["data"]["id"] == "poll_1"

    @pytest.mark.asyncio
    async def test_get_poll_responses(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivGetPollResponsesConfig(publication_id=PUB, poll_id="poll_1", limit="5"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope([{"id": "resp_1", "answer": "Good"}]))
        assert result["status"] == "success"
        assert result["action"] == "get_poll_responses"
        assert len(result["data"]) == 1


# ============================================================================
# Webhooks (management)
# ============================================================================


class TestBeehiivWebhooksMock:
    @pytest.mark.asyncio
    async def test_get_webhook(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivGetWebhookConfig(publication_id=PUB, webhook_id="wh_1"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope({"id": "wh_1", "url": "https://example.com/hook"}))
        assert result["status"] == "success"
        assert result["action"] == "get_webhook"
        assert result["data"]["id"] == "wh_1"

    @pytest.mark.asyncio
    async def test_list_webhooks(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivListWebhooksConfig(publication_id=PUB), credentials=api_key_credentials
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 200, _envelope([{"id": "wh_1"}]))
        assert result["status"] == "success"
        assert result["action"] == "list_webhooks"

    @pytest.mark.asyncio
    async def test_create_webhook(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivCreateWebhookConfig(
                publication_id=PUB,
                url="https://example.com/hook",
                event_types="subscription.created, post.sent",
            ),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 201, _envelope({"id": "wh_new"}))
        assert result["status"] == "success"
        assert result["action"] == "create_webhook"
        assert result["data"]["id"] == "wh_new"

    @pytest.mark.asyncio
    async def test_delete_webhook(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivDeleteWebhookConfig(publication_id=PUB, webhook_id="wh_1"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 204, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_webhook"


# ============================================================================
# Trigger
# ============================================================================


class TestBeehiivTriggerMock:
    @pytest.mark.asyncio
    async def test_on_beehiiv_event_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = BeehiivNodeConfig(
            config=BeehiivTriggerConfig(
                publication_id=PUB, webhook_url="https://abc.hooks.example.test"
            ),
            credentials=None,
        )
        node = create_beehiiv_node(config)
        payload = {"event_type": "subscription.created", "data": {"id": "sub_x"}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_beehiiv_event"
        assert result["data"]["event_type"] == "subscription.created"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        with patch(
            "nodes.beehiiv_node._beehiiv_request",
            return_value={"status": "success", "data": {"id": "wh_99", "secret": "shh"}},
        ) as mock_req:
            extra = await BeehiivNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "test"},
                config={"publication_id": PUB},
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "wh_99"
        assert extra["signing_secret"] == "shh"

    @pytest.mark.asyncio
    async def test_register_external_webhook_requires_publication(self):
        with pytest.raises(ValueError, match="Select a publication"):
            await BeehiivNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "test"},
                config={},
                node_id="node-1",
            )

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.beehiiv_node._beehiiv_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await BeehiivNode._unregister_external_webhook(
                credential={"api_key": "test"},
                config={"external_webhook_id": "wh_99", "publication_id": PUB},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        secret = "topsecret"
        body = b'{"event_type":"subscription.created"}'
        good_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert BeehiivNode.verify_webhook_signature(
            body, {"x-beehiiv-signature": good_sig}, {"signing_secret": secret}
        )
        assert not BeehiivNode.verify_webhook_signature(
            body, {"x-beehiiv-signature": "deadbeef"}, {"signing_secret": secret}
        )
        # no secret stored yet -> accept (trigger not armed)
        assert BeehiivNode.verify_webhook_signature(body, {}, {})


# ============================================================================
# Error handling
# ============================================================================


class TestBeehiivErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivGetSubscriptionConfig(publication_id=PUB, subscription_id="missing"),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        result = await _run(node, 404, {"message": "Subscription not found"})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = BeehiivNodeConfig(
            config=BeehiivListPublicationsConfig(), credentials=None
        )
        node = create_beehiiv_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_invalid_json_field(self, api_key_credentials):
        config = BeehiivNodeConfig(
            config=BeehiivCreateSubscriptionConfig(
                publication_id=PUB, email="ada@example.com", custom_fields="not-json{"
            ),
            credentials=api_key_credentials,
        )
        node = create_beehiiv_node(config)
        with pytest.raises(ValueError, match="Invalid JSON"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestBeehiivDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_publication_options(self):
        with patch(
            "nodes.beehiiv_node._beehiiv_request",
            return_value={
                "status": "success",
                "data": [{"id": "pub_1", "name": "Daily News"}],
            },
        ):
            result = await BeehiivNode.load_field_options(
                "publication_id", credential_data={"api_key": "test"}
            )
        assert "options" in result
        assert result["options"][0]["value"] == "pub_1"
        assert result["options"][0]["label"] == "Daily News"

    @pytest.mark.asyncio
    async def test_load_post_options(self):
        with patch(
            "nodes.beehiiv_node._beehiiv_request",
            return_value={
                "status": "success",
                "data": [{"id": "post_1", "title": "Issue #1"}, {"id": "post_2"}],
            },
        ) as mock_req:
            result = await BeehiivNode.load_field_options(
                "post_id",
                credential_data={"api_key": "test"},
                context={"publication_id": PUB},
            )
        # LIST endpoint must be scoped under the chosen publication.
        assert mock_req.call_args.args[2] == f"/publications/{PUB}/posts"
        assert result["options"][0] == {"label": "Issue #1", "value": "post_1"}
        # Falls back to the id when no human label key is present.
        assert result["options"][1] == {"label": "post_2", "value": "post_2"}

    @pytest.mark.asyncio
    async def test_load_segment_options(self):
        with patch(
            "nodes.beehiiv_node._beehiiv_request",
            return_value={
                "status": "success",
                "data": [{"id": "seg_1", "name": "Power users"}],
            },
        ) as mock_req:
            result = await BeehiivNode.load_field_options(
                "segment_id",
                credential_data={"api_key": "test"},
                context={"publication_id": PUB},
            )
        assert mock_req.call_args.args[2] == f"/publications/{PUB}/segments"
        assert result["options"][0] == {"label": "Power users", "value": "seg_1"}

    @pytest.mark.asyncio
    async def test_load_automation_options(self):
        with patch(
            "nodes.beehiiv_node._beehiiv_request",
            return_value={
                "status": "success",
                "data": [{"id": "aut_1", "name": "Welcome flow"}],
            },
        ) as mock_req:
            result = await BeehiivNode.load_field_options(
                "automation_id",
                credential_data={"api_key": "test"},
                context={"publication_id": PUB},
            )
        assert mock_req.call_args.args[2] == f"/publications/{PUB}/automations"
        assert result["options"][0] == {"label": "Welcome flow", "value": "aut_1"}

    @pytest.mark.asyncio
    async def test_load_webhook_options(self):
        with patch(
            "nodes.beehiiv_node._beehiiv_request",
            return_value={
                "status": "success",
                "data": [{"id": "wh_1", "url": "https://example.com/hook"}],
            },
        ) as mock_req:
            result = await BeehiivNode.load_field_options(
                "webhook_id",
                credential_data={"api_key": "test"},
                context={"publication_id": PUB},
            )
        assert mock_req.call_args.args[2] == f"/publications/{PUB}/webhooks"
        assert result["options"][0] == {"label": "https://example.com/hook", "value": "wh_1"}

    @pytest.mark.asyncio
    async def test_scoped_options_require_publication(self):
        """A scoped field returns no options until a publication is chosen."""
        with patch("nodes.beehiiv_node._beehiiv_request") as mock_req:
            result = await BeehiivNode.load_field_options(
                "post_id", credential_data={"api_key": "test"}, context={}
            )
        assert result == {"options": []}
        assert not mock_req.called
