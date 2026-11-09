"""Salesmsg public API v2.3, using a person-created Personal Access Token.

Contract: https://app.salesmessage.com/api/docs/salesmessage-public-api-v2.3.json
Each operation sends one request. Pagination remains explicit; SMS responses
acknowledge provider state and do not claim delivery. Writes are never retried.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.salesmessage.com/pub/v2.3"
CREDENTIAL_TYPE = "salesmsg_personal_access_token"


class SalesmsgPersonalAccessToken(BaseModel):
    model_config = ConfigDict(title="Salesmsg Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.salesmessage.com/settings/developer/access-tokens",
            "x-credential-instructions": "In Salesmsg Settings > Developer > Personal Access Tokens, create a token and paste it here. Allow contacts, conversations, messages and tags read/write, teams read and users read for the operations you use. The connection check reads your account's tags and requires tags:read.",
        })
    credential_type: Literal["salesmsg_personal_access_token"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=4096, title="Personal Access Token", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class GetCurrentUserConfig(_Input):
    """Read the current user's unread count."""
    operation: Literal["get_current_user"] = "get_current_user"

class ListContactsConfig(_Input):
    """Read one page of contacts with optional search."""
    operation: Literal["list_contacts"] = "list_contacts"
    search: str | None = None
    length: str = Field("10", pattern=r"^(?:[1-9]|[1-9][0-9]|100)$")
    page: str = Field("1", pattern=r"^[1-9][0-9]*$")

class GetContactConfig(_Input):
    """Read a contact by ID."""
    operation: Literal["get_contact"] = "get_contact"
    contact_id: int = Field(..., ge=1, title="Contact ID")

class CreateContactConfig(_Input):
    """Create a contact from a phone number and optional profile fields."""
    operation: Literal["create_contact"] = "create_contact"
    number: str = Field(..., min_length=1)
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    owner_id: int | None = Field(None, ge=1)

class UpdateContactConfig(_Input):
    """Update the supplied profile fields of a contact."""
    operation: Literal["update_contact"] = "update_contact"
    contact_id: int = Field(..., ge=1, title="Contact ID")
    number: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None

class DeleteContactConfig(_Input):
    """Delete a contact by ID."""
    operation: Literal["delete_contact"] = "delete_contact"
    contact_id: int = Field(..., ge=1, title="Contact ID")

class SearchContactsConfig(_Input):
    """Search contacts by a text term."""
    operation: Literal["search_contacts"] = "search_contacts"
    term: str = Field(..., min_length=1)
    limit: int = Field(50, ge=1, le=100)

class CreateContactNoteConfig(_Input):
    """Add a note to a contact."""
    operation: Literal["create_contact_note"] = "create_contact_note"
    contact_id: int = Field(..., ge=1, title="Contact ID")
    text: str = Field(..., min_length=1)

class ListTagsConfig(_Input):
    """Read one page of your account's tags."""
    operation: Literal["list_tags"] = "list_tags"
    search: str | None = None
    page: int = Field(1, ge=1)
    length: int = Field(10, ge=1, le=100)

class GetTagConfig(_Input):
    """Read a tag by ID."""
    operation: Literal["get_tag"] = "get_tag"
    tag_id: int = Field(..., ge=1, title="Tag ID")

class CreateTagConfig(_Input):
    """Create a tag."""
    operation: Literal["create_tag"] = "create_tag"
    label: str = Field(..., min_length=1, max_length=50)

class UpdateTagConfig(_Input):
    """Rename a tag."""
    operation: Literal["update_tag"] = "update_tag"
    tag_id: int = Field(..., ge=1, title="Tag ID")
    label: str = Field(..., min_length=1, max_length=50)

class AddContactTagConfig(_Input):
    """Attach an existing tag to a contact."""
    operation: Literal["add_contact_tag"] = "add_contact_tag"
    contact_id: int = Field(..., ge=1, title="Contact ID")
    tag_id: int = Field(..., ge=1, title="Tag ID")

class RemoveContactTagConfig(_Input):
    """Remove a tag from a contact."""
    operation: Literal["remove_contact_tag"] = "remove_contact_tag"
    contact_id: int = Field(..., ge=1, title="Contact ID")
    tag_id: int = Field(..., ge=1, title="Tag ID")

class ListInboxesConfig(_Input):
    """List inboxes, optionally limited to your memberships."""
    operation: Literal["list_inboxes"] = "list_inboxes"
    limit: int = Field(50, ge=1, le=100)
    has_membership: bool | None = None

class GetInboxConfig(_Input):
    """Read an inbox by ID."""
    operation: Literal["get_inbox"] = "get_inbox"
    team_id: int = Field(..., ge=1, title="Team ID")

class ListConversationsConfig(_Input):
    """Read a bounded page of conversations by status and optional search."""
    operation: Literal["list_conversations"] = "list_conversations"
    filter: Literal["open", "closed", "unread", "assigned", "unassigned", "outbound", "optout", "nocalls"] = "open"
    limit: int = Field(10, ge=1, le=100)
    offset: int = Field(0, ge=0)
    query: str | None = Field(None, min_length=1)

class GetConversationConfig(_Input):
    """Read a conversation by ID."""
    operation: Literal["get_conversation"] = "get_conversation"
    conversation_id: int = Field(..., ge=1, title="Conversation ID")

class CloseConversationConfig(_Input):
    """Close a conversation."""
    operation: Literal["close_conversation"] = "close_conversation"
    conversation_id: int = Field(..., ge=1, title="Conversation ID")

class OpenConversationConfig(_Input):
    """Reopen a conversation."""
    operation: Literal["open_conversation"] = "open_conversation"
    conversation_id: int = Field(..., ge=1, title="Conversation ID")

class ListMessagesConfig(_Input):
    """Read one page of conversation messages, preserving pagination metadata."""
    operation: Literal["list_messages"] = "list_messages"
    conversation_id: int = Field(..., ge=1, title="Conversation ID")
    per_page: int = Field(15, ge=1, le=100)
    page: int = Field(1, ge=1)
    only_scheduled: bool | None = None
    with_activity_logs: bool | None = None

class SendSmsConfig(_Input):
    """Send an SMS to a phone number from an inbox, immediately or at a scheduled time."""
    operation: Literal["send_sms"] = "send_sms"
    number: str = Field(..., min_length=1, description="Recipient phone number, e.g. +12025550018.")
    team_id: int = Field(..., ge=1, title="Inbox ID")
    message: str = Field(..., min_length=1)
    send_at: datetime | None = Field(None, description="Optional scheduled send time with timezone.")

class SendConversationSmsConfig(_Input):
    """Send an SMS within an existing conversation."""
    operation: Literal["send_conversation_sms"] = "send_conversation_sms"
    conversation_id: int = Field(..., ge=1, title="Conversation ID")
    message: str = Field(..., min_length=1)
    enable_quiet_hours: bool | None = None


SalesmsgConfig = Annotated[Union[
    GetCurrentUserConfig,
    ListContactsConfig,
    GetContactConfig,
    CreateContactConfig,
    UpdateContactConfig,
    DeleteContactConfig,
    SearchContactsConfig,
    CreateContactNoteConfig,
    ListTagsConfig,
    GetTagConfig,
    CreateTagConfig,
    UpdateTagConfig,
    AddContactTagConfig,
    RemoveContactTagConfig,
    ListInboxesConfig,
    GetInboxConfig,
    ListConversationsConfig,
    GetConversationConfig,
    CloseConversationConfig,
    OpenConversationConfig,
    ListMessagesConfig,
    SendSmsConfig,
    SendConversationSmsConfig], Field(discriminator="operation")]


class SalesmsgFullConfig(NodeConfig[SalesmsgConfig, SalesmsgPersonalAccessToken]):
    pass


ROUTES = {
    "get_current_user": ("GET", "/users/me", ()),
    "list_contacts": ("GET", "/contacts", ()),
    "get_contact": ("GET", "/contacts/{contact}", ('contact',)),
    "create_contact": ("POST", "/contacts", ()),
    "update_contact": ("PUT", "/contacts/{contact}", ('contact',)),
    "delete_contact": ("DELETE", "/contacts/{contact}", ('contact',)),
    "search_contacts": ("GET", "/contacts/search", ()),
    "create_contact_note": ("POST", "/contacts/note/{contact}/create", ('contact',)),
    "list_tags": ("GET", "/tags", ()),
    "get_tag": ("GET", "/tags/{tag}", ('tag',)),
    "create_tag": ("POST", "/tags", ()),
    "update_tag": ("PUT", "/tags/{tag}", ('tag',)),
    "add_contact_tag": ("PUT", "/tags/contact/{contact}/{tag}", ('contact', 'tag')),
    "remove_contact_tag": ("DELETE", "/tags/contact/{contact}/{tag}", ('contact', 'tag')),
    "list_inboxes": ("GET", "/teams", ()),
    "get_inbox": ("GET", "/teams/{team}", ('team',)),
    "list_conversations": ("GET", "/conversations", ()),
    "get_conversation": ("GET", "/conversations/{conversation}", ('conversation',)),
    "close_conversation": ("PUT", "/conversations/{conversation}/close", ('conversation',)),
    "open_conversation": ("PUT", "/conversations/{conversation}/open", ('conversation',)),
    "list_messages": ("GET", "/messages/{conversation}/paginated", ('conversation',)),
    "send_sms": ("POST", "/messages", ()),
    "send_conversation_sms": ("POST", "/messages/{conversation}", ('conversation',)),
}


class SalesmsgNode(WorkflowNode):
    integration_type = "automation-salesmsg"
    connection_evidence = ConnectionEvidence(operation="list_tags", noun="Salesmsg tags")

    @classmethod
    def get_config_model(cls):
        return SalesmsgFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, SalesmsgFullConfig) or self.config.credentials is None:
            raise ValueError("A Salesmsg Personal Access Token is required")
        config = self.config.config
        token = self.config.credentials.access_token
        method, path, ids = ROUTES[config.operation]
        payload = config.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        for name in ids:
            path = path.replace("{" + name + "}", str(payload.pop(name + "_id")))
        # v2.3 explicitly locates these write parameters in the query string.
        # Only Update Contact declares a JSON request body.
        kwargs = {"json": payload} if config.operation == "update_contact" else {"params": {
            key: str(value).lower() if isinstance(value, bool) else value for key, value in payload.items()
        }}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers={
                "Authorization": "Bearer " + token, "Accept": "application/json",
            }, **kwargs)
        if not 200 <= response.status_code < 300:
            message = "Salesmsg request failed"
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = str(error.get("message") or error.get("error") or message)
            except (ValueError, TypeError):
                pass
            raise ValueError(f"Salesmsg HTTP {response.status_code}: {message.replace(token, '[redacted]')[:1000]}")
        body = response.json()
        if not isinstance(body, (dict, list)):
            raise ValueError("Expected a Salesmsg JSON object or array")
        if isinstance(body, dict) and (body.get("error") or body.get("errors") or body.get("success") is False):
            message = str(body.get("message") or body.get("error") or body.get("errors") or "Salesmsg rejected the request")
            raise ValueError(message.replace(token, "[redacted]")[:1000])
        # Preserve documented resource fields and pagination metadata. An SMS
        # response may describe queued/scheduled/failed state, not delivery.
        return body if isinstance(body, dict) else {"data": body}
