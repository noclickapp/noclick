"""
Integration tests for Slack Web API node.

Tests the complete Slack node functionality including all 36 operations
organized by category: messaging, conversations, users, reactions, pins,
files, search, and team/auth.

Uses a real Slack Bot Token to test against the Slack API. Tests are designed to be
non-destructive where possible (read operations). Write operations test the action
name is correct but may fail due to permission constraints.
"""

import asyncio
import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

# Import the node and config classes - ALL 36 operations
from nodes.slack_node import (
    SlackNode,
    SlackNodeConfig,
    SlackBotTokenCredential,
    # Messaging operations (6)
    SlackPostMessageConfig,
    SlackUpdateMessageConfig,
    SlackDeleteMessageConfig,
    SlackPostEphemeralConfig,
    SlackScheduleMessageConfig,
    SlackGetPermalinkConfig,
    # Conversation operations (14)
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
    # User operations (4)
    SlackListUsersConfig,
    SlackUserInfoConfig,
    SlackLookupUserByEmailConfig,
    SlackGetUserPresenceConfig,
    # Reaction operations (3)
    SlackAddReactionConfig,
    SlackRemoveReactionConfig,
    SlackGetReactionsConfig,
    # Pin operations (3)
    SlackAddPinConfig,
    SlackRemovePinConfig,
    SlackListPinsConfig,
    # File operations (3)
    SlackListFilesConfig,
    SlackFileInfoConfig,
    SlackDeleteFileConfig,
    # Search operations (1)
    SlackSearchMessagesConfig,
    # Team/Auth operations (2)
    SlackAuthTestConfig,
    SlackTeamInfoConfig,
)

# Environment variable for Bot Token (don't hardcode in tests)
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")

# Test channel - should be a channel the bot is in for testing
# Set via environment variable or use default
TEST_CHANNEL = os.environ.get("SLACK_TEST_CHANNEL", "")


def get_credentials():
    """Get Slack credentials from environment."""
    if not SLACK_BOT_TOKEN:
        pytest.skip("SLACK_BOT_TOKEN environment variable not set")
    return SlackBotTokenCredential(bot_token=SLACK_BOT_TOKEN)


def create_node(config) -> SlackNode:
    """Create a SlackNode instance with the given config."""
    credentials = get_credentials()
    node_config = SlackNodeConfig(config=config, credentials=credentials)
    node = SlackNode(
        node_id="test-node",
        node_type="automation-slack",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


# ============================================================================
# Team/Auth Operations Tests (2 operations) - Run these first to validate token
# ============================================================================


class TestTeamAuthOperations:
    """Test team and auth-related Slack API operations (2 total)."""

    @pytest.mark.asyncio
    async def test_auth_test(self):
        """Test authentication and get info about the token."""
        config = SlackAuthTestConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "test_authentication"
        if result["status"] == "success":
            assert result["data"]["ok"] is True
            # Store bot user ID for other tests
            print(f"Authenticated as: {result['data'].get('user')}")

    @pytest.mark.asyncio
    async def test_team_info(self):
        """Test getting workspace information."""
        config = SlackTeamInfoConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_workspace_information"
        if result["status"] == "success":
            assert "team" in result["data"]


# ============================================================================
# Conversation Operations Tests (14 operations)
# ============================================================================


class TestConversationOperations:
    """Test conversation-related Slack API operations (14 total)."""

    @pytest.mark.asyncio
    async def test_list_conversations(self):
        """Test listing channels in the workspace."""
        config = SlackListConversationsConfig(limit=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_channels_in_workspace"
        if result["status"] == "success":
            assert "channels" in result["data"]
            assert isinstance(result["data"]["channels"], list)

    @pytest.mark.asyncio
    async def test_conversation_info(self):
        """Test getting information about a channel."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        config = SlackConversationInfoConfig(channel=TEST_CHANNEL)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_channel_information"
        if result["status"] == "success":
            assert "channel" in result["data"]

    @pytest.mark.asyncio
    async def test_conversation_history(self):
        """Test getting messages from a channel."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        config = SlackConversationHistoryConfig(channel=TEST_CHANNEL, limit=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_channel_messages"
        if result["status"] == "success":
            assert "messages" in result["data"]

    @pytest.mark.asyncio
    async def test_conversation_members(self):
        """Test getting members of a channel."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        config = SlackConversationMembersConfig(channel=TEST_CHANNEL, limit=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_channel_members"
        if result["status"] == "success":
            assert "members" in result["data"]

    @pytest.mark.asyncio
    async def test_join_conversation(self):
        """Test joining a public channel (may fail if already member)."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        config = SlackJoinConversationConfig(channel=TEST_CHANNEL)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "join_public_channel"

    @pytest.mark.asyncio
    async def test_leave_conversation(self):
        """Test leaving a channel (may fail if not a member or required)."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        config = SlackLeaveConversationConfig(channel=TEST_CHANNEL)
        node = create_node(config)

        result = await node.execute({})

        # May fail with "not_in_channel" or "cant_leave_general"
        assert result["action"] == "leave_channel"

    @pytest.mark.asyncio
    async def test_create_conversation(self):
        """Test creating a new channel (requires channels:write scope)."""
        config = SlackCreateConversationConfig(
            name=f"test-channel-{int(time.time())}", is_private=True
        )
        node = create_node(config)

        result = await node.execute({})

        # May fail without proper scopes
        assert result["action"] == "create_channel"

    @pytest.mark.asyncio
    async def test_archive_conversation(self):
        """Test archiving a channel (requires admin access)."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        config = SlackArchiveConversationConfig(channel=TEST_CHANNEL)
        node = create_node(config)

        result = await node.execute({})

        # Will likely fail without admin access
        assert result["action"] == "archive_channel"

    @pytest.mark.asyncio
    async def test_unarchive_conversation(self):
        """Test unarchiving a channel (requires admin access)."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        config = SlackUnarchiveConversationConfig(channel=TEST_CHANNEL)
        node = create_node(config)

        result = await node.execute({})

        # Will likely fail without admin access
        assert result["action"] == "unarchive_channel"

    @pytest.mark.asyncio
    async def test_invite_to_conversation(self):
        """Test inviting users to a channel."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        # Use a placeholder user ID - will fail but tests the action
        config = SlackInviteToConversationConfig(
            channel=TEST_CHANNEL, users="U00000000"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "invite_users_to_channel"

    @pytest.mark.asyncio
    async def test_kick_from_conversation(self):
        """Test removing a user from a channel."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        config = SlackKickFromConversationConfig(channel=TEST_CHANNEL, user="U00000000")
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "remove_user_from_channel"

    @pytest.mark.asyncio
    async def test_set_conversation_topic(self):
        """Test setting a channel topic."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        config = SlackSetConversationTopicConfig(
            channel=TEST_CHANNEL, topic="Test topic from automated tests"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "set_channel_topic"

    @pytest.mark.asyncio
    async def test_set_conversation_purpose(self):
        """Test setting a channel purpose."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        config = SlackSetConversationPurposeConfig(
            channel=TEST_CHANNEL, purpose="Test purpose from automated tests"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "set_channel_purpose"

    @pytest.mark.asyncio
    async def test_rename_conversation(self):
        """Test renaming a channel."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        config = SlackRenameConversationConfig(
            channel=TEST_CHANNEL, name="renamed-channel"
        )
        node = create_node(config)

        result = await node.execute({})

        # Will likely fail without admin access
        assert result["action"] == "rename_channel"


# ============================================================================
# Messaging Operations Tests (6 operations)
# ============================================================================


class TestMessagingOperations:
    """Test messaging-related Slack API operations (6 total)."""

    @pytest.mark.asyncio
    async def test_post_message(self):
        """Test posting a message to a channel."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        config = SlackPostMessageConfig(
            channel=TEST_CHANNEL, text="Test message from automated tests"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "send_message_to_channel"
        if result["status"] == "success":
            assert "ts" in result["data"]

    @pytest.mark.asyncio
    async def test_update_message(self):
        """Test updating an existing message."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        # First post a message
        post_config = SlackPostMessageConfig(
            channel=TEST_CHANNEL, text="Message to update"
        )
        post_node = create_node(post_config)
        post_result = await post_node.execute({})

        if post_result["status"] == "success":
            ts = post_result["data"]["ts"]

            # Now update it
            config = SlackUpdateMessageConfig(
                channel=TEST_CHANNEL, ts=ts, text="Updated message"
            )
            node = create_node(config)
            result = await node.execute({})

            assert result["action"] == "update_existing_message"
        else:
            # Test with placeholder if posting failed
            config = SlackUpdateMessageConfig(
                channel=TEST_CHANNEL, ts="1234567890.123456", text="Updated message"
            )
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "update_existing_message"

    @pytest.mark.asyncio
    async def test_delete_message(self):
        """Test deleting a message."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        # First post a message to delete
        post_config = SlackPostMessageConfig(
            channel=TEST_CHANNEL, text="Message to delete"
        )
        post_node = create_node(post_config)
        post_result = await post_node.execute({})

        if post_result["status"] == "success":
            ts = post_result["data"]["ts"]

            # Now delete it
            config = SlackDeleteMessageConfig(channel=TEST_CHANNEL, ts=ts)
            node = create_node(config)
            result = await node.execute({})

            assert result["action"] == "delete_message"
        else:
            config = SlackDeleteMessageConfig(
                channel=TEST_CHANNEL, ts="1234567890.123456"
            )
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "delete_message"

    @pytest.mark.asyncio
    async def test_post_ephemeral(self):
        """Test posting an ephemeral message."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        # Need a valid user ID - get from auth.test
        auth_config = SlackAuthTestConfig()
        auth_node = create_node(auth_config)
        auth_result = await auth_node.execute({})

        user_id = auth_result.get("data", {}).get("user_id", "U00000000")

        config = SlackPostEphemeralConfig(
            channel=TEST_CHANNEL, user=user_id, text="Ephemeral test message"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "send_ephemeral_message"

    @pytest.mark.asyncio
    async def test_schedule_message(self):
        """Test scheduling a message for later."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        # Schedule for 5 minutes from now
        post_at = int(time.time()) + 300

        config = SlackScheduleMessageConfig(
            channel=TEST_CHANNEL, text="Scheduled test message", post_at=post_at
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "schedule_message_for_later"

    @pytest.mark.asyncio
    async def test_get_permalink(self):
        """Test getting a permalink for a message."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        # First get a message ts from history
        history_config = SlackConversationHistoryConfig(channel=TEST_CHANNEL, limit=1)
        history_node = create_node(history_config)
        history_result = await history_node.execute({})

        if history_result["status"] == "success" and history_result["data"].get(
            "messages"
        ):
            ts = history_result["data"]["messages"][0]["ts"]

            config = SlackGetPermalinkConfig(channel=TEST_CHANNEL, message_ts=ts)
            node = create_node(config)
            result = await node.execute({})

            assert result["action"] == "get_message_permalink"
            if result["status"] == "success":
                assert "permalink" in result["data"]
        else:
            config = SlackGetPermalinkConfig(
                channel=TEST_CHANNEL, message_ts="1234567890.123456"
            )
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "get_message_permalink"


# ============================================================================
# User Operations Tests (4 operations)
# ============================================================================


class TestUserOperations:
    """Test user-related Slack API operations (4 total)."""

    @pytest.mark.asyncio
    async def test_list_users(self):
        """Test listing all users in the workspace."""
        config = SlackListUsersConfig(limit=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_workspace_users"
        if result["status"] == "success":
            assert "members" in result["data"]
            assert isinstance(result["data"]["members"], list)

    @pytest.mark.asyncio
    async def test_user_info(self):
        """Test getting information about a user."""
        # First get a user ID
        list_config = SlackListUsersConfig(limit=1)
        list_node = create_node(list_config)
        list_result = await list_node.execute({})

        if list_result["status"] == "success" and list_result["data"].get("members"):
            user_id = list_result["data"]["members"][0]["id"]

            config = SlackUserInfoConfig(user=user_id)
            node = create_node(config)
            result = await node.execute({})

            assert result["action"] == "get_user_information"
            if result["status"] == "success":
                assert "user" in result["data"]
        else:
            config = SlackUserInfoConfig(user="U00000000")
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "get_user_information"

    @pytest.mark.asyncio
    async def test_lookup_user_by_email(self):
        """Test finding a user by email (requires users:read.email scope)."""
        config = SlackLookupUserByEmailConfig(email="test@example.com")
        node = create_node(config)

        result = await node.execute({})

        # May fail without users:read.email scope or if user doesn't exist
        assert result["action"] == "find_user_by_email"

    @pytest.mark.asyncio
    async def test_get_user_presence(self):
        """Test getting a user's presence status."""
        # First get a user ID
        list_config = SlackListUsersConfig(limit=1)
        list_node = create_node(list_config)
        list_result = await list_node.execute({})

        if list_result["status"] == "success" and list_result["data"].get("members"):
            user_id = list_result["data"]["members"][0]["id"]

            config = SlackGetUserPresenceConfig(user=user_id)
            node = create_node(config)
            result = await node.execute({})

            assert result["action"] == "get_user_presence_status"
        else:
            config = SlackGetUserPresenceConfig(user="U00000000")
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "get_user_presence_status"


# ============================================================================
# Reaction Operations Tests (3 operations)
# ============================================================================


class TestReactionOperations:
    """Test reaction-related Slack API operations (3 total)."""

    @pytest.mark.asyncio
    async def test_add_reaction(self):
        """Test adding an emoji reaction to a message."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        # First post a message to react to
        post_config = SlackPostMessageConfig(
            channel=TEST_CHANNEL, text="Message for reaction test"
        )
        post_node = create_node(post_config)
        post_result = await post_node.execute({})

        if post_result["status"] == "success":
            ts = post_result["data"]["ts"]

            config = SlackAddReactionConfig(
                channel=TEST_CHANNEL, timestamp=ts, name="thumbsup"
            )
            node = create_node(config)
            result = await node.execute({})

            assert result["action"] == "add_emoji_reaction_to_message"
        else:
            config = SlackAddReactionConfig(
                channel=TEST_CHANNEL, timestamp="1234567890.123456", name="thumbsup"
            )
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "add_emoji_reaction_to_message"

    @pytest.mark.asyncio
    async def test_remove_reaction(self):
        """Test removing an emoji reaction from a message."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        config = SlackRemoveReactionConfig(
            channel=TEST_CHANNEL, timestamp="1234567890.123456", name="thumbsup"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "remove_emoji_reaction_from_message"

    @pytest.mark.asyncio
    async def test_get_reactions(self):
        """Test getting reactions on a message."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        # Get a message from history
        history_config = SlackConversationHistoryConfig(channel=TEST_CHANNEL, limit=1)
        history_node = create_node(history_config)
        history_result = await history_node.execute({})

        if history_result["status"] == "success" and history_result["data"].get(
            "messages"
        ):
            ts = history_result["data"]["messages"][0]["ts"]

            config = SlackGetReactionsConfig(channel=TEST_CHANNEL, timestamp=ts)
            node = create_node(config)
            result = await node.execute({})

            assert result["action"] == "get_message_reactions"
        else:
            config = SlackGetReactionsConfig(
                channel=TEST_CHANNEL, timestamp="1234567890.123456"
            )
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "get_message_reactions"


# ============================================================================
# Pin Operations Tests (3 operations)
# ============================================================================


class TestPinOperations:
    """Test pin-related Slack API operations (3 total)."""

    @pytest.mark.asyncio
    async def test_list_pins(self):
        """Test listing pinned items in a channel."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        config = SlackListPinsConfig(channel=TEST_CHANNEL)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_pinned_items_in_channel"
        if result["status"] == "success":
            assert "items" in result["data"]

    @pytest.mark.asyncio
    async def test_add_pin(self):
        """Test pinning a message to a channel."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        # First post a message to pin
        post_config = SlackPostMessageConfig(
            channel=TEST_CHANNEL, text="Message to pin"
        )
        post_node = create_node(post_config)
        post_result = await post_node.execute({})

        if post_result["status"] == "success":
            ts = post_result["data"]["ts"]

            config = SlackAddPinConfig(channel=TEST_CHANNEL, timestamp=ts)
            node = create_node(config)
            result = await node.execute({})

            assert result["action"] == "pin_message_to_channel"
        else:
            config = SlackAddPinConfig(
                channel=TEST_CHANNEL, timestamp="1234567890.123456"
            )
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "pin_message_to_channel"

    @pytest.mark.asyncio
    async def test_remove_pin(self):
        """Test unpinning a message from a channel."""
        if not TEST_CHANNEL:
            pytest.skip("SLACK_TEST_CHANNEL environment variable not set")

        config = SlackRemovePinConfig(
            channel=TEST_CHANNEL, timestamp="1234567890.123456"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "unpin_message_from_channel"


# ============================================================================
# File Operations Tests (3 operations)
# ============================================================================


class TestFileOperations:
    """Test file-related Slack API operations (3 total)."""

    @pytest.mark.asyncio
    async def test_list_files(self):
        """Test listing files in the workspace."""
        config = SlackListFilesConfig(count=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_workspace_files"
        if result["status"] == "success":
            assert "files" in result["data"]

    @pytest.mark.asyncio
    async def test_file_info(self):
        """Test getting information about a file."""
        # First list files to find one
        list_config = SlackListFilesConfig(count=1)
        list_node = create_node(list_config)
        list_result = await list_node.execute({})

        if list_result["status"] == "success" and list_result["data"].get("files"):
            file_id = list_result["data"]["files"][0]["id"]

            config = SlackFileInfoConfig(file=file_id)
            node = create_node(config)
            result = await node.execute({})

            assert result["action"] == "get_file_information"
        else:
            config = SlackFileInfoConfig(file="F00000000")
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "get_file_information"

    @pytest.mark.asyncio
    async def test_delete_file(self):
        """Test deleting a file (requires file ownership)."""
        config = SlackDeleteFileConfig(file="F00000000")
        node = create_node(config)

        result = await node.execute({})

        # Will fail without valid file ID
        assert result["action"] == "delete_file"


# ============================================================================
# Search Operations Tests (1 operation)
# ============================================================================


class TestSearchOperations:
    """Test search-related Slack API operations (1 total)."""

    @pytest.mark.asyncio
    async def test_search_messages(self):
        """Test searching for messages in the workspace."""
        config = SlackSearchMessagesConfig(query="test", count=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_workspace_messages"
        # May fail without search:read scope


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_invalid_channel(self):
        """Test handling of invalid channel."""
        config = SlackConversationInfoConfig(channel="C00000000")
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "error"
        # The node enriches channel_not_found with the bot's accessible
        # channels; the Slack error code still leads the message.
        assert result["error"].startswith("channel_not_found")

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test handling of missing credentials."""
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
    async def test_invalid_token(self):
        """Test handling of invalid token."""
        config = SlackListConversationsConfig()
        credentials = SlackBotTokenCredential(bot_token="xoxb-invalid-token")
        node_config = SlackNodeConfig(config=config, credentials=credentials)
        node = SlackNode(
            node_id="test-node",
            node_type="automation-slack",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["error"] in ["invalid_auth", "not_authed"]


# ============================================================================
# Timing and Performance Tests
# ============================================================================


class TestPerformance:
    """Test performance and timing information."""

    @pytest.mark.asyncio
    async def test_timing_information(self):
        """Test that timing information is included in responses."""
        config = SlackAuthTestConfig()
        node = create_node(config)

        result = await node.execute({})

        assert "timing_ms" in result
        assert "api_request" in result["timing_ms"]
        assert "total" in result["timing_ms"]
        assert result["timing_ms"]["api_request"] >= 0
        assert result["timing_ms"]["total"] >= 0


if __name__ == "__main__":
    # Run tests with: SLACK_BOT_TOKEN=xoxb-... SLACK_TEST_CHANNEL=C... pytest nodes/tests/test_slack_node.py -v
    pytest.main([__file__, "-v"])
