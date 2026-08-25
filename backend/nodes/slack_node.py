"""
Slack Web API automation node.

Provides workflow integration for Slack with operations for:
- Messaging: Post, update, delete, schedule messages
- Conversations: List, create, archive, manage channels
- Users: List, get info, lookup by email
- Reactions: Add, remove, get reactions on messages
- Pins: Pin, unpin, list pinned items
- Files: List, get info, delete files
- Search: Search messages

API Reference: https://api.slack.com/methods
Authentication: https://api.slack.com/authentication/token-types
"""

import json
import logging
import inspect
import time
from typing import Dict, Any, Optional, Tuple, Union, Literal, List, Annotated

import httpx
from pydantic import BaseModel, Field, Discriminator, ConfigDict

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import load_paginated_options
from nodes.core.oauth_refresh import ensure_fresh_oauth_token
from nodes.core.webhook_subscriptions import AppEventTriggerMixin
from nodes.scopes.slack import BOT as _SLACK_BOT
from nodes.scopes.slack import USER as _SLACK_USER
from nodes.scopes.slack import (
    CONNECT_ADMIN_OPERATIONS,
    CONNECT_ADMIN_TIER,
    GRID_ADMIN_OPERATIONS,
    GRID_ADMIN_TIER,
    SLACK_SCOPES,
)
from nodes.oauth.slack_oauth import (
    is_token_expired,
    refresh_access_token,
    validate_token,
)
from utils.slack_installations import ensure_fresh_slack_bot_token
from utils.ssrf import assert_url_allowed, guarded_async_client

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"

# Endpoints whose success response is a message NoClick created/edited —
# fingerprinted for the self-echo guard (utils/slack_self_echo.py). Both
# return top-level `channel` + `ts` (chat.update's ts = the edited message).
_MESSAGE_WRITE_ENDPOINTS = frozenset({"chat.postMessage", "chat.update"})


SendAs = Literal["user", "bot"]


def _send_as_field() -> Any:
    """Per-operation field choosing whether to send as the authenticated user
    (xoxp-) or as the workspace bot (xoxb-). Defaults to ``user`` so messages
    appear from the person who connected Slack rather than from the app.

    "user" requires the credential to have been authorized with the user
    scopes declared on ``SlackOAuthCredential.x-oauth-user-scopes``. Older
    credentials authorized before user scopes were requested will be rejected
    at runtime with a re-authorize hint.
    """
    return Field(
        "user",
        title="Send As",
        description=(
            "Whose token to authenticate this action with. "
            "Prefer 'User' (xoxp-, the default): it posts as the person who "
            "connected Slack, who is already a member of their channels. "
            "'Bot' (xoxb-) posts as the workspace app, which fails with "
            "'not_in_channel' unless the app was explicitly invited to the "
            "target channel — common when a new user tries the product before "
            "adding the app. Only choose 'Bot' when the message must appear "
            "from the app AND you know it's a member of the channel. "
            "'User' requires re-authorizing Slack if your credential predates user-scope support."
        ),
        json_schema_extra={
            "enumNames": ["User who authenticated", "Bot"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Slack Credential Schemas
# ============================================================================


class SlackOAuthCredential(BaseModel):
    """OAuth 2.0 credential for Slack. Tokens are obtained via OAuth flow, not entered manually. Register OAuth app at: https://api.slack.com/apps"""

    credential_type: Literal["slack_oauth"] = Field(
        "slack_oauth", json_schema_extra={"ui:hidden": True}
    )
    model_config = ConfigDict(
        json_schema_extra={
            "title": "SlackOAuthCredential",
            "x-credential-type": "oauth",
            "x-oauth-provider": "slack",
            # DERIVED, not hand-written: both lists come from the endpoint →
            # scope table in nodes/scopes/slack.py, so they cannot drift from
            # the operations that need them. Slack returns a separate xoxp-
            # user token; write ops honoring ``send_as`` and the reads
            # hard-coded to the user token declare their variant there. Adding
            # a scope forces existing users to re-authorize, so the table's
            # retained-scope set deliberately keeps granted-but-unused scopes.
            "x-oauth-scopes": SLACK_SCOPES.declared_scopes(variant=_SLACK_BOT),
            "x-oauth-user-scopes": SLACK_SCOPES.declared_scopes(
                variant=_SLACK_USER
            ),
        }
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    scope: Optional[str] = Field(
        None, title="Scope", json_schema_extra={"ui:hidden": True}
    )
    token_type: Optional[str] = Field(
        None, title="Token Type", json_schema_extra={"ui:hidden": True}
    )
    team_id: Optional[str] = Field(None, title="Team ID")
    team_name: Optional[str] = Field(None, title="Team Name")
    bot_user_id: Optional[str] = Field(None, title="Bot User ID")
    app_id: Optional[str] = Field(
        None, title="App ID", json_schema_extra={"ui:hidden": True}
    )
    client_id: Optional[str] = Field(
        None, title="Client ID", json_schema_extra={"ui:hidden": True}
    )
    client_secret: Optional[str] = Field(
        None, title="Client Secret", json_schema_extra={"ui:hidden": True}
    )
    # The user OAuth token (xoxp-) returned in `authed_user.access_token` from
    # Slack's OAuth v2 exchange. Used at execute time for write ops whose
    # ``send_as=user`` (the default) and for the channel-scoped read ops that
    # are hard-coded to the user token, so messages/reactions/pins and channel
    # reads are attributed to — and scoped to the channels visible to — the
    # human who connected Slack rather than the workspace bot. Write ops fall
    # back to ``access_token`` (bot) only when they explicitly opt into
    # ``send_as=bot``.
    user_access_token: Optional[str] = Field(
        None, title="User Access Token", json_schema_extra={"ui:hidden": True}
    )
    user_refresh_token: Optional[str] = Field(
        None, title="User Refresh Token", json_schema_extra={"ui:hidden": True}
    )
    user_expires_at: Optional[str] = Field(
        None, title="User Token Expiry", json_schema_extra={"ui:hidden": True}
    )
    user_id_xoxp: Optional[str] = Field(
        None, title="OAuth User ID", json_schema_extra={"ui:hidden": True}
    )


class SlackBotTokenCredential(BaseModel):
    """Bot Token credential for Slack. Get your Bot Token at: https://api.slack.com/apps (OAuth & Permissions page) Bot tokens start with 'xoxb-'"""

    credential_type: Literal["slack_bot_token"] = Field(
        "slack_bot_token", json_schema_extra={"ui:hidden": True}
    )
    model_config = ConfigDict(
        json_schema_extra={
            "title": "SlackBotTokenCredential",
            "x-credential-url": "https://api.slack.com/apps",
        }
    )
    bot_token: str = Field(
        ...,
        title="Bot Token",
        description="Slack Bot User OAuth Token (starts with xoxb-)",
        json_schema_extra={"ui:widget": "password", "placeholder": "xoxb-..."},
    )


# Union type - OAuth shown first in UI
SlackCredential = Union[SlackOAuthCredential, SlackBotTokenCredential]


# ----------------------------------------------------------------------------
# Channel field helper
# ----------------------------------------------------------------------------


def _channel_field(
    description: str,
    *,
    title: str = "Channel",
    field_name: str = "channel",
    default: Any = ...,
) -> Any:
    """Build a channel config field backed by the dynamic channel picker.

    The frontend renders this as a searchable dropdown populated from
    SlackNode.load_field_options. allow_custom keeps manual channel IDs and
    {{references}} usable for cases the dropdown can't cover (e.g. DM IDs).
    """
    return Field(
        default,
        title=title,
        description=description,
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": field_name,
                "placeholder": "Select a channel...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a channel ID / reference",
            },
            "x-resource-type": "slack_channel",
        },
    )


# ============================================================================
# Messaging Configuration Models
# ============================================================================


class SlackPostMessageConfig(BaseModel):
    """Post a message to a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["send_message_to_channel"] = Field(
        default="send_message_to_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Message to Channel",
            "x-keywords": [
                "post to channel",
                "send slack message",
                "message a channel",
                "write in channel",
                "say in channel",
                "notify channel",
            ],
        },
        title="Send Message to Channel",
    )
    channel: str = _channel_field("Channel ID or name (e.g., C1234567890 or #general)")
    text: str = Field(
        ...,
        title="Message",
        description="Message text (supports mrkdwn formatting)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    thread_ts: Optional[str] = Field(
        default=None,
        title="Thread Timestamp",
        description="Reply in thread - provide parent message's ts value",
    )
    reply_broadcast: Optional[bool] = Field(
        default=False,
        title="Also Send to Channel",
        description="When replying in thread, also post to the channel",
    )
    unfurl_links: Optional[bool] = Field(
        default=True, title="Unfurl Links", description="Enable link previews"
    )
    unfurl_media: Optional[bool] = Field(
        default=True, title="Unfurl Media", description="Enable media previews"
    )
    mrkdwn: Optional[bool] = Field(
        default=True,
        title="Enable Markdown",
        description="Enable Slack's mrkdwn formatting",
    )
    send_as: SendAs = _send_as_field()


class SlackUpdateMessageConfig(BaseModel):
    """Update an existing message"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_existing_message"] = Field(
        default="update_existing_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Update Existing Message",
            "x-keywords": [
                "edit a message",
                "change posted message",
                "modify sent message",
                "edit slack message",
                "rewrite message",
            ],
        },
        title="Update Existing Message",
    )
    channel: str = _channel_field("Channel containing the message")
    ts: str = Field(
        ...,
        title="Message Timestamp",
        description="Timestamp of the message to update (ts value)",
    )
    text: str = Field(
        ...,
        title="New Message",
        description="New message text",
        json_schema_extra={"ui:widget": "textarea"},
    )
    send_as: SendAs = _send_as_field()


class SlackDeleteMessageConfig(BaseModel):
    """Delete a message"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_message"] = Field(
        default="delete_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Delete Message",
            "x-keywords": [
                "delete a message",
                "remove posted message",
                "erase message",
                "take down message",
            ],
        },
        title="Delete Message",
    )
    channel: str = _channel_field("Channel containing the message")
    ts: str = Field(
        ...,
        title="Message Timestamp",
        description="Timestamp of the message to delete (ts value)",
    )
    send_as: SendAs = _send_as_field()


class SlackPostEphemeralConfig(BaseModel):
    """Send an ephemeral message (only visible to one user)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["send_ephemeral_message"] = Field(
        default="send_ephemeral_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Ephemeral Message",
            "x-keywords": [
                "ephemeral message",
                "private temporary message",
                "visible to one user",
                "only you see this",
                "hidden message",
            ],
        },
        title="Send Ephemeral Message",
    )
    channel: str = _channel_field("Channel ID")
    user: str = Field(..., title="User", description="User ID who will see the message")
    text: str = Field(
        ...,
        title="Message",
        description="Message text (only visible to specified user)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    thread_ts: Optional[str] = Field(
        default=None, title="Thread Timestamp", description="Post ephemeral in a thread"
    )
    send_as: SendAs = _send_as_field()


class SlackScheduleMessageConfig(BaseModel):
    """Schedule a message for later"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["schedule_message_for_later"] = Field(
        default="schedule_message_for_later",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Schedule Message for Later",
            "x-keywords": [
                "schedule message",
                "send message later",
                "queue message",
                "delayed message",
                "post at time",
            ],
        },
        title="Schedule Message for Later",
    )
    channel: str = _channel_field("Channel ID")
    text: str = Field(
        ...,
        title="Message",
        description="Message text",
        json_schema_extra={"ui:widget": "textarea"},
    )
    post_at: int = Field(
        ...,
        title="Post At",
        description="Unix timestamp for when to post (must be in future, within 120 days)",
    )
    thread_ts: Optional[str] = Field(
        default=None, title="Thread Timestamp", description="Schedule as a thread reply"
    )
    send_as: SendAs = _send_as_field()


class SlackGetPermalinkConfig(BaseModel):
    """Get a permalink URL for a message"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_message_permalink"] = Field(
        default="get_message_permalink",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Get Message Permalink",
            "x-keywords": [
                "message link",
                "permalink to message",
                "copy message url",
                "get message url",
                "share message link",
            ],
        },
        title="Get Message Permalink",
    )
    channel: str = _channel_field("Channel containing the message")
    message_ts: str = Field(
        ..., title="Message Timestamp", description="Timestamp of the message"
    )


# ============================================================================
# Conversations Configuration Models
# ============================================================================


class SlackListConversationsConfig(BaseModel):
    """List channels in the workspace"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_channels_in_workspace"] = Field(
        default="list_channels_in_workspace",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "List Channels in Workspace",
            "x-keywords": [
                "list channels",
                "all channels",
                "show workspace channels",
                "browse channels",
                "channels in workspace",
            ],
        },
        title="List Channels in Workspace",
    )
    types: Optional[str] = Field(
        default="public_channel,private_channel",
        title="Channel Types",
        description="Comma-separated: public_channel, private_channel, mpim, im",
    )
    exclude_archived: Optional[bool] = Field(
        default=True, title="Exclude Archived", description="Exclude archived channels"
    )
    limit: Optional[int] = Field(
        default=100, title="Limit", description="Maximum results (1-1000)"
    )


class SlackConversationInfoConfig(BaseModel):
    """Get information about a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_channel_information"] = Field(
        default="get_channel_information",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Get Channel Information",
            "x-keywords": [
                "channel info",
                "channel details",
                "about a channel",
                "channel metadata",
            ],
        },
        title="Get Channel Information",
    )
    channel: str = _channel_field("Channel ID")
    include_num_members: Optional[bool] = Field(
        default=True,
        title="Include Member Count",
        description="Include number of members",
    )


class SlackConversationHistoryConfig(BaseModel):
    """Get messages from a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_channel_messages"] = Field(
        default="get_channel_messages",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Get Channel Messages",
            "x-keywords": [
                "read channel history",
                "fetch channel messages",
                "channel conversation history",
                "get messages from channel",
                "pull channel chat",
            ],
        },
        title="Get Channel Messages",
    )
    channel: str = _channel_field("Channel ID")
    limit: Optional[int] = Field(
        default=100, title="Limit", description="Number of messages to return (1-1000)"
    )
    oldest: Optional[str] = Field(
        default=None, title="Oldest", description="Start of time range (Unix timestamp)"
    )
    latest: Optional[str] = Field(
        default=None, title="Latest", description="End of time range (Unix timestamp)"
    )
    inclusive: Optional[bool] = Field(
        default=False,
        title="Inclusive",
        description="Include messages with oldest/latest timestamps",
    )


class SlackConversationMembersConfig(BaseModel):
    """Get members of a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_channel_members"] = Field(
        default="list_channel_members",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "List Channel Members",
            "x-keywords": [
                "who is in channel",
                "channel members",
                "people in channel",
                "channel participants",
            ],
        },
        title="List Channel Members",
    )
    channel: str = _channel_field("Channel ID")
    limit: Optional[int] = Field(
        default=100, title="Limit", description="Maximum results"
    )


class SlackJoinConversationConfig(BaseModel):
    """Join a public channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["join_public_channel"] = Field(
        default="join_public_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Join Public Channel",
            "x-keywords": [
                "join channel",
                "enter public channel",
                "add bot to channel",
                "become member",
            ],
        },
        title="Join Public Channel",
    )
    channel: str = _channel_field("Channel ID to join")
    send_as: SendAs = _send_as_field()


class SlackLeaveConversationConfig(BaseModel):
    """Leave a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["leave_channel"] = Field(
        default="leave_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Leave Channel",
            "x-keywords": [
                "leave channel",
                "exit channel",
                "quit channel",
                "remove bot from channel",
            ],
        },
        title="Leave Channel",
    )
    channel: str = _channel_field("Channel ID to leave")
    send_as: SendAs = _send_as_field()


class SlackCreateConversationConfig(BaseModel):
    """Create a new channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_channel"] = Field(
        default="create_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Create Channel",
            "x-keywords": [
                "create channel",
                "new channel",
                "make a channel",
                "start a channel",
            ],
            "x-creates-resource": True,
            "x-resource-type": "slack_channel",
            "x-resource-id-path": "data.channel.id",
        },
        title="Create Channel",
    )
    name: str = Field(
        ...,
        title="Channel Name",
        description="Name of the channel (lowercase, no spaces, max 80 chars)",
    )
    is_private: Optional[bool] = Field(
        default=False, title="Private", description="Create as a private channel"
    )
    send_as: SendAs = _send_as_field()


class SlackArchiveConversationConfig(BaseModel):
    """Archive a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["archive_channel"] = Field(
        default="archive_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Archive Channel",
            "x-keywords": [
                "archive channel",
                "close channel",
                "shut down channel",
                "deactivate channel",
            ],
        },
        title="Archive Channel",
    )
    channel: str = _channel_field("Channel ID to archive")
    send_as: SendAs = _send_as_field()


class SlackUnarchiveConversationConfig(BaseModel):
    """Unarchive a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["unarchive_channel"] = Field(
        default="unarchive_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Unarchive Channel",
            "x-keywords": [
                "unarchive channel",
                "restore channel",
                "reopen channel",
                "reactivate channel",
            ],
        },
        title="Unarchive Channel",
    )
    channel: str = _channel_field("Channel ID to unarchive")
    send_as: SendAs = _send_as_field()


class SlackInviteToConversationConfig(BaseModel):
    """Invite users to a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["invite_users_to_channel"] = Field(
        default="invite_users_to_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Invite Users to Channel",
            "x-keywords": [
                "invite to channel",
                "add people to channel",
                "add users to channel",
                "bring someone into channel",
            ],
        },
        title="Invite Users to Channel",
    )
    channel: str = _channel_field("Channel ID")
    users: str = Field(
        ..., title="Users", description="Comma-separated user IDs to invite"
    )
    send_as: SendAs = _send_as_field()


class SlackKickFromConversationConfig(BaseModel):
    """Remove a user from a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_user_from_channel"] = Field(
        default="remove_user_from_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Remove User from Channel",
            "x-keywords": [
                "kick from channel",
                "remove someone from channel",
                "remove member from channel",
                "eject user",
            ],
        },
        title="Remove User from Channel",
    )
    channel: str = _channel_field("Channel ID")
    user: str = Field(..., title="User", description="User ID to remove")
    send_as: SendAs = _send_as_field()


class SlackSetConversationTopicConfig(BaseModel):
    """Set the topic of a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_channel_topic"] = Field(
        default="set_channel_topic",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Set Channel Topic",
            "x-keywords": [
                "set channel topic",
                "change channel topic",
                "update topic",
                "edit channel headline",
            ],
        },
        title="Set Channel Topic",
    )
    channel: str = _channel_field("Channel ID")
    topic: str = Field(..., title="Topic", description="New channel topic")
    send_as: SendAs = _send_as_field()


class SlackSetConversationPurposeConfig(BaseModel):
    """Set the purpose of a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_channel_purpose"] = Field(
        default="set_channel_purpose",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Set Channel Purpose",
            "x-keywords": [
                "set channel purpose",
                "channel description",
                "change channel purpose",
                "update purpose",
            ],
        },
        title="Set Channel Purpose",
    )
    channel: str = _channel_field("Channel ID")
    purpose: str = Field(..., title="Purpose", description="New channel purpose")
    send_as: SendAs = _send_as_field()


class SlackRenameConversationConfig(BaseModel):
    """Rename a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["rename_channel"] = Field(
        default="rename_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Rename Channel",
            "x-keywords": [
                "rename channel",
                "change channel name",
                "give channel new name",
            ],
        },
        title="Rename Channel",
    )
    channel: str = _channel_field("Channel ID")
    name: str = Field(..., title="New Name", description="New channel name")
    send_as: SendAs = _send_as_field()


class SlackConversationRepliesConfig(BaseModel):
    """Get thread replies"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_thread_replies"] = Field(
        default="get_thread_replies",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Get Thread Replies",
            "x-keywords": [
                "thread replies",
                "replies in thread",
                "thread messages",
                "read thread",
                "conversation thread",
            ],
        },
        title="Get Thread Replies",
    )
    channel: str = _channel_field("Channel ID containing the thread")
    ts: str = Field(
        ...,
        title="Thread Timestamp",
        description="Timestamp of the parent message (ts value)",
    )
    limit: Optional[int] = Field(
        default=100, title="Limit", description="Number of replies to return"
    )
    oldest: Optional[str] = Field(
        default=None, title="Oldest", description="Start of time range (Unix timestamp)"
    )
    latest: Optional[str] = Field(
        default=None, title="Latest", description="End of time range (Unix timestamp)"
    )


class SlackOpenConversationConfig(BaseModel):
    """Open or resume a direct message or multi-person DM"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["open_direct_message"] = Field(
        default="open_direct_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Open Direct Message",
            "x-keywords": [
                "open dm",
                "start dm",
                "direct message someone",
                "group dm",
                "private message",
            ],
        },
        title="Open Direct Message",
    )
    users: Optional[str] = Field(
        default=None,
        title="Users",
        description="Comma-separated user IDs to open DM with",
    )
    channel: Optional[str] = _channel_field(
        "Resume a conversation by its ID", default=None
    )
    return_im: Optional[bool] = Field(
        default=False,
        title="Return IM",
        description="Return the full IM channel object",
    )


class SlackCloseConversationConfig(BaseModel):
    """Close a direct message or multi-person DM"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["close_direct_message"] = Field(
        default="close_direct_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Close Direct Message",
            "x-keywords": ["close dm", "close direct message", "end dm", "dismiss dm"],
        },
        title="Close Direct Message",
    )
    channel: str = _channel_field("DM channel ID to close")


class SlackMarkConversationConfig(BaseModel):
    """Mark a channel as read"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["mark_channel_as_read"] = Field(
        default="mark_channel_as_read",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Mark Channel As Read",
            "x-keywords": [
                "mark read",
                "clear unread",
                "mark seen",
                "mark channel read",
            ],
        },
        title="Mark Channel As Read",
    )
    channel: str = _channel_field("Channel ID to mark")
    ts: str = Field(
        ..., title="Timestamp", description="Timestamp to mark as read up to"
    )


# ============================================================================
# Users Configuration Models
# ============================================================================


class SlackListUsersConfig(BaseModel):
    """List all users in the workspace"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_workspace_users"] = Field(
        default="list_workspace_users",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List Workspace Users",
            "x-keywords": [
                "all members",
                "everyone in workspace",
                "team roster",
                "workspace members",
                "all users",
            ],
        },
        title="List Workspace Users",
    )
    limit: Optional[int] = Field(
        default=100,
        title="Limit",
        description="Maximum results (recommended: 200 or less)",
    )
    include_locale: Optional[bool] = Field(
        default=False,
        title="Include Locale",
        description="Include user locale information",
    )


class SlackUserInfoConfig(BaseModel):
    """Get information about a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_user_information"] = Field(
        default="get_user_information",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User Information",
            "x-keywords": [
                "user info",
                "user details",
                "member profile",
                "who is",
                "lookup user",
            ],
        },
        title="Get User Information",
    )
    user: str = Field(..., title="User ID", description="User ID (e.g., U1234567890)")
    include_locale: Optional[bool] = Field(
        default=False,
        title="Include Locale",
        description="Include user locale information",
    )


class SlackLookupUserByEmailConfig(BaseModel):
    """Find a user by their email address"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["find_user_by_email"] = Field(
        default="find_user_by_email",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Find User by Email",
            "x-keywords": [
                "user by email",
                "email to user",
                "lookup by email",
                "find member email",
            ],
        },
        title="Find User by Email",
    )
    email: str = Field(..., title="Email", description="Email address to look up")


class SlackGetUserPresenceConfig(BaseModel):
    """Get a user's presence status"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_user_presence_status"] = Field(
        default="get_user_presence_status",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User Presence Status",
            "x-keywords": [
                "online or away",
                "is active",
                "presence",
                "active status",
                "away status",
            ],
        },
        title="Get User Presence Status",
    )
    user: str = Field(..., title="User ID", description="User ID to check presence for")


class SlackUsersConversationsConfig(BaseModel):
    """List conversations the calling user may access"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_user_accessible_conversations"] = Field(
        default="list_user_accessible_conversations",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List User Accessible Conversations",
            "x-keywords": [
                "my conversations",
                "channels i can see",
                "accessible channels",
                "conversations for me",
                "channels im in",
            ],
        },
        title="List User Accessible Conversations",
    )
    user: Optional[str] = Field(
        default=None,
        title="User ID",
        description="User ID (defaults to authenticated user)",
    )
    types: Optional[str] = Field(
        default="public_channel,private_channel",
        title="Types",
        description="Comma-separated: public_channel, private_channel, mpim, im",
    )
    exclude_archived: Optional[bool] = Field(
        default=True, title="Exclude Archived", description="Exclude archived channels"
    )
    limit: Optional[int] = Field(
        default=100, title="Limit", description="Maximum results"
    )


# ============================================================================
# Bookmarks Configuration Models
# ============================================================================


class SlackAddBookmarkConfig(BaseModel):
    """Add a bookmark to a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_bookmark_to_channel"] = Field(
        default="add_bookmark_to_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Add Bookmark to Channel",
            "x-keywords": [
                "add bookmark",
                "pin link",
                "bookmark link",
                "save link channel",
            ],
        },
        title="Add Bookmark to Channel",
    )
    channel_id: str = _channel_field(
        "Channel to add bookmark to", title="Channel ID", field_name="channel_id"
    )
    title: str = Field(..., title="Title", description="Title for the bookmark")
    type: Literal["link", "emoji"] = Field(
        default="link", title="Type", description="Type of bookmark"
    )
    link: Optional[str] = Field(
        default=None,
        title="Link",
        description="Link to bookmark (required for link type)",
    )
    emoji: Optional[str] = Field(
        default=None, title="Emoji", description="Emoji for the bookmark"
    )
    send_as: SendAs = _send_as_field()


class SlackEditBookmarkConfig(BaseModel):
    """Edit an existing bookmark"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["edit_channel_bookmark"] = Field(
        default="edit_channel_bookmark",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Edit Channel Bookmark",
            "x-keywords": [
                "edit bookmark",
                "change bookmark",
                "rename bookmark",
                "update bookmark link",
            ],
        },
        title="Edit Channel Bookmark",
    )
    channel_id: str = _channel_field(
        "Channel containing the bookmark", title="Channel ID", field_name="channel_id"
    )
    bookmark_id: str = Field(
        ..., title="Bookmark ID", description="ID of the bookmark to edit"
    )
    title: Optional[str] = Field(
        default=None, title="Title", description="New title for the bookmark"
    )
    link: Optional[str] = Field(
        default=None, title="Link", description="New link for the bookmark"
    )
    emoji: Optional[str] = Field(
        default=None, title="Emoji", description="New emoji for the bookmark"
    )
    send_as: SendAs = _send_as_field()


class SlackListBookmarksConfig(BaseModel):
    """List bookmarks in a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_channel_bookmarks"] = Field(
        default="list_channel_bookmarks",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "List Channel Bookmarks",
            "x-keywords": [
                "all bookmarks",
                "show bookmarks",
                "channel bookmarks",
                "saved links",
            ],
        },
        title="List Channel Bookmarks",
    )
    channel_id: str = _channel_field(
        "Channel to list bookmarks from", title="Channel ID", field_name="channel_id"
    )


class SlackRemoveBookmarkConfig(BaseModel):
    """Remove a bookmark from a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_channel_bookmark"] = Field(
        default="remove_channel_bookmark",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Remove Channel Bookmark",
            "x-keywords": ["remove bookmark", "delete bookmark", "unbookmark"],
        },
        title="Remove Channel Bookmark",
    )
    channel_id: str = _channel_field(
        "Channel containing the bookmark", title="Channel ID", field_name="channel_id"
    )
    bookmark_id: str = Field(
        ..., title="Bookmark ID", description="ID of the bookmark to remove"
    )

    # ============================================================================
    # User Groups Configuration Models
    # ============================================================================
    send_as: SendAs = _send_as_field()


class SlackListUserGroupsConfig(BaseModel):
    """List user groups in the workspace"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_workspace_user_groups"] = Field(
        default="list_workspace_user_groups",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User Group",
            "x-is-trigger": False,
            "x-display-name": "List Workspace User Groups",
            "x-keywords": [
                "all user groups",
                "show user groups",
                "list groups",
                "team groups",
            ],
        },
        title="List Workspace User Groups",
    )
    include_count: Optional[bool] = Field(
        default=False,
        title="Include Count",
        description="Include the count of users in each group",
    )
    include_disabled: Optional[bool] = Field(
        default=False,
        title="Include Disabled",
        description="Include disabled user groups",
    )
    include_users: Optional[bool] = Field(
        default=False,
        title="Include Users",
        description="Include the list of users in each group",
    )


class SlackCreateUserGroupConfig(BaseModel):
    """Create a new user group"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_user_group"] = Field(
        default="create_user_group",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User Group",
            "x-is-trigger": False,
            "x-display-name": "Create User Group",
            "x-keywords": ["new user group", "make group", "add user group"],
        },
        title="Create User Group",
    )
    name: str = Field(..., title="Name", description="A name for the User Group")
    handle: Optional[str] = Field(
        default=None, title="Handle", description="A mention handle (e.g., @marketing)"
    )
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="A short description of the User Group",
    )
    channels: Optional[str] = Field(
        default=None,
        title="Channels",
        description="Comma-separated channel IDs for default channels",
    )


class SlackDisableUserGroupConfig(BaseModel):
    """Disable an existing user group"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["disable_user_group"] = Field(
        default="disable_user_group",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User Group",
            "x-is-trigger": False,
            "x-display-name": "Disable User Group",
            "x-keywords": ["disable group", "turn off group", "deactivate user group"],
        },
        title="Disable User Group",
    )
    usergroup: str = Field(
        ..., title="User Group ID", description="The ID of the User Group to disable"
    )


class SlackEnableUserGroupConfig(BaseModel):
    """Enable a disabled user group"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["enable_user_group"] = Field(
        default="enable_user_group",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User Group",
            "x-is-trigger": False,
            "x-display-name": "Enable User Group",
            "x-keywords": [
                "enable group",
                "turn on group",
                "reactivate user group",
                "activate group",
            ],
        },
        title="Enable User Group",
    )
    usergroup: str = Field(
        ..., title="User Group ID", description="The ID of the User Group to enable"
    )


class SlackUpdateUserGroupConfig(BaseModel):
    """Update an existing user group"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_user_group"] = Field(
        default="update_user_group",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User Group",
            "x-is-trigger": False,
            "x-display-name": "Update User Group",
            "x-keywords": [
                "edit user group",
                "rename group",
                "change user group",
                "modify group",
            ],
        },
        title="Update User Group",
    )
    usergroup: str = Field(
        ..., title="User Group ID", description="The ID of the User Group to update"
    )
    name: Optional[str] = Field(
        default=None, title="Name", description="New name for the User Group"
    )
    handle: Optional[str] = Field(
        default=None, title="Handle", description="New mention handle"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="New description"
    )
    channels: Optional[str] = Field(
        default=None,
        title="Channels",
        description="Comma-separated channel IDs for default channels",
    )


class SlackListUserGroupUsersConfig(BaseModel):
    """List users in a user group"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_usergroup_members"] = Field(
        default="list_usergroup_members",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User Group",
            "x-is-trigger": False,
            "x-display-name": "List Usergroup Members",
            "x-keywords": [
                "group members",
                "who is in group",
                "users in group",
                "usergroup roster",
            ],
        },
        title="List Usergroup Members",
    )
    usergroup: str = Field(
        ..., title="User Group ID", description="The ID of the User Group"
    )
    include_disabled: Optional[bool] = Field(
        default=False,
        title="Include Disabled",
        description="Include disabled User Groups",
    )


class SlackUpdateUserGroupUsersConfig(BaseModel):
    """Update the list of users in a user group"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_usergroup_member_list"] = Field(
        default="update_usergroup_member_list",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User Group",
            "x-is-trigger": False,
            "x-display-name": "Update Usergroup Member List",
            "x-keywords": [
                "set group members",
                "change group members",
                "edit group membership",
                "manage group users",
            ],
        },
        title="Update Usergroup Member List",
    )
    usergroup: str = Field(
        ..., title="User Group ID", description="The ID of the User Group"
    )
    users: str = Field(
        ...,
        title="Users",
        description="Comma-separated user IDs that will be the members",
    )


# ============================================================================
# DND (Do Not Disturb) Configuration Models
# ============================================================================


class SlackDndSetSnoozeConfig(BaseModel):
    """Turn on Do Not Disturb for the current user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_do_not_disturb_snooze"] = Field(
        default="set_do_not_disturb_snooze",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Do Not Disturb",
            "x-is-trigger": False,
            "x-display-name": "Set Do Not Disturb Snooze",
            "x-keywords": [
                "do not disturb",
                "dnd on",
                "snooze notifications",
                "turn on dnd",
                "mute me",
            ],
        },
        title="Set Do Not Disturb Snooze",
    )
    num_minutes: int = Field(
        ..., title="Minutes", description="Number of minutes to snooze DND"
    )


class SlackDndEndSnoozeConfig(BaseModel):
    """End the current user's snooze mode"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["end_snooze_mode"] = Field(
        default="end_snooze_mode",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Do Not Disturb",
            "x-is-trigger": False,
            "x-display-name": "End Snooze Mode",
            "x-keywords": ["end snooze", "stop snooze", "turn off snooze"],
        },
        title="End Snooze Mode",
    )


class SlackDndEndDndConfig(BaseModel):
    """End the current user's Do Not Disturb session"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["end_do_not_disturb"] = Field(
        default="end_do_not_disturb",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Do Not Disturb",
            "x-is-trigger": False,
            "x-display-name": "End Do Not Disturb",
            "x-keywords": [
                "end dnd",
                "turn off do not disturb",
                "stop dnd",
                "unmute me",
            ],
        },
        title="End Do Not Disturb",
    )


class SlackDndInfoConfig(BaseModel):
    """Get Do Not Disturb status for a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_do_not_disturb_status"] = Field(
        default="get_do_not_disturb_status",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Do Not Disturb",
            "x-is-trigger": False,
            "x-display-name": "Get Do Not Disturb Status",
            "x-keywords": [
                "dnd status",
                "am i snoozed",
                "check do not disturb",
                "my dnd",
            ],
        },
        title="Get Do Not Disturb Status",
    )
    user: Optional[str] = Field(
        default=None,
        title="User ID",
        description="User to get DND status for (defaults to current user)",
    )


class SlackDndTeamInfoConfig(BaseModel):
    """Get Do Not Disturb status for users on a team"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_team_do_not_disturb_status"] = Field(
        default="get_team_do_not_disturb_status",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Do Not Disturb",
            "x-is-trigger": False,
            "x-display-name": "Get Team Do Not Disturb Status",
            "x-keywords": [
                "team dnd status",
                "who is snoozed",
                "dnd for users",
                "team do not disturb",
            ],
        },
        title="Get Team Do Not Disturb Status",
    )
    # dnd.teamInfo rejects a userless call with invalid_arguments — required.
    users: str = Field(
        ...,
        title="Users",
        description="Comma-separated user IDs to fetch DND status for",
    )


# ============================================================================
# Emoji Configuration Models
# ============================================================================


class SlackListEmojiConfig(BaseModel):
    """List custom emoji in the workspace"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_custom_emoji_in_workspace"] = Field(
        default="list_custom_emoji_in_workspace",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Emoji",
            "x-is-trigger": False,
            "x-display-name": "List Custom Emoji in Workspace",
            "x-keywords": [
                "custom emoji",
                "workspace emoji",
                "emoji list",
                "all emoji",
            ],
        },
        title="List Custom Emoji in Workspace",
    )
    include_categories: Optional[bool] = Field(
        default=False,
        title="Include Categories",
        description="Include emoji categories",
    )


# ============================================================================
# Stars Configuration Models
# ============================================================================


class SlackAddStarConfig(BaseModel):
    """Star a message, file, or channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["star_message_or_file"] = Field(
        default="star_message_or_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reaction",
            "x-is-trigger": False,
            "x-display-name": "Star Message or File",
            "x-keywords": [
                "star item",
                "save message",
                "bookmark message",
                "star file",
            ],
        },
        title="Star Message or File",
    )
    channel: Optional[str] = _channel_field(
        "Channel to star, or channel containing the message", default=None
    )
    timestamp: Optional[str] = Field(
        default=None,
        title="Message Timestamp",
        description="Timestamp of message to star",
    )
    file: Optional[str] = Field(
        default=None, title="File ID", description="File ID to star"
    )
    send_as: SendAs = _send_as_field()


class SlackRemoveStarConfig(BaseModel):
    """Remove a star from an item"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["unstar_item"] = Field(
        default="unstar_item",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reaction",
            "x-is-trigger": False,
            "x-display-name": "Unstar Item",
            "x-keywords": ["unstar", "unsave message", "remove star"],
        },
        title="Unstar Item",
    )
    channel: Optional[str] = _channel_field(
        "Channel to unstar, or channel containing the message", default=None
    )
    timestamp: Optional[str] = Field(
        default=None,
        title="Message Timestamp",
        description="Timestamp of message to unstar",
    )
    file: Optional[str] = Field(
        default=None, title="File ID", description="File ID to unstar"
    )
    send_as: SendAs = _send_as_field()


class SlackListStarsConfig(BaseModel):
    """List starred items for the current user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_user_starred_items"] = Field(
        default="list_user_starred_items",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reaction",
            "x-is-trigger": False,
            "x-display-name": "List User Starred Items",
            "x-keywords": [
                "my starred",
                "saved items",
                "starred messages",
                "saved for later",
            ],
        },
        title="List User Starred Items",
    )
    count: Optional[int] = Field(
        default=100, title="Count", description="Number of items to return"
    )


# ============================================================================
# Bots Configuration Models
# ============================================================================


class SlackBotInfoConfig(BaseModel):
    """Get information about a bot"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_bot_information"] = Field(
        default="get_bot_information",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Bot",
            "x-is-trigger": False,
            "x-display-name": "Get Bot Information",
            "x-keywords": ["bot info", "bot details", "about a bot", "bot profile"],
        },
        title="Get Bot Information",
    )
    bot: Optional[str] = Field(
        default=None,
        title="Bot ID",
        description="Bot user ID (defaults to the current bot)",
    )


# ============================================================================
# Reminders Configuration Models
# Note: Reminders API is deprecated but still functional
# ============================================================================


class SlackAddReminderConfig(BaseModel):
    """Create a reminder"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_reminder"] = Field(
        default="create_reminder",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reminder",
            "x-is-trigger": False,
            "x-display-name": "Create Reminder",
            "x-keywords": ["set reminder", "remind me", "new reminder", "add reminder"],
        },
        title="Create Reminder",
    )
    text: str = Field(..., title="Text", description="The content of the reminder")
    time: str = Field(
        ...,
        title="Time",
        description="When to remind (Unix timestamp or natural language like 'in 5 minutes')",
    )
    user: Optional[str] = Field(
        default=None,
        title="User",
        description="User ID to create reminder for (requires bot token)",
    )
    send_as: SendAs = _send_as_field()


class SlackCompleteReminderConfig(BaseModel):
    """Mark a reminder as complete"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["mark_reminder_complete"] = Field(
        default="mark_reminder_complete",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reminder",
            "x-is-trigger": False,
            "x-display-name": "Mark Reminder Complete",
            "x-keywords": [
                "complete reminder",
                "finish reminder",
                "done reminder",
                "check off reminder",
            ],
        },
        title="Mark Reminder Complete",
    )
    reminder: str = Field(
        ..., title="Reminder ID", description="The ID of the reminder to complete"
    )


class SlackDeleteReminderConfig(BaseModel):
    """Delete a reminder"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_reminder"] = Field(
        default="delete_reminder",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reminder",
            "x-is-trigger": False,
            "x-display-name": "Delete Reminder",
            "x-keywords": ["remove reminder", "cancel reminder", "drop reminder"],
        },
        title="Delete Reminder",
    )
    reminder: str = Field(
        ..., title="Reminder ID", description="The ID of the reminder to delete"
    )


class SlackReminderInfoConfig(BaseModel):
    """Get information about a reminder"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_reminder_information"] = Field(
        default="get_reminder_information",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reminder",
            "x-is-trigger": False,
            "x-display-name": "Get Reminder Information",
            "x-keywords": ["reminder info", "reminder details", "show reminder"],
        },
        title="Get Reminder Information",
    )
    reminder: str = Field(
        ..., title="Reminder ID", description="The ID of the reminder"
    )


class SlackListRemindersConfig(BaseModel):
    """List all reminders for the current user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_user_reminders"] = Field(
        default="list_user_reminders",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reminder",
            "x-is-trigger": False,
            "x-display-name": "List User Reminders",
            "x-keywords": [
                "my reminders",
                "all reminders",
                "show reminders",
                "upcoming reminders",
            ],
        },
        title="List User Reminders",
    )


# ============================================================================
# Reactions Configuration Models
# ============================================================================


class SlackAddReactionConfig(BaseModel):
    """Add an emoji reaction to a message"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_emoji_reaction_to_message"] = Field(
        default="add_emoji_reaction_to_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Add Emoji Reaction to Message",
            "x-keywords": [
                "react to message",
                "add reaction",
                "emoji react",
                "thumbs up",
            ],
        },
        title="Add Emoji Reaction to Message",
    )
    channel: str = _channel_field("Channel containing the message")
    timestamp: str = Field(
        ...,
        title="Message Timestamp",
        description="Timestamp of the message (ts value)",
    )
    name: str = Field(
        ...,
        title="Emoji Name",
        description="Emoji name without colons (e.g., thumbsup, heart, rocket)",
    )
    send_as: SendAs = _send_as_field()


class SlackRemoveReactionConfig(BaseModel):
    """Remove an emoji reaction from a message"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_emoji_reaction_from_message"] = Field(
        default="remove_emoji_reaction_from_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Remove Emoji Reaction from Message",
            "x-keywords": [
                "remove reaction",
                "unreact",
                "delete reaction",
                "take off emoji",
            ],
        },
        title="Remove Emoji Reaction from Message",
    )
    channel: str = _channel_field("Channel containing the message")
    timestamp: str = Field(
        ...,
        title="Message Timestamp",
        description="Timestamp of the message (ts value)",
    )
    name: str = Field(..., title="Emoji Name", description="Emoji name without colons")
    send_as: SendAs = _send_as_field()


class SlackGetReactionsConfig(BaseModel):
    """Get reactions on a message"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_message_reactions"] = Field(
        default="get_message_reactions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Get Message Reactions",
            "x-keywords": [
                "who reacted",
                "message reactions",
                "list reactions",
                "reaction counts",
            ],
        },
        title="Get Message Reactions",
    )
    channel: str = _channel_field("Channel containing the message")
    timestamp: str = Field(
        ...,
        title="Message Timestamp",
        description="Timestamp of the message (ts value)",
    )
    full: Optional[bool] = Field(
        default=False,
        title="Full",
        description="Include full user info for each reaction",
    )


# ============================================================================
# Pins Configuration Models
# ============================================================================


class SlackAddPinConfig(BaseModel):
    """Pin a message to a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["pin_message_to_channel"] = Field(
        default="pin_message_to_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Pin Message to Channel",
            "x-keywords": ["pin message", "pin to channel", "pin post"],
        },
        title="Pin Message to Channel",
    )
    channel: str = _channel_field("Channel containing the message")
    timestamp: str = Field(
        ...,
        title="Message Timestamp",
        description="Timestamp of the message to pin (ts value)",
    )
    send_as: SendAs = _send_as_field()


class SlackRemovePinConfig(BaseModel):
    """Unpin a message from a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["unpin_message_from_channel"] = Field(
        default="unpin_message_from_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Unpin Message from Channel",
            "x-keywords": ["unpin message", "remove pin", "unpin post"],
        },
        title="Unpin Message from Channel",
    )
    channel: str = _channel_field("Channel containing the message")
    timestamp: str = Field(
        ...,
        title="Message Timestamp",
        description="Timestamp of the message to unpin (ts value)",
    )
    send_as: SendAs = _send_as_field()


class SlackListPinsConfig(BaseModel):
    """List pinned items in a channel"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_pinned_items_in_channel"] = Field(
        default="list_pinned_items_in_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "List Pinned Items in Channel",
            "x-keywords": [
                "pinned messages",
                "show pins",
                "channel pins",
                "pinned items",
            ],
        },
        title="List Pinned Items in Channel",
    )
    channel: str = _channel_field("Channel to get pinned items from")


# ============================================================================
# Files Configuration Models
# ============================================================================


class SlackListFilesConfig(BaseModel):
    """List files in the workspace"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_workspace_files"] = Field(
        default="list_workspace_files",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "List Workspace Files",
            "x-keywords": [
                "all files",
                "workspace files",
                "show files",
                "uploaded files",
            ],
        },
        title="List Workspace Files",
    )
    channel: Optional[str] = _channel_field(
        "Filter to files in this channel", default=None
    )
    user: Optional[str] = Field(
        default=None, title="User", description="Filter to files from this user"
    )
    types: Optional[str] = Field(
        default=None,
        title="File Types",
        description="Filter by type: all, spaces, snippets, images, gdocs, zips, pdfs",
    )
    count: Optional[int] = Field(
        default=100, title="Count", description="Number of files to return"
    )


class SlackFileInfoConfig(BaseModel):
    """Get information about a file"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_file_information"] = Field(
        default="get_file_information",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Get File Information",
            "x-keywords": [
                "file info",
                "file details",
                "about a file",
                "file metadata",
            ],
        },
        title="Get File Information",
    )
    file: str = Field(..., title="File ID", description="File ID")


class SlackDeleteFileConfig(BaseModel):
    """Delete a file"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_file"] = Field(
        default="delete_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Delete File",
            "x-keywords": ["remove file", "delete upload", "erase file"],
        },
        title="Delete File",
    )
    file: str = Field(..., title="File ID", description="File ID to delete")

    # ============================================================================
    # Search Configuration Models
    # ============================================================================
    send_as: SendAs = _send_as_field()


class SlackSearchMessagesConfig(BaseModel):
    """Search for messages in the workspace"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_workspace_messages"] = Field(
        default="search_workspace_messages",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search Workspace Messages",
            "x-keywords": [
                "search messages",
                "find a message",
                "message search",
                "search chats",
            ],
        },
        title="Search Workspace Messages",
    )
    query: str = Field(
        ...,
        title="Search Query",
        description="Search query (supports Slack search modifiers)",
    )
    sort: Optional[Literal["score", "timestamp"]] = Field(
        default="score",
        title="Sort By",
        description="Sort results by relevance (score) or date (timestamp)",
    )
    sort_dir: Optional[Literal["asc", "desc"]] = Field(
        default="desc", title="Sort Direction", description="Sort direction"
    )
    count: Optional[int] = Field(
        default=20, title="Count", description="Number of results to return"
    )


# ============================================================================
# Team/Auth Configuration Models
# ============================================================================


class SlackAuthTestConfig(BaseModel):
    """Test authentication and get info about the token"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["test_authentication"] = Field(
        default="test_authentication",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Authentication",
            "x-is-trigger": False,
            "x-display-name": "Test Authentication",
            "x-keywords": [
                "auth test",
                "whoami token",
                "verify token identity",
                "check signed in",
            ],
        },
        title="Test Authentication",
    )


class SlackTeamInfoConfig(BaseModel):
    """Get information about the workspace"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_workspace_information"] = Field(
        default="get_workspace_information",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Get Workspace Information",
            "x-keywords": [
                "workspace info",
                "team details",
                "workspace name domain",
                "about this workspace",
            ],
        },
        title="Get Workspace Information",
    )


# ============================================================================
# Additional API Operations
# ============================================================================


class SlackUploadFileConfig(BaseModel):
    """Upload a file to Slack"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["upload_file_to_slack"] = Field(
        default="upload_file_to_slack",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Upload File to Slack",
            "x-keywords": ["upload file", "share file", "attach file", "send file"],
        },
        title="Upload File to Slack",
    )
    channels: Optional[str] = Field(
        default=None,
        title="Channels",
        description="Comma-separated list of channel IDs to share the file to",
    )
    content: Optional[str] = Field(
        default=None,
        title="Content",
        description="File contents: plain text, or — for binary — a URL, an upstream file reference (e.g. {{http-1.response.url}}), or a data: URI.",
    )
    filename: Optional[str] = Field(
        default=None, title="Filename", description="Filename of file"
    )
    filetype: Optional[str] = Field(
        default=None,
        title="File Type",
        description="File type identifier (e.g., 'text', 'python', 'json')",
    )
    initial_comment: Optional[str] = Field(
        default=None,
        title="Initial Comment",
        description="Initial comment to add to the file",
    )
    thread_ts: Optional[str] = Field(
        default=None,
        title="Thread Timestamp",
        description="Thread timestamp to reply to",
    )
    title: Optional[str] = Field(
        default=None, title="Title", description="Title of file"
    )
    send_as: SendAs = _send_as_field()


class SlackGetFilePublicURLConfig(BaseModel):
    """Create a public URL for a file (files.sharedPublicURL)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_file_public_url"] = Field(
        default="create_file_public_url",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Create File Public Url",
            "x-keywords": [
                "public file link",
                "share file publicly",
                "make file public",
                "external file url",
            ],
        },
        title="Create File Public Url",
    )
    file: str = Field(
        ..., title="File ID", description="File ID to create public URL for"
    )


class SlackRevokeFilePublicURLConfig(BaseModel):
    """Revoke public URL for a file (files.revokePublicURL)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["revoke_file_public_url"] = Field(
        default="revoke_file_public_url",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Revoke File Public Url",
            "x-keywords": [
                "revoke public link",
                "make file private",
                "disable public url",
                "unshare file publicly",
            ],
        },
        title="Revoke File Public Url",
    )
    file: str = Field(
        ..., title="File ID", description="File ID to revoke public URL for"
    )


class SlackDeleteScheduledMessageConfig(BaseModel):
    """Delete a scheduled message (chat.deleteScheduledMessage)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_scheduled_message"] = Field(
        default="delete_scheduled_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Delete Scheduled Message",
            "x-keywords": [
                "cancel scheduled message",
                "unschedule message",
                "remove queued message",
                "cancel pending post",
            ],
        },
        title="Delete Scheduled Message",
    )
    channel: str = _channel_field("Channel ID containing the scheduled message")
    scheduled_message_id: str = Field(
        ...,
        title="Scheduled Message ID",
        description="ID of the scheduled message to delete",
    )
    send_as: SendAs = _send_as_field()


class SlackListScheduledMessagesConfig(BaseModel):
    """List scheduled messages (chat.scheduledMessages.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_scheduled_messages"] = Field(
        default="list_scheduled_messages",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "List Scheduled Messages",
            "x-keywords": [
                "scheduled messages",
                "queued posts",
                "pending scheduled sends",
                "messages scheduled later",
            ],
        },
        title="List Scheduled Messages",
    )
    channel: Optional[str] = _channel_field(
        "Channel ID to filter by (optional)", default=None
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: Optional[int] = Field(
        default=100,
        title="Limit",
        description="Maximum number of messages to return (default 100, max 100)",
    )
    oldest: Optional[str] = Field(
        default=None,
        title="Oldest",
        description="Unix timestamp of oldest scheduled message",
    )
    latest: Optional[str] = Field(
        default=None,
        title="Latest",
        description="Unix timestamp of latest scheduled message",
    )


class SlackMeMessageConfig(BaseModel):
    """Share a /me message into a channel (chat.meMessage)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["send_me_message"] = Field(
        default="send_me_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Me Message",
            "x-keywords": [
                "me message",
                "slash me action",
                "italic action message",
                "third person message",
            ],
        },
        title="Send Me Message",
    )
    channel: str = _channel_field("Channel ID to post to")
    text: str = Field(..., title="Text", description="Text of the /me message")


class SlackUnfurlConfig(BaseModel):
    """Provide custom unfurl behavior for URLs (chat.unfurl)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["provide_custom_unfurl_behavior"] = Field(
        default="provide_custom_unfurl_behavior",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Provide Custom Unfurl Behavior",
            "x-keywords": [
                "custom unfurl",
                "link preview attachments",
                "url unfurling",
                "expand link preview",
            ],
        },
        title="Provide Custom Unfurl Behavior",
    )
    channel: str = _channel_field("Channel ID containing the message with URL")
    ts: str = Field(
        ..., title="Message Timestamp", description="Timestamp of the message"
    )
    unfurls: str = Field(
        ..., title="Unfurls", description="JSON string of URL-to-unfurl mappings"
    )


class SlackGetUserProfileConfig(BaseModel):
    """Get a user's profile information (users.profile.get)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_user_profile_information"] = Field(
        default="get_user_profile_information",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User Profile Information",
            "x-keywords": [
                "user profile",
                "profile fields",
                "person profile info",
                "profile photo title",
            ],
        },
        title="Get User Profile Information",
    )
    user: Optional[str] = Field(
        default=None,
        title="User ID",
        description="User ID to get profile for (defaults to authed user)",
    )
    include_labels: Optional[bool] = Field(
        default=False,
        title="Include Labels",
        description="Include custom profile field labels",
    )


class SlackSetUserPresenceConfig(BaseModel):
    """Set user presence (users.setPresence)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_user_presence_status"] = Field(
        default="set_user_presence_status",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Set User Presence Status",
            "x-keywords": [
                "set presence",
                "mark away",
                "set online offline",
                "presence auto away",
            ],
        },
        title="Set User Presence Status",
    )
    presence: Literal["auto", "away"] = Field(
        ..., title="Presence", description="Presence status: 'auto' (online) or 'away'"
    )


class SlackSearchFilesConfig(BaseModel):
    """Search for files in the workspace (search.files)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_workspace_files"] = Field(
        default="search_workspace_files",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search Workspace Files",
            "x-keywords": ["search files", "find a file", "file search"],
        },
        title="Search Workspace Files",
    )
    query: str = Field(..., title="Query", description="Search query string")
    count: Optional[int] = Field(
        default=20, title="Count", description="Number of results per page (default 20)"
    )
    page: Optional[int] = Field(
        default=1, title="Page", description="Page number of results"
    )
    sort: Optional[Literal["score", "timestamp"]] = Field(
        default="score",
        title="Sort",
        description="Sort by score (relevance) or timestamp",
    )
    sort_dir: Optional[Literal["asc", "desc"]] = Field(
        default="desc", title="Sort Direction", description="Sort direction"
    )


class SlackSearchAllConfig(BaseModel):
    """Search for messages and files (search.all)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_messages_and_files"] = Field(
        default="search_messages_and_files",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search Messages and Files",
            "x-keywords": [
                "search everything",
                "search all",
                "find messages and files",
                "global search",
            ],
        },
        title="Search Messages and Files",
    )
    query: str = Field(..., title="Query", description="Search query string")
    count: Optional[int] = Field(
        default=20, title="Count", description="Number of results per page"
    )
    page: Optional[int] = Field(
        default=1, title="Page", description="Page number of results"
    )
    sort: Optional[Literal["score", "timestamp"]] = Field(
        default="score",
        title="Sort",
        description="Sort by score (relevance) or timestamp",
    )
    sort_dir: Optional[Literal["asc", "desc"]] = Field(
        default="desc", title="Sort Direction", description="Sort direction"
    )


class SlackApiTestConfig(BaseModel):
    """Test the API connection (api.test)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["test_api_connection"] = Field(
        default="test_api_connection",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Authentication",
            "x-is-trigger": False,
            "x-display-name": "Test Api Connection",
            "x-keywords": [
                "api test",
                "ping slack api",
                "connectivity check",
                "api health check",
            ],
        },
        title="Test Api Connection",
    )


class SlackAuthRevokeConfig(BaseModel):
    """Revoke an OAuth token (auth.revoke)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["revoke_oauth_token"] = Field(
        default="revoke_oauth_token",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Authentication",
            "x-is-trigger": False,
            "x-display-name": "Revoke Oauth Token",
            "x-keywords": [
                "revoke token",
                "invalidate access token",
                "sign out token",
                "deauthorize token",
            ],
        },
        title="Revoke Oauth Token",
    )
    test: Optional[bool] = Field(
        default=False,
        title="Test Mode",
        description="If true, don't actually revoke the token",
    )


class SlackAppsUninstallConfig(BaseModel):
    """Uninstall an app from a workspace (apps.uninstall)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["uninstall_app_from_workspace"] = Field(
        default="uninstall_app_from_workspace",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "App",
            "x-is-trigger": False,
            "x-display-name": "Uninstall App from Workspace",
            "x-keywords": [
                "uninstall app",
                "remove integration",
                "deauthorize app",
                "uninstall bot",
            ],
        },
        title="Uninstall App from Workspace",
    )


class SlackTeamBillableInfoConfig(BaseModel):
    """Get billable info for team members (team.billableInfo)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_team_billable_information"] = Field(
        default="get_team_billable_information",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Get Team Billable Information",
            "x-keywords": [
                "billable members",
                "billing info",
                "active seats",
                "paid seats",
            ],
        },
        title="Get Team Billable Information",
    )
    user: Optional[str] = Field(
        default=None,
        title="User ID",
        description="User ID to get billable info for (optional)",
    )


class SlackTeamAccessLogsConfig(BaseModel):
    """Get access logs for the workspace (team.accessLogs)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_workspace_access_logs"] = Field(
        default="get_workspace_access_logs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Get Workspace Access Logs",
            "x-keywords": [
                "access logs",
                "login history",
                "sign in records",
                "user login audit",
            ],
        },
        title="Get Workspace Access Logs",
    )
    count: Optional[int] = Field(
        default=100, title="Count", description="Number of logs to return"
    )
    page: Optional[int] = Field(default=1, title="Page", description="Page number")
    before: Optional[int] = Field(
        default=None,
        title="Before",
        description="Unix timestamp for filtering (logs before this)",
    )


class SlackTeamIntegrationLogsConfig(BaseModel):
    """Get integration logs for the workspace (team.integrationLogs)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_workspace_integration_logs"] = Field(
        default="get_workspace_integration_logs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Get Workspace Integration Logs",
            "x-keywords": [
                "integration logs",
                "app activity audit",
                "bot integration history",
                "third party app log",
            ],
        },
        title="Get Workspace Integration Logs",
    )
    count: Optional[int] = Field(
        default=100, title="Count", description="Number of logs to return"
    )
    page: Optional[int] = Field(default=1, title="Page", description="Page number")
    app_id: Optional[str] = Field(
        default=None, title="App ID", description="Filter by app ID"
    )
    change_type: Optional[str] = Field(
        default=None,
        title="Change Type",
        description="Filter by change type (e.g., 'added')",
    )
    service_id: Optional[str] = Field(
        default=None, title="Service ID", description="Filter by service ID"
    )
    user: Optional[str] = Field(
        default=None, title="User ID", description="Filter by user ID"
    )


class SlackConversationsAcceptSharedInviteConfig(BaseModel):
    """Accept a shared channel invite (conversations.acceptSharedInvite)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["accept_shared_channel_invite"] = Field(
        default="accept_shared_channel_invite",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Slack Connect",
            "x-is-trigger": False,
            "x-display-name": "Accept Shared Channel Invite",
            "x-keywords": [
                "accept slack connect",
                "join shared channel",
                "accept external invite",
                "confirm shared channel",
            ],
        },
        title="Accept Shared Channel Invite",
    )
    channel_name: str = Field(
        ..., title="Channel Name", description="Name of the channel"
    )
    channel_id: Optional[str] = _channel_field(
        "ID of the channel", title="Channel ID", field_name="channel_id", default=None
    )
    invite_id: Optional[str] = Field(
        default=None, title="Invite ID", description="ID of the invite"
    )
    is_private: Optional[bool] = Field(
        default=None, title="Is Private", description="Whether the channel is private"
    )
    team_id: Optional[str] = Field(
        default=None, title="Team ID", description="Team ID to accept for"
    )


class SlackConversationsDeclineSharedInviteConfig(BaseModel):
    """Decline a shared channel invite (conversations.declineSharedInvite)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["decline_shared_channel_invite"] = Field(
        default="decline_shared_channel_invite",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Slack Connect",
            "x-is-trigger": False,
            "x-display-name": "Decline Shared Channel Invite",
            "x-keywords": [
                "decline slack connect",
                "reject shared channel",
                "refuse external invite",
                "deny connect invite",
            ],
        },
        title="Decline Shared Channel Invite",
    )
    invite_id: str = Field(
        ..., title="Invite ID", description="ID of the invite to decline"
    )
    target_team: Optional[str] = Field(
        default=None, title="Target Team", description="Target team ID"
    )


class SlackConversationsListConnectInvitesConfig(BaseModel):
    """List Slack Connect invites (conversations.listConnectInvites)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_slack_connect_invites"] = Field(
        default="list_slack_connect_invites",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Slack Connect",
            "x-is-trigger": False,
            "x-display-name": "List Slack Connect Invites",
            "x-keywords": [
                "slack connect invites",
                "shared channel invites",
                "external invites list",
                "pending connect invites",
            ],
        },
        title="List Slack Connect Invites",
    )
    count: Optional[int] = Field(
        default=100, title="Count", description="Number of invites to return"
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    team_id: Optional[str] = Field(
        default=None, title="Team ID", description="Team ID to list invites for"
    )


# ============================================================================
# New File Upload Operations (files.upload deprecated Nov 2025)
# ============================================================================


class SlackGetUploadURLExternalConfig(BaseModel):
    """Get URL for uploading a file externally (files.getUploadURLExternal)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_external_file_upload_url"] = Field(
        default="get_external_file_upload_url",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Get External File Upload Url",
            "x-keywords": [
                "upload url",
                "external upload link",
                "presigned upload",
                "start external upload",
            ],
        },
        title="Get External File Upload Url",
    )
    filename: str = Field(
        ..., title="Filename", description="Name of the file being uploaded"
    )
    length: int = Field(..., title="File Size", description="Size of the file in bytes")
    alt_txt: Optional[str] = Field(
        default=None,
        title="Alt Text",
        description="Alternative text for the file (for accessibility)",
    )
    snippet_type: Optional[str] = Field(
        default=None,
        title="Snippet Type",
        description="Syntax type for code snippets (e.g., python, javascript)",
    )


class SlackCompleteUploadExternalConfig(BaseModel):
    """Complete a file upload after uploading to external URL (files.completeUploadExternal)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["complete_external_file_upload"] = Field(
        default="complete_external_file_upload",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Complete External File Upload",
            "x-keywords": [
                "finish upload",
                "finalize external upload",
                "commit uploaded file",
                "register uploaded file",
            ],
        },
        title="Complete External File Upload",
    )
    files: str = Field(
        ...,
        title="Files",
        description='JSON array of file objects with id and title (e.g., [{"id": "F123", "title": "myfile.txt"}])',
    )
    channel_id: Optional[str] = _channel_field(
        "Channel to share the file in",
        title="Channel ID",
        field_name="channel_id",
        default=None,
    )
    initial_comment: Optional[str] = Field(
        default=None,
        title="Initial Comment",
        description="Message to post with the file",
    )
    thread_ts: Optional[str] = Field(
        default=None,
        title="Thread Timestamp",
        description="Thread to reply to when sharing",
    )


# ============================================================================
# User Profile Operations
# ============================================================================


class SlackSetUserProfileConfig(BaseModel):
    """Set user profile fields (users.profile.set)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_user_profile_fields"] = Field(
        default="set_user_profile_fields",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Set User Profile Fields",
            "x-keywords": [
                "edit profile",
                "update profile fields",
                "set profile title",
                "set custom fields",
            ],
        },
        title="Set User Profile Fields",
    )
    profile: str = Field(
        ...,
        title="Profile",
        description='JSON object of profile fields to set (e.g., {"status_text": "Working from home", "status_emoji": ":house:"})',
    )
    user: Optional[str] = Field(
        default=None,
        title="User ID",
        description="User ID to set profile for (admin only, defaults to current user)",
    )


# ============================================================================
# Additional Slack Connect Operations
# ============================================================================


class SlackApproveSharedInviteConfig(BaseModel):
    """Approve an invitation to a Slack Connect channel (conversations.approveSharedInvite)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["approve_slack_connect_channel_invite"] = Field(
        default="approve_slack_connect_channel_invite",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Slack Connect",
            "x-is-trigger": False,
            "x-display-name": "Approve Slack Connect Channel Invite",
            "x-keywords": [
                "approve shared channel",
                "approve connect channel",
                "allow external channel",
                "grant shared channel",
            ],
        },
        title="Approve Slack Connect Channel Invite",
    )
    invite_id: str = Field(
        ..., title="Invite ID", description="ID of the Slack Connect invite to approve"
    )
    channel_id: Optional[str] = _channel_field(
        "ID of the channel to approve (if known)",
        title="Channel ID",
        field_name="channel_id",
        default=None,
    )
    is_private: Optional[bool] = Field(
        default=None,
        title="Is Private",
        description="Whether to make the channel private",
    )
    target_team: Optional[str] = Field(
        default=None,
        title="Target Team",
        description="Team ID to approve for (multi-workspace apps only)",
    )


class SlackInviteSharedConfig(BaseModel):
    """Invite a user to a Slack Connect channel (conversations.inviteShared)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["invite_user_to_slack_connect_channel"] = Field(
        default="invite_user_to_slack_connect_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Slack Connect",
            "x-is-trigger": False,
            "x-display-name": "Invite User to Slack Connect Channel",
            "x-keywords": [
                "invite external user",
                "invite to shared channel",
                "invite cross workspace",
                "add external partner",
            ],
        },
        title="Invite User to Slack Connect Channel",
    )
    channel: str = _channel_field("ID of the channel to invite to", title="Channel ID")
    emails: Optional[str] = Field(
        default=None,
        title="Emails",
        description="Comma-separated list of email addresses to invite",
    )
    user_ids: Optional[str] = Field(
        default=None,
        title="User IDs",
        description="Comma-separated list of user IDs to invite",
    )
    external_limited: Optional[bool] = Field(
        default=None,
        title="External Limited",
        description="Whether to limit external users to just this channel",
    )


# ============================================================================
# Remote File Operations
# ============================================================================


class SlackAddRemoteFileConfig(BaseModel):
    """Add a remote file (files.remote.add)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_remote_file_to_workspace"] = Field(
        default="add_remote_file_to_workspace",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Add Remote File to Workspace",
            "x-keywords": [
                "add remote file",
                "register external file",
                "link external file",
                "import hosted file",
            ],
        },
        title="Add Remote File to Workspace",
    )
    external_id: str = Field(
        ...,
        title="External ID",
        description="Unique identifier for the remote file in your system",
    )
    external_url: str = Field(
        ..., title="External URL", description="URL of the remote file"
    )
    title: str = Field(..., title="Title", description="Title of the file")
    filetype: Optional[str] = Field(
        default=None, title="File Type", description="File type (e.g., 'pdf', 'docx')"
    )
    preview_image: Optional[str] = Field(
        default=None, title="Preview Image", description="URL for preview image"
    )
    indexable_file_contents: Optional[str] = Field(
        default=None,
        title="Indexable Content",
        description="Text content for search indexing",
    )


class SlackRemoveRemoteFileConfig(BaseModel):
    """Remove a remote file (files.remote.remove)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_remote_file"] = Field(
        default="remove_remote_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Remove Remote File",
            "x-keywords": [
                "remove remote file",
                "delete external file",
                "unlink hosted file",
                "remove cloud file",
            ],
        },
        title="Remove Remote File",
    )
    external_id: Optional[str] = Field(
        default=None,
        title="External ID",
        description="External ID of the remote file to remove",
    )
    file: Optional[str] = Field(
        default=None, title="File ID", description="Slack file ID to remove"
    )


class SlackShareRemoteFileConfig(BaseModel):
    """Share a remote file to a channel (files.remote.share)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["share_remote_file_to_channel"] = Field(
        default="share_remote_file_to_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Share Remote File to Channel",
            "x-keywords": [
                "share remote file",
                "post external file",
                "send hosted file",
                "share cloud file",
            ],
        },
        title="Share Remote File to Channel",
    )
    channels: str = Field(
        ...,
        title="Channels",
        description="Comma-separated list of channel IDs to share to",
    )
    external_id: Optional[str] = Field(
        default=None,
        title="External ID",
        description="External ID of the remote file to share",
    )
    file: Optional[str] = Field(
        default=None, title="File ID", description="Slack file ID to share"
    )


class SlackListRemoteFilesConfig(BaseModel):
    """List remote files (files.remote.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_remote_files"] = Field(
        default="list_remote_files",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "List Remote Files",
            "x-keywords": [
                "remote files",
                "external files",
                "hosted files list",
                "linked files",
            ],
        },
        title="List Remote Files",
    )
    channel: Optional[str] = _channel_field("Filter by channel ID", default=None)
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of files to return"
    )
    ts_from: Optional[str] = Field(
        default=None,
        title="From Timestamp",
        description="Filter files created after this timestamp",
    )
    ts_to: Optional[str] = Field(
        default=None,
        title="To Timestamp",
        description="Filter files created before this timestamp",
    )


class SlackListReactionsConfig(BaseModel):
    """List reactions for an item (reactions.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_reactions_for_item"] = Field(
        default="list_reactions_for_item",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "List Reactions for Item",
            "x-keywords": [
                "item reactions",
                "list emoji reactions",
                "who reacted",
                "reactions on item",
            ],
        },
        title="List Reactions for Item",
    )
    channel: Optional[str] = _channel_field(
        "Channel where the message was posted", default=None
    )
    file: Optional[str] = Field(
        default=None, title="File ID", description="File to get reactions for"
    )
    file_comment: Optional[str] = Field(
        default=None,
        title="File Comment ID",
        description="File comment to get reactions for",
    )
    timestamp: Optional[str] = Field(
        default=None,
        title="Message Timestamp",
        description="Timestamp of the message to get reactions for",
    )
    full: bool = Field(
        default=False,
        title="Full",
        description="If true, return complete reaction list",
    )


class SlackRemoteFileInfoConfig(BaseModel):
    """Get information about a remote file (files.remote.info)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_remote_file_information"] = Field(
        default="get_remote_file_information",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Get Remote File Information",
            "x-keywords": [
                "remote file info",
                "external file details",
                "hosted file metadata",
                "linked file details",
            ],
        },
        title="Get Remote File Information",
    )
    external_id: Optional[str] = Field(
        default=None,
        title="External ID",
        description="Creator-defined unique ID for the file",
    )
    file: Optional[str] = Field(
        default=None, title="File ID", description="Slack file ID"
    )


class SlackRemoteFileUpdateConfig(BaseModel):
    """Update a remote file (files.remote.update)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_remote_file"] = Field(
        default="update_remote_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Update Remote File",
            "x-keywords": [
                "edit remote file",
                "update external file",
                "change hosted file",
                "update linked file",
            ],
        },
        title="Update Remote File",
    )
    external_id: Optional[str] = Field(
        default=None,
        title="External ID",
        description="Creator-defined unique ID for the file",
    )
    file: Optional[str] = Field(
        default=None, title="File ID", description="Slack file ID"
    )
    title: Optional[str] = Field(
        default=None, title="Title", description="New title for the file"
    )
    external_url: Optional[str] = Field(
        default=None, title="External URL", description="URL of the remote file"
    )
    filetype: Optional[str] = Field(
        default=None,
        title="File Type",
        description="Type of file (e.g., 'gdoc', 'gsheet')",
    )
    indexable_file_contents: Optional[str] = Field(
        default=None,
        title="Indexable Contents",
        description="File contents for search indexing",
    )
    preview_image: Optional[str] = Field(
        default=None,
        title="Preview Image",
        description="Base64 preview image for the file",
    )


class SlackDeleteFileCommentConfig(BaseModel):
    """Delete a file comment (files.comments.delete)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_file_comment"] = Field(
        default="delete_file_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Delete File Comment",
            "x-keywords": [
                "delete file comment",
                "remove file comment",
                "erase comment on file",
                "delete attachment comment",
            ],
        },
        title="Delete File Comment",
    )
    file: str = Field(..., title="File ID", description="File containing the comment")
    id: str = Field(..., title="Comment ID", description="ID of the comment to delete")


class SlackDeleteUserPhotoConfig(BaseModel):
    """Delete the user's profile photo (users.deletePhoto)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_user_profile_photo"] = Field(
        default="delete_user_profile_photo",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Delete User Profile Photo",
            "x-keywords": [
                "remove profile photo",
                "delete avatar",
                "clear profile picture",
                "remove profile image",
            ],
        },
        title="Delete User Profile Photo",
    )
    # This method takes no parameters


class SlackSetUserActiveConfig(BaseModel):
    """Mark user as active (users.setActive) - Deprecated but still functional"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_user_as_active"] = Field(
        default="set_user_as_active",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Set User As Active",
            "x-keywords": [
                "mark active",
                "set user active",
                "presence active",
                "flag user online",
            ],
        },
        title="Set User As Active",
    )
    # This method takes no parameters


class SlackCreateCanvasConfig(BaseModel):
    """Create a canvas in a channel (conversations.canvases.create)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_canvas_in_channel"] = Field(
        default="create_canvas_in_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Create Canvas in Channel",
            "x-keywords": [
                "create canvas",
                "new channel canvas",
                "add canvas doc",
                "make canvas",
            ],
        },
        title="Create Canvas in Channel",
    )
    channel_id: str = _channel_field(
        "Channel to create the canvas in", title="Channel ID", field_name="channel_id"
    )
    document_content: Optional[str] = Field(
        default=None,
        title="Document Content",
        description="JSON structure for initial canvas content",
    )


class SlackSetExternalInvitePermissionsConfig(BaseModel):
    """Set external invite permissions for a channel (conversations.externalInvitePermissions.set)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_channel_external_invite_permissions"] = Field(
        default="set_channel_external_invite_permissions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Set Channel External Invite Permissions",
            "x-keywords": [
                "external invite permissions",
                "channel connect permissions",
                "who can invite externally",
                "limit external invites",
            ],
        },
        title="Set Channel External Invite Permissions",
    )
    channel: str = _channel_field(
        "Channel to modify permissions for", title="Channel ID"
    )
    action_type: str = Field(
        ..., title="Action", description="Permission action: 'upgrade' or 'downgrade'"
    )


class SlackApproveSharedInviteRequestConfig(BaseModel):
    """Approve a Slack Connect invite request (conversations.requestSharedInvite.approve)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["approve_slack_connect_invite_request"] = Field(
        default="approve_slack_connect_invite_request",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Slack Connect",
            "x-is-trigger": False,
            "x-display-name": "Approve Slack Connect Invite Request",
            "x-keywords": [
                "approve invite request",
                "approve connect request",
                "grant shared invite request",
                "allow connect request",
            ],
        },
        title="Approve Slack Connect Invite Request",
    )
    invite_id: str = Field(
        ..., title="Invite ID", description="ID of the invite request to approve"
    )
    channel_id: Optional[str] = _channel_field(
        "Channel to use for the connection",
        title="Channel ID",
        field_name="channel_id",
        default=None,
    )
    is_external_limited: bool = Field(
        default=False,
        title="External Limited",
        description="Whether the channel should be external limited",
    )
    message: Optional[str] = Field(
        default=None, title="Message", description="Message to include with approval"
    )


class SlackDenySharedInviteRequestConfig(BaseModel):
    """Deny a Slack Connect invite request (conversations.requestSharedInvite.deny)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["deny_slack_connect_invite_request"] = Field(
        default="deny_slack_connect_invite_request",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Slack Connect",
            "x-is-trigger": False,
            "x-display-name": "Deny Slack Connect Invite Request",
            "x-keywords": [
                "reject slack connect request",
                "deny connect invite",
                "refuse shared invite request",
                "decline connect request",
            ],
        },
        title="Deny Slack Connect Invite Request",
    )
    invite_id: str = Field(
        ..., title="Invite ID", description="ID of the invite request to deny"
    )
    message: Optional[str] = Field(
        default=None, title="Message", description="Message to include with denial"
    )


class SlackListSharedInviteRequestsConfig(BaseModel):
    """List Slack Connect invite requests (conversations.requestSharedInvite.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_slack_connect_invite_requests"] = Field(
        default="list_slack_connect_invite_requests",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Slack Connect",
            "x-is-trigger": False,
            "x-display-name": "List Slack Connect Invite Requests",
            "x-keywords": [
                "pending connect requests",
                "slack connect invite requests",
                "shared channel requests",
                "incoming connect requests",
            ],
        },
        title="List Slack Connect Invite Requests",
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    include_approved: bool = Field(
        default=False, title="Include Approved", description="Include approved requests"
    )
    include_denied: bool = Field(
        default=False, title="Include Denied", description="Include denied requests"
    )
    include_expired: bool = Field(
        default=False, title="Include Expired", description="Include expired requests"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of requests to return"
    )


# ============================================================================
# Admin API Configuration Models (Enterprise Grid)
# These operations require admin-level permissions
# ============================================================================

# --- admin.analytics (1) ---


class SlackAdminAnalyticsGetFileConfig(BaseModel):
    """Get analytics data for a given date (admin.analytics.getFile)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_analytics_file_for_date"] = Field(
        default="get_analytics_file_for_date",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Analytics",
            "x-is-trigger": False,
            "x-display-name": "Get Analytics File for Date",
            "x-keywords": [
                "workspace analytics file",
                "usage analytics export",
                "daily analytics data",
                "member activity stats",
            ],
        },
        title="Get Analytics File for Date",
    )
    type: str = Field(
        ...,
        title="Analytics Type",
        description="Type of analytics to retrieve (e.g., 'member', 'public_channel')",
    )
    date: Optional[str] = Field(
        default=None,
        title="Date",
        description="Date to retrieve analytics for (YYYY-MM-DD format)",
    )
    metadata_only: bool = Field(
        default=False,
        title="Metadata Only",
        description="Return only metadata without the file content",
    )


# --- admin.apps (11) ---


class SlackAdminAppsActivitiesListConfig(BaseModel):
    """Get logs for app activities (admin.apps.activities.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_app_activity_logs"] = Field(
        default="list_app_activity_logs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "App",
            "x-is-trigger": False,
            "x-display-name": "List App Activity Logs",
            "x-keywords": [
                "app activity history",
                "installed app logs",
                "app usage logs",
                "app audit trail",
            ],
        },
        title="List App Activity Logs",
    )
    app_id: Optional[str] = Field(
        default=None, title="App ID", description="Filter by app ID"
    )
    component_id: Optional[str] = Field(
        default=None, title="Component ID", description="Filter by component ID"
    )
    component_type: Optional[str] = Field(
        default=None, title="Component Type", description="Filter by component type"
    )
    log_event_type: Optional[str] = Field(
        default=None, title="Log Event Type", description="Filter by log event type"
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results to return"
    )
    max_date_created: Optional[int] = Field(
        default=None,
        title="Max Date Created",
        description="Filter activities created before this timestamp",
    )
    min_date_created: Optional[int] = Field(
        default=None,
        title="Min Date Created",
        description="Filter activities created after this timestamp",
    )
    sort_direction: str = Field(
        default="desc",
        title="Sort Direction",
        description="Sort direction ('asc' or 'desc')",
    )
    source: Optional[str] = Field(
        default=None, title="Source", description="Filter by source"
    )
    team_id: Optional[str] = Field(
        default=None, title="Team ID", description="Filter by team ID"
    )


class SlackAdminAppsApproveConfig(BaseModel):
    """Approve an app for installation (admin.apps.approve)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["approve_app_for_installation"] = Field(
        default="approve_app_for_installation",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "App",
            "x-is-trigger": False,
            "x-display-name": "Approve App for Installation",
            "x-keywords": [
                "allow app install",
                "approve installation",
                "whitelist app",
                "permit app",
            ],
        },
        title="Approve App for Installation",
    )
    app_id: Optional[str] = Field(
        default=None, title="App ID", description="ID of the app to approve"
    )
    request_id: Optional[str] = Field(
        default=None, title="Request ID", description="ID of the request to approve"
    )
    enterprise_id: Optional[str] = Field(
        default=None, title="Enterprise ID", description="Enterprise ID to approve for"
    )
    team_id: Optional[str] = Field(
        default=None, title="Team ID", description="Team ID to approve for"
    )


class SlackAdminAppsApprovedListConfig(BaseModel):
    """List approved apps (admin.apps.approved.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_approved_apps"] = Field(
        default="list_approved_apps",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "App",
            "x-is-trigger": False,
            "x-display-name": "List Approved Apps",
            "x-keywords": [
                "allowed apps",
                "whitelisted apps",
                "permitted apps",
                "approved integrations",
            ],
        },
        title="List Approved Apps",
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    enterprise_id: Optional[str] = Field(
        default=None, title="Enterprise ID", description="Enterprise ID to filter by"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )
    team_id: Optional[str] = Field(
        default=None, title="Team ID", description="Team ID to filter by"
    )


class SlackAdminAppsClearResolutionConfig(BaseModel):
    """Clear app resolution (admin.apps.clearResolution)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["clear_app_resolution"] = Field(
        default="clear_app_resolution",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "App",
            "x-is-trigger": False,
            "x-display-name": "Clear App Resolution",
            "x-keywords": [
                "reset app decision",
                "undo app approval",
                "clear approve deny",
                "reset app status",
            ],
        },
        title="Clear App Resolution",
    )
    app_id: str = Field(
        ..., title="App ID", description="ID of the app to clear resolution for"
    )
    enterprise_id: Optional[str] = Field(
        default=None, title="Enterprise ID", description="Enterprise ID"
    )
    team_id: Optional[str] = Field(default=None, title="Team ID", description="Team ID")


class SlackAdminAppsConfigLookupConfig(BaseModel):
    """Look up app config (admin.apps.config.lookup)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["lookup_app_configuration"] = Field(
        default="lookup_app_configuration",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "App",
            "x-is-trigger": False,
            "x-display-name": "Lookup App Configuration",
            "x-keywords": [
                "read app config",
                "app settings lookup",
                "check app configuration",
                "app config details",
            ],
        },
        title="Lookup App Configuration",
    )
    app_ids: List[str] = Field(
        ..., title="App IDs", description="List of app IDs to look up"
    )


class SlackAdminAppsConfigSetConfig(BaseModel):
    """Set app config (admin.apps.config.set)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_app_configuration"] = Field(
        default="set_app_configuration",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "App",
            "x-is-trigger": False,
            "x-display-name": "Set App Configuration",
            "x-keywords": [
                "configure app settings",
                "change app config",
                "app configuration set",
                "apply app settings",
            ],
        },
        title="Set App Configuration",
    )
    app_id: str = Field(..., title="App ID", description="ID of the app")
    domain_restrictions: Optional[str] = Field(
        default=None,
        title="Domain Restrictions",
        description="JSON object containing domain restrictions",
    )
    workflow_auth_strategy: Optional[str] = Field(
        default=None,
        title="Workflow Auth Strategy",
        description="Workflow authentication strategy",
    )


class SlackAdminAppsRequestsCancelConfig(BaseModel):
    """Cancel an app request (admin.apps.requests.cancel)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["cancel_app_request"] = Field(
        default="cancel_app_request",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "App",
            "x-is-trigger": False,
            "x-display-name": "Cancel App Request",
            "x-keywords": [
                "withdraw app request",
                "abort install request",
                "rescind app request",
            ],
        },
        title="Cancel App Request",
    )
    request_id: str = Field(
        ..., title="Request ID", description="ID of the request to cancel"
    )
    enterprise_id: Optional[str] = Field(
        default=None, title="Enterprise ID", description="Enterprise ID"
    )
    team_id: Optional[str] = Field(default=None, title="Team ID", description="Team ID")


class SlackAdminAppsRequestsListConfig(BaseModel):
    """List app requests (admin.apps.requests.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_app_requests"] = Field(
        default="list_app_requests",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "App",
            "x-is-trigger": False,
            "x-display-name": "List App Requests",
            "x-keywords": [
                "pending app installs",
                "app install requests",
                "requested apps",
                "apps awaiting approval",
            ],
        },
        title="List App Requests",
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    enterprise_id: Optional[str] = Field(
        default=None, title="Enterprise ID", description="Enterprise ID to filter by"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )
    team_id: Optional[str] = Field(
        default=None, title="Team ID", description="Team ID to filter by"
    )


class SlackAdminAppsRestrictConfig(BaseModel):
    """Restrict an app (admin.apps.restrict)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["restrict_app"] = Field(
        default="restrict_app",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "App",
            "x-is-trigger": False,
            "x-display-name": "Restrict App",
            "x-keywords": [
                "block app",
                "blacklist app",
                "deny app usage",
                "ban integration",
            ],
        },
        title="Restrict App",
    )
    app_id: Optional[str] = Field(
        default=None, title="App ID", description="ID of the app to restrict"
    )
    request_id: Optional[str] = Field(
        default=None, title="Request ID", description="ID of the request to restrict"
    )
    enterprise_id: Optional[str] = Field(
        default=None, title="Enterprise ID", description="Enterprise ID"
    )
    team_id: Optional[str] = Field(default=None, title="Team ID", description="Team ID")


class SlackAdminAppsRestrictedListConfig(BaseModel):
    """List restricted apps (admin.apps.restricted.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_restricted_apps"] = Field(
        default="list_restricted_apps",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "App",
            "x-is-trigger": False,
            "x-display-name": "List Restricted Apps",
            "x-keywords": [
                "blocked apps",
                "blacklisted apps",
                "banned integrations",
                "denied apps",
            ],
        },
        title="List Restricted Apps",
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    enterprise_id: Optional[str] = Field(
        default=None, title="Enterprise ID", description="Enterprise ID to filter by"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )
    team_id: Optional[str] = Field(
        default=None, title="Team ID", description="Team ID to filter by"
    )


class SlackAdminAppsUninstallConfig(BaseModel):
    """Uninstall an app (admin.apps.uninstall)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["uninstall_app"] = Field(
        default="uninstall_app",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "App",
            "x-is-trigger": False,
            "x-display-name": "Uninstall App",
            "x-keywords": [
                "remove installed app",
                "remove integration",
                "uninstall integration",
            ],
        },
        title="Uninstall App",
    )
    app_id: str = Field(..., title="App ID", description="ID of the app to uninstall")
    enterprise_id: Optional[str] = Field(
        default=None, title="Enterprise ID", description="Enterprise ID"
    )
    team_ids: Optional[List[str]] = Field(
        default=None, title="Team IDs", description="List of team IDs to uninstall from"
    )


# --- admin.audit (2) ---


class SlackAdminAuditAnomalyAllowGetItemConfig(BaseModel):
    """Get allowed audit anomaly item (admin.audit.anomaly.allow.getItem)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_allowed_audit_anomaly_item"] = Field(
        default="get_allowed_audit_anomaly_item",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Audit",
            "x-is-trigger": False,
            "x-display-name": "Get Allowed Audit Anomaly Item",
            "x-keywords": [
                "read audit anomaly allow",
                "allowed anomaly item",
                "anomaly allowlist entry",
            ],
        },
        title="Get Allowed Audit Anomaly Item",
    )
    constraint_type: str = Field(
        ..., title="Constraint Type", description="Type of constraint"
    )
    constraint_resource: str = Field(
        ..., title="Constraint Resource", description="Resource ID for the constraint"
    )


class SlackAdminAuditAnomalyAllowUpdateItemConfig(BaseModel):
    """Update allowed audit anomaly item (admin.audit.anomaly.allow.updateItem)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_allowed_audit_anomaly_item"] = Field(
        default="update_allowed_audit_anomaly_item",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Audit",
            "x-is-trigger": False,
            "x-display-name": "Update Allowed Audit Anomaly Item",
            "x-keywords": [
                "edit audit anomaly allow",
                "change anomaly allowlist",
                "modify allowed anomaly",
            ],
        },
        title="Update Allowed Audit Anomaly Item",
    )
    constraint_type: str = Field(
        ..., title="Constraint Type", description="Type of constraint"
    )
    constraint_resource: str = Field(
        ..., title="Constraint Resource", description="Resource ID for the constraint"
    )
    allow_list: List[str] = Field(
        ..., title="Allow List", description="List of items to allow"
    )


# --- admin.auth.policy (3) ---


class SlackAdminAuthPolicyAssignEntitiesConfig(BaseModel):
    """Assign entities to auth policy (admin.auth.policy.assignEntities)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["assign_entities_to_auth_policy"] = Field(
        default="assign_entities_to_auth_policy",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Auth Policy",
            "x-is-trigger": False,
            "x-display-name": "Assign Entities to Auth Policy",
            "x-keywords": [
                "attach entities policy",
                "apply auth policy",
                "assign users to policy",
                "add to security policy",
            ],
        },
        title="Assign Entities to Auth Policy",
    )
    entity_ids: List[str] = Field(
        ..., title="Entity IDs", description="List of entity IDs to assign"
    )
    entity_type: str = Field(
        ..., title="Entity Type", description="Type of entities being assigned"
    )
    policy_name: str = Field(..., title="Policy Name", description="Name of the policy")


class SlackAdminAuthPolicyGetEntitiesConfig(BaseModel):
    """Get entities for auth policy (admin.auth.policy.getEntities)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_entities_for_auth_policy"] = Field(
        default="get_entities_for_auth_policy",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Auth Policy",
            "x-is-trigger": False,
            "x-display-name": "Get Entities for Auth Policy",
            "x-keywords": [
                "read auth policy members",
                "policy assigned entities",
                "who is on policy",
                "list policy users",
            ],
        },
        title="Get Entities for Auth Policy",
    )
    policy_name: str = Field(..., title="Policy Name", description="Name of the policy")
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    entity_type: Optional[str] = Field(
        default=None, title="Entity Type", description="Filter by entity type"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )


class SlackAdminAuthPolicyRemoveEntitiesConfig(BaseModel):
    """Remove entities from auth policy (admin.auth.policy.removeEntities)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_entities_from_auth_policy"] = Field(
        default="remove_entities_from_auth_policy",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Auth Policy",
            "x-is-trigger": False,
            "x-display-name": "Remove Entities from Auth Policy",
            "x-keywords": [
                "detach entities policy",
                "unassign auth policy",
                "remove from security policy",
            ],
        },
        title="Remove Entities from Auth Policy",
    )
    entity_ids: List[str] = Field(
        ..., title="Entity IDs", description="List of entity IDs to remove"
    )
    entity_type: str = Field(
        ..., title="Entity Type", description="Type of entities being removed"
    )
    policy_name: str = Field(..., title="Policy Name", description="Name of the policy")


# --- admin.barriers (4) ---


class SlackAdminBarriersCreateConfig(BaseModel):
    """Create an information barrier (admin.barriers.create)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_information_barrier"] = Field(
        default="create_information_barrier",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Barrier",
            "x-is-trigger": False,
            "x-display-name": "Create Information Barrier",
            "x-keywords": [
                "new info barrier",
                "add ethical wall",
                "create compliance barrier",
                "block group communication",
            ],
        },
        title="Create Information Barrier",
    )
    barriered_from_usergroup_ids: List[str] = Field(
        ...,
        title="Barriered From Usergroup IDs",
        description="Usergroup IDs that cannot communicate",
    )
    primary_usergroup_id: str = Field(
        ...,
        title="Primary Usergroup ID",
        description="Primary usergroup ID for the barrier",
    )
    restricted_subjects: List[str] = Field(
        ..., title="Restricted Subjects", description="List of restricted subjects"
    )


class SlackAdminBarriersDeleteConfig(BaseModel):
    """Delete an information barrier (admin.barriers.delete)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_information_barrier"] = Field(
        default="delete_information_barrier",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Barrier",
            "x-is-trigger": False,
            "x-display-name": "Delete Information Barrier",
            "x-keywords": [
                "remove info barrier",
                "drop ethical wall",
                "delete compliance barrier",
            ],
        },
        title="Delete Information Barrier",
    )
    barrier_id: str = Field(
        ..., title="Barrier ID", description="ID of the barrier to delete"
    )


class SlackAdminBarriersListConfig(BaseModel):
    """List information barriers (admin.barriers.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_information_barriers"] = Field(
        default="list_information_barriers",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Barrier",
            "x-is-trigger": False,
            "x-display-name": "List Information Barriers",
            "x-keywords": ["all info barriers", "ethical walls", "compliance barriers"],
        },
        title="List Information Barriers",
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )


class SlackAdminBarriersUpdateConfig(BaseModel):
    """Update an information barrier (admin.barriers.update)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_information_barrier"] = Field(
        default="update_information_barrier",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Barrier",
            "x-is-trigger": False,
            "x-display-name": "Update Information Barrier",
            "x-keywords": [
                "edit info barrier",
                "modify ethical wall",
                "change compliance barrier",
            ],
        },
        title="Update Information Barrier",
    )
    barrier_id: str = Field(
        ..., title="Barrier ID", description="ID of the barrier to update"
    )
    barriered_from_usergroup_ids: List[str] = Field(
        ...,
        title="Barriered From Usergroup IDs",
        description="Usergroup IDs that cannot communicate",
    )
    primary_usergroup_id: str = Field(
        ...,
        title="Primary Usergroup ID",
        description="Primary usergroup ID for the barrier",
    )
    restricted_subjects: List[str] = Field(
        ..., title="Restricted Subjects", description="List of restricted subjects"
    )


# --- admin.conversations (28) ---


class SlackAdminConversationsArchiveConfig(BaseModel):
    """Archive a conversation (admin.conversations.archive)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["archive_conversation_as_admin"] = Field(
        default="archive_conversation_as_admin",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Archive Conversation As Admin",
            "x-keywords": [
                "admin archive channel",
                "force archive channel",
                "archive channel admin",
            ],
        },
        title="Archive Conversation As Admin",
    )
    channel_id: str = _channel_field(
        "ID of the channel to archive", title="Channel ID", field_name="channel_id"
    )


class SlackAdminConversationsBulkArchiveConfig(BaseModel):
    """Bulk archive conversations (admin.conversations.bulkArchive)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["bulk_archive_conversations"] = Field(
        default="bulk_archive_conversations",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Bulk Archive Conversations",
            "x-keywords": [
                "mass archive channels",
                "archive many channels",
                "batch archive channels",
            ],
        },
        title="Bulk Archive Conversations",
    )
    channel_ids: List[str] = Field(
        ..., title="Channel IDs", description="List of channel IDs to archive"
    )


class SlackAdminConversationsBulkDeleteConfig(BaseModel):
    """Bulk delete conversations (admin.conversations.bulkDelete)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["bulk_delete_conversations"] = Field(
        default="bulk_delete_conversations",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Bulk Delete Conversations",
            "x-keywords": [
                "mass delete channels",
                "delete many channels",
                "batch delete channels",
            ],
        },
        title="Bulk Delete Conversations",
    )
    channel_ids: List[str] = Field(
        ..., title="Channel IDs", description="List of channel IDs to delete"
    )


class SlackAdminConversationsBulkMoveConfig(BaseModel):
    """Bulk move conversations to a team (admin.conversations.bulkMove)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["bulk_move_conversations_to_team"] = Field(
        default="bulk_move_conversations_to_team",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Bulk Move Conversations to Team",
            "x-keywords": [
                "mass move channels",
                "move channels to workspace",
                "batch move channels team",
            ],
        },
        title="Bulk Move Conversations to Team",
    )
    channel_ids: List[str] = Field(
        ..., title="Channel IDs", description="List of channel IDs to move"
    )
    target_team_id: str = Field(
        ..., title="Target Team ID", description="ID of the team to move channels to"
    )


class SlackAdminConversationsConvertToPrivateConfig(BaseModel):
    """Convert public channel to private (admin.conversations.convertToPrivate)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["convert_channel_to_private"] = Field(
        default="convert_channel_to_private",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Convert Channel to Private",
            "x-keywords": [
                "make channel private",
                "private channel convert",
                "change public to private",
            ],
        },
        title="Convert Channel to Private",
    )
    channel_id: str = _channel_field(
        "ID of the channel to convert", title="Channel ID", field_name="channel_id"
    )


class SlackAdminConversationsConvertToPublicConfig(BaseModel):
    """Convert private channel to public (admin.conversations.convertToPublic)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["convert_channel_to_public"] = Field(
        default="convert_channel_to_public",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Convert Channel to Public",
            "x-keywords": [
                "make channel public",
                "public channel convert",
                "change private to public",
            ],
        },
        title="Convert Channel to Public",
    )
    channel_id: str = _channel_field(
        "ID of the channel to convert", title="Channel ID", field_name="channel_id"
    )


class SlackAdminConversationsCreateConfig(BaseModel):
    """Create a conversation (admin.conversations.create)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_admin_conversation"] = Field(
        default="create_admin_conversation",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Create Admin Conversation",
            "x-keywords": [
                "admin create channel",
                "provision channel",
                "create channel admin",
            ],
            "x-creates-resource": True,
            "x-resource-type": "slack_channel",
            "x-resource-id-path": "data.channel_id",
        },
        title="Create Admin Conversation",
    )
    name: str = Field(..., title="Name", description="Name of the channel to create")
    is_private: bool = Field(
        default=False,
        title="Is Private",
        description="Whether the channel should be private",
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Description of the channel"
    )
    org_wide: bool = Field(
        default=False, title="Org Wide", description="Whether the channel is org-wide"
    )
    team_id: Optional[str] = Field(
        default=None, title="Team ID", description="Team ID to create the channel in"
    )


class SlackAdminConversationsDeleteConfig(BaseModel):
    """Delete a conversation (admin.conversations.delete)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_conversation"] = Field(
        default="delete_conversation",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Delete Conversation",
            "x-keywords": [
                "admin delete channel",
                "permanently remove channel",
                "delete channel admin",
            ],
        },
        title="Delete Conversation",
    )
    channel_id: str = _channel_field(
        "ID of the channel to delete", title="Channel ID", field_name="channel_id"
    )


class SlackAdminConversationsDisconnectSharedConfig(BaseModel):
    """Disconnect a shared channel (admin.conversations.disconnectShared)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["disconnect_shared_channel"] = Field(
        default="disconnect_shared_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Disconnect Shared Channel",
            "x-keywords": [
                "unshare slack connect channel",
                "disconnect connect channel",
                "remove channel sharing",
            ],
        },
        title="Disconnect Shared Channel",
    )
    channel_id: str = _channel_field(
        "ID of the shared channel to disconnect",
        title="Channel ID",
        field_name="channel_id",
    )
    leaving_team_ids: Optional[List[str]] = Field(
        default=None, title="Leaving Team IDs", description="Team IDs to disconnect"
    )


class SlackAdminConversationsEkmListOriginalConnectedChannelInfoConfig(BaseModel):
    """List original connected channel info for EKM (admin.conversations.ekm.listOriginalConnectedChannelInfo)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_ekm_original_channel_info"] = Field(
        default="list_ekm_original_channel_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "EKM",
            "x-is-trigger": False,
            "x-display-name": "List Ekm Original Channel Info",
            "x-keywords": [
                "ekm connected channels",
                "encryption key channel info",
                "original ekm channels",
            ],
        },
        title="List Ekm Original Channel Info",
    )
    channel_ids: Optional[List[str]] = Field(
        default=None,
        title="Channel IDs",
        description="List of channel IDs to get info for",
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )
    team_ids: Optional[List[str]] = Field(
        default=None, title="Team IDs", description="Filter by team IDs"
    )


class SlackAdminConversationsGetConversationPrefsConfig(BaseModel):
    """Get conversation preferences (admin.conversations.getConversationPrefs)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_conversation_preferences"] = Field(
        default="get_conversation_preferences",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Get Conversation Preferences",
            "x-keywords": [
                "read channel prefs",
                "channel posting settings",
                "who can post settings",
            ],
        },
        title="Get Conversation Preferences",
    )
    channel_id: str = _channel_field(
        "ID of the channel", title="Channel ID", field_name="channel_id"
    )


class SlackAdminConversationsGetCustomRetentionConfig(BaseModel):
    """Get custom retention settings (admin.conversations.getCustomRetention)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_channel_retention_settings"] = Field(
        default="get_channel_retention_settings",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Get Channel Retention Settings",
            "x-keywords": [
                "read message retention",
                "channel data retention",
                "message expiry settings",
            ],
        },
        title="Get Channel Retention Settings",
    )
    channel_id: str = _channel_field(
        "ID of the channel", title="Channel ID", field_name="channel_id"
    )


class SlackAdminConversationsGetTeamsConfig(BaseModel):
    """Get teams for a conversation (admin.conversations.getTeams)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_teams_for_conversation"] = Field(
        default="list_teams_for_conversation",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "List Teams for Conversation",
            "x-keywords": [
                "channel teams",
                "workspaces sharing channel",
                "teams on channel",
                "connected teams",
            ],
        },
        title="List Teams for Conversation",
    )
    channel_id: str = _channel_field(
        "ID of the channel", title="Channel ID", field_name="channel_id"
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )


class SlackAdminConversationsInviteConfig(BaseModel):
    """Invite users to a conversation (admin.conversations.invite)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["invite_users_to_conversation_as_admin"] = Field(
        default="invite_users_to_conversation_as_admin",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Invite Users to Conversation As Admin",
            "x-keywords": [
                "admin invite",
                "force add members",
                "admin add users",
                "invite as admin",
            ],
        },
        title="Invite Users to Conversation As Admin",
    )
    channel_id: str = _channel_field(
        "ID of the channel", title="Channel ID", field_name="channel_id"
    )
    user_ids: List[str] = Field(
        ..., title="User IDs", description="List of user IDs to invite"
    )


class SlackAdminConversationsLookupConfig(BaseModel):
    """Look up conversations (admin.conversations.lookup)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["lookup_conversations"] = Field(
        default="lookup_conversations",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Lookup Conversations",
            "x-keywords": [
                "lookup channels",
                "admin channel lookup",
                "resolve channels",
            ],
        },
        title="Lookup Conversations",
    )
    last_message_activity_before: int = Field(
        ...,
        title="Last Message Activity Before",
        description="Filter channels with no messages after this timestamp",
    )
    team_ids: List[str] = Field(
        ..., title="Team IDs", description="List of team IDs to search"
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )
    max_member_count: Optional[int] = Field(
        default=None,
        title="Max Member Count",
        description="Filter by maximum member count",
    )


class SlackAdminConversationsRemoveCustomRetentionConfig(BaseModel):
    """Remove custom retention settings (admin.conversations.removeCustomRetention)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_channel_retention_settings"] = Field(
        default="remove_channel_retention_settings",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Remove Channel Retention Settings",
            "x-keywords": [
                "clear retention",
                "reset retention",
                "drop custom retention",
                "remove message expiry",
            ],
        },
        title="Remove Channel Retention Settings",
    )
    channel_id: str = _channel_field(
        "ID of the channel", title="Channel ID", field_name="channel_id"
    )


class SlackAdminConversationsRenameConfig(BaseModel):
    """Rename a conversation (admin.conversations.rename)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["rename_conversation_as_admin"] = Field(
        default="rename_conversation_as_admin",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Rename Conversation As Admin",
            "x-keywords": ["admin rename channel", "force rename", "rename as admin"],
        },
        title="Rename Conversation As Admin",
    )
    channel_id: str = _channel_field(
        "ID of the channel to rename", title="Channel ID", field_name="channel_id"
    )
    name: str = Field(..., title="Name", description="New name for the channel")


class SlackAdminConversationsRestrictAccessAddGroupConfig(BaseModel):
    """Add IDP group to channel (admin.conversations.restrictAccess.addGroup)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_idp_group_to_channel"] = Field(
        default="add_idp_group_to_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Add Idp Group to Channel",
            "x-keywords": [
                "add idp group",
                "link saml group",
                "grant idp group",
                "attach directory group",
            ],
        },
        title="Add Idp Group to Channel",
    )
    channel_id: str = _channel_field(
        "ID of the channel", title="Channel ID", field_name="channel_id"
    )
    group_id: str = Field(..., title="Group ID", description="ID of the IDP group")
    team_id: Optional[str] = Field(default=None, title="Team ID", description="Team ID")


class SlackAdminConversationsRestrictAccessListGroupsConfig(BaseModel):
    """List IDP groups for channel (admin.conversations.restrictAccess.listGroups)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_idp_groups_for_channel"] = Field(
        default="list_idp_groups_for_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "List Idp Groups for Channel",
            "x-keywords": ["idp groups", "saml groups", "directory groups"],
        },
        title="List Idp Groups for Channel",
    )
    channel_id: str = _channel_field(
        "ID of the channel", title="Channel ID", field_name="channel_id"
    )
    team_id: Optional[str] = Field(default=None, title="Team ID", description="Team ID")


class SlackAdminConversationsRestrictAccessRemoveGroupConfig(BaseModel):
    """Remove IDP group from channel (admin.conversations.restrictAccess.removeGroup)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_idp_group_from_channel"] = Field(
        default="remove_idp_group_from_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Remove Idp Group from Channel",
            "x-keywords": [
                "remove idp group",
                "unlink saml group",
                "detach directory group",
            ],
        },
        title="Remove Idp Group from Channel",
    )
    channel_id: str = _channel_field(
        "ID of the channel", title="Channel ID", field_name="channel_id"
    )
    group_id: str = Field(..., title="Group ID", description="ID of the IDP group")
    team_id: str = Field(..., title="Team ID", description="Team ID")


class SlackAdminConversationsSearchConfig(BaseModel):
    """Search for conversations (admin.conversations.search)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_conversations"] = Field(
        default="search_conversations",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Search Conversations",
            "x-keywords": [
                "admin channel search",
                "find channels admin",
                "search all channels",
            ],
        },
        title="Search Conversations",
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )
    query: Optional[str] = Field(
        default=None, title="Query", description="Search query"
    )
    search_channel_types: Optional[List[str]] = Field(
        default=None,
        title="Search Channel Types",
        description="Types of channels to search",
    )
    sort: Optional[str] = Field(default=None, title="Sort", description="Sort order")
    sort_dir: Optional[str] = Field(
        default=None, title="Sort Direction", description="Sort direction"
    )
    team_ids: Optional[List[str]] = Field(
        default=None, title="Team IDs", description="Team IDs to filter by"
    )
    connected_team_ids: Optional[List[str]] = Field(
        default=None,
        title="Connected Team IDs",
        description="Connected team IDs to filter by",
    )
    total_count_only: bool = Field(
        default=False,
        title="Total Count Only",
        description="Return only the total count",
    )


class SlackAdminConversationsSetConversationPrefsConfig(BaseModel):
    """Set conversation preferences (admin.conversations.setConversationPrefs)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_conversation_preferences"] = Field(
        default="set_conversation_preferences",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Set Conversation Preferences",
            "x-keywords": [
                "set channel prefs",
                "channel posting rules",
                "who can post",
                "channel preferences",
            ],
        },
        title="Set Conversation Preferences",
    )
    channel_id: str = _channel_field(
        "ID of the channel", title="Channel ID", field_name="channel_id"
    )
    prefs: str = Field(
        ..., title="Preferences", description="JSON object with channel preferences"
    )


class SlackAdminConversationsSetCustomRetentionConfig(BaseModel):
    """Set custom retention settings (admin.conversations.setCustomRetention)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_channel_retention_settings"] = Field(
        default="set_channel_retention_settings",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Set Channel Retention Settings",
            "x-keywords": [
                "set retention",
                "message expiry",
                "auto delete messages",
                "custom retention",
            ],
        },
        title="Set Channel Retention Settings",
    )
    channel_id: str = _channel_field(
        "ID of the channel", title="Channel ID", field_name="channel_id"
    )
    duration_days: int = Field(
        ..., title="Duration Days", description="Number of days for retention"
    )


class SlackAdminConversationsSetTeamsConfig(BaseModel):
    """Set teams for a conversation (admin.conversations.setTeams)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_teams_for_conversation"] = Field(
        default="set_teams_for_conversation",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Set Teams for Conversation",
            "x-keywords": [
                "assign channel teams",
                "share channel teams",
                "set channel workspaces",
            ],
        },
        title="Set Teams for Conversation",
    )
    channel_id: str = _channel_field(
        "ID of the channel", title="Channel ID", field_name="channel_id"
    )
    org_channel: bool = Field(
        default=False,
        title="Org Channel",
        description="Whether this is an org-wide channel",
    )
    target_team_ids: Optional[List[str]] = Field(
        default=None,
        title="Target Team IDs",
        description="Team IDs to set for the channel",
    )
    team_id: Optional[str] = Field(default=None, title="Team ID", description="Team ID")


class SlackAdminConversationsUnarchiveConfig(BaseModel):
    """Unarchive a conversation (admin.conversations.unarchive)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["unarchive_conversation_as_admin"] = Field(
        default="unarchive_conversation_as_admin",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Unarchive Conversation As Admin",
            "x-keywords": [
                "admin unarchive",
                "restore channel admin",
                "reopen as admin",
            ],
        },
        title="Unarchive Conversation As Admin",
    )
    channel_id: str = _channel_field(
        "ID of the channel to unarchive", title="Channel ID", field_name="channel_id"
    )


# --- admin.emoji (5) ---


class SlackAdminEmojiAddConfig(BaseModel):
    """Add custom emoji (admin.emoji.add)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_custom_emoji"] = Field(
        default="add_custom_emoji",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Emoji",
            "x-is-trigger": False,
            "x-display-name": "Add Custom Emoji",
            "x-keywords": ["upload emoji", "new custom emoji", "add workspace emoji"],
        },
        title="Add Custom Emoji",
    )
    name: str = Field(..., title="Name", description="Name of the emoji")
    url: str = Field(..., title="URL", description="URL of the emoji image")


class SlackAdminEmojiAddAliasConfig(BaseModel):
    """Add emoji alias (admin.emoji.addAlias)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_emoji_alias"] = Field(
        default="add_emoji_alias",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Emoji",
            "x-is-trigger": False,
            "x-display-name": "Add Emoji Alias",
            "x-keywords": [
                "emoji alias",
                "alias emoji",
                "nickname emoji",
                "shortcut emoji",
            ],
        },
        title="Add Emoji Alias",
    )
    alias_for: str = Field(
        ..., title="Alias For", description="Name of the emoji to alias"
    )
    name: str = Field(..., title="Name", description="Name of the alias")


class SlackAdminEmojiListConfig(BaseModel):
    """List custom emoji (admin.emoji.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_custom_emoji"] = Field(
        default="list_custom_emoji",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Emoji",
            "x-is-trigger": False,
            "x-display-name": "List Custom Emoji",
            "x-keywords": [
                "admin emoji list",
                "custom emoji admin",
                "workspace emoji admin",
            ],
        },
        title="List Custom Emoji",
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )


class SlackAdminEmojiRemoveConfig(BaseModel):
    """Remove custom emoji (admin.emoji.remove)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_custom_emoji"] = Field(
        default="remove_custom_emoji",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Emoji",
            "x-is-trigger": False,
            "x-display-name": "Remove Custom Emoji",
            "x-keywords": [
                "remove emoji",
                "delete custom emoji",
                "drop workspace emoji",
            ],
        },
        title="Remove Custom Emoji",
    )
    name: str = Field(..., title="Name", description="Name of the emoji to remove")


class SlackAdminEmojiRenameConfig(BaseModel):
    """Rename custom emoji (admin.emoji.rename)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["rename_custom_emoji"] = Field(
        default="rename_custom_emoji",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Emoji",
            "x-is-trigger": False,
            "x-display-name": "Rename Custom Emoji",
            "x-keywords": ["rename emoji", "change emoji name", "relabel custom emoji"],
        },
        title="Rename Custom Emoji",
    )
    name: str = Field(..., title="Name", description="Current name of the emoji")
    new_name: str = Field(..., title="New Name", description="New name for the emoji")


# --- admin.functions (3) ---


class SlackAdminFunctionsListConfig(BaseModel):
    """List functions (admin.functions.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_functions"] = Field(
        default="list_functions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Function",
            "x-is-trigger": False,
            "x-display-name": "List Functions",
            "x-keywords": ["workflow functions", "custom functions", "function list"],
        },
        title="List Functions",
    )
    app_ids: Optional[List[str]] = Field(
        default=None, title="App IDs", description="Filter by app IDs"
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )
    team_id: Optional[str] = Field(
        default=None, title="Team ID", description="Team ID to filter by"
    )


class SlackAdminFunctionsPermissionsLookupConfig(BaseModel):
    """Look up function permissions (admin.functions.permissions.lookup)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["lookup_function_permissions"] = Field(
        default="lookup_function_permissions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Function",
            "x-is-trigger": False,
            "x-display-name": "Lookup Function Permissions",
            "x-keywords": [
                "function permissions",
                "function runners",
                "function access",
            ],
        },
        title="Lookup Function Permissions",
    )
    function_ids: List[str] = Field(
        ..., title="Function IDs", description="List of function IDs"
    )


class SlackAdminFunctionsPermissionsSetConfig(BaseModel):
    """Set function permissions (admin.functions.permissions.set)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_function_permissions"] = Field(
        default="set_function_permissions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Function",
            "x-is-trigger": False,
            "x-display-name": "Set Function Permissions",
            "x-keywords": [
                "set function access",
                "grant function permission",
                "restrict function",
            ],
        },
        title="Set Function Permissions",
    )
    function_id: str = Field(..., title="Function ID", description="ID of the function")
    visibility: str = Field(
        ..., title="Visibility", description="Visibility setting for the function"
    )
    user_ids: Optional[List[str]] = Field(
        default=None, title="User IDs", description="List of user IDs with access"
    )


# --- admin.inviteRequests (5) ---


class SlackAdminInviteRequestsApproveConfig(BaseModel):
    """Approve invite request (admin.inviteRequests.approve)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["approve_invite_request"] = Field(
        default="approve_invite_request",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Invite Request",
            "x-is-trigger": False,
            "x-display-name": "Approve Invite Request",
            "x-keywords": [
                "approve join request",
                "accept membership request",
                "grant invite",
            ],
        },
        title="Approve Invite Request",
    )
    invite_request_id: str = Field(
        ...,
        title="Invite Request ID",
        description="ID of the invite request to approve",
    )
    team_id: Optional[str] = Field(default=None, title="Team ID", description="Team ID")


class SlackAdminInviteRequestsApprovedListConfig(BaseModel):
    """List approved invite requests (admin.inviteRequests.approved.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_approved_invite_requests"] = Field(
        default="list_approved_invite_requests",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Invite Request",
            "x-is-trigger": False,
            "x-display-name": "List Approved Invite Requests",
            "x-keywords": [
                "approved requests",
                "accepted join requests",
                "granted invites",
            ],
        },
        title="List Approved Invite Requests",
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )
    team_id: Optional[str] = Field(
        default=None, title="Team ID", description="Team ID to filter by"
    )


class SlackAdminInviteRequestsDeniedListConfig(BaseModel):
    """List denied invite requests (admin.inviteRequests.denied.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_denied_invite_requests"] = Field(
        default="list_denied_invite_requests",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Invite Request",
            "x-is-trigger": False,
            "x-display-name": "List Denied Invite Requests",
            "x-keywords": [
                "denied requests",
                "rejected join requests",
                "refused invites",
            ],
        },
        title="List Denied Invite Requests",
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )
    team_id: Optional[str] = Field(
        default=None, title="Team ID", description="Team ID to filter by"
    )


class SlackAdminInviteRequestsDenyConfig(BaseModel):
    """Deny invite request (admin.inviteRequests.deny)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["deny_invite_request"] = Field(
        default="deny_invite_request",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Invite Request",
            "x-is-trigger": False,
            "x-display-name": "Deny Invite Request",
            "x-keywords": [
                "deny join request",
                "reject membership request",
                "refuse invite",
            ],
        },
        title="Deny Invite Request",
    )
    invite_request_id: str = Field(
        ..., title="Invite Request ID", description="ID of the invite request to deny"
    )
    team_id: Optional[str] = Field(default=None, title="Team ID", description="Team ID")


class SlackAdminInviteRequestsListConfig(BaseModel):
    """List invite requests (admin.inviteRequests.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_invite_requests"] = Field(
        default="list_invite_requests",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Invite Request",
            "x-is-trigger": False,
            "x-display-name": "List Invite Requests",
            "x-keywords": [
                "pending join requests",
                "membership requests",
                "invite requests",
            ],
        },
        title="List Invite Requests",
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )
    team_id: Optional[str] = Field(
        default=None, title="Team ID", description="Team ID to filter by"
    )


# --- admin.roles (3) ---


class SlackAdminRolesAddAssignmentsConfig(BaseModel):
    """Add role assignments (admin.roles.addAssignments)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_role_assignments"] = Field(
        default="add_role_assignments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Role",
            "x-is-trigger": False,
            "x-display-name": "Add Role Assignments",
            "x-keywords": ["assign role", "grant admin role", "add role holder"],
        },
        title="Add Role Assignments",
    )
    entity_ids: List[str] = Field(
        ..., title="Entity IDs", description="List of entity IDs"
    )
    role_id: str = Field(..., title="Role ID", description="ID of the role")
    user_ids: List[str] = Field(..., title="User IDs", description="List of user IDs")


class SlackAdminRolesListAssignmentsConfig(BaseModel):
    """List role assignments (admin.roles.listAssignments)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_role_assignments"] = Field(
        default="list_role_assignments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Role",
            "x-is-trigger": False,
            "x-display-name": "List Role Assignments",
            "x-keywords": ["role assignments", "who has role", "role holders"],
        },
        title="List Role Assignments",
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    entity_ids: Optional[List[str]] = Field(
        default=None, title="Entity IDs", description="Filter by entity IDs"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )
    role_ids: Optional[List[str]] = Field(
        default=None, title="Role IDs", description="Filter by role IDs"
    )
    sort_dir: Optional[str] = Field(
        default=None, title="Sort Direction", description="Sort direction"
    )


class SlackAdminRolesRemoveAssignmentsConfig(BaseModel):
    """Remove role assignments (admin.roles.removeAssignments)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_role_assignments"] = Field(
        default="remove_role_assignments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Role",
            "x-is-trigger": False,
            "x-display-name": "Remove Role Assignments",
            "x-keywords": ["unassign role", "revoke role", "strip role"],
        },
        title="Remove Role Assignments",
    )
    entity_ids: List[str] = Field(
        ..., title="Entity IDs", description="List of entity IDs"
    )
    role_id: str = Field(..., title="Role ID", description="ID of the role")
    user_ids: List[str] = Field(..., title="User IDs", description="List of user IDs")


# --- admin.teams (10) ---


class SlackAdminTeamsAdminsListConfig(BaseModel):
    """List team admins (admin.teams.admins.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_team_admins"] = Field(
        default="list_team_admins",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "List Team Admins",
            "x-keywords": ["team admins", "workspace admins", "admin list"],
        },
        title="List Team Admins",
    )
    team_id: str = Field(..., title="Team ID", description="ID of the team")
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )


class SlackAdminTeamsCreateConfig(BaseModel):
    """Create a team (admin.teams.create)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_team"] = Field(
        default="create_team",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Create Team",
            "x-keywords": ["new team", "add workspace", "provision team"],
        },
        title="Create Team",
    )
    team_domain: str = Field(
        ..., title="Team Domain", description="Domain name for the team"
    )
    team_name: str = Field(..., title="Team Name", description="Name of the team")
    team_description: Optional[str] = Field(
        default=None, title="Team Description", description="Description of the team"
    )
    team_discoverability: Optional[str] = Field(
        default=None,
        title="Team Discoverability",
        description="Discoverability setting",
    )


class SlackAdminTeamsListConfig(BaseModel):
    """List teams (admin.teams.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_teams"] = Field(
        default="list_teams",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "List Teams",
            "x-keywords": ["all teams", "workspaces list", "org teams"],
        },
        title="List Teams",
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )


class SlackAdminTeamsOwnersListConfig(BaseModel):
    """List team owners (admin.teams.owners.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_team_owners"] = Field(
        default="list_team_owners",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "List Team Owners",
            "x-keywords": ["team owners", "workspace owners", "owner list"],
        },
        title="List Team Owners",
    )
    team_id: str = Field(..., title="Team ID", description="ID of the team")
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )


class SlackAdminTeamsSettingsInfoConfig(BaseModel):
    """Get team settings info (admin.teams.settings.info)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_team_settings"] = Field(
        default="get_team_settings",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Get Team Settings",
            "x-keywords": ["team settings", "workspace settings", "team config"],
        },
        title="Get Team Settings",
    )
    team_id: str = Field(..., title="Team ID", description="ID of the team")


class SlackAdminTeamsSettingsSetDefaultChannelsConfig(BaseModel):
    """Set default channels for team (admin.teams.settings.setDefaultChannels)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_default_channels_for_team"] = Field(
        default="set_default_channels_for_team",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Set Default Channels for Team",
            "x-keywords": [
                "default channels",
                "auto join channels",
                "onboarding channels",
                "set default workspaces",
            ],
        },
        title="Set Default Channels for Team",
    )
    team_id: str = Field(..., title="Team ID", description="ID of the team")
    channel_ids: List[str] = Field(
        ..., title="Channel IDs", description="List of default channel IDs"
    )


class SlackAdminTeamsSettingsSetDescriptionConfig(BaseModel):
    """Set team description (admin.teams.settings.setDescription)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_team_description"] = Field(
        default="set_team_description",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Set Team Description",
            "x-keywords": [
                "team description",
                "workspace description",
                "team about",
                "describe workspace",
            ],
        },
        title="Set Team Description",
    )
    team_id: str = Field(..., title="Team ID", description="ID of the team")
    description: str = Field(
        ..., title="Description", description="New description for the team"
    )


class SlackAdminTeamsSettingsSetDiscoverabilityConfig(BaseModel):
    """Set team discoverability (admin.teams.settings.setDiscoverability)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_team_discoverability"] = Field(
        default="set_team_discoverability",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Set Team Discoverability",
            "x-keywords": [
                "team discoverability",
                "workspace findable",
                "join visibility",
                "discoverable team",
            ],
        },
        title="Set Team Discoverability",
    )
    team_id: str = Field(..., title="Team ID", description="ID of the team")
    discoverability: str = Field(
        ...,
        title="Discoverability",
        description="Discoverability setting ('open', 'closed', 'invite_only', 'unlisted')",
    )


class SlackAdminTeamsSettingsSetIconConfig(BaseModel):
    """Set team icon (admin.teams.settings.setIcon)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_team_icon"] = Field(
        default="set_team_icon",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Set Team Icon",
            "x-keywords": [
                "team icon",
                "workspace logo",
                "team avatar",
                "workspace icon",
            ],
        },
        title="Set Team Icon",
    )
    team_id: str = Field(..., title="Team ID", description="ID of the team")
    image_url: str = Field(
        ..., title="Image URL", description="URL of the team icon image"
    )


class SlackAdminTeamsSettingsSetNameConfig(BaseModel):
    """Set team name (admin.teams.settings.setName)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_team_name"] = Field(
        default="set_team_name",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Set Team Name",
            "x-keywords": [
                "team name",
                "workspace name",
                "rename workspace",
                "rename team",
            ],
        },
        title="Set Team Name",
    )
    team_id: str = Field(..., title="Team ID", description="ID of the team")
    name: str = Field(..., title="Name", description="New name for the team")


# --- admin.usergroups (4) ---


class SlackAdminUsergroupsAddChannelsConfig(BaseModel):
    """Add channels to usergroup (admin.usergroups.addChannels)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_channels_to_usergroup"] = Field(
        default="add_channels_to_usergroup",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User Group",
            "x-is-trigger": False,
            "x-display-name": "Add Channels to Usergroup",
            "x-keywords": [
                "channels to usergroup",
                "default channels group",
                "usergroup channels",
                "assign channels group",
            ],
        },
        title="Add Channels to Usergroup",
    )
    channel_ids: List[str] = Field(
        ..., title="Channel IDs", description="List of channel IDs to add"
    )
    usergroup_id: str = Field(
        ..., title="Usergroup ID", description="ID of the usergroup"
    )
    team_id: Optional[str] = Field(default=None, title="Team ID", description="Team ID")


class SlackAdminUsergroupsAddTeamsConfig(BaseModel):
    """Add teams to usergroup (admin.usergroups.addTeams)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_teams_to_usergroup"] = Field(
        default="add_teams_to_usergroup",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User Group",
            "x-is-trigger": False,
            "x-display-name": "Add Teams to Usergroup",
            "x-keywords": [
                "teams to usergroup",
                "usergroup teams",
                "workspaces to group",
                "assign teams group",
            ],
        },
        title="Add Teams to Usergroup",
    )
    team_ids: List[str] = Field(
        ..., title="Team IDs", description="List of team IDs to add"
    )
    usergroup_id: str = Field(
        ..., title="Usergroup ID", description="ID of the usergroup"
    )
    auto_provision: bool = Field(
        default=False, title="Auto Provision", description="Auto-provision members"
    )


class SlackAdminUsergroupsListChannelsConfig(BaseModel):
    """List channels in usergroup (admin.usergroups.listChannels)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_channels_in_usergroup"] = Field(
        default="list_channels_in_usergroup",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User Group",
            "x-is-trigger": False,
            "x-display-name": "List Channels in Usergroup",
            "x-keywords": [
                "usergroup channels",
                "group default channels",
                "channels of usergroup",
            ],
        },
        title="List Channels in Usergroup",
    )
    usergroup_id: str = Field(
        ..., title="Usergroup ID", description="ID of the usergroup"
    )
    include_num_members: bool = Field(
        default=False,
        title="Include Num Members",
        description="Include member count in response",
    )
    team_id: Optional[str] = Field(default=None, title="Team ID", description="Team ID")


class SlackAdminUsergroupsRemoveChannelsConfig(BaseModel):
    """Remove channels from usergroup (admin.usergroups.removeChannels)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_channels_from_usergroup"] = Field(
        default="remove_channels_from_usergroup",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User Group",
            "x-is-trigger": False,
            "x-display-name": "Remove Channels from Usergroup",
            "x-keywords": [
                "channels from usergroup",
                "detach channels group",
                "drop usergroup channels",
            ],
        },
        title="Remove Channels from Usergroup",
    )
    channel_ids: List[str] = Field(
        ..., title="Channel IDs", description="List of channel IDs to remove"
    )
    usergroup_id: str = Field(
        ..., title="Usergroup ID", description="ID of the usergroup"
    )


# --- admin.users (17) ---


class SlackAdminUsersAssignConfig(BaseModel):
    """Assign a user to a team (admin.users.assign)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["assign_user_to_team"] = Field(
        default="assign_user_to_team",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Assign User to Team",
            "x-keywords": [
                "assign member team",
                "add user workspace",
                "place user team",
                "onboard to workspace",
            ],
        },
        title="Assign User to Team",
    )
    team_id: str = Field(..., title="Team ID", description="ID of the team")
    user_id: str = Field(..., title="User ID", description="ID of the user")
    channel_ids: Optional[List[str]] = Field(
        default=None, title="Channel IDs", description="Channels to add the user to"
    )
    is_restricted: bool = Field(
        default=False,
        title="Is Restricted",
        description="Is the user a restricted user (guest)",
    )
    is_ultra_restricted: bool = Field(
        default=False,
        title="Is Ultra Restricted",
        description="Is the user an ultra restricted user (single-channel guest)",
    )


class SlackAdminUsersGetExpirationConfig(BaseModel):
    """Get expiration for a user (admin.users.getExpiration)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_user_expiration"] = Field(
        default="get_user_expiration",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User Expiration",
            "x-keywords": [
                "member expiration date",
                "guest expiry",
                "account expires when",
            ],
        },
        title="Get User Expiration",
    )
    user_id: str = Field(..., title="User ID", description="ID of the user")


class SlackAdminUsersInviteConfig(BaseModel):
    """Invite a user to a team (admin.users.invite)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["invite_user_to_team"] = Field(
        default="invite_user_to_team",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Invite User to Team",
            "x-keywords": [
                "invite member workspace",
                "send team invite",
                "add guest workspace",
                "onboard new member",
            ],
        },
        title="Invite User to Team",
    )
    channel_ids: List[str] = Field(
        ..., title="Channel IDs", description="Channels to add the user to"
    )
    email: str = Field(..., title="Email", description="Email address of the user")
    team_id: str = Field(..., title="Team ID", description="ID of the team")
    custom_message: Optional[str] = Field(
        default=None,
        title="Custom Message",
        description="Custom message for the invite",
    )
    guest_expiration_ts: Optional[str] = Field(
        default=None, title="Guest Expiration", description="Guest expiration timestamp"
    )
    is_restricted: bool = Field(
        default=False,
        title="Is Restricted",
        description="Is the user a restricted user (guest)",
    )
    is_ultra_restricted: bool = Field(
        default=False,
        title="Is Ultra Restricted",
        description="Is the user an ultra restricted user (single-channel guest)",
    )
    real_name: Optional[str] = Field(
        default=None, title="Real Name", description="Real name of the user"
    )
    resend: bool = Field(
        default=True,
        title="Resend",
        description="Resend the invite if user is already invited",
    )


class SlackAdminUsersListConfig(BaseModel):
    """List users in a team (admin.users.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_users_in_team"] = Field(
        default="list_users_in_team",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List Users in Team",
            "x-keywords": [
                "members of workspace",
                "team roster",
                "workspace member list",
                "users in team",
            ],
        },
        title="List Users in Team",
    )
    team_id: str = Field(..., title="Team ID", description="ID of the team")
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    include_deactivated_user_workspaces: bool = Field(
        default=False,
        title="Include Deactivated User Workspaces",
        description="Include deactivated user workspaces",
    )
    is_active: Optional[bool] = Field(
        default=None, title="Is Active", description="Filter by active status"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )


class SlackAdminUsersRemoveConfig(BaseModel):
    """Remove a user from a team (admin.users.remove)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_user_from_team"] = Field(
        default="remove_user_from_team",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Remove User from Team",
            "x-keywords": [
                "deactivate member",
                "kick from workspace",
                "offboard user",
                "remove from team",
            ],
        },
        title="Remove User from Team",
    )
    team_id: str = Field(..., title="Team ID", description="ID of the team")
    user_id: str = Field(..., title="User ID", description="ID of the user")


class SlackAdminUsersSessionClearSettingsConfig(BaseModel):
    """Clear session settings (admin.users.session.clearSettings)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["clear_user_session_settings"] = Field(
        default="clear_user_session_settings",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Session",
            "x-is-trigger": False,
            "x-display-name": "Clear User Session Settings",
            "x-keywords": [
                "clear session settings",
                "reset session config",
                "wipe session prefs",
            ],
        },
        title="Clear User Session Settings",
    )
    user_ids: List[str] = Field(..., title="User IDs", description="List of user IDs")


class SlackAdminUsersSessionGetSettingsConfig(BaseModel):
    """Get session settings (admin.users.session.getSettings)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_user_session_settings"] = Field(
        default="get_user_session_settings",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Session",
            "x-is-trigger": False,
            "x-display-name": "Get User Session Settings",
            "x-keywords": [
                "session settings",
                "session duration config",
                "device session prefs",
            ],
        },
        title="Get User Session Settings",
    )
    user_ids: List[str] = Field(..., title="User IDs", description="List of user IDs")


class SlackAdminUsersSessionInvalidateConfig(BaseModel):
    """Invalidate user session (admin.users.session.invalidate)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["invalidate_user_session"] = Field(
        default="invalidate_user_session",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Session",
            "x-is-trigger": False,
            "x-display-name": "Invalidate User Session",
            "x-keywords": [
                "invalidate session",
                "force logout",
                "kill session",
                "sign out user",
            ],
        },
        title="Invalidate User Session",
    )
    session_id: str = Field(
        ..., title="Session ID", description="ID of the session to invalidate"
    )
    team_id: str = Field(..., title="Team ID", description="ID of the team")


class SlackAdminUsersSessionListConfig(BaseModel):
    """List user sessions (admin.users.session.list)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_user_sessions"] = Field(
        default="list_user_sessions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Session",
            "x-is-trigger": False,
            "x-display-name": "List User Sessions",
            "x-keywords": [
                "active sessions",
                "logged in devices",
                "user sign-ins",
                "open sessions",
            ],
        },
        title="List User Sessions",
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )
    team_id: Optional[str] = Field(
        default=None, title="Team ID", description="Team ID to filter by"
    )
    user_id: Optional[str] = Field(
        default=None, title="User ID", description="User ID to filter by"
    )


class SlackAdminUsersSessionResetConfig(BaseModel):
    """Reset user session (admin.users.session.reset)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["reset_user_session"] = Field(
        default="reset_user_session",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Session",
            "x-is-trigger": False,
            "x-display-name": "Reset User Session",
            "x-keywords": ["reset session", "force reauth", "log out everywhere"],
        },
        title="Reset User Session",
    )
    user_id: str = Field(..., title="User ID", description="ID of the user")
    mobile_only: bool = Field(
        default=False, title="Mobile Only", description="Only reset mobile sessions"
    )
    web_only: bool = Field(
        default=False, title="Web Only", description="Only reset web sessions"
    )


class SlackAdminUsersSessionResetBulkConfig(BaseModel):
    """Bulk reset user sessions (admin.users.session.resetBulk)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["bulk_reset_user_sessions"] = Field(
        default="bulk_reset_user_sessions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Session",
            "x-is-trigger": False,
            "x-display-name": "Bulk Reset User Sessions",
            "x-keywords": [
                "bulk reset sessions",
                "mass force logout",
                "reset all sessions",
                "wipe everyone sessions",
            ],
        },
        title="Bulk Reset User Sessions",
    )
    user_ids: List[str] = Field(..., title="User IDs", description="List of user IDs")
    mobile_only: bool = Field(
        default=False, title="Mobile Only", description="Only reset mobile sessions"
    )
    web_only: bool = Field(
        default=False, title="Web Only", description="Only reset web sessions"
    )


class SlackAdminUsersSessionSetSettingsConfig(BaseModel):
    """Set session settings (admin.users.session.setSettings)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_user_session_settings"] = Field(
        default="set_user_session_settings",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Session",
            "x-is-trigger": False,
            "x-display-name": "Set User Session Settings",
            "x-keywords": [
                "session settings",
                "session timeout config",
                "device session policy",
            ],
        },
        title="Set User Session Settings",
    )
    user_ids: List[str] = Field(..., title="User IDs", description="List of user IDs")
    desktop_app_browser_quit: Optional[bool] = Field(
        default=None,
        title="Desktop App Browser Quit",
        description="Desktop app browser quit setting",
    )
    duration: Optional[int] = Field(
        default=None, title="Duration", description="Session duration in seconds"
    )


class SlackAdminUsersSetAdminConfig(BaseModel):
    """Set a user as admin (admin.users.setAdmin)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_user_as_admin"] = Field(
        default="set_user_as_admin",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Set User As Admin",
            "x-keywords": [
                "make admin",
                "promote to admin",
                "grant admin role",
                "user as admin",
            ],
        },
        title="Set User As Admin",
    )
    team_id: str = Field(..., title="Team ID", description="ID of the team")
    user_id: str = Field(..., title="User ID", description="ID of the user")


class SlackAdminUsersSetExpirationConfig(BaseModel):
    """Set expiration for a user (admin.users.setExpiration)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_user_expiration"] = Field(
        default="set_user_expiration",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Set User Expiration",
            "x-keywords": [
                "set member expiry",
                "guest expiration date",
                "expire account when",
            ],
        },
        title="Set User Expiration",
    )
    expiration_ts: int = Field(
        ..., title="Expiration Timestamp", description="Unix timestamp for expiration"
    )
    user_id: str = Field(..., title="User ID", description="ID of the user")
    team_id: Optional[str] = Field(default=None, title="Team ID", description="Team ID")


class SlackAdminUsersSetOwnerConfig(BaseModel):
    """Set a user as owner (admin.users.setOwner)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_user_as_owner"] = Field(
        default="set_user_as_owner",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Set User As Owner",
            "x-keywords": [
                "make owner",
                "promote to owner",
                "grant owner role",
                "user as owner",
            ],
        },
        title="Set User As Owner",
    )
    team_id: str = Field(..., title="Team ID", description="ID of the team")
    user_id: str = Field(..., title="User ID", description="ID of the user")


class SlackAdminUsersSetRegularConfig(BaseModel):
    """Set a user as regular (admin.users.setRegular)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_user_as_regular"] = Field(
        default="set_user_as_regular",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Set User As Regular",
            "x-keywords": [
                "demote to member",
                "make regular",
                "downgrade from admin",
                "revoke admin role",
            ],
        },
        title="Set User As Regular",
    )
    team_id: str = Field(..., title="Team ID", description="ID of the team")
    user_id: str = Field(..., title="User ID", description="ID of the user")


class SlackAdminUsersUnsupportedVersionsExportConfig(BaseModel):
    """Export unsupported version users (admin.users.unsupportedVersions.export)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["export_unsupported_version_users"] = Field(
        default="export_unsupported_version_users",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Export Unsupported Version Users",
            "x-keywords": [
                "unsupported app versions",
                "outdated client users",
                "stale version members",
            ],
        },
        title="Export Unsupported Version Users",
    )
    date_end_of_support: Optional[str] = Field(
        default=None,
        title="Date End of Support",
        description="Filter by end of support date",
    )
    date_sessions_started: Optional[str] = Field(
        default=None,
        title="Date Sessions Started",
        description="Filter by sessions started date",
    )


# --- admin.workflows (7) ---


class SlackAdminWorkflowsCollaboratorsAddConfig(BaseModel):
    """Add workflow collaborators (admin.workflows.collaborators.add)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_workflow_collaborators"] = Field(
        default="add_workflow_collaborators",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Add Workflow Collaborators",
            "x-keywords": [
                "workflow collaborators",
                "add workflow editors",
                "grant workflow access",
            ],
        },
        title="Add Workflow Collaborators",
    )
    collaborator_ids: List[str] = Field(
        ..., title="Collaborator IDs", description="List of collaborator IDs to add"
    )
    workflow_ids: List[str] = Field(
        ..., title="Workflow IDs", description="List of workflow IDs"
    )


class SlackAdminWorkflowsCollaboratorsRemoveConfig(BaseModel):
    """Remove workflow collaborators (admin.workflows.collaborators.remove)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_workflow_collaborators"] = Field(
        default="remove_workflow_collaborators",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Remove Workflow Collaborators",
            "x-keywords": [
                "remove workflow editors",
                "revoke workflow access",
                "drop workflow collaborator",
            ],
        },
        title="Remove Workflow Collaborators",
    )
    collaborator_ids: List[str] = Field(
        ..., title="Collaborator IDs", description="List of collaborator IDs to remove"
    )
    workflow_ids: List[str] = Field(
        ..., title="Workflow IDs", description="List of workflow IDs"
    )


class SlackAdminWorkflowsPermissionsLookupConfig(BaseModel):
    """Look up workflow permissions (admin.workflows.permissions.lookup)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["lookup_workflow_permissions"] = Field(
        default="lookup_workflow_permissions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Lookup Workflow Permissions",
            "x-keywords": [
                "workflow permissions",
                "who can run workflow",
                "workflow access check",
            ],
        },
        title="Lookup Workflow Permissions",
    )
    workflow_ids: List[str] = Field(
        ..., title="Workflow IDs", description="List of workflow IDs"
    )
    max_workflow_triggers: int = Field(
        default=10,
        title="Max Workflow Triggers",
        description="Maximum number of triggers to return",
    )


class SlackAdminWorkflowsSearchConfig(BaseModel):
    """Search workflows (admin.workflows.search)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_workflows"] = Field(
        default="search_workflows",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Search Workflows",
            "x-keywords": ["workflows", "automations", "slack workflows"],
        },
        title="Search Workflows",
    )
    app_id: Optional[str] = Field(
        default=None, title="App ID", description="Filter by app ID"
    )
    collaborator_ids: Optional[List[str]] = Field(
        default=None, title="Collaborator IDs", description="Filter by collaborator IDs"
    )
    cursor: Optional[str] = Field(
        default=None, title="Cursor", description="Pagination cursor"
    )
    limit: int = Field(
        default=100, title="Limit", description="Maximum number of results"
    )
    no_collaborators: bool = Field(
        default=False,
        title="No Collaborators",
        description="Filter workflows with no collaborators",
    )
    num_trigger_ids: int = Field(
        default=0,
        title="Num Trigger IDs",
        description="Number of trigger IDs to include",
    )
    query: Optional[str] = Field(
        default=None, title="Query", description="Search query"
    )
    sort: Optional[str] = Field(default=None, title="Sort", description="Sort order")
    sort_dir: Optional[str] = Field(
        default=None, title="Sort Direction", description="Sort direction"
    )
    source: Optional[str] = Field(
        default=None, title="Source", description="Filter by source"
    )


class SlackAdminWorkflowsTriggersTypesPermissionsLookupConfig(BaseModel):
    """Look up workflow trigger type permissions (admin.workflows.triggers.types.permissions.lookup)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["lookup_workflow_trigger_type_permissions"] = Field(
        default="lookup_workflow_trigger_type_permissions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Lookup Workflow Trigger Type Permissions",
            "x-keywords": [
                "trigger type permissions",
                "who can add trigger",
                "trigger permission check",
            ],
        },
        title="Lookup Workflow Trigger Type Permissions",
    )
    trigger_type_ids: List[str] = Field(
        ..., title="Trigger Type IDs", description="List of trigger type IDs"
    )


class SlackAdminWorkflowsTriggersTypesPermissionsSetConfig(BaseModel):
    """Set workflow trigger type permissions (admin.workflows.triggers.types.permissions.set)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_workflow_trigger_type_permissions"] = Field(
        default="set_workflow_trigger_type_permissions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Set Workflow Trigger Type Permissions",
            "x-keywords": [
                "set trigger permissions",
                "allow trigger type",
                "trigger access control",
            ],
        },
        title="Set Workflow Trigger Type Permissions",
    )
    trigger_type_id: str = Field(
        ..., title="Trigger Type ID", description="ID of the trigger type"
    )
    visibility: str = Field(..., title="Visibility", description="Visibility setting")
    user_ids: Optional[List[str]] = Field(
        default=None, title="User IDs", description="List of user IDs with access"
    )


class SlackAdminWorkflowsUnpublishConfig(BaseModel):
    """Unpublish a workflow (admin.workflows.unpublish)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["unpublish_workflow"] = Field(
        default="unpublish_workflow",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Unpublish Workflow",
            "x-keywords": [
                "unpublish workflow",
                "retract automation",
                "take workflow offline",
                "deactivate workflow",
            ],
        },
        title="Unpublish Workflow",
    )
    workflow_ids: List[str] = Field(
        ..., title="Workflow IDs", description="List of workflow IDs to unpublish"
    )


# ============================================================================
# Discriminated Union of All Configs
# ============================================================================


def _slack_trigger_field(value: str, display: str, keywords: Optional[list] = None):
    """Build the hidden `operation` discriminator Field for a Slack trigger."""
    extra = {
        "ui:hidden": True,
        "x-category": None,
        "x-is-trigger": True,
        "x-display-name": display,
    }
    if keywords:
        extra["x-keywords"] = keywords
    return Field(value, json_schema_extra=extra, title=display)


class _SlackEventTriggerBase(BaseModel):
    """Shared fields for Slack per-event triggers.

    Each per-event trigger op is a separate operation (On App Mention, etc.) so
    the user picks the specific trigger rather than a generic event field; the
    event type is resolved from the operation via ``_trigger_event_map``.
    """

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


class _SlackChannelScopedTriggerBase(_SlackEventTriggerBase):
    """Base for Slack triggers whose events belong to a channel.

    The optional ``channel`` filter narrows the trigger to a single channel;
    empty fires for every channel the bot is in. The filter is evaluated at fire
    time against the node's live config, so changing it needs no re-registration.
    """

    channel: str = _channel_field(
        "Optional — fire only for events in this channel. Leave empty to fire "
        "for every channel the bot is in.",
        default="",
    )


class SlackOnChannelMessageConfig(_SlackChannelScopedTriggerBase):
    """Trigger: fires when a message is posted in a channel the bot is in."""

    operation: Literal["on_channel_message"] = _slack_trigger_field(
        "on_channel_message",
        "On Channel Message",
        keywords=[
            "when new message",
            "on message posted",
            "watch channel messages",
            "new chat in channel",
            "incoming message",
        ],
    )


class SlackOnAppMentionConfig(_SlackChannelScopedTriggerBase):
    """Trigger: fires when the bot is @-mentioned."""

    operation: Literal["on_app_mention"] = _slack_trigger_field(
        "on_app_mention",
        "On App Mention",
        keywords=[
            "when bot mentioned",
            "on app mention",
            "watch for mentions",
            "when tagged",
            "someone mentions bot",
        ],
    )


class SlackOnReactionAddedConfig(_SlackChannelScopedTriggerBase):
    """Trigger: fires when an emoji reaction is added to a message."""

    operation: Literal["on_reaction_added"] = _slack_trigger_field(
        "on_reaction_added",
        "On Reaction Added",
        keywords=[
            "when reaction added",
            "on emoji added",
            "watch reactions",
            "new emoji reaction",
            "someone reacts",
        ],
    )


class SlackOnChannelCreatedConfig(_SlackEventTriggerBase):
    """Trigger: fires when a new channel is created in the workspace."""

    operation: Literal["on_channel_created"] = _slack_trigger_field(
        "on_channel_created",
        "On Channel Created",
        keywords=[
            "when channel created",
            "on new channel",
            "watch for new channels",
            "channel added",
        ],
    )


class SlackOnMemberJoinedChannelConfig(_SlackChannelScopedTriggerBase):
    """Trigger: fires when a member joins a channel."""

    operation: Literal["on_member_joined_channel"] = _slack_trigger_field(
        "on_member_joined_channel",
        "On Member Joined Channel",
        keywords=[
            "when member joins",
            "on user joined channel",
            "watch channel joins",
            "someone joins channel",
            "new member in channel",
        ],
    )


class SlackOnFileSharedConfig(_SlackChannelScopedTriggerBase):
    """Trigger: fires when a file is shared in a channel the bot is in."""

    operation: Literal["on_file_shared"] = _slack_trigger_field(
        "on_file_shared",
        "On File Shared",
        keywords=[
            "when file shared",
            "on file uploaded",
            "watch for files",
            "new attachment shared",
        ],
    )


SlackConfig = Annotated[
    Union[
        # Trigger operations
        SlackOnChannelMessageConfig,
        SlackOnAppMentionConfig,
        SlackOnReactionAddedConfig,
        SlackOnChannelCreatedConfig,
        SlackOnMemberJoinedChannelConfig,
        SlackOnFileSharedConfig,
        # Messaging operations (6)
        SlackPostMessageConfig,
        SlackUpdateMessageConfig,
        SlackDeleteMessageConfig,
        SlackPostEphemeralConfig,
        SlackScheduleMessageConfig,
        SlackGetPermalinkConfig,
        # Conversation operations (18)
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
        # User operations (5)
        SlackListUsersConfig,
        SlackUserInfoConfig,
        SlackLookupUserByEmailConfig,
        SlackGetUserPresenceConfig,
        SlackUsersConversationsConfig,
        # Bookmark operations (4)
        SlackAddBookmarkConfig,
        SlackEditBookmarkConfig,
        SlackListBookmarksConfig,
        SlackRemoveBookmarkConfig,
        # User Group operations (7)
        SlackListUserGroupsConfig,
        SlackCreateUserGroupConfig,
        SlackDisableUserGroupConfig,
        SlackEnableUserGroupConfig,
        SlackUpdateUserGroupConfig,
        SlackListUserGroupUsersConfig,
        SlackUpdateUserGroupUsersConfig,
        # DND operations (5)
        SlackDndSetSnoozeConfig,
        SlackDndEndSnoozeConfig,
        SlackDndEndDndConfig,
        SlackDndInfoConfig,
        SlackDndTeamInfoConfig,
        # Emoji operations (1)
        SlackListEmojiConfig,
        # Star operations (3)
        SlackAddStarConfig,
        SlackRemoveStarConfig,
        SlackListStarsConfig,
        # Bot operations (1)
        SlackBotInfoConfig,
        # Reminder operations (5)
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
        # Admin API operations (90 total)
        # admin.analytics (1)
        SlackAdminAnalyticsGetFileConfig,
        # admin.apps (11)
        SlackAdminAppsActivitiesListConfig,
        SlackAdminAppsApproveConfig,
        SlackAdminAppsApprovedListConfig,
        SlackAdminAppsClearResolutionConfig,
        SlackAdminAppsConfigLookupConfig,
        SlackAdminAppsConfigSetConfig,
        SlackAdminAppsRequestsCancelConfig,
        SlackAdminAppsRequestsListConfig,
        SlackAdminAppsRestrictConfig,
        SlackAdminAppsRestrictedListConfig,
        SlackAdminAppsUninstallConfig,
        # admin.audit (2)
        SlackAdminAuditAnomalyAllowGetItemConfig,
        SlackAdminAuditAnomalyAllowUpdateItemConfig,
        # admin.auth.policy (3)
        SlackAdminAuthPolicyAssignEntitiesConfig,
        SlackAdminAuthPolicyGetEntitiesConfig,
        SlackAdminAuthPolicyRemoveEntitiesConfig,
        # admin.barriers (4)
        SlackAdminBarriersCreateConfig,
        SlackAdminBarriersDeleteConfig,
        SlackAdminBarriersListConfig,
        SlackAdminBarriersUpdateConfig,
        # admin.conversations (26)
        SlackAdminConversationsArchiveConfig,
        SlackAdminConversationsBulkArchiveConfig,
        SlackAdminConversationsBulkDeleteConfig,
        SlackAdminConversationsBulkMoveConfig,
        SlackAdminConversationsConvertToPrivateConfig,
        SlackAdminConversationsConvertToPublicConfig,
        SlackAdminConversationsCreateConfig,
        SlackAdminConversationsDeleteConfig,
        SlackAdminConversationsDisconnectSharedConfig,
        SlackAdminConversationsEkmListOriginalConnectedChannelInfoConfig,
        SlackAdminConversationsGetConversationPrefsConfig,
        SlackAdminConversationsGetCustomRetentionConfig,
        SlackAdminConversationsGetTeamsConfig,
        SlackAdminConversationsInviteConfig,
        SlackAdminConversationsLookupConfig,
        SlackAdminConversationsRemoveCustomRetentionConfig,
        SlackAdminConversationsRenameConfig,
        SlackAdminConversationsRestrictAccessAddGroupConfig,
        SlackAdminConversationsRestrictAccessListGroupsConfig,
        SlackAdminConversationsRestrictAccessRemoveGroupConfig,
        SlackAdminConversationsSearchConfig,
        SlackAdminConversationsSetConversationPrefsConfig,
        SlackAdminConversationsSetCustomRetentionConfig,
        SlackAdminConversationsSetTeamsConfig,
        SlackAdminConversationsUnarchiveConfig,
        # admin.emoji (5)
        SlackAdminEmojiAddConfig,
        SlackAdminEmojiAddAliasConfig,
        SlackAdminEmojiListConfig,
        SlackAdminEmojiRemoveConfig,
        SlackAdminEmojiRenameConfig,
        # admin.functions (3)
        SlackAdminFunctionsListConfig,
        SlackAdminFunctionsPermissionsLookupConfig,
        SlackAdminFunctionsPermissionsSetConfig,
        # admin.inviteRequests (5)
        SlackAdminInviteRequestsApproveConfig,
        SlackAdminInviteRequestsApprovedListConfig,
        SlackAdminInviteRequestsDeniedListConfig,
        SlackAdminInviteRequestsDenyConfig,
        SlackAdminInviteRequestsListConfig,
        # admin.roles (3)
        SlackAdminRolesAddAssignmentsConfig,
        SlackAdminRolesListAssignmentsConfig,
        SlackAdminRolesRemoveAssignmentsConfig,
        # admin.teams (10)
        SlackAdminTeamsAdminsListConfig,
        SlackAdminTeamsCreateConfig,
        SlackAdminTeamsListConfig,
        SlackAdminTeamsOwnersListConfig,
        SlackAdminTeamsSettingsInfoConfig,
        SlackAdminTeamsSettingsSetDefaultChannelsConfig,
        SlackAdminTeamsSettingsSetDescriptionConfig,
        SlackAdminTeamsSettingsSetDiscoverabilityConfig,
        SlackAdminTeamsSettingsSetIconConfig,
        SlackAdminTeamsSettingsSetNameConfig,
        # admin.usergroups (4)
        SlackAdminUsergroupsAddChannelsConfig,
        SlackAdminUsergroupsAddTeamsConfig,
        SlackAdminUsergroupsListChannelsConfig,
        SlackAdminUsergroupsRemoveChannelsConfig,
        # admin.users (17)
        SlackAdminUsersAssignConfig,
        SlackAdminUsersGetExpirationConfig,
        SlackAdminUsersInviteConfig,
        SlackAdminUsersListConfig,
        SlackAdminUsersRemoveConfig,
        SlackAdminUsersSessionClearSettingsConfig,
        SlackAdminUsersSessionGetSettingsConfig,
        SlackAdminUsersSessionInvalidateConfig,
        SlackAdminUsersSessionListConfig,
        SlackAdminUsersSessionResetConfig,
        SlackAdminUsersSessionResetBulkConfig,
        SlackAdminUsersSessionSetSettingsConfig,
        SlackAdminUsersSetAdminConfig,
        SlackAdminUsersSetExpirationConfig,
        SlackAdminUsersSetOwnerConfig,
        SlackAdminUsersSetRegularConfig,
        SlackAdminUsersUnsupportedVersionsExportConfig,
        # admin.workflows (7)
        SlackAdminWorkflowsCollaboratorsAddConfig,
        SlackAdminWorkflowsCollaboratorsRemoveConfig,
        SlackAdminWorkflowsPermissionsLookupConfig,
        SlackAdminWorkflowsSearchConfig,
        SlackAdminWorkflowsTriggersTypesPermissionsLookupConfig,
        SlackAdminWorkflowsTriggersTypesPermissionsSetConfig,
        SlackAdminWorkflowsUnpublishConfig,
    ],
    Discriminator("operation"),
]


class SlackNodeConfig(NodeConfig[SlackConfig, SlackCredential]):
    """Full configuration for Slack node including credentials"""

    pass


def _iter_operation_definitions(schema: Dict[str, Any]):
    """Yield ``(operation_name, config_class_definition)`` for a node schema.

    Markers belong on the config class's ``$defs`` entry, NOT on its nested
    ``properties.operation`` — that is where the frontend reads them from
    (``NodeConfig.getOptionTierLabel`` resolves the ``$ref`` and reads the top
    level). The operation name itself lives on the nested ``const``.
    """
    for definition in (schema.get("$defs") or {}).values():
        if not isinstance(definition, dict):
            continue
        operation = (definition.get("properties") or {}).get("operation")
        if isinstance(operation, dict) and "const" in operation:
            yield operation["const"], definition


# ============================================================================
# Slack Node Implementation
# ============================================================================


class SlackNode(AppEventTriggerMixin, WorkflowNode):
    """
    Slack Web API automation node.

    Executes Slack operations via the Web API.
    Supports messaging, channels, users, reactions, pins, files, and search.
    """

    edit_examples = [
        "Post daily standup update to #engineering with formatted thread",
        "Send alert message to #incidents with error details and timestamp",
        "List all users and search for members in #sales department",
        "Create new channel for project launch with 10 members",
        "Pin important announcement to #announcements and lock thread",
        "Add emoji reaction to celebrate wins in #wins channel",
        "Search messages mentioning bugs in #dev-support last week",
    ]

    _app_provider = "slack"
    _trigger_event_map = {
        "on_channel_message": ["message"],
        "on_app_mention": ["app_mention"],
        "on_reaction_added": ["reaction_added"],
        "on_channel_created": ["channel_created"],
        "on_member_joined_channel": ["member_joined_channel"],
        "on_file_shared": ["file_shared"],
    }

    scope_registry = SLACK_SCOPES

    # The channel picker already returns exactly what a user recognises, so the
    # dropdown query and the proof are one call. test_authentication names the
    # workspace when a bot is in no channels yet.
    connection_evidence = ConnectionEvidence(
        field="channel",
        noun="channels",
        identity_operation="test_authentication",
    )

    @classmethod
    def get_config_model(cls):
        return SlackNodeConfig

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Schema with the Grid-admin operations marked in the picker.

        These operations cannot run on the shared OAuth app (Slack refuses an
        admin-scoped install outside Enterprise Grid), so the picker has to say
        so before a user wires one into a workflow — the runtime gate in
        ``_make_request`` is correct but arrives too late to be good UX.
        """
        schema = super().get_config_schema()
        for operation, definition in _iter_operation_definitions(schema):
            if operation in GRID_ADMIN_OPERATIONS:
                definition["x-requires-tier"] = GRID_ADMIN_TIER
                definition["x-tier-label"] = "Enterprise Grid"
            elif operation in CONNECT_ADMIN_OPERATIONS:
                definition["x-requires-tier"] = CONNECT_ADMIN_TIER
                definition["x-tier-label"] = "Admin install"
        return schema

    # ========================================================================
    # App-event trigger (on_slack_event)
    # ========================================================================

    @classmethod
    async def _resolve_tenant_id(cls, credential: Dict[str, Any]) -> Optional[str]:
        """Return the workspace team_id — from the credential, or via auth.test.

        The credential is pre-freshened by :meth:`freshen_credential` at load
        (trigger registration path), so the token here is non-stale.
        """
        team_id = credential.get("team_id")
        if team_id:
            return team_id
        token = credential.get("access_token") or credential.get("bot_token")
        if not token:
            return None
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{SLACK_API_BASE}/auth.test",
                headers={"Authorization": f"Bearer {token}"},
            )
            data = response.json()
            return data.get("team_id") if data.get("ok") else None

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Return a structured Slack event payload for app-level trigger runs."""
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return {"type": "slack", "status": "success", "data": payload}

        event = payload.get("event") if isinstance(payload, dict) else None
        operation = (config or {}).get("operation")
        return {
            "type": "slack",
            "action": operation,
            "status": "success",
            "event_type": event.get("type") if isinstance(event, dict) else None,
            "team_id": payload.get("team_id") if isinstance(payload, dict) else None,
            "data": payload,
            "timestamp": time.time(),
        }

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Slack event → message text for the agent's user turn + a
        channel/thread conversation key: DMs key on the channel, channel
        messages on the thread root (a top-level message starts a
        thread-scoped conversation). Channel + thread ts in the text double
        as the reply ids for send-message tools."""
        data = output.get("data") if isinstance(output.get("data"), dict) else {}
        event = data.get("event") if isinstance(data.get("event"), dict) else None
        if not event or not event.get("text"):
            # Non-message events (reactions, channel created, ...): raw JSON.
            return super().resolve_agent_event(output)
        channel = event.get("channel")
        thread = event.get("thread_ts") or event.get("ts")
        if event.get("channel_type") == "im":
            ck = channel
            where = f"DM {channel}"
        else:
            ck = f"{channel}:{thread}" if channel and thread else channel
            where = f"channel {channel}" + (f", thread {thread}" if thread else "")
        return {
            "text": (
                f"Slack message from {event.get('user') or 'unknown'} in {where}:\n"
                f"{event['text']}"
            ),
            "conversation_key": ck,
        }

    async def _trigger_on_slack_event(self, config, credentials) -> Dict[str, Any]:
        """Output when the trigger node is run manually from the editor.

        In a live workflow the node fires from a Slack Events API delivery,
        fanned out by the app-level webhook receiver."""
        node_config = (self.node_data or {}).get("config", {})
        trigger_payload = node_config.get("_triggerPayload")
        if trigger_payload:
            event = (
                trigger_payload.get("event")
                if isinstance(trigger_payload, dict)
                else None
            )
            return {
                "type": "slack",
                "action": config.operation,
                "status": "success",
                "event_type": event.get("type") if isinstance(event, dict) else None,
                "team_id": trigger_payload.get("team_id")
                if isinstance(trigger_payload, dict)
                else None,
                "data": trigger_payload,
                "timestamp": time.time(),
            }
        return {
            "message": (
                "This trigger fires when the subscribed Slack event occurs in "
                "the workspace. It outputs the Slack event payload."
            ),
            "event_types": self._trigger_event_map.get(config.operation, []),
        }

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load dynamic options for a config field (channel pickers).

        Called by the workflow handler to populate the channel dropdown.
        Both `channel` and `channel_id` fields resolve to the channel list.
        """
        logger.info(
            f"[SlackNode] load_field_options called: field={field_name}, page_token={page_token}, search={search!r}"
        )
        if field_name in ("channel", "channel_id"):
            return await cls._list_channels(credential_data, page_token, search=search)
        return {"options": [], "next_page_token": None}

    @classmethod
    async def _list_channels(
        cls,
        credential_data: Dict[str, Any],
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List public and private channels via ``conversations.list``.

        Raises on missing credential or API error so the dropdown surfaces a
        clear message instead of a silent empty list. ``conversations.list``
        has no native name filter, so search mode delegates to
        :func:`load_paginated_options` which paginates up to the shared
        safety cap and substring-filters server-side.

        ``credential_data`` is pre-freshened by :meth:`freshen_credential` at
        load (dynamic-options handler), so the token here is non-stale.
        """
        access_token = credential_data.get("access_token") or credential_data.get(
            "bot_token"
        )
        if not access_token:
            raise ValueError("Connect a Slack account to load channels")

        async def fetch_page(
            cursor: Optional[str],
        ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            params: Dict[str, Any] = {
                "types": "public_channel,private_channel",
                "exclude_archived": "true",
                "limit": 200,
            }
            if cursor:
                params["cursor"] = cursor
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{SLACK_API_BASE}/conversations.list",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                    timeout=30.0,
                )
            data = response.json() if response.content else {}
            if not data.get("ok", False):
                raise ValueError(f"Slack API error: {data.get('error', 'unknown')}")
            options = [
                {
                    "value": ch["id"],
                    "label": f"#{ch['name']}" if ch.get("name") else ch["id"],
                    "metadata": {
                        "is_private": ch.get("is_private", False),
                        "num_members": ch.get("num_members"),
                    },
                }
                for ch in (data.get("channels") or [])
            ]
            next_cursor = data.get("response_metadata", {}).get("next_cursor") or None
            return options, next_cursor

        return await load_paginated_options(
            fetch_page,
            page_token=page_token,
            search=search,
            log_label="SlackNode._list_channels",
        )

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Slack action via Web API."""
        logger.info(f"[SlackNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, SlackNodeConfig):
            raise ValueError("SlackNode requires valid configuration")

        config = node_config.config
        credentials = node_config.credentials

        if not credentials:
            raise ValueError(
                "[SlackNode] Credentials are required. "
                "Please connect your Slack account or add a Bot Token in the credentials tab."
            )

        # Route to appropriate handler based on config type
        action_handlers = {
            # Trigger operations (all route to the same manual-run handler)
            SlackOnChannelMessageConfig: self._trigger_on_slack_event,
            SlackOnAppMentionConfig: self._trigger_on_slack_event,
            SlackOnReactionAddedConfig: self._trigger_on_slack_event,
            SlackOnChannelCreatedConfig: self._trigger_on_slack_event,
            SlackOnMemberJoinedChannelConfig: self._trigger_on_slack_event,
            SlackOnFileSharedConfig: self._trigger_on_slack_event,
            # Messaging operations (6)
            SlackPostMessageConfig: self._post_message,
            SlackUpdateMessageConfig: self._update_message,
            SlackDeleteMessageConfig: self._delete_message,
            SlackPostEphemeralConfig: self._post_ephemeral,
            SlackScheduleMessageConfig: self._schedule_message,
            SlackGetPermalinkConfig: self._get_permalink,
            # Conversation operations (18)
            SlackListConversationsConfig: self._list_conversations,
            SlackConversationInfoConfig: self._conversation_info,
            SlackConversationHistoryConfig: self._conversation_history,
            SlackConversationMembersConfig: self._conversation_members,
            SlackJoinConversationConfig: self._join_conversation,
            SlackLeaveConversationConfig: self._leave_conversation,
            SlackCreateConversationConfig: self._create_conversation,
            SlackArchiveConversationConfig: self._archive_conversation,
            SlackUnarchiveConversationConfig: self._unarchive_conversation,
            SlackInviteToConversationConfig: self._invite_to_conversation,
            SlackKickFromConversationConfig: self._kick_from_conversation,
            SlackSetConversationTopicConfig: self._set_conversation_topic,
            SlackSetConversationPurposeConfig: self._set_conversation_purpose,
            SlackRenameConversationConfig: self._rename_conversation,
            SlackConversationRepliesConfig: self._conversation_replies,
            SlackOpenConversationConfig: self._open_conversation,
            SlackCloseConversationConfig: self._close_conversation,
            SlackMarkConversationConfig: self._mark_conversation,
            # User operations (5)
            SlackListUsersConfig: self._list_users,
            SlackUserInfoConfig: self._user_info,
            SlackLookupUserByEmailConfig: self._lookup_user_by_email,
            SlackGetUserPresenceConfig: self._get_user_presence,
            SlackUsersConversationsConfig: self._users_conversations,
            # Bookmark operations (4)
            SlackAddBookmarkConfig: self._add_bookmark,
            SlackEditBookmarkConfig: self._edit_bookmark,
            SlackListBookmarksConfig: self._list_bookmarks,
            SlackRemoveBookmarkConfig: self._remove_bookmark,
            # User Group operations (7)
            SlackListUserGroupsConfig: self._list_usergroups,
            SlackCreateUserGroupConfig: self._create_usergroup,
            SlackDisableUserGroupConfig: self._disable_usergroup,
            SlackEnableUserGroupConfig: self._enable_usergroup,
            SlackUpdateUserGroupConfig: self._update_usergroup,
            SlackListUserGroupUsersConfig: self._list_usergroup_users,
            SlackUpdateUserGroupUsersConfig: self._update_usergroup_users,
            # DND operations (5)
            SlackDndSetSnoozeConfig: self._dnd_set_snooze,
            SlackDndEndSnoozeConfig: self._dnd_end_snooze,
            SlackDndEndDndConfig: self._dnd_end_dnd,
            SlackDndInfoConfig: self._dnd_info,
            SlackDndTeamInfoConfig: self._dnd_team_info,
            # Emoji operations (1)
            SlackListEmojiConfig: self._list_emoji,
            # Star operations (3)
            SlackAddStarConfig: self._add_star,
            SlackRemoveStarConfig: self._remove_star,
            SlackListStarsConfig: self._list_stars,
            # Bot operations (1)
            SlackBotInfoConfig: self._bot_info,
            # Reminder operations (5)
            SlackAddReminderConfig: self._add_reminder,
            SlackCompleteReminderConfig: self._complete_reminder,
            SlackDeleteReminderConfig: self._delete_reminder,
            SlackReminderInfoConfig: self._reminder_info,
            SlackListRemindersConfig: self._list_reminders,
            # Reaction operations (3)
            SlackAddReactionConfig: self._add_reaction,
            SlackRemoveReactionConfig: self._remove_reaction,
            SlackGetReactionsConfig: self._get_reactions,
            # Pin operations (3)
            SlackAddPinConfig: self._add_pin,
            SlackRemovePinConfig: self._remove_pin,
            SlackListPinsConfig: self._list_pins,
            # File operations (6)
            SlackListFilesConfig: self._list_files,
            SlackFileInfoConfig: self._file_info,
            SlackDeleteFileConfig: self._delete_file,
            SlackUploadFileConfig: self._upload_file,
            SlackGetFilePublicURLConfig: self._get_file_public_url,
            SlackRevokeFilePublicURLConfig: self._revoke_file_public_url,
            # Search operations (3)
            SlackSearchMessagesConfig: self._search_messages,
            SlackSearchFilesConfig: self._search_files,
            SlackSearchAllConfig: self._search_all,
            # Scheduled message operations (2)
            SlackDeleteScheduledMessageConfig: self._delete_scheduled_message,
            SlackListScheduledMessagesConfig: self._list_scheduled_messages,
            # Chat extras (2)
            SlackMeMessageConfig: self._me_message,
            SlackUnfurlConfig: self._unfurl,
            # User profile operations (2)
            SlackGetUserProfileConfig: self._get_user_profile,
            SlackSetUserPresenceConfig: self._set_user_presence,
            # Team/Auth operations (6)
            SlackAuthTestConfig: self._auth_test,
            SlackTeamInfoConfig: self._team_info,
            SlackApiTestConfig: self._api_test,
            SlackAuthRevokeConfig: self._auth_revoke,
            SlackAppsUninstallConfig: self._apps_uninstall,
            SlackTeamBillableInfoConfig: self._team_billable_info,
            SlackTeamAccessLogsConfig: self._team_access_logs,
            SlackTeamIntegrationLogsConfig: self._team_integration_logs,
            # Slack Connect operations (3)
            SlackConversationsAcceptSharedInviteConfig: self._accept_shared_invite,
            SlackConversationsDeclineSharedInviteConfig: self._decline_shared_invite,
            SlackConversationsListConnectInvitesConfig: self._list_connect_invites,
            # New file upload operations (2)
            SlackGetUploadURLExternalConfig: self._get_upload_url_external,
            SlackCompleteUploadExternalConfig: self._complete_upload_external,
            # User profile operations (1)
            SlackSetUserProfileConfig: self._set_user_profile,
            # Additional Slack Connect operations (2)
            SlackApproveSharedInviteConfig: self._approve_shared_invite,
            SlackInviteSharedConfig: self._invite_shared,
            # Remote file operations (4)
            SlackAddRemoteFileConfig: self._add_remote_file,
            SlackRemoveRemoteFileConfig: self._remove_remote_file,
            SlackShareRemoteFileConfig: self._share_remote_file,
            SlackListRemoteFilesConfig: self._list_remote_files,
            # Additional reactions operations (1)
            SlackListReactionsConfig: self._list_reactions,
            # Additional remote file operations (2)
            SlackRemoteFileInfoConfig: self._remote_file_info,
            SlackRemoteFileUpdateConfig: self._remote_file_update,
            # File comment operations (1)
            SlackDeleteFileCommentConfig: self._delete_file_comment,
            # Additional user operations (2)
            SlackDeleteUserPhotoConfig: self._delete_user_photo,
            SlackSetUserActiveConfig: self._set_user_active,
            # Canvas operations (1)
            SlackCreateCanvasConfig: self._create_canvas,
            # Additional Slack Connect operations (4)
            SlackSetExternalInvitePermissionsConfig: self._set_external_invite_permissions,
            SlackApproveSharedInviteRequestConfig: self._approve_shared_invite_request,
            SlackDenySharedInviteRequestConfig: self._deny_shared_invite_request,
            SlackListSharedInviteRequestsConfig: self._list_shared_invite_requests,
            # Admin API operations (90 total)
            # admin.analytics (1)
            SlackAdminAnalyticsGetFileConfig: self._admin_analytics_get_file,
            # admin.apps (11)
            SlackAdminAppsActivitiesListConfig: self._admin_apps_activities_list,
            SlackAdminAppsApproveConfig: self._admin_apps_approve,
            SlackAdminAppsApprovedListConfig: self._admin_apps_approved_list,
            SlackAdminAppsClearResolutionConfig: self._admin_apps_clear_resolution,
            SlackAdminAppsConfigLookupConfig: self._admin_apps_config_lookup,
            SlackAdminAppsConfigSetConfig: self._admin_apps_config_set,
            SlackAdminAppsRequestsCancelConfig: self._admin_apps_requests_cancel,
            SlackAdminAppsRequestsListConfig: self._admin_apps_requests_list,
            SlackAdminAppsRestrictConfig: self._admin_apps_restrict,
            SlackAdminAppsRestrictedListConfig: self._admin_apps_restricted_list,
            SlackAdminAppsUninstallConfig: self._admin_apps_uninstall,
            # admin.audit (2)
            SlackAdminAuditAnomalyAllowGetItemConfig: self._admin_audit_anomaly_allow_get_item,
            SlackAdminAuditAnomalyAllowUpdateItemConfig: self._admin_audit_anomaly_allow_update_item,
            # admin.auth.policy (3)
            SlackAdminAuthPolicyAssignEntitiesConfig: self._admin_auth_policy_assign_entities,
            SlackAdminAuthPolicyGetEntitiesConfig: self._admin_auth_policy_get_entities,
            SlackAdminAuthPolicyRemoveEntitiesConfig: self._admin_auth_policy_remove_entities,
            # admin.barriers (4)
            SlackAdminBarriersCreateConfig: self._admin_barriers_create,
            SlackAdminBarriersDeleteConfig: self._admin_barriers_delete,
            SlackAdminBarriersListConfig: self._admin_barriers_list,
            SlackAdminBarriersUpdateConfig: self._admin_barriers_update,
            # admin.conversations (26)
            SlackAdminConversationsArchiveConfig: self._admin_conversations_archive,
            SlackAdminConversationsBulkArchiveConfig: self._admin_conversations_bulk_archive,
            SlackAdminConversationsBulkDeleteConfig: self._admin_conversations_bulk_delete,
            SlackAdminConversationsBulkMoveConfig: self._admin_conversations_bulk_move,
            SlackAdminConversationsConvertToPrivateConfig: self._admin_conversations_convert_to_private,
            SlackAdminConversationsConvertToPublicConfig: self._admin_conversations_convert_to_public,
            SlackAdminConversationsCreateConfig: self._admin_conversations_create,
            SlackAdminConversationsDeleteConfig: self._admin_conversations_delete,
            SlackAdminConversationsDisconnectSharedConfig: self._admin_conversations_disconnect_shared,
            SlackAdminConversationsEkmListOriginalConnectedChannelInfoConfig: self._admin_conversations_ekm_list_original_connected_channel_info,
            SlackAdminConversationsGetConversationPrefsConfig: self._admin_conversations_get_conversation_prefs,
            SlackAdminConversationsGetCustomRetentionConfig: self._admin_conversations_get_custom_retention,
            SlackAdminConversationsGetTeamsConfig: self._admin_conversations_get_teams,
            SlackAdminConversationsInviteConfig: self._admin_conversations_invite,
            SlackAdminConversationsLookupConfig: self._admin_conversations_lookup,
            SlackAdminConversationsRemoveCustomRetentionConfig: self._admin_conversations_remove_custom_retention,
            SlackAdminConversationsRenameConfig: self._admin_conversations_rename,
            SlackAdminConversationsRestrictAccessAddGroupConfig: self._admin_conversations_restrict_access_add_group,
            SlackAdminConversationsRestrictAccessListGroupsConfig: self._admin_conversations_restrict_access_list_groups,
            SlackAdminConversationsRestrictAccessRemoveGroupConfig: self._admin_conversations_restrict_access_remove_group,
            SlackAdminConversationsSearchConfig: self._admin_conversations_search,
            SlackAdminConversationsSetConversationPrefsConfig: self._admin_conversations_set_conversation_prefs,
            SlackAdminConversationsSetCustomRetentionConfig: self._admin_conversations_set_custom_retention,
            SlackAdminConversationsSetTeamsConfig: self._admin_conversations_set_teams,
            SlackAdminConversationsUnarchiveConfig: self._admin_conversations_unarchive,
            # admin.emoji (5)
            SlackAdminEmojiAddConfig: self._admin_emoji_add,
            SlackAdminEmojiAddAliasConfig: self._admin_emoji_add_alias,
            SlackAdminEmojiListConfig: self._admin_emoji_list,
            SlackAdminEmojiRemoveConfig: self._admin_emoji_remove,
            SlackAdminEmojiRenameConfig: self._admin_emoji_rename,
            # admin.functions (3)
            SlackAdminFunctionsListConfig: self._admin_functions_list,
            SlackAdminFunctionsPermissionsLookupConfig: self._admin_functions_permissions_lookup,
            SlackAdminFunctionsPermissionsSetConfig: self._admin_functions_permissions_set,
            # admin.inviteRequests (5)
            SlackAdminInviteRequestsApproveConfig: self._admin_invite_requests_approve,
            SlackAdminInviteRequestsApprovedListConfig: self._admin_invite_requests_approved_list,
            SlackAdminInviteRequestsDeniedListConfig: self._admin_invite_requests_denied_list,
            SlackAdminInviteRequestsDenyConfig: self._admin_invite_requests_deny,
            SlackAdminInviteRequestsListConfig: self._admin_invite_requests_list,
            # admin.roles (3)
            SlackAdminRolesAddAssignmentsConfig: self._admin_roles_add_assignments,
            SlackAdminRolesListAssignmentsConfig: self._admin_roles_list_assignments,
            SlackAdminRolesRemoveAssignmentsConfig: self._admin_roles_remove_assignments,
            # admin.teams (10)
            SlackAdminTeamsAdminsListConfig: self._admin_teams_admins_list,
            SlackAdminTeamsCreateConfig: self._admin_teams_create,
            SlackAdminTeamsListConfig: self._admin_teams_list,
            SlackAdminTeamsOwnersListConfig: self._admin_teams_owners_list,
            SlackAdminTeamsSettingsInfoConfig: self._admin_teams_settings_info,
            SlackAdminTeamsSettingsSetDefaultChannelsConfig: self._admin_teams_settings_set_default_channels,
            SlackAdminTeamsSettingsSetDescriptionConfig: self._admin_teams_settings_set_description,
            SlackAdminTeamsSettingsSetDiscoverabilityConfig: self._admin_teams_settings_set_discoverability,
            SlackAdminTeamsSettingsSetIconConfig: self._admin_teams_settings_set_icon,
            SlackAdminTeamsSettingsSetNameConfig: self._admin_teams_settings_set_name,
            # admin.usergroups (4)
            SlackAdminUsergroupsAddChannelsConfig: self._admin_usergroups_add_channels,
            SlackAdminUsergroupsAddTeamsConfig: self._admin_usergroups_add_teams,
            SlackAdminUsergroupsListChannelsConfig: self._admin_usergroups_list_channels,
            SlackAdminUsergroupsRemoveChannelsConfig: self._admin_usergroups_remove_channels,
            # admin.users (17)
            SlackAdminUsersAssignConfig: self._admin_users_assign,
            SlackAdminUsersGetExpirationConfig: self._admin_users_get_expiration,
            SlackAdminUsersInviteConfig: self._admin_users_invite,
            SlackAdminUsersListConfig: self._admin_users_list,
            SlackAdminUsersRemoveConfig: self._admin_users_remove,
            SlackAdminUsersSessionClearSettingsConfig: self._admin_users_session_clear_settings,
            SlackAdminUsersSessionGetSettingsConfig: self._admin_users_session_get_settings,
            SlackAdminUsersSessionInvalidateConfig: self._admin_users_session_invalidate,
            SlackAdminUsersSessionListConfig: self._admin_users_session_list,
            SlackAdminUsersSessionResetConfig: self._admin_users_session_reset,
            SlackAdminUsersSessionResetBulkConfig: self._admin_users_session_reset_bulk,
            SlackAdminUsersSessionSetSettingsConfig: self._admin_users_session_set_settings,
            SlackAdminUsersSetAdminConfig: self._admin_users_set_admin,
            SlackAdminUsersSetExpirationConfig: self._admin_users_set_expiration,
            SlackAdminUsersSetOwnerConfig: self._admin_users_set_owner,
            SlackAdminUsersSetRegularConfig: self._admin_users_set_regular,
            SlackAdminUsersUnsupportedVersionsExportConfig: self._admin_users_unsupported_versions_export,
            # admin.workflows (7)
            SlackAdminWorkflowsCollaboratorsAddConfig: self._admin_workflows_collaborators_add,
            SlackAdminWorkflowsCollaboratorsRemoveConfig: self._admin_workflows_collaborators_remove,
            SlackAdminWorkflowsPermissionsLookupConfig: self._admin_workflows_permissions_lookup,
            SlackAdminWorkflowsSearchConfig: self._admin_workflows_search,
            SlackAdminWorkflowsTriggersTypesPermissionsLookupConfig: self._admin_workflows_triggers_types_permissions_lookup,
            SlackAdminWorkflowsTriggersTypesPermissionsSetConfig: self._admin_workflows_triggers_types_permissions_set,
            SlackAdminWorkflowsUnpublishConfig: self._admin_workflows_unpublish,
        }

        handler = action_handlers.get(type(config))
        if not handler:
            raise ValueError(f"Unknown config type: {type(config)}")

        return await handler(config, credentials)

    def _credential_type(self, credentials: SlackCredential) -> Optional[str]:
        """The credential's discriminator, however it was loaded.

        Credentials arrive as Pydantic models on the execute path and as plain
        dicts from some loaders, so read both rather than isinstance-ing.
        """
        if isinstance(credentials, dict):
            return credentials.get("credential_type")
        return getattr(credentials, "credential_type", None)

    def _get_access_token(self, credentials: SlackCredential) -> str:
        """Extract access token from either OAuth or Bot Token credentials."""
        if isinstance(credentials, SlackOAuthCredential):
            return credentials.access_token
        elif isinstance(credentials, SlackBotTokenCredential):
            return credentials.bot_token
        else:
            # Fallback for dict-like access (when loaded from DB)
            if hasattr(credentials, "access_token"):
                return credentials.access_token
            elif hasattr(credentials, "bot_token"):
                return credentials.bot_token
            raise ValueError("Invalid credential type - no access token found")

    @classmethod
    async def freshen_credential(
        cls,
        credential_data: Dict[str, Any],
        *,
        pool=None,
        user_id: Optional[str] = None,
        credential_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Refresh the Slack workspace bot token in a decrypted credential.

        The freshening choke point for every NON-execute path that loads a
        Slack credential (channel dropdown, trigger registration, trigger
        tests) — all of which use the bot token. The bot token chain of record
        is the workspace's ``slack_installations`` row, not this credential's
        blob copy: ``ensure_fresh_slack_bot_token`` refreshes it there (with
        the same lock + CAS persist discipline as any credential) and merges
        the fresh bundle into the dict. Bot-token and pre-rotation credentials
        pass through untouched. The user (xoxp-) token is refreshed on demand
        by :meth:`_ensure_fresh_token` on the execute path (send_as user), so
        it is intentionally not refreshed here — doing so would burn a
        single-use user rotation on a bot-only path. Mutates and returns the dict.
        """
        if not credential_data or not (
            credential_data.get("refresh_token") or credential_data.get("team_id")
        ):
            return credential_data
        # Honor an ambient caller_path_scope (manual_refresh, trigger_test, …)
        # so audit attribution survives the freshen indirection.
        from nodes.core.oauth_audit import current_caller_path

        ambient = current_caller_path()
        await ensure_fresh_slack_bot_token(
            pool,
            credential_data,
            user_id=user_id,
            credential_id=credential_id,
            # Same gate as the pre-normalization freshen: the repair force-
            # refresh needs a persistable row of record, so only validate when
            # the caller identified one.
            validate_when_fresh=bool(user_id and credential_id),
            caller_path=ambient if ambient != "unknown" else "freshen",
        )
        return credential_data

    async def _ensure_fresh_token(
        self,
        credentials: SlackCredential,
        send_as: SendAs = "bot",
    ) -> str:
        """Return a valid Slack access token, refreshing + persisting if expired.

        Bot tokens don't expire. OAuth tokens use Slack token rotation and are
        refreshed via the shared ``ensure_fresh_oauth_token`` helper (per-
        credential lock + DB re-read + persist + retry).

        When ``send_as="user"`` the credential's ``user_access_token`` (xoxp-)
        is returned so the operation is attributed to the human who connected
        Slack. Slack rotates that token separately from the bot token, so its
        ``user_refresh_token`` is refreshed into the ``user_*`` fields without
        overwriting the bot token fields.
        """
        if send_as == "user":
            if isinstance(credentials, SlackBotTokenCredential):
                return credentials.bot_token
            if not isinstance(credentials, SlackOAuthCredential):
                raise ValueError(
                    "'Send As: User' requires a Slack OAuth credential — bot-token "
                    "credentials have no user token. Connect Slack via OAuth or "
                    "change 'Send As' to 'Bot'."
                )
            if not credentials.user_access_token:
                raise ValueError(
                    "Slack credential is missing a user token. Re-authorize Slack "
                    "from Settings → Credentials to grant user scopes, or change "
                    "'Send As' to 'Bot' on this node."
                )
            if not credentials.user_refresh_token:
                raise ValueError(
                    "Slack credential is missing a user refresh token. Re-authorize "
                    "Slack from Settings → Credentials, or change 'Send As' to "
                    "'Bot' on this node."
                )
            if is_token_expired(credentials.user_expires_at):
                cred_dict = credentials.model_dump()

                async def _refresh_user_token(refresh_token: str):
                    # Bind the credential's own OAuth client — custom-app
                    # installs must not refresh against the env default client.
                    return await refresh_access_token(
                        refresh_token,
                        cred_dict.get("client_id"),
                        cred_dict.get("client_secret"),
                    )

                token = await ensure_fresh_oauth_token(
                    credential_id=(self.node_data or {}).get("credential_id"),
                    user_id=self.user_id,
                    credential=cred_dict,
                    is_expired=is_token_expired,
                    refresh=_refresh_user_token,
                    access_token_key="user_access_token",
                    refresh_token_key="user_refresh_token",
                    expires_at_key="user_expires_at",
                    provider="slack",
                )
                credentials.user_access_token = cred_dict["user_access_token"]
                credentials.user_expires_at = cred_dict.get("user_expires_at")
                if cred_dict.get("user_refresh_token"):
                    credentials.user_refresh_token = cred_dict["user_refresh_token"]
                return token
            return credentials.user_access_token

        if isinstance(credentials, SlackBotTokenCredential):
            return credentials.bot_token
        if not isinstance(credentials, SlackOAuthCredential):
            return self._get_access_token(credentials)

        credential_id = (self.node_data or {}).get("credential_id")
        cred_dict = credentials.model_dump()
        token = await ensure_fresh_slack_bot_token(
            None,
            cred_dict,
            user_id=self.user_id,
            credential_id=credential_id,
            caller_path="execute",
        )
        # Mirror the refreshed tokens back onto the in-memory model.
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        credentials.scope = cred_dict.get("scope")
        credentials.token_type = cred_dict.get("token_type")
        credentials.app_id = cred_dict.get("app_id")
        credentials.client_id = cred_dict.get("client_id")
        credentials.client_secret = cred_dict.get("client_secret")
        return token

    async def _force_refresh_oauth_credentials(
        self, credentials: SlackOAuthCredential
    ) -> str:
        """Refresh the bot token after Slack reports it invalid before expiry."""
        credential_id = (self.node_data or {}).get("credential_id")
        if not credential_id or not self.user_id:
            raise ValueError(
                "Slack token is invalid and cannot be refreshed without a credential id"
            )

        cred_dict = credentials.model_dump()
        token = await ensure_fresh_slack_bot_token(
            None,
            cred_dict,
            user_id=self.user_id,
            credential_id=credential_id,
            # The rejected token: an installation chain that already rotated
            # past it is adopted instead of burning another single-use
            # rotation (one adopt per call until the blob copy expires).
            invalid_access_token=credentials.access_token,
            caller_path="execute",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        credentials.scope = cred_dict.get("scope")
        credentials.token_type = cred_dict.get("token_type")
        credentials.app_id = cred_dict.get("app_id")
        credentials.client_id = cred_dict.get("client_id")
        credentials.client_secret = cred_dict.get("client_secret")
        return token

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: SlackCredential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        form_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
        send_as: SendAs = "bot",
    ) -> Dict[str, Any]:
        """Make an authenticated Slack API request with timing."""
        total_start = time.time()

        # The scope choke point. Every operation reaches Slack through here, so
        # an endpoint with no declared requirement raises rather than shipping
        # as an operation that can only ever return missing_scope, and the
        # Grid-admin methods are gated on the credential type in one place
        # instead of 103 per-handler checks.
        scope_req = SLACK_SCOPES.enforce_credential_type(
            endpoint, self._credential_type(credentials)
        )

        url = f"{SLACK_API_BASE}/{endpoint}"

        # Filter out None params/body
        if params:
            params = {k: v for k, v in params.items() if v is not None}
        if json_body:
            json_body = {k: v for k, v in json_body.items() if v is not None}
        if form_body:
            form_body = {k: v for k, v in form_body.items() if v is not None}

        async with httpx.AsyncClient() as client:
            # API request timing
            api_start = time.time()
            logger.info(f"[SlackNode] 🔌 {method} {endpoint}")

            async def send_with_token(token: str):
                request_headers = {"Authorization": f"Bearer {token}"}
                if method == "GET":
                    # No Content-Type on GETs: Slack ignores query params on
                    # some methods (bookmarks.list) when the request claims a
                    # JSON body it doesn't have.
                    return await client.get(
                        url, headers=request_headers, params=params, timeout=30.0
                    )
                if form_body is not None:
                    # Some methods (files.remote.*) only parse form encoding.
                    return await client.post(
                        url, headers=request_headers, data=form_body, timeout=30.0
                    )
                request_headers["Content-Type"] = "application/json; charset=utf-8"
                return await client.post(
                    url, headers=request_headers, json=json_body or params, timeout=30.0
                )

            access_token = await self._ensure_fresh_token(credentials, send_as=send_as)
            response = await send_with_token(access_token)

            api_time = (time.time() - api_start) * 1000
            logger.info(
                f"[SlackNode] ⏱️ API request: {api_time:.1f}ms (status: {response.status_code})"
            )

            # Response parsing timing
            parse_start = time.time()
            data = response.json() if response.content else {}
            parse_time = (time.time() - parse_start) * 1000

            if (
                not data.get("ok", False)
                and data.get("error") in {"token_revoked", "token_expired"}
                and send_as == "bot"
                and isinstance(credentials, SlackOAuthCredential)
                and credentials.refresh_token
            ):
                logger.warning(
                    "[SlackNode] %s returned %s; force-refreshing Slack bot token once",
                    endpoint,
                    data.get("error"),
                )
                access_token = await self._force_refresh_oauth_credentials(credentials)
                retry_start = time.time()
                response = await send_with_token(access_token)
                api_time += (time.time() - retry_start) * 1000
                parse_start = time.time()
                data = response.json() if response.content else {}
                parse_time += (time.time() - parse_start) * 1000

            # Slack API returns {"ok": false, "error": "..."} on errors
            if not data.get("ok", False):
                error_msg = data.get("error", "Unknown error")

                # Channel-access errors are the #1 cause of agentic-builder
                # rabbit holes: a bare "not_in_channel" / "channel_not_found"
                # leaves the LLM with no information about which channels the
                # bot CAN reach, so it spawns list_channels / join_channel /
                # list_user_accessible_conversations scratch nodes onto the
                # user's canvas to figure it out. Surface the bot's actual
                # accessible-channel list inline so the next turn can either
                # pick a reachable channel ID or ask the user to invite the
                # bot in Slack.
                if error_msg in ("not_in_channel", "channel_not_found"):
                    hint = await self._fetch_accessible_channel_hint(
                        client, access_token
                    )
                    if hint:
                        error_msg = f"{error_msg} — {hint}"

                # The channel-scoped reads run as the user (xoxp-). A user token
                # minted before a read scope was added lacks it, so Slack returns
                # missing_scope until the user re-authorizes. Point them there
                # instead of surfacing a bare Slack error code.
                elif error_msg == "missing_scope":
                    needed = data.get("needed") or ", ".join(scope_req.scopes)
                    error_msg = (
                        f"missing_scope — this Slack credential is missing the "
                        f"{needed or 'required'} permission. Re-authorize Slack from "
                        f"Settings → Credentials to grant the newly required scopes."
                    )

                logger.error(f"[SlackNode] API error: {error_msg}")

                total_time = (time.time() - total_start) * 1000
                output = {
                    "type": "slack",
                    "action": action_name,
                    "status": "error",
                    "error": error_msg,
                    "status_code": response.status_code,
                    "data": None,
                    "timestamp": time.time(),
                    "timing_ms": {
                        "api_request": round(api_time, 1),
                        "total": round(total_time, 1),
                    },
                }
                await self.emit(output)
                return output

            total_time = (time.time() - total_start) * 1000
            logger.info(f"[SlackNode] ⏱️ TOTAL time: {total_time:.1f}ms")

            # Self-echo guard: fingerprint every message this platform creates
            # so the app events receiver can drop its redelivery — a channel
            # agent replying into its own trigger channel re-triggers itself
            # otherwise, and send_as="user" posts carry no authorship marker.
            # (chat.scheduleMessage is not covered: its final ts is unknown at
            # schedule time; the bot-authorship drop in _slack_parse bounds it.)
            if endpoint in _MESSAGE_WRITE_ENDPOINTS:
                from utils.slack_self_echo import record_self_post

                await record_self_post(data.get("channel"), data.get("ts"))

            output = {
                "type": "slack",
                "action": action_name,
                "status": "success",
                "data": data,
                "timestamp": time.time(),
                "timing_ms": {
                    "api_request": round(api_time, 1),
                    "response_parsing": round(parse_time, 1),
                    "total": round(total_time, 1),
                },
            }

            await self.emit(output)
            return output

    async def _fetch_accessible_channel_hint(
        self,
        client: httpx.AsyncClient,
        access_token: str,
    ) -> Optional[str]:
        """Build a short, human + LLM readable hint listing channels the bot
        currently has access to, for enriching channel-access error messages.

        Returns ``None`` on any failure so the caller falls back to the bare
        Slack error code (we never want this best-effort enrichment to mask
        the real error or itself throw).
        """
        try:
            resp = await client.get(
                f"{SLACK_API_BASE}/users.conversations",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "types": "public_channel,private_channel",
                    "limit": 50,
                    "exclude_archived": True,
                },
                timeout=10.0,
            )
            data = resp.json() if resp.content else {}
            if not data.get("ok"):
                return None
            channels = data.get("channels") or []
            if not channels:
                return (
                    "the bot isn't a member of any channel. Invite it to the "
                    "target channel in Slack (or pick one it's already in) and retry."
                )
            named = [
                f"#{c['name']} ({c['id']})"
                for c in channels[:20]
                if c.get("name") and c.get("id")
            ]
            suffix = f" (+{len(channels) - 20} more)" if len(channels) > 20 else ""
            return (
                f"bot has access to: {', '.join(named)}{suffix}. "
                f"Either invite the bot to the target channel in Slack, or use "
                f"one of these channel IDs."
            )
        except Exception as e:  # pragma: no cover - best-effort hint
            logger.warning(f"[SlackNode] Failed to fetch accessible-channel hint: {e}")
            return None

    # ============================================================================
    # Messaging Actions
    # ============================================================================

    async def _post_message(
        self, config: SlackPostMessageConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Post a message to a channel."""
        body = {
            "channel": config.channel,
            "text": config.text,
            "mrkdwn": config.mrkdwn,
            "unfurl_links": config.unfurl_links,
            "unfurl_media": config.unfurl_media,
        }
        if config.thread_ts:
            body["thread_ts"] = config.thread_ts
            body["reply_broadcast"] = config.reply_broadcast

        return await self._make_request(
            "POST",
            "chat.postMessage",
            credentials,
            json_body=body,
            action_name="send_message_to_channel",
            send_as=config.send_as,
        )

    async def _update_message(
        self, config: SlackUpdateMessageConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Update an existing message."""
        body = {
            "channel": config.channel,
            "ts": config.ts,
            "text": config.text,
        }
        return await self._make_request(
            "POST",
            "chat.update",
            credentials,
            json_body=body,
            action_name="update_existing_message",
            send_as=config.send_as,
        )

    async def _delete_message(
        self, config: SlackDeleteMessageConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Delete a message."""
        body = {
            "channel": config.channel,
            "ts": config.ts,
        }
        return await self._make_request(
            "POST",
            "chat.delete",
            credentials,
            json_body=body,
            action_name="delete_message",
            send_as=config.send_as,
        )

    async def _post_ephemeral(
        self, config: SlackPostEphemeralConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Send an ephemeral message."""
        body = {
            "channel": config.channel,
            "user": config.user,
            "text": config.text,
        }
        if config.thread_ts:
            body["thread_ts"] = config.thread_ts

        return await self._make_request(
            "POST",
            "chat.postEphemeral",
            credentials,
            json_body=body,
            action_name="send_ephemeral_message",
            send_as=config.send_as,
        )

    async def _schedule_message(
        self, config: SlackScheduleMessageConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Schedule a message for later."""
        body = {
            "channel": config.channel,
            "text": config.text,
            "post_at": config.post_at,
        }
        if config.thread_ts:
            body["thread_ts"] = config.thread_ts

        return await self._make_request(
            "POST",
            "chat.scheduleMessage",
            credentials,
            json_body=body,
            action_name="schedule_message_for_later",
            send_as=config.send_as,
        )

    async def _get_permalink(
        self, config: SlackGetPermalinkConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get permalink URL for a message."""
        params = {
            "channel": config.channel,
            "message_ts": config.message_ts,
        }
        return await self._make_request(
            "GET",
            "chat.getPermalink",
            credentials,
            params=params,
            action_name="get_message_permalink",
        )

    # ============================================================================
    # Conversation Actions
    # ============================================================================

    async def _list_conversations(
        self, config: SlackListConversationsConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List channels in the workspace."""
        params = {
            "types": config.types,
            "exclude_archived": config.exclude_archived,
            "limit": config.limit,
        }
        return await self._make_request(
            "GET",
            "conversations.list",
            credentials,
            params=params,
            action_name="list_channels_in_workspace",
        )

    async def _conversation_info(
        self, config: SlackConversationInfoConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get information about a channel."""
        params = {
            "channel": config.channel,
            "include_num_members": config.include_num_members,
        }
        return await self._make_request(
            "GET",
            "conversations.info",
            credentials,
            params=params,
            action_name="get_channel_information",
            send_as="user",
        )

    async def _conversation_history(
        self, config: SlackConversationHistoryConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get messages from a channel."""
        params = {
            "channel": config.channel,
            "limit": config.limit,
            "oldest": config.oldest,
            "latest": config.latest,
            "inclusive": config.inclusive,
        }
        return await self._make_request(
            "GET",
            "conversations.history",
            credentials,
            params=params,
            action_name="get_channel_messages",
            send_as="user",
        )

    async def _conversation_members(
        self, config: SlackConversationMembersConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get members of a channel."""
        params = {
            "channel": config.channel,
            "limit": config.limit,
        }
        return await self._make_request(
            "GET",
            "conversations.members",
            credentials,
            params=params,
            action_name="list_channel_members",
            send_as="user",
        )

    async def _join_conversation(
        self, config: SlackJoinConversationConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Join a public channel."""
        body = {"channel": config.channel}
        return await self._make_request(
            "POST",
            "conversations.join",
            credentials,
            json_body=body,
            action_name="join_public_channel",
            send_as=config.send_as,
        )

    async def _leave_conversation(
        self, config: SlackLeaveConversationConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Leave a channel."""
        body = {"channel": config.channel}
        return await self._make_request(
            "POST",
            "conversations.leave",
            credentials,
            json_body=body,
            action_name="leave_channel",
            send_as=config.send_as,
        )

    async def _create_conversation(
        self, config: SlackCreateConversationConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Create a new channel."""
        body = {
            "name": config.name,
            "is_private": config.is_private,
        }
        return await self._make_request(
            "POST",
            "conversations.create",
            credentials,
            json_body=body,
            action_name="create_channel",
            send_as=config.send_as,
        )

    async def _archive_conversation(
        self, config: SlackArchiveConversationConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Archive a channel."""
        body = {"channel": config.channel}
        return await self._make_request(
            "POST",
            "conversations.archive",
            credentials,
            json_body=body,
            action_name="archive_channel",
            send_as=config.send_as,
        )

    async def _unarchive_conversation(
        self, config: SlackUnarchiveConversationConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Unarchive a channel."""
        body = {"channel": config.channel}
        return await self._make_request(
            "POST",
            "conversations.unarchive",
            credentials,
            json_body=body,
            action_name="unarchive_channel",
            send_as=config.send_as,
        )

    async def _invite_to_conversation(
        self, config: SlackInviteToConversationConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Invite users to a channel."""
        body = {
            "channel": config.channel,
            "users": config.users,
        }
        return await self._make_request(
            "POST",
            "conversations.invite",
            credentials,
            json_body=body,
            action_name="invite_users_to_channel",
            send_as=config.send_as,
        )

    async def _kick_from_conversation(
        self, config: SlackKickFromConversationConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Remove a user from a channel."""
        body = {
            "channel": config.channel,
            "user": config.user,
        }
        return await self._make_request(
            "POST",
            "conversations.kick",
            credentials,
            json_body=body,
            action_name="remove_user_from_channel",
            send_as=config.send_as,
        )

    async def _set_conversation_topic(
        self, config: SlackSetConversationTopicConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Set the topic of a channel."""
        body = {
            "channel": config.channel,
            "topic": config.topic,
        }
        return await self._make_request(
            "POST",
            "conversations.setTopic",
            credentials,
            json_body=body,
            action_name="set_channel_topic",
            send_as=config.send_as,
        )

    async def _set_conversation_purpose(
        self, config: SlackSetConversationPurposeConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Set the purpose of a channel."""
        body = {
            "channel": config.channel,
            "purpose": config.purpose,
        }
        return await self._make_request(
            "POST",
            "conversations.setPurpose",
            credentials,
            json_body=body,
            action_name="set_channel_purpose",
            send_as=config.send_as,
        )

    async def _rename_conversation(
        self, config: SlackRenameConversationConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Rename a channel."""
        body = {
            "channel": config.channel,
            "name": config.name,
        }
        return await self._make_request(
            "POST",
            "conversations.rename",
            credentials,
            json_body=body,
            action_name="rename_channel",
            send_as=config.send_as,
        )

    async def _conversation_replies(
        self, config: SlackConversationRepliesConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get thread replies."""
        params = {
            "channel": config.channel,
            "ts": config.ts,
            "limit": config.limit,
            "oldest": config.oldest,
            "latest": config.latest,
        }
        return await self._make_request(
            "GET",
            "conversations.replies",
            credentials,
            params=params,
            action_name="get_thread_replies",
            send_as="user",
        )

    async def _open_conversation(
        self, config: SlackOpenConversationConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Open or resume a DM."""
        body = {
            "users": config.users,
            "channel": config.channel,
            "return_im": config.return_im,
        }
        return await self._make_request(
            "POST",
            "conversations.open",
            credentials,
            json_body=body,
            action_name="open_direct_message",
        )

    async def _close_conversation(
        self, config: SlackCloseConversationConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Close a DM."""
        body = {"channel": config.channel}
        return await self._make_request(
            "POST",
            "conversations.close",
            credentials,
            json_body=body,
            action_name="close_direct_message",
        )

    async def _mark_conversation(
        self, config: SlackMarkConversationConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Mark a channel as read."""
        body = {
            "channel": config.channel,
            "ts": config.ts,
        }
        return await self._make_request(
            "POST",
            "conversations.mark",
            credentials,
            json_body=body,
            action_name="mark_channel_as_read",
            send_as="user",
        )

    # ============================================================================
    # User Actions
    # ============================================================================

    async def _list_users(
        self, config: SlackListUsersConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List all users in the workspace."""
        params = {
            "limit": config.limit,
            "include_locale": config.include_locale,
        }
        return await self._make_request(
            "GET",
            "users.list",
            credentials,
            params=params,
            action_name="list_workspace_users",
        )

    async def _user_info(
        self, config: SlackUserInfoConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get information about a user."""
        params = {
            "user": config.user,
            "include_locale": config.include_locale,
        }
        return await self._make_request(
            "GET",
            "users.info",
            credentials,
            params=params,
            action_name="get_user_information",
        )

    async def _lookup_user_by_email(
        self, config: SlackLookupUserByEmailConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Find a user by their email address."""
        params = {"email": config.email}
        return await self._make_request(
            "GET",
            "users.lookupByEmail",
            credentials,
            params=params,
            action_name="find_user_by_email",
        )

    async def _get_user_presence(
        self, config: SlackGetUserPresenceConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get a user's presence status."""
        params = {"user": config.user}
        return await self._make_request(
            "GET",
            "users.getPresence",
            credentials,
            params=params,
            action_name="get_user_presence_status",
        )

    async def _users_conversations(
        self, config: SlackUsersConversationsConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List conversations the calling user may access."""
        params = {
            "user": config.user,
            "types": config.types,
            "exclude_archived": config.exclude_archived,
            "limit": config.limit,
        }
        return await self._make_request(
            "GET",
            "users.conversations",
            credentials,
            params=params,
            action_name="list_user_accessible_conversations",
        )

    # ============================================================================
    # Bookmark Actions
    # ============================================================================

    async def _add_bookmark(
        self, config: SlackAddBookmarkConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Add a bookmark to a channel."""
        body = {
            "channel_id": config.channel_id,
            "title": config.title,
            "type": config.type,
            "link": config.link,
            "emoji": config.emoji,
        }
        return await self._make_request(
            "POST",
            "bookmarks.add",
            credentials,
            json_body=body,
            action_name="add_bookmark_to_channel",
            send_as=config.send_as,
        )

    async def _edit_bookmark(
        self, config: SlackEditBookmarkConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Edit an existing bookmark."""
        body = {
            "channel_id": config.channel_id,
            "bookmark_id": config.bookmark_id,
            "title": config.title,
            "link": config.link,
            "emoji": config.emoji,
        }
        return await self._make_request(
            "POST",
            "bookmarks.edit",
            credentials,
            json_body=body,
            action_name="edit_channel_bookmark",
            send_as=config.send_as,
        )

    async def _list_bookmarks(
        self, config: SlackListBookmarksConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List bookmarks in a channel."""
        params = {"channel_id": config.channel_id}
        return await self._make_request(
            "GET",
            "bookmarks.list",
            credentials,
            params=params,
            action_name="list_channel_bookmarks",
            send_as="user",
        )

    async def _remove_bookmark(
        self, config: SlackRemoveBookmarkConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Remove a bookmark from a channel."""
        body = {
            "channel_id": config.channel_id,
            "bookmark_id": config.bookmark_id,
        }
        return await self._make_request(
            "POST",
            "bookmarks.remove",
            credentials,
            json_body=body,
            action_name="remove_channel_bookmark",
            send_as=config.send_as,
        )

    # ============================================================================
    # User Group Actions
    # ============================================================================

    async def _list_usergroups(
        self, config: SlackListUserGroupsConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List user groups in the workspace."""
        params = {
            "include_count": config.include_count,
            "include_disabled": config.include_disabled,
            "include_users": config.include_users,
        }
        return await self._make_request(
            "GET",
            "usergroups.list",
            credentials,
            params=params,
            action_name="list_workspace_user_groups",
        )

    async def _create_usergroup(
        self, config: SlackCreateUserGroupConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Create a new user group."""
        body = {
            "name": config.name,
            "handle": config.handle,
            "description": config.description,
            "channels": config.channels,
        }
        return await self._make_request(
            "POST",
            "usergroups.create",
            credentials,
            json_body=body,
            action_name="create_user_group",
        )

    async def _disable_usergroup(
        self, config: SlackDisableUserGroupConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Disable an existing user group."""
        body = {"usergroup": config.usergroup}
        return await self._make_request(
            "POST",
            "usergroups.disable",
            credentials,
            json_body=body,
            action_name="disable_user_group",
        )

    async def _enable_usergroup(
        self, config: SlackEnableUserGroupConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Enable a disabled user group."""
        body = {"usergroup": config.usergroup}
        return await self._make_request(
            "POST",
            "usergroups.enable",
            credentials,
            json_body=body,
            action_name="enable_user_group",
        )

    async def _update_usergroup(
        self, config: SlackUpdateUserGroupConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Update an existing user group."""
        body = {
            "usergroup": config.usergroup,
            "name": config.name,
            "handle": config.handle,
            "description": config.description,
            "channels": config.channels,
        }
        return await self._make_request(
            "POST",
            "usergroups.update",
            credentials,
            json_body=body,
            action_name="update_user_group",
        )

    async def _list_usergroup_users(
        self, config: SlackListUserGroupUsersConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List users in a user group."""
        params = {
            "usergroup": config.usergroup,
            "include_disabled": config.include_disabled,
        }
        return await self._make_request(
            "GET",
            "usergroups.users.list",
            credentials,
            params=params,
            action_name="list_usergroup_members",
        )

    async def _update_usergroup_users(
        self, config: SlackUpdateUserGroupUsersConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Update the list of users in a user group."""
        body = {
            "usergroup": config.usergroup,
            "users": config.users,
        }
        return await self._make_request(
            "POST",
            "usergroups.users.update",
            credentials,
            json_body=body,
            action_name="update_usergroup_member_list",
        )

    # ============================================================================
    # DND (Do Not Disturb) Actions
    # ============================================================================

    async def _dnd_set_snooze(
        self, config: SlackDndSetSnoozeConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Turn on Do Not Disturb for the current user."""
        body = {"num_minutes": config.num_minutes}
        return await self._make_request(
            "POST",
            "dnd.setSnooze",
            credentials,
            json_body=body,
            action_name="set_do_not_disturb_snooze",
            send_as="user",
        )

    async def _dnd_end_snooze(
        self, config: SlackDndEndSnoozeConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """End the current user's snooze mode."""
        return await self._make_request(
            "POST", "dnd.endSnooze", credentials, action_name="end_snooze_mode",
            send_as="user"
        )

    async def _dnd_end_dnd(
        self, config: SlackDndEndDndConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """End the current user's Do Not Disturb session."""
        return await self._make_request(
            "POST", "dnd.endDnd", credentials, action_name="end_do_not_disturb",
            send_as="user"
        )

    async def _dnd_info(
        self, config: SlackDndInfoConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get Do Not Disturb status for a user."""
        params = {"user": config.user}
        return await self._make_request(
            "GET",
            "dnd.info",
            credentials,
            params=params,
            action_name="get_do_not_disturb_status",
        )

    async def _dnd_team_info(
        self, config: SlackDndTeamInfoConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get Do Not Disturb status for users on a team."""
        params = {"users": config.users}
        return await self._make_request(
            "GET",
            "dnd.teamInfo",
            credentials,
            params=params,
            action_name="get_team_do_not_disturb_status",
        )

    # ============================================================================
    # Emoji Actions
    # ============================================================================

    async def _list_emoji(
        self, config: SlackListEmojiConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List custom emoji in the workspace."""
        params = {"include_categories": config.include_categories}
        return await self._make_request(
            "GET",
            "emoji.list",
            credentials,
            params=params,
            action_name="list_custom_emoji_in_workspace",
        )

    # ============================================================================
    # Star Actions
    # ============================================================================

    async def _add_star(
        self, config: SlackAddStarConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Star a message, file, or channel."""
        body = {
            "channel": config.channel,
            "timestamp": config.timestamp,
            "file": config.file,
        }
        return await self._make_request(
            "POST",
            "stars.add",
            credentials,
            json_body=body,
            action_name="star_message_or_file",
            send_as=config.send_as,
        )

    async def _remove_star(
        self, config: SlackRemoveStarConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Remove a star from an item."""
        body = {
            "channel": config.channel,
            "timestamp": config.timestamp,
            "file": config.file,
        }
        return await self._make_request(
            "POST",
            "stars.remove",
            credentials,
            json_body=body,
            action_name="unstar_item",
            send_as=config.send_as,
        )

    async def _list_stars(
        self, config: SlackListStarsConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List starred items for the current user."""
        params = {"count": config.count}
        return await self._make_request(
            "GET",
            "stars.list",
            credentials,
            params=params,
            action_name="list_user_starred_items",
            send_as="user",
        )

    # ============================================================================
    # Bot Actions
    # ============================================================================

    async def _bot_info(
        self, config: SlackBotInfoConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get information about a bot."""
        params = {"bot": config.bot}
        return await self._make_request(
            "GET",
            "bots.info",
            credentials,
            params=params,
            action_name="get_bot_information",
        )

    # ============================================================================
    # Reminder Actions
    # ============================================================================

    async def _add_reminder(
        self, config: SlackAddReminderConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Create a reminder."""
        body = {
            "text": config.text,
            "time": config.time,
            "user": config.user,
        }
        return await self._make_request(
            "POST",
            "reminders.add",
            credentials,
            json_body=body,
            action_name="create_reminder",
            send_as=config.send_as,
        )

    async def _complete_reminder(
        self, config: SlackCompleteReminderConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Mark a reminder as complete."""
        body = {"reminder": config.reminder}
        return await self._make_request(
            "POST",
            "reminders.complete",
            credentials,
            json_body=body,
            action_name="mark_reminder_complete",
            send_as="user",
        )

    async def _delete_reminder(
        self, config: SlackDeleteReminderConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Delete a reminder."""
        body = {"reminder": config.reminder}
        return await self._make_request(
            "POST",
            "reminders.delete",
            credentials,
            json_body=body,
            action_name="delete_reminder",
            send_as="user",
        )

    async def _reminder_info(
        self, config: SlackReminderInfoConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get information about a reminder."""
        params = {"reminder": config.reminder}
        return await self._make_request(
            "GET",
            "reminders.info",
            credentials,
            params=params,
            action_name="get_reminder_information",
            send_as="user",
        )

    async def _list_reminders(
        self, config: SlackListRemindersConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List all reminders for the current user."""
        return await self._make_request(
            "GET", "reminders.list", credentials, action_name="list_user_reminders",
            send_as="user"
        )

    # ============================================================================
    # Reaction Actions
    # ============================================================================

    async def _add_reaction(
        self, config: SlackAddReactionConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Add an emoji reaction to a message."""
        body = {
            "channel": config.channel,
            "timestamp": config.timestamp,
            "name": config.name,
        }
        return await self._make_request(
            "POST",
            "reactions.add",
            credentials,
            json_body=body,
            action_name="add_emoji_reaction_to_message",
            send_as=config.send_as,
        )

    async def _remove_reaction(
        self, config: SlackRemoveReactionConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Remove an emoji reaction from a message."""
        body = {
            "channel": config.channel,
            "timestamp": config.timestamp,
            "name": config.name,
        }
        return await self._make_request(
            "POST",
            "reactions.remove",
            credentials,
            json_body=body,
            action_name="remove_emoji_reaction_from_message",
            send_as=config.send_as,
        )

    async def _get_reactions(
        self, config: SlackGetReactionsConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get reactions on a message."""
        params = {
            "channel": config.channel,
            "timestamp": config.timestamp,
            "full": config.full,
        }
        return await self._make_request(
            "GET",
            "reactions.get",
            credentials,
            params=params,
            action_name="get_message_reactions",
            send_as="user",
        )

    # ============================================================================
    # Pin Actions
    # ============================================================================

    async def _add_pin(
        self, config: SlackAddPinConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Pin a message to a channel."""
        body = {
            "channel": config.channel,
            "timestamp": config.timestamp,
        }
        return await self._make_request(
            "POST",
            "pins.add",
            credentials,
            json_body=body,
            action_name="pin_message_to_channel",
            send_as=config.send_as,
        )

    async def _remove_pin(
        self, config: SlackRemovePinConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Unpin a message from a channel."""
        body = {
            "channel": config.channel,
            "timestamp": config.timestamp,
        }
        return await self._make_request(
            "POST",
            "pins.remove",
            credentials,
            json_body=body,
            action_name="unpin_message_from_channel",
            send_as=config.send_as,
        )

    async def _list_pins(
        self, config: SlackListPinsConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List pinned items in a channel."""
        params = {"channel": config.channel}
        return await self._make_request(
            "GET",
            "pins.list",
            credentials,
            params=params,
            action_name="list_pinned_items_in_channel",
            send_as="user",
        )

    # ============================================================================
    # File Actions
    # ============================================================================

    async def _list_files(
        self, config: SlackListFilesConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List files in the workspace."""
        params = {
            "channel": config.channel,
            "user": config.user,
            "types": config.types,
            "count": config.count,
        }
        return await self._make_request(
            "GET",
            "files.list",
            credentials,
            params=params,
            action_name="list_workspace_files",
        )

    async def _file_info(
        self, config: SlackFileInfoConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get information about a file."""
        params = {"file": config.file}
        return await self._make_request(
            "GET",
            "files.info",
            credentials,
            params=params,
            action_name="get_file_information",
        )

    async def _delete_file(
        self, config: SlackDeleteFileConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Delete a file."""
        body = {"file": config.file}
        return await self._make_request(
            "POST",
            "files.delete",
            credentials,
            json_body=body,
            action_name="delete_file",
            send_as=config.send_as,
        )

    # ============================================================================
    # Search Actions
    # ============================================================================

    async def _search_messages(
        self, config: SlackSearchMessagesConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Search for messages in the workspace."""
        params = {
            "query": config.query,
            "sort": config.sort,
            "sort_dir": config.sort_dir,
            "count": config.count,
        }
        return await self._make_request(
            "GET",
            "search.messages",
            credentials,
            params=params,
            action_name="search_workspace_messages",
            send_as="user",
        )

    # ============================================================================
    # Team/Auth Actions
    # ============================================================================

    async def _auth_test(
        self, config: SlackAuthTestConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Test authentication and get info about the token."""
        return await self._make_request(
            "POST", "auth.test", credentials, action_name="test_authentication"
        )

    async def _team_info(
        self, config: SlackTeamInfoConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get information about the workspace."""
        return await self._make_request(
            "GET", "team.info", credentials, action_name="get_workspace_information"
        )

    # ============================================================================
    # Additional File Operations
    # ============================================================================

    async def _upload_file(
        self, config: SlackUploadFileConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Upload a file to Slack using the external upload flow.

        Slack deprecated ``files.upload``; this keeps the high-level workflow
        operation working by wrapping get-upload-url, upload, and completion.
        """
        access_token = await self._ensure_fresh_token(
            credentials, send_as=config.send_as
        )
        content = config.content or ""
        if not content:
            raise ValueError("upload_file_to_slack requires content")

        # A media reference (resource_id from an upstream download/upload, a URL,
        # or a data: URI) uploads the actual file bytes; plain text uploads as-is.
        from nodes.core.media_resolver import looks_like_media_ref, resolve_media_input

        if looks_like_media_ref(content):
            resolved = await resolve_media_input(content)
            content_bytes = resolved.data
            filename = config.filename or resolved.filename
        else:
            content_bytes = content.encode("utf-8")
            filename = config.filename or "upload.txt"
        title = config.title or filename
        auth_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        async with guarded_async_client() as client:
            upload_meta_response = await client.get(
                f"{SLACK_API_BASE}/files.getUploadURLExternal",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "filename": filename,
                    "length": len(content_bytes),
                    **({"snippet_type": config.filetype} if config.filetype else {}),
                },
                timeout=30.0,
            )
            upload_meta = upload_meta_response.json()
            if inspect.isawaitable(upload_meta):
                upload_meta = await upload_meta
            if not upload_meta.get("ok", False):
                raise ValueError(
                    f"Slack API error: {upload_meta.get('error', 'Unknown error')}"
                )

            upload_url = upload_meta["upload_url"]
            await assert_url_allowed(upload_url)
            upload_response = await client.post(
                upload_url,
                content=content_bytes,
                headers={"Content-Type": "application/octet-stream"},
                timeout=60.0,
            )
            if upload_response.status_code >= 400:
                raise ValueError(
                    f"Slack upload URL error: HTTP {upload_response.status_code}"
                )

            complete_body = {
                "files": [{"id": upload_meta["file_id"], "title": title}],
            }
            if config.channels:
                complete_body["channel_id"] = config.channels.split(",")[0].strip()
            if config.initial_comment:
                complete_body["initial_comment"] = config.initial_comment
            if config.thread_ts:
                complete_body["thread_ts"] = config.thread_ts

            complete_response = await client.post(
                f"{SLACK_API_BASE}/files.completeUploadExternal",
                headers=auth_headers,
                json=complete_body,
                timeout=30.0,
            )
            result = complete_response.json()
            if not result.get("ok", False):
                raise ValueError(
                    f"Slack API error: {result.get('error', 'Unknown error')}"
                )

            return {
                "status": "success",
                "action": "upload_file_to_slack",
                "file": (result.get("files") or [{}])[0],
                "files": result.get("files", []),
            }

    async def _get_file_public_url(
        self, config: SlackGetFilePublicURLConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get public URL for a file."""
        return await self._make_request(
            "POST",
            "files.sharedPublicURL",
            credentials,
            json_body={"file": config.file},
            action_name="create_file_public_url",
            send_as="user",
        )

    async def _revoke_file_public_url(
        self, config: SlackRevokeFilePublicURLConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Revoke public URL for a file."""
        return await self._make_request(
            "POST",
            "files.revokePublicURL",
            credentials,
            json_body={"file": config.file},
            action_name="revoke_file_public_url",
        )

    # ============================================================================
    # Additional Search Operations
    # ============================================================================

    async def _search_files(
        self, config: SlackSearchFilesConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Search for files in the workspace."""
        params = {
            "query": config.query,
            "sort": config.sort,
            "sort_dir": config.sort_dir,
            "count": config.count,
        }
        return await self._make_request(
            "GET",
            "search.files",
            credentials,
            params=params,
            action_name="search_workspace_files",
            send_as="user",
        )

    async def _search_all(
        self, config: SlackSearchAllConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Search for messages and files in the workspace."""
        params = {
            "query": config.query,
            "sort": config.sort,
            "sort_dir": config.sort_dir,
            "count": config.count,
        }
        return await self._make_request(
            "GET",
            "search.all",
            credentials,
            params=params,
            action_name="search_messages_and_files",
            send_as="user",
        )

    # ============================================================================
    # Scheduled Message Operations
    # ============================================================================

    async def _delete_scheduled_message(
        self, config: SlackDeleteScheduledMessageConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Delete a scheduled message."""
        return await self._make_request(
            "POST",
            "chat.deleteScheduledMessage",
            credentials,
            json_body={
                "channel": config.channel,
                "scheduled_message_id": config.scheduled_message_id,
            },
            action_name="delete_scheduled_message",
            send_as=config.send_as,
        )

    async def _list_scheduled_messages(
        self, config: SlackListScheduledMessagesConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List scheduled messages."""
        params = {
            "channel": config.channel,
            "cursor": config.cursor,
            "latest": config.latest,
            "limit": config.limit,
            "oldest": config.oldest,
        }
        return await self._make_request(
            "POST",
            "chat.scheduledMessages.list",
            credentials,
            json_body=params,
            action_name="list_scheduled_messages",
        )

    # ============================================================================
    # Chat Extras
    # ============================================================================

    async def _me_message(
        self, config: SlackMeMessageConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Send a /me message."""
        return await self._make_request(
            "POST",
            "chat.meMessage",
            credentials,
            json_body={
                "channel": config.channel,
                "text": config.text,
            },
            action_name="send_me_message",
        )

    async def _unfurl(
        self, config: SlackUnfurlConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Provide custom unfurl behavior for URLs in messages."""
        import json as json_module

        # Parse unfurls JSON string
        try:
            unfurls_dict = json_module.loads(config.unfurls)
        except (json_module.JSONDecodeError, TypeError):
            unfurls_dict = config.unfurls

        body = {
            "channel": config.channel,
            "ts": config.ts,
            "unfurls": unfurls_dict,
        }

        return await self._make_request(
            "POST",
            "chat.unfurl",
            credentials,
            json_body=body,
            action_name="provide_custom_unfurl_behavior",
        )

    # ============================================================================
    # User Profile Operations
    # ============================================================================

    async def _get_user_profile(
        self, config: SlackGetUserProfileConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get a user's profile."""
        params = {
            "user": config.user,
            "include_labels": config.include_labels,
        }
        return await self._make_request(
            "GET",
            "users.profile.get",
            credentials,
            params=params,
            action_name="get_user_profile_information",
            send_as="user",
        )

    async def _set_user_presence(
        self, config: SlackSetUserPresenceConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Set user presence (auto or away)."""
        return await self._make_request(
            "POST",
            "users.setPresence",
            credentials,
            json_body={"presence": config.presence},
            action_name="set_user_presence_status",
            send_as="user",
        )

    # ============================================================================
    # Additional Team/Auth Operations
    # ============================================================================

    async def _api_test(
        self, config: SlackApiTestConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Test the Slack API."""
        return await self._make_request(
            "POST", "api.test", credentials, action_name="test_api_connection"
        )

    async def _auth_revoke(
        self, config: SlackAuthRevokeConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Revoke an access token."""
        params = {}
        if config.test:
            params["test"] = config.test

        return await self._make_request(
            "GET",
            "auth.revoke",
            credentials,
            params=params if params else None,
            action_name="revoke_oauth_token",
        )

    async def _apps_uninstall(
        self, config: SlackAppsUninstallConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Uninstall the app from a workspace."""
        return await self._make_request(
            "GET",
            "apps.uninstall",
            credentials,
            action_name="uninstall_app_from_workspace",
        )

    async def _team_billable_info(
        self, config: SlackTeamBillableInfoConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get billable info for team members."""
        params = {}
        if config.user:
            params["user"] = config.user

        return await self._make_request(
            "GET",
            "team.billableInfo",
            credentials,
            params=params if params else None,
            action_name="get_team_billable_information",
        )

    async def _team_access_logs(
        self, config: SlackTeamAccessLogsConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get access logs for the team."""
        params = {
            "before": config.before,
            "count": config.count,
            "page": config.page,
        }
        return await self._make_request(
            "GET",
            "team.accessLogs",
            credentials,
            params=params,
            action_name="get_workspace_access_logs",
        )

    async def _team_integration_logs(
        self, config: SlackTeamIntegrationLogsConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get integration logs for the team."""
        params = {
            "app_id": config.app_id,
            "change_type": config.change_type,
            "count": config.count,
            "page": config.page,
            "service_id": config.service_id,
            "user": config.user,
        }
        return await self._make_request(
            "GET",
            "team.integrationLogs",
            credentials,
            params=params,
            action_name="get_workspace_integration_logs",
        )

    # ============================================================================
    # Slack Connect Operations
    # ============================================================================

    async def _accept_shared_invite(
        self,
        config: SlackConversationsAcceptSharedInviteConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Accept a shared channel invite."""
        body = {
            "channel_name": config.channel_name,
        }
        if config.channel_id:
            body["channel_id"] = config.channel_id
        if config.invite_id:
            body["invite_id"] = config.invite_id
        if config.is_private is not None:
            body["is_private"] = config.is_private

        return await self._make_request(
            "POST",
            "conversations.acceptSharedInvite",
            credentials,
            json_body=body,
            action_name="accept_shared_channel_invite",
        )

    async def _decline_shared_invite(
        self,
        config: SlackConversationsDeclineSharedInviteConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Decline a shared channel invite."""
        body = {
            "invite_id": config.invite_id,
        }
        if config.target_team:
            body["target_team"] = config.target_team

        return await self._make_request(
            "POST",
            "conversations.declineSharedInvite",
            credentials,
            json_body=body,
            action_name="decline_shared_channel_invite",
        )

    async def _list_connect_invites(
        self,
        config: SlackConversationsListConnectInvitesConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """List shared channel invites."""
        params = {
            "count": config.count,
            "cursor": config.cursor,
            "team_id": config.team_id,
        }
        return await self._make_request(
            "POST",
            "conversations.listConnectInvites",
            credentials,
            json_body=params,
            action_name="list_slack_connect_invites",
        )

    # ============================================================================
    # New File Upload Operations (files.upload deprecated Nov 2025)
    # ============================================================================

    async def _get_upload_url_external(
        self, config: SlackGetUploadURLExternalConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get a URL for external file upload."""
        params = {
            "filename": config.filename,
            "length": config.length,
        }
        if config.alt_txt:
            params["alt_txt"] = config.alt_txt
        if config.snippet_type:
            params["snippet_type"] = config.snippet_type

        return await self._make_request(
            "GET",
            "files.getUploadURLExternal",
            credentials,
            params=params,
            action_name="get_external_file_upload_url",
        )

    async def _complete_upload_external(
        self, config: SlackCompleteUploadExternalConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Complete a file upload after uploading to external URL."""
        # Parse the files JSON string
        try:
            files_list = json.loads(config.files)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in files parameter")

        body = {
            "files": files_list,
        }
        if config.channel_id:
            body["channel_id"] = config.channel_id
        if config.initial_comment:
            body["initial_comment"] = config.initial_comment
        if config.thread_ts:
            body["thread_ts"] = config.thread_ts

        return await self._make_request(
            "POST",
            "files.completeUploadExternal",
            credentials,
            json_body=body,
            action_name="complete_external_file_upload",
        )

    # ============================================================================
    # User Profile Operations
    # ============================================================================

    async def _set_user_profile(
        self, config: SlackSetUserProfileConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Set user profile fields."""
        # Parse the profile JSON string
        try:
            profile_data = json.loads(config.profile)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in profile parameter")

        body = {
            "profile": profile_data,
        }
        if config.user:
            body["user"] = config.user

        return await self._make_request(
            "POST",
            "users.profile.set",
            credentials,
            json_body=body,
            action_name="set_user_profile_fields",
            send_as="user",
        )

    # ============================================================================
    # Additional Slack Connect Operations
    # ============================================================================

    async def _approve_shared_invite(
        self, config: SlackApproveSharedInviteConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Approve a shared channel invite."""
        body = {
            "invite_id": config.invite_id,
        }
        if config.channel_id:
            body["channel_id"] = config.channel_id
        if config.is_private is not None:
            body["is_private"] = config.is_private
        if config.target_team:
            body["target_team"] = config.target_team

        return await self._make_request(
            "POST",
            "conversations.approveSharedInvite",
            credentials,
            json_body=body,
            action_name="approve_slack_connect_channel_invite",
        )

    async def _invite_shared(
        self, config: SlackInviteSharedConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Invite users to a Slack Connect channel."""
        body = {
            "channel": config.channel,
        }
        if config.emails:
            body["emails"] = config.emails
        if config.user_ids:
            body["user_ids"] = config.user_ids
        if config.external_limited is not None:
            body["external_limited"] = config.external_limited

        return await self._make_request(
            "POST",
            "conversations.inviteShared",
            credentials,
            json_body=body,
            action_name="invite_user_to_slack_connect_channel",
        )

    # ============================================================================
    # Remote File Operations
    # ============================================================================

    async def _add_remote_file(
        self, config: SlackAddRemoteFileConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Add a remote file."""
        body = {
            "external_id": config.external_id,
            "external_url": config.external_url,
            "title": config.title,
        }
        if config.filetype:
            body["filetype"] = config.filetype
        if config.preview_image:
            body["preview_image"] = config.preview_image
        if config.indexable_file_contents:
            body["indexable_file_contents"] = config.indexable_file_contents

        return await self._make_request(
            "POST",
            "files.remote.add",
            credentials,
            form_body=body,
            action_name="add_remote_file_to_workspace",
        )

    async def _remove_remote_file(
        self, config: SlackRemoveRemoteFileConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Remove a remote file."""
        body = {}
        if config.external_id:
            body["external_id"] = config.external_id
        if config.file:
            body["file"] = config.file

        return await self._make_request(
            "POST",
            "files.remote.remove",
            credentials,
            form_body=body,
            action_name="remove_remote_file",
        )

    async def _share_remote_file(
        self, config: SlackShareRemoteFileConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Share a remote file to channels."""
        body = {
            "channels": config.channels,
        }
        if config.external_id:
            body["external_id"] = config.external_id
        if config.file:
            body["file"] = config.file

        return await self._make_request(
            # Documented as GET — arguments ride the query string.
            "GET",
            "files.remote.share",
            credentials,
            params=body,
            action_name="share_remote_file_to_channel",
        )

    async def _list_remote_files(
        self, config: SlackListRemoteFilesConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List remote files."""
        params = {
            "limit": config.limit,
        }
        if config.channel:
            params["channel"] = config.channel
        if config.cursor:
            params["cursor"] = config.cursor
        if config.ts_from:
            params["ts_from"] = config.ts_from
        if config.ts_to:
            params["ts_to"] = config.ts_to

        return await self._make_request(
            "GET",
            "files.remote.list",
            credentials,
            params=params,
            action_name="list_remote_files",
        )

    # ========================================================================
    # Additional Operations (11 new methods)
    # ========================================================================

    async def _list_reactions(
        self, config: SlackListReactionsConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List reactions for an item."""
        params = {
            "full": config.full,
        }
        if config.channel:
            params["channel"] = config.channel
        if config.file:
            params["file"] = config.file
        if config.file_comment:
            params["file_comment"] = config.file_comment
        if config.timestamp:
            params["timestamp"] = config.timestamp

        return await self._make_request(
            "GET",
            "reactions.list",
            credentials,
            params=params,
            action_name="list_reactions_for_item",
        )

    async def _remote_file_info(
        self, config: SlackRemoteFileInfoConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get information about a remote file."""
        params = {}
        if config.external_id:
            params["external_id"] = config.external_id
        if config.file:
            params["file"] = config.file

        return await self._make_request(
            "GET",
            "files.remote.info",
            credentials,
            params=params,
            action_name="get_remote_file_information",
        )

    async def _remote_file_update(
        self, config: SlackRemoteFileUpdateConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Update a remote file."""
        body = {}
        if config.external_id:
            body["external_id"] = config.external_id
        if config.file:
            body["file"] = config.file
        if config.title:
            body["title"] = config.title
        if config.external_url:
            body["external_url"] = config.external_url
        if config.filetype:
            body["filetype"] = config.filetype
        if config.indexable_file_contents:
            body["indexable_file_contents"] = config.indexable_file_contents
        if config.preview_image:
            body["preview_image"] = config.preview_image

        return await self._make_request(
            "POST",
            "files.remote.update",
            credentials,
            form_body=body,
            action_name="update_remote_file",
        )

    async def _delete_file_comment(
        self, config: SlackDeleteFileCommentConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Delete a file comment."""
        body = {
            "file": config.file,
            "id": config.id,
        }

        return await self._make_request(
            "POST",
            "files.comments.delete",
            credentials,
            json_body=body,
            action_name="delete_file_comment",
        )

    async def _delete_user_photo(
        self, config: SlackDeleteUserPhotoConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Delete the user's profile photo."""
        return await self._make_request(
            "POST",
            "users.deletePhoto",
            credentials,
            json_body={},
            action_name="delete_user_profile_photo",
            send_as="user",
        )

    async def _set_user_active(
        self, config: SlackSetUserActiveConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Mark user as active."""
        return await self._make_request(
            "POST",
            "users.setActive",
            credentials,
            json_body={},
            action_name="set_user_as_active",
            send_as="user",
        )

    async def _create_canvas(
        self, config: SlackCreateCanvasConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Create a canvas in a channel."""
        body = {
            "channel_id": config.channel_id,
        }
        if config.document_content:
            body["document_content"] = config.document_content

        return await self._make_request(
            "POST",
            "conversations.canvases.create",
            credentials,
            json_body=body,
            action_name="create_canvas_in_channel",
        )

    async def _set_external_invite_permissions(
        self,
        config: SlackSetExternalInvitePermissionsConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Set external invite permissions for a channel."""
        body = {
            "channel": config.channel,
            "action": config.action_type,
        }

        return await self._make_request(
            "POST",
            "conversations.externalInvitePermissions.set",
            credentials,
            json_body=body,
            action_name="set_channel_external_invite_permissions",
        )

    async def _approve_shared_invite_request(
        self,
        config: SlackApproveSharedInviteRequestConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Approve a Slack Connect invite request."""
        body = {
            "invite_id": config.invite_id,
            "is_external_limited": config.is_external_limited,
        }
        if config.channel_id:
            body["channel_id"] = config.channel_id
        if config.message:
            body["message"] = config.message

        return await self._make_request(
            "POST",
            "conversations.requestSharedInvite.approve",
            credentials,
            json_body=body,
            action_name="approve_slack_connect_invite_request",
        )

    async def _deny_shared_invite_request(
        self, config: SlackDenySharedInviteRequestConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Deny a Slack Connect invite request."""
        body = {
            "invite_id": config.invite_id,
        }
        if config.message:
            body["message"] = config.message

        return await self._make_request(
            "POST",
            "conversations.requestSharedInvite.deny",
            credentials,
            json_body=body,
            action_name="deny_slack_connect_invite_request",
        )

    async def _list_shared_invite_requests(
        self, config: SlackListSharedInviteRequestsConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List Slack Connect invite requests."""
        params = {
            "limit": config.limit,
            "include_approved": config.include_approved,
            "include_denied": config.include_denied,
            "include_expired": config.include_expired,
        }
        if config.cursor:
            params["cursor"] = config.cursor

        return await self._make_request(
            "GET",
            "conversations.requestSharedInvite.list",
            credentials,
            params=params,
            action_name="list_slack_connect_invite_requests",
        )

    # ========================================================================
    # Admin API Operations (Enterprise Grid)
    # ========================================================================

    # --- admin.analytics (1) ---

    async def _admin_analytics_get_file(
        self, config: SlackAdminAnalyticsGetFileConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get analytics data for a given date."""
        params = {
            "type": config.type,
            "metadata_only": config.metadata_only,
        }
        if config.date:
            params["date"] = config.date

        return await self._make_request(
            "GET",
            "admin.analytics.getFile",
            credentials,
            params=params,
            action_name="get_analytics_file_for_date",
        )

    # --- admin.apps (11) ---

    async def _admin_apps_activities_list(
        self, config: SlackAdminAppsActivitiesListConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get logs for app activities."""
        params = {
            "limit": config.limit,
            "sort_direction": config.sort_direction,
        }
        if config.app_id:
            params["app_id"] = config.app_id
        if config.component_id:
            params["component_id"] = config.component_id
        if config.component_type:
            params["component_type"] = config.component_type
        if config.log_event_type:
            params["log_event_type"] = config.log_event_type
        if config.cursor:
            params["cursor"] = config.cursor
        if config.max_date_created:
            params["max_date_created"] = config.max_date_created
        if config.min_date_created:
            params["min_date_created"] = config.min_date_created
        if config.source:
            params["source"] = config.source
        if config.team_id:
            params["team_id"] = config.team_id

        return await self._make_request(
            "GET",
            "admin.apps.activities.list",
            credentials,
            params=params,
            action_name="list_app_activity_logs",
        )

    async def _admin_apps_approve(
        self, config: SlackAdminAppsApproveConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Approve an app for installation."""
        body = {}
        if config.app_id:
            body["app_id"] = config.app_id
        if config.request_id:
            body["request_id"] = config.request_id
        if config.enterprise_id:
            body["enterprise_id"] = config.enterprise_id
        if config.team_id:
            body["team_id"] = config.team_id

        return await self._make_request(
            "POST",
            "admin.apps.approve",
            credentials,
            json_body=body,
            action_name="approve_app_for_installation",
        )

    async def _admin_apps_approved_list(
        self, config: SlackAdminAppsApprovedListConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List approved apps."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        if config.enterprise_id:
            params["enterprise_id"] = config.enterprise_id
        if config.team_id:
            params["team_id"] = config.team_id

        return await self._make_request(
            "GET",
            "admin.apps.approved.list",
            credentials,
            params=params,
            action_name="list_approved_apps",
        )

    async def _admin_apps_clear_resolution(
        self, config: SlackAdminAppsClearResolutionConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Clear app resolution."""
        body = {"app_id": config.app_id}
        if config.enterprise_id:
            body["enterprise_id"] = config.enterprise_id
        if config.team_id:
            body["team_id"] = config.team_id

        return await self._make_request(
            "POST",
            "admin.apps.clearResolution",
            credentials,
            json_body=body,
            action_name="clear_app_resolution",
        )

    async def _admin_apps_config_lookup(
        self, config: SlackAdminAppsConfigLookupConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Look up app config."""
        body = {"app_ids": config.app_ids}

        return await self._make_request(
            "POST",
            "admin.apps.config.lookup",
            credentials,
            json_body=body,
            action_name="lookup_app_configuration",
        )

    async def _admin_apps_config_set(
        self, config: SlackAdminAppsConfigSetConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Set app config."""
        body = {"app_id": config.app_id}
        if config.domain_restrictions:
            body["domain_restrictions"] = config.domain_restrictions
        if config.workflow_auth_strategy:
            body["workflow_auth_strategy"] = config.workflow_auth_strategy

        return await self._make_request(
            "POST",
            "admin.apps.config.set",
            credentials,
            json_body=body,
            action_name="set_app_configuration",
        )

    async def _admin_apps_requests_cancel(
        self, config: SlackAdminAppsRequestsCancelConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Cancel an app request."""
        body = {"request_id": config.request_id}
        if config.enterprise_id:
            body["enterprise_id"] = config.enterprise_id
        if config.team_id:
            body["team_id"] = config.team_id

        return await self._make_request(
            "POST",
            "admin.apps.requests.cancel",
            credentials,
            json_body=body,
            action_name="cancel_app_request",
        )

    async def _admin_apps_requests_list(
        self, config: SlackAdminAppsRequestsListConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List app requests."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        if config.enterprise_id:
            params["enterprise_id"] = config.enterprise_id
        if config.team_id:
            params["team_id"] = config.team_id

        return await self._make_request(
            "GET",
            "admin.apps.requests.list",
            credentials,
            params=params,
            action_name="list_app_requests",
        )

    async def _admin_apps_restrict(
        self, config: SlackAdminAppsRestrictConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Restrict an app."""
        body = {}
        if config.app_id:
            body["app_id"] = config.app_id
        if config.request_id:
            body["request_id"] = config.request_id
        if config.enterprise_id:
            body["enterprise_id"] = config.enterprise_id
        if config.team_id:
            body["team_id"] = config.team_id

        return await self._make_request(
            "POST",
            "admin.apps.restrict",
            credentials,
            json_body=body,
            action_name="restrict_app",
        )

    async def _admin_apps_restricted_list(
        self, config: SlackAdminAppsRestrictedListConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List restricted apps."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        if config.enterprise_id:
            params["enterprise_id"] = config.enterprise_id
        if config.team_id:
            params["team_id"] = config.team_id

        return await self._make_request(
            "GET",
            "admin.apps.restricted.list",
            credentials,
            params=params,
            action_name="list_restricted_apps",
        )

    async def _admin_apps_uninstall(
        self, config: SlackAdminAppsUninstallConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Uninstall an app."""
        body = {"app_id": config.app_id}
        if config.enterprise_id:
            body["enterprise_id"] = config.enterprise_id
        if config.team_ids:
            body["team_ids"] = config.team_ids

        return await self._make_request(
            "POST",
            "admin.apps.uninstall",
            credentials,
            json_body=body,
            action_name="uninstall_app",
        )

    # --- admin.audit (2) ---

    async def _admin_audit_anomaly_allow_get_item(
        self,
        config: SlackAdminAuditAnomalyAllowGetItemConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Get allowed audit anomaly item."""
        params = {
            "constraint_type": config.constraint_type,
            "constraint_resource": config.constraint_resource,
        }

        return await self._make_request(
            "GET",
            "admin.audit.anomaly.allow.getItem",
            credentials,
            params=params,
            action_name="get_allowed_audit_anomaly_item",
        )

    async def _admin_audit_anomaly_allow_update_item(
        self,
        config: SlackAdminAuditAnomalyAllowUpdateItemConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Update allowed audit anomaly item."""
        body = {
            "constraint_type": config.constraint_type,
            "constraint_resource": config.constraint_resource,
            "allow_list": config.allow_list,
        }

        return await self._make_request(
            "POST",
            "admin.audit.anomaly.allow.updateItem",
            credentials,
            json_body=body,
            action_name="update_allowed_audit_anomaly_item",
        )

    # --- admin.auth.policy (3) ---

    async def _admin_auth_policy_assign_entities(
        self,
        config: SlackAdminAuthPolicyAssignEntitiesConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Assign entities to auth policy."""
        body = {
            "entity_ids": config.entity_ids,
            "entity_type": config.entity_type,
            "policy_name": config.policy_name,
        }

        return await self._make_request(
            "POST",
            "admin.auth.policy.assignEntities",
            credentials,
            json_body=body,
            action_name="assign_entities_to_auth_policy",
        )

    async def _admin_auth_policy_get_entities(
        self,
        config: SlackAdminAuthPolicyGetEntitiesConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Get entities for auth policy."""
        params = {
            "policy_name": config.policy_name,
            "limit": config.limit,
        }
        if config.cursor:
            params["cursor"] = config.cursor
        if config.entity_type:
            params["entity_type"] = config.entity_type

        return await self._make_request(
            "GET",
            "admin.auth.policy.getEntities",
            credentials,
            params=params,
            action_name="get_entities_for_auth_policy",
        )

    async def _admin_auth_policy_remove_entities(
        self,
        config: SlackAdminAuthPolicyRemoveEntitiesConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Remove entities from auth policy."""
        body = {
            "entity_ids": config.entity_ids,
            "entity_type": config.entity_type,
            "policy_name": config.policy_name,
        }

        return await self._make_request(
            "POST",
            "admin.auth.policy.removeEntities",
            credentials,
            json_body=body,
            action_name="remove_entities_from_auth_policy",
        )

    # --- admin.barriers (4) ---

    async def _admin_barriers_create(
        self, config: SlackAdminBarriersCreateConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Create an information barrier."""
        body = {
            "barriered_from_usergroup_ids": config.barriered_from_usergroup_ids,
            "primary_usergroup_id": config.primary_usergroup_id,
            "restricted_subjects": config.restricted_subjects,
        }

        return await self._make_request(
            "POST",
            "admin.barriers.create",
            credentials,
            json_body=body,
            action_name="create_information_barrier",
        )

    async def _admin_barriers_delete(
        self, config: SlackAdminBarriersDeleteConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Delete an information barrier."""
        body = {"barrier_id": config.barrier_id}

        return await self._make_request(
            "POST",
            "admin.barriers.delete",
            credentials,
            json_body=body,
            action_name="delete_information_barrier",
        )

    async def _admin_barriers_list(
        self, config: SlackAdminBarriersListConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List information barriers."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        return await self._make_request(
            "GET",
            "admin.barriers.list",
            credentials,
            params=params,
            action_name="list_information_barriers",
        )

    async def _admin_barriers_update(
        self, config: SlackAdminBarriersUpdateConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Update an information barrier."""
        body = {
            "barrier_id": config.barrier_id,
            "barriered_from_usergroup_ids": config.barriered_from_usergroup_ids,
            "primary_usergroup_id": config.primary_usergroup_id,
            "restricted_subjects": config.restricted_subjects,
        }

        return await self._make_request(
            "POST",
            "admin.barriers.update",
            credentials,
            json_body=body,
            action_name="update_information_barrier",
        )

    # --- admin.conversations (26) ---

    async def _admin_conversations_archive(
        self, config: SlackAdminConversationsArchiveConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Archive a conversation."""
        body = {"channel_id": config.channel_id}

        return await self._make_request(
            "POST",
            "admin.conversations.archive",
            credentials,
            json_body=body,
            action_name="archive_conversation_as_admin",
        )

    async def _admin_conversations_bulk_archive(
        self,
        config: SlackAdminConversationsBulkArchiveConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Bulk archive conversations."""
        body = {"channel_ids": config.channel_ids}

        return await self._make_request(
            "POST",
            "admin.conversations.bulkArchive",
            credentials,
            json_body=body,
            action_name="bulk_archive_conversations",
        )

    async def _admin_conversations_bulk_delete(
        self,
        config: SlackAdminConversationsBulkDeleteConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Bulk delete conversations."""
        body = {"channel_ids": config.channel_ids}

        return await self._make_request(
            "POST",
            "admin.conversations.bulkDelete",
            credentials,
            json_body=body,
            action_name="bulk_delete_conversations",
        )

    async def _admin_conversations_bulk_move(
        self,
        config: SlackAdminConversationsBulkMoveConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Bulk move conversations to a team."""
        body = {
            "channel_ids": config.channel_ids,
            "target_team_id": config.target_team_id,
        }

        return await self._make_request(
            "POST",
            "admin.conversations.bulkMove",
            credentials,
            json_body=body,
            action_name="bulk_move_conversations_to_team",
        )

    async def _admin_conversations_convert_to_private(
        self,
        config: SlackAdminConversationsConvertToPrivateConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Convert public channel to private."""
        body = {"channel_id": config.channel_id}

        return await self._make_request(
            "POST",
            "admin.conversations.convertToPrivate",
            credentials,
            json_body=body,
            action_name="convert_channel_to_private",
        )

    async def _admin_conversations_convert_to_public(
        self,
        config: SlackAdminConversationsConvertToPublicConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Convert private channel to public."""
        body = {"channel_id": config.channel_id}

        return await self._make_request(
            "POST",
            "admin.conversations.convertToPublic",
            credentials,
            json_body=body,
            action_name="convert_channel_to_public",
        )

    async def _admin_conversations_create(
        self, config: SlackAdminConversationsCreateConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Create a conversation."""
        body = {
            "name": config.name,
            "is_private": config.is_private,
            "org_wide": config.org_wide,
        }
        if config.description:
            body["description"] = config.description
        if config.team_id:
            body["team_id"] = config.team_id

        return await self._make_request(
            "POST",
            "admin.conversations.create",
            credentials,
            json_body=body,
            action_name="create_admin_conversation",
        )

    async def _admin_conversations_delete(
        self, config: SlackAdminConversationsDeleteConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Delete a conversation."""
        body = {"channel_id": config.channel_id}

        return await self._make_request(
            "POST",
            "admin.conversations.delete",
            credentials,
            json_body=body,
            action_name="delete_conversation",
        )

    async def _admin_conversations_disconnect_shared(
        self,
        config: SlackAdminConversationsDisconnectSharedConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Disconnect a shared channel."""
        body = {"channel_id": config.channel_id}
        if config.leaving_team_ids:
            body["leaving_team_ids"] = config.leaving_team_ids

        return await self._make_request(
            "POST",
            "admin.conversations.disconnectShared",
            credentials,
            json_body=body,
            action_name="disconnect_shared_channel",
        )

    async def _admin_conversations_ekm_list_original_connected_channel_info(
        self,
        config: SlackAdminConversationsEkmListOriginalConnectedChannelInfoConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """List original connected channel info for EKM."""
        params = {"limit": config.limit}
        if config.channel_ids:
            params["channel_ids"] = ",".join(config.channel_ids)
        if config.cursor:
            params["cursor"] = config.cursor
        if config.team_ids:
            params["team_ids"] = ",".join(config.team_ids)

        return await self._make_request(
            "GET",
            "admin.conversations.ekm.listOriginalConnectedChannelInfo",
            credentials,
            params=params,
            action_name="list_ekm_original_channel_info",
        )

    async def _admin_conversations_get_conversation_prefs(
        self,
        config: SlackAdminConversationsGetConversationPrefsConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Get conversation preferences."""
        params = {"channel_id": config.channel_id}

        return await self._make_request(
            "GET",
            "admin.conversations.getConversationPrefs",
            credentials,
            params=params,
            action_name="get_conversation_preferences",
        )

    async def _admin_conversations_get_custom_retention(
        self,
        config: SlackAdminConversationsGetCustomRetentionConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Get custom retention settings."""
        params = {"channel_id": config.channel_id}

        return await self._make_request(
            "GET",
            "admin.conversations.getCustomRetention",
            credentials,
            params=params,
            action_name="get_channel_retention_settings",
        )

    async def _admin_conversations_get_teams(
        self,
        config: SlackAdminConversationsGetTeamsConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Get teams for a conversation."""
        params = {
            "channel_id": config.channel_id,
            "limit": config.limit,
        }
        if config.cursor:
            params["cursor"] = config.cursor

        return await self._make_request(
            "GET",
            "admin.conversations.getTeams",
            credentials,
            params=params,
            action_name="list_teams_for_conversation",
        )

    async def _admin_conversations_invite(
        self, config: SlackAdminConversationsInviteConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Invite users to a conversation."""
        body = {
            "channel_id": config.channel_id,
            "user_ids": config.user_ids,
        }

        return await self._make_request(
            "POST",
            "admin.conversations.invite",
            credentials,
            json_body=body,
            action_name="invite_users_to_conversation_as_admin",
        )

    async def _admin_conversations_lookup(
        self, config: SlackAdminConversationsLookupConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Look up conversations."""
        params = {
            "last_message_activity_before": config.last_message_activity_before,
            "team_ids": ",".join(config.team_ids),
            "limit": config.limit,
        }
        if config.cursor:
            params["cursor"] = config.cursor
        if config.max_member_count:
            params["max_member_count"] = config.max_member_count

        return await self._make_request(
            "GET",
            "admin.conversations.lookup",
            credentials,
            params=params,
            action_name="lookup_conversations",
        )

    async def _admin_conversations_remove_custom_retention(
        self,
        config: SlackAdminConversationsRemoveCustomRetentionConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Remove custom retention settings."""
        body = {"channel_id": config.channel_id}

        return await self._make_request(
            "POST",
            "admin.conversations.removeCustomRetention",
            credentials,
            json_body=body,
            action_name="remove_channel_retention_settings",
        )

    async def _admin_conversations_rename(
        self, config: SlackAdminConversationsRenameConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Rename a conversation."""
        body = {
            "channel_id": config.channel_id,
            "name": config.name,
        }

        return await self._make_request(
            "POST",
            "admin.conversations.rename",
            credentials,
            json_body=body,
            action_name="rename_conversation_as_admin",
        )

    async def _admin_conversations_restrict_access_add_group(
        self,
        config: SlackAdminConversationsRestrictAccessAddGroupConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Add IDP group to channel."""
        body = {
            "channel_id": config.channel_id,
            "group_id": config.group_id,
        }
        if config.team_id:
            body["team_id"] = config.team_id

        return await self._make_request(
            "POST",
            "admin.conversations.restrictAccess.addGroup",
            credentials,
            json_body=body,
            action_name="add_idp_group_to_channel",
        )

    async def _admin_conversations_restrict_access_list_groups(
        self,
        config: SlackAdminConversationsRestrictAccessListGroupsConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """List IDP groups for channel."""
        params = {"channel_id": config.channel_id}
        if config.team_id:
            params["team_id"] = config.team_id

        return await self._make_request(
            "GET",
            "admin.conversations.restrictAccess.listGroups",
            credentials,
            params=params,
            action_name="list_idp_groups_for_channel",
        )

    async def _admin_conversations_restrict_access_remove_group(
        self,
        config: SlackAdminConversationsRestrictAccessRemoveGroupConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Remove IDP group from channel."""
        body = {
            "channel_id": config.channel_id,
            "group_id": config.group_id,
            "team_id": config.team_id,
        }

        return await self._make_request(
            "POST",
            "admin.conversations.restrictAccess.removeGroup",
            credentials,
            json_body=body,
            action_name="remove_idp_group_from_channel",
        )

    async def _admin_conversations_search(
        self, config: SlackAdminConversationsSearchConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Search for conversations."""
        params = {
            "limit": config.limit,
            "total_count_only": config.total_count_only,
        }
        if config.cursor:
            params["cursor"] = config.cursor
        if config.query:
            params["query"] = config.query
        if config.search_channel_types:
            params["search_channel_types"] = ",".join(config.search_channel_types)
        if config.sort:
            params["sort"] = config.sort
        if config.sort_dir:
            params["sort_dir"] = config.sort_dir
        if config.team_ids:
            params["team_ids"] = ",".join(config.team_ids)
        if config.connected_team_ids:
            params["connected_team_ids"] = ",".join(config.connected_team_ids)

        return await self._make_request(
            "GET",
            "admin.conversations.search",
            credentials,
            params=params,
            action_name="search_conversations",
        )

    async def _admin_conversations_set_conversation_prefs(
        self,
        config: SlackAdminConversationsSetConversationPrefsConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Set conversation preferences."""
        body = {
            "channel_id": config.channel_id,
            "prefs": config.prefs,
        }

        return await self._make_request(
            "POST",
            "admin.conversations.setConversationPrefs",
            credentials,
            json_body=body,
            action_name="set_conversation_preferences",
        )

    async def _admin_conversations_set_custom_retention(
        self,
        config: SlackAdminConversationsSetCustomRetentionConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Set custom retention settings."""
        body = {
            "channel_id": config.channel_id,
            "duration_days": config.duration_days,
        }

        return await self._make_request(
            "POST",
            "admin.conversations.setCustomRetention",
            credentials,
            json_body=body,
            action_name="set_channel_retention_settings",
        )

    async def _admin_conversations_set_teams(
        self,
        config: SlackAdminConversationsSetTeamsConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Set teams for a conversation."""
        body = {
            "channel_id": config.channel_id,
            "org_channel": config.org_channel,
        }
        if config.target_team_ids:
            body["target_team_ids"] = config.target_team_ids
        if config.team_id:
            body["team_id"] = config.team_id

        return await self._make_request(
            "POST",
            "admin.conversations.setTeams",
            credentials,
            json_body=body,
            action_name="set_teams_for_conversation",
        )

    async def _admin_conversations_unarchive(
        self,
        config: SlackAdminConversationsUnarchiveConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Unarchive a conversation."""
        body = {"channel_id": config.channel_id}

        return await self._make_request(
            "POST",
            "admin.conversations.unarchive",
            credentials,
            json_body=body,
            action_name="unarchive_conversation_as_admin",
        )

    # --- admin.emoji (5) ---

    async def _admin_emoji_add(
        self, config: SlackAdminEmojiAddConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Add custom emoji."""
        body = {
            "name": config.name,
            "url": config.url,
        }

        return await self._make_request(
            "POST",
            "admin.emoji.add",
            credentials,
            json_body=body,
            action_name="add_custom_emoji",
        )

    async def _admin_emoji_add_alias(
        self, config: SlackAdminEmojiAddAliasConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Add emoji alias."""
        body = {
            "alias_for": config.alias_for,
            "name": config.name,
        }

        return await self._make_request(
            "POST",
            "admin.emoji.addAlias",
            credentials,
            json_body=body,
            action_name="add_emoji_alias",
        )

    async def _admin_emoji_list(
        self, config: SlackAdminEmojiListConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List custom emoji."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        return await self._make_request(
            "GET",
            "admin.emoji.list",
            credentials,
            params=params,
            action_name="list_custom_emoji",
        )

    async def _admin_emoji_remove(
        self, config: SlackAdminEmojiRemoveConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Remove custom emoji."""
        body = {"name": config.name}

        return await self._make_request(
            "POST",
            "admin.emoji.remove",
            credentials,
            json_body=body,
            action_name="remove_custom_emoji",
        )

    async def _admin_emoji_rename(
        self, config: SlackAdminEmojiRenameConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Rename custom emoji."""
        body = {
            "name": config.name,
            "new_name": config.new_name,
        }

        return await self._make_request(
            "POST",
            "admin.emoji.rename",
            credentials,
            json_body=body,
            action_name="rename_custom_emoji",
        )

    # --- admin.functions (3) ---

    async def _admin_functions_list(
        self, config: SlackAdminFunctionsListConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List functions."""
        params = {"limit": config.limit}
        if config.app_ids:
            params["app_ids"] = ",".join(config.app_ids)
        if config.cursor:
            params["cursor"] = config.cursor
        if config.team_id:
            params["team_id"] = config.team_id

        return await self._make_request(
            "GET",
            "admin.functions.list",
            credentials,
            params=params,
            action_name="list_functions",
        )

    async def _admin_functions_permissions_lookup(
        self,
        config: SlackAdminFunctionsPermissionsLookupConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Look up function permissions."""
        body = {"function_ids": config.function_ids}

        return await self._make_request(
            "POST",
            "admin.functions.permissions.lookup",
            credentials,
            json_body=body,
            action_name="lookup_function_permissions",
        )

    async def _admin_functions_permissions_set(
        self,
        config: SlackAdminFunctionsPermissionsSetConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Set function permissions."""
        body = {
            "function_id": config.function_id,
            "visibility": config.visibility,
        }
        if config.user_ids:
            body["user_ids"] = config.user_ids

        return await self._make_request(
            "POST",
            "admin.functions.permissions.set",
            credentials,
            json_body=body,
            action_name="set_function_permissions",
        )

    # --- admin.inviteRequests (5) ---

    async def _admin_invite_requests_approve(
        self,
        config: SlackAdminInviteRequestsApproveConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Approve invite request."""
        body = {"invite_request_id": config.invite_request_id}
        if config.team_id:
            body["team_id"] = config.team_id

        return await self._make_request(
            "POST",
            "admin.inviteRequests.approve",
            credentials,
            json_body=body,
            action_name="approve_invite_request",
        )

    async def _admin_invite_requests_approved_list(
        self,
        config: SlackAdminInviteRequestsApprovedListConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """List approved invite requests."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        if config.team_id:
            params["team_id"] = config.team_id

        return await self._make_request(
            "GET",
            "admin.inviteRequests.approved.list",
            credentials,
            params=params,
            action_name="list_approved_invite_requests",
        )

    async def _admin_invite_requests_denied_list(
        self,
        config: SlackAdminInviteRequestsDeniedListConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """List denied invite requests."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        if config.team_id:
            params["team_id"] = config.team_id

        return await self._make_request(
            "GET",
            "admin.inviteRequests.denied.list",
            credentials,
            params=params,
            action_name="list_denied_invite_requests",
        )

    async def _admin_invite_requests_deny(
        self, config: SlackAdminInviteRequestsDenyConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Deny invite request."""
        body = {"invite_request_id": config.invite_request_id}
        if config.team_id:
            body["team_id"] = config.team_id

        return await self._make_request(
            "POST",
            "admin.inviteRequests.deny",
            credentials,
            json_body=body,
            action_name="deny_invite_request",
        )

    async def _admin_invite_requests_list(
        self, config: SlackAdminInviteRequestsListConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List invite requests."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        if config.team_id:
            params["team_id"] = config.team_id

        return await self._make_request(
            "GET",
            "admin.inviteRequests.list",
            credentials,
            params=params,
            action_name="list_invite_requests",
        )

    # --- admin.roles (3) ---

    async def _admin_roles_add_assignments(
        self, config: SlackAdminRolesAddAssignmentsConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Add role assignments."""
        body = {
            "entity_ids": config.entity_ids,
            "role_id": config.role_id,
            "user_ids": config.user_ids,
        }

        return await self._make_request(
            "POST",
            "admin.roles.addAssignments",
            credentials,
            json_body=body,
            action_name="add_role_assignments",
        )

    async def _admin_roles_list_assignments(
        self, config: SlackAdminRolesListAssignmentsConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List role assignments."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        if config.entity_ids:
            params["entity_ids"] = ",".join(config.entity_ids)
        if config.role_ids:
            params["role_ids"] = ",".join(config.role_ids)
        if config.sort_dir:
            params["sort_dir"] = config.sort_dir

        return await self._make_request(
            "GET",
            "admin.roles.listAssignments",
            credentials,
            params=params,
            action_name="list_role_assignments",
        )

    async def _admin_roles_remove_assignments(
        self,
        config: SlackAdminRolesRemoveAssignmentsConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Remove role assignments."""
        body = {
            "entity_ids": config.entity_ids,
            "role_id": config.role_id,
            "user_ids": config.user_ids,
        }

        return await self._make_request(
            "POST",
            "admin.roles.removeAssignments",
            credentials,
            json_body=body,
            action_name="remove_role_assignments",
        )

    # --- admin.teams (10) ---

    async def _admin_teams_admins_list(
        self, config: SlackAdminTeamsAdminsListConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List team admins."""
        params = {
            "team_id": config.team_id,
            "limit": config.limit,
        }
        if config.cursor:
            params["cursor"] = config.cursor

        return await self._make_request(
            "GET",
            "admin.teams.admins.list",
            credentials,
            params=params,
            action_name="list_team_admins",
        )

    async def _admin_teams_create(
        self, config: SlackAdminTeamsCreateConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Create a team."""
        body = {
            "team_domain": config.team_domain,
            "team_name": config.team_name,
        }
        if config.team_description:
            body["team_description"] = config.team_description
        if config.team_discoverability:
            body["team_discoverability"] = config.team_discoverability

        return await self._make_request(
            "POST",
            "admin.teams.create",
            credentials,
            json_body=body,
            action_name="create_team",
        )

    async def _admin_teams_list(
        self, config: SlackAdminTeamsListConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List teams."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        return await self._make_request(
            "GET",
            "admin.teams.list",
            credentials,
            params=params,
            action_name="list_teams",
        )

    async def _admin_teams_owners_list(
        self, config: SlackAdminTeamsOwnersListConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List team owners."""
        params = {
            "team_id": config.team_id,
            "limit": config.limit,
        }
        if config.cursor:
            params["cursor"] = config.cursor

        return await self._make_request(
            "GET",
            "admin.teams.owners.list",
            credentials,
            params=params,
            action_name="list_team_owners",
        )

    async def _admin_teams_settings_info(
        self, config: SlackAdminTeamsSettingsInfoConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get team settings info."""
        params = {"team_id": config.team_id}

        return await self._make_request(
            "GET",
            "admin.teams.settings.info",
            credentials,
            params=params,
            action_name="get_team_settings",
        )

    async def _admin_teams_settings_set_default_channels(
        self,
        config: SlackAdminTeamsSettingsSetDefaultChannelsConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Set default channels for team."""
        body = {
            "team_id": config.team_id,
            "channel_ids": config.channel_ids,
        }

        return await self._make_request(
            "POST",
            "admin.teams.settings.setDefaultChannels",
            credentials,
            json_body=body,
            action_name="set_default_channels_for_team",
        )

    async def _admin_teams_settings_set_description(
        self,
        config: SlackAdminTeamsSettingsSetDescriptionConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Set team description."""
        body = {
            "team_id": config.team_id,
            "description": config.description,
        }

        return await self._make_request(
            "POST",
            "admin.teams.settings.setDescription",
            credentials,
            json_body=body,
            action_name="set_team_description",
        )

    async def _admin_teams_settings_set_discoverability(
        self,
        config: SlackAdminTeamsSettingsSetDiscoverabilityConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Set team discoverability."""
        body = {
            "team_id": config.team_id,
            "discoverability": config.discoverability,
        }

        return await self._make_request(
            "POST",
            "admin.teams.settings.setDiscoverability",
            credentials,
            json_body=body,
            action_name="set_team_discoverability",
        )

    async def _admin_teams_settings_set_icon(
        self, config: SlackAdminTeamsSettingsSetIconConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Set team icon."""
        body = {
            "team_id": config.team_id,
            "image_url": config.image_url,
        }

        return await self._make_request(
            "POST",
            "admin.teams.settings.setIcon",
            credentials,
            json_body=body,
            action_name="set_team_icon",
        )

    async def _admin_teams_settings_set_name(
        self, config: SlackAdminTeamsSettingsSetNameConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Set team name."""
        body = {
            "team_id": config.team_id,
            "name": config.name,
        }

        return await self._make_request(
            "POST",
            "admin.teams.settings.setName",
            credentials,
            json_body=body,
            action_name="set_team_name",
        )

    # --- admin.usergroups (4) ---

    async def _admin_usergroups_add_channels(
        self,
        config: SlackAdminUsergroupsAddChannelsConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Add channels to usergroup."""
        body = {
            "channel_ids": config.channel_ids,
            "usergroup_id": config.usergroup_id,
        }
        if config.team_id:
            body["team_id"] = config.team_id

        return await self._make_request(
            "POST",
            "admin.usergroups.addChannels",
            credentials,
            json_body=body,
            action_name="add_channels_to_usergroup",
        )

    async def _admin_usergroups_add_teams(
        self, config: SlackAdminUsergroupsAddTeamsConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Add teams to usergroup."""
        body = {
            "team_ids": config.team_ids,
            "usergroup_id": config.usergroup_id,
            "auto_provision": config.auto_provision,
        }

        return await self._make_request(
            "POST",
            "admin.usergroups.addTeams",
            credentials,
            json_body=body,
            action_name="add_teams_to_usergroup",
        )

    async def _admin_usergroups_list_channels(
        self,
        config: SlackAdminUsergroupsListChannelsConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """List channels in usergroup."""
        params = {
            "usergroup_id": config.usergroup_id,
            "include_num_members": config.include_num_members,
        }
        if config.team_id:
            params["team_id"] = config.team_id

        return await self._make_request(
            "GET",
            "admin.usergroups.listChannels",
            credentials,
            params=params,
            action_name="list_channels_in_usergroup",
        )

    async def _admin_usergroups_remove_channels(
        self,
        config: SlackAdminUsergroupsRemoveChannelsConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Remove channels from usergroup."""
        body = {
            "channel_ids": config.channel_ids,
            "usergroup_id": config.usergroup_id,
        }

        return await self._make_request(
            "POST",
            "admin.usergroups.removeChannels",
            credentials,
            json_body=body,
            action_name="remove_channels_from_usergroup",
        )

    # --- admin.users (17) ---

    async def _admin_users_assign(
        self, config: SlackAdminUsersAssignConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Assign a user to a team."""
        body = {
            "team_id": config.team_id,
            "user_id": config.user_id,
            "is_restricted": config.is_restricted,
            "is_ultra_restricted": config.is_ultra_restricted,
        }
        if config.channel_ids:
            body["channel_ids"] = config.channel_ids

        return await self._make_request(
            "POST",
            "admin.users.assign",
            credentials,
            json_body=body,
            action_name="assign_user_to_team",
        )

    async def _admin_users_get_expiration(
        self, config: SlackAdminUsersGetExpirationConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Get expiration for a user."""
        params = {"user_id": config.user_id}

        return await self._make_request(
            "GET",
            "admin.users.getExpiration",
            credentials,
            params=params,
            action_name="get_user_expiration",
        )

    async def _admin_users_invite(
        self, config: SlackAdminUsersInviteConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Invite a user to a team."""
        body = {
            "channel_ids": config.channel_ids,
            "email": config.email,
            "team_id": config.team_id,
            "is_restricted": config.is_restricted,
            "is_ultra_restricted": config.is_ultra_restricted,
            "resend": config.resend,
        }
        if config.custom_message:
            body["custom_message"] = config.custom_message
        if config.guest_expiration_ts:
            body["guest_expiration_ts"] = config.guest_expiration_ts
        if config.real_name:
            body["real_name"] = config.real_name

        return await self._make_request(
            "POST",
            "admin.users.invite",
            credentials,
            json_body=body,
            action_name="invite_user_to_team",
        )

    async def _admin_users_list(
        self, config: SlackAdminUsersListConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List users in a team."""
        params = {
            "team_id": config.team_id,
            "limit": config.limit,
            "include_deactivated_user_workspaces": config.include_deactivated_user_workspaces,
        }
        if config.cursor:
            params["cursor"] = config.cursor
        if config.is_active is not None:
            params["is_active"] = config.is_active

        return await self._make_request(
            "GET",
            "admin.users.list",
            credentials,
            params=params,
            action_name="list_users_in_team",
        )

    async def _admin_users_remove(
        self, config: SlackAdminUsersRemoveConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Remove a user from a team."""
        body = {
            "team_id": config.team_id,
            "user_id": config.user_id,
        }

        return await self._make_request(
            "POST",
            "admin.users.remove",
            credentials,
            json_body=body,
            action_name="remove_user_from_team",
        )

    async def _admin_users_session_clear_settings(
        self,
        config: SlackAdminUsersSessionClearSettingsConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Clear session settings."""
        body = {"user_ids": config.user_ids}

        return await self._make_request(
            "POST",
            "admin.users.session.clearSettings",
            credentials,
            json_body=body,
            action_name="clear_user_session_settings",
        )

    async def _admin_users_session_get_settings(
        self,
        config: SlackAdminUsersSessionGetSettingsConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Get session settings."""
        body = {"user_ids": config.user_ids}

        return await self._make_request(
            "POST",
            "admin.users.session.getSettings",
            credentials,
            json_body=body,
            action_name="get_user_session_settings",
        )

    async def _admin_users_session_invalidate(
        self,
        config: SlackAdminUsersSessionInvalidateConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Invalidate user session."""
        body = {
            "session_id": config.session_id,
            "team_id": config.team_id,
        }

        return await self._make_request(
            "POST",
            "admin.users.session.invalidate",
            credentials,
            json_body=body,
            action_name="invalidate_user_session",
        )

    async def _admin_users_session_list(
        self, config: SlackAdminUsersSessionListConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """List user sessions."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        if config.team_id:
            params["team_id"] = config.team_id
        if config.user_id:
            params["user_id"] = config.user_id

        return await self._make_request(
            "GET",
            "admin.users.session.list",
            credentials,
            params=params,
            action_name="list_user_sessions",
        )

    async def _admin_users_session_reset(
        self, config: SlackAdminUsersSessionResetConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Reset user session."""
        body = {
            "user_id": config.user_id,
            "mobile_only": config.mobile_only,
            "web_only": config.web_only,
        }

        return await self._make_request(
            "POST",
            "admin.users.session.reset",
            credentials,
            json_body=body,
            action_name="reset_user_session",
        )

    async def _admin_users_session_reset_bulk(
        self,
        config: SlackAdminUsersSessionResetBulkConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Bulk reset user sessions."""
        body = {
            "user_ids": config.user_ids,
            "mobile_only": config.mobile_only,
            "web_only": config.web_only,
        }

        return await self._make_request(
            "POST",
            "admin.users.session.resetBulk",
            credentials,
            json_body=body,
            action_name="bulk_reset_user_sessions",
        )

    async def _admin_users_session_set_settings(
        self,
        config: SlackAdminUsersSessionSetSettingsConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Set session settings."""
        body = {"user_ids": config.user_ids}
        if config.desktop_app_browser_quit is not None:
            body["desktop_app_browser_quit"] = config.desktop_app_browser_quit
        if config.duration:
            body["duration"] = config.duration

        return await self._make_request(
            "POST",
            "admin.users.session.setSettings",
            credentials,
            json_body=body,
            action_name="set_user_session_settings",
        )

    async def _admin_users_set_admin(
        self, config: SlackAdminUsersSetAdminConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Set a user as admin."""
        body = {
            "team_id": config.team_id,
            "user_id": config.user_id,
        }

        return await self._make_request(
            "POST",
            "admin.users.setAdmin",
            credentials,
            json_body=body,
            action_name="set_user_as_admin",
        )

    async def _admin_users_set_expiration(
        self, config: SlackAdminUsersSetExpirationConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Set expiration for a user."""
        body = {
            "expiration_ts": config.expiration_ts,
            "user_id": config.user_id,
        }
        if config.team_id:
            body["team_id"] = config.team_id

        return await self._make_request(
            "POST",
            "admin.users.setExpiration",
            credentials,
            json_body=body,
            action_name="set_user_expiration",
        )

    async def _admin_users_set_owner(
        self, config: SlackAdminUsersSetOwnerConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Set a user as owner."""
        body = {
            "team_id": config.team_id,
            "user_id": config.user_id,
        }

        return await self._make_request(
            "POST",
            "admin.users.setOwner",
            credentials,
            json_body=body,
            action_name="set_user_as_owner",
        )

    async def _admin_users_set_regular(
        self, config: SlackAdminUsersSetRegularConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Set a user as regular."""
        body = {
            "team_id": config.team_id,
            "user_id": config.user_id,
        }

        return await self._make_request(
            "POST",
            "admin.users.setRegular",
            credentials,
            json_body=body,
            action_name="set_user_as_regular",
        )

    async def _admin_users_unsupported_versions_export(
        self,
        config: SlackAdminUsersUnsupportedVersionsExportConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Export unsupported version users."""
        params = {}
        if config.date_end_of_support:
            params["date_end_of_support"] = config.date_end_of_support
        if config.date_sessions_started:
            params["date_sessions_started"] = config.date_sessions_started

        return await self._make_request(
            "GET",
            "admin.users.unsupportedVersions.export",
            credentials,
            params=params,
            action_name="export_unsupported_version_users",
        )

    # --- admin.workflows (7) ---

    async def _admin_workflows_collaborators_add(
        self,
        config: SlackAdminWorkflowsCollaboratorsAddConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Add workflow collaborators."""
        body = {
            "collaborator_ids": config.collaborator_ids,
            "workflow_ids": config.workflow_ids,
        }

        return await self._make_request(
            "POST",
            "admin.workflows.collaborators.add",
            credentials,
            json_body=body,
            action_name="add_workflow_collaborators",
        )

    async def _admin_workflows_collaborators_remove(
        self,
        config: SlackAdminWorkflowsCollaboratorsRemoveConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Remove workflow collaborators."""
        body = {
            "collaborator_ids": config.collaborator_ids,
            "workflow_ids": config.workflow_ids,
        }

        return await self._make_request(
            "POST",
            "admin.workflows.collaborators.remove",
            credentials,
            json_body=body,
            action_name="remove_workflow_collaborators",
        )

    async def _admin_workflows_permissions_lookup(
        self,
        config: SlackAdminWorkflowsPermissionsLookupConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Look up workflow permissions."""
        body = {
            "workflow_ids": config.workflow_ids,
            "max_workflow_triggers": config.max_workflow_triggers,
        }

        return await self._make_request(
            "POST",
            "admin.workflows.permissions.lookup",
            credentials,
            json_body=body,
            action_name="lookup_workflow_permissions",
        )

    async def _admin_workflows_search(
        self, config: SlackAdminWorkflowsSearchConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Search workflows."""
        params = {
            "limit": config.limit,
            "no_collaborators": config.no_collaborators,
            "num_trigger_ids": config.num_trigger_ids,
        }
        if config.app_id:
            params["app_id"] = config.app_id
        if config.collaborator_ids:
            params["collaborator_ids"] = ",".join(config.collaborator_ids)
        if config.cursor:
            params["cursor"] = config.cursor
        if config.query:
            params["query"] = config.query
        if config.sort:
            params["sort"] = config.sort
        if config.sort_dir:
            params["sort_dir"] = config.sort_dir
        if config.source:
            params["source"] = config.source

        return await self._make_request(
            "GET",
            "admin.workflows.search",
            credentials,
            params=params,
            action_name="search_workflows",
        )

    async def _admin_workflows_triggers_types_permissions_lookup(
        self,
        config: SlackAdminWorkflowsTriggersTypesPermissionsLookupConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Look up workflow trigger type permissions."""
        body = {"trigger_type_ids": config.trigger_type_ids}

        return await self._make_request(
            "POST",
            "admin.workflows.triggers.types.permissions.lookup",
            credentials,
            json_body=body,
            action_name="lookup_workflow_trigger_type_permissions",
        )

    async def _admin_workflows_triggers_types_permissions_set(
        self,
        config: SlackAdminWorkflowsTriggersTypesPermissionsSetConfig,
        credentials: SlackCredential,
    ) -> Dict[str, Any]:
        """Set workflow trigger type permissions."""
        body = {
            "trigger_type_id": config.trigger_type_id,
            "visibility": config.visibility,
        }
        if config.user_ids:
            body["user_ids"] = config.user_ids

        return await self._make_request(
            "POST",
            "admin.workflows.triggers.types.permissions.set",
            credentials,
            json_body=body,
            action_name="set_workflow_trigger_type_permissions",
        )

    async def _admin_workflows_unpublish(
        self, config: SlackAdminWorkflowsUnpublishConfig, credentials: SlackCredential
    ) -> Dict[str, Any]:
        """Unpublish a workflow."""
        body = {"workflow_ids": config.workflow_ids}

        return await self._make_request(
            "POST",
            "admin.workflows.unpublish",
            credentials,
            json_body=body,
            action_name="unpublish_workflow",
        )
