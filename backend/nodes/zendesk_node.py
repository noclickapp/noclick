"""
Zendesk Support automation node.

Provides workflow integration with the Zendesk Support REST API (v2) for
operations including:
- Tickets: list, show, create, update, delete, create many, update many,
  merge, count, list comments, add comment, list audits, add tags
- Search: unified search, search users
- Users: list, show, create, create or update, update, delete
- Organizations: list, create, update, delete
- Groups, ticket fields, satisfaction ratings, job statuses
- Webhooks: create webhook
- Webhook Trigger: fire when Zendesk POSTs a user-selected event (ticket
  created, status changed, comment added, user/org created, etc.) to a
  registered webhook

Authentication: API token via HTTP Basic auth, username `{email}/token`,
password = the API token. The account subdomain is required and forms the
base URL `https://{subdomain}.zendesk.com/api/v2`.

API Base URL: https://{subdomain}.zendesk.com/api/v2
Documentation: https://developer.zendesk.com/api-reference/

The subdomain is account-specific and not discoverable from the token alone,
so it is collected as a credential field alongside the email + token.
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator, create_model
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import guarded_async_client, normalize_provider_subdomain
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.scopes.zendesk import ZENDESK_SCOPES

logger = logging.getLogger(__name__)

# Zendesk webhook event types the trigger can subscribe to. Zendesk delivers
# events to a webhook via native object event subscriptions, each named with a
# ``zen:event-type:`` prefix. There is no coarse "ticket.updated" event — Zendesk
# instead emits a granular event per field change (status, comment, priority, …),
# so the trigger lets the user pick exactly which one fires the workflow.
#
# (value, human label). Curated to the most useful ticket/user/organization
# lifecycle events; ``*`` is a wildcard meaning "any subscribed ticket event".
WEBHOOK_TRIGGER_EVENT_CHOICES: List[tuple] = [
    ("*", "All ticket events"),
    ("zen:event-type:ticket.created", "Ticket created"),
    ("zen:event-type:ticket.status_changed", "Ticket status changed"),
    ("zen:event-type:ticket.comment_added", "Ticket comment added"),
    ("zen:event-type:ticket.priority_changed", "Ticket priority changed"),
    ("zen:event-type:ticket.agent_assignment_changed", "Ticket agent reassigned"),
    ("zen:event-type:ticket.group_assignment_changed", "Ticket group reassigned"),
    ("zen:event-type:ticket.tags_changed", "Ticket tags changed"),
    ("zen:event-type:ticket.requester_changed", "Ticket requester changed"),
    ("zen:event-type:ticket.organization_changed", "Ticket organization changed"),
    ("zen:event-type:ticket.custom_field_changed", "Ticket custom field changed"),
    ("zen:event-type:ticket.custom_status_changed", "Ticket custom status changed"),
    ("zen:event-type:ticket.type_changed", "Ticket type changed"),
    ("zen:event-type:ticket.subject_changed", "Ticket subject changed"),
    ("zen:event-type:ticket.merged", "Ticket merged"),
    ("zen:event-type:ticket.soft_deleted", "Ticket soft-deleted"),
    ("zen:event-type:ticket.csat_received", "CSAT rating received"),
    ("zen:event-type:user.created", "User created"),
    ("zen:event-type:user.deleted", "User deleted"),
    ("zen:event-type:organization.created", "Organization created"),
    ("zen:event-type:organization.deleted", "Organization deleted"),
]

# Concrete subscription list used when the user picks the "*" wildcard: every
# ticket event in the curated set (the wildcard is a UI convenience, but the
# Webhooks API needs an explicit subscriptions array).
_ALL_TICKET_EVENTS: List[str] = [
    value
    for value, _ in WEBHOOK_TRIGGER_EVENT_CHOICES
    if value.startswith("zen:event-type:ticket.")
]


# Entity-picker fields that should render as searchable dropdowns populated from
# the account. Keyed by config field name → the list endpoint + response key used
# to fetch options. Only bounded, pick-from-a-list resources are included (NOT
# unbounded ones like ticket_id / individual user_id, which stay free-text).
# ``params`` narrows the list (e.g. agents only); ``label`` keys are tried in order.
_DYNAMIC_OPTION_SOURCES: Dict[str, Dict[str, Any]] = {
    "assignee_id": {"endpoint": "/users.json", "params": {"role": "agent"}, "items_key": "users", "noun": "agent"},
    "group_id": {"endpoint": "/groups.json", "items_key": "groups", "noun": "group", "resource_type": "zendesk_group"},
    "organization_id": {"endpoint": "/organizations.json", "items_key": "organizations", "noun": "organization", "resource_type": "zendesk_organization"},
    "brand_id": {"endpoint": "/brands.json", "items_key": "brands", "noun": "brand", "resource_type": "zendesk_brand"},
    "ticket_form_id": {"endpoint": "/ticket_forms.json", "items_key": "ticket_forms", "noun": "ticket form", "resource_type": "zendesk_ticket_form"},
    "macro_id": {"endpoint": "/macros/active.json", "items_key": "macros", "noun": "macro", "resource_type": "zendesk_macro"},
    "view_id": {"endpoint": "/views/active.json", "items_key": "views", "noun": "view", "resource_type": "zendesk_view"},
    "trigger_id": {"endpoint": "/triggers/active.json", "items_key": "triggers", "noun": "trigger", "resource_type": "zendesk_trigger"},
    "automation_id": {"endpoint": "/automations/active.json", "items_key": "automations", "noun": "automation", "resource_type": "zendesk_automation"},
    "sla_policy_id": {"endpoint": "/slas/policies.json", "items_key": "sla_policies", "noun": "SLA policy", "resource_type": "zendesk_sla_policy"},
    "custom_role_id": {"endpoint": "/custom_roles.json", "items_key": "custom_roles", "noun": "custom role", "resource_type": "zendesk_custom_role"},
    "category_id": {"endpoint": "/help_center/categories.json", "items_key": "categories", "noun": "category", "resource_type": "zendesk_category"},
    "ticket_field_id": {"endpoint": "/ticket_fields.json", "items_key": "ticket_fields", "noun": "ticket field", "resource_type": "zendesk_ticket_field"},
    "user_field_id": {"endpoint": "/user_fields.json", "items_key": "user_fields", "noun": "user field", "resource_type": "zendesk_user_field"},
    "organization_field_id": {"endpoint": "/organization_fields.json", "items_key": "organization_fields", "noun": "organization field", "resource_type": "zendesk_organization_field"},
    "webhook_id": {"endpoint": "/webhooks", "items_key": "webhooks", "noun": "webhook", "resource_type": "zendesk_webhook"},
}

_DYNAMIC_OPTION_LABEL_KEYS = ("name", "title", "email", "raw_title", "key")


# ============================================================================
# Credential Schema
# ============================================================================


class ZendeskApiTokenCredential(BaseModel):
    """API token credential for Zendesk (HTTP Basic auth)."""

    credential_type: Literal["zendesk_api_token"] = Field(
        "zendesk_api_token", json_schema_extra={"ui:hidden": True}
    )
    subdomain: str = Field(
        ...,
        title="Subdomain",
        description="Your Zendesk subdomain. For acme.zendesk.com enter 'acme'.",
    )
    email: str = Field(
        ...,
        title="Email",
        description="The email address of the agent/admin who owns the API token",
    )
    api_token: str = Field(
        ...,
        title="API Token",
        description="API token from Admin Center -> Apps and integrations -> APIs -> Zendesk API -> Settings (Token Access)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://support.zendesk.com/hc/en-us/articles/4408889192858-Managing-access-to-the-Zendesk-API",
        }
    )


class ZendeskOAuthCredential(BaseModel):
    """OAuth 2.0 credential for Zendesk (authorization_code flow).

    Tokens are obtained via the OAuth flow, not entered manually. Zendesk OAuth
    is subdomain-scoped, so the subdomain is still required (it forms both the
    OAuth host and the API base URL). Access tokens expire and are auto-refreshed
    via the long-lived refresh token.

    Register an OAuth app at: Admin Center -> Apps and integrations -> APIs ->
    Zendesk API -> OAuth Clients.
    """

    credential_type: Literal["zendesk_oauth"] = Field(
        "zendesk_oauth", json_schema_extra={"ui:hidden": True}
    )
    subdomain: str = Field(
        ...,
        title="Subdomain",
        description="Your Zendesk subdomain. For acme.zendesk.com enter 'acme'.",
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="Zendesk OAuth access token (Bearer).",
        json_schema_extra={"ui:widget": "password"},
    )
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    name: Optional[str] = Field(None, title="User Name")
    email: Optional[str] = Field(None, title="Account Email")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "zendesk",
            # Hidden from the connect UI until Zendesk approves our Marketplace
            # OAuth app — existing OAuth credentials still parse/execute; new
            # connections use the API-token credential above.
            "x-credential-hidden": True,
            "x-oauth-scopes": [
                "read",
                "write",
            ],
            "x-oauth-supports-custom-client": True,
            "x-oauth-custom-client-help": (
                "Optionally bring your own Zendesk OAuth app. Register one in your "
                "Zendesk Admin Center (Apps and integrations -> APIs -> Zendesk API "
                "-> OAuth Clients), set its redirect URL to NoClick's Zendesk "
                "callback, and paste its client ID and secret here. Leave blank to "
                "use NoClick's shared Zendesk app."
            ),
            "x-credential-url": "https://support.zendesk.com/hc/en-us/articles/4408845965210-Using-OAuth-authentication-with-your-application",
        }
    )


class ZendeskConversationsCredential(BaseModel):
    """Sunshine Conversations (Smooch) app-key credential (HTTP Basic auth).

    Distinct from the Support API auth: Sunshine Conversations uses an
    app-scoped API key (Key ID + Secret) against a separate base URL
    (https://{subdomain}.zendesk.com/sc/v2/apps/{app_id}). Only the
    Conversations-category operations use this credential.
    """

    credential_type: Literal["zendesk_conversations"] = Field(
        "zendesk_conversations", json_schema_extra={"ui:hidden": True}
    )
    subdomain: str = Field(
        ...,
        title="Subdomain",
        description="Your Zendesk subdomain. For acme.zendesk.com enter 'acme'.",
    )
    app_id: str = Field(
        ...,
        title="App ID",
        description="Sunshine Conversations App ID (from Admin Center -> Conversations integrations, or the app URL).",
    )
    key_id: str = Field(
        ...,
        title="Key ID",
        description="Sunshine Conversations API key ID (starts with 'app_').",
    )
    secret_key: str = Field(
        ...,
        title="Secret Key",
        description="Sunshine Conversations API secret paired with the Key ID.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://developer.zendesk.com/documentation/conversations/getting-started/api-authentication/",
        }
    )


# OAuth first so it is the default choice when a user adds a credential, with the
# API token as the simplest always-working self-serve path, and the Sunshine
# Conversations app-key for the messaging (Conversations) operations.
ZendeskCredential = Union[
    ZendeskOAuthCredential, ZendeskApiTokenCredential, ZendeskConversationsCredential
]


# ============================================================================
# Operation Configs — Tickets
# ============================================================================


class ZendeskListTicketsConfig(BaseModel):
    """List tickets, optionally sorted."""

    operation: Literal["list_tickets"] = Field(
        "list_tickets",
        json_schema_extra={
            "const": "list_tickets",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "List Tickets",
        },
        title="List Tickets",
    )
    sort_by: Optional[str] = Field(
        None,
        title="Sort By",
        description="Field to sort by",
        json_schema_extra={
            "enum": ["", "created_at", "updated_at", "priority", "status", "ticket_type"],
            "enumNames": ["Default", "Created At", "Updated At", "Priority", "Status", "Type"],
            "x-enum-searchable": True,
        },
    )
    sort_order: Optional[str] = Field(
        None,
        title="Sort Order",
        description="Ascending or descending",
        json_schema_extra={
            "enum": ["", "asc", "desc"],
            "enumNames": ["Default", "Ascending", "Descending"],
            "x-enum-searchable": True,
        },
    )
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Number of tickets per page (max 100)"
    )


class ZendeskShowTicketConfig(BaseModel):
    """Retrieve a single ticket by ID."""

    operation: Literal["show_ticket"] = Field(
        "show_ticket",
        json_schema_extra={
            "const": "show_ticket",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Show Ticket",
        },
        title="Show Ticket",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The ID of the ticket to retrieve")


class ZendeskCreateTicketConfig(BaseModel):
    """Create a new ticket."""

    operation: Literal["create_ticket"] = Field(
        "create_ticket",
        json_schema_extra={
            "const": "create_ticket",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Create Ticket",
        },
        title="Create Ticket",
    )
    subject: str = Field(..., title="Subject", description="The ticket subject")
    comment_body: str = Field(
        ...,
        title="Description",
        description="The first comment / description on the ticket",
        json_schema_extra={"ui:widget": "textarea"},
    )
    requester_email: Optional[str] = Field(
        None,
        title="Requester Email",
        description="Email of the person requesting support (created if new)",
    )
    requester_name: Optional[str] = Field(
        None, title="Requester Name", description="Display name of the requester"
    )
    priority: Optional[str] = Field(
        None,
        title="Priority",
        description="Ticket priority",
        json_schema_extra={
            "enum": ["", "urgent", "high", "normal", "low"],
            "enumNames": ["Default", "Urgent", "High", "Normal", "Low"],
            "x-enum-searchable": True,
        },
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Initial ticket status",
        json_schema_extra={
            "enum": ["", "new", "open", "pending", "hold", "solved", "closed"],
            "enumNames": ["Default", "New", "Open", "Pending", "Hold", "Solved", "Closed"],
            "x-enum-searchable": True,
        },
    )
    ticket_type: Optional[str] = Field(
        None,
        title="Type",
        description="Ticket type",
        json_schema_extra={
            "enum": ["", "problem", "incident", "question", "task"],
            "enumNames": ["Default", "Problem", "Incident", "Question", "Task"],
            "x-enum-searchable": True,
        },
    )
    assignee_id: Optional[str] = Field(
        None,
        title="Assignee",
        description="Agent to assign the ticket to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "assignee_id",
                "placeholder": "Select an agent...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a user ID",
            }
        },
    )
    group_id: Optional[str] = Field(
        None,
        title="Group",
        description="Group to assign the ticket to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "group_id",
                "placeholder": "Select a group...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a group ID",
            }
        },
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated tags to apply to the ticket"
    )
    attachment_tokens: Optional[str] = Field(
        None,
        title="Attachment Tokens",
        description="Comma-separated upload tokens (from Upload File) to attach to the first comment",
    )


class ZendeskUpdateTicketConfig(BaseModel):
    """Update a ticket — change status/assignee/tags or add a comment."""

    operation: Literal["update_ticket"] = Field(
        "update_ticket",
        json_schema_extra={
            "const": "update_ticket",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Update Ticket",
        },
        title="Update Ticket",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The ID of the ticket to update")
    status: Optional[str] = Field(
        None,
        title="Status",
        description="New ticket status",
        json_schema_extra={
            "enum": ["", "new", "open", "pending", "hold", "solved", "closed"],
            "enumNames": ["Unchanged", "New", "Open", "Pending", "Hold", "Solved", "Closed"],
            "x-enum-searchable": True,
        },
    )
    priority: Optional[str] = Field(
        None,
        title="Priority",
        description="New priority",
        json_schema_extra={
            "enum": ["", "urgent", "high", "normal", "low"],
            "enumNames": ["Unchanged", "Urgent", "High", "Normal", "Low"],
            "x-enum-searchable": True,
        },
    )
    assignee_id: Optional[str] = Field(
        None,
        title="Assignee",
        description="Agent to reassign the ticket to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "assignee_id",
                "placeholder": "Select an agent...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a user ID",
            }
        },
    )
    comment_body: Optional[str] = Field(
        None,
        title="Comment",
        description="Add a comment when updating the ticket",
        json_schema_extra={"ui:widget": "textarea"},
    )
    comment_public: Optional[str] = Field(
        "true",
        title="Comment Visibility",
        description="Public (visible to requester) or internal note",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Public reply", "Internal note"],
            "x-enum-searchable": True,
        },
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated tags to set on the ticket"
    )


class ZendeskDeleteTicketConfig(BaseModel):
    """Soft-delete a ticket."""

    operation: Literal["delete_ticket"] = Field(
        "delete_ticket",
        json_schema_extra={
            "const": "delete_ticket",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Delete Ticket",
        },
        title="Delete Ticket",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The ID of the ticket to delete")


class ZendeskCreateManyTicketsConfig(BaseModel):
    """Bulk-create up to 100 tickets (asynchronous; returns a job status)."""

    operation: Literal["create_many_tickets"] = Field(
        "create_many_tickets",
        json_schema_extra={
            "const": "create_many_tickets",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Create Many Tickets",
        },
        title="Create Many Tickets",
    )
    tickets_json: str = Field(
        ...,
        title="Tickets (JSON)",
        description='JSON array of ticket objects, e.g. [{"subject":"...","comment":{"body":"..."}}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateManyTicketsConfig(BaseModel):
    """Bulk-update tickets by IDs (asynchronous; returns a job status)."""

    operation: Literal["update_many_tickets"] = Field(
        "update_many_tickets",
        json_schema_extra={
            "const": "update_many_tickets",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Update Many Tickets",
        },
        title="Update Many Tickets",
    )
    ticket_ids: str = Field(
        ..., title="Ticket IDs", description="Comma-separated ticket IDs to update"
    )
    update_json: str = Field(
        ...,
        title="Update (JSON)",
        description='JSON object of fields to apply to every ticket, e.g. {"status":"solved"}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskMergeTicketsConfig(BaseModel):
    """Merge one or more source tickets into a target ticket."""

    operation: Literal["merge_tickets"] = Field(
        "merge_tickets",
        json_schema_extra={
            "const": "merge_tickets",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Merge Tickets",
        },
        title="Merge Tickets",
    )
    ticket_id: str = Field(
        ..., title="Target Ticket ID", description="The ticket to merge the others into"
    )
    source_ticket_ids: str = Field(
        ...,
        title="Source Ticket IDs",
        description="Comma-separated IDs of tickets to merge into the target",
    )
    target_comment: Optional[str] = Field(
        None,
        title="Target Comment",
        description="Private comment added to the target ticket",
        json_schema_extra={"ui:widget": "textarea"},
    )
    source_comment: Optional[str] = Field(
        None,
        title="Source Comment",
        description="Private comment added to each source ticket",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskListCommentsConfig(BaseModel):
    """List the comments / conversation on a ticket."""

    operation: Literal["list_comments"] = Field(
        "list_comments",
        json_schema_extra={
            "const": "list_comments",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "List Ticket Comments",
        },
        title="List Ticket Comments",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The ID of the ticket")


class ZendeskAddCommentConfig(BaseModel):
    """Reply to a ticket by adding a public or internal comment."""

    operation: Literal["add_comment"] = Field(
        "add_comment",
        json_schema_extra={
            "const": "add_comment",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Add Comment",
        },
        title="Add Comment",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The ID of the ticket to comment on")
    comment_body: str = Field(
        ...,
        title="Comment",
        description="The comment text",
        json_schema_extra={"ui:widget": "textarea"},
    )
    public: Optional[str] = Field(
        "true",
        title="Visibility",
        description="Public reply (visible to requester) or internal note",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Public reply", "Internal note"],
            "x-enum-searchable": True,
        },
    )
    attachment_tokens: Optional[str] = Field(
        None,
        title="Attachment Tokens",
        description="Comma-separated upload tokens (from Upload File) to attach to this comment",
    )


class ZendeskAddTagsConfig(BaseModel):
    """Add tags to a ticket."""

    operation: Literal["add_tags"] = Field(
        "add_tags",
        json_schema_extra={
            "const": "add_tags",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Add Tags",
        },
        title="Add Tags",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The ID of the ticket")
    tags: str = Field(..., title="Tags", description="Comma-separated tags to add")


class ZendeskListAuditsConfig(BaseModel):
    """List the full change history (audits) for a ticket."""

    operation: Literal["list_audits"] = Field(
        "list_audits",
        json_schema_extra={
            "const": "list_audits",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "List Ticket Audits",
        },
        title="List Ticket Audits",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The ID of the ticket")


class ZendeskCountTicketsConfig(BaseModel):
    """Return an approximate count of tickets."""

    operation: Literal["count_tickets"] = Field(
        "count_tickets",
        json_schema_extra={
            "const": "count_tickets",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Count Tickets",
        },
        title="Count Tickets",
    )


# ============================================================================
# Operation Configs — Search
# ============================================================================


class ZendeskSearchConfig(BaseModel):
    """Unified search across tickets, users, organizations, and groups."""

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
    query: str = Field(
        ...,
        title="Query",
        description='Zendesk search syntax, e.g. "type:ticket status:open" or "requester:a@b.com"',
    )


class ZendeskSearchUsersConfig(BaseModel):
    """Find users by name, email, external_id, etc."""

    operation: Literal["search_users"] = Field(
        "search_users",
        json_schema_extra={
            "const": "search_users",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search Users",
        },
        title="Search Users",
    )
    query: str = Field(
        ..., title="Query", description="Search term — name, email, or external_id"
    )


# ============================================================================
# Operation Configs — Users
# ============================================================================


class ZendeskListUsersConfig(BaseModel):
    """List users (agents and end users)."""

    operation: Literal["list_users"] = Field(
        "list_users",
        json_schema_extra={
            "const": "list_users",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "List Users",
        },
        title="List Users",
    )
    role: Optional[str] = Field(
        None,
        title="Role",
        description="Filter by role",
        json_schema_extra={
            "enum": ["", "end-user", "agent", "admin"],
            "enumNames": ["Any", "End User", "Agent", "Admin"],
            "x-enum-searchable": True,
        },
    )


class ZendeskShowUserConfig(BaseModel):
    """Retrieve a single user by ID."""

    operation: Literal["show_user"] = Field(
        "show_user",
        json_schema_extra={
            "const": "show_user",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Show User",
        },
        title="Show User",
    )
    user_id: str = Field(..., title="User ID", description="The ID of the user to retrieve")


class ZendeskCreateUserConfig(BaseModel):
    """Create an end user or agent."""

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
    name: str = Field(..., title="Name", description="The user's display name")
    email: str = Field(..., title="Email", description="The user's email address")
    role: Optional[str] = Field(
        None,
        title="Role",
        description="The user's role",
        json_schema_extra={
            "enum": ["", "end-user", "agent", "admin"],
            "enumNames": ["End User", "End User", "Agent", "Admin"],
            "x-enum-searchable": True,
        },
    )
    phone: Optional[str] = Field(None, title="Phone", description="The user's phone number")


class ZendeskCreateOrUpdateUserConfig(BaseModel):
    """Upsert a user by email / external_id (idempotent create)."""

    operation: Literal["create_or_update_user"] = Field(
        "create_or_update_user",
        json_schema_extra={
            "const": "create_or_update_user",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Create or Update User",
        },
        title="Create or Update User",
    )
    name: str = Field(..., title="Name", description="The user's display name")
    email: str = Field(..., title="Email", description="The user's email address (match key)")
    role: Optional[str] = Field(
        None,
        title="Role",
        description="The user's role",
        json_schema_extra={
            "enum": ["", "end-user", "agent", "admin"],
            "enumNames": ["End User", "End User", "Agent", "Admin"],
            "x-enum-searchable": True,
        },
    )


class ZendeskUpdateUserConfig(BaseModel):
    """Update attributes of an existing user."""

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
    user_id: str = Field(..., title="User ID", description="The ID of the user to update")
    name: Optional[str] = Field(None, title="Name", description="New display name")
    email: Optional[str] = Field(None, title="Email", description="New email address")
    phone: Optional[str] = Field(None, title="Phone", description="New phone number")
    notes: Optional[str] = Field(
        None, title="Notes", description="Agent-only notes about the user",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteUserConfig(BaseModel):
    """Soft-delete a user."""

    operation: Literal["delete_user"] = Field(
        "delete_user",
        json_schema_extra={
            "const": "delete_user",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Delete User",
        },
        title="Delete User",
    )
    user_id: str = Field(..., title="User ID", description="The ID of the user to delete")


# ============================================================================
# Operation Configs — Organizations
# ============================================================================


class ZendeskListOrganizationsConfig(BaseModel):
    """List organizations."""

    operation: Literal["list_organizations"] = Field(
        "list_organizations",
        json_schema_extra={
            "const": "list_organizations",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "List Organizations",
        },
        title="List Organizations",
    )


class ZendeskCreateOrganizationConfig(BaseModel):
    """Create an organization."""

    operation: Literal["create_organization"] = Field(
        "create_organization",
        json_schema_extra={
            "const": "create_organization",
            "x-creates-resource": True,
            "x-resource-type": "zendesk_organization",
            "x-resource-id-path": "data.organization.id",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Create Organization",
        },
        title="Create Organization",
    )
    name: str = Field(..., title="Name", description="The organization name")
    domain_names: Optional[str] = Field(
        None,
        title="Domain Names",
        description="Comma-separated email domains that map users to this organization",
    )
    notes: Optional[str] = Field(
        None, title="Notes", description="Notes about the organization",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateOrganizationConfig(BaseModel):
    """Update an organization."""

    operation: Literal["update_organization"] = Field(
        "update_organization",
        json_schema_extra={
            "const": "update_organization",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Update Organization",
        },
        title="Update Organization",
    )
    organization_id: str = Field(
        ..., title="Organization ID", description="The ID of the organization to update"
    )
    name: Optional[str] = Field(None, title="Name", description="New organization name")
    domain_names: Optional[str] = Field(
        None, title="Domain Names", description="Comma-separated email domains"
    )
    notes: Optional[str] = Field(
        None, title="Notes", description="Notes about the organization",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteOrganizationConfig(BaseModel):
    """Delete an organization."""

    operation: Literal["delete_organization"] = Field(
        "delete_organization",
        json_schema_extra={
            "const": "delete_organization",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Delete Organization",
        },
        title="Delete Organization",
    )
    organization_id: str = Field(
        ..., title="Organization ID", description="The ID of the organization to delete"
    )


# ============================================================================
# Operation Configs — Metadata
# ============================================================================


class ZendeskListGroupsConfig(BaseModel):
    """List agent groups."""

    operation: Literal["list_groups"] = Field(
        "list_groups",
        json_schema_extra={
            "const": "list_groups",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "List Groups",
        },
        title="List Groups",
    )


class ZendeskListTicketFieldsConfig(BaseModel):
    """List ticket field definitions."""

    operation: Literal["list_ticket_fields"] = Field(
        "list_ticket_fields",
        json_schema_extra={
            "const": "list_ticket_fields",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "List Ticket Fields",
        },
        title="List Ticket Fields",
    )


class ZendeskListSatisfactionRatingsConfig(BaseModel):
    """List CSAT satisfaction ratings on solved tickets."""

    operation: Literal["list_satisfaction_ratings"] = Field(
        "list_satisfaction_ratings",
        json_schema_extra={
            "const": "list_satisfaction_ratings",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "List Satisfaction Ratings",
        },
        title="List Satisfaction Ratings",
    )


class ZendeskShowJobStatusConfig(BaseModel):
    """Poll the status of an async bulk job (create_many / update_many)."""

    operation: Literal["show_job_status"] = Field(
        "show_job_status",
        json_schema_extra={
            "const": "show_job_status",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Show Job Status",
        },
        title="Show Job Status",
    )
    job_id: str = Field(..., title="Job ID", description="The ID of the job to poll")


class ZendeskCreateWebhookConfig(BaseModel):
    """Register a webhook endpoint via the Webhooks API."""

    operation: Literal["create_webhook"] = Field(
        "create_webhook",
        json_schema_extra={
            "const": "create_webhook",
            "x-creates-resource": True,
            "x-resource-type": "zendesk_webhook",
            "x-resource-id-path": "data.webhook.id",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Create Webhook",
        },
        title="Create Webhook",
    )
    name: str = Field(..., title="Name", description="A name for the webhook")
    endpoint: str = Field(..., title="Endpoint URL", description="The URL Zendesk will POST events to")
    subscriptions: Optional[str] = Field(
        "conversation.message.created",
        title="Subscriptions",
        description="Comma-separated event subscriptions, e.g. conversation.message.created",
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class ZendeskWebhookTriggerBase(BaseModel):
    """Shared webhook-trigger config. Each concrete trigger subclass fixes ONE
    Zendesk event via its operation (decomposed so the AI builder can pick a
    specific trigger, rather than one trigger multi-selecting events)."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Zendesk posts the event here. Registered automatically when you connect credentials.",
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


# One decomposed trigger operation per Zendesk event, derived from the curated
# event list. ``on_any_ticket_event`` subscribes to every ticket event; the rest
# subscribe to exactly one. (operation, display, [subscribed event types]).
_TRIGGER_DEFS: List[tuple] = []
for _value, _label in WEBHOOK_TRIGGER_EVENT_CHOICES:
    if _value == "*":
        _TRIGGER_DEFS.append(("on_any_ticket_event", "On Any Ticket Event", list(_ALL_TICKET_EVENTS)))
    else:
        _op = "on_" + _value.replace("zen:event-type:", "").replace(".", "_")
        _TRIGGER_DEFS.append((_op, "On " + _label, [_value]))

# operation -> list of Zendesk event types it subscribes to / fires on.
_TRIGGER_EVENTS: Dict[str, List[str]] = {op: events for op, _, events in _TRIGGER_DEFS}


def _make_trigger_model(operation: str, display: str):
    name = "Zendesk" + "".join(p.capitalize() for p in operation.split("_")) + "Config"
    model = create_model(
        name,
        __base__=ZendeskWebhookTriggerBase,
        operation=(
            Literal[operation],
            Field(
                operation,
                json_schema_extra={
                    "const": operation,
                    "ui:hidden": True,
                    "x-category": None,
                    "x-is-trigger": True,
                    "x-display-name": display,
                },
                title=display,
            ),
        ),
    )
    model.__doc__ = f"Fire the workflow when Zendesk delivers the {display[3:]!r} event."
    return model


# Generate the trigger models and expose each by its class name at module level
# (so tests and external code can import them, e.g. ZendeskOnTicketCreatedConfig).
_TRIGGER_MODELS: Dict[str, type] = {
    op: _make_trigger_model(op, display) for op, display, _ in _TRIGGER_DEFS
}
for _m in _TRIGGER_MODELS.values():
    globals()[_m.__name__] = _m


# ---------------------------------------------------------------------------
# Phase 1: Support / Ticketing completion
# ---------------------------------------------------------------------------


class ZendeskShowManyTicketsConfig(BaseModel):
    """Retrieve multiple tickets by ID in one call."""

    operation: Literal["show_many_tickets"] = Field(
        "show_many_tickets",
        json_schema_extra={
            "const": "show_many_tickets",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Show Many Tickets",
        },
        title="Show Many Tickets",
    )
    ticket_ids: str = Field(
        ..., title="Ticket IDs", description="Comma-separated ticket IDs (max 100)"
    )


class ZendeskDestroyManyTicketsConfig(BaseModel):
    """Bulk-delete tickets by ID (async job)."""

    operation: Literal["destroy_many_tickets"] = Field(
        "destroy_many_tickets",
        json_schema_extra={
            "const": "destroy_many_tickets",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Bulk Delete Tickets",
        },
        title="Bulk Delete Tickets",
    )
    ticket_ids: str = Field(
        ..., title="Ticket IDs", description="Comma-separated ticket IDs (max 100)"
    )


class ZendeskMarkTicketAsSpamConfig(BaseModel):
    """Mark a ticket as spam and suspend its requester."""

    operation: Literal["mark_ticket_as_spam"] = Field(
        "mark_ticket_as_spam",
        json_schema_extra={
            "const": "mark_ticket_as_spam",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Mark Ticket as Spam",
        },
        title="Mark Ticket as Spam",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The ticket to mark as spam")


class ZendeskListOrganizationTicketsConfig(BaseModel):
    """List tickets belonging to an organization."""

    operation: Literal["list_organization_tickets"] = Field(
        "list_organization_tickets",
        json_schema_extra={
            "const": "list_organization_tickets",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "List Organization Tickets",
        },
        title="List Organization Tickets",
    )
    organization_id: str = Field(
        ..., title="Organization ID", description="The organization whose tickets to list"
    )


class ZendeskListUserTicketsConfig(BaseModel):
    """List tickets requested by, assigned to, or CC'd to a user."""

    operation: Literal["list_user_tickets"] = Field(
        "list_user_tickets",
        json_schema_extra={
            "const": "list_user_tickets",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "List User Tickets",
        },
        title="List User Tickets",
    )
    user_id: str = Field(..., title="User ID", description="The user whose tickets to list")
    relation: str = Field(
        "requested",
        title="Relation",
        description="Which of the user's tickets to list",
        json_schema_extra={
            "enum": ["requested", "assigned", "ccd"],
            "enumNames": ["Requested", "Assigned", "CC'd"],
            "x-enum-searchable": True,
        },
    )


class ZendeskListTicketTagsConfig(BaseModel):
    """List the tags on a ticket."""

    operation: Literal["list_ticket_tags"] = Field(
        "list_ticket_tags",
        json_schema_extra={
            "const": "list_ticket_tags",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "List Ticket Tags",
        },
        title="List Ticket Tags",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The ticket to read tags from")


class ZendeskSetTicketTagsConfig(BaseModel):
    """Replace all tags on a ticket."""

    operation: Literal["set_ticket_tags"] = Field(
        "set_ticket_tags",
        json_schema_extra={
            "const": "set_ticket_tags",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Set Ticket Tags",
        },
        title="Set Ticket Tags",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The ticket to set tags on")
    tags: str = Field(
        ..., title="Tags", description="Comma-separated tags that replace the ticket's current tags"
    )


class ZendeskRemoveTicketTagsConfig(BaseModel):
    """Remove specific tags from a ticket."""

    operation: Literal["remove_ticket_tags"] = Field(
        "remove_ticket_tags",
        json_schema_extra={
            "const": "remove_ticket_tags",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Remove Ticket Tags",
        },
        title="Remove Ticket Tags",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The ticket to remove tags from")
    tags: str = Field(..., title="Tags", description="Comma-separated tags to remove")


class ZendeskMakeCommentPrivateConfig(BaseModel):
    """Convert a public ticket comment into an internal (private) note."""

    operation: Literal["make_comment_private"] = Field(
        "make_comment_private",
        json_schema_extra={
            "const": "make_comment_private",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Make Comment Private",
        },
        title="Make Comment Private",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The ticket the comment belongs to")
    comment_id: str = Field(..., title="Comment ID", description="The comment to make private")


class ZendeskCreateSatisfactionRatingConfig(BaseModel):
    """Create a satisfaction rating on a solved ticket."""

    operation: Literal["create_satisfaction_rating"] = Field(
        "create_satisfaction_rating",
        json_schema_extra={
            "const": "create_satisfaction_rating",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Create Satisfaction Rating",
        },
        title="Create Satisfaction Rating",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The solved ticket to rate")
    score: str = Field(
        "good",
        title="Score",
        description="Satisfaction score",
        json_schema_extra={
            "enum": ["good", "bad", "good_with_comment", "bad_with_comment", "offered", "unoffered"],
            "x-enum-searchable": True,
        },
    )
    comment: Optional[str] = Field(
        None, title="Comment", description="Optional free-text comment on the rating"
    )


class ZendeskListIncrementalTicketsConfig(BaseModel):
    """Cursor-based incremental export of tickets changed since a start time."""

    operation: Literal["list_incremental_tickets"] = Field(
        "list_incremental_tickets",
        json_schema_extra={
            "const": "list_incremental_tickets",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Incremental Ticket Export",
        },
        title="Incremental Ticket Export",
    )
    start_time: Optional[str] = Field(
        None,
        title="Start Time (Unix)",
        description="Unix epoch seconds; returns tickets changed at/after this time. Omit when paging with a cursor.",
    )
    cursor: Optional[str] = Field(
        None,
        title="Cursor",
        description="after_cursor from a previous response, to fetch the next page",
    )


class ZendeskUploadFileConfig(BaseModel):
    """Upload a file from a URL to Zendesk and return an attachment token.

    The returned ``upload.token`` can be passed to Create Ticket or Add Comment
    (their Attachment Tokens field) to attach the file to a ticket comment.
    """

    operation: Literal["upload_file"] = Field(
        "upload_file",
        json_schema_extra={
            "const": "upload_file",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Upload File (Attachment)",
        },
        title="Upload File (Attachment)",
    )
    file_url: str = Field(
        ..., title="File URL", description="Publicly fetchable URL of the file to upload"
    )
    filename: Optional[str] = Field(
        None, title="Filename", description="Filename to store in Zendesk (defaults to the URL's basename)"
    )
    token: Optional[str] = Field(
        None,
        title="Append to Token",
        description="Optional existing upload token to append this file to (multiple attachments in one comment)",
    )


# ---------------------------------------------------------------------------
# Family: users-core
# ---------------------------------------------------------------------------


class ZendeskShowManyUsersConfig(BaseModel):
    """Retrieve multiple users at once by ID or external ID."""

    operation: Literal["show_many_users"] = Field(
        "show_many_users",
        json_schema_extra={
            "const": "show_many_users",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Show Many Users",
        },
        title="Show Many Users",
    )
    ids: Optional[str] = Field(
        None,
        title="User IDs",
        description="Comma-separated user IDs to fetch (use this OR External IDs)",
    )
    external_ids: Optional[str] = Field(
        None,
        title="External IDs",
        description="Comma-separated external IDs to fetch (use this OR User IDs)",
    )


class ZendeskCreateManyUsersConfig(BaseModel):
    """Bulk-create up to 100 users (asynchronous; returns a job status)."""

    operation: Literal["create_many_users"] = Field(
        "create_many_users",
        json_schema_extra={
            "const": "create_many_users",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Create Many Users",
        },
        title="Create Many Users",
    )
    users_json: str = Field(
        ...,
        title="Users (JSON)",
        description='JSON array of user objects, e.g. [{"name":"...","email":"..."}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskCreateOrUpdateManyUsersConfig(BaseModel):
    """Bulk upsert up to 100 users by email / external_id (asynchronous; returns a job status)."""

    operation: Literal["create_or_update_many_users"] = Field(
        "create_or_update_many_users",
        json_schema_extra={
            "const": "create_or_update_many_users",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Create or Update Many Users",
        },
        title="Create or Update Many Users",
    )
    users_json: str = Field(
        ...,
        title="Users (JSON)",
        description='JSON array of user objects with a match key, e.g. [{"email":"...","name":"..."}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateManyUsersConfig(BaseModel):
    """Bulk-update users (asynchronous; returns a job status)."""

    operation: Literal["update_many_users"] = Field(
        "update_many_users",
        json_schema_extra={
            "const": "update_many_users",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Update Many Users",
        },
        title="Update Many Users",
    )
    ids: Optional[str] = Field(
        None,
        title="User IDs",
        description="Comma-separated user IDs. When set, the Update JSON object is applied to every listed user.",
    )
    users_json: str = Field(
        ...,
        title="Users (JSON)",
        description=(
            "When User IDs is empty: a JSON array of user objects each containing an id, "
            'e.g. [{"id":123,"name":"..."}]. When User IDs is set: a single JSON object of fields '
            'to apply to all, e.g. {"organization_id":456}.'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskBulkDeleteUsersConfig(BaseModel):
    """Bulk soft-delete up to 100 users by ID or external ID (asynchronous; returns a job status)."""

    operation: Literal["bulk_delete_users"] = Field(
        "bulk_delete_users",
        json_schema_extra={
            "const": "bulk_delete_users",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Bulk Delete Users",
        },
        title="Bulk Delete Users",
    )
    ids: Optional[str] = Field(
        None,
        title="User IDs",
        description="Comma-separated user IDs to delete (use this OR External IDs)",
    )
    external_ids: Optional[str] = Field(
        None,
        title="External IDs",
        description="Comma-separated external IDs to delete (use this OR User IDs)",
    )


class ZendeskPermanentlyDeleteUserConfig(BaseModel):
    """Permanently delete a user that has already been soft-deleted."""

    operation: Literal["permanently_delete_user"] = Field(
        "permanently_delete_user",
        json_schema_extra={
            "const": "permanently_delete_user",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Permanently Delete User",
        },
        title="Permanently Delete User",
    )
    user_id: str = Field(
        ..., title="User ID", description="The ID of the already soft-deleted user to purge"
    )


class ZendeskMergeEndUsersConfig(BaseModel):
    """Merge one end user into another end user."""

    operation: Literal["merge_end_users"] = Field(
        "merge_end_users",
        json_schema_extra={
            "const": "merge_end_users",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Merge End Users",
        },
        title="Merge End Users",
    )
    user_id: str = Field(
        ...,
        title="Source User ID",
        description="The end user to merge and delete (its data moves to the target)",
    )
    target_user_id: str = Field(
        ...,
        title="Target User ID",
        description="The winning end user that survives the merge",
    )


class ZendeskAutocompleteUsersConfig(BaseModel):
    """Find users whose name or email starts with a partial string."""

    operation: Literal["autocomplete_users"] = Field(
        "autocomplete_users",
        json_schema_extra={
            "const": "autocomplete_users",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Autocomplete Users",
        },
        title="Autocomplete Users",
    )
    name: str = Field(
        ...,
        title="Name",
        description="Partial name or email to match (minimum 2 characters)",
    )


class ZendeskCountUsersConfig(BaseModel):
    """Return the total number of users, optionally filtered by role."""

    operation: Literal["count_users"] = Field(
        "count_users",
        json_schema_extra={
            "const": "count_users",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Count Users",
        },
        title="Count Users",
    )
    role: Optional[str] = Field(
        None,
        title="Role",
        description="Filter the count by role",
        json_schema_extra={
            "enum": ["", "end-user", "agent", "admin"],
            "enumNames": ["Any", "End User", "Agent", "Admin"],
            "x-enum-searchable": True,
        },
    )


class ZendeskShowUserRelatedConfig(BaseModel):
    """Retrieve a user's related counts (tickets, entries, etc.)."""

    operation: Literal["show_user_related"] = Field(
        "show_user_related",
        json_schema_extra={
            "const": "show_user_related",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Show User Related",
        },
        title="Show User Related",
    )
    user_id: str = Field(
        ..., title="User ID", description="The ID of the user to read related information for"
    )


class ZendeskShowSelfConfig(BaseModel):
    """Retrieve the user tied to the current API credentials."""

    operation: Literal["show_self"] = Field(
        "show_self",
        json_schema_extra={
            "const": "show_self",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Show Self",
        },
        title="Show Self",
    )


class ZendeskListUsersByGroupConfig(BaseModel):
    """List the users that belong to a group."""

    operation: Literal["list_users_by_group"] = Field(
        "list_users_by_group",
        json_schema_extra={
            "const": "list_users_by_group",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "List Users by Group",
        },
        title="List Users by Group",
    )
    group_id: str = Field(
        ..., title="Group ID", description="The ID of the group whose users to list"
    )


class ZendeskListUsersByOrganizationConfig(BaseModel):
    """List the users that belong to an organization."""

    operation: Literal["list_users_by_organization"] = Field(
        "list_users_by_organization",
        json_schema_extra={
            "const": "list_users_by_organization",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "List Users by Organization",
        },
        title="List Users by Organization",
    )
    organization_id: str = Field(
        ...,
        title="Organization ID",
        description="The ID of the organization whose users to list",
    )


# ---------------------------------------------------------------------------
# Family: user-identities-fields
# ---------------------------------------------------------------------------


class ZendeskListIdentitiesConfig(BaseModel):
    """List all identities (email/phone) for a user."""

    operation: Literal["list_identities"] = Field(
        "list_identities",
        json_schema_extra={
            "const": "list_identities",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "List User Identities",
        },
        title="List User Identities",
    )
    user_id: str = Field(..., title="User ID", description="The user whose identities to list")


class ZendeskShowIdentityConfig(BaseModel):
    """Show a single identity on a user."""

    operation: Literal["show_identity"] = Field(
        "show_identity",
        json_schema_extra={
            "const": "show_identity",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Show User Identity",
        },
        title="Show User Identity",
    )
    user_id: str = Field(..., title="User ID", description="The user that owns the identity")
    identity_id: str = Field(..., title="Identity ID", description="The identity to show")


class ZendeskCreateIdentityConfig(BaseModel):
    """Add an email or phone identity to a user."""

    operation: Literal["create_identity"] = Field(
        "create_identity",
        json_schema_extra={
            "const": "create_identity",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Create User Identity",
        },
        title="Create User Identity",
    )
    user_id: str = Field(..., title="User ID", description="The user to add the identity to")
    identity_type: str = Field(
        "email",
        title="Identity Type",
        description="The kind of identity to create",
        json_schema_extra={
            "enum": ["email", "phone_number"],
            "enumNames": ["Email", "Phone Number"],
            "x-enum-searchable": True,
        },
    )
    value: str = Field(..., title="Value", description="The email address or phone number")
    verified: Optional[str] = Field(
        None,
        title="Mark Verified",
        description="Create the identity already verified (requires admin)",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Default", "Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    primary: Optional[str] = Field(
        None,
        title="Primary",
        description="Make this the user's primary identity",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Default", "Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class ZendeskUpdateIdentityConfig(BaseModel):
    """Update the value or verification state of a user identity."""

    operation: Literal["update_identity"] = Field(
        "update_identity",
        json_schema_extra={
            "const": "update_identity",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Update User Identity",
        },
        title="Update User Identity",
    )
    user_id: str = Field(..., title="User ID", description="The user that owns the identity")
    identity_id: str = Field(..., title="Identity ID", description="The identity to update")
    value: Optional[str] = Field(None, title="Value", description="New email address or phone number")
    verified: Optional[str] = Field(
        None,
        title="Verified",
        description="Set the identity's verified state",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Unchanged", "Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class ZendeskDeleteIdentityConfig(BaseModel):
    """Delete an identity from a user."""

    operation: Literal["delete_identity"] = Field(
        "delete_identity",
        json_schema_extra={
            "const": "delete_identity",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Delete User Identity",
        },
        title="Delete User Identity",
    )
    user_id: str = Field(..., title="User ID", description="The user that owns the identity")
    identity_id: str = Field(..., title="Identity ID", description="The identity to delete")


class ZendeskMakeIdentityPrimaryConfig(BaseModel):
    """Make an identity the user's primary identity."""

    operation: Literal["make_identity_primary"] = Field(
        "make_identity_primary",
        json_schema_extra={
            "const": "make_identity_primary",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Make Identity Primary",
        },
        title="Make Identity Primary",
    )
    user_id: str = Field(..., title="User ID", description="The user that owns the identity")
    identity_id: str = Field(..., title="Identity ID", description="The identity to promote to primary")


class ZendeskVerifyIdentityConfig(BaseModel):
    """Mark an identity as verified without sending a verification email."""

    operation: Literal["verify_identity"] = Field(
        "verify_identity",
        json_schema_extra={
            "const": "verify_identity",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Verify Identity",
        },
        title="Verify Identity",
    )
    user_id: str = Field(..., title="User ID", description="The user that owns the identity")
    identity_id: str = Field(..., title="Identity ID", description="The identity to mark verified")


class ZendeskRequestIdentityVerificationConfig(BaseModel):
    """Send the user a verification email/text for an identity."""

    operation: Literal["request_identity_verification"] = Field(
        "request_identity_verification",
        json_schema_extra={
            "const": "request_identity_verification",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Request Identity Verification",
        },
        title="Request Identity Verification",
    )
    user_id: str = Field(..., title="User ID", description="The user that owns the identity")
    identity_id: str = Field(..., title="Identity ID", description="The identity to request verification for")


class ZendeskListUserFieldsConfig(BaseModel):
    """List all custom user fields."""

    operation: Literal["list_user_fields"] = Field(
        "list_user_fields",
        json_schema_extra={
            "const": "list_user_fields",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "List User Fields",
        },
        title="List User Fields",
    )


class ZendeskShowUserFieldConfig(BaseModel):
    """Show a single custom user field."""

    operation: Literal["show_user_field"] = Field(
        "show_user_field",
        json_schema_extra={
            "const": "show_user_field",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Show User Field",
        },
        title="Show User Field",
    )
    user_field_id: str = Field(..., title="User Field ID", description="The custom user field to show")


class ZendeskCreateUserFieldConfig(BaseModel):
    """Create a custom user field."""

    operation: Literal["create_user_field"] = Field(
        "create_user_field",
        json_schema_extra={
            "const": "create_user_field",
            "x-creates-resource": True,
            "x-resource-type": "zendesk_user_field",
            "x-resource-id-path": "data.user_field.id",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Create User Field",
        },
        title="Create User Field",
    )
    field_type: str = Field(
        "text",
        title="Field Type",
        description="The data type of the custom field",
        json_schema_extra={
            "enum": [
                "text", "textarea", "checkbox", "date", "integer", "decimal",
                "regexp", "dropdown", "multiselect", "lookup",
            ],
            "enumNames": [
                "Text", "Multi-line Text", "Checkbox", "Date", "Integer", "Decimal",
                "Regex", "Dropdown", "Multi-select", "Lookup",
            ],
            "x-enum-searchable": True,
        },
    )
    title: str = Field(..., title="Title", description="The title shown to agents")
    key: str = Field(
        ...,
        title="Key",
        description="Unique key (letters, numbers, underscores; not purely numeric)",
    )
    description: Optional[str] = Field(
        None, title="Description", description="Optional description of the field",
        json_schema_extra={"ui:widget": "textarea"},
    )
    custom_field_options_json: Optional[str] = Field(
        None,
        title="Options JSON",
        description='For dropdown/multiselect: JSON array like [{"name":"Label","value":"val"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateUserFieldConfig(BaseModel):
    """Update a custom user field."""

    operation: Literal["update_user_field"] = Field(
        "update_user_field",
        json_schema_extra={
            "const": "update_user_field",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Update User Field",
        },
        title="Update User Field",
    )
    user_field_id: str = Field(..., title="User Field ID", description="The custom user field to update")
    title: Optional[str] = Field(None, title="Title", description="New title")
    description: Optional[str] = Field(
        None, title="Description", description="New description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    active: Optional[str] = Field(
        None,
        title="Active",
        description="Whether the field is active",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Unchanged", "Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class ZendeskDeleteUserFieldConfig(BaseModel):
    """Delete a custom user field."""

    operation: Literal["delete_user_field"] = Field(
        "delete_user_field",
        json_schema_extra={
            "const": "delete_user_field",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Delete User Field",
        },
        title="Delete User Field",
    )
    user_field_id: str = Field(..., title="User Field ID", description="The custom user field to delete")


class ZendeskListUserFieldOptionsConfig(BaseModel):
    """List the dropdown options of a custom user field."""

    operation: Literal["list_user_field_options"] = Field(
        "list_user_field_options",
        json_schema_extra={
            "const": "list_user_field_options",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "List User Field Options",
        },
        title="List User Field Options",
    )
    user_field_id: str = Field(..., title="User Field ID", description="The dropdown/multiselect user field")


class ZendeskCreateUserFieldOptionConfig(BaseModel):
    """Add an option to a dropdown/multiselect user field."""

    operation: Literal["create_user_field_option"] = Field(
        "create_user_field_option",
        json_schema_extra={
            "const": "create_user_field_option",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Create User Field Option",
        },
        title="Create User Field Option",
    )
    user_field_id: str = Field(..., title="User Field ID", description="The dropdown/multiselect user field")
    name: str = Field(..., title="Name", description="The display name of the option")
    value: str = Field(..., title="Value", description="The stored value of the option")


class ZendeskUpdateUserFieldOptionConfig(BaseModel):
    """Update an existing option on a user field."""

    operation: Literal["update_user_field_option"] = Field(
        "update_user_field_option",
        json_schema_extra={
            "const": "update_user_field_option",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Update User Field Option",
        },
        title="Update User Field Option",
    )
    user_field_id: str = Field(..., title="User Field ID", description="The dropdown/multiselect user field")
    option_id: str = Field(..., title="Option ID", description="The option to update")
    name: str = Field(..., title="Name", description="New display name")
    value: str = Field(..., title="Value", description="New stored value")


class ZendeskDeleteUserFieldOptionConfig(BaseModel):
    """Delete an option from a user field."""

    operation: Literal["delete_user_field_option"] = Field(
        "delete_user_field_option",
        json_schema_extra={
            "const": "delete_user_field_option",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Delete User Field Option",
        },
        title="Delete User Field Option",
    )
    user_field_id: str = Field(..., title="User Field ID", description="The dropdown/multiselect user field")
    option_id: str = Field(..., title="Option ID", description="The option to delete")


# ---------------------------------------------------------------------------
# Family: orgs-extended
# ---------------------------------------------------------------------------


class ZendeskShowOrganizationConfig(BaseModel):
    """Show a single organization by ID."""

    operation: Literal["show_organization"] = Field(
        "show_organization",
        json_schema_extra={
            "const": "show_organization",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Show Organization",
        },
        title="Show Organization",
    )
    organization_id: str = Field(
        ..., title="Organization ID", description="The ID of the organization to show"
    )


class ZendeskShowManyOrganizationsConfig(BaseModel):
    """Show many organizations by IDs or external IDs (up to 100)."""

    operation: Literal["show_many_organizations"] = Field(
        "show_many_organizations",
        json_schema_extra={
            "const": "show_many_organizations",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Show Many Organizations",
        },
        title="Show Many Organizations",
    )
    organization_ids: Optional[str] = Field(
        None,
        title="Organization IDs",
        description="Comma-separated organization IDs (up to 100). Use this OR External IDs",
    )
    external_ids: Optional[str] = Field(
        None,
        title="External IDs",
        description="Comma-separated external IDs (up to 100). Use this OR Organization IDs",
    )


class ZendeskCreateManyOrganizationsConfig(BaseModel):
    """Create many organizations in one background job (up to 100)."""

    operation: Literal["create_many_organizations"] = Field(
        "create_many_organizations",
        json_schema_extra={
            "const": "create_many_organizations",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Create Many Organizations",
        },
        title="Create Many Organizations",
    )
    organizations_json: str = Field(
        ...,
        title="Organizations JSON",
        description='A JSON array of organization objects, e.g. [{"name": "Acme"}, {"name": "Globex"}] (up to 100)',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskCreateOrUpdateOrganizationConfig(BaseModel):
    """Create an organization, or update it if one already exists with the same name or external ID."""

    operation: Literal["create_or_update_organization"] = Field(
        "create_or_update_organization",
        json_schema_extra={
            "const": "create_or_update_organization",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Create Or Update Organization",
        },
        title="Create Or Update Organization",
    )
    name: str = Field(..., title="Name", description="The organization name (used to match an existing organization)")
    external_id: Optional[str] = Field(
        None,
        title="External ID",
        description="A unique external ID used to match an existing organization",
    )
    domain_names: Optional[str] = Field(
        None,
        title="Domain Names",
        description="Comma-separated email domains that map users to this organization",
    )
    notes: Optional[str] = Field(
        None, title="Notes", description="Notes about the organization",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateManyOrganizationsConfig(BaseModel):
    """Apply the same update to many organizations in one background job."""

    operation: Literal["update_many_organizations"] = Field(
        "update_many_organizations",
        json_schema_extra={
            "const": "update_many_organizations",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Update Many Organizations",
        },
        title="Update Many Organizations",
    )
    organization_ids: Optional[str] = Field(
        None,
        title="Organization IDs",
        description="Comma-separated organization IDs to update. Use this OR External IDs",
    )
    external_ids: Optional[str] = Field(
        None,
        title="External IDs",
        description="Comma-separated external IDs to update. Use this OR Organization IDs",
    )
    update_json: str = Field(
        ...,
        title="Update JSON",
        description='A JSON object of organization fields to apply to all matched organizations, e.g. {"notes": "VIP"}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDestroyManyOrganizationsConfig(BaseModel):
    """Bulk delete organizations by ID in one background job (up to 100)."""

    operation: Literal["destroy_many_organizations"] = Field(
        "destroy_many_organizations",
        json_schema_extra={
            "const": "destroy_many_organizations",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Bulk Delete Organizations",
        },
        title="Bulk Delete Organizations",
    )
    organization_ids: str = Field(
        ...,
        title="Organization IDs",
        description="Comma-separated organization IDs to delete (up to 100)",
    )


class ZendeskSearchOrganizationsConfig(BaseModel):
    """Search organizations by external ID, or autocomplete by name prefix."""

    operation: Literal["search_organizations"] = Field(
        "search_organizations",
        json_schema_extra={
            "const": "search_organizations",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Search Organizations",
        },
        title="Search Organizations",
    )
    external_id: Optional[str] = Field(
        None,
        title="External ID",
        description="Exact external ID to search for (uses the organizations search endpoint)",
    )
    name: Optional[str] = Field(
        None,
        title="Name",
        description="Name prefix to autocomplete (min 2 characters; uses the autocomplete endpoint). Ignored if External ID is set",
    )


class ZendeskCountOrganizationsConfig(BaseModel):
    """Count the organizations in the account."""

    operation: Literal["count_organizations"] = Field(
        "count_organizations",
        json_schema_extra={
            "const": "count_organizations",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Count Organizations",
        },
        title="Count Organizations",
    )


class ZendeskRelatedOrganizationsConfig(BaseModel):
    """Show data related to an organization (ticket, user and group counts)."""

    operation: Literal["related_organizations"] = Field(
        "related_organizations",
        json_schema_extra={
            "const": "related_organizations",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Organization Related Information",
        },
        title="Organization Related Information",
    )
    organization_id: str = Field(
        ..., title="Organization ID", description="The organization whose related information to fetch"
    )


class ZendeskMergeOrganizationConfig(BaseModel):
    """Merge one organization into another in a background job."""

    operation: Literal["merge_organization"] = Field(
        "merge_organization",
        json_schema_extra={
            "const": "merge_organization",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Merge Organization",
        },
        title="Merge Organization",
    )
    organization_id: str = Field(
        ...,
        title="Organization ID (merged from)",
        description="The ID of the organization to merge FROM (this organization is deleted after the merge)",
    )
    target_organization_id: str = Field(
        ...,
        title="Target Organization ID (merged into)",
        description="The ID of the winning organization the source is merged INTO",
    )


# ---------------------------------------------------------------------------
# Family: org-fields-memberships
# ---------------------------------------------------------------------------


class ZendeskListOrganizationFieldsConfig(BaseModel):
    """List all organization fields."""

    operation: Literal["list_organization_fields"] = Field(
        "list_organization_fields",
        json_schema_extra={
            "const": "list_organization_fields",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "List Organization Fields",
        },
        title="List Organization Fields",
    )


class ZendeskShowOrganizationFieldConfig(BaseModel):
    """Retrieve a single organization field by ID."""

    operation: Literal["show_organization_field"] = Field(
        "show_organization_field",
        json_schema_extra={
            "const": "show_organization_field",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Show Organization Field",
        },
        title="Show Organization Field",
    )
    field_id: str = Field(..., title="Field ID", description="The ID of the organization field to retrieve")


class ZendeskCreateOrganizationFieldConfig(BaseModel):
    """Create a custom organization field."""

    operation: Literal["create_organization_field"] = Field(
        "create_organization_field",
        json_schema_extra={
            "const": "create_organization_field",
            "x-creates-resource": True,
            "x-resource-type": "zendesk_organization_field",
            "x-resource-id-path": "data.organization_field.id",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Create Organization Field",
        },
        title="Create Organization Field",
    )
    field_type: str = Field(
        ...,
        title="Field Type",
        description="The type of custom field to create",
        json_schema_extra={
            "enum": [
                "text",
                "textarea",
                "checkbox",
                "date",
                "integer",
                "decimal",
                "regexp",
                "dropdown",
                "lookup",
                "multiselect",
            ],
            "enumNames": [
                "Text",
                "Multi-line Text",
                "Checkbox",
                "Date",
                "Integer",
                "Decimal",
                "Regex",
                "Dropdown",
                "Lookup",
                "Multi-select",
            ],
            "x-enum-searchable": True,
        },
    )
    title: str = Field(..., title="Title", description="The title of the organization field")
    key: str = Field(
        ...,
        title="Key",
        description="Unique key (letters, numbers, and underscores only)",
    )
    description: Optional[str] = Field(
        None, title="Description", description="Description of the field's purpose"
    )
    active: Optional[str] = Field(
        None,
        title="Active",
        description="Whether the field is active",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Default", "Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    regexp_for_validation: Optional[str] = Field(
        None,
        title="Regex For Validation",
        description="Regular expression for validation (regexp type only)",
    )
    custom_field_options: Optional[str] = Field(
        None,
        title="Custom Field Options",
        description=(
            "JSON array of options for dropdown/multiselect fields, each "
            '{"name": "...", "value": "..."}'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateOrganizationFieldConfig(BaseModel):
    """Update an existing organization field."""

    operation: Literal["update_organization_field"] = Field(
        "update_organization_field",
        json_schema_extra={
            "const": "update_organization_field",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Update Organization Field",
        },
        title="Update Organization Field",
    )
    field_id: str = Field(..., title="Field ID", description="The ID of the organization field to update")
    title: Optional[str] = Field(None, title="Title", description="New title for the field")
    description: Optional[str] = Field(
        None, title="Description", description="New description for the field"
    )
    active: Optional[str] = Field(
        None,
        title="Active",
        description="Whether the field is active",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Default", "Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    regexp_for_validation: Optional[str] = Field(
        None,
        title="Regex For Validation",
        description="Regular expression for validation (regexp type only)",
    )
    custom_field_options: Optional[str] = Field(
        None,
        title="Custom Field Options",
        description=(
            "JSON array of ALL options for dropdown/multiselect fields (omitted "
            'options are removed), each {"name": "...", "value": "..."}'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteOrganizationFieldConfig(BaseModel):
    """Delete an organization field."""

    operation: Literal["delete_organization_field"] = Field(
        "delete_organization_field",
        json_schema_extra={
            "const": "delete_organization_field",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Delete Organization Field",
        },
        title="Delete Organization Field",
    )
    field_id: str = Field(..., title="Field ID", description="The ID of the organization field to delete")


class ZendeskListOrganizationMembershipsConfig(BaseModel):
    """List all organization memberships."""

    operation: Literal["list_organization_memberships"] = Field(
        "list_organization_memberships",
        json_schema_extra={
            "const": "list_organization_memberships",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "List Organization Memberships",
        },
        title="List Organization Memberships",
    )


class ZendeskListUserOrganizationMembershipsConfig(BaseModel):
    """List the organization memberships for a given user."""

    operation: Literal["list_user_organization_memberships"] = Field(
        "list_user_organization_memberships",
        json_schema_extra={
            "const": "list_user_organization_memberships",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "List User's Organization Memberships",
        },
        title="List User's Organization Memberships",
    )
    user_id: str = Field(..., title="User ID", description="The user whose memberships to list")


class ZendeskShowOrganizationMembershipConfig(BaseModel):
    """Retrieve a single organization membership by ID."""

    operation: Literal["show_organization_membership"] = Field(
        "show_organization_membership",
        json_schema_extra={
            "const": "show_organization_membership",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Show Organization Membership",
        },
        title="Show Organization Membership",
    )
    membership_id: str = Field(
        ..., title="Membership ID", description="The ID of the organization membership to retrieve"
    )


class ZendeskCreateOrganizationMembershipConfig(BaseModel):
    """Add a user to an organization."""

    operation: Literal["create_organization_membership"] = Field(
        "create_organization_membership",
        json_schema_extra={
            "const": "create_organization_membership",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Create Organization Membership",
        },
        title="Create Organization Membership",
    )
    user_id: str = Field(..., title="User ID", description="The user to add to the organization")
    organization_id: str = Field(
        ..., title="Organization ID", description="The organization to add the user to"
    )
    default: Optional[str] = Field(
        None,
        title="Set As Default",
        description="Make this the user's default organization",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Default", "Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class ZendeskCreateManyOrganizationMembershipsConfig(BaseModel):
    """Bulk-create up to 100 organization memberships (async job)."""

    operation: Literal["create_many_organization_memberships"] = Field(
        "create_many_organization_memberships",
        json_schema_extra={
            "const": "create_many_organization_memberships",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Create Many Organization Memberships",
        },
        title="Create Many Organization Memberships",
    )
    memberships_json: str = Field(
        ...,
        title="Memberships JSON",
        description=(
            "JSON array of up to 100 membership objects, each "
            '{"user_id": ..., "organization_id": ..., "default": true|false}'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteOrganizationMembershipConfig(BaseModel):
    """Remove a user from an organization by membership ID."""

    operation: Literal["delete_organization_membership"] = Field(
        "delete_organization_membership",
        json_schema_extra={
            "const": "delete_organization_membership",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Delete Organization Membership",
        },
        title="Delete Organization Membership",
    )
    membership_id: str = Field(
        ..., title="Membership ID", description="The ID of the organization membership to delete"
    )


class ZendeskSetDefaultOrganizationMembershipConfig(BaseModel):
    """Set an organization membership as the user's default."""

    operation: Literal["set_default_organization_membership"] = Field(
        "set_default_organization_membership",
        json_schema_extra={
            "const": "set_default_organization_membership",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Set Default Organization Membership",
        },
        title="Set Default Organization Membership",
    )
    user_id: str = Field(..., title="User ID", description="The user whose default to change")
    membership_id: str = Field(
        ..., title="Membership ID", description="The membership to mark as default"
    )


class ZendeskListOrganizationSubscriptionsConfig(BaseModel):
    """List all organization subscriptions."""

    operation: Literal["list_organization_subscriptions"] = Field(
        "list_organization_subscriptions",
        json_schema_extra={
            "const": "list_organization_subscriptions",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "List Organization Subscriptions",
        },
        title="List Organization Subscriptions",
    )


class ZendeskShowOrganizationSubscriptionConfig(BaseModel):
    """Retrieve a single organization subscription by ID."""

    operation: Literal["show_organization_subscription"] = Field(
        "show_organization_subscription",
        json_schema_extra={
            "const": "show_organization_subscription",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Show Organization Subscription",
        },
        title="Show Organization Subscription",
    )
    subscription_id: str = Field(
        ..., title="Subscription ID", description="The ID of the organization subscription to retrieve"
    )


class ZendeskCreateOrganizationSubscriptionConfig(BaseModel):
    """Subscribe a user to an organization's updates."""

    operation: Literal["create_organization_subscription"] = Field(
        "create_organization_subscription",
        json_schema_extra={
            "const": "create_organization_subscription",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Create Organization Subscription",
        },
        title="Create Organization Subscription",
    )
    user_id: str = Field(..., title="User ID", description="The user to subscribe")
    organization_id: str = Field(
        ..., title="Organization ID", description="The organization to subscribe to"
    )


class ZendeskDeleteOrganizationSubscriptionConfig(BaseModel):
    """Delete an organization subscription."""

    operation: Literal["delete_organization_subscription"] = Field(
        "delete_organization_subscription",
        json_schema_extra={
            "const": "delete_organization_subscription",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Delete Organization Subscription",
        },
        title="Delete Organization Subscription",
    )
    subscription_id: str = Field(
        ..., title="Subscription ID", description="The ID of the organization subscription to delete"
    )


# ---------------------------------------------------------------------------
# Family: groups-roles
# ---------------------------------------------------------------------------


class ZendeskShowGroupConfig(BaseModel):
    """Show a single agent group by ID."""

    operation: Literal["show_group"] = Field(
        "show_group",
        json_schema_extra={
            "const": "show_group",
            "ui:hidden": True,
            "x-category": "Groups",
            "x-is-trigger": False,
            "x-display-name": "Show Group",
        },
        title="Show Group",
    )
    group_id: str = Field(..., title="Group ID", description="The ID of the group to retrieve")


class ZendeskCreateGroupConfig(BaseModel):
    """Create an agent group."""

    operation: Literal["create_group"] = Field(
        "create_group",
        json_schema_extra={
            "const": "create_group",
            "x-creates-resource": True,
            "x-resource-type": "zendesk_group",
            "x-resource-id-path": "data.group.id",
            "ui:hidden": True,
            "x-category": "Groups",
            "x-is-trigger": False,
            "x-display-name": "Create Group",
        },
        title="Create Group",
    )
    name: str = Field(..., title="Name", description="The name of the group")
    description: Optional[str] = Field(
        None, title="Description", description="A description of the group",
        json_schema_extra={"ui:widget": "textarea"},
    )
    is_public: Optional[str] = Field(
        None, title="Public", description="Whether the group is public (visible to all agents)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class ZendeskUpdateGroupConfig(BaseModel):
    """Update an agent group."""

    operation: Literal["update_group"] = Field(
        "update_group",
        json_schema_extra={
            "const": "update_group",
            "ui:hidden": True,
            "x-category": "Groups",
            "x-is-trigger": False,
            "x-display-name": "Update Group",
        },
        title="Update Group",
    )
    group_id: str = Field(..., title="Group ID", description="The ID of the group to update")
    name: Optional[str] = Field(None, title="Name", description="New name for the group")
    description: Optional[str] = Field(
        None, title="Description", description="New description for the group",
        json_schema_extra={"ui:widget": "textarea"},
    )
    is_public: Optional[str] = Field(
        None, title="Public", description="Whether the group is public (cannot change private to public)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class ZendeskDeleteGroupConfig(BaseModel):
    """Delete an agent group."""

    operation: Literal["delete_group"] = Field(
        "delete_group",
        json_schema_extra={
            "const": "delete_group",
            "ui:hidden": True,
            "x-category": "Groups",
            "x-is-trigger": False,
            "x-display-name": "Delete Group",
        },
        title="Delete Group",
    )
    group_id: str = Field(..., title="Group ID", description="The ID of the group to delete")


class ZendeskListAssignableGroupsConfig(BaseModel):
    """List groups that tickets can be assigned to."""

    operation: Literal["list_assignable_groups"] = Field(
        "list_assignable_groups",
        json_schema_extra={
            "const": "list_assignable_groups",
            "ui:hidden": True,
            "x-category": "Groups",
            "x-is-trigger": False,
            "x-display-name": "List Assignable Groups",
        },
        title="List Assignable Groups",
    )


class ZendeskListGroupMembershipsConfig(BaseModel):
    """List all group memberships in the account."""

    operation: Literal["list_group_memberships"] = Field(
        "list_group_memberships",
        json_schema_extra={
            "const": "list_group_memberships",
            "ui:hidden": True,
            "x-category": "Group Memberships",
            "x-is-trigger": False,
            "x-display-name": "List Group Memberships",
        },
        title="List Group Memberships",
    )


class ZendeskListUserGroupMembershipsConfig(BaseModel):
    """List the group memberships for a user."""

    operation: Literal["list_user_group_memberships"] = Field(
        "list_user_group_memberships",
        json_schema_extra={
            "const": "list_user_group_memberships",
            "ui:hidden": True,
            "x-category": "Group Memberships",
            "x-is-trigger": False,
            "x-display-name": "List User's Group Memberships",
        },
        title="List User's Group Memberships",
    )
    user_id: str = Field(..., title="User ID", description="The ID of the user whose memberships to list")


class ZendeskListGroupMembershipsByGroupConfig(BaseModel):
    """List the memberships of a group."""

    operation: Literal["list_group_memberships_by_group"] = Field(
        "list_group_memberships_by_group",
        json_schema_extra={
            "const": "list_group_memberships_by_group",
            "ui:hidden": True,
            "x-category": "Group Memberships",
            "x-is-trigger": False,
            "x-display-name": "List Memberships by Group",
        },
        title="List Memberships by Group",
    )
    group_id: str = Field(..., title="Group ID", description="The ID of the group whose memberships to list")


class ZendeskShowGroupMembershipConfig(BaseModel):
    """Show a single group membership by ID."""

    operation: Literal["show_group_membership"] = Field(
        "show_group_membership",
        json_schema_extra={
            "const": "show_group_membership",
            "ui:hidden": True,
            "x-category": "Group Memberships",
            "x-is-trigger": False,
            "x-display-name": "Show Group Membership",
        },
        title="Show Group Membership",
    )
    group_membership_id: str = Field(
        ..., title="Membership ID", description="The ID of the group membership to retrieve"
    )


class ZendeskCreateGroupMembershipConfig(BaseModel):
    """Assign a user to a group by creating a group membership."""

    operation: Literal["create_group_membership"] = Field(
        "create_group_membership",
        json_schema_extra={
            "const": "create_group_membership",
            "ui:hidden": True,
            "x-category": "Group Memberships",
            "x-is-trigger": False,
            "x-display-name": "Create Group Membership",
        },
        title="Create Group Membership",
    )
    user_id: str = Field(..., title="User ID", description="The ID of the user (agent) to add")
    group_id: str = Field(..., title="Group ID", description="The ID of the group to add the user to")
    default: Optional[str] = Field(
        None, title="Default", description="Whether this is the user's default group",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class ZendeskCreateManyGroupMembershipsConfig(BaseModel):
    """Bulk-create up to 100 group memberships. Returns an async job status."""

    operation: Literal["create_many_group_memberships"] = Field(
        "create_many_group_memberships",
        json_schema_extra={
            "const": "create_many_group_memberships",
            "ui:hidden": True,
            "x-category": "Group Memberships",
            "x-is-trigger": False,
            "x-display-name": "Create Many Group Memberships",
        },
        title="Create Many Group Memberships",
    )
    memberships_json: str = Field(
        ...,
        title="Memberships JSON",
        description='A JSON array of membership objects, e.g. [{"user_id": 72, "group_id": 88}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteGroupMembershipConfig(BaseModel):
    """Delete a group membership, removing a user from a group."""

    operation: Literal["delete_group_membership"] = Field(
        "delete_group_membership",
        json_schema_extra={
            "const": "delete_group_membership",
            "ui:hidden": True,
            "x-category": "Group Memberships",
            "x-is-trigger": False,
            "x-display-name": "Delete Group Membership",
        },
        title="Delete Group Membership",
    )
    group_membership_id: str = Field(
        ..., title="Membership ID", description="The ID of the group membership to delete"
    )


class ZendeskSetDefaultGroupMembershipConfig(BaseModel):
    """Set a group membership as the user's default group."""

    operation: Literal["set_default_group_membership"] = Field(
        "set_default_group_membership",
        json_schema_extra={
            "const": "set_default_group_membership",
            "ui:hidden": True,
            "x-category": "Group Memberships",
            "x-is-trigger": False,
            "x-display-name": "Set Default Group Membership",
        },
        title="Set Default Group Membership",
    )
    user_id: str = Field(..., title="User ID", description="The ID of the user")
    group_membership_id: str = Field(
        ..., title="Membership ID", description="The ID of the membership to make default"
    )


class ZendeskListAssignableGroupMembershipsConfig(BaseModel):
    """List group memberships that are assignable."""

    operation: Literal["list_assignable_group_memberships"] = Field(
        "list_assignable_group_memberships",
        json_schema_extra={
            "const": "list_assignable_group_memberships",
            "ui:hidden": True,
            "x-category": "Group Memberships",
            "x-is-trigger": False,
            "x-display-name": "List Assignable Memberships",
        },
        title="List Assignable Memberships",
    )


class ZendeskListCustomRolesConfig(BaseModel):
    """List the custom agent roles in the account."""

    operation: Literal["list_custom_roles"] = Field(
        "list_custom_roles",
        json_schema_extra={
            "const": "list_custom_roles",
            "ui:hidden": True,
            "x-category": "Custom Roles",
            "x-is-trigger": False,
            "x-display-name": "List Custom Roles",
        },
        title="List Custom Roles",
    )


class ZendeskShowCustomRoleConfig(BaseModel):
    """Show a single custom agent role by ID."""

    operation: Literal["show_custom_role"] = Field(
        "show_custom_role",
        json_schema_extra={
            "const": "show_custom_role",
            "ui:hidden": True,
            "x-category": "Custom Roles",
            "x-is-trigger": False,
            "x-display-name": "Show Custom Role",
        },
        title="Show Custom Role",
    )
    custom_role_id: str = Field(
        ..., title="Custom Role ID", description="The ID of the custom role to retrieve"
    )


class ZendeskCreateCustomRoleConfig(BaseModel):
    """Create a custom agent role."""

    operation: Literal["create_custom_role"] = Field(
        "create_custom_role",
        json_schema_extra={
            "const": "create_custom_role",
            "x-creates-resource": True,
            "x-resource-type": "zendesk_custom_role",
            "x-resource-id-path": "data.custom_role.id",
            "ui:hidden": True,
            "x-category": "Custom Roles",
            "x-is-trigger": False,
            "x-display-name": "Create Custom Role",
        },
        title="Create Custom Role",
    )
    name: str = Field(..., title="Name", description="The name of the custom role")
    description: Optional[str] = Field(
        None, title="Description", description="A description of the custom role",
        json_schema_extra={"ui:widget": "textarea"},
    )
    configuration_json: Optional[str] = Field(
        None,
        title="Configuration JSON",
        description='A JSON object of permission settings, e.g. {"ticket_editing": true, "manage_groups": false}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateCustomRoleConfig(BaseModel):
    """Update a custom agent role."""

    operation: Literal["update_custom_role"] = Field(
        "update_custom_role",
        json_schema_extra={
            "const": "update_custom_role",
            "ui:hidden": True,
            "x-category": "Custom Roles",
            "x-is-trigger": False,
            "x-display-name": "Update Custom Role",
        },
        title="Update Custom Role",
    )
    custom_role_id: str = Field(
        ..., title="Custom Role ID", description="The ID of the custom role to update"
    )
    name: Optional[str] = Field(None, title="Name", description="New name for the custom role")
    description: Optional[str] = Field(
        None, title="Description", description="New description for the custom role",
        json_schema_extra={"ui:widget": "textarea"},
    )
    configuration_json: Optional[str] = Field(
        None,
        title="Configuration JSON",
        description='A JSON object of permission settings to update, e.g. {"ticket_editing": true}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteCustomRoleConfig(BaseModel):
    """Delete a custom agent role."""

    operation: Literal["delete_custom_role"] = Field(
        "delete_custom_role",
        json_schema_extra={
            "const": "delete_custom_role",
            "ui:hidden": True,
            "x-category": "Custom Roles",
            "x-is-trigger": False,
            "x-display-name": "Delete Custom Role",
        },
        title="Delete Custom Role",
    )
    custom_role_id: str = Field(
        ..., title="Custom Role ID", description="The ID of the custom role to delete"
    )


class ZendeskListUserSessionsConfig(BaseModel):
    """List the active sessions for a user."""

    operation: Literal["list_user_sessions"] = Field(
        "list_user_sessions",
        json_schema_extra={
            "const": "list_user_sessions",
            "ui:hidden": True,
            "x-category": "Sessions",
            "x-is-trigger": False,
            "x-display-name": "List User Sessions",
        },
        title="List User Sessions",
    )
    user_id: str = Field(..., title="User ID", description="The ID of the user whose sessions to list")


class ZendeskShowSessionConfig(BaseModel):
    """Show a single user session by ID."""

    operation: Literal["show_session"] = Field(
        "show_session",
        json_schema_extra={
            "const": "show_session",
            "ui:hidden": True,
            "x-category": "Sessions",
            "x-is-trigger": False,
            "x-display-name": "Show Session",
        },
        title="Show Session",
    )
    user_id: str = Field(..., title="User ID", description="The ID of the user who owns the session")
    session_id: str = Field(..., title="Session ID", description="The ID of the session to retrieve")


class ZendeskDeleteSessionConfig(BaseModel):
    """Delete a user session, signing that session out."""

    operation: Literal["delete_session"] = Field(
        "delete_session",
        json_schema_extra={
            "const": "delete_session",
            "ui:hidden": True,
            "x-category": "Sessions",
            "x-is-trigger": False,
            "x-display-name": "Delete Session",
        },
        title="Delete Session",
    )
    user_id: str = Field(..., title="User ID", description="The ID of the user who owns the session")
    session_id: str = Field(..., title="Session ID", description="The ID of the session to delete")


class ZendeskShowCurrentSessionConfig(BaseModel):
    """Show the current session of the authenticated user."""

    operation: Literal["show_current_session"] = Field(
        "show_current_session",
        json_schema_extra={
            "const": "show_current_session",
            "ui:hidden": True,
            "x-category": "Sessions",
            "x-is-trigger": False,
            "x-display-name": "Show Current Session",
        },
        title="Show Current Session",
    )


class ZendeskLogoutCurrentSessionConfig(BaseModel):
    """Delete the current session, logging out the authenticated user."""

    operation: Literal["logout_current_session"] = Field(
        "logout_current_session",
        json_schema_extra={
            "const": "logout_current_session",
            "ui:hidden": True,
            "x-category": "Sessions",
            "x-is-trigger": False,
            "x-display-name": "Logout Current Session",
        },
        title="Logout Current Session",
    )


# ---------------------------------------------------------------------------
# Family: fields-forms-statuses
# ---------------------------------------------------------------------------


class ZendeskShowTicketFieldConfig(BaseModel):
    """Show a single ticket field definition."""

    operation: Literal["show_ticket_field"] = Field(
        "show_ticket_field",
        json_schema_extra={
            "const": "show_ticket_field",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Show Ticket Field",
        },
        title="Show Ticket Field",
    )
    ticket_field_id: str = Field(
        ..., title="Ticket Field ID", description="The ID of the ticket field to show"
    )


class ZendeskCreateTicketFieldConfig(BaseModel):
    """Create a ticket field."""

    operation: Literal["create_ticket_field"] = Field(
        "create_ticket_field",
        json_schema_extra={
            "const": "create_ticket_field",
            "x-creates-resource": True,
            "x-resource-type": "zendesk_ticket_field",
            "x-resource-id-path": "data.ticket_field.id",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Create Ticket Field",
        },
        title="Create Ticket Field",
    )
    ticket_field_json: str = Field(
        ...,
        title="Ticket Field JSON",
        description=(
            "The ticket field object as JSON. Must include 'type' and 'title', "
            'e.g. {"type": "text", "title": "Age"}.'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateTicketFieldConfig(BaseModel):
    """Update a ticket field."""

    operation: Literal["update_ticket_field"] = Field(
        "update_ticket_field",
        json_schema_extra={
            "const": "update_ticket_field",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Update Ticket Field",
        },
        title="Update Ticket Field",
    )
    ticket_field_id: str = Field(
        ..., title="Ticket Field ID", description="The ID of the ticket field to update"
    )
    ticket_field_json: str = Field(
        ...,
        title="Ticket Field JSON",
        description='The updated ticket field object as JSON, e.g. {"title": "New title"}.',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteTicketFieldConfig(BaseModel):
    """Delete a ticket field."""

    operation: Literal["delete_ticket_field"] = Field(
        "delete_ticket_field",
        json_schema_extra={
            "const": "delete_ticket_field",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Delete Ticket Field",
        },
        title="Delete Ticket Field",
    )
    ticket_field_id: str = Field(
        ..., title="Ticket Field ID", description="The ID of the ticket field to delete"
    )


class ZendeskListTicketFieldOptionsConfig(BaseModel):
    """List the custom field options of a drop-down ticket field."""

    operation: Literal["list_ticket_field_options"] = Field(
        "list_ticket_field_options",
        json_schema_extra={
            "const": "list_ticket_field_options",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "List Ticket Field Options",
        },
        title="List Ticket Field Options",
    )
    ticket_field_id: str = Field(
        ..., title="Ticket Field ID", description="The ID of the drop-down ticket field"
    )


class ZendeskShowTicketFieldOptionConfig(BaseModel):
    """Show a single custom field option of a ticket field."""

    operation: Literal["show_ticket_field_option"] = Field(
        "show_ticket_field_option",
        json_schema_extra={
            "const": "show_ticket_field_option",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Show Ticket Field Option",
        },
        title="Show Ticket Field Option",
    )
    ticket_field_id: str = Field(
        ..., title="Ticket Field ID", description="The ID of the drop-down ticket field"
    )
    option_id: str = Field(
        ..., title="Option ID", description="The ID of the custom field option to show"
    )


class ZendeskCreateTicketFieldOptionConfig(BaseModel):
    """Create a custom field option on a drop-down ticket field."""

    operation: Literal["create_ticket_field_option"] = Field(
        "create_ticket_field_option",
        json_schema_extra={
            "const": "create_ticket_field_option",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Create Ticket Field Option",
        },
        title="Create Ticket Field Option",
    )
    ticket_field_id: str = Field(
        ..., title="Ticket Field ID", description="The ID of the drop-down ticket field"
    )
    option_json: str = Field(
        ...,
        title="Option JSON",
        description=(
            "The custom field option object as JSON. Must include 'name' and 'value', "
            'e.g. {"name": "Basketball", "value": "basketball"}.'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateTicketFieldOptionConfig(BaseModel):
    """Update an existing custom field option of a drop-down ticket field."""

    operation: Literal["update_ticket_field_option"] = Field(
        "update_ticket_field_option",
        json_schema_extra={
            "const": "update_ticket_field_option",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Update Ticket Field Option",
        },
        title="Update Ticket Field Option",
    )
    ticket_field_id: str = Field(
        ..., title="Ticket Field ID", description="The ID of the drop-down ticket field"
    )
    option_id: str = Field(
        ..., title="Option ID", description="The ID of the custom field option to update"
    )
    option_json: str = Field(
        ...,
        title="Option JSON",
        description='The updated option fields as JSON, e.g. {"name": "Soccer", "value": "soccer"}.',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteTicketFieldOptionConfig(BaseModel):
    """Delete a custom field option from a drop-down ticket field."""

    operation: Literal["delete_ticket_field_option"] = Field(
        "delete_ticket_field_option",
        json_schema_extra={
            "const": "delete_ticket_field_option",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Delete Ticket Field Option",
        },
        title="Delete Ticket Field Option",
    )
    ticket_field_id: str = Field(
        ..., title="Ticket Field ID", description="The ID of the drop-down ticket field"
    )
    option_id: str = Field(
        ..., title="Option ID", description="The ID of the custom field option to delete"
    )


class ZendeskListTicketFormsConfig(BaseModel):
    """List all ticket forms."""

    operation: Literal["list_ticket_forms"] = Field(
        "list_ticket_forms",
        json_schema_extra={
            "const": "list_ticket_forms",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "List Ticket Forms",
        },
        title="List Ticket Forms",
    )


class ZendeskShowTicketFormConfig(BaseModel):
    """Show a single ticket form."""

    operation: Literal["show_ticket_form"] = Field(
        "show_ticket_form",
        json_schema_extra={
            "const": "show_ticket_form",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Show Ticket Form",
        },
        title="Show Ticket Form",
    )
    ticket_form_id: str = Field(
        ..., title="Ticket Form ID", description="The ID of the ticket form to show"
    )


class ZendeskCreateTicketFormConfig(BaseModel):
    """Create a ticket form."""

    operation: Literal["create_ticket_form"] = Field(
        "create_ticket_form",
        json_schema_extra={
            "const": "create_ticket_form",
            "x-creates-resource": True,
            "x-resource-type": "zendesk_ticket_form",
            "x-resource-id-path": "data.ticket_form.id",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Create Ticket Form",
        },
        title="Create Ticket Form",
    )
    ticket_form_json: str = Field(
        ...,
        title="Ticket Form JSON",
        description=(
            "The ticket form object as JSON. Must include 'name', "
            'e.g. {"name": "Snowboard Problem", "ticket_field_ids": [2, 3]}.'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateTicketFormConfig(BaseModel):
    """Update a ticket form."""

    operation: Literal["update_ticket_form"] = Field(
        "update_ticket_form",
        json_schema_extra={
            "const": "update_ticket_form",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Update Ticket Form",
        },
        title="Update Ticket Form",
    )
    ticket_form_id: str = Field(
        ..., title="Ticket Form ID", description="The ID of the ticket form to update"
    )
    ticket_form_json: str = Field(
        ...,
        title="Ticket Form JSON",
        description='The updated ticket form object as JSON, e.g. {"name": "New name"}.',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteTicketFormConfig(BaseModel):
    """Delete a ticket form."""

    operation: Literal["delete_ticket_form"] = Field(
        "delete_ticket_form",
        json_schema_extra={
            "const": "delete_ticket_form",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Delete Ticket Form",
        },
        title="Delete Ticket Form",
    )
    ticket_form_id: str = Field(
        ..., title="Ticket Form ID", description="The ID of the ticket form to delete"
    )


class ZendeskListCustomStatusesConfig(BaseModel):
    """List custom ticket statuses."""

    operation: Literal["list_custom_statuses"] = Field(
        "list_custom_statuses",
        json_schema_extra={
            "const": "list_custom_statuses",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "List Custom Statuses",
        },
        title="List Custom Statuses",
    )


class ZendeskShowCustomStatusConfig(BaseModel):
    """Show a single custom ticket status."""

    operation: Literal["show_custom_status"] = Field(
        "show_custom_status",
        json_schema_extra={
            "const": "show_custom_status",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Show Custom Status",
        },
        title="Show Custom Status",
    )
    custom_status_id: str = Field(
        ..., title="Custom Status ID", description="The ID of the custom ticket status to show"
    )


class ZendeskCreateCustomStatusConfig(BaseModel):
    """Create a custom ticket status."""

    operation: Literal["create_custom_status"] = Field(
        "create_custom_status",
        json_schema_extra={
            "const": "create_custom_status",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Create Custom Status",
        },
        title="Create Custom Status",
    )
    custom_status_json: str = Field(
        ...,
        title="Custom Status JSON",
        description=(
            "The custom status object as JSON. Must include 'status_category' and "
            "'agent_label', e.g. "
            '{"status_category": "open", "agent_label": "Awaiting parts", '
            '"end_user_label": "In progress"}.'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateCustomStatusConfig(BaseModel):
    """Update a custom ticket status."""

    operation: Literal["update_custom_status"] = Field(
        "update_custom_status",
        json_schema_extra={
            "const": "update_custom_status",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Update Custom Status",
        },
        title="Update Custom Status",
    )
    custom_status_id: str = Field(
        ..., title="Custom Status ID", description="The ID of the custom ticket status to update"
    )
    custom_status_json: str = Field(
        ...,
        title="Custom Status JSON",
        description='The updated custom status object as JSON, e.g. {"agent_label": "New label"}.',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskListBrandsConfig(BaseModel):
    """List all brands."""

    operation: Literal["list_brands"] = Field(
        "list_brands",
        json_schema_extra={
            "const": "list_brands",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "List Brands",
        },
        title="List Brands",
    )


class ZendeskShowBrandConfig(BaseModel):
    """Show a single brand."""

    operation: Literal["show_brand"] = Field(
        "show_brand",
        json_schema_extra={
            "const": "show_brand",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Show Brand",
        },
        title="Show Brand",
    )
    brand_id: str = Field(..., title="Brand ID", description="The ID of the brand to show")


class ZendeskCreateBrandConfig(BaseModel):
    """Create a brand."""

    operation: Literal["create_brand"] = Field(
        "create_brand",
        json_schema_extra={
            "const": "create_brand",
            "x-creates-resource": True,
            "x-resource-type": "zendesk_brand",
            "x-resource-id-path": "data.brand.id",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Create Brand",
        },
        title="Create Brand",
    )
    brand_json: str = Field(
        ...,
        title="Brand JSON",
        description=(
            "The brand object as JSON. Must include 'name' and 'subdomain', e.g. "
            '{"name": "Brand 1", "subdomain": "brand1"}.'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateBrandConfig(BaseModel):
    """Update a brand."""

    operation: Literal["update_brand"] = Field(
        "update_brand",
        json_schema_extra={
            "const": "update_brand",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Update Brand",
        },
        title="Update Brand",
    )
    brand_id: str = Field(..., title="Brand ID", description="The ID of the brand to update")
    brand_json: str = Field(
        ...,
        title="Brand JSON",
        description='The updated brand object as JSON, e.g. {"name": "New brand name"}.',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteBrandConfig(BaseModel):
    """Delete a brand."""

    operation: Literal["delete_brand"] = Field(
        "delete_brand",
        json_schema_extra={
            "const": "delete_brand",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Delete Brand",
        },
        title="Delete Brand",
    )
    brand_id: str = Field(..., title="Brand ID", description="The ID of the brand to delete")


# ---------------------------------------------------------------------------
# Family: requests-sideconv-import
# ---------------------------------------------------------------------------


class ZendeskListRequestsConfig(BaseModel):
    """List end-user requests (the requester-facing view of tickets)."""

    operation: Literal["list_requests"] = Field(
        "list_requests",
        json_schema_extra={
            "const": "list_requests",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "List Requests",
        },
        title="List Requests",
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Filter requests by status",
        json_schema_extra={
            "enum": ["", "new", "open", "pending", "hold", "solved", "closed"],
            "enumNames": ["Any", "New", "Open", "Pending", "Hold", "Solved", "Closed"],
            "x-enum-searchable": True,
        },
    )
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Number of requests per page (max 100)"
    )


class ZendeskShowRequestConfig(BaseModel):
    """Retrieve a single request by ID."""

    operation: Literal["show_request"] = Field(
        "show_request",
        json_schema_extra={
            "const": "show_request",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Show Request",
        },
        title="Show Request",
    )
    request_id: str = Field(..., title="Request ID", description="The ID of the request to retrieve")


class ZendeskCreateRequestConfig(BaseModel):
    """Create a request (end-user ticket) with an initial comment."""

    operation: Literal["create_request"] = Field(
        "create_request",
        json_schema_extra={
            "const": "create_request",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Create Request",
        },
        title="Create Request",
    )
    subject: str = Field(..., title="Subject", description="The request subject")
    comment_body: str = Field(
        ...,
        title="Description",
        description="The first comment / description on the request",
        json_schema_extra={"ui:widget": "textarea"},
    )
    priority: Optional[str] = Field(
        None,
        title="Priority",
        description="Request priority",
        json_schema_extra={
            "enum": ["", "urgent", "high", "normal", "low"],
            "enumNames": ["Default", "Urgent", "High", "Normal", "Low"],
            "x-enum-searchable": True,
        },
    )
    request_type: Optional[str] = Field(
        None,
        title="Type",
        description="Request type",
        json_schema_extra={
            "enum": ["", "problem", "incident", "question", "task"],
            "enumNames": ["Default", "Problem", "Incident", "Question", "Task"],
            "x-enum-searchable": True,
        },
    )
    requester_email: Optional[str] = Field(
        None,
        title="Requester Email",
        description="Email of the requester (for anonymous/agent-submitted requests)",
    )
    requester_name: Optional[str] = Field(
        None, title="Requester Name", description="Display name of the requester"
    )


class ZendeskUpdateRequestConfig(BaseModel):
    """Update a request. End users can only add a comment, mark it solved, or add collaborators."""

    operation: Literal["update_request"] = Field(
        "update_request",
        json_schema_extra={
            "const": "update_request",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Update Request",
        },
        title="Update Request",
    )
    request_id: str = Field(..., title="Request ID", description="The ID of the request to update")
    comment_body: Optional[str] = Field(
        None,
        title="Comment",
        description="A new comment to add to the request",
        json_schema_extra={"ui:widget": "textarea"},
    )
    solved: Optional[str] = Field(
        None,
        title="Mark Solved",
        description="Set the request to solved",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["No change", "Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    additional_collaborators: Optional[str] = Field(
        None,
        title="Additional Collaborators",
        description="Comma-separated emails or user IDs to add as collaborators",
    )


class ZendeskListRequestCommentsConfig(BaseModel):
    """List the comments on a request."""

    operation: Literal["list_request_comments"] = Field(
        "list_request_comments",
        json_schema_extra={
            "const": "list_request_comments",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "List Request Comments",
        },
        title="List Request Comments",
    )
    request_id: str = Field(..., title="Request ID", description="The request to read comments from")


class ZendeskListSideConversationsConfig(BaseModel):
    """List the side conversations on a ticket."""

    operation: Literal["list_side_conversations"] = Field(
        "list_side_conversations",
        json_schema_extra={
            "const": "list_side_conversations",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "List Side Conversations",
        },
        title="List Side Conversations",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The parent ticket ID")


class ZendeskShowSideConversationConfig(BaseModel):
    """Retrieve a single side conversation on a ticket."""

    operation: Literal["show_side_conversation"] = Field(
        "show_side_conversation",
        json_schema_extra={
            "const": "show_side_conversation",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Show Side Conversation",
        },
        title="Show Side Conversation",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The parent ticket ID")
    side_conversation_id: str = Field(
        ..., title="Side Conversation ID", description="The side conversation to retrieve"
    )


class ZendeskCreateSideConversationConfig(BaseModel):
    """Start a new side conversation on a ticket."""

    operation: Literal["create_side_conversation"] = Field(
        "create_side_conversation",
        json_schema_extra={
            "const": "create_side_conversation",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Create Side Conversation",
        },
        title="Create Side Conversation",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The parent ticket ID")
    to_emails: str = Field(
        ...,
        title="Recipients",
        description="Comma-separated recipient email addresses",
    )
    subject: Optional[str] = Field(
        None, title="Subject", description="Subject line for the side conversation"
    )
    body: str = Field(
        ...,
        title="Message",
        description="The message body of the side conversation",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskReplySideConversationConfig(BaseModel):
    """Reply to an existing side conversation on a ticket."""

    operation: Literal["reply_side_conversation"] = Field(
        "reply_side_conversation",
        json_schema_extra={
            "const": "reply_side_conversation",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Reply to Side Conversation",
        },
        title="Reply to Side Conversation",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The parent ticket ID")
    side_conversation_id: str = Field(
        ..., title="Side Conversation ID", description="The side conversation to reply to"
    )
    body: str = Field(
        ...,
        title="Reply",
        description="The reply message body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    to_emails: Optional[str] = Field(
        None,
        title="Recipients",
        description="Optional comma-separated recipient emails to override the thread recipients",
    )


class ZendeskUpdateSideConversationConfig(BaseModel):
    """Update a side conversation's state or subject."""

    operation: Literal["update_side_conversation"] = Field(
        "update_side_conversation",
        json_schema_extra={
            "const": "update_side_conversation",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Update Side Conversation",
        },
        title="Update Side Conversation",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The parent ticket ID")
    side_conversation_id: str = Field(
        ..., title="Side Conversation ID", description="The side conversation to update"
    )
    state: Optional[str] = Field(
        None,
        title="State",
        description="New state for the side conversation",
        json_schema_extra={
            "enum": ["", "open", "closed"],
            "enumNames": ["No change", "Open", "Closed"],
            "x-enum-searchable": True,
        },
    )
    subject: Optional[str] = Field(
        None, title="Subject", description="New subject for the side conversation"
    )


class ZendeskImportTicketConfig(BaseModel):
    """Import a single historical ticket, preserving original timestamps."""

    operation: Literal["import_ticket"] = Field(
        "import_ticket",
        json_schema_extra={
            "const": "import_ticket",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Import Ticket",
        },
        title="Import Ticket",
    )
    subject: str = Field(..., title="Subject", description="The ticket subject")
    comment_body: str = Field(
        ...,
        title="Description",
        description="The first comment / description on the imported ticket",
        json_schema_extra={"ui:widget": "textarea"},
    )
    status: Optional[str] = Field(
        "closed",
        title="Status",
        description="Status for the imported ticket (imports are usually closed)",
        json_schema_extra={
            "enum": ["", "new", "open", "pending", "hold", "solved", "closed"],
            "enumNames": ["Default", "New", "Open", "Pending", "Hold", "Solved", "Closed"],
            "x-enum-searchable": True,
        },
    )
    created_at: Optional[str] = Field(
        None,
        title="Created At",
        description="Original creation timestamp (ISO 8601, e.g. 2020-01-15T10:00:00Z)",
    )
    solved_at: Optional[str] = Field(
        None,
        title="Solved At",
        description="Original solved timestamp (ISO 8601)",
    )
    requester_email: Optional[str] = Field(
        None, title="Requester Email", description="Email of the original requester"
    )
    extra_json: Optional[str] = Field(
        None,
        title="Extra Fields (JSON)",
        description="JSON object of additional ticket fields merged into the import (tags, custom_fields, comments, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskImportManyTicketsConfig(BaseModel):
    """Bulk-import up to 100 historical tickets as a background job."""

    operation: Literal["import_many_tickets"] = Field(
        "import_many_tickets",
        json_schema_extra={
            "const": "import_many_tickets",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Import Many Tickets",
        },
        title="Import Many Tickets",
    )
    tickets_json: str = Field(
        ...,
        title="Tickets (JSON)",
        description="JSON array of up to 100 ticket objects to import",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskIncrementalUsersConfig(BaseModel):
    """Cursor-based incremental export of users changed since a start time."""

    operation: Literal["incremental_users"] = Field(
        "incremental_users",
        json_schema_extra={
            "const": "incremental_users",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Incremental Users Export",
        },
        title="Incremental Users Export",
    )
    start_time: str = Field(
        ...,
        title="Start Time",
        description="Unix epoch seconds; export users changed at/after this time (ignored once a cursor is supplied)",
    )
    cursor: Optional[str] = Field(
        None,
        title="Cursor",
        description="Pagination cursor (after_cursor) from a previous response to fetch the next page",
    )


class ZendeskIncrementalOrganizationsConfig(BaseModel):
    """Time-based incremental export of organizations changed since a start time."""

    operation: Literal["incremental_organizations"] = Field(
        "incremental_organizations",
        json_schema_extra={
            "const": "incremental_organizations",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Incremental Organizations Export",
        },
        title="Incremental Organizations Export",
    )
    start_time: str = Field(
        ...,
        title="Start Time",
        description="Unix epoch seconds; export organizations changed at/after this time",
    )
    cursor: Optional[str] = Field(
        None,
        title="Cursor",
        description="Optional pagination cursor from a previous response",
    )


class ZendeskIncrementalTicketEventsConfig(BaseModel):
    """Time-based incremental export of ticket events since a start time."""

    operation: Literal["incremental_ticket_events"] = Field(
        "incremental_ticket_events",
        json_schema_extra={
            "const": "incremental_ticket_events",
            "ui:hidden": True,
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Incremental Ticket Events Export",
        },
        title="Incremental Ticket Events Export",
    )
    start_time: str = Field(
        ...,
        title="Start Time",
        description="Unix epoch seconds; export ticket events at/after this time",
    )
    cursor: Optional[str] = Field(
        None,
        title="Cursor",
        description="Optional pagination cursor from a previous response",
    )


# ---------------------------------------------------------------------------
# Family: macros-views
# ---------------------------------------------------------------------------


class ZendeskListMacrosConfig(BaseModel):
    """List all shared macros available to the current user."""

    operation: Literal["list_macros"] = Field(
        "list_macros",
        json_schema_extra={
            "const": "list_macros",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "List Macros",
        },
        title="List Macros",
    )


class ZendeskListActiveMacrosConfig(BaseModel):
    """List all active shared macros."""

    operation: Literal["list_active_macros"] = Field(
        "list_active_macros",
        json_schema_extra={
            "const": "list_active_macros",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "List Active Macros",
        },
        title="List Active Macros",
    )


class ZendeskShowMacroConfig(BaseModel):
    """Retrieve a single macro by ID."""

    operation: Literal["show_macro"] = Field(
        "show_macro",
        json_schema_extra={
            "const": "show_macro",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Show Macro",
        },
        title="Show Macro",
    )
    macro_id: str = Field(..., title="Macro ID", description="The ID of the macro to retrieve")


class ZendeskCreateMacroConfig(BaseModel):
    """Create a new macro."""

    operation: Literal["create_macro"] = Field(
        "create_macro",
        json_schema_extra={
            "const": "create_macro",
            "x-creates-resource": True,
            "x-resource-type": "zendesk_macro",
            "x-resource-id-path": "data.macro.id",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Create Macro",
        },
        title="Create Macro",
    )
    macro_json: str = Field(
        ...,
        title="Macro (JSON)",
        description='JSON object for the macro, e.g. {"title":"Close and Redirect","actions":[{"field":"status","value":"solved"}]}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateMacroConfig(BaseModel):
    """Update an existing macro."""

    operation: Literal["update_macro"] = Field(
        "update_macro",
        json_schema_extra={
            "const": "update_macro",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Update Macro",
        },
        title="Update Macro",
    )
    macro_id: str = Field(..., title="Macro ID", description="The ID of the macro to update")
    macro_json: str = Field(
        ...,
        title="Macro (JSON)",
        description='JSON object of fields to update, e.g. {"title":"New title","active":false}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteMacroConfig(BaseModel):
    """Delete a macro by ID."""

    operation: Literal["delete_macro"] = Field(
        "delete_macro",
        json_schema_extra={
            "const": "delete_macro",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Delete Macro",
        },
        title="Delete Macro",
    )
    macro_id: str = Field(..., title="Macro ID", description="The ID of the macro to delete")


class ZendeskShowMacroChangesConfig(BaseModel):
    """Show the changes a macro would make (the macro's resulting actions)."""

    operation: Literal["show_macro_changes"] = Field(
        "show_macro_changes",
        json_schema_extra={
            "const": "show_macro_changes",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Show Changes to Ticket",
        },
        title="Show Changes to Ticket",
    )
    macro_id: str = Field(..., title="Macro ID", description="The ID of the macro to preview")


class ZendeskShowTicketAfterMacroConfig(BaseModel):
    """Preview a ticket as it would appear after applying a macro (no changes saved)."""

    operation: Literal["show_ticket_after_macro"] = Field(
        "show_ticket_after_macro",
        json_schema_extra={
            "const": "show_ticket_after_macro",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Show Ticket After Applying Macro",
        },
        title="Show Ticket After Applying Macro",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The ticket to preview against")
    macro_id: str = Field(..., title="Macro ID", description="The macro to apply in the preview")


class ZendeskListViewsConfig(BaseModel):
    """List all shared and personal views available to the current user."""

    operation: Literal["list_views"] = Field(
        "list_views",
        json_schema_extra={
            "const": "list_views",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "List Views",
        },
        title="List Views",
    )


class ZendeskListActiveViewsConfig(BaseModel):
    """List all active shared and personal views."""

    operation: Literal["list_active_views"] = Field(
        "list_active_views",
        json_schema_extra={
            "const": "list_active_views",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "List Active Views",
        },
        title="List Active Views",
    )


class ZendeskShowViewConfig(BaseModel):
    """Retrieve a single view by ID."""

    operation: Literal["show_view"] = Field(
        "show_view",
        json_schema_extra={
            "const": "show_view",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Show View",
        },
        title="Show View",
    )
    view_id: str = Field(..., title="View ID", description="The ID of the view to retrieve")


class ZendeskCreateViewConfig(BaseModel):
    """Create a new view."""

    operation: Literal["create_view"] = Field(
        "create_view",
        json_schema_extra={
            "const": "create_view",
            "x-creates-resource": True,
            "x-resource-type": "zendesk_view",
            "x-resource-id-path": "data.view.id",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Create View",
        },
        title="Create View",
    )
    view_json: str = Field(
        ...,
        title="View (JSON)",
        description='JSON object for the view, e.g. {"title":"My open tickets","all":[{"field":"status","operator":"less_than","value":"solved"}]}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateViewConfig(BaseModel):
    """Update an existing view."""

    operation: Literal["update_view"] = Field(
        "update_view",
        json_schema_extra={
            "const": "update_view",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Update View",
        },
        title="Update View",
    )
    view_id: str = Field(..., title="View ID", description="The ID of the view to update")
    view_json: str = Field(
        ...,
        title="View (JSON)",
        description='JSON object of fields to update, e.g. {"title":"New title","active":false}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteViewConfig(BaseModel):
    """Delete a view by ID."""

    operation: Literal["delete_view"] = Field(
        "delete_view",
        json_schema_extra={
            "const": "delete_view",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Delete View",
        },
        title="Delete View",
    )
    view_id: str = Field(..., title="View ID", description="The ID of the view to delete")


class ZendeskListViewTicketsConfig(BaseModel):
    """List the tickets that belong to a view."""

    operation: Literal["list_view_tickets"] = Field(
        "list_view_tickets",
        json_schema_extra={
            "const": "list_view_tickets",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "List Tickets From View",
        },
        title="List Tickets From View",
    )
    view_id: str = Field(..., title="View ID", description="The view to list tickets from")


class ZendeskExecuteViewConfig(BaseModel):
    """Execute a view and return its tickets with the view's columns."""

    operation: Literal["execute_view"] = Field(
        "execute_view",
        json_schema_extra={
            "const": "execute_view",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Execute View",
        },
        title="Execute View",
    )
    view_id: str = Field(..., title="View ID", description="The view to execute")


class ZendeskCountViewConfig(BaseModel):
    """Get the ticket count for a single view."""

    operation: Literal["count_view"] = Field(
        "count_view",
        json_schema_extra={
            "const": "count_view",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Count View",
        },
        title="Count View",
    )
    view_id: str = Field(..., title="View ID", description="The view to count tickets for")


class ZendeskExportViewConfig(BaseModel):
    """Export a view (returns an export ticket set for the view)."""

    operation: Literal["export_view"] = Field(
        "export_view",
        json_schema_extra={
            "const": "export_view",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Export View",
        },
        title="Export View",
    )
    view_id: str = Field(..., title="View ID", description="The view to export")


# ---------------------------------------------------------------------------
# Family: triggers-automations-slas
# ---------------------------------------------------------------------------


class ZendeskListTriggersConfig(BaseModel):
    """List all ticket triggers (business rules)."""

    operation: Literal["list_triggers"] = Field(
        "list_triggers",
        json_schema_extra={
            "const": "list_triggers",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "List Triggers (Business Rule)",
        },
        title="List Triggers (Business Rule)",
    )


class ZendeskListActiveTriggersConfig(BaseModel):
    """List only the active ticket triggers (business rules)."""

    operation: Literal["list_active_triggers"] = Field(
        "list_active_triggers",
        json_schema_extra={
            "const": "list_active_triggers",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "List Active Triggers (Business Rule)",
        },
        title="List Active Triggers (Business Rule)",
    )


class ZendeskShowTriggerConfig(BaseModel):
    """Retrieve a single ticket trigger (business rule) by ID."""

    operation: Literal["show_trigger"] = Field(
        "show_trigger",
        json_schema_extra={
            "const": "show_trigger",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Show Trigger (Business Rule)",
        },
        title="Show Trigger (Business Rule)",
    )
    trigger_id: str = Field(..., title="Trigger ID", description="The ID of the trigger to retrieve")


class ZendeskCreateTriggerConfig(BaseModel):
    """Create a ticket trigger (business rule)."""

    operation: Literal["create_trigger"] = Field(
        "create_trigger",
        json_schema_extra={
            "const": "create_trigger",
            "x-creates-resource": True,
            "x-resource-type": "zendesk_trigger",
            "x-resource-id-path": "data.trigger.id",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Create Trigger (Business Rule)",
        },
        title="Create Trigger (Business Rule)",
    )
    body_json: str = Field(
        ...,
        title="Trigger JSON",
        description=(
            "The trigger object as a JSON object, e.g. "
            '{"title": "...", "conditions": {"all": [...], "any": [...]}, "actions": [...]}. '
            "It is sent wrapped under the 'trigger' key."
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateTriggerConfig(BaseModel):
    """Update an existing ticket trigger (business rule)."""

    operation: Literal["update_trigger"] = Field(
        "update_trigger",
        json_schema_extra={
            "const": "update_trigger",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Update Trigger (Business Rule)",
        },
        title="Update Trigger (Business Rule)",
    )
    trigger_id: str = Field(..., title="Trigger ID", description="The ID of the trigger to update")
    body_json: str = Field(
        ...,
        title="Trigger JSON",
        description=(
            "The trigger fields to change as a JSON object, e.g. "
            '{"title": "...", "conditions": {...}, "actions": [...]}. '
            "It is sent wrapped under the 'trigger' key."
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteTriggerConfig(BaseModel):
    """Delete a ticket trigger (business rule) by ID."""

    operation: Literal["delete_trigger"] = Field(
        "delete_trigger",
        json_schema_extra={
            "const": "delete_trigger",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Delete Trigger (Business Rule)",
        },
        title="Delete Trigger (Business Rule)",
    )
    trigger_id: str = Field(..., title="Trigger ID", description="The ID of the trigger to delete")


class ZendeskListAutomationsConfig(BaseModel):
    """List all ticket automations (business rules)."""

    operation: Literal["list_automations"] = Field(
        "list_automations",
        json_schema_extra={
            "const": "list_automations",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "List Automations (Business Rule)",
        },
        title="List Automations (Business Rule)",
    )


class ZendeskListActiveAutomationsConfig(BaseModel):
    """List only the active ticket automations (business rules)."""

    operation: Literal["list_active_automations"] = Field(
        "list_active_automations",
        json_schema_extra={
            "const": "list_active_automations",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "List Active Automations (Business Rule)",
        },
        title="List Active Automations (Business Rule)",
    )


class ZendeskShowAutomationConfig(BaseModel):
    """Retrieve a single ticket automation (business rule) by ID."""

    operation: Literal["show_automation"] = Field(
        "show_automation",
        json_schema_extra={
            "const": "show_automation",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Show Automation (Business Rule)",
        },
        title="Show Automation (Business Rule)",
    )
    automation_id: str = Field(
        ..., title="Automation ID", description="The ID of the automation to retrieve"
    )


class ZendeskCreateAutomationConfig(BaseModel):
    """Create a ticket automation (business rule)."""

    operation: Literal["create_automation"] = Field(
        "create_automation",
        json_schema_extra={
            "const": "create_automation",
            "x-creates-resource": True,
            "x-resource-type": "zendesk_automation",
            "x-resource-id-path": "data.automation.id",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Create Automation (Business Rule)",
        },
        title="Create Automation (Business Rule)",
    )
    body_json: str = Field(
        ...,
        title="Automation JSON",
        description=(
            "The automation object as a JSON object, e.g. "
            '{"title": "...", "conditions": {"all": [...], "any": [...]}, "actions": [...]}. '
            "Automations require a time-based condition. Sent wrapped under the 'automation' key."
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateAutomationConfig(BaseModel):
    """Update an existing ticket automation (business rule)."""

    operation: Literal["update_automation"] = Field(
        "update_automation",
        json_schema_extra={
            "const": "update_automation",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Update Automation (Business Rule)",
        },
        title="Update Automation (Business Rule)",
    )
    automation_id: str = Field(
        ..., title="Automation ID", description="The ID of the automation to update"
    )
    body_json: str = Field(
        ...,
        title="Automation JSON",
        description=(
            "The automation fields to change as a JSON object, e.g. "
            '{"title": "...", "conditions": {...}, "actions": [...]}. '
            "Sent wrapped under the 'automation' key."
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteAutomationConfig(BaseModel):
    """Delete a ticket automation (business rule) by ID."""

    operation: Literal["delete_automation"] = Field(
        "delete_automation",
        json_schema_extra={
            "const": "delete_automation",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Delete Automation (Business Rule)",
        },
        title="Delete Automation (Business Rule)",
    )
    automation_id: str = Field(
        ..., title="Automation ID", description="The ID of the automation to delete"
    )


class ZendeskListSlaPoliciesConfig(BaseModel):
    """List all SLA policies (business rules)."""

    operation: Literal["list_sla_policies"] = Field(
        "list_sla_policies",
        json_schema_extra={
            "const": "list_sla_policies",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "List SLA Policies (Business Rule)",
        },
        title="List SLA Policies (Business Rule)",
    )


class ZendeskShowSlaPolicyConfig(BaseModel):
    """Retrieve a single SLA policy (business rule) by ID."""

    operation: Literal["show_sla_policy"] = Field(
        "show_sla_policy",
        json_schema_extra={
            "const": "show_sla_policy",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Show SLA Policy (Business Rule)",
        },
        title="Show SLA Policy (Business Rule)",
    )
    sla_policy_id: str = Field(
        ..., title="SLA Policy ID", description="The ID of the SLA policy to retrieve"
    )


class ZendeskCreateSlaPolicyConfig(BaseModel):
    """Create an SLA policy (business rule)."""

    operation: Literal["create_sla_policy"] = Field(
        "create_sla_policy",
        json_schema_extra={
            "const": "create_sla_policy",
            "x-creates-resource": True,
            "x-resource-type": "zendesk_sla_policy",
            "x-resource-id-path": "data.sla_policy.id",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Create SLA Policy (Business Rule)",
        },
        title="Create SLA Policy (Business Rule)",
    )
    body_json: str = Field(
        ...,
        title="SLA Policy JSON",
        description=(
            "The SLA policy object as a JSON object, e.g. "
            '{"title": "...", "filter": {"all": [...], "any": [...]}, '
            '"policy_metrics": [{"priority": "normal", "metric": "first_reply_time", '
            '"target": 60, "business_hours": false}]}. Sent wrapped under the sla_policy key."'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateSlaPolicyConfig(BaseModel):
    """Update an existing SLA policy (business rule)."""

    operation: Literal["update_sla_policy"] = Field(
        "update_sla_policy",
        json_schema_extra={
            "const": "update_sla_policy",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Update SLA Policy (Business Rule)",
        },
        title="Update SLA Policy (Business Rule)",
    )
    sla_policy_id: str = Field(
        ..., title="SLA Policy ID", description="The ID of the SLA policy to update"
    )
    body_json: str = Field(
        ...,
        title="SLA Policy JSON",
        description=(
            "The SLA policy fields to change as a JSON object, e.g. "
            '{"title": "...", "filter": {...}, "policy_metrics": [...]}. '
            "Sent wrapped under the 'sla_policy' key."
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteSlaPolicyConfig(BaseModel):
    """Delete an SLA policy (business rule) by ID."""

    operation: Literal["delete_sla_policy"] = Field(
        "delete_sla_policy",
        json_schema_extra={
            "const": "delete_sla_policy",
            "ui:hidden": True,
            "x-category": "Business Rules",
            "x-is-trigger": False,
            "x-display-name": "Delete SLA Policy (Business Rule)",
        },
        title="Delete SLA Policy (Business Rule)",
    )
    sla_policy_id: str = Field(
        ..., title="SLA Policy ID", description="The ID of the SLA policy to delete"
    )


# ---------------------------------------------------------------------------
# Family: webhooks-search
# ---------------------------------------------------------------------------


class ZendeskListWebhooksConfig(BaseModel):
    """List webhooks configured on the account."""

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
    name_contains: Optional[str] = Field(
        None,
        title="Name Contains",
        description="Only return webhooks whose name contains this text",
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Filter by webhook status",
        json_schema_extra={
            "enum": ["", "active", "inactive"],
            "enumNames": ["Any", "Active", "Inactive"],
            "x-enum-searchable": True,
        },
    )
    sort: Optional[str] = Field(
        None,
        title="Sort",
        description="Sort field, e.g. name, status, created_at (prefix with - for descending)",
    )
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Number of webhooks per page (max 100)"
    )


class ZendeskShowWebhookConfig(BaseModel):
    """Retrieve a single webhook by ID."""

    operation: Literal["show_webhook"] = Field(
        "show_webhook",
        json_schema_extra={
            "const": "show_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Show Webhook",
        },
        title="Show Webhook",
    )
    webhook_id: str = Field(..., title="Webhook ID", description="The ID of the webhook to retrieve")


class ZendeskUpdateWebhookConfig(BaseModel):
    """Replace a webhook (PUT). The JSON body must be the complete webhook object."""

    operation: Literal["update_webhook"] = Field(
        "update_webhook",
        json_schema_extra={
            "const": "update_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Update Webhook",
        },
        title="Update Webhook",
    )
    webhook_id: str = Field(..., title="Webhook ID", description="The ID of the webhook to update")
    webhook_json: str = Field(
        ...,
        title="Webhook JSON",
        description=(
            "The full webhook object as JSON (all required fields: name, endpoint, "
            "http_method, request_format, status). PUT replaces the whole resource."
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskPatchWebhookConfig(BaseModel):
    """Partially update a webhook (PATCH). Only the fields you supply change."""

    operation: Literal["patch_webhook"] = Field(
        "patch_webhook",
        json_schema_extra={
            "const": "patch_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Patch Webhook",
        },
        title="Patch Webhook",
    )
    webhook_id: str = Field(..., title="Webhook ID", description="The ID of the webhook to patch")
    webhook_json: str = Field(
        ...,
        title="Webhook JSON",
        description="A JSON object with only the webhook fields you want to change",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteWebhookConfig(BaseModel):
    """Delete a webhook by ID."""

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
    webhook_id: str = Field(..., title="Webhook ID", description="The ID of the webhook to delete")


class ZendeskCloneWebhookConfig(BaseModel):
    """Create a new webhook by cloning an existing one."""

    operation: Literal["clone_webhook"] = Field(
        "clone_webhook",
        json_schema_extra={
            "const": "clone_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Clone Webhook",
        },
        title="Clone Webhook",
    )
    clone_webhook_id: str = Field(
        ...,
        title="Source Webhook ID",
        description="The ID of the existing webhook to clone",
    )


class ZendeskTestWebhookConfig(BaseModel):
    """Send a test request for a webhook without saving it."""

    operation: Literal["test_webhook"] = Field(
        "test_webhook",
        json_schema_extra={
            "const": "test_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Test Webhook",
        },
        title="Test Webhook",
    )
    webhook_id: Optional[str] = Field(
        None,
        title="Webhook ID",
        description="ID of an existing webhook to test (leave blank to test the inline request)",
    )
    request_json: Optional[str] = Field(
        None,
        title="Request JSON",
        description=(
            "Optional JSON object describing the test request/webhook, e.g. "
            '{"request": {"endpoint": "https://example.com", "http_method": "POST", '
            '"request_format": "json"}}'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskListWebhookInvocationsConfig(BaseModel):
    """List recent invocations (delivery events) for a webhook."""

    operation: Literal["list_webhook_invocations"] = Field(
        "list_webhook_invocations",
        json_schema_extra={
            "const": "list_webhook_invocations",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "List Webhook Invocations",
        },
        title="List Webhook Invocations",
    )
    webhook_id: str = Field(..., title="Webhook ID", description="The webhook whose invocations to list")
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Number of invocations per page (max 100)"
    )


class ZendeskListWebhookInvocationAttemptsConfig(BaseModel):
    """List the delivery attempts for a single webhook invocation."""

    operation: Literal["list_webhook_invocation_attempts"] = Field(
        "list_webhook_invocation_attempts",
        json_schema_extra={
            "const": "list_webhook_invocation_attempts",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "List Invocation Attempts",
        },
        title="List Invocation Attempts",
    )
    webhook_id: str = Field(..., title="Webhook ID", description="The webhook that was invoked")
    invocation_id: str = Field(
        ..., title="Invocation ID", description="The invocation whose attempts to list"
    )


class ZendeskShowWebhookSigningSecretConfig(BaseModel):
    """Retrieve a webhook's signing secret (used to verify authenticity)."""

    operation: Literal["show_webhook_signing_secret"] = Field(
        "show_webhook_signing_secret",
        json_schema_extra={
            "const": "show_webhook_signing_secret",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Show Signing Secret",
        },
        title="Show Signing Secret",
    )
    webhook_id: str = Field(..., title="Webhook ID", description="The webhook whose signing secret to show")


class ZendeskResetWebhookSigningSecretConfig(BaseModel):
    """Rotate (reset) a webhook's signing secret and return the new one."""

    operation: Literal["reset_webhook_signing_secret"] = Field(
        "reset_webhook_signing_secret",
        json_schema_extra={
            "const": "reset_webhook_signing_secret",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Reset Signing Secret",
        },
        title="Reset Signing Secret",
    )
    webhook_id: str = Field(..., title="Webhook ID", description="The webhook whose signing secret to reset")


class ZendeskSearchCountConfig(BaseModel):
    """Return only the count of results matching a search query."""

    operation: Literal["search_count"] = Field(
        "search_count",
        json_schema_extra={
            "const": "search_count",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search Count",
        },
        title="Search Count",
    )
    query: str = Field(
        ...,
        title="Query",
        description="Zendesk search query, e.g. 'type:ticket status:open'",
    )


class ZendeskExportSearchConfig(BaseModel):
    """Export search results with cursor pagination (large result sets)."""

    operation: Literal["export_search"] = Field(
        "export_search",
        json_schema_extra={
            "const": "export_search",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Export Search",
        },
        title="Export Search",
    )
    query: str = Field(
        ...,
        title="Query",
        description="Zendesk search query, e.g. 'type:ticket status:open'",
    )
    filter_type: str = Field(
        ...,
        title="Result Type",
        description="Required object type to export",
        json_schema_extra={
            "enum": ["ticket", "user", "organization", "group"],
            "enumNames": ["Tickets", "Users", "Organizations", "Groups"],
            "x-enum-searchable": True,
        },
    )
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Results per page (max 1000)"
    )


class ZendeskAutocompleteTagsConfig(BaseModel):
    """Autocomplete tag names by prefix."""

    operation: Literal["autocomplete_tags"] = Field(
        "autocomplete_tags",
        json_schema_extra={
            "const": "autocomplete_tags",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Autocomplete Tags",
        },
        title="Autocomplete Tags",
    )
    name: str = Field(
        ...,
        title="Name Prefix",
        description="Tag name prefix to autocomplete (at least 2 characters)",
    )


# ---------------------------------------------------------------------------
# Family: guide-articles
# ---------------------------------------------------------------------------


class ZendeskListArticlesConfig(BaseModel):
    """List all Help Center articles."""

    operation: Literal["list_articles"] = Field(
        "list_articles",
        json_schema_extra={
            "const": "list_articles",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "List Articles",
        },
        title="List Articles",
    )
    locale: Optional[str] = Field(
        None, title="Locale", description="Filter by locale, e.g. en-us (optional)"
    )
    sort_by: Optional[str] = Field(
        None,
        title="Sort By",
        description="Field to sort by",
        json_schema_extra={
            "enum": ["", "position", "title", "created_at", "updated_at"],
            "enumNames": ["Default", "Position", "Title", "Created At", "Updated At"],
            "x-enum-searchable": True,
        },
    )
    sort_order: Optional[str] = Field(
        None,
        title="Sort Order",
        description="Ascending or descending",
        json_schema_extra={
            "enum": ["", "asc", "desc"],
            "enumNames": ["Default", "Ascending", "Descending"],
            "x-enum-searchable": True,
        },
    )
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Number of articles per page (max 100)"
    )


class ZendeskListSectionArticlesConfig(BaseModel):
    """List articles belonging to a section."""

    operation: Literal["list_section_articles"] = Field(
        "list_section_articles",
        json_schema_extra={
            "const": "list_section_articles",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "List Section Articles",
        },
        title="List Section Articles",
    )
    section_id: str = Field(..., title="Section ID", description="The section to list articles from")
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Number of articles per page (max 100)"
    )


class ZendeskListCategoryArticlesConfig(BaseModel):
    """List articles belonging to a category."""

    operation: Literal["list_category_articles"] = Field(
        "list_category_articles",
        json_schema_extra={
            "const": "list_category_articles",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "List Category Articles",
        },
        title="List Category Articles",
    )
    category_id: str = Field(..., title="Category ID", description="The category to list articles from")
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Number of articles per page (max 100)"
    )


class ZendeskShowArticleConfig(BaseModel):
    """Retrieve a single Help Center article by ID."""

    operation: Literal["show_article"] = Field(
        "show_article",
        json_schema_extra={
            "const": "show_article",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Show Article",
        },
        title="Show Article",
    )
    article_id: str = Field(..., title="Article ID", description="The ID of the article to retrieve")


class ZendeskCreateArticleConfig(BaseModel):
    """Create a Help Center article in a section."""

    operation: Literal["create_article"] = Field(
        "create_article",
        json_schema_extra={
            "const": "create_article",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Create Article",
        },
        title="Create Article",
    )
    section_id: str = Field(..., title="Section ID", description="The section the article is created in")
    title: str = Field(..., title="Title", description="The article title")
    body: Optional[str] = Field(
        None,
        title="Body",
        description="The article body (HTML)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    locale: str = Field(
        "en-us", title="Locale", description="The article locale, e.g. en-us (required)"
    )
    permission_group_id: Optional[str] = Field(
        None,
        title="Permission Group ID",
        description="Permission group that defines who can edit the article (required on Guide Professional+)",
    )
    user_segment_id: Optional[str] = Field(
        None,
        title="User Segment ID",
        description="User segment that defines who can view the article; omit for everyone",
    )
    draft: Optional[str] = Field(
        "true",
        title="Draft",
        description="Create as a draft (unpublished)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class ZendeskUpdateArticleConfig(BaseModel):
    """Update an existing Help Center article (PATCH)."""

    operation: Literal["update_article"] = Field(
        "update_article",
        json_schema_extra={
            "const": "update_article",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Update Article",
        },
        title="Update Article",
    )
    article_id: str = Field(..., title="Article ID", description="The ID of the article to update")
    title: Optional[str] = Field(None, title="Title", description="New article title")
    body: Optional[str] = Field(
        None,
        title="Body",
        description="New article body (HTML)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    section_id: Optional[str] = Field(
        None, title="Section ID", description="Move the article to this section"
    )
    draft: Optional[str] = Field(
        None,
        title="Draft",
        description="Set draft (unpublished) state",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Unchanged", "Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class ZendeskArchiveArticleConfig(BaseModel):
    """Archive (delete) a Help Center article."""

    operation: Literal["archive_article"] = Field(
        "archive_article",
        json_schema_extra={
            "const": "archive_article",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Archive Article",
        },
        title="Archive Article",
    )
    article_id: str = Field(..., title="Article ID", description="The ID of the article to archive")


class ZendeskSearchArticlesConfig(BaseModel):
    """Search Help Center articles by query text."""

    operation: Literal["search_articles"] = Field(
        "search_articles",
        json_schema_extra={
            "const": "search_articles",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Search Articles",
        },
        title="Search Articles",
    )
    query: str = Field(..., title="Query", description="Full-text search query")
    locale: Optional[str] = Field(
        None, title="Locale", description="Restrict search to a locale, e.g. en-us (optional)"
    )
    label_names: Optional[str] = Field(
        None,
        title="Label Names",
        description="Comma-separated label names to filter by (optional)",
    )


class ZendeskGuideSearchConfig(BaseModel):
    """Unified Guide search across articles, posts, and external content."""

    operation: Literal["guide_search"] = Field(
        "guide_search",
        json_schema_extra={
            "const": "guide_search",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Unified Guide Search",
        },
        title="Unified Guide Search",
    )
    query: str = Field(..., title="Query", description="Full-text search query")
    locale: Optional[str] = Field(
        None, title="Locale", description="Restrict search to a locale, e.g. en-us (optional)"
    )


class ZendeskListArticleLabelsConfig(BaseModel):
    """List the labels attached to an article."""

    operation: Literal["list_article_labels"] = Field(
        "list_article_labels",
        json_schema_extra={
            "const": "list_article_labels",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "List Article Labels",
        },
        title="List Article Labels",
    )
    article_id: str = Field(..., title="Article ID", description="The article to read labels from")


class ZendeskCreateArticleLabelConfig(BaseModel):
    """Add a label to an article."""

    operation: Literal["create_article_label"] = Field(
        "create_article_label",
        json_schema_extra={
            "const": "create_article_label",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Create Article Label",
        },
        title="Create Article Label",
    )
    article_id: str = Field(..., title="Article ID", description="The article to add the label to")
    name: str = Field(..., title="Label Name", description="The name of the label to create")


class ZendeskDeleteArticleLabelConfig(BaseModel):
    """Remove a label from an article."""

    operation: Literal["delete_article_label"] = Field(
        "delete_article_label",
        json_schema_extra={
            "const": "delete_article_label",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Delete Article Label",
        },
        title="Delete Article Label",
    )
    article_id: str = Field(..., title="Article ID", description="The article to remove the label from")
    label_id: str = Field(..., title="Label ID", description="The ID of the label to remove")


class ZendeskListArticleAttachmentsConfig(BaseModel):
    """List the attachments on an article."""

    operation: Literal["list_article_attachments"] = Field(
        "list_article_attachments",
        json_schema_extra={
            "const": "list_article_attachments",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "List Article Attachments",
        },
        title="List Article Attachments",
    )
    article_id: str = Field(..., title="Article ID", description="The article to list attachments from")


class ZendeskShowArticleAttachmentConfig(BaseModel):
    """Retrieve a single article attachment by ID."""

    operation: Literal["show_article_attachment"] = Field(
        "show_article_attachment",
        json_schema_extra={
            "const": "show_article_attachment",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Show Article Attachment",
        },
        title="Show Article Attachment",
    )
    attachment_id: str = Field(
        ..., title="Attachment ID", description="The ID of the article attachment to retrieve"
    )


class ZendeskDeleteArticleAttachmentConfig(BaseModel):
    """Delete an article attachment by ID."""

    operation: Literal["delete_article_attachment"] = Field(
        "delete_article_attachment",
        json_schema_extra={
            "const": "delete_article_attachment",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Delete Article Attachment",
        },
        title="Delete Article Attachment",
    )
    attachment_id: str = Field(
        ..., title="Attachment ID", description="The ID of the article attachment to delete"
    )


# ---------------------------------------------------------------------------
# Family: guide-structure
# ---------------------------------------------------------------------------


class ZendeskListSectionsConfig(BaseModel):
    """List all Help Center sections."""

    operation: Literal["list_sections"] = Field(
        "list_sections",
        json_schema_extra={
            "const": "list_sections",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "List Sections",
        },
        title="List Sections",
    )
    category_id: Optional[str] = Field(
        None,
        title="Category ID",
        description="Optionally restrict to sections in this category",
    )
    locale: Optional[str] = Field(
        None,
        title="Locale",
        description="Optional locale filter, e.g. en-us",
    )


class ZendeskShowSectionConfig(BaseModel):
    """Show a single Help Center section."""

    operation: Literal["show_section"] = Field(
        "show_section",
        json_schema_extra={
            "const": "show_section",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Show Section",
        },
        title="Show Section",
    )
    section_id: str = Field(..., title="Section ID", description="The section to retrieve")


class ZendeskCreateSectionConfig(BaseModel):
    """Create a Help Center section within a category."""

    operation: Literal["create_section"] = Field(
        "create_section",
        json_schema_extra={
            "const": "create_section",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Create Section",
        },
        title="Create Section",
    )
    category_id: str = Field(
        ..., title="Category ID", description="The category the section is created in"
    )
    name: str = Field(..., title="Name", description="The section name")
    locale: str = Field(
        ...,
        title="Locale",
        description="The section's source locale, e.g. en-us (required)",
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="The section description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    position: Optional[str] = Field(
        None, title="Position", description="Sort position among sibling sections (integer)"
    )


class ZendeskUpdateSectionConfig(BaseModel):
    """Update a Help Center section."""

    operation: Literal["update_section"] = Field(
        "update_section",
        json_schema_extra={
            "const": "update_section",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Update Section",
        },
        title="Update Section",
    )
    section_id: str = Field(..., title="Section ID", description="The section to update")
    name: Optional[str] = Field(None, title="Name", description="New section name")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="New section description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    position: Optional[str] = Field(
        None, title="Position", description="New sort position (integer)"
    )
    category_id: Optional[str] = Field(
        None, title="Category ID", description="Move the section to this category"
    )


class ZendeskDeleteSectionConfig(BaseModel):
    """Delete a Help Center section."""

    operation: Literal["delete_section"] = Field(
        "delete_section",
        json_schema_extra={
            "const": "delete_section",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Delete Section",
        },
        title="Delete Section",
    )
    section_id: str = Field(..., title="Section ID", description="The section to delete")


class ZendeskListCategoriesConfig(BaseModel):
    """List all Help Center categories."""

    operation: Literal["list_categories"] = Field(
        "list_categories",
        json_schema_extra={
            "const": "list_categories",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "List Categories",
        },
        title="List Categories",
    )
    locale: Optional[str] = Field(
        None,
        title="Locale",
        description="Optional locale filter, e.g. en-us",
    )


class ZendeskShowCategoryConfig(BaseModel):
    """Show a single Help Center category."""

    operation: Literal["show_category"] = Field(
        "show_category",
        json_schema_extra={
            "const": "show_category",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Show Category",
        },
        title="Show Category",
    )
    category_id: str = Field(..., title="Category ID", description="The category to retrieve")


class ZendeskCreateCategoryConfig(BaseModel):
    """Create a Help Center category."""

    operation: Literal["create_category"] = Field(
        "create_category",
        json_schema_extra={
            "const": "create_category",
            "x-creates-resource": True,
            "x-resource-type": "zendesk_category",
            "x-resource-id-path": "data.category.id",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Create Category",
        },
        title="Create Category",
    )
    name: str = Field(..., title="Name", description="The category name")
    locale: str = Field(
        ...,
        title="Locale",
        description="The category's source locale, e.g. en-us (required)",
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="The category description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    position: Optional[str] = Field(
        None, title="Position", description="Sort position among categories (integer)"
    )


class ZendeskUpdateCategoryConfig(BaseModel):
    """Update a Help Center category."""

    operation: Literal["update_category"] = Field(
        "update_category",
        json_schema_extra={
            "const": "update_category",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Update Category",
        },
        title="Update Category",
    )
    category_id: str = Field(..., title="Category ID", description="The category to update")
    name: Optional[str] = Field(None, title="Name", description="New category name")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="New category description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    position: Optional[str] = Field(
        None, title="Position", description="New sort position (integer)"
    )


class ZendeskDeleteCategoryConfig(BaseModel):
    """Delete a Help Center category."""

    operation: Literal["delete_category"] = Field(
        "delete_category",
        json_schema_extra={
            "const": "delete_category",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Delete Category",
        },
        title="Delete Category",
    )
    category_id: str = Field(..., title="Category ID", description="The category to delete")


class ZendeskListArticleCommentsConfig(BaseModel):
    """List the comments on a Help Center article."""

    operation: Literal["list_article_comments"] = Field(
        "list_article_comments",
        json_schema_extra={
            "const": "list_article_comments",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "List Article Comments",
        },
        title="List Article Comments",
    )
    article_id: str = Field(
        ..., title="Article ID", description="The article whose comments to list"
    )


class ZendeskShowArticleCommentConfig(BaseModel):
    """Show a single comment on a Help Center article."""

    operation: Literal["show_article_comment"] = Field(
        "show_article_comment",
        json_schema_extra={
            "const": "show_article_comment",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Show Article Comment",
        },
        title="Show Article Comment",
    )
    article_id: str = Field(..., title="Article ID", description="The parent article")
    comment_id: str = Field(..., title="Comment ID", description="The comment to retrieve")


class ZendeskCreateArticleCommentConfig(BaseModel):
    """Create a comment on a Help Center article."""

    operation: Literal["create_article_comment"] = Field(
        "create_article_comment",
        json_schema_extra={
            "const": "create_article_comment",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Create Article Comment",
        },
        title="Create Article Comment",
    )
    article_id: str = Field(..., title="Article ID", description="The article to comment on")
    body: str = Field(..., title="Body", description="The comment text",
                      json_schema_extra={"ui:widget": "textarea"})
    locale: str = Field(
        ..., title="Locale", description="The comment's locale, e.g. en-us (required)"
    )
    author_id: Optional[str] = Field(
        None,
        title="Author ID",
        description="Author user ID (Help Center managers only; defaults to the API user)",
    )
    notify_subscribers: Optional[str] = Field(
        None,
        title="Notify Subscribers",
        description="Email the article's subscribers about the new comment",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class ZendeskUpdateArticleCommentConfig(BaseModel):
    """Update a comment on a Help Center article."""

    operation: Literal["update_article_comment"] = Field(
        "update_article_comment",
        json_schema_extra={
            "const": "update_article_comment",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Update Article Comment",
        },
        title="Update Article Comment",
    )
    article_id: str = Field(..., title="Article ID", description="The parent article")
    comment_id: str = Field(..., title="Comment ID", description="The comment to update")
    body: str = Field(..., title="Body", description="The new comment text",
                      json_schema_extra={"ui:widget": "textarea"})


class ZendeskDeleteArticleCommentConfig(BaseModel):
    """Delete a comment on a Help Center article."""

    operation: Literal["delete_article_comment"] = Field(
        "delete_article_comment",
        json_schema_extra={
            "const": "delete_article_comment",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Delete Article Comment",
        },
        title="Delete Article Comment",
    )
    article_id: str = Field(..., title="Article ID", description="The parent article")
    comment_id: str = Field(..., title="Comment ID", description="The comment to delete")


class ZendeskListArticleSubscriptionsConfig(BaseModel):
    """List the subscriptions on a Help Center article."""

    operation: Literal["list_article_subscriptions"] = Field(
        "list_article_subscriptions",
        json_schema_extra={
            "const": "list_article_subscriptions",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "List Article Subscriptions",
        },
        title="List Article Subscriptions",
    )
    article_id: str = Field(
        ..., title="Article ID", description="The article whose subscriptions to list"
    )


class ZendeskCreateArticleSubscriptionConfig(BaseModel):
    """Subscribe a user to a Help Center article."""

    operation: Literal["create_article_subscription"] = Field(
        "create_article_subscription",
        json_schema_extra={
            "const": "create_article_subscription",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Create Article Subscription",
        },
        title="Create Article Subscription",
    )
    article_id: str = Field(..., title="Article ID", description="The article to subscribe to")
    user_id: str = Field(..., title="User ID", description="The user to subscribe")
    source_locale: Optional[str] = Field(
        None, title="Source Locale", description="Locale of the subscription, e.g. en-us"
    )


class ZendeskDeleteArticleSubscriptionConfig(BaseModel):
    """Remove a subscription from a Help Center article."""

    operation: Literal["delete_article_subscription"] = Field(
        "delete_article_subscription",
        json_schema_extra={
            "const": "delete_article_subscription",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Delete Article Subscription",
        },
        title="Delete Article Subscription",
    )
    article_id: str = Field(..., title="Article ID", description="The parent article")
    subscription_id: str = Field(
        ..., title="Subscription ID", description="The subscription to delete"
    )


class ZendeskListSectionSubscriptionsConfig(BaseModel):
    """List the subscriptions on a Help Center section."""

    operation: Literal["list_section_subscriptions"] = Field(
        "list_section_subscriptions",
        json_schema_extra={
            "const": "list_section_subscriptions",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "List Section Subscriptions",
        },
        title="List Section Subscriptions",
    )
    section_id: str = Field(
        ..., title="Section ID", description="The section whose subscriptions to list"
    )


class ZendeskCreateSectionSubscriptionConfig(BaseModel):
    """Subscribe a user to a Help Center section."""

    operation: Literal["create_section_subscription"] = Field(
        "create_section_subscription",
        json_schema_extra={
            "const": "create_section_subscription",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Create Section Subscription",
        },
        title="Create Section Subscription",
    )
    section_id: str = Field(..., title="Section ID", description="The section to subscribe to")
    user_id: str = Field(..., title="User ID", description="The user to subscribe")
    source_locale: Optional[str] = Field(
        None, title="Source Locale", description="Locale of the subscription, e.g. en-us"
    )
    include_comments: Optional[str] = Field(
        None,
        title="Include Comments",
        description="Also notify the subscriber about new article comments in the section",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class ZendeskDeleteSectionSubscriptionConfig(BaseModel):
    """Remove a subscription from a Help Center section."""

    operation: Literal["delete_section_subscription"] = Field(
        "delete_section_subscription",
        json_schema_extra={
            "const": "delete_section_subscription",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Delete Section Subscription",
        },
        title="Delete Section Subscription",
    )
    section_id: str = Field(..., title="Section ID", description="The parent section")
    subscription_id: str = Field(
        ..., title="Subscription ID", description="The subscription to delete"
    )


class ZendeskListTranslationsConfig(BaseModel):
    """List the translations of a Help Center article."""

    operation: Literal["list_translations"] = Field(
        "list_translations",
        json_schema_extra={
            "const": "list_translations",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "List Translations",
        },
        title="List Translations",
    )
    article_id: str = Field(
        ..., title="Article ID", description="The article whose translations to list"
    )


class ZendeskCreateTranslationConfig(BaseModel):
    """Add a translation to a Help Center article."""

    operation: Literal["create_translation"] = Field(
        "create_translation",
        json_schema_extra={
            "const": "create_translation",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Create Translation",
        },
        title="Create Translation",
    )
    article_id: str = Field(..., title="Article ID", description="The article to translate")
    locale: str = Field(
        ..., title="Locale", description="The translation locale, e.g. fr (required)"
    )
    title: str = Field(..., title="Title", description="The translated article title")
    body: Optional[str] = Field(
        None,
        title="Body",
        description="The translated article body (HTML)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    draft: Optional[str] = Field(
        None,
        title="Draft",
        description="Create the translation as a draft (unpublished)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class ZendeskUpdateTranslationConfig(BaseModel):
    """Update a Help Center article translation for a locale."""

    operation: Literal["update_translation"] = Field(
        "update_translation",
        json_schema_extra={
            "const": "update_translation",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Update Translation",
        },
        title="Update Translation",
    )
    article_id: str = Field(..., title="Article ID", description="The parent article")
    locale: str = Field(
        ..., title="Locale", description="The locale of the translation to update, e.g. fr"
    )
    title: Optional[str] = Field(None, title="Title", description="New translated title")
    body: Optional[str] = Field(
        None,
        title="Body",
        description="New translated body (HTML)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    draft: Optional[str] = Field(
        None,
        title="Draft",
        description="Set the translation's draft (unpublished) state",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class ZendeskDeleteTranslationConfig(BaseModel):
    """Delete a Help Center translation by its ID."""

    operation: Literal["delete_translation"] = Field(
        "delete_translation",
        json_schema_extra={
            "const": "delete_translation",
            "ui:hidden": True,
            "x-category": "Help Center",
            "x-is-trigger": False,
            "x-display-name": "Delete Translation",
        },
        title="Delete Translation",
    )
    translation_id: str = Field(
        ..., title="Translation ID", description="The translation to delete"
    )


# ---------------------------------------------------------------------------
# Family: custom-objects
# ---------------------------------------------------------------------------


class ZendeskListCustomObjectsConfig(BaseModel):
    """List all custom object types defined in the account."""

    operation: Literal["list_custom_objects"] = Field(
        "list_custom_objects",
        json_schema_extra={
            "const": "list_custom_objects",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "List Custom Objects",
        },
        title="List Custom Objects",
    )


class ZendeskShowCustomObjectConfig(BaseModel):
    """Retrieve a single custom object type by its key."""

    operation: Literal["show_custom_object"] = Field(
        "show_custom_object",
        json_schema_extra={
            "const": "show_custom_object",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "Show Custom Object",
        },
        title="Show Custom Object",
    )
    custom_object_key: str = Field(
        ..., title="Custom Object Key", description="The key of the custom object type, e.g. 'apartment'"
    )


class ZendeskCreateCustomObjectConfig(BaseModel):
    """Create a new custom object type."""

    operation: Literal["create_custom_object"] = Field(
        "create_custom_object",
        json_schema_extra={
            "const": "create_custom_object",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "Create Custom Object",
        },
        title="Create Custom Object",
    )
    key: str = Field(
        ..., title="Key", description="Unique identifier for the object type (writable on create only), e.g. 'apartment'"
    )
    title: str = Field(..., title="Title", description="Display name for the object, e.g. 'Apartment'")
    title_pluralized: str = Field(
        ..., title="Title (Plural)", description="Pluralized display name, e.g. 'Apartments'"
    )
    description: Optional[str] = Field(
        None, title="Description", description="Optional description of the object type"
    )


class ZendeskUpdateCustomObjectConfig(BaseModel):
    """Update an existing custom object type."""

    operation: Literal["update_custom_object"] = Field(
        "update_custom_object",
        json_schema_extra={
            "const": "update_custom_object",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "Update Custom Object",
        },
        title="Update Custom Object",
    )
    key: str = Field(..., title="Key", description="The key of the custom object type to update")
    title: Optional[str] = Field(None, title="Title", description="New display name")
    title_pluralized: Optional[str] = Field(
        None, title="Title (Plural)", description="New pluralized display name"
    )
    description: Optional[str] = Field(None, title="Description", description="New description")


class ZendeskDeleteCustomObjectConfig(BaseModel):
    """Delete a custom object type by its key."""

    operation: Literal["delete_custom_object"] = Field(
        "delete_custom_object",
        json_schema_extra={
            "const": "delete_custom_object",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "Delete Custom Object",
        },
        title="Delete Custom Object",
    )
    key: str = Field(..., title="Key", description="The key of the custom object type to delete")


class ZendeskListCustomObjectRecordsConfig(BaseModel):
    """List the records of a custom object type."""

    operation: Literal["list_custom_object_records"] = Field(
        "list_custom_object_records",
        json_schema_extra={
            "const": "list_custom_object_records",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "List Custom Object Records",
        },
        title="List Custom Object Records",
    )
    custom_object_key: str = Field(
        ..., title="Custom Object Key", description="The key of the custom object type"
    )
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Number of records per page (max 100)"
    )


class ZendeskShowCustomObjectRecordConfig(BaseModel):
    """Retrieve a single custom object record by ID."""

    operation: Literal["show_custom_object_record"] = Field(
        "show_custom_object_record",
        json_schema_extra={
            "const": "show_custom_object_record",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "Show Custom Object Record",
        },
        title="Show Custom Object Record",
    )
    custom_object_key: str = Field(
        ..., title="Custom Object Key", description="The key of the custom object type"
    )
    record_id: str = Field(..., title="Record ID", description="The ID of the record to retrieve")


class ZendeskCreateCustomObjectRecordConfig(BaseModel):
    """Create a new custom object record."""

    operation: Literal["create_custom_object_record"] = Field(
        "create_custom_object_record",
        json_schema_extra={
            "const": "create_custom_object_record",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "Create Custom Object Record",
        },
        title="Create Custom Object Record",
    )
    custom_object_key: str = Field(
        ..., title="Custom Object Key", description="The key of the custom object type"
    )
    record_json: str = Field(
        ...,
        title="Record (JSON)",
        description='JSON object for the record, e.g. {"name":"Unit 4","external_id":"a-9","custom_object_fields":{"floor":4}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateCustomObjectRecordConfig(BaseModel):
    """Update an existing custom object record."""

    operation: Literal["update_custom_object_record"] = Field(
        "update_custom_object_record",
        json_schema_extra={
            "const": "update_custom_object_record",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "Update Custom Object Record",
        },
        title="Update Custom Object Record",
    )
    custom_object_key: str = Field(
        ..., title="Custom Object Key", description="The key of the custom object type"
    )
    record_id: str = Field(..., title="Record ID", description="The ID of the record to update")
    record_json: str = Field(
        ...,
        title="Record (JSON)",
        description='JSON object of fields to update, e.g. {"custom_object_fields":{"floor":5}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteCustomObjectRecordConfig(BaseModel):
    """Delete a custom object record by ID."""

    operation: Literal["delete_custom_object_record"] = Field(
        "delete_custom_object_record",
        json_schema_extra={
            "const": "delete_custom_object_record",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "Delete Custom Object Record",
        },
        title="Delete Custom Object Record",
    )
    custom_object_key: str = Field(
        ..., title="Custom Object Key", description="The key of the custom object type"
    )
    record_id: str = Field(..., title="Record ID", description="The ID of the record to delete")


class ZendeskUpsertCustomObjectRecordConfig(BaseModel):
    """Create or update a custom object record matched by external id or name."""

    operation: Literal["upsert_custom_object_record"] = Field(
        "upsert_custom_object_record",
        json_schema_extra={
            "const": "upsert_custom_object_record",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "Upsert Custom Object Record",
        },
        title="Upsert Custom Object Record",
    )
    custom_object_key: str = Field(
        ..., title="Custom Object Key", description="The key of the custom object type"
    )
    match_by: str = Field(
        "external_id",
        title="Match By",
        description="Which identifier to match the record on (external id or name)",
        json_schema_extra={
            "enum": ["external_id", "name"],
            "enumNames": ["External ID", "Name"],
            "x-enum-searchable": True,
        },
    )
    match_value: str = Field(
        ..., title="Match Value", description="The external id or name value to match/create on"
    )
    record_json: str = Field(
        ...,
        title="Record (JSON)",
        description='JSON object for the record, e.g. {"name":"Unit 4","custom_object_fields":{"floor":4}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskSearchCustomObjectRecordsConfig(BaseModel):
    """Search a custom object type's records with a text/filter query."""

    operation: Literal["search_custom_object_records"] = Field(
        "search_custom_object_records",
        json_schema_extra={
            "const": "search_custom_object_records",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "Search Custom Object Records",
        },
        title="Search Custom Object Records",
    )
    custom_object_key: str = Field(
        ..., title="Custom Object Key", description="The key of the custom object type"
    )
    query: str = Field(
        ..., title="Query", description="Search query string, e.g. 'Unit 4' (use '*' to match all)"
    )
    sort: Optional[str] = Field(
        None,
        title="Sort",
        description="Sort order; without a sort only the first 10,000 records are returned",
        json_schema_extra={
            "enum": ["", "name", "-name", "created_at", "-created_at", "updated_at", "-updated_at"],
            "enumNames": [
                "Relevance",
                "Name (Asc)",
                "Name (Desc)",
                "Created (Asc)",
                "Created (Desc)",
                "Updated (Asc)",
                "Updated (Desc)",
            ],
            "x-enum-searchable": True,
        },
    )


class ZendeskCountCustomObjectRecordsConfig(BaseModel):
    """Return the total count of records for a custom object type."""

    operation: Literal["count_custom_object_records"] = Field(
        "count_custom_object_records",
        json_schema_extra={
            "const": "count_custom_object_records",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "Count Custom Object Records",
        },
        title="Count Custom Object Records",
    )
    custom_object_key: str = Field(
        ..., title="Custom Object Key", description="The key of the custom object type"
    )


class ZendeskListCustomObjectFieldsConfig(BaseModel):
    """List the fields defined on a custom object type."""

    operation: Literal["list_custom_object_fields"] = Field(
        "list_custom_object_fields",
        json_schema_extra={
            "const": "list_custom_object_fields",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "List Custom Object Fields",
        },
        title="List Custom Object Fields",
    )
    custom_object_key: str = Field(
        ..., title="Custom Object Key", description="The key of the custom object type"
    )


class ZendeskShowCustomObjectFieldConfig(BaseModel):
    """Retrieve a single custom object field by key or ID."""

    operation: Literal["show_custom_object_field"] = Field(
        "show_custom_object_field",
        json_schema_extra={
            "const": "show_custom_object_field",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "Show Custom Object Field",
        },
        title="Show Custom Object Field",
    )
    custom_object_key: str = Field(
        ..., title="Custom Object Key", description="The key of the custom object type"
    )
    field_key_or_id: str = Field(
        ..., title="Field Key or ID", description="The key or numeric ID of the field to retrieve"
    )


class ZendeskCreateCustomObjectFieldConfig(BaseModel):
    """Create a new field on a custom object type."""

    operation: Literal["create_custom_object_field"] = Field(
        "create_custom_object_field",
        json_schema_extra={
            "const": "create_custom_object_field",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "Create Custom Object Field",
        },
        title="Create Custom Object Field",
    )
    custom_object_key: str = Field(
        ..., title="Custom Object Key", description="The key of the custom object type"
    )
    field_json: str = Field(
        ...,
        title="Field (JSON)",
        description='JSON object for the field, e.g. {"type":"text","key":"floor","title":"Floor"}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskUpdateCustomObjectFieldConfig(BaseModel):
    """Update an existing custom object field."""

    operation: Literal["update_custom_object_field"] = Field(
        "update_custom_object_field",
        json_schema_extra={
            "const": "update_custom_object_field",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "Update Custom Object Field",
        },
        title="Update Custom Object Field",
    )
    custom_object_key: str = Field(
        ..., title="Custom Object Key", description="The key of the custom object type"
    )
    field_key_or_id: str = Field(
        ..., title="Field Key or ID", description="The key or numeric ID of the field to update"
    )
    field_json: str = Field(
        ...,
        title="Field (JSON)",
        description='JSON object of field properties to update, e.g. {"title":"Floor Number"}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteCustomObjectFieldConfig(BaseModel):
    """Delete a custom object field by key or ID."""

    operation: Literal["delete_custom_object_field"] = Field(
        "delete_custom_object_field",
        json_schema_extra={
            "const": "delete_custom_object_field",
            "ui:hidden": True,
            "x-category": "Custom Objects",
            "x-is-trigger": False,
            "x-display-name": "Delete Custom Object Field",
        },
        title="Delete Custom Object Field",
    )
    custom_object_key: str = Field(
        ..., title="Custom Object Key", description="The key of the custom object type"
    )
    field_key_or_id: str = Field(
        ..., title="Field Key or ID", description="The key or numeric ID of the field to delete"
    )


# ---------------------------------------------------------------------------
# Family: events-talk-chat
# ---------------------------------------------------------------------------


class ZendeskGetUserEventsConfig(BaseModel):
    """Get the events tracked for a Zendesk user."""

    operation: Literal["get_user_events"] = Field(
        "get_user_events",
        json_schema_extra={
            "const": "get_user_events",
            "ui:hidden": True,
            "x-category": "Events",
            "x-is-trigger": False,
            "x-display-name": "Get User Events",
        },
        title="Get User Events",
    )
    user_id: str = Field(..., title="User ID", description="The Zendesk user whose events to return")


class ZendeskTrackUserEventConfig(BaseModel):
    """Store (track) an event for a Zendesk user."""

    operation: Literal["track_user_event"] = Field(
        "track_user_event",
        json_schema_extra={
            "const": "track_user_event",
            "ui:hidden": True,
            "x-category": "Events",
            "x-is-trigger": False,
            "x-display-name": "Track User Event",
        },
        title="Track User Event",
    )
    user_id: str = Field(..., title="User ID", description="The Zendesk user to attach the event to")
    event_json: str = Field(
        ...,
        title="Event JSON",
        description='The event object with source, type and properties, e.g. {"source":"my_app","type":"purchase","properties":{"amount":10}}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    profile_json: Optional[str] = Field(
        None,
        title="Profile JSON",
        description='Optional profile object identifying the user, e.g. {"source":"my_app","type":"customer","identifiers":[{"type":"email","value":"a@b.com"}]}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskShowProfileConfig(BaseModel):
    """Show a user profile by its profile id."""

    operation: Literal["show_profile"] = Field(
        "show_profile",
        json_schema_extra={
            "const": "show_profile",
            "ui:hidden": True,
            "x-category": "Events",
            "x-is-trigger": False,
            "x-display-name": "Show Profile",
        },
        title="Show Profile",
    )
    profile_id: str = Field(..., title="Profile ID", description="The profile id to retrieve")


class ZendeskCreateUpdateProfileConfig(BaseModel):
    """Create or update a user profile (identified by an identifier query)."""

    operation: Literal["create_update_profile"] = Field(
        "create_update_profile",
        json_schema_extra={
            "const": "create_update_profile",
            "ui:hidden": True,
            "x-category": "Events",
            "x-is-trigger": False,
            "x-display-name": "Create or Update Profile",
        },
        title="Create or Update Profile",
    )
    user_id: str = Field(..., title="User ID", description="The Zendesk user the profile belongs to")
    identifier: str = Field(
        ...,
        title="Identifier",
        description="Identifier query of the form <source>:<type>:<identifier_key>:<identifier_value>",
    )
    profile_json: str = Field(
        ...,
        title="Profile JSON",
        description='The full request body, e.g. {"profile":{"source":"my_app","type":"customer","identifiers":[{"type":"email","value":"a@b.com"}],"attributes":{}}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ZendeskDeleteProfileConfig(BaseModel):
    """Delete a user profile by its profile id."""

    operation: Literal["delete_profile"] = Field(
        "delete_profile",
        json_schema_extra={
            "const": "delete_profile",
            "ui:hidden": True,
            "x-category": "Events",
            "x-is-trigger": False,
            "x-display-name": "Delete Profile",
        },
        title="Delete Profile",
    )
    profile_id: str = Field(..., title="Profile ID", description="The profile id to delete")


class ZendeskCurrentQueueActivityConfig(BaseModel):
    """Show Talk's current voice queue activity snapshot."""

    operation: Literal["current_queue_activity"] = Field(
        "current_queue_activity",
        json_schema_extra={
            "const": "current_queue_activity",
            "ui:hidden": True,
            "x-category": "Talk",
            "x-is-trigger": False,
            "x-display-name": "Current Queue Activity",
        },
        title="Current Queue Activity",
    )


class ZendeskAgentsActivityConfig(BaseModel):
    """Show per-agent Talk voice activity stats."""

    operation: Literal["agents_activity"] = Field(
        "agents_activity",
        json_schema_extra={
            "const": "agents_activity",
            "ui:hidden": True,
            "x-category": "Talk",
            "x-is-trigger": False,
            "x-display-name": "Agents Activity",
        },
        title="Agents Activity",
    )


class ZendeskShowAvailabilityConfig(BaseModel):
    """Show a Talk agent's voice availability."""

    operation: Literal["show_availability"] = Field(
        "show_availability",
        json_schema_extra={
            "const": "show_availability",
            "ui:hidden": True,
            "x-category": "Talk",
            "x-is-trigger": False,
            "x-display-name": "Show Availability",
        },
        title="Show Availability",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent whose availability to read")


class ZendeskUpdateAvailabilityConfig(BaseModel):
    """Update a Talk agent's voice availability state."""

    operation: Literal["update_availability"] = Field(
        "update_availability",
        json_schema_extra={
            "const": "update_availability",
            "ui:hidden": True,
            "x-category": "Talk",
            "x-is-trigger": False,
            "x-display-name": "Update Availability",
        },
        title="Update Availability",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent whose availability to update")
    agent_state: str = Field(
        "available",
        title="Agent State",
        description="The voice availability state to set for the agent",
        json_schema_extra={
            "enum": ["available", "offline", "transfers_only", "away", "wrap_up"],
            "x-enum-searchable": True,
        },
    )
    via: Optional[str] = Field(
        None, title="Via", description="Optional source of the change (e.g. agent_workspace)"
    )


class ZendeskCreateVoicemailTicketConfig(BaseModel):
    """Create a Talk Partner Edition voice / voicemail ticket."""

    operation: Literal["create_voicemail_ticket"] = Field(
        "create_voicemail_ticket",
        json_schema_extra={
            "const": "create_voicemail_ticket",
            "ui:hidden": True,
            "x-category": "Talk",
            "x-is-trigger": False,
            "x-display-name": "Create Voicemail Ticket",
        },
        title="Create Voicemail Ticket",
    )
    ticket_json: str = Field(
        ...,
        title="Ticket JSON",
        description='The ticket object (must include via_id and a voice_comment), e.g. {"via_id":44,"description":"Voicemail","voice_comment":{"from":"+16617480240","to":"+16617480123","recording_url":"https://example.com/1.mp3","started_at":"2019-04-16T09:14:57Z","call_duration":40}}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    display_to_agent: Optional[str] = Field(
        None,
        title="Display To Agent",
        description="Optional agent id who should see the newly created ticket",
    )


class ZendeskListChatsConfig(BaseModel):
    """List Chat conversations (Chat REST API)."""

    operation: Literal["list_chats"] = Field(
        "list_chats",
        json_schema_extra={
            "const": "list_chats",
            "ui:hidden": True,
            "x-category": "Chat",
            "x-is-trigger": False,
            "x-display-name": "List Chats",
        },
        title="List Chats",
    )
    ids: Optional[str] = Field(
        None, title="Chat IDs", description="Optional comma-separated chat ids to filter to"
    )


class ZendeskShowChatConfig(BaseModel):
    """Show a single Chat conversation by id."""

    operation: Literal["show_chat"] = Field(
        "show_chat",
        json_schema_extra={
            "const": "show_chat",
            "ui:hidden": True,
            "x-category": "Chat",
            "x-is-trigger": False,
            "x-display-name": "Show Chat",
        },
        title="Show Chat",
    )
    chat_id: str = Field(..., title="Chat ID", description="The chat id to retrieve")


class ZendeskListAgentsConfig(BaseModel):
    """List Chat agents (Chat REST API)."""

    operation: Literal["list_agents"] = Field(
        "list_agents",
        json_schema_extra={
            "const": "list_agents",
            "ui:hidden": True,
            "x-category": "Chat",
            "x-is-trigger": False,
            "x-display-name": "List Agents",
        },
        title="List Agents",
    )


class ZendeskShowAgentConfig(BaseModel):
    """Show a single Chat agent by id."""

    operation: Literal["show_agent"] = Field(
        "show_agent",
        json_schema_extra={
            "const": "show_agent",
            "ui:hidden": True,
            "x-category": "Chat",
            "x-is-trigger": False,
            "x-display-name": "Show Agent",
        },
        title="Show Agent",
    )
    agent_id: str = Field(..., title="Agent ID", description="The Chat agent id to retrieve")


class ZendeskListDepartmentsConfig(BaseModel):
    """List Chat departments (Chat REST API)."""

    operation: Literal["list_departments"] = Field(
        "list_departments",
        json_schema_extra={
            "const": "list_departments",
            "ui:hidden": True,
            "x-category": "Chat",
            "x-is-trigger": False,
            "x-display-name": "List Departments",
        },
        title="List Departments",
    )


# ---------------------------------------------------------------------------
# Phase 3: Sunshine Conversations (messaging) — uses ZendeskConversationsCredential
# ---------------------------------------------------------------------------


class ZendeskSCCCreateUserConfig(BaseModel):
    """Create a Sunshine Conversations user."""

    operation: Literal["scc_create_user"] = Field(
        "scc_create_user",
        json_schema_extra={"const": "scc_create_user", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Create User"},
        title="SCC: Create User",
    )
    external_id: str = Field(..., title="External ID", description="Your external identifier for the user")
    profile_json: Optional[str] = Field(None, title="Profile (JSON)", description='Optional profile object, e.g. {"givenName":"Jane"}', json_schema_extra={"ui:widget": "textarea"})
    metadata_json: Optional[str] = Field(None, title="Metadata (JSON)", description="Optional metadata object", json_schema_extra={"ui:widget": "textarea"})


class ZendeskSCCGetUserConfig(BaseModel):
    """Get a Sunshine Conversations user by ID or external ID."""

    operation: Literal["scc_get_user"] = Field(
        "scc_get_user",
        json_schema_extra={"const": "scc_get_user", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Get User"},
        title="SCC: Get User",
    )
    user_id: str = Field(..., title="User ID", description="User ID or externalId")


class ZendeskSCCUpdateUserConfig(BaseModel):
    """Update a Sunshine Conversations user's profile/metadata."""

    operation: Literal["scc_update_user"] = Field(
        "scc_update_user",
        json_schema_extra={"const": "scc_update_user", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Update User"},
        title="SCC: Update User",
    )
    user_id: str = Field(..., title="User ID", description="User ID or externalId")
    profile_json: Optional[str] = Field(None, title="Profile (JSON)", json_schema_extra={"ui:widget": "textarea"})
    metadata_json: Optional[str] = Field(None, title="Metadata (JSON)", json_schema_extra={"ui:widget": "textarea"})


class ZendeskSCCDeleteUserConfig(BaseModel):
    """Delete a Sunshine Conversations user."""

    operation: Literal["scc_delete_user"] = Field(
        "scc_delete_user",
        json_schema_extra={"const": "scc_delete_user", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Delete User"},
        title="SCC: Delete User",
    )
    user_id: str = Field(..., title="User ID", description="User ID or externalId")


class ZendeskSCCListUsersConfig(BaseModel):
    """Find Sunshine Conversations users by email (SCC requires a filter)."""

    operation: Literal["scc_list_users"] = Field(
        "scc_list_users",
        json_schema_extra={"const": "scc_list_users", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Find Users by Email"},
        title="SCC: Find Users by Email",
    )
    email: str = Field(..., title="Email", description="Match users whose identity email equals this address")
    page_size: Optional[str] = Field(None, title="Page Size")
    page_after: Optional[str] = Field(None, title="Cursor (after)", description="page[after] cursor from a previous response")


class ZendeskSCCCreateConversationConfig(BaseModel):
    """Create a Sunshine Conversations conversation."""

    operation: Literal["scc_create_conversation"] = Field(
        "scc_create_conversation",
        json_schema_extra={"const": "scc_create_conversation", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Create Conversation"},
        title="SCC: Create Conversation",
    )
    conversation_type: str = Field("personal", title="Type", json_schema_extra={"enum": ["personal", "sdkGroup"], "x-enum-searchable": True})
    user_id: Optional[str] = Field(None, title="Participant User ID", description="User to add as the initial participant")
    display_name: Optional[str] = Field(None, title="Display Name")
    metadata_json: Optional[str] = Field(None, title="Metadata (JSON)", json_schema_extra={"ui:widget": "textarea"})


class ZendeskSCCGetConversationConfig(BaseModel):
    """Get a Sunshine Conversations conversation."""

    operation: Literal["scc_get_conversation"] = Field(
        "scc_get_conversation",
        json_schema_extra={"const": "scc_get_conversation", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Get Conversation"},
        title="SCC: Get Conversation",
    )
    conversation_id: str = Field(..., title="Conversation ID")


class ZendeskSCCListConversationsConfig(BaseModel):
    """List conversations, optionally filtered by user."""

    operation: Literal["scc_list_conversations"] = Field(
        "scc_list_conversations",
        json_schema_extra={"const": "scc_list_conversations", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: List Conversations"},
        title="SCC: List Conversations",
    )
    user_id: str = Field(..., title="User ID", description="filter[userId] — conversations for this user")
    page_after: Optional[str] = Field(None, title="Cursor (after)")


class ZendeskSCCUpdateConversationConfig(BaseModel):
    """Update a conversation's display name / metadata."""

    operation: Literal["scc_update_conversation"] = Field(
        "scc_update_conversation",
        json_schema_extra={"const": "scc_update_conversation", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Update Conversation"},
        title="SCC: Update Conversation",
    )
    conversation_id: str = Field(..., title="Conversation ID")
    display_name: Optional[str] = Field(None, title="Display Name")
    metadata_json: Optional[str] = Field(None, title="Metadata (JSON)", json_schema_extra={"ui:widget": "textarea"})


class ZendeskSCCDeleteConversationConfig(BaseModel):
    """Delete a conversation."""

    operation: Literal["scc_delete_conversation"] = Field(
        "scc_delete_conversation",
        json_schema_extra={"const": "scc_delete_conversation", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Delete Conversation"},
        title="SCC: Delete Conversation",
    )
    conversation_id: str = Field(..., title="Conversation ID")


class ZendeskSCCPostMessageConfig(BaseModel):
    """Post a message to a conversation."""

    operation: Literal["scc_post_message"] = Field(
        "scc_post_message",
        json_schema_extra={"const": "scc_post_message", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Post Message"},
        title="SCC: Post Message",
    )
    conversation_id: str = Field(..., title="Conversation ID")
    text: str = Field(..., title="Text", description="Message text")
    author_type: str = Field("business", title="Author Type", json_schema_extra={"enum": ["business", "user"], "x-enum-searchable": True})
    author_user_id: Optional[str] = Field(None, title="Author User ID", description="Required when Author Type is 'user'")


class ZendeskSCCListMessagesConfig(BaseModel):
    """List messages in a conversation (max 100/page)."""

    operation: Literal["scc_list_messages"] = Field(
        "scc_list_messages",
        json_schema_extra={"const": "scc_list_messages", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: List Messages"},
        title="SCC: List Messages",
    )
    conversation_id: str = Field(..., title="Conversation ID")
    page_size: Optional[str] = Field(None, title="Page Size", description="Max 100")
    page_after: Optional[str] = Field(None, title="Cursor (after)")


class ZendeskSCCDeleteMessageConfig(BaseModel):
    """Delete a single message."""

    operation: Literal["scc_delete_message"] = Field(
        "scc_delete_message",
        json_schema_extra={"const": "scc_delete_message", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Delete Message"},
        title="SCC: Delete Message",
    )
    conversation_id: str = Field(..., title="Conversation ID")
    message_id: str = Field(..., title="Message ID")


class ZendeskSCCDeleteAllMessagesConfig(BaseModel):
    """Delete all messages in a conversation."""

    operation: Literal["scc_delete_all_messages"] = Field(
        "scc_delete_all_messages",
        json_schema_extra={"const": "scc_delete_all_messages", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Delete All Messages"},
        title="SCC: Delete All Messages",
    )
    conversation_id: str = Field(..., title="Conversation ID")


class ZendeskSCCPostActivityConfig(BaseModel):
    """Post a conversation activity (typing / read)."""

    operation: Literal["scc_post_activity"] = Field(
        "scc_post_activity",
        json_schema_extra={"const": "scc_post_activity", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Post Activity"},
        title="SCC: Post Activity",
    )
    conversation_id: str = Field(..., title="Conversation ID")
    activity_type: str = Field("conversation:read", title="Activity", json_schema_extra={"enum": ["conversation:read", "typing:start", "typing:stop"], "x-enum-searchable": True})
    author_type: str = Field("business", title="Author Type", json_schema_extra={"enum": ["business", "user"], "x-enum-searchable": True})
    author_user_id: Optional[str] = Field(None, title="Author User ID", description="Required when Author Type is 'user'")


class ZendeskSCCPassControlConfig(BaseModel):
    """Pass switchboard control of a conversation to another integration."""

    operation: Literal["scc_pass_control"] = Field(
        "scc_pass_control",
        json_schema_extra={"const": "scc_pass_control", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Pass Control"},
        title="SCC: Pass Control",
    )
    conversation_id: str = Field(..., title="Conversation ID")
    switchboard_integration: str = Field(..., title="Switchboard Integration", description="Target switchboard integration name or ID")
    metadata_json: Optional[str] = Field(None, title="Metadata (JSON)", json_schema_extra={"ui:widget": "textarea"})


class ZendeskSCCOfferControlConfig(BaseModel):
    """Offer switchboard control of a conversation."""

    operation: Literal["scc_offer_control"] = Field(
        "scc_offer_control",
        json_schema_extra={"const": "scc_offer_control", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Offer Control"},
        title="SCC: Offer Control",
    )
    conversation_id: str = Field(..., title="Conversation ID")
    switchboard_integration: str = Field(..., title="Switchboard Integration")


class ZendeskSCCAcceptControlConfig(BaseModel):
    """Accept offered switchboard control."""

    operation: Literal["scc_accept_control"] = Field(
        "scc_accept_control",
        json_schema_extra={"const": "scc_accept_control", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Accept Control"},
        title="SCC: Accept Control",
    )
    conversation_id: str = Field(..., title="Conversation ID")
    metadata_json: Optional[str] = Field(None, title="Metadata (JSON)", json_schema_extra={"ui:widget": "textarea"})


class ZendeskSCCReleaseControlConfig(BaseModel):
    """Release switchboard control back to the default integration."""

    operation: Literal["scc_release_control"] = Field(
        "scc_release_control",
        json_schema_extra={"const": "scc_release_control", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Release Control"},
        title="SCC: Release Control",
    )
    conversation_id: str = Field(..., title="Conversation ID")


class ZendeskSCCListIntegrationsConfig(BaseModel):
    """List Sunshine Conversations integrations."""

    operation: Literal["scc_list_integrations"] = Field(
        "scc_list_integrations",
        json_schema_extra={"const": "scc_list_integrations", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: List Integrations"},
        title="SCC: List Integrations",
    )


class ZendeskSCCCreateIntegrationConfig(BaseModel):
    """Create a Sunshine Conversations integration."""

    operation: Literal["scc_create_integration"] = Field(
        "scc_create_integration",
        json_schema_extra={"const": "scc_create_integration", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Create Integration"},
        title="SCC: Create Integration",
    )
    integration_json: str = Field(..., title="Integration (JSON)", description='Integration object, e.g. {"type":"custom","displayName":"..."}', json_schema_extra={"ui:widget": "textarea"})


class ZendeskSCCListWebhooksConfig(BaseModel):
    """List webhooks on a custom integration."""

    operation: Literal["scc_list_webhooks"] = Field(
        "scc_list_webhooks",
        json_schema_extra={"const": "scc_list_webhooks", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: List Webhooks"},
        title="SCC: List Webhooks",
    )
    integration_id: str = Field(..., title="Integration ID")


class ZendeskSCCCreateWebhookConfig(BaseModel):
    """Create a webhook on a custom integration."""

    operation: Literal["scc_create_webhook"] = Field(
        "scc_create_webhook",
        json_schema_extra={"const": "scc_create_webhook", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "SCC: Create Webhook"},
        title="SCC: Create Webhook",
    )
    integration_id: str = Field(..., title="Integration ID")
    target: str = Field(..., title="Target URL", description="HTTPS URL that receives webhook deliveries")
    triggers: str = Field(..., title="Triggers", description="Comma-separated triggers, e.g. conversation:message,conversation:read")
    include_full_user: str = Field("false", title="Include Full User", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})


# ============================================================================
# Discriminated Union
# ============================================================================


ZendeskConfig = Annotated[
    Union[
        ZendeskListTicketsConfig,
        ZendeskShowTicketConfig,
        ZendeskCreateTicketConfig,
        ZendeskUpdateTicketConfig,
        ZendeskDeleteTicketConfig,
        ZendeskCreateManyTicketsConfig,
        ZendeskUpdateManyTicketsConfig,
        ZendeskMergeTicketsConfig,
        ZendeskListCommentsConfig,
        ZendeskAddCommentConfig,
        ZendeskAddTagsConfig,
        ZendeskListAuditsConfig,
        ZendeskCountTicketsConfig,
        ZendeskShowManyTicketsConfig,
        ZendeskDestroyManyTicketsConfig,
        ZendeskMarkTicketAsSpamConfig,
        ZendeskListOrganizationTicketsConfig,
        ZendeskListUserTicketsConfig,
        ZendeskListTicketTagsConfig,
        ZendeskSetTicketTagsConfig,
        ZendeskRemoveTicketTagsConfig,
        ZendeskMakeCommentPrivateConfig,
        ZendeskCreateSatisfactionRatingConfig,
        ZendeskListIncrementalTicketsConfig,
        ZendeskUploadFileConfig,
        ZendeskSearchConfig,
        ZendeskSearchUsersConfig,
        ZendeskListUsersConfig,
        ZendeskShowUserConfig,
        ZendeskCreateUserConfig,
        ZendeskCreateOrUpdateUserConfig,
        ZendeskUpdateUserConfig,
        ZendeskDeleteUserConfig,
        ZendeskListOrganizationsConfig,
        ZendeskCreateOrganizationConfig,
        ZendeskUpdateOrganizationConfig,
        ZendeskDeleteOrganizationConfig,
        ZendeskListGroupsConfig,
        ZendeskListTicketFieldsConfig,
        ZendeskListSatisfactionRatingsConfig,
        ZendeskShowJobStatusConfig,
        ZendeskCreateWebhookConfig,
        ZendeskShowManyUsersConfig,
        ZendeskCreateManyUsersConfig,
        ZendeskCreateOrUpdateManyUsersConfig,
        ZendeskUpdateManyUsersConfig,
        ZendeskBulkDeleteUsersConfig,
        ZendeskPermanentlyDeleteUserConfig,
        ZendeskMergeEndUsersConfig,
        ZendeskAutocompleteUsersConfig,
        ZendeskCountUsersConfig,
        ZendeskShowUserRelatedConfig,
        ZendeskShowSelfConfig,
        ZendeskListUsersByGroupConfig,
        ZendeskListUsersByOrganizationConfig,
        ZendeskListIdentitiesConfig,
        ZendeskShowIdentityConfig,
        ZendeskCreateIdentityConfig,
        ZendeskUpdateIdentityConfig,
        ZendeskDeleteIdentityConfig,
        ZendeskMakeIdentityPrimaryConfig,
        ZendeskVerifyIdentityConfig,
        ZendeskRequestIdentityVerificationConfig,
        ZendeskListUserFieldsConfig,
        ZendeskShowUserFieldConfig,
        ZendeskCreateUserFieldConfig,
        ZendeskUpdateUserFieldConfig,
        ZendeskDeleteUserFieldConfig,
        ZendeskListUserFieldOptionsConfig,
        ZendeskCreateUserFieldOptionConfig,
        ZendeskUpdateUserFieldOptionConfig,
        ZendeskDeleteUserFieldOptionConfig,
        ZendeskShowOrganizationConfig,
        ZendeskShowManyOrganizationsConfig,
        ZendeskCreateManyOrganizationsConfig,
        ZendeskCreateOrUpdateOrganizationConfig,
        ZendeskUpdateManyOrganizationsConfig,
        ZendeskDestroyManyOrganizationsConfig,
        ZendeskSearchOrganizationsConfig,
        ZendeskCountOrganizationsConfig,
        ZendeskRelatedOrganizationsConfig,
        ZendeskMergeOrganizationConfig,
        ZendeskListOrganizationFieldsConfig,
        ZendeskShowOrganizationFieldConfig,
        ZendeskCreateOrganizationFieldConfig,
        ZendeskUpdateOrganizationFieldConfig,
        ZendeskDeleteOrganizationFieldConfig,
        ZendeskListOrganizationMembershipsConfig,
        ZendeskListUserOrganizationMembershipsConfig,
        ZendeskShowOrganizationMembershipConfig,
        ZendeskCreateOrganizationMembershipConfig,
        ZendeskCreateManyOrganizationMembershipsConfig,
        ZendeskDeleteOrganizationMembershipConfig,
        ZendeskSetDefaultOrganizationMembershipConfig,
        ZendeskListOrganizationSubscriptionsConfig,
        ZendeskShowOrganizationSubscriptionConfig,
        ZendeskCreateOrganizationSubscriptionConfig,
        ZendeskDeleteOrganizationSubscriptionConfig,
        ZendeskShowGroupConfig,
        ZendeskCreateGroupConfig,
        ZendeskUpdateGroupConfig,
        ZendeskDeleteGroupConfig,
        ZendeskListAssignableGroupsConfig,
        ZendeskListGroupMembershipsConfig,
        ZendeskListUserGroupMembershipsConfig,
        ZendeskListGroupMembershipsByGroupConfig,
        ZendeskShowGroupMembershipConfig,
        ZendeskCreateGroupMembershipConfig,
        ZendeskCreateManyGroupMembershipsConfig,
        ZendeskDeleteGroupMembershipConfig,
        ZendeskSetDefaultGroupMembershipConfig,
        ZendeskListAssignableGroupMembershipsConfig,
        ZendeskListCustomRolesConfig,
        ZendeskShowCustomRoleConfig,
        ZendeskCreateCustomRoleConfig,
        ZendeskUpdateCustomRoleConfig,
        ZendeskDeleteCustomRoleConfig,
        ZendeskListUserSessionsConfig,
        ZendeskShowSessionConfig,
        ZendeskDeleteSessionConfig,
        ZendeskShowCurrentSessionConfig,
        ZendeskLogoutCurrentSessionConfig,
        ZendeskShowTicketFieldConfig,
        ZendeskCreateTicketFieldConfig,
        ZendeskUpdateTicketFieldConfig,
        ZendeskDeleteTicketFieldConfig,
        ZendeskListTicketFieldOptionsConfig,
        ZendeskShowTicketFieldOptionConfig,
        ZendeskCreateTicketFieldOptionConfig,
        ZendeskUpdateTicketFieldOptionConfig,
        ZendeskDeleteTicketFieldOptionConfig,
        ZendeskListTicketFormsConfig,
        ZendeskShowTicketFormConfig,
        ZendeskCreateTicketFormConfig,
        ZendeskUpdateTicketFormConfig,
        ZendeskDeleteTicketFormConfig,
        ZendeskListCustomStatusesConfig,
        ZendeskShowCustomStatusConfig,
        ZendeskCreateCustomStatusConfig,
        ZendeskUpdateCustomStatusConfig,
        ZendeskListBrandsConfig,
        ZendeskShowBrandConfig,
        ZendeskCreateBrandConfig,
        ZendeskUpdateBrandConfig,
        ZendeskDeleteBrandConfig,
        ZendeskListRequestsConfig,
        ZendeskShowRequestConfig,
        ZendeskCreateRequestConfig,
        ZendeskUpdateRequestConfig,
        ZendeskListRequestCommentsConfig,
        ZendeskListSideConversationsConfig,
        ZendeskShowSideConversationConfig,
        ZendeskCreateSideConversationConfig,
        ZendeskReplySideConversationConfig,
        ZendeskUpdateSideConversationConfig,
        ZendeskImportTicketConfig,
        ZendeskImportManyTicketsConfig,
        ZendeskIncrementalUsersConfig,
        ZendeskIncrementalOrganizationsConfig,
        ZendeskIncrementalTicketEventsConfig,
        ZendeskListMacrosConfig,
        ZendeskListActiveMacrosConfig,
        ZendeskShowMacroConfig,
        ZendeskCreateMacroConfig,
        ZendeskUpdateMacroConfig,
        ZendeskDeleteMacroConfig,
        ZendeskShowMacroChangesConfig,
        ZendeskShowTicketAfterMacroConfig,
        ZendeskListViewsConfig,
        ZendeskListActiveViewsConfig,
        ZendeskShowViewConfig,
        ZendeskCreateViewConfig,
        ZendeskUpdateViewConfig,
        ZendeskDeleteViewConfig,
        ZendeskListViewTicketsConfig,
        ZendeskExecuteViewConfig,
        ZendeskCountViewConfig,
        ZendeskExportViewConfig,
        ZendeskListTriggersConfig,
        ZendeskListActiveTriggersConfig,
        ZendeskShowTriggerConfig,
        ZendeskCreateTriggerConfig,
        ZendeskUpdateTriggerConfig,
        ZendeskDeleteTriggerConfig,
        ZendeskListAutomationsConfig,
        ZendeskListActiveAutomationsConfig,
        ZendeskShowAutomationConfig,
        ZendeskCreateAutomationConfig,
        ZendeskUpdateAutomationConfig,
        ZendeskDeleteAutomationConfig,
        ZendeskListSlaPoliciesConfig,
        ZendeskShowSlaPolicyConfig,
        ZendeskCreateSlaPolicyConfig,
        ZendeskUpdateSlaPolicyConfig,
        ZendeskDeleteSlaPolicyConfig,
        ZendeskListWebhooksConfig,
        ZendeskShowWebhookConfig,
        ZendeskUpdateWebhookConfig,
        ZendeskPatchWebhookConfig,
        ZendeskDeleteWebhookConfig,
        ZendeskCloneWebhookConfig,
        ZendeskTestWebhookConfig,
        ZendeskListWebhookInvocationsConfig,
        ZendeskListWebhookInvocationAttemptsConfig,
        ZendeskShowWebhookSigningSecretConfig,
        ZendeskResetWebhookSigningSecretConfig,
        ZendeskSearchCountConfig,
        ZendeskExportSearchConfig,
        ZendeskAutocompleteTagsConfig,
        ZendeskListArticlesConfig,
        ZendeskListSectionArticlesConfig,
        ZendeskListCategoryArticlesConfig,
        ZendeskShowArticleConfig,
        ZendeskCreateArticleConfig,
        ZendeskUpdateArticleConfig,
        ZendeskArchiveArticleConfig,
        ZendeskSearchArticlesConfig,
        ZendeskGuideSearchConfig,
        ZendeskListArticleLabelsConfig,
        ZendeskCreateArticleLabelConfig,
        ZendeskDeleteArticleLabelConfig,
        ZendeskListArticleAttachmentsConfig,
        ZendeskShowArticleAttachmentConfig,
        ZendeskDeleteArticleAttachmentConfig,
        ZendeskListSectionsConfig,
        ZendeskShowSectionConfig,
        ZendeskCreateSectionConfig,
        ZendeskUpdateSectionConfig,
        ZendeskDeleteSectionConfig,
        ZendeskListCategoriesConfig,
        ZendeskShowCategoryConfig,
        ZendeskCreateCategoryConfig,
        ZendeskUpdateCategoryConfig,
        ZendeskDeleteCategoryConfig,
        ZendeskListArticleCommentsConfig,
        ZendeskShowArticleCommentConfig,
        ZendeskCreateArticleCommentConfig,
        ZendeskUpdateArticleCommentConfig,
        ZendeskDeleteArticleCommentConfig,
        ZendeskListArticleSubscriptionsConfig,
        ZendeskCreateArticleSubscriptionConfig,
        ZendeskDeleteArticleSubscriptionConfig,
        ZendeskListSectionSubscriptionsConfig,
        ZendeskCreateSectionSubscriptionConfig,
        ZendeskDeleteSectionSubscriptionConfig,
        ZendeskListTranslationsConfig,
        ZendeskCreateTranslationConfig,
        ZendeskUpdateTranslationConfig,
        ZendeskDeleteTranslationConfig,
        ZendeskListCustomObjectsConfig,
        ZendeskShowCustomObjectConfig,
        ZendeskCreateCustomObjectConfig,
        ZendeskUpdateCustomObjectConfig,
        ZendeskDeleteCustomObjectConfig,
        ZendeskListCustomObjectRecordsConfig,
        ZendeskShowCustomObjectRecordConfig,
        ZendeskCreateCustomObjectRecordConfig,
        ZendeskUpdateCustomObjectRecordConfig,
        ZendeskDeleteCustomObjectRecordConfig,
        ZendeskUpsertCustomObjectRecordConfig,
        ZendeskSearchCustomObjectRecordsConfig,
        ZendeskCountCustomObjectRecordsConfig,
        ZendeskListCustomObjectFieldsConfig,
        ZendeskShowCustomObjectFieldConfig,
        ZendeskCreateCustomObjectFieldConfig,
        ZendeskUpdateCustomObjectFieldConfig,
        ZendeskDeleteCustomObjectFieldConfig,
        ZendeskGetUserEventsConfig,
        ZendeskTrackUserEventConfig,
        ZendeskShowProfileConfig,
        ZendeskCreateUpdateProfileConfig,
        ZendeskDeleteProfileConfig,
        ZendeskCurrentQueueActivityConfig,
        ZendeskAgentsActivityConfig,
        ZendeskShowAvailabilityConfig,
        ZendeskUpdateAvailabilityConfig,
        ZendeskCreateVoicemailTicketConfig,
        ZendeskListChatsConfig,
        ZendeskShowChatConfig,
        ZendeskListAgentsConfig,
        ZendeskShowAgentConfig,
        ZendeskListDepartmentsConfig,
        ZendeskSCCCreateUserConfig,
        ZendeskSCCGetUserConfig,
        ZendeskSCCUpdateUserConfig,
        ZendeskSCCDeleteUserConfig,
        ZendeskSCCListUsersConfig,
        ZendeskSCCCreateConversationConfig,
        ZendeskSCCGetConversationConfig,
        ZendeskSCCListConversationsConfig,
        ZendeskSCCUpdateConversationConfig,
        ZendeskSCCDeleteConversationConfig,
        ZendeskSCCPostMessageConfig,
        ZendeskSCCListMessagesConfig,
        ZendeskSCCDeleteMessageConfig,
        ZendeskSCCDeleteAllMessagesConfig,
        ZendeskSCCPostActivityConfig,
        ZendeskSCCPassControlConfig,
        ZendeskSCCOfferControlConfig,
        ZendeskSCCAcceptControlConfig,
        ZendeskSCCReleaseControlConfig,
        ZendeskSCCListIntegrationsConfig,
        ZendeskSCCCreateIntegrationConfig,
        ZendeskSCCListWebhooksConfig,
        ZendeskSCCCreateWebhookConfig,
        *_TRIGGER_MODELS.values(),
    ],
    Discriminator("operation"),
]


class ZendeskNodeConfig(NodeConfig[ZendeskConfig, ZendeskCredential]):
    """Full configuration for the Zendesk node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _base_url(subdomain: str) -> str:
    tenant = normalize_provider_subdomain(
        subdomain, "zendesk.com", field_name="Zendesk subdomain"
    )
    return f"https://{tenant}.zendesk.com/api/v2"


def _auth_from_credential(credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build the ``_zendesk_request`` auth kwargs from a decrypted credential
    dict, supporting both OAuth (Bearer access_token) and API token (HTTP Basic
    email + api_token). Returns None when required fields are missing."""
    if not credential:
        return None
    subdomain = credential.get("subdomain")
    if not subdomain:
        return None
    access_token = credential.get("access_token")
    if access_token:
        return {"subdomain": subdomain, "access_token": access_token}
    email = credential.get("email")
    api_token = credential.get("api_token")
    if email and api_token:
        return {"subdomain": subdomain, "email": email, "api_token": api_token}
    return None


def _basic_auth_header(email: str, api_token: str) -> str:
    raw = f"{email}/token:{api_token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _auth_header(
    *,
    email: Optional[str] = None,
    api_token: Optional[str] = None,
    access_token: Optional[str] = None,
) -> str:
    """Build the Authorization header for either auth method: Bearer for OAuth
    access tokens, HTTP Basic (`{email}/token:{api_token}`) for API tokens."""
    if access_token:
        return f"Bearer {access_token}"
    return _basic_auth_header(email, api_token)


async def _zendesk_request(
    *,
    subdomain: str,
    email: Optional[str] = None,
    api_token: Optional[str] = None,
    access_token: Optional[str] = None,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
    base_url: Optional[str] = None,
    auth_header: Optional[str] = None,
    content: Optional[bytes] = None,
    content_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Make an authenticated Zendesk v2 request and return a structured result.

    Auth is either an OAuth Bearer ``access_token`` or HTTP Basic via
    ``email`` + ``api_token``; the *auth* dict the node spreads in carries
    whichever pair matches the credential type. ``base_url`` / ``auth_header``
    override both for the Sunshine Conversations API (different host + app key).
    """
    url = f"{base_url or _base_url(subdomain)}{endpoint}"
    headers = {
        "Authorization": auth_header or _auth_header(
            email=email, api_token=api_token, access_token=access_token
        ),
        "Content-Type": content_type or "application/json",
        "Accept": "application/json",
    }
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=60.0 if content is not None else 30.0) as client:
        try:
            if content is not None:
                response = await client.request(
                    method=method, url=url, headers=headers, params=params, content=content
                )
            else:
                response = await client.request(
                    method=method, url=url, headers=headers, params=params, json=json_body
                )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                message = None
                try:
                    err = response.json()
                    if isinstance(err, dict):
                        message = err.get("error") or err.get("description")
                        # Zendesk validation errors: {"errors": [{"title","detail"}]}
                        errs = err.get("errors")
                        if not message and isinstance(errs, list) and errs and isinstance(errs[0], dict):
                            message = errs[0].get("detail") or errs[0].get("title") or errs[0].get("message")
                        # {"details": {field: [{"description": ...}]}}
                        if not message and isinstance(err.get("details"), dict):
                            message = str(err["details"])
                        if isinstance(message, dict):
                            message = message.get("message") or message.get("title") or str(message)
                        if not message:
                            message = err.get("message") or (str(err) if err else None)
                    else:
                        message = str(err) if err else None
                except Exception:
                    message = response.text or None
                if not message:
                    message = f"HTTP {response.status_code}"
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[ZendeskNode] API error ({action_name}): {message}")
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
            logger.error(f"[ZendeskNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


def _scc_base_url(subdomain: str, app_id: str) -> str:
    tenant = normalize_provider_subdomain(
        subdomain, "zendesk.com", field_name="Zendesk subdomain"
    )
    return f"https://{tenant}.zendesk.com/sc/v2/apps/{app_id}"


async def _scc_request(
    *,
    cred: "ZendeskConversationsCredential",
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Sunshine Conversations request: app-key HTTP Basic auth against the
    /sc/v2/apps/{app_id} base. Reuses ``_zendesk_request``'s HTTP + error
    handling via base_url / auth_header overrides."""
    raw = f"{cred.key_id}:{cred.secret_key}".encode("utf-8")
    auth_header = "Basic " + base64.b64encode(raw).decode("ascii")
    return await _zendesk_request(
        subdomain=cred.subdomain,
        method=method,
        endpoint=endpoint,
        params=params,
        json_body=json_body,
        action_name=action_name,
        base_url=_scc_base_url(cred.subdomain, cred.app_id),
        auth_header=auth_header,
    )


# ============================================================================
# Node Implementation
# ============================================================================


class ZendeskNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Zendesk Support automation node."""

    edit_examples = [
        "Create a Zendesk ticket when a customer submits the contact form",
        "Add an internal note to a ticket when a deal closes",
        "Search for open tickets assigned to a specific agent",
        "Create or update a Zendesk user from a CRM record",
        "Trigger a workflow whenever a new ticket is created",
    ]

    scope_registry = ZENDESK_SCOPES
    # Agents by name, not groups — most Zendesk accounts have the one seeded
    # "Support" group.
    connection_evidence = ConnectionEvidence(
        operation="list_agents",
        noun="agents",
    )

    @classmethod
    def get_config_model(cls):
        return ZendeskNodeConfig

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Inject searchable dropdowns for entity-picker fields at generation
        time, so every operation that references e.g. ``macro_id`` gets a
        populated-from-account dropdown without per-field boilerplate."""
        schema = super().get_config_schema()

        def walk(node):
            if isinstance(node, dict):
                props = node.get("properties")
                if isinstance(props, dict):
                    for fname, fschema in props.items():
                        if (
                            fname in _DYNAMIC_OPTION_SOURCES
                            and isinstance(fschema, dict)
                            and not fschema.get("ui:hidden")
                        ):
                            src = _DYNAMIC_OPTION_SOURCES[fname]
                            if "x-dynamic-options" not in fschema:
                                noun = src["noun"]
                                fschema["x-dynamic-options"] = {
                                    "field_name": fname,
                                    "placeholder": f"Select {'an' if noun[0] in 'aeiou' else 'a'} {noun}…",
                                    "searchable": True,
                                    "allow_custom": True,
                                    "custom_placeholder": f"Or paste {'an' if noun[0] in 'aeiou' else 'a'} {noun} ID",
                                }
                            rtype = src.get("resource_type")
                            if rtype and "x-resource-type" not in fschema:
                                fschema["x-resource-type"] = rtype
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(schema)
        return schema

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring Zendesk OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating API token credentials
        (which carry no refresh_token). Zendesk's token endpoint is
        subdomain-scoped, so the refresher reads the subdomain off the credential."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.zendesk_oauth import refresh_access_token

        subdomain = (credential_data or {}).get("subdomain")

        async def _refresh(refresh_token: str):
            return await refresh_access_token(
                refresh_token=refresh_token, subdomain=subdomain
            )

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=_refresh,
            provider="zendesk",
        )

    async def _ensure_fresh_token(self, credentials: "ZendeskCredential") -> None:
        """Refresh an expired Zendesk OAuth token in place before an API call.
        API token credentials carry no refresh_token and are left untouched."""
        if not isinstance(credentials, ZendeskOAuthCredential):
            return

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.zendesk_oauth import refresh_access_token
        
        subdomain = credentials.subdomain

        async def _refresh(refresh_token: str):
            return await refresh_access_token(
                refresh_token=refresh_token, subdomain=subdomain
            )

        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=_refresh,
            provider="zendesk",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]

    # ------------------------------------------------------------------
    # Dynamic options (agents / groups)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        user_id: str,
        config_data: Dict[str, Any],
        credential_ids: Optional[Dict[str, str]] = None,
        pool=None,
    ) -> Dict[str, Any]:
        source = _DYNAMIC_OPTION_SOURCES.get(field_name)
        if not source:
            return {"options": []}
        from utils.credential_loader import load_credential

        credential_id = next((cid for cid in (credential_ids or {}).values() if cid), None)
        credential = await load_credential(pool, user_id, credential_id) if credential_id else None
        if not credential:
            return {"options": []}
        credential = await cls.freshen_credential(
            credential, pool=pool, user_id=user_id, credential_id=credential_id
        )
        auth = _auth_from_credential(credential)
        if not auth:
            return {"options": []}

        result = await _zendesk_request(
            **auth, method="GET", endpoint=source["endpoint"],
            params=source.get("params"), action_name=f"list_options_{field_name}",
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        items = data.get(source["items_key"], []) if isinstance(data, dict) else []
        options = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if item_id is None:
                continue
            label = next(
                (item[k] for k in _DYNAMIC_OPTION_LABEL_KEYS if item.get(k)),
                str(item_id),
            )
            options.append({"label": str(label), "value": str(item_id)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Webhook trigger registration
    # ------------------------------------------------------------------
    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        auth = _auth_from_credential(credential)
        if not auth:
            raise ValueError("Valid Zendesk credentials (subdomain plus OAuth token or email + API token) are required to register the trigger")
        subscriptions = _TRIGGER_EVENTS.get((config or {}).get("operation")) or list(_ALL_TICKET_EVENTS)
        # Zendesk generates the signing secret itself and REJECTS a client-supplied
        # one (InvalidPermissions on /webhook/signing_secret), so create the webhook
        # first, then read back the auto-generated secret used to sign deliveries.
        result = await _zendesk_request(
            **auth,
            method="POST", endpoint="/webhooks",
            json_body={
                "webhook": {
                    "name": f"NoClick {node_id}"[:255],
                    "endpoint": webhook_url,
                    "http_method": "POST",
                    "request_format": "json",
                    "status": "active",
                    "subscriptions": subscriptions,
                }
            },
            action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"Zendesk webhook registration failed: {result.get('error')}")
        data = result.get("data") or {}
        webhook = data.get("webhook") if isinstance(data, dict) else None
        external_id = webhook.get("id") if isinstance(webhook, dict) else None
        if not external_id:
            raise ValueError("Zendesk webhook registration returned no id")
        # Read back Zendesk's generated signing secret (used to verify delivery
        # signatures). Retry a couple times — a transient failure here would
        # otherwise leave the trigger unable to verify signatures.
        secret = None
        for _attempt in range(3):
            secret_result = await _zendesk_request(
                **auth,
                method="GET", endpoint=f"/webhooks/{external_id}/signing_secret",
                action_name="get_webhook_signing_secret",
            )
            if secret_result.get("status") == "success":
                secret = ((secret_result.get("data") or {}).get("signing_secret") or {}).get("secret")
                if secret:
                    break
        return {
            "external_webhook_id": str(external_id),
            "signing_secret": secret,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        auth = _auth_from_credential(credential or {})
        if not external_id or not auth:
            return
        await _zendesk_request(
            **auth,
            method="DELETE", endpoint=f"/webhooks/{external_id}",
            action_name="unregister_webhook",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored — accept (trigger not yet armed)
        timestamp = headers.get("x-zendesk-webhook-signature-timestamp") or ""
        sent = headers.get("x-zendesk-webhook-signature")
        if not sent:
            return False
        signed = (timestamp.encode() + body) if timestamp else body
        digest = hmac.new(secret.encode(), signed, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode()
        return hmac.compare_digest(expected, sent)

    @classmethod
    def filter_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> bool:
        """Only fire the workflow for the event this decomposed trigger owns.

        Each trigger operation is bound to a fixed event (or, for
        ``on_any_ticket_event``, every ticket event). Zendesk names the event in
        the payload's ``type`` field; a delivery fires only when it matches.
        """
        operation = (config or {}).get("operation")
        inbound = (payload or {}).get("type") or (payload or {}).get("event_type") or ""
        if operation == "on_any_ticket_event":
            return inbound.startswith("zen:event-type:ticket.") if inbound else True
        events = _TRIGGER_EVENTS.get(operation) or []
        if not events:
            return True
        return inbound in events if inbound else True

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, ZendeskNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if op.operation in _TRIGGER_EVENTS:
            return {
                "status": "success",
                "action": op.operation,
                "data": {
                    **inputs,
                    "webhook_url": op.webhook_url,
                    "events": _TRIGGER_EVENTS.get(op.operation),
                },
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Connect a Zendesk account (OAuth) or add your subdomain, email, and API token.")
        # Refresh an expiring OAuth access token in place before building auth.
        await self._ensure_fresh_token(credentials)

        # Sunshine Conversations ops use the app-key credential + a different host.
        if op.operation.startswith("scc_"):
            if not isinstance(credentials, ZendeskConversationsCredential):
                raise ValueError(
                    "Conversations (SCC) operations require a Sunshine Conversations credential (App ID, Key ID, Secret)."
                )
            scc_handler = self._scc_handlers().get(op.operation)
            if not scc_handler:
                raise ValueError(f"Unknown operation: {op.operation}")
            result = await scc_handler(op, credentials)
            result["timing_ms"] = {
                **result.get("timing_ms", {}),
                "total": round((time.time() - start_time) * 1000, 2),
            }
            return result
        if isinstance(credentials, ZendeskConversationsCredential):
            raise ValueError(
                "This operation requires a Zendesk Support credential (OAuth or API token), not a Sunshine Conversations credential."
            )

        if isinstance(credentials, ZendeskOAuthCredential):
            auth = {
                "subdomain": credentials.subdomain,
                "access_token": credentials.access_token,
            }
        else:
            auth = {
                "subdomain": credentials.subdomain,
                "email": credentials.email,
                "api_token": credentials.api_token,
            }

        handlers = {
            "list_tickets": self._list_tickets,
            "show_ticket": self._show_ticket,
            "create_ticket": self._create_ticket,
            "update_ticket": self._update_ticket,
            "delete_ticket": self._delete_ticket,
            "create_many_tickets": self._create_many_tickets,
            "update_many_tickets": self._update_many_tickets,
            "merge_tickets": self._merge_tickets,
            "list_comments": self._list_comments,
            "add_comment": self._add_comment,
            "add_tags": self._add_tags,
            "list_audits": self._list_audits,
            "count_tickets": self._count_tickets,
            "show_many_tickets": self._show_many_tickets,
            "destroy_many_tickets": self._destroy_many_tickets,
            "mark_ticket_as_spam": self._mark_ticket_as_spam,
            "list_organization_tickets": self._list_organization_tickets,
            "list_user_tickets": self._list_user_tickets,
            "list_ticket_tags": self._list_ticket_tags,
            "set_ticket_tags": self._set_ticket_tags,
            "remove_ticket_tags": self._remove_ticket_tags,
            "make_comment_private": self._make_comment_private,
            "create_satisfaction_rating": self._create_satisfaction_rating,
            "list_incremental_tickets": self._list_incremental_tickets,
            "upload_file": self._upload_file,
            "search": self._search,
            "search_users": self._search_users,
            "list_users": self._list_users,
            "show_user": self._show_user,
            "create_user": self._create_user,
            "create_or_update_user": self._create_or_update_user,
            "update_user": self._update_user,
            "delete_user": self._delete_user,
            "list_organizations": self._list_organizations,
            "create_organization": self._create_organization,
            "update_organization": self._update_organization,
            "delete_organization": self._delete_organization,
            "list_groups": self._list_groups,
            "list_ticket_fields": self._list_ticket_fields,
            "list_satisfaction_ratings": self._list_satisfaction_ratings,
            "show_job_status": self._show_job_status,
            "create_webhook": self._create_webhook,
            "show_many_users": self._show_many_users,
            "create_many_users": self._create_many_users,
            "create_or_update_many_users": self._create_or_update_many_users,
            "update_many_users": self._update_many_users,
            "bulk_delete_users": self._bulk_delete_users,
            "permanently_delete_user": self._permanently_delete_user,
            "merge_end_users": self._merge_end_users,
            "autocomplete_users": self._autocomplete_users,
            "count_users": self._count_users,
            "show_user_related": self._show_user_related,
            "show_self": self._show_self,
            "list_users_by_group": self._list_users_by_group,
            "list_users_by_organization": self._list_users_by_organization,
            "list_identities": self._list_identities,
            "show_identity": self._show_identity,
            "create_identity": self._create_identity,
            "update_identity": self._update_identity,
            "delete_identity": self._delete_identity,
            "make_identity_primary": self._make_identity_primary,
            "verify_identity": self._verify_identity,
            "request_identity_verification": self._request_identity_verification,
            "list_user_fields": self._list_user_fields,
            "show_user_field": self._show_user_field,
            "create_user_field": self._create_user_field,
            "update_user_field": self._update_user_field,
            "delete_user_field": self._delete_user_field,
            "list_user_field_options": self._list_user_field_options,
            "create_user_field_option": self._create_user_field_option,
            "update_user_field_option": self._update_user_field_option,
            "delete_user_field_option": self._delete_user_field_option,
            "show_organization": self._show_organization,
            "show_many_organizations": self._show_many_organizations,
            "create_many_organizations": self._create_many_organizations,
            "create_or_update_organization": self._create_or_update_organization,
            "update_many_organizations": self._update_many_organizations,
            "destroy_many_organizations": self._destroy_many_organizations,
            "search_organizations": self._search_organizations,
            "count_organizations": self._count_organizations,
            "related_organizations": self._related_organizations,
            "merge_organization": self._merge_organization,
            "list_organization_fields": self._list_organization_fields,
            "show_organization_field": self._show_organization_field,
            "create_organization_field": self._create_organization_field,
            "update_organization_field": self._update_organization_field,
            "delete_organization_field": self._delete_organization_field,
            "list_organization_memberships": self._list_organization_memberships,
            "list_user_organization_memberships": self._list_user_organization_memberships,
            "show_organization_membership": self._show_organization_membership,
            "create_organization_membership": self._create_organization_membership,
            "create_many_organization_memberships": self._create_many_organization_memberships,
            "delete_organization_membership": self._delete_organization_membership,
            "set_default_organization_membership": self._set_default_organization_membership,
            "list_organization_subscriptions": self._list_organization_subscriptions,
            "show_organization_subscription": self._show_organization_subscription,
            "create_organization_subscription": self._create_organization_subscription,
            "delete_organization_subscription": self._delete_organization_subscription,
            "show_group": self._show_group,
            "create_group": self._create_group,
            "update_group": self._update_group,
            "delete_group": self._delete_group,
            "list_assignable_groups": self._list_assignable_groups,
            "list_group_memberships": self._list_group_memberships,
            "list_user_group_memberships": self._list_user_group_memberships,
            "list_group_memberships_by_group": self._list_group_memberships_by_group,
            "show_group_membership": self._show_group_membership,
            "create_group_membership": self._create_group_membership,
            "create_many_group_memberships": self._create_many_group_memberships,
            "delete_group_membership": self._delete_group_membership,
            "set_default_group_membership": self._set_default_group_membership,
            "list_assignable_group_memberships": self._list_assignable_group_memberships,
            "list_custom_roles": self._list_custom_roles,
            "show_custom_role": self._show_custom_role,
            "create_custom_role": self._create_custom_role,
            "update_custom_role": self._update_custom_role,
            "delete_custom_role": self._delete_custom_role,
            "list_user_sessions": self._list_user_sessions,
            "show_session": self._show_session,
            "delete_session": self._delete_session,
            "show_current_session": self._show_current_session,
            "logout_current_session": self._logout_current_session,
            "show_ticket_field": self._show_ticket_field,
            "create_ticket_field": self._create_ticket_field,
            "update_ticket_field": self._update_ticket_field,
            "delete_ticket_field": self._delete_ticket_field,
            "list_ticket_field_options": self._list_ticket_field_options,
            "show_ticket_field_option": self._show_ticket_field_option,
            "create_ticket_field_option": self._create_ticket_field_option,
            "update_ticket_field_option": self._update_ticket_field_option,
            "delete_ticket_field_option": self._delete_ticket_field_option,
            "list_ticket_forms": self._list_ticket_forms,
            "show_ticket_form": self._show_ticket_form,
            "create_ticket_form": self._create_ticket_form,
            "update_ticket_form": self._update_ticket_form,
            "delete_ticket_form": self._delete_ticket_form,
            "list_custom_statuses": self._list_custom_statuses,
            "show_custom_status": self._show_custom_status,
            "create_custom_status": self._create_custom_status,
            "update_custom_status": self._update_custom_status,
            "list_brands": self._list_brands,
            "show_brand": self._show_brand,
            "create_brand": self._create_brand,
            "update_brand": self._update_brand,
            "delete_brand": self._delete_brand,
            "list_requests": self._list_requests,
            "show_request": self._show_request,
            "create_request": self._create_request,
            "update_request": self._update_request,
            "list_request_comments": self._list_request_comments,
            "list_side_conversations": self._list_side_conversations,
            "show_side_conversation": self._show_side_conversation,
            "create_side_conversation": self._create_side_conversation,
            "reply_side_conversation": self._reply_side_conversation,
            "update_side_conversation": self._update_side_conversation,
            "import_ticket": self._import_ticket,
            "import_many_tickets": self._import_many_tickets,
            "incremental_users": self._incremental_users,
            "incremental_organizations": self._incremental_organizations,
            "incremental_ticket_events": self._incremental_ticket_events,
            "list_macros": self._list_macros,
            "list_active_macros": self._list_active_macros,
            "show_macro": self._show_macro,
            "create_macro": self._create_macro,
            "update_macro": self._update_macro,
            "delete_macro": self._delete_macro,
            "show_macro_changes": self._show_macro_changes,
            "show_ticket_after_macro": self._show_ticket_after_macro,
            "list_views": self._list_views,
            "list_active_views": self._list_active_views,
            "show_view": self._show_view,
            "create_view": self._create_view,
            "update_view": self._update_view,
            "delete_view": self._delete_view,
            "list_view_tickets": self._list_view_tickets,
            "execute_view": self._execute_view,
            "count_view": self._count_view,
            "export_view": self._export_view,
            "list_triggers": self._list_triggers,
            "list_active_triggers": self._list_active_triggers,
            "show_trigger": self._show_trigger,
            "create_trigger": self._create_trigger,
            "update_trigger": self._update_trigger,
            "delete_trigger": self._delete_trigger,
            "list_automations": self._list_automations,
            "list_active_automations": self._list_active_automations,
            "show_automation": self._show_automation,
            "create_automation": self._create_automation,
            "update_automation": self._update_automation,
            "delete_automation": self._delete_automation,
            "list_sla_policies": self._list_sla_policies,
            "show_sla_policy": self._show_sla_policy,
            "create_sla_policy": self._create_sla_policy,
            "update_sla_policy": self._update_sla_policy,
            "delete_sla_policy": self._delete_sla_policy,
            "list_webhooks": self._list_webhooks,
            "show_webhook": self._show_webhook,
            "update_webhook": self._update_webhook,
            "patch_webhook": self._patch_webhook,
            "delete_webhook": self._delete_webhook,
            "clone_webhook": self._clone_webhook,
            "test_webhook": self._test_webhook,
            "list_webhook_invocations": self._list_webhook_invocations,
            "list_webhook_invocation_attempts": self._list_webhook_invocation_attempts,
            "show_webhook_signing_secret": self._show_webhook_signing_secret,
            "reset_webhook_signing_secret": self._reset_webhook_signing_secret,
            "search_count": self._search_count,
            "export_search": self._export_search,
            "autocomplete_tags": self._autocomplete_tags,
            "list_articles": self._list_articles,
            "list_section_articles": self._list_section_articles,
            "list_category_articles": self._list_category_articles,
            "show_article": self._show_article,
            "create_article": self._create_article,
            "update_article": self._update_article,
            "archive_article": self._archive_article,
            "search_articles": self._search_articles,
            "guide_search": self._guide_search,
            "list_article_labels": self._list_article_labels,
            "create_article_label": self._create_article_label,
            "delete_article_label": self._delete_article_label,
            "list_article_attachments": self._list_article_attachments,
            "show_article_attachment": self._show_article_attachment,
            "delete_article_attachment": self._delete_article_attachment,
            "list_sections": self._list_sections,
            "show_section": self._show_section,
            "create_section": self._create_section,
            "update_section": self._update_section,
            "delete_section": self._delete_section,
            "list_categories": self._list_categories,
            "show_category": self._show_category,
            "create_category": self._create_category,
            "update_category": self._update_category,
            "delete_category": self._delete_category,
            "list_article_comments": self._list_article_comments,
            "show_article_comment": self._show_article_comment,
            "create_article_comment": self._create_article_comment,
            "update_article_comment": self._update_article_comment,
            "delete_article_comment": self._delete_article_comment,
            "list_article_subscriptions": self._list_article_subscriptions,
            "create_article_subscription": self._create_article_subscription,
            "delete_article_subscription": self._delete_article_subscription,
            "list_section_subscriptions": self._list_section_subscriptions,
            "create_section_subscription": self._create_section_subscription,
            "delete_section_subscription": self._delete_section_subscription,
            "list_translations": self._list_translations,
            "create_translation": self._create_translation,
            "update_translation": self._update_translation,
            "delete_translation": self._delete_translation,
            "list_custom_objects": self._list_custom_objects,
            "show_custom_object": self._show_custom_object,
            "create_custom_object": self._create_custom_object,
            "update_custom_object": self._update_custom_object,
            "delete_custom_object": self._delete_custom_object,
            "list_custom_object_records": self._list_custom_object_records,
            "show_custom_object_record": self._show_custom_object_record,
            "create_custom_object_record": self._create_custom_object_record,
            "update_custom_object_record": self._update_custom_object_record,
            "delete_custom_object_record": self._delete_custom_object_record,
            "upsert_custom_object_record": self._upsert_custom_object_record,
            "search_custom_object_records": self._search_custom_object_records,
            "count_custom_object_records": self._count_custom_object_records,
            "list_custom_object_fields": self._list_custom_object_fields,
            "show_custom_object_field": self._show_custom_object_field,
            "create_custom_object_field": self._create_custom_object_field,
            "update_custom_object_field": self._update_custom_object_field,
            "delete_custom_object_field": self._delete_custom_object_field,
            "get_user_events": self._get_user_events,
            "track_user_event": self._track_user_event,
            "show_profile": self._show_profile,
            "create_update_profile": self._create_update_profile,
            "delete_profile": self._delete_profile,
            "current_queue_activity": self._current_queue_activity,
            "agents_activity": self._agents_activity,
            "show_availability": self._show_availability,
            "update_availability": self._update_availability,
            "create_voicemail_ticket": self._create_voicemail_ticket,
            "list_chats": self._list_chats,
            "show_chat": self._show_chat,
            "list_agents": self._list_agents,
            "show_agent": self._show_agent,
            "list_departments": self._list_departments,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, auth)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Ticket handlers
    # ------------------------------------------------------------------
    async def _list_tickets(self, c: ZendeskListTicketsConfig, auth) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "sort_by": c.sort_by or None,
            "sort_order": c.sort_order or None,
        }
        if c.page_size:
            params["page[size]"] = c.page_size
        return await _zendesk_request(
            **auth, method="GET", endpoint="/tickets.json", params=params, action_name="list_tickets"
        )

    async def _show_ticket(self, c: ZendeskShowTicketConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/tickets/{c.ticket_id}.json", action_name="show_ticket"
        )

    async def _create_ticket(self, c: ZendeskCreateTicketConfig, auth) -> Dict[str, Any]:
        ticket: Dict[str, Any] = {
            "subject": c.subject,
            "comment": {"body": c.comment_body},
            "priority": c.priority or None,
            "status": c.status or None,
            "type": c.ticket_type or None,
            "assignee_id": int(c.assignee_id) if c.assignee_id and c.assignee_id.isdigit() else None,
            "group_id": int(c.group_id) if c.group_id and c.group_id.isdigit() else None,
            "tags": _comma_list(c.tags),
        }
        if c.requester_email:
            ticket["requester"] = {"email": c.requester_email}
            if c.requester_name:
                ticket["requester"]["name"] = c.requester_name
        uploads = _comma_list(c.attachment_tokens)
        if uploads:
            ticket["comment"]["uploads"] = uploads
        ticket = {k: v for k, v in ticket.items() if v is not None}
        return await _zendesk_request(
            **auth, method="POST", endpoint="/tickets.json",
            json_body={"ticket": ticket}, action_name="create_ticket",
        )

    async def _update_ticket(self, c: ZendeskUpdateTicketConfig, auth) -> Dict[str, Any]:
        ticket: Dict[str, Any] = {
            "status": c.status or None,
            "priority": c.priority or None,
            "assignee_id": int(c.assignee_id) if c.assignee_id and c.assignee_id.isdigit() else None,
            "tags": _comma_list(c.tags),
        }
        if c.comment_body:
            ticket["comment"] = {"body": c.comment_body, "public": c.comment_public == "true"}
        ticket = {k: v for k, v in ticket.items() if v is not None}
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/tickets/{c.ticket_id}.json",
            json_body={"ticket": ticket}, action_name="update_ticket",
        )

    async def _delete_ticket(self, c: ZendeskDeleteTicketConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/tickets/{c.ticket_id}.json",
            action_name="delete_ticket",
        )

    async def _create_many_tickets(self, c: ZendeskCreateManyTicketsConfig, auth) -> Dict[str, Any]:
        try:
            tickets = json.loads(c.tickets_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Tickets JSON is not valid JSON: {e}")
        if not isinstance(tickets, list):
            raise ValueError("Tickets JSON must be a JSON array of ticket objects")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/tickets/create_many.json",
            json_body={"tickets": tickets}, action_name="create_many_tickets",
        )

    async def _update_many_tickets(self, c: ZendeskUpdateManyTicketsConfig, auth) -> Dict[str, Any]:
        try:
            update = json.loads(c.update_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Update JSON is not valid JSON: {e}")
        if not isinstance(update, dict):
            raise ValueError("Update JSON must be a JSON object")
        ids = _comma_list(c.ticket_ids) or []
        return await _zendesk_request(
            **auth, method="PUT", endpoint="/tickets/update_many.json",
            params={"ids": ",".join(ids)},
            json_body={"ticket": update}, action_name="update_many_tickets",
        )

    async def _merge_tickets(self, c: ZendeskMergeTicketsConfig, auth) -> Dict[str, Any]:
        ids = [int(i) for i in (_comma_list(c.source_ticket_ids) or []) if i.isdigit()]
        body: Dict[str, Any] = {"ids": ids}
        if c.target_comment:
            body["target_comment"] = c.target_comment
        if c.source_comment:
            body["source_comment"] = c.source_comment
        return await _zendesk_request(
            **auth, method="POST", endpoint=f"/tickets/{c.ticket_id}/merge.json",
            json_body=body, action_name="merge_tickets",
        )

    async def _list_comments(self, c: ZendeskListCommentsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/tickets/{c.ticket_id}/comments.json",
            action_name="list_comments",
        )

    async def _add_comment(self, c: ZendeskAddCommentConfig, auth) -> Dict[str, Any]:
        comment: Dict[str, Any] = {"body": c.comment_body, "public": c.public == "true"}
        uploads = _comma_list(c.attachment_tokens)
        if uploads:
            comment["uploads"] = uploads
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/tickets/{c.ticket_id}.json",
            json_body={"ticket": {"comment": comment}}, action_name="add_comment",
        )

    async def _upload_file(self, c: ZendeskUploadFileConfig, auth) -> Dict[str, Any]:
        filename = c.filename or (c.file_url.rstrip("/").rsplit("/", 1)[-1] or "upload")
        async with guarded_async_client(timeout=60.0) as client:
            try:
                resp = await client.get(c.file_url, follow_redirects=True)
            except Exception as e:
                return {"status": "error", "action": "upload_file", "error": f"Could not fetch file: {e}", "status_code": 400}
        if resp.status_code >= 400:
            return {"status": "error", "action": "upload_file", "error": f"Could not fetch file ({resp.status_code})", "status_code": resp.status_code}
        return await _zendesk_request(
            **auth, method="POST", endpoint="/uploads.json",
            params={"filename": filename, "token": c.token or None},
            content=resp.content, content_type="application/binary",
            action_name="upload_file",
        )

    async def _add_tags(self, c: ZendeskAddTagsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/tickets/{c.ticket_id}/tags.json",
            json_body={"tags": _comma_list(c.tags) or []}, action_name="add_tags",
        )

    async def _list_audits(self, c: ZendeskListAuditsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/tickets/{c.ticket_id}/audits.json",
            action_name="list_audits",
        )

    async def _count_tickets(self, c: ZendeskCountTicketsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/tickets/count.json", action_name="count_tickets"
        )

    async def _show_many_tickets(self, c: ZendeskShowManyTicketsConfig, auth) -> Dict[str, Any]:
        ids = ",".join(_comma_list(c.ticket_ids) or [])
        return await _zendesk_request(
            **auth, method="GET", endpoint="/tickets/show_many.json",
            params={"ids": ids}, action_name="show_many_tickets",
        )

    async def _destroy_many_tickets(self, c: ZendeskDestroyManyTicketsConfig, auth) -> Dict[str, Any]:
        ids = ",".join(_comma_list(c.ticket_ids) or [])
        return await _zendesk_request(
            **auth, method="DELETE", endpoint="/tickets/destroy_many.json",
            params={"ids": ids}, action_name="destroy_many_tickets",
        )

    async def _mark_ticket_as_spam(self, c: ZendeskMarkTicketAsSpamConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/tickets/{c.ticket_id}/mark_as_spam.json",
            action_name="mark_ticket_as_spam",
        )

    async def _list_organization_tickets(self, c: ZendeskListOrganizationTicketsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/organizations/{c.organization_id}/tickets.json",
            action_name="list_organization_tickets",
        )

    async def _list_user_tickets(self, c: ZendeskListUserTicketsConfig, auth) -> Dict[str, Any]:
        relation = c.relation if c.relation in ("requested", "assigned", "ccd") else "requested"
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/users/{c.user_id}/tickets/{relation}.json",
            action_name="list_user_tickets",
        )

    async def _list_ticket_tags(self, c: ZendeskListTicketTagsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/tickets/{c.ticket_id}/tags.json",
            action_name="list_ticket_tags",
        )

    async def _set_ticket_tags(self, c: ZendeskSetTicketTagsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="POST", endpoint=f"/tickets/{c.ticket_id}/tags.json",
            json_body={"tags": _comma_list(c.tags) or []}, action_name="set_ticket_tags",
        )

    async def _remove_ticket_tags(self, c: ZendeskRemoveTicketTagsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/tickets/{c.ticket_id}/tags.json",
            json_body={"tags": _comma_list(c.tags) or []}, action_name="remove_ticket_tags",
        )

    async def _make_comment_private(self, c: ZendeskMakeCommentPrivateConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="PUT",
            endpoint=f"/tickets/{c.ticket_id}/comments/{c.comment_id}/make_private.json",
            action_name="make_comment_private",
        )

    async def _create_satisfaction_rating(self, c: ZendeskCreateSatisfactionRatingConfig, auth) -> Dict[str, Any]:
        rating: Dict[str, Any] = {"score": c.score}
        if c.comment:
            rating["comment"] = c.comment
        return await _zendesk_request(
            **auth, method="POST",
            endpoint=f"/tickets/{c.ticket_id}/satisfaction_rating.json",
            json_body={"satisfaction_rating": rating},
            action_name="create_satisfaction_rating",
        )

    async def _list_incremental_tickets(self, c: ZendeskListIncrementalTicketsConfig, auth) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if c.cursor:
            params["cursor"] = c.cursor
        elif c.start_time:
            params["start_time"] = c.start_time
        return await _zendesk_request(
            **auth, method="GET", endpoint="/incremental/tickets/cursor.json",
            params=params, action_name="list_incremental_tickets",
        )

    # ------------------------------------------------------------------
    # Search handlers
    # ------------------------------------------------------------------
    async def _search(self, c: ZendeskSearchConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/search.json",
            params={"query": c.query}, action_name="search",
        )

    async def _search_users(self, c: ZendeskSearchUsersConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/users/search.json",
            params={"query": c.query}, action_name="search_users",
        )

    # ------------------------------------------------------------------
    # User handlers
    # ------------------------------------------------------------------
    async def _list_users(self, c: ZendeskListUsersConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/users.json",
            params={"role": c.role or None}, action_name="list_users",
        )

    async def _show_user(self, c: ZendeskShowUserConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/users/{c.user_id}.json", action_name="show_user"
        )

    async def _create_user(self, c: ZendeskCreateUserConfig, auth) -> Dict[str, Any]:
        user = {
            "name": c.name,
            "email": c.email,
            "role": c.role or None,
            "phone": c.phone or None,
        }
        user = {k: v for k, v in user.items() if v is not None}
        return await _zendesk_request(
            **auth, method="POST", endpoint="/users.json",
            json_body={"user": user}, action_name="create_user",
        )

    async def _create_or_update_user(self, c: ZendeskCreateOrUpdateUserConfig, auth) -> Dict[str, Any]:
        user = {"name": c.name, "email": c.email, "role": c.role or None}
        user = {k: v for k, v in user.items() if v is not None}
        return await _zendesk_request(
            **auth, method="POST", endpoint="/users/create_or_update.json",
            json_body={"user": user}, action_name="create_or_update_user",
        )

    async def _update_user(self, c: ZendeskUpdateUserConfig, auth) -> Dict[str, Any]:
        user = {
            "name": c.name or None,
            "email": c.email or None,
            "phone": c.phone or None,
            "notes": c.notes or None,
        }
        user = {k: v for k, v in user.items() if v is not None}
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/users/{c.user_id}.json",
            json_body={"user": user}, action_name="update_user",
        )

    async def _delete_user(self, c: ZendeskDeleteUserConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/users/{c.user_id}.json", action_name="delete_user"
        )

    # ------------------------------------------------------------------
    # Organization handlers
    # ------------------------------------------------------------------
    async def _list_organizations(self, c: ZendeskListOrganizationsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/organizations.json", action_name="list_organizations"
        )

    async def _create_organization(self, c: ZendeskCreateOrganizationConfig, auth) -> Dict[str, Any]:
        org = {
            "name": c.name,
            "domain_names": _comma_list(c.domain_names),
            "notes": c.notes or None,
        }
        org = {k: v for k, v in org.items() if v is not None}
        return await _zendesk_request(
            **auth, method="POST", endpoint="/organizations.json",
            json_body={"organization": org}, action_name="create_organization",
        )

    async def _update_organization(self, c: ZendeskUpdateOrganizationConfig, auth) -> Dict[str, Any]:
        org = {
            "name": c.name or None,
            "domain_names": _comma_list(c.domain_names),
            "notes": c.notes or None,
        }
        org = {k: v for k, v in org.items() if v is not None}
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/organizations/{c.organization_id}.json",
            json_body={"organization": org}, action_name="update_organization",
        )

    async def _delete_organization(self, c: ZendeskDeleteOrganizationConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/organizations/{c.organization_id}.json",
            action_name="delete_organization",
        )

    # ------------------------------------------------------------------
    # Metadata handlers
    # ------------------------------------------------------------------
    async def _list_groups(self, c: ZendeskListGroupsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/groups.json", action_name="list_groups"
        )

    async def _list_ticket_fields(self, c: ZendeskListTicketFieldsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/ticket_fields.json", action_name="list_ticket_fields"
        )

    async def _list_satisfaction_ratings(self, c: ZendeskListSatisfactionRatingsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/satisfaction_ratings.json",
            action_name="list_satisfaction_ratings",
        )

    async def _show_job_status(self, c: ZendeskShowJobStatusConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/job_statuses/{c.job_id}.json",
            action_name="show_job_status",
        )

    async def _create_webhook(self, c: ZendeskCreateWebhookConfig, auth) -> Dict[str, Any]:
        webhook = {
            "name": c.name,
            "endpoint": c.endpoint,
            "http_method": "POST",
            "request_format": "json",
            "status": "active",
            "subscriptions": _comma_list(c.subscriptions) or ["conversation.message.created"],
        }
        return await _zendesk_request(
            **auth, method="POST", endpoint="/webhooks",
            json_body={"webhook": webhook}, action_name="create_webhook",
        )

    # --- users-core ---
    async def _show_many_users(self, c: ZendeskShowManyUsersConfig, auth) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if c.ids:
            params["ids"] = ",".join(_comma_list(c.ids) or [])
        if c.external_ids:
            params["external_ids"] = ",".join(_comma_list(c.external_ids) or [])
        if not params:
            raise ValueError("Provide either User IDs or External IDs")
        return await _zendesk_request(
            **auth, method="GET", endpoint="/users/show_many.json",
            params=params, action_name="show_many_users",
        )

    async def _create_many_users(self, c: ZendeskCreateManyUsersConfig, auth) -> Dict[str, Any]:
        try:
            users = json.loads(c.users_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Users JSON is not valid JSON: {e}")
        if not isinstance(users, list):
            raise ValueError("Users JSON must be a JSON array of user objects")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/users/create_many.json",
            json_body={"users": users}, action_name="create_many_users",
        )

    async def _create_or_update_many_users(self, c: ZendeskCreateOrUpdateManyUsersConfig, auth) -> Dict[str, Any]:
        try:
            users = json.loads(c.users_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Users JSON is not valid JSON: {e}")
        if not isinstance(users, list):
            raise ValueError("Users JSON must be a JSON array of user objects")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/users/create_or_update_many.json",
            json_body={"users": users}, action_name="create_or_update_many_users",
        )

    async def _update_many_users(self, c: ZendeskUpdateManyUsersConfig, auth) -> Dict[str, Any]:
        try:
            payload = json.loads(c.users_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Users JSON is not valid JSON: {e}")
        ids = _comma_list(c.ids) or []
        if ids:
            if not isinstance(payload, dict):
                raise ValueError("When User IDs is set, Users JSON must be a single JSON object")
            return await _zendesk_request(
                **auth, method="PUT", endpoint="/users/update_many.json",
                params={"ids": ",".join(ids)},
                json_body={"user": payload}, action_name="update_many_users",
            )
        if not isinstance(payload, list):
            raise ValueError("When User IDs is empty, Users JSON must be a JSON array of user objects")
        return await _zendesk_request(
            **auth, method="PUT", endpoint="/users/update_many.json",
            json_body={"users": payload}, action_name="update_many_users",
        )

    async def _bulk_delete_users(self, c: ZendeskBulkDeleteUsersConfig, auth) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if c.ids:
            params["ids"] = ",".join(_comma_list(c.ids) or [])
        if c.external_ids:
            params["external_ids"] = ",".join(_comma_list(c.external_ids) or [])
        if not params:
            raise ValueError("Provide either User IDs or External IDs")
        return await _zendesk_request(
            **auth, method="DELETE", endpoint="/users/destroy_many.json",
            params=params, action_name="bulk_delete_users",
        )

    async def _permanently_delete_user(self, c: ZendeskPermanentlyDeleteUserConfig, auth) -> Dict[str, Any]:
        # Permanent deletion happens against the deleted_users collection (the
        # user must already be soft-deleted); /users/{id}/permanently_delete
        # does not exist (404 InvalidEndpoint).
        return await _zendesk_request(
            **auth, method="DELETE",
            endpoint=f"/deleted_users/{c.user_id}.json",
            action_name="permanently_delete_user",
        )

    async def _merge_end_users(self, c: ZendeskMergeEndUsersConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/users/{c.user_id}/merge.json",
            json_body={"user": {"id": c.target_user_id}}, action_name="merge_end_users",
        )

    async def _autocomplete_users(self, c: ZendeskAutocompleteUsersConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/users/autocomplete.json",
            params={"name": c.name}, action_name="autocomplete_users",
        )

    async def _count_users(self, c: ZendeskCountUsersConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/users/count.json",
            params={"role": c.role or None}, action_name="count_users",
        )

    async def _show_user_related(self, c: ZendeskShowUserRelatedConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/users/{c.user_id}/related.json",
            action_name="show_user_related",
        )

    async def _show_self(self, c: ZendeskShowSelfConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/users/me.json", action_name="show_self"
        )

    async def _list_users_by_group(self, c: ZendeskListUsersByGroupConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/groups/{c.group_id}/users.json",
            action_name="list_users_by_group",
        )

    async def _list_users_by_organization(self, c: ZendeskListUsersByOrganizationConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/organizations/{c.organization_id}/users.json",
            action_name="list_users_by_organization",
        )

    # --- user-identities-fields ---
    async def _list_identities(self, c: ZendeskListIdentitiesConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/users/{c.user_id}/identities.json",
            action_name="list_identities",
        )

    async def _show_identity(self, c: ZendeskShowIdentityConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/users/{c.user_id}/identities/{c.identity_id}.json",
            action_name="show_identity",
        )

    async def _create_identity(self, c: ZendeskCreateIdentityConfig, auth) -> Dict[str, Any]:
        identity: Dict[str, Any] = {"type": c.identity_type, "value": c.value}
        if c.verified in ("true", "false"):
            identity["verified"] = c.verified == "true"
        if c.primary in ("true", "false"):
            identity["primary"] = c.primary == "true"
        return await _zendesk_request(
            **auth, method="POST", endpoint=f"/users/{c.user_id}/identities.json",
            json_body={"identity": identity}, action_name="create_identity",
        )

    async def _update_identity(self, c: ZendeskUpdateIdentityConfig, auth) -> Dict[str, Any]:
        identity: Dict[str, Any] = {}
        if c.value:
            identity["value"] = c.value
        if c.verified in ("true", "false"):
            identity["verified"] = c.verified == "true"
        return await _zendesk_request(
            **auth, method="PUT",
            endpoint=f"/users/{c.user_id}/identities/{c.identity_id}.json",
            json_body={"identity": identity}, action_name="update_identity",
        )

    async def _delete_identity(self, c: ZendeskDeleteIdentityConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE",
            endpoint=f"/users/{c.user_id}/identities/{c.identity_id}.json",
            action_name="delete_identity",
        )

    async def _make_identity_primary(self, c: ZendeskMakeIdentityPrimaryConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="PUT",
            endpoint=f"/users/{c.user_id}/identities/{c.identity_id}/make_primary.json",
            action_name="make_identity_primary",
        )

    async def _verify_identity(self, c: ZendeskVerifyIdentityConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="PUT",
            endpoint=f"/users/{c.user_id}/identities/{c.identity_id}/verify.json",
            action_name="verify_identity",
        )

    async def _request_identity_verification(self, c: ZendeskRequestIdentityVerificationConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="PUT",
            endpoint=f"/users/{c.user_id}/identities/{c.identity_id}/request_verification.json",
            action_name="request_identity_verification",
        )

    async def _list_user_fields(self, c: ZendeskListUserFieldsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/user_fields.json",
            action_name="list_user_fields",
        )

    async def _show_user_field(self, c: ZendeskShowUserFieldConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/user_fields/{c.user_field_id}.json",
            action_name="show_user_field",
        )

    async def _create_user_field(self, c: ZendeskCreateUserFieldConfig, auth) -> Dict[str, Any]:
        user_field: Dict[str, Any] = {"type": c.field_type, "title": c.title, "key": c.key}
        if c.description:
            user_field["description"] = c.description
        if c.custom_field_options_json:
            try:
                options = json.loads(c.custom_field_options_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"Options JSON is not valid JSON: {e}")
            if not isinstance(options, list):
                raise ValueError("Options JSON must be a JSON array of {name, value} objects")
            user_field["custom_field_options"] = options
        return await _zendesk_request(
            **auth, method="POST", endpoint="/user_fields.json",
            json_body={"user_field": user_field}, action_name="create_user_field",
        )

    async def _update_user_field(self, c: ZendeskUpdateUserFieldConfig, auth) -> Dict[str, Any]:
        user_field: Dict[str, Any] = {}
        if c.title:
            user_field["title"] = c.title
        if c.description:
            user_field["description"] = c.description
        if c.active in ("true", "false"):
            user_field["active"] = c.active == "true"
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/user_fields/{c.user_field_id}.json",
            json_body={"user_field": user_field}, action_name="update_user_field",
        )

    async def _delete_user_field(self, c: ZendeskDeleteUserFieldConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/user_fields/{c.user_field_id}.json",
            action_name="delete_user_field",
        )

    async def _list_user_field_options(self, c: ZendeskListUserFieldOptionsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/user_fields/{c.user_field_id}/options.json",
            action_name="list_user_field_options",
        )

    async def _create_user_field_option(self, c: ZendeskCreateUserFieldOptionConfig, auth) -> Dict[str, Any]:
        option = {"name": c.name, "value": c.value}
        return await _zendesk_request(
            **auth, method="POST",
            endpoint=f"/user_fields/{c.user_field_id}/options.json",
            json_body={"custom_field_option": option},
            action_name="create_user_field_option",
        )

    async def _update_user_field_option(self, c: ZendeskUpdateUserFieldOptionConfig, auth) -> Dict[str, Any]:
        option = {"id": int(c.option_id) if c.option_id.isdigit() else c.option_id,
                  "name": c.name, "value": c.value}
        return await _zendesk_request(
            **auth, method="POST",
            endpoint=f"/user_fields/{c.user_field_id}/options.json",
            json_body={"custom_field_option": option},
            action_name="update_user_field_option",
        )

    async def _delete_user_field_option(self, c: ZendeskDeleteUserFieldOptionConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE",
            endpoint=f"/user_fields/{c.user_field_id}/options/{c.option_id}.json",
            action_name="delete_user_field_option",
        )

    # --- orgs-extended ---
    async def _show_organization(self, c: ZendeskShowOrganizationConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/organizations/{c.organization_id}.json",
            action_name="show_organization",
        )

    async def _show_many_organizations(self, c: ZendeskShowManyOrganizationsConfig, auth) -> Dict[str, Any]:
        ids = _comma_list(c.organization_ids)
        external_ids = _comma_list(c.external_ids)
        if not ids and not external_ids:
            raise ValueError("Provide organization_ids or external_ids")
        params: Dict[str, Any] = {}
        if ids:
            params["ids"] = ",".join(ids)
        else:
            params["external_ids"] = ",".join(external_ids)
        return await _zendesk_request(
            **auth, method="GET", endpoint="/organizations/show_many.json",
            params=params, action_name="show_many_organizations",
        )

    async def _create_many_organizations(self, c: ZendeskCreateManyOrganizationsConfig, auth) -> Dict[str, Any]:
        try:
            orgs = json.loads(c.organizations_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Organizations JSON is not valid JSON: {e}")
        if not isinstance(orgs, list):
            raise ValueError("Organizations JSON must be a JSON array of organization objects")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/organizations/create_many.json",
            json_body={"organizations": orgs}, action_name="create_many_organizations",
        )

    async def _create_or_update_organization(self, c: ZendeskCreateOrUpdateOrganizationConfig, auth) -> Dict[str, Any]:
        org = {
            "name": c.name,
            "external_id": c.external_id or None,
            "domain_names": _comma_list(c.domain_names),
            "notes": c.notes or None,
        }
        org = {k: v for k, v in org.items() if v is not None}
        return await _zendesk_request(
            **auth, method="POST", endpoint="/organizations/create_or_update.json",
            json_body={"organization": org}, action_name="create_or_update_organization",
        )

    async def _update_many_organizations(self, c: ZendeskUpdateManyOrganizationsConfig, auth) -> Dict[str, Any]:
        try:
            update = json.loads(c.update_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Update JSON is not valid JSON: {e}")
        if not isinstance(update, dict):
            raise ValueError("Update JSON must be a JSON object")
        ids = _comma_list(c.organization_ids)
        external_ids = _comma_list(c.external_ids)
        if not ids and not external_ids:
            raise ValueError("Provide organization_ids or external_ids")
        params: Dict[str, Any] = {}
        if ids:
            params["ids"] = ",".join(ids)
        else:
            params["external_ids"] = ",".join(external_ids)
        return await _zendesk_request(
            **auth, method="PUT", endpoint="/organizations/update_many.json",
            params=params, json_body={"organization": update},
            action_name="update_many_organizations",
        )

    async def _destroy_many_organizations(self, c: ZendeskDestroyManyOrganizationsConfig, auth) -> Dict[str, Any]:
        ids = ",".join(_comma_list(c.organization_ids) or [])
        return await _zendesk_request(
            **auth, method="DELETE", endpoint="/organizations/destroy_many.json",
            params={"ids": ids}, action_name="destroy_many_organizations",
        )

    async def _search_organizations(self, c: ZendeskSearchOrganizationsConfig, auth) -> Dict[str, Any]:
        if c.external_id:
            return await _zendesk_request(
                **auth, method="GET", endpoint="/organizations/search.json",
                params={"external_id": c.external_id}, action_name="search_organizations",
            )
        if c.name:
            return await _zendesk_request(
                **auth, method="GET", endpoint="/organizations/autocomplete.json",
                params={"name": c.name}, action_name="search_organizations",
            )
        raise ValueError("Provide external_id or name to search organizations")

    async def _count_organizations(self, c: ZendeskCountOrganizationsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/organizations/count.json",
            action_name="count_organizations",
        )

    async def _related_organizations(self, c: ZendeskRelatedOrganizationsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/organizations/{c.organization_id}/related.json",
            action_name="related_organizations",
        )

    async def _merge_organization(self, c: ZendeskMergeOrganizationConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="POST", endpoint=f"/organizations/{c.organization_id}/merge.json",
            json_body={"organization": {"id": int(c.target_organization_id)}},
            action_name="merge_organization",
        )

    # --- org-fields-memberships ---
    async def _list_organization_fields(self, c: ZendeskListOrganizationFieldsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/organization_fields.json",
            action_name="list_organization_fields",
        )

    async def _show_organization_field(self, c: ZendeskShowOrganizationFieldConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/organization_fields/{c.field_id}.json",
            action_name="show_organization_field",
        )

    async def _create_organization_field(self, c: ZendeskCreateOrganizationFieldConfig, auth) -> Dict[str, Any]:
        field: Dict[str, Any] = {
            "type": c.field_type,
            "title": c.title,
            "key": c.key,
            "description": c.description or None,
            "regexp_for_validation": c.regexp_for_validation or None,
        }
        if c.active in ("true", "false"):
            field["active"] = c.active == "true"
        if c.custom_field_options:
            try:
                options = json.loads(c.custom_field_options)
            except json.JSONDecodeError as e:
                raise ValueError(f"Custom Field Options is not valid JSON: {e}")
            if not isinstance(options, list):
                raise ValueError("Custom Field Options must be a JSON array of option objects")
            field["custom_field_options"] = options
        field = {k: v for k, v in field.items() if v is not None}
        return await _zendesk_request(
            **auth, method="POST", endpoint="/organization_fields.json",
            json_body={"organization_field": field}, action_name="create_organization_field",
        )

    async def _update_organization_field(self, c: ZendeskUpdateOrganizationFieldConfig, auth) -> Dict[str, Any]:
        field: Dict[str, Any] = {
            "title": c.title or None,
            "description": c.description or None,
            "regexp_for_validation": c.regexp_for_validation or None,
        }
        if c.active in ("true", "false"):
            field["active"] = c.active == "true"
        if c.custom_field_options:
            try:
                options = json.loads(c.custom_field_options)
            except json.JSONDecodeError as e:
                raise ValueError(f"Custom Field Options is not valid JSON: {e}")
            if not isinstance(options, list):
                raise ValueError("Custom Field Options must be a JSON array of option objects")
            field["custom_field_options"] = options
        field = {k: v for k, v in field.items() if v is not None}
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/organization_fields/{c.field_id}.json",
            json_body={"organization_field": field}, action_name="update_organization_field",
        )

    async def _delete_organization_field(self, c: ZendeskDeleteOrganizationFieldConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/organization_fields/{c.field_id}.json",
            action_name="delete_organization_field",
        )

    async def _list_organization_memberships(self, c: ZendeskListOrganizationMembershipsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/organization_memberships.json",
            action_name="list_organization_memberships",
        )

    async def _list_user_organization_memberships(self, c: ZendeskListUserOrganizationMembershipsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/users/{c.user_id}/organization_memberships.json",
            action_name="list_user_organization_memberships",
        )

    async def _show_organization_membership(self, c: ZendeskShowOrganizationMembershipConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/organization_memberships/{c.membership_id}.json",
            action_name="show_organization_membership",
        )

    async def _create_organization_membership(self, c: ZendeskCreateOrganizationMembershipConfig, auth) -> Dict[str, Any]:
        membership: Dict[str, Any] = {
            "user_id": c.user_id,
            "organization_id": c.organization_id,
        }
        if c.default in ("true", "false"):
            membership["default"] = c.default == "true"
        return await _zendesk_request(
            **auth, method="POST", endpoint="/organization_memberships.json",
            json_body={"organization_membership": membership},
            action_name="create_organization_membership",
        )

    async def _create_many_organization_memberships(self, c: ZendeskCreateManyOrganizationMembershipsConfig, auth) -> Dict[str, Any]:
        try:
            memberships = json.loads(c.memberships_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Memberships JSON is not valid JSON: {e}")
        if not isinstance(memberships, list):
            raise ValueError("Memberships JSON must be a JSON array of membership objects")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/organization_memberships/create_many.json",
            json_body={"organization_memberships": memberships},
            action_name="create_many_organization_memberships",
        )

    async def _delete_organization_membership(self, c: ZendeskDeleteOrganizationMembershipConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/organization_memberships/{c.membership_id}.json",
            action_name="delete_organization_membership",
        )

    async def _set_default_organization_membership(self, c: ZendeskSetDefaultOrganizationMembershipConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="PUT",
            endpoint=f"/users/{c.user_id}/organization_memberships/{c.membership_id}/make_default.json",
            action_name="set_default_organization_membership",
        )

    async def _list_organization_subscriptions(self, c: ZendeskListOrganizationSubscriptionsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/organization_subscriptions.json",
            action_name="list_organization_subscriptions",
        )

    async def _show_organization_subscription(self, c: ZendeskShowOrganizationSubscriptionConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/organization_subscriptions/{c.subscription_id}.json",
            action_name="show_organization_subscription",
        )

    async def _create_organization_subscription(self, c: ZendeskCreateOrganizationSubscriptionConfig, auth) -> Dict[str, Any]:
        subscription = {
            "user_id": c.user_id,
            "organization_id": c.organization_id,
        }
        return await _zendesk_request(
            **auth, method="POST", endpoint="/organization_subscriptions.json",
            json_body={"organization_subscription": subscription},
            action_name="create_organization_subscription",
        )

    async def _delete_organization_subscription(self, c: ZendeskDeleteOrganizationSubscriptionConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/organization_subscriptions/{c.subscription_id}.json",
            action_name="delete_organization_subscription",
        )

    # --- groups-roles ---
    async def _show_group(self, c: ZendeskShowGroupConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/groups/{c.group_id}.json",
            action_name="show_group",
        )

    async def _create_group(self, c: ZendeskCreateGroupConfig, auth) -> Dict[str, Any]:
        group: Dict[str, Any] = {
            "name": c.name,
            "description": c.description or None,
        }
        if c.is_public is not None:
            group["is_public"] = c.is_public == "true"
        group = {k: v for k, v in group.items() if v is not None}
        return await _zendesk_request(
            **auth, method="POST", endpoint="/groups.json",
            json_body={"group": group}, action_name="create_group",
        )

    async def _update_group(self, c: ZendeskUpdateGroupConfig, auth) -> Dict[str, Any]:
        group: Dict[str, Any] = {
            "name": c.name or None,
            "description": c.description or None,
        }
        if c.is_public is not None:
            group["is_public"] = c.is_public == "true"
        group = {k: v for k, v in group.items() if v is not None}
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/groups/{c.group_id}.json",
            json_body={"group": group}, action_name="update_group",
        )

    async def _delete_group(self, c: ZendeskDeleteGroupConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/groups/{c.group_id}.json",
            action_name="delete_group",
        )

    async def _list_assignable_groups(self, c: ZendeskListAssignableGroupsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/groups/assignable.json",
            action_name="list_assignable_groups",
        )

    async def _list_group_memberships(self, c: ZendeskListGroupMembershipsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/group_memberships.json",
            action_name="list_group_memberships",
        )

    async def _list_user_group_memberships(self, c: ZendeskListUserGroupMembershipsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/users/{c.user_id}/group_memberships.json",
            action_name="list_user_group_memberships",
        )

    async def _list_group_memberships_by_group(self, c: ZendeskListGroupMembershipsByGroupConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/groups/{c.group_id}/memberships.json",
            action_name="list_group_memberships_by_group",
        )

    async def _show_group_membership(self, c: ZendeskShowGroupMembershipConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/group_memberships/{c.group_membership_id}.json",
            action_name="show_group_membership",
        )

    async def _create_group_membership(self, c: ZendeskCreateGroupMembershipConfig, auth) -> Dict[str, Any]:
        membership: Dict[str, Any] = {
            "user_id": int(c.user_id) if c.user_id.isdigit() else c.user_id,
            "group_id": int(c.group_id) if c.group_id.isdigit() else c.group_id,
        }
        if c.default is not None:
            membership["default"] = c.default == "true"
        return await _zendesk_request(
            **auth, method="POST", endpoint="/group_memberships.json",
            json_body={"group_membership": membership}, action_name="create_group_membership",
        )

    async def _create_many_group_memberships(self, c: ZendeskCreateManyGroupMembershipsConfig, auth) -> Dict[str, Any]:
        try:
            memberships = json.loads(c.memberships_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Memberships JSON is not valid JSON: {e}")
        if not isinstance(memberships, list):
            raise ValueError("Memberships JSON must be a JSON array of membership objects")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/group_memberships/create_many.json",
            json_body={"group_memberships": memberships}, action_name="create_many_group_memberships",
        )

    async def _delete_group_membership(self, c: ZendeskDeleteGroupMembershipConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/group_memberships/{c.group_membership_id}.json",
            action_name="delete_group_membership",
        )

    async def _set_default_group_membership(self, c: ZendeskSetDefaultGroupMembershipConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="PUT",
            endpoint=f"/users/{c.user_id}/group_memberships/{c.group_membership_id}/make_default.json",
            action_name="set_default_group_membership",
        )

    async def _list_assignable_group_memberships(self, c: ZendeskListAssignableGroupMembershipsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/group_memberships/assignable.json",
            action_name="list_assignable_group_memberships",
        )

    async def _list_custom_roles(self, c: ZendeskListCustomRolesConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/custom_roles.json",
            action_name="list_custom_roles",
        )

    async def _show_custom_role(self, c: ZendeskShowCustomRoleConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/custom_roles/{c.custom_role_id}.json",
            action_name="show_custom_role",
        )

    async def _create_custom_role(self, c: ZendeskCreateCustomRoleConfig, auth) -> Dict[str, Any]:
        role: Dict[str, Any] = {
            "name": c.name,
            "description": c.description or None,
        }
        if c.configuration_json:
            try:
                configuration = json.loads(c.configuration_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"Configuration JSON is not valid JSON: {e}")
            if not isinstance(configuration, dict):
                raise ValueError("Configuration JSON must be a JSON object")
            role["configuration"] = configuration
        role = {k: v for k, v in role.items() if v is not None}
        return await _zendesk_request(
            **auth, method="POST", endpoint="/custom_roles.json",
            json_body={"custom_role": role}, action_name="create_custom_role",
        )

    async def _update_custom_role(self, c: ZendeskUpdateCustomRoleConfig, auth) -> Dict[str, Any]:
        role: Dict[str, Any] = {
            "name": c.name or None,
            "description": c.description or None,
        }
        if c.configuration_json:
            try:
                configuration = json.loads(c.configuration_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"Configuration JSON is not valid JSON: {e}")
            if not isinstance(configuration, dict):
                raise ValueError("Configuration JSON must be a JSON object")
            role["configuration"] = configuration
        role = {k: v for k, v in role.items() if v is not None}
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/custom_roles/{c.custom_role_id}.json",
            json_body={"custom_role": role}, action_name="update_custom_role",
        )

    async def _delete_custom_role(self, c: ZendeskDeleteCustomRoleConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/custom_roles/{c.custom_role_id}.json",
            action_name="delete_custom_role",
        )

    async def _list_user_sessions(self, c: ZendeskListUserSessionsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/users/{c.user_id}/sessions.json",
            action_name="list_user_sessions",
        )

    async def _show_session(self, c: ZendeskShowSessionConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/users/{c.user_id}/sessions/{c.session_id}.json",
            action_name="show_session",
        )

    async def _delete_session(self, c: ZendeskDeleteSessionConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/users/{c.user_id}/sessions/{c.session_id}.json",
            action_name="delete_session",
        )

    async def _show_current_session(self, c: ZendeskShowCurrentSessionConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/users/me/session.json",
            action_name="show_current_session",
        )

    async def _logout_current_session(self, c: ZendeskLogoutCurrentSessionConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint="/users/me/logout.json",
            action_name="logout_current_session",
        )

    # --- fields-forms-statuses ---
    async def _show_ticket_field(self, c: ZendeskShowTicketFieldConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/ticket_fields/{c.ticket_field_id}.json",
            action_name="show_ticket_field",
        )

    async def _create_ticket_field(self, c: ZendeskCreateTicketFieldConfig, auth) -> Dict[str, Any]:
        try:
            field = json.loads(c.ticket_field_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Ticket Field JSON is not valid JSON: {e}")
        if not isinstance(field, dict):
            raise ValueError("Ticket Field JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/ticket_fields.json",
            json_body={"ticket_field": field}, action_name="create_ticket_field",
        )

    async def _update_ticket_field(self, c: ZendeskUpdateTicketFieldConfig, auth) -> Dict[str, Any]:
        try:
            field = json.loads(c.ticket_field_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Ticket Field JSON is not valid JSON: {e}")
        if not isinstance(field, dict):
            raise ValueError("Ticket Field JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/ticket_fields/{c.ticket_field_id}.json",
            json_body={"ticket_field": field}, action_name="update_ticket_field",
        )

    async def _delete_ticket_field(self, c: ZendeskDeleteTicketFieldConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/ticket_fields/{c.ticket_field_id}.json",
            action_name="delete_ticket_field",
        )

    async def _list_ticket_field_options(self, c: ZendeskListTicketFieldOptionsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/ticket_fields/{c.ticket_field_id}/options.json",
            action_name="list_ticket_field_options",
        )

    async def _show_ticket_field_option(self, c: ZendeskShowTicketFieldOptionConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/ticket_fields/{c.ticket_field_id}/options/{c.option_id}.json",
            action_name="show_ticket_field_option",
        )

    async def _create_ticket_field_option(self, c: ZendeskCreateTicketFieldOptionConfig, auth) -> Dict[str, Any]:
        try:
            option = json.loads(c.option_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Option JSON is not valid JSON: {e}")
        if not isinstance(option, dict):
            raise ValueError("Option JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="POST", endpoint=f"/ticket_fields/{c.ticket_field_id}/options.json",
            json_body={"custom_field_option": option}, action_name="create_ticket_field_option",
        )

    async def _update_ticket_field_option(self, c: ZendeskUpdateTicketFieldOptionConfig, auth) -> Dict[str, Any]:
        try:
            option = json.loads(c.option_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Option JSON is not valid JSON: {e}")
        if not isinstance(option, dict):
            raise ValueError("Option JSON must be a JSON object")
        if c.option_id and c.option_id.isdigit():
            option["id"] = int(c.option_id)
        return await _zendesk_request(
            **auth, method="POST", endpoint=f"/ticket_fields/{c.ticket_field_id}/options.json",
            json_body={"custom_field_option": option}, action_name="update_ticket_field_option",
        )

    async def _delete_ticket_field_option(self, c: ZendeskDeleteTicketFieldOptionConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE",
            endpoint=f"/ticket_fields/{c.ticket_field_id}/options/{c.option_id}.json",
            action_name="delete_ticket_field_option",
        )

    async def _list_ticket_forms(self, c: ZendeskListTicketFormsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/ticket_forms.json",
            action_name="list_ticket_forms",
        )

    async def _show_ticket_form(self, c: ZendeskShowTicketFormConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/ticket_forms/{c.ticket_form_id}.json",
            action_name="show_ticket_form",
        )

    async def _create_ticket_form(self, c: ZendeskCreateTicketFormConfig, auth) -> Dict[str, Any]:
        try:
            form = json.loads(c.ticket_form_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Ticket Form JSON is not valid JSON: {e}")
        if not isinstance(form, dict):
            raise ValueError("Ticket Form JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/ticket_forms.json",
            json_body={"ticket_form": form}, action_name="create_ticket_form",
        )

    async def _update_ticket_form(self, c: ZendeskUpdateTicketFormConfig, auth) -> Dict[str, Any]:
        try:
            form = json.loads(c.ticket_form_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Ticket Form JSON is not valid JSON: {e}")
        if not isinstance(form, dict):
            raise ValueError("Ticket Form JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/ticket_forms/{c.ticket_form_id}.json",
            json_body={"ticket_form": form}, action_name="update_ticket_form",
        )

    async def _delete_ticket_form(self, c: ZendeskDeleteTicketFormConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/ticket_forms/{c.ticket_form_id}.json",
            action_name="delete_ticket_form",
        )

    async def _list_custom_statuses(self, c: ZendeskListCustomStatusesConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/custom_statuses.json",
            action_name="list_custom_statuses",
        )

    async def _show_custom_status(self, c: ZendeskShowCustomStatusConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/custom_statuses/{c.custom_status_id}.json",
            action_name="show_custom_status",
        )

    async def _create_custom_status(self, c: ZendeskCreateCustomStatusConfig, auth) -> Dict[str, Any]:
        try:
            status = json.loads(c.custom_status_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Custom Status JSON is not valid JSON: {e}")
        if not isinstance(status, dict):
            raise ValueError("Custom Status JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/custom_statuses.json",
            json_body={"custom_status": status}, action_name="create_custom_status",
        )

    async def _update_custom_status(self, c: ZendeskUpdateCustomStatusConfig, auth) -> Dict[str, Any]:
        try:
            status = json.loads(c.custom_status_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Custom Status JSON is not valid JSON: {e}")
        if not isinstance(status, dict):
            raise ValueError("Custom Status JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/custom_statuses/{c.custom_status_id}.json",
            json_body={"custom_status": status}, action_name="update_custom_status",
        )

    async def _list_brands(self, c: ZendeskListBrandsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/brands.json", action_name="list_brands",
        )

    async def _show_brand(self, c: ZendeskShowBrandConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/brands/{c.brand_id}.json", action_name="show_brand",
        )

    async def _create_brand(self, c: ZendeskCreateBrandConfig, auth) -> Dict[str, Any]:
        try:
            brand = json.loads(c.brand_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Brand JSON is not valid JSON: {e}")
        if not isinstance(brand, dict):
            raise ValueError("Brand JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/brands.json",
            json_body={"brand": brand}, action_name="create_brand",
        )

    async def _update_brand(self, c: ZendeskUpdateBrandConfig, auth) -> Dict[str, Any]:
        try:
            brand = json.loads(c.brand_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Brand JSON is not valid JSON: {e}")
        if not isinstance(brand, dict):
            raise ValueError("Brand JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/brands/{c.brand_id}.json",
            json_body={"brand": brand}, action_name="update_brand",
        )

    async def _delete_brand(self, c: ZendeskDeleteBrandConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/brands/{c.brand_id}.json",
            action_name="delete_brand",
        )

    # --- requests-sideconv-import ---
    async def _list_requests(self, c: ZendeskListRequestsConfig, auth) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if c.status:
            params["status"] = c.status
        if c.page_size:
            params["per_page"] = c.page_size
        return await _zendesk_request(
            **auth, method="GET", endpoint="/requests.json",
            params=params or None, action_name="list_requests",
        )

    async def _show_request(self, c: ZendeskShowRequestConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/requests/{c.request_id}.json",
            action_name="show_request",
        )

    async def _create_request(self, c: ZendeskCreateRequestConfig, auth) -> Dict[str, Any]:
        request: Dict[str, Any] = {
            "subject": c.subject,
            "comment": {"body": c.comment_body},
            "priority": c.priority or None,
            "type": c.request_type or None,
        }
        if c.requester_email:
            requester: Dict[str, Any] = {"email": c.requester_email}
            if c.requester_name:
                requester["name"] = c.requester_name
            request["requester"] = requester
        request = {k: v for k, v in request.items() if v is not None}
        return await _zendesk_request(
            **auth, method="POST", endpoint="/requests.json",
            json_body={"request": request}, action_name="create_request",
        )

    async def _update_request(self, c: ZendeskUpdateRequestConfig, auth) -> Dict[str, Any]:
        request: Dict[str, Any] = {}
        if c.comment_body:
            request["comment"] = {"body": c.comment_body}
        if c.solved == "true":
            request["solved"] = True
        collaborators = _comma_list(c.additional_collaborators)
        if collaborators:
            request["additional_collaborators"] = collaborators
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/requests/{c.request_id}.json",
            json_body={"request": request}, action_name="update_request",
        )

    async def _list_request_comments(self, c: ZendeskListRequestCommentsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/requests/{c.request_id}/comments.json",
            action_name="list_request_comments",
        )

    async def _list_side_conversations(self, c: ZendeskListSideConversationsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/tickets/{c.ticket_id}/side_conversations.json",
            action_name="list_side_conversations",
        )

    async def _show_side_conversation(self, c: ZendeskShowSideConversationConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/tickets/{c.ticket_id}/side_conversations/{c.side_conversation_id}.json",
            action_name="show_side_conversation",
        )

    async def _create_side_conversation(self, c: ZendeskCreateSideConversationConfig, auth) -> Dict[str, Any]:
        message: Dict[str, Any] = {"body": c.body}
        if c.subject:
            message["subject"] = c.subject
        recipients = [{"email": e} for e in (_comma_list(c.to_emails) or [])]
        if recipients:
            message["to"] = recipients
        return await _zendesk_request(
            **auth, method="POST",
            endpoint=f"/tickets/{c.ticket_id}/side_conversations.json",
            json_body={"message": message}, action_name="create_side_conversation",
        )

    async def _reply_side_conversation(self, c: ZendeskReplySideConversationConfig, auth) -> Dict[str, Any]:
        message: Dict[str, Any] = {"body": c.body}
        recipients = [{"email": e} for e in (_comma_list(c.to_emails) or [])]
        if recipients:
            message["to"] = recipients
        return await _zendesk_request(
            **auth, method="POST",
            endpoint=f"/tickets/{c.ticket_id}/side_conversations/{c.side_conversation_id}/reply.json",
            json_body={"message": message}, action_name="reply_side_conversation",
        )

    async def _update_side_conversation(self, c: ZendeskUpdateSideConversationConfig, auth) -> Dict[str, Any]:
        side_conversation: Dict[str, Any] = {}
        if c.state:
            side_conversation["state"] = c.state
        if c.subject:
            side_conversation["subject"] = c.subject
        return await _zendesk_request(
            **auth, method="PUT",
            endpoint=f"/tickets/{c.ticket_id}/side_conversations/{c.side_conversation_id}.json",
            json_body={"side_conversation": side_conversation},
            action_name="update_side_conversation",
        )

    async def _import_ticket(self, c: ZendeskImportTicketConfig, auth) -> Dict[str, Any]:
        ticket: Dict[str, Any] = {
            "subject": c.subject,
            "comment": {"body": c.comment_body},
            "status": c.status or None,
            "created_at": c.created_at or None,
            "solved_at": c.solved_at or None,
        }
        if c.requester_email:
            ticket["requester"] = {"email": c.requester_email}
        ticket = {k: v for k, v in ticket.items() if v is not None}
        if c.extra_json:
            try:
                extra = json.loads(c.extra_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"Extra Fields JSON is not valid JSON: {e}")
            if not isinstance(extra, dict):
                raise ValueError("Extra Fields JSON must be a JSON object")
            ticket.update(extra)
        return await _zendesk_request(
            **auth, method="POST", endpoint="/imports/tickets.json",
            json_body={"ticket": ticket}, action_name="import_ticket",
        )

    async def _import_many_tickets(self, c: ZendeskImportManyTicketsConfig, auth) -> Dict[str, Any]:
        try:
            tickets = json.loads(c.tickets_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Tickets JSON is not valid JSON: {e}")
        if not isinstance(tickets, list):
            raise ValueError("Tickets JSON must be a JSON array of ticket objects")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/imports/tickets/create_many.json",
            json_body={"tickets": tickets}, action_name="import_many_tickets",
        )

    async def _incremental_users(self, c: ZendeskIncrementalUsersConfig, auth) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if c.cursor:
            params["cursor"] = c.cursor
        else:
            params["start_time"] = c.start_time
        return await _zendesk_request(
            **auth, method="GET", endpoint="/incremental/users/cursor.json",
            params=params, action_name="incremental_users",
        )

    async def _incremental_organizations(self, c: ZendeskIncrementalOrganizationsConfig, auth) -> Dict[str, Any]:
        params: Dict[str, Any] = {"start_time": c.start_time}
        if c.cursor:
            params["cursor"] = c.cursor
        return await _zendesk_request(
            **auth, method="GET", endpoint="/incremental/organizations.json",
            params=params, action_name="incremental_organizations",
        )

    async def _incremental_ticket_events(self, c: ZendeskIncrementalTicketEventsConfig, auth) -> Dict[str, Any]:
        params: Dict[str, Any] = {"start_time": c.start_time}
        if c.cursor:
            params["cursor"] = c.cursor
        return await _zendesk_request(
            **auth, method="GET", endpoint="/incremental/ticket_events.json",
            params=params, action_name="incremental_ticket_events",
        )

    # --- macros-views ---
    async def _list_macros(self, c: ZendeskListMacrosConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/macros.json", action_name="list_macros",
        )

    async def _list_active_macros(self, c: ZendeskListActiveMacrosConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/macros/active.json", action_name="list_active_macros",
        )

    async def _show_macro(self, c: ZendeskShowMacroConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/macros/{c.macro_id}.json", action_name="show_macro",
        )

    async def _create_macro(self, c: ZendeskCreateMacroConfig, auth) -> Dict[str, Any]:
        try:
            macro = json.loads(c.macro_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Macro JSON is not valid JSON: {e}")
        if not isinstance(macro, dict):
            raise ValueError("Macro JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/macros.json",
            json_body={"macro": macro}, action_name="create_macro",
        )

    async def _update_macro(self, c: ZendeskUpdateMacroConfig, auth) -> Dict[str, Any]:
        try:
            macro = json.loads(c.macro_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Macro JSON is not valid JSON: {e}")
        if not isinstance(macro, dict):
            raise ValueError("Macro JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/macros/{c.macro_id}.json",
            json_body={"macro": macro}, action_name="update_macro",
        )

    async def _delete_macro(self, c: ZendeskDeleteMacroConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/macros/{c.macro_id}.json",
            action_name="delete_macro",
        )

    async def _show_macro_changes(self, c: ZendeskShowMacroChangesConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/macros/{c.macro_id}/apply.json",
            action_name="show_macro_changes",
        )

    async def _show_ticket_after_macro(self, c: ZendeskShowTicketAfterMacroConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/tickets/{c.ticket_id}/macros/{c.macro_id}/apply.json",
            action_name="show_ticket_after_macro",
        )

    async def _list_views(self, c: ZendeskListViewsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/views.json", action_name="list_views",
        )

    async def _list_active_views(self, c: ZendeskListActiveViewsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/views/active.json", action_name="list_active_views",
        )

    async def _show_view(self, c: ZendeskShowViewConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/views/{c.view_id}.json", action_name="show_view",
        )

    async def _create_view(self, c: ZendeskCreateViewConfig, auth) -> Dict[str, Any]:
        try:
            view = json.loads(c.view_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"View JSON is not valid JSON: {e}")
        if not isinstance(view, dict):
            raise ValueError("View JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/views.json",
            json_body={"view": view}, action_name="create_view",
        )

    async def _update_view(self, c: ZendeskUpdateViewConfig, auth) -> Dict[str, Any]:
        try:
            view = json.loads(c.view_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"View JSON is not valid JSON: {e}")
        if not isinstance(view, dict):
            raise ValueError("View JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/views/{c.view_id}.json",
            json_body={"view": view}, action_name="update_view",
        )

    async def _delete_view(self, c: ZendeskDeleteViewConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/views/{c.view_id}.json",
            action_name="delete_view",
        )

    async def _list_view_tickets(self, c: ZendeskListViewTicketsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/views/{c.view_id}/tickets.json",
            action_name="list_view_tickets",
        )

    async def _execute_view(self, c: ZendeskExecuteViewConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/views/{c.view_id}/execute.json",
            action_name="execute_view",
        )

    async def _count_view(self, c: ZendeskCountViewConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/views/{c.view_id}/count.json",
            action_name="count_view",
        )

    async def _export_view(self, c: ZendeskExportViewConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/views/{c.view_id}/export.json",
            action_name="export_view",
        )

    # --- triggers-automations-slas ---
    async def _list_triggers(self, c: ZendeskListTriggersConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/triggers.json", action_name="list_triggers",
        )

    async def _list_active_triggers(self, c: ZendeskListActiveTriggersConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/triggers/active.json",
            action_name="list_active_triggers",
        )

    async def _show_trigger(self, c: ZendeskShowTriggerConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/triggers/{c.trigger_id}.json",
            action_name="show_trigger",
        )

    async def _create_trigger(self, c: ZendeskCreateTriggerConfig, auth) -> Dict[str, Any]:
        try:
            trigger = json.loads(c.body_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Trigger JSON is not valid JSON: {e}")
        if not isinstance(trigger, dict):
            raise ValueError("Trigger JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/triggers.json",
            json_body={"trigger": trigger}, action_name="create_trigger",
        )

    async def _update_trigger(self, c: ZendeskUpdateTriggerConfig, auth) -> Dict[str, Any]:
        try:
            trigger = json.loads(c.body_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Trigger JSON is not valid JSON: {e}")
        if not isinstance(trigger, dict):
            raise ValueError("Trigger JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/triggers/{c.trigger_id}.json",
            json_body={"trigger": trigger}, action_name="update_trigger",
        )

    async def _delete_trigger(self, c: ZendeskDeleteTriggerConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/triggers/{c.trigger_id}.json",
            action_name="delete_trigger",
        )

    async def _list_automations(self, c: ZendeskListAutomationsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/automations.json", action_name="list_automations",
        )

    async def _list_active_automations(self, c: ZendeskListActiveAutomationsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/automations/active.json",
            action_name="list_active_automations",
        )

    async def _show_automation(self, c: ZendeskShowAutomationConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/automations/{c.automation_id}.json",
            action_name="show_automation",
        )

    async def _create_automation(self, c: ZendeskCreateAutomationConfig, auth) -> Dict[str, Any]:
        try:
            automation = json.loads(c.body_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Automation JSON is not valid JSON: {e}")
        if not isinstance(automation, dict):
            raise ValueError("Automation JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/automations.json",
            json_body={"automation": automation}, action_name="create_automation",
        )

    async def _update_automation(self, c: ZendeskUpdateAutomationConfig, auth) -> Dict[str, Any]:
        try:
            automation = json.loads(c.body_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Automation JSON is not valid JSON: {e}")
        if not isinstance(automation, dict):
            raise ValueError("Automation JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/automations/{c.automation_id}.json",
            json_body={"automation": automation}, action_name="update_automation",
        )

    async def _delete_automation(self, c: ZendeskDeleteAutomationConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/automations/{c.automation_id}.json",
            action_name="delete_automation",
        )

    async def _list_sla_policies(self, c: ZendeskListSlaPoliciesConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/slas/policies.json",
            action_name="list_sla_policies",
        )

    async def _show_sla_policy(self, c: ZendeskShowSlaPolicyConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/slas/policies/{c.sla_policy_id}.json",
            action_name="show_sla_policy",
        )

    async def _create_sla_policy(self, c: ZendeskCreateSlaPolicyConfig, auth) -> Dict[str, Any]:
        try:
            sla_policy = json.loads(c.body_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"SLA Policy JSON is not valid JSON: {e}")
        if not isinstance(sla_policy, dict):
            raise ValueError("SLA Policy JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/slas/policies.json",
            json_body={"sla_policy": sla_policy}, action_name="create_sla_policy",
        )

    async def _update_sla_policy(self, c: ZendeskUpdateSlaPolicyConfig, auth) -> Dict[str, Any]:
        try:
            sla_policy = json.loads(c.body_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"SLA Policy JSON is not valid JSON: {e}")
        if not isinstance(sla_policy, dict):
            raise ValueError("SLA Policy JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/slas/policies/{c.sla_policy_id}.json",
            json_body={"sla_policy": sla_policy}, action_name="update_sla_policy",
        )

    async def _delete_sla_policy(self, c: ZendeskDeleteSlaPolicyConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/slas/policies/{c.sla_policy_id}.json",
            action_name="delete_sla_policy",
        )

    # --- webhooks-search ---
    async def _list_webhooks(self, c: ZendeskListWebhooksConfig, auth) -> Dict[str, Any]:
        params = {
            "filter[name_contains]": c.name_contains or None,
            "filter[status]": c.status or None,
            "sort": c.sort or None,
            "page[size]": c.page_size or None,
        }
        return await _zendesk_request(
            **auth, method="GET", endpoint="/webhooks",
            params=params, action_name="list_webhooks",
        )

    async def _show_webhook(self, c: ZendeskShowWebhookConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/webhooks/{c.webhook_id}",
            action_name="show_webhook",
        )

    async def _update_webhook(self, c: ZendeskUpdateWebhookConfig, auth) -> Dict[str, Any]:
        try:
            webhook = json.loads(c.webhook_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Webhook JSON is not valid JSON: {e}")
        if not isinstance(webhook, dict):
            raise ValueError("Webhook JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/webhooks/{c.webhook_id}",
            json_body={"webhook": webhook}, action_name="update_webhook",
        )

    async def _patch_webhook(self, c: ZendeskPatchWebhookConfig, auth) -> Dict[str, Any]:
        try:
            webhook = json.loads(c.webhook_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Webhook JSON is not valid JSON: {e}")
        if not isinstance(webhook, dict):
            raise ValueError("Webhook JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="PATCH", endpoint=f"/webhooks/{c.webhook_id}",
            json_body={"webhook": webhook}, action_name="patch_webhook",
        )

    async def _delete_webhook(self, c: ZendeskDeleteWebhookConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/webhooks/{c.webhook_id}",
            action_name="delete_webhook",
        )

    async def _clone_webhook(self, c: ZendeskCloneWebhookConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="POST", endpoint="/webhooks",
            params={"clone_webhook_id": c.clone_webhook_id}, action_name="clone_webhook",
        )

    async def _test_webhook(self, c: ZendeskTestWebhookConfig, auth) -> Dict[str, Any]:
        body = None
        if c.request_json:
            try:
                body = json.loads(c.request_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"Request JSON is not valid JSON: {e}")
            if not isinstance(body, dict):
                raise ValueError("Request JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="POST", endpoint="/webhooks/test",
            params={"webhook_id": c.webhook_id or None}, json_body=body,
            action_name="test_webhook",
        )

    async def _list_webhook_invocations(self, c: ZendeskListWebhookInvocationsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/webhooks/{c.webhook_id}/invocations",
            params={"page[size]": c.page_size or None}, action_name="list_webhook_invocations",
        )

    async def _list_webhook_invocation_attempts(self, c: ZendeskListWebhookInvocationAttemptsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/webhooks/{c.webhook_id}/invocations/{c.invocation_id}/attempts",
            action_name="list_webhook_invocation_attempts",
        )

    async def _show_webhook_signing_secret(self, c: ZendeskShowWebhookSigningSecretConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/webhooks/{c.webhook_id}/signing_secret",
            action_name="show_webhook_signing_secret",
        )

    async def _reset_webhook_signing_secret(self, c: ZendeskResetWebhookSigningSecretConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="POST", endpoint=f"/webhooks/{c.webhook_id}/signing_secret",
            action_name="reset_webhook_signing_secret",
        )

    async def _search_count(self, c: ZendeskSearchCountConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/search/count.json",
            params={"query": c.query}, action_name="search_count",
        )

    async def _export_search(self, c: ZendeskExportSearchConfig, auth) -> Dict[str, Any]:
        params = {
            "query": c.query,
            "filter[type]": c.filter_type,
            "page[size]": c.page_size or None,
        }
        return await _zendesk_request(
            **auth, method="GET", endpoint="/search/export.json",
            params=params, action_name="export_search",
        )

    async def _autocomplete_tags(self, c: ZendeskAutocompleteTagsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/autocomplete/tags.json",
            params={"name": c.name}, action_name="autocomplete_tags",
        )

    # --- guide-articles ---
    async def _list_articles(self, c: ZendeskListArticlesConfig, auth) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "locale": c.locale or None,
            "sort_by": c.sort_by or None,
            "sort_order": c.sort_order or None,
        }
        if c.page_size:
            params["page[size]"] = c.page_size
        return await _zendesk_request(
            **auth, method="GET", endpoint="/help_center/articles.json",
            params=params, action_name="list_articles",
        )

    async def _list_section_articles(self, c: ZendeskListSectionArticlesConfig, auth) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if c.page_size:
            params["page[size]"] = c.page_size
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/help_center/sections/{c.section_id}/articles.json",
            params=params, action_name="list_section_articles",
        )

    async def _list_category_articles(self, c: ZendeskListCategoryArticlesConfig, auth) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if c.page_size:
            params["page[size]"] = c.page_size
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/help_center/categories/{c.category_id}/articles.json",
            params=params, action_name="list_category_articles",
        )

    async def _show_article(self, c: ZendeskShowArticleConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/help_center/articles/{c.article_id}.json",
            action_name="show_article",
        )

    async def _create_article(self, c: ZendeskCreateArticleConfig, auth) -> Dict[str, Any]:
        article: Dict[str, Any] = {
            "title": c.title,
            "body": c.body or None,
            "locale": c.locale,
            "permission_group_id": int(c.permission_group_id)
            if c.permission_group_id and c.permission_group_id.isdigit() else None,
            "user_segment_id": int(c.user_segment_id)
            if c.user_segment_id and c.user_segment_id.isdigit() else None,
            "draft": c.draft == "true" if c.draft else None,
        }
        article = {k: v for k, v in article.items() if v is not None}
        return await _zendesk_request(
            **auth, method="POST",
            endpoint=f"/help_center/sections/{c.section_id}/articles.json",
            json_body={"article": article}, action_name="create_article",
        )

    async def _update_article(self, c: ZendeskUpdateArticleConfig, auth) -> Dict[str, Any]:
        article: Dict[str, Any] = {
            "title": c.title or None,
            "body": c.body or None,
            "section_id": int(c.section_id)
            if c.section_id and c.section_id.isdigit() else None,
            "draft": c.draft == "true" if c.draft else None,
        }
        article = {k: v for k, v in article.items() if v is not None}
        return await _zendesk_request(
            **auth, method="PATCH", endpoint=f"/help_center/articles/{c.article_id}.json",
            json_body={"article": article}, action_name="update_article",
        )

    async def _archive_article(self, c: ZendeskArchiveArticleConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/help_center/articles/{c.article_id}.json",
            action_name="archive_article",
        )

    async def _search_articles(self, c: ZendeskSearchArticlesConfig, auth) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "query": c.query,
            "locale": c.locale or None,
        }
        labels = _comma_list(c.label_names)
        if labels:
            params["label_names"] = ",".join(labels)
        return await _zendesk_request(
            **auth, method="GET", endpoint="/help_center/articles/search.json",
            params=params, action_name="search_articles",
        )

    async def _guide_search(self, c: ZendeskGuideSearchConfig, auth) -> Dict[str, Any]:
        # Zendesk has no /guide/search endpoint; Help Center search lives at
        # /help_center/articles/search (optionally locale-scoped).
        params: Dict[str, Any] = {
            "query": c.query,
            "locale": c.locale or None,
        }
        return await _zendesk_request(
            **auth, method="GET", endpoint="/help_center/articles/search.json",
            params=params, action_name="guide_search",
        )

    async def _list_article_labels(self, c: ZendeskListArticleLabelsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/help_center/articles/{c.article_id}/labels.json",
            action_name="list_article_labels",
        )

    async def _create_article_label(self, c: ZendeskCreateArticleLabelConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="POST",
            endpoint=f"/help_center/articles/{c.article_id}/labels.json",
            json_body={"label": {"name": c.name}}, action_name="create_article_label",
        )

    async def _delete_article_label(self, c: ZendeskDeleteArticleLabelConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE",
            endpoint=f"/help_center/articles/{c.article_id}/labels/{c.label_id}.json",
            action_name="delete_article_label",
        )

    async def _list_article_attachments(self, c: ZendeskListArticleAttachmentsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/help_center/articles/{c.article_id}/attachments.json",
            action_name="list_article_attachments",
        )

    async def _show_article_attachment(self, c: ZendeskShowArticleAttachmentConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/help_center/articles/attachments/{c.attachment_id}.json",
            action_name="show_article_attachment",
        )

    async def _delete_article_attachment(self, c: ZendeskDeleteArticleAttachmentConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE",
            endpoint=f"/help_center/articles/attachments/{c.attachment_id}.json",
            action_name="delete_article_attachment",
        )

    # --- guide-structure ---
    async def _list_sections(self, c: ZendeskListSectionsConfig, auth) -> Dict[str, Any]:
        if c.category_id:
            endpoint = f"/help_center/categories/{c.category_id}/sections.json"
        else:
            endpoint = "/help_center/sections.json"
        return await _zendesk_request(
            **auth, method="GET", endpoint=endpoint,
            params={"locale": c.locale or None}, action_name="list_sections",
        )

    async def _show_section(self, c: ZendeskShowSectionConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/help_center/sections/{c.section_id}.json",
            action_name="show_section",
        )

    async def _create_section(self, c: ZendeskCreateSectionConfig, auth) -> Dict[str, Any]:
        section: Dict[str, Any] = {
            "name": c.name,
            "locale": c.locale,
            "description": c.description or None,
            "position": int(c.position) if c.position and c.position.isdigit() else None,
        }
        section = {k: v for k, v in section.items() if v is not None}
        return await _zendesk_request(
            **auth, method="POST",
            endpoint=f"/help_center/categories/{c.category_id}/sections.json",
            json_body={"section": section}, action_name="create_section",
        )

    async def _update_section(self, c: ZendeskUpdateSectionConfig, auth) -> Dict[str, Any]:
        section: Dict[str, Any] = {
            "name": c.name or None,
            "description": c.description or None,
            "position": int(c.position) if c.position and c.position.isdigit() else None,
            "category_id": int(c.category_id) if c.category_id and c.category_id.isdigit() else None,
        }
        section = {k: v for k, v in section.items() if v is not None}
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/help_center/sections/{c.section_id}.json",
            json_body={"section": section}, action_name="update_section",
        )

    async def _delete_section(self, c: ZendeskDeleteSectionConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/help_center/sections/{c.section_id}.json",
            action_name="delete_section",
        )

    async def _list_categories(self, c: ZendeskListCategoriesConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/help_center/categories.json",
            params={"locale": c.locale or None}, action_name="list_categories",
        )

    async def _show_category(self, c: ZendeskShowCategoryConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/help_center/categories/{c.category_id}.json",
            action_name="show_category",
        )

    async def _create_category(self, c: ZendeskCreateCategoryConfig, auth) -> Dict[str, Any]:
        category: Dict[str, Any] = {
            "name": c.name,
            "locale": c.locale,
            "description": c.description or None,
            "position": int(c.position) if c.position and c.position.isdigit() else None,
        }
        category = {k: v for k, v in category.items() if v is not None}
        return await _zendesk_request(
            **auth, method="POST", endpoint="/help_center/categories.json",
            json_body={"category": category}, action_name="create_category",
        )

    async def _update_category(self, c: ZendeskUpdateCategoryConfig, auth) -> Dict[str, Any]:
        category: Dict[str, Any] = {
            "name": c.name or None,
            "description": c.description or None,
            "position": int(c.position) if c.position and c.position.isdigit() else None,
        }
        category = {k: v for k, v in category.items() if v is not None}
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/help_center/categories/{c.category_id}.json",
            json_body={"category": category}, action_name="update_category",
        )

    async def _delete_category(self, c: ZendeskDeleteCategoryConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/help_center/categories/{c.category_id}.json",
            action_name="delete_category",
        )

    async def _list_article_comments(self, c: ZendeskListArticleCommentsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/help_center/articles/{c.article_id}/comments.json",
            action_name="list_article_comments",
        )

    async def _show_article_comment(self, c: ZendeskShowArticleCommentConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/help_center/articles/{c.article_id}/comments/{c.comment_id}.json",
            action_name="show_article_comment",
        )

    async def _create_article_comment(self, c: ZendeskCreateArticleCommentConfig, auth) -> Dict[str, Any]:
        comment: Dict[str, Any] = {
            "body": c.body,
            "locale": c.locale,
            "author_id": int(c.author_id) if c.author_id and c.author_id.isdigit() else None,
        }
        comment = {k: v for k, v in comment.items() if v is not None}
        body: Dict[str, Any] = {"comment": comment}
        if c.notify_subscribers:
            body["notify_subscribers"] = c.notify_subscribers == "true"
        return await _zendesk_request(
            **auth, method="POST",
            endpoint=f"/help_center/articles/{c.article_id}/comments.json",
            json_body=body, action_name="create_article_comment",
        )

    async def _update_article_comment(self, c: ZendeskUpdateArticleCommentConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="PUT",
            endpoint=f"/help_center/articles/{c.article_id}/comments/{c.comment_id}.json",
            json_body={"comment": {"body": c.body}}, action_name="update_article_comment",
        )

    async def _delete_article_comment(self, c: ZendeskDeleteArticleCommentConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE",
            endpoint=f"/help_center/articles/{c.article_id}/comments/{c.comment_id}.json",
            action_name="delete_article_comment",
        )

    async def _list_article_subscriptions(self, c: ZendeskListArticleSubscriptionsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/help_center/articles/{c.article_id}/subscriptions.json",
            action_name="list_article_subscriptions",
        )

    async def _create_article_subscription(self, c: ZendeskCreateArticleSubscriptionConfig, auth) -> Dict[str, Any]:
        subscription: Dict[str, Any] = {
            "user_id": int(c.user_id) if c.user_id and c.user_id.isdigit() else c.user_id,
            "source_locale": c.source_locale or None,
        }
        subscription = {k: v for k, v in subscription.items() if v is not None}
        return await _zendesk_request(
            **auth, method="POST",
            endpoint=f"/help_center/articles/{c.article_id}/subscriptions.json",
            json_body={"subscription": subscription},
            action_name="create_article_subscription",
        )

    async def _delete_article_subscription(self, c: ZendeskDeleteArticleSubscriptionConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE",
            endpoint=f"/help_center/articles/{c.article_id}/subscriptions/{c.subscription_id}.json",
            action_name="delete_article_subscription",
        )

    async def _list_section_subscriptions(self, c: ZendeskListSectionSubscriptionsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/help_center/sections/{c.section_id}/subscriptions.json",
            action_name="list_section_subscriptions",
        )

    async def _create_section_subscription(self, c: ZendeskCreateSectionSubscriptionConfig, auth) -> Dict[str, Any]:
        subscription: Dict[str, Any] = {
            "user_id": int(c.user_id) if c.user_id and c.user_id.isdigit() else c.user_id,
            "source_locale": c.source_locale or None,
        }
        if c.include_comments:
            subscription["include_comments"] = c.include_comments == "true"
        subscription = {k: v for k, v in subscription.items() if v is not None}
        return await _zendesk_request(
            **auth, method="POST",
            endpoint=f"/help_center/sections/{c.section_id}/subscriptions.json",
            json_body={"subscription": subscription},
            action_name="create_section_subscription",
        )

    async def _delete_section_subscription(self, c: ZendeskDeleteSectionSubscriptionConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE",
            endpoint=f"/help_center/sections/{c.section_id}/subscriptions/{c.subscription_id}.json",
            action_name="delete_section_subscription",
        )

    async def _list_translations(self, c: ZendeskListTranslationsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/help_center/articles/{c.article_id}/translations.json",
            action_name="list_translations",
        )

    async def _create_translation(self, c: ZendeskCreateTranslationConfig, auth) -> Dict[str, Any]:
        translation: Dict[str, Any] = {
            "locale": c.locale,
            "title": c.title,
            "body": c.body or None,
        }
        if c.draft:
            translation["draft"] = c.draft == "true"
        translation = {k: v for k, v in translation.items() if v is not None}
        return await _zendesk_request(
            **auth, method="POST",
            endpoint=f"/help_center/articles/{c.article_id}/translations.json",
            json_body={"translation": translation}, action_name="create_translation",
        )

    async def _update_translation(self, c: ZendeskUpdateTranslationConfig, auth) -> Dict[str, Any]:
        translation: Dict[str, Any] = {
            "title": c.title or None,
            "body": c.body or None,
        }
        if c.draft:
            translation["draft"] = c.draft == "true"
        translation = {k: v for k, v in translation.items() if v is not None}
        return await _zendesk_request(
            **auth, method="PUT",
            endpoint=f"/help_center/articles/{c.article_id}/translations/{c.locale}.json",
            json_body={"translation": translation}, action_name="update_translation",
        )

    async def _delete_translation(self, c: ZendeskDeleteTranslationConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE",
            endpoint=f"/help_center/translations/{c.translation_id}.json",
            action_name="delete_translation",
        )

    # --- custom-objects ---
    async def _list_custom_objects(self, c: ZendeskListCustomObjectsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/custom_objects",
            action_name="list_custom_objects",
        )

    async def _show_custom_object(self, c: ZendeskShowCustomObjectConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/custom_objects/{c.custom_object_key}",
            action_name="show_custom_object",
        )

    async def _create_custom_object(self, c: ZendeskCreateCustomObjectConfig, auth) -> Dict[str, Any]:
        obj: Dict[str, Any] = {
            "key": c.key,
            "title": c.title,
            "title_pluralized": c.title_pluralized,
            "description": c.description or None,
        }
        obj = {k: v for k, v in obj.items() if v is not None}
        return await _zendesk_request(
            **auth, method="POST", endpoint="/custom_objects",
            json_body={"custom_object": obj}, action_name="create_custom_object",
        )

    async def _update_custom_object(self, c: ZendeskUpdateCustomObjectConfig, auth) -> Dict[str, Any]:
        obj: Dict[str, Any] = {
            "title": c.title or None,
            "title_pluralized": c.title_pluralized or None,
            "description": c.description or None,
        }
        obj = {k: v for k, v in obj.items() if v is not None}
        return await _zendesk_request(
            **auth, method="PATCH", endpoint=f"/custom_objects/{c.key}",
            json_body={"custom_object": obj}, action_name="update_custom_object",
        )

    async def _delete_custom_object(self, c: ZendeskDeleteCustomObjectConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/custom_objects/{c.key}",
            action_name="delete_custom_object",
        )

    async def _list_custom_object_records(self, c: ZendeskListCustomObjectRecordsConfig, auth) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if c.page_size:
            params["page[size]"] = c.page_size
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/custom_objects/{c.custom_object_key}/records",
            params=params, action_name="list_custom_object_records",
        )

    async def _show_custom_object_record(self, c: ZendeskShowCustomObjectRecordConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/custom_objects/{c.custom_object_key}/records/{c.record_id}",
            action_name="show_custom_object_record",
        )

    async def _create_custom_object_record(self, c: ZendeskCreateCustomObjectRecordConfig, auth) -> Dict[str, Any]:
        try:
            record = json.loads(c.record_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Record JSON is not valid JSON: {e}")
        if not isinstance(record, dict):
            raise ValueError("Record JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="POST", endpoint=f"/custom_objects/{c.custom_object_key}/records",
            json_body={"custom_object_record": record}, action_name="create_custom_object_record",
        )

    async def _update_custom_object_record(self, c: ZendeskUpdateCustomObjectRecordConfig, auth) -> Dict[str, Any]:
        try:
            record = json.loads(c.record_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Record JSON is not valid JSON: {e}")
        if not isinstance(record, dict):
            raise ValueError("Record JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="PATCH",
            endpoint=f"/custom_objects/{c.custom_object_key}/records/{c.record_id}",
            json_body={"custom_object_record": record}, action_name="update_custom_object_record",
        )

    async def _delete_custom_object_record(self, c: ZendeskDeleteCustomObjectRecordConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE",
            endpoint=f"/custom_objects/{c.custom_object_key}/records/{c.record_id}",
            action_name="delete_custom_object_record",
        )

    async def _upsert_custom_object_record(self, c: ZendeskUpsertCustomObjectRecordConfig, auth) -> Dict[str, Any]:
        try:
            record = json.loads(c.record_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Record JSON is not valid JSON: {e}")
        if not isinstance(record, dict):
            raise ValueError("Record JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="PATCH", endpoint=f"/custom_objects/{c.custom_object_key}/records",
            params={c.match_by: c.match_value},
            json_body={"custom_object_record": record}, action_name="upsert_custom_object_record",
        )

    async def _search_custom_object_records(self, c: ZendeskSearchCustomObjectRecordsConfig, auth) -> Dict[str, Any]:
        params: Dict[str, Any] = {"query": c.query, "sort": c.sort or None}
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/custom_objects/{c.custom_object_key}/records/search",
            params=params, action_name="search_custom_object_records",
        )

    async def _count_custom_object_records(self, c: ZendeskCountCustomObjectRecordsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/custom_objects/{c.custom_object_key}/records/count",
            action_name="count_custom_object_records",
        )

    async def _list_custom_object_fields(self, c: ZendeskListCustomObjectFieldsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/custom_objects/{c.custom_object_key}/fields",
            action_name="list_custom_object_fields",
        )

    async def _show_custom_object_field(self, c: ZendeskShowCustomObjectFieldConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/custom_objects/{c.custom_object_key}/fields/{c.field_key_or_id}",
            action_name="show_custom_object_field",
        )

    async def _create_custom_object_field(self, c: ZendeskCreateCustomObjectFieldConfig, auth) -> Dict[str, Any]:
        try:
            field = json.loads(c.field_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Field JSON is not valid JSON: {e}")
        if not isinstance(field, dict):
            raise ValueError("Field JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="POST", endpoint=f"/custom_objects/{c.custom_object_key}/fields",
            json_body={"custom_object_field": field}, action_name="create_custom_object_field",
        )

    async def _update_custom_object_field(self, c: ZendeskUpdateCustomObjectFieldConfig, auth) -> Dict[str, Any]:
        try:
            field = json.loads(c.field_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Field JSON is not valid JSON: {e}")
        if not isinstance(field, dict):
            raise ValueError("Field JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="PATCH",
            endpoint=f"/custom_objects/{c.custom_object_key}/fields/{c.field_key_or_id}",
            json_body={"custom_object_field": field}, action_name="update_custom_object_field",
        )

    async def _delete_custom_object_field(self, c: ZendeskDeleteCustomObjectFieldConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE",
            endpoint=f"/custom_objects/{c.custom_object_key}/fields/{c.field_key_or_id}",
            action_name="delete_custom_object_field",
        )

    # --- events-talk-chat ---
    async def _get_user_events(self, c: ZendeskGetUserEventsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/users/{c.user_id}/events",
            action_name="get_user_events",
        )

    async def _track_user_event(self, c: ZendeskTrackUserEventConfig, auth) -> Dict[str, Any]:
        try:
            event = json.loads(c.event_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Event JSON is not valid JSON: {e}")
        if not isinstance(event, dict):
            raise ValueError("Event JSON must be a JSON object")
        body: Dict[str, Any] = {"event": event}
        if c.profile_json:
            try:
                profile = json.loads(c.profile_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"Profile JSON is not valid JSON: {e}")
            if not isinstance(profile, dict):
                raise ValueError("Profile JSON must be a JSON object")
            body["profile"] = profile
        return await _zendesk_request(
            **auth, method="POST", endpoint=f"/users/{c.user_id}/events",
            json_body=body, action_name="track_user_event",
        )

    async def _show_profile(self, c: ZendeskShowProfileConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/user_profiles/{c.profile_id}",
            action_name="show_profile",
        )

    async def _create_update_profile(self, c: ZendeskCreateUpdateProfileConfig, auth) -> Dict[str, Any]:
        try:
            body = json.loads(c.profile_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Profile JSON is not valid JSON: {e}")
        if not isinstance(body, dict):
            raise ValueError("Profile JSON must be a JSON object")
        return await _zendesk_request(
            **auth, method="PUT", endpoint=f"/users/{c.user_id}/profiles",
            params={"identifier": c.identifier}, json_body=body,
            action_name="create_update_profile",
        )

    async def _delete_profile(self, c: ZendeskDeleteProfileConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="DELETE", endpoint=f"/user_profiles/{c.profile_id}",
            action_name="delete_profile",
        )

    async def _current_queue_activity(self, c: ZendeskCurrentQueueActivityConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint="/channels/voice/stats/current_queue_activity.json",
            action_name="current_queue_activity",
        )

    async def _agents_activity(self, c: ZendeskAgentsActivityConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint="/channels/voice/stats/agents_activity.json",
            action_name="agents_activity",
        )

    async def _show_availability(self, c: ZendeskShowAvailabilityConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET",
            endpoint=f"/channels/voice/availabilities/{c.agent_id}.json",
            action_name="show_availability",
        )

    async def _update_availability(self, c: ZendeskUpdateAvailabilityConfig, auth) -> Dict[str, Any]:
        availability: Dict[str, Any] = {"agent_state": c.agent_state}
        if c.via:
            availability["via"] = c.via
        return await _zendesk_request(
            **auth, method="PUT",
            endpoint=f"/channels/voice/availabilities/{c.agent_id}.json",
            json_body={"availability": availability},
            action_name="update_availability",
        )

    async def _create_voicemail_ticket(self, c: ZendeskCreateVoicemailTicketConfig, auth) -> Dict[str, Any]:
        try:
            ticket = json.loads(c.ticket_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Ticket JSON is not valid JSON: {e}")
        if not isinstance(ticket, dict):
            raise ValueError("Ticket JSON must be a JSON object")
        body: Dict[str, Any] = {"ticket": ticket}
        if c.display_to_agent:
            body["display_to_agent"] = (
                int(c.display_to_agent) if c.display_to_agent.isdigit() else c.display_to_agent
            )
        return await _zendesk_request(
            **auth, method="POST", endpoint="/channels/voice/tickets",
            json_body=body, action_name="create_voicemail_ticket",
        )

    async def _list_chats(self, c: ZendeskListChatsConfig, auth) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if c.ids:
            params["ids"] = ",".join(_comma_list(c.ids) or [])
        return await _zendesk_request(
            **auth, method="GET", endpoint="/chat/chats", params=params or None,
            action_name="list_chats",
        )

    async def _show_chat(self, c: ZendeskShowChatConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/chat/chats/{c.chat_id}",
            action_name="show_chat",
        )

    async def _list_agents(self, c: ZendeskListAgentsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/chat/agents", action_name="list_agents",
        )

    async def _show_agent(self, c: ZendeskShowAgentConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint=f"/chat/agents/{c.agent_id}",
            action_name="show_agent",
        )

    async def _list_departments(self, c: ZendeskListDepartmentsConfig, auth) -> Dict[str, Any]:
        return await _zendesk_request(
            **auth, method="GET", endpoint="/chat/departments",
            action_name="list_departments",
        )

    # ------------------------------------------------------------------
    # Sunshine Conversations (SCC) handlers
    # ------------------------------------------------------------------
    def _scc_handlers(self):
        return {
            "scc_create_user": self._scc_create_user,
            "scc_get_user": self._scc_get_user,
            "scc_update_user": self._scc_update_user,
            "scc_delete_user": self._scc_delete_user,
            "scc_list_users": self._scc_list_users,
            "scc_create_conversation": self._scc_create_conversation,
            "scc_get_conversation": self._scc_get_conversation,
            "scc_list_conversations": self._scc_list_conversations,
            "scc_update_conversation": self._scc_update_conversation,
            "scc_delete_conversation": self._scc_delete_conversation,
            "scc_post_message": self._scc_post_message,
            "scc_list_messages": self._scc_list_messages,
            "scc_delete_message": self._scc_delete_message,
            "scc_delete_all_messages": self._scc_delete_all_messages,
            "scc_post_activity": self._scc_post_activity,
            "scc_pass_control": self._scc_pass_control,
            "scc_offer_control": self._scc_offer_control,
            "scc_accept_control": self._scc_accept_control,
            "scc_release_control": self._scc_release_control,
            "scc_list_integrations": self._scc_list_integrations,
            "scc_create_integration": self._scc_create_integration,
            "scc_list_webhooks": self._scc_list_webhooks,
            "scc_create_webhook": self._scc_create_webhook,
        }

    @staticmethod
    def _scc_json(value, field):
        if not value:
            return None
        try:
            return json.loads(value)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid JSON in {field}: {e}")

    async def _scc_create_user(self, c, cred) -> Dict[str, Any]:
        body: Dict[str, Any] = {"externalId": c.external_id}
        profile = self._scc_json(c.profile_json, "Profile")
        if profile is not None:
            body["profile"] = profile
        metadata = self._scc_json(c.metadata_json, "Metadata")
        if metadata is not None:
            body["metadata"] = metadata
        return await _scc_request(cred=cred, method="POST", endpoint="/users", json_body=body, action_name="scc_create_user")

    async def _scc_get_user(self, c, cred) -> Dict[str, Any]:
        return await _scc_request(cred=cred, method="GET", endpoint=f"/users/{c.user_id}", action_name="scc_get_user")

    async def _scc_update_user(self, c, cred) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        profile = self._scc_json(c.profile_json, "Profile")
        if profile is not None:
            body["profile"] = profile
        metadata = self._scc_json(c.metadata_json, "Metadata")
        if metadata is not None:
            body["metadata"] = metadata
        return await _scc_request(cred=cred, method="PATCH", endpoint=f"/users/{c.user_id}", json_body=body, action_name="scc_update_user")

    async def _scc_delete_user(self, c, cred) -> Dict[str, Any]:
        return await _scc_request(cred=cred, method="DELETE", endpoint=f"/users/{c.user_id}", action_name="scc_delete_user")

    async def _scc_list_users(self, c, cred) -> Dict[str, Any]:
        params = {"filter[identities.email]": c.email, "page[size]": c.page_size, "page[after]": c.page_after}
        return await _scc_request(cred=cred, method="GET", endpoint="/users", params=params, action_name="scc_list_users")

    async def _scc_create_conversation(self, c, cred) -> Dict[str, Any]:
        body: Dict[str, Any] = {"type": c.conversation_type}
        if c.user_id:
            body["participants"] = [{"userId": c.user_id}]
        if c.display_name:
            body["displayName"] = c.display_name
        metadata = self._scc_json(c.metadata_json, "Metadata")
        if metadata is not None:
            body["metadata"] = metadata
        return await _scc_request(cred=cred, method="POST", endpoint="/conversations", json_body=body, action_name="scc_create_conversation")

    async def _scc_get_conversation(self, c, cred) -> Dict[str, Any]:
        return await _scc_request(cred=cred, method="GET", endpoint=f"/conversations/{c.conversation_id}", action_name="scc_get_conversation")

    async def _scc_list_conversations(self, c, cred) -> Dict[str, Any]:
        params = {"filter[userId]": c.user_id, "page[after]": c.page_after}
        return await _scc_request(cred=cred, method="GET", endpoint="/conversations", params=params, action_name="scc_list_conversations")

    async def _scc_update_conversation(self, c, cred) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if c.display_name:
            body["displayName"] = c.display_name
        metadata = self._scc_json(c.metadata_json, "Metadata")
        if metadata is not None:
            body["metadata"] = metadata
        return await _scc_request(cred=cred, method="PATCH", endpoint=f"/conversations/{c.conversation_id}", json_body=body, action_name="scc_update_conversation")

    async def _scc_delete_conversation(self, c, cred) -> Dict[str, Any]:
        return await _scc_request(cred=cred, method="DELETE", endpoint=f"/conversations/{c.conversation_id}", action_name="scc_delete_conversation")

    async def _scc_post_message(self, c, cred) -> Dict[str, Any]:
        author: Dict[str, Any] = {"type": c.author_type}
        if c.author_type == "user" and c.author_user_id:
            author["userId"] = c.author_user_id
        body = {"author": author, "content": {"type": "text", "text": c.text}}
        return await _scc_request(cred=cred, method="POST", endpoint=f"/conversations/{c.conversation_id}/messages", json_body=body, action_name="scc_post_message")

    async def _scc_list_messages(self, c, cred) -> Dict[str, Any]:
        params = {"page[size]": c.page_size, "page[after]": c.page_after}
        return await _scc_request(cred=cred, method="GET", endpoint=f"/conversations/{c.conversation_id}/messages", params=params, action_name="scc_list_messages")

    async def _scc_delete_message(self, c, cred) -> Dict[str, Any]:
        return await _scc_request(cred=cred, method="DELETE", endpoint=f"/conversations/{c.conversation_id}/messages/{c.message_id}", action_name="scc_delete_message")

    async def _scc_delete_all_messages(self, c, cred) -> Dict[str, Any]:
        return await _scc_request(cred=cred, method="DELETE", endpoint=f"/conversations/{c.conversation_id}/messages", action_name="scc_delete_all_messages")

    async def _scc_post_activity(self, c, cred) -> Dict[str, Any]:
        author: Dict[str, Any] = {"type": c.author_type}
        if c.author_type == "user" and c.author_user_id:
            author["userId"] = c.author_user_id
        body = {"author": author, "type": c.activity_type}
        return await _scc_request(cred=cred, method="POST", endpoint=f"/conversations/{c.conversation_id}/activity", json_body=body, action_name="scc_post_activity")

    async def _scc_pass_control(self, c, cred) -> Dict[str, Any]:
        body: Dict[str, Any] = {"switchboardIntegration": c.switchboard_integration}
        metadata = self._scc_json(c.metadata_json, "Metadata")
        if metadata is not None:
            body["metadata"] = metadata
        return await _scc_request(cred=cred, method="POST", endpoint=f"/conversations/{c.conversation_id}/passControl", json_body=body, action_name="scc_pass_control")

    async def _scc_offer_control(self, c, cred) -> Dict[str, Any]:
        body = {"switchboardIntegration": c.switchboard_integration}
        return await _scc_request(cred=cred, method="POST", endpoint=f"/conversations/{c.conversation_id}/offerControl", json_body=body, action_name="scc_offer_control")

    async def _scc_accept_control(self, c, cred) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        metadata = self._scc_json(c.metadata_json, "Metadata")
        if metadata is not None:
            body["metadata"] = metadata
        return await _scc_request(cred=cred, method="POST", endpoint=f"/conversations/{c.conversation_id}/acceptControl", json_body=body, action_name="scc_accept_control")

    async def _scc_release_control(self, c, cred) -> Dict[str, Any]:
        return await _scc_request(cred=cred, method="POST", endpoint=f"/conversations/{c.conversation_id}/releaseControl", json_body={}, action_name="scc_release_control")

    async def _scc_list_integrations(self, c, cred) -> Dict[str, Any]:
        return await _scc_request(cred=cred, method="GET", endpoint="/integrations", action_name="scc_list_integrations")

    async def _scc_create_integration(self, c, cred) -> Dict[str, Any]:
        body = self._scc_json(c.integration_json, "Integration")
        return await _scc_request(cred=cred, method="POST", endpoint="/integrations", json_body=body, action_name="scc_create_integration")

    async def _scc_list_webhooks(self, c, cred) -> Dict[str, Any]:
        return await _scc_request(cred=cred, method="GET", endpoint=f"/integrations/{c.integration_id}/webhooks", action_name="scc_list_webhooks")

    async def _scc_create_webhook(self, c, cred) -> Dict[str, Any]:
        body = {
            "target": c.target,
            "triggers": _comma_list(c.triggers) or [],
            "includeFullUser": c.include_full_user == "true",
        }
        return await _scc_request(cred=cred, method="POST", endpoint=f"/integrations/{c.integration_id}/webhooks", json_body=body, action_name="scc_create_webhook")
