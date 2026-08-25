"""
Intercom customer messaging automation node.

Provides workflow integration with the Intercom REST API for operations including:
- Contacts: create/update, get, update, list, search, archive, merge, add note
- Conversations: create, get, list, search, reply, manage, tag
- Tickets: create, get, update, search
- Companies: create/update, get, list company contacts
- Messaging: send message, submit data event
- Tags / Admins / Teams / Data Attributes / Segments: list & manage
- Webhook Trigger: receive Intercom topic events (contact/conversation/ticket)

Authentication: OAuth 2.0 (public app, authorization_code — "Connect Intercom
account") or a static Access Token (Bearer) auto-generated for a private app in
the Intercom Developer Hub. Both forms pass `Authorization: Bearer <token>`.
Intercom OAuth tokens are long-lived (no expiry) and have no refresh token, so
there is nothing to rotate.

API Base URL: https://api.intercom.io (US) / https://api.eu.intercom.io (EU) /
https://api.au.intercom.io (AU). Region is selectable per credential.
Documentation: https://developers.intercom.com/docs/references/rest-api/api.intercom.io
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
from nodes.scopes.intercom import INTERCOM_SCOPES

logger = logging.getLogger(__name__)

# Regional base URLs (data residency). US is the default.
INTERCOM_REGION_BASES = {
    "us": "https://api.intercom.io",
    "eu": "https://api.eu.intercom.io",
    "au": "https://api.au.intercom.io",
}

# Pin the API version; behavior/shape differs across versions and unpinned
# requests follow the Developer Hub default which can change underneath us.
INTERCOM_API_VERSION = "2.14"

# Domain-specific webhook topic lists. Intercom supports multiple webhook
# subscriptions per app, each with its own URL + independent topic selection
# (https://developers.intercom.com/docs/build-an-integration/learn-more/webhooks/).
# Each domain trigger gets its own NoClick webhook URL; the user adds each URL
# separately in Developer Hub > Configure > Webhooks and subscribes the matching
# topic group. The sentinel "*" means "fire on any topic received at this URL".

INTERCOM_CONVERSATION_TOPICS: List[tuple[str, str]] = [
    ("*", "All conversation events"),
    ("conversation.user.created", "User started a conversation"),
    ("conversation.user.replied", "User replied to a conversation"),
    ("conversation.admin.replied", "Admin replied to a conversation"),
    ("conversation.admin.single.created", "Admin started a conversation"),
    ("conversation.admin.assigned", "Conversation assigned to an admin"),
    ("conversation.admin.open.assigned", "Admin opened and assigned conversation"),
    ("conversation.admin.noted", "Admin added a note"),
    ("conversation.admin.opened", "Conversation reopened"),
    ("conversation.admin.closed", "Conversation closed"),
    ("conversation.admin.snoozed", "Conversation snoozed"),
    ("conversation.admin.unsnoozed", "Conversation unsnoozed"),
    ("conversation.operator.replied", "Fin/bot replied to a conversation"),
    ("conversation.rating.added", "Conversation rated"),
    ("conversation.priority.updated", "Conversation priority changed"),
    ("conversation.read", "Conversation marked as read"),
    ("conversation.deleted", "Conversation deleted"),
    ("conversation.company.updated", "Company on conversation updated"),
    ("conversation.contact.attached", "Contact attached to conversation"),
    ("conversation.contact.detached", "Contact detached from conversation"),
    ("conversation_part.tag.created", "Tag added to a conversation part"),
    ("conversation_part.redacted", "Conversation part redacted"),
]

INTERCOM_CONTACT_TOPICS: List[tuple[str, str]] = [
    ("*", "All contact events"),
    ("contact.user.created", "User contact created"),
    ("contact.user.updated", "User contact updated"),
    ("contact.lead.created", "Lead created"),
    ("contact.lead.updated", "Lead updated"),
    ("contact.lead.added_email", "Email added to lead"),
    ("contact.lead.signed_up", "Lead signed up (converted to user)"),
    ("contact.user.tag.created", "User tagged"),
    ("contact.user.tag.deleted", "User untagged"),
    ("contact.lead.tag.created", "Lead tagged"),
    ("contact.lead.tag.deleted", "Lead untagged"),
    ("contact.email.updated", "Contact email updated"),
    ("contact.subscribed", "Contact subscribed"),
    ("contact.unsubscribed", "Contact unsubscribed"),
    ("contact.archived", "Contact archived"),
    ("contact.unarchive", "Contact unarchived"),
    ("contact.merged", "Contacts merged"),
    ("contact.deleted", "Contact deleted"),
    ("visitor.signed_up", "Visitor converted to a user"),
]

INTERCOM_TICKET_TOPICS: List[tuple[str, str]] = [
    ("*", "All ticket events"),
    ("ticket.created", "Ticket created"),
    ("ticket.state.updated", "Ticket state changed"),
    ("ticket.admin.assigned", "Ticket assigned to an admin"),
    ("ticket.team.assigned", "Ticket assigned to a team"),
    ("ticket.admin.replied", "Admin replied to a ticket"),
    ("ticket.contact.replied", "Contact replied to a ticket"),
    ("ticket.note.created", "Note added to a ticket"),
    ("ticket.attribute.updated", "Ticket attribute updated"),
    ("ticket.rating.provided", "Ticket rated"),
    ("ticket.closed", "Ticket closed"),
    ("ticket.resolved", "Ticket resolved"),
    ("ticket.contact.attached", "Contact attached to ticket"),
    ("ticket.contact.detached", "Contact detached from ticket"),
]

INTERCOM_COMPANY_TOPICS: List[tuple[str, str]] = [
    ("*", "All company & workspace events"),
    ("company.created", "Company created"),
    ("company.updated", "Company updated"),
    ("company.deleted", "Company deleted"),
    ("company.contact.attached", "Contact attached to a company"),
    ("company.contact.detached", "Contact detached from a company"),
    ("event.created", "Custom data event submitted"),
    ("admin.activity_log_event.created", "Admin activity log entry created"),
    ("admin.added_to_workspace", "Admin added to workspace"),
    ("admin.removed_from_workspace", "Admin removed from workspace"),
    ("admin.away_mode_updated", "Admin away mode changed"),
    ("ping", "Ping (subscription health check)"),
]


# ============================================================================
# Credential Schemas
# ============================================================================


class IntercomAccessTokenCredential(BaseModel):
    """Static Access Token credential for Intercom (private app)."""

    credential_type: Literal["intercom_token"] = Field(
        "intercom_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="Your Intercom Access Token from Developer Hub > your app > Configure > Authentication",
        json_schema_extra={"ui:widget": "password"},
    )
    region: str = Field(
        "us",
        title="Region",
        description="Data residency region for your Intercom workspace",
        json_schema_extra={
            "enum": ["us", "eu", "au"],
            "enumNames": ["US (api.intercom.io)", "EU (api.eu.intercom.io)", "AU (api.au.intercom.io)"],
            "x-enum-searchable": True,
        },
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://app.intercom.com/a/apps/_/developer-hub",
            "x-credential-instructions": (
                "Create a private app in the Intercom Developer Hub, open "
                "Configure > Authentication, copy the Access Token, and select "
                "the region matching your workspace's data residency."
            ),
        }
    )


class IntercomOAuthCredential(BaseModel):
    """OAuth 2.0 credential for Intercom (public app, authorization_code flow).

    Tokens are obtained via the OAuth flow ("Connect Intercom account"), not
    entered manually. Intercom access tokens are LONG-LIVED — they never expire
    and there is no refresh token, so this credential intentionally carries no
    ``refresh_token`` / ``expires_at`` (nothing to rotate).

    Register an OAuth app at: https://app.intercom.com/a/apps/_/developer-hub
    """

    credential_type: Literal["intercom_oauth"] = Field(
        "intercom_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="Intercom OAuth access token (Bearer). Long-lived; never expires.",
        json_schema_extra={"ui:widget": "password"},
    )
    region: str = Field(
        "us",
        title="Region",
        description="Data residency region for your Intercom workspace",
        json_schema_extra={
            "enum": ["us", "eu", "au"],
            "enumNames": ["US (api.intercom.io)", "EU (api.eu.intercom.io)", "AU (api.au.intercom.io)"],
            "x-enum-searchable": True,
        },
    )
    name: Optional[str] = Field(None, title="Workspace Name")
    email: Optional[str] = Field(None, title="Account Email")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "intercom",
            "x-oauth-scopes": [
                "read_write_users",
                "read_write_companies",
                "read_write_conversations",
                "read_write_tags",
                "read_write_events",
                "read_write_tickets",
                "read_admins",
                "read_teams",
            ],
            "x-oauth-supports-custom-client": True,
            "x-oauth-custom-client-help": (
                "Optionally bring your own Intercom OAuth app. Create one in the "
                "Intercom Developer Hub, open Configure > Authentication, add "
                "NoClick's Intercom callback as a redirect URL, enable the scopes "
                "above, and paste its Client ID and Secret here. Leave blank to "
                "use NoClick's shared Intercom app."
            ),
            "x-credential-url": "https://app.intercom.com/a/apps/_/developer-hub",
        }
    )


IntercomCredential = Union[IntercomOAuthCredential, IntercomAccessTokenCredential]


# ============================================================================
# Contact Operation Configs
# ============================================================================


class IntercomCreateContactConfig(BaseModel):
    """Create (or upsert) a contact — a user or a lead."""

    operation: Literal["create_contact"] = Field(
        "create_contact",
        json_schema_extra={
            "const": "create_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Create or Update Contact",
            "x-creates-resource": True,
            "x-resource-type": "intercom_contact",
            "x-resource-id-path": "data.id",
        },
        title="Create or Update Contact",
    )
    role: str = Field(
        "user",
        title="Role",
        description="Whether the contact is a user or a lead",
        json_schema_extra={
            "enum": ["user", "lead"],
            "enumNames": ["User", "Lead"],
            "x-enum-searchable": True,
        },
    )
    email: Optional[str] = Field(None, title="Email", description="Contact email address")
    external_id: Optional[str] = Field(
        None, title="External ID", description="Your unique identifier for this contact (upserts on it)"
    )
    name: Optional[str] = Field(None, title="Name", description="Contact's full name")
    phone: Optional[str] = Field(None, title="Phone", description="Contact phone number")
    custom_attributes: Optional[str] = Field(
        None,
        title="Custom Attributes (JSON)",
        description="JSON object of custom attributes",
        json_schema_extra={"ui:widget": "textarea"},
    )


# Shared dynamic-option dicts for contact/company/ticket ID picker fields
_CONTACT_ID_OPTS: Dict[str, Any] = {
    "x-resource-type": "intercom_contact",
    "x-dynamic-options": {
        "field_name": "contact_id",
        "placeholder": "Search contacts...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste contact ID",
    }
}
_COMPANY_ID_OPTS: Dict[str, Any] = {
    "x-resource-type": "intercom_company",
    "x-dynamic-options": {
        "field_name": "company_id",
        "placeholder": "Search companies...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste company ID",
    }
}
_TICKET_TYPE_ID_OPTS: Dict[str, Any] = {
    "x-dynamic-options": {
        "field_name": "ticket_type_id",
        "placeholder": "Select ticket type...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste ticket type ID",
    }
}

class IntercomGetContactConfig(BaseModel):
    """Retrieve a single contact by its Intercom ID."""

    operation: Literal["get_contact"] = Field(
        "get_contact",
        json_schema_extra={
            "const": "get_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Get Contact",
        },
        title="Get Contact",
    )
    contact_id: str = Field(..., title="Contact ID", description="The Intercom contact ID", json_schema_extra=_CONTACT_ID_OPTS)


class IntercomUpdateContactConfig(BaseModel):
    """Update a contact's attributes."""

    operation: Literal["update_contact"] = Field(
        "update_contact",
        json_schema_extra={
            "const": "update_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Update Contact",
        },
        title="Update Contact",
    )
    contact_id: str = Field(..., title="Contact ID", description="The Intercom contact ID to update", json_schema_extra=_CONTACT_ID_OPTS)
    email: Optional[str] = Field(None, title="Email", description="New email address")
    name: Optional[str] = Field(None, title="Name", description="New full name")
    phone: Optional[str] = Field(None, title="Phone", description="New phone number")
    custom_attributes: Optional[str] = Field(
        None,
        title="Custom Attributes (JSON)",
        description="JSON object of custom attributes to set",
        json_schema_extra={"ui:widget": "textarea"},
    )


class IntercomListContactsConfig(BaseModel):
    """List/cursor-paginate all contacts."""

    operation: Literal["list_contacts"] = Field(
        "list_contacts",
        json_schema_extra={
            "const": "list_contacts",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "List Contacts",
        },
        title="List Contacts",
    )
    per_page: Optional[str] = Field(
        "50", title="Per Page", description="Number of contacts per page (max 150)"
    )
    starting_after: Optional[str] = Field(
        None, title="Starting After", description="Pagination cursor for the next page"
    )


class IntercomSearchContactsConfig(BaseModel):
    """Search contacts by attribute filters (JSON query body)."""

    operation: Literal["search_contacts"] = Field(
        "search_contacts",
        json_schema_extra={
            "const": "search_contacts",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Search Contacts",
        },
        title="Search Contacts",
    )
    query: str = Field(
        ...,
        title="Query (JSON)",
        description='Intercom search query object, e.g. {"field":"email","operator":"=","value":"a@b.com"}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    per_page: Optional[str] = Field(
        "50", title="Per Page", description="Number of results per page"
    )


class IntercomArchiveContactConfig(BaseModel):
    """Archive (soft-delete) a contact."""

    operation: Literal["archive_contact"] = Field(
        "archive_contact",
        json_schema_extra={
            "const": "archive_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Archive Contact",
        },
        title="Archive Contact",
    )
    contact_id: str = Field(..., title="Contact ID", description="The Intercom contact ID to archive", json_schema_extra=_CONTACT_ID_OPTS)


class IntercomMergeContactsConfig(BaseModel):
    """Merge a lead into a user."""

    operation: Literal["merge_contacts"] = Field(
        "merge_contacts",
        json_schema_extra={
            "const": "merge_contacts",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Merge Contacts",
        },
        title="Merge Contacts",
    )
    contact_id: str = Field(
        ..., title="Lead ID", description="The lead contact ID (the contact being merged from)",
        json_schema_extra=_CONTACT_ID_OPTS,
    )
    into_contact_id: str = Field(
        ..., title="Into User ID", description="The user contact ID to merge the lead into",
        json_schema_extra=_CONTACT_ID_OPTS,
    )


class IntercomCreateNoteConfig(BaseModel):
    """Add an internal note to a contact."""

    operation: Literal["create_note"] = Field(
        "create_note",
        json_schema_extra={
            "const": "create_note",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Create Contact Note",
        },
        title="Create Contact Note",
    )
    contact_id: str = Field(..., title="Contact ID", description="The contact to add a note to", json_schema_extra=_CONTACT_ID_OPTS)
    body: str = Field(
        ...,
        title="Note Body",
        description="The note text",
        json_schema_extra={"ui:widget": "textarea"},
    )
    admin_id: Optional[str] = Field(
        None,
        title="Admin",
        description="Admin who authors the note",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "admin_id",
                "placeholder": "Select an admin...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste admin ID",
            }
        },
    )


class IntercomUnarchiveContactConfig(BaseModel):
    operation: Literal["unarchive_contact"] = Field("unarchive_contact", json_schema_extra={"const": "unarchive_contact", "ui:hidden": True, "x-category": "Contacts", "x-is-trigger": False, "x-display-name": "Unarchive Contact"}, title="Unarchive Contact")
    contact_id: str = Field(..., title="Contact ID", description="The Intercom contact ID to unarchive", json_schema_extra=_CONTACT_ID_OPTS)


class IntercomDeleteContactConfig(BaseModel):
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"const": "delete_contact", "ui:hidden": True, "x-category": "Contacts", "x-is-trigger": False, "x-display-name": "Delete Contact"}, title="Delete Contact")
    contact_id: str = Field(..., title="Contact ID", description="The Intercom contact ID to permanently delete", json_schema_extra=_CONTACT_ID_OPTS)


class IntercomListContactNotesConfig(BaseModel):
    operation: Literal["list_contact_notes"] = Field("list_contact_notes", json_schema_extra={"const": "list_contact_notes", "ui:hidden": True, "x-category": "Contacts", "x-is-trigger": False, "x-display-name": "List Contact Notes"}, title="List Contact Notes")
    contact_id: str = Field(..., title="Contact ID", description="The Intercom contact ID", json_schema_extra=_CONTACT_ID_OPTS)


class IntercomListContactCompaniesConfig(BaseModel):
    operation: Literal["list_contact_companies"] = Field("list_contact_companies", json_schema_extra={"const": "list_contact_companies", "ui:hidden": True, "x-category": "Contacts", "x-is-trigger": False, "x-display-name": "List Contact Companies"}, title="List Contact Companies")
    contact_id: str = Field(..., title="Contact ID", description="The Intercom contact ID", json_schema_extra=_CONTACT_ID_OPTS)


class IntercomAttachContactToCompanyConfig(BaseModel):
    operation: Literal["attach_contact_to_company"] = Field("attach_contact_to_company", json_schema_extra={"const": "attach_contact_to_company", "ui:hidden": True, "x-category": "Contacts", "x-is-trigger": False, "x-display-name": "Attach Contact to Company"}, title="Attach Contact to Company")
    contact_id: str = Field(..., title="Contact ID", description="The Intercom contact ID", json_schema_extra=_CONTACT_ID_OPTS)
    company_id: str = Field(..., title="Company ID", description="The Intercom company ID to attach the contact to", json_schema_extra=_COMPANY_ID_OPTS)


class IntercomDetachContactFromCompanyConfig(BaseModel):
    operation: Literal["detach_contact_from_company"] = Field("detach_contact_from_company", json_schema_extra={"const": "detach_contact_from_company", "ui:hidden": True, "x-category": "Contacts", "x-is-trigger": False, "x-display-name": "Detach Contact from Company"}, title="Detach Contact from Company")
    contact_id: str = Field(..., title="Contact ID", description="The Intercom contact ID", json_schema_extra=_CONTACT_ID_OPTS)
    company_id: str = Field(..., title="Company ID", description="The Intercom company ID to detach", json_schema_extra=_COMPANY_ID_OPTS)


class IntercomTagContactConfig(BaseModel):
    operation: Literal["tag_contact"] = Field("tag_contact", json_schema_extra={"const": "tag_contact", "ui:hidden": True, "x-category": "Contacts", "x-is-trigger": False, "x-display-name": "Tag Contact"}, title="Tag Contact")
    contact_id: str = Field(..., title="Contact ID", description="The Intercom contact ID", json_schema_extra=_CONTACT_ID_OPTS)
    tag_id: str = Field(..., title="Tag", description="The tag to attach", json_schema_extra={"x-resource-type": "intercom_tag", "x-dynamic-options": {"field_name": "tag_id", "placeholder": "Select a tag...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste tag ID"}})


class IntercomUntagContactConfig(BaseModel):
    operation: Literal["untag_contact"] = Field("untag_contact", json_schema_extra={"const": "untag_contact", "ui:hidden": True, "x-category": "Contacts", "x-is-trigger": False, "x-display-name": "Untag Contact"}, title="Untag Contact")
    contact_id: str = Field(..., title="Contact ID", description="The Intercom contact ID", json_schema_extra=_CONTACT_ID_OPTS)
    tag_id: str = Field(..., title="Tag", description="The tag to remove", json_schema_extra={"x-resource-type": "intercom_tag", "x-dynamic-options": {"field_name": "tag_id", "placeholder": "Select a tag...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste tag ID"}})


# ============================================================================
# Conversation Operation Configs
# ============================================================================


class IntercomCreateConversationConfig(BaseModel):
    """Start a conversation from a contact."""

    operation: Literal["create_conversation"] = Field(
        "create_conversation",
        json_schema_extra={
            "const": "create_conversation",
            "ui:hidden": True,
            "x-category": "Conversations",
            "x-is-trigger": False,
            "x-display-name": "Create Conversation",
        },
        title="Create Conversation",
    )
    contact_id: str = Field(
        ..., title="From Contact ID", description="The contact starting the conversation"
    )
    body: str = Field(
        ...,
        title="Message Body",
        description="The opening message body (HTML supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class IntercomGetConversationConfig(BaseModel):
    """Retrieve a conversation with its parts."""

    operation: Literal["get_conversation"] = Field(
        "get_conversation",
        json_schema_extra={
            "const": "get_conversation",
            "ui:hidden": True,
            "x-category": "Conversations",
            "x-is-trigger": False,
            "x-display-name": "Get Conversation",
        },
        title="Get Conversation",
    )
    conversation_id: str = Field(..., title="Conversation ID", description="The conversation ID")


class IntercomListConversationsConfig(BaseModel):
    """List all conversations."""

    operation: Literal["list_conversations"] = Field(
        "list_conversations",
        json_schema_extra={
            "const": "list_conversations",
            "ui:hidden": True,
            "x-category": "Conversations",
            "x-is-trigger": False,
            "x-display-name": "List Conversations",
        },
        title="List Conversations",
    )
    per_page: Optional[str] = Field(
        "20", title="Per Page", description="Number of conversations per page (max 150)"
    )
    starting_after: Optional[str] = Field(
        None, title="Starting After", description="Pagination cursor for the next page"
    )


class IntercomSearchConversationsConfig(BaseModel):
    """Search conversations by filters (JSON query body)."""

    operation: Literal["search_conversations"] = Field(
        "search_conversations",
        json_schema_extra={
            "const": "search_conversations",
            "ui:hidden": True,
            "x-category": "Conversations",
            "x-is-trigger": False,
            "x-display-name": "Search Conversations",
        },
        title="Search Conversations",
    )
    query: str = Field(
        ...,
        title="Query (JSON)",
        description='Intercom search query object, e.g. {"field":"open","operator":"=","value":true}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    per_page: Optional[str] = Field(
        "20", title="Per Page", description="Number of results per page"
    )


class IntercomReplyConversationConfig(BaseModel):
    """Add an admin or user reply (comment or note) to a conversation."""

    operation: Literal["reply_conversation"] = Field(
        "reply_conversation",
        json_schema_extra={
            "const": "reply_conversation",
            "ui:hidden": True,
            "x-category": "Conversations",
            "x-is-trigger": False,
            "x-display-name": "Reply to Conversation",
        },
        title="Reply to Conversation",
    )
    conversation_id: str = Field(
        ...,
        title="Conversation ID",
        description="The conversation to reply to. When triggered by a conversation event, use the conversation_id from that event.",
    )
    message_type: str = Field(
        "comment",
        title="Message Type",
        description="Type of reply",
        json_schema_extra={
            "enum": ["comment", "note"],
            "enumNames": ["Comment (visible)", "Note (internal)"],
            "x-enum-searchable": True,
        },
    )
    reply_type: str = Field(
        "admin",
        title="Reply As",
        description="Whether an admin or the user replies",
        json_schema_extra={
            "enum": ["admin", "user"],
            "enumNames": ["Admin", "User"],
            "x-enum-searchable": True,
        },
    )
    body: str = Field(
        ...,
        title="Reply Body",
        description="The reply text (HTML supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    admin_id: Optional[str] = Field(
        None,
        title="Admin",
        description="Admin authoring the reply (required when replying as admin)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "admin_id",
                "placeholder": "Select an admin...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste admin ID",
            }
        },
    )
    contact_id: Optional[str] = Field(
        None, title="Contact ID", description="Contact authoring the reply (required when replying as user)"
    )


class IntercomManageConversationConfig(BaseModel):
    """Assign, snooze, open, or close a conversation."""

    operation: Literal["manage_conversation"] = Field(
        "manage_conversation",
        json_schema_extra={
            "const": "manage_conversation",
            "ui:hidden": True,
            "x-category": "Conversations",
            "x-is-trigger": False,
            "x-display-name": "Manage Conversation",
        },
        title="Manage Conversation",
    )
    conversation_id: str = Field(..., title="Conversation ID", description="The conversation to manage")
    message_type: str = Field(
        "close",
        title="Action",
        description="The management action to run",
        json_schema_extra={
            "enum": ["assignment", "snoozed", "open", "close"],
            "enumNames": ["Assign", "Snooze", "Open", "Close"],
            "x-enum-searchable": True,
        },
    )
    admin_id: Optional[str] = Field(
        None,
        title="Admin",
        description="Admin performing the action",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "admin_id",
                "placeholder": "Select an admin...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste admin ID",
            }
        },
    )
    assignee_id: Optional[str] = Field(
        None, title="Assignee ID", description="Admin or team ID to assign to (for the assignment action)"
    )
    snoozed_until: Optional[str] = Field(
        None, title="Snoozed Until", description="UNIX timestamp to snooze until (for the snooze action)"
    )


class IntercomTagConversationConfig(BaseModel):
    """Attach a tag to a conversation."""

    operation: Literal["tag_conversation"] = Field(
        "tag_conversation",
        json_schema_extra={
            "const": "tag_conversation",
            "ui:hidden": True,
            "x-category": "Conversations",
            "x-is-trigger": False,
            "x-display-name": "Tag Conversation",
        },
        title="Tag Conversation",
    )
    conversation_id: str = Field(..., title="Conversation ID", description="The conversation to tag")
    tag_id: str = Field(
        ...,
        title="Tag",
        description="The tag to attach",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "tag_id",
                "placeholder": "Select a tag...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste tag ID",
            }
        },
    )
    admin_id: str = Field(
        ...,
        title="Admin",
        description="Admin applying the tag",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "admin_id",
                "placeholder": "Select an admin...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste admin ID",
            }
        },
    )


class IntercomUntagConversationConfig(BaseModel):
    operation: Literal["untag_conversation"] = Field("untag_conversation", json_schema_extra={"const": "untag_conversation", "ui:hidden": True, "x-category": "Conversations", "x-is-trigger": False, "x-display-name": "Untag Conversation"}, title="Untag Conversation")
    conversation_id: str = Field(..., title="Conversation ID", description="The conversation to untag")
    tag_id: str = Field(..., title="Tag", description="The tag to remove", json_schema_extra={"x-resource-type": "intercom_tag", "x-dynamic-options": {"field_name": "tag_id", "placeholder": "Select a tag...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste tag ID"}})
    admin_id: str = Field(..., title="Admin", description="Admin removing the tag", json_schema_extra={"x-dynamic-options": {"field_name": "admin_id", "placeholder": "Select an admin...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste admin ID"}})


# ============================================================================
# Ticket Operation Configs
# ============================================================================


class IntercomCreateTicketConfig(BaseModel):
    """Create a support, back-office, or tracker ticket."""

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
    ticket_type_id: str = Field(
        ..., title="Ticket Type", description="The ID of the ticket type to create",
        json_schema_extra=_TICKET_TYPE_ID_OPTS,
    )
    contact_id: str = Field(
        ..., title="Contact ID", description="The contact the ticket is for",
        json_schema_extra=_CONTACT_ID_OPTS,
    )
    title: Optional[str] = Field(None, title="Title", description="The ticket title (a ticket attribute)")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="The ticket description (a ticket attribute)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    ticket_attributes: Optional[str] = Field(
        None,
        title="Ticket Attributes (JSON)",
        description="JSON object of additional ticket attributes",
        json_schema_extra={"ui:widget": "textarea"},
    )


class IntercomGetTicketConfig(BaseModel):
    """Retrieve a ticket by ID."""

    operation: Literal["get_ticket"] = Field(
        "get_ticket",
        json_schema_extra={
            "const": "get_ticket",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Get Ticket",
        },
        title="Get Ticket",
    )
    ticket_id: str = Field(..., title="Ticket ID", description="The ticket ID")


class IntercomUpdateTicketConfig(BaseModel):
    """Update ticket state, attributes, or assignee."""

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
    ticket_id: str = Field(..., title="Ticket ID", description="The ticket ID to update")
    state: Optional[str] = Field(
        None,
        title="State",
        description="New ticket state",
        json_schema_extra={
            "enum": ["", "submitted", "in_progress", "waiting_on_customer", "resolved"],
            "enumNames": ["Unchanged", "Submitted", "In Progress", "Waiting on Customer", "Resolved"],
            "x-enum-searchable": True,
        },
    )
    assignee_id: Optional[str] = Field(
        None, title="Assignee ID", description="Admin or team ID to assign the ticket to"
    )
    ticket_attributes: Optional[str] = Field(
        None,
        title="Ticket Attributes (JSON)",
        description="JSON object of ticket attributes to update",
        json_schema_extra={"ui:widget": "textarea"},
    )


class IntercomSearchTicketsConfig(BaseModel):
    """Search tickets by filters (JSON query body)."""

    operation: Literal["search_tickets"] = Field(
        "search_tickets",
        json_schema_extra={
            "const": "search_tickets",
            "ui:hidden": True,
            "x-category": "Tickets",
            "x-is-trigger": False,
            "x-display-name": "Search Tickets",
        },
        title="Search Tickets",
    )
    query: str = Field(
        ...,
        title="Query (JSON)",
        description='Intercom search query object, e.g. {"field":"state","operator":"=","value":"submitted"}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    per_page: Optional[str] = Field(
        "20", title="Per Page", description="Number of results per page"
    )


class IntercomListTicketTypesConfig(BaseModel):
    operation: Literal["list_ticket_types"] = Field("list_ticket_types", json_schema_extra={"const": "list_ticket_types", "ui:hidden": True, "x-category": "Tickets", "x-is-trigger": False, "x-display-name": "List Ticket Types"}, title="List Ticket Types")


class IntercomReplyTicketConfig(BaseModel):
    operation: Literal["reply_ticket"] = Field("reply_ticket", json_schema_extra={"const": "reply_ticket", "ui:hidden": True, "x-category": "Tickets", "x-is-trigger": False, "x-display-name": "Reply to Ticket"}, title="Reply to Ticket")
    ticket_id: str = Field(..., title="Ticket ID", description="The ticket ID to reply to")
    message_type: str = Field("comment", title="Message Type", description="Type of reply", json_schema_extra={"enum": ["comment", "note"], "enumNames": ["Comment (visible)", "Note (internal)"], "x-enum-searchable": True})
    admin_id: str = Field(..., title="Admin", description="Admin authoring the reply", json_schema_extra={"x-dynamic-options": {"field_name": "admin_id", "placeholder": "Select an admin...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste admin ID"}})
    body: str = Field(..., title="Reply Body", description="The reply text (HTML supported)", json_schema_extra={"ui:widget": "textarea"})


# ============================================================================
# Company Operation Configs
# ============================================================================


class IntercomCreateCompanyConfig(BaseModel):
    """Create or upsert a company by company_id."""

    operation: Literal["create_company"] = Field(
        "create_company",
        json_schema_extra={
            "const": "create_company",
            "ui:hidden": True,
            "x-category": "Companies",
            "x-is-trigger": False,
            "x-display-name": "Create or Update Company",
            "x-creates-resource": True,
            "x-resource-type": "intercom_company",
            "x-resource-id-path": "data.id",
        },
        title="Create or Update Company",
    )
    company_id: str = Field(
        ..., title="Company ID", description="Your unique identifier for the company (upserts on it)"
    )
    name: Optional[str] = Field(None, title="Name", description="The company name")
    plan: Optional[str] = Field(None, title="Plan", description="The company's plan name")
    custom_attributes: Optional[str] = Field(
        None,
        title="Custom Attributes (JSON)",
        description="JSON object of custom attributes",
        json_schema_extra={"ui:widget": "textarea"},
    )


class IntercomGetCompanyConfig(BaseModel):
    """Retrieve a company by its Intercom ID."""

    operation: Literal["get_company"] = Field(
        "get_company",
        json_schema_extra={
            "const": "get_company",
            "ui:hidden": True,
            "x-category": "Companies",
            "x-is-trigger": False,
            "x-display-name": "Get Company",
        },
        title="Get Company",
    )
    company_id: str = Field(..., title="Company ID", description="The Intercom company ID", json_schema_extra=_COMPANY_ID_OPTS)


class IntercomListCompanyContactsConfig(BaseModel):
    """List contacts attached to a company."""

    operation: Literal["list_company_contacts"] = Field(
        "list_company_contacts",
        json_schema_extra={
            "const": "list_company_contacts",
            "ui:hidden": True,
            "x-category": "Companies",
            "x-is-trigger": False,
            "x-display-name": "List Company Contacts",
        },
        title="List Company Contacts",
    )
    company_id: str = Field(..., title="Company ID", description="The Intercom company ID", json_schema_extra=_COMPANY_ID_OPTS)


class IntercomListCompaniesConfig(BaseModel):
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"const": "list_companies", "ui:hidden": True, "x-category": "Companies", "x-is-trigger": False, "x-display-name": "List Companies"}, title="List Companies")
    per_page: Optional[str] = Field("50", title="Per Page", description="Number of companies per page (max 150)")


class IntercomDeleteCompanyConfig(BaseModel):
    operation: Literal["delete_company"] = Field("delete_company", json_schema_extra={"const": "delete_company", "ui:hidden": True, "x-category": "Companies", "x-is-trigger": False, "x-display-name": "Delete Company"}, title="Delete Company")
    company_id: str = Field(..., title="Company ID", description="The Intercom company ID to delete", json_schema_extra=_COMPANY_ID_OPTS)


# ============================================================================
# Messaging & Events Operation Configs
# ============================================================================


class IntercomSendMessageConfig(BaseModel):
    """Send an in-app or email message from an admin to a contact."""

    operation: Literal["send_message"] = Field(
        "send_message",
        json_schema_extra={
            "const": "send_message",
            "ui:hidden": True,
            "x-category": "Messaging",
            "x-is-trigger": False,
            "x-display-name": "Send Message",
        },
        title="Send Message",
    )
    message_type: str = Field(
        "inapp",
        title="Message Type",
        description="Whether to send an in-app or email message",
        json_schema_extra={
            "enum": ["inapp", "email"],
            "enumNames": ["In-App", "Email"],
            "x-enum-searchable": True,
        },
    )
    contact_id: str = Field(..., title="To Contact ID", description="The recipient contact ID", json_schema_extra=_CONTACT_ID_OPTS)
    admin_id: str = Field(
        ...,
        title="From Admin",
        description="The admin sending the message",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "admin_id",
                "placeholder": "Select an admin...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste admin ID",
            }
        },
    )
    body: str = Field(
        ...,
        title="Body",
        description="The message body (HTML supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    subject: Optional[str] = Field(
        None, title="Subject", description="Email subject line (required for email messages)"
    )


class IntercomSubmitEventConfig(BaseModel):
    """Submit a custom data event for a contact (analytics / triggers)."""

    operation: Literal["submit_event"] = Field(
        "submit_event",
        json_schema_extra={
            "const": "submit_event",
            "ui:hidden": True,
            "x-category": "Messaging",
            "x-is-trigger": False,
            "x-display-name": "Submit Data Event",
        },
        title="Submit Data Event",
    )
    event_name: str = Field(..., title="Event Name", description="The name of the event")
    contact_id: Optional[str] = Field(
        None, title="Contact ID", description="The Intercom contact ID (or use email / external ID)"
    )
    email: Optional[str] = Field(
        None, title="Email", description="Contact email (alternative to contact ID)"
    )
    user_external_id: Optional[str] = Field(
        None, title="External ID", description="Contact external ID (alternative to contact ID)"
    )
    metadata: Optional[str] = Field(
        None,
        title="Metadata (JSON)",
        description="JSON object of event metadata",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Tag / Admin / Team / Schema Operation Configs
# ============================================================================


class IntercomListTagsConfig(BaseModel):
    """List all tags in the workspace."""

    operation: Literal["list_tags"] = Field(
        "list_tags",
        json_schema_extra={
            "const": "list_tags",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "List Tags",
        },
        title="List Tags",
    )


class IntercomCreateTagConfig(BaseModel):
    """Create a tag (or update an existing tag by name)."""

    operation: Literal["create_tag"] = Field(
        "create_tag",
        json_schema_extra={
            "const": "create_tag",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "Create Tag",
            "x-creates-resource": True,
            "x-resource-type": "intercom_tag",
            "x-resource-id-path": "data.id",
        },
        title="Create Tag",
    )
    name: str = Field(..., title="Tag Name", description="The name of the tag to create or update")


class IntercomDeleteTagConfig(BaseModel):
    operation: Literal["delete_tag"] = Field("delete_tag", json_schema_extra={"const": "delete_tag", "ui:hidden": True, "x-category": "Workspace", "x-is-trigger": False, "x-display-name": "Delete Tag"}, title="Delete Tag")
    tag_id: str = Field(..., title="Tag", description="The tag to delete", json_schema_extra={"x-resource-type": "intercom_tag", "x-dynamic-options": {"field_name": "tag_id", "placeholder": "Select a tag...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste tag ID"}})


class IntercomListAdminsConfig(BaseModel):
    """List all admins (teammates) in the workspace."""

    operation: Literal["list_admins"] = Field(
        "list_admins",
        json_schema_extra={
            "const": "list_admins",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "List Admins",
        },
        title="List Admins",
    )


class IntercomListTeamsConfig(BaseModel):
    """List all teams in the workspace."""

    operation: Literal["list_teams"] = Field(
        "list_teams",
        json_schema_extra={
            "const": "list_teams",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "List Teams",
        },
        title="List Teams",
    )


class IntercomListDataAttributesConfig(BaseModel):
    """List custom/standard data attributes (schema)."""

    operation: Literal["list_data_attributes"] = Field(
        "list_data_attributes",
        json_schema_extra={
            "const": "list_data_attributes",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "List Data Attributes",
        },
        title="List Data Attributes",
    )
    model: Optional[str] = Field(
        None,
        title="Model",
        description="Filter attributes by the model they belong to",
        json_schema_extra={
            "enum": ["", "contact", "company", "conversation"],
            "enumNames": ["All", "Contact", "Company", "Conversation"],
            "x-enum-searchable": True,
        },
    )


class IntercomListSegmentsConfig(BaseModel):
    """List all segments."""

    operation: Literal["list_segments"] = Field(
        "list_segments",
        json_schema_extra={
            "const": "list_segments",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "List Segments",
        },
        title="List Segments",
    )


# ============================================================================
# Article (Help Center) Operation Configs
# ============================================================================


class IntercomListArticlesConfig(BaseModel):
    operation: Literal["list_articles"] = Field("list_articles", json_schema_extra={"const": "list_articles", "ui:hidden": True, "x-category": "Help Center", "x-is-trigger": False, "x-display-name": "List Articles"}, title="List Articles")
    per_page: Optional[str] = Field("20", title="Per Page", description="Number of articles per page")


class IntercomGetArticleConfig(BaseModel):
    operation: Literal["get_article"] = Field("get_article", json_schema_extra={"const": "get_article", "ui:hidden": True, "x-category": "Help Center", "x-is-trigger": False, "x-display-name": "Get Article"}, title="Get Article")
    article_id: str = Field(..., title="Article ID", description="The Intercom article ID")


class IntercomCreateArticleConfig(BaseModel):
    operation: Literal["create_article"] = Field("create_article", json_schema_extra={"const": "create_article", "ui:hidden": True, "x-category": "Help Center", "x-is-trigger": False, "x-display-name": "Create Article"}, title="Create Article")
    title: str = Field(..., title="Title", description="The article title")
    body: Optional[str] = Field(None, title="Body (HTML)", description="The article body in HTML", json_schema_extra={"ui:widget": "textarea"})
    author_id: Optional[str] = Field(None, title="Author Admin", description="The admin who authors the article", json_schema_extra={"x-dynamic-options": {"field_name": "admin_id", "placeholder": "Select an admin...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste admin ID"}})
    state: Optional[str] = Field("draft", title="State", description="Article state", json_schema_extra={"enum": ["draft", "published"], "enumNames": ["Draft", "Published"], "x-enum-searchable": True})


class IntercomUpdateArticleConfig(BaseModel):
    operation: Literal["update_article"] = Field("update_article", json_schema_extra={"const": "update_article", "ui:hidden": True, "x-category": "Help Center", "x-is-trigger": False, "x-display-name": "Update Article"}, title="Update Article")
    article_id: str = Field(..., title="Article ID", description="The article ID to update")
    title: Optional[str] = Field(None, title="Title", description="New article title")
    body: Optional[str] = Field(None, title="Body (HTML)", description="New article body in HTML", json_schema_extra={"ui:widget": "textarea"})
    state: Optional[str] = Field(None, title="State", description="New article state", json_schema_extra={"enum": ["", "draft", "published"], "enumNames": ["Unchanged", "Draft", "Published"], "x-enum-searchable": True})


class IntercomDeleteArticleConfig(BaseModel):
    operation: Literal["delete_article"] = Field("delete_article", json_schema_extra={"const": "delete_article", "ui:hidden": True, "x-category": "Help Center", "x-is-trigger": False, "x-display-name": "Delete Article"}, title="Delete Article")
    article_id: str = Field(..., title="Article ID", description="The article ID to delete")


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class IntercomConversationEventConfig(BaseModel):
    """Trigger: fire when an Intercom conversation event occurs.

    Add the generated webhook URL as a separate endpoint in Intercom Developer
    Hub > Configure > Webhooks and subscribe the conversation.* topics you need.
    Each domain trigger gets its own URL, so topics are isolated per trigger.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_conversation_event"] = Field(
        "on_conversation_event",
        json_schema_extra={
            "const": "on_conversation_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Conversation Event",
        },
        title="On Conversation Event",
    )
    event_types: str = Field(
        "*",
        title="Trigger On",
        description=(
            "Which conversation event fires this workflow. Choose \"All conversation "
            "events\" to fire on every conversation.* topic, or pick one specific "
            "event (e.g. conversation.user.created, conversation.admin.closed). "
            "Subscribe the matching topics at the URL above in Developer Hub."
        ),
        json_schema_extra={
            "enum": [c for c, _ in INTERCOM_CONVERSATION_TOPICS],
            "enumNames": [l for _, l in INTERCOM_CONVERSATION_TOPICS],
            "x-enum-searchable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Add this URL in Intercom Developer Hub > Configure > Webhooks and subscribe conversation.* topics",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )
    signing_secret: Optional[str] = Field(
        default=None,
        title="Client Secret",
        description="Your app's Client Secret (Developer Hub > Basic Info) for X-Hub-Signature verification",
        json_schema_extra={"ui:widget": "password"},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})


class IntercomContactEventConfig(BaseModel):
    """Trigger: fire when an Intercom contact event occurs.

    Add the generated webhook URL in Developer Hub > Configure > Webhooks and
    subscribe contact.* and/or visitor.* topics.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_contact_event"] = Field(
        "on_contact_event",
        json_schema_extra={
            "const": "on_contact_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Contact Event",
        },
        title="On Contact Event",
    )
    event_types: str = Field(
        "*",
        title="Trigger On",
        description=(
            "Which contact event fires this workflow. Choose \"All contact events\" "
            "to fire on any contact.* / visitor.signed_up topic, or pick one "
            "(e.g. contact.user.created, contact.archived). Subscribe matching "
            "topics at the URL above in Developer Hub."
        ),
        json_schema_extra={
            "enum": [c for c, _ in INTERCOM_CONTACT_TOPICS],
            "enumNames": [l for _, l in INTERCOM_CONTACT_TOPICS],
            "x-enum-searchable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Add this URL in Intercom Developer Hub > Configure > Webhooks and subscribe contact.* topics",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )
    signing_secret: Optional[str] = Field(
        default=None,
        title="Client Secret",
        description="Your app's Client Secret (Developer Hub > Basic Info) for X-Hub-Signature verification",
        json_schema_extra={"ui:widget": "password"},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})


class IntercomTicketEventConfig(BaseModel):
    """Trigger: fire when an Intercom ticket event occurs.

    Add the generated webhook URL in Developer Hub > Configure > Webhooks and
    subscribe ticket.* topics.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_ticket_event"] = Field(
        "on_ticket_event",
        json_schema_extra={
            "const": "on_ticket_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Ticket Event",
        },
        title="On Ticket Event",
    )
    event_types: str = Field(
        "*",
        title="Trigger On",
        description=(
            "Which ticket event fires this workflow. Choose \"All ticket events\" "
            "to fire on any ticket.* topic, or pick one (e.g. ticket.created, "
            "ticket.resolved). Subscribe matching topics at the URL above in "
            "Developer Hub."
        ),
        json_schema_extra={
            "enum": [c for c, _ in INTERCOM_TICKET_TOPICS],
            "enumNames": [l for _, l in INTERCOM_TICKET_TOPICS],
            "x-enum-searchable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Add this URL in Intercom Developer Hub > Configure > Webhooks and subscribe ticket.* topics",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )
    signing_secret: Optional[str] = Field(
        default=None,
        title="Client Secret",
        description="Your app's Client Secret (Developer Hub > Basic Info) for X-Hub-Signature verification",
        json_schema_extra={"ui:widget": "password"},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})


class IntercomCompanyEventConfig(BaseModel):
    """Trigger: fire when an Intercom company, admin, or workspace event occurs.

    Add the generated webhook URL in Developer Hub > Configure > Webhooks and
    subscribe company.* and/or admin.* topics.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_company_event"] = Field(
        "on_company_event",
        json_schema_extra={
            "const": "on_company_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Company / Workspace Event",
        },
        title="On Company / Workspace Event",
    )
    event_types: str = Field(
        "*",
        title="Trigger On",
        description=(
            "Which company or workspace event fires this workflow. Choose \"All "
            "company & workspace events\" to fire on any company.* / admin.* / "
            "event.created topic, or pick one (e.g. company.created). Subscribe "
            "matching topics at the URL above in Developer Hub."
        ),
        json_schema_extra={
            "enum": [c for c, _ in INTERCOM_COMPANY_TOPICS],
            "enumNames": [l for _, l in INTERCOM_COMPANY_TOPICS],
            "x-enum-searchable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Add this URL in Intercom Developer Hub > Configure > Webhooks and subscribe company.* / admin.* topics",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )
    signing_secret: Optional[str] = Field(
        default=None,
        title="Client Secret",
        description="Your app's Client Secret (Developer Hub > Basic Info) for X-Hub-Signature verification",
        json_schema_extra={"ui:widget": "password"},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


IntercomConfig = Annotated[
    Union[
        IntercomCreateContactConfig,
        IntercomGetContactConfig,
        IntercomUpdateContactConfig,
        IntercomListContactsConfig,
        IntercomSearchContactsConfig,
        IntercomArchiveContactConfig,
        IntercomMergeContactsConfig,
        IntercomCreateNoteConfig,
        IntercomUnarchiveContactConfig,
        IntercomDeleteContactConfig,
        IntercomListContactNotesConfig,
        IntercomListContactCompaniesConfig,
        IntercomAttachContactToCompanyConfig,
        IntercomDetachContactFromCompanyConfig,
        IntercomTagContactConfig,
        IntercomUntagContactConfig,
        IntercomCreateConversationConfig,
        IntercomGetConversationConfig,
        IntercomListConversationsConfig,
        IntercomSearchConversationsConfig,
        IntercomReplyConversationConfig,
        IntercomManageConversationConfig,
        IntercomTagConversationConfig,
        IntercomUntagConversationConfig,
        IntercomCreateTicketConfig,
        IntercomGetTicketConfig,
        IntercomUpdateTicketConfig,
        IntercomSearchTicketsConfig,
        IntercomListTicketTypesConfig,
        IntercomReplyTicketConfig,
        IntercomCreateCompanyConfig,
        IntercomGetCompanyConfig,
        IntercomListCompanyContactsConfig,
        IntercomListCompaniesConfig,
        IntercomDeleteCompanyConfig,
        IntercomSendMessageConfig,
        IntercomSubmitEventConfig,
        IntercomListTagsConfig,
        IntercomCreateTagConfig,
        IntercomDeleteTagConfig,
        IntercomListAdminsConfig,
        IntercomListTeamsConfig,
        IntercomListDataAttributesConfig,
        IntercomListSegmentsConfig,
        IntercomListArticlesConfig,
        IntercomGetArticleConfig,
        IntercomCreateArticleConfig,
        IntercomUpdateArticleConfig,
        IntercomDeleteArticleConfig,
        IntercomConversationEventConfig,
        IntercomContactEventConfig,
        IntercomTicketEventConfig,
        IntercomCompanyEventConfig,
    ],
    Discriminator("operation"),
]


class IntercomNodeConfig(NodeConfig[IntercomConfig, IntercomCredential]):
    """Full configuration for the Intercom node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _parse_json_field(value: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse a user-supplied JSON object field. Raises ValueError on bad JSON."""
    if not value:
        return None
    import json

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object")
    return parsed


def _base_url(credential: Dict[str, Any]) -> str:
    region = (credential or {}).get("region") or "us"
    return INTERCOM_REGION_BASES.get(region, INTERCOM_REGION_BASES["us"])


async def _intercom_request(
    access_token: str,
    base_url: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Intercom request and return a structured result."""
    url = f"{base_url}{endpoint}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Intercom-Version": INTERCOM_API_VERSION,
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
                    errors = err.get("errors") if isinstance(err, dict) else None
                    if errors and isinstance(errors, list):
                        message = "; ".join(
                            e.get("message", str(e)) if isinstance(e, dict) else str(e)
                            for e in errors
                        )
                    else:
                        message = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[IntercomNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204 or not response.text:
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
            logger.error(f"[IntercomNode] Request failed ({action_name}): {msg}")
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


class IntercomNode(WorkflowNode):
    """Intercom customer messaging automation node."""

    edit_examples = [
        "Create or update an Intercom contact when a user signs up",
        "Reply to an open Intercom conversation as an admin",
        "Create a support ticket for a contact",
        "Send an in-app message to a user",
        "Trigger a workflow when a new Intercom conversation is created",
    ]

    scope_registry = INTERCOM_SCOPES
    connection_evidence = ConnectionEvidence(
        field="admin_id",
        noun="teammates",
    )

    @classmethod
    def get_config_model(cls):
        return IntercomNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (admins, tags)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name not in ("admin_id", "tag_id", "contact_id", "company_id", "ticket_type_id"):
            return {"options": []}
        if not credential_data:
            return {"options": []}
        access_token = credential_data.get("access_token")
        base_url = _base_url(credential_data)

        if field_name == "admin_id":
            result = await _intercom_request(
                access_token, base_url, "GET", "/admins", action_name="list_admins"
            )
            if result.get("status") != "success":
                return {"options": []}
            admins = (result.get("data") or {}).get("admins") or []
            options = []
            for a in admins:
                if not isinstance(a, dict):
                    continue
                aid = a.get("id")
                name = a.get("name") or a.get("email") or f"Admin {aid}"
                if aid is not None:
                    options.append({"label": str(name), "value": str(aid)})
            return {"options": options}

        if field_name == "tag_id":
            result = await _intercom_request(
                access_token, base_url, "GET", "/tags", action_name="list_tags"
            )
            if result.get("status") != "success":
                return {"options": []}
            tags = (result.get("data") or {}).get("data") or []
            options = []
            for t in tags:
                if not isinstance(t, dict):
                    continue
                tid = t.get("id")
                name = t.get("name") or f"Tag {tid}"
                if tid is not None:
                    options.append({"label": str(name), "value": str(tid)})
            return {"options": options}

        if field_name == "contact_id":
            if search:
                body: Dict[str, Any] = {
                    "query": {
                        "operator": "OR",
                        "value": [
                            {"field": "email", "operator": "CONTAINS", "value": search},
                            {"field": "name", "operator": "CONTAINS", "value": search},
                        ],
                    },
                    "pagination": {"per_page": 20},
                }
                result = await _intercom_request(
                    access_token, base_url, "POST", "/contacts/search",
                    json_body=body, action_name="search_contacts"
                )
            else:
                result = await _intercom_request(
                    access_token, base_url, "GET", "/contacts?per_page=50", action_name="list_contacts"
                )
            if result.get("status") != "success":
                return {"options": []}
            contacts = (result.get("data") or {}).get("data") or []
            options = []
            for c in contacts:
                if not isinstance(c, dict):
                    continue
                cid = c.get("id")
                name = c.get("name") or c.get("email") or f"Contact {cid}"
                email = c.get("email", "")
                label = f"{name} ({email})" if email and email != name else str(name)
                if cid is not None:
                    options.append({"label": label, "value": str(cid)})
            return {"options": options}

        if field_name == "company_id":
            url = f"/companies?per_page=50{('&name=' + search) if search else ''}"
            result = await _intercom_request(
                access_token, base_url, "GET", url, action_name="list_companies"
            )
            if result.get("status") != "success":
                return {"options": []}
            companies = (result.get("data") or {}).get("data") or []
            options = []
            for co in companies:
                if not isinstance(co, dict):
                    continue
                coid = co.get("id")
                name = co.get("name") or f"Company {coid}"
                if coid is not None:
                    options.append({"label": str(name), "value": str(coid)})
            return {"options": options}

        # ticket_type_id
        result = await _intercom_request(
            access_token, base_url, "GET", "/ticket_types", action_name="list_ticket_types"
        )
        if result.get("status") != "success":
            return {"options": []}
        ticket_types = (result.get("data") or {}).get("ticket_types") or []
        options = []
        for tt in ticket_types:
            if not isinstance(tt, dict):
                continue
            ttid = tt.get("id")
            name = tt.get("name") or f"Type {ttid}"
            if ttid is not None:
                options.append({"label": str(name), "value": str(ttid)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Webhook helpers
    # ------------------------------------------------------------------
    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify Intercom's X-Hub-Signature (HMAC-SHA1 of the body using the client secret)."""
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored — accept (verification not configured)
        sent = headers.get("x-hub-signature") or headers.get("X-Hub-Signature")
        if not sent:
            return False
        expected = "sha1=" + hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
        return hmac.compare_digest(expected, sent)

    @staticmethod
    def _inbound_topic(payload: Dict[str, Any]) -> Optional[str]:
        """Extract the Intercom topic from an inbound webhook delivery.

        Intercom puts the topic at the top level as ``topic``; some deliveries
        carry it as ``data.item.type`` only — prefer the explicit field.
        """
        topic = (payload or {}).get("topic")
        return topic if isinstance(topic, str) else None

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Skip deliveries whose topic isn't the selected one.

        Intercom subscriptions deliver every chosen topic to the same URL with no
        per-subscription filter, so a node that wants only one event must filter
        here. ``event_types == "*"`` (or unset) fires on any topic; ``ping`` (the
        subscription health check) is always allowed so verification still works.
        """
        selected = (config or {}).get("event_types") or "*"
        if selected == "*":
            return True
        topic = cls._inbound_topic(payload)
        if topic is None:
            return True  # can't classify — don't silently drop
        if topic == "ping":
            return True
        return topic == selected

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Intercom conversation webhook → the agent's user turn + a per-conversation
        key. Only conversation.* events (``data.item`` is a conversation) are handled
        here; contact/company/ticket topics fall through to the raw-JSON default. The
        conversation id in the text doubles as the ``conversation_id`` the
        ``reply_conversation`` tool needs to answer the right thread."""
        data = output.get("data") if isinstance(output.get("data"), dict) else {}
        item = data.get("item") if isinstance(data.get("item"), dict) else {}
        if item.get("type") != "conversation" or not item.get("id"):
            return super().resolve_agent_event(output)
        conv_id = item["id"]

        # Latest message: newest conversation part carrying a body, else the
        # opening source message. Bodies are raw Intercom HTML — surfaced as-is.
        parts_wrap = item.get("conversation_parts")
        parts = parts_wrap.get("conversation_parts") if isinstance(parts_wrap, dict) else None
        part = None
        if isinstance(parts, list):
            part = next((p for p in reversed(parts) if isinstance(p, dict) and p.get("body")), None)
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        msg = part or source
        author = msg.get("author") if isinstance(msg.get("author"), dict) else {}
        who = author.get("name") or author.get("email") or author.get("type") or "someone"
        body = msg.get("body") or "[no message body]"
        topic = output.get("topic") or "conversation event"
        return {
            "text": (
                f"Intercom {topic} from {who} (conversation {conv_id}):\n{body}\n\n"
                f"To reply, use conversation_id={conv_id} with the reply_conversation tool."
            ),
            "conversation_key": str(conv_id),
        }

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, IntercomNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        _TRIGGER_OPS = {
            "on_conversation_event",
            "on_contact_event",
            "on_ticket_event",
            "on_company_event",
        }
        if op.operation in _TRIGGER_OPS:
            return {
                "status": "success",
                "action": op.operation,
                "data": {
                    **inputs,
                    "webhook_url": op.webhook_url,
                    "event_types": op.event_types,
                },
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Intercom Access Token.")
        access_token = credentials.access_token
        base_url = INTERCOM_REGION_BASES.get(
            getattr(credentials, "region", "us") or "us", INTERCOM_REGION_BASES["us"]
        )

        handlers = {
            "create_contact": self._create_contact,
            "get_contact": self._get_contact,
            "update_contact": self._update_contact,
            "list_contacts": self._list_contacts,
            "search_contacts": self._search_contacts,
            "archive_contact": self._archive_contact,
            "merge_contacts": self._merge_contacts,
            "create_note": self._create_note,
            "unarchive_contact": self._unarchive_contact,
            "delete_contact": self._delete_contact,
            "list_contact_notes": self._list_contact_notes,
            "list_contact_companies": self._list_contact_companies,
            "attach_contact_to_company": self._attach_contact_to_company,
            "detach_contact_from_company": self._detach_contact_from_company,
            "tag_contact": self._tag_contact,
            "untag_contact": self._untag_contact,
            "create_conversation": self._create_conversation,
            "get_conversation": self._get_conversation,
            "list_conversations": self._list_conversations,
            "search_conversations": self._search_conversations,
            "reply_conversation": self._reply_conversation,
            "manage_conversation": self._manage_conversation,
            "tag_conversation": self._tag_conversation,
            "untag_conversation": self._untag_conversation,
            "create_ticket": self._create_ticket,
            "get_ticket": self._get_ticket,
            "update_ticket": self._update_ticket,
            "search_tickets": self._search_tickets,
            "list_ticket_types": self._list_ticket_types,
            "reply_ticket": self._reply_ticket,
            "create_company": self._create_company,
            "get_company": self._get_company,
            "list_company_contacts": self._list_company_contacts,
            "list_companies": self._list_companies,
            "delete_company": self._delete_company,
            "send_message": self._send_message,
            "submit_event": self._submit_event,
            "list_tags": self._list_tags,
            "create_tag": self._create_tag,
            "delete_tag": self._delete_tag,
            "list_admins": self._list_admins,
            "list_teams": self._list_teams,
            "list_data_attributes": self._list_data_attributes,
            "list_segments": self._list_segments,
            "list_articles": self._list_articles,
            "get_article": self._get_article,
            "create_article": self._create_article,
            "update_article": self._update_article,
            "delete_article": self._delete_article,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, access_token, base_url)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Contact handlers
    # ------------------------------------------------------------------
    async def _create_contact(self, c: IntercomCreateContactConfig, token: str, base: str) -> Dict[str, Any]:
        body = {
            "role": c.role,
            "email": c.email,
            "external_id": c.external_id,
            "name": c.name,
            "phone": c.phone,
            "custom_attributes": _parse_json_field(c.custom_attributes),
        }
        return await _intercom_request(token, base, "POST", "/contacts", json_body=body, action_name="create_contact")

    async def _get_contact(self, c: IntercomGetContactConfig, token: str, base: str) -> Dict[str, Any]:
        return await _intercom_request(token, base, "GET", f"/contacts/{c.contact_id}", action_name="get_contact")

    async def _update_contact(self, c: IntercomUpdateContactConfig, token: str, base: str) -> Dict[str, Any]:
        body = {
            "email": c.email,
            "name": c.name,
            "phone": c.phone,
            "custom_attributes": _parse_json_field(c.custom_attributes),
        }
        return await _intercom_request(token, base, "PUT", f"/contacts/{c.contact_id}", json_body=body, action_name="update_contact")

    async def _list_contacts(self, c: IntercomListContactsConfig, token: str, base: str) -> Dict[str, Any]:
        params = {"per_page": c.per_page, "starting_after": c.starting_after}
        return await _intercom_request(token, base, "GET", "/contacts", params=params, action_name="list_contacts")

    async def _search_contacts(self, c: IntercomSearchContactsConfig, token: str, base: str) -> Dict[str, Any]:
        body = {
            "query": _parse_json_field(c.query),
            "pagination": {"per_page": int(c.per_page)} if c.per_page else None,
        }
        return await _intercom_request(token, base, "POST", "/contacts/search", json_body=body, action_name="search_contacts")

    async def _archive_contact(self, c: IntercomArchiveContactConfig, token: str, base: str) -> Dict[str, Any]:
        return await _intercom_request(token, base, "POST", f"/contacts/{c.contact_id}/archive", action_name="archive_contact")

    async def _merge_contacts(self, c: IntercomMergeContactsConfig, token: str, base: str) -> Dict[str, Any]:
        body = {"from": c.contact_id, "into": c.into_contact_id}
        return await _intercom_request(token, base, "POST", f"/contacts/{c.contact_id}/merge", json_body=body, action_name="merge_contacts")

    async def _create_note(self, c: IntercomCreateNoteConfig, token: str, base: str) -> Dict[str, Any]:
        body = {"body": c.body, "admin_id": c.admin_id}
        return await _intercom_request(token, base, "POST", f"/contacts/{c.contact_id}/notes", json_body=body, action_name="create_note")

    async def _unarchive_contact(self, c, token, base):
        return await _intercom_request(token, base, "POST", f"/contacts/{c.contact_id}/unarchive", action_name="unarchive_contact")

    async def _delete_contact(self, c, token, base):
        return await _intercom_request(token, base, "DELETE", f"/contacts/{c.contact_id}", action_name="delete_contact")

    async def _list_contact_notes(self, c, token, base):
        return await _intercom_request(token, base, "GET", f"/contacts/{c.contact_id}/notes", action_name="list_contact_notes")

    async def _list_contact_companies(self, c, token, base):
        return await _intercom_request(token, base, "GET", f"/contacts/{c.contact_id}/companies", action_name="list_contact_companies")

    async def _attach_contact_to_company(self, c, token, base):
        return await _intercom_request(token, base, "POST", f"/contacts/{c.contact_id}/companies", json_body={"id": c.company_id}, action_name="attach_contact_to_company")

    async def _detach_contact_from_company(self, c, token, base):
        return await _intercom_request(token, base, "DELETE", f"/contacts/{c.contact_id}/companies/{c.company_id}", action_name="detach_contact_from_company")

    async def _tag_contact(self, c, token, base):
        return await _intercom_request(token, base, "POST", f"/contacts/{c.contact_id}/tags", json_body={"id": c.tag_id}, action_name="tag_contact")

    async def _untag_contact(self, c, token, base):
        return await _intercom_request(token, base, "DELETE", f"/contacts/{c.contact_id}/tags/{c.tag_id}", action_name="untag_contact")

    # ------------------------------------------------------------------
    # Conversation handlers
    # ------------------------------------------------------------------
    async def _create_conversation(self, c: IntercomCreateConversationConfig, token: str, base: str) -> Dict[str, Any]:
        body = {
            "from": {"type": "user", "id": c.contact_id},
            "body": c.body,
        }
        return await _intercom_request(token, base, "POST", "/conversations", json_body=body, action_name="create_conversation")

    async def _get_conversation(self, c: IntercomGetConversationConfig, token: str, base: str) -> Dict[str, Any]:
        return await _intercom_request(token, base, "GET", f"/conversations/{c.conversation_id}", action_name="get_conversation")

    async def _list_conversations(self, c: IntercomListConversationsConfig, token: str, base: str) -> Dict[str, Any]:
        params = {"per_page": c.per_page, "starting_after": c.starting_after}
        return await _intercom_request(token, base, "GET", "/conversations", params=params, action_name="list_conversations")

    async def _search_conversations(self, c: IntercomSearchConversationsConfig, token: str, base: str) -> Dict[str, Any]:
        body = {
            "query": _parse_json_field(c.query),
            "pagination": {"per_page": int(c.per_page)} if c.per_page else None,
        }
        return await _intercom_request(token, base, "POST", "/conversations/search", json_body=body, action_name="search_conversations")

    async def _reply_conversation(self, c: IntercomReplyConversationConfig, token: str, base: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "message_type": c.message_type,
            "type": c.reply_type,
            "body": c.body,
        }
        if c.reply_type == "admin":
            body["admin_id"] = c.admin_id
        else:
            body["intercom_user_id"] = c.contact_id
        return await _intercom_request(token, base, "POST", f"/conversations/{c.conversation_id}/reply", json_body=body, action_name="reply_conversation")

    async def _manage_conversation(self, c: IntercomManageConversationConfig, token: str, base: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "message_type": c.message_type,
            "type": "admin",
            "admin_id": c.admin_id,
        }
        if c.message_type == "assignment":
            body["assignee_id"] = c.assignee_id
        if c.message_type == "snoozed":
            body["snoozed_until"] = int(c.snoozed_until) if c.snoozed_until else None
        return await _intercom_request(token, base, "POST", f"/conversations/{c.conversation_id}/parts", json_body=body, action_name="manage_conversation")

    async def _tag_conversation(self, c: IntercomTagConversationConfig, token: str, base: str) -> Dict[str, Any]:
        body = {"id": c.tag_id, "admin_id": c.admin_id}
        return await _intercom_request(token, base, "POST", f"/conversations/{c.conversation_id}/tags", json_body=body, action_name="tag_conversation")

    async def _untag_conversation(self, c, token, base):
        body = {"id": c.tag_id, "admin_id": c.admin_id}
        return await _intercom_request(token, base, "DELETE", f"/conversations/{c.conversation_id}/tags/{c.tag_id}", json_body=body, action_name="untag_conversation")

    # ------------------------------------------------------------------
    # Ticket handlers
    # ------------------------------------------------------------------
    async def _create_ticket(self, c: IntercomCreateTicketConfig, token: str, base: str) -> Dict[str, Any]:
        attributes = _parse_json_field(c.ticket_attributes) or {}
        if c.title is not None:
            attributes.setdefault("_default_title_", c.title)
        if c.description is not None:
            attributes.setdefault("_default_description_", c.description)
        body = {
            "ticket_type_id": c.ticket_type_id,
            "contacts": [{"id": c.contact_id}],
            "ticket_attributes": attributes or None,
        }
        return await _intercom_request(token, base, "POST", "/tickets", json_body=body, action_name="create_ticket")

    async def _get_ticket(self, c: IntercomGetTicketConfig, token: str, base: str) -> Dict[str, Any]:
        return await _intercom_request(token, base, "GET", f"/tickets/{c.ticket_id}", action_name="get_ticket")

    async def _update_ticket(self, c: IntercomUpdateTicketConfig, token: str, base: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "state": c.state or None,
            "ticket_attributes": _parse_json_field(c.ticket_attributes),
        }
        if c.assignee_id:
            body["assignment"] = {"assignee_id": c.assignee_id}
        return await _intercom_request(token, base, "PUT", f"/tickets/{c.ticket_id}", json_body=body, action_name="update_ticket")

    async def _search_tickets(self, c: IntercomSearchTicketsConfig, token: str, base: str) -> Dict[str, Any]:
        body = {
            "query": _parse_json_field(c.query),
            "pagination": {"per_page": int(c.per_page)} if c.per_page else None,
        }
        return await _intercom_request(token, base, "POST", "/tickets/search", json_body=body, action_name="search_tickets")

    async def _list_ticket_types(self, c, token, base):
        return await _intercom_request(token, base, "GET", "/ticket_types", action_name="list_ticket_types")

    async def _reply_ticket(self, c, token, base):
        body = {"message_type": c.message_type, "type": "admin", "admin_id": c.admin_id, "body": c.body}
        return await _intercom_request(token, base, "POST", f"/tickets/{c.ticket_id}/reply", json_body=body, action_name="reply_ticket")

    # ------------------------------------------------------------------
    # Company handlers
    # ------------------------------------------------------------------
    async def _create_company(self, c: IntercomCreateCompanyConfig, token: str, base: str) -> Dict[str, Any]:
        body = {
            "company_id": c.company_id,
            "name": c.name,
            "plan": c.plan,
            "custom_attributes": _parse_json_field(c.custom_attributes),
        }
        return await _intercom_request(token, base, "POST", "/companies", json_body=body, action_name="create_company")

    async def _get_company(self, c: IntercomGetCompanyConfig, token: str, base: str) -> Dict[str, Any]:
        return await _intercom_request(token, base, "GET", f"/companies/{c.company_id}", action_name="get_company")

    async def _list_company_contacts(self, c: IntercomListCompanyContactsConfig, token: str, base: str) -> Dict[str, Any]:
        return await _intercom_request(token, base, "GET", f"/companies/{c.company_id}/contacts", action_name="list_company_contacts")

    async def _list_companies(self, c, token, base):
        params = {"per_page": c.per_page}
        return await _intercom_request(token, base, "GET", "/companies", params=params, action_name="list_companies")

    async def _delete_company(self, c, token, base):
        return await _intercom_request(token, base, "DELETE", f"/companies/{c.company_id}", action_name="delete_company")

    # ------------------------------------------------------------------
    # Messaging handlers
    # ------------------------------------------------------------------
    async def _send_message(self, c: IntercomSendMessageConfig, token: str, base: str) -> Dict[str, Any]:
        body = {
            "message_type": c.message_type,
            "subject": c.subject,
            "body": c.body,
            "from": {"type": "admin", "id": c.admin_id},
            "to": {"type": "user", "id": c.contact_id},
        }
        return await _intercom_request(token, base, "POST", "/messages", json_body=body, action_name="send_message")

    async def _submit_event(self, c: IntercomSubmitEventConfig, token: str, base: str) -> Dict[str, Any]:
        body = {
            "event_name": c.event_name,
            "created_at": int(time.time()),
            "id": c.contact_id,
            "email": c.email,
            "user_id": c.user_external_id,
            "metadata": _parse_json_field(c.metadata),
        }
        return await _intercom_request(token, base, "POST", "/events", json_body=body, action_name="submit_event")

    # ------------------------------------------------------------------
    # Tag / Admin / Team / Schema handlers
    # ------------------------------------------------------------------
    async def _list_tags(self, c: IntercomListTagsConfig, token: str, base: str) -> Dict[str, Any]:
        return await _intercom_request(token, base, "GET", "/tags", action_name="list_tags")

    async def _create_tag(self, c: IntercomCreateTagConfig, token: str, base: str) -> Dict[str, Any]:
        return await _intercom_request(token, base, "POST", "/tags", json_body={"name": c.name}, action_name="create_tag")

    async def _delete_tag(self, c, token, base):
        return await _intercom_request(token, base, "DELETE", f"/tags/{c.tag_id}", action_name="delete_tag")

    async def _list_admins(self, c: IntercomListAdminsConfig, token: str, base: str) -> Dict[str, Any]:
        return await _intercom_request(token, base, "GET", "/admins", action_name="list_admins")

    async def _list_teams(self, c: IntercomListTeamsConfig, token: str, base: str) -> Dict[str, Any]:
        return await _intercom_request(token, base, "GET", "/teams", action_name="list_teams")

    async def _list_data_attributes(self, c: IntercomListDataAttributesConfig, token: str, base: str) -> Dict[str, Any]:
        params = {"model": c.model or None}
        return await _intercom_request(token, base, "GET", "/data_attributes", params=params, action_name="list_data_attributes")

    async def _list_segments(self, c: IntercomListSegmentsConfig, token: str, base: str) -> Dict[str, Any]:
        return await _intercom_request(token, base, "GET", "/segments", action_name="list_segments")

    # ------------------------------------------------------------------
    # Article (Help Center) handlers
    # ------------------------------------------------------------------
    async def _list_articles(self, c, token, base):
        params = {"per_page": c.per_page}
        return await _intercom_request(token, base, "GET", "/articles", params=params, action_name="list_articles")

    async def _get_article(self, c, token, base):
        return await _intercom_request(token, base, "GET", f"/articles/{c.article_id}", action_name="get_article")

    async def _create_article(self, c, token, base):
        body = {"title": c.title, "body": c.body, "author_id": c.author_id, "state": c.state}
        return await _intercom_request(token, base, "POST", "/articles", json_body=body, action_name="create_article")

    async def _update_article(self, c, token, base):
        body = {"title": c.title, "body": c.body, "state": c.state or None}
        return await _intercom_request(token, base, "PUT", f"/articles/{c.article_id}", json_body=body, action_name="update_article")

    async def _delete_article(self, c, token, base):
        return await _intercom_request(token, base, "DELETE", f"/articles/{c.article_id}", action_name="delete_article")
