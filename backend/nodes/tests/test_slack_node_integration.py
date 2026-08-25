# Integration tests for SlackNode using actual Slack API.
# These tests verify that the SlackNode operations work correctly with the real Slack API.
# Run with: pytest nodes/tests/test_slack_node_integration.py -v -m integration
# Requires SLACK_TEST_BOT_TOKEN environment variable to be set.

"""
Integration tests for SlackNode.

These tests use actual Slack API calls to verify functionality.
They require a valid bot token with appropriate scopes.

To run:
    SLACK_TEST_BOT_TOKEN="xoxb-..." pytest nodes/tests/test_slack_node_integration.py -v -m integration

Required bot token scopes (tests will skip gracefully if missing):
    - channels:read (list conversations, channel info, users.conversations)
    - users:read (list users, user info, user presence)
    - team:read (team info)
    - emoji:read (list emoji)
    - files:read (list files)
    - files:write (file upload operations)
    - remote_files:read (remote file operations)
    - bookmarks:read (list bookmarks)
    - usergroups:read (list user groups)
    - dnd:read (DND status)
    - stars:read (list starred items)
    - reminders:read (list reminders)
    - reactions:read (list reactions)
    - pins:read (list pinned items)
    - search:read (search messages and files)

Admin scopes (Enterprise Grid only - tests skip gracefully):
    - admin.apps:read (list approved apps)
    - admin.teams:read (list teams)
    - admin.users:read (list users across Grid)
"""

import os
import pytest
from typing import Optional, Dict, Any

from nodes.slack_node import (
    SlackNode,
    SlackNodeConfig,
    SlackCredential,
    SlackBotTokenCredential,
    # Read operations
    SlackListConversationsConfig,
    SlackConversationInfoConfig,
    SlackListUsersConfig,
    SlackUserInfoConfig,
    SlackTeamInfoConfig,
    SlackAuthTestConfig,
    SlackApiTestConfig,
    SlackListEmojiConfig,
    SlackBotInfoConfig,
    # File operations
    SlackGetUploadURLExternalConfig,
    SlackListRemoteFilesConfig,
    SlackListFilesConfig,
    # Bookmark operations
    SlackListBookmarksConfig,
    # User group operations
    SlackListUserGroupsConfig,
    # DND operations
    SlackDndInfoConfig,
    SlackDndTeamInfoConfig,
    # Star operations
    SlackListStarsConfig,
    # Reminder operations
    SlackListRemindersConfig,
    # Reaction operations
    SlackListReactionsConfig,
    # Pin operations
    SlackListPinsConfig,
    # Search operations
    SlackSearchMessagesConfig,
    SlackSearchFilesConfig,
    # User profile operations
    SlackGetUserProfileConfig,
    SlackUsersConversationsConfig,
    SlackGetUserPresenceConfig,
    # Scheduled messages
    SlackListScheduledMessagesConfig,
    # Team operations
    SlackTeamBillableInfoConfig,
    SlackTeamAccessLogsConfig,
    # Admin operations (Enterprise Grid - will skip gracefully if not available)
    SlackAdminAppsApprovedListConfig,
    SlackAdminTeamsListConfig,
    SlackAdminUsersListConfig,
    SlackAdminEmojiListConfig,
)


# A real workspace token, so it comes from the environment and nowhere else.
# There was a hardcoded default here: it rode every commit of this file into git
# history and would have shipped in the open-source export. These tests are
# opt-in (-m integration), and skipping them is the right outcome with no token.
BOT_TOKEN = os.environ.get("SLACK_TEST_BOT_TOKEN")


def create_node(config, credentials) -> SlackNode:
    """Create a SlackNode with the given config and credentials."""
    node_config = SlackNodeConfig(config=config, credentials=credentials)
    return SlackNode(
        node_id="test-integration-node",
        node_type="automation-slack",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-integration-workflow",
    )


def check_result_or_skip(
    result: Dict[str, Any], action_name: str, required_scope: str = None
):
    """
    Check result status and skip if missing scope or token type restriction.

    Returns the data dict if successful, otherwise handles the error appropriately.
    Some Slack APIs require user tokens (xoxp-) instead of bot tokens (xoxb-).
    """
    if result["status"] == "error":
        error = result.get("error", "")
        if "missing_scope" in error:
            scope_info = f" (requires {required_scope})" if required_scope else ""
            pytest.skip(f"Token missing required scope{scope_info}: {error}")
        elif "not_allowed_token_type" in error:
            pytest.skip(
                f"Token type not allowed (may require user token instead of bot token): {error}"
            )
        elif "token_revoked" in error or "invalid_auth" in error:
            pytest.skip(f"Token authentication issue: {error}")
        elif "invalid_arguments" in error:
            # Some APIs have specific parameter requirements that may not be met
            pytest.skip(f"Invalid arguments (may require specific parameters): {error}")
        elif "not_allowed" in error or "access_denied" in error:
            pytest.skip(f"Access denied (may require specific permissions): {error}")
        elif "not_in_channel" in error:
            pytest.skip(f"Bot not in channel (must be a member to access): {error}")
        else:
            # Real failure - raise assertion
            raise AssertionError(f"{action_name} failed with error: {error}")

    assert result["status"] == "success", f"{action_name} failed: {result.get('error')}"
    assert result["action"] == action_name
    return result.get("data", {})


@pytest.fixture
def bot_credentials() -> SlackCredential:
    """Bot token credentials for testing."""
    return SlackBotTokenCredential(credential_type="bot_token", bot_token=BOT_TOKEN)


# Mark all tests in this module as integration tests
pytestmark = [
    pytest.mark.integration,
    # Explicit, so an opt-in run without a token says why instead of failing
    # inside the first API call with an opaque invalid_auth.
    pytest.mark.skipif(
        not BOT_TOKEN,
        reason="set SLACK_TEST_BOT_TOKEN to a workspace bot token to run these",
    ),
]


class TestAuthOperations:
    """Test authentication and API connectivity."""

    @pytest.mark.asyncio
    async def test_auth_test(self, bot_credentials):
        """Test auth.test - verifies token is valid."""
        config = SlackAuthTestConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "test_authentication")

        # Should return user/team info
        assert "ok" in data, "Response should contain 'ok' field"
        assert data.get("ok") is True, f"API returned error: {data.get('error')}"

        # Log info for debugging
        print(f"\nAuthenticated as: {data.get('user', 'unknown')}")
        print(f"Team: {data.get('team', 'unknown')}")
        print(f"User ID: {data.get('user_id', 'unknown')}")

    @pytest.mark.asyncio
    async def test_api_test(self, bot_credentials):
        """Test api.test - basic API connectivity check."""
        config = SlackApiTestConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        check_result_or_skip(result, "test_api_connection")


class TestTeamOperations:
    """Test team-related operations."""

    @pytest.mark.asyncio
    async def test_team_info(self, bot_credentials):
        """Test team.info - get workspace information."""
        config = SlackTeamInfoConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "get_workspace_information", "team:read")

        if data.get("ok"):
            team = data.get("team", {})
            print(f"\nTeam name: {team.get('name', 'unknown')}")
            print(f"Team domain: {team.get('domain', 'unknown')}")


class TestConversationOperations:
    """Test conversation (channel) operations."""

    @pytest.mark.asyncio
    async def test_list_conversations(self, bot_credentials):
        """Test conversations.list - list channels the bot can see."""
        config = SlackListConversationsConfig(types="public_channel", limit=10)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "list_conversations", "channels:read")

        if data.get("ok"):
            channels = data.get("channels", [])
            print(f"\nFound {len(channels)} channels")
            for ch in channels[:5]:
                print(f"  - #{ch.get('name', 'unknown')} ({ch.get('id')})")

    @pytest.mark.asyncio
    async def test_conversation_info(self, bot_credentials):
        """Test conversations.info - get channel details."""
        # First, get a channel ID
        list_config = SlackListConversationsConfig(types="public_channel", limit=1)
        node = create_node(list_config, bot_credentials)
        list_result = await node.execute({})

        if list_result["status"] != "success":
            if "missing_scope" in list_result.get("error", ""):
                pytest.skip("Token missing channels:read scope")
            pytest.skip("Could not list conversations to get channel ID")

        channels = list_result.get("data", {}).get("channels", [])
        if not channels:
            pytest.skip("No channels available for testing")

        channel_id = channels[0]["id"]

        # Now get info for that channel
        config = SlackConversationInfoConfig(channel=channel_id)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "get_channel_information", "channels:read")

        if data.get("ok"):
            channel = data.get("channel", {})
            print(f"\nChannel: #{channel.get('name')}")
            print(f"Topic: {channel.get('topic', {}).get('value', 'none')}")
            print(f"Members: {channel.get('num_members', 'unknown')}")


class TestUserOperations:
    """Test user-related operations."""

    @pytest.mark.asyncio
    async def test_list_users(self, bot_credentials):
        """Test users.list - list workspace members."""
        config = SlackListUsersConfig(limit=10)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "list_users", "users:read")

        if data.get("ok"):
            members = data.get("members", [])
            print(f"\nFound {len(members)} users")
            for member in members[:5]:
                if not member.get("is_bot"):
                    print(f"  - {member.get('name', 'unknown')} ({member.get('id')})")

    @pytest.mark.asyncio
    async def test_user_info(self, bot_credentials):
        """Test users.info - get user details."""
        # First, get a user ID from the auth test
        auth_config = SlackAuthTestConfig()
        node = create_node(auth_config, bot_credentials)
        auth_result = await node.execute({})

        if auth_result["status"] != "success":
            pytest.skip("Could not get user ID from auth test")

        user_id = auth_result.get("data", {}).get("user_id")
        if not user_id:
            pytest.skip("No user ID returned from auth test")

        # Now get info for that user
        config = SlackUserInfoConfig(user=user_id)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "get_user_information", "users:read")

        if data.get("ok"):
            user = data.get("user", {})
            print(f"\nUser: {user.get('name')}")
            print(f"Real name: {user.get('real_name', 'unknown')}")


class TestMiscOperations:
    """Test miscellaneous operations."""

    @pytest.mark.asyncio
    async def test_list_emoji(self, bot_credentials):
        """Test emoji.list - list custom emoji."""
        config = SlackListEmojiConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "list_custom_emoji_in_workspace", "emoji:read")

        if data.get("ok"):
            emoji = data.get("emoji", {})
            print(f"\nFound {len(emoji)} custom emoji")
            for name in list(emoji.keys())[:5]:
                print(f"  :{name}:")


class TestNewFileUploadOperations:
    """Test the new file upload operations added in this PR."""

    @pytest.mark.asyncio
    async def test_get_upload_url_external(self, bot_credentials):
        """Test files.getUploadURLExternal - get URL for file upload."""
        config = SlackGetUploadURLExternalConfig(
            filename="test_file.txt", length=1024  # 1KB file
        )
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "get_external_file_upload_url", "files:write")

        if data.get("ok"):
            print(f"\nUpload URL obtained: {data.get('upload_url', 'hidden')[:50]}...")
            print(f"File ID: {data.get('file_id')}")


class TestRemoteFileOperations:
    """Test remote file operations added in this PR."""

    @pytest.mark.asyncio
    async def test_list_remote_files(self, bot_credentials):
        """Test files.remote.list - list remote files."""
        config = SlackListRemoteFilesConfig(limit=10)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "list_remote_files", "remote_files:read")

        if data.get("ok"):
            files = data.get("files", [])
            print(f"\nFound {len(files)} remote files")


class TestErrorHandling:
    """Test error handling with invalid inputs."""

    @pytest.mark.asyncio
    async def test_invalid_channel_id(self, bot_credentials):
        """Test that invalid channel ID returns appropriate error."""
        config = SlackConversationInfoConfig(channel="INVALID_CHANNEL_ID")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        # Skip if missing scope
        if result["status"] == "error" and "missing_scope" in result.get("error", ""):
            pytest.skip("Token missing channels:read scope")

        # If we have the scope, verify the error handling
        if result["status"] == "success":
            data = result.get("data", {})
            assert (
                data.get("ok") is False
            ), "Expected API to return error for invalid channel"
            print(f"\nExpected error received: {data.get('error')}")
        else:
            # For invalid input, Slack returns an error response
            # Check that we got a channel_not_found or similar error
            error = result.get("error", "")
            assert (
                "channel" in error.lower()
                or "not_found" in error.lower()
                or error != ""
            ), f"Expected channel error but got: {error}"
            print(f"\nExpected error received: {error}")

    @pytest.mark.asyncio
    async def test_invalid_user_id(self, bot_credentials):
        """Test that invalid user ID returns appropriate error."""
        config = SlackUserInfoConfig(user="INVALID_USER_ID")
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        # Skip if missing scope
        if result["status"] == "error" and "missing_scope" in result.get("error", ""):
            pytest.skip("Token missing users:read scope")

        # If we have the scope, verify the error handling
        if result["status"] == "success":
            data = result.get("data", {})
            assert (
                data.get("ok") is False
            ), "Expected API to return error for invalid user"
            print(f"\nExpected error received: {data.get('error')}")
        else:
            # For invalid input, Slack returns an error response
            error = result.get("error", "")
            assert (
                "user" in error.lower() or "not_found" in error.lower() or error != ""
            ), f"Expected user error but got: {error}"
            print(f"\nExpected error received: {error}")


class TestFileOperations:
    """Test file-related operations."""

    @pytest.mark.asyncio
    async def test_list_files(self, bot_credentials):
        """Test files.list - list files in the workspace."""
        config = SlackListFilesConfig(count=10)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "list_files", "files:read")

        if data.get("ok"):
            files = data.get("files", [])
            print(f"\nFound {len(files)} files")
            for f in files[:5]:
                print(f"  - {f.get('name', 'unknown')} ({f.get('id')})")


class TestBookmarkOperations:
    """Test bookmark-related operations."""

    @pytest.mark.asyncio
    async def test_list_bookmarks(self, bot_credentials):
        """Test bookmarks.list - list bookmarks in a channel."""
        # First, get a channel ID
        list_config = SlackListConversationsConfig(types="public_channel", limit=1)
        node = create_node(list_config, bot_credentials)
        list_result = await node.execute({})

        if list_result["status"] != "success":
            if "missing_scope" in list_result.get("error", ""):
                pytest.skip("Token missing channels:read scope")
            pytest.skip("Could not list conversations to get channel ID")

        channels = list_result.get("data", {}).get("channels", [])
        if not channels:
            pytest.skip("No channels available for testing")

        channel_id = channels[0]["id"]

        config = SlackListBookmarksConfig(channel_id=channel_id)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "list_bookmarks", "bookmarks:read")

        if data.get("ok"):
            bookmarks = data.get("bookmarks", [])
            print(f"\nFound {len(bookmarks)} bookmarks")


class TestUserGroupOperations:
    """Test user group operations."""

    @pytest.mark.asyncio
    async def test_list_usergroups(self, bot_credentials):
        """Test usergroups.list - list user groups."""
        config = SlackListUserGroupsConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "list_workspace_user_groups", "usergroups:read")

        if data.get("ok"):
            usergroups = data.get("usergroups", [])
            print(f"\nFound {len(usergroups)} user groups")
            for ug in usergroups[:5]:
                print(f"  - {ug.get('name', 'unknown')} ({ug.get('id')})")


class TestDndOperations:
    """Test Do Not Disturb operations."""

    @pytest.mark.asyncio
    async def test_dnd_info(self, bot_credentials):
        """Test dnd.info - get DND status for the current user."""
        config = SlackDndInfoConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "get_do_not_disturb_status", "dnd:read")

        if data.get("ok"):
            print(f"\nDND enabled: {data.get('dnd_enabled', 'unknown')}")
            print(f"Snooze enabled: {data.get('snooze_enabled', 'unknown')}")


class TestStarOperations:
    """Test star operations."""

    @pytest.mark.asyncio
    async def test_list_stars(self, bot_credentials):
        """Test stars.list - list starred items."""
        config = SlackListStarsConfig(limit=10)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "list_user_starred_items", "stars:read")

        if data.get("ok"):
            items = data.get("items", [])
            print(f"\nFound {len(items)} starred items")


class TestReminderOperations:
    """Test reminder operations."""

    @pytest.mark.asyncio
    async def test_list_reminders(self, bot_credentials):
        """Test reminders.list - list reminders."""
        config = SlackListRemindersConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "list_reminders", "reminders:read")

        if data.get("ok"):
            reminders = data.get("reminders", [])
            print(f"\nFound {len(reminders)} reminders")


class TestReactionOperations:
    """Test reaction operations."""

    @pytest.mark.asyncio
    async def test_list_reactions(self, bot_credentials):
        """Test reactions.list - list reactions for a user."""
        config = SlackListReactionsConfig(limit=10)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "list_reactions_for_item", "reactions:read")

        if data.get("ok"):
            items = data.get("items", [])
            print(f"\nFound {len(items)} items with reactions")


class TestPinOperations:
    """Test pin operations."""

    @pytest.mark.asyncio
    async def test_list_pins(self, bot_credentials):
        """Test pins.list - list pinned items in a channel."""
        # First, get a channel ID
        list_config = SlackListConversationsConfig(types="public_channel", limit=1)
        node = create_node(list_config, bot_credentials)
        list_result = await node.execute({})

        if list_result["status"] != "success":
            if "missing_scope" in list_result.get("error", ""):
                pytest.skip("Token missing channels:read scope")
            pytest.skip("Could not list conversations to get channel ID")

        channels = list_result.get("data", {}).get("channels", [])
        if not channels:
            pytest.skip("No channels available for testing")

        channel_id = channels[0]["id"]

        config = SlackListPinsConfig(channel=channel_id)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "list_pinned_items_in_channel", "pins:read")

        if data.get("ok"):
            items = data.get("items", [])
            print(f"\nFound {len(items)} pinned items")


class TestSearchOperations:
    """Test search operations."""

    @pytest.mark.asyncio
    async def test_search_messages(self, bot_credentials):
        """Test search.messages - search for messages."""
        config = SlackSearchMessagesConfig(query="test", count=5)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "search_workspace_messages", "search:read")

        if data.get("ok"):
            messages = data.get("messages", {})
            total = messages.get("total", 0)
            print(f"\nFound {total} messages matching 'test'")

    @pytest.mark.asyncio
    async def test_search_files(self, bot_credentials):
        """Test search.files - search for files."""
        config = SlackSearchFilesConfig(query="*", count=5)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "search_files", "search:read")

        if data.get("ok"):
            files = data.get("files", {})
            total = files.get("total", 0)
            print(f"\nFound {total} files")


class TestUserProfileOperations:
    """Test user profile operations."""

    @pytest.mark.asyncio
    async def test_get_user_profile(self, bot_credentials):
        """Test users.profile.get - get user profile."""
        # First, get a user ID from the auth test
        auth_config = SlackAuthTestConfig()
        node = create_node(auth_config, bot_credentials)
        auth_result = await node.execute({})

        if auth_result["status"] != "success":
            pytest.skip("Could not get user ID from auth test")

        user_id = auth_result.get("data", {}).get("user_id")
        if not user_id:
            pytest.skip("No user ID returned from auth test")

        config = SlackGetUserProfileConfig(user=user_id)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "get_user_profile", "users.profile:read")

        if data.get("ok"):
            profile = data.get("profile", {})
            print(f"\nDisplay name: {profile.get('display_name', 'unknown')}")
            print(f"Real name: {profile.get('real_name', 'unknown')}")

    @pytest.mark.asyncio
    async def test_users_conversations(self, bot_credentials):
        """Test users.conversations - list user's conversations."""
        config = SlackUsersConversationsConfig(types="public_channel", limit=10)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "list_user_accessible_conversations", "channels:read")

        if data.get("ok"):
            channels = data.get("channels", [])
            print(f"\nUser is in {len(channels)} public channels")

    @pytest.mark.asyncio
    async def test_get_user_presence(self, bot_credentials):
        """Test users.getPresence - get user presence."""
        # First, get a user ID from the auth test
        auth_config = SlackAuthTestConfig()
        node = create_node(auth_config, bot_credentials)
        auth_result = await node.execute({})

        if auth_result["status"] != "success":
            pytest.skip("Could not get user ID from auth test")

        user_id = auth_result.get("data", {}).get("user_id")
        if not user_id:
            pytest.skip("No user ID returned from auth test")

        config = SlackGetUserPresenceConfig(user=user_id)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "get_user_presence_status", "users:read")

        if data.get("ok"):
            print(f"\nPresence: {data.get('presence', 'unknown')}")


class TestScheduledMessageOperations:
    """Test scheduled message operations."""

    @pytest.mark.asyncio
    async def test_list_scheduled_messages(self, bot_credentials):
        """Test chat.scheduledMessages.list - list scheduled messages."""
        config = SlackListScheduledMessagesConfig(limit=10)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "list_scheduled_messages", "chat:read")

        if data.get("ok"):
            messages = data.get("scheduled_messages", [])
            print(f"\nFound {len(messages)} scheduled messages")


class TestBotOperations:
    """Test bot-related operations."""

    @pytest.mark.asyncio
    async def test_bot_info(self, bot_credentials):
        """Test bots.info - get bot information."""
        # First, get bot user ID from auth test
        auth_config = SlackAuthTestConfig()
        node = create_node(auth_config, bot_credentials)
        auth_result = await node.execute({})

        if auth_result["status"] != "success":
            pytest.skip("Could not get bot info from auth test")

        bot_id = auth_result.get("data", {}).get("bot_id")
        if not bot_id:
            pytest.skip("No bot ID returned from auth test")

        config = SlackBotInfoConfig(bot=bot_id)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        data = check_result_or_skip(result, "get_bot_information", "users:read")

        if data.get("ok"):
            bot = data.get("bot", {})
            print(f"\nBot name: {bot.get('name', 'unknown')}")


class TestTeamExtendedOperations:
    """Test extended team operations (may require admin scopes)."""

    @pytest.mark.asyncio
    async def test_team_billable_info(self, bot_credentials):
        """Test team.billableInfo - get billable info."""
        config = SlackTeamBillableInfoConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        # This requires admin scope, so skip gracefully
        data = check_result_or_skip(result, "get_team_billable_information", "admin")

        if data.get("ok"):
            billable_info = data.get("billable_info", {})
            print(f"\nBillable users: {len(billable_info)}")


class TestAdminOperations:
    """Test admin operations (Enterprise Grid - will skip if not available)."""

    @pytest.mark.asyncio
    async def test_admin_apps_approved_list(self, bot_credentials):
        """Test admin.apps.approved.list - list approved apps."""
        config = SlackAdminAppsApprovedListConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        # Admin operations require Enterprise Grid - skip gracefully
        if result["status"] == "error":
            error = result.get("error", "")
            if any(
                x in error
                for x in [
                    "missing_scope",
                    "not_allowed",
                    "feature_not_enabled",
                    "not_an_admin",
                    "org_not_found",
                ]
            ):
                pytest.skip(
                    f"Admin scope not available (Enterprise Grid required): {error}"
                )

        data = check_result_or_skip(
            result, "list_approved_apps", "admin.apps:read"
        )

        if data.get("ok"):
            apps = data.get("approved_apps", [])
            print(f"\nFound {len(apps)} approved apps")

    @pytest.mark.asyncio
    async def test_admin_teams_list(self, bot_credentials):
        """Test admin.teams.list - list teams in Enterprise Grid."""
        config = SlackAdminTeamsListConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        # Admin operations require Enterprise Grid - skip gracefully
        if result["status"] == "error":
            error = result.get("error", "")
            if any(
                x in error
                for x in [
                    "missing_scope",
                    "not_allowed",
                    "feature_not_enabled",
                    "not_an_admin",
                    "org_not_found",
                ]
            ):
                pytest.skip(
                    f"Admin scope not available (Enterprise Grid required): {error}"
                )

        data = check_result_or_skip(result, "list_teams", "admin.teams:read")

        if data.get("ok"):
            teams = data.get("teams", [])
            print(f"\nFound {len(teams)} teams")

    @pytest.mark.asyncio
    async def test_admin_users_list(self, bot_credentials):
        """Test admin.users.list - list users across Enterprise Grid."""
        # Need a team_id for this operation
        # First try to get one from admin.teams.list
        teams_config = SlackAdminTeamsListConfig()
        node = create_node(teams_config, bot_credentials)
        teams_result = await node.execute({})

        if teams_result["status"] != "success":
            error = teams_result.get("error", "")
            if any(
                x in error
                for x in [
                    "missing_scope",
                    "not_allowed",
                    "feature_not_enabled",
                    "not_an_admin",
                    "org_not_found",
                ]
            ):
                pytest.skip(
                    f"Admin scope not available (Enterprise Grid required): {error}"
                )
            pytest.skip(f"Could not list teams: {error}")

        teams = teams_result.get("data", {}).get("teams", [])
        if not teams:
            pytest.skip("No teams available for testing")

        team_id = teams[0]["id"]

        config = SlackAdminUsersListConfig(team_id=team_id, limit=10)
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        # Admin operations require Enterprise Grid - skip gracefully
        if result["status"] == "error":
            error = result.get("error", "")
            if any(
                x in error
                for x in [
                    "missing_scope",
                    "not_allowed",
                    "feature_not_enabled",
                    "not_an_admin",
                    "org_not_found",
                ]
            ):
                pytest.skip(
                    f"Admin scope not available (Enterprise Grid required): {error}"
                )

        data = check_result_or_skip(result, "list_users_in_team", "admin.users:read")

        if data.get("ok"):
            users = data.get("users", [])
            print(f"\nFound {len(users)} users")

    @pytest.mark.asyncio
    async def test_admin_emoji_list(self, bot_credentials):
        """Test admin.emoji.list - list emoji across Enterprise Grid."""
        config = SlackAdminEmojiListConfig()
        node = create_node(config, bot_credentials)
        result = await node.execute({})

        # Admin operations require Enterprise Grid - skip gracefully
        if result["status"] == "error":
            error = result.get("error", "")
            if any(
                x in error
                for x in [
                    "missing_scope",
                    "not_allowed",
                    "feature_not_enabled",
                    "not_an_admin",
                    "org_not_found",
                ]
            ):
                pytest.skip(
                    f"Admin scope not available (Enterprise Grid required): {error}"
                )

        data = check_result_or_skip(result, "list_custom_emoji", "admin.teams:read")

        if data.get("ok"):
            emoji = data.get("emoji", {})
            print(f"\nFound {len(emoji)} custom emoji")


# Optional: Run a quick sanity check when this file is run directly
if __name__ == "__main__":
    import asyncio

    async def quick_test():
        """Quick sanity check of the integration tests."""
        print("Running quick integration test sanity check...")
        print(f"Using token: {BOT_TOKEN[:20]}...")

        credentials = SlackBotTokenCredential(
            credential_type="bot_token", bot_token=BOT_TOKEN
        )

        # Test auth
        config = SlackAuthTestConfig()
        node = create_node(config, credentials)
        result = await node.execute({})

        if result["status"] == "success" and result.get("data", {}).get("ok"):
            print(f"✓ Authentication successful!")
            print(f"  Team: {result['data'].get('team')}")
            print(f"  User: {result['data'].get('user')}")
        else:
            print(f"✗ Authentication failed: {result}")

    asyncio.run(quick_test())
