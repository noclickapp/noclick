"""Capture real HTTP requests for methods whose encodings differ from JSON.

Sources: https://docs.slack.dev/reference/methods/ and the matching methods in
https://github.com/slackapi/python-slack-sdk/blob/main/slack_sdk/web/async_client.py
No response is fabricated: the transport stops after capturing the request.
"""

import json
from urllib.parse import parse_qs
from unittest.mock import patch

import httpx
import pytest

from nodes.slack_node import SlackNode, SlackNodeConfig


class RequestCaptured(Exception):
    def __init__(self, request):
        self.request = request


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,endpoint,method,config,expected",
    [
        ("delete_user_profile_photo", "users.deletePhoto", "GET", {}, {}),
        (
            "set_channel_external_invite_permissions",
            "conversations.externalInvitePermissions.set",
            "POST",
            {
                "channel": "C123456",
                "target_team": "T726G27TT",
                "action_type": "upgrade",
            },
            {"channel": "C123456", "target_team": "T726G27TT", "action": "upgrade"},
        ),
        (
            "create_information_barrier",
            "admin.barriers.create",
            "POST",
            {
                "primary_usergroup_id": "S12345678",
                "barriered_from_usergroup_ids": ["S11111111", "S22222222"],
                "restricted_subjects": ["im", "mpim", "call"],
            },
            {
                "primary_usergroup_id": "S12345678",
                "barriered_from_usergroup_ids": "S11111111,S22222222",
                "restricted_subjects": "im,mpim,call",
            },
        ),
        (
            "delete_information_barrier",
            "admin.barriers.delete",
            "POST",
            {"barrier_id": "Ba03T70KB2H3"},
            {"barrier_id": "Ba03T70KB2H3"},
        ),
        (
            "update_information_barrier",
            "admin.barriers.update",
            "POST",
            {
                "barrier_id": "Ba03T70KB2H3",
                "primary_usergroup_id": "S12345678",
                "barriered_from_usergroup_ids": ["S11111111", "S22222222"],
                "restricted_subjects": ["im", "mpim", "call"],
            },
            {
                "barrier_id": "Ba03T70KB2H3",
                "primary_usergroup_id": "S12345678",
                "barriered_from_usergroup_ids": "S11111111,S22222222",
                "restricted_subjects": "im,mpim,call",
            },
        ),
        (
            "bulk_archive_conversations",
            "admin.conversations.bulkArchive",
            "POST",
            {"channel_ids": ["C11111111", "C22222222"]},
            {"channel_ids": "C11111111,C22222222"},
        ),
        (
            "bulk_delete_conversations",
            "admin.conversations.bulkDelete",
            "POST",
            {"channel_ids": ["C11111111", "C22222222"]},
            {"channel_ids": "C11111111,C22222222"},
        ),
        (
            "bulk_move_conversations_to_team",
            "admin.conversations.bulkMove",
            "POST",
            {"channel_ids": ["C11111111", "C22222222"], "target_team_id": "T12345678"},
            {"channel_ids": "C11111111,C22222222", "target_team_id": "T12345678"},
        ),
        (
            "add_idp_group_to_channel",
            "admin.conversations.restrictAccess.addGroup",
            "GET",
            {"channel_id": "C12345678", "group_id": "S12345678"},
            {"channel_id": "C12345678", "group_id": "S12345678"},
        ),
        (
            "remove_idp_group_from_channel",
            "admin.conversations.restrictAccess.removeGroup",
            "GET",
            {"channel_id": "C12345678", "group_id": "S12345678", "team_id": "T12345678"},
            {"channel_id": "C12345678", "group_id": "S12345678", "team_id": "T12345678"},
        ),
        (
            "add_custom_emoji",
            "admin.emoji.add",
            "GET",
            {"name": "party", "url": "https://example.com/party.png"},
            {"name": "party", "url": "https://example.com/party.png"},
        ),
        (
            "add_emoji_alias",
            "admin.emoji.addAlias",
            "GET",
            {"name": "party", "alias_for": "tada"},
            {"name": "party", "alias_for": "tada"},
        ),
        (
            "remove_custom_emoji",
            "admin.emoji.remove",
            "GET",
            {"name": "party"},
            {"name": "party"},
        ),
        (
            "rename_custom_emoji",
            "admin.emoji.rename",
            "GET",
            {"name": "party", "new_name": "celebrate"},
            {"name": "party", "new_name": "celebrate"},
        ),
        (
            "set_default_channels_for_team",
            "admin.teams.settings.setDefaultChannels",
            "GET",
            {"team_id": "T12345678", "channel_ids": ["C11111111", "C22222222"]},
            {"team_id": "T12345678", "channel_ids": "C11111111,C22222222"},
        ),
        (
            "set_team_icon",
            "admin.teams.settings.setIcon",
            "GET",
            {"team_id": "T12345678", "image_url": "https://example.com/icon.png"},
            {"team_id": "T12345678", "image_url": "https://example.com/icon.png"},
        ),
        (
            "set_workflow_trigger_type_permissions",
            "admin.workflows.triggers.types.permissions.set",
            "JSON",
            {"trigger_type_id": "FTT01", "visibility": "everyone"},
            {"id": "FTT01", "visibility": "everyone"},
        ),
        (
            "invalidate_user_session",
            "admin.users.session.invalidate",
            "JSON",
            {"session_id": "12345", "team_id": "T12345678"},
            {"session_id": 12345, "team_id": "T12345678"},
        ),
        (
            "uninstall_app_from_workspace",
            "apps.uninstall",
            "GET",
            {},
            {"client_id": "123456789.987654321", "client_secret": "fake-client-secret"},
        ),
    ],
)
async def test_slack_request_contract(operation, endpoint, method, config, expected):
    config = SlackNodeConfig.model_validate(
        {
            "config": {"operation": operation, **config},
            "credentials": {
                "credential_type": "slack_bot_token",
                "bot_token": "xoxb-fake-token",
                "client_id": "123456789.987654321",
                "client_secret": "fake-client-secret",
            },
        }
    )
    node = SlackNode(
        node_id="contract",
        node_type="automation-slack",
        node_data={},
        config=config,
        sio=None,
    )
    real_client = httpx.AsyncClient

    def capture(request):
        raise RequestCaptured(request)

    def client(*args, **kwargs):
        return real_client(*args, **kwargs, transport=httpx.MockTransport(capture))

    with patch("httpx.AsyncClient", client), pytest.raises(RequestCaptured) as captured:
        await node.execute({})

    request = captured.value.request
    assert request.url.path == f"/api/{endpoint}"
    assert request.headers["authorization"] == "Bearer xoxb-fake-token"
    assert request.method == ("POST" if method == "JSON" else method)
    if method == "JSON":
        assert json.loads(request.content) == expected
    else:
        if method == "GET":
            assert not request.content
            assert "content-type" not in request.headers
            encoded = request.url.query.decode()
        else:
            assert (
                request.headers["content-type"] == "application/x-www-form-urlencoded"
            )
            encoded = request.content.decode()
        assert parse_qs(encoded) == {key: [value] for key, value in expected.items()}


def test_external_invite_permissions_requires_target_team():
    with pytest.raises(ValueError, match="target_team"):
        SlackNodeConfig.model_validate(
            {
                "config": {
                    "operation": "set_channel_external_invite_permissions",
                    "channel": "C123456",
                    "action_type": "upgrade",
                }
            }
        )
