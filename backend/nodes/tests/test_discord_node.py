"""
Integration tests for Discord node.

Tests the complete Discord node functionality including ALL 137 operations:
- Message operations (11): send, edit, delete, pin, unpin, get messages, crosspost, bulk delete, etc
- Reaction operations (5): create, delete, get, delete all, delete for emoji
- Channel operations (7): get, create, modify, delete, typing, permissions, list
- Thread operations (8): start from message/channel, join, leave, add/remove member, list
- Guild operations (7): list, get, modify, preview, vanity URL, prune
- User/Member operations (9): get user, members, member, modify, kick, ban, unban, get bans
- Role operations (6): get, create, modify, delete, add/remove to member
- Invite operations (5): get, delete, get channel/guild invites, create
- Webhook operations (7): execute, get channel/guild/specific webhooks, create, modify, delete
- Emoji operations (5): list, get, create, modify, delete
- Sticker operations (4): list, get, modify, delete
- Scheduled Events (6): list, get, create, modify, delete, get users
- Auto Moderation (5): list, get, create, modify, delete rules
- Audit Log (1): get audit log
- Stage Instance (4): create, get, modify, delete
- Voice (1): list regions
- Poll (2): get answer voters, end poll
- Soundboard (7): send, list default/guild sounds, get, create, modify, delete
- Guild Templates (7): get, create from template, list, create, sync, modify, delete
- Guild Onboarding (2): get, modify
- DM/Group DM (2): create DM, create group DM
- Application Commands (10): full CRUD for global and guild commands
- SKUs & Entitlements (5): list, create/delete/consume entitlements
- Guild Widget (2): get, modify
- Guild Welcome Screen (2): get, modify
- Voice State (2): modify current user and other users
- Additional User Operations (3): get current user guilds, leave guild, get connections
- Guild Integration (2): get, delete integrations

Uses a real Discord Bot Token to test against the Discord API. Tests are designed to
be non-destructive where possible (read operations). Write operations verify the
action name is correct.
"""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from nodes.core.media_resolver import ResolvedMedia

# Import the node and config classes - ALL 137 operations
from nodes.discord_node import (
    DiscordNode,
    DiscordNodeConfig,
    DiscordBotTokenCredential,
    DiscordBotInstallCredential,
    # Message operations
    DiscordSendMessageConfig,
    DiscordSendEmbedConfig,
    DiscordEditMessageConfig,
    DiscordDeleteMessageConfig,
    DiscordPinMessageConfig,
    DiscordUnpinMessageConfig,
    DiscordGetMessagesConfig,
    DiscordGetPinnedMessagesConfig,
    DiscordGetMessageConfig,
    DiscordCrosspostMessageConfig,
    DiscordBulkDeleteMessagesConfig,
    # Channel operations
    DiscordGetChannelConfig,
    DiscordListChannelsConfig,
    DiscordCreateChannelConfig,
    DiscordModifyChannelConfig,
    DiscordDeleteChannelConfig,
    DiscordTriggerTypingConfig,
    DiscordEditChannelPermissionsConfig,
    # Thread operations
    DiscordStartThreadFromMessageConfig,
    DiscordStartThreadConfig,
    DiscordJoinThreadConfig,
    DiscordLeaveThreadConfig,
    DiscordAddThreadMemberConfig,
    DiscordRemoveThreadMemberConfig,
    DiscordListThreadMembersConfig,
    DiscordListActiveThreadsConfig,
    # Guild operations
    DiscordListGuildsConfig,
    DiscordGetGuildConfig,
    DiscordModifyGuildConfig,
    DiscordGetGuildPreviewConfig,
    DiscordGetGuildVanityUrlConfig,
    DiscordGetGuildMembersConfig,
    DiscordGetGuildMemberConfig,
    DiscordModifyGuildMemberConfig,
    DiscordGetGuildRolesConfig,
    DiscordGetGuildBansConfig,
    DiscordGetGuildBanConfig,
    DiscordGetGuildPruneCountConfig,
    DiscordBeginGuildPruneConfig,
    # Member management
    DiscordKickMemberConfig,
    DiscordBanMemberConfig,
    DiscordUnbanMemberConfig,
    # Reactions
    DiscordCreateReactionConfig,
    DiscordDeleteReactionConfig,
    DiscordGetReactionsConfig,
    DiscordDeleteAllReactionsConfig,
    DiscordDeleteAllReactionsForEmojiConfig,
    # Roles
    DiscordCreateRoleConfig,
    DiscordModifyRoleConfig,
    DiscordDeleteRoleConfig,
    DiscordAddRoleToMemberConfig,
    DiscordRemoveRoleFromMemberConfig,
    # Invites
    DiscordGetInviteConfig,
    DiscordDeleteInviteConfig,
    DiscordGetChannelInvitesConfig,
    DiscordCreateChannelInviteConfig,
    DiscordGetGuildInvitesConfig,
    # Webhooks
    DiscordExecuteWebhookConfig,
    DiscordOnApplicationAuthorizedConfig,
    DiscordOnEntitlementCreateConfig,
    DiscordGetChannelWebhooksConfig,
    DiscordGetGuildWebhooksConfig,
    DiscordGetWebhookConfig,
    DiscordCreateWebhookConfig,
    DiscordModifyWebhookConfig,
    DiscordDeleteWebhookConfig,
    # Emojis
    DiscordListGuildEmojisConfig,
    DiscordGetGuildEmojiConfig,
    DiscordCreateGuildEmojiConfig,
    DiscordModifyGuildEmojiConfig,
    DiscordDeleteGuildEmojiConfig,
    # Stickers
    DiscordListGuildStickersConfig,
    DiscordGetGuildStickerConfig,
    DiscordModifyGuildStickerConfig,
    DiscordDeleteGuildStickerConfig,
    # Scheduled Events
    DiscordListScheduledEventsConfig,
    DiscordGetScheduledEventConfig,
    DiscordCreateScheduledEventConfig,
    DiscordModifyScheduledEventConfig,
    DiscordDeleteScheduledEventConfig,
    DiscordGetScheduledEventUsersConfig,
    # Auto Moderation
    DiscordListAutoModRulesConfig,
    DiscordGetAutoModRuleConfig,
    DiscordCreateAutoModRuleConfig,
    DiscordModifyAutoModRuleConfig,
    DiscordDeleteAutoModRuleConfig,
    # Audit Log
    DiscordGetAuditLogConfig,
    # Stage Instance
    DiscordCreateStageInstanceConfig,
    DiscordGetStageInstanceConfig,
    DiscordModifyStageInstanceConfig,
    DiscordDeleteStageInstanceConfig,
    # Voice
    DiscordListVoiceRegionsConfig,
    # Polls
    DiscordGetPollAnswerVotersConfig,
    DiscordEndPollConfig,
    # User
    DiscordGetUserConfig,
    # Soundboard Operations
    DiscordSendSoundboardSoundConfig,
    DiscordListDefaultSoundboardSoundsConfig,
    DiscordListGuildSoundboardSoundsConfig,
    DiscordGetGuildSoundboardSoundConfig,
    DiscordCreateGuildSoundboardSoundConfig,
    DiscordModifyGuildSoundboardSoundConfig,
    DiscordDeleteGuildSoundboardSoundConfig,
    # Guild Template Operations
    DiscordGetGuildTemplateConfig,
    DiscordCreateGuildFromTemplateConfig,
    DiscordGetGuildTemplatesConfig,
    DiscordCreateGuildTemplateConfig,
    DiscordSyncGuildTemplateConfig,
    DiscordModifyGuildTemplateConfig,
    DiscordDeleteGuildTemplateConfig,
    # Guild Onboarding
    DiscordGetGuildOnboardingConfig,
    DiscordModifyGuildOnboardingConfig,
    # DM Operations
    DiscordCreateDMConfig,
    DiscordCreateGroupDMConfig,
    # Application Commands
    DiscordGetGlobalApplicationCommandsConfig,
    DiscordCreateGlobalApplicationCommandConfig,
    DiscordGetGlobalApplicationCommandConfig,
    DiscordEditGlobalApplicationCommandConfig,
    DiscordDeleteGlobalApplicationCommandConfig,
    DiscordGetGuildApplicationCommandsConfig,
    DiscordCreateGuildApplicationCommandConfig,
    DiscordGetGuildApplicationCommandConfig,
    DiscordEditGuildApplicationCommandConfig,
    DiscordDeleteGuildApplicationCommandConfig,
    # SKUs & Entitlements
    DiscordListSKUsConfig,
    DiscordListEntitlementsConfig,
    DiscordCreateTestEntitlementConfig,
    DiscordDeleteTestEntitlementConfig,
    DiscordConsumeEntitlementConfig,
    # Guild Widget
    DiscordGetGuildWidgetConfig,
    DiscordModifyGuildWidgetConfig,
    # Guild Welcome Screen
    DiscordGetGuildWelcomeScreenConfig,
    DiscordModifyGuildWelcomeScreenConfig,
    # Voice State
    DiscordModifyCurrentUserVoiceStateConfig,
    DiscordModifyUserVoiceStateConfig,
    # Additional User Operations
    DiscordGetCurrentUserGuildsConfig,
    DiscordLeaveGuildConfig,
    DiscordGetUserConnectionsConfig,
    # Guild Integration
    DiscordGetGuildIntegrationsConfig,
    DiscordDeleteGuildIntegrationConfig,
)

# Test constants
TEST_GUILD_ID = os.environ.get("DISCORD_TEST_GUILD_ID", "111111111111111111")
TEST_CHANNEL_ID = os.environ.get("DISCORD_TEST_CHANNEL_ID", "222222222222222222")
TEST_USER_ID = os.environ.get("DISCORD_TEST_USER_ID", "123456789012345678")
TEST_MESSAGE_ID = os.environ.get("DISCORD_TEST_MESSAGE_ID", "123456789012345678")

# Environment variable for Bot Token
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")


def get_credentials():
    """Get Discord credentials from environment."""
    if not DISCORD_BOT_TOKEN:
        pytest.skip("DISCORD_BOT_TOKEN environment variable not set")
    return DiscordBotTokenCredential(bot_token=DISCORD_BOT_TOKEN)


def create_node(config) -> DiscordNode:
    """Create a DiscordNode instance with the given config."""
    credentials = get_credentials()
    node_config = DiscordNodeConfig(config=config, credentials=credentials)
    node = DiscordNode(
        node_id="test-node",
        node_type="automation-discord",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


def create_mock_node(config) -> DiscordNode:
    """Create a DiscordNode instance with mock credentials for unit tests."""
    credentials = DiscordBotTokenCredential(bot_token="mock_token_123")
    node_config = DiscordNodeConfig(config=config, credentials=credentials)
    node = DiscordNode(
        node_id="test-node",
        node_type="automation-discord",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


# ============================================================================
# Config Parsing Tests
# ============================================================================


class TestConfigParsing:
    """Test that all Discord config models parse correctly."""

    def test_send_message_config(self):
        """Test SendMessage config parsing."""
        config = DiscordSendMessageConfig(
            channel_id="123456789", content="Hello World", tts=False
        )
        assert config.operation == "send_message_to_channel"
        assert config.channel_id == "123456789"
        assert config.content == "Hello World"

    def test_send_embed_config(self):
        """Test SendEmbed config parsing."""
        config = DiscordSendEmbedConfig(
            channel_id="123456789",
            title="Test Title",
            description="Test Description",
            color=0x5865F2,
        )
        assert config.operation == "send_embed_message_to_channel"
        assert config.title == "Test Title"

    def test_edit_message_config(self):
        """Test EditMessage config parsing."""
        config = DiscordEditMessageConfig(
            channel_id="123456789", message_id="987654321", content="Updated content"
        )
        assert config.operation == "edit_message_content"
        assert config.message_id == "987654321"

    def test_delete_message_config(self):
        """Test DeleteMessage config parsing."""
        config = DiscordDeleteMessageConfig(
            channel_id="123456789", message_id="987654321"
        )
        assert config.operation == "delete_message_from_channel"

    def test_pin_message_config(self):
        """Test PinMessage config parsing."""
        config = DiscordPinMessageConfig(channel_id="123456789", message_id="987654321")
        assert config.operation == "pin_message_in_channel"

    def test_unpin_message_config(self):
        """Test UnpinMessage config parsing."""
        config = DiscordUnpinMessageConfig(
            channel_id="123456789", message_id="987654321"
        )
        assert config.operation == "unpin_message_from_channel"

    def test_get_messages_config(self):
        """Test GetMessages config parsing."""
        config = DiscordGetMessagesConfig(channel_id="123456789", limit=50)
        assert config.operation == "list_channel_messages"
        assert config.limit == 50

    def test_get_pinned_messages_config(self):
        """Test GetPinnedMessages config parsing."""
        config = DiscordGetPinnedMessagesConfig(channel_id="123456789")
        assert config.operation == "list_pinned_messages_in_channel"

    def test_get_channel_config(self):
        """Test GetChannel config parsing."""
        config = DiscordGetChannelConfig(channel_id="123456789")
        assert config.operation == "get_channel_info"

    def test_list_channels_config(self):
        """Test ListChannels config parsing."""
        config = DiscordListChannelsConfig(guild_id="123456789")
        assert config.operation == "list_guild_channels"

    def test_list_guilds_config(self):
        """Test ListGuilds config parsing."""
        config = DiscordListGuildsConfig(limit=100)
        assert config.operation == "list_user_guilds"

    def test_get_guild_config(self):
        """Test GetGuild config parsing."""
        config = DiscordGetGuildConfig(guild_id="123456789")
        assert config.operation == "get_guild_info"

    def test_get_guild_members_config(self):
        """Test GetGuildMembers config parsing."""
        config = DiscordGetGuildMembersConfig(guild_id="123456789", limit=100)
        assert config.operation == "list_guild_members"
        assert config.limit == 100

    def test_get_guild_member_config(self):
        """Test GetGuildMember config parsing."""
        config = DiscordGetGuildMemberConfig(guild_id="123456789", user_id="987654321")
        assert config.operation == "get_guild_member_info"

    def test_modify_guild_member_config(self):
        """Test ModifyGuildMember config parsing."""
        config = DiscordModifyGuildMemberConfig(
            guild_id="123456789",
            user_id="987654321",
            nick="New Nickname",
            roles=["role1", "role2"],
        )
        assert config.operation == "update_guild_member_info"
        assert config.nick == "New Nickname"
        assert len(config.roles) == 2

    def test_get_guild_roles_config(self):
        """Test GetGuildRoles config parsing."""
        config = DiscordGetGuildRolesConfig(guild_id="123456789")
        assert config.operation == "list_guild_roles"

    def test_kick_member_config(self):
        """Test KickMember config parsing."""
        config = DiscordKickMemberConfig(guild_id="123456789", user_id="987654321")
        assert config.operation == "kick_member_from_guild"

    def test_ban_member_config(self):
        """Test BanMember config parsing."""
        config = DiscordBanMemberConfig(
            guild_id="123456789", user_id="987654321", delete_message_days=7
        )
        assert config.operation == "ban_member_from_guild"
        assert config.delete_message_days == 7

    def test_unban_member_config(self):
        """Test UnbanMember config parsing."""
        config = DiscordUnbanMemberConfig(guild_id="123456789", user_id="987654321")
        assert config.operation == "unban_member_from_guild"

    def test_create_reaction_config(self):
        """Test CreateReaction config parsing."""
        config = DiscordCreateReactionConfig(
            channel_id="123456789", message_id="987654321", emoji="👍"
        )
        assert config.operation == "add_reaction_to_message"
        assert config.emoji == "👍"

    def test_delete_reaction_config(self):
        """Test DeleteReaction config parsing."""
        config = DiscordDeleteReactionConfig(
            channel_id="123456789", message_id="987654321", emoji="👍"
        )
        assert config.operation == "remove_reaction_from_message"

    def test_execute_webhook_config(self):
        """Test ExecuteWebhook config parsing."""
        config = DiscordExecuteWebhookConfig(
            webhook_url="https://discord.com/api/webhooks/123/abc",
            content="Webhook message",
            username="Bot Name",
            embed_title="Title",
            embed_description="Description",
        )
        assert config.operation == "execute_webhook_send_message"
        assert config.username == "Bot Name"

    def test_discord_trigger_configs(self):
        """Test Discord trigger config parsing."""
        assert (
            DiscordOnApplicationAuthorizedConfig().operation
            == "on_application_authorized"
        )
        assert DiscordOnEntitlementCreateConfig().operation == "on_entitlement_create"

    def test_get_user_config(self):
        """Test GetUser config parsing."""
        config = DiscordGetUserConfig()
        assert config.operation == "get_authenticated_user_info"

    # Soundboard Operations
    def test_send_soundboard_sound_config(self):
        """Test SendSoundboardSound config parsing."""
        config = DiscordSendSoundboardSoundConfig(
            channel_id="123456789", sound_id="987654321", source_guild_id="111222333"
        )
        assert config.operation == "play_soundboard_sound_in_voice_channel"
        assert config.sound_id == "987654321"

    def test_list_default_soundboard_sounds_config(self):
        """Test ListDefaultSoundboardSounds config parsing."""
        config = DiscordListDefaultSoundboardSoundsConfig()
        assert config.operation == "list_default_soundboard_sounds"

    def test_list_guild_soundboard_sounds_config(self):
        """Test ListGuildSoundboardSounds config parsing."""
        config = DiscordListGuildSoundboardSoundsConfig(guild_id="123456789")
        assert config.operation == "list_guild_soundboard_sounds"

    def test_get_guild_soundboard_sound_config(self):
        """Test GetGuildSoundboardSound config parsing."""
        config = DiscordGetGuildSoundboardSoundConfig(
            guild_id="123456789", sound_id="987654321"
        )
        assert config.operation == "get_guild_soundboard_sound"

    def test_create_guild_soundboard_sound_config(self):
        """Test CreateGuildSoundboardSound config parsing."""
        config = DiscordCreateGuildSoundboardSoundConfig(
            guild_id="123456789", name="Test Sound", sound="base64data", volume=0.8
        )
        assert config.operation == "create_guild_soundboard_sound"
        assert config.volume == 0.8

    def test_modify_guild_soundboard_sound_config(self):
        """Test ModifyGuildSoundboardSound config parsing."""
        config = DiscordModifyGuildSoundboardSoundConfig(
            guild_id="123456789", sound_id="987654321", name="Updated Sound", volume=0.5
        )
        assert config.operation == "update_guild_soundboard_sound"

    def test_delete_guild_soundboard_sound_config(self):
        """Test DeleteGuildSoundboardSound config parsing."""
        config = DiscordDeleteGuildSoundboardSoundConfig(
            guild_id="123456789", sound_id="987654321"
        )
        assert config.operation == "delete_guild_soundboard_sound"

    # Guild Template Operations
    def test_get_guild_template_config(self):
        """Test GetGuildTemplate config parsing."""
        config = DiscordGetGuildTemplateConfig(template_code="abc123")
        assert config.operation == "get_guild_template"

    def test_create_guild_from_template_config(self):
        """Test CreateGuildFromTemplate config parsing."""
        config = DiscordCreateGuildFromTemplateConfig(
            template_code="abc123", name="New Guild"
        )
        assert config.operation == "create_guild_from_template"

    def test_get_guild_templates_config(self):
        """Test GetGuildTemplates config parsing."""
        config = DiscordGetGuildTemplatesConfig(guild_id="123456789")
        assert config.operation == "list_guild_templates"

    def test_create_guild_template_config(self):
        """Test CreateGuildTemplate config parsing."""
        config = DiscordCreateGuildTemplateConfig(
            guild_id="123456789", name="My Template", description="Test template"
        )
        assert config.operation == "create_guild_template"

    def test_sync_guild_template_config(self):
        """Test SyncGuildTemplate config parsing."""
        config = DiscordSyncGuildTemplateConfig(
            guild_id="123456789", template_code="abc123"
        )
        assert config.operation == "sync_guild_template_with_state"

    def test_modify_guild_template_config(self):
        """Test ModifyGuildTemplate config parsing."""
        config = DiscordModifyGuildTemplateConfig(
            guild_id="123456789", template_code="abc123", name="Updated Template"
        )
        assert config.operation == "update_guild_template"

    def test_delete_guild_template_config(self):
        """Test DeleteGuildTemplate config parsing."""
        config = DiscordDeleteGuildTemplateConfig(
            guild_id="123456789", template_code="abc123"
        )
        assert config.operation == "delete_guild_template"

    # Guild Onboarding Operations
    def test_get_guild_onboarding_config(self):
        """Test GetGuildOnboarding config parsing."""
        config = DiscordGetGuildOnboardingConfig(guild_id="123456789")
        assert config.operation == "get_guild_onboarding_config"

    def test_modify_guild_onboarding_config(self):
        """Test ModifyGuildOnboarding config parsing."""
        config = DiscordModifyGuildOnboardingConfig(
            guild_id="123456789", enabled=True, default_channel_ids=["111", "222"]
        )
        assert config.operation == "update_guild_onboarding_config"

    # DM Operations
    def test_create_dm_config(self):
        """Test CreateDM config parsing."""
        config = DiscordCreateDMConfig(recipient_id="123456789")
        assert config.operation == "create_direct_message_channel"

    def test_create_group_dm_config(self):
        """Test CreateGroupDM config parsing."""
        config = DiscordCreateGroupDMConfig(
            access_tokens=["token1", "token2"], nicks={"user1": "Nick1"}
        )
        assert config.operation == "create_group_direct_message_channel"

    # Application Commands Operations
    def test_get_global_application_commands_config(self):
        """Test GetGlobalApplicationCommands config parsing."""
        config = DiscordGetGlobalApplicationCommandsConfig(
            application_id="123456789", with_localizations=True
        )
        assert config.operation == "list_global_application_commands"

    def test_create_global_application_command_config(self):
        """Test CreateGlobalApplicationCommand config parsing."""
        config = DiscordCreateGlobalApplicationCommandConfig(
            application_id="123456789",
            name="test-command",
            description="Test command",
            type=1,
        )
        assert config.operation == "create_global_application_command"

    def test_get_global_application_command_config(self):
        """Test GetGlobalApplicationCommand config parsing."""
        config = DiscordGetGlobalApplicationCommandConfig(
            application_id="123456789", command_id="987654321"
        )
        assert config.operation == "get_global_application_command"

    def test_edit_global_application_command_config(self):
        """Test EditGlobalApplicationCommand config parsing."""
        config = DiscordEditGlobalApplicationCommandConfig(
            application_id="123456789", command_id="987654321", name="updated-command"
        )
        assert config.operation == "edit_global_application_command"

    def test_delete_global_application_command_config(self):
        """Test DeleteGlobalApplicationCommand config parsing."""
        config = DiscordDeleteGlobalApplicationCommandConfig(
            application_id="123456789", command_id="987654321"
        )
        assert config.operation == "delete_global_application_command"

    def test_get_guild_application_commands_config(self):
        """Test GetGuildApplicationCommands config parsing."""
        config = DiscordGetGuildApplicationCommandsConfig(
            application_id="123456789", guild_id="987654321"
        )
        assert config.operation == "list_guild_application_commands"

    def test_create_guild_application_command_config(self):
        """Test CreateGuildApplicationCommand config parsing."""
        config = DiscordCreateGuildApplicationCommandConfig(
            application_id="123456789",
            guild_id="987654321",
            name="test-command",
            description="Test command",
        )
        assert config.operation == "create_guild_application_command"

    def test_get_guild_application_command_config(self):
        """Test GetGuildApplicationCommand config parsing."""
        config = DiscordGetGuildApplicationCommandConfig(
            application_id="123456789", guild_id="987654321", command_id="111222333"
        )
        assert config.operation == "get_guild_application_command"

    def test_edit_guild_application_command_config(self):
        """Test EditGuildApplicationCommand config parsing."""
        config = DiscordEditGuildApplicationCommandConfig(
            application_id="123456789",
            guild_id="987654321",
            command_id="111222333",
            description="Updated description",
        )
        assert config.operation == "edit_guild_application_command"

    def test_delete_guild_application_command_config(self):
        """Test DeleteGuildApplicationCommand config parsing."""
        config = DiscordDeleteGuildApplicationCommandConfig(
            application_id="123456789", guild_id="987654321", command_id="111222333"
        )
        assert config.operation == "delete_guild_application_command"

    # SKUs & Entitlements Operations
    def test_list_skus_config(self):
        """Test ListSKUs config parsing."""
        config = DiscordListSKUsConfig(application_id="123456789")
        assert config.operation == "list_application_skus"

    def test_list_entitlements_config(self):
        """Test ListEntitlements config parsing."""
        config = DiscordListEntitlementsConfig(
            application_id="123456789", user_id="987654321", exclude_ended=True
        )
        assert config.operation == "list_application_entitlements"

    def test_create_test_entitlement_config(self):
        """Test CreateTestEntitlement config parsing."""
        config = DiscordCreateTestEntitlementConfig(
            application_id="123456789",
            sku_id="987654321",
            owner_id="111222333",
            owner_type=2,
        )
        assert config.operation == "create_test_entitlement"

    def test_delete_test_entitlement_config(self):
        """Test DeleteTestEntitlement config parsing."""
        config = DiscordDeleteTestEntitlementConfig(
            application_id="123456789", entitlement_id="987654321"
        )
        assert config.operation == "delete_test_entitlement"

    def test_consume_entitlement_config(self):
        """Test ConsumeEntitlement config parsing."""
        config = DiscordConsumeEntitlementConfig(
            application_id="123456789", entitlement_id="987654321"
        )
        assert config.operation == "consume_one_time_purchase_entitlement"

    # Guild Widget Operations
    def test_get_guild_widget_config(self):
        """Test GetGuildWidget config parsing."""
        config = DiscordGetGuildWidgetConfig(guild_id="123456789")
        assert config.operation == "get_guild_widget_settings"

    def test_modify_guild_widget_config(self):
        """Test ModifyGuildWidget config parsing."""
        config = DiscordModifyGuildWidgetConfig(
            guild_id="123456789", enabled=True, channel_id="987654321"
        )
        assert config.operation == "update_guild_widget_settings"

    # Guild Welcome Screen Operations
    def test_get_guild_welcome_screen_config(self):
        """Test GetGuildWelcomeScreen config parsing."""
        config = DiscordGetGuildWelcomeScreenConfig(guild_id="123456789")
        assert config.operation == "get_guild_welcome_screen"

    def test_modify_guild_welcome_screen_config(self):
        """Test ModifyGuildWelcomeScreen config parsing."""
        config = DiscordModifyGuildWelcomeScreenConfig(
            guild_id="123456789", enabled=True, description="Welcome to our server!"
        )
        assert config.operation == "update_guild_welcome_screen"

    # Voice State Operations
    def test_modify_current_user_voice_state_config(self):
        """Test ModifyCurrentUserVoiceState config parsing."""
        config = DiscordModifyCurrentUserVoiceStateConfig(
            guild_id="123456789", channel_id="987654321", suppress=False
        )
        assert config.operation == "update_current_user_voice_state"

    def test_modify_user_voice_state_config(self):
        """Test ModifyUserVoiceState config parsing."""
        config = DiscordModifyUserVoiceStateConfig(
            guild_id="123456789",
            channel_id="987654321",
            user_id="111222333",
            suppress=True,
        )
        assert config.operation == "update_user_voice_state"

    # Additional User Operations
    def test_get_current_user_guilds_config(self):
        """Test GetCurrentUserGuilds config parsing."""
        config = DiscordGetCurrentUserGuildsConfig(limit=100, after="123456789")
        assert config.operation == "list_current_user_guilds"

    def test_leave_guild_config(self):
        """Test LeaveGuild config parsing."""
        config = DiscordLeaveGuildConfig(guild_id="123456789")
        assert config.operation == "leave_guild"

    def test_get_user_connections_config(self):
        """Test GetUserConnections config parsing."""
        config = DiscordGetUserConnectionsConfig()
        assert config.operation == "list_user_connections"

    # Guild Integration Operations
    def test_get_guild_integrations_config(self):
        """Test GetGuildIntegrations config parsing."""
        config = DiscordGetGuildIntegrationsConfig(guild_id="123456789")
        assert config.operation == "list_guild_integrations"

    def test_delete_guild_integration_config(self):
        """Test DeleteGuildIntegration config parsing."""
        config = DiscordDeleteGuildIntegrationConfig(
            guild_id="123456789", integration_id="987654321"
        )
        assert config.operation == "delete_guild_integration"

    # Channel Operations (Additional)
    def test_create_channel_config(self):
        """Test CreateChannel config parsing."""
        config = DiscordCreateChannelConfig(
            guild_id="123456789", name="new-channel", type=0
        )
        assert config.operation == "create_channel_in_guild"
        assert config.name == "new-channel"

    def test_modify_channel_config(self):
        """Test ModifyChannel config parsing."""
        config = DiscordModifyChannelConfig(
            channel_id="123456789", name="updated-channel", topic="New topic"
        )
        assert config.operation == "update_channel_settings"
        assert config.name == "updated-channel"

    def test_delete_channel_config(self):
        """Test DeleteChannel config parsing."""
        config = DiscordDeleteChannelConfig(channel_id="123456789")
        assert config.operation == "delete_channel"
        assert config.channel_id == "123456789"

    def test_trigger_typing_config(self):
        """Test TriggerTyping config parsing."""
        config = DiscordTriggerTypingConfig(channel_id="123456789")
        assert config.operation == "show_typing_indicator_in_channel"
        assert config.channel_id == "123456789"

    def test_bulk_delete_messages_config(self):
        """Test BulkDeleteMessages config parsing."""
        config = DiscordBulkDeleteMessagesConfig(
            channel_id="123456789", message_ids=["111", "222", "333"]
        )
        assert config.operation == "bulk_delete_channel_messages"
        assert len(config.message_ids) == 3

    def test_edit_channel_permissions_config(self):
        """Test EditChannelPermissions config parsing."""
        config = DiscordEditChannelPermissionsConfig(
            channel_id="123456789", overwrite_id="987654321", type=0, allow="1024"
        )
        assert config.operation == "edit_channel_permission_overwrites"
        assert config.type == 0

    # Thread Operations (Additional)
    def test_start_thread_from_message_config(self):
        """Test StartThreadFromMessage config parsing."""
        config = DiscordStartThreadFromMessageConfig(
            channel_id="123456789", message_id="987654321", name="Discussion Thread"
        )
        assert config.operation == "start_thread_from_existing_message"
        assert config.name == "Discussion Thread"

    def test_start_thread_config(self):
        """Test StartThread config parsing."""
        config = DiscordStartThreadConfig(
            channel_id="123456789", name="Forum Thread", type=11
        )
        assert config.operation == "start_thread_in_forum_channel"
        assert config.name == "Forum Thread"

    def test_join_thread_config(self):
        """Test JoinThread config parsing."""
        config = DiscordJoinThreadConfig(thread_id="123456789")
        assert config.operation == "join_thread"
        assert config.thread_id == "123456789"

    def test_leave_thread_config(self):
        """Test LeaveThread config parsing."""
        config = DiscordLeaveThreadConfig(thread_id="123456789")
        assert config.operation == "leave_thread"
        assert config.thread_id == "123456789"

    def test_add_thread_member_config(self):
        """Test AddThreadMember config parsing."""
        config = DiscordAddThreadMemberConfig(
            thread_id="123456789", user_id="987654321"
        )
        assert config.operation == "add_member_to_thread"
        assert config.user_id == "987654321"

    def test_remove_thread_member_config(self):
        """Test RemoveThreadMember config parsing."""
        config = DiscordRemoveThreadMemberConfig(
            thread_id="123456789", user_id="987654321"
        )
        assert config.operation == "remove_member_from_thread"
        assert config.user_id == "987654321"

    def test_list_thread_members_config(self):
        """Test ListThreadMembers config parsing."""
        config = DiscordListThreadMembersConfig(thread_id="123456789")
        assert config.operation == "list_thread_members"
        assert config.thread_id == "123456789"

    def test_list_active_threads_config(self):
        """Test ListActiveThreads config parsing."""
        config = DiscordListActiveThreadsConfig(guild_id="123456789")
        assert config.operation == "list_guild_active_threads"
        assert config.guild_id == "123456789"

    # Message Operations (Additional)
    def test_get_message_config(self):
        """Test GetMessage config parsing."""
        config = DiscordGetMessageConfig(channel_id="123456789", message_id="987654321")
        assert config.operation == "get_message_by_id"
        assert config.message_id == "987654321"

    def test_crosspost_message_config(self):
        """Test CrosspostMessage config parsing."""
        config = DiscordCrosspostMessageConfig(
            channel_id="123456789", message_id="987654321"
        )
        assert config.operation == "crosspost_message_to_announcement_channel"
        assert config.channel_id == "123456789"

    # Reaction Operations (Additional)
    def test_get_reactions_config(self):
        """Test GetReactions config parsing."""
        config = DiscordGetReactionsConfig(
            channel_id="123456789", message_id="987654321", emoji="👍", limit=50
        )
        assert config.operation == "list_message_reaction_users"
        assert config.emoji == "👍"

    def test_delete_all_reactions_config(self):
        """Test DeleteAllReactions config parsing."""
        config = DiscordDeleteAllReactionsConfig(
            channel_id="123456789", message_id="987654321"
        )
        assert config.operation == "delete_all_message_reactions"
        assert config.message_id == "987654321"

    def test_delete_all_reactions_for_emoji_config(self):
        """Test DeleteAllReactionsForEmoji config parsing."""
        config = DiscordDeleteAllReactionsForEmojiConfig(
            channel_id="123456789", message_id="987654321", emoji="😀"
        )
        assert config.operation == "delete_emoji_reactions_from_message"
        assert config.emoji == "😀"

    # Role Operations (Additional)
    def test_create_role_config(self):
        """Test CreateRole config parsing."""
        config = DiscordCreateRoleConfig(
            guild_id="123456789", name="Admin", color=0xFF0000, hoist=True
        )
        assert config.operation == "create_role_in_guild"
        assert config.name == "Admin"

    def test_modify_role_config(self):
        """Test ModifyRole config parsing."""
        config = DiscordModifyRoleConfig(
            guild_id="123456789",
            role_id="987654321",
            name="Updated Role",
            color=0x00FF00,
        )
        assert config.operation == "update_guild_role"
        assert config.name == "Updated Role"

    def test_delete_role_config(self):
        """Test DeleteRole config parsing."""
        config = DiscordDeleteRoleConfig(guild_id="123456789", role_id="987654321")
        assert config.operation == "delete_role_from_guild"
        assert config.role_id == "987654321"

    def test_add_role_to_member_config(self):
        """Test AddRoleToMember config parsing."""
        config = DiscordAddRoleToMemberConfig(
            guild_id="123456789", user_id="987654321", role_id="111222333"
        )
        assert config.operation == "add_role_to_guild_member"
        assert config.role_id == "111222333"

    def test_remove_role_from_member_config(self):
        """Test RemoveRoleFromMember config parsing."""
        config = DiscordRemoveRoleFromMemberConfig(
            guild_id="123456789", user_id="987654321", role_id="111222333"
        )
        assert config.operation == "remove_role_from_guild_member"
        assert config.role_id == "111222333"

    # Invite Operations (Additional)
    def test_get_invite_config(self):
        """Test GetInvite config parsing."""
        config = DiscordGetInviteConfig(invite_code="abc123", with_counts=True)
        assert config.operation == "get_invite_info"
        assert config.invite_code == "abc123"

    def test_delete_invite_config(self):
        """Test DeleteInvite config parsing."""
        config = DiscordDeleteInviteConfig(invite_code="abc123")
        assert config.operation == "delete_invite"
        assert config.invite_code == "abc123"

    def test_get_channel_invites_config(self):
        """Test GetChannelInvites config parsing."""
        config = DiscordGetChannelInvitesConfig(channel_id="123456789")
        assert config.operation == "list_channel_invites"
        assert config.channel_id == "123456789"

    def test_create_channel_invite_config(self):
        """Test CreateChannelInvite config parsing."""
        config = DiscordCreateChannelInviteConfig(
            channel_id="123456789", max_age=3600, max_uses=10
        )
        assert config.operation == "create_channel_invite"
        assert config.max_age == 3600

    def test_get_guild_invites_config(self):
        """Test GetGuildInvites config parsing."""
        config = DiscordGetGuildInvitesConfig(guild_id="123456789")
        assert config.operation == "list_guild_invites"
        assert config.guild_id == "123456789"

    # Webhook Operations (Additional)
    def test_get_channel_webhooks_config(self):
        """Test GetChannelWebhooks config parsing."""
        config = DiscordGetChannelWebhooksConfig(channel_id="123456789")
        assert config.operation == "list_channel_webhooks"
        assert config.channel_id == "123456789"

    def test_get_guild_webhooks_config(self):
        """Test GetGuildWebhooks config parsing."""
        config = DiscordGetGuildWebhooksConfig(guild_id="123456789")
        assert config.operation == "list_guild_webhooks"
        assert config.guild_id == "123456789"

    def test_get_webhook_config(self):
        """Test GetWebhook config parsing."""
        config = DiscordGetWebhookConfig(webhook_id="123456789")
        assert config.operation == "get_webhook_by_id"
        assert config.webhook_id == "123456789"

    def test_create_webhook_config(self):
        """Test CreateWebhook config parsing."""
        config = DiscordCreateWebhookConfig(channel_id="123456789", name="My Webhook")
        assert config.operation == "create_channel_webhook"
        assert config.name == "My Webhook"

    def test_modify_webhook_config(self):
        """Test ModifyWebhook config parsing."""
        config = DiscordModifyWebhookConfig(
            webhook_id="123456789", name="Updated Webhook"
        )
        assert config.operation == "update_webhook_settings"
        assert config.name == "Updated Webhook"

    def test_delete_webhook_config(self):
        """Test DeleteWebhook config parsing."""
        config = DiscordDeleteWebhookConfig(webhook_id="123456789")
        assert config.operation == "delete_webhook"
        assert config.webhook_id == "123456789"

    # Emoji Operations (Additional)
    def test_list_guild_emojis_config(self):
        """Test ListGuildEmojis config parsing."""
        config = DiscordListGuildEmojisConfig(guild_id="123456789")
        assert config.operation == "list_guild_emojis"
        assert config.guild_id == "123456789"

    def test_get_guild_emoji_config(self):
        """Test GetGuildEmoji config parsing."""
        config = DiscordGetGuildEmojiConfig(guild_id="123456789", emoji_id="987654321")
        assert config.operation == "get_emoji_from_guild"
        assert config.emoji_id == "987654321"

    def test_create_guild_emoji_config(self):
        """Test CreateGuildEmoji config parsing."""
        config = DiscordCreateGuildEmojiConfig(
            guild_id="123456789",
            name="custom_emoji",
            image="data:image/png;base64,abc123",
        )
        assert config.operation == "create_emoji_in_guild"
        assert config.name == "custom_emoji"

    def test_modify_guild_emoji_config(self):
        """Test ModifyGuildEmoji config parsing."""
        config = DiscordModifyGuildEmojiConfig(
            guild_id="123456789", emoji_id="987654321", name="updated_emoji"
        )
        assert config.operation == "update_guild_emoji"
        assert config.name == "updated_emoji"

    def test_delete_guild_emoji_config(self):
        """Test DeleteGuildEmoji config parsing."""
        config = DiscordDeleteGuildEmojiConfig(
            guild_id="123456789", emoji_id="987654321"
        )
        assert config.operation == "delete_emoji_from_guild"
        assert config.emoji_id == "987654321"

    # Sticker Operations (Additional)
    def test_list_guild_stickers_config(self):
        """Test ListGuildStickers config parsing."""
        config = DiscordListGuildStickersConfig(guild_id="123456789")
        assert config.operation == "list_guild_stickers"
        assert config.guild_id == "123456789"

    def test_get_guild_sticker_config(self):
        """Test GetGuildSticker config parsing."""
        config = DiscordGetGuildStickerConfig(
            guild_id="123456789", sticker_id="987654321"
        )
        assert config.operation == "get_sticker_from_guild"
        assert config.sticker_id == "987654321"

    def test_modify_guild_sticker_config(self):
        """Test ModifyGuildSticker config parsing."""
        config = DiscordModifyGuildStickerConfig(
            guild_id="123456789", sticker_id="987654321", name="Updated Sticker"
        )
        assert config.operation == "update_guild_sticker"
        assert config.name == "Updated Sticker"

    def test_delete_guild_sticker_config(self):
        """Test DeleteGuildSticker config parsing."""
        config = DiscordDeleteGuildStickerConfig(
            guild_id="123456789", sticker_id="987654321"
        )
        assert config.operation == "delete_sticker_from_guild"
        assert config.sticker_id == "987654321"

    # Scheduled Events Operations (Additional)
    def test_list_scheduled_events_config(self):
        """Test ListScheduledEvents config parsing."""
        config = DiscordListScheduledEventsConfig(
            guild_id="123456789", with_user_count=True
        )
        assert config.operation == "list_guild_scheduled_events"
        assert config.with_user_count is True

    def test_get_scheduled_event_config(self):
        """Test GetScheduledEvent config parsing."""
        config = DiscordGetScheduledEventConfig(
            guild_id="123456789", event_id="987654321"
        )
        assert config.operation == "get_scheduled_event"
        assert config.event_id == "987654321"

    def test_create_scheduled_event_config(self):
        """Test CreateScheduledEvent config parsing."""
        config = DiscordCreateScheduledEventConfig(
            guild_id="123456789",
            name="Community Event",
            scheduled_start_time="2025-12-25T18:00:00Z",
            entity_type=2,
        )
        assert config.operation == "create_scheduled_event"
        assert config.name == "Community Event"

    def test_modify_scheduled_event_config(self):
        """Test ModifyScheduledEvent config parsing."""
        config = DiscordModifyScheduledEventConfig(
            guild_id="123456789", event_id="987654321", name="Updated Event"
        )
        assert config.operation == "update_scheduled_event"
        assert config.name == "Updated Event"

    def test_delete_scheduled_event_config(self):
        """Test DeleteScheduledEvent config parsing."""
        config = DiscordDeleteScheduledEventConfig(
            guild_id="123456789", event_id="987654321"
        )
        assert config.operation == "delete_scheduled_event"
        assert config.event_id == "987654321"

    def test_get_scheduled_event_users_config(self):
        """Test GetScheduledEventUsers config parsing."""
        config = DiscordGetScheduledEventUsersConfig(
            guild_id="123456789", event_id="987654321", limit=50
        )
        assert config.operation == "list_scheduled_event_users"
        assert config.limit == 50

    # Auto Moderation Operations (Additional)
    def test_list_auto_mod_rules_config(self):
        """Test ListAutoModRules config parsing."""
        config = DiscordListAutoModRulesConfig(guild_id="123456789")
        assert config.operation == "list_guild_auto_moderation_rules"
        assert config.guild_id == "123456789"

    def test_get_auto_mod_rule_config(self):
        """Test GetAutoModRule config parsing."""
        config = DiscordGetAutoModRuleConfig(guild_id="123456789", rule_id="987654321")
        assert config.operation == "get_auto_moderation_rule"
        assert config.rule_id == "987654321"

    def test_create_auto_mod_rule_config(self):
        """Test CreateAutoModRule config parsing."""
        config = DiscordCreateAutoModRuleConfig(
            guild_id="123456789", name="Profanity Filter", event_type=1, trigger_type=1
        )
        assert config.operation == "create_auto_moderation_rule"
        assert config.name == "Profanity Filter"

    def test_modify_auto_mod_rule_config(self):
        """Test ModifyAutoModRule config parsing."""
        config = DiscordModifyAutoModRuleConfig(
            guild_id="123456789", rule_id="987654321", name="Updated Rule"
        )
        assert config.operation == "update_auto_moderation_rule"
        assert config.name == "Updated Rule"

    def test_delete_auto_mod_rule_config(self):
        """Test DeleteAutoModRule config parsing."""
        config = DiscordDeleteAutoModRuleConfig(
            guild_id="123456789", rule_id="987654321"
        )
        assert config.operation == "delete_auto_moderation_rule"
        assert config.rule_id == "987654321"

    # Audit Log Operations
    def test_get_audit_log_config(self):
        """Test GetAuditLog config parsing."""
        config = DiscordGetAuditLogConfig(guild_id="123456789", limit=100)
        assert config.operation == "get_guild_audit_log"
        assert config.limit == 100

    # Stage Instance Operations (Additional)
    def test_create_stage_instance_config(self):
        """Test CreateStageInstance config parsing."""
        config = DiscordCreateStageInstanceConfig(
            channel_id="123456789", topic="Community Stage", privacy_level=2
        )
        assert config.operation == "create_stage_instance"
        assert config.topic == "Community Stage"

    def test_get_stage_instance_config(self):
        """Test GetStageInstance config parsing."""
        config = DiscordGetStageInstanceConfig(channel_id="123456789")
        assert config.operation == "get_stage_instance_for_channel"
        assert config.channel_id == "123456789"

    def test_modify_stage_instance_config(self):
        """Test ModifyStageInstance config parsing."""
        config = DiscordModifyStageInstanceConfig(
            channel_id="123456789", topic="Updated Topic"
        )
        assert config.operation == "update_stage_instance"
        assert config.topic == "Updated Topic"

    def test_delete_stage_instance_config(self):
        """Test DeleteStageInstance config parsing."""
        config = DiscordDeleteStageInstanceConfig(channel_id="123456789")
        assert config.operation == "delete_stage_instance"
        assert config.channel_id == "123456789"

    # Voice Operations (Additional)
    def test_list_voice_regions_config(self):
        """Test ListVoiceRegions config parsing."""
        config = DiscordListVoiceRegionsConfig()
        assert config.operation == "list_available_voice_regions"

    # Guild Operations (Additional)
    def test_modify_guild_config(self):
        """Test ModifyGuild config parsing."""
        config = DiscordModifyGuildConfig(
            guild_id="123456789",
            name="Updated Guild Name",
            description="New description",
        )
        assert config.operation == "update_guild_settings"
        assert config.name == "Updated Guild Name"

    def test_get_guild_preview_config(self):
        """Test GetGuildPreview config parsing."""
        config = DiscordGetGuildPreviewConfig(guild_id="123456789")
        assert config.operation == "get_guild_preview"
        assert config.guild_id == "123456789"

    def test_get_guild_vanity_url_config(self):
        """Test GetGuildVanityUrl config parsing."""
        config = DiscordGetGuildVanityUrlConfig(guild_id="123456789")
        assert config.operation == "get_guild_vanity_url"
        assert config.guild_id == "123456789"

    def test_get_guild_bans_config(self):
        """Test GetGuildBans config parsing."""
        config = DiscordGetGuildBansConfig(guild_id="123456789", limit=50)
        assert config.operation == "list_guild_bans"
        assert config.limit == 50

    def test_get_guild_ban_config(self):
        """Test GetGuildBan config parsing."""
        config = DiscordGetGuildBanConfig(guild_id="123456789", user_id="987654321")
        assert config.operation == "get_guild_ban"
        assert config.user_id == "987654321"

    def test_get_guild_prune_count_config(self):
        """Test GetGuildPruneCount config parsing."""
        config = DiscordGetGuildPruneCountConfig(guild_id="123456789", days=14)
        assert config.operation == "get_guild_prune_count"
        assert config.days == 14

    def test_begin_guild_prune_config(self):
        """Test BeginGuildPrune config parsing."""
        config = DiscordBeginGuildPruneConfig(
            guild_id="123456789", days=7, compute_prune_count=True
        )
        assert config.operation == "begin_guild_prune_for_inactive_members"
        assert config.days == 7

    # Poll Operations (Additional)
    def test_get_poll_answer_voters_config(self):
        """Test GetPollAnswerVoters config parsing."""
        config = DiscordGetPollAnswerVotersConfig(
            channel_id="123456789", message_id="987654321", answer_id=1, limit=50
        )
        assert config.operation == "list_poll_answer_voters"
        assert config.answer_id == 1

    def test_end_poll_config(self):
        """Test EndPoll config parsing."""
        config = DiscordEndPollConfig(channel_id="123456789", message_id="987654321")
        assert config.operation == "end_poll_immediately"
        assert config.message_id == "987654321"


# ============================================================================
# Credential Tests
# ============================================================================


class TestCredentials:
    """Test credential handling."""

    def test_bot_token_credential(self):
        """Test Bot Token credential parsing."""
        cred = DiscordBotTokenCredential(bot_token="test_token_123")
        assert cred.bot_token == "test_token_123"

    def test_bot_install_credential(self):
        """Test Bot Install OAuth credential parsing."""
        cred = DiscordBotInstallCredential(
            guild_id="987654321",
            guild_name="Test Server",
            access_token="access_123",
            refresh_token="refresh_456",
            expires_at="2025-12-31T23:59:59Z",
            username="testuser",
        )
        assert cred.access_token == "access_123"
        assert cred.guild_id == "987654321"
        assert cred.guild_name == "Test Server"
        assert cred.username == "testuser"


# ============================================================================
# Node Config Tests
# ============================================================================


class TestNodeConfig:
    """Test complete node configuration."""

    def test_node_config_with_bot_token(self):
        """Test full node config with bot token credential."""
        config = DiscordSendMessageConfig(
            channel_id="123456789", content="Test message"
        )
        credentials = DiscordBotTokenCredential(bot_token="test_token")
        node_config = DiscordNodeConfig(config=config, credentials=credentials)

        assert node_config.config.operation == "send_message_to_channel"
        assert node_config.credentials.bot_token == "test_token"

    def test_node_config_with_bot_install(self):
        """Test full node config with Bot Install credential."""
        config = DiscordListGuildsConfig()
        credentials = DiscordBotInstallCredential(
            guild_id="987654321",
            access_token="access_123",
            refresh_token="refresh_456",
            expires_at="2025-12-31T23:59:59Z",
        )
        node_config = DiscordNodeConfig(config=config, credentials=credentials)

        assert node_config.config.operation == "list_user_guilds"
        assert node_config.credentials.access_token == "access_123"


# ============================================================================
# Mock API Tests
# ============================================================================


class TestMockAPIOperations:
    """Test Discord API operations with mocked HTTP responses."""

    @pytest.mark.asyncio
    async def test_send_message_mock(self):
        """Test send message with mocked API response."""
        config = DiscordSendMessageConfig(
            channel_id="123456789", content="Test message"
        )
        node = create_mock_node(config)

        mock_response = {
            "id": "111111111111111111",
            "channel_id": "123456789",
            "content": "Test message",
            "timestamp": "2025-01-01T00:00:00.000000+00:00",
            "author": {"id": "222222222222222222", "username": "TestBot"},
        }

        with patch.object(
            node, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            result = await node.execute({})

            assert result["action"] == "send_message_to_channel"
            assert result["content"] == "Test message"
            assert result["message_id"] == "111111111111111111"

    @pytest.mark.asyncio
    async def test_get_channel_mock(self):
        """Test get channel with mocked API response."""
        config = DiscordGetChannelConfig(channel_id="123456789")
        node = create_mock_node(config)

        mock_response = {
            "id": "123456789",
            "type": 0,
            "name": "general",
            "guild_id": "987654321",
        }

        with patch.object(
            node, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            result = await node.execute({})

            assert result["action"] == "get_channel_info"
            assert result["channel"]["name"] == "general"

    @pytest.mark.asyncio
    async def test_list_guilds_mock(self):
        """Test list guilds with mocked API response."""
        config = DiscordListGuildsConfig(limit=10)
        node = create_mock_node(config)

        mock_response = [
            {"id": "111111111111111111", "name": "Test Server 1"},
            {"id": "222222222222222222", "name": "Test Server 2"},
        ]

        with patch.object(
            node, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            result = await node.execute({})

            assert result["action"] == "list_user_guilds"
            assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_get_messages_mock(self):
        """Test get messages with mocked API response."""
        config = DiscordGetMessagesConfig(channel_id="123456789", limit=10)
        node = create_mock_node(config)

        mock_response = [
            {"id": "111", "content": "Message 1"},
            {"id": "222", "content": "Message 2"},
            {"id": "333", "content": "Message 3"},
        ]

        with patch.object(
            node, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            result = await node.execute({})

            assert result["action"] == "list_channel_messages"
            assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_get_guild_members_mock(self):
        """Test get guild members with mocked API response."""
        config = DiscordGetGuildMembersConfig(guild_id="123456789", limit=10)
        node = create_mock_node(config)

        mock_response = [
            {"user": {"id": "111", "username": "User1"}},
            {"user": {"id": "222", "username": "User2"}},
        ]

        with patch.object(
            node, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            result = await node.execute({})

            assert result["action"] == "list_guild_members"
            assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_get_guild_roles_mock(self):
        """Test get guild roles with mocked API response."""
        config = DiscordGetGuildRolesConfig(guild_id="123456789")
        node = create_mock_node(config)

        mock_response = [
            {"id": "111", "name": "@everyone"},
            {"id": "222", "name": "Admin"},
            {"id": "333", "name": "Moderator"},
        ]

        with patch.object(
            node, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            result = await node.execute({})

            assert result["action"] == "list_guild_roles"
            assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_edit_message_mock(self):
        """Test edit message with mocked API response."""
        config = DiscordEditMessageConfig(
            channel_id="123456789", message_id="987654321", content="Updated content"
        )
        node = create_mock_node(config)

        mock_response = {
            "id": "987654321",
            "channel_id": "123456789",
            "content": "Updated content",
        }

        with patch.object(
            node, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            result = await node.execute({})

            assert result["action"] == "edit_message_content"
            assert result["message"]["content"] == "Updated content"

    @pytest.mark.asyncio
    async def test_delete_message_mock(self):
        """Test delete message with mocked API response."""
        config = DiscordDeleteMessageConfig(
            channel_id="123456789", message_id="987654321"
        )
        node = create_mock_node(config)

        with patch.object(
            node, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {"success": True}
            result = await node.execute({})

            assert result["action"] == "delete_message_from_channel"
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_create_reaction_mock(self):
        """Test create reaction with mocked API response."""
        config = DiscordCreateReactionConfig(
            channel_id="123456789", message_id="987654321", emoji="👍"
        )
        node = create_mock_node(config)

        with patch.object(
            node, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {"success": True}
            result = await node.execute({})

            assert result["action"] == "add_reaction_to_message"
            assert result["emoji"] == "👍"

    @pytest.mark.asyncio
    async def test_ban_member_mock(self):
        """Test ban member with mocked API response."""
        config = DiscordBanMemberConfig(
            guild_id="123456789", user_id="987654321", delete_message_days=1
        )
        node = create_mock_node(config)

        with patch.object(
            node, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {"success": True}
            result = await node.execute({})

            assert result["action"] == "ban_member_from_guild"
            assert result["success"] is True

    # Soundboard Mock Tests
    @pytest.mark.asyncio
    async def test_list_guild_soundboard_sounds_mock(self):
        """Test list guild soundboard sounds with mocked API response."""
        config = DiscordListGuildSoundboardSoundsConfig(guild_id="123456789")
        node = create_mock_node(config)

        mock_response = [
            {"sound_id": "111", "name": "Sound 1"},
            {"sound_id": "222", "name": "Sound 2"},
        ]

        with patch.object(
            node, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            result = await node.execute({})

            assert result["action"] == "list_guild_soundboard_sounds"
            assert result["count"] == 2

    # Guild Template Mock Tests
    @pytest.mark.asyncio
    async def test_get_guild_templates_mock(self):
        """Test get guild templates with mocked API response."""
        config = DiscordGetGuildTemplatesConfig(guild_id="123456789")
        node = create_mock_node(config)

        mock_response = [
            {"code": "abc123", "name": "Template 1"},
            {"code": "def456", "name": "Template 2"},
        ]

        with patch.object(
            node, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            result = await node.execute({})

            assert result["action"] == "list_guild_templates"
            assert result["count"] == 2

    # Application Commands Mock Tests
    @pytest.mark.asyncio
    async def test_get_global_application_commands_mock(self):
        """Test get global application commands with mocked API response."""
        config = DiscordGetGlobalApplicationCommandsConfig(application_id="123456789")
        node = create_mock_node(config)

        mock_response = [
            {"id": "111", "name": "command1"},
            {"id": "222", "name": "command2"},
        ]

        with patch.object(
            node, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            result = await node.execute({})

            assert result["action"] == "list_global_application_commands"
            assert result["count"] == 2

    # SKUs Mock Tests
    @pytest.mark.asyncio
    async def test_list_skus_mock(self):
        """Test list SKUs with mocked API response."""
        config = DiscordListSKUsConfig(application_id="123456789")
        node = create_mock_node(config)

        mock_response = [
            {"id": "sku1", "name": "SKU 1"},
            {"id": "sku2", "name": "SKU 2"},
        ]

        with patch.object(
            node, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            result = await node.execute({})

            assert result["action"] == "list_application_skus"
            assert result["count"] == 2

    # User Operations Mock Tests
    @pytest.mark.asyncio
    async def test_get_current_user_guilds_mock(self):
        """Test get current user guilds with mocked API response."""
        config = DiscordGetCurrentUserGuildsConfig(limit=100)
        node = create_mock_node(config)

        mock_response = [
            {"id": "111", "name": "Guild 1"},
            {"id": "222", "name": "Guild 2"},
        ]

        with patch.object(
            node, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            result = await node.execute({})

            assert result["action"] == "list_current_user_guilds"
            assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_get_user_connections_mock(self):
        """Test get user connections with mocked API response."""
        config = DiscordGetUserConnectionsConfig()
        node = create_mock_node(config)

        mock_response = [
            {"type": "github", "name": "username"},
            {"type": "spotify", "name": "spotify_user"},
        ]

        with patch.object(
            node, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response
            result = await node.execute({})

            assert result["action"] == "list_user_connections"
            assert result["count"] == 2


# ============================================================================
# Webhook Tests (No Auth Required)
# ============================================================================


class TestWebhookOperations:
    """Test webhook operations that don't require authentication."""

    @pytest.mark.asyncio
    async def test_execute_webhook_mock(self):
        """Test execute webhook with mocked HTTP response."""
        config = DiscordExecuteWebhookConfig(
            webhook_url="https://discord.com/api/webhooks/123/abc",
            content="Webhook test message",
        )
        # Webhook doesn't need credentials
        node_config = DiscordNodeConfig(config=config, credentials=None)
        node = DiscordNode(
            node_id="test-node",
            node_type="automation-discord",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.text = ""
            mock_client.return_value.__aenter__.return_value.post.return_value = (
                mock_response
            )

            result = await node.execute({})

            assert result["action"] == "execute_webhook_send_message"
            assert result["success"] is True


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_missing_credentials(self):
        """Test that non-webhook operations fail without credentials."""
        config = DiscordSendMessageConfig(channel_id="123456789", content="Test")
        node_config = DiscordNodeConfig(config=config, credentials=None)
        node = DiscordNode(
            node_id="test-node",
            node_type="automation-discord",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="Credentials required"):
            asyncio.run(node.execute({}))


# ============================================================================
# Integration Tests (Requires Real Bot Token)
# ============================================================================


@pytest.mark.skipif(not DISCORD_BOT_TOKEN, reason="DISCORD_BOT_TOKEN not set")
class TestLiveAPIOperations:
    """Integration tests using real Discord API (requires bot token)."""

    @pytest.mark.asyncio
    async def test_get_user_live(self):
        """Test getting authenticated user (bot) information."""
        config = DiscordGetUserConfig()
        node = create_node(config)

        try:
            result = await node.execute({})
        except ValueError as e:
            # Skip test if rate limited by Discord API
            if "429" in str(e):
                pytest.skip(f"Skipping due to Discord API rate limit: {e}")
            raise

        assert result["action"] == "get_authenticated_user_info"
        assert "user" in result

    @pytest.mark.asyncio
    async def test_list_guilds_live(self):
        """Test listing guilds the bot is in."""
        config = DiscordListGuildsConfig(limit=10)
        node = create_node(config)

        try:
            result = await node.execute({})
        except ValueError as e:
            # Skip test if rate limited by Discord API
            if "429" in str(e):
                pytest.skip(f"Skipping due to Discord API rate limit: {e}")
            raise

        assert result["action"] == "list_user_guilds"
        # Bot might not be in any guilds during testing
        assert "guilds" in result or "count" in result

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.environ.get("DISCORD_TEST_CHANNEL_ID"),
        reason="DISCORD_TEST_CHANNEL_ID not set",
    )
    async def test_get_channel_live(self):
        """Test getting channel information."""
        config = DiscordGetChannelConfig(channel_id=TEST_CHANNEL_ID)
        node = create_node(config)

        try:
            result = await node.execute({})
        except ValueError as e:
            # Skip test if rate limited by Discord API
            if "429" in str(e):
                pytest.skip(f"Skipping due to Discord API rate limit: {e}")
            raise

        assert result["action"] == "get_channel_info"

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.environ.get("DISCORD_TEST_GUILD_ID"),
        reason="DISCORD_TEST_GUILD_ID not set",
    )
    async def test_get_guild_live(self):
        """Test getting guild information."""
        config = DiscordGetGuildConfig(guild_id=TEST_GUILD_ID)
        node = create_node(config)

        try:
            result = await node.execute({})
        except ValueError as e:
            # Skip test if rate limited by Discord API
            if "429" in str(e):
                pytest.skip(f"Skipping due to Discord API rate limit: {e}")
            raise

        assert result["action"] == "get_guild_info"

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.environ.get("DISCORD_TEST_GUILD_ID"),
        reason="DISCORD_TEST_GUILD_ID not set",
    )
    async def test_get_guild_roles_live(self):
        """Test getting guild roles."""
        config = DiscordGetGuildRolesConfig(guild_id=TEST_GUILD_ID)
        node = create_node(config)

        try:
            result = await node.execute({})
        except ValueError as e:
            # Skip test if rate limited by Discord API
            if "429" in str(e):
                pytest.skip(f"Skipping due to Discord API rate limit: {e}")
            raise

        assert result["action"] == "list_guild_roles"
        assert "roles" in result


class TestDynamicOptions:
    """Test Discord dynamic dropdown schema and option loading."""

    def test_schema_injects_dynamic_options(self):
        schema = DiscordNode.get_config_schema()

        send_message_props = schema["$defs"]["DiscordSendMessageConfig"]["properties"]
        assert send_message_props["channel_id"]["x-dynamic-options"]["field_name"] == "channel_id"
        assert "depends_on" not in send_message_props["channel_id"]["x-dynamic-options"]

        add_role_props = schema["$defs"]["DiscordAddRoleToMemberConfig"]["properties"]
        assert add_role_props["guild_id"]["x-dynamic-options"]["field_name"] == "guild_id"
        assert add_role_props["user_id"]["x-dynamic-options"]["depends_on"] == "guild_id"
        assert add_role_props["role_id"]["x-dynamic-options"]["depends_on"] == "guild_id"

    @pytest.mark.asyncio
    async def test_load_channel_options_without_guild_context_aggregates_guilds(self):
        side_effect = [
            [
                {"id": "guild-1", "name": "Engineering"},
                {"id": "guild-2", "name": "Operations"},
            ],
            [{"id": "chan-1", "name": "general", "type": 0}],
            [{"id": "chan-2", "name": "alerts", "type": 0}],
        ]

        with patch.object(
            DiscordNode,
            "_dynamic_options_request",
            new=AsyncMock(side_effect=side_effect),
        ):
            result = await DiscordNode.load_field_options(
                "channel_id",
                {"bot_token": "test-token"},
                search="alert",
            )

        assert result["next_page_token"] is None
        assert result["options"] == [
            {
                "value": "chan-2",
                "label": "Operations / #alerts",
                "metadata": {
                    "guild_id": "guild-2",
                    "guild_name": "Operations",
                    "type": 0,
                },
            }
        ]

    @pytest.mark.asyncio
    async def test_load_role_options_requires_guild_context(self):
        with pytest.raises(ValueError, match="Select a server first to load roles"):
            await DiscordNode.load_field_options(
                "role_id",
                {"bot_token": "test-token"},
                context={},
            )



# ============================================================================
# Webhook & Emoji Management - Mock Execution Tests
# ============================================================================


class TestWebhookEmojiMockOperations:
    """Execute the webhook/emoji management handlers against a mocked API."""

    @pytest.mark.asyncio
    async def test_get_channel_webhooks_mock(self):
        config = DiscordGetChannelWebhooksConfig(channel_id="123456789")
        node = create_mock_node(config)

        with patch.object(node, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = [{"id": "wh1", "name": "hook"}]
            result = await node.execute({})

            mock_request.assert_awaited_once()
            assert mock_request.call_args.args[0] == "GET"
            assert mock_request.call_args.args[1] == "/channels/123456789/webhooks"
            assert result["action"] == "list_channel_webhooks"
            assert result["webhooks"][0]["id"] == "wh1"

    @pytest.mark.asyncio
    async def test_create_webhook_mock_resolves_avatar_to_data_uri(self):
        config = DiscordCreateWebhookConfig(
            channel_id="123456789",
            name="My Webhook",
            avatar="https://example.com/avatar.png",
        )
        node = create_mock_node(config)

        resolved = ResolvedMedia(
            data=b"img", mime_type="image/png", filename="avatar.png"
        )

        with patch(
            "nodes.core.media_resolver.resolve_media_input",
            new=AsyncMock(return_value=resolved),
        ), patch.object(node, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"id": "wh1", "name": "My Webhook"}
            result = await node.execute({})

            assert mock_request.call_args.args[0] == "POST"
            assert mock_request.call_args.args[1] == "/channels/123456789/webhooks"
            payload = mock_request.call_args.kwargs["json_data"]
            assert payload["name"] == "My Webhook"
            # Discord wants the avatar as a base64 image data URI, not a URL.
            assert payload["avatar"] == "data:image/png;base64,aW1n"
            assert result["action"] == "create_channel_webhook"
            assert result["webhook"]["id"] == "wh1"

    @pytest.mark.asyncio
    async def test_create_webhook_mock_omits_avatar_when_absent(self):
        config = DiscordCreateWebhookConfig(channel_id="123456789", name="NoAvatar")
        node = create_mock_node(config)

        with patch.object(node, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"id": "wh2"}
            await node.execute({})

            payload = mock_request.call_args.kwargs["json_data"]
            assert payload == {"name": "NoAvatar"}
            assert "avatar" not in payload

    @pytest.mark.asyncio
    async def test_modify_webhook_mock(self):
        config = DiscordModifyWebhookConfig(
            webhook_id="wh1", name="Renamed", channel_id="999"
        )
        node = create_mock_node(config)

        with patch.object(node, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"id": "wh1", "name": "Renamed"}
            result = await node.execute({})

            assert mock_request.call_args.args[0] == "PATCH"
            assert mock_request.call_args.args[1] == "/webhooks/wh1"
            payload = mock_request.call_args.kwargs["json_data"]
            assert payload == {"name": "Renamed", "channel_id": "999"}
            assert result["action"] == "update_webhook_settings"

    @pytest.mark.asyncio
    async def test_delete_webhook_mock(self):
        config = DiscordDeleteWebhookConfig(webhook_id="wh1")
        node = create_mock_node(config)

        with patch.object(node, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"success": True}
            result = await node.execute({})

            assert mock_request.call_args.args[0] == "DELETE"
            assert mock_request.call_args.args[1] == "/webhooks/wh1"
            assert result["action"] == "delete_webhook"
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_list_guild_emojis_mock(self):
        config = DiscordListGuildEmojisConfig(guild_id="987654321")
        node = create_mock_node(config)

        with patch.object(node, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = [{"id": "e1", "name": "blob"}]
            result = await node.execute({})

            assert mock_request.call_args.args[1] == "/guilds/987654321/emojis"
            assert result["action"] == "list_guild_emojis"
            assert result["emojis"][0]["name"] == "blob"

    @pytest.mark.asyncio
    async def test_create_guild_emoji_mock_resolves_image_to_data_uri(self):
        config = DiscordCreateGuildEmojiConfig(
            guild_id="987654321",
            name="blob",
            image="https://example.com/blob.png",
            roles=["role1"],
        )
        node = create_mock_node(config)

        resolved = ResolvedMedia(
            data=b"img", mime_type="image/png", filename="blob.png"
        )

        with patch(
            "nodes.core.media_resolver.resolve_media_input",
            new=AsyncMock(return_value=resolved),
        ), patch.object(node, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"id": "e1", "name": "blob"}
            result = await node.execute({})

            assert mock_request.call_args.args[0] == "POST"
            assert mock_request.call_args.args[1] == "/guilds/987654321/emojis"
            payload = mock_request.call_args.kwargs["json_data"]
            assert payload["name"] == "blob"
            assert payload["image"] == "data:image/png;base64,aW1n"
            assert payload["roles"] == ["role1"]
            assert result["action"] == "create_emoji_in_guild"

    @pytest.mark.asyncio
    async def test_modify_guild_emoji_mock(self):
        config = DiscordModifyGuildEmojiConfig(
            guild_id="987654321", emoji_id="e1", name="newname", roles=["r2"]
        )
        node = create_mock_node(config)

        with patch.object(node, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"id": "e1", "name": "newname"}
            result = await node.execute({})

            assert mock_request.call_args.args[0] == "PATCH"
            assert mock_request.call_args.args[1] == "/guilds/987654321/emojis/e1"
            payload = mock_request.call_args.kwargs["json_data"]
            assert payload == {"name": "newname", "roles": ["r2"]}
            assert result["action"] == "update_guild_emoji"

    @pytest.mark.asyncio
    async def test_delete_guild_emoji_mock(self):
        config = DiscordDeleteGuildEmojiConfig(guild_id="987654321", emoji_id="e1")
        node = create_mock_node(config)

        with patch.object(node, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"success": True}
            result = await node.execute({})

            assert mock_request.call_args.args[0] == "DELETE"
            assert mock_request.call_args.args[1] == "/guilds/987654321/emojis/e1"
            assert result["action"] == "delete_emoji_from_guild"
            assert result["success"] is True
