"""
Discord automation node implementation.

Provides Discord operations for workflow automation via the Discord API.
Supports both Bot Token authentication and OAuth2 for user-based operations.

API Reference: https://discord.com/developers/docs/reference
"""

import re
import logging
import asyncio
import os
import time
from typing import Dict, Any, Optional, Union, Literal, List, Annotated

import httpx
from pydantic import BaseModel, Field, Discriminator, ConfigDict

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import guarded_async_client
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import filter_options_by_search, load_paginated_options
from nodes.core.webhook_subscriptions import AppEventTriggerMixin
from nodes.scopes.discord import DISCORD_SCOPES

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"

# ============================================================================
# Discord Credential Schemas
# ============================================================================


class DiscordBotTokenCredential(BaseModel):
    """Bot token authentication for Discord API.
    Use this for server/channel operations via a bot.

    Get your bot token at: https://discord.com/developers/applications
    """

    credential_type: Literal["discord_bot_token"] = Field(
        "discord_bot_token", json_schema_extra={"ui:hidden": True}
    )
    bot_token: str = Field(
        ...,
        title="Bot Token",
        description="Discord bot token from Developer Portal",
        json_schema_extra={
            "ui:widget": "password",
        },
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://discord.com/developers/applications"
        }
    )


class DiscordBotInstallCredential(BaseModel):
    """Created when NoClick's bot is installed into a Discord server via OAuth.

    The platform bot token (DISCORD_BOT_TOKEN env var) drives server operations;
    the access_token here is the authorizing user's OAuth token.
    """

    credential_type: Literal["discord_bot_install"] = Field(
        "discord_bot_install", json_schema_extra={"ui:hidden": True}
    )
    guild_id: str = Field(..., title="Guild ID")
    guild_name: Optional[str] = Field(None, title="Server Name")
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: str = Field(..., title="Token Expiry")
    username: Optional[str] = Field(None, title="Discord Username")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "discord",
            "x-oauth-scopes": ["bot", "applications.commands", "identify"],
            "x-credential-instructions": (
                "Installs NoClick's bot into your Discord server. "
                "You'll select which server during the OAuth flow."
            ),
            "x-credential-url": "https://discord.com/developers/applications",
        }
    )


DiscordCredential = Union[DiscordBotInstallCredential, DiscordBotTokenCredential]


# ============================================================================
# Discord Configuration Models (One per action)
# ============================================================================


class DiscordSendMessageConfig(BaseModel):
    """Send a message to a Discord channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["send_message_to_channel"] = Field(
        default="send_message_to_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Message to Channel",
            "x-keywords": [
                "message channel",
                "post in channel",
                "send text",
                "ping channel",
                "say something",
            ],
        },
        title="Send Message to Channel",
    )
    channel_id: str = Field(
        ..., title="Channel ID", description="Discord channel ID to send the message to"
    )
    content: str = Field(
        ...,
        title="Message Content",
        description="The message text to send (max 2000 characters)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    tts: Optional[bool] = Field(
        default=False,
        title="Text-to-Speech",
        description="Whether this is a TTS message",
    )


class DiscordSendEmbedConfig(BaseModel):
    """Send an embed message to a Discord channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["send_embed_message_to_channel"] = Field(
        default="send_embed_message_to_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Embed Message to Channel",
            "x-keywords": [
                "embed",
                "rich embed",
                "embedded card",
                "fancy message",
                "embed card",
            ],
        },
        title="Send Embed Message to Channel",
    )
    channel_id: str = Field(
        ..., title="Channel ID", description="Discord channel ID to send the embed to"
    )
    title: Optional[str] = Field(
        default=None, title="Embed Title", description="Title of the embed"
    )
    description: Optional[str] = Field(
        default=None,
        title="Embed Description",
        description="Description text of the embed",
        json_schema_extra={"ui:widget": "textarea"},
    )
    color: Optional[int] = Field(
        default=None,
        title="Embed Color",
        description="Color code of the embed (decimal format, e.g., 5814783 for blue)",
    )
    url: Optional[str] = Field(
        default=None, title="Embed URL", description="URL of the embed title"
    )
    footer_text: Optional[str] = Field(
        default=None, title="Footer Text", description="Footer text for the embed"
    )


class DiscordGetChannelConfig(BaseModel):
    """Get information about a Discord channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_channel_info"] = Field(
        default="get_channel_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Get Channel Info",
            "x-keywords": ["channel details", "channel info", "about channel"],
        },
        title="Get Channel Info",
    )
    channel_id: str = Field(
        ..., title="Channel ID", description="Discord channel ID to get information for"
    )


class DiscordListGuildsConfig(BaseModel):
    """List guilds (servers) the user/bot is a member of"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_user_guilds"] = Field(
        default="list_user_guilds",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "List User Guilds",
            "x-keywords": [
                "my servers",
                "bot servers",
                "joined servers",
                "list guilds",
            ],
        },
        title="List User Guilds",
    )
    limit: Optional[int] = Field(
        default=100, title="Limit", description="Max number of guilds to return (1-200)"
    )


class DiscordGetGuildConfig(BaseModel):
    """Get information about a Discord guild (server)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_guild_info"] = Field(
        default="get_guild_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "Get Guild Info",
            "x-keywords": ["server details", "guild info", "about server"],
        },
        title="Get Guild Info",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


class DiscordListChannelsConfig(BaseModel):
    """List all channels in a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_guild_channels"] = Field(
        default="list_guild_channels",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "List Guild Channels",
            "x-keywords": ["all channels", "server channels", "list channels"],
        },
        title="List Guild Channels",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


class DiscordGetUserConfig(BaseModel):
    """Get information about the authenticated user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_authenticated_user_info"] = Field(
        default="get_authenticated_user_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Authenticated User Info",
            "x-keywords": ["my profile", "who am i", "current user", "my account"],
        },
        title="Get Authenticated User Info",
    )


class DiscordExecuteWebhookConfig(BaseModel):
    """Execute a Discord webhook to send a message"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["execute_webhook_send_message"] = Field(
        default="execute_webhook_send_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Execute Webhook Send Message",
            "x-keywords": [
                "post via webhook",
                "webhook message",
                "trigger webhook",
                "fire webhook",
                "webhook send",
            ],
        },
        title="Execute Webhook Send Message",
    )
    webhook_url: str = Field(
        ...,
        title="Webhook URL",
        description="Full Discord webhook URL (https://discord.com/api/webhooks/...)",
    )
    content: Optional[str] = Field(
        default=None,
        title="Message Content",
        description="The message text to send",
        json_schema_extra={"ui:widget": "textarea"},
    )
    username: Optional[str] = Field(
        default=None,
        title="Username Override",
        description="Override the default webhook username",
    )
    avatar_url: Optional[str] = Field(
        default=None,
        title="Avatar URL",
        description="The avatar to use for this message — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )
    embed_title: Optional[str] = Field(
        default=None, title="Embed Title", description="Title for an embed (optional)"
    )
    embed_description: Optional[str] = Field(
        default=None,
        title="Embed Description",
        description="Description for an embed (optional)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    embed_color: Optional[int] = Field(
        default=None, title="Embed Color", description="Color code for embed (decimal)"
    )


_MENTION_RE = re.compile(r"<@!?([\w-]+)>")


def humanize_discord_mentions(
    content: str, mentions: Any, *, drop_user_id: Optional[str] = None
) -> str:
    """``<@id>`` markup → ``@name`` using the message's own mentions list;
    the ``drop_user_id`` mention (the bot's) is removed outright."""
    names = {
        str(m.get("id")): (m.get("display_name") or m.get("username") or "user")
        for m in (mentions or [])
        if isinstance(m, dict) and m.get("id")
    }

    def _sub(match: "re.Match[str]") -> str:
        user_id = match.group(1)
        if drop_user_id and user_id == str(drop_user_id):
            return ""
        return f"@{names.get(user_id, 'user')}"

    return re.sub(r"\s{2,}", " ", _MENTION_RE.sub(_sub, content)).strip()


def _discord_trigger_field(value: str, display: str, keywords: Optional[list] = None):
    """Build the hidden operation discriminator Field for a Discord trigger."""
    extra = {
        "ui:hidden": True,
        "x-category": None,
        "x-is-trigger": True,
        "x-display-name": display,
    }
    if keywords:
        extra["x-keywords"] = keywords
    return Field(value, json_schema_extra=extra, title=display)


class _DiscordEventTriggerBase(BaseModel):
    """Shared fields for Discord application-level webhook triggers."""

    subscription_status: Optional[str] = Field(
        default=None,
        title="Status",
        json_schema_extra={"ui:widget": "readonly", "ui:loadValue": True},
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


class DiscordOnApplicationAuthorizedConfig(_DiscordEventTriggerBase):
    operation: Literal["on_application_authorized"] = _discord_trigger_field(
        "on_application_authorized",
        "On Application Authorized",
        keywords=[
            "when app authorized",
            "on app install",
            "when bot added",
            "app added to server",
            "when authorized",
        ],
    )


class DiscordOnApplicationDeauthorizedConfig(_DiscordEventTriggerBase):
    operation: Literal["on_application_deauthorized"] = _discord_trigger_field(
        "on_application_deauthorized",
        "On Application Deauthorized",
        keywords=[
            "when app removed",
            "on app uninstall",
            "when bot kicked",
            "app revoked",
            "when deauthorized",
        ],
    )


class DiscordOnEntitlementCreateConfig(_DiscordEventTriggerBase):
    operation: Literal["on_entitlement_create"] = _discord_trigger_field(
        "on_entitlement_create",
        "On Entitlement Create",
        keywords=[
            "when entitlement created",
            "on new purchase",
            "when user buys",
            "new subscription event",
        ],
    )


class DiscordOnEntitlementUpdateConfig(_DiscordEventTriggerBase):
    operation: Literal["on_entitlement_update"] = _discord_trigger_field(
        "on_entitlement_update",
        "On Entitlement Update",
        keywords=[
            "when entitlement updated",
            "on subscription renewal",
            "entitlement changed",
            "purchase renewed",
        ],
    )


class DiscordOnEntitlementDeleteConfig(_DiscordEventTriggerBase):
    operation: Literal["on_entitlement_delete"] = _discord_trigger_field(
        "on_entitlement_delete",
        "On Entitlement Delete",
        keywords=[
            "when entitlement deleted",
            "on subscription ends",
            "purchase expired",
            "entitlement revoked",
        ],
    )


class DiscordOnSlashCommandConfig(_DiscordEventTriggerBase):
    operation: Literal["on_slash_command"] = _discord_trigger_field(
        "on_slash_command",
        "On Slash Command",
        keywords=[
            "when slash command",
            "on command used",
            "slash command triggered",
            "user runs command",
        ],
    )


class _DiscordMessageTriggerFields(BaseModel):
    """Channel-message triggers listen on NoClick's bot Gateway session (Discord
    delivers messages nowhere else), scoped to the server the bot was installed
    into. Declared before the status fields so the picker leads the form."""

    channel_id: Optional[str] = Field(
        default=None,
        title="Channel",
        description="Only messages in this channel and the threads opened in it. Leave empty for every channel in the server.",
    )
    ignore_bots: str = Field(
        default="true",
        title="Ignore bot messages",
        description="Skip messages posted by bots and webhooks — automated channels flood a trigger otherwise.",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class _DiscordMessageTriggerBase(_DiscordEventTriggerBase, _DiscordMessageTriggerFields):
    pass


class DiscordOnMessageConfig(_DiscordMessageTriggerBase):
    operation: Literal["on_message"] = _discord_trigger_field(
        "on_message",
        "On Channel Message",
        keywords=[
            "when message posted",
            "new message in channel",
            "message received",
            "on message",
            "when someone posts",
            "chat message",
        ],
    )


class DiscordOnMentionConfig(_DiscordMessageTriggerBase):
    operation: Literal["on_mention"] = _discord_trigger_field(
        "on_mention",
        "On Bot Mention",
        keywords=[
            "when mentioned",
            "when bot is mentioned",
            "on @mention",
            "someone tags the bot",
            "mention received",
        ],
    )


class DiscordGetMessagesConfig(BaseModel):
    """Get messages from a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_channel_messages"] = Field(
        default="list_channel_messages",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "List Channel Messages",
            "x-keywords": [
                "channel history",
                "recent messages",
                "message history",
                "read channel",
            ],
        },
        title="List Channel Messages",
    )
    channel_id: str = Field(
        ..., title="Channel ID", description="Discord channel ID to get messages from"
    )
    limit: Optional[int] = Field(
        default=50,
        title="Limit",
        description="Max number of messages to return (1-100)",
    )


class DiscordCreateReactionConfig(BaseModel):
    """Add a reaction to a message"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_reaction_to_message"] = Field(
        default="add_reaction_to_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reaction",
            "x-is-trigger": False,
            "x-display-name": "Add Reaction to Message",
            "x-keywords": ["react", "add emoji", "react with emoji", "thumbs up"],
        },
        title="Add Reaction to Message",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")
    message_id: str = Field(
        ..., title="Message ID", description="Message ID to react to"
    )
    emoji: str = Field(
        ...,
        title="Emoji",
        description="Emoji to react with (e.g., '👍' or custom 'name:id')",
    )


class DiscordEditMessageConfig(BaseModel):
    """Edit an existing message"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["edit_message_content"] = Field(
        default="edit_message_content",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Edit Message Content",
            "x-keywords": [
                "edit message",
                "change message",
                "update text",
                "fix message",
            ],
        },
        title="Edit Message Content",
    )
    channel_id: str = Field(
        ..., title="Channel ID", description="Discord channel ID containing the message"
    )
    message_id: str = Field(
        ..., title="Message ID", description="ID of the message to edit"
    )
    content: Optional[str] = Field(
        default=None,
        title="New Content",
        description="The new message content",
        json_schema_extra={"ui:widget": "textarea"},
    )


class DiscordDeleteMessageConfig(BaseModel):
    """Delete a message from a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_message_from_channel"] = Field(
        default="delete_message_from_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Delete Message from Channel",
            "x-keywords": ["delete message", "remove message", "erase message"],
        },
        title="Delete Message from Channel",
    )
    channel_id: str = Field(
        ..., title="Channel ID", description="Discord channel ID containing the message"
    )
    message_id: str = Field(
        ..., title="Message ID", description="ID of the message to delete"
    )


class DiscordPinMessageConfig(BaseModel):
    """Pin a message in a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["pin_message_in_channel"] = Field(
        default="pin_message_in_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Pin Message in Channel",
            "x-keywords": ["pin message", "pin post", "stick message"],
        },
        title="Pin Message in Channel",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")
    message_id: str = Field(
        ..., title="Message ID", description="ID of the message to pin"
    )


class DiscordUnpinMessageConfig(BaseModel):
    """Unpin a message in a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["unpin_message_from_channel"] = Field(
        default="unpin_message_from_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Unpin Message from Channel",
            "x-keywords": ["unpin message", "remove pin", "unstick message"],
        },
        title="Unpin Message from Channel",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")
    message_id: str = Field(
        ..., title="Message ID", description="ID of the message to unpin"
    )


class DiscordGetPinnedMessagesConfig(BaseModel):
    """Get pinned messages in a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_pinned_messages_in_channel"] = Field(
        default="list_pinned_messages_in_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "List Pinned Messages in Channel",
            "x-keywords": ["pinned messages", "show pins", "view pinned"],
        },
        title="List Pinned Messages in Channel",
    )
    channel_id: str = Field(
        ...,
        title="Channel ID",
        description="Discord channel ID to get pinned messages from",
    )


class DiscordGetGuildMembersConfig(BaseModel):
    """Get members of a guild (server)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_guild_members"] = Field(
        default="list_guild_members",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "List Guild Members",
            "x-keywords": [
                "server members",
                "guild members",
                "list members",
                "who is in server",
            ],
        },
        title="List Guild Members",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    limit: Optional[int] = Field(
        default=100,
        title="Limit",
        description="Max number of members to return (1-1000)",
    )


class DiscordGetGuildMemberConfig(BaseModel):
    """Get a specific guild member"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_guild_member_info"] = Field(
        default="get_guild_member_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Get Guild Member Info",
            "x-keywords": ["member details", "one member", "member profile"],
        },
        title="Get Guild Member Info",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    user_id: str = Field(..., title="User ID", description="Discord user ID")


class DiscordModifyGuildMemberConfig(BaseModel):
    """Modify a guild member (nickname, roles)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_guild_member_info"] = Field(
        default="update_guild_member_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Update Guild Member Info",
            "x-keywords": [
                "edit member",
                "change nickname",
                "set nickname",
                "modify member",
            ],
        },
        title="Update Guild Member Info",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    user_id: str = Field(..., title="User ID", description="Discord user ID")
    nick: Optional[str] = Field(
        default=None,
        title="Nickname",
        description="New nickname for the member (empty to reset)",
    )
    roles: Optional[List[str]] = Field(
        default=None,
        title="Role IDs",
        description="List of role IDs to assign (replaces existing roles)",
    )


class DiscordGetGuildRolesConfig(BaseModel):
    """Get all roles in a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_guild_roles"] = Field(
        default="list_guild_roles",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Role",
            "x-is-trigger": False,
            "x-display-name": "List Guild Roles",
            "x-keywords": ["server roles", "guild roles", "list roles", "all roles"],
        },
        title="List Guild Roles",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


class DiscordKickMemberConfig(BaseModel):
    """Kick a member from a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["kick_member_from_guild"] = Field(
        default="kick_member_from_guild",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Kick Member from Guild",
            "x-keywords": ["kick member", "kick from server", "remove member"],
        },
        title="Kick Member from Guild",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    user_id: str = Field(..., title="User ID", description="Discord user ID to kick")


class DiscordBanMemberConfig(BaseModel):
    """Ban a member from a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["ban_member_from_guild"] = Field(
        default="ban_member_from_guild",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Ban Member from Guild",
            "x-keywords": ["ban member", "ban from server", "block user"],
        },
        title="Ban Member from Guild",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    user_id: str = Field(..., title="User ID", description="Discord user ID to ban")
    delete_message_days: Optional[int] = Field(
        default=0,
        title="Delete Message Days",
        description="Number of days of messages to delete (0-7)",
    )


class DiscordUnbanMemberConfig(BaseModel):
    """Unban a member from a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["unban_member_from_guild"] = Field(
        default="unban_member_from_guild",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Unban Member from Guild",
            "x-keywords": ["unban member", "remove ban", "lift ban"],
        },
        title="Unban Member from Guild",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    user_id: str = Field(..., title="User ID", description="Discord user ID to unban")


class DiscordDeleteReactionConfig(BaseModel):
    """Remove a reaction from a message"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_reaction_from_message"] = Field(
        default="remove_reaction_from_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reaction",
            "x-is-trigger": False,
            "x-display-name": "Remove Reaction from Message",
            "x-keywords": ["remove reaction", "unreact", "take off emoji"],
        },
        title="Remove Reaction from Message",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")
    message_id: str = Field(
        ..., title="Message ID", description="Message ID to remove reaction from"
    )
    emoji: str = Field(
        ...,
        title="Emoji",
        description="Emoji to remove (e.g., '👍' or custom 'name:id')",
    )


# ============================================================================
# Channel Operations
# ============================================================================


class DiscordCreateChannelConfig(BaseModel):
    """Create a new channel in a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_channel_in_guild"] = Field(
        default="create_channel_in_guild",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Create Channel in Guild",
            "x-keywords": [
                "create channel",
                "new channel",
                "make channel",
                "add channel",
            ],
            "x-creates-resource": True,
            "x-resource-type": "discord_channel",
            "x-resource-id-path": "channel.id",
        },
        title="Create Channel in Guild",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    name: str = Field(
        ..., title="Channel Name", description="Name of the channel (2-100 characters)"
    )
    type: Optional[int] = Field(
        default=0,
        title="Channel Type",
        description="0=Text, 2=Voice, 4=Category, 5=Announcement, 13=Stage, 15=Forum",
    )
    topic: Optional[str] = Field(
        default=None, title="Topic", description="Channel topic (max 1024 characters)"
    )
    parent_id: Optional[str] = Field(
        default=None,
        title="Parent Category ID",
        description="ID of the parent category",
    )
    nsfw: Optional[bool] = Field(
        default=False, title="NSFW", description="Whether the channel is NSFW"
    )


class DiscordModifyChannelConfig(BaseModel):
    """Modify an existing channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_channel_settings"] = Field(
        default="update_channel_settings",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Update Channel Settings",
            "x-keywords": [
                "edit channel",
                "rename channel",
                "channel settings",
                "modify channel",
            ],
        },
        title="Update Channel Settings",
    )
    channel_id: str = Field(
        ..., title="Channel ID", description="Discord channel ID to modify"
    )
    name: Optional[str] = Field(
        default=None, title="New Name", description="New name for the channel"
    )
    topic: Optional[str] = Field(
        default=None, title="New Topic", description="New topic for the channel"
    )
    nsfw: Optional[bool] = Field(
        default=None, title="NSFW", description="Whether the channel is NSFW"
    )
    position: Optional[int] = Field(
        default=None, title="Position", description="Sorting position of the channel"
    )


class DiscordDeleteChannelConfig(BaseModel):
    """Delete a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_channel"] = Field(
        default="delete_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Delete Channel",
            "x-keywords": ["delete channel", "remove channel"],
        },
        title="Delete Channel",
    )
    channel_id: str = Field(
        ..., title="Channel ID", description="Discord channel ID to delete"
    )


class DiscordTriggerTypingConfig(BaseModel):
    """Trigger typing indicator in a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["show_typing_indicator_in_channel"] = Field(
        default="show_typing_indicator_in_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Show Typing Indicator in Channel",
            "x-keywords": [
                "typing indicator",
                "is typing",
                "show typing",
                "bot typing",
            ],
        },
        title="Show Typing Indicator in Channel",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")


class DiscordBulkDeleteMessagesConfig(BaseModel):
    """Bulk delete messages (2-100 messages, less than 14 days old)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["bulk_delete_channel_messages"] = Field(
        default="bulk_delete_channel_messages",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Bulk Delete Channel Messages",
            "x-keywords": [
                "bulk delete",
                "purge messages",
                "clear messages",
                "mass delete",
                "wipe channel",
            ],
        },
        title="Bulk Delete Channel Messages",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")
    message_ids: List[str] = Field(
        ..., title="Message IDs", description="List of message IDs to delete (2-100)"
    )


class DiscordEditChannelPermissionsConfig(BaseModel):
    """Edit channel permission overwrites"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["edit_channel_permission_overwrites"] = Field(
        default="edit_channel_permission_overwrites",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Edit Channel Permission Overwrites",
            "x-keywords": [
                "channel permissions",
                "permission overwrites",
                "set permissions",
                "access control",
            ],
        },
        title="Edit Channel Permission Overwrites",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")
    overwrite_id: str = Field(
        ..., title="Overwrite ID", description="Role or user ID to set permissions for"
    )
    type: int = Field(..., title="Type", description="0 for role, 1 for member")
    allow: Optional[str] = Field(
        default="0",
        title="Allow Permissions",
        description="Bitwise value of allowed permissions",
    )
    deny: Optional[str] = Field(
        default="0",
        title="Deny Permissions",
        description="Bitwise value of denied permissions",
    )


# ============================================================================
# Thread Operations
# ============================================================================


class DiscordStartThreadFromMessageConfig(BaseModel):
    """Start a thread from an existing message"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["start_thread_from_existing_message"] = Field(
        default="start_thread_from_existing_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Thread",
            "x-is-trigger": False,
            "x-display-name": "Start Thread from Existing Message",
            "x-keywords": [
                "thread from message",
                "reply in thread",
                "branch message",
                "create thread on message",
            ],
        },
        title="Start Thread from Existing Message",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")
    message_id: str = Field(
        ..., title="Message ID", description="Message ID to start thread from"
    )
    name: str = Field(
        ..., title="Thread Name", description="Name of the thread (1-100 characters)"
    )
    auto_archive_duration: Optional[int] = Field(
        default=1440,
        title="Auto Archive Duration",
        description="Minutes of inactivity until auto-archive (60, 1440, 4320, 10080)",
    )


class DiscordStartThreadConfig(BaseModel):
    """Start a thread without a message (forum/media channels)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["start_thread_in_forum_channel"] = Field(
        default="start_thread_in_forum_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Thread",
            "x-is-trigger": False,
            "x-display-name": "Start Thread in Forum Channel",
            "x-keywords": [
                "forum thread",
                "forum post",
                "new forum thread",
                "media channel thread",
            ],
        },
        title="Start Thread in Forum Channel",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")
    name: str = Field(
        ..., title="Thread Name", description="Name of the thread (1-100 characters)"
    )
    auto_archive_duration: Optional[int] = Field(
        default=1440,
        title="Auto Archive Duration",
        description="Minutes of inactivity until auto-archive",
    )
    type: Optional[int] = Field(
        default=11,
        title="Thread Type",
        description="10=Announcement, 11=Public, 12=Private",
    )
    message_content: Optional[str] = Field(
        default=None,
        title="Initial Message",
        description="Content for the first message in forum threads",
    )


class DiscordJoinThreadConfig(BaseModel):
    """Join a thread"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["join_thread"] = Field(
        default="join_thread",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Thread",
            "x-is-trigger": False,
            "x-display-name": "Join Thread",
            "x-keywords": ["join thread", "enter thread"],
        },
        title="Join Thread",
    )
    thread_id: str = Field(..., title="Thread ID", description="Thread ID to join")


class DiscordLeaveThreadConfig(BaseModel):
    """Leave a thread"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["leave_thread"] = Field(
        default="leave_thread",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Thread",
            "x-is-trigger": False,
            "x-display-name": "Leave Thread",
            "x-keywords": ["leave thread", "exit thread"],
        },
        title="Leave Thread",
    )
    thread_id: str = Field(..., title="Thread ID", description="Thread ID to leave")


class DiscordAddThreadMemberConfig(BaseModel):
    """Add a member to a thread"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_member_to_thread"] = Field(
        default="add_member_to_thread",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Thread",
            "x-is-trigger": False,
            "x-display-name": "Add Member to Thread",
            "x-keywords": ["add to thread", "invite to thread", "add person thread"],
        },
        title="Add Member to Thread",
    )
    thread_id: str = Field(..., title="Thread ID", description="Thread ID")
    user_id: str = Field(..., title="User ID", description="User ID to add")


class DiscordRemoveThreadMemberConfig(BaseModel):
    """Remove a member from a thread"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_member_from_thread"] = Field(
        default="remove_member_from_thread",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Thread",
            "x-is-trigger": False,
            "x-display-name": "Remove Member from Thread",
            "x-keywords": ["remove from thread", "kick from thread"],
        },
        title="Remove Member from Thread",
    )
    thread_id: str = Field(..., title="Thread ID", description="Thread ID")
    user_id: str = Field(..., title="User ID", description="User ID to remove")


class DiscordListThreadMembersConfig(BaseModel):
    """List members in a thread"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_thread_members"] = Field(
        default="list_thread_members",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Thread",
            "x-is-trigger": False,
            "x-display-name": "List Thread Members",
            "x-keywords": ["thread members", "who is in thread", "thread participants"],
        },
        title="List Thread Members",
    )
    thread_id: str = Field(..., title="Thread ID", description="Thread ID")


class DiscordListActiveThreadsConfig(BaseModel):
    """List all active threads in a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_guild_active_threads"] = Field(
        default="list_guild_active_threads",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Thread",
            "x-is-trigger": False,
            "x-display-name": "List Guild Active Threads",
            "x-keywords": ["active threads", "open threads", "server threads"],
        },
        title="List Guild Active Threads",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


# ============================================================================
# Additional Message Operations
# ============================================================================


class DiscordGetMessageConfig(BaseModel):
    """Get a single message by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_message_by_id"] = Field(
        default="get_message_by_id",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Get Message by Id",
            "x-keywords": [
                "single message",
                "one message",
                "message details",
                "fetch message",
            ],
        },
        title="Get Message by Id",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")
    message_id: str = Field(
        ..., title="Message ID", description="Message ID to retrieve"
    )


class DiscordCrosspostMessageConfig(BaseModel):
    """Crosspost a message in an announcement channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["crosspost_message_to_announcement_channel"] = Field(
        default="crosspost_message_to_announcement_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Crosspost Message to Announcement Channel",
            "x-keywords": [
                "crosspost",
                "publish announcement",
                "broadcast message",
                "share announcement",
                "follow channel post",
            ],
        },
        title="Crosspost Message to Announcement Channel",
    )
    channel_id: str = Field(
        ..., title="Channel ID", description="Announcement channel ID"
    )
    message_id: str = Field(
        ..., title="Message ID", description="Message ID to crosspost"
    )


class DiscordGetReactionsConfig(BaseModel):
    """Get users who reacted with a specific emoji"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_message_reaction_users"] = Field(
        default="list_message_reaction_users",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reaction",
            "x-is-trigger": False,
            "x-display-name": "List Message Reaction Users",
            "x-keywords": [
                "who reacted",
                "reaction users",
                "reactors",
                "people who reacted",
            ],
        },
        title="List Message Reaction Users",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")
    message_id: str = Field(..., title="Message ID", description="Message ID")
    emoji: str = Field(..., title="Emoji", description="Emoji to get reactions for")
    limit: Optional[int] = Field(
        default=25, title="Limit", description="Max users to return (1-100)"
    )


class DiscordDeleteAllReactionsConfig(BaseModel):
    """Delete all reactions from a message"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_all_message_reactions"] = Field(
        default="delete_all_message_reactions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reaction",
            "x-is-trigger": False,
            "x-display-name": "Delete All Message Reactions",
            "x-keywords": ["clear reactions", "remove all reactions", "wipe reactions"],
        },
        title="Delete All Message Reactions",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")
    message_id: str = Field(
        ..., title="Message ID", description="Message ID to clear reactions from"
    )


class DiscordDeleteAllReactionsForEmojiConfig(BaseModel):
    """Delete all reactions for a specific emoji"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_emoji_reactions_from_message"] = Field(
        default="delete_emoji_reactions_from_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reaction",
            "x-is-trigger": False,
            "x-display-name": "Delete Emoji Reactions from Message",
            "x-keywords": [
                "remove emoji reaction",
                "clear specific reaction",
                "delete one emoji",
            ],
        },
        title="Delete Emoji Reactions from Message",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")
    message_id: str = Field(..., title="Message ID", description="Message ID")
    emoji: str = Field(..., title="Emoji", description="Emoji to delete reactions for")


# ============================================================================
# Role Operations
# ============================================================================


class DiscordCreateRoleConfig(BaseModel):
    """Create a new role in a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_role_in_guild"] = Field(
        default="create_role_in_guild",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Role",
            "x-is-trigger": False,
            "x-display-name": "Create Role in Guild",
            "x-keywords": ["create role", "new role", "make role", "add role"],
            "x-creates-resource": True,
            "x-resource-type": "discord_role",
            "x-resource-id-path": "role.id",
        },
        title="Create Role in Guild",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    name: str = Field(..., title="Role Name", description="Name of the role")
    color: Optional[int] = Field(
        default=0, title="Color", description="RGB color value (decimal)"
    )
    hoist: Optional[bool] = Field(
        default=False, title="Hoist", description="Display role members separately"
    )
    mentionable: Optional[bool] = Field(
        default=False,
        title="Mentionable",
        description="Allow anyone to @mention this role",
    )
    permissions: Optional[str] = Field(
        default=None, title="Permissions", description="Bitwise permission flags"
    )


class DiscordModifyRoleConfig(BaseModel):
    """Modify an existing role"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_guild_role"] = Field(
        default="update_guild_role",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Role",
            "x-is-trigger": False,
            "x-display-name": "Update Guild Role",
            "x-keywords": ["edit role", "rename role", "modify role", "role settings"],
        },
        title="Update Guild Role",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    role_id: str = Field(..., title="Role ID", description="Role ID to modify")
    name: Optional[str] = Field(
        default=None, title="New Name", description="New name for the role"
    )
    color: Optional[int] = Field(
        default=None, title="New Color", description="New RGB color value (decimal)"
    )
    hoist: Optional[bool] = Field(
        default=None, title="Hoist", description="Display role members separately"
    )
    mentionable: Optional[bool] = Field(
        default=None,
        title="Mentionable",
        description="Allow anyone to @mention this role",
    )


class DiscordDeleteRoleConfig(BaseModel):
    """Delete a role from a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_role_from_guild"] = Field(
        default="delete_role_from_guild",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Role",
            "x-is-trigger": False,
            "x-display-name": "Delete Role from Guild",
            "x-keywords": [
                "delete server role",
                "remove role from server",
                "destroy guild role",
                "delete a role",
            ],
        },
        title="Delete Role from Guild",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    role_id: str = Field(..., title="Role ID", description="Role ID to delete")


class DiscordAddRoleToMemberConfig(BaseModel):
    """Add a role to a guild member"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_role_to_guild_member"] = Field(
        default="add_role_to_guild_member",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Role",
            "x-is-trigger": False,
            "x-display-name": "Add Role to Guild Member",
            "x-keywords": [
                "assign role to member",
                "give member a role",
                "grant role to user",
                "add role to someone",
                "give someone a role",
            ],
        },
        title="Add Role to Guild Member",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    user_id: str = Field(..., title="User ID", description="User ID to add role to")
    role_id: str = Field(..., title="Role ID", description="Role ID to add")


class DiscordRemoveRoleFromMemberConfig(BaseModel):
    """Remove a role from a guild member"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_role_from_guild_member"] = Field(
        default="remove_role_from_guild_member",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Role",
            "x-is-trigger": False,
            "x-display-name": "Remove Role from Guild Member",
            "x-keywords": [
                "revoke role from member",
                "take role away from user",
                "strip member role",
                "unassign role from someone",
            ],
        },
        title="Remove Role from Guild Member",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    user_id: str = Field(
        ..., title="User ID", description="User ID to remove role from"
    )
    role_id: str = Field(..., title="Role ID", description="Role ID to remove")


# ============================================================================
# Invite Operations
# ============================================================================


class DiscordGetInviteConfig(BaseModel):
    """Get information about an invite"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_invite_info"] = Field(
        default="get_invite_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Invite",
            "x-is-trigger": False,
            "x-display-name": "Get Invite Info",
            "x-keywords": [
                "lookup invite details",
                "check invite code",
                "inspect server invite",
                "view invite link",
            ],
        },
        title="Get Invite Info",
    )
    invite_code: str = Field(
        ..., title="Invite Code", description="Invite code (without discord.gg prefix)"
    )
    with_counts: Optional[bool] = Field(
        default=True,
        title="Include Counts",
        description="Include approximate member counts",
    )


class DiscordDeleteInviteConfig(BaseModel):
    """Delete an invite"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_invite"] = Field(
        default="delete_invite",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Invite",
            "x-is-trigger": False,
            "x-display-name": "Delete Invite",
            "x-keywords": [
                "revoke invite link",
                "delete invite code",
                "cancel server invite",
                "remove an invite",
            ],
        },
        title="Delete Invite",
    )
    invite_code: str = Field(
        ..., title="Invite Code", description="Invite code to delete"
    )


class DiscordGetChannelInvitesConfig(BaseModel):
    """Get all invites for a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_channel_invites"] = Field(
        default="list_channel_invites",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "List Channel Invites",
            "x-keywords": [
                "channel invite links",
                "all invites for channel",
                "show channel invites",
            ],
        },
        title="List Channel Invites",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")


class DiscordCreateChannelInviteConfig(BaseModel):
    """Create a new invite for a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_channel_invite"] = Field(
        default="create_channel_invite",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Invite",
            "x-is-trigger": False,
            "x-display-name": "Create Channel Invite",
            "x-keywords": [
                "make invite link",
                "generate channel invite",
                "new server invite",
                "invite people to channel",
            ],
        },
        title="Create Channel Invite",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")
    max_age: Optional[int] = Field(
        default=86400,
        title="Max Age (seconds)",
        description="Duration in seconds (0 for never, default 24h)",
    )
    max_uses: Optional[int] = Field(
        default=0, title="Max Uses", description="Max number of uses (0 for unlimited)"
    )
    temporary: Optional[bool] = Field(
        default=False, title="Temporary", description="Grant temporary membership"
    )
    unique: Optional[bool] = Field(
        default=False, title="Unique", description="Create a unique invite"
    )


class DiscordGetGuildInvitesConfig(BaseModel):
    """Get all invites for a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_guild_invites"] = Field(
        default="list_guild_invites",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "List Guild Invites",
            "x-keywords": [
                "server invites",
                "all server invites",
                "guild invite links",
                "view server invites",
            ],
        },
        title="List Guild Invites",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


# ============================================================================
# Webhook Operations
# ============================================================================


class DiscordGetChannelWebhooksConfig(BaseModel):
    """Get all webhooks for a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_channel_webhooks"] = Field(
        default="list_channel_webhooks",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "List Channel Webhooks",
            "x-keywords": [
                "channel webhooks",
                "webhooks for channel",
                "view channel webhooks",
            ],
        },
        title="List Channel Webhooks",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")


class DiscordGetGuildWebhooksConfig(BaseModel):
    """Get all webhooks for a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_guild_webhooks"] = Field(
        default="list_guild_webhooks",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "List Guild Webhooks",
            "x-keywords": [
                "server webhooks",
                "webhooks for server",
                "all guild webhooks",
            ],
        },
        title="List Guild Webhooks",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


class DiscordGetWebhookConfig(BaseModel):
    """Get a webhook by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_webhook_by_id"] = Field(
        default="get_webhook_by_id",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Get Webhook by Id",
            "x-keywords": ["webhook details", "single webhook", "fetch webhook"],
        },
        title="Get Webhook by Id",
    )
    webhook_id: str = Field(..., title="Webhook ID", description="Webhook ID to get")


class DiscordCreateWebhookConfig(BaseModel):
    """Create a new webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_channel_webhook"] = Field(
        default="create_channel_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Create Channel Webhook",
            "x-keywords": ["make webhook", "new webhook", "set up webhook"],
        },
        title="Create Channel Webhook",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")
    name: str = Field(
        ..., title="Webhook Name", description="Name of the webhook (1-80 characters)"
    )
    avatar: Optional[str] = Field(
        default=None,
        title="Avatar",
        description="The avatar image to use — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )


class DiscordModifyWebhookConfig(BaseModel):
    """Modify an existing webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_webhook_settings"] = Field(
        default="update_webhook_settings",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Update Webhook Settings",
            "x-keywords": ["edit webhook", "rename webhook", "change webhook avatar"],
        },
        title="Update Webhook Settings",
    )
    webhook_id: str = Field(..., title="Webhook ID", description="Webhook ID to modify")
    name: Optional[str] = Field(
        default=None, title="New Name", description="New name for the webhook"
    )
    channel_id: Optional[str] = Field(
        default=None,
        title="New Channel ID",
        description="Move webhook to a different channel",
    )


class DiscordDeleteWebhookConfig(BaseModel):
    """Delete a webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_webhook"] = Field(
        default="delete_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Delete Webhook",
            "x-keywords": ["remove webhook", "destroy webhook"],
        },
        title="Delete Webhook",
    )
    webhook_id: str = Field(..., title="Webhook ID", description="Webhook ID to delete")


# ============================================================================
# Emoji Operations
# ============================================================================


class DiscordListGuildEmojisConfig(BaseModel):
    """List all emojis in a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_guild_emojis"] = Field(
        default="list_guild_emojis",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Emoji",
            "x-is-trigger": False,
            "x-display-name": "List Guild Emojis",
            "x-keywords": ["server emojis", "custom emojis", "all guild emojis"],
        },
        title="List Guild Emojis",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


class DiscordGetGuildEmojiConfig(BaseModel):
    """Get a specific emoji from a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_emoji_from_guild"] = Field(
        default="get_emoji_from_guild",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Emoji",
            "x-is-trigger": False,
            "x-display-name": "Get Emoji from Guild",
            "x-keywords": ["emoji details", "single custom emoji", "fetch one emoji"],
        },
        title="Get Emoji from Guild",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    emoji_id: str = Field(..., title="Emoji ID", description="Emoji ID to get")


class DiscordCreateGuildEmojiConfig(BaseModel):
    """Create a new emoji in a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_emoji_in_guild"] = Field(
        default="create_emoji_in_guild",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Emoji",
            "x-is-trigger": False,
            "x-display-name": "Create Emoji in Guild",
            "x-keywords": ["upload emoji", "add custom emoji", "new server emoji"],
        },
        title="Create Emoji in Guild",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    name: str = Field(..., title="Emoji Name", description="Name of the emoji")
    image: str = Field(
        ...,
        title="Image",
        description="The emoji image to upload — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )
    roles: Optional[List[str]] = Field(
        default=None, title="Role IDs", description="Roles allowed to use this emoji"
    )


class DiscordModifyGuildEmojiConfig(BaseModel):
    """Modify an existing emoji"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_guild_emoji"] = Field(
        default="update_guild_emoji",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Emoji",
            "x-is-trigger": False,
            "x-display-name": "Update Guild Emoji",
            "x-keywords": ["rename emoji", "edit custom emoji", "change emoji name"],
        },
        title="Update Guild Emoji",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    emoji_id: str = Field(..., title="Emoji ID", description="Emoji ID to modify")
    name: Optional[str] = Field(
        default=None, title="New Name", description="New name for the emoji"
    )
    roles: Optional[List[str]] = Field(
        default=None, title="Role IDs", description="Roles allowed to use this emoji"
    )


class DiscordDeleteGuildEmojiConfig(BaseModel):
    """Delete an emoji from a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_emoji_from_guild"] = Field(
        default="delete_emoji_from_guild",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Emoji",
            "x-is-trigger": False,
            "x-display-name": "Delete Emoji from Guild",
            "x-keywords": ["remove emoji", "delete custom emoji"],
        },
        title="Delete Emoji from Guild",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    emoji_id: str = Field(..., title="Emoji ID", description="Emoji ID to delete")


# ============================================================================
# Sticker Operations
# ============================================================================


class DiscordListGuildStickersConfig(BaseModel):
    """List all stickers in a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_guild_stickers"] = Field(
        default="list_guild_stickers",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Sticker",
            "x-is-trigger": False,
            "x-display-name": "List Guild Stickers",
            "x-keywords": ["server stickers", "custom stickers", "all guild stickers"],
        },
        title="List Guild Stickers",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


class DiscordGetGuildStickerConfig(BaseModel):
    """Get a specific sticker from a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_sticker_from_guild"] = Field(
        default="get_sticker_from_guild",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Sticker",
            "x-is-trigger": False,
            "x-display-name": "Get Sticker from Guild",
            "x-keywords": ["sticker details", "single sticker", "fetch one sticker"],
        },
        title="Get Sticker from Guild",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    sticker_id: str = Field(..., title="Sticker ID", description="Sticker ID to get")


class DiscordModifyGuildStickerConfig(BaseModel):
    """Modify an existing sticker"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_guild_sticker"] = Field(
        default="update_guild_sticker",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Sticker",
            "x-is-trigger": False,
            "x-display-name": "Update Guild Sticker",
            "x-keywords": ["rename sticker", "edit custom sticker", "change sticker"],
        },
        title="Update Guild Sticker",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    sticker_id: str = Field(..., title="Sticker ID", description="Sticker ID to modify")
    name: Optional[str] = Field(
        default=None, title="New Name", description="New name for the sticker"
    )
    description: Optional[str] = Field(
        default=None,
        title="New Description",
        description="New description (empty to clear)",
    )
    tags: Optional[str] = Field(
        default=None, title="Tags", description="Autocomplete/suggestion tags"
    )


class DiscordDeleteGuildStickerConfig(BaseModel):
    """Delete a sticker from a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_sticker_from_guild"] = Field(
        default="delete_sticker_from_guild",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Sticker",
            "x-is-trigger": False,
            "x-display-name": "Delete Sticker from Guild",
            "x-keywords": ["remove sticker", "delete custom sticker"],
        },
        title="Delete Sticker from Guild",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    sticker_id: str = Field(..., title="Sticker ID", description="Sticker ID to delete")


# ============================================================================
# Scheduled Events Operations
# ============================================================================


class DiscordListScheduledEventsConfig(BaseModel):
    """List all scheduled events in a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_guild_scheduled_events"] = Field(
        default="list_guild_scheduled_events",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Scheduled Event",
            "x-is-trigger": False,
            "x-display-name": "List Guild Scheduled Events",
            "x-keywords": ["server events", "upcoming events", "all scheduled events"],
        },
        title="List Guild Scheduled Events",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    with_user_count: Optional[bool] = Field(
        default=False,
        title="Include User Count",
        description="Include number of users interested",
    )


class DiscordGetScheduledEventConfig(BaseModel):
    """Get a specific scheduled event"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_scheduled_event"] = Field(
        default="get_scheduled_event",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Scheduled Event",
            "x-is-trigger": False,
            "x-display-name": "Get Scheduled Event",
            "x-keywords": [
                "event details",
                "single scheduled event",
                "fetch one event",
            ],
        },
        title="Get Scheduled Event",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    event_id: str = Field(..., title="Event ID", description="Scheduled event ID")


class DiscordCreateScheduledEventConfig(BaseModel):
    """Create a new scheduled event"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_scheduled_event"] = Field(
        default="create_scheduled_event",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Scheduled Event",
            "x-is-trigger": False,
            "x-display-name": "Create Scheduled Event",
            "x-keywords": [
                "schedule event",
                "plan server event",
                "new scheduled event",
            ],
        },
        title="Create Scheduled Event",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    name: str = Field(..., title="Event Name", description="Name of the event")
    scheduled_start_time: str = Field(
        ..., title="Start Time", description="ISO8601 timestamp for event start"
    )
    entity_type: int = Field(
        ..., title="Entity Type", description="1=Stage, 2=Voice, 3=External"
    )
    privacy_level: Optional[int] = Field(
        default=2, title="Privacy Level", description="2=Guild Only"
    )
    channel_id: Optional[str] = Field(
        default=None,
        title="Channel ID",
        description="Channel ID (for Stage/Voice events)",
    )
    entity_metadata_location: Optional[str] = Field(
        default=None,
        title="External Location",
        description="Location for external events",
    )
    scheduled_end_time: Optional[str] = Field(
        default=None,
        title="End Time",
        description="ISO8601 timestamp for event end (required for external)",
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Event description"
    )


class DiscordModifyScheduledEventConfig(BaseModel):
    """Modify an existing scheduled event"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_scheduled_event"] = Field(
        default="update_scheduled_event",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Scheduled Event",
            "x-is-trigger": False,
            "x-display-name": "Update Scheduled Event",
            "x-keywords": [
                "reschedule event",
                "edit scheduled event",
                "change event time",
            ],
        },
        title="Update Scheduled Event",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    event_id: str = Field(..., title="Event ID", description="Scheduled event ID")
    name: Optional[str] = Field(
        default=None, title="New Name", description="New name for the event"
    )
    description: Optional[str] = Field(
        default=None, title="New Description", description="New description"
    )
    scheduled_start_time: Optional[str] = Field(
        default=None, title="New Start Time", description="New ISO8601 start timestamp"
    )
    scheduled_end_time: Optional[str] = Field(
        default=None, title="New End Time", description="New ISO8601 end timestamp"
    )
    status: Optional[int] = Field(
        default=None,
        title="Status",
        description="1=Scheduled, 2=Active, 3=Completed, 4=Canceled",
    )


class DiscordDeleteScheduledEventConfig(BaseModel):
    """Delete a scheduled event"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_scheduled_event"] = Field(
        default="delete_scheduled_event",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Scheduled Event",
            "x-is-trigger": False,
            "x-display-name": "Delete Scheduled Event",
            "x-keywords": ["cancel event", "remove scheduled event"],
        },
        title="Delete Scheduled Event",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    event_id: str = Field(
        ..., title="Event ID", description="Scheduled event ID to delete"
    )


class DiscordGetScheduledEventUsersConfig(BaseModel):
    """Get users interested in a scheduled event"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_scheduled_event_users"] = Field(
        default="list_scheduled_event_users",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Scheduled Event",
            "x-is-trigger": False,
            "x-display-name": "List Scheduled Event Users",
            "x-keywords": [
                "event attendees",
                "interested users",
                "who is going",
                "event rsvps",
            ],
        },
        title="List Scheduled Event Users",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    event_id: str = Field(..., title="Event ID", description="Scheduled event ID")
    limit: Optional[int] = Field(
        default=100, title="Limit", description="Max users to return (1-100)"
    )


# ============================================================================
# Auto Moderation Operations
# ============================================================================


class DiscordListAutoModRulesConfig(BaseModel):
    """List all auto moderation rules in a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_guild_auto_moderation_rules"] = Field(
        default="list_guild_auto_moderation_rules",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Auto Moderation",
            "x-is-trigger": False,
            "x-display-name": "List Guild Auto Moderation Rules",
            "x-keywords": ["automod rules", "all moderation rules", "view automod"],
        },
        title="List Guild Auto Moderation Rules",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


class DiscordGetAutoModRuleConfig(BaseModel):
    """Get a specific auto moderation rule"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_auto_moderation_rule"] = Field(
        default="get_auto_moderation_rule",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Auto Moderation",
            "x-is-trigger": False,
            "x-display-name": "Get Auto Moderation Rule",
            "x-keywords": [
                "automod rule details",
                "single automod rule",
                "fetch one rule",
            ],
        },
        title="Get Auto Moderation Rule",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    rule_id: str = Field(..., title="Rule ID", description="Auto moderation rule ID")


class DiscordCreateAutoModRuleConfig(BaseModel):
    """Create a new auto moderation rule"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_auto_moderation_rule"] = Field(
        default="create_auto_moderation_rule",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Auto Moderation",
            "x-is-trigger": False,
            "x-display-name": "Create Auto Moderation Rule",
            "x-keywords": [
                "add automod rule",
                "new moderation filter",
                "set up automod",
            ],
        },
        title="Create Auto Moderation Rule",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    name: str = Field(..., title="Rule Name", description="Name of the rule")
    event_type: int = Field(default=1, title="Event Type", description="1=Message Send")
    trigger_type: int = Field(
        ...,
        title="Trigger Type",
        description="1=Keyword, 3=Spam, 4=KeywordPreset, 5=MentionSpam",
    )
    trigger_metadata_keyword_filter: Optional[List[str]] = Field(
        default=None,
        title="Keyword Filter",
        description="Keywords to trigger on (for type 1)",
    )
    trigger_metadata_presets: Optional[List[int]] = Field(
        default=None,
        title="Presets",
        description="Preset keyword lists (for type 4): 1=Profanity, 2=SexualContent, 3=Slurs",
    )
    actions: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        title="Actions",
        description="Actions to take (list of {type, metadata})",
    )
    enabled: Optional[bool] = Field(
        default=True, title="Enabled", description="Whether the rule is enabled"
    )
    exempt_roles: Optional[List[str]] = Field(
        default=None, title="Exempt Roles", description="Roles exempt from this rule"
    )
    exempt_channels: Optional[List[str]] = Field(
        default=None,
        title="Exempt Channels",
        description="Channels exempt from this rule",
    )


class DiscordModifyAutoModRuleConfig(BaseModel):
    """Modify an existing auto moderation rule"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_auto_moderation_rule"] = Field(
        default="update_auto_moderation_rule",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Auto Moderation",
            "x-is-trigger": False,
            "x-display-name": "Update Auto Moderation Rule",
            "x-keywords": [
                "edit automod rule",
                "change moderation filter",
                "modify automod",
            ],
        },
        title="Update Auto Moderation Rule",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    rule_id: str = Field(..., title="Rule ID", description="Auto moderation rule ID")
    name: Optional[str] = Field(
        default=None, title="New Name", description="New name for the rule"
    )
    enabled: Optional[bool] = Field(
        default=None, title="Enabled", description="Whether the rule is enabled"
    )
    exempt_roles: Optional[List[str]] = Field(
        default=None, title="Exempt Roles", description="Roles exempt from this rule"
    )
    exempt_channels: Optional[List[str]] = Field(
        default=None,
        title="Exempt Channels",
        description="Channels exempt from this rule",
    )


class DiscordDeleteAutoModRuleConfig(BaseModel):
    """Delete an auto moderation rule"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_auto_moderation_rule"] = Field(
        default="delete_auto_moderation_rule",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Auto Moderation",
            "x-is-trigger": False,
            "x-display-name": "Delete Auto Moderation Rule",
            "x-keywords": ["remove automod rule", "delete moderation filter"],
        },
        title="Delete Auto Moderation Rule",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    rule_id: str = Field(
        ..., title="Rule ID", description="Auto moderation rule ID to delete"
    )


# ============================================================================
# Audit Log Operations
# ============================================================================


class DiscordGetAuditLogConfig(BaseModel):
    """Get the audit log for a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_guild_audit_log"] = Field(
        default="get_guild_audit_log",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "Get Guild Audit Log",
            "x-keywords": [
                "audit log",
                "server logs",
                "moderation history",
                "action history",
            ],
        },
        title="Get Guild Audit Log",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    user_id: Optional[str] = Field(
        default=None,
        title="User ID",
        description="Filter by user who performed the action",
    )
    action_type: Optional[int] = Field(
        default=None,
        title="Action Type",
        description="Filter by action type (see Discord docs)",
    )
    limit: Optional[int] = Field(
        default=50, title="Limit", description="Max entries to return (1-100)"
    )


# ============================================================================
# Stage Instance Operations
# ============================================================================


class DiscordCreateStageInstanceConfig(BaseModel):
    """Create a stage instance (go live)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_stage_instance"] = Field(
        default="create_stage_instance",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Stage Instance",
            "x-is-trigger": False,
            "x-display-name": "Create Stage Instance",
            "x-keywords": [
                "go live",
                "start stage",
                "open stage channel",
                "begin stage",
            ],
        },
        title="Create Stage Instance",
    )
    channel_id: str = Field(..., title="Channel ID", description="Stage channel ID")
    topic: str = Field(
        ..., title="Topic", description="Topic of the stage instance (1-120 characters)"
    )
    privacy_level: Optional[int] = Field(
        default=2, title="Privacy Level", description="2=Guild Only"
    )


class DiscordGetStageInstanceConfig(BaseModel):
    """Get the stage instance for a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_stage_instance_for_channel"] = Field(
        default="get_stage_instance_for_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Stage Instance",
            "x-is-trigger": False,
            "x-display-name": "Get Stage Instance for Channel",
            "x-keywords": ["stage details", "current stage info", "fetch stage"],
        },
        title="Get Stage Instance for Channel",
    )
    channel_id: str = Field(..., title="Channel ID", description="Stage channel ID")


class DiscordModifyStageInstanceConfig(BaseModel):
    """Modify a stage instance"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_stage_instance"] = Field(
        default="update_stage_instance",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Stage Instance",
            "x-is-trigger": False,
            "x-display-name": "Update Stage Instance",
            "x-keywords": ["edit stage topic", "change stage", "modify stage"],
        },
        title="Update Stage Instance",
    )
    channel_id: str = Field(..., title="Channel ID", description="Stage channel ID")
    topic: Optional[str] = Field(
        default=None, title="New Topic", description="New topic (1-120 characters)"
    )
    privacy_level: Optional[int] = Field(
        default=None, title="Privacy Level", description="2=Guild Only"
    )


class DiscordDeleteStageInstanceConfig(BaseModel):
    """Delete a stage instance (end the stage)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_stage_instance"] = Field(
        default="delete_stage_instance",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Stage Instance",
            "x-is-trigger": False,
            "x-display-name": "Delete Stage Instance",
            "x-keywords": ["end stage", "close stage", "stop going live"],
        },
        title="Delete Stage Instance",
    )
    channel_id: str = Field(..., title="Channel ID", description="Stage channel ID")


# ============================================================================
# Voice Operations
# ============================================================================


class DiscordListVoiceRegionsConfig(BaseModel):
    """List available voice regions"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_available_voice_regions"] = Field(
        default="list_available_voice_regions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Voice",
            "x-is-trigger": False,
            "x-display-name": "List Available Voice Regions",
            "x-keywords": ["voice regions", "voice servers", "available regions"],
        },
        title="List Available Voice Regions",
    )


# ============================================================================
# Guild Operations (Additional)
# ============================================================================


class DiscordModifyGuildConfig(BaseModel):
    """Modify guild settings"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_guild_settings"] = Field(
        default="update_guild_settings",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "Update Guild Settings",
            "x-keywords": [
                "edit server",
                "server settings",
                "rename server",
                "modify guild",
            ],
        },
        title="Update Guild Settings",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    name: Optional[str] = Field(
        default=None, title="New Name", description="New name for the guild"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Guild description"
    )
    afk_channel_id: Optional[str] = Field(
        default=None, title="AFK Channel ID", description="AFK voice channel ID"
    )
    afk_timeout: Optional[int] = Field(
        default=None, title="AFK Timeout", description="AFK timeout in seconds"
    )


class DiscordGetGuildPreviewConfig(BaseModel):
    """Get guild preview (public guilds)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_guild_preview"] = Field(
        default="get_guild_preview",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "Get Guild Preview",
            "x-keywords": ["server preview", "guild preview", "public server info"],
        },
        title="Get Guild Preview",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


class DiscordGetGuildVanityUrlConfig(BaseModel):
    """Get guild vanity URL"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_guild_vanity_url"] = Field(
        default="get_guild_vanity_url",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "Get Guild Vanity Url",
            "x-keywords": [
                "vanity url",
                "custom invite",
                "server vanity",
                "vanity link",
            ],
        },
        title="Get Guild Vanity Url",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


class DiscordGetGuildBansConfig(BaseModel):
    """Get all bans for a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_guild_bans"] = Field(
        default="list_guild_bans",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "List Guild Bans",
            "x-keywords": ["banned users", "ban list", "all bans"],
        },
        title="List Guild Bans",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    limit: Optional[int] = Field(
        default=100, title="Limit", description="Max bans to return (1-1000)"
    )


class DiscordGetGuildBanConfig(BaseModel):
    """Get a specific ban"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_guild_ban"] = Field(
        default="get_guild_ban",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Get Guild Ban",
            "x-keywords": ["one ban", "ban details", "check ban"],
        },
        title="Get Guild Ban",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    user_id: str = Field(..., title="User ID", description="User ID to get ban for")


class DiscordGetGuildPruneCountConfig(BaseModel):
    """Get guild prune count (inactive members)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_guild_prune_count"] = Field(
        default="get_guild_prune_count",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "Get Guild Prune Count",
            "x-keywords": [
                "prune count",
                "inactive members count",
                "how many inactive",
            ],
        },
        title="Get Guild Prune Count",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    days: Optional[int] = Field(
        default=7, title="Days", description="Number of days of inactivity (1-30)"
    )


class DiscordBeginGuildPruneConfig(BaseModel):
    """Begin guild prune (remove inactive members)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["begin_guild_prune_for_inactive_members"] = Field(
        default="begin_guild_prune_for_inactive_members",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "Begin Guild Prune for Inactive Members",
            "x-keywords": [
                "prune members",
                "remove inactive",
                "clean inactive members",
                "kick inactive",
            ],
        },
        title="Begin Guild Prune for Inactive Members",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    days: int = Field(
        default=7, title="Days", description="Number of days of inactivity (1-30)"
    )
    compute_prune_count: Optional[bool] = Field(
        default=True,
        title="Compute Prune Count",
        description="Whether to return pruned count",
    )


# ============================================================================
# Poll Operations
# ============================================================================


class DiscordGetPollAnswerVotersConfig(BaseModel):
    """Get voters for a poll answer"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_poll_answer_voters"] = Field(
        default="list_poll_answer_voters",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Poll",
            "x-is-trigger": False,
            "x-display-name": "List Poll Answer Voters",
            "x-keywords": [
                "who voted",
                "poll voters",
                "poll answer votes",
                "voters for option",
            ],
        },
        title="List Poll Answer Voters",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")
    message_id: str = Field(..., title="Message ID", description="Poll message ID")
    answer_id: int = Field(..., title="Answer ID", description="Poll answer ID")
    limit: Optional[int] = Field(
        default=25, title="Limit", description="Max voters to return (1-100)"
    )


class DiscordEndPollConfig(BaseModel):
    """Immediately end a poll"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["end_poll_immediately"] = Field(
        default="end_poll_immediately",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "End Poll Immediately",
            "x-keywords": ["close poll", "stop poll", "finish poll early"],
        },
        title="End Poll Immediately",
    )
    channel_id: str = Field(..., title="Channel ID", description="Discord channel ID")
    message_id: str = Field(..., title="Message ID", description="Poll message ID")


# ============================================================================
# Soundboard Operations
# ============================================================================


class DiscordSendSoundboardSoundConfig(BaseModel):
    """Play a soundboard sound in a voice channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["play_soundboard_sound_in_voice_channel"] = Field(
        default="play_soundboard_sound_in_voice_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Soundboard",
            "x-is-trigger": False,
            "x-display-name": "Play Soundboard Sound in Voice Channel",
            "x-keywords": [
                "play sound",
                "soundboard play",
                "play clip in voice",
                "trigger sound",
            ],
        },
        title="Play Soundboard Sound in Voice Channel",
    )
    channel_id: str = Field(
        ..., title="Voice Channel ID", description="Voice channel ID to play sound in"
    )
    sound_id: str = Field(..., title="Sound ID", description="Soundboard sound ID")
    source_guild_id: Optional[str] = Field(
        default=None,
        title="Source Guild ID",
        description="Guild ID where the soundboard sound is from (if custom)",
    )


class DiscordListDefaultSoundboardSoundsConfig(BaseModel):
    """List default soundboard sounds available to all users"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_default_soundboard_sounds"] = Field(
        default="list_default_soundboard_sounds",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Soundboard",
            "x-is-trigger": False,
            "x-display-name": "List Default Soundboard Sounds",
            "x-keywords": [
                "default soundboard sounds",
                "built in sounds",
                "stock sounds",
                "global sound effects",
                "standard soundboard",
            ],
        },
        title="List Default Soundboard Sounds",
    )


class DiscordListGuildSoundboardSoundsConfig(BaseModel):
    """List guild's soundboard sounds"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_guild_soundboard_sounds"] = Field(
        default="list_guild_soundboard_sounds",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Soundboard",
            "x-is-trigger": False,
            "x-display-name": "List Guild Soundboard Sounds",
            "x-keywords": [
                "server soundboard sounds",
                "custom guild sounds",
                "soundboard sound effects",
                "server sound clips",
                "guild sound effects",
            ],
        },
        title="List Guild Soundboard Sounds",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


class DiscordGetGuildSoundboardSoundConfig(BaseModel):
    """Get a specific guild soundboard sound"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_guild_soundboard_sound"] = Field(
        default="get_guild_soundboard_sound",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Soundboard",
            "x-is-trigger": False,
            "x-display-name": "Get Guild Soundboard Sound",
            "x-keywords": [
                "single soundboard sound",
                "fetch sound clip",
                "one server sound",
                "sound effect details",
            ],
        },
        title="Get Guild Soundboard Sound",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    sound_id: str = Field(..., title="Sound ID", description="Soundboard sound ID")


class DiscordCreateGuildSoundboardSoundConfig(BaseModel):
    """Create a new soundboard sound for a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_guild_soundboard_sound"] = Field(
        default="create_guild_soundboard_sound",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Soundboard",
            "x-is-trigger": False,
            "x-display-name": "Create Guild Soundboard Sound",
            "x-keywords": [
                "upload soundboard sound",
                "new sound clip",
                "add server sound",
                "make sound effect",
                "upload sound effect",
            ],
        },
        title="Create Guild Soundboard Sound",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    name: str = Field(
        ..., title="Sound Name", description="Name of the soundboard sound"
    )
    sound: str = Field(
        ...,
        title="Sound",
        description="The sound to upload — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). Max 512kb, max 5.2s duration.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "audio/*"},
    )
    volume: Optional[float] = Field(
        default=1.0, title="Volume", description="Volume of the sound (0.0 to 1.0)"
    )
    emoji_id: Optional[str] = Field(
        default=None, title="Emoji ID", description="Custom emoji ID for the sound"
    )
    emoji_name: Optional[str] = Field(
        default=None, title="Emoji Name", description="Unicode emoji for the sound"
    )


class DiscordModifyGuildSoundboardSoundConfig(BaseModel):
    """Modify a guild soundboard sound"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_guild_soundboard_sound"] = Field(
        default="update_guild_soundboard_sound",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Soundboard",
            "x-is-trigger": False,
            "x-display-name": "Update Guild Soundboard Sound",
            "x-keywords": [
                "rename soundboard sound",
                "edit sound clip",
                "change server sound",
                "modify sound effect",
            ],
        },
        title="Update Guild Soundboard Sound",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    sound_id: str = Field(..., title="Sound ID", description="Soundboard sound ID")
    name: Optional[str] = Field(
        default=None, title="Sound Name", description="New name for the sound"
    )
    volume: Optional[float] = Field(
        default=None, title="Volume", description="New volume (0.0 to 1.0)"
    )
    emoji_id: Optional[str] = Field(
        default=None, title="Emoji ID", description="New custom emoji ID"
    )
    emoji_name: Optional[str] = Field(
        default=None, title="Emoji Name", description="New unicode emoji"
    )


class DiscordDeleteGuildSoundboardSoundConfig(BaseModel):
    """Delete a guild soundboard sound"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_guild_soundboard_sound"] = Field(
        default="delete_guild_soundboard_sound",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Soundboard",
            "x-is-trigger": False,
            "x-display-name": "Delete Guild Soundboard Sound",
            "x-keywords": [
                "remove soundboard sound",
                "delete sound clip",
                "erase server sound",
                "trash sound effect",
            ],
        },
        title="Delete Guild Soundboard Sound",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    sound_id: str = Field(
        ..., title="Sound ID", description="Soundboard sound ID to delete"
    )


# ============================================================================
# Guild Template Operations
# ============================================================================


class DiscordGetGuildTemplateConfig(BaseModel):
    """Get a guild template by code"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_guild_template"] = Field(
        default="get_guild_template",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild Template",
            "x-is-trigger": False,
            "x-display-name": "Get Guild Template",
            "x-keywords": [
                "server template by code",
                "fetch server blueprint",
                "template details",
                "preview server template",
            ],
        },
        title="Get Guild Template",
    )
    template_code: str = Field(
        ..., title="Template Code", description="Guild template code"
    )


class DiscordCreateGuildFromTemplateConfig(BaseModel):
    """Create a new guild from a template"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_guild_from_template"] = Field(
        default="create_guild_from_template",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "Create Guild from Template",
            "x-keywords": [
                "new server from template",
                "clone server blueprint",
                "spin up server template",
                "build server from template",
            ],
        },
        title="Create Guild from Template",
    )
    template_code: str = Field(
        ..., title="Template Code", description="Guild template code"
    )
    name: str = Field(..., title="Guild Name", description="Name of the new guild")
    icon: Optional[str] = Field(
        default=None,
        title="Guild Icon",
        description="The guild icon to use — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )


class DiscordGetGuildTemplatesConfig(BaseModel):
    """Get all templates for a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_guild_templates"] = Field(
        default="list_guild_templates",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild Template",
            "x-is-trigger": False,
            "x-display-name": "List Guild Templates",
            "x-keywords": [
                "server templates",
                "all server blueprints",
                "guild blueprint list",
                "saved server templates",
            ],
        },
        title="List Guild Templates",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


class DiscordCreateGuildTemplateConfig(BaseModel):
    """Create a guild template"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_guild_template"] = Field(
        default="create_guild_template",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild Template",
            "x-is-trigger": False,
            "x-display-name": "Create Guild Template",
            "x-keywords": [
                "save server as template",
                "make server blueprint",
                "snapshot server template",
                "new guild template",
            ],
        },
        title="Create Guild Template",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    name: str = Field(..., title="Template Name", description="Name of the template")
    description: Optional[str] = Field(
        default=None, title="Description", description="Description of the template"
    )


class DiscordSyncGuildTemplateConfig(BaseModel):
    """Sync a guild template with current guild state"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["sync_guild_template_with_state"] = Field(
        default="sync_guild_template_with_state",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild Template",
            "x-is-trigger": False,
            "x-display-name": "Sync Guild Template with State",
            "x-keywords": [
                "refresh server template",
                "resync blueprint",
                "update template snapshot",
                "match template to server",
            ],
        },
        title="Sync Guild Template with State",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    template_code: str = Field(
        ..., title="Template Code", description="Guild template code"
    )


class DiscordModifyGuildTemplateConfig(BaseModel):
    """Modify a guild template"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_guild_template"] = Field(
        default="update_guild_template",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild Template",
            "x-is-trigger": False,
            "x-display-name": "Update Guild Template",
            "x-keywords": [
                "rename server template",
                "edit blueprint details",
                "change template name",
                "modify guild template",
            ],
        },
        title="Update Guild Template",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    template_code: str = Field(
        ..., title="Template Code", description="Guild template code"
    )
    name: Optional[str] = Field(
        default=None, title="Template Name", description="New name for the template"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="New description"
    )


class DiscordDeleteGuildTemplateConfig(BaseModel):
    """Delete a guild template"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_guild_template"] = Field(
        default="delete_guild_template",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild Template",
            "x-is-trigger": False,
            "x-display-name": "Delete Guild Template",
            "x-keywords": [
                "remove server template",
                "delete server blueprint",
                "erase guild template",
                "trash template",
            ],
        },
        title="Delete Guild Template",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    template_code: str = Field(
        ..., title="Template Code", description="Guild template code"
    )


# ============================================================================
# Guild Onboarding Operations
# ============================================================================


class DiscordGetGuildOnboardingConfig(BaseModel):
    """Get guild onboarding configuration"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_guild_onboarding_config"] = Field(
        default="get_guild_onboarding_config",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "Get Guild Onboarding Config",
            "x-keywords": [
                "server onboarding settings",
                "fetch onboarding flow",
                "view newcomer setup",
                "onboarding configuration",
            ],
        },
        title="Get Guild Onboarding Config",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


class DiscordModifyGuildOnboardingConfig(BaseModel):
    """Modify guild onboarding configuration"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_guild_onboarding_config"] = Field(
        default="update_guild_onboarding_config",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "Update Guild Onboarding Config",
            "x-keywords": [
                "edit onboarding flow",
                "change newcomer setup",
                "configure server onboarding",
                "modify onboarding prompts",
            ],
        },
        title="Update Guild Onboarding Config",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    enabled: Optional[bool] = Field(
        default=None, title="Enabled", description="Whether onboarding is enabled"
    )
    mode: Optional[int] = Field(
        default=None, title="Mode", description="Onboarding mode"
    )
    default_channel_ids: Optional[List[str]] = Field(
        default=None,
        title="Default Channel IDs",
        description="Default channels for new members",
    )


# ============================================================================
# DM/Group DM Operations
# ============================================================================


class DiscordCreateDMConfig(BaseModel):
    """Create a DM channel with a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_direct_message_channel"] = Field(
        default="create_direct_message_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Direct Message",
            "x-is-trigger": False,
            "x-display-name": "Create Direct Message Channel",
            "x-keywords": [
                "open dm",
                "start private message",
                "dm a user",
                "begin direct message",
                "private chat with user",
            ],
        },
        title="Create Direct Message Channel",
    )
    recipient_id: str = Field(
        ..., title="Recipient User ID", description="Discord user ID to create DM with"
    )


class DiscordCreateGroupDMConfig(BaseModel):
    """Create a group DM channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_group_direct_message_channel"] = Field(
        default="create_group_direct_message_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Direct Message",
            "x-is-trigger": False,
            "x-display-name": "Create Group Direct Message Channel",
            "x-keywords": [
                "start group dm",
                "group private message",
                "multi person dm",
                "open group chat",
            ],
        },
        title="Create Group Direct Message Channel",
    )
    access_tokens: List[str] = Field(
        ..., title="Access Tokens", description="Access tokens of users to add"
    )
    nicks: Optional[Dict[str, str]] = Field(
        default=None, title="Nicknames", description="Map of user IDs to nicknames"
    )


# ============================================================================
# Application Commands Operations
# ============================================================================


class DiscordGetGlobalApplicationCommandsConfig(BaseModel):
    """Get all global application commands"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_global_application_commands"] = Field(
        default="list_global_application_commands",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Application Command",
            "x-is-trigger": False,
            "x-display-name": "List Global Application Commands",
            "x-keywords": [
                "global slash commands",
                "all bot commands",
                "app commands everywhere",
                "global bot commands",
            ],
        },
        title="List Global Application Commands",
    )
    application_id: str = Field(
        ..., title="Application ID", description="Discord application ID"
    )
    with_localizations: Optional[bool] = Field(
        default=False,
        title="With Localizations",
        description="Include full localization dictionaries",
    )


class DiscordCreateGlobalApplicationCommandConfig(BaseModel):
    """Create a global application command"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_global_application_command"] = Field(
        default="create_global_application_command",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Application Command",
            "x-is-trigger": False,
            "x-display-name": "Create Global Application Command",
            "x-keywords": [
                "register global slash command",
                "new global bot command",
                "add app command everywhere",
                "make global command",
            ],
        },
        title="Create Global Application Command",
    )
    application_id: str = Field(
        ..., title="Application ID", description="Discord application ID"
    )
    name: str = Field(
        ..., title="Command Name", description="Name of the command (1-32 chars)"
    )
    description: str = Field(
        ..., title="Description", description="Description of the command (1-100 chars)"
    )
    type: Optional[int] = Field(
        default=1,
        title="Command Type",
        description="Type of command (1=CHAT_INPUT, 2=USER, 3=MESSAGE)",
    )


class DiscordGetGlobalApplicationCommandConfig(BaseModel):
    """Get a specific global application command"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_global_application_command"] = Field(
        default="get_global_application_command",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Application Command",
            "x-is-trigger": False,
            "x-display-name": "Get Global Application Command",
            "x-keywords": [
                "single global command",
                "fetch global slash command",
                "one global bot command",
                "global command details",
            ],
        },
        title="Get Global Application Command",
    )
    application_id: str = Field(
        ..., title="Application ID", description="Discord application ID"
    )
    command_id: str = Field(
        ..., title="Command ID", description="Application command ID"
    )


class DiscordEditGlobalApplicationCommandConfig(BaseModel):
    """Edit a global application command"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["edit_global_application_command"] = Field(
        default="edit_global_application_command",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Application Command",
            "x-is-trigger": False,
            "x-display-name": "Edit Global Application Command",
            "x-keywords": [
                "update global slash command",
                "change global bot command",
                "modify global command",
                "edit app command everywhere",
            ],
        },
        title="Edit Global Application Command",
    )
    application_id: str = Field(
        ..., title="Application ID", description="Discord application ID"
    )
    command_id: str = Field(
        ..., title="Command ID", description="Application command ID"
    )
    name: Optional[str] = Field(
        default=None, title="Command Name", description="New name for the command"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="New description"
    )


class DiscordDeleteGlobalApplicationCommandConfig(BaseModel):
    """Delete a global application command"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_global_application_command"] = Field(
        default="delete_global_application_command",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Application Command",
            "x-is-trigger": False,
            "x-display-name": "Delete Global Application Command",
            "x-keywords": [
                "remove global slash command",
                "delete global bot command",
                "unregister global command",
                "erase app command everywhere",
            ],
        },
        title="Delete Global Application Command",
    )
    application_id: str = Field(
        ..., title="Application ID", description="Discord application ID"
    )
    command_id: str = Field(
        ..., title="Command ID", description="Application command ID to delete"
    )


class DiscordGetGuildApplicationCommandsConfig(BaseModel):
    """Get all guild application commands"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_guild_application_commands"] = Field(
        default="list_guild_application_commands",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Application Command",
            "x-is-trigger": False,
            "x-display-name": "List Guild Application Commands",
            "x-keywords": [
                "server slash commands",
                "guild bot commands",
                "app commands for server",
                "server specific commands",
            ],
        },
        title="List Guild Application Commands",
    )
    application_id: str = Field(
        ..., title="Application ID", description="Discord application ID"
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


class DiscordCreateGuildApplicationCommandConfig(BaseModel):
    """Create a guild application command"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_guild_application_command"] = Field(
        default="create_guild_application_command",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Application Command",
            "x-is-trigger": False,
            "x-display-name": "Create Guild Application Command",
            "x-keywords": [
                "register server slash command",
                "new guild bot command",
                "add command to server",
                "make server command",
            ],
        },
        title="Create Guild Application Command",
    )
    application_id: str = Field(
        ..., title="Application ID", description="Discord application ID"
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    name: str = Field(
        ..., title="Command Name", description="Name of the command (1-32 chars)"
    )
    description: str = Field(
        ..., title="Description", description="Description of the command (1-100 chars)"
    )
    type: Optional[int] = Field(
        default=1,
        title="Command Type",
        description="Type of command (1=CHAT_INPUT, 2=USER, 3=MESSAGE)",
    )


class DiscordGetGuildApplicationCommandConfig(BaseModel):
    """Get a specific guild application command"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_guild_application_command"] = Field(
        default="get_guild_application_command",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Application Command",
            "x-is-trigger": False,
            "x-display-name": "Get Guild Application Command",
            "x-keywords": [
                "single server command",
                "fetch guild slash command",
                "one server bot command",
                "server command details",
            ],
        },
        title="Get Guild Application Command",
    )
    application_id: str = Field(
        ..., title="Application ID", description="Discord application ID"
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    command_id: str = Field(
        ..., title="Command ID", description="Application command ID"
    )


class DiscordEditGuildApplicationCommandConfig(BaseModel):
    """Edit a guild application command"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["edit_guild_application_command"] = Field(
        default="edit_guild_application_command",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Application Command",
            "x-is-trigger": False,
            "x-display-name": "Edit Guild Application Command",
            "x-keywords": [
                "update server slash command",
                "change guild bot command",
                "modify server command",
                "edit command in server",
            ],
        },
        title="Edit Guild Application Command",
    )
    application_id: str = Field(
        ..., title="Application ID", description="Discord application ID"
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    command_id: str = Field(
        ..., title="Command ID", description="Application command ID"
    )
    name: Optional[str] = Field(
        default=None, title="Command Name", description="New name for the command"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="New description"
    )


class DiscordDeleteGuildApplicationCommandConfig(BaseModel):
    """Delete a guild application command"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_guild_application_command"] = Field(
        default="delete_guild_application_command",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Application Command",
            "x-is-trigger": False,
            "x-display-name": "Delete Guild Application Command",
            "x-keywords": [
                "remove server slash command",
                "delete guild bot command",
                "unregister server command",
                "erase command from server",
            ],
        },
        title="Delete Guild Application Command",
    )
    application_id: str = Field(
        ..., title="Application ID", description="Discord application ID"
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    command_id: str = Field(
        ..., title="Command ID", description="Application command ID to delete"
    )


# ============================================================================
# SKUs & Entitlements Operations (Monetization)
# ============================================================================


class DiscordListSKUsConfig(BaseModel):
    """List all SKUs for an application"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_application_skus"] = Field(
        default="list_application_skus",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "SKU",
            "x-is-trigger": False,
            "x-display-name": "List Application Skus",
            "x-keywords": [
                "app skus",
                "store skus",
                "premium products",
                "monetization skus",
                "app store items",
            ],
        },
        title="List Application Skus",
    )
    application_id: str = Field(
        ..., title="Application ID", description="Discord application ID"
    )


class DiscordListEntitlementsConfig(BaseModel):
    """List entitlements for an application"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_application_entitlements"] = Field(
        default="list_application_entitlements",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Entitlement",
            "x-is-trigger": False,
            "x-display-name": "List Application Entitlements",
            "x-keywords": [
                "app entitlements",
                "premium grants",
                "user entitlements",
                "subscription entitlements",
                "purchases for app",
            ],
        },
        title="List Application Entitlements",
    )
    application_id: str = Field(
        ..., title="Application ID", description="Discord application ID"
    )
    user_id: Optional[str] = Field(
        default=None, title="User ID", description="Filter by user ID"
    )
    guild_id: Optional[str] = Field(
        default=None, title="Guild ID", description="Filter by guild ID"
    )
    exclude_ended: Optional[bool] = Field(
        default=False, title="Exclude Ended", description="Exclude ended entitlements"
    )


class DiscordCreateTestEntitlementConfig(BaseModel):
    """Create a test entitlement"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_test_entitlement"] = Field(
        default="create_test_entitlement",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Entitlement",
            "x-is-trigger": False,
            "x-display-name": "Create Test Entitlement",
            "x-keywords": [
                "test entitlement",
                "grant premium for testing",
                "fake purchase",
                "sandbox entitlement",
            ],
        },
        title="Create Test Entitlement",
    )
    application_id: str = Field(
        ..., title="Application ID", description="Discord application ID"
    )
    sku_id: str = Field(
        ..., title="SKU ID", description="SKU ID to grant entitlement for"
    )
    owner_id: str = Field(..., title="Owner ID", description="User or Guild ID")
    owner_type: int = Field(
        ..., title="Owner Type", description="Type of owner (1=Guild, 2=User)"
    )


class DiscordDeleteTestEntitlementConfig(BaseModel):
    """Delete a test entitlement"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_test_entitlement"] = Field(
        default="delete_test_entitlement",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Entitlement",
            "x-is-trigger": False,
            "x-display-name": "Delete Test Entitlement",
            "x-keywords": [
                "remove test entitlement",
                "revoke test premium",
                "delete fake purchase",
                "clear sandbox entitlement",
            ],
        },
        title="Delete Test Entitlement",
    )
    application_id: str = Field(
        ..., title="Application ID", description="Discord application ID"
    )
    entitlement_id: str = Field(
        ..., title="Entitlement ID", description="Test entitlement ID to delete"
    )


class DiscordConsumeEntitlementConfig(BaseModel):
    """Consume a one-time purchase entitlement"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["consume_one_time_purchase_entitlement"] = Field(
        default="consume_one_time_purchase_entitlement",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Entitlement",
            "x-is-trigger": False,
            "x-display-name": "Consume One Time Purchase Entitlement",
            "x-keywords": [
                "consume entitlement",
                "mark purchase used",
                "redeem one time purchase",
                "use up entitlement",
            ],
        },
        title="Consume One Time Purchase Entitlement",
    )
    application_id: str = Field(
        ..., title="Application ID", description="Discord application ID"
    )
    entitlement_id: str = Field(
        ..., title="Entitlement ID", description="Entitlement ID to consume"
    )


# ============================================================================
# Guild Widget Operations
# ============================================================================


class DiscordGetGuildWidgetConfig(BaseModel):
    """Get guild widget settings"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_guild_widget_settings"] = Field(
        default="get_guild_widget_settings",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "Get Guild Widget Settings",
            "x-keywords": [
                "server widget settings",
                "embed widget config",
                "fetch widget settings",
                "website widget config",
            ],
        },
        title="Get Guild Widget Settings",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


class DiscordModifyGuildWidgetConfig(BaseModel):
    """Modify guild widget settings"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_guild_widget_settings"] = Field(
        default="update_guild_widget_settings",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "Update Guild Widget Settings",
            "x-keywords": [
                "edit server widget",
                "change embed widget",
                "configure website widget",
                "modify widget settings",
            ],
        },
        title="Update Guild Widget Settings",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    enabled: Optional[bool] = Field(
        default=None, title="Enabled", description="Whether the widget is enabled"
    )
    channel_id: Optional[str] = Field(
        default=None, title="Channel ID", description="Widget channel ID"
    )


# ============================================================================
# Guild Welcome Screen Operations
# ============================================================================


class DiscordGetGuildWelcomeScreenConfig(BaseModel):
    """Get guild welcome screen"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_guild_welcome_screen"] = Field(
        default="get_guild_welcome_screen",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "Get Guild Welcome Screen",
            "x-keywords": [
                "server welcome screen",
                "fetch welcome page",
                "view greeting screen",
                "welcome screen config",
            ],
        },
        title="Get Guild Welcome Screen",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


class DiscordModifyGuildWelcomeScreenConfig(BaseModel):
    """Modify guild welcome screen"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_guild_welcome_screen"] = Field(
        default="update_guild_welcome_screen",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "Update Guild Welcome Screen",
            "x-keywords": [
                "edit welcome screen",
                "change greeting screen",
                "configure welcome page",
                "modify welcome screen",
            ],
        },
        title="Update Guild Welcome Screen",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    enabled: Optional[bool] = Field(
        default=None,
        title="Enabled",
        description="Whether the welcome screen is enabled",
    )
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="Server description in the welcome screen",
    )


# ============================================================================
# Voice State Operations
# ============================================================================


class DiscordModifyCurrentUserVoiceStateConfig(BaseModel):
    """Modify current user's voice state"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_current_user_voice_state"] = Field(
        default="update_current_user_voice_state",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Voice",
            "x-is-trigger": False,
            "x-display-name": "Update Current User Voice State",
            "x-keywords": [
                "my voice state",
                "unmute myself",
                "request to speak",
                "go on stage",
                "suppress my voice",
            ],
        },
        title="Update Current User Voice State",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    channel_id: str = Field(..., title="Channel ID", description="Voice channel ID")
    suppress: Optional[bool] = Field(
        default=None, title="Suppress", description="Whether to suppress the user"
    )
    request_to_speak_timestamp: Optional[str] = Field(
        default=None,
        title="Request to Speak Timestamp",
        description="ISO 8601 timestamp to request to speak",
    )


class DiscordModifyUserVoiceStateConfig(BaseModel):
    """Modify another user's voice state"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_user_voice_state"] = Field(
        default="update_user_voice_state",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Voice",
            "x-is-trigger": False,
            "x-display-name": "Update User Voice State",
            "x-keywords": [
                "move user to speaker",
                "invite member to speak",
                "another user voice state",
                "force user on stage",
            ],
        },
        title="Update User Voice State",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    channel_id: str = Field(..., title="Channel ID", description="Voice channel ID")
    user_id: str = Field(..., title="User ID", description="User ID to modify")
    suppress: Optional[bool] = Field(
        default=None, title="Suppress", description="Whether to suppress the user"
    )


# ============================================================================
# Additional User Operations
# ============================================================================


class DiscordGetCurrentUserGuildsConfig(BaseModel):
    """Get current user's guilds"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_current_user_guilds"] = Field(
        default="list_current_user_guilds",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List Current User Guilds",
            "x-keywords": [
                "my servers",
                "servers im in",
                "current user servers",
                "guilds i belong to",
            ],
        },
        title="List Current User Guilds",
    )
    limit: Optional[int] = Field(
        default=200, title="Limit", description="Max guilds to return (1-200)"
    )
    before: Optional[str] = Field(
        default=None, title="Before", description="Get guilds before this guild ID"
    )
    after: Optional[str] = Field(
        default=None, title="After", description="Get guilds after this guild ID"
    )


class DiscordLeaveGuildConfig(BaseModel):
    """Leave a guild"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["leave_guild"] = Field(
        default="leave_guild",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "Leave Guild",
            "x-keywords": [
                "leave server",
                "exit guild",
                "quit server",
                "remove myself from server",
            ],
        },
        title="Leave Guild",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID to leave"
    )


class DiscordGetUserConnectionsConfig(BaseModel):
    """Get user's connections"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_user_connections"] = Field(
        default="list_user_connections",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List User Connections",
            "x-keywords": [
                "linked accounts",
                "connected accounts",
                "social connections",
                "external account links",
            ],
        },
        title="List User Connections",
    )


# ============================================================================
# Guild Integration Operations
# ============================================================================


class DiscordGetGuildIntegrationsConfig(BaseModel):
    """Get guild integrations"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_guild_integrations"] = Field(
        default="list_guild_integrations",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "List Guild Integrations",
            "x-keywords": [
                "server integrations",
                "connected apps",
                "guild integrations list",
                "linked services",
            ],
        },
        title="List Guild Integrations",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )


class DiscordDeleteGuildIntegrationConfig(BaseModel):
    """Delete a guild integration"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_guild_integration"] = Field(
        default="delete_guild_integration",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Guild",
            "x-is-trigger": False,
            "x-display-name": "Delete Guild Integration",
            "x-keywords": [
                "remove server integration",
                "disconnect app",
                "delete guild integration",
                "unlink service",
            ],
        },
        title="Delete Guild Integration",
    )
    guild_id: str = Field(
        ..., title="Guild ID", description="Discord guild (server) ID"
    )
    integration_id: str = Field(
        ..., title="Integration ID", description="Integration ID to delete"
    )


# Discriminated union for all config types
DiscordConfig = Annotated[
    Union[
        # Message Operations
        DiscordSendMessageConfig,
        DiscordSendEmbedConfig,
        DiscordGetMessageConfig,
        DiscordGetMessagesConfig,
        DiscordEditMessageConfig,
        DiscordDeleteMessageConfig,
        DiscordCrosspostMessageConfig,
        DiscordPinMessageConfig,
        DiscordUnpinMessageConfig,
        DiscordGetPinnedMessagesConfig,
        DiscordBulkDeleteMessagesConfig,
        # Reaction Operations
        DiscordCreateReactionConfig,
        DiscordDeleteReactionConfig,
        DiscordGetReactionsConfig,
        DiscordDeleteAllReactionsConfig,
        DiscordDeleteAllReactionsForEmojiConfig,
        # Channel Operations
        DiscordGetChannelConfig,
        DiscordCreateChannelConfig,
        DiscordModifyChannelConfig,
        DiscordDeleteChannelConfig,
        DiscordTriggerTypingConfig,
        DiscordEditChannelPermissionsConfig,
        DiscordListChannelsConfig,
        # Thread Operations
        DiscordStartThreadFromMessageConfig,
        DiscordStartThreadConfig,
        DiscordJoinThreadConfig,
        DiscordLeaveThreadConfig,
        DiscordAddThreadMemberConfig,
        DiscordRemoveThreadMemberConfig,
        DiscordListThreadMembersConfig,
        DiscordListActiveThreadsConfig,
        # Guild Operations
        DiscordListGuildsConfig,
        DiscordGetGuildConfig,
        DiscordModifyGuildConfig,
        DiscordGetGuildPreviewConfig,
        DiscordGetGuildVanityUrlConfig,
        DiscordGetGuildPruneCountConfig,
        DiscordBeginGuildPruneConfig,
        # User/Member Operations
        DiscordGetUserConfig,
        DiscordGetGuildMembersConfig,
        DiscordGetGuildMemberConfig,
        DiscordModifyGuildMemberConfig,
        DiscordKickMemberConfig,
        DiscordBanMemberConfig,
        DiscordUnbanMemberConfig,
        DiscordGetGuildBansConfig,
        DiscordGetGuildBanConfig,
        # Role Operations
        DiscordGetGuildRolesConfig,
        DiscordCreateRoleConfig,
        DiscordModifyRoleConfig,
        DiscordDeleteRoleConfig,
        DiscordAddRoleToMemberConfig,
        DiscordRemoveRoleFromMemberConfig,
        # Invite Operations
        DiscordGetInviteConfig,
        DiscordDeleteInviteConfig,
        DiscordGetChannelInvitesConfig,
        DiscordCreateChannelInviteConfig,
        DiscordGetGuildInvitesConfig,
        # Webhook Operations
        DiscordExecuteWebhookConfig,
        DiscordOnApplicationAuthorizedConfig,
        DiscordOnApplicationDeauthorizedConfig,
        DiscordOnEntitlementCreateConfig,
        DiscordOnEntitlementUpdateConfig,
        DiscordOnEntitlementDeleteConfig,
        DiscordOnSlashCommandConfig,
        DiscordOnMessageConfig,
        DiscordOnMentionConfig,
        DiscordGetChannelWebhooksConfig,
        DiscordGetGuildWebhooksConfig,
        DiscordGetWebhookConfig,
        DiscordCreateWebhookConfig,
        DiscordModifyWebhookConfig,
        DiscordDeleteWebhookConfig,
        # Emoji Operations
        DiscordListGuildEmojisConfig,
        DiscordGetGuildEmojiConfig,
        DiscordCreateGuildEmojiConfig,
        DiscordModifyGuildEmojiConfig,
        DiscordDeleteGuildEmojiConfig,
        # Sticker Operations
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
        # Poll
        DiscordGetPollAnswerVotersConfig,
        DiscordEndPollConfig,
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
        # DM/Group DM Operations
        DiscordCreateDMConfig,
        DiscordCreateGroupDMConfig,
        # Application Commands Operations
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
        # SKUs & Entitlements (Monetization)
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
        # Voice State Operations
        DiscordModifyCurrentUserVoiceStateConfig,
        DiscordModifyUserVoiceStateConfig,
        # Additional User Operations
        DiscordGetCurrentUserGuildsConfig,
        DiscordLeaveGuildConfig,
        DiscordGetUserConnectionsConfig,
        # Guild Integration Operations
        DiscordGetGuildIntegrationsConfig,
        DiscordDeleteGuildIntegrationConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Config
# ============================================================================


class DiscordNodeConfig(NodeConfig[DiscordConfig, DiscordCredential]):
    """Complete node configuration for Discord"""

    pass


# ============================================================================
# Discord Node Implementation
# ============================================================================


class DiscordNode(AppEventTriggerMixin, WorkflowNode):
    """
    Discord automation node.

    Supports message sending, channel/guild operations, and webhooks.
    Works with both OAuth2 (user operations) and Bot Token authentication.
    """

    edit_examples = [
        'Send a message to #engineering: "Deploy to prod is complete"',
        'Create a new private channel named "incident-response"',
        "Add a reaction emoji to a specific message in #alerts",
        "Bulk delete messages older than 7 days in #spam",
        "Get all members of the server and export as a list",
        "Start a thread in #announcements with the new policy",
        "Forward a message from #general to #archive with metadata",
    ]

    _app_provider = "discord"
    _credential_prompt = (
        "Connect a Discord credential (bot install or bot token) to activate "
        "this trigger"
    )
    _trigger_event_map = {
        # Application lifecycle (via Discord Application Webhooks)
        "on_application_authorized": ["APPLICATION_AUTHORIZED"],
        "on_application_deauthorized": ["APPLICATION_DEAUTHORIZED"],
        # Premium entitlement events (via Discord Application Webhooks)
        "on_entitlement_create": ["ENTITLEMENT_CREATE"],
        "on_entitlement_update": ["ENTITLEMENT_UPDATE"],
        "on_entitlement_delete": ["ENTITLEMENT_DELETE"],
        # Interactions (via Discord Interactions endpoint)
        "on_slash_command": ["INTERACTION_APPLICATION_COMMAND"],
        # Channel messages (via the Gateway session NoClick's bot holds —
        # utils/discord_gateway_bridge.py; MESSAGE_MENTION is minted by the
        # receiver from a MESSAGE_CREATE that mentions the bot)
        "on_message": ["MESSAGE_CREATE"],
        "on_mention": ["MESSAGE_MENTION"],
    }

    # Event types delivered via the Interactions endpoint rather than app webhooks
    _interaction_event_types = {"INTERACTION_APPLICATION_COMMAND"}
    # Event types the Gateway listener forwards: rows are keyed by GUILD (the
    # bot-install credential's server), and Discord's application webhook
    # config never learns about them.
    _gateway_event_types = frozenset({"MESSAGE_CREATE", "MESSAGE_MENTION"})
    _gateway_trigger_operations = frozenset({"on_message", "on_mention"})

    scope_registry = DISCORD_SCOPES
    connection_evidence = ConnectionEvidence(
        field="guild_id",
        noun="servers",
    )

    @classmethod
    def get_config_model(cls):
        return DiscordNodeConfig

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        schema = super().get_config_schema()
        for config_schema in (schema.get("$defs") or {}).values():
            properties = config_schema.get("properties") or {}

            if (
                "guild_id" in properties
                and "x-dynamic-options" not in properties["guild_id"]
            ):
                properties["guild_id"]["x-dynamic-options"] = {
                    "field_name": "guild_id",
                    "placeholder": "Select a server...",
                    "searchable": True,
                    "allow_custom": True,
                    "custom_placeholder": "Or paste a guild ID / reference",
                }
                properties["guild_id"]["x-resource-type"] = "discord_guild"

            if (
                "channel_id" in properties
                and "x-dynamic-options" not in properties["channel_id"]
            ):
                dynamic_options = {
                    "field_name": "channel_id",
                    "placeholder": "Select a channel...",
                    "searchable": True,
                    "allow_custom": True,
                    "custom_placeholder": "Or paste a channel ID / reference",
                }
                if "guild_id" in properties:
                    dynamic_options["depends_on"] = "guild_id"
                properties["channel_id"]["x-dynamic-options"] = dynamic_options
                properties["channel_id"]["x-resource-type"] = "discord_channel"

            if (
                "user_id" in properties
                and "guild_id" in properties
                and "x-dynamic-options" not in properties["user_id"]
            ):
                properties["user_id"]["x-dynamic-options"] = {
                    "field_name": "user_id",
                    "placeholder": "Select a member...",
                    "searchable": True,
                    "allow_custom": True,
                    "custom_placeholder": "Or paste a user ID / reference",
                    "depends_on": "guild_id",
                }

            if (
                "role_id" in properties
                and "guild_id" in properties
                and "x-dynamic-options" not in properties["role_id"]
            ):
                properties["role_id"]["x-dynamic-options"] = {
                    "field_name": "role_id",
                    "placeholder": "Select a role...",
                    "searchable": True,
                    "allow_custom": True,
                    "custom_placeholder": "Or paste a role ID / reference",
                    "depends_on": "guild_id",
                }
                properties["role_id"]["x-resource-type"] = "discord_role"
        return schema

    @classmethod
    def _dynamic_options_auth_header(cls, credential_data: Dict[str, Any]) -> str:
        credential_data = credential_data or {}
        # bot_install — use platform bot token
        if credential_data.get("credential_type") == "discord_bot_install":
            platform_token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
            if platform_token:
                return (
                    platform_token
                    if platform_token.startswith("Bot ")
                    else f"Bot {platform_token}"
                )
            # Fall through to access_token for user-scoped ops when no platform token
        bot_token = (credential_data.get("bot_token") or "").strip()
        if bot_token:
            return bot_token if bot_token.startswith("Bot ") else f"Bot {bot_token}"
        access_token = (credential_data.get("access_token") or "").strip()
        if access_token:
            return f"Bearer {access_token}"
        raise ValueError("Connect a Discord account or bot token to load options")

    @classmethod
    async def _dynamic_options_request(
        cls,
        endpoint: str,
        auth_header: str,
        *,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{DISCORD_API_BASE}{endpoint}",
                headers={
                    "Authorization": auth_header,
                    "Content-Type": "application/json",
                },
                params=params,
            )

        if response.status_code == 204:
            return {}

        if response.status_code >= 400:
            try:
                error_data = response.json()
                error_msg = error_data.get("message", "Unknown error")
            except Exception:
                error_msg = response.text or "Unknown error"
            raise ValueError(
                f"Discord API error: {response.status_code} {response.reason_phrase} - {error_msg}"
            )

        return response.json()

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        logger.info(f"[DiscordNode] load_field_options called: field={field_name}")
        auth_header = cls._dynamic_options_auth_header(credential_data)
        context = context or {}
        operation = context.get("operation")
        # A bot-install credential authenticates as the PLATFORM bot, which is
        # in every customer's server — its options are the one server this
        # credential was installed into, never the bot's whole guild list.
        install_guild_id = cls._install_guild_id(credential_data)

        if field_name == "guild_id" and install_guild_id:
            options = [{
                "value": install_guild_id,
                "label": (credential_data or {}).get("guild_name") or install_guild_id,
            }]
            return {
                "options": filter_options_by_search(options, search, fields=("label", "value")),
                "next_page_token": None,
            }

        if field_name == "guild_id":

            async def fetch_page(after: Optional[str]):
                params: Dict[str, Any] = {"limit": 200}
                if after:
                    params["after"] = after
                guilds = await cls._dynamic_options_request(
                    "/users/@me/guilds", auth_header, params=params
                )
                options = [
                    {
                        "value": guild.get("id"),
                        "label": guild.get("name") or guild.get("id"),
                    }
                    for guild in guilds
                    if guild.get("id")
                ]
                next_cursor = guilds[-1].get("id") if len(guilds) == 200 else None
                return options, next_cursor

            return await load_paginated_options(
                fetch_page,
                page_token=page_token,
                search=search,
                fields=("label", "value"),
                log_label="DiscordNode.guild_id",
            )

        if field_name == "channel_id":
            guild_id = context.get("guild_id") or install_guild_id
            if guild_id:
                channels = await cls._dynamic_options_request(
                    f"/guilds/{guild_id}/channels", auth_header
                )
                options = [
                    {
                        "value": channel.get("id"),
                        "label": f"#{channel.get('name')}"
                        if channel.get("name")
                        else channel.get("id"),
                        "metadata": {"type": channel.get("type")},
                    }
                    for channel in channels
                    if channel.get("id")
                ]
            else:
                guilds = await cls._dynamic_options_request(
                    "/users/@me/guilds", auth_header, params={"limit": 50}
                )
                channel_lists = await asyncio.gather(
                    *[
                        cls._dynamic_options_request(
                            f"/guilds/{guild.get('id')}/channels", auth_header
                        )
                        for guild in guilds
                        if guild.get("id")
                    ],
                    return_exceptions=True,
                )
                options = []
                for guild, channels in zip(guilds, channel_lists):
                    if isinstance(channels, Exception):
                        logger.warning(
                            "[DiscordNode] skipping channel list for guild %s: %s",
                            guild.get("id"),
                            channels,
                        )
                        continue
                    guild_name = guild.get("name") or guild.get("id")
                    for channel in channels or []:
                        if not channel.get("id"):
                            continue
                        channel_name = channel.get("name") or channel.get("id")
                        label = (
                            f"{guild_name} / #{channel_name}"
                            if channel.get("name")
                            else f"{guild_name} / {channel_name}"
                        )
                        options.append(
                            {
                                "value": channel.get("id"),
                                "label": label,
                                "metadata": {
                                    "guild_id": guild.get("id"),
                                    "guild_name": guild_name,
                                    "type": channel.get("type"),
                                },
                            }
                        )
            return {
                "options": filter_options_by_search(
                    options, search, fields=("label", "value")
                ),
                "next_page_token": None,
            }

        if field_name == "user_id":
            guild_id = context.get("guild_id")
            if not guild_id:
                raise ValueError("Select a server first to load members")

            async def fetch_page(after: Optional[str]):
                params: Dict[str, Any] = {"limit": 1000}
                if after:
                    params["after"] = after
                members = await cls._dynamic_options_request(
                    f"/guilds/{guild_id}/members", auth_header, params=params
                )
                options = []
                for member in members:
                    user = member.get("user") or {}
                    user_id = user.get("id")
                    if not user_id:
                        continue
                    label = (
                        member.get("nick")
                        or user.get("global_name")
                        or user.get("username")
                        or user_id
                    )
                    options.append({"value": user_id, "label": label})
                next_cursor = (
                    ((members[-1].get("user") or {}).get("id"))
                    if len(members) == 1000
                    else None
                )
                return options, next_cursor

            return await load_paginated_options(
                fetch_page,
                page_token=page_token,
                search=search,
                fields=("label", "value"),
                log_label="DiscordNode.user_id",
            )

        if field_name == "role_id":
            guild_id = context.get("guild_id")
            if not guild_id:
                raise ValueError("Select a server first to load roles")
            roles = await cls._dynamic_options_request(
                f"/guilds/{guild_id}/roles", auth_header
            )
            options = [
                {
                    "value": role.get("id"),
                    "label": role.get("name") or role.get("id"),
                }
                for role in roles
                if role.get("id")
            ]
            return {
                "options": filter_options_by_search(
                    options, search, fields=("label", "value")
                ),
                "next_page_token": None,
            }

        return {"options": [], "next_page_token": None}

    @staticmethod
    def _format_bot_auth_header(bot_token: str) -> str:
        token = (bot_token or "").strip()
        if not token:
            raise ValueError("Discord bot token is required")
        return token if token.startswith("Bot ") else f"Bot {token}"

    @classmethod
    def _bot_auth_header_from_credential(cls, credential: Dict[str, Any]) -> str:
        if not isinstance(credential, dict):
            raise ValueError(
                "Discord trigger registration requires a bot token credential"
            )
        # bot_install OAuth — use the platform bot token from environment
        if credential.get("credential_type") == "discord_bot_install":
            platform_token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
            if platform_token:
                return cls._format_bot_auth_header(platform_token)
            raise ValueError(
                "DISCORD_BOT_TOKEN environment variable is required for bot install credentials. "
                "Add your Discord application's bot token to the server environment."
            )
        # Check for explicit bot_token key — works even if credential_type wasn't stored
        bot_token = credential.get("bot_token")
        if bot_token:
            return cls._format_bot_auth_header(bot_token)
        raise ValueError(
            "Discord trigger registration requires a bot token or bot install credential"
        )

    @classmethod
    def _discord_event_webhook_url(cls) -> str:
        base = os.environ.get("APP_WEBHOOK_BASE_URL")
        if not base:
            raise ValueError(
                "APP_WEBHOOK_BASE_URL is required to register Discord event webhooks"
            )
        return f"{base.rstrip('/')}/webhook/app/discord"

    @classmethod
    def _discord_interactions_webhook_url(cls) -> str:
        # Same host as app webhooks; the same route distinguishes payload types
        # by the `type` field in the JSON body (app events use type=1 + `event`
        # key; interactions use type=1 for PING and type=2+ for commands).
        return cls._discord_event_webhook_url()

    @staticmethod
    async def _discord_api_request(
        method: str,
        endpoint: str,
        auth_header: str,
        json_data: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        url = f"{DISCORD_API_BASE}{endpoint}"
        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json",
        }

        logger.info(f"[DiscordNode] Making {method} request to {endpoint}")

        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_data,
                params=params,
                timeout=30.0,
            )

            logger.info(f"[DiscordNode] Response status: {response.status_code}")

            if response.status_code == 204:
                return {"success": True}

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message", "Unknown error")
                except Exception:
                    error_msg = response.text or "Unknown error"
                raise ValueError(
                    f"Discord API error: {response.status_code} "
                    f"{response.reason_phrase} - {error_msg}"
                )

            return response.json()

    @classmethod
    async def _fetch_current_application(
        cls, credential: Dict[str, Any]
    ) -> Dict[str, Any]:
        app = await cls._discord_api_request(
            "GET",
            "/oauth2/applications/@me",
            cls._bot_auth_header_from_credential(credential),
        )
        if not app.get("id") or not app.get("verify_key"):
            raise ValueError(
                "Discord did not return the current application id/verify_key"
            )
        return app

    @staticmethod
    def _install_guild_id(credential: Optional[Dict[str, Any]]) -> Optional[str]:
        """The server a bot-install credential was installed into (None for a
        bot-token credential, which is not bound to one server)."""
        if not isinstance(credential, dict):
            return None
        if credential.get("credential_type") != "discord_bot_install":
            return None
        guild_id = str(credential.get("guild_id") or "").strip()
        return guild_id or None

    @classmethod
    async def _update_event_webhooks(
        cls, credential: Dict[str, Any], event_types: List[str]
    ) -> Dict[str, Any]:
        # Separate app-level webhook events from interaction events; Gateway
        # types are not application-webhook events and Discord rejects them.
        app_event_types = [
            t for t in event_types
            if t not in cls._interaction_event_types and t not in cls._gateway_event_types
        ]
        has_interactions = any(t in cls._interaction_event_types for t in event_types)

        payload: Dict[str, Any] = {
            "event_webhooks_url": cls._discord_event_webhook_url(),
            "event_webhooks_status": 2 if app_event_types else 1,
            "event_webhooks_types": sorted(set(app_event_types)),
        }
        if has_interactions:
            payload[
                "interactions_endpoint_url"
            ] = cls._discord_interactions_webhook_url()

        return await cls._discord_api_request(
            "PATCH",
            "/applications/@me",
            cls._bot_auth_header_from_credential(credential),
            json_data=payload,
        )

    @classmethod
    async def _resolve_tenant_id(cls, credential: Dict[str, Any]) -> Optional[str]:
        app = await cls._fetch_current_application(credential)
        return str(app.get("id")) if app.get("id") else None

    @classmethod
    def _discord_subscription_status(cls, event_types: List[str]) -> str:
        if len(event_types) == 1:
            return f"Active — listening for {event_types[0]}"
        return f"Active — listening for {len(event_types)} Discord events"

    @classmethod
    async def register_node_subscriptions(
        cls,
        pool,
        *,
        user_id: str,
        workflow_id,
        node_id: str,
        operation: Optional[str],
        credential_id: Optional[str],
        credential: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Discord registration core: subscription rows PLUS the provider-side
        event-webhook union across every node subscribed to this application
        (Discord delivers only the event types its app webhook is configured
        for). Rolls the rows back when the provider update fails."""
        from nodes.core.webhook_subscriptions import (
            delete_subscriptions,
            get_node_subscriptions,
            list_subscriptions_for_tenant,
            save_subscriptions,
            subscription_rows_match,
        )

        event_types = cls._trigger_event_map.get(operation or "", [])
        if not event_types:
            raise ValueError(f"Unknown trigger operation: {operation}")

        if operation in cls._gateway_trigger_operations:
            return await cls._register_gateway_subscriptions(
                pool,
                user_id=user_id,
                workflow_id=workflow_id,
                node_id=node_id,
                operation=operation,
                credential_id=credential_id,
                credential=credential,
                config=config,
            )

        app = await cls._fetch_current_application(credential)
        application_id = str(app["id"])
        verify_key = str(app["verify_key"])

        node_rows = await get_node_subscriptions(pool, str(workflow_id), node_id)
        if subscription_rows_match(
            node_rows,
            event_types=event_types,
            credential_id=credential_id,
            user_id=user_id,
            tenant_id=application_id,
        ) and all(r.get("verification_key") for r in node_rows):
            # Rows were written together with a successful provider update —
            # the union already includes this node's event types.
            return cls._discord_subscription_status(event_types)

        existing_rows = await list_subscriptions_for_tenant(
            pool, cls._app_provider, application_id
        )
        desired_event_types = {
            row["event_type"]
            for row in existing_rows
            if not (
                str(row["workflow_id"]) == str(workflow_id)
                and row["node_id"] == node_id
            )
        }
        desired_event_types.update(event_types)

        await save_subscriptions(
            pool,
            provider=cls._app_provider,
            tenant_id=application_id,
            user_id=user_id,
            workflow_id=str(workflow_id),
            node_id=node_id,
            credential_id=credential_id,
            event_types=event_types,
            verification_key=verify_key,
        )
        try:
            await cls._update_event_webhooks(
                credential, sorted(desired_event_types)
            )
        except Exception:
            await delete_subscriptions(pool, str(workflow_id), node_id)
            raise
        return cls._discord_subscription_status(event_types)

    @classmethod
    async def _register_gateway_subscriptions(
        cls,
        pool,
        *,
        user_id: str,
        workflow_id,
        node_id: str,
        operation: str,
        credential_id: Optional[str],
        credential: Dict[str, Any],
        config: Optional[Dict[str, Any]],
    ) -> str:
        """Message triggers: rows keyed by the install credential's GUILD and
        nothing provider-side — the listener already receives every message
        in every server the bot is in, and the rows are what make it forward
        this server's. No verify key: Gateway envelopes are HMAC-signed by
        NoClick's own listener, not Ed25519-signed by Discord."""
        from nodes.core.webhook_subscriptions import (
            get_node_subscriptions,
            save_subscriptions,
            subscription_rows_match,
        )

        guild_id = cls._install_guild_id(credential)
        if not guild_id:
            raise ValueError(
                "Channel message triggers listen through NoClick's bot, which "
                "must be installed into your server: connect Discord with "
                "'Install bot' instead of a bot token."
            )
        event_types = cls._trigger_event_map[operation]
        existing = await get_node_subscriptions(pool, str(workflow_id), node_id)
        if not subscription_rows_match(
            existing,
            event_types=event_types,
            credential_id=credential_id,
            user_id=user_id,
            tenant_id=guild_id,
        ):
            await save_subscriptions(
                pool,
                provider=cls._app_provider,
                tenant_id=guild_id,
                user_id=user_id,
                workflow_id=str(workflow_id),
                node_id=node_id,
                credential_id=credential_id,
                event_types=event_types,
            )
        return cls._gateway_status_line(operation, credential, config)

    @classmethod
    def _gateway_status_line(
        cls, operation: str, credential: Dict[str, Any], config: Optional[Dict[str, Any]]
    ) -> str:
        what = "mentions of the bot" if operation == "on_mention" else "messages"
        channel = (config or {}).get("channel_id")
        where = f"in channel {channel} (and its threads)" if channel else "in every channel"
        server = (credential or {}).get("guild_name") or cls._install_guild_id(credential)
        return f"Active — listening for {what} {where} of {server}"

    @classmethod
    async def cleanup_external_webhook(
        cls,
        pool,
        workflow_id: str,
        node_id: str,
        config: Dict[str, Any],
        credentials: Optional[Dict[str, Any]] = None,
    ) -> None:
        from nodes.core.webhook_subscriptions import (
            delete_subscriptions,
            get_node_subscriptions,
            list_subscriptions_for_tenant,
        )
        from utils.credential_loader import load_credential

        node_rows = await get_node_subscriptions(pool, str(workflow_id), node_id)
        if not node_rows:
            return
        if all(row.get("event_type") in cls._gateway_event_types for row in node_rows):
            # Gateway rows have no provider-side counterpart to reconcile.
            await delete_subscriptions(pool, str(workflow_id), node_id)
            return

        application_id = str(node_rows[0]["tenant_id"])
        remaining_rows = await list_subscriptions_for_tenant(
            pool, cls._app_provider, application_id
        )
        remaining_event_types = {
            row["event_type"]
            for row in remaining_rows
            if not (
                str(row["workflow_id"]) == str(workflow_id)
                and row["node_id"] == node_id
            )
        }

        credential = credentials
        if credential is None:
            first_row = node_rows[0]
            credential_id = first_row.get("credential_id")
            row_user_id = first_row.get("user_id")
            if credential_id and row_user_id:
                credential = await load_credential(
                    pool, str(row_user_id), str(credential_id)
                )
                if credential is not None:
                    credential = await cls.freshen_credential(
                        credential,
                        pool=pool,
                        user_id=str(row_user_id),
                        credential_id=str(credential_id),
                    )

        try:
            if credential is not None:
                await cls._update_event_webhooks(
                    credential, sorted(remaining_event_types)
                )
        finally:
            await delete_subscriptions(pool, str(workflow_id), node_id)

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        return cls._resolve_app_event_payload(payload, config)

    @classmethod
    def _resolve_gateway_payload(
        cls, payload: Dict[str, Any], operation: Optional[str]
    ) -> Dict[str, Any]:
        """A Gateway MESSAGE_CREATE envelope → the trigger's output: the fields
        a downstream node or an agent needs by name, the raw message under
        ``data``."""
        message = payload.get("d") if isinstance(payload.get("d"), dict) else {}
        author = message.get("author") if isinstance(message.get("author"), dict) else {}
        member = message.get("member") if isinstance(message.get("member"), dict) else {}
        reference = (
            message.get("message_reference")
            if isinstance(message.get("message_reference"), dict)
            else {}
        )
        bot_user_id = payload.get("bot_user_id")
        mentions = [m for m in (message.get("mentions") or []) if isinstance(m, dict)]
        attachments = [
            {
                "url": a.get("url"),
                "filename": a.get("filename"),
                "content_type": a.get("content_type"),
                "size": a.get("size"),
            }
            for a in (message.get("attachments") or [])
            if isinstance(a, dict) and a.get("url")
        ]
        guild_id = message.get("guild_id")
        channel_id = message.get("channel_id")
        message_id = message.get("id")
        return {
            "type": "discord",
            "action": operation,
            "status": "success",
            "event_type": operation,
            "message_id": message_id,
            "content": message.get("content") or "",
            "channel_id": channel_id,
            "guild_id": guild_id,
            "author_id": author.get("id"),
            "author_username": author.get("username"),
            "author_display_name": (
                member.get("nick") or author.get("global_name") or author.get("username")
            ),
            "author_is_bot": bool(author.get("bot")),
            "guild_name": payload.get("guild_name"),
            "channel_name": payload.get("channel_name"),
            # Set for a message in a thread: the channel the thread lives in.
            "parent_channel_id": payload.get("parent_channel_id"),
            "parent_channel_name": payload.get("parent_channel_name"),
            "mentions_bot": bool(bot_user_id) and any(
                str(m.get("id")) == str(bot_user_id) for m in mentions
            ),
            "mentioned_user_ids": [str(m.get("id")) for m in mentions if m.get("id")],
            "mentions": [
                {
                    "id": str(m.get("id")),
                    "username": m.get("username"),
                    "display_name": m.get("global_name") or m.get("username"),
                }
                for m in mentions
                if m.get("id")
            ],
            "attachments": attachments,
            "reply_to_message_id": reference.get("message_id"),
            "message_url": (
                f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
                if guild_id and channel_id and message_id
                else None
            ),
            "sent_at": message.get("timestamp"),
            "data": payload,
            "timestamp": time.time(),
        }

    @classmethod
    def _resolve_app_event_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        operation = (config or {}).get("operation")
        if isinstance(payload, dict) and payload.get("source") == "gateway":
            return cls._resolve_gateway_payload(payload, operation)
        body_type = payload.get("type") if isinstance(payload, dict) else None

        # Interaction payload (slash command: body type=2)
        if body_type == 2:
            interaction_data = payload.get("data") or {}
            member = payload.get("member") or {}
            user = member.get("user") or payload.get("user") or {}
            options = interaction_data.get("options") or []
            return {
                "type": "discord",
                "action": operation,
                "status": "success",
                "event_type": "on_slash_command",
                "command_name": interaction_data.get("name"),
                "application_id": payload.get("application_id"),
                "guild_id": payload.get("guild_id"),
                "channel_id": payload.get("channel_id"),
                "user_id": user.get("id"),
                "username": user.get("username"),
                "options": {
                    opt["name"]: opt.get("value") for opt in options if "name" in opt
                },
                "interaction_token": payload.get("token"),
                "data": payload,
                "timestamp": time.time(),
            }

        # Application event payload (type=1 with `event` key)
        event = payload.get("event") if isinstance(payload, dict) else None
        event_data = event.get("data") if isinstance(event, dict) else None
        resolved: Dict[str, Any] = {
            "type": "discord",
            "action": operation,
            "status": "success",
            "event_type": event.get("type") if isinstance(event, dict) else None,
            "application_id": payload.get("application_id")
            if isinstance(payload, dict)
            else None,
            "data": payload,
            "timestamp": time.time(),
        }
        # Surface useful fields for message / member events
        if isinstance(event_data, dict):
            if event_data.get("content") is not None:
                resolved["message_content"] = event_data.get("content")
                resolved["channel_id"] = event_data.get("channel_id")
                author = event_data.get("author") or {}
                resolved["author_id"] = author.get("id")
                resolved["author_username"] = author.get("username")
            if event_data.get("user") is not None:
                member_user = event_data.get("user") or {}
                resolved["user_id"] = member_user.get("id")
                resolved["username"] = member_user.get("username")
                resolved["guild_id"] = event_data.get("guild_id")
        return resolved

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Discord slash command or channel message → the agent's user turn.
        The channel id is both the conversation key (one conversation per
        channel — a thread IS a channel, so threads get their own; Discord
        channel snowflakes are globally unique, so guild scoping is redundant)
        and the reply target the send tools accept verbatim. Non-conversational
        events (entitlement, application authorized/deauthorized) fall through to
        the base JSON delivery."""
        if not isinstance(output, dict):
            return super().resolve_agent_event(output)
        if output.get("source") == "gateway":
            # A raw listener envelope reads as the message it carries.
            output = cls._resolve_gateway_payload(output, "on_message")
        channel_id = str(output.get("channel_id") or "").strip()
        event_type = output.get("event_type")
        if event_type in cls._gateway_trigger_operations and channel_id:
            return cls._message_agent_event(output, channel_id)
        if event_type != "on_slash_command" or not channel_id:
            return super().resolve_agent_event(output)
        who = output.get("username") or output.get("user_id") or "a user"
        command = output.get("command_name") or "unknown"
        options = output.get("options")
        args = (
            "\nArguments: " + ", ".join(f"{k}={v}" for k, v in options.items())
            if isinstance(options, dict) and options
            else ""
        )
        guild = f" (guild {output['guild_id']})" if output.get("guild_id") else ""
        text = (
            f"Discord slash command /{command} from {who} in channel {channel_id}"
            f"{guild}:{args}\n\n"
            f"To respond, use send_message_to_channel with channel_id={channel_id} "
            f"(pass this exactly)."
        )
        return {"text": text, "conversation_key": channel_id}

    @classmethod
    def _message_agent_event(cls, output: Dict[str, Any], channel_id: str) -> Dict[str, Any]:
        who = (
            output.get("author_display_name")
            or output.get("author_username")
            or output.get("author_id")
            or "someone"
        )
        bot_user_id = (output.get("data") or {}).get("bot_user_id") if isinstance(output.get("data"), dict) else None
        # Names for people, ids for tools: the mention that woke the agent is
        # noise in its own turn, other mentions read as @name.
        content = humanize_discord_mentions(
            str(output.get("content") or ""), output.get("mentions"), drop_user_id=bot_user_id
        )
        where = f"#{output['channel_name']}" if output.get("channel_name") else f"channel {channel_id}"
        parent_id = str(output.get("parent_channel_id") or "").strip()
        if parent_id:
            # A thread: its own conversation, named after where it was opened.
            parent = f"#{output['parent_channel_name']}" if output.get("parent_channel_name") else f"channel {parent_id}"
            thread = f"thread “{output['channel_name']}”" if output.get("channel_name") else f"thread {channel_id}"
            where = f"{thread} under {parent}"
        if output.get("guild_name"):
            server = f" ({output['guild_name']})"
        elif output.get("guild_id"):
            server = f" (server {output['guild_id']})"
        else:
            server = ""
        lines = [f"Discord message from {who} in {where}{server}:", content or "(no text)"]
        attachments = [a.get("url") for a in output.get("attachments") or [] if a.get("url")]
        if attachments:
            lines.append("Attachments: " + ", ".join(attachments))
        if output.get("reply_to_message_id"):
            lines.append(f"(a reply to message {output['reply_to_message_id']})")
        if parent_id:
            lines.append(
                f"(a thread in {parent}; earlier messages in it: list_channel_messages with channel_id={channel_id})"
            )
        lines.append("")
        lines.append(
            f"To respond, use send_message_to_channel with channel_id={channel_id} "
            f"(pass this exactly); message_id={output.get('message_id')} if you want to reply to it."
        )
        return {"text": "\n".join(lines), "conversation_key": channel_id}

    async def _trigger_on_discord_event(
        self, config: _DiscordEventTriggerBase, credentials
    ) -> Dict[str, Any]:
        node_config = (self.node_data or {}).get("config", {})
        trigger_payload = node_config.get("_triggerPayload")
        if trigger_payload:
            return self.resolve_trigger_payload(
                trigger_payload, {"operation": config.operation}
            )
        waiting_for = (
            "a channel message"
            if config.operation in self._gateway_trigger_operations
            else "an event webhook"
        )
        return {
            "type": "discord",
            "action": config.operation,
            "status": "waiting",
            "message": f"Discord trigger is registered and waiting for {waiting_for}",
            "event_types": self._trigger_event_map.get(config.operation, []),
            "timestamp": time.time(),
        }

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Discord operation based on config"""
        start_time = time.time()

        node_config = self.config
        if not node_config or not isinstance(node_config, DiscordNodeConfig):
            raise ValueError("Configuration is required")

        config = node_config.config
        credentials = node_config.credentials

        # Webhook operations don't require credentials
        if isinstance(config, DiscordExecuteWebhookConfig):
            result = await self._execute_webhook(config)
        else:
            # All other operations require credentials
            if not credentials:
                raise ValueError(
                    "Credentials required. Connect a Discord account or add a bot token."
                )

            # Get the appropriate auth header
            if isinstance(credentials, DiscordBotInstallCredential):
                platform_token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
                if not platform_token:
                    raise ValueError(
                        "DISCORD_BOT_TOKEN environment variable is required for bot install credentials."
                    )
                auth_header = self._format_bot_auth_header(platform_token)
                logger.info(
                    "[DiscordNode] Using platform bot token (bot install credential)"
                )
            else:
                auth_header = self._format_bot_auth_header(credentials.bot_token)
                logger.info(
                    f"[DiscordNode] Using bot token (length: {len(credentials.bot_token.strip())})"
                )

            # Route to appropriate handler
            if isinstance(config, _DiscordEventTriggerBase):
                result = await self._trigger_on_discord_event(config, credentials)
            # Message Operations
            elif isinstance(config, DiscordSendMessageConfig):
                result = await self._send_message(config, auth_header)
            elif isinstance(config, DiscordSendEmbedConfig):
                result = await self._send_embed(config, auth_header)
            elif isinstance(config, DiscordGetMessageConfig):
                result = await self._get_message(config, auth_header)
            elif isinstance(config, DiscordGetMessagesConfig):
                result = await self._get_messages(config, auth_header)
            elif isinstance(config, DiscordEditMessageConfig):
                result = await self._edit_message(config, auth_header)
            elif isinstance(config, DiscordDeleteMessageConfig):
                result = await self._delete_message(config, auth_header)
            elif isinstance(config, DiscordCrosspostMessageConfig):
                result = await self._crosspost_message(config, auth_header)
            elif isinstance(config, DiscordPinMessageConfig):
                result = await self._pin_message(config, auth_header)
            elif isinstance(config, DiscordUnpinMessageConfig):
                result = await self._unpin_message(config, auth_header)
            elif isinstance(config, DiscordGetPinnedMessagesConfig):
                result = await self._get_pinned_messages(config, auth_header)
            elif isinstance(config, DiscordBulkDeleteMessagesConfig):
                result = await self._bulk_delete_messages(config, auth_header)
            # Reaction Operations
            elif isinstance(config, DiscordCreateReactionConfig):
                result = await self._create_reaction(config, auth_header)
            elif isinstance(config, DiscordDeleteReactionConfig):
                result = await self._delete_reaction(config, auth_header)
            elif isinstance(config, DiscordGetReactionsConfig):
                result = await self._get_reactions(config, auth_header)
            elif isinstance(config, DiscordDeleteAllReactionsConfig):
                result = await self._delete_all_reactions(config, auth_header)
            elif isinstance(config, DiscordDeleteAllReactionsForEmojiConfig):
                result = await self._delete_all_reactions_for_emoji(config, auth_header)
            # Channel Operations
            elif isinstance(config, DiscordGetChannelConfig):
                result = await self._get_channel(config, auth_header)
            elif isinstance(config, DiscordCreateChannelConfig):
                result = await self._create_channel(config, auth_header)
            elif isinstance(config, DiscordModifyChannelConfig):
                result = await self._modify_channel(config, auth_header)
            elif isinstance(config, DiscordDeleteChannelConfig):
                result = await self._delete_channel(config, auth_header)
            elif isinstance(config, DiscordTriggerTypingConfig):
                result = await self._trigger_typing(config, auth_header)
            elif isinstance(config, DiscordEditChannelPermissionsConfig):
                result = await self._edit_channel_permissions(config, auth_header)
            elif isinstance(config, DiscordListChannelsConfig):
                result = await self._list_channels(config, auth_header)
            # Thread Operations
            elif isinstance(config, DiscordStartThreadFromMessageConfig):
                result = await self._start_thread_from_message(config, auth_header)
            elif isinstance(config, DiscordStartThreadConfig):
                result = await self._start_thread(config, auth_header)
            elif isinstance(config, DiscordJoinThreadConfig):
                result = await self._join_thread(config, auth_header)
            elif isinstance(config, DiscordLeaveThreadConfig):
                result = await self._leave_thread(config, auth_header)
            elif isinstance(config, DiscordAddThreadMemberConfig):
                result = await self._add_thread_member(config, auth_header)
            elif isinstance(config, DiscordRemoveThreadMemberConfig):
                result = await self._remove_thread_member(config, auth_header)
            elif isinstance(config, DiscordListThreadMembersConfig):
                result = await self._list_thread_members(config, auth_header)
            elif isinstance(config, DiscordListActiveThreadsConfig):
                result = await self._list_active_threads(config, auth_header)
            # Guild Operations
            elif isinstance(config, DiscordListGuildsConfig):
                result = await self._list_guilds(config, auth_header, credentials)
            elif isinstance(config, DiscordGetGuildConfig):
                result = await self._get_guild(config, auth_header)
            elif isinstance(config, DiscordModifyGuildConfig):
                result = await self._modify_guild(config, auth_header)
            elif isinstance(config, DiscordGetGuildPreviewConfig):
                result = await self._get_guild_preview(config, auth_header)
            elif isinstance(config, DiscordGetGuildVanityUrlConfig):
                result = await self._get_guild_vanity_url(config, auth_header)
            elif isinstance(config, DiscordGetGuildPruneCountConfig):
                result = await self._get_guild_prune_count(config, auth_header)
            elif isinstance(config, DiscordBeginGuildPruneConfig):
                result = await self._begin_guild_prune(config, auth_header)
            # User/Member Operations
            elif isinstance(config, DiscordGetUserConfig):
                result = await self._get_user(auth_header)
            elif isinstance(config, DiscordGetGuildMembersConfig):
                result = await self._get_guild_members(config, auth_header)
            elif isinstance(config, DiscordGetGuildMemberConfig):
                result = await self._get_guild_member(config, auth_header)
            elif isinstance(config, DiscordModifyGuildMemberConfig):
                result = await self._modify_guild_member(config, auth_header)
            elif isinstance(config, DiscordKickMemberConfig):
                result = await self._kick_member(config, auth_header)
            elif isinstance(config, DiscordBanMemberConfig):
                result = await self._ban_member(config, auth_header)
            elif isinstance(config, DiscordUnbanMemberConfig):
                result = await self._unban_member(config, auth_header)
            elif isinstance(config, DiscordGetGuildBansConfig):
                result = await self._get_guild_bans(config, auth_header)
            elif isinstance(config, DiscordGetGuildBanConfig):
                result = await self._get_guild_ban(config, auth_header)
            # Role Operations
            elif isinstance(config, DiscordGetGuildRolesConfig):
                result = await self._get_guild_roles(config, auth_header)
            elif isinstance(config, DiscordCreateRoleConfig):
                result = await self._create_role(config, auth_header)
            elif isinstance(config, DiscordModifyRoleConfig):
                result = await self._modify_role(config, auth_header)
            elif isinstance(config, DiscordDeleteRoleConfig):
                result = await self._delete_role(config, auth_header)
            elif isinstance(config, DiscordAddRoleToMemberConfig):
                result = await self._add_role_to_member(config, auth_header)
            elif isinstance(config, DiscordRemoveRoleFromMemberConfig):
                result = await self._remove_role_from_member(config, auth_header)
            # Invite Operations
            elif isinstance(config, DiscordGetInviteConfig):
                result = await self._get_invite(config, auth_header)
            elif isinstance(config, DiscordDeleteInviteConfig):
                result = await self._delete_invite(config, auth_header)
            elif isinstance(config, DiscordGetChannelInvitesConfig):
                result = await self._get_channel_invites(config, auth_header)
            elif isinstance(config, DiscordCreateChannelInviteConfig):
                result = await self._create_channel_invite(config, auth_header)
            elif isinstance(config, DiscordGetGuildInvitesConfig):
                result = await self._get_guild_invites(config, auth_header)
            # Webhook Operations
            elif isinstance(config, DiscordGetChannelWebhooksConfig):
                result = await self._get_channel_webhooks(config, auth_header)
            elif isinstance(config, DiscordGetGuildWebhooksConfig):
                result = await self._get_guild_webhooks(config, auth_header)
            elif isinstance(config, DiscordGetWebhookConfig):
                result = await self._get_webhook(config, auth_header)
            elif isinstance(config, DiscordCreateWebhookConfig):
                result = await self._create_webhook(config, auth_header)
            elif isinstance(config, DiscordModifyWebhookConfig):
                result = await self._modify_webhook(config, auth_header)
            elif isinstance(config, DiscordDeleteWebhookConfig):
                result = await self._delete_webhook(config, auth_header)
            # Emoji Operations
            elif isinstance(config, DiscordListGuildEmojisConfig):
                result = await self._list_guild_emojis(config, auth_header)
            elif isinstance(config, DiscordGetGuildEmojiConfig):
                result = await self._get_guild_emoji(config, auth_header)
            elif isinstance(config, DiscordCreateGuildEmojiConfig):
                result = await self._create_guild_emoji(config, auth_header)
            elif isinstance(config, DiscordModifyGuildEmojiConfig):
                result = await self._modify_guild_emoji(config, auth_header)
            elif isinstance(config, DiscordDeleteGuildEmojiConfig):
                result = await self._delete_guild_emoji(config, auth_header)
            # Sticker Operations
            elif isinstance(config, DiscordListGuildStickersConfig):
                result = await self._list_guild_stickers(config, auth_header)
            elif isinstance(config, DiscordGetGuildStickerConfig):
                result = await self._get_guild_sticker(config, auth_header)
            elif isinstance(config, DiscordModifyGuildStickerConfig):
                result = await self._modify_guild_sticker(config, auth_header)
            elif isinstance(config, DiscordDeleteGuildStickerConfig):
                result = await self._delete_guild_sticker(config, auth_header)
            # Scheduled Events
            elif isinstance(config, DiscordListScheduledEventsConfig):
                result = await self._list_scheduled_events(config, auth_header)
            elif isinstance(config, DiscordGetScheduledEventConfig):
                result = await self._get_scheduled_event(config, auth_header)
            elif isinstance(config, DiscordCreateScheduledEventConfig):
                result = await self._create_scheduled_event(config, auth_header)
            elif isinstance(config, DiscordModifyScheduledEventConfig):
                result = await self._modify_scheduled_event(config, auth_header)
            elif isinstance(config, DiscordDeleteScheduledEventConfig):
                result = await self._delete_scheduled_event(config, auth_header)
            elif isinstance(config, DiscordGetScheduledEventUsersConfig):
                result = await self._get_scheduled_event_users(config, auth_header)
            # Auto Moderation
            elif isinstance(config, DiscordListAutoModRulesConfig):
                result = await self._list_auto_mod_rules(config, auth_header)
            elif isinstance(config, DiscordGetAutoModRuleConfig):
                result = await self._get_auto_mod_rule(config, auth_header)
            elif isinstance(config, DiscordCreateAutoModRuleConfig):
                result = await self._create_auto_mod_rule(config, auth_header)
            elif isinstance(config, DiscordModifyAutoModRuleConfig):
                result = await self._modify_auto_mod_rule(config, auth_header)
            elif isinstance(config, DiscordDeleteAutoModRuleConfig):
                result = await self._delete_auto_mod_rule(config, auth_header)
            # Audit Log
            elif isinstance(config, DiscordGetAuditLogConfig):
                result = await self._get_audit_log(config, auth_header)
            # Stage Instance
            elif isinstance(config, DiscordCreateStageInstanceConfig):
                result = await self._create_stage_instance(config, auth_header)
            elif isinstance(config, DiscordGetStageInstanceConfig):
                result = await self._get_stage_instance(config, auth_header)
            elif isinstance(config, DiscordModifyStageInstanceConfig):
                result = await self._modify_stage_instance(config, auth_header)
            elif isinstance(config, DiscordDeleteStageInstanceConfig):
                result = await self._delete_stage_instance(config, auth_header)
            # Voice
            elif isinstance(config, DiscordListVoiceRegionsConfig):
                result = await self._list_voice_regions(auth_header)
            # Poll
            elif isinstance(config, DiscordGetPollAnswerVotersConfig):
                result = await self._get_poll_answer_voters(config, auth_header)
            elif isinstance(config, DiscordEndPollConfig):
                result = await self._end_poll(config, auth_header)
            # Soundboard Operations
            elif isinstance(config, DiscordSendSoundboardSoundConfig):
                result = await self._send_soundboard_sound(config, auth_header)
            elif isinstance(config, DiscordListDefaultSoundboardSoundsConfig):
                result = await self._list_default_soundboard_sounds(auth_header)
            elif isinstance(config, DiscordListGuildSoundboardSoundsConfig):
                result = await self._list_guild_soundboard_sounds(config, auth_header)
            elif isinstance(config, DiscordGetGuildSoundboardSoundConfig):
                result = await self._get_guild_soundboard_sound(config, auth_header)
            elif isinstance(config, DiscordCreateGuildSoundboardSoundConfig):
                result = await self._create_guild_soundboard_sound(config, auth_header)
            elif isinstance(config, DiscordModifyGuildSoundboardSoundConfig):
                result = await self._modify_guild_soundboard_sound(config, auth_header)
            elif isinstance(config, DiscordDeleteGuildSoundboardSoundConfig):
                result = await self._delete_guild_soundboard_sound(config, auth_header)
            # Guild Template Operations
            elif isinstance(config, DiscordGetGuildTemplateConfig):
                result = await self._get_guild_template(config, auth_header)
            elif isinstance(config, DiscordCreateGuildFromTemplateConfig):
                result = await self._create_guild_from_template(config, auth_header)
            elif isinstance(config, DiscordGetGuildTemplatesConfig):
                result = await self._get_guild_templates(config, auth_header)
            elif isinstance(config, DiscordCreateGuildTemplateConfig):
                result = await self._create_guild_template(config, auth_header)
            elif isinstance(config, DiscordSyncGuildTemplateConfig):
                result = await self._sync_guild_template(config, auth_header)
            elif isinstance(config, DiscordModifyGuildTemplateConfig):
                result = await self._modify_guild_template(config, auth_header)
            elif isinstance(config, DiscordDeleteGuildTemplateConfig):
                result = await self._delete_guild_template(config, auth_header)
            # Guild Onboarding
            elif isinstance(config, DiscordGetGuildOnboardingConfig):
                result = await self._get_guild_onboarding(config, auth_header)
            elif isinstance(config, DiscordModifyGuildOnboardingConfig):
                result = await self._modify_guild_onboarding(config, auth_header)
            # DM/Group DM Operations
            elif isinstance(config, DiscordCreateDMConfig):
                result = await self._create_dm(config, auth_header)
            elif isinstance(config, DiscordCreateGroupDMConfig):
                result = await self._create_group_dm(config, auth_header)
            # Application Commands Operations
            elif isinstance(config, DiscordGetGlobalApplicationCommandsConfig):
                result = await self._get_global_application_commands(
                    config, auth_header
                )
            elif isinstance(config, DiscordCreateGlobalApplicationCommandConfig):
                result = await self._create_global_application_command(
                    config, auth_header
                )
            elif isinstance(config, DiscordGetGlobalApplicationCommandConfig):
                result = await self._get_global_application_command(config, auth_header)
            elif isinstance(config, DiscordEditGlobalApplicationCommandConfig):
                result = await self._edit_global_application_command(
                    config, auth_header
                )
            elif isinstance(config, DiscordDeleteGlobalApplicationCommandConfig):
                result = await self._delete_global_application_command(
                    config, auth_header
                )
            elif isinstance(config, DiscordGetGuildApplicationCommandsConfig):
                result = await self._get_guild_application_commands(config, auth_header)
            elif isinstance(config, DiscordCreateGuildApplicationCommandConfig):
                result = await self._create_guild_application_command(
                    config, auth_header
                )
            elif isinstance(config, DiscordGetGuildApplicationCommandConfig):
                result = await self._get_guild_application_command(config, auth_header)
            elif isinstance(config, DiscordEditGuildApplicationCommandConfig):
                result = await self._edit_guild_application_command(config, auth_header)
            elif isinstance(config, DiscordDeleteGuildApplicationCommandConfig):
                result = await self._delete_guild_application_command(
                    config, auth_header
                )
            # SKUs & Entitlements (Monetization)
            elif isinstance(config, DiscordListSKUsConfig):
                result = await self._list_skus(config, auth_header)
            elif isinstance(config, DiscordListEntitlementsConfig):
                result = await self._list_entitlements(config, auth_header)
            elif isinstance(config, DiscordCreateTestEntitlementConfig):
                result = await self._create_test_entitlement(config, auth_header)
            elif isinstance(config, DiscordDeleteTestEntitlementConfig):
                result = await self._delete_test_entitlement(config, auth_header)
            elif isinstance(config, DiscordConsumeEntitlementConfig):
                result = await self._consume_entitlement(config, auth_header)
            # Guild Widget
            elif isinstance(config, DiscordGetGuildWidgetConfig):
                result = await self._get_guild_widget(config, auth_header)
            elif isinstance(config, DiscordModifyGuildWidgetConfig):
                result = await self._modify_guild_widget(config, auth_header)
            # Guild Welcome Screen
            elif isinstance(config, DiscordGetGuildWelcomeScreenConfig):
                result = await self._get_guild_welcome_screen(config, auth_header)
            elif isinstance(config, DiscordModifyGuildWelcomeScreenConfig):
                result = await self._modify_guild_welcome_screen(config, auth_header)
            # Voice State Operations
            elif isinstance(config, DiscordModifyCurrentUserVoiceStateConfig):
                result = await self._modify_current_user_voice_state(
                    config, auth_header
                )
            elif isinstance(config, DiscordModifyUserVoiceStateConfig):
                result = await self._modify_user_voice_state(config, auth_header)
            # Additional User Operations
            elif isinstance(config, DiscordGetCurrentUserGuildsConfig):
                result = await self._get_current_user_guilds(config, auth_header)
            elif isinstance(config, DiscordLeaveGuildConfig):
                result = await self._leave_guild(config, auth_header)
            elif isinstance(config, DiscordGetUserConnectionsConfig):
                result = await self._get_user_connections(auth_header)
            # Guild Integration Operations
            elif isinstance(config, DiscordGetGuildIntegrationsConfig):
                result = await self._get_guild_integrations(config, auth_header)
            elif isinstance(config, DiscordDeleteGuildIntegrationConfig):
                result = await self._delete_guild_integration(config, auth_header)
            else:
                raise ValueError(f"Unknown action type: {type(config).__name__}")

        # Add timing info
        result["timing_ms"] = int((time.time() - start_time) * 1000)

        await self.emit(result)
        return result

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.discord_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="discord",
        )

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        auth_header: str,
        json_data: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Make an authenticated request to Discord API."""
        return await self._discord_api_request(
            method,
            endpoint,
            auth_header,
            json_data=json_data,
            params=params,
        )

    async def _send_message(
        self, config: DiscordSendMessageConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Send a message to a channel"""
        payload = {
            "content": config.content,
            "tts": config.tts or False,
        }

        result = await self._make_request(
            "POST",
            f"/channels/{config.channel_id}/messages",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "send_message_to_channel",
            "message_id": result.get("id"),
            "channel_id": config.channel_id,
            "content": config.content,
            "timestamp": result.get("timestamp"),
            "author": result.get("author", {}),
        }

    async def _send_embed(
        self, config: DiscordSendEmbedConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Send an embed message to a channel"""
        embed = {}
        if config.title:
            embed["title"] = config.title
        if config.description:
            embed["description"] = config.description
        if config.color:
            embed["color"] = config.color
        if config.url:
            embed["url"] = config.url
        if config.footer_text:
            embed["footer"] = {"text": config.footer_text}

        payload = {"embeds": [embed]}

        result = await self._make_request(
            "POST",
            f"/channels/{config.channel_id}/messages",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "send_embed_message_to_channel",
            "message_id": result.get("id"),
            "channel_id": config.channel_id,
            "embed": embed,
            "timestamp": result.get("timestamp"),
        }

    async def _get_channel(
        self, config: DiscordGetChannelConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get channel information"""
        result = await self._make_request(
            "GET",
            f"/channels/{config.channel_id}",
            auth_header,
        )

        return {
            "action": "get_channel_info",
            "channel": result,
        }

    async def _list_guilds(
        self,
        config: DiscordListGuildsConfig,
        auth_header: str,
        credentials: DiscordCredential,
    ) -> Dict[str, Any]:
        """List guilds the user/bot is in"""
        # For OAuth users, use /users/@me/guilds
        # For bots, this endpoint also works
        params = {"limit": min(config.limit or 100, 200)}

        result = await self._make_request(
            "GET",
            "/users/@me/guilds",
            auth_header,
            params=params,
        )

        return {
            "action": "list_user_guilds",
            "guilds": result,
            "count": len(result),
        }

    async def _get_guild(
        self, config: DiscordGetGuildConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get guild information"""
        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}",
            auth_header,
        )

        return {
            "action": "get_guild_info",
            "guild": result,
        }

    async def _list_channels(
        self, config: DiscordListChannelsConfig, auth_header: str
    ) -> Dict[str, Any]:
        """List all channels in a guild"""
        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}/channels",
            auth_header,
        )

        return {
            "action": "list_guild_channels",
            "channels": result,
            "count": len(result),
        }

    async def _get_user(self, auth_header: str) -> Dict[str, Any]:
        """Get authenticated user information"""
        result = await self._make_request(
            "GET",
            "/users/@me",
            auth_header,
        )

        return {
            "action": "get_authenticated_user_info",
            "user": result,
        }

    async def _get_messages(
        self, config: DiscordGetMessagesConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get messages from a channel"""
        params = {"limit": min(config.limit or 50, 100)}

        result = await self._make_request(
            "GET",
            f"/channels/{config.channel_id}/messages",
            auth_header,
            params=params,
        )

        return {
            "action": "list_channel_messages",
            "channel_id": config.channel_id,
            "messages": result,
            "count": len(result),
        }

    async def _create_reaction(
        self, config: DiscordCreateReactionConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Add a reaction to a message"""
        # URL-encode the emoji
        from urllib.parse import quote

        emoji_encoded = quote(config.emoji, safe="")

        await self._make_request(
            "PUT",
            f"/channels/{config.channel_id}/messages/{config.message_id}/reactions/{emoji_encoded}/@me",
            auth_header,
        )

        return {
            "action": "add_reaction_to_message",
            "channel_id": config.channel_id,
            "message_id": config.message_id,
            "emoji": config.emoji,
            "success": True,
        }

    async def _execute_webhook(
        self, config: DiscordExecuteWebhookConfig
    ) -> Dict[str, Any]:
        """Execute a Discord webhook (no auth required)"""
        payload: Dict[str, Any] = {}

        if config.content:
            payload["content"] = config.content
        if config.username:
            payload["username"] = config.username
        if config.avatar_url:
            payload["avatar_url"] = config.avatar_url

        # Build embed if any embed fields are provided
        if config.embed_title or config.embed_description or config.embed_color:
            embed = {}
            if config.embed_title:
                embed["title"] = config.embed_title
            if config.embed_description:
                embed["description"] = config.embed_description
            if config.embed_color:
                embed["color"] = config.embed_color
            payload["embeds"] = [embed]

        async with guarded_async_client() as client:
            response = await client.post(
                config.webhook_url,
                json=payload,
                timeout=30.0,
            )

            if response.status_code >= 400:
                error_text = response.text
                raise ValueError(
                    f"Webhook error ({response.status_code}): {error_text}"
                )

            return {
                "action": "execute_webhook_send_message",
                "webhook_url": config.webhook_url[:50] + "...",  # Truncate for security
                "success": True,
                "status_code": response.status_code,
            }

    async def _edit_message(
        self, config: DiscordEditMessageConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Edit an existing message"""
        payload = {}
        if config.content is not None:
            payload["content"] = config.content

        result = await self._make_request(
            "PATCH",
            f"/channels/{config.channel_id}/messages/{config.message_id}",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "edit_message_content",
            "channel_id": config.channel_id,
            "message_id": config.message_id,
            "message": result,
        }

    async def _delete_message(
        self, config: DiscordDeleteMessageConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Delete a message from a channel"""
        await self._make_request(
            "DELETE",
            f"/channels/{config.channel_id}/messages/{config.message_id}",
            auth_header,
        )

        return {
            "action": "delete_message_from_channel",
            "channel_id": config.channel_id,
            "message_id": config.message_id,
            "success": True,
        }

    async def _pin_message(
        self, config: DiscordPinMessageConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Pin a message in a channel"""
        await self._make_request(
            "PUT",
            f"/channels/{config.channel_id}/pins/{config.message_id}",
            auth_header,
        )

        return {
            "action": "pin_message_in_channel",
            "channel_id": config.channel_id,
            "message_id": config.message_id,
            "success": True,
        }

    async def _unpin_message(
        self, config: DiscordUnpinMessageConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Unpin a message in a channel"""
        await self._make_request(
            "DELETE",
            f"/channels/{config.channel_id}/pins/{config.message_id}",
            auth_header,
        )

        return {
            "action": "unpin_message_from_channel",
            "channel_id": config.channel_id,
            "message_id": config.message_id,
            "success": True,
        }

    async def _get_pinned_messages(
        self, config: DiscordGetPinnedMessagesConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get pinned messages in a channel"""
        result = await self._make_request(
            "GET",
            f"/channels/{config.channel_id}/pins",
            auth_header,
        )

        return {
            "action": "list_pinned_messages_in_channel",
            "channel_id": config.channel_id,
            "messages": result,
            "count": len(result),
        }

    async def _get_guild_members(
        self, config: DiscordGetGuildMembersConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get members of a guild"""
        params = {"limit": min(config.limit or 100, 1000)}

        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}/members",
            auth_header,
            params=params,
        )

        return {
            "action": "list_guild_members",
            "guild_id": config.guild_id,
            "members": result,
            "count": len(result),
        }

    async def _get_guild_member(
        self, config: DiscordGetGuildMemberConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get a specific guild member"""
        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}/members/{config.user_id}",
            auth_header,
        )

        return {
            "action": "get_guild_member_info",
            "guild_id": config.guild_id,
            "user_id": config.user_id,
            "member": result,
        }

    async def _modify_guild_member(
        self, config: DiscordModifyGuildMemberConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Modify a guild member (nickname, roles)"""
        payload = {}
        if config.nick is not None:
            payload["nick"] = config.nick
        if config.roles is not None:
            payload["roles"] = config.roles

        result = await self._make_request(
            "PATCH",
            f"/guilds/{config.guild_id}/members/{config.user_id}",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "update_guild_member_info",
            "guild_id": config.guild_id,
            "user_id": config.user_id,
            "member": result,
        }

    async def _get_guild_roles(
        self, config: DiscordGetGuildRolesConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get all roles in a guild"""
        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}/roles",
            auth_header,
        )

        return {
            "action": "list_guild_roles",
            "guild_id": config.guild_id,
            "roles": result,
            "count": len(result),
        }

    async def _kick_member(
        self, config: DiscordKickMemberConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Kick a member from a guild"""
        await self._make_request(
            "DELETE",
            f"/guilds/{config.guild_id}/members/{config.user_id}",
            auth_header,
        )

        return {
            "action": "kick_member_from_guild",
            "guild_id": config.guild_id,
            "user_id": config.user_id,
            "success": True,
        }

    async def _ban_member(
        self, config: DiscordBanMemberConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Ban a member from a guild"""
        payload = {}
        if config.delete_message_days:
            payload["delete_message_days"] = min(config.delete_message_days, 7)

        await self._make_request(
            "PUT",
            f"/guilds/{config.guild_id}/bans/{config.user_id}",
            auth_header,
            json_data=payload if payload else None,
        )

        return {
            "action": "ban_member_from_guild",
            "guild_id": config.guild_id,
            "user_id": config.user_id,
            "success": True,
        }

    async def _unban_member(
        self, config: DiscordUnbanMemberConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Unban a member from a guild"""
        await self._make_request(
            "DELETE",
            f"/guilds/{config.guild_id}/bans/{config.user_id}",
            auth_header,
        )

        return {
            "action": "unban_member_from_guild",
            "guild_id": config.guild_id,
            "user_id": config.user_id,
            "success": True,
        }

    async def _delete_reaction(
        self, config: DiscordDeleteReactionConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Remove a reaction from a message"""
        from urllib.parse import quote

        emoji_encoded = quote(config.emoji, safe="")

        await self._make_request(
            "DELETE",
            f"/channels/{config.channel_id}/messages/{config.message_id}/reactions/{emoji_encoded}/@me",
            auth_header,
        )

        return {
            "action": "remove_reaction_from_message",
            "channel_id": config.channel_id,
            "message_id": config.message_id,
            "emoji": config.emoji,
            "success": True,
        }

    # ============================================================================
    # Soundboard Handler Methods
    # ============================================================================

    async def _send_soundboard_sound(
        self, config: DiscordSendSoundboardSoundConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Play a soundboard sound in a voice channel"""
        payload = {"sound_id": config.sound_id}
        if config.source_guild_id:
            payload["source_guild_id"] = config.source_guild_id

        await self._make_request(
            "POST",
            f"/channels/{config.channel_id}/send-soundboard-sound",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "play_soundboard_sound_in_voice_channel",
            "channel_id": config.channel_id,
            "sound_id": config.sound_id,
            "success": True,
        }

    async def _list_default_soundboard_sounds(self, auth_header: str) -> Dict[str, Any]:
        """List default soundboard sounds"""
        result = await self._make_request(
            "GET",
            "/soundboard-default-sounds",
            auth_header,
        )

        return {
            "action": "list_default_soundboard_sounds",
            "sounds": result,
            "count": len(result) if isinstance(result, list) else 0,
        }

    async def _list_guild_soundboard_sounds(
        self, config: DiscordListGuildSoundboardSoundsConfig, auth_header: str
    ) -> Dict[str, Any]:
        """List guild's soundboard sounds"""
        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}/soundboard-sounds",
            auth_header,
        )

        return {
            "action": "list_guild_soundboard_sounds",
            "guild_id": config.guild_id,
            "sounds": result,
            "count": len(result) if isinstance(result, list) else 0,
        }

    async def _get_guild_soundboard_sound(
        self, config: DiscordGetGuildSoundboardSoundConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get a specific guild soundboard sound"""
        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}/soundboard-sounds/{config.sound_id}",
            auth_header,
        )

        return {
            "action": "get_guild_soundboard_sound",
            "guild_id": config.guild_id,
            "sound_id": config.sound_id,
            "sound": result,
        }

    # ----- Webhook management -----

    async def _get_channel_webhooks(
        self, config: DiscordGetChannelWebhooksConfig, auth_header: str
    ) -> Dict[str, Any]:
        """List a channel's webhooks"""
        result = await self._make_request(
            "GET", f"/channels/{config.channel_id}/webhooks", auth_header
        )
        return {
            "action": "list_channel_webhooks",
            "channel_id": config.channel_id,
            "webhooks": result,
        }

    async def _get_guild_webhooks(
        self, config: DiscordGetGuildWebhooksConfig, auth_header: str
    ) -> Dict[str, Any]:
        """List a guild's webhooks"""
        result = await self._make_request(
            "GET", f"/guilds/{config.guild_id}/webhooks", auth_header
        )
        return {
            "action": "list_guild_webhooks",
            "guild_id": config.guild_id,
            "webhooks": result,
        }

    async def _get_webhook(
        self, config: DiscordGetWebhookConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get a webhook by ID"""
        result = await self._make_request(
            "GET", f"/webhooks/{config.webhook_id}", auth_header
        )
        return {
            "action": "get_webhook_by_id",
            "webhook_id": config.webhook_id,
            "webhook": result,
        }

    async def _create_webhook(
        self, config: DiscordCreateWebhookConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Create a webhook on a channel"""
        payload: Dict[str, Any] = {"name": config.name}
        if config.avatar:
            from nodes.core.media_resolver import resolve_media_input

            resolved = await resolve_media_input(
                config.avatar, default_mime="image/png"
            )
            payload["avatar"] = f"data:{resolved.mime_type};base64,{resolved.base64}"

        result = await self._make_request(
            "POST",
            f"/channels/{config.channel_id}/webhooks",
            auth_header,
            json_data=payload,
        )
        return {
            "action": "create_channel_webhook",
            "channel_id": config.channel_id,
            "webhook": result,
        }

    async def _modify_webhook(
        self, config: DiscordModifyWebhookConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Modify a webhook's name or channel"""
        payload: Dict[str, Any] = {}
        if config.name is not None:
            payload["name"] = config.name
        if config.channel_id is not None:
            payload["channel_id"] = config.channel_id

        result = await self._make_request(
            "PATCH",
            f"/webhooks/{config.webhook_id}",
            auth_header,
            json_data=payload,
        )
        return {
            "action": "update_webhook_settings",
            "webhook_id": config.webhook_id,
            "webhook": result,
        }

    async def _delete_webhook(
        self, config: DiscordDeleteWebhookConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Delete a webhook"""
        await self._make_request(
            "DELETE", f"/webhooks/{config.webhook_id}", auth_header
        )
        return {
            "action": "delete_webhook",
            "webhook_id": config.webhook_id,
            "success": True,
        }

    # ----- Emoji management -----

    async def _list_guild_emojis(
        self, config: DiscordListGuildEmojisConfig, auth_header: str
    ) -> Dict[str, Any]:
        """List a guild's custom emojis"""
        result = await self._make_request(
            "GET", f"/guilds/{config.guild_id}/emojis", auth_header
        )
        return {
            "action": "list_guild_emojis",
            "guild_id": config.guild_id,
            "emojis": result,
        }

    async def _get_guild_emoji(
        self, config: DiscordGetGuildEmojiConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get a single guild emoji"""
        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}/emojis/{config.emoji_id}",
            auth_header,
        )
        return {
            "action": "get_emoji_from_guild",
            "guild_id": config.guild_id,
            "emoji_id": config.emoji_id,
            "emoji": result,
        }

    async def _create_guild_emoji(
        self, config: DiscordCreateGuildEmojiConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Create a custom emoji in a guild"""
        from nodes.core.media_resolver import resolve_media_input

        resolved = await resolve_media_input(config.image, default_mime="image/png")
        payload: Dict[str, Any] = {
            "name": config.name,
            "image": f"data:{resolved.mime_type};base64,{resolved.base64}",
            "roles": config.roles or [],
        }

        result = await self._make_request(
            "POST",
            f"/guilds/{config.guild_id}/emojis",
            auth_header,
            json_data=payload,
        )
        return {
            "action": "create_emoji_in_guild",
            "guild_id": config.guild_id,
            "emoji": result,
        }

    async def _modify_guild_emoji(
        self, config: DiscordModifyGuildEmojiConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Modify a guild emoji's name or roles"""
        payload: Dict[str, Any] = {}
        if config.name is not None:
            payload["name"] = config.name
        if config.roles is not None:
            payload["roles"] = config.roles

        result = await self._make_request(
            "PATCH",
            f"/guilds/{config.guild_id}/emojis/{config.emoji_id}",
            auth_header,
            json_data=payload,
        )
        return {
            "action": "update_guild_emoji",
            "guild_id": config.guild_id,
            "emoji_id": config.emoji_id,
            "emoji": result,
        }

    async def _delete_guild_emoji(
        self, config: DiscordDeleteGuildEmojiConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Delete a guild emoji"""
        await self._make_request(
            "DELETE",
            f"/guilds/{config.guild_id}/emojis/{config.emoji_id}",
            auth_header,
        )
        return {
            "action": "delete_emoji_from_guild",
            "guild_id": config.guild_id,
            "emoji_id": config.emoji_id,
            "success": True,
        }

    async def _get_message(self, config: DiscordGetMessageConfig, auth_header: str) -> Dict[str, Any]:
        """Get a single message by ID"""
        result = await self._make_request(
            "GET",
            f"/channels/{config.channel_id}/messages/{config.message_id}",
            auth_header,
        )
        return {
            "action": "get_message_by_id",
            "channel_id": config.channel_id,
            "message_id": config.message_id,
            "message": result,
        }

    async def _crosspost_message(self, config: DiscordCrosspostMessageConfig, auth_header: str) -> Dict[str, Any]:
        """Crosspost a message in an announcement channel"""
        result = await self._make_request(
            "POST",
            f"/channels/{config.channel_id}/messages/{config.message_id}/crosspost",
            auth_header,
        )
        return {
            "action": "crosspost_message_to_announcement_channel",
            "channel_id": config.channel_id,
            "message_id": config.message_id,
            "message": result,
        }

    async def _bulk_delete_messages(self, config: DiscordBulkDeleteMessagesConfig, auth_header: str) -> Dict[str, Any]:
        """Bulk delete messages from a channel"""
        payload = {"messages": config.message_ids}
        await self._make_request(
            "POST",
            f"/channels/{config.channel_id}/messages/bulk-delete",
            auth_header,
            json_data=payload,
        )
        return {
            "action": "bulk_delete_channel_messages",
            "channel_id": config.channel_id,
            "message_ids": config.message_ids,
            "success": True,
        }

    async def _get_reactions(self, config: DiscordGetReactionsConfig, auth_header: str) -> Dict[str, Any]:
        """Get users who reacted to a message with a specific emoji"""
        from urllib.parse import quote

        emoji_encoded = quote(config.emoji, safe="")
        params = {"limit": min(config.limit or 25, 100)}
        result = await self._make_request(
            "GET",
            f"/channels/{config.channel_id}/messages/{config.message_id}/reactions/{emoji_encoded}",
            auth_header,
            params=params,
        )
        return {
            "action": "list_message_reaction_users",
            "channel_id": config.channel_id,
            "message_id": config.message_id,
            "emoji": config.emoji,
            "users": result,
            "count": len(result),
        }

    async def _delete_all_reactions(self, config: DiscordDeleteAllReactionsConfig, auth_header: str) -> Dict[str, Any]:
        """Delete all reactions from a message"""
        await self._make_request(
            "DELETE",
            f"/channels/{config.channel_id}/messages/{config.message_id}/reactions",
            auth_header,
        )
        return {
            "action": "delete_all_message_reactions",
            "channel_id": config.channel_id,
            "message_id": config.message_id,
            "success": True,
        }

    async def _delete_all_reactions_for_emoji(self, config: DiscordDeleteAllReactionsForEmojiConfig, auth_header: str) -> Dict[str, Any]:
        """Delete all reactions for a specific emoji from a message"""
        from urllib.parse import quote

        emoji_encoded = quote(config.emoji, safe="")
        await self._make_request(
            "DELETE",
            f"/channels/{config.channel_id}/messages/{config.message_id}/reactions/{emoji_encoded}",
            auth_header,
        )
        return {
            "action": "delete_emoji_reactions_from_message",
            "channel_id": config.channel_id,
            "message_id": config.message_id,
            "emoji": config.emoji,
            "success": True,
        }

    async def _trigger_typing(self, config: DiscordTriggerTypingConfig, auth_header: str) -> Dict[str, Any]:
        """Trigger a typing indicator in a channel"""
        await self._make_request(
            "POST",
            f"/channels/{config.channel_id}/typing",
            auth_header,
        )
        return {
            "action": "show_typing_indicator_in_channel",
            "channel_id": config.channel_id,
            "success": True,
        }

    async def _get_poll_answer_voters(self, config: DiscordGetPollAnswerVotersConfig, auth_header: str) -> Dict[str, Any]:
        """Get voters for a poll answer"""
        params = {"limit": min(config.limit or 25, 100)}
        result = await self._make_request(
            "GET",
            f"/channels/{config.channel_id}/polls/{config.message_id}/answers/{config.answer_id}",
            auth_header,
            params=params,
        )
        return {
            "action": "list_poll_answer_voters",
            "channel_id": config.channel_id,
            "message_id": config.message_id,
            "answer_id": config.answer_id,
            "voters": result.get("users", []),
        }

    async def _end_poll(self, config: DiscordEndPollConfig, auth_header: str) -> Dict[str, Any]:
        """Immediately end a poll"""
        result = await self._make_request(
            "POST",
            f"/channels/{config.channel_id}/polls/{config.message_id}/expire",
            auth_header,
        )
        return {
            "action": "end_poll_immediately",
            "channel_id": config.channel_id,
            "message_id": config.message_id,
            "message": result,
        }

    async def _create_channel(self, config: DiscordCreateChannelConfig, auth_header: str) -> Dict[str, Any]:
        """Create a new channel in a guild"""
        payload: Dict[str, Any] = {"name": config.name}
        if config.type is not None:
            payload["type"] = config.type
        if config.topic is not None:
            payload["topic"] = config.topic
        if config.parent_id is not None:
            payload["parent_id"] = config.parent_id
        if config.nsfw is not None:
            payload["nsfw"] = config.nsfw
        result = await self._make_request("POST", f"/guilds/{config.guild_id}/channels", auth_header, json_data=payload)
        return {"action": "create_channel_in_guild", "guild_id": config.guild_id, "channel": result}

    async def _modify_channel(self, config: DiscordModifyChannelConfig, auth_header: str) -> Dict[str, Any]:
        """Modify an existing channel"""
        payload: Dict[str, Any] = {}
        if config.name is not None:
            payload["name"] = config.name
        if config.topic is not None:
            payload["topic"] = config.topic
        if config.nsfw is not None:
            payload["nsfw"] = config.nsfw
        if config.position is not None:
            payload["position"] = config.position
        result = await self._make_request("PATCH", f"/channels/{config.channel_id}", auth_header, json_data=payload)
        return {"action": "update_channel_settings", "channel_id": config.channel_id, "channel": result}

    async def _delete_channel(self, config: DiscordDeleteChannelConfig, auth_header: str) -> Dict[str, Any]:
        """Delete a channel"""
        result = await self._make_request("DELETE", f"/channels/{config.channel_id}", auth_header)
        return {"action": "delete_channel", "channel_id": config.channel_id, "channel": result, "success": True}

    async def _edit_channel_permissions(self, config: DiscordEditChannelPermissionsConfig, auth_header: str) -> Dict[str, Any]:
        """Edit channel permission overwrites"""
        payload: Dict[str, Any] = {"type": config.type}
        if config.allow is not None:
            payload["allow"] = config.allow
        if config.deny is not None:
            payload["deny"] = config.deny
        await self._make_request("PUT", f"/channels/{config.channel_id}/permissions/{config.overwrite_id}", auth_header, json_data=payload)
        return {"action": "edit_channel_permission_overwrites", "channel_id": config.channel_id, "overwrite_id": config.overwrite_id, "success": True}

    async def _start_thread_from_message(
        self, config: DiscordStartThreadFromMessageConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Start a thread from an existing message"""
        payload: Dict[str, Any] = {"name": config.name}
        if config.auto_archive_duration is not None:
            payload["auto_archive_duration"] = config.auto_archive_duration
        result = await self._make_request(
            "POST",
            f"/channels/{config.channel_id}/messages/{config.message_id}/threads",
            auth_header,
            json_data=payload,
        )
        return {
            "action": "start_thread_from_existing_message",
            "channel_id": config.channel_id,
            "message_id": config.message_id,
            "thread": result,
        }

    async def _start_thread(
        self, config: DiscordStartThreadConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Start a thread without a message (forum/media channels)"""
        payload: Dict[str, Any] = {"name": config.name}
        if config.auto_archive_duration is not None:
            payload["auto_archive_duration"] = config.auto_archive_duration
        if config.type is not None:
            payload["type"] = config.type
        if config.message_content is not None:
            payload["message"] = {"content": config.message_content}
        result = await self._make_request(
            "POST",
            f"/channels/{config.channel_id}/threads",
            auth_header,
            json_data=payload,
        )
        return {
            "action": "start_thread_in_forum_channel",
            "channel_id": config.channel_id,
            "thread": result,
        }

    async def _join_thread(
        self, config: DiscordJoinThreadConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Join a thread"""
        await self._make_request(
            "PUT",
            f"/channels/{config.thread_id}/thread-members/@me",
            auth_header,
        )
        return {
            "action": "join_thread",
            "thread_id": config.thread_id,
            "success": True,
        }

    async def _leave_thread(
        self, config: DiscordLeaveThreadConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Leave a thread"""
        await self._make_request(
            "DELETE",
            f"/channels/{config.thread_id}/thread-members/@me",
            auth_header,
        )
        return {
            "action": "leave_thread",
            "thread_id": config.thread_id,
            "success": True,
        }

    async def _add_thread_member(
        self, config: DiscordAddThreadMemberConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Add a member to a thread"""
        await self._make_request(
            "PUT",
            f"/channels/{config.thread_id}/thread-members/{config.user_id}",
            auth_header,
        )
        return {
            "action": "add_member_to_thread",
            "thread_id": config.thread_id,
            "user_id": config.user_id,
            "success": True,
        }

    async def _remove_thread_member(
        self, config: DiscordRemoveThreadMemberConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Remove a member from a thread"""
        await self._make_request(
            "DELETE",
            f"/channels/{config.thread_id}/thread-members/{config.user_id}",
            auth_header,
        )
        return {
            "action": "remove_member_from_thread",
            "thread_id": config.thread_id,
            "user_id": config.user_id,
            "success": True,
        }

    async def _list_thread_members(
        self, config: DiscordListThreadMembersConfig, auth_header: str
    ) -> Dict[str, Any]:
        """List members in a thread"""
        result = await self._make_request(
            "GET",
            f"/channels/{config.thread_id}/thread-members",
            auth_header,
        )
        return {
            "action": "list_thread_members",
            "thread_id": config.thread_id,
            "members": result,
            "count": len(result),
        }

    async def _list_active_threads(
        self, config: DiscordListActiveThreadsConfig, auth_header: str
    ) -> Dict[str, Any]:
        """List all active threads in a guild"""
        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}/threads/active",
            auth_header,
        )
        return {
            "action": "list_guild_active_threads",
            "guild_id": config.guild_id,
            "threads": result,
        }

    async def _create_role(self, config: DiscordCreateRoleConfig, auth_header: str) -> Dict[str, Any]:
        """Create a new role in a guild"""
        payload: Dict[str, Any] = {"name": config.name}
        if config.color is not None:
            payload["color"] = config.color
        if config.hoist is not None:
            payload["hoist"] = config.hoist
        if config.mentionable is not None:
            payload["mentionable"] = config.mentionable
        if config.permissions is not None:
            payload["permissions"] = config.permissions
        result = await self._make_request(
            "POST",
            f"/guilds/{config.guild_id}/roles",
            auth_header,
            json_data=payload,
        )
        return {
            "action": "create_role_in_guild",
            "guild_id": config.guild_id,
            "role": result,
        }

    async def _modify_role(self, config: DiscordModifyRoleConfig, auth_header: str) -> Dict[str, Any]:
        """Modify an existing role"""
        payload: Dict[str, Any] = {}
        if config.name is not None:
            payload["name"] = config.name
        if config.color is not None:
            payload["color"] = config.color
        if config.hoist is not None:
            payload["hoist"] = config.hoist
        if config.mentionable is not None:
            payload["mentionable"] = config.mentionable
        result = await self._make_request(
            "PATCH",
            f"/guilds/{config.guild_id}/roles/{config.role_id}",
            auth_header,
            json_data=payload,
        )
        return {
            "action": "update_guild_role",
            "guild_id": config.guild_id,
            "role_id": config.role_id,
            "role": result,
        }

    async def _delete_role(self, config: DiscordDeleteRoleConfig, auth_header: str) -> Dict[str, Any]:
        """Delete a role from a guild"""
        await self._make_request(
            "DELETE",
            f"/guilds/{config.guild_id}/roles/{config.role_id}",
            auth_header,
        )
        return {
            "action": "delete_role_from_guild",
            "guild_id": config.guild_id,
            "role_id": config.role_id,
            "success": True,
        }

    async def _add_role_to_member(self, config: DiscordAddRoleToMemberConfig, auth_header: str) -> Dict[str, Any]:
        """Add a role to a guild member"""
        await self._make_request(
            "PUT",
            f"/guilds/{config.guild_id}/members/{config.user_id}/roles/{config.role_id}",
            auth_header,
        )
        return {
            "action": "add_role_to_guild_member",
            "guild_id": config.guild_id,
            "user_id": config.user_id,
            "role_id": config.role_id,
            "success": True,
        }

    async def _remove_role_from_member(self, config: DiscordRemoveRoleFromMemberConfig, auth_header: str) -> Dict[str, Any]:
        """Remove a role from a guild member"""
        await self._make_request(
            "DELETE",
            f"/guilds/{config.guild_id}/members/{config.user_id}/roles/{config.role_id}",
            auth_header,
        )
        return {
            "action": "remove_role_from_guild_member",
            "guild_id": config.guild_id,
            "user_id": config.user_id,
            "role_id": config.role_id,
            "success": True,
        }

    async def _modify_guild(self, config: DiscordModifyGuildConfig, auth_header: str) -> Dict[str, Any]:
        """Modify guild settings"""
        payload: Dict[str, Any] = {}
        if config.name is not None:
            payload["name"] = config.name
        if config.description is not None:
            payload["description"] = config.description
        if config.afk_channel_id is not None:
            payload["afk_channel_id"] = config.afk_channel_id
        if config.afk_timeout is not None:
            payload["afk_timeout"] = config.afk_timeout
        result = await self._make_request("PATCH", f"/guilds/{config.guild_id}", auth_header, json_data=payload)
        return {"action": "update_guild_settings", "guild_id": config.guild_id, "guild": result}

    async def _get_guild_preview(self, config: DiscordGetGuildPreviewConfig, auth_header: str) -> Dict[str, Any]:
        """Get guild preview"""
        result = await self._make_request("GET", f"/guilds/{config.guild_id}/preview", auth_header)
        return {"action": "get_guild_preview", "guild_id": config.guild_id, "preview": result}

    async def _get_guild_vanity_url(self, config: DiscordGetGuildVanityUrlConfig, auth_header: str) -> Dict[str, Any]:
        """Get guild vanity URL"""
        result = await self._make_request("GET", f"/guilds/{config.guild_id}/vanity-url", auth_header)
        return {"action": "get_guild_vanity_url", "guild_id": config.guild_id, "vanity_url": result}

    async def _get_guild_prune_count(self, config: DiscordGetGuildPruneCountConfig, auth_header: str) -> Dict[str, Any]:
        """Get guild prune count"""
        params: Dict[str, Any] = {}
        if config.days is not None:
            params["days"] = config.days
        result = await self._make_request("GET", f"/guilds/{config.guild_id}/prune", auth_header, params=params)
        return {"action": "get_guild_prune_count", "guild_id": config.guild_id, "prune": result}

    async def _begin_guild_prune(self, config: DiscordBeginGuildPruneConfig, auth_header: str) -> Dict[str, Any]:
        """Begin guild prune for inactive members"""
        payload: Dict[str, Any] = {"days": config.days}
        if config.compute_prune_count is not None:
            payload["compute_prune_count"] = config.compute_prune_count
        result = await self._make_request("POST", f"/guilds/{config.guild_id}/prune", auth_header, json_data=payload)
        return {"action": "begin_guild_prune_for_inactive_members", "guild_id": config.guild_id, "prune": result}

    async def _get_guild_bans(self, config: DiscordGetGuildBansConfig, auth_header: str) -> Dict[str, Any]:
        """Get all bans for a guild"""
        params: Dict[str, Any] = {}
        if config.limit is not None:
            params["limit"] = config.limit
        result = await self._make_request("GET", f"/guilds/{config.guild_id}/bans", auth_header, params=params)
        return {"action": "list_guild_bans", "guild_id": config.guild_id, "bans": result}

    async def _get_guild_ban(self, config: DiscordGetGuildBanConfig, auth_header: str) -> Dict[str, Any]:
        """Get a specific ban"""
        result = await self._make_request("GET", f"/guilds/{config.guild_id}/bans/{config.user_id}", auth_header)
        return {"action": "get_guild_ban", "guild_id": config.guild_id, "user_id": config.user_id, "ban": result}

    async def _get_audit_log(self, config: DiscordGetAuditLogConfig, auth_header: str) -> Dict[str, Any]:
        """Get the audit log for a guild"""
        params: Dict[str, Any] = {}
        if config.user_id is not None:
            params["user_id"] = config.user_id
        if config.action_type is not None:
            params["action_type"] = config.action_type
        if config.limit is not None:
            params["limit"] = config.limit
        result = await self._make_request("GET", f"/guilds/{config.guild_id}/audit-logs", auth_header, params=params)
        return {"action": "get_guild_audit_log", "guild_id": config.guild_id, "audit_log": result}

    async def _get_invite(self, config: DiscordGetInviteConfig, auth_header: str) -> Dict[str, Any]:
        """Get information about an invite"""
        params: Dict[str, Any] = {}
        if config.with_counts is not None:
            params["with_counts"] = config.with_counts
        result = await self._make_request("GET", f"/invites/{config.invite_code}", auth_header, params=params or None)
        return {"action": "get_invite_info", "invite_code": config.invite_code, "invite": result}

    async def _delete_invite(self, config: DiscordDeleteInviteConfig, auth_header: str) -> Dict[str, Any]:
        """Delete an invite"""
        await self._make_request("DELETE", f"/invites/{config.invite_code}", auth_header)
        return {"action": "delete_invite", "invite_code": config.invite_code, "success": True}

    async def _get_channel_invites(self, config: DiscordGetChannelInvitesConfig, auth_header: str) -> Dict[str, Any]:
        """Get all invites for a channel"""
        result = await self._make_request("GET", f"/channels/{config.channel_id}/invites", auth_header)
        return {"action": "list_channel_invites", "channel_id": config.channel_id, "invites": result}

    async def _create_channel_invite(self, config: DiscordCreateChannelInviteConfig, auth_header: str) -> Dict[str, Any]:
        """Create a new invite for a channel"""
        payload: Dict[str, Any] = {}
        if config.max_age is not None:
            payload["max_age"] = config.max_age
        if config.max_uses is not None:
            payload["max_uses"] = config.max_uses
        if config.temporary is not None:
            payload["temporary"] = config.temporary
        if config.unique is not None:
            payload["unique"] = config.unique
        result = await self._make_request("POST", f"/channels/{config.channel_id}/invites", auth_header, json_data=payload)
        return {"action": "create_channel_invite", "channel_id": config.channel_id, "invite": result}

    async def _get_guild_invites(self, config: DiscordGetGuildInvitesConfig, auth_header: str) -> Dict[str, Any]:
        """Get all invites for a guild"""
        result = await self._make_request("GET", f"/guilds/{config.guild_id}/invites", auth_header)
        return {"action": "list_guild_invites", "guild_id": config.guild_id, "invites": result}

    async def _list_guild_stickers(
        self, config: DiscordListGuildStickersConfig, auth_header: str
    ) -> Dict[str, Any]:
        """List a guild's custom stickers"""
        result = await self._make_request(
            "GET", f"/guilds/{config.guild_id}/stickers", auth_header
        )
        return {
            "action": "list_guild_stickers",
            "guild_id": config.guild_id,
            "stickers": result,
        }

    async def _get_guild_sticker(
        self, config: DiscordGetGuildStickerConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get a single guild sticker"""
        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}/stickers/{config.sticker_id}",
            auth_header,
        )
        return {
            "action": "get_sticker_from_guild",
            "guild_id": config.guild_id,
            "sticker_id": config.sticker_id,
            "sticker": result,
        }

    async def _modify_guild_sticker(
        self, config: DiscordModifyGuildStickerConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Modify a guild sticker's name, description, or tags"""
        payload: Dict[str, Any] = {}
        if config.name is not None:
            payload["name"] = config.name
        if config.description is not None:
            payload["description"] = config.description
        if config.tags is not None:
            payload["tags"] = config.tags

        result = await self._make_request(
            "PATCH",
            f"/guilds/{config.guild_id}/stickers/{config.sticker_id}",
            auth_header,
            json_data=payload,
        )
        return {
            "action": "update_guild_sticker",
            "guild_id": config.guild_id,
            "sticker_id": config.sticker_id,
            "sticker": result,
        }

    async def _delete_guild_sticker(
        self, config: DiscordDeleteGuildStickerConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Delete a guild sticker"""
        await self._make_request(
            "DELETE",
            f"/guilds/{config.guild_id}/stickers/{config.sticker_id}",
            auth_header,
        )
        return {
            "action": "delete_sticker_from_guild",
            "guild_id": config.guild_id,
            "sticker_id": config.sticker_id,
            "success": True,
        }

    async def _list_scheduled_events(self, config: DiscordListScheduledEventsConfig, auth_header: str) -> Dict[str, Any]:
        """List all scheduled events in a guild"""
        params: Dict[str, Any] = {}
        if config.with_user_count is not None:
            params["with_user_count"] = config.with_user_count
        result = await self._make_request("GET", f"/guilds/{config.guild_id}/scheduled-events", auth_header, params=params or None)
        return {"action": "list_guild_scheduled_events", "guild_id": config.guild_id, "scheduled_events": result}

    async def _get_scheduled_event(self, config: DiscordGetScheduledEventConfig, auth_header: str) -> Dict[str, Any]:
        """Get a specific scheduled event"""
        result = await self._make_request("GET", f"/guilds/{config.guild_id}/scheduled-events/{config.event_id}", auth_header)
        return {"action": "get_scheduled_event", "guild_id": config.guild_id, "event_id": config.event_id, "scheduled_event": result}

    async def _create_scheduled_event(self, config: DiscordCreateScheduledEventConfig, auth_header: str) -> Dict[str, Any]:
        """Create a new scheduled event"""
        payload: Dict[str, Any] = {
            "name": config.name,
            "scheduled_start_time": config.scheduled_start_time,
            "entity_type": config.entity_type,
        }
        if config.privacy_level is not None:
            payload["privacy_level"] = config.privacy_level
        if config.channel_id is not None:
            payload["channel_id"] = config.channel_id
        if config.entity_metadata_location is not None:
            payload["entity_metadata"] = {"location": config.entity_metadata_location}
        if config.scheduled_end_time is not None:
            payload["scheduled_end_time"] = config.scheduled_end_time
        if config.description is not None:
            payload["description"] = config.description
        result = await self._make_request("POST", f"/guilds/{config.guild_id}/scheduled-events", auth_header, json_data=payload)
        return {"action": "create_scheduled_event", "guild_id": config.guild_id, "scheduled_event": result}

    async def _modify_scheduled_event(self, config: DiscordModifyScheduledEventConfig, auth_header: str) -> Dict[str, Any]:
        """Modify an existing scheduled event"""
        payload: Dict[str, Any] = {}
        if config.name is not None:
            payload["name"] = config.name
        if config.description is not None:
            payload["description"] = config.description
        if config.scheduled_start_time is not None:
            payload["scheduled_start_time"] = config.scheduled_start_time
        if config.scheduled_end_time is not None:
            payload["scheduled_end_time"] = config.scheduled_end_time
        if config.status is not None:
            payload["status"] = config.status
        result = await self._make_request("PATCH", f"/guilds/{config.guild_id}/scheduled-events/{config.event_id}", auth_header, json_data=payload)
        return {"action": "update_scheduled_event", "guild_id": config.guild_id, "event_id": config.event_id, "scheduled_event": result}

    async def _delete_scheduled_event(self, config: DiscordDeleteScheduledEventConfig, auth_header: str) -> Dict[str, Any]:
        """Delete a scheduled event"""
        await self._make_request("DELETE", f"/guilds/{config.guild_id}/scheduled-events/{config.event_id}", auth_header)
        return {"action": "delete_scheduled_event", "guild_id": config.guild_id, "event_id": config.event_id, "success": True}

    async def _get_scheduled_event_users(self, config: DiscordGetScheduledEventUsersConfig, auth_header: str) -> Dict[str, Any]:
        """Get users interested in a scheduled event"""
        params: Dict[str, Any] = {}
        if config.limit is not None:
            params["limit"] = config.limit
        result = await self._make_request("GET", f"/guilds/{config.guild_id}/scheduled-events/{config.event_id}/users", auth_header, params=params or None)
        return {"action": "list_scheduled_event_users", "guild_id": config.guild_id, "event_id": config.event_id, "users": result}

    async def _list_auto_mod_rules(
        self, config: DiscordListAutoModRulesConfig, auth_header: str
    ) -> Dict[str, Any]:
        """List all auto moderation rules in a guild"""
        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}/auto-moderation/rules",
            auth_header,
        )
        return {
            "action": "list_guild_auto_moderation_rules",
            "guild_id": config.guild_id,
            "rules": result,
        }

    async def _get_auto_mod_rule(
        self, config: DiscordGetAutoModRuleConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get a specific auto moderation rule"""
        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}/auto-moderation/rules/{config.rule_id}",
            auth_header,
        )
        return {
            "action": "get_auto_moderation_rule",
            "guild_id": config.guild_id,
            "rule_id": config.rule_id,
            "rule": result,
        }

    async def _create_auto_mod_rule(
        self, config: DiscordCreateAutoModRuleConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Create a new auto moderation rule"""
        payload: Dict[str, Any] = {
            "name": config.name,
            "event_type": config.event_type,
            "trigger_type": config.trigger_type,
            "actions": config.actions or [],
        }
        trigger_metadata: Dict[str, Any] = {}
        if config.trigger_metadata_keyword_filter is not None:
            trigger_metadata["keyword_filter"] = config.trigger_metadata_keyword_filter
        if config.trigger_metadata_presets is not None:
            trigger_metadata["presets"] = config.trigger_metadata_presets
        if trigger_metadata:
            payload["trigger_metadata"] = trigger_metadata
        if config.enabled is not None:
            payload["enabled"] = config.enabled
        if config.exempt_roles is not None:
            payload["exempt_roles"] = config.exempt_roles
        if config.exempt_channels is not None:
            payload["exempt_channels"] = config.exempt_channels

        result = await self._make_request(
            "POST",
            f"/guilds/{config.guild_id}/auto-moderation/rules",
            auth_header,
            json_data=payload,
        )
        return {
            "action": "create_auto_moderation_rule",
            "guild_id": config.guild_id,
            "rule": result,
        }

    async def _modify_auto_mod_rule(
        self, config: DiscordModifyAutoModRuleConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Modify an existing auto moderation rule"""
        payload: Dict[str, Any] = {}
        if config.name is not None:
            payload["name"] = config.name
        if config.enabled is not None:
            payload["enabled"] = config.enabled
        if config.exempt_roles is not None:
            payload["exempt_roles"] = config.exempt_roles
        if config.exempt_channels is not None:
            payload["exempt_channels"] = config.exempt_channels

        result = await self._make_request(
            "PATCH",
            f"/guilds/{config.guild_id}/auto-moderation/rules/{config.rule_id}",
            auth_header,
            json_data=payload,
        )
        return {
            "action": "update_auto_moderation_rule",
            "guild_id": config.guild_id,
            "rule_id": config.rule_id,
            "rule": result,
        }

    async def _delete_auto_mod_rule(
        self, config: DiscordDeleteAutoModRuleConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Delete an auto moderation rule"""
        await self._make_request(
            "DELETE",
            f"/guilds/{config.guild_id}/auto-moderation/rules/{config.rule_id}",
            auth_header,
        )
        return {
            "action": "delete_auto_moderation_rule",
            "guild_id": config.guild_id,
            "rule_id": config.rule_id,
            "success": True,
        }

    async def _create_stage_instance(
        self, config: DiscordCreateStageInstanceConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Create a stage instance (go live)"""
        payload: Dict[str, Any] = {
            "channel_id": config.channel_id,
            "topic": config.topic,
        }
        if config.privacy_level is not None:
            payload["privacy_level"] = config.privacy_level
        result = await self._make_request(
            "POST",
            "/stage-instances",
            auth_header,
            json_data=payload,
        )
        return {
            "action": "create_stage_instance",
            "channel_id": config.channel_id,
            "stage_instance": result,
        }

    async def _get_stage_instance(
        self, config: DiscordGetStageInstanceConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get the stage instance for a channel"""
        result = await self._make_request(
            "GET",
            f"/stage-instances/{config.channel_id}",
            auth_header,
        )
        return {
            "action": "get_stage_instance_for_channel",
            "channel_id": config.channel_id,
            "stage_instance": result,
        }

    async def _modify_stage_instance(
        self, config: DiscordModifyStageInstanceConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Modify a stage instance"""
        payload: Dict[str, Any] = {}
        if config.topic is not None:
            payload["topic"] = config.topic
        if config.privacy_level is not None:
            payload["privacy_level"] = config.privacy_level
        result = await self._make_request(
            "PATCH",
            f"/stage-instances/{config.channel_id}",
            auth_header,
            json_data=payload,
        )
        return {
            "action": "update_stage_instance",
            "channel_id": config.channel_id,
            "stage_instance": result,
        }

    async def _delete_stage_instance(
        self, config: DiscordDeleteStageInstanceConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Delete a stage instance (end the stage)"""
        await self._make_request(
            "DELETE",
            f"/stage-instances/{config.channel_id}",
            auth_header,
        )
        return {
            "action": "delete_stage_instance",
            "channel_id": config.channel_id,
            "success": True,
        }

    async def _create_guild_soundboard_sound(
        self, config: DiscordCreateGuildSoundboardSoundConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Create a new soundboard sound for a guild"""
        from nodes.core.media_resolver import resolve_media_input

        resolved = await resolve_media_input(config.sound, default_mime="audio/mpeg")
        payload = {
            "name": config.name,
            "sound": f"data:{resolved.mime_type};base64,{resolved.base64}",
        }
        if config.volume is not None:
            payload["volume"] = config.volume
        if config.emoji_id:
            payload["emoji_id"] = config.emoji_id
        if config.emoji_name:
            payload["emoji_name"] = config.emoji_name

        result = await self._make_request(
            "POST",
            f"/guilds/{config.guild_id}/soundboard-sounds",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "create_guild_soundboard_sound",
            "guild_id": config.guild_id,
            "sound": result,
        }

    async def _modify_guild_soundboard_sound(
        self, config: DiscordModifyGuildSoundboardSoundConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Modify a guild soundboard sound"""
        payload = {}
        if config.name is not None:
            payload["name"] = config.name
        if config.volume is not None:
            payload["volume"] = config.volume
        if config.emoji_id is not None:
            payload["emoji_id"] = config.emoji_id
        if config.emoji_name is not None:
            payload["emoji_name"] = config.emoji_name

        result = await self._make_request(
            "PATCH",
            f"/guilds/{config.guild_id}/soundboard-sounds/{config.sound_id}",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "update_guild_soundboard_sound",
            "guild_id": config.guild_id,
            "sound_id": config.sound_id,
            "sound": result,
        }

    async def _delete_guild_soundboard_sound(
        self, config: DiscordDeleteGuildSoundboardSoundConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Delete a guild soundboard sound"""
        await self._make_request(
            "DELETE",
            f"/guilds/{config.guild_id}/soundboard-sounds/{config.sound_id}",
            auth_header,
        )

        return {
            "action": "delete_guild_soundboard_sound",
            "guild_id": config.guild_id,
            "sound_id": config.sound_id,
            "success": True,
        }

    # ============================================================================
    # Guild Template Handler Methods
    # ============================================================================

    async def _get_guild_template(
        self, config: DiscordGetGuildTemplateConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get a guild template by code"""
        result = await self._make_request(
            "GET",
            f"/guilds/templates/{config.template_code}",
            auth_header,
        )

        return {
            "action": "get_guild_template",
            "template_code": config.template_code,
            "template": result,
        }

    async def _create_guild_from_template(
        self, config: DiscordCreateGuildFromTemplateConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Create a new guild from a template"""
        payload = {"name": config.name}
        if config.icon:
            from nodes.core.media_resolver import resolve_media_input

            resolved = await resolve_media_input(config.icon, default_mime="image/png")
            payload["icon"] = f"data:{resolved.mime_type};base64,{resolved.base64}"

        result = await self._make_request(
            "POST",
            f"/guilds/templates/{config.template_code}",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "create_guild_from_template",
            "template_code": config.template_code,
            "guild": result,
        }

    async def _get_guild_templates(
        self, config: DiscordGetGuildTemplatesConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get all templates for a guild"""
        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}/templates",
            auth_header,
        )

        return {
            "action": "list_guild_templates",
            "guild_id": config.guild_id,
            "templates": result,
            "count": len(result) if isinstance(result, list) else 0,
        }

    async def _create_guild_template(
        self, config: DiscordCreateGuildTemplateConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Create a guild template"""
        payload = {"name": config.name}
        if config.description:
            payload["description"] = config.description

        result = await self._make_request(
            "POST",
            f"/guilds/{config.guild_id}/templates",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "create_guild_template",
            "guild_id": config.guild_id,
            "template": result,
        }

    async def _sync_guild_template(
        self, config: DiscordSyncGuildTemplateConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Sync a guild template with current guild state"""
        result = await self._make_request(
            "PUT",
            f"/guilds/{config.guild_id}/templates/{config.template_code}",
            auth_header,
        )

        return {
            "action": "sync_guild_template_with_state",
            "guild_id": config.guild_id,
            "template_code": config.template_code,
            "template": result,
        }

    async def _modify_guild_template(
        self, config: DiscordModifyGuildTemplateConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Modify a guild template"""
        payload = {}
        if config.name is not None:
            payload["name"] = config.name
        if config.description is not None:
            payload["description"] = config.description

        result = await self._make_request(
            "PATCH",
            f"/guilds/{config.guild_id}/templates/{config.template_code}",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "update_guild_template",
            "guild_id": config.guild_id,
            "template_code": config.template_code,
            "template": result,
        }

    async def _delete_guild_template(
        self, config: DiscordDeleteGuildTemplateConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Delete a guild template"""
        await self._make_request(
            "DELETE",
            f"/guilds/{config.guild_id}/templates/{config.template_code}",
            auth_header,
        )

        return {
            "action": "delete_guild_template",
            "guild_id": config.guild_id,
            "template_code": config.template_code,
            "success": True,
        }

    # ============================================================================
    # Guild Onboarding Handler Methods
    # ============================================================================

    async def _get_guild_onboarding(
        self, config: DiscordGetGuildOnboardingConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get guild onboarding configuration"""
        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}/onboarding",
            auth_header,
        )

        return {
            "action": "get_guild_onboarding_config",
            "guild_id": config.guild_id,
            "onboarding": result,
        }

    async def _modify_guild_onboarding(
        self, config: DiscordModifyGuildOnboardingConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Modify guild onboarding configuration"""
        payload = {}
        if config.enabled is not None:
            payload["enabled"] = config.enabled
        if config.mode is not None:
            payload["mode"] = config.mode
        if config.default_channel_ids is not None:
            payload["default_channel_ids"] = config.default_channel_ids

        result = await self._make_request(
            "PUT",
            f"/guilds/{config.guild_id}/onboarding",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "update_guild_onboarding_config",
            "guild_id": config.guild_id,
            "onboarding": result,
        }

    # ============================================================================
    # DM/Group DM Handler Methods
    # ============================================================================

    async def _create_dm(
        self, config: DiscordCreateDMConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Create a DM channel with a user"""
        payload = {"recipient_id": config.recipient_id}

        result = await self._make_request(
            "POST",
            "/users/@me/channels",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "create_direct_message_channel",
            "recipient_id": config.recipient_id,
            "channel": result,
        }

    async def _create_group_dm(
        self, config: DiscordCreateGroupDMConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Create a group DM channel"""
        payload = {"access_tokens": config.access_tokens}
        if config.nicks:
            payload["nicks"] = config.nicks

        result = await self._make_request(
            "POST",
            "/users/@me/channels",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "create_group_direct_message_channel",
            "channel": result,
        }

    # ============================================================================
    # Application Commands Handler Methods
    # ============================================================================

    async def _get_global_application_commands(
        self, config: DiscordGetGlobalApplicationCommandsConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get all global application commands"""
        params = {}
        if config.with_localizations:
            params["with_localizations"] = "true"

        result = await self._make_request(
            "GET",
            f"/applications/{config.application_id}/commands",
            auth_header,
            params=params,
        )

        return {
            "action": "list_global_application_commands",
            "application_id": config.application_id,
            "commands": result,
            "count": len(result) if isinstance(result, list) else 0,
        }

    async def _create_global_application_command(
        self, config: DiscordCreateGlobalApplicationCommandConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Create a global application command"""
        payload = {
            "name": config.name,
            "description": config.description,
            "type": config.type or 1,
        }

        result = await self._make_request(
            "POST",
            f"/applications/{config.application_id}/commands",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "create_global_application_command",
            "application_id": config.application_id,
            "command": result,
        }

    async def _get_global_application_command(
        self, config: DiscordGetGlobalApplicationCommandConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get a specific global application command"""
        result = await self._make_request(
            "GET",
            f"/applications/{config.application_id}/commands/{config.command_id}",
            auth_header,
        )

        return {
            "action": "get_global_application_command",
            "application_id": config.application_id,
            "command_id": config.command_id,
            "command": result,
        }

    async def _edit_global_application_command(
        self, config: DiscordEditGlobalApplicationCommandConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Edit a global application command"""
        payload = {}
        if config.name is not None:
            payload["name"] = config.name
        if config.description is not None:
            payload["description"] = config.description

        result = await self._make_request(
            "PATCH",
            f"/applications/{config.application_id}/commands/{config.command_id}",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "edit_global_application_command",
            "application_id": config.application_id,
            "command_id": config.command_id,
            "command": result,
        }

    async def _delete_global_application_command(
        self, config: DiscordDeleteGlobalApplicationCommandConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Delete a global application command"""
        await self._make_request(
            "DELETE",
            f"/applications/{config.application_id}/commands/{config.command_id}",
            auth_header,
        )

        return {
            "action": "delete_global_application_command",
            "application_id": config.application_id,
            "command_id": config.command_id,
            "success": True,
        }

    async def _get_guild_application_commands(
        self, config: DiscordGetGuildApplicationCommandsConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get all guild application commands"""
        result = await self._make_request(
            "GET",
            f"/applications/{config.application_id}/guilds/{config.guild_id}/commands",
            auth_header,
        )

        return {
            "action": "list_guild_application_commands",
            "application_id": config.application_id,
            "guild_id": config.guild_id,
            "commands": result,
            "count": len(result) if isinstance(result, list) else 0,
        }

    async def _create_guild_application_command(
        self, config: DiscordCreateGuildApplicationCommandConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Create a guild application command"""
        payload = {
            "name": config.name,
            "description": config.description,
            "type": config.type or 1,
        }

        result = await self._make_request(
            "POST",
            f"/applications/{config.application_id}/guilds/{config.guild_id}/commands",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "create_guild_application_command",
            "application_id": config.application_id,
            "guild_id": config.guild_id,
            "command": result,
        }

    async def _get_guild_application_command(
        self, config: DiscordGetGuildApplicationCommandConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get a specific guild application command"""
        result = await self._make_request(
            "GET",
            f"/applications/{config.application_id}/guilds/{config.guild_id}/commands/{config.command_id}",
            auth_header,
        )

        return {
            "action": "get_guild_application_command",
            "application_id": config.application_id,
            "guild_id": config.guild_id,
            "command_id": config.command_id,
            "command": result,
        }

    async def _edit_guild_application_command(
        self, config: DiscordEditGuildApplicationCommandConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Edit a guild application command"""
        payload = {}
        if config.name is not None:
            payload["name"] = config.name
        if config.description is not None:
            payload["description"] = config.description

        result = await self._make_request(
            "PATCH",
            f"/applications/{config.application_id}/guilds/{config.guild_id}/commands/{config.command_id}",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "edit_guild_application_command",
            "application_id": config.application_id,
            "guild_id": config.guild_id,
            "command_id": config.command_id,
            "command": result,
        }

    async def _delete_guild_application_command(
        self, config: DiscordDeleteGuildApplicationCommandConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Delete a guild application command"""
        await self._make_request(
            "DELETE",
            f"/applications/{config.application_id}/guilds/{config.guild_id}/commands/{config.command_id}",
            auth_header,
        )

        return {
            "action": "delete_guild_application_command",
            "application_id": config.application_id,
            "guild_id": config.guild_id,
            "command_id": config.command_id,
            "success": True,
        }

    # ============================================================================
    # SKUs & Entitlements Handler Methods
    # ============================================================================

    async def _list_skus(
        self, config: DiscordListSKUsConfig, auth_header: str
    ) -> Dict[str, Any]:
        """List all SKUs for an application"""
        result = await self._make_request(
            "GET",
            f"/applications/{config.application_id}/skus",
            auth_header,
        )

        return {
            "action": "list_application_skus",
            "application_id": config.application_id,
            "skus": result,
            "count": len(result) if isinstance(result, list) else 0,
        }

    async def _list_entitlements(
        self, config: DiscordListEntitlementsConfig, auth_header: str
    ) -> Dict[str, Any]:
        """List entitlements for an application"""
        params = {}
        if config.user_id:
            params["user_id"] = config.user_id
        if config.guild_id:
            params["guild_id"] = config.guild_id
        if config.exclude_ended:
            params["exclude_ended"] = "true"

        result = await self._make_request(
            "GET",
            f"/applications/{config.application_id}/entitlements",
            auth_header,
            params=params,
        )

        return {
            "action": "list_application_entitlements",
            "application_id": config.application_id,
            "entitlements": result,
            "count": len(result) if isinstance(result, list) else 0,
        }

    async def _create_test_entitlement(
        self, config: DiscordCreateTestEntitlementConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Create a test entitlement"""
        payload = {
            "sku_id": config.sku_id,
            "owner_id": config.owner_id,
            "owner_type": config.owner_type,
        }

        result = await self._make_request(
            "POST",
            f"/applications/{config.application_id}/entitlements",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "create_test_entitlement",
            "application_id": config.application_id,
            "entitlement": result,
        }

    async def _delete_test_entitlement(
        self, config: DiscordDeleteTestEntitlementConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Delete a test entitlement"""
        await self._make_request(
            "DELETE",
            f"/applications/{config.application_id}/entitlements/{config.entitlement_id}",
            auth_header,
        )

        return {
            "action": "delete_test_entitlement",
            "application_id": config.application_id,
            "entitlement_id": config.entitlement_id,
            "success": True,
        }

    async def _consume_entitlement(
        self, config: DiscordConsumeEntitlementConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Consume a one-time purchase entitlement"""
        await self._make_request(
            "POST",
            f"/applications/{config.application_id}/entitlements/{config.entitlement_id}/consume",
            auth_header,
        )

        return {
            "action": "consume_one_time_purchase_entitlement",
            "application_id": config.application_id,
            "entitlement_id": config.entitlement_id,
            "success": True,
        }

    # ============================================================================
    # Guild Widget Handler Methods
    # ============================================================================

    async def _get_guild_widget(
        self, config: DiscordGetGuildWidgetConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get guild widget settings"""
        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}/widget",
            auth_header,
        )

        return {
            "action": "get_guild_widget_settings",
            "guild_id": config.guild_id,
            "widget": result,
        }

    async def _modify_guild_widget(
        self, config: DiscordModifyGuildWidgetConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Modify guild widget settings"""
        payload = {}
        if config.enabled is not None:
            payload["enabled"] = config.enabled
        if config.channel_id is not None:
            payload["channel_id"] = config.channel_id

        result = await self._make_request(
            "PATCH",
            f"/guilds/{config.guild_id}/widget",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "update_guild_widget_settings",
            "guild_id": config.guild_id,
            "widget": result,
        }

    # ============================================================================
    # Guild Welcome Screen Handler Methods
    # ============================================================================

    async def _get_guild_welcome_screen(
        self, config: DiscordGetGuildWelcomeScreenConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get guild welcome screen"""
        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}/welcome-screen",
            auth_header,
        )

        return {
            "action": "get_guild_welcome_screen",
            "guild_id": config.guild_id,
            "welcome_screen": result,
        }

    async def _modify_guild_welcome_screen(
        self, config: DiscordModifyGuildWelcomeScreenConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Modify guild welcome screen"""
        payload = {}
        if config.enabled is not None:
            payload["enabled"] = config.enabled
        if config.description is not None:
            payload["description"] = config.description

        result = await self._make_request(
            "PATCH",
            f"/guilds/{config.guild_id}/welcome-screen",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "update_guild_welcome_screen",
            "guild_id": config.guild_id,
            "welcome_screen": result,
        }

    # ============================================================================
    # Voice State Handler Methods
    # ============================================================================

    async def _modify_current_user_voice_state(
        self, config: DiscordModifyCurrentUserVoiceStateConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Modify current user's voice state"""
        payload = {"channel_id": config.channel_id}
        if config.suppress is not None:
            payload["suppress"] = config.suppress
        if config.request_to_speak_timestamp is not None:
            payload["request_to_speak_timestamp"] = config.request_to_speak_timestamp

        await self._make_request(
            "PATCH",
            f"/guilds/{config.guild_id}/voice-states/@me",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "update_current_user_voice_state",
            "guild_id": config.guild_id,
            "channel_id": config.channel_id,
            "success": True,
        }

    async def _modify_user_voice_state(
        self, config: DiscordModifyUserVoiceStateConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Modify another user's voice state"""
        payload = {"channel_id": config.channel_id}
        if config.suppress is not None:
            payload["suppress"] = config.suppress

        await self._make_request(
            "PATCH",
            f"/guilds/{config.guild_id}/voice-states/{config.user_id}",
            auth_header,
            json_data=payload,
        )

        return {
            "action": "update_user_voice_state",
            "guild_id": config.guild_id,
            "user_id": config.user_id,
            "channel_id": config.channel_id,
            "success": True,
        }

    # ============================================================================
    # Additional User Handler Methods
    # ============================================================================

    async def _get_current_user_guilds(
        self, config: DiscordGetCurrentUserGuildsConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get current user's guilds"""
        params = {"limit": str(config.limit or 200)}
        if config.before:
            params["before"] = config.before
        if config.after:
            params["after"] = config.after

        result = await self._make_request(
            "GET",
            "/users/@me/guilds",
            auth_header,
            params=params,
        )

        return {
            "action": "list_current_user_guilds",
            "guilds": result,
            "count": len(result) if isinstance(result, list) else 0,
        }

    async def _leave_guild(
        self, config: DiscordLeaveGuildConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Leave a guild"""
        await self._make_request(
            "DELETE",
            f"/users/@me/guilds/{config.guild_id}",
            auth_header,
        )

        return {
            "action": "leave_guild",
            "guild_id": config.guild_id,
            "success": True,
        }

    async def _get_user_connections(self, auth_header: str) -> Dict[str, Any]:
        """Get user's connections"""
        result = await self._make_request(
            "GET",
            "/users/@me/connections",
            auth_header,
        )

        return {
            "action": "list_user_connections",
            "connections": result,
            "count": len(result) if isinstance(result, list) else 0,
        }

    # ============================================================================
    # Guild Integration Handler Methods
    # ============================================================================

    async def _get_guild_integrations(
        self, config: DiscordGetGuildIntegrationsConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Get guild integrations"""
        result = await self._make_request(
            "GET",
            f"/guilds/{config.guild_id}/integrations",
            auth_header,
        )

        return {
            "action": "list_guild_integrations",
            "guild_id": config.guild_id,
            "integrations": result,
            "count": len(result) if isinstance(result, list) else 0,
        }

    async def _delete_guild_integration(
        self, config: DiscordDeleteGuildIntegrationConfig, auth_header: str
    ) -> Dict[str, Any]:
        """Delete a guild integration"""
        await self._make_request(
            "DELETE",
            f"/guilds/{config.guild_id}/integrations/{config.integration_id}",
            auth_header,
        )

        return {
            "action": "delete_guild_integration",
            "guild_id": config.guild_id,
            "integration_id": config.integration_id,
            "success": True,
        }
