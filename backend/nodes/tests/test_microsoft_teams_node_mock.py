"""
Mock tests for the Microsoft Teams (Microsoft Graph) node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Teams: list joined teams, get, create
- Channels: list, get, create, delete
- Channel messages: list, get, send, reply, list replies
- Chats: list, get, create, list messages, send
- Members: list, add, remove
- Apps & tabs: list installed apps, install app, list tabs, add tab
- Meetings: create, get
- Presence: get user presence
- Triggers: on_channel_message / on_chat_message / on_change_notification
  passthrough, per-resource subscription registration, deregister, and
  clientState signature verification
- Error handling: API errors, missing credentials
- Dynamic options: team / channel / chat dropdowns

The node's `_ensure_fresh_token` short-circuits to a no-op when the credential's
`expires_at` is in the future AND no `credential_id` is present in node_data
(no DB store -> no persistence), so the mock credential uses a future expiry.
"""

import json

import pytest
from unittest.mock import Mock, patch

from nodes.microsoft_teams_node import (
    MicrosoftTeamsNode,
    MicrosoftTeamsNodeConfig,
    MicrosoftTeamsOAuthCredential,
    TeamsListJoinedTeamsConfig,
    TeamsGetTeamConfig,
    TeamsCreateTeamConfig,
    TeamsListChannelsConfig,
    TeamsGetChannelConfig,
    TeamsCreateChannelConfig,
    TeamsDeleteChannelConfig,
    TeamsListChannelMessagesConfig,
    TeamsGetChannelMessageConfig,
    TeamsSendChannelMessageConfig,
    TeamsReplyChannelMessageConfig,
    TeamsListChannelMessageRepliesConfig,
    TeamsListChatsConfig,
    TeamsGetChatConfig,
    TeamsCreateChatConfig,
    TeamsListChatMessagesConfig,
    TeamsSendChatMessageConfig,
    TeamsListMembersConfig,
    TeamsAddMemberConfig,
    TeamsRemoveMemberConfig,
    TeamsListInstalledAppsConfig,
    TeamsInstallAppConfig,
    TeamsListTabsConfig,
    TeamsAddTabConfig,
    TeamsCreateMeetingConfig,
    TeamsGetMeetingConfig,
    TeamsGetPresenceConfig,
    TeamsUpdateTeamConfig,
    TeamsArchiveTeamConfig,
    TeamsUnarchiveTeamConfig,
    TeamsUpdateChannelConfig,
    TeamsListChannelMembersConfig,
    TeamsGetChatMessageConfig,
    TeamsListChatMembersConfig,
    TeamsDeleteChannelTabConfig,
    TeamsUninstallAppConfig,
    TeamsGetMyPresenceConfig,
    TeamsOnChannelMessageConfig,
    TeamsOnChatMessageConfig,
    TeamsSubscriptionTriggerConfig,
    _graph_request,
)
from utils.ssrf import SSRFError


@pytest.fixture
def oauth_credentials():
    return MicrosoftTeamsOAuthCredential(
        access_token="mock_access_token",
        refresh_token="mock_refresh_token",
        expires_at="2099-12-31T23:59:59Z",
        email="user@example.com",
    )


def create_teams_node(config):
    return MicrosoftTeamsNode(
        node_id="test-teams-node",
        node_type="automation-microsoft-teams",
        node_data={},  # no credential_id -> token refresh is an in-memory no-op
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None, headers=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.headers = headers or {}
    # Non-204 responses must have content so the helper parses JSON.
    mock_response.content = b"{}" if status_code != 204 else b""
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None, headers=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data, headers)
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


def _collection(items):
    """Graph collection envelope."""
    return {"value": items}


class TestTeamsOperationsMock:
    @pytest.mark.asyncio
    async def test_list_joined_teams(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsListJoinedTeamsConfig(), credentials=oauth_credentials
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(
            200, _collection([{"id": "t1", "displayName": "Eng"}])
        )
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_joined_teams"
        assert result["data"][0]["id"] == "t1"

    @pytest.mark.asyncio
    async def test_get_team(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsGetTeamConfig(team_id="t1"), credentials=oauth_credentials
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(200, {"id": "t1", "displayName": "Eng"})
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_team"
        assert result["data"]["id"] == "t1"

    @pytest.mark.asyncio
    async def test_create_team(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsCreateTeamConfig(display_name="New Team", visibility="private"),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(
            202, {"success": True}, headers={"Location": "/teams('t9')/operations('op1')"}
        )
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_team"
        assert result["data"]["operation_location"].endswith("operations('op1')")


class TestChannelOperationsMock:
    @pytest.mark.asyncio
    async def test_list_channels(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsListChannelsConfig(team_id="t1"), credentials=oauth_credentials
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(
            200, _collection([{"id": "c1", "displayName": "General"}])
        )
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_channels"
        assert result["data"][0]["id"] == "c1"

    @pytest.mark.asyncio
    async def test_get_channel(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsGetChannelConfig(team_id="t1", channel_id="19:abc@thread.tacv2"),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(200, {"id": "19:abc@thread.tacv2"})
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_channel"

    @pytest.mark.asyncio
    async def test_create_channel(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsCreateChannelConfig(
                team_id="t1", display_name="Releases", membership_type="standard"
            ),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(201, {"id": "c2", "displayName": "Releases"})
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_channel"
        assert result["data"]["id"] == "c2"

    @pytest.mark.asyncio
    async def test_delete_channel(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsDeleteChannelConfig(team_id="t1", channel_id="c2"),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(204)
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_channel"
        assert result["data"]["success"] is True


class TestChannelMessageOperationsMock:
    @pytest.mark.asyncio
    async def test_list_channel_messages(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsListChannelMessagesConfig(team_id="t1", channel_id="c1", top="10"),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(200, _collection([{"id": "m1"}, {"id": "m2"}]))
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_channel_messages"
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_get_channel_message(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsGetChannelMessageConfig(team_id="t1", channel_id="c1", message_id="m1"),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(200, {"id": "m1"})
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_channel_message"
        assert result["data"]["id"] == "m1"

    @pytest.mark.asyncio
    async def test_send_channel_message(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsSendChannelMessageConfig(
                team_id="t1", channel_id="c1", content="Hello team", content_type="html"
            ),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(201, {"id": "m_new"})
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "send_channel_message"
        assert result["data"]["id"] == "m_new"

    @pytest.mark.asyncio
    async def test_reply_channel_message(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsReplyChannelMessageConfig(
                team_id="t1", channel_id="c1", message_id="m1", content="Reply", content_type="text"
            ),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(201, {"id": "r_new"})
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "reply_channel_message"

    @pytest.mark.asyncio
    async def test_list_channel_message_replies(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsListChannelMessageRepliesConfig(
                team_id="t1", channel_id="c1", message_id="m1"
            ),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(200, _collection([{"id": "r1"}]))
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_channel_message_replies"


class TestChatOperationsMock:
    @pytest.mark.asyncio
    async def test_list_chats(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsListChatsConfig(top="10"), credentials=oauth_credentials
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(200, _collection([{"id": "ch1", "topic": "Project"}]))
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_chats"
        assert result["data"][0]["id"] == "ch1"

    @pytest.mark.asyncio
    async def test_get_chat(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsGetChatConfig(chat_id="ch1"), credentials=oauth_credentials
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(200, {"id": "ch1"})
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_chat"

    @pytest.mark.asyncio
    async def test_create_chat(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsCreateChatConfig(
                chat_type="group",
                member_emails="a@example.com,b@example.com",
                topic="Launch",
            ),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(201, {"id": "ch_new", "chatType": "group"})
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_chat"
        assert result["data"]["id"] == "ch_new"

    @pytest.mark.asyncio
    async def test_list_chat_messages(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsListChatMessagesConfig(chat_id="ch1", top="5"),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(200, _collection([{"id": "cm1"}]))
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_chat_messages"

    @pytest.mark.asyncio
    async def test_send_chat_message(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsSendChatMessageConfig(
                chat_id="ch1", content="Hi there", content_type="html"
            ),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(201, {"id": "cm_new"})
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "send_chat_message"
        assert result["data"]["id"] == "cm_new"


class TestMemberOperationsMock:
    @pytest.mark.asyncio
    async def test_list_team_members(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsListMembersConfig(team_id="t1"), credentials=oauth_credentials
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(200, _collection([{"id": "mem1"}]))
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_team_members"

    @pytest.mark.asyncio
    async def test_add_team_member(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsAddMemberConfig(
                team_id="t1", user_email="new@example.com", is_owner="true"
            ),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(201, {"id": "mem_new", "roles": ["owner"]})
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "add_team_member"

    @pytest.mark.asyncio
    async def test_remove_team_member(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsRemoveMemberConfig(team_id="t1", membership_id="mem1"),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(204)
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "remove_team_member"


class TestAppsAndTabsOperationsMock:
    @pytest.mark.asyncio
    async def test_list_installed_apps(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsListInstalledAppsConfig(team_id="t1"), credentials=oauth_credentials
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(200, _collection([{"id": "app1"}]))
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_installed_apps"

    @pytest.mark.asyncio
    async def test_install_app(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsInstallAppConfig(team_id="t1", app_id="catalogApp123"),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(201, {"id": "install1"})
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "install_app"

    @pytest.mark.asyncio
    async def test_list_channel_tabs(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsListTabsConfig(team_id="t1", channel_id="c1"),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(200, _collection([{"id": "tab1"}]))
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_channel_tabs"

    @pytest.mark.asyncio
    async def test_add_channel_tab(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsAddTabConfig(
                team_id="t1",
                channel_id="c1",
                display_name="Docs",
                app_id="catalogApp123",
                content_url="https://example.com/tab",
            ),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(201, {"id": "tab_new"})
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "add_channel_tab"
        assert result["data"]["id"] == "tab_new"


class TestMeetingAndPresenceOperationsMock:
    @pytest.mark.asyncio
    async def test_create_online_meeting(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsCreateMeetingConfig(
                subject="Sync",
                start_datetime="2026-07-01T10:00:00Z",
                end_datetime="2026-07-01T11:00:00Z",
            ),
            credentials=oauth_credentials,
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(
            201, {"id": "mtg1", "joinWebUrl": "https://teams.microsoft.com/l/meetup/..."}
        )
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_online_meeting"
        assert "joinWebUrl" in result["data"]

    @pytest.mark.asyncio
    async def test_get_online_meeting(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsGetMeetingConfig(meeting_id="mtg1"), credentials=oauth_credentials
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(200, {"id": "mtg1"})
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_online_meeting"

    @pytest.mark.asyncio
    async def test_get_user_presence(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsGetPresenceConfig(user_id="u1"), credentials=oauth_credentials
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(200, {"availability": "Available", "activity": "Available"})
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_user_presence"
        assert result["data"]["availability"] == "Available"


class TestTeamsTriggerMock:
    @pytest.mark.asyncio
    async def test_on_change_notification_passthrough(self):
        """The trigger passes the inbound Graph notification payload through."""
        config = MicrosoftTeamsNodeConfig(
            config=TeamsSubscriptionTriggerConfig(
                webhook_url="https://abc.hooks.example.test", resource="/me/chats/getAllMessages"
            ),
            credentials=None,
        )
        node = create_teams_node(config)
        payload = {"value": [{"resource": "chats('ch1')/messages('m1')"}]}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_change_notification"
        assert result["data"]["value"][0]["resource"].startswith("chats")
        assert result["data"]["resource"] == "/me/chats/getAllMessages"

    @pytest.mark.asyncio
    async def test_on_channel_message_passthrough(self):
        """The channel-message trigger passes the Graph notification through."""
        config = MicrosoftTeamsNodeConfig(
            config=TeamsOnChannelMessageConfig(
                team_id="t1", channel_id="c1", webhook_url="https://abc.hooks.example.test"
            ),
            credentials=None,
        )
        node = create_teams_node(config)
        result = await node.execute({"value": [{"resource": "teams('t1')/channels('c1')/messages('m1')"}]})
        assert result["status"] == "success"
        assert result["action"] == "on_channel_message"
        assert result["data"]["value"][0]["resource"].startswith("teams")

    @pytest.mark.asyncio
    async def test_on_chat_message_passthrough(self):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsOnChatMessageConfig(chat_id="ch1", webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_teams_node(config)
        result = await node.execute({"value": [{"resource": "chats('ch1')/messages('m1')"}]})
        assert result["status"] == "success"
        assert result["action"] == "on_chat_message"

    @pytest.mark.asyncio
    async def test_channel_message_subscription_resource(self):
        """The channel-message trigger subscribes to the selected channel's messages."""
        captured = {}

        async def fake_req(token, method, endpoint, **kwargs):
            captured["endpoint"] = endpoint
            captured["body"] = kwargs.get("json_body")
            return {"status": "success", "data": {"id": "sub_1"}}

        with patch("nodes.microsoft_teams_node._graph_request", side_effect=fake_req):
            extra = await MicrosoftTeamsNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "tok"},
                config={"operation": "on_channel_message", "team_id": "t1", "channel_id": "c1"},
                node_id="node-1",
            )
        assert extra["external_webhook_id"] == "sub_1"
        assert captured["endpoint"] == "/subscriptions"
        assert captured["body"]["resource"] == "teams/t1/channels/c1/messages"

    @pytest.mark.asyncio
    async def test_chat_message_subscription_resource(self):
        captured = {}

        async def fake_req(token, method, endpoint, **kwargs):
            captured["body"] = kwargs.get("json_body")
            return {"status": "success", "data": {"id": "sub_2"}}

        with patch("nodes.microsoft_teams_node._graph_request", side_effect=fake_req):
            await MicrosoftTeamsNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "tok"},
                config={"operation": "on_chat_message", "chat_id": "ch1"},
                node_id="node-1",
            )
        assert captured["body"]["resource"] == "chats/ch1/messages"

    @pytest.mark.asyncio
    async def test_channel_message_subscription_requires_ids(self):
        """Missing team/channel is a clear error, not a malformed subscription."""
        with pytest.raises(ValueError, match="Team and Channel"):
            await MicrosoftTeamsNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "tok"},
                config={"operation": "on_channel_message"},
                node_id="node-1",
            )

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        with patch(
            "nodes.microsoft_teams_node._graph_request",
            return_value={"status": "success", "data": {"id": "sub_99"}},
        ) as mock_req:
            extra = await MicrosoftTeamsNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={
                    "access_token": "tok",
                    "refresh_token": "rt",
                    "expires_at": "2099-01-01T00:00:00Z",
                },
                config={"resource": "/me/chats/getAllMessages"},
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "sub_99"
        assert extra["signing_secret"]

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.microsoft_teams_node._graph_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await MicrosoftTeamsNode._unregister_external_webhook(
                credential={
                    "access_token": "tok",
                    "refresh_token": "rt",
                    "expires_at": "2099-01-01T00:00:00Z",
                },
                config={"external_webhook_id": "sub_99"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        secret = "topsecret"
        good_body = json.dumps({"value": [{"clientState": secret}]}).encode()
        bad_body = json.dumps({"value": [{"clientState": "wrong"}]}).encode()
        assert MicrosoftTeamsNode.verify_webhook_signature(
            good_body, {}, {"signing_secret": secret}
        )
        assert not MicrosoftTeamsNode.verify_webhook_signature(
            bad_body, {}, {"signing_secret": secret}
        )
        # no secret stored yet -> accept (trigger not armed / validation handshake)
        assert MicrosoftTeamsNode.verify_webhook_signature(good_body, {}, {})


class TestTeamsErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, oauth_credentials):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsGetTeamConfig(team_id="missing"), credentials=oauth_credentials
        )
        node = create_teams_node(config)
        mock_client = create_mock_client(
            404, {"error": {"code": "NotFound", "message": "Team not found"}}
        )
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = MicrosoftTeamsNodeConfig(
            config=TeamsListJoinedTeamsConfig(), credentials=None
        )
        node = create_teams_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestTeamsDynamicOptionsMock:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cursor",
        [
            "http://169.254.169.254/latest/meta-data",
            "https://graph.microsoft.com.evil.example/v1.0/users",
        ],
    )
    async def test_graph_cursor_cannot_exfiltrate_bearer(self, cursor):
        with patch("nodes.microsoft_teams_node.httpx.AsyncClient") as client:
            with pytest.raises(SSRFError, match="outside"):
                await _graph_request("secret-bearer", "GET", cursor)
        client.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_team_options(self):
        cred = {
            "access_token": "tok",
            "refresh_token": "rt",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        with patch(
            "nodes.microsoft_teams_node._graph_request",
            return_value={"status": "success", "data": [{"id": "t1", "displayName": "Eng"}]},
        ):
            result = await MicrosoftTeamsNode.load_field_options("team_id", cred)
        assert "options" in result
        assert result["options"][0]["value"] == "t1"
        assert result["options"][0]["label"] == "Eng"

    @pytest.mark.asyncio
    async def test_load_channel_options(self):
        cred = {
            "access_token": "tok",
            "refresh_token": "rt",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        with patch(
            "nodes.microsoft_teams_node._graph_request",
            return_value={"status": "success", "data": [{"id": "c1", "displayName": "General"}]},
        ):
            result = await MicrosoftTeamsNode.load_field_options(
                "channel_id", cred, context={"team_id": "t1"}
            )
        assert result["options"][0]["value"] == "c1"
        assert result["options"][0]["label"] == "General"

    @pytest.mark.asyncio
    async def test_load_channel_options_without_team_returns_empty(self):
        cred = {
            "access_token": "tok",
            "refresh_token": "rt",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        result = await MicrosoftTeamsNode.load_field_options("channel_id", cred, context={})
        assert result["options"] == []

    @pytest.mark.asyncio
    async def test_load_chat_options(self):
        cred = {
            "access_token": "tok",
            "refresh_token": "rt",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        with patch(
            "nodes.microsoft_teams_node._graph_request",
            return_value={"status": "success", "data": [{"id": "ch1", "topic": "Project X"}]},
        ):
            result = await MicrosoftTeamsNode.load_field_options("chat_id", cred)
        assert result["options"][0]["value"] == "ch1"
        assert result["options"][0]["label"] == "Project X"

    @pytest.mark.asyncio
    async def test_load_membership_options(self):
        cred = {
            "access_token": "tok",
            "refresh_token": "rt",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        with patch(
            "nodes.microsoft_teams_node._graph_request",
            return_value={
                "status": "success",
                "data": [{"id": "mem1", "displayName": "Ada Lovelace"}],
            },
        ):
            result = await MicrosoftTeamsNode.load_field_options(
                "membership_id", cred, context={"team_id": "t1"}
            )
        assert result["options"][0]["value"] == "mem1"
        assert result["options"][0]["label"] == "Ada Lovelace"

    @pytest.mark.asyncio
    async def test_load_membership_options_without_team_returns_empty(self):
        cred = {
            "access_token": "tok",
            "refresh_token": "rt",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        result = await MicrosoftTeamsNode.load_field_options(
            "membership_id", cred, context={}
        )
        assert result["options"] == []

    @pytest.mark.asyncio
    async def test_load_message_options(self):
        cred = {
            "access_token": "tok",
            "refresh_token": "rt",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        with patch(
            "nodes.microsoft_teams_node._graph_request",
            return_value={
                "status": "success",
                "data": [{"id": "m1", "body": {"content": "Release is live"}}],
            },
        ):
            result = await MicrosoftTeamsNode.load_field_options(
                "message_id", cred, context={"team_id": "t1", "channel_id": "c1"}
            )
        assert result["options"][0]["value"] == "m1"
        assert result["options"][0]["label"] == "Release is live"

    @pytest.mark.asyncio
    async def test_load_message_options_without_channel_returns_empty(self):
        cred = {
            "access_token": "tok",
            "refresh_token": "rt",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        result = await MicrosoftTeamsNode.load_field_options(
            "message_id", cred, context={"team_id": "t1"}
        )
        assert result["options"] == []

    @pytest.mark.asyncio
    async def test_load_app_options(self):
        cred = {
            "access_token": "tok",
            "refresh_token": "rt",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        with patch(
            "nodes.microsoft_teams_node._graph_request",
            return_value={
                "status": "success",
                "data": [{"id": "app1", "displayName": "Polls"}],
            },
        ):
            result = await MicrosoftTeamsNode.load_field_options("app_id", cred)
        assert result["options"][0]["value"] == "app1"
        assert result["options"][0]["label"] == "Polls"

    @pytest.mark.asyncio
    async def test_load_user_options(self):
        cred = {
            "access_token": "tok",
            "refresh_token": "rt",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        with patch(
            "nodes.microsoft_teams_node._graph_request",
            return_value={
                "status": "success",
                "data": [
                    {
                        "id": "u1",
                        "displayName": "Grace Hopper",
                        "userPrincipalName": "grace@example.com",
                    }
                ],
            },
        ):
            result = await MicrosoftTeamsNode.load_field_options("user_id", cred)
        assert result["options"][0]["value"] == "u1"
        assert result["options"][0]["label"] == "Grace Hopper"


def _capture_client(status_code=200, json_data=None):
    """Mock httpx client recording the request (method/url/json)."""
    captured = {}
    mock_response = create_mock_response(status_code, json_data or {}, None)

    async def async_request(*args, **kwargs):
        captured.update(kwargs)
        return mock_response

    mock_client = Mock()
    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *a):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client, captured


async def _run_capture(node, mock_client):
    with patch("nodes.microsoft_teams_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


class TestTeamsAdditionalOpsMock:
    """New coverage operations, asserting the exact Graph endpoint hit."""

    @pytest.mark.asyncio
    async def test_update_team(self, oauth_credentials):
        node = create_teams_node(MicrosoftTeamsNodeConfig(
            config=TeamsUpdateTeamConfig(team_id="t1", body='{"description": "x"}'),
            credentials=oauth_credentials))
        client, cap = _capture_client(204)
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["method"] == "PATCH"
        assert cap["url"].endswith("/teams/t1")
        assert cap["json"] == {"description": "x"}

    @pytest.mark.asyncio
    async def test_archive_team(self, oauth_credentials):
        node = create_teams_node(MicrosoftTeamsNodeConfig(
            config=TeamsArchiveTeamConfig(team_id="t1"), credentials=oauth_credentials))
        client, cap = _capture_client(202)
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["method"] == "POST"
        assert cap["url"].endswith("/teams/t1/archive")

    @pytest.mark.asyncio
    async def test_unarchive_team(self, oauth_credentials):
        node = create_teams_node(MicrosoftTeamsNodeConfig(
            config=TeamsUnarchiveTeamConfig(team_id="t1"), credentials=oauth_credentials))
        client, cap = _capture_client(202)
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["url"].endswith("/teams/t1/unarchive")

    @pytest.mark.asyncio
    async def test_update_channel(self, oauth_credentials):
        node = create_teams_node(MicrosoftTeamsNodeConfig(
            config=TeamsUpdateChannelConfig(team_id="t1", channel_id="c1", body='{"displayName": "R"}'),
            credentials=oauth_credentials))
        client, cap = _capture_client(200, {"id": "c1"})
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["method"] == "PATCH"
        assert cap["url"].endswith("/teams/t1/channels/c1")

    @pytest.mark.asyncio
    async def test_list_channel_members(self, oauth_credentials):
        node = create_teams_node(MicrosoftTeamsNodeConfig(
            config=TeamsListChannelMembersConfig(team_id="t1", channel_id="c1"),
            credentials=oauth_credentials))
        client, cap = _capture_client(200, _collection([{"id": "m1"}]))
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["method"] == "GET"
        assert cap["url"].endswith("/teams/t1/channels/c1/members")

    @pytest.mark.asyncio
    async def test_get_chat_message(self, oauth_credentials):
        node = create_teams_node(MicrosoftTeamsNodeConfig(
            config=TeamsGetChatMessageConfig(chat_id="ch1", message_id="m1"),
            credentials=oauth_credentials))
        client, cap = _capture_client(200, {"id": "m1"})
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["url"].endswith("/chats/ch1/messages/m1")

    @pytest.mark.asyncio
    async def test_list_chat_members(self, oauth_credentials):
        node = create_teams_node(MicrosoftTeamsNodeConfig(
            config=TeamsListChatMembersConfig(chat_id="ch1"), credentials=oauth_credentials))
        client, cap = _capture_client(200, _collection([{"id": "m1"}]))
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["url"].endswith("/chats/ch1/members")

    @pytest.mark.asyncio
    async def test_delete_channel_tab(self, oauth_credentials):
        node = create_teams_node(MicrosoftTeamsNodeConfig(
            config=TeamsDeleteChannelTabConfig(team_id="t1", channel_id="c1", tab_id="tab1"),
            credentials=oauth_credentials))
        client, cap = _capture_client(204)
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["method"] == "DELETE"
        assert cap["url"].endswith("/teams/t1/channels/c1/tabs/tab1")

    @pytest.mark.asyncio
    async def test_uninstall_app(self, oauth_credentials):
        node = create_teams_node(MicrosoftTeamsNodeConfig(
            config=TeamsUninstallAppConfig(team_id="t1", installation_id="inst1"),
            credentials=oauth_credentials))
        client, cap = _capture_client(204)
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["method"] == "DELETE"
        assert cap["url"].endswith("/teams/t1/installedApps/inst1")

    @pytest.mark.asyncio
    async def test_get_my_presence(self, oauth_credentials):
        node = create_teams_node(MicrosoftTeamsNodeConfig(
            config=TeamsGetMyPresenceConfig(), credentials=oauth_credentials))
        client, cap = _capture_client(200, {"availability": "Available"})
        result = await _run_capture(node, client)
        assert result["status"] == "success"
        assert cap["url"].endswith("/me/presence")
