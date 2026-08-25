"""
Mock tests for Slack Web API node.

Tests 96 Slack operations using mocked httpx responses.
No actual Slack API calls are made - tests verify correct URL construction,
request body formation, and response handling.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

# Import the node and all config classes
from nodes.slack_node import (
    SlackNode,
    SlackNodeConfig,
    SlackBotTokenCredential,
    SlackOAuthCredential,
    # Messaging operations (6)
    SlackPostMessageConfig,
    SlackUpdateMessageConfig,
    SlackDeleteMessageConfig,
    SlackPostEphemeralConfig,
    SlackScheduleMessageConfig,
    SlackGetPermalinkConfig,
    # Conversation operations (18 - original 14 + 4 new)
    SlackListConversationsConfig,
    SlackConversationInfoConfig,
    SlackConversationHistoryConfig,
    SlackConversationMembersConfig,
    SlackJoinConversationConfig,
    SlackLeaveConversationConfig,
    SlackCreateConversationConfig,
    SlackArchiveConversationConfig,
    SlackUnarchiveConversationConfig,
    SlackInviteToConversationConfig,
    SlackKickFromConversationConfig,
    SlackSetConversationTopicConfig,
    SlackSetConversationPurposeConfig,
    SlackRenameConversationConfig,
    SlackConversationRepliesConfig,
    SlackOpenConversationConfig,
    SlackCloseConversationConfig,
    SlackMarkConversationConfig,
    # User operations (5 - original 4 + 1 new)
    SlackListUsersConfig,
    SlackUserInfoConfig,
    SlackLookupUserByEmailConfig,
    SlackGetUserPresenceConfig,
    SlackUsersConversationsConfig,
    # Bookmark operations (4 new)
    SlackAddBookmarkConfig,
    SlackEditBookmarkConfig,
    SlackListBookmarksConfig,
    SlackRemoveBookmarkConfig,
    # User Group operations (7 new)
    SlackListUserGroupsConfig,
    SlackCreateUserGroupConfig,
    SlackDisableUserGroupConfig,
    SlackEnableUserGroupConfig,
    SlackUpdateUserGroupConfig,
    SlackListUserGroupUsersConfig,
    SlackUpdateUserGroupUsersConfig,
    # DND operations (5 new)
    SlackDndSetSnoozeConfig,
    SlackDndEndSnoozeConfig,
    SlackDndEndDndConfig,
    SlackDndInfoConfig,
    SlackDndTeamInfoConfig,
    # Emoji operations (1 new)
    SlackListEmojiConfig,
    # Star operations (3 new)
    SlackAddStarConfig,
    SlackRemoveStarConfig,
    SlackListStarsConfig,
    # Bot operations (1 new)
    SlackBotInfoConfig,
    # Reminder operations (5 new)
    SlackAddReminderConfig,
    SlackCompleteReminderConfig,
    SlackDeleteReminderConfig,
    SlackReminderInfoConfig,
    SlackListRemindersConfig,
    # Reaction operations (3)
    SlackAddReactionConfig,
    SlackRemoveReactionConfig,
    SlackGetReactionsConfig,
    # Pin operations (3)
    SlackAddPinConfig,
    SlackRemovePinConfig,
    SlackListPinsConfig,
    # File operations (6)
    SlackListFilesConfig,
    SlackFileInfoConfig,
    SlackDeleteFileConfig,
    SlackUploadFileConfig,
    SlackGetFilePublicURLConfig,
    SlackRevokeFilePublicURLConfig,
    # Search operations (3)
    SlackSearchMessagesConfig,
    SlackSearchFilesConfig,
    SlackSearchAllConfig,
    # Scheduled message operations (2)
    SlackDeleteScheduledMessageConfig,
    SlackListScheduledMessagesConfig,
    # Chat extras (2)
    SlackMeMessageConfig,
    SlackUnfurlConfig,
    # User profile operations (2)
    SlackGetUserProfileConfig,
    SlackSetUserPresenceConfig,
    # Team/Auth operations (6)
    SlackAuthTestConfig,
    SlackTeamInfoConfig,
    SlackApiTestConfig,
    SlackAuthRevokeConfig,
    SlackAppsUninstallConfig,
    SlackTeamBillableInfoConfig,
    SlackTeamAccessLogsConfig,
    SlackTeamIntegrationLogsConfig,
    # Slack Connect operations (3)
    SlackConversationsAcceptSharedInviteConfig,
    SlackConversationsDeclineSharedInviteConfig,
    SlackConversationsListConnectInvitesConfig,
    # New file upload operations (2)
    SlackGetUploadURLExternalConfig,
    SlackCompleteUploadExternalConfig,
    # User profile operations (1)
    SlackSetUserProfileConfig,
    # Additional Slack Connect operations (2)
    SlackApproveSharedInviteConfig,
    SlackInviteSharedConfig,
    # Remote file operations (4)
    SlackAddRemoteFileConfig,
    SlackRemoveRemoteFileConfig,
    SlackShareRemoteFileConfig,
    SlackListRemoteFilesConfig,
    # Additional reactions operations (1)
    SlackListReactionsConfig,
    # Additional remote file operations (2)
    SlackRemoteFileInfoConfig,
    SlackRemoteFileUpdateConfig,
    # File comment operations (1)
    SlackDeleteFileCommentConfig,
    # Additional user operations (2)
    SlackDeleteUserPhotoConfig,
    SlackSetUserActiveConfig,
    # Canvas operations (1)
    SlackCreateCanvasConfig,
    # Additional Slack Connect operations (4)
    SlackSetExternalInvitePermissionsConfig,
    SlackApproveSharedInviteRequestConfig,
    SlackDenySharedInviteRequestConfig,
    SlackListSharedInviteRequestsConfig,
    # Admin API operations (90 total - importing representative sample for testing)
    # admin.analytics (1)
    SlackAdminAnalyticsGetFileConfig,
    # admin.apps (11 - sample)
    SlackAdminAppsApprovedListConfig,
    SlackAdminAppsRestrictedListConfig,
    # admin.barriers (4 - sample)
    SlackAdminBarriersListConfig,
    SlackAdminBarriersCreateConfig,
    # admin.conversations (26 - sample)
    SlackAdminConversationsSearchConfig,
    SlackAdminConversationsArchiveConfig,
    SlackAdminConversationsCreateConfig,
    # admin.emoji (5 - sample)
    SlackAdminEmojiListConfig,
    SlackAdminEmojiAddConfig,
    # admin.functions (3 - sample)
    SlackAdminFunctionsListConfig,
    # admin.inviteRequests (5 - sample)
    SlackAdminInviteRequestsListConfig,
    SlackAdminInviteRequestsApproveConfig,
    # admin.roles (3 - sample)
    SlackAdminRolesListAssignmentsConfig,
    # admin.teams (10 - sample)
    SlackAdminTeamsListConfig,
    SlackAdminTeamsCreateConfig,
    # admin.usergroups (4 - sample)
    SlackAdminUsergroupsListChannelsConfig,
    SlackAdminUsergroupsAddChannelsConfig,
    # admin.users (17 - sample)
    SlackAdminUsersListConfig,
    SlackAdminUsersInviteConfig,
    SlackAdminUsersSessionListConfig,
    # admin.workflows (7 - sample)
    SlackAdminWorkflowsSearchConfig,
    SlackAdminWorkflowsUnpublishConfig,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def bot_credentials():
    """Create bot token credentials."""
    return SlackBotTokenCredential(bot_token="xoxb-test-token-12345")


@pytest.fixture
def oauth_credentials():
    """Create OAuth credentials."""
    return SlackOAuthCredential(
        access_token="xoxp-oauth-token-12345",
        refresh_token="refresh-token",
        team_id="T12345678",
        team_name="Test Team",
    )


def create_node(config, credentials) -> SlackNode:
    """Helper to create a SlackNode with given config and credentials."""
    node_config = SlackNodeConfig(config=config, credentials=credentials)
    return SlackNode(
        node_id="test-node",
        node_type="automation-slack",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


def mock_slack_response(data: dict, ok: bool = True):
    """Create a mock httpx response for Slack API."""
    response_data = {"ok": ok, **data}
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = response_data
    response.text = str(response_data)
    return response


# ============================================================================
# Messaging Operations Tests (6 operations)
# ============================================================================


class TestMessagingOperations:
    """Test messaging-related Slack API operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_post_message(self, mock_client_class, bot_credentials):
        """Test posting a message."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {
                "channel": "C12345678",
                "ts": "1234567890.123456",
                "message": {"text": "Hello World"},
            }
        )

        config = SlackPostMessageConfig(channel="C12345678", text="Hello World")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "send_message_to_channel"
        assert result["data"]["ts"] == "1234567890.123456"
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_update_message(self, mock_client_class, bot_credentials):
        """Test updating a message."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"channel": "C12345678", "ts": "1234567890.123456"}
        )

        config = SlackUpdateMessageConfig(
            channel="C12345678", ts="1234567890.123456", text="Updated message"
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "update_existing_message"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_delete_message(self, mock_client_class, bot_credentials):
        """Test deleting a message."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"channel": "C12345678", "ts": "1234567890.123456"}
        )

        config = SlackDeleteMessageConfig(channel="C12345678", ts="1234567890.123456")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_message"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_post_ephemeral(self, mock_client_class, bot_credentials):
        """Test posting an ephemeral message."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"message_ts": "1234567890.123456"}
        )

        config = SlackPostEphemeralConfig(
            channel="C12345678", user="U12345678", text="Secret message"
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "send_ephemeral_message"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_schedule_message(self, mock_client_class, bot_credentials):
        """Test scheduling a message."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"scheduled_message_id": "Q12345678", "post_at": "1234567890"}
        )

        config = SlackScheduleMessageConfig(
            channel="C12345678", text="Scheduled message", post_at=1234567890
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "schedule_message_for_later"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_get_permalink(self, mock_client_class, bot_credentials):
        """Test getting a message permalink."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"permalink": "https://team.slack.com/archives/C12345678/p1234567890123456"}
        )

        config = SlackGetPermalinkConfig(
            channel="C12345678", message_ts="1234567890.123456"
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_message_permalink"
        assert "permalink" in result["data"]


# ============================================================================
# Conversation Operations Tests (18 operations)
# ============================================================================


class TestConversationOperations:
    """Test conversation-related Slack API operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_list_conversations(self, mock_client_class, bot_credentials):
        """Test listing conversations."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"channels": [{"id": "C12345678", "name": "general"}]}
        )

        config = SlackListConversationsConfig(limit=10)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_channels_in_workspace"
        assert "channels" in result["data"]

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_conversation_info(self, mock_client_class, bot_credentials):
        """Test getting conversation info."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"channel": {"id": "C12345678", "name": "general"}}
        )

        config = SlackConversationInfoConfig(channel="C12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_channel_information"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_conversation_history(self, mock_client_class, bot_credentials):
        """Test getting conversation history."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"messages": [{"text": "Hello", "ts": "1234567890.123456"}]}
        )

        config = SlackConversationHistoryConfig(channel="C12345678", limit=10)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_channel_messages"
        assert "messages" in result["data"]

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_conversation_members(self, mock_client_class, bot_credentials):
        """Test getting conversation members."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"members": ["U12345678", "U87654321"]}
        )

        config = SlackConversationMembersConfig(channel="C12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_channel_members"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_join_conversation(self, mock_client_class, bot_credentials):
        """Test joining a conversation."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"channel": {"id": "C12345678"}}
        )

        config = SlackJoinConversationConfig(channel="C12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "join_public_channel"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_leave_conversation(self, mock_client_class, bot_credentials):
        """Test leaving a conversation."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackLeaveConversationConfig(channel="C12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "leave_channel"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_create_conversation(self, mock_client_class, bot_credentials):
        """Test creating a conversation."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"channel": {"id": "C12345678", "name": "new-channel"}}
        )

        config = SlackCreateConversationConfig(name="new-channel")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_channel"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_conversation_replies(self, mock_client_class, bot_credentials):
        """Test getting thread replies."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"messages": [{"text": "Reply", "ts": "1234567890.123457"}]}
        )

        config = SlackConversationRepliesConfig(
            channel="C12345678", ts="1234567890.123456"
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_thread_replies"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_open_conversation(self, mock_client_class, bot_credentials):
        """Test opening a DM conversation."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"channel": {"id": "D12345678"}}
        )

        config = SlackOpenConversationConfig(users="U12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "open_direct_message"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_close_conversation(self, mock_client_class, bot_credentials):
        """Test closing a conversation."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackCloseConversationConfig(channel="C12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "close_direct_message"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_mark_conversation(self, mock_client_class, bot_credentials):
        """Test marking a conversation as read."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackMarkConversationConfig(
            channel="C12345678", ts="1234567890.123456"
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "mark_channel_as_read"


# ============================================================================
# User Operations Tests (5 operations)
# ============================================================================


class TestUserOperations:
    """Test user-related Slack API operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_list_users(self, mock_client_class, bot_credentials):
        """Test listing users."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"members": [{"id": "U12345678", "name": "testuser"}]}
        )

        config = SlackListUsersConfig(limit=10)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_workspace_users"
        assert "members" in result["data"]

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_user_info(self, mock_client_class, bot_credentials):
        """Test getting user info."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"user": {"id": "U12345678", "name": "testuser"}}
        )

        config = SlackUserInfoConfig(user="U12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_user_information"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_users_conversations(self, mock_client_class, bot_credentials):
        """Test getting user's conversations."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"channels": [{"id": "C12345678", "name": "general"}]}
        )

        config = SlackUsersConversationsConfig(user="U12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_user_accessible_conversations"


# ============================================================================
# Bookmark Operations Tests (4 operations)
# ============================================================================


class TestBookmarkOperations:
    """Test bookmark-related Slack API operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_add_bookmark(self, mock_client_class, bot_credentials):
        """Test adding a bookmark."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"bookmark": {"id": "Bk12345678", "title": "Important Link"}}
        )

        config = SlackAddBookmarkConfig(
            channel_id="C12345678", title="Important Link", link="https://example.com"
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "add_bookmark_to_channel"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_list_bookmarks(self, mock_client_class, bot_credentials):
        """Test listing bookmarks."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"bookmarks": [{"id": "Bk12345678", "title": "Important Link"}]}
        )

        config = SlackListBookmarksConfig(channel_id="C12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_channel_bookmarks"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_remove_bookmark(self, mock_client_class, bot_credentials):
        """Test removing a bookmark."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackRemoveBookmarkConfig(
            channel_id="C12345678", bookmark_id="Bk12345678"
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "remove_channel_bookmark"


# ============================================================================
# User Group Operations Tests (7 operations)
# ============================================================================


class TestUserGroupOperations:
    """Test user group-related Slack API operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_list_usergroups(self, mock_client_class, bot_credentials):
        """Test listing user groups."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"usergroups": [{"id": "S12345678", "name": "Engineering"}]}
        )

        config = SlackListUserGroupsConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_workspace_user_groups"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_create_usergroup(self, mock_client_class, bot_credentials):
        """Test creating a user group."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"usergroup": {"id": "S12345678", "name": "New Group"}}
        )

        config = SlackCreateUserGroupConfig(name="New Group")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_user_group"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_list_usergroup_users(self, mock_client_class, bot_credentials):
        """Test listing users in a user group."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"users": ["U12345678", "U87654321"]}
        )

        config = SlackListUserGroupUsersConfig(usergroup="S12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_usergroup_members"


# ============================================================================
# DND Operations Tests (5 operations)
# ============================================================================


class TestDndOperations:
    """Test DND-related Slack API operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_dnd_set_snooze(self, mock_client_class, bot_credentials):
        """Test setting snooze."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"snooze_enabled": True, "snooze_endtime": 1234567890}
        )

        config = SlackDndSetSnoozeConfig(num_minutes=60)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "set_do_not_disturb_snooze"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_dnd_end_snooze(self, mock_client_class, bot_credentials):
        """Test ending snooze."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({"dnd_enabled": False})

        config = SlackDndEndSnoozeConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "end_snooze_mode"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_dnd_info(self, mock_client_class, bot_credentials):
        """Test getting DND info."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"dnd_enabled": True, "next_dnd_start_ts": 1234567890}
        )

        config = SlackDndInfoConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_do_not_disturb_status"


# ============================================================================
# Star, Emoji, Bot, Reminder Operations Tests
# ============================================================================


class TestMiscOperations:
    """Test miscellaneous Slack API operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_list_emoji(self, mock_client_class, bot_credentials):
        """Test listing custom emoji."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"emoji": {"thumbsup": "https://example.com/thumbsup.png"}}
        )

        config = SlackListEmojiConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_custom_emoji_in_workspace"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_add_star(self, mock_client_class, bot_credentials):
        """Test adding a star."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackAddStarConfig(channel="C12345678", timestamp="1234567890.123456")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "star_message_or_file"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_list_stars(self, mock_client_class, bot_credentials):
        """Test listing stars."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"items": [{"type": "message"}]}
        )

        config = SlackListStarsConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_user_starred_items"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_bot_info(self, mock_client_class, bot_credentials):
        """Test getting bot info."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"bot": {"id": "B12345678", "name": "TestBot"}}
        )

        config = SlackBotInfoConfig(bot="B12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_bot_information"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_add_reminder(self, mock_client_class, bot_credentials):
        """Test adding a reminder."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"reminder": {"id": "Rm12345678", "text": "Do something"}}
        )

        config = SlackAddReminderConfig(text="Do something", time="in 1 hour")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_reminder"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_list_reminders(self, mock_client_class, bot_credentials):
        """Test listing reminders."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"reminders": [{"id": "Rm12345678", "text": "Do something"}]}
        )

        config = SlackListRemindersConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_user_reminders"


# ============================================================================
# Reaction, Pin, File, Search Operations Tests
# ============================================================================


class TestReactionPinFileOperations:
    """Test reaction, pin, file, and search operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_add_reaction(self, mock_client_class, bot_credentials):
        """Test adding a reaction."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackAddReactionConfig(
            channel="C12345678", timestamp="1234567890.123456", name="thumbsup"
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "add_emoji_reaction_to_message"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_list_pins(self, mock_client_class, bot_credentials):
        """Test listing pins."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"items": [{"type": "message"}]}
        )

        config = SlackListPinsConfig(channel="C12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_pinned_items_in_channel"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_list_files(self, mock_client_class, bot_credentials):
        """Test listing files."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"files": [{"id": "F12345678", "name": "test.txt"}]}
        )

        config = SlackListFilesConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_workspace_files"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_search_messages(self, mock_client_class, bot_credentials):
        """Test searching messages."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"messages": {"matches": [{"text": "Hello"}]}}
        )

        config = SlackSearchMessagesConfig(query="hello")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "search_workspace_messages"


# ============================================================================
# Team/Auth Operations Tests
# ============================================================================


class TestTeamAuthOperations:
    """Test team and auth operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_auth_test(self, mock_client_class, bot_credentials):
        """Test auth.test."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"user_id": "U12345678", "team_id": "T12345678", "user": "testuser"}
        )

        config = SlackAuthTestConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "test_authentication"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_team_info(self, mock_client_class, bot_credentials):
        """Test getting team info."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"team": {"id": "T12345678", "name": "Test Team"}}
        )

        config = SlackTeamInfoConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_workspace_information"


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_api_error_response(self, mock_client_class, bot_credentials):
        """Test handling API error responses."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"error": "channel_not_found"}, ok=False
        )

        config = SlackConversationInfoConfig(channel="C00000000")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "error"
        assert "channel_not_found" in result["error"]

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_not_in_channel_error_includes_accessible_channels_hint(
        self, mock_client_class, bot_credentials
    ):
        """When Slack returns not_in_channel, the node fetches the bot's
        accessible-channels list and appends it to the error string so the
        caller (LLM or human) can recover in one step instead of spawning
        scratch list_channels / join_channel nodes."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        # Two sequential GETs: the original conversations.history call returns
        # the channel-access error, then the enrichment's users.conversations
        # call returns the bot's accessible-channels list.
        mock_client.get.side_effect = [
            mock_slack_response({"error": "not_in_channel"}, ok=False),
            mock_slack_response({
                "channels": [
                    {"id": "C0000000001", "name": "general"},
                    {"id": "C0000000002", "name": "checks"},
                ],
            }),
        ]

        config = SlackConversationHistoryConfig(channel="C0000000003")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "error"
        assert "not_in_channel" in result["error"]
        # Accessible-channel names + IDs should be inlined so the caller
        # can swap the channel field without another round trip.
        assert "#general" in result["error"]
        assert "C0000000001" in result["error"]
        assert "#checks" in result["error"]
        # Confirm the enrichment GET was issued against the right Slack endpoint.
        second_call = mock_client.get.call_args_list[1]
        assert "users.conversations" in second_call.args[0]

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_channel_error_hint_falls_back_silently_when_lookup_fails(
        self, mock_client_class, bot_credentials
    ):
        """The enrichment is best-effort — if users.conversations itself fails
        (missing scope, network blip, etc.) we surface the bare Slack error
        rather than letting the hint helper mask it."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.side_effect = [
            mock_slack_response({"error": "not_in_channel"}, ok=False),
            mock_slack_response({"error": "missing_scope"}, ok=False),
        ]

        config = SlackConversationHistoryConfig(channel="C0000000003")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "error"
        assert "not_in_channel" in result["error"]
        # No "bot has access to" decoration when the enrichment lookup fails.
        assert "bot has access to" not in result["error"]

    @pytest.mark.asyncio
    async def test_missing_credentials(self, bot_credentials):
        """Test handling missing credentials."""
        config = SlackListConversationsConfig()
        node_config = SlackNodeConfig(config=config, credentials=None)
        node = SlackNode(
            node_id="test-node",
            node_type="automation-slack",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_oauth_credentials(self, mock_client_class, oauth_credentials):
        """Test using OAuth credentials."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({"user_id": "U12345678"})

        config = SlackAuthTestConfig()
        node = create_node(config, oauth_credentials)
        result = await node.execute({})

        assert result["status"] == "success"


# ============================================================================
# Additional File Operations Tests
# ============================================================================


class TestAdditionalFileOperations:
    """Tests for additional file operations (upload, public URL)."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_upload_file(self, mock_client_class, bot_credentials):
        """Test uploading a file to Slack."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        upload_meta_response = MagicMock(spec=httpx.Response)
        upload_meta_response.status_code = 200
        upload_meta_response.json.return_value = {
            "ok": True,
            "upload_url": "https://uploads.slack.test/file",
            "file_id": "F12345678",
        }
        mock_client.get.return_value = upload_meta_response

        upload_binary_response = MagicMock(spec=httpx.Response)
        upload_binary_response.status_code = 200

        complete_response = MagicMock(spec=httpx.Response)
        complete_response.status_code = 200
        complete_response.json.return_value = {
            "ok": True,
            "files": [{"id": "F12345678", "name": "test.txt"}],
        }
        mock_client.post.side_effect = [upload_binary_response, complete_response]

        config = SlackUploadFileConfig(
            channels="C12345678",
            content="Hello World",
            filename="test.txt",
            title="Test File",
        )
        node = create_node(config, bot_credentials)
        with patch(
            "nodes.slack_node.assert_url_allowed", new_callable=AsyncMock
        ):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "upload_file_to_slack"
        assert "file" in result

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_upload_file_with_async_json_response(
        self, mock_client_class, bot_credentials
    ):
        """Handle environments where response.json() is awaitable."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        upload_meta_response = MagicMock(spec=httpx.Response)
        upload_meta_response.status_code = 200
        upload_meta_response.json = AsyncMock(
            return_value={
                "ok": True,
                "upload_url": "https://uploads.slack.test/file",
                "file_id": "F12345678",
            }
        )
        mock_client.get.return_value = upload_meta_response

        upload_binary_response = MagicMock(spec=httpx.Response)
        upload_binary_response.status_code = 200

        complete_response = MagicMock(spec=httpx.Response)
        complete_response.status_code = 200
        complete_response.json.return_value = {
            "ok": True,
            "files": [{"id": "F12345678", "name": "test.txt"}],
        }
        mock_client.post.side_effect = [upload_binary_response, complete_response]

        config = SlackUploadFileConfig(
            channels="C12345678",
            content="Hello World",
            filename="test.txt",
            title="Test File",
        )
        node = create_node(config, bot_credentials)
        with patch(
            "nodes.slack_node.assert_url_allowed", new_callable=AsyncMock
        ):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "upload_file_to_slack"
        assert result["file"]["id"] == "F12345678"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_upload_file_rejects_private_provider_upload_url(
        self, mock_client_class, bot_credentials
    ):
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        upload_meta_response = MagicMock(spec=httpx.Response)
        upload_meta_response.status_code = 200
        upload_meta_response.json.return_value = {
            "ok": True,
            "upload_url": "http://169.254.169.254/latest/meta-data",
            "file_id": "F12345678",
        }
        mock_client.get.return_value = upload_meta_response

        node = create_node(
            SlackUploadFileConfig(content="secret bytes", filename="test.txt"),
            bot_credentials,
        )
        with pytest.raises(ValueError, match="non-public address"):
            await node.execute({})
        mock_client.post.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_get_file_public_url(self, mock_client_class, bot_credentials):
        """Test getting a public URL for a file."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {
                "file": {
                    "id": "F12345678",
                    "permalink_public": "https://slack.com/files/...",
                }
            }
        )

        config = SlackGetFilePublicURLConfig(file="F12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_file_public_url"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_revoke_file_public_url(self, mock_client_class, bot_credentials):
        """Test revoking a public URL for a file."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"file": {"id": "F12345678"}}
        )

        config = SlackRevokeFilePublicURLConfig(file="F12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "revoke_file_public_url"


# ============================================================================
# Additional Search Operations Tests
# ============================================================================


class TestAdditionalSearchOperations:
    """Tests for additional search operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_search_files(self, mock_client_class, bot_credentials):
        """Test searching for files."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"files": {"matches": [{"id": "F12345678", "name": "test.txt"}]}}
        )

        config = SlackSearchFilesConfig(query="test")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "search_workspace_files"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_search_all(self, mock_client_class, bot_credentials):
        """Test searching for all (messages and files)."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"messages": {"matches": []}, "files": {"matches": []}}
        )

        config = SlackSearchAllConfig(query="test")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "search_messages_and_files"


# ============================================================================
# Scheduled Message Operations Tests
# ============================================================================


class TestScheduledMessageOperations:
    """Tests for scheduled message operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_delete_scheduled_message(self, mock_client_class, bot_credentials):
        """Test deleting a scheduled message."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackDeleteScheduledMessageConfig(
            channel="C12345678", scheduled_message_id="Q12345678"
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_scheduled_message"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_list_scheduled_messages(self, mock_client_class, bot_credentials):
        """Test listing scheduled messages."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"scheduled_messages": [{"id": "Q12345678", "channel_id": "C12345678"}]}
        )

        config = SlackListScheduledMessagesConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_scheduled_messages"


# ============================================================================
# Chat Extras Tests
# ============================================================================


class TestChatExtras:
    """Tests for chat extras (me message, unfurl)."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_me_message(self, mock_client_class, bot_credentials):
        """Test sending a /me message."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"channel": "C12345678", "ts": "1234567890.123456"}
        )

        config = SlackMeMessageConfig(channel="C12345678", text="is testing")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "send_me_message"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_unfurl(self, mock_client_class, bot_credentials):
        """Test custom URL unfurling."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        # unfurls is a JSON string per the config model
        config = SlackUnfurlConfig(
            channel="C12345678",
            ts="1234567890.123456",
            unfurls='{"https://example.com": {"text": "Example"}}',
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "provide_custom_unfurl_behavior"


# ============================================================================
# User Profile Operations Tests
# ============================================================================


class TestUserProfileOperations:
    """Tests for user profile operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_get_user_profile(self, mock_client_class, bot_credentials):
        """Test getting a user's profile."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"profile": {"display_name": "Test User", "email": "test@example.com"}}
        )

        config = SlackGetUserProfileConfig(user="U12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_user_profile_information"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_set_user_presence(self, mock_client_class, bot_credentials):
        """Test setting user presence."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackSetUserPresenceConfig(presence="away")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "set_user_presence_status"


# ============================================================================
# Additional Team/Auth Operations Tests
# ============================================================================


class TestAdditionalTeamAuthOperations:
    """Tests for additional team/auth operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_api_test(self, mock_client_class, bot_credentials):
        """Test the Slack API test endpoint."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackApiTestConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "test_api_connection"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_auth_revoke(self, mock_client_class, bot_credentials):
        """Test revoking an access token."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({"revoked": True})

        config = SlackAuthRevokeConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "revoke_oauth_token"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_apps_uninstall(self, mock_client_class, bot_credentials):
        """Test uninstalling the app."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({})

        config = SlackAppsUninstallConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "uninstall_app_from_workspace"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_team_billable_info(self, mock_client_class, bot_credentials):
        """Test getting billable info."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"billable_info": {"U12345678": {"billing_active": True}}}
        )

        config = SlackTeamBillableInfoConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_team_billable_information"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_team_access_logs(self, mock_client_class, bot_credentials):
        """Test getting team access logs."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"logins": [{"user_id": "U12345678", "date_first": 1234567890}]}
        )

        config = SlackTeamAccessLogsConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_workspace_access_logs"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_team_integration_logs(self, mock_client_class, bot_credentials):
        """Test getting team integration logs."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"logs": [{"service_id": "123456789", "service_type": "oauth"}]}
        )

        config = SlackTeamIntegrationLogsConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_workspace_integration_logs"


# ============================================================================
# Slack Connect Operations Tests
# ============================================================================


class TestSlackConnectOperations:
    """Tests for Slack Connect operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_accept_shared_invite(self, mock_client_class, bot_credentials):
        """Test accepting a shared channel invite."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"channel": {"id": "C12345678", "name": "shared-channel"}}
        )

        config = SlackConversationsAcceptSharedInviteConfig(
            channel_name="shared-channel", invite_id="I12345678"
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "accept_shared_channel_invite"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_decline_shared_invite(self, mock_client_class, bot_credentials):
        """Test declining a shared channel invite."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackConversationsDeclineSharedInviteConfig(invite_id="I12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "decline_shared_channel_invite"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_list_connect_invites(self, mock_client_class, bot_credentials):
        """Test listing Slack Connect invites."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {
                "invites": [
                    {"invite_id": "I12345678", "channel": {"name": "shared-channel"}}
                ]
            }
        )

        config = SlackConversationsListConnectInvitesConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_slack_connect_invites"


# ============================================================================
# New File Upload Operations Tests
# ============================================================================


class TestNewFileUploadOperations:
    """Test new file upload operations (files.upload deprecated Nov 2025)."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_get_upload_url_external(self, mock_client_class, bot_credentials):
        """Test getting external upload URL."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"upload_url": "https://files.slack.com/upload/...", "file_id": "F12345678"}
        )

        config = SlackGetUploadURLExternalConfig(filename="test.txt", length=1024)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_external_file_upload_url"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_complete_upload_external(self, mock_client_class, bot_credentials):
        """Test completing external upload."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"files": [{"id": "F12345678", "name": "test.txt"}]}
        )

        config = SlackCompleteUploadExternalConfig(
            files='[{"id": "F12345678", "title": "test.txt"}]', channel_id="C12345678"
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "complete_external_file_upload"


# ============================================================================
# User Profile Operations Tests
# ============================================================================


class TestUserProfileSetOperations:
    """Test user profile set operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_set_user_profile(self, mock_client_class, bot_credentials):
        """Test setting user profile."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"profile": {"status_text": "Working from home", "status_emoji": ":house:"}}
        )

        config = SlackSetUserProfileConfig(
            profile='{"status_text": "Working from home", "status_emoji": ":house:"}'
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "set_user_profile_fields"


# ============================================================================
# Additional Slack Connect Operations Tests
# ============================================================================


class TestAdditionalSlackConnectOperations:
    """Test additional Slack Connect operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_approve_shared_invite(self, mock_client_class, bot_credentials):
        """Test approving shared invite."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"invite_id": "I12345678", "ok": True}
        )

        config = SlackApproveSharedInviteConfig(invite_id="I12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "approve_slack_connect_channel_invite"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_invite_shared(self, mock_client_class, bot_credentials):
        """Test inviting to shared channel."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"invite_id": "I12345678", "is_legacy_shared_channel": False}
        )

        config = SlackInviteSharedConfig(channel="C12345678", emails="user@example.com")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "invite_user_to_slack_connect_channel"


# ============================================================================
# Remote File Operations Tests
# ============================================================================


class TestRemoteFileOperations:
    """Test remote file operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_add_remote_file(self, mock_client_class, bot_credentials):
        """Test adding remote file."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"file": {"id": "F12345678", "name": "document.pdf"}}
        )

        config = SlackAddRemoteFileConfig(
            external_id="ext_123",
            external_url="https://example.com/document.pdf",
            title="Important Document",
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "add_remote_file_to_workspace"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_remove_remote_file(self, mock_client_class, bot_credentials):
        """Test removing remote file."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({"ok": True})

        config = SlackRemoveRemoteFileConfig(external_id="ext_123")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "remove_remote_file"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_share_remote_file(self, mock_client_class, bot_credentials):
        """Test sharing remote file."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        # files.remote.share is a documented GET — args ride the query string.
        mock_client.get.return_value = mock_slack_response(
            {"file": {"id": "F12345678", "shares": {"public": {"C12345678": [{}]}}}}
        )

        config = SlackShareRemoteFileConfig(channels="C12345678", external_id="ext_123")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "share_remote_file_to_channel"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_list_remote_files(self, mock_client_class, bot_credentials):
        """Test listing remote files."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {
                "files": [{"id": "F12345678", "name": "doc.pdf"}],
                "response_metadata": {"next_cursor": ""},
            }
        )

        config = SlackListRemoteFilesConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_remote_files"


# ============================================================================
# Additional Operations Tests (11 new methods)
# ============================================================================


class TestAdditionalReactionsOperations:
    """Test additional reactions operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_list_reactions(self, mock_client_class, bot_credentials):
        """Test listing reactions."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {
                "items": [
                    {
                        "type": "message",
                        "channel": "C12345678",
                        "message": {"reactions": []},
                    }
                ],
                "paging": {"count": 100, "total": 1, "page": 1, "pages": 1},
            }
        )

        config = SlackListReactionsConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_reactions_for_item"


class TestAdditionalRemoteFileOperations:
    """Test additional remote file operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_remote_file_info(self, mock_client_class, bot_credentials):
        """Test getting remote file info."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"file": {"id": "F12345678", "name": "doc.pdf", "external_type": "gdrive"}}
        )

        config = SlackRemoteFileInfoConfig(external_id="ext_123")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_remote_file_information"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_remote_file_update(self, mock_client_class, bot_credentials):
        """Test updating remote file."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"file": {"id": "F12345678", "name": "updated.pdf"}}
        )

        config = SlackRemoteFileUpdateConfig(
            external_id="ext_123", title="Updated Title"
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "update_remote_file"


class TestFileCommentOperations:
    """Test file comment operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_delete_file_comment(self, mock_client_class, bot_credentials):
        """Test deleting a file comment."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackDeleteFileCommentConfig(file="F12345678", id="Fc12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_file_comment"


class TestAdditionalUserOperations:
    """Test additional user operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_delete_user_photo(self, mock_client_class, bot_credentials):
        """Test deleting user photo."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackDeleteUserPhotoConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_user_profile_photo"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_set_user_active(self, mock_client_class, bot_credentials):
        """Test setting user active."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackSetUserActiveConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "set_user_as_active"


class TestCanvasOperations:
    """Test canvas operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_create_canvas(self, mock_client_class, bot_credentials):
        """Test creating a canvas."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({"canvas_id": "F12345678"})

        config = SlackCreateCanvasConfig(channel_id="C12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_canvas_in_channel"


class TestSlackConnectRequestOperations:
    """Test Slack Connect request operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_set_external_invite_permissions(
        self, mock_client_class, bot_credentials
    ):
        """Test setting external invite permissions."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackSetExternalInvitePermissionsConfig(
            channel="C12345678", action_type="upgrade"
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "set_channel_external_invite_permissions"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_approve_shared_invite_request(
        self, mock_client_class, bot_credentials
    ):
        """Test approving a shared invite request."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({"invite_id": "I12345678"})

        config = SlackApproveSharedInviteRequestConfig(invite_id="I12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "approve_slack_connect_invite_request"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_deny_shared_invite_request(self, mock_client_class, bot_credentials):
        """Test denying a shared invite request."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackDenySharedInviteRequestConfig(invite_id="I12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "deny_slack_connect_invite_request"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_list_shared_invite_requests(
        self, mock_client_class, bot_credentials
    ):
        """Test listing shared invite requests."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"invite_requests": [], "response_metadata": {"next_cursor": ""}}
        )

        config = SlackListSharedInviteRequestsConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_slack_connect_invite_requests"


# ============================================================================
# Admin API Tests (Enterprise Grid)
# ============================================================================


class TestAdminAnalyticsOperations:
    """Test admin.analytics operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_analytics_get_file(self, mock_client_class, bot_credentials):
        """Test getting analytics file."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"file_data": "analytics data"}
        )

        config = SlackAdminAnalyticsGetFileConfig(type="member")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_analytics_file_for_date"


class TestAdminAppsOperations:
    """Test admin.apps operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_apps_approved_list(self, mock_client_class, bot_credentials):
        """Test listing approved apps."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({"approved_apps": []})

        config = SlackAdminAppsApprovedListConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_approved_apps"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_apps_restricted_list(self, mock_client_class, bot_credentials):
        """Test listing restricted apps."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({"restricted_apps": []})

        config = SlackAdminAppsRestrictedListConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_restricted_apps"


class TestAdminBarriersOperations:
    """Test admin.barriers operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_barriers_list(self, mock_client_class, bot_credentials):
        """Test listing barriers."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({"barriers": []})

        config = SlackAdminBarriersListConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_information_barriers"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_barriers_create(self, mock_client_class, bot_credentials):
        """Test creating a barrier."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response(
            {"barrier": {"id": "B12345"}}
        )

        config = SlackAdminBarriersCreateConfig(
            barriered_from_usergroup_ids=["S12345"],
            primary_usergroup_id="S67890",
            restricted_subjects=["im", "call"],
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_information_barrier"


class TestAdminConversationsOperations:
    """Test admin.conversations operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_conversations_search(self, mock_client_class, bot_credentials):
        """Test searching conversations."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({"conversations": []})

        config = SlackAdminConversationsSearchConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "search_conversations"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_conversations_archive(
        self, mock_client_class, bot_credentials
    ):
        """Test archiving a conversation."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackAdminConversationsArchiveConfig(channel_id="C12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "archive_conversation_as_admin"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_conversations_create(self, mock_client_class, bot_credentials):
        """Test creating a conversation."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({"channel_id": "C12345678"})

        config = SlackAdminConversationsCreateConfig(name="test-channel")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_admin_conversation"


class TestAdminEmojiOperations:
    """Test admin.emoji operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_emoji_list(self, mock_client_class, bot_credentials):
        """Test listing emoji."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({"emoji": {}})

        config = SlackAdminEmojiListConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_custom_emoji"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_emoji_add(self, mock_client_class, bot_credentials):
        """Test adding emoji."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackAdminEmojiAddConfig(
            name="test_emoji", url="https://example.com/emoji.png"
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "add_custom_emoji"


class TestAdminFunctionsOperations:
    """Test admin.functions operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_functions_list(self, mock_client_class, bot_credentials):
        """Test listing functions."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({"functions": []})

        config = SlackAdminFunctionsListConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_functions"


class TestAdminInviteRequestsOperations:
    """Test admin.inviteRequests operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_invite_requests_list(self, mock_client_class, bot_credentials):
        """Test listing invite requests."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({"invite_requests": []})

        config = SlackAdminInviteRequestsListConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_invite_requests"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_invite_requests_approve(
        self, mock_client_class, bot_credentials
    ):
        """Test approving invite request."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackAdminInviteRequestsApproveConfig(invite_request_id="IR12345")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "approve_invite_request"


class TestAdminRolesOperations:
    """Test admin.roles operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_roles_list_assignments(
        self, mock_client_class, bot_credentials
    ):
        """Test listing role assignments."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({"role_assignments": []})

        config = SlackAdminRolesListAssignmentsConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_role_assignments"


class TestAdminTeamsOperations:
    """Test admin.teams operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_teams_list(self, mock_client_class, bot_credentials):
        """Test listing teams."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({"teams": []})

        config = SlackAdminTeamsListConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_teams"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_teams_create(self, mock_client_class, bot_credentials):
        """Test creating a team."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({"team": {"id": "T12345"}})

        config = SlackAdminTeamsCreateConfig(
            team_domain="test-team", team_name="Test Team"
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_team"


class TestAdminUsergroupsOperations:
    """Test admin.usergroups operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_usergroups_list_channels(
        self, mock_client_class, bot_credentials
    ):
        """Test listing usergroup channels."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({"channels": []})

        config = SlackAdminUsergroupsListChannelsConfig(usergroup_id="S12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_channels_in_usergroup"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_usergroups_add_channels(
        self, mock_client_class, bot_credentials
    ):
        """Test adding channels to usergroup."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackAdminUsergroupsAddChannelsConfig(
            usergroup_id="S12345678", channel_ids=["C12345678"]
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "add_channels_to_usergroup"


class TestAdminUsersOperations:
    """Test admin.users operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_users_list(self, mock_client_class, bot_credentials):
        """Test listing users."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({"users": []})

        config = SlackAdminUsersListConfig(team_id="T12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_users_in_team"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_users_invite(self, mock_client_class, bot_credentials):
        """Test inviting a user."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackAdminUsersInviteConfig(
            email="test@example.com", team_id="T12345678", channel_ids=["C12345678"]
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "invite_user_to_team"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_users_session_list(self, mock_client_class, bot_credentials):
        """Test listing user sessions."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({"active_sessions": []})

        config = SlackAdminUsersSessionListConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_user_sessions"


class TestAdminWorkflowsOperations:
    """Test admin.workflows operations."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_workflows_search(self, mock_client_class, bot_credentials):
        """Test searching workflows."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({"workflows": []})

        config = SlackAdminWorkflowsSearchConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "search_workflows"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_admin_workflows_unpublish(self, mock_client_class, bot_credentials):
        """Test unpublishing workflows."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({})

        config = SlackAdminWorkflowsUnpublishConfig(workflow_ids=["Wf12345678"])
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "unpublish_workflow"


# ============================================================================
# Timing Information Tests
# ============================================================================


class TestTimingInformation:
    """Test that timing information is included in responses."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_timing_in_response(self, mock_client_class, bot_credentials):
        """Test that timing information is present."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_slack_response({"user_id": "U12345678"})

        config = SlackAuthTestConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert "timing_ms" in result
        assert "api_request" in result["timing_ms"]
        assert "total" in result["timing_ms"]
        assert result["timing_ms"]["api_request"] >= 0
        assert result["timing_ms"]["total"] >= 0


# ============================================================================
# Channel-scoped reads run as the user (xoxp-), not the bot (xoxb-)
# ============================================================================


# (config, http_method) — every channel-scoped read that is hard-coded to the
# user token. If any of these stops passing send_as="user" it would silently
# revert to the bot token and re-introduce not_in_channel for un-joined channels.
READ_OPS_USER_TOKEN = [
    (SlackConversationInfoConfig(channel="C12345678"), "get"),
    (SlackConversationHistoryConfig(channel="C12345678", limit=5), "get"),
    (SlackConversationMembersConfig(channel="C12345678"), "get"),
    (SlackConversationRepliesConfig(channel="C12345678", ts="1234567890.000100"), "get"),
    (SlackMarkConversationConfig(channel="C12345678", ts="1234567890.000100"), "post"),
    (SlackGetReactionsConfig(channel="C12345678", timestamp="1234567890.000100"), "get"),
    (SlackListPinsConfig(channel="C12345678"), "get"),
    (SlackListBookmarksConfig(channel_id="C12345678"), "get"),
]


class TestReadOpsUseUserToken:
    """Channel-scoped reads authenticate with the user token (xoxp-) so they see
    the channels the authorizing user can, not only those the bot was invited to."""

    @pytest.fixture
    def oauth_user_credentials(self):
        """OAuth credential carrying a distinct bot and user token, user token
        non-expiring so _ensure_fresh_token takes the no-DB fast path."""
        return SlackOAuthCredential(
            access_token="xoxb-bot-token",
            refresh_token="bot-refresh-token",
            user_access_token="xoxp-user-token",
            user_refresh_token="user-refresh-token",
            team_id="T12345678",
            team_name="Test Team",
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "config,http_method",
        READ_OPS_USER_TOKEN,
        ids=[c.operation for c, _ in READ_OPS_USER_TOKEN],
    )
    @patch("httpx.AsyncClient")
    async def test_read_authenticates_as_user(
        self, mock_client_class, config, http_method, oauth_user_credentials
    ):
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({})
        mock_client.post.return_value = mock_slack_response({})

        node = create_node(config, oauth_user_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        call = mock_client.get if http_method == "get" else mock_client.post
        assert call.called, f"{config.operation} did not issue a {http_method.upper()}"
        assert call.call_args.kwargs["headers"]["Authorization"] == "Bearer xoxp-user-token"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_read_without_user_token_raises_reauth(
        self, mock_client_class, oauth_credentials
    ):
        """An OAuth credential with no user token (predates user scopes) must
        raise a re-authorize hint rather than silently falling back to the bot."""
        config = SlackConversationHistoryConfig(channel="C12345678")
        node = create_node(config, oauth_credentials)
        with pytest.raises(ValueError, match="user token"):
            await node.execute({})

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_read_missing_scope_surfaces_reauth_hint(
        self, mock_client_class, oauth_user_credentials
    ):
        """A user token minted before a read scope was added yields missing_scope;
        the error is rewritten into a re-authorize hint naming the needed scope."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response(
            {"error": "missing_scope", "needed": "channels:history"}, ok=False
        )

        config = SlackConversationHistoryConfig(channel="C12345678")
        node = create_node(config, oauth_user_credentials)
        result = await node.execute({})

        assert result["status"] == "error"
        assert "Re-authorize Slack" in result["error"]
        assert "channels:history" in result["error"]

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_bot_token_credential_reads_with_bot_token(
        self, mock_client_class, bot_credentials
    ):
        """A manually-entered bot-token credential has no user identity, so reads
        necessarily run with the bot token — the only token it has."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_slack_response({"messages": []})

        config = SlackConversationHistoryConfig(channel="C12345678")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        assert result["status"] == "success"
        assert (
            mock_client.get.call_args.kwargs["headers"]["Authorization"]
            == "Bearer xoxb-test-token-12345"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
