"""
Mock tests for the Discourse REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Posts & Topics: create post, get/update/delete topic, set status, latest/top,
  category topics, get/update/delete post, post action, private messages
- Categories & Tags: list/create/update categories, list tags
- Search
- Users: get/create/update/list, suspend, password reset, notifications
- Groups: list, add/remove members, create invite
- Trigger: on_event passthrough, webhook registration/deregistration,
  signature verification
- Error handling: API errors, missing credentials
- Dynamic options: category dropdown
"""

import hashlib
import hmac

import pytest
from unittest.mock import AsyncMock, Mock, patch

from nodes.core.run_op import run_node_lookup
from nodes.core.connection_evidence import collect_evidence

from nodes.discourse_node import (
    DiscourseNode,
    DiscourseNodeConfig,
    DiscourseApiKeyCredential,
    DiscourseCreatePostConfig,
    DiscourseGetTopicConfig,
    DiscourseUpdateTopicConfig,
    DiscourseDeleteTopicConfig,
    DiscourseSetTopicStatusConfig,
    DiscourseGetLatestTopicsConfig,
    DiscourseGetTopTopicsConfig,
    DiscourseListCategoryTopicsConfig,
    DiscourseGetPostConfig,
    DiscourseUpdatePostConfig,
    DiscourseDeletePostConfig,
    DiscoursePostActionConfig,
    DiscourseListCategoriesConfig,
    DiscourseCreateCategoryConfig,
    DiscourseUpdateCategoryConfig,
    DiscourseSearchConfig,
    DiscourseGetUserConfig,
    DiscourseCreateUserConfig,
    DiscourseUpdateUserConfig,
    DiscourseListUsersConfig,
    DiscourseSuspendUserConfig,
    DiscourseSendPasswordResetConfig,
    DiscourseGetNotificationsConfig,
    DiscourseListGroupsConfig,
    DiscourseAddGroupMembersConfig,
    DiscourseRemoveGroupMembersConfig,
    DiscourseCreateInviteConfig,
    DiscourseListTagsConfig,
    DiscourseGetPrivateMessagesConfig,
    DiscourseTriggerConfig,
)


@pytest.fixture
def api_key_credentials():
    return DiscourseApiKeyCredential(
        site_url="https://meta.discourse.org",
        api_key="testkey1234567890",
        api_username="system",
    )


def create_discourse_node(config):
    return DiscourseNode(
        node_id="test-discourse-node",
        node_type="automation-discourse",
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
    mock_response.content = b'{"ok": true}'
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


async def _run(node, json_data, status_code=200):
    mock_client = create_mock_client(status_code, json_data)
    with patch("nodes.discourse_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation, endpoint, body",
    [
        (
            DiscourseCreatePostConfig(raw="Hello world", title="My new topic", category="5"),
            "/posts.json",
            {"raw": "Hello world", "title": "My new topic", "category": 5},
        ),
        (
            DiscourseCreatePostConfig(raw="A reply", topic_id="55"),
            "/posts.json",
            {"raw": "A reply", "title": None, "topic_id": 55},
        ),
        (
            DiscourseUpdatePostConfig(post_id="101", raw="edited"),
            "/posts/101.json",
            {"post": {"raw": "edited"}},
        ),
        (
            DiscoursePostActionConfig(post_id="101", post_action_type_id="2"),
            "/post_actions.json",
            {"id": 101, "post_action_type_id": 2, "flag_topic": False},
        ),
        (
            DiscourseCreateInviteConfig(email="not-a-user-yet@example.com", group_ids="42, 43"),
            "/invites.json",
            {"email": "not-a-user-yet@example.com", "custom_message": None, "group_ids": "42,43"},
        ),
        (
            DiscourseCreatePostConfig(
                raw="This is the raw markdown for my post",
                title="Concert Master: A new way to choose", category="1", tags="asdf,fdsa",
            ),
            "/posts.json",
            {"raw": "This is the raw markdown for my post", "title": "Concert Master: A new way to choose",
             "category": 1, "tags": ["asdf", "fdsa"]},
        ),
        (
            DiscourseUpdateTopicConfig(topic_id="55", tags="asdf,fdsa"),
            "/t/-/55.json",
            {"title": None, "category_id": None, "tags": ["asdf", "fdsa"]},
        ),
    ],
)
async def test_provider_request_body(api_key_credentials, operation, endpoint, body):
    node = create_discourse_node(DiscourseNodeConfig(
        config=operation, credentials=api_key_credentials,
    ))
    with patch("nodes.discourse_node._discourse_request", new=AsyncMock(return_value={})) as request:
        await node.execute({})
    assert request.call_args.args[4] == endpoint
    assert request.call_args.kwargs["json_body"] == body


class TestDiscoursePostsTopicsMock:
    @pytest.mark.asyncio
    async def test_create_post_topic(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseCreatePostConfig(raw="Hello world", title="My new topic", category="5"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"id": 101, "topic_id": 55}, 200)
        assert result["status"] == "success"
        assert result["action"] == "create_post"
        assert result["data"]["topic_id"] == 55

    @pytest.mark.asyncio
    async def test_create_post_reply(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseCreatePostConfig(raw="A reply", topic_id="55"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"id": 102}, 200)
        assert result["status"] == "success"
        assert result["action"] == "create_post"

    @pytest.mark.asyncio
    async def test_create_post_pm(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseCreatePostConfig(
                raw="A private note", title="Hi", target_recipients="alice,bob"
            ),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"id": 103}, 200)
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_topic(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseGetTopicConfig(topic_id="55"), credentials=api_key_credentials
        )
        node = create_discourse_node(config)
        result = await _run(node, {"id": 55, "title": "Hello"})
        assert result["status"] == "success"
        assert result["action"] == "get_topic"
        assert result["data"]["id"] == 55

    @pytest.mark.asyncio
    async def test_update_topic(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseUpdateTopicConfig(topic_id="55", title="New title", tags="a,b"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"basic_topic": {"id": 55}})
        assert result["status"] == "success"
        assert result["action"] == "update_topic"

    @pytest.mark.asyncio
    async def test_delete_topic(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseDeleteTopicConfig(topic_id="55"), credentials=api_key_credentials
        )
        node = create_discourse_node(config)
        result = await _run(node, {"success": "OK"})
        assert result["status"] == "success"
        assert result["action"] == "delete_topic"

    @pytest.mark.asyncio
    async def test_set_topic_status(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseSetTopicStatusConfig(topic_id="55", status="closed", enabled="true"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"success": "OK", "topic_status_update": None})
        assert result["status"] == "success"
        assert result["action"] == "set_topic_status"

    @pytest.mark.asyncio
    async def test_get_latest_topics(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseGetLatestTopicsConfig(page="0"), credentials=api_key_credentials
        )
        node = create_discourse_node(config)
        result = await _run(node, {"topic_list": {"topics": [{"id": 1}]}})
        assert result["status"] == "success"
        assert result["action"] == "get_latest_topics"

    @pytest.mark.asyncio
    async def test_get_top_topics(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseGetTopTopicsConfig(period="weekly"), credentials=api_key_credentials
        )
        node = create_discourse_node(config)
        result = await _run(node, {"topic_list": {"topics": [{"id": 2}]}})
        assert result["status"] == "success"
        assert result["action"] == "get_top_topics"

    @pytest.mark.asyncio
    async def test_list_category_topics(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseListCategoryTopicsConfig(category_slug="support", category_id="5"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"topic_list": {"topics": [{"id": 3}]}})
        assert result["status"] == "success"
        assert result["action"] == "list_category_topics"

    @pytest.mark.asyncio
    async def test_get_post(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseGetPostConfig(post_id="101"), credentials=api_key_credentials
        )
        node = create_discourse_node(config)
        result = await _run(node, {"id": 101, "raw": "body"})
        assert result["status"] == "success"
        assert result["action"] == "get_post"
        assert result["data"]["id"] == 101

    @pytest.mark.asyncio
    async def test_update_post(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseUpdatePostConfig(post_id="101", raw="edited", edit_reason="typo"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"post": {"id": 101}})
        assert result["status"] == "success"
        assert result["action"] == "update_post"

    @pytest.mark.asyncio
    async def test_delete_post(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseDeletePostConfig(post_id="101"), credentials=api_key_credentials
        )
        node = create_discourse_node(config)
        result = await _run(node, {"success": "OK"})
        assert result["status"] == "success"
        assert result["action"] == "delete_post"

    @pytest.mark.asyncio
    async def test_post_action(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscoursePostActionConfig(post_id="101", post_action_type_id="2"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"id": 101, "actions_summary": []})
        assert result["status"] == "success"
        assert result["action"] == "post_action"

    @pytest.mark.asyncio
    async def test_get_private_messages(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseGetPrivateMessagesConfig(username="alice"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"topic_list": {"topics": [{"id": 9}]}})
        assert result["status"] == "success"
        assert result["action"] == "get_private_messages"


class TestDiscourseCategoriesTagsMock:
    @pytest.mark.asyncio
    async def test_list_categories(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseListCategoriesConfig(), credentials=api_key_credentials
        )
        node = create_discourse_node(config)
        result = await _run(node, {"category_list": {"categories": [{"id": 1, "name": "General"}]}})
        assert result["status"] == "success"
        assert result["action"] == "list_categories"

    @pytest.mark.asyncio
    async def test_create_category(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseCreateCategoryConfig(name="Announcements"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"category": {"id": 7, "name": "Announcements"}})
        assert result["status"] == "success"
        assert result["action"] == "create_category"
        assert result["data"]["category"]["id"] == 7

    @pytest.mark.asyncio
    async def test_update_category(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseUpdateCategoryConfig(category_id="7", name="News"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"category": {"id": 7, "name": "News"}})
        assert result["status"] == "success"
        assert result["action"] == "update_category"

    @pytest.mark.asyncio
    async def test_list_tags(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseListTagsConfig(), credentials=api_key_credentials
        )
        node = create_discourse_node(config)
        result = await _run(node, {"tags": [{"id": "bug", "text": "bug"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_tags"


class TestDiscourseSearchMock:
    @pytest.mark.asyncio
    async def test_search(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseSearchConfig(query="hello"), credentials=api_key_credentials
        )
        node = create_discourse_node(config)
        result = await _run(node, {"topics": [{"id": 1}], "posts": [{"id": 2}]})
        assert result["status"] == "success"
        assert result["action"] == "search"


class TestDiscourseUsersMock:
    @pytest.mark.asyncio
    async def test_get_user(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseGetUserConfig(username="alice"), credentials=api_key_credentials
        )
        node = create_discourse_node(config)
        result = await _run(node, {"user": {"username": "alice", "id": 12}})
        assert result["status"] == "success"
        assert result["action"] == "get_user"
        assert result["data"]["user"]["username"] == "alice"

    @pytest.mark.asyncio
    async def test_create_user(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseCreateUserConfig(
                name="Ada Lovelace",
                email="ada@example.com",
                username="ada",
                password="supersecret123",
            ),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"success": True, "user_id": 99})
        assert result["status"] == "success"
        assert result["action"] == "create_user"

    @pytest.mark.asyncio
    async def test_update_user(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseUpdateUserConfig(username="ada", name="Ada L", bio_raw="Hello"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"user": {"username": "ada"}, "success": "OK"})
        assert result["status"] == "success"
        assert result["action"] == "update_user"

    @pytest.mark.asyncio
    async def test_list_users(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseListUsersConfig(flag="active", page="1"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, [{"id": 1, "username": "ada"}])
        assert result["status"] == "success"
        assert result["action"] == "list_users"

    @pytest.mark.asyncio
    async def test_suspend_user(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseSuspendUserConfig(
                user_id="12", suspend_until="2026-12-31T00:00:00Z", reason="Spam"
            ),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"suspension": {"suspended_till": "2026-12-31"}})
        assert result["status"] == "success"
        assert result["action"] == "suspend_user"

    @pytest.mark.asyncio
    async def test_send_password_reset(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseSendPasswordResetConfig(login="ada"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"success": "OK", "user_found": True})
        assert result["status"] == "success"
        assert result["action"] == "send_password_reset"

    @pytest.mark.asyncio
    async def test_get_notifications(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseGetNotificationsConfig(), credentials=api_key_credentials
        )
        node = create_discourse_node(config)
        result = await _run(node, {"notifications": [{"id": 1}]})
        assert result["status"] == "success"
        assert result["action"] == "get_notifications"


class TestDiscourseGroupsMock:
    @pytest.mark.asyncio
    async def test_list_groups(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseListGroupsConfig(), credentials=api_key_credentials
        )
        node = create_discourse_node(config)
        result = await _run(node, {"groups": [{"id": 1, "name": "admins"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_groups"

    @pytest.mark.asyncio
    async def test_add_group_members(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseAddGroupMembersConfig(group_id="3", usernames="ada,bob"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"success": "OK", "usernames": ["ada", "bob"]})
        assert result["status"] == "success"
        assert result["action"] == "add_group_members"

    @pytest.mark.asyncio
    async def test_remove_group_members(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseRemoveGroupMembersConfig(group_id="3", usernames="ada"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"success": "OK"})
        assert result["status"] == "success"
        assert result["action"] == "remove_group_members"

    @pytest.mark.asyncio
    async def test_create_invite(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseCreateInviteConfig(email="new@example.com", group_ids="3"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"id": 88, "link": "https://meta.discourse.org/invites/abc"})
        assert result["status"] == "success"
        assert result["action"] == "create_invite"
        assert result["data"]["id"] == 88


class TestDiscourseTriggerMock:
    @pytest.mark.asyncio
    async def test_on_event_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = DiscourseNodeConfig(
            config=DiscourseTriggerConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_discourse_node(config)
        payload = {"topic": {"id": 55, "title": "New topic"}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_event"
        assert result["data"]["topic"]["id"] == 55
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    @pytest.mark.asyncio
    async def test_on_event_surfaces_event_types(self):
        """The trigger output reports which event group it is subscribed to."""
        config = DiscourseNodeConfig(
            config=DiscourseTriggerConfig(
                webhook_url="https://abc.hooks.example.test", event_types="topic"
            ),
            credentials=None,
        )
        node = create_discourse_node(config)
        result = await node.execute({"topic": {"id": 1}})
        assert result["event_types"] == "topic"

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        with patch(
            "nodes.discourse_node._discourse_request",
            return_value={"status": "success", "data": {"web_hook": {"id": 42}}},
        ) as mock_req:
            extra = await DiscourseNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={
                    "site_url": "https://meta.discourse.org",
                    "api_key": "testkey",
                    "api_username": "system",
                },
                config={},
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "42"
        assert extra["signing_secret"]
        # Default (no event_types) registers wildcard — empty event-type-ids array.
        sent_body = mock_req.call_args.kwargs["json_body"]
        assert sent_body["web_hook"]["web_hook_event_type_ids"] == []

    @pytest.mark.asyncio
    async def test_register_external_webhook_subscribes_selected_events(self):
        """The webhook subscribes to exactly the chosen event group's numeric ID."""
        with patch(
            "nodes.discourse_node._discourse_request",
            return_value={"status": "success", "data": {"web_hook": {"id": 42}}},
        ) as mock_req:
            await DiscourseNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={
                    "site_url": "https://meta.discourse.org",
                    "api_key": "testkey",
                    "api_username": "system",
                },
                config={"event_types": "post"},
                node_id="node-1",
            )
        sent_body = mock_req.call_args.kwargs["json_body"]
        # POST group => WebHookEventType id 2.
        assert sent_body["web_hook"]["web_hook_event_type_ids"] == [2]

    @pytest.mark.asyncio
    async def test_register_external_webhook_multiple_events(self):
        """A comma-separated selection maps to all matching numeric group IDs."""
        with patch(
            "nodes.discourse_node._discourse_request",
            return_value={"status": "success", "data": {"web_hook": {"id": 42}}},
        ) as mock_req:
            await DiscourseNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={
                    "site_url": "https://meta.discourse.org",
                    "api_key": "testkey",
                    "api_username": "system",
                },
                config={"event_types": "topic,user"},
                node_id="node-1",
            )
        sent_body = mock_req.call_args.kwargs["json_body"]
        # topic => 1, user => 3.
        assert sent_body["web_hook"]["web_hook_event_type_ids"] == [1, 3]

    @pytest.mark.asyncio
    async def test_register_external_webhook_wildcard_all_events(self):
        """The '*' selection subscribes to every event (empty event-type-ids)."""
        with patch(
            "nodes.discourse_node._discourse_request",
            return_value={"status": "success", "data": {"web_hook": {"id": 42}}},
        ) as mock_req:
            await DiscourseNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={
                    "site_url": "https://meta.discourse.org",
                    "api_key": "testkey",
                    "api_username": "system",
                },
                config={"event_types": "*"},
                node_id="node-1",
            )
        sent_body = mock_req.call_args.kwargs["json_body"]
        assert sent_body["web_hook"]["web_hook_event_type_ids"] == []

    def test_filter_trigger_payload_skips_non_selected_event(self):
        """A delivery for an unselected event group is skipped (returns False)."""
        payload = {
            "post": {"id": 9},
            "_webhook": {"headers": {"X-Discourse-Event-Type": "post"}},
        }
        # Subscribed to 'topic' only — a 'post' delivery must be filtered out.
        assert (
            DiscourseNode.filter_trigger_payload(payload, {"event_types": "topic"})
            is False
        )

    def test_filter_trigger_payload_passes_selected_event(self):
        """A delivery matching the selected event group passes (returns True)."""
        payload = {
            "topic": {"id": 55},
            "_webhook": {"headers": {"x-discourse-event-type": "topic"}},
        }
        assert (
            DiscourseNode.filter_trigger_payload(payload, {"event_types": "topic"})
            is True
        )

    def test_filter_trigger_payload_all_events_passes_anything(self):
        """The 'All Events' selection passes every delivery."""
        payload = {
            "user": {"id": 3},
            "_webhook": {"headers": {"X-Discourse-Event-Type": "user"}},
        }
        assert DiscourseNode.filter_trigger_payload(payload, {"event_types": "*"}) is True
        # Missing event_types (legacy config) also defaults to all events.
        assert DiscourseNode.filter_trigger_payload(payload, {}) is True

    def test_filter_trigger_payload_passes_ping_without_event_header(self):
        """The webhook ping/test (no X-Discourse-Event-Type header) is not filtered."""
        payload = {"ping": "OK", "_webhook": {"headers": {}}}
        assert (
            DiscourseNode.filter_trigger_payload(payload, {"event_types": "topic"})
            is True
        )

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.discourse_node._discourse_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await DiscourseNode._unregister_external_webhook(
                credential={
                    "site_url": "https://meta.discourse.org",
                    "api_key": "testkey",
                    "api_username": "system",
                },
                config={"external_webhook_id": "42"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        secret = "topsecret"
        body = b'{"topic":{"id":55}}'
        good_sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert DiscourseNode.verify_webhook_signature(
            body, {"x-discourse-event-signature": good_sig}, {"signing_secret": secret}
        )
        assert not DiscourseNode.verify_webhook_signature(
            body, {"x-discourse-event-signature": "sha256=deadbeef"}, {"signing_secret": secret}
        )
        # no secret stored yet -> accept (trigger not armed)
        assert DiscourseNode.verify_webhook_signature(body, {}, {})


class TestDiscourseErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = DiscourseNodeConfig(
            config=DiscourseGetTopicConfig(topic_id="999999"),
            credentials=api_key_credentials,
        )
        node = create_discourse_node(config)
        result = await _run(node, {"errors": ["The requested URL or resource could not be found."]}, 404)
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "could not be found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = DiscourseNodeConfig(config=DiscourseListGroupsConfig(), credentials=None)
        node = create_discourse_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestDiscourseDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_connection_evidence_shows_categories_and_rejects_bad_key(self):
        credential_data = {
            "site_url": "https://forum.example.com",
            "api_key": "testkey",
            "api_username": "qa-admin",
        }
        with patch(
            "nodes.discourse_node._discourse_request",
            new=AsyncMock(return_value={
                "status": "success",
                "data": {"category_list": {"categories": [{"id": 7, "name": "QA"}]}},
            }),
        ):
            evidence = await collect_evidence(
                node_type="automation-discourse", user_id="user-1",
                credential_data=credential_data,
            )
        assert evidence.reachable is True
        assert [sample.label for sample in evidence.samples] == ["QA"]

        with patch(
            "nodes.discourse_node._discourse_request",
            new=AsyncMock(return_value={
                "status": "error", "error": "unauthorized", "status_code": 401,
            }),
        ):
            evidence = await collect_evidence(
                node_type="automation-discourse", user_id="user-1",
                credential_data=credential_data,
            )
        assert evidence.reachable is False

    @pytest.mark.asyncio
    async def test_load_category_options(self):
        with patch(
            "nodes.discourse_node._discourse_request",
            new=AsyncMock(return_value={
                "status": "success",
                "data": {
                    "category_list": {
                        "categories": [{"id": 1, "name": "General"}, {"id": 2, "name": "Support"}]
                    }
                },
            }),
        ) as request:
            result = await DiscourseNode.load_field_options(
                field_name="category",
                credential_data={
                    "site_url": "https://meta.discourse.org",
                    "api_key": "testkey",
                    "api_username": "qa-admin",
                },
                context={"_user_id": "user-1"},
                page_token=None,
                search="supp",
            )
        assert result == [{"value": "2", "label": "Support"}]
        request.assert_awaited_once_with(
            "https://meta.discourse.org", "testkey", "qa-admin",
            "GET", "/categories.json", action_name="list_categories",
        )

    @pytest.mark.asyncio
    async def test_lookup_resolves_credential_and_normalizes_options(self):
        credentials = {
            "site_url": "https://forum.example.com",
            "api_key": "testkey",
            "api_username": "qa-admin",
        }
        response = {
            "status": "success",
            "data": {"category_list": {"categories": [{"id": 7, "name": "QA"}]}},
        }
        with patch(
            "nodes.core.run_op.resolve_operation_credential",
            new=AsyncMock(return_value=credentials),
        ) as resolve, patch(
            "utils.credential_approval.admit_lookup",
            new=AsyncMock(return_value=None),
        ), patch(
            "nodes.discourse_node._discourse_request",
            new=AsyncMock(return_value=response),
        ) as request:
            result = await run_node_lookup(
                node_type="automation-discourse",
                field_name="category_id",
                user_id="user-1",
                credential_id="cred-1",
                pool=object(),
                search=" QA ",
            )
        assert result == {
            "options": [{"value": "7", "label": "QA"}],
            "next_page_token": None,
        }
        assert resolve.await_count == 2  # access check, then credential load
        request.assert_awaited_once_with(
            "https://forum.example.com", "testkey", "qa-admin",
            "GET", "/categories.json", action_name="list_categories",
        )

    @pytest.mark.asyncio
    async def test_missing_credentials_and_api_error_yield_no_options(self):
        with patch("nodes.discourse_node._discourse_request", new=AsyncMock()) as request:
            assert await DiscourseNode.load_field_options(
                field_name="category", credential_data={}, context={},
                page_token=None, search=None,
            ) == []
            request.assert_not_awaited()

        with patch(
            "nodes.discourse_node._discourse_request",
            new=AsyncMock(return_value={"status": "error", "error": "forbidden"}),
        ):
            assert await DiscourseNode.load_field_options(
                field_name="category", credential_data={
                    "site_url": "https://forum.example.com", "api_key": "testkey",
                }, context={}, page_token=None, search=None,
            ) == []
