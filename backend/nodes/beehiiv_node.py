"""
beehiiv newsletter automation node.

Provides workflow integration with beehiiv (v2 REST API) for operations including:
- Publications: list, get
- Subscriptions: list, create, get by email, get by id, update, delete, bulk create, add tag
- Posts: list, get, create, update, delete, aggregate stats
- Segments: list, get, list subscribers
- Custom Fields: list, create
- Automations: list, add subscriber to journey
- Tiers / Referral program: list / get
- Webhooks: list, create, delete
- Newsletter lists / Polls: list
- Webhook Trigger: fire when a beehiiv event occurs (new subscriber, post sent, etc.)

Authentication: API Key (Bearer token)
API Base URL: https://api.beehiiv.com/v2
Documentation: https://developers.beehiiv.com
"""

import hashlib
import hmac
import json
import logging
import time
from typing import ClassVar, Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin

logger = logging.getLogger(__name__)

BEEHIIV_API_BASE = "https://api.beehiiv.com/v2"

# Event types the webhook trigger subscribes to (full set from the spec).
BEEHIIV_TRIGGER_EVENTS = [
    "post.sent",
    "post.updated",
    "post.scheduled",
    "subscription.created",
    "subscription.confirmed",
    "subscription.upgraded",
    "subscription.downgraded",
    "subscription.paused",
    "subscription.resumed",
    "subscription.deleted",
    "subscription.tier.created",
    "subscription.tier.deleted",
    "subscription.tier.paused",
    "subscription.tier.resumed",
    "survey.response_submitted",
    "newsletter_list_subscription.subscribed",
    "newsletter_list_subscription.unsubscribed",
    "newsletter_list_subscription.paused",
    "newsletter_list_subscription.resumed",
]


# A publication picker shared across operations; almost every endpoint is
# publication-scoped so each op exposes the same dynamic dropdown.
def _publication_field(required: bool = True) -> Any:
    extra = {
        "x-dynamic-options": {
            "field_name": "publication_id",
            "placeholder": "Select a publication...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste publication ID (pub_...)",
        },
        "x-resource-type": "beehiiv_publication",
    }
    return Field(
        ... if required else None,
        title="Publication",
        description="The beehiiv publication (pub_...) to operate on",
        json_schema_extra=extra,
    )


# Publication-scoped resource pickers. Each lists its resource under the
# publication already chosen on the same operation (depends_on publication_id),
# so the user picks from a live list instead of pasting a prefixed ID.
def _scoped_field(
    *,
    field_name: str,
    title: str,
    description: str,
    placeholder: str,
    custom_placeholder: str,
    resource_type: Optional[str] = None,
) -> Any:
    extra: Dict[str, Any] = {
        "x-dynamic-options": {
            "field_name": field_name,
            "placeholder": placeholder,
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": custom_placeholder,
            "depends_on": "publication_id",
        }
    }
    if resource_type:
        extra["x-resource-type"] = resource_type
    return Field(..., title=title, description=description, json_schema_extra=extra)


def _post_field() -> Any:
    return _scoped_field(
        field_name="post_id",
        title="Post",
        description="The post (post_...) to operate on",
        placeholder="Select a post...",
        custom_placeholder="Or paste post ID (post_...)",
        resource_type="beehiiv_post",
    )


def _segment_field() -> Any:
    return _scoped_field(
        field_name="segment_id",
        title="Segment",
        description="The segment to operate on",
        placeholder="Select a segment...",
        custom_placeholder="Or paste segment ID",
        resource_type="beehiiv_segment",
    )


def _automation_field() -> Any:
    return _scoped_field(
        field_name="automation_id",
        title="Automation",
        description="The automation (aut_...) to enroll the subscriber into",
        placeholder="Select an automation...",
        custom_placeholder="Or paste automation ID (aut_...)",
        resource_type="beehiiv_automation",
    )


def _webhook_field() -> Any:
    return _scoped_field(
        field_name="webhook_id",
        title="Webhook",
        description="The webhook endpoint to delete",
        placeholder="Select a webhook...",
        custom_placeholder="Or paste webhook ID",
        resource_type="beehiiv_webhook",
    )


# ============================================================================
# Credential Schema
# ============================================================================


class BeehiivApiKeyCredential(BaseModel):
    """API Key credential for beehiiv."""

    credential_type: Literal["beehiiv_api_key"] = Field(
        "beehiiv_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your beehiiv API key from Settings -> API (Workspace Settings). Passed as a Bearer token.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://app.beehiiv.com/settings/integrations/api"}
    )


BeehiivCredential = BeehiivApiKeyCredential


# ============================================================================
# Operation Configs — Publications
# ============================================================================


class BeehiivListPublicationsConfig(BaseModel):
    """List all publications associated with the API key."""

    operation: Literal["list_publications"] = Field(
        "list_publications",
        json_schema_extra={
            "const": "list_publications",
            "ui:hidden": True,
            "x-category": "Publications",
            "x-is-trigger": False,
            "x-display-name": "List Publications",
        },
        title="List Publications",
    )
    limit: Optional[str] = Field(
        "10", title="Limit", description="Max number of publications to return (1-100)"
    )


class BeehiivGetPublicationConfig(BaseModel):
    """Retrieve a single publication."""

    operation: Literal["get_publication"] = Field(
        "get_publication",
        json_schema_extra={
            "const": "get_publication",
            "ui:hidden": True,
            "x-category": "Publications",
            "x-is-trigger": False,
            "x-display-name": "Get Publication",
        },
        title="Get Publication",
    )
    publication_id: str = _publication_field()
    expand: Optional[str] = Field(
        None,
        title="Expand",
        description="Comma-separated fields to expand (e.g. stats)",
    )


# ============================================================================
# Operation Configs — Subscriptions
# ============================================================================


class BeehiivListSubscriptionsConfig(BaseModel):
    """List all subscriptions for a publication."""

    operation: Literal["list_subscriptions"] = Field(
        "list_subscriptions",
        json_schema_extra={
            "const": "list_subscriptions",
            "ui:hidden": True,
            "x-category": "Subscriptions",
            "x-is-trigger": False,
            "x-display-name": "List Subscriptions",
        },
        title="List Subscriptions",
    )
    publication_id: str = _publication_field()
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Filter by subscription status",
        json_schema_extra={
            "enum": ["", "active", "inactive", "pending", "validating", "invalid"],
            "enumNames": ["Any", "Active", "Inactive", "Pending", "Validating", "Invalid"],
            "x-enum-searchable": True,
        },
    )
    tier: Optional[str] = Field(
        None,
        title="Tier",
        description="Filter by tier",
        json_schema_extra={
            "enum": ["", "free", "premium"],
            "enumNames": ["Any", "Free", "Premium"],
            "x-enum-searchable": True,
        },
    )
    limit: Optional[str] = Field(
        "10", title="Limit", description="Max number of subscriptions to return (1-100)"
    )


class BeehiivCreateSubscriptionConfig(BaseModel):
    """Add a new subscriber to a publication."""

    operation: Literal["create_subscription"] = Field(
        "create_subscription",
        json_schema_extra={
            "const": "create_subscription",
            "ui:hidden": True,
            "x-category": "Subscriptions",
            "x-is-trigger": False,
            "x-display-name": "Create Subscription",
        },
        title="Create Subscription",
    )
    publication_id: str = _publication_field()
    email: str = Field(..., title="Email", description="The subscriber's email address")
    reactivate_existing: Optional[str] = Field(
        "false",
        title="Reactivate Existing",
        description="Reactivate the subscriber if they previously unsubscribed",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    send_welcome_email: Optional[str] = Field(
        "false",
        title="Send Welcome Email",
        description="Send the publication's welcome email to the new subscriber",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    utm_source: Optional[str] = Field(None, title="UTM Source", description="UTM source attribution")
    utm_medium: Optional[str] = Field(None, title="UTM Medium", description="UTM medium attribution")
    utm_campaign: Optional[str] = Field(
        None, title="UTM Campaign", description="UTM campaign attribution"
    )
    referring_site: Optional[str] = Field(
        None, title="Referring Site", description="URL the subscriber came from"
    )
    custom_fields: Optional[str] = Field(
        None,
        title="Custom Fields (JSON)",
        description='JSON array of custom fields, e.g. [{"name":"First Name","value":"Ada"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class BeehiivGetSubscriptionByEmailConfig(BaseModel):
    """Look up a subscriber by email address."""

    operation: Literal["get_subscription_by_email"] = Field(
        "get_subscription_by_email",
        json_schema_extra={
            "const": "get_subscription_by_email",
            "ui:hidden": True,
            "x-category": "Subscriptions",
            "x-is-trigger": False,
            "x-display-name": "Get Subscription by Email",
        },
        title="Get Subscription by Email",
    )
    publication_id: str = _publication_field()
    email: str = Field(..., title="Email", description="The subscriber's email address")


class BeehiivGetSubscriptionConfig(BaseModel):
    """Retrieve a single subscription by its prefixed ID."""

    operation: Literal["get_subscription"] = Field(
        "get_subscription",
        json_schema_extra={
            "const": "get_subscription",
            "ui:hidden": True,
            "x-category": "Subscriptions",
            "x-is-trigger": False,
            "x-display-name": "Get Subscription",
        },
        title="Get Subscription",
    )
    publication_id: str = _publication_field()
    subscription_id: str = Field(
        ..., title="Subscription ID", description="The subscription ID (sub_...)"
    )


class BeehiivUpdateSubscriptionConfig(BaseModel):
    """Update a subscriber's tier, custom fields, or status."""

    operation: Literal["update_subscription"] = Field(
        "update_subscription",
        json_schema_extra={
            "const": "update_subscription",
            "ui:hidden": True,
            "x-category": "Subscriptions",
            "x-is-trigger": False,
            "x-display-name": "Update Subscription",
        },
        title="Update Subscription",
    )
    publication_id: str = _publication_field()
    subscription_id: str = Field(
        ..., title="Subscription ID", description="The subscription ID (sub_...) to update"
    )
    tier: Optional[str] = Field(
        None,
        title="Tier",
        description="New tier for the subscriber",
        json_schema_extra={
            "enum": ["", "free", "premium"],
            "enumNames": ["Unchanged", "Free", "Premium"],
            "x-enum-searchable": True,
        },
    )
    unsubscribe: Optional[str] = Field(
        "false",
        title="Unsubscribe",
        description="Set to Yes to unsubscribe this subscriber",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    custom_fields: Optional[str] = Field(
        None,
        title="Custom Fields (JSON)",
        description='JSON array of custom fields to set, e.g. [{"name":"First Name","value":"Ada"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class BeehiivDeleteSubscriptionConfig(BaseModel):
    """Remove a subscriber from the publication."""

    operation: Literal["delete_subscription"] = Field(
        "delete_subscription",
        json_schema_extra={
            "const": "delete_subscription",
            "ui:hidden": True,
            "x-category": "Subscriptions",
            "x-is-trigger": False,
            "x-display-name": "Delete Subscription",
        },
        title="Delete Subscription",
    )
    publication_id: str = _publication_field()
    subscription_id: str = Field(
        ..., title="Subscription ID", description="The subscription ID (sub_...) to delete"
    )


class BeehiivBulkCreateSubscriptionsConfig(BaseModel):
    """Import many subscribers in one async job."""

    operation: Literal["bulk_create_subscriptions"] = Field(
        "bulk_create_subscriptions",
        json_schema_extra={
            "const": "bulk_create_subscriptions",
            "ui:hidden": True,
            "x-category": "Subscriptions",
            "x-is-trigger": False,
            "x-display-name": "Bulk Create Subscriptions",
        },
        title="Bulk Create Subscriptions",
    )
    publication_id: str = _publication_field()
    subscriptions: str = Field(
        ...,
        title="Subscriptions (JSON)",
        description='JSON array of subscriber objects, e.g. [{"email":"a@x.com"},{"email":"b@x.com"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class BeehiivAddSubscriptionTagConfig(BaseModel):
    """Attach tags to a subscriber."""

    operation: Literal["add_subscription_tag"] = Field(
        "add_subscription_tag",
        json_schema_extra={
            "const": "add_subscription_tag",
            "ui:hidden": True,
            "x-category": "Subscriptions",
            "x-is-trigger": False,
            "x-display-name": "Add Subscription Tag",
        },
        title="Add Subscription Tag",
    )
    publication_id: str = _publication_field()
    subscription_id: str = Field(
        ..., title="Subscription ID", description="The subscription ID (sub_...) to tag"
    )
    tags: str = Field(
        ..., title="Tags", description="Comma-separated list of tag names to attach"
    )


# ============================================================================
# Operation Configs — Posts
# ============================================================================


class BeehiivListPostsConfig(BaseModel):
    """List newsletter posts for a publication."""

    operation: Literal["list_posts"] = Field(
        "list_posts",
        json_schema_extra={
            "const": "list_posts",
            "ui:hidden": True,
            "x-category": "Posts",
            "x-is-trigger": False,
            "x-display-name": "List Posts",
        },
        title="List Posts",
    )
    publication_id: str = _publication_field()
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Filter by post status",
        json_schema_extra={
            "enum": ["", "draft", "confirmed", "archived"],
            "enumNames": ["Any", "Draft", "Confirmed", "Archived"],
            "x-enum-searchable": True,
        },
    )
    limit: Optional[str] = Field(
        "10", title="Limit", description="Max number of posts to return (1-100)"
    )


class BeehiivGetPostConfig(BaseModel):
    """Retrieve a single post."""

    operation: Literal["get_post"] = Field(
        "get_post",
        json_schema_extra={
            "const": "get_post",
            "ui:hidden": True,
            "x-category": "Posts",
            "x-is-trigger": False,
            "x-display-name": "Get Post",
        },
        title="Get Post",
    )
    publication_id: str = _publication_field()
    post_id: str = _post_field()
    expand: Optional[str] = Field(
        None,
        title="Expand",
        description="Comma-separated fields to expand (e.g. free_web_content,stats)",
    )


class BeehiivCreatePostConfig(BaseModel):
    """Create a draft/scheduled post for a publication."""

    operation: Literal["create_post"] = Field(
        "create_post",
        json_schema_extra={
            "const": "create_post",
            "ui:hidden": True,
            "x-category": "Posts",
            "x-is-trigger": False,
            "x-display-name": "Create Post",
            "x-creates-resource": True,
            "x-resource-type": "beehiiv_post",
            "x-resource-id-path": "data.id",
        },
        title="Create Post",
    )
    publication_id: str = _publication_field()
    title: str = Field(..., title="Title", description="The post title")
    body_content: str = Field(
        ...,
        title="Body Content",
        description="The post body (HTML or markdown)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    subtitle: Optional[str] = Field(None, title="Subtitle", description="Optional post subtitle")
    status: Optional[str] = Field(
        "draft",
        title="Status",
        description="The status to create the post in",
        json_schema_extra={
            "enum": ["draft", "confirmed", "scheduled"],
            "enumNames": ["Draft", "Confirmed", "Scheduled"],
            "x-enum-searchable": True,
        },
    )
    scheduled_at: Optional[str] = Field(
        None, title="Scheduled At", description="ISO 8601 send time (when status is scheduled)"
    )


class BeehiivUpdatePostConfig(BaseModel):
    """Update an existing post's content or scheduling."""

    operation: Literal["update_post"] = Field(
        "update_post",
        json_schema_extra={
            "const": "update_post",
            "ui:hidden": True,
            "x-category": "Posts",
            "x-is-trigger": False,
            "x-display-name": "Update Post",
        },
        title="Update Post",
    )
    publication_id: str = _publication_field()
    post_id: str = _post_field()
    title: Optional[str] = Field(None, title="Title", description="Updated post title")
    body_content: Optional[str] = Field(
        None,
        title="Body Content",
        description="Updated post body (HTML or markdown)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    scheduled_at: Optional[str] = Field(
        None, title="Scheduled At", description="Updated ISO 8601 send time"
    )


class BeehiivDeletePostConfig(BaseModel):
    """Delete a post."""

    operation: Literal["delete_post"] = Field(
        "delete_post",
        json_schema_extra={
            "const": "delete_post",
            "ui:hidden": True,
            "x-category": "Posts",
            "x-is-trigger": False,
            "x-display-name": "Delete Post",
        },
        title="Delete Post",
    )
    publication_id: str = _publication_field()
    post_id: str = _post_field()


class BeehiivGetPostStatsConfig(BaseModel):
    """Retrieve open/click/engagement stats for a post."""

    operation: Literal["get_post_stats"] = Field(
        "get_post_stats",
        json_schema_extra={
            "const": "get_post_stats",
            "ui:hidden": True,
            "x-category": "Posts",
            "x-is-trigger": False,
            "x-display-name": "Get Post Stats",
        },
        title="Get Post Stats",
    )
    publication_id: str = _publication_field()
    post_id: str = _post_field()


# ============================================================================
# Operation Configs — Segments
# ============================================================================


class BeehiivListSegmentsConfig(BaseModel):
    """List all segments for a publication."""

    operation: Literal["list_segments"] = Field(
        "list_segments",
        json_schema_extra={
            "const": "list_segments",
            "ui:hidden": True,
            "x-category": "Segments",
            "x-is-trigger": False,
            "x-display-name": "List Segments",
        },
        title="List Segments",
    )
    publication_id: str = _publication_field()
    limit: Optional[str] = Field(
        "10", title="Limit", description="Max number of segments to return (1-100)"
    )


class BeehiivGetSegmentConfig(BaseModel):
    """Retrieve a single segment."""

    operation: Literal["get_segment"] = Field(
        "get_segment",
        json_schema_extra={
            "const": "get_segment",
            "ui:hidden": True,
            "x-category": "Segments",
            "x-is-trigger": False,
            "x-display-name": "Get Segment",
        },
        title="Get Segment",
    )
    publication_id: str = _publication_field()
    segment_id: str = _segment_field()


class BeehiivListSegmentSubscribersConfig(BaseModel):
    """List subscribers matching a segment."""

    operation: Literal["list_segment_subscribers"] = Field(
        "list_segment_subscribers",
        json_schema_extra={
            "const": "list_segment_subscribers",
            "ui:hidden": True,
            "x-category": "Segments",
            "x-is-trigger": False,
            "x-display-name": "List Segment Subscribers",
        },
        title="List Segment Subscribers",
    )
    publication_id: str = _publication_field()
    segment_id: str = _segment_field()
    limit: Optional[str] = Field(
        "10", title="Limit", description="Max number of subscribers to return (1-100)"
    )


class BeehiivDeleteSegmentConfig(BaseModel):
    """Delete a segment."""

    operation: Literal["delete_segment"] = Field(
        "delete_segment",
        json_schema_extra={
            "const": "delete_segment",
            "ui:hidden": True,
            "x-category": "Segments",
            "x-is-trigger": False,
            "x-display-name": "Delete Segment",
        },
        title="Delete Segment",
    )
    publication_id: str = _publication_field()
    segment_id: str = _segment_field()


# ============================================================================
# Operation Configs — Custom Fields
# ============================================================================


class BeehiivListCustomFieldsConfig(BaseModel):
    """List custom subscriber fields."""

    operation: Literal["list_custom_fields"] = Field(
        "list_custom_fields",
        json_schema_extra={
            "const": "list_custom_fields",
            "ui:hidden": True,
            "x-category": "Custom Fields",
            "x-is-trigger": False,
            "x-display-name": "List Custom Fields",
        },
        title="List Custom Fields",
    )
    publication_id: str = _publication_field()


class BeehiivCreateCustomFieldConfig(BaseModel):
    """Define a new custom field on subscribers."""

    operation: Literal["create_custom_field"] = Field(
        "create_custom_field",
        json_schema_extra={
            "const": "create_custom_field",
            "ui:hidden": True,
            "x-category": "Custom Fields",
            "x-is-trigger": False,
            "x-display-name": "Create Custom Field",
        },
        title="Create Custom Field",
    )
    publication_id: str = _publication_field()
    display: str = Field(..., title="Display Name", description="The display name of the custom field")
    kind: Optional[str] = Field(
        "string",
        title="Kind",
        description="The data type of the custom field",
        json_schema_extra={
            "enum": ["string", "integer", "boolean", "date", "datetime", "list"],
            "enumNames": ["String", "Integer", "Boolean", "Date", "Datetime", "List"],
            "x-enum-searchable": True,
        },
    )


class BeehiivDeleteCustomFieldConfig(BaseModel):
    """Delete a custom subscriber field."""

    operation: Literal["delete_custom_field"] = Field(
        "delete_custom_field",
        json_schema_extra={
            "const": "delete_custom_field",
            "ui:hidden": True,
            "x-category": "Custom Fields",
            "x-is-trigger": False,
            "x-display-name": "Delete Custom Field",
        },
        title="Delete Custom Field",
    )
    publication_id: str = _publication_field()
    field_id: str = Field(..., title="Field ID", description="The ID of the custom field to delete")


# ============================================================================
# Operation Configs — Automations
# ============================================================================


class BeehiivListAutomationsConfig(BaseModel):
    """List automation flows for a publication."""

    operation: Literal["list_automations"] = Field(
        "list_automations",
        json_schema_extra={
            "const": "list_automations",
            "ui:hidden": True,
            "x-category": "Automations",
            "x-is-trigger": False,
            "x-display-name": "List Automations",
        },
        title="List Automations",
    )
    publication_id: str = _publication_field()
    limit: Optional[str] = Field(
        "10", title="Limit", description="Max number of automations to return (1-100)"
    )


class BeehiivGetAutomationConfig(BaseModel):
    """Retrieve a single automation by ID."""

    operation: Literal["get_automation"] = Field(
        "get_automation",
        json_schema_extra={
            "const": "get_automation",
            "ui:hidden": True,
            "x-category": "Automations",
            "x-is-trigger": False,
            "x-display-name": "Get Automation",
        },
        title="Get Automation",
    )
    publication_id: str = _publication_field()
    automation_id: str = _automation_field()


class BeehiivAddToAutomationConfig(BaseModel):
    """Enroll a subscriber into an automation journey."""

    operation: Literal["add_to_automation"] = Field(
        "add_to_automation",
        json_schema_extra={
            "const": "add_to_automation",
            "ui:hidden": True,
            "x-category": "Automations",
            "x-is-trigger": False,
            "x-display-name": "Add Subscriber to Automation",
        },
        title="Add Subscriber to Automation",
    )
    publication_id: str = _publication_field()
    automation_id: str = _automation_field()
    email: Optional[str] = Field(
        None, title="Email", description="Email of the subscriber to enroll (or use Subscription ID)"
    )
    subscription_id: Optional[str] = Field(
        None,
        title="Subscription ID",
        description="Subscription ID (sub_...) of the subscriber to enroll",
    )


# ============================================================================
# Operation Configs — Tiers / Referral / Newsletter Lists / Polls
# ============================================================================


class BeehiivListTiersConfig(BaseModel):
    """List paid subscription tiers."""

    operation: Literal["list_tiers"] = Field(
        "list_tiers",
        json_schema_extra={
            "const": "list_tiers",
            "ui:hidden": True,
            "x-category": "Tiers & Referrals",
            "x-is-trigger": False,
            "x-display-name": "List Tiers",
        },
        title="List Tiers",
    )
    publication_id: str = _publication_field()


class BeehiivGetReferralProgramConfig(BaseModel):
    """Retrieve referral program milestones/rewards."""

    operation: Literal["get_referral_program"] = Field(
        "get_referral_program",
        json_schema_extra={
            "const": "get_referral_program",
            "ui:hidden": True,
            "x-category": "Tiers & Referrals",
            "x-is-trigger": False,
            "x-display-name": "Get Referral Program",
        },
        title="Get Referral Program",
    )
    publication_id: str = _publication_field()


class BeehiivListNewsletterListsConfig(BaseModel):
    """List newsletter lists (multi-list feature, beta)."""

    operation: Literal["list_newsletter_lists"] = Field(
        "list_newsletter_lists",
        json_schema_extra={
            "const": "list_newsletter_lists",
            "ui:hidden": True,
            "x-category": "Lists & Polls",
            "x-is-trigger": False,
            "x-display-name": "List Newsletter Lists",
        },
        title="List Newsletter Lists",
    )
    publication_id: str = _publication_field()


class BeehiivListPollsConfig(BaseModel):
    """List polls and their responses."""

    operation: Literal["list_polls"] = Field(
        "list_polls",
        json_schema_extra={
            "const": "list_polls",
            "ui:hidden": True,
            "x-category": "Lists & Polls",
            "x-is-trigger": False,
            "x-display-name": "List Polls",
        },
        title="List Polls",
    )
    publication_id: str = _publication_field()
    limit: Optional[str] = Field(
        "10", title="Limit", description="Max number of polls to return (1-100)"
    )


class BeehiivGetPollConfig(BaseModel):
    """Retrieve a single poll."""

    operation: Literal["get_poll"] = Field(
        "get_poll",
        json_schema_extra={
            "const": "get_poll",
            "ui:hidden": True,
            "x-category": "Lists & Polls",
            "x-is-trigger": False,
            "x-display-name": "Get Poll",
        },
        title="Get Poll",
    )
    publication_id: str = _publication_field()
    poll_id: str = Field(..., title="Poll ID", description="The poll ID to retrieve")


class BeehiivGetPollResponsesConfig(BaseModel):
    """List responses for a poll."""

    operation: Literal["get_poll_responses"] = Field(
        "get_poll_responses",
        json_schema_extra={
            "const": "get_poll_responses",
            "ui:hidden": True,
            "x-category": "Lists & Polls",
            "x-is-trigger": False,
            "x-display-name": "Get Poll Responses",
        },
        title="Get Poll Responses",
    )
    publication_id: str = _publication_field()
    poll_id: str = Field(..., title="Poll ID", description="The poll ID to get responses for")
    limit: Optional[str] = Field(
        "10", title="Limit", description="Max number of responses to return (1-100)"
    )


# ============================================================================
# Operation Configs — Webhooks (management)
# ============================================================================


class BeehiivGetWebhookConfig(BaseModel):
    """Retrieve a single webhook endpoint."""

    operation: Literal["get_webhook"] = Field(
        "get_webhook",
        json_schema_extra={
            "const": "get_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Get Webhook",
        },
        title="Get Webhook",
    )
    publication_id: str = _publication_field()
    webhook_id: str = _webhook_field()


class BeehiivListWebhooksConfig(BaseModel):
    """List configured webhook endpoints."""

    operation: Literal["list_webhooks"] = Field(
        "list_webhooks",
        json_schema_extra={
            "const": "list_webhooks",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "List Webhooks",
        },
        title="List Webhooks",
    )
    publication_id: str = _publication_field()


class BeehiivCreateWebhookConfig(BaseModel):
    """Subscribe an endpoint URL to event types."""

    operation: Literal["create_webhook"] = Field(
        "create_webhook",
        json_schema_extra={
            "const": "create_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Create Webhook",
            "x-creates-resource": True,
            "x-resource-type": "beehiiv_webhook",
            "x-resource-id-path": "data.id",
        },
        title="Create Webhook",
    )
    publication_id: str = _publication_field()
    url: str = Field(..., title="Endpoint URL", description="The URL to receive webhook events")
    event_types: str = Field(
        ...,
        title="Event Types",
        description="Comma-separated event types (e.g. subscription.created, post.sent)",
    )
    description: Optional[str] = Field(
        None, title="Description", description="Optional description for the webhook"
    )


class BeehiivDeleteWebhookConfig(BaseModel):
    """Remove a webhook subscription."""

    operation: Literal["delete_webhook"] = Field(
        "delete_webhook",
        json_schema_extra={
            "const": "delete_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Delete Webhook",
        },
        title="Delete Webhook",
    )
    publication_id: str = _publication_field()
    webhook_id: str = _webhook_field()


# ============================================================================
# Webhook Trigger Configs — decomposed (one per logical event group)
# ============================================================================

# Shared hidden fields every trigger config carries.
def _trigger_hidden(name: str, **kwargs):
    return Field(default=None, json_schema_extra={"ui:hidden": True}, **kwargs)


class _BeehiivTriggerBase(BaseModel):
    """Common fields shared by all beehiiv trigger operations."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    publication_id: str = _publication_field()
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="beehiiv posts events here. Registered automatically when you connect credentials.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )
    webhook_id: Optional[str] = _trigger_hidden("webhook_id")
    external_webhook_id: Optional[str] = _trigger_hidden("external_webhook_id")
    signing_secret: Optional[str] = _trigger_hidden("signing_secret")
    relay_connected: Optional[bool] = _trigger_hidden("relay_connected")
    is_production: Optional[bool] = _trigger_hidden("is_production")
    trigger_registered: Optional[bool] = _trigger_hidden("trigger_registered")
    trigger_error: Optional[str] = _trigger_hidden("trigger_error")


def _trigger_op(value: str, display: str, keywords: Optional[List[str]] = None) -> Any:
    extra: Dict[str, Any] = {
        "ui:hidden": True,
        "x-category": None,
        "x-is-trigger": True,
        "x-display-name": display,
    }
    if keywords:
        extra["x-keywords"] = keywords
    return Field(default=value, json_schema_extra=extra, title=display)


class BeehiivOnSubscriberCreatedConfig(_BeehiivTriggerBase):
    """Trigger: fires when a new subscriber is created."""
    operation: Literal["on_subscriber_created"] = _trigger_op(
        "on_subscriber_created", "On New Subscriber",
        ["new subscriber", "subscription created", "new signup", "subscriber joined", "new reader"],
    )


class BeehiivOnSubscriberConfirmedConfig(_BeehiivTriggerBase):
    """Trigger: fires when a subscriber confirms their email (double opt-in)."""
    operation: Literal["on_subscriber_confirmed"] = _trigger_op(
        "on_subscriber_confirmed", "On Subscriber Confirmed",
        ["subscriber confirmed", "double opt-in confirmed", "email confirmed"],
    )


class BeehiivOnSubscriptionUpgradedConfig(_BeehiivTriggerBase):
    """Trigger: fires when a subscription is upgraded to a paid tier."""
    operation: Literal["on_subscription_upgraded"] = _trigger_op(
        "on_subscription_upgraded", "On Subscription Upgraded",
        ["subscription upgraded", "paid upgrade", "premium subscriber", "tier upgrade"],
    )


class BeehiivOnSubscriptionDowngradedConfig(_BeehiivTriggerBase):
    """Trigger: fires when a subscription is downgraded."""
    operation: Literal["on_subscription_downgraded"] = _trigger_op(
        "on_subscription_downgraded", "On Subscription Downgraded",
        ["subscription downgraded", "tier downgraded", "downgrade", "churn signal"],
    )


class BeehiivOnSubscriptionPausedConfig(_BeehiivTriggerBase):
    """Trigger: fires when a subscription is paused."""
    operation: Literal["on_subscription_paused"] = _trigger_op(
        "on_subscription_paused", "On Subscription Paused",
        ["subscription paused", "subscriber paused", "paused subscription"],
    )


class BeehiivOnSubscriptionResumedConfig(_BeehiivTriggerBase):
    """Trigger: fires when a paused subscription is resumed."""
    operation: Literal["on_subscription_resumed"] = _trigger_op(
        "on_subscription_resumed", "On Subscription Resumed",
        ["subscription resumed", "reactivated", "subscriber returned", "resumed subscription"],
    )


class BeehiivOnSubscriptionDeletedConfig(_BeehiivTriggerBase):
    """Trigger: fires when a subscriber unsubscribes or is deleted."""
    operation: Literal["on_subscription_deleted"] = _trigger_op(
        "on_subscription_deleted", "On Subscriber Unsubscribed",
        ["subscriber deleted", "unsubscribed", "subscriber removed", "churn", "cancel subscription"],
    )


class BeehiivOnPostSentConfig(_BeehiivTriggerBase):
    """Trigger: fires when a post is sent to subscribers."""
    operation: Literal["on_post_sent"] = _trigger_op(
        "on_post_sent", "On Post Sent",
        ["post sent", "newsletter sent", "email sent", "post published", "newsletter delivered"],
    )


class BeehiivOnPostScheduledConfig(_BeehiivTriggerBase):
    """Trigger: fires when a post is scheduled for future delivery."""
    operation: Literal["on_post_scheduled"] = _trigger_op(
        "on_post_scheduled", "On Post Scheduled",
        ["post scheduled", "newsletter scheduled", "scheduled post", "upcoming post"],
    )


class BeehiivOnPostUpdatedConfig(_BeehiivTriggerBase):
    """Trigger: fires when an existing post is updated."""
    operation: Literal["on_post_updated"] = _trigger_op(
        "on_post_updated", "On Post Updated",
        ["post updated", "newsletter updated", "content changed", "post edited"],
    )


class BeehiivOnSurveyResponseConfig(_BeehiivTriggerBase):
    """Trigger: fires when a subscriber submits a survey response."""
    operation: Literal["on_survey_response"] = _trigger_op(
        "on_survey_response", "On Survey Response",
        ["survey response", "survey submitted", "survey answer", "reader survey"],
    )


class BeehiivOnTierChangedConfig(_BeehiivTriggerBase):
    """Trigger: fires when a subscription tier is created, deleted, paused, or resumed."""
    operation: Literal["on_tier_changed"] = _trigger_op(
        "on_tier_changed", "On Tier Changed",
        ["tier changed", "premium tier", "subscription tier event", "tier lifecycle"],
    )


class BeehiivOnNewsletterListEventConfig(_BeehiivTriggerBase):
    """Trigger: fires when a subscriber joins, leaves, pauses, or resumes a newsletter list."""
    operation: Literal["on_newsletter_list_event"] = _trigger_op(
        "on_newsletter_list_event", "On Newsletter List Event",
        ["newsletter list", "list subscription", "list joined", "list unsubscribed", "list event"],
    )


# Kept for backward compatibility; new workflows should use the decomposed triggers above.
class BeehiivTriggerConfig(_BeehiivTriggerBase):
    """Trigger: fires on any beehiiv event (catch-all)."""
    operation: Literal["on_beehiiv_event"] = _trigger_op(
        "on_beehiiv_event", "On beehiiv Event (Any)",
        ["any beehiiv event", "beehiiv webhook", "all events"],
    )


# All trigger config types as a tuple for isinstance checks.
_BEEHIIV_TRIGGER_TYPES = (
    BeehiivOnSubscriberCreatedConfig,
    BeehiivOnSubscriberConfirmedConfig,
    BeehiivOnSubscriptionUpgradedConfig,
    BeehiivOnSubscriptionDowngradedConfig,
    BeehiivOnSubscriptionPausedConfig,
    BeehiivOnSubscriptionResumedConfig,
    BeehiivOnSubscriptionDeletedConfig,
    BeehiivOnPostSentConfig,
    BeehiivOnPostScheduledConfig,
    BeehiivOnPostUpdatedConfig,
    BeehiivOnSurveyResponseConfig,
    BeehiivOnTierChangedConfig,
    BeehiivOnNewsletterListEventConfig,
    BeehiivTriggerConfig,
)


# ============================================================================
# Discriminated Union
# ============================================================================


BeehiivConfig = Annotated[
    Union[
        BeehiivListPublicationsConfig,
        BeehiivGetPublicationConfig,
        BeehiivListSubscriptionsConfig,
        BeehiivCreateSubscriptionConfig,
        BeehiivGetSubscriptionByEmailConfig,
        BeehiivGetSubscriptionConfig,
        BeehiivUpdateSubscriptionConfig,
        BeehiivDeleteSubscriptionConfig,
        BeehiivBulkCreateSubscriptionsConfig,
        BeehiivAddSubscriptionTagConfig,
        BeehiivListPostsConfig,
        BeehiivGetPostConfig,
        BeehiivCreatePostConfig,
        BeehiivUpdatePostConfig,
        BeehiivDeletePostConfig,
        BeehiivGetPostStatsConfig,
        BeehiivListSegmentsConfig,
        BeehiivGetSegmentConfig,
        BeehiivListSegmentSubscribersConfig,
        BeehiivDeleteSegmentConfig,
        BeehiivListCustomFieldsConfig,
        BeehiivCreateCustomFieldConfig,
        BeehiivDeleteCustomFieldConfig,
        BeehiivListAutomationsConfig,
        BeehiivGetAutomationConfig,
        BeehiivAddToAutomationConfig,
        BeehiivListTiersConfig,
        BeehiivGetReferralProgramConfig,
        BeehiivListNewsletterListsConfig,
        BeehiivListPollsConfig,
        BeehiivGetPollConfig,
        BeehiivGetPollResponsesConfig,
        BeehiivGetWebhookConfig,
        BeehiivListWebhooksConfig,
        BeehiivCreateWebhookConfig,
        BeehiivDeleteWebhookConfig,
        # Decomposed triggers (one per event group)
        BeehiivOnSubscriberCreatedConfig,
        BeehiivOnSubscriberConfirmedConfig,
        BeehiivOnSubscriptionUpgradedConfig,
        BeehiivOnSubscriptionDowngradedConfig,
        BeehiivOnSubscriptionPausedConfig,
        BeehiivOnSubscriptionResumedConfig,
        BeehiivOnSubscriptionDeletedConfig,
        BeehiivOnPostSentConfig,
        BeehiivOnPostScheduledConfig,
        BeehiivOnPostUpdatedConfig,
        BeehiivOnSurveyResponseConfig,
        BeehiivOnTierChangedConfig,
        BeehiivOnNewsletterListEventConfig,
        BeehiivTriggerConfig,  # catch-all / backward compat
    ],
    Discriminator("operation"),
]


class BeehiivNodeConfig(NodeConfig[BeehiivConfig, BeehiivCredential]):
    """Full configuration for the beehiiv node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _parse_json(value: Optional[str], field: str) -> Optional[Any]:
    """Parse a JSON string field, raising a clear error on invalid JSON."""
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in '{field}': {e}")


async def _beehiiv_request(
    api_key: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated beehiiv v2 request and return a structured result."""
    url = f"{BEEHIIV_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if json_body:
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
                    if isinstance(err, dict):
                        message = err.get("message") or err.get("error") or err.get("errors") or str(err)
                    else:
                        message = str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[BeehiivNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
            else:
                try:
                    payload = response.json()
                    # beehiiv v2 wraps single/list results in {data: ...}
                    data = payload.get("data", payload) if isinstance(payload, dict) else payload
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
            logger.error(f"[BeehiivNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class BeehiivNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """beehiiv newsletter automation node."""

    edit_examples = [
        "Add a new subscriber to my newsletter when a user signs up",
        "Create and schedule a newsletter post",
        "Look up a subscriber by their email address",
        "List all active subscriptions for a publication",
        "Trigger a workflow whenever a new subscriber confirms",
    ]

    @classmethod
    def get_config_model(cls):
        return BeehiivNodeConfig

    # Maps each trigger operation to the beehiiv event_types it subscribes to.
    _trigger_event_map: ClassVar[Dict[str, List[str]]] = {
        "on_subscriber_created": ["subscription.created"],
        "on_subscriber_confirmed": ["subscription.confirmed"],
        "on_subscription_upgraded": ["subscription.upgraded"],
        "on_subscription_downgraded": ["subscription.downgraded"],
        "on_subscription_paused": ["subscription.paused"],
        "on_subscription_resumed": ["subscription.resumed"],
        "on_subscription_deleted": ["subscription.deleted"],
        "on_post_sent": ["post.sent"],
        "on_post_scheduled": ["post.scheduled"],
        "on_post_updated": ["post.updated"],
        "on_survey_response": ["survey.response_submitted"],
        "on_tier_changed": [
            "subscription.tier.created",
            "subscription.tier.deleted",
            "subscription.tier.paused",
            "subscription.tier.resumed",
        ],
        "on_newsletter_list_event": [
            "newsletter_list_subscription.subscribed",
            "newsletter_list_subscription.unsubscribed",
            "newsletter_list_subscription.paused",
            "newsletter_list_subscription.resumed",
        ],
        # catch-all: subscribe to every event
        "on_beehiiv_event": BEEHIIV_TRIGGER_EVENTS,
    }

    # ------------------------------------------------------------------
    # Dynamic options (publications)
    # ------------------------------------------------------------------
    # Maps each publication-scoped dynamic field to its LIST endpoint (relative
    # to /publications/{pubId}) and the response keys used for the option label.
    _SCOPED_OPTION_SOURCES: Dict[str, Dict[str, Any]] = {
        "post_id": {"path": "posts", "label_keys": ("title",)},
        "segment_id": {"path": "segments", "label_keys": ("name",)},
        "automation_id": {"path": "automations", "label_keys": ("name",)},
        "webhook_id": {"path": "webhooks", "label_keys": ("url",)},
    }

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name != "publication_id" and field_name not in cls._SCOPED_OPTION_SOURCES:
            return {"options": []}
        api_key = (credential_data or {}).get("api_key")
        if not api_key:
            return {"options": []}
        if field_name == "publication_id":
            return await cls._load_publication_options(api_key)
        return await cls._load_scoped_options(api_key, field_name, context or {})

    @classmethod
    async def _load_publication_options(cls, api_key: str) -> Dict[str, Any]:
        result = await _beehiiv_request(
            api_key, "GET", "/publications", params={"limit": "100"}, action_name="list_publications"
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or []
        publications = data if isinstance(data, list) else data.get("data") or []
        options = []
        for pub in publications:
            if not isinstance(pub, dict):
                continue
            pub_id = pub.get("id")
            name = pub.get("name") or pub_id
            if pub_id:
                options.append({"label": str(name), "value": str(pub_id)})
        return {"options": options}

    @classmethod
    async def _load_scoped_options(
        cls, api_key: str, field_name: str, config_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        publication_id = config_data.get("publication_id")
        if not publication_id:
            return {"options": []}
        source = cls._SCOPED_OPTION_SOURCES[field_name]
        result = await _beehiiv_request(
            api_key,
            "GET",
            f"/publications/{publication_id}/{source['path']}",
            params={"limit": "100"},
            action_name=f"list_{source['path']}",
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or []
        rows = data if isinstance(data, list) else data.get("data") or []
        options = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_id = row.get("id")
            if not row_id:
                continue
            label = next((row.get(k) for k in source["label_keys"] if row.get(k)), None) or row_id
            options.append({"label": str(label), "value": str(row_id)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Webhook trigger registration
    # ------------------------------------------------------------------
    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "publication_id": (config or {}).get("publication_id"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        api_key = credential.get("api_key")
        if not api_key:
            raise ValueError("A beehiiv API key is required to register the trigger")
        publication_id = (config or {}).get("publication_id")
        if not publication_id:
            raise ValueError("Select a publication before activating this trigger")
        operation = (config or {}).get("operation", "on_beehiiv_event")
        event_types = cls._trigger_event_map.get(operation) or BEEHIIV_TRIGGER_EVENTS
        result = await _beehiiv_request(
            api_key,
            "POST",
            f"/publications/{publication_id}/webhooks",
            json_body={
                "url": webhook_url,
                "event_types": event_types,
                "description": "NoClick workflow trigger",
            },
            action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"beehiiv webhook registration failed: {result.get('error')}")
        data = result.get("data") or {}
        external_id = data.get("id") if isinstance(data, dict) else None
        secret = data.get("secret") if isinstance(data, dict) else None
        return {
            "external_webhook_id": str(external_id) if external_id else None,
            "signing_secret": secret,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        publication_id = (config or {}).get("publication_id")
        api_key = (credential or {}).get("api_key")
        if not external_id or not api_key or not publication_id:
            return
        await _beehiiv_request(
            api_key,
            "DELETE",
            f"/publications/{publication_id}/webhooks/{external_id}",
            action_name="unregister_webhook",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored — accept (trigger not yet armed)
        sent = headers.get("x-beehiiv-signature") or headers.get("beehiiv-signature")
        if not sent:
            return False
        # Strip "sha256=" prefix if beehiiv sends it
        if sent.startswith("sha256="):
            sent = sent[7:]
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sent)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, BeehiivNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, _BEEHIIV_TRIGGER_TYPES):
            return {
                "status": "success",
                "action": op.operation,
                "event_types": self._trigger_event_map.get(op.operation, []),
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your beehiiv API key.")
        api_key = credentials.api_key

        handlers = {
            "list_publications": self._list_publications,
            "get_publication": self._get_publication,
            "list_subscriptions": self._list_subscriptions,
            "create_subscription": self._create_subscription,
            "get_subscription_by_email": self._get_subscription_by_email,
            "get_subscription": self._get_subscription,
            "update_subscription": self._update_subscription,
            "delete_subscription": self._delete_subscription,
            "bulk_create_subscriptions": self._bulk_create_subscriptions,
            "add_subscription_tag": self._add_subscription_tag,
            "list_posts": self._list_posts,
            "get_post": self._get_post,
            "create_post": self._create_post,
            "update_post": self._update_post,
            "delete_post": self._delete_post,
            "get_post_stats": self._get_post_stats,
            "list_segments": self._list_segments,
            "get_segment": self._get_segment,
            "list_segment_subscribers": self._list_segment_subscribers,
            "delete_segment": self._delete_segment,
            "list_custom_fields": self._list_custom_fields,
            "create_custom_field": self._create_custom_field,
            "delete_custom_field": self._delete_custom_field,
            "list_automations": self._list_automations,
            "get_automation": self._get_automation,
            "add_to_automation": self._add_to_automation,
            "list_tiers": self._list_tiers,
            "get_referral_program": self._get_referral_program,
            "list_newsletter_lists": self._list_newsletter_lists,
            "list_polls": self._list_polls,
            "get_poll": self._get_poll,
            "get_poll_responses": self._get_poll_responses,
            "get_webhook": self._get_webhook,
            "list_webhooks": self._list_webhooks,
            "create_webhook": self._create_webhook,
            "delete_webhook": self._delete_webhook,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers — Publications
    # ------------------------------------------------------------------
    async def _list_publications(self, c: BeehiivListPublicationsConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", "/publications", params={"limit": c.limit}, action_name="list_publications"
        )

    async def _get_publication(self, c: BeehiivGetPublicationConfig, api_key: str) -> Dict[str, Any]:
        params = {"expand[]": _comma_list(c.expand)} if c.expand else None
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}", params=params, action_name="get_publication"
        )

    # ------------------------------------------------------------------
    # Handlers — Subscriptions
    # ------------------------------------------------------------------
    async def _list_subscriptions(self, c: BeehiivListSubscriptionsConfig, api_key: str) -> Dict[str, Any]:
        params = {"status": c.status or None, "tier": c.tier or None, "limit": c.limit}
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/subscriptions",
            params=params, action_name="list_subscriptions"
        )

    async def _create_subscription(self, c: BeehiivCreateSubscriptionConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "email": c.email,
            "reactivate_existing": c.reactivate_existing == "true",
            "send_welcome_email": c.send_welcome_email == "true",
            "utm_source": c.utm_source,
            "utm_medium": c.utm_medium,
            "utm_campaign": c.utm_campaign,
            "referring_site": c.referring_site,
            "custom_fields": _parse_json(c.custom_fields, "custom_fields"),
        }
        return await _beehiiv_request(
            api_key, "POST", f"/publications/{c.publication_id}/subscriptions",
            json_body=body, action_name="create_subscription"
        )

    async def _get_subscription_by_email(
        self, c: BeehiivGetSubscriptionByEmailConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/subscriptions/by_email/{c.email}",
            action_name="get_subscription_by_email"
        )

    async def _get_subscription(self, c: BeehiivGetSubscriptionConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/subscriptions/{c.subscription_id}",
            action_name="get_subscription"
        )

    async def _update_subscription(self, c: BeehiivUpdateSubscriptionConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "tier": c.tier or None,
            "unsubscribe": True if c.unsubscribe == "true" else None,
            "custom_fields": _parse_json(c.custom_fields, "custom_fields"),
        }
        return await _beehiiv_request(
            api_key, "PUT", f"/publications/{c.publication_id}/subscriptions/{c.subscription_id}",
            json_body=body, action_name="update_subscription"
        )

    async def _delete_subscription(self, c: BeehiivDeleteSubscriptionConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "DELETE", f"/publications/{c.publication_id}/subscriptions/{c.subscription_id}",
            action_name="delete_subscription"
        )

    async def _bulk_create_subscriptions(
        self, c: BeehiivBulkCreateSubscriptionsConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {"subscriptions": _parse_json(c.subscriptions, "subscriptions")}
        return await _beehiiv_request(
            api_key, "POST", f"/publications/{c.publication_id}/bulk_subscriptions",
            json_body=body, action_name="bulk_create_subscriptions"
        )

    async def _add_subscription_tag(self, c: BeehiivAddSubscriptionTagConfig, api_key: str) -> Dict[str, Any]:
        body = {"tags": _comma_list(c.tags)}
        return await _beehiiv_request(
            api_key, "POST",
            f"/publications/{c.publication_id}/subscriptions/{c.subscription_id}/tags",
            json_body=body, action_name="add_subscription_tag"
        )

    # ------------------------------------------------------------------
    # Handlers — Posts
    # ------------------------------------------------------------------
    async def _list_posts(self, c: BeehiivListPostsConfig, api_key: str) -> Dict[str, Any]:
        params = {"status": c.status or None, "limit": c.limit}
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/posts",
            params=params, action_name="list_posts"
        )

    async def _get_post(self, c: BeehiivGetPostConfig, api_key: str) -> Dict[str, Any]:
        params = {"expand[]": _comma_list(c.expand)} if c.expand else None
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/posts/{c.post_id}",
            params=params, action_name="get_post"
        )

    async def _create_post(self, c: BeehiivCreatePostConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "title": c.title,
            "body_content": c.body_content,
            "subtitle": c.subtitle,
            "status": c.status,
            "scheduled_at": c.scheduled_at,
        }
        return await _beehiiv_request(
            api_key, "POST", f"/publications/{c.publication_id}/posts",
            json_body=body, action_name="create_post"
        )

    async def _update_post(self, c: BeehiivUpdatePostConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "title": c.title,
            "body_content": c.body_content,
            "scheduled_at": c.scheduled_at,
        }
        return await _beehiiv_request(
            api_key, "PATCH", f"/publications/{c.publication_id}/posts/{c.post_id}",
            json_body=body, action_name="update_post"
        )

    async def _delete_post(self, c: BeehiivDeletePostConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "DELETE", f"/publications/{c.publication_id}/posts/{c.post_id}",
            action_name="delete_post"
        )

    async def _get_post_stats(self, c: BeehiivGetPostStatsConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/posts/{c.post_id}/aggregate_stats",
            action_name="get_post_stats"
        )

    # ------------------------------------------------------------------
    # Handlers — Segments
    # ------------------------------------------------------------------
    async def _list_segments(self, c: BeehiivListSegmentsConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/segments",
            params={"limit": c.limit}, action_name="list_segments"
        )

    async def _get_segment(self, c: BeehiivGetSegmentConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/segments/{c.segment_id}",
            action_name="get_segment"
        )

    async def _list_segment_subscribers(
        self, c: BeehiivListSegmentSubscribersConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/segments/{c.segment_id}/members",
            params={"limit": c.limit}, action_name="list_segment_subscribers"
        )

    async def _delete_segment(self, c: BeehiivDeleteSegmentConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "DELETE", f"/publications/{c.publication_id}/segments/{c.segment_id}",
            action_name="delete_segment"
        )

    # ------------------------------------------------------------------
    # Handlers — Custom Fields
    # ------------------------------------------------------------------
    async def _list_custom_fields(self, c: BeehiivListCustomFieldsConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/custom_fields",
            action_name="list_custom_fields"
        )

    async def _create_custom_field(self, c: BeehiivCreateCustomFieldConfig, api_key: str) -> Dict[str, Any]:
        body = {"display": c.display, "kind": c.kind}
        return await _beehiiv_request(
            api_key, "POST", f"/publications/{c.publication_id}/custom_fields",
            json_body=body, action_name="create_custom_field"
        )

    async def _delete_custom_field(self, c: BeehiivDeleteCustomFieldConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "DELETE", f"/publications/{c.publication_id}/custom_fields/{c.field_id}",
            action_name="delete_custom_field"
        )

    # ------------------------------------------------------------------
    # Handlers — Automations
    # ------------------------------------------------------------------
    async def _list_automations(self, c: BeehiivListAutomationsConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/automations",
            params={"limit": c.limit}, action_name="list_automations"
        )

    async def _get_automation(self, c: BeehiivGetAutomationConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/automations/{c.automation_id}",
            action_name="get_automation"
        )

    async def _add_to_automation(self, c: BeehiivAddToAutomationConfig, api_key: str) -> Dict[str, Any]:
        if not c.email and not c.subscription_id:
            raise ValueError("Provide either an Email or a Subscription ID to enroll")
        body = {"email": c.email, "subscription_id": c.subscription_id}
        return await _beehiiv_request(
            api_key, "POST",
            f"/publications/{c.publication_id}/automations/{c.automation_id}/journeys",
            json_body=body, action_name="add_to_automation"
        )

    # ------------------------------------------------------------------
    # Handlers — Tiers / Referral / Lists / Polls
    # ------------------------------------------------------------------
    async def _list_tiers(self, c: BeehiivListTiersConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/tiers", action_name="list_tiers"
        )

    async def _get_referral_program(self, c: BeehiivGetReferralProgramConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/referral_program",
            action_name="get_referral_program"
        )

    async def _list_newsletter_lists(self, c: BeehiivListNewsletterListsConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/newsletter_lists",
            action_name="list_newsletter_lists"
        )

    async def _list_polls(self, c: BeehiivListPollsConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/polls",
            params={"limit": c.limit}, action_name="list_polls"
        )

    async def _get_poll(self, c: BeehiivGetPollConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/polls/{c.poll_id}",
            action_name="get_poll"
        )

    async def _get_poll_responses(self, c: BeehiivGetPollResponsesConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/polls/{c.poll_id}/responses",
            params={"limit": c.limit}, action_name="get_poll_responses"
        )

    # ------------------------------------------------------------------
    # Handlers — Webhooks (management)
    # ------------------------------------------------------------------
    async def _get_webhook(self, c: BeehiivGetWebhookConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/webhooks/{c.webhook_id}",
            action_name="get_webhook"
        )

    async def _list_webhooks(self, c: BeehiivListWebhooksConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "GET", f"/publications/{c.publication_id}/webhooks", action_name="list_webhooks"
        )

    async def _create_webhook(self, c: BeehiivCreateWebhookConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "url": c.url,
            "event_types": _comma_list(c.event_types),
            "description": c.description,
        }
        return await _beehiiv_request(
            api_key, "POST", f"/publications/{c.publication_id}/webhooks",
            json_body=body, action_name="create_webhook"
        )

    async def _delete_webhook(self, c: BeehiivDeleteWebhookConfig, api_key: str) -> Dict[str, Any]:
        return await _beehiiv_request(
            api_key, "DELETE", f"/publications/{c.publication_id}/webhooks/{c.webhook_id}",
            action_name="delete_webhook"
        )
