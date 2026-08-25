"""
Microsoft Teams automation node (via Microsoft Graph API).

Provides workflow integration with Microsoft Teams for operations across:
- Teams: list joined teams, get, create, update, archive, unarchive
- Channels: list, get, create, update, delete, list members
- Channel messages: list, get, send, reply, list replies
- Chats: list, get, create, list messages, get message, send message, list members
- Members: list, add, remove
- Apps: list installed, install, uninstall
- Tabs: list, add, delete
- Meetings: create online meeting, get online meeting
- Presence: get user presence, get my presence
- Triggers (Microsoft Graph change-notification webhooks via /subscriptions):
  on channel message (per channel), on chat message (per chat), and an advanced
  "on change notification" for any Graph resource (lifecycle, membership, etc.)

Authentication: Microsoft OAuth 2.0 (Microsoft Entra ID), delegated
(authorization_code) only — deliberately. The node's operations are
user-context (many hit /me/* endpoints — joined teams, chats, online meetings,
presence) and sending messages requires delegated permissions, which app-only
(client-credentials) tokens cannot satisfy. Microsoft Graph issues no static
API keys; every request carries an OAuth bearer token.

API Base URL: https://graph.microsoft.com/v1.0
Documentation: https://learn.microsoft.com/en-us/graph/api/resources/teams-api-overview
"""

import logging
import re
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated, Tuple
from urllib.parse import quote
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.microsoft import MICROSOFT_TEAMS_SCOPES
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.core.dynamic_options import load_paginated_options, normalize_search
from nodes.oauth.microsoft_oauth import refresh_access_token, is_token_expired
from utils.ssrf import assert_exact_url_origin

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_API_ORIGIN = "https://graph.microsoft.com"

# Change-notification subscriptions expire; Graph caps message-resource
# subscriptions at ~60 minutes. Renewal is a human follow-up (PATCH /subscriptions).
SUBSCRIPTION_EXPIRY_MINUTES = 55


def _enc(segment: str) -> str:
    """URL-encode an opaque Teams ID for use in a path segment.

    Channel / chat IDs contain ``:`` and ``@`` (e.g. ``19:...@thread.tacv2``)
    and must be percent-encoded so they don't break the path.
    """
    return quote(str(segment), safe="")


def _teams_resource_id(resource: str, key: str) -> Optional[str]:
    """Pull the id following a Graph resource keyword, tolerating both the
    ``key('id')`` form Graph change notifications use (e.g.
    ``teams('t1')/channels('c1')/messages('m1')``) and the plain ``key/id``
    path form. Teams ids contain ``:`` / ``@`` / ``.`` but never ``/``."""
    key = re.escape(key)
    m = re.search(rf"{key}\((?:'([^']*)'|\"([^\"]*)\")\)", resource)
    if m:
        return m.group(1) or m.group(2)
    m = re.search(rf"{key}/([^/()]+)", resource)
    return m.group(1) if m else None


# ============================================================================
# Credential Schema
# ============================================================================


class MicrosoftTeamsOAuthCredential(BaseModel):
    """Microsoft OAuth credential for Teams (via Microsoft Graph).

    Uses the centralized Microsoft OAuth flow — credentials are created
    automatically when the user connects their Microsoft (work/school) account.
    Personal Microsoft accounts are not supported for Teams messaging.
    """

    credential_type: Literal["microsoft_teams_oauth"] = Field(
        "microsoft_teams_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., description="OAuth access token")
    refresh_token: str = Field(..., description="OAuth refresh token for token renewal")
    expires_at: str = Field(..., description="Token expiry timestamp (ISO 8601)")
    email: str = Field(..., description="Microsoft account email address")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "microsoft",
            "x-oauth-scopes": [
                "https://graph.microsoft.com/User.Read",
                "https://graph.microsoft.com/Team.ReadBasic.All",
                "https://graph.microsoft.com/Team.Create",
                "https://graph.microsoft.com/Channel.ReadBasic.All",
                "https://graph.microsoft.com/Channel.Create",
                "https://graph.microsoft.com/Channel.Delete.All",
                "https://graph.microsoft.com/ChannelMessage.Read.All",
                "https://graph.microsoft.com/ChannelMessage.Send",
                "https://graph.microsoft.com/Chat.ReadWrite",
                "https://graph.microsoft.com/ChatMessage.Send",
                "https://graph.microsoft.com/TeamMember.ReadWrite.All",
                "https://graph.microsoft.com/TeamsAppInstallation.ReadWriteForTeam",
                "https://graph.microsoft.com/TeamsTab.ReadWriteForTeam",
                "https://graph.microsoft.com/OnlineMeetings.ReadWrite",
                "https://graph.microsoft.com/Presence.Read.All",
            ],
            "x-credential-url": "https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
            "x-credential-instructions": (
                "Connect your Microsoft work/school account to access Teams via Microsoft Graph. "
                "Personal Microsoft accounts are not supported for Teams messaging."
            ),
        }
    )


MicrosoftTeamsCredential = MicrosoftTeamsOAuthCredential


# Reusable dynamic-options blocks ------------------------------------------------

_TEAM_OPTIONS = {
    "x-resource-type": "teams_team",
    "x-dynamic-options": {
        "field_name": "team_id",
        "placeholder": "Select a team...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste team ID",
    }
}

_CHANNEL_OPTIONS = {
    "x-resource-type": "teams_channel",
    "x-dynamic-options": {
        "field_name": "channel_id",
        "placeholder": "Select a channel...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste channel ID",
    }
}

_CHAT_OPTIONS = {
    "x-resource-type": "teams_chat",
    "x-dynamic-options": {
        "field_name": "chat_id",
        "placeholder": "Select a chat...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste chat ID",
    }
}

_APP_OPTIONS = {
    "x-dynamic-options": {
        "field_name": "app_id",
        "placeholder": "Select an app...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste teamsApp ID",
    }
}

_USER_OPTIONS = {
    "x-dynamic-options": {
        "field_name": "user_id",
        "placeholder": "Select a user...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste user ID",
    }
}

# Members are listed per-team, so the dropdown depends on the chosen team.
_MEMBERSHIP_OPTIONS = {
    "x-dynamic-options": {
        "field_name": "membership_id",
        "placeholder": "Select a member...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste membership ID",
        "depends_on": "team_id",
    }
}

# Channel messages are listed per-channel (which itself depends on the team),
# so the message picker depends on the chosen channel.
_MESSAGE_OPTIONS = {
    "x-dynamic-options": {
        "field_name": "message_id",
        "placeholder": "Select a message...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste message ID",
        "depends_on": "channel_id",
    }
}


# ============================================================================
# Operation Configs — Teams
# ============================================================================


class TeamsListJoinedTeamsConfig(BaseModel):
    """List teams the signed-in user is a member of."""

    operation: Literal["list_joined_teams"] = Field(
        "list_joined_teams",
        json_schema_extra={
            "const": "list_joined_teams",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "List Joined Teams",
        },
        title="List Joined Teams",
    )


class TeamsGetTeamConfig(BaseModel):
    """Retrieve a team's properties and settings."""

    operation: Literal["get_team"] = Field(
        "get_team",
        json_schema_extra={
            "const": "get_team",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "Get Team",
        },
        title="Get Team",
    )
    team_id: str = Field(
        ..., title="Team", description="The team to retrieve",
        json_schema_extra=_TEAM_OPTIONS,
    )


class TeamsCreateTeamConfig(BaseModel):
    """Create a new team (async; returns an operation location)."""

    operation: Literal["create_team"] = Field(
        "create_team",
        json_schema_extra={
            "const": "create_team",
            "x-creates-resource": True,
            "x-resource-type": "teams_team",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "Create Team",
        },
        title="Create Team",
    )
    display_name: str = Field(..., title="Team Name", description="Display name for the new team")
    description: Optional[str] = Field(
        None, title="Description", description="Description for the new team"
    )
    visibility: str = Field(
        "private",
        title="Visibility",
        description="Team visibility",
        json_schema_extra={
            "enum": ["private", "public"],
            "enumNames": ["Private", "Public"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Operation Configs — Channels
# ============================================================================


class TeamsListChannelsConfig(BaseModel):
    """List channels in a team."""

    operation: Literal["list_channels"] = Field(
        "list_channels",
        json_schema_extra={
            "const": "list_channels",
            "ui:hidden": True,
            "x-category": "Channels",
            "x-is-trigger": False,
            "x-display-name": "List Channels",
        },
        title="List Channels",
    )
    team_id: str = Field(
        ..., title="Team", description="The team whose channels to list",
        json_schema_extra=_TEAM_OPTIONS,
    )


class TeamsGetChannelConfig(BaseModel):
    """Retrieve a single channel."""

    operation: Literal["get_channel"] = Field(
        "get_channel",
        json_schema_extra={
            "const": "get_channel",
            "ui:hidden": True,
            "x-category": "Channels",
            "x-is-trigger": False,
            "x-display-name": "Get Channel",
        },
        title="Get Channel",
    )
    team_id: str = Field(
        ..., title="Team", description="The team that owns the channel",
        json_schema_extra=_TEAM_OPTIONS,
    )
    channel_id: str = Field(
        ..., title="Channel", description="The channel to retrieve",
        json_schema_extra=_CHANNEL_OPTIONS,
    )


class TeamsCreateChannelConfig(BaseModel):
    """Create a standard / private / shared channel in a team."""

    operation: Literal["create_channel"] = Field(
        "create_channel",
        json_schema_extra={
            "const": "create_channel",
            "x-creates-resource": True,
            "x-resource-type": "teams_channel",
            "x-resource-id-path": "data.id",
            "ui:hidden": True,
            "x-category": "Channels",
            "x-is-trigger": False,
            "x-display-name": "Create Channel",
        },
        title="Create Channel",
    )
    team_id: str = Field(
        ..., title="Team", description="The team to create the channel in",
        json_schema_extra=_TEAM_OPTIONS,
    )
    display_name: str = Field(..., title="Channel Name", description="Display name for the channel")
    description: Optional[str] = Field(
        None, title="Description", description="Description for the channel"
    )
    membership_type: str = Field(
        "standard",
        title="Membership Type",
        description="Channel membership type",
        json_schema_extra={
            "enum": ["standard", "private", "shared"],
            "enumNames": ["Standard", "Private", "Shared"],
            "x-enum-searchable": True,
        },
    )


class TeamsDeleteChannelConfig(BaseModel):
    """Soft-delete a channel."""

    operation: Literal["delete_channel"] = Field(
        "delete_channel",
        json_schema_extra={
            "const": "delete_channel",
            "ui:hidden": True,
            "x-category": "Channels",
            "x-is-trigger": False,
            "x-display-name": "Delete Channel",
        },
        title="Delete Channel",
    )
    team_id: str = Field(
        ..., title="Team", description="The team that owns the channel",
        json_schema_extra=_TEAM_OPTIONS,
    )
    channel_id: str = Field(
        ..., title="Channel", description="The channel to delete",
        json_schema_extra=_CHANNEL_OPTIONS,
    )


# ============================================================================
# Operation Configs — Channel Messages
# ============================================================================


class TeamsListChannelMessagesConfig(BaseModel):
    """List top-level messages in a channel."""

    operation: Literal["list_channel_messages"] = Field(
        "list_channel_messages",
        json_schema_extra={
            "const": "list_channel_messages",
            "ui:hidden": True,
            "x-category": "Channel Messages",
            "x-is-trigger": False,
            "x-display-name": "List Channel Messages",
        },
        title="List Channel Messages",
    )
    team_id: str = Field(
        ..., title="Team", description="The team that owns the channel",
        json_schema_extra=_TEAM_OPTIONS,
    )
    channel_id: str = Field(
        ..., title="Channel", description="The channel whose messages to list",
        json_schema_extra=_CHANNEL_OPTIONS,
    )
    top: Optional[str] = Field(
        "20", title="Limit", description="Max number of messages to return (1-50)"
    )


class TeamsGetChannelMessageConfig(BaseModel):
    """Retrieve a single channel message."""

    operation: Literal["get_channel_message"] = Field(
        "get_channel_message",
        json_schema_extra={
            "const": "get_channel_message",
            "ui:hidden": True,
            "x-category": "Channel Messages",
            "x-is-trigger": False,
            "x-display-name": "Get Channel Message",
        },
        title="Get Channel Message",
    )
    team_id: str = Field(
        ..., title="Team", description="The team that owns the channel",
        json_schema_extra=_TEAM_OPTIONS,
    )
    channel_id: str = Field(
        ..., title="Channel", description="The channel that owns the message",
        json_schema_extra=_CHANNEL_OPTIONS,
    )
    message_id: str = Field(
        ..., title="Message", description="The message to retrieve",
        json_schema_extra=_MESSAGE_OPTIONS,
    )


class TeamsSendChannelMessageConfig(BaseModel):
    """Post a message to a channel (delegated ChannelMessage.Send)."""

    operation: Literal["send_channel_message"] = Field(
        "send_channel_message",
        json_schema_extra={
            "const": "send_channel_message",
            "ui:hidden": True,
            "x-category": "Channel Messages",
            "x-is-trigger": False,
            "x-display-name": "Send Channel Message",
        },
        title="Send Channel Message",
    )
    team_id: str = Field(
        ..., title="Team", description="The team that owns the channel",
        json_schema_extra=_TEAM_OPTIONS,
    )
    channel_id: str = Field(
        ..., title="Channel", description="The channel to post to",
        json_schema_extra=_CHANNEL_OPTIONS,
    )
    content: str = Field(
        ...,
        title="Message",
        description="Message body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    content_type: str = Field(
        "html",
        title="Content Type",
        description="How the message body is interpreted",
        json_schema_extra={
            "enum": ["html", "text"],
            "enumNames": ["HTML", "Plain Text"],
            "x-enum-searchable": True,
        },
    )


class TeamsReplyChannelMessageConfig(BaseModel):
    """Reply within a channel message thread."""

    operation: Literal["reply_channel_message"] = Field(
        "reply_channel_message",
        json_schema_extra={
            "const": "reply_channel_message",
            "ui:hidden": True,
            "x-category": "Channel Messages",
            "x-is-trigger": False,
            "x-display-name": "Reply to Channel Message",
        },
        title="Reply to Channel Message",
    )
    team_id: str = Field(
        ..., title="Team", description="The team that owns the channel",
        json_schema_extra=_TEAM_OPTIONS,
    )
    channel_id: str = Field(
        ..., title="Channel", description="The channel that owns the message",
        json_schema_extra=_CHANNEL_OPTIONS,
    )
    message_id: str = Field(
        ..., title="Message", description="The message to reply to",
        json_schema_extra=_MESSAGE_OPTIONS,
    )
    content: str = Field(
        ...,
        title="Reply",
        description="Reply body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    content_type: str = Field(
        "html",
        title="Content Type",
        description="How the reply body is interpreted",
        json_schema_extra={
            "enum": ["html", "text"],
            "enumNames": ["HTML", "Plain Text"],
            "x-enum-searchable": True,
        },
    )


class TeamsListChannelMessageRepliesConfig(BaseModel):
    """List replies in a channel message thread."""

    operation: Literal["list_channel_message_replies"] = Field(
        "list_channel_message_replies",
        json_schema_extra={
            "const": "list_channel_message_replies",
            "ui:hidden": True,
            "x-category": "Channel Messages",
            "x-is-trigger": False,
            "x-display-name": "List Channel Message Replies",
        },
        title="List Channel Message Replies",
    )
    team_id: str = Field(
        ..., title="Team", description="The team that owns the channel",
        json_schema_extra=_TEAM_OPTIONS,
    )
    channel_id: str = Field(
        ..., title="Channel", description="The channel that owns the message",
        json_schema_extra=_CHANNEL_OPTIONS,
    )
    message_id: str = Field(
        ..., title="Message", description="The parent message",
        json_schema_extra=_MESSAGE_OPTIONS,
    )


# ============================================================================
# Operation Configs — Chats
# ============================================================================


class TeamsListChatsConfig(BaseModel):
    """List the signed-in user's 1:1 / group / meeting chats."""

    operation: Literal["list_chats"] = Field(
        "list_chats",
        json_schema_extra={
            "const": "list_chats",
            "ui:hidden": True,
            "x-category": "Chats",
            "x-is-trigger": False,
            "x-display-name": "List Chats",
        },
        title="List Chats",
    )
    top: Optional[str] = Field(
        "20", title="Limit", description="Max number of chats to return (1-50)"
    )


class TeamsGetChatConfig(BaseModel):
    """Retrieve a single chat."""

    operation: Literal["get_chat"] = Field(
        "get_chat",
        json_schema_extra={
            "const": "get_chat",
            "ui:hidden": True,
            "x-category": "Chats",
            "x-is-trigger": False,
            "x-display-name": "Get Chat",
        },
        title="Get Chat",
    )
    chat_id: str = Field(
        ..., title="Chat", description="The chat to retrieve",
        json_schema_extra=_CHAT_OPTIONS,
    )


class TeamsCreateChatConfig(BaseModel):
    """Create a new 1:1 or group chat with members."""

    operation: Literal["create_chat"] = Field(
        "create_chat",
        json_schema_extra={
            "const": "create_chat",
            "x-creates-resource": True,
            "x-resource-type": "teams_chat",
            "x-resource-id-path": "data.id",
            "ui:hidden": True,
            "x-category": "Chats",
            "x-is-trigger": False,
            "x-display-name": "Create Chat",
        },
        title="Create Chat",
    )
    chat_type: str = Field(
        "group",
        title="Chat Type",
        description="Type of chat to create",
        json_schema_extra={
            "enum": ["group", "oneOnOne"],
            "enumNames": ["Group", "One-on-One"],
            "x-enum-searchable": True,
        },
    )
    member_emails: str = Field(
        ...,
        title="Member Emails",
        description="Comma-separated user principal names / emails to add to the chat",
    )
    topic: Optional[str] = Field(
        None, title="Topic", description="Chat topic (group chats only)"
    )


class TeamsListChatMessagesConfig(BaseModel):
    """List messages in a chat."""

    operation: Literal["list_chat_messages"] = Field(
        "list_chat_messages",
        json_schema_extra={
            "const": "list_chat_messages",
            "ui:hidden": True,
            "x-category": "Chats",
            "x-is-trigger": False,
            "x-display-name": "List Chat Messages",
        },
        title="List Chat Messages",
    )
    chat_id: str = Field(
        ..., title="Chat", description="The chat whose messages to list",
        json_schema_extra=_CHAT_OPTIONS,
    )
    top: Optional[str] = Field(
        "20", title="Limit", description="Max number of messages to return (1-50)"
    )


class TeamsSendChatMessageConfig(BaseModel):
    """Post a message to an existing chat (delegated ChatMessage.Send)."""

    operation: Literal["send_chat_message"] = Field(
        "send_chat_message",
        json_schema_extra={
            "const": "send_chat_message",
            "ui:hidden": True,
            "x-category": "Chats",
            "x-is-trigger": False,
            "x-display-name": "Send Chat Message",
        },
        title="Send Chat Message",
    )
    chat_id: str = Field(
        ..., title="Chat", description="The chat to post to",
        json_schema_extra=_CHAT_OPTIONS,
    )
    content: str = Field(
        ...,
        title="Message",
        description="Message body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    content_type: str = Field(
        "html",
        title="Content Type",
        description="How the message body is interpreted",
        json_schema_extra={
            "enum": ["html", "text"],
            "enumNames": ["HTML", "Plain Text"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Operation Configs — Members
# ============================================================================


class TeamsListMembersConfig(BaseModel):
    """List members and their roles in a team."""

    operation: Literal["list_team_members"] = Field(
        "list_team_members",
        json_schema_extra={
            "const": "list_team_members",
            "ui:hidden": True,
            "x-category": "Members",
            "x-is-trigger": False,
            "x-display-name": "List Team Members",
        },
        title="List Team Members",
    )
    team_id: str = Field(
        ..., title="Team", description="The team whose members to list",
        json_schema_extra=_TEAM_OPTIONS,
    )


class TeamsAddMemberConfig(BaseModel):
    """Add a member to a team."""

    operation: Literal["add_team_member"] = Field(
        "add_team_member",
        json_schema_extra={
            "const": "add_team_member",
            "ui:hidden": True,
            "x-category": "Members",
            "x-is-trigger": False,
            "x-display-name": "Add Team Member",
        },
        title="Add Team Member",
    )
    team_id: str = Field(
        ..., title="Team", description="The team to add the member to",
        json_schema_extra=_TEAM_OPTIONS,
    )
    user_email: str = Field(
        ..., title="User Email", description="User principal name / email of the member to add"
    )
    is_owner: str = Field(
        "false",
        title="Owner",
        description="Add as a team owner instead of a regular member",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class TeamsRemoveMemberConfig(BaseModel):
    """Remove a member from a team."""

    operation: Literal["remove_team_member"] = Field(
        "remove_team_member",
        json_schema_extra={
            "const": "remove_team_member",
            "ui:hidden": True,
            "x-category": "Members",
            "x-is-trigger": False,
            "x-display-name": "Remove Team Member",
        },
        title="Remove Team Member",
    )
    team_id: str = Field(
        ..., title="Team", description="The team to remove the member from",
        json_schema_extra=_TEAM_OPTIONS,
    )
    membership_id: str = Field(
        ..., title="Member", description="The membership ID of the member to remove",
        json_schema_extra=_MEMBERSHIP_OPTIONS,
    )


# ============================================================================
# Operation Configs — Apps & Tabs
# ============================================================================


class TeamsListInstalledAppsConfig(BaseModel):
    """List apps installed in a team."""

    operation: Literal["list_installed_apps"] = Field(
        "list_installed_apps",
        json_schema_extra={
            "const": "list_installed_apps",
            "ui:hidden": True,
            "x-category": "Apps & Tabs",
            "x-is-trigger": False,
            "x-display-name": "List Installed Apps",
        },
        title="List Installed Apps",
    )
    team_id: str = Field(
        ..., title="Team", description="The team whose installed apps to list",
        json_schema_extra=_TEAM_OPTIONS,
    )


class TeamsInstallAppConfig(BaseModel):
    """Install an app from the catalog into a team."""

    operation: Literal["install_app"] = Field(
        "install_app",
        json_schema_extra={
            "const": "install_app",
            "ui:hidden": True,
            "x-category": "Apps & Tabs",
            "x-is-trigger": False,
            "x-display-name": "Install App",
        },
        title="Install App",
    )
    team_id: str = Field(
        ..., title="Team", description="The team to install the app into",
        json_schema_extra=_TEAM_OPTIONS,
    )
    app_id: str = Field(
        ...,
        title="App",
        description="The teamsApp catalog ID (teamsAppId) of the app to install",
        json_schema_extra=_APP_OPTIONS,
    )


class TeamsListTabsConfig(BaseModel):
    """List tabs pinned to a channel."""

    operation: Literal["list_channel_tabs"] = Field(
        "list_channel_tabs",
        json_schema_extra={
            "const": "list_channel_tabs",
            "ui:hidden": True,
            "x-category": "Apps & Tabs",
            "x-is-trigger": False,
            "x-display-name": "List Channel Tabs",
        },
        title="List Channel Tabs",
    )
    team_id: str = Field(
        ..., title="Team", description="The team that owns the channel",
        json_schema_extra=_TEAM_OPTIONS,
    )
    channel_id: str = Field(
        ..., title="Channel", description="The channel whose tabs to list",
        json_schema_extra=_CHANNEL_OPTIONS,
    )


class TeamsAddTabConfig(BaseModel):
    """Pin a configured tab to a channel."""

    operation: Literal["add_channel_tab"] = Field(
        "add_channel_tab",
        json_schema_extra={
            "const": "add_channel_tab",
            "ui:hidden": True,
            "x-category": "Apps & Tabs",
            "x-is-trigger": False,
            "x-display-name": "Add Channel Tab",
        },
        title="Add Channel Tab",
    )
    team_id: str = Field(
        ..., title="Team", description="The team that owns the channel",
        json_schema_extra=_TEAM_OPTIONS,
    )
    channel_id: str = Field(
        ..., title="Channel", description="The channel to pin the tab to",
        json_schema_extra=_CHANNEL_OPTIONS,
    )
    display_name: str = Field(..., title="Tab Name", description="Display name for the tab")
    app_id: str = Field(
        ...,
        title="App",
        description="The teamsApp catalog ID (teamsAppId) backing the tab",
        json_schema_extra=_APP_OPTIONS,
    )
    content_url: Optional[str] = Field(
        None, title="Content URL", description="The URL the tab displays (teamsTabConfiguration)"
    )


# ============================================================================
# Operation Configs — Meetings & Presence
# ============================================================================


class TeamsCreateMeetingConfig(BaseModel):
    """Create a Teams online meeting and get the join URL."""

    operation: Literal["create_online_meeting"] = Field(
        "create_online_meeting",
        json_schema_extra={
            "const": "create_online_meeting",
            "ui:hidden": True,
            "x-category": "Meetings",
            "x-is-trigger": False,
            "x-display-name": "Create Online Meeting",
        },
        title="Create Online Meeting",
    )
    subject: str = Field(..., title="Subject", description="Meeting subject / title")
    start_datetime: Optional[str] = Field(
        None, title="Start Time", description="Meeting start in ISO 8601 (e.g. 2026-07-01T10:00:00Z)"
    )
    end_datetime: Optional[str] = Field(
        None, title="End Time", description="Meeting end in ISO 8601 (e.g. 2026-07-01T11:00:00Z)"
    )


class TeamsGetMeetingConfig(BaseModel):
    """Retrieve an online meeting's details."""

    operation: Literal["get_online_meeting"] = Field(
        "get_online_meeting",
        json_schema_extra={
            "const": "get_online_meeting",
            "ui:hidden": True,
            "x-category": "Meetings",
            "x-is-trigger": False,
            "x-display-name": "Get Online Meeting",
        },
        title="Get Online Meeting",
    )
    meeting_id: str = Field(
        ..., title="Meeting ID", description="The online meeting ID to retrieve"
    )


class TeamsGetPresenceConfig(BaseModel):
    """Get a user's availability / activity (e.g. Available, Busy)."""

    operation: Literal["get_user_presence"] = Field(
        "get_user_presence",
        json_schema_extra={
            "const": "get_user_presence",
            "ui:hidden": True,
            "x-category": "Presence",
            "x-is-trigger": False,
            "x-display-name": "Get User Presence",
        },
        title="Get User Presence",
    )
    user_id: str = Field(
        ..., title="User", description="The user whose presence to fetch",
        json_schema_extra=_USER_OPTIONS,
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


def _webhook_url_field() -> Any:
    return Field(
        default=None,
        title="Webhook URL",
        description="Microsoft Graph posts change notifications here. Registered automatically when you connect credentials.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )


class _TeamsWebhookTrigger(BaseModel):
    """Shared bookkeeping fields for Teams change-notification triggers.

    Every Teams trigger registers a Microsoft Graph ``/subscriptions`` webhook;
    the concrete subclasses differ only in which resource they subscribe to
    (a specific channel, a specific chat, or an arbitrary Graph resource)."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class TeamsOnChannelMessageConfig(_TeamsWebhookTrigger):
    """Fire when a message is posted in a specific channel (like Slack's
    "on channel message"). Subscribes to that channel's messages resource."""

    operation: Literal["on_channel_message"] = Field(
        "on_channel_message",
        json_schema_extra={
            "const": "on_channel_message",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Channel Message",
        },
        title="On Channel Message",
    )
    team_id: str = Field(
        ..., title="Team", description="The team that owns the channel to watch",
        json_schema_extra=_TEAM_OPTIONS,
    )
    channel_id: str = Field(
        ..., title="Channel", description="The channel to watch for new/updated messages",
        json_schema_extra=_CHANNEL_OPTIONS,
    )
    webhook_url: Optional[str] = _webhook_url_field()


class TeamsOnChatMessageConfig(_TeamsWebhookTrigger):
    """Fire when a message is posted in a specific chat (1:1 or group DM).
    Subscribes to that chat's messages resource."""

    operation: Literal["on_chat_message"] = Field(
        "on_chat_message",
        json_schema_extra={
            "const": "on_chat_message",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Chat Message",
        },
        title="On Chat Message",
    )
    chat_id: str = Field(
        ..., title="Chat", description="The chat to watch for new/updated messages",
        json_schema_extra=_CHAT_OPTIONS,
    )
    webhook_url: Optional[str] = _webhook_url_field()


class TeamsSubscriptionTriggerConfig(_TeamsWebhookTrigger):
    """Advanced: subscribe to any Microsoft Graph change-notification resource
    (e.g. team/channel/membership lifecycle, presence) by pasting the resource."""

    operation: Literal["on_change_notification"] = Field(
        "on_change_notification",
        json_schema_extra={
            "const": "on_change_notification",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Change Notification (Advanced)",
        },
        title="On Change Notification",
    )
    resource: str = Field(
        "/me/chats/getAllMessages",
        title="Resource",
        description="Any Graph change-notification resource, e.g. teams/{id}/channels/{id}/messages or chats/{id}/messages",
    )
    webhook_url: Optional[str] = _webhook_url_field()


# ============================================================================
# Operation Configs — additional coverage
# ============================================================================


class TeamsUpdateTeamConfig(BaseModel):
    """Update a team's properties (PATCH)."""

    operation: Literal["update_team"] = Field(
        "update_team",
        json_schema_extra={
            "const": "update_team",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "Update Team",
        },
        title="Update Team",
    )
    team_id: str = Field(
        ..., title="Team", description="The team to update", json_schema_extra=_TEAM_OPTIONS
    )
    body: str = Field(
        ...,
        title="Update JSON",
        description='Team fields to update, e.g. {"description": "New desc", "memberSettings": {"allowCreateUpdateChannels": true}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class TeamsArchiveTeamConfig(BaseModel):
    """Archive a team (read-only for members; POST /archive)."""

    operation: Literal["archive_team"] = Field(
        "archive_team",
        json_schema_extra={
            "const": "archive_team",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "Archive Team",
        },
        title="Archive Team",
    )
    team_id: str = Field(
        ..., title="Team", description="The team to archive", json_schema_extra=_TEAM_OPTIONS
    )


class TeamsUnarchiveTeamConfig(BaseModel):
    """Restore an archived team (POST /unarchive)."""

    operation: Literal["unarchive_team"] = Field(
        "unarchive_team",
        json_schema_extra={
            "const": "unarchive_team",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "Unarchive Team",
        },
        title="Unarchive Team",
    )
    team_id: str = Field(
        ..., title="Team", description="The team to unarchive", json_schema_extra=_TEAM_OPTIONS
    )


class TeamsUpdateChannelConfig(BaseModel):
    """Update a channel's properties (PATCH)."""

    operation: Literal["update_channel"] = Field(
        "update_channel",
        json_schema_extra={
            "const": "update_channel",
            "ui:hidden": True,
            "x-category": "Channels",
            "x-is-trigger": False,
            "x-display-name": "Update Channel",
        },
        title="Update Channel",
    )
    team_id: str = Field(
        ..., title="Team", description="The team that owns the channel",
        json_schema_extra=_TEAM_OPTIONS,
    )
    channel_id: str = Field(
        ..., title="Channel", description="The channel to update",
        json_schema_extra=_CHANNEL_OPTIONS,
    )
    body: str = Field(
        ...,
        title="Update JSON",
        description='Channel fields to update, e.g. {"displayName": "Renamed", "description": "..."}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class TeamsListChannelMembersConfig(BaseModel):
    """List the members of a channel (private/shared channels)."""

    operation: Literal["list_channel_members"] = Field(
        "list_channel_members",
        json_schema_extra={
            "const": "list_channel_members",
            "ui:hidden": True,
            "x-category": "Channels",
            "x-is-trigger": False,
            "x-display-name": "List Channel Members",
        },
        title="List Channel Members",
    )
    team_id: str = Field(
        ..., title="Team", description="The team that owns the channel",
        json_schema_extra=_TEAM_OPTIONS,
    )
    channel_id: str = Field(
        ..., title="Channel", description="The channel whose members to list",
        json_schema_extra=_CHANNEL_OPTIONS,
    )


class TeamsGetChatMessageConfig(BaseModel):
    """Fetch a single chat message."""

    operation: Literal["get_chat_message"] = Field(
        "get_chat_message",
        json_schema_extra={
            "const": "get_chat_message",
            "ui:hidden": True,
            "x-category": "Chats",
            "x-is-trigger": False,
            "x-display-name": "Get Chat Message",
        },
        title="Get Chat Message",
    )
    chat_id: str = Field(
        ..., title="Chat", description="The chat that owns the message",
        json_schema_extra=_CHAT_OPTIONS,
    )
    message_id: str = Field(
        ..., title="Message ID", description="ID of the chat message to fetch"
    )


class TeamsListChatMembersConfig(BaseModel):
    """List the members of a chat."""

    operation: Literal["list_chat_members"] = Field(
        "list_chat_members",
        json_schema_extra={
            "const": "list_chat_members",
            "ui:hidden": True,
            "x-category": "Chats",
            "x-is-trigger": False,
            "x-display-name": "List Chat Members",
        },
        title="List Chat Members",
    )
    chat_id: str = Field(
        ..., title="Chat", description="The chat whose members to list",
        json_schema_extra=_CHAT_OPTIONS,
    )


class TeamsDeleteChannelTabConfig(BaseModel):
    """Remove a tab from a channel."""

    operation: Literal["delete_channel_tab"] = Field(
        "delete_channel_tab",
        json_schema_extra={
            "const": "delete_channel_tab",
            "ui:hidden": True,
            "x-category": "Tabs",
            "x-is-trigger": False,
            "x-display-name": "Delete Channel Tab",
        },
        title="Delete Channel Tab",
    )
    team_id: str = Field(
        ..., title="Team", description="The team that owns the channel",
        json_schema_extra=_TEAM_OPTIONS,
    )
    channel_id: str = Field(
        ..., title="Channel", description="The channel that owns the tab",
        json_schema_extra=_CHANNEL_OPTIONS,
    )
    tab_id: str = Field(..., title="Tab ID", description="ID of the tab to remove")


class TeamsUninstallAppConfig(BaseModel):
    """Uninstall an app from a team."""

    operation: Literal["uninstall_app"] = Field(
        "uninstall_app",
        json_schema_extra={
            "const": "uninstall_app",
            "ui:hidden": True,
            "x-category": "Apps",
            "x-is-trigger": False,
            "x-display-name": "Uninstall App",
        },
        title="Uninstall App",
    )
    team_id: str = Field(
        ..., title="Team", description="The team to uninstall the app from",
        json_schema_extra=_TEAM_OPTIONS,
    )
    installation_id: str = Field(
        ..., title="Installation ID",
        description="The teamsAppInstallation ID to remove (from List Installed Apps)",
    )


class TeamsGetMyPresenceConfig(BaseModel):
    """Get the signed-in user's presence."""

    operation: Literal["get_my_presence"] = Field(
        "get_my_presence",
        json_schema_extra={
            "const": "get_my_presence",
            "ui:hidden": True,
            "x-category": "Presence",
            "x-is-trigger": False,
            "x-display-name": "Get My Presence",
        },
        title="Get My Presence",
    )


# ============================================================================
# Discriminated Union
# ============================================================================


MicrosoftTeamsConfig = Annotated[
    Union[
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
    ],
    Discriminator("operation"),
]


class MicrosoftTeamsNodeConfig(NodeConfig[MicrosoftTeamsConfig, MicrosoftTeamsCredential]):
    """Full configuration for the Microsoft Teams node including credentials."""

    pass


# ============================================================================
# HTTP Request Helper
# ============================================================================


def _comma_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


async def _graph_request(
    access_token: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Microsoft Graph request and return a structured result."""
    url = endpoint if endpoint.startswith("http") else f"{GRAPH_API_BASE}{endpoint}"
    # Opaque page tokens may be fully-qualified Graph nextLink URLs. Validate
    # the parsed origin before attaching the OAuth bearer token so a crafted
    # cursor cannot exfiltrate it to another host.
    assert_exact_url_origin(url, GRAPH_API_ORIGIN)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    if json_body is not None:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    error_obj = err.get("error", {})
                    message = (
                        error_obj.get("message")
                        if isinstance(error_obj, dict)
                        else err.get("message", str(err))
                    )
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[MicrosoftTeamsNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }

            location = response.headers.get("Location")
            # Async 202 creates (e.g. POST /teams) return the NEW resource id in
            # Content-Location (`/teams('{id}')`), while Location points only at
            # the teamsAsyncOperation. Capture both and surface the id so
            # created-resource tracking (x-resource-id-path: data.id) resolves.
            content_location = response.headers.get("Content-Location")
            if response.status_code == 204 or not response.content:
                data: Any = {"success": True}
                if location:
                    data["operation_location"] = location
                if content_location:
                    data["content_location"] = content_location
                    match = re.search(r"\('([^']+)'\)", content_location)
                    if match:
                        data["id"] = match.group(1)
            else:
                try:
                    payload = response.json()
                    # Graph collections wrap items in {"value": [...]}.
                    data = payload.get("value", payload) if isinstance(payload, dict) else payload
                except Exception:
                    data = {"raw": response.text}
                if location and isinstance(data, dict):
                    data["operation_location"] = location
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[MicrosoftTeamsNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


def _message_body(content: str, content_type: str) -> Dict[str, Any]:
    return {"body": {"contentType": content_type, "content": content}}


# ============================================================================
# Node Implementation
# ============================================================================


class MicrosoftTeamsNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Microsoft Teams automation node (via Microsoft Graph API)."""

    edit_examples = [
        "Send a message to a Teams channel when a deal closes",
        "List all teams I'm a member of",
        "Create a Teams online meeting and share the join link",
        "Reply in a channel thread with an update",
        "Trigger a workflow when a new message arrives in a chat",
    ]

    #: OAuth scope requirements per operation (nodes/scopes/microsoft.py).
    scope_registry = MICROSOFT_TEAMS_SCOPES
    connection_evidence = ConnectionEvidence(
        field="team_id",
        noun="teams",
    )

    @classmethod
    def get_config_model(cls):
        return MicrosoftTeamsNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns / triggers)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.microsoft_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="microsoft",
        )

    # ------------------------------------------------------------------
    # OAuth token refresh
    # ------------------------------------------------------------------
    async def _ensure_fresh_token(self, credentials: MicrosoftTeamsOAuthCredential) -> str:
        """Return a valid Microsoft Teams access token, refreshing + persisting if expired."""
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token

        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            caller_path="execute",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    # ------------------------------------------------------------------
    # Dynamic options (teams / channels / chats)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        access_token = await cls._resolve_options_token(credential_data)
        if not access_token:
            return {"options": [], "next_page_token": None}
        search = normalize_search(search)
        context = context or {}

        if field_name == "team_id":
            return await cls._load_team_options(access_token, page_token, search)
        if field_name == "channel_id":
            team_id = context.get("team_id")
            if not team_id:
                return {"options": [], "next_page_token": None}
            return await cls._load_channel_options(access_token, team_id, page_token, search)
        if field_name == "chat_id":
            return await cls._load_chat_options(access_token, page_token, search)
        if field_name == "membership_id":
            team_id = context.get("team_id")
            if not team_id:
                return {"options": [], "next_page_token": None}
            return await cls._load_membership_options(access_token, team_id, page_token, search)
        if field_name == "message_id":
            team_id = context.get("team_id")
            channel_id = context.get("channel_id")
            if not team_id or not channel_id:
                return {"options": [], "next_page_token": None}
            return await cls._load_message_options(
                access_token, team_id, channel_id, page_token, search
            )
        if field_name == "app_id":
            return await cls._load_app_options(access_token, page_token, search)
        if field_name == "user_id":
            return await cls._load_user_options(access_token, page_token, search)
        return {"options": [], "next_page_token": None}

    @classmethod
    async def _resolve_options_token(cls, credential_data: Dict[str, Any]) -> Optional[str]:
        access_token = credential_data.get("access_token")
        if not access_token:
            return None
        expires_at = credential_data.get("expires_at")
        if expires_at and is_token_expired(expires_at):
            refresh_token = credential_data.get("refresh_token")
            if refresh_token:
                try:
                    new_tokens = await refresh_access_token(refresh_token)
                    access_token = new_tokens.access_token
                except Exception as e:
                    logger.error(f"[MicrosoftTeamsNode] Token refresh failed: {e}")
        return access_token

    @classmethod
    async def _load_team_options(
        cls, access_token: str, page_token: Optional[str], search: Optional[str]
    ) -> Dict[str, Any]:
        async def fetch_page(
            cursor: Optional[str],
        ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            endpoint = cursor or "/me/joinedTeams"
            result = await _graph_request(
                access_token, "GET", endpoint, action_name="list_joined_teams"
            )
            if result.get("status") != "success":
                return [], None
            data = result.get("data") or []
            teams = data if isinstance(data, list) else data.get("value") or []
            options = [
                {"label": t.get("displayName") or t.get("id"), "value": t.get("id")}
                for t in teams
                if isinstance(t, dict) and t.get("id")
            ]
            return options, None

        return await load_paginated_options(
            fetch_page, page_token=page_token, search=search, log_label="teams_team"
        )

    @classmethod
    async def _load_channel_options(
        cls, access_token: str, team_id: str, page_token: Optional[str], search: Optional[str]
    ) -> Dict[str, Any]:
        async def fetch_page(
            cursor: Optional[str],
        ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            result = await _graph_request(
                access_token, "GET", f"/teams/{_enc(team_id)}/channels",
                action_name="list_channels",
            )
            if result.get("status") != "success":
                return [], None
            data = result.get("data") or []
            channels = data if isinstance(data, list) else data.get("value") or []
            options = [
                {"label": c.get("displayName") or c.get("id"), "value": c.get("id")}
                for c in channels
                if isinstance(c, dict) and c.get("id")
            ]
            return options, None

        return await load_paginated_options(
            fetch_page, page_token=page_token, search=search, log_label="teams_channel"
        )

    @classmethod
    async def _load_chat_options(
        cls, access_token: str, page_token: Optional[str], search: Optional[str]
    ) -> Dict[str, Any]:
        async def fetch_page(
            cursor: Optional[str],
        ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            endpoint = cursor or "/me/chats?$top=50"
            result = await _graph_request(
                access_token, "GET", endpoint, action_name="list_chats"
            )
            if result.get("status") != "success":
                return [], None
            data = result.get("data") or []
            chats = data if isinstance(data, list) else data.get("value") or []
            options = []
            for c in chats:
                if not isinstance(c, dict) or not c.get("id"):
                    continue
                label = c.get("topic") or c.get("chatType") or c.get("id")
                options.append({"label": label, "value": c.get("id")})
            return options, None

        return await load_paginated_options(
            fetch_page, page_token=page_token, search=search, log_label="teams_chat"
        )

    @classmethod
    async def _load_membership_options(
        cls, access_token: str, team_id: str, page_token: Optional[str], search: Optional[str]
    ) -> Dict[str, Any]:
        async def fetch_page(
            cursor: Optional[str],
        ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            result = await _graph_request(
                access_token, "GET", f"/teams/{_enc(team_id)}/members",
                action_name="list_team_members",
            )
            if result.get("status") != "success":
                return [], None
            data = result.get("data") or []
            members = data if isinstance(data, list) else data.get("value") or []
            options = []
            for m in members:
                if not isinstance(m, dict) or not m.get("id"):
                    continue
                label = m.get("displayName") or m.get("email") or m.get("id")
                options.append({"label": label, "value": m.get("id")})
            return options, None

        return await load_paginated_options(
            fetch_page, page_token=page_token, search=search, log_label="teams_membership"
        )

    @classmethod
    async def _load_message_options(
        cls,
        access_token: str,
        team_id: str,
        channel_id: str,
        page_token: Optional[str],
        search: Optional[str],
    ) -> Dict[str, Any]:
        async def fetch_page(
            cursor: Optional[str],
        ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            result = await _graph_request(
                access_token, "GET",
                f"/teams/{_enc(team_id)}/channels/{_enc(channel_id)}/messages",
                params={"$top": "50"}, action_name="list_channel_messages",
            )
            if result.get("status") != "success":
                return [], None
            data = result.get("data") or []
            messages = data if isinstance(data, list) else data.get("value") or []
            options = []
            for msg in messages:
                if not isinstance(msg, dict) or not msg.get("id"):
                    continue
                body = msg.get("body") or {}
                preview = body.get("content") if isinstance(body, dict) else None
                label = (preview or msg.get("subject") or msg.get("id"))[:80]
                options.append({"label": label, "value": msg.get("id")})
            return options, None

        return await load_paginated_options(
            fetch_page, page_token=page_token, search=search, log_label="teams_message"
        )

    @classmethod
    async def _load_app_options(
        cls, access_token: str, page_token: Optional[str], search: Optional[str]
    ) -> Dict[str, Any]:
        async def fetch_page(
            cursor: Optional[str],
        ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            endpoint = cursor or "/appCatalogs/teamsApps?$top=50"
            result = await _graph_request(
                access_token, "GET", endpoint, action_name="list_teams_apps"
            )
            if result.get("status") != "success":
                return [], None
            data = result.get("data") or []
            apps = data if isinstance(data, list) else data.get("value") or []
            options = [
                {"label": a.get("displayName") or a.get("id"), "value": a.get("id")}
                for a in apps
                if isinstance(a, dict) and a.get("id")
            ]
            return options, None

        return await load_paginated_options(
            fetch_page, page_token=page_token, search=search, log_label="teams_app"
        )

    @classmethod
    async def _load_user_options(
        cls, access_token: str, page_token: Optional[str], search: Optional[str]
    ) -> Dict[str, Any]:
        async def fetch_page(
            cursor: Optional[str],
        ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            endpoint = cursor or "/users?$top=50&$select=id,displayName,userPrincipalName"
            result = await _graph_request(
                access_token, "GET", endpoint, action_name="list_users"
            )
            if result.get("status") != "success":
                return [], None
            data = result.get("data") or []
            users = data if isinstance(data, list) else data.get("value") or []
            options = []
            for u in users:
                if not isinstance(u, dict) or not u.get("id"):
                    continue
                label = u.get("displayName") or u.get("userPrincipalName") or u.get("id")
                options.append({"label": label, "value": u.get("id")})
            return options, None

        return await load_paginated_options(
            fetch_page, page_token=page_token, search=search, log_label="teams_user"
        )

    # ------------------------------------------------------------------
    # Webhook (Graph subscription) registration
    # ------------------------------------------------------------------
    @staticmethod
    def _subscription_target(config: Dict[str, Any]) -> Tuple[str, str]:
        """Map a trigger config to its Graph subscription (resource, changeType).

        The concrete message triggers derive the resource from their selected
        channel / chat; the advanced trigger passes the raw resource through."""
        op = config.get("operation")
        if op == "on_channel_message":
            team, channel = config.get("team_id"), config.get("channel_id")
            if not team or not channel:
                raise ValueError(
                    "Team and Channel are required for the On Channel Message trigger"
                )
            return f"teams/{team}/channels/{channel}/messages", "created,updated"
        if op == "on_chat_message":
            chat = config.get("chat_id")
            if not chat:
                raise ValueError("Chat is required for the On Chat Message trigger")
            return f"chats/{chat}/messages", "created,updated"
        # on_change_notification (advanced) — pass the raw resource through.
        return (config.get("resource") or "/me/chats/getAllMessages"), "created,updated"

    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "team_id": (config or {}).get("team_id"),
            "channel_id": (config or {}).get("channel_id"),
            "chat_id": (config or {}).get("chat_id"),
            "resource": (config or {}).get("resource"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        from datetime import datetime, timedelta, timezone
        import hashlib

        access_token = await cls._resolve_options_token(credential)
        if not access_token:
            raise ValueError("A connected Microsoft account is required to register the trigger")
        resource, change_type = cls._subscription_target(config or {})
        # Graph validates clientState back on every notification (our signing secret).
        secret = hashlib.sha256(f"{node_id}:{webhook_url}".encode()).hexdigest()[:32]
        expires = (
            datetime.now(timezone.utc) + timedelta(minutes=SUBSCRIPTION_EXPIRY_MINUTES)
        ).isoformat()
        result = await _graph_request(
            access_token,
            "POST",
            "/subscriptions",
            json_body={
                "changeType": change_type,
                "notificationUrl": webhook_url,
                "resource": resource,
                "expirationDateTime": expires,
                "clientState": secret,
            },
            action_name="create_subscription",
        )
        if result.get("status") != "success":
            raise ValueError(
                f"Microsoft Graph subscription failed: {result.get('error')}"
            )
        data = result.get("data") or {}
        external_id = data.get("id") if isinstance(data, dict) else None
        return {
            "external_webhook_id": str(external_id) if external_id else None,
            "signing_secret": secret,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        if not external_id or not credential:
            return
        access_token = await cls._resolve_options_token(credential)
        if not access_token:
            return
        await _graph_request(
            access_token,
            "DELETE",
            f"/subscriptions/{_enc(external_id)}",
            action_name="delete_subscription",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Graph echoes the registered clientState in each notification payload.

        Validate it against the secret stored at registration. If no secret is
        stored yet, the trigger isn't armed — accept (e.g. the validation handshake).
        """
        import json

        secret = (config or {}).get("signing_secret")
        if not secret:
            return True
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return False
        notifications = payload.get("value")
        if not isinstance(notifications, list) or not notifications:
            return False
        return all(n.get("clientState") == secret for n in notifications)

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """A Graph change notification (channel/chat message) → the human's turn
        for a directly-wired agent, with the reply ids surfaced VERBATIM in the
        exact form the send/reply tools accept, keyed to a stable per-conversation
        id (chat id for chats; team:channel for channels).

        This node registers 'basic' subscriptions (no ``includeResourceData``),
        so a notification carries only the resource PATH + message id — never the
        body or sender. We therefore hand the agent the ids and point it at the
        matching get_* tool to fetch the text (we never fabricate a body). Non-
        message notifications (membership/lifecycle/presence, incl. the advanced
        on_change_notification trigger) don't parse and fall back to raw JSON."""
        notifications = output.get("value") if isinstance(output, dict) else None
        if not isinstance(notifications, list):
            return super().resolve_agent_event(output)
        for n in notifications:
            if not isinstance(n, dict):
                continue
            resource = n.get("resource") or ""
            message_id = _teams_resource_id(resource, "messages")
            if not message_id and "/messages" in resource:
                # Rich/encrypted notifications can carry the id only in resourceData.
                rd = n.get("resourceData")
                message_id = rd.get("id") if isinstance(rd, dict) else None
            if not message_id:
                continue
            change = n.get("changeType") or "created"
            team_id = _teams_resource_id(resource, "teams")
            channel_id = _teams_resource_id(resource, "channels")
            chat_id = _teams_resource_id(resource, "chats")
            if team_id and channel_id:
                text = (
                    f"New Microsoft Teams channel message ({change}) — "
                    f"team {team_id}, channel {channel_id}, message {message_id}.\n"
                    "The notification does not include the message text; fetch it with "
                    f"get_channel_message (team_id={team_id}, channel_id={channel_id}, "
                    f"message_id={message_id}).\n"
                    "To reply in this thread, call reply_channel_message with "
                    f"team_id={team_id}, channel_id={channel_id}, message_id={message_id} "
                    "(pass these ids from the trigger event exactly)."
                )
                return {"text": text, "conversation_key": f"{team_id}:{channel_id}"}
            if chat_id:
                text = (
                    f"New Microsoft Teams chat message ({change}) — "
                    f"chat {chat_id}, message {message_id}.\n"
                    "The notification does not include the message text; fetch it with "
                    f"get_chat_message (chat_id={chat_id}, message_id={message_id}).\n"
                    f"To reply, call send_chat_message with chat_id={chat_id} "
                    "(pass this chat id from the trigger event exactly)."
                )
                return {"text": text, "conversation_key": chat_id}
        return super().resolve_agent_event(output)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, MicrosoftTeamsNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(
            op,
            (
                TeamsOnChannelMessageConfig,
                TeamsOnChatMessageConfig,
                TeamsSubscriptionTriggerConfig,
            ),
        ):
            data = {**inputs, "webhook_url": op.webhook_url}
            if isinstance(op, TeamsSubscriptionTriggerConfig):
                data["resource"] = op.resource
            return {
                "status": "success",
                "action": op.operation,
                "data": data,
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Connect your Microsoft account in the node's credentials tab."
            )

        access_token = await self._ensure_fresh_token(credentials)

        handlers = {
            "list_joined_teams": self._list_joined_teams,
            "get_team": self._get_team,
            "create_team": self._create_team,
            "list_channels": self._list_channels,
            "get_channel": self._get_channel,
            "create_channel": self._create_channel,
            "delete_channel": self._delete_channel,
            "list_channel_messages": self._list_channel_messages,
            "get_channel_message": self._get_channel_message,
            "send_channel_message": self._send_channel_message,
            "reply_channel_message": self._reply_channel_message,
            "list_channel_message_replies": self._list_channel_message_replies,
            "list_chats": self._list_chats,
            "get_chat": self._get_chat,
            "create_chat": self._create_chat,
            "list_chat_messages": self._list_chat_messages,
            "send_chat_message": self._send_chat_message,
            "list_team_members": self._list_team_members,
            "add_team_member": self._add_team_member,
            "remove_team_member": self._remove_team_member,
            "list_installed_apps": self._list_installed_apps,
            "install_app": self._install_app,
            "list_channel_tabs": self._list_channel_tabs,
            "add_channel_tab": self._add_channel_tab,
            "create_online_meeting": self._create_online_meeting,
            "get_online_meeting": self._get_online_meeting,
            "get_user_presence": self._get_user_presence,
            "update_team": self._update_team,
            "archive_team": self._archive_team,
            "unarchive_team": self._unarchive_team,
            "update_channel": self._update_channel,
            "list_channel_members": self._list_channel_members,
            "get_chat_message": self._get_chat_message,
            "list_chat_members": self._list_chat_members,
            "delete_channel_tab": self._delete_channel_tab,
            "uninstall_app": self._uninstall_app,
            "get_my_presence": self._get_my_presence,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, access_token)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers — Teams
    # ------------------------------------------------------------------
    async def _list_joined_teams(self, c: TeamsListJoinedTeamsConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(token, "GET", "/me/joinedTeams", action_name="list_joined_teams")

    async def _get_team(self, c: TeamsGetTeamConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET", f"/teams/{_enc(c.team_id)}", action_name="get_team"
        )

    async def _create_team(self, c: TeamsCreateTeamConfig, token: str) -> Dict[str, Any]:
        body = {
            "template@odata.bind": "https://graph.microsoft.com/v1.0/teamsTemplates('standard')",
            "displayName": c.display_name,
            "description": c.description,
            "visibility": c.visibility,
        }
        return await _graph_request(
            token, "POST", "/teams", json_body=body, action_name="create_team"
        )

    # ------------------------------------------------------------------
    # Handlers — Channels
    # ------------------------------------------------------------------
    async def _list_channels(self, c: TeamsListChannelsConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET", f"/teams/{_enc(c.team_id)}/channels", action_name="list_channels"
        )

    async def _get_channel(self, c: TeamsGetChannelConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET", f"/teams/{_enc(c.team_id)}/channels/{_enc(c.channel_id)}",
            action_name="get_channel",
        )

    async def _create_channel(self, c: TeamsCreateChannelConfig, token: str) -> Dict[str, Any]:
        body = {
            "displayName": c.display_name,
            "description": c.description,
            "membershipType": c.membership_type,
        }
        return await _graph_request(
            token, "POST", f"/teams/{_enc(c.team_id)}/channels", json_body=body,
            action_name="create_channel",
        )

    async def _delete_channel(self, c: TeamsDeleteChannelConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "DELETE", f"/teams/{_enc(c.team_id)}/channels/{_enc(c.channel_id)}",
            action_name="delete_channel",
        )

    # ------------------------------------------------------------------
    # Handlers — Channel Messages
    # ------------------------------------------------------------------
    async def _list_channel_messages(
        self, c: TeamsListChannelMessagesConfig, token: str
    ) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET", f"/teams/{_enc(c.team_id)}/channels/{_enc(c.channel_id)}/messages",
            params={"$top": c.top}, action_name="list_channel_messages",
        )

    async def _get_channel_message(
        self, c: TeamsGetChannelMessageConfig, token: str
    ) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET",
            f"/teams/{_enc(c.team_id)}/channels/{_enc(c.channel_id)}/messages/{_enc(c.message_id)}",
            action_name="get_channel_message",
        )

    async def _send_channel_message(
        self, c: TeamsSendChannelMessageConfig, token: str
    ) -> Dict[str, Any]:
        return await _graph_request(
            token, "POST", f"/teams/{_enc(c.team_id)}/channels/{_enc(c.channel_id)}/messages",
            json_body=_message_body(c.content, c.content_type),
            action_name="send_channel_message",
        )

    async def _reply_channel_message(
        self, c: TeamsReplyChannelMessageConfig, token: str
    ) -> Dict[str, Any]:
        return await _graph_request(
            token, "POST",
            f"/teams/{_enc(c.team_id)}/channels/{_enc(c.channel_id)}/messages/{_enc(c.message_id)}/replies",
            json_body=_message_body(c.content, c.content_type),
            action_name="reply_channel_message",
        )

    async def _list_channel_message_replies(
        self, c: TeamsListChannelMessageRepliesConfig, token: str
    ) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET",
            f"/teams/{_enc(c.team_id)}/channels/{_enc(c.channel_id)}/messages/{_enc(c.message_id)}/replies",
            action_name="list_channel_message_replies",
        )

    # ------------------------------------------------------------------
    # Handlers — Chats
    # ------------------------------------------------------------------
    async def _list_chats(self, c: TeamsListChatsConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET", "/me/chats", params={"$top": c.top}, action_name="list_chats"
        )

    async def _get_chat(self, c: TeamsGetChatConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET", f"/chats/{_enc(c.chat_id)}", action_name="get_chat"
        )

    async def _create_chat(self, c: TeamsCreateChatConfig, token: str) -> Dict[str, Any]:
        members = [
            {
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "roles": ["owner"],
                "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{email}')",
            }
            for email in _comma_list(c.member_emails)
        ]
        body: Dict[str, Any] = {"chatType": c.chat_type, "members": members}
        if c.chat_type == "group" and c.topic:
            body["topic"] = c.topic
        return await _graph_request(
            token, "POST", "/chats", json_body=body, action_name="create_chat"
        )

    async def _list_chat_messages(
        self, c: TeamsListChatMessagesConfig, token: str
    ) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET", f"/chats/{_enc(c.chat_id)}/messages",
            params={"$top": c.top}, action_name="list_chat_messages",
        )

    async def _send_chat_message(
        self, c: TeamsSendChatMessageConfig, token: str
    ) -> Dict[str, Any]:
        return await _graph_request(
            token, "POST", f"/chats/{_enc(c.chat_id)}/messages",
            json_body=_message_body(c.content, c.content_type),
            action_name="send_chat_message",
        )

    # ------------------------------------------------------------------
    # Handlers — Members
    # ------------------------------------------------------------------
    async def _list_team_members(self, c: TeamsListMembersConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET", f"/teams/{_enc(c.team_id)}/members", action_name="list_team_members"
        )

    async def _add_team_member(self, c: TeamsAddMemberConfig, token: str) -> Dict[str, Any]:
        roles = ["owner"] if c.is_owner == "true" else []
        body = {
            "@odata.type": "#microsoft.graph.aadUserConversationMember",
            "roles": roles,
            "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{c.user_email}')",
        }
        return await _graph_request(
            token, "POST", f"/teams/{_enc(c.team_id)}/members", json_body=body,
            action_name="add_team_member",
        )

    async def _remove_team_member(self, c: TeamsRemoveMemberConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "DELETE", f"/teams/{_enc(c.team_id)}/members/{_enc(c.membership_id)}",
            action_name="remove_team_member",
        )

    # ------------------------------------------------------------------
    # Handlers — Apps & Tabs
    # ------------------------------------------------------------------
    async def _list_installed_apps(
        self, c: TeamsListInstalledAppsConfig, token: str
    ) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET", f"/teams/{_enc(c.team_id)}/installedApps",
            params={"$expand": "teamsAppDefinition"}, action_name="list_installed_apps",
        )

    async def _install_app(self, c: TeamsInstallAppConfig, token: str) -> Dict[str, Any]:
        body = {
            "teamsApp@odata.bind": f"https://graph.microsoft.com/v1.0/appCatalogs/teamsApps/{c.app_id}"
        }
        return await _graph_request(
            token, "POST", f"/teams/{_enc(c.team_id)}/installedApps", json_body=body,
            action_name="install_app",
        )

    async def _list_channel_tabs(self, c: TeamsListTabsConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET", f"/teams/{_enc(c.team_id)}/channels/{_enc(c.channel_id)}/tabs",
            params={"$expand": "teamsApp"}, action_name="list_channel_tabs",
        )

    async def _add_channel_tab(self, c: TeamsAddTabConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "displayName": c.display_name,
            "teamsApp@odata.bind": f"https://graph.microsoft.com/v1.0/appCatalogs/teamsApps/{c.app_id}",
        }
        if c.content_url:
            body["configuration"] = {"contentUrl": c.content_url}
        return await _graph_request(
            token, "POST", f"/teams/{_enc(c.team_id)}/channels/{_enc(c.channel_id)}/tabs",
            json_body=body, action_name="add_channel_tab",
        )

    # ------------------------------------------------------------------
    # Handlers — Meetings & Presence
    # ------------------------------------------------------------------
    async def _create_online_meeting(
        self, c: TeamsCreateMeetingConfig, token: str
    ) -> Dict[str, Any]:
        body = {
            "subject": c.subject,
            "startDateTime": c.start_datetime,
            "endDateTime": c.end_datetime,
        }
        return await _graph_request(
            token, "POST", "/me/onlineMeetings", json_body=body,
            action_name="create_online_meeting",
        )

    async def _get_online_meeting(self, c: TeamsGetMeetingConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET", f"/me/onlineMeetings/{_enc(c.meeting_id)}",
            action_name="get_online_meeting",
        )

    async def _get_user_presence(self, c: TeamsGetPresenceConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET", f"/users/{_enc(c.user_id)}/presence",
            action_name="get_user_presence",
        )

    # ------------------------------------------------------------------
    # Handlers — additional coverage
    # ------------------------------------------------------------------
    @staticmethod
    def _json_body(value: str, label: str) -> Dict[str, Any]:
        import json

        try:
            data = json.loads(value)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid JSON in {label}: {e}")
        if not isinstance(data, dict):
            raise ValueError(f"{label} must be a JSON object")
        return data

    async def _update_team(self, c: TeamsUpdateTeamConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "PATCH", f"/teams/{_enc(c.team_id)}",
            json_body=self._json_body(c.body, "Update JSON"),
            action_name="update_team",
        )

    async def _archive_team(self, c: TeamsArchiveTeamConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "POST", f"/teams/{_enc(c.team_id)}/archive", json_body={},
            action_name="archive_team",
        )

    async def _unarchive_team(self, c: TeamsUnarchiveTeamConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "POST", f"/teams/{_enc(c.team_id)}/unarchive", json_body={},
            action_name="unarchive_team",
        )

    async def _update_channel(self, c: TeamsUpdateChannelConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "PATCH", f"/teams/{_enc(c.team_id)}/channels/{_enc(c.channel_id)}",
            json_body=self._json_body(c.body, "Update JSON"),
            action_name="update_channel",
        )

    async def _list_channel_members(
        self, c: TeamsListChannelMembersConfig, token: str
    ) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET", f"/teams/{_enc(c.team_id)}/channels/{_enc(c.channel_id)}/members",
            action_name="list_channel_members",
        )

    async def _get_chat_message(self, c: TeamsGetChatMessageConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET", f"/chats/{_enc(c.chat_id)}/messages/{_enc(c.message_id)}",
            action_name="get_chat_message",
        )

    async def _list_chat_members(self, c: TeamsListChatMembersConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET", f"/chats/{_enc(c.chat_id)}/members",
            action_name="list_chat_members",
        )

    async def _delete_channel_tab(
        self, c: TeamsDeleteChannelTabConfig, token: str
    ) -> Dict[str, Any]:
        return await _graph_request(
            token, "DELETE",
            f"/teams/{_enc(c.team_id)}/channels/{_enc(c.channel_id)}/tabs/{_enc(c.tab_id)}",
            action_name="delete_channel_tab",
        )

    async def _uninstall_app(self, c: TeamsUninstallAppConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "DELETE",
            f"/teams/{_enc(c.team_id)}/installedApps/{_enc(c.installation_id)}",
            action_name="uninstall_app",
        )

    async def _get_my_presence(self, c: TeamsGetMyPresenceConfig, token: str) -> Dict[str, Any]:
        return await _graph_request(
            token, "GET", "/me/presence", action_name="get_my_presence",
        )
