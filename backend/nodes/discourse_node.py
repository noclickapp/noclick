"""
Discourse community/forum automation node.

Provides workflow integration with a self-hosted or hosted Discourse instance
(REST/JSON API) for operations including:
- Posts & Topics: create post/topic/PM, get/update/delete topic, set topic
  status, list latest/top topics, list category topics, get/update/delete post,
  post action (like/flag), private messages
- Categories & Tags: list/create/update categories, list tags
- Search: full-text search
- Users: get/create/update user, list users (admin), suspend user (admin),
  send password reset, get notifications
- Groups: list groups, add/remove group members, create invite
- Webhook Trigger: fire when a topic/post/user event occurs

Authentication: Admin API key via two headers `Api-Key` + `Api-Username`,
against a per-instance forum base URL (no central host).
API Base URL: https://{your-forum-domain}
Documentation: https://docs.discourse.org/
"""

import hashlib
import hmac
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import filter_options_by_search
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin

logger = logging.getLogger(__name__)

# Discourse delivers webhooks per *event group*. The webhook-create API takes a
# `web_hook_event_type_ids` array of the numeric group IDs below (empty array =
# wildcard, i.e. all events). The group name is echoed on each delivery in the
# `X-Discourse-Event-Type` header, which we use to filter at runtime.
# IDs/names mirror Discourse's WebHookEventType model (app/models/web_hook_event_type.rb).
DISCOURSE_EVENT_GROUPS: List[Dict[str, Any]] = [
    {"value": "topic", "id": 1, "label": "Topic (created, edited, destroyed, recovered)"},
    {"value": "post", "id": 2, "label": "Post (created, edited, destroyed, recovered)"},
    {"value": "user", "id": 3, "label": "User (created, approved, updated, logged in)"},
    {"value": "group", "id": 4, "label": "Group (created, updated, destroyed)"},
    {"value": "category", "id": 5, "label": "Category (created, updated, destroyed)"},
    {"value": "tag", "id": 6, "label": "Tag (created, updated, destroyed)"},
    {"value": "reviewable", "id": 9, "label": "Reviewable (created, updated)"},
    {"value": "notification", "id": 10, "label": "Notification (created)"},
    {"value": "like", "id": 15, "label": "Like (created)"},
    {"value": "user_promoted", "id": 16, "label": "User Promoted"},
]

# Wildcard sentinel — subscribe to every event (Discourse: empty event-type-ids).
DISCOURSE_ALL_EVENTS = "*"

_DISCOURSE_EVENT_NAME_TO_ID = {g["value"]: g["id"] for g in DISCOURSE_EVENT_GROUPS}


# ============================================================================
# Credential Schema
# ============================================================================


class DiscourseApiKeyCredential(BaseModel):
    """Admin API key credential for a Discourse instance.

    Discourse has no central API host: every install exposes its own REST API at
    its own domain, and authenticates with two headers together — `Api-Key` and
    `Api-Username` (the latter selects which user the request acts as).
    """

    credential_type: Literal["discourse_api_key"] = Field(
        "discourse_api_key", json_schema_extra={"ui:hidden": True}
    )
    site_url: str = Field(
        ...,
        title="Forum URL",
        description="Your Discourse site base URL, e.g. https://meta.discourse.org (no trailing /admin)",
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Admin API key from Admin -> API -> Keys (/admin/api/keys)",
        json_schema_extra={"ui:widget": "password"},
    )
    api_username: str = Field(
        "system",
        title="API Username",
        description="Username the request acts as. Use 'system' or an admin for full access.",
    )

    model_config = ConfigDict(
        title="Discourse API Key",
        json_schema_extra={"x-credential-url": "https://meta.discourse.org/t/create-and-configure-an-api-key/230124"}
    )


DiscourseCredential = DiscourseApiKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class DiscourseCreatePostConfig(BaseModel):
    """Create a topic (with title), a reply (with topic_id), or a PM."""

    operation: Literal["create_post"] = Field(
        "create_post",
        json_schema_extra={
            "const": "create_post",
            "ui:hidden": True,
            "x-category": "Posts & Topics",
            "x-is-trigger": False,
            "x-display-name": "Create Post / Topic / PM",
        },
        title="Create Post / Topic / PM",
    )
    raw: str = Field(
        ...,
        title="Body",
        description="The raw markdown content of the post",
        json_schema_extra={"ui:widget": "textarea"},
    )
    title: Optional[str] = Field(
        None,
        title="Title",
        description="Topic title. Provide to create a NEW topic (omit for a reply).",
    )
    topic_id: Optional[str] = Field(
        None,
        title="Topic ID",
        description="Reply to this topic. Provide to add a reply (omit when creating a new topic).",
    )
    category: Optional[str] = Field(
        None,
        title="Category",
        description="Category ID to post the new topic into",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "category",
                "placeholder": "Select a category...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste category ID",
            }
        },
    )
    target_recipients: Optional[str] = Field(
        None,
        title="PM Recipients",
        description="Comma-separated usernames. Provide to send a private message.",
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated tags for the new topic"
    )


class DiscourseGetTopicConfig(BaseModel):
    """Retrieve a topic and its posts by topic id."""

    operation: Literal["get_topic"] = Field(
        "get_topic",
        json_schema_extra={
            "const": "get_topic",
            "ui:hidden": True,
            "x-category": "Posts & Topics",
            "x-is-trigger": False,
            "x-display-name": "Get Topic",
        },
        title="Get Topic",
    )
    topic_id: str = Field(..., title="Topic ID", description="The id of the topic to retrieve")


class DiscourseUpdateTopicConfig(BaseModel):
    """Update a topic's title, category, or tags."""

    operation: Literal["update_topic"] = Field(
        "update_topic",
        json_schema_extra={
            "const": "update_topic",
            "ui:hidden": True,
            "x-category": "Posts & Topics",
            "x-is-trigger": False,
            "x-display-name": "Update Topic",
        },
        title="Update Topic",
    )
    topic_id: str = Field(..., title="Topic ID", description="The id of the topic to update")
    title: Optional[str] = Field(None, title="Title", description="New topic title")
    category_id: Optional[str] = Field(
        None, title="Category ID", description="Move the topic to this category id"
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated tags to set on the topic"
    )


class DiscourseDeleteTopicConfig(BaseModel):
    """Remove (soft-delete) a topic."""

    operation: Literal["delete_topic"] = Field(
        "delete_topic",
        json_schema_extra={
            "const": "delete_topic",
            "ui:hidden": True,
            "x-category": "Posts & Topics",
            "x-is-trigger": False,
            "x-display-name": "Delete Topic",
        },
        title="Delete Topic",
    )
    topic_id: str = Field(..., title="Topic ID", description="The id of the topic to delete")


class DiscourseSetTopicStatusConfig(BaseModel):
    """Change a topic's status (close, pin, archive, visible)."""

    operation: Literal["set_topic_status"] = Field(
        "set_topic_status",
        json_schema_extra={
            "const": "set_topic_status",
            "ui:hidden": True,
            "x-category": "Posts & Topics",
            "x-is-trigger": False,
            "x-display-name": "Set Topic Status",
        },
        title="Set Topic Status",
    )
    topic_id: str = Field(..., title="Topic ID", description="The id of the topic to update")
    status: str = Field(
        ...,
        title="Status",
        description="Which status flag to change",
        json_schema_extra={
            "enum": ["closed", "pinned", "pinned_globally", "archived", "visible"],
            "enumNames": ["Closed", "Pinned", "Pinned Globally", "Archived", "Visible"],
            "x-enum-searchable": True,
        },
    )
    enabled: str = Field(
        "true",
        title="Enabled",
        description="Enable (true) or disable (false) the chosen status",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class DiscourseGetLatestTopicsConfig(BaseModel):
    """List the most recent topics."""

    operation: Literal["get_latest_topics"] = Field(
        "get_latest_topics",
        json_schema_extra={
            "const": "get_latest_topics",
            "ui:hidden": True,
            "x-category": "Posts & Topics",
            "x-is-trigger": False,
            "x-display-name": "Get Latest Topics",
        },
        title="Get Latest Topics",
    )
    page: Optional[str] = Field(
        None, title="Page", description="Page number for pagination (0-based)"
    )


class DiscourseGetTopTopicsConfig(BaseModel):
    """List top topics filtered by a period."""

    operation: Literal["get_top_topics"] = Field(
        "get_top_topics",
        json_schema_extra={
            "const": "get_top_topics",
            "ui:hidden": True,
            "x-category": "Posts & Topics",
            "x-is-trigger": False,
            "x-display-name": "Get Top Topics",
        },
        title="Get Top Topics",
    )
    period: str = Field(
        "weekly",
        title="Period",
        description="Time window for top topics",
        json_schema_extra={
            "enum": ["daily", "weekly", "monthly", "quarterly", "yearly", "all"],
            "enumNames": ["Daily", "Weekly", "Monthly", "Quarterly", "Yearly", "All Time"],
            "x-enum-searchable": True,
        },
    )


class DiscourseListCategoryTopicsConfig(BaseModel):
    """List topics within a specific category."""

    operation: Literal["list_category_topics"] = Field(
        "list_category_topics",
        json_schema_extra={
            "const": "list_category_topics",
            "ui:hidden": True,
            "x-category": "Posts & Topics",
            "x-is-trigger": False,
            "x-display-name": "List Category Topics",
        },
        title="List Category Topics",
    )
    category_slug: str = Field(..., title="Category Slug", description="The category slug, e.g. 'support'")
    category_id: str = Field(
        ...,
        title="Category ID",
        description="The category id",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "category_id",
                "placeholder": "Select a category...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste category ID",
            }
        },
    )


class DiscourseGetPostConfig(BaseModel):
    """Retrieve one post by id."""

    operation: Literal["get_post"] = Field(
        "get_post",
        json_schema_extra={
            "const": "get_post",
            "ui:hidden": True,
            "x-category": "Posts & Topics",
            "x-is-trigger": False,
            "x-display-name": "Get Post",
        },
        title="Get Post",
    )
    post_id: str = Field(..., title="Post ID", description="The id of the post to retrieve")


class DiscourseUpdatePostConfig(BaseModel):
    """Edit the raw content of a post."""

    operation: Literal["update_post"] = Field(
        "update_post",
        json_schema_extra={
            "const": "update_post",
            "ui:hidden": True,
            "x-category": "Posts & Topics",
            "x-is-trigger": False,
            "x-display-name": "Update Post",
        },
        title="Update Post",
    )
    post_id: str = Field(..., title="Post ID", description="The id of the post to edit")
    raw: str = Field(
        ...,
        title="Body",
        description="New raw markdown content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    edit_reason: Optional[str] = Field(
        None, title="Edit Reason", description="Optional reason for the edit"
    )


class DiscourseDeletePostConfig(BaseModel):
    """Delete a single post."""

    operation: Literal["delete_post"] = Field(
        "delete_post",
        json_schema_extra={
            "const": "delete_post",
            "ui:hidden": True,
            "x-category": "Posts & Topics",
            "x-is-trigger": False,
            "x-display-name": "Delete Post",
        },
        title="Delete Post",
    )
    post_id: str = Field(..., title="Post ID", description="The id of the post to delete")


class DiscoursePostActionConfig(BaseModel):
    """Apply a post action such as like, flag, or bookmark."""

    operation: Literal["post_action"] = Field(
        "post_action",
        json_schema_extra={
            "const": "post_action",
            "ui:hidden": True,
            "x-category": "Posts & Topics",
            "x-is-trigger": False,
            "x-display-name": "Post Action (Like/Flag)",
        },
        title="Post Action (Like/Flag)",
    )
    post_id: str = Field(..., title="Post ID", description="The id of the post to act on")
    post_action_type_id: str = Field(
        "2",
        title="Action",
        description="Action type",
        json_schema_extra={
            "enum": ["2", "3", "4", "8", "6", "7"],
            "enumNames": ["Like", "Off-Topic Flag", "Inappropriate Flag", "Spam Flag", "Notify User", "Notify Moderators"],
            "x-enum-searchable": True,
        },
    )


class DiscourseListCategoriesConfig(BaseModel):
    """Retrieve the list of categories."""

    operation: Literal["list_categories"] = Field(
        "list_categories",
        json_schema_extra={
            "const": "list_categories",
            "ui:hidden": True,
            "x-category": "Categories & Tags",
            "x-is-trigger": False,
            "x-display-name": "List Categories",
        },
        title="List Categories",
    )


class DiscourseCreateCategoryConfig(BaseModel):
    """Create a new category."""

    operation: Literal["create_category"] = Field(
        "create_category",
        json_schema_extra={
            "const": "create_category",
            "ui:hidden": True,
            "x-category": "Categories & Tags",
            "x-is-trigger": False,
            "x-display-name": "Create Category",
        },
        title="Create Category",
    )
    name: str = Field(..., title="Name", description="The category name")
    color: str = Field("0088CC", title="Color", description="Hex color (no #), e.g. 0088CC")
    text_color: str = Field("FFFFFF", title="Text Color", description="Hex text color (no #)")


class DiscourseUpdateCategoryConfig(BaseModel):
    """Update a category's settings."""

    operation: Literal["update_category"] = Field(
        "update_category",
        json_schema_extra={
            "const": "update_category",
            "ui:hidden": True,
            "x-category": "Categories & Tags",
            "x-is-trigger": False,
            "x-display-name": "Update Category",
        },
        title="Update Category",
    )
    category_id: str = Field(
        ...,
        title="Category ID",
        description="The category id to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "category_id",
                "placeholder": "Select a category...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste category ID",
            }
        },
    )
    name: Optional[str] = Field(None, title="Name", description="New category name")
    color: Optional[str] = Field(None, title="Color", description="New hex color (no #)")
    text_color: Optional[str] = Field(None, title="Text Color", description="New hex text color (no #)")


class DiscourseSearchConfig(BaseModel):
    """Full-text search across topics, posts, and users."""

    operation: Literal["search"] = Field(
        "search",
        json_schema_extra={
            "const": "search",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search",
        },
        title="Search",
    )
    query: str = Field(..., title="Query", description="The search term")


class DiscourseGetUserConfig(BaseModel):
    """Fetch a single user's profile by username."""

    operation: Literal["get_user"] = Field(
        "get_user",
        json_schema_extra={
            "const": "get_user",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Get User",
        },
        title="Get User",
    )
    username: str = Field(..., title="Username", description="The username to fetch")


class DiscourseCreateUserConfig(BaseModel):
    """Create a new user account."""

    operation: Literal["create_user"] = Field(
        "create_user",
        json_schema_extra={
            "const": "create_user",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Create User",
        },
        title="Create User",
    )
    name: str = Field(..., title="Name", description="The user's full name")
    email: str = Field(..., title="Email", description="The user's email address")
    username: str = Field(..., title="Username", description="The desired username")
    password: str = Field(
        ...,
        title="Password",
        description="The user's password",
        json_schema_extra={"ui:widget": "password"},
    )
    active: str = Field(
        "true",
        title="Active",
        description="Mark the account active immediately",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    approved: str = Field(
        "true",
        title="Approved",
        description="Approve the account immediately",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class DiscourseUpdateUserConfig(BaseModel):
    """Update a user's profile fields."""

    operation: Literal["update_user"] = Field(
        "update_user",
        json_schema_extra={
            "const": "update_user",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Update User",
        },
        title="Update User",
    )
    username: str = Field(..., title="Username", description="The username to update")
    name: Optional[str] = Field(None, title="Name", description="New full name")
    title: Optional[str] = Field(None, title="Title", description="New user title")
    bio_raw: Optional[str] = Field(
        None,
        title="Bio",
        description="New bio (raw markdown)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class DiscourseListUsersConfig(BaseModel):
    """List users filtered by a flag (admin)."""

    operation: Literal["list_users"] = Field(
        "list_users",
        json_schema_extra={
            "const": "list_users",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "List Users (Admin)",
        },
        title="List Users (Admin)",
    )
    flag: str = Field(
        "active",
        title="Filter",
        description="Which users to list",
        json_schema_extra={
            "enum": ["active", "new", "staff", "suspended", "blocked", "suspect"],
            "enumNames": ["Active", "New", "Staff", "Suspended", "Blocked", "Suspect"],
            "x-enum-searchable": True,
        },
    )
    page: Optional[str] = Field(
        None, title="Page", description="Page number for pagination (1-based)"
    )


class DiscourseSuspendUserConfig(BaseModel):
    """Suspend a user with a reason and until-date (admin)."""

    operation: Literal["suspend_user"] = Field(
        "suspend_user",
        json_schema_extra={
            "const": "suspend_user",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Suspend User (Admin)",
        },
        title="Suspend User (Admin)",
    )
    user_id: str = Field(..., title="User ID", description="The numeric user id to suspend")
    suspend_until: str = Field(
        ...,
        title="Suspend Until",
        description="ISO 8601 date the suspension ends, e.g. 2026-12-31T00:00:00Z",
    )
    reason: str = Field(..., title="Reason", description="Reason shown to the user")


class DiscourseSendPasswordResetConfig(BaseModel):
    """Trigger a password-reset email for a user."""

    operation: Literal["send_password_reset"] = Field(
        "send_password_reset",
        json_schema_extra={
            "const": "send_password_reset",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Send Password Reset",
        },
        title="Send Password Reset",
    )
    login: str = Field(..., title="Username or Email", description="The username or email to reset")


class DiscourseGetNotificationsConfig(BaseModel):
    """Get the current user's notifications."""

    operation: Literal["get_notifications"] = Field(
        "get_notifications",
        json_schema_extra={
            "const": "get_notifications",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Get Notifications",
        },
        title="Get Notifications",
    )


class DiscourseListGroupsConfig(BaseModel):
    """List all groups."""

    operation: Literal["list_groups"] = Field(
        "list_groups",
        json_schema_extra={
            "const": "list_groups",
            "ui:hidden": True,
            "x-category": "Groups",
            "x-is-trigger": False,
            "x-display-name": "List Groups",
        },
        title="List Groups",
    )


class DiscourseAddGroupMembersConfig(BaseModel):
    """Add one or more users to a group."""

    operation: Literal["add_group_members"] = Field(
        "add_group_members",
        json_schema_extra={
            "const": "add_group_members",
            "ui:hidden": True,
            "x-category": "Groups",
            "x-is-trigger": False,
            "x-display-name": "Add Group Members",
        },
        title="Add Group Members",
    )
    group_id: str = Field(..., title="Group ID", description="The numeric group id")
    usernames: str = Field(
        ..., title="Usernames", description="Comma-separated usernames to add"
    )


class DiscourseRemoveGroupMembersConfig(BaseModel):
    """Remove users from a group."""

    operation: Literal["remove_group_members"] = Field(
        "remove_group_members",
        json_schema_extra={
            "const": "remove_group_members",
            "ui:hidden": True,
            "x-category": "Groups",
            "x-is-trigger": False,
            "x-display-name": "Remove Group Members",
        },
        title="Remove Group Members",
    )
    group_id: str = Field(..., title="Group ID", description="The numeric group id")
    usernames: str = Field(
        ..., title="Usernames", description="Comma-separated usernames to remove"
    )


class DiscourseCreateInviteConfig(BaseModel):
    """Generate an invite link or email invite."""

    operation: Literal["create_invite"] = Field(
        "create_invite",
        json_schema_extra={
            "const": "create_invite",
            "ui:hidden": True,
            "x-category": "Groups",
            "x-is-trigger": False,
            "x-display-name": "Create Invite",
        },
        title="Create Invite",
    )
    email: Optional[str] = Field(
        None, title="Email", description="Email to invite. Omit for a reusable link invite."
    )
    group_ids: Optional[str] = Field(
        None, title="Group IDs", description="Comma-separated group ids to add the invitee to"
    )
    custom_message: Optional[str] = Field(
        None,
        title="Custom Message",
        description="Message included in the invite",
        json_schema_extra={"ui:widget": "textarea"},
    )


class DiscourseListTagsConfig(BaseModel):
    """Get the list of tags."""

    operation: Literal["list_tags"] = Field(
        "list_tags",
        json_schema_extra={
            "const": "list_tags",
            "ui:hidden": True,
            "x-category": "Categories & Tags",
            "x-is-trigger": False,
            "x-display-name": "List Tags",
        },
        title="List Tags",
    )


class DiscourseGetPrivateMessagesConfig(BaseModel):
    """Get private messages received by a user."""

    operation: Literal["get_private_messages"] = Field(
        "get_private_messages",
        json_schema_extra={
            "const": "get_private_messages",
            "ui:hidden": True,
            "x-category": "Posts & Topics",
            "x-is-trigger": False,
            "x-display-name": "Get Private Messages",
        },
        title="Get Private Messages",
    )
    username: str = Field(..., title="Username", description="The username whose PMs to fetch")


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class DiscourseTriggerConfig(BaseModel):
    """Fire the workflow when a Discourse topic/post/user event occurs."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_event"] = Field(
        "on_event",
        json_schema_extra={
            "const": "on_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Forum Event",
        },
        title="On Forum Event",
    )
    event_types: str = Field(
        DISCOURSE_ALL_EVENTS,
        title="Event Type",
        description=(
            "Which Discourse event group fires this workflow. The webhook only "
            "subscribes to the chosen group (Discourse filters server-side), and "
            "deliveries are re-checked at runtime against the X-Discourse-Event-Type "
            "header. Choose 'All Events' to fire on every event group.\n"
            "- All Events: every event Discourse emits\n"
            "- Topic: topic_created, topic_edited, topic_destroyed, topic_recovered\n"
            "- Post: post_created, post_edited, post_destroyed, post_recovered\n"
            "- User: user_created, user_approved, user_updated, user_logged_in\n"
            "- Group / Category / Tag: created, updated, destroyed for each\n"
            "- Reviewable / Notification / Like / User Promoted: their respective events"
        ),
        json_schema_extra={
            "enum": [DISCOURSE_ALL_EVENTS] + [g["value"] for g in DISCOURSE_EVENT_GROUPS],
            "enumNames": ["All Events"] + [g["label"] for g in DISCOURSE_EVENT_GROUPS],
            "x-enum-searchable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Discourse posts forum events here. Registered automatically when you connect credentials.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
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


# ============================================================================
# Discriminated Union
# ============================================================================


DiscourseConfig = Annotated[
    Union[
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
    ],
    Discriminator("operation"),
]


class DiscourseNodeConfig(NodeConfig[DiscourseConfig, DiscourseCredential]):
    """Full configuration for the Discourse node including credentials."""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _selected_event_groups(config: Dict[str, Any]) -> List[str]:
    """Resolve the configured ``event_types`` into a list of event-group names.

    Accepts a single value or a comma-separated list. The wildcard ("*") or an
    empty/missing value means "all groups" and resolves to ``[]`` (Discourse's
    empty ``web_hook_event_type_ids`` array subscribes to every event).
    """
    raw = (config or {}).get("event_types")
    groups = _comma_list(raw) if isinstance(raw, str) else (raw or None)
    if not groups or DISCOURSE_ALL_EVENTS in groups:
        return []
    return [g for g in groups if g in _DISCOURSE_EVENT_NAME_TO_ID]


def _event_type_ids_for(groups: List[str]) -> List[int]:
    """Map event-group names to Discourse numeric ``web_hook_event_type_ids``."""
    return [_DISCOURSE_EVENT_NAME_TO_ID[g] for g in groups if g in _DISCOURSE_EVENT_NAME_TO_ID]


async def _discourse_request(
    site_url: str,
    api_key: str,
    api_username: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    data_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Discourse request and return a structured result.

    Discourse authenticates with two headers (`Api-Key` + `Api-Username`) against
    a per-instance base URL; `Accept: application/json` is sent so the .json
    suffix is not required and "more" pagination URLs can be followed.
    """
    base = site_url.rstrip("/")
    url = f"{base}{endpoint}"
    headers = {
        "Api-Key": api_key,
        "Api-Username": api_username,
        "Accept": "application/json",
    }
    if json_body is not None:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if data_body is not None:
        data_body = {k: v for k, v in data_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
                data=data_body,
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    errors = err.get("errors") if isinstance(err, dict) else None
                    if isinstance(errors, list) and errors:
                        message = "; ".join(str(e) for e in errors)
                    else:
                        message = err.get("error", err.get("message", str(err))) if isinstance(err, dict) else str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[DiscourseNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204 or not response.content:
                data: Any = {"success": True}
            else:
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}
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
            logger.error(f"[DiscourseNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


class DiscourseNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Discourse community/forum automation node."""

    integration_type = "automation-discourse"

    # The operation retains the provider's error envelope, so an invalid API
    # key cannot appear connected merely because the category picker is empty.
    connection_evidence = ConnectionEvidence(
        operation="list_categories",
        noun="categories",
    )

    edit_examples = [
        "Create a new topic in the announcements category",
        "Post a reply to a topic",
        "Search the forum for posts about a keyword",
        "Suspend a user who violated the rules",
        "Trigger a workflow whenever a new topic is created",
    ]

    @classmethod
    def get_config_model(cls):
        return DiscourseNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (categories)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if field_name not in ("category", "category_id"):
            return []
        credential = credential_data or {}
        if not credential.get("site_url") or not credential.get("api_key"):
            return []
        result = await _discourse_request(
            credential.get("site_url"),
            credential.get("api_key"),
            credential.get("api_username", "system"),
            "GET",
            "/categories.json",
            action_name="list_categories",
        )
        if result.get("status") != "success":
            return []
        data = result.get("data") or {}
        categories = []
        if isinstance(data, dict):
            categories = (data.get("category_list") or {}).get("categories") or []
        options = []
        for cat in categories:
            if not isinstance(cat, dict):
                continue
            cat_id = cat.get("id")
            name = cat.get("name") or f"Category {cat_id}"
            if cat_id is not None:
                options.append({"label": str(name), "value": str(cat_id)})
        return filter_options_by_search(options, search)

    # ------------------------------------------------------------------
    # Webhook trigger registration
    # ------------------------------------------------------------------
    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        site_url = credential.get("site_url")
        api_key = credential.get("api_key")
        api_username = credential.get("api_username", "system")
        if not site_url or not api_key:
            raise ValueError("A Discourse site URL and API key are required to register the trigger")
        secret = hashlib.sha256(f"{node_id}:{webhook_url}".encode()).hexdigest()
        # Subscribe only to the chosen event groups (empty array = all events).
        event_type_ids = _event_type_ids_for(_selected_event_groups(config))
        result = await _discourse_request(
            site_url,
            api_key,
            api_username,
            "POST",
            "/admin/api/web_hooks.json",
            json_body={
                "web_hook": {
                    "payload_url": webhook_url,
                    "content_type": 1,
                    "secret": secret,
                    "wildcard_web_hook": False,
                    "verify_certificate": True,
                    "active": True,
                    "web_hook_event_type_ids": event_type_ids,
                    "group_ids": [],
                    "tag_names": [],
                }
            },
            action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"Discourse webhook registration failed: {result.get('error')}")
        data = result.get("data") or {}
        web_hook = data.get("web_hook") if isinstance(data, dict) else None
        external_id = web_hook.get("id") if isinstance(web_hook, dict) else None
        return {
            "external_webhook_id": str(external_id) if external_id else None,
            "signing_secret": secret,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        site_url = (credential or {}).get("site_url")
        api_key = (credential or {}).get("api_key")
        api_username = (credential or {}).get("api_username", "system")
        if not external_id or not site_url or not api_key:
            return
        await _discourse_request(
            site_url,
            api_key,
            api_username,
            "DELETE",
            f"/admin/api/web_hooks/{external_id}.json",
            action_name="unregister_webhook",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored — accept (trigger not yet armed)
        sent = headers.get("x-discourse-event-signature")
        if not sent:
            return False
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sent)

    @classmethod
    def filter_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> bool:
        """Skip deliveries whose event group isn't selected.

        Belt-and-suspenders: Discourse already filters server-side via
        ``web_hook_event_type_ids``, but a webhook created before the selection
        changed (or registered wildcard) can still deliver other groups. The
        delivered group is in the ``X-Discourse-Event-Type`` header, surfaced on
        ``payload["_webhook"]["headers"]``. Empty selection ("All Events") always
        passes; the test/ping delivery (no event-type header) also passes.
        """
        selected = _selected_event_groups(config)
        if not selected:
            return True
        headers = ((payload or {}).get("_webhook") or {}).get("headers") or {}
        event_type = next(
            (v for k, v in headers.items() if k.lower() == "x-discourse-event-type"),
            None,
        )
        if not event_type:
            return True
        return str(event_type).strip().lower() in selected

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, DiscourseNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, DiscourseTriggerConfig):
            return {
                "status": "success",
                "action": "on_event",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "event_types": op.event_types,
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Discourse site URL and API key.")
        site_url = credentials.site_url
        api_key = credentials.api_key
        api_username = credentials.api_username

        handlers = {
            "create_post": self._create_post,
            "get_topic": self._get_topic,
            "update_topic": self._update_topic,
            "delete_topic": self._delete_topic,
            "set_topic_status": self._set_topic_status,
            "get_latest_topics": self._get_latest_topics,
            "get_top_topics": self._get_top_topics,
            "list_category_topics": self._list_category_topics,
            "get_post": self._get_post,
            "update_post": self._update_post,
            "delete_post": self._delete_post,
            "post_action": self._post_action,
            "list_categories": self._list_categories,
            "create_category": self._create_category,
            "update_category": self._update_category,
            "search": self._search,
            "get_user": self._get_user,
            "create_user": self._create_user,
            "update_user": self._update_user,
            "list_users": self._list_users,
            "suspend_user": self._suspend_user,
            "send_password_reset": self._send_password_reset,
            "get_notifications": self._get_notifications,
            "list_groups": self._list_groups,
            "add_group_members": self._add_group_members,
            "remove_group_members": self._remove_group_members,
            "create_invite": self._create_invite,
            "list_tags": self._list_tags,
            "get_private_messages": self._get_private_messages,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, site_url, api_key, api_username)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    async def _create_post(self, c: DiscourseCreatePostConfig, site_url, api_key, api_username):
        body: Dict[str, Any] = {"raw": c.raw, "title": c.title}
        if c.topic_id:
            body["topic_id"] = int(c.topic_id)
        if c.category:
            body["category"] = int(c.category)
        recipients = _comma_list(c.target_recipients)
        if recipients:
            body["target_recipients"] = ",".join(recipients)
            body["archetype"] = "private_message"
        tags = _comma_list(c.tags)
        if tags:
            body["tags"] = tags
        return await _discourse_request(
            site_url, api_key, api_username, "POST", "/posts.json",
            json_body=body, action_name="create_post"
        )

    async def _get_topic(self, c: DiscourseGetTopicConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "GET", f"/t/{c.topic_id}.json",
            action_name="get_topic"
        )

    async def _update_topic(self, c: DiscourseUpdateTopicConfig, site_url, api_key, api_username):
        body: Dict[str, Any] = {"title": c.title, "category_id": c.category_id}
        tags = _comma_list(c.tags)
        if tags:
            body["tags"] = tags
        return await _discourse_request(
            site_url, api_key, api_username, "PUT", f"/t/-/{c.topic_id}.json",
            json_body=body, action_name="update_topic"
        )

    async def _delete_topic(self, c: DiscourseDeleteTopicConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "DELETE", f"/t/{c.topic_id}.json",
            action_name="delete_topic"
        )

    async def _set_topic_status(self, c: DiscourseSetTopicStatusConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "PUT", f"/t/{c.topic_id}/status.json",
            json_body={"status": c.status, "enabled": c.enabled},
            action_name="set_topic_status"
        )

    async def _get_latest_topics(self, c: DiscourseGetLatestTopicsConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "GET", "/latest.json",
            params={"page": c.page}, action_name="get_latest_topics"
        )

    async def _get_top_topics(self, c: DiscourseGetTopTopicsConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "GET", "/top.json",
            params={"period": c.period}, action_name="get_top_topics"
        )

    async def _list_category_topics(self, c: DiscourseListCategoryTopicsConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "GET", f"/c/{c.category_slug}/{c.category_id}.json",
            action_name="list_category_topics"
        )

    async def _get_post(self, c: DiscourseGetPostConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "GET", f"/posts/{c.post_id}.json",
            action_name="get_post"
        )

    async def _update_post(self, c: DiscourseUpdatePostConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "PUT", f"/posts/{c.post_id}.json",
            json_body={"post": {
                "raw": c.raw,
                **({"edit_reason": c.edit_reason} if c.edit_reason is not None else {}),
            }},
            action_name="update_post"
        )

    async def _delete_post(self, c: DiscourseDeletePostConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "DELETE", f"/posts/{c.post_id}.json",
            action_name="delete_post"
        )

    async def _post_action(self, c: DiscoursePostActionConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "POST", "/post_actions.json",
            json_body={"id": int(c.post_id), "post_action_type_id": int(c.post_action_type_id), "flag_topic": False},
            action_name="post_action"
        )

    async def _list_categories(self, c: DiscourseListCategoriesConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "GET", "/categories.json",
            action_name="list_categories"
        )

    async def _create_category(self, c: DiscourseCreateCategoryConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "POST", "/categories.json",
            json_body={"name": c.name, "color": c.color, "text_color": c.text_color},
            action_name="create_category"
        )

    async def _update_category(self, c: DiscourseUpdateCategoryConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "PUT", f"/categories/{c.category_id}.json",
            json_body={"name": c.name, "color": c.color, "text_color": c.text_color},
            action_name="update_category"
        )

    async def _search(self, c: DiscourseSearchConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "GET", "/search.json",
            params={"q": c.query}, action_name="search"
        )

    async def _get_user(self, c: DiscourseGetUserConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "GET", f"/u/{c.username}.json",
            action_name="get_user"
        )

    async def _create_user(self, c: DiscourseCreateUserConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "POST", "/users.json",
            json_body={
                "name": c.name,
                "email": c.email,
                "username": c.username,
                "password": c.password,
                "active": c.active == "true",
                "approved": c.approved == "true",
            },
            action_name="create_user"
        )

    async def _update_user(self, c: DiscourseUpdateUserConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "PUT", f"/u/{c.username}.json",
            json_body={"name": c.name, "title": c.title, "bio_raw": c.bio_raw},
            action_name="update_user"
        )

    async def _list_users(self, c: DiscourseListUsersConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "GET", f"/admin/users/list/{c.flag}.json",
            params={"page": c.page}, action_name="list_users"
        )

    async def _suspend_user(self, c: DiscourseSuspendUserConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "PUT", f"/admin/users/{c.user_id}/suspend.json",
            json_body={"suspend_until": c.suspend_until, "reason": c.reason},
            action_name="suspend_user"
        )

    async def _send_password_reset(self, c: DiscourseSendPasswordResetConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "POST", "/session/forgot_password.json",
            json_body={"login": c.login}, action_name="send_password_reset"
        )

    async def _get_notifications(self, c: DiscourseGetNotificationsConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "GET", "/notifications.json",
            action_name="get_notifications"
        )

    async def _list_groups(self, c: DiscourseListGroupsConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "GET", "/groups.json",
            action_name="list_groups"
        )

    async def _add_group_members(self, c: DiscourseAddGroupMembersConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "PUT", f"/groups/{c.group_id}/members.json",
            json_body={"usernames": ",".join(_comma_list(c.usernames) or [])},
            action_name="add_group_members"
        )

    async def _remove_group_members(self, c: DiscourseRemoveGroupMembersConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "DELETE", f"/groups/{c.group_id}/members.json",
            json_body={"usernames": ",".join(_comma_list(c.usernames) or [])},
            action_name="remove_group_members"
        )

    async def _create_invite(self, c: DiscourseCreateInviteConfig, site_url, api_key, api_username):
        body: Dict[str, Any] = {"email": c.email, "custom_message": c.custom_message}
        group_ids = _comma_list(c.group_ids)
        if group_ids:
            body["group_ids"] = ",".join(group_ids)
        return await _discourse_request(
            site_url, api_key, api_username, "POST", "/invites.json",
            json_body=body, action_name="create_invite"
        )

    async def _list_tags(self, c: DiscourseListTagsConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "GET", "/tags.json",
            action_name="list_tags"
        )

    async def _get_private_messages(self, c: DiscourseGetPrivateMessagesConfig, site_url, api_key, api_username):
        return await _discourse_request(
            site_url, api_key, api_username, "GET", f"/topics/private-messages/{c.username}.json",
            action_name="get_private_messages"
        )
