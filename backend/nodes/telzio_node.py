"""Telzio public API v3: one documented request per operation.

Contract: https://api.telzio.com/swagger/v3/swagger.json
Accept an existing claims_token; authentication and token renewal stay with Telzio.
Lists return one page and preserve the provider's paging fields.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.telzio.com"


class TelzioTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Telzio Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.telzio.com/swagger/v3/swagger.json",
            "x-credential-instructions": "Paste an existing Telzio claims_token, returned by Telzio's POST /v3/auth. Telzio documents this token for Bearer authorization on subsequent requests. Paste only the token, without Bearer. When it expires, replace it with a new token obtained from Telzio. NoClick does not sign in or renew tokens for you.",
        },
    )
    credential_type: Literal["telzio_token"] = Field("telzio_token", json_schema_extra={"ui:hidden": True})
    token: str = Field(..., title="Token", min_length=1, max_length=16384, json_schema_extra={"ui:widget": "password"})

    @field_validator("token", mode="before")
    @classmethod
    def validate_token(cls, value):
        value = clean_secret(value, field_name="Token", key=True)
        if any(c.isspace() for c in value) or value.lower().startswith("bearer "):
            raise ValueError("Paste only the token without an authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_identifiers(cls, value, info):
        if value is not None and info.field_name in {"query", "call_id", "conversation_id", "item_id", "queue_id", "recording_id", "voicemail_id"}:
            if isinstance(value, str) and (value in {".", ".."} or any(c in value for c in "/\\?#\r\n")):
                raise ValueError("Use one Telzio identifier or user query")
        if info.field_name == "query" and value == "groups":
            raise ValueError("Use a user ID, username or extension")
        if info.field_name == "call_id" and value == "recent":
            raise ValueError("Use a call ID")
        return value


class TelzioListUsersConfig(_Input):
    """List users on the connected account, with optional search and a page cursor."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    limit: int = Field(100, ge=1, le=500)
    starting_page_id: Optional[str] = None
    term: Optional[str] = None


class TelzioGetUserConfig(_Input):
    """Retrieve a user by user ID, username or extension."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=256)


class TelzioListRecentCallsConfig(_Input):
    """List one page of the connected user's recent calls."""
    operation: Literal["list_recent_calls"] = Field("list_recent_calls", json_schema_extra={"ui:hidden": True})
    limit: int = Field(30, ge=1, le=100)
    starting_after: Optional[int] = None
    ending_before: Optional[int] = None


class TelzioGetCallConfig(_Input):
    """Retrieve the details of a call."""
    operation: Literal["get_call"] = Field("get_call", json_schema_extra={"ui:hidden": True})
    call_id: str = Field(..., min_length=1, max_length=256)


class TelzioListConversationsConfig(_Input):
    """List one page of conversations, including each conversation's most recent item."""
    operation: Literal["list_conversations"] = Field("list_conversations", json_schema_extra={"ui:hidden": True})
    limit: int = Field(30, ge=1, le=100)
    starting_after: Optional[int] = None
    ending_before: Optional[int] = None


class TelzioGetConversationConfig(_Input):
    """Retrieve a conversation and its details."""
    operation: Literal["get_conversation"] = Field("get_conversation", json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=256)


class TelzioListConversationItemsConfig(_Input):
    """List the first page of items in a conversation. Returns the oldest message ID; cursor paging is not exposed for this operation."""
    operation: Literal["list_conversation_items"] = Field("list_conversation_items", json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=256)
    limit: int = Field(30, ge=1, le=100)


class TelzioCreateSmsConversationConfig(_Input):
    """Start a new SMS conversation by sending a text message from a Telzio number."""
    operation: Literal["create_sms_conversation"] = Field("create_sms_conversation", json_schema_extra={"ui:hidden": True})
    number_id: str = Field(..., min_length=1, max_length=256)
    recipient: str = Field(..., min_length=1, max_length=256, description="Recipient phone number")
    text: str = Field(..., min_length=1, max_length=750)


class TelzioSendSmsConfig(_Input):
    """Send a text message in an existing SMS conversation."""
    operation: Literal["send_sms"] = Field("send_sms", json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=256)
    text: str = Field(..., min_length=1, max_length=2048)


class TelzioSearchPhonebookConfig(_Input):
    """Search contacts and organizations by name, or list them when no search is supplied."""
    operation: Literal["search_phonebook"] = Field("search_phonebook", json_schema_extra={"ui:hidden": True})
    q: Optional[str] = None
    limit: int = Field(100, ge=1, le=100)
    entity_type: Optional[Literal["contact", "organization"]] = None


class TelzioGetContactConfig(_Input):
    """Retrieve a contact and its phonebook endpoints."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: UUID


class TelzioCreateContactConfig(_Input):
    """Create a phonebook contact, optionally linked to an organization."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    contact_name: str = Field(..., min_length=1, max_length=256)
    organization_id: Optional[UUID] = None


class TelzioUpdateContactConfig(_Input):
    """Rename a phonebook contact and optionally change its organization."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: UUID
    contact_name: str = Field(..., min_length=1, max_length=256)
    organization_id: Optional[UUID] = None


class TelzioDeleteContactConfig(_Input):
    """Permanently delete a phonebook contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})
    contact_id: UUID


class TelzioListCommentsConfig(_Input):
    """List one page of comments on a call, voicemail or other Telzio item."""
    operation: Literal["list_comments"] = Field("list_comments", json_schema_extra={"ui:hidden": True})
    item_id: str = Field(..., min_length=1, max_length=256)
    limit: int = Field(30, ge=1, le=100)
    starting_after: Optional[str] = None
    ending_before: Optional[str] = None


class TelzioCreateCommentConfig(_Input):
    """Add a comment to a Telzio item."""
    operation: Literal["create_comment"] = Field("create_comment", json_schema_extra={"ui:hidden": True})
    item_id: str = Field(..., min_length=1, max_length=256)
    text: str = Field(..., min_length=1, max_length=3000)


class TelzioListQueuesConfig(_Input):
    """List call queues the connected user can access."""
    operation: Literal["list_queues"] = Field("list_queues", json_schema_extra={"ui:hidden": True})


class TelzioGetQueueConfig(_Input):
    """Retrieve a call queue, including its agents and waiting calls."""
    operation: Literal["get_queue"] = Field("get_queue", json_schema_extra={"ui:hidden": True})
    queue_id: str = Field(..., min_length=1, max_length=256)


class TelzioListRecordingsConfig(_Input):
    """List one page of recordings the connected user can access."""
    operation: Literal["list_recordings"] = Field("list_recordings", json_schema_extra={"ui:hidden": True})
    limit: int = Field(30, ge=1, le=100)
    starting_after: Optional[str] = None
    ending_before: Optional[str] = None


class TelzioGetRecordingConfig(_Input):
    """Retrieve recording details without downloading audio."""
    operation: Literal["get_recording"] = Field("get_recording", json_schema_extra={"ui:hidden": True})
    recording_id: str = Field(..., min_length=1, max_length=256)


class TelzioListVoicemailsConfig(_Input):
    """List one page of the connected user's available voicemails."""
    operation: Literal["list_voicemails"] = Field("list_voicemails", json_schema_extra={"ui:hidden": True})
    limit: int = Field(30, ge=1, le=100)
    starting_after: Optional[str] = None
    ending_before: Optional[str] = None


class TelzioGetVoicemailConfig(_Input):
    """Retrieve a voicemail assigned to the connected user."""
    operation: Literal["get_voicemail"] = Field("get_voicemail", json_schema_extra={"ui:hidden": True})
    voicemail_id: str = Field(..., min_length=1, max_length=256)


class TelzioUpdateVoicemailConfig(_Input):
    """Mark a voicemail as listened or unlistened."""
    operation: Literal["update_voicemail"] = Field("update_voicemail", json_schema_extra={"ui:hidden": True})
    voicemail_id: str = Field(..., min_length=1, max_length=256)
    status: Literal["unlistened", "listened"]


class TelzioListTagsConfig(_Input):
    """List one page of tags associated with the connected account."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})
    limit: int = Field(30, ge=1, le=100)
    starting_after: Optional[str] = None
    ending_before: Optional[str] = None


class TelzioCreateTagConfig(_Input):
    """Create a tag for the connected account."""
    operation: Literal["create_tag"] = Field("create_tag", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=128)


TelzioConfig = Annotated[Union[
    TelzioListUsersConfig,
    TelzioGetUserConfig,
    TelzioListRecentCallsConfig,
    TelzioGetCallConfig,
    TelzioListConversationsConfig,
    TelzioGetConversationConfig,
    TelzioListConversationItemsConfig,
    TelzioCreateSmsConversationConfig,
    TelzioSendSmsConfig,
    TelzioSearchPhonebookConfig,
    TelzioGetContactConfig,
    TelzioCreateContactConfig,
    TelzioUpdateContactConfig,
    TelzioDeleteContactConfig,
    TelzioListCommentsConfig,
    TelzioCreateCommentConfig,
    TelzioListQueuesConfig,
    TelzioGetQueueConfig,
    TelzioListRecordingsConfig,
    TelzioGetRecordingConfig,
    TelzioListVoicemailsConfig,
    TelzioGetVoicemailConfig,
    TelzioUpdateVoicemailConfig,
    TelzioListTagsConfig,
    TelzioCreateTagConfig
], Field(discriminator="operation")]


class TelzioFullConfig(NodeConfig[TelzioConfig, TelzioTokenCredential]):
    pass


OPERATIONS = {
    'list_users': ('GET', '/v3/users', ('limit', 'starting_page_id', 'term'), (), True),
    'get_user': ('GET', '/v3/users/{query}', (), (), False),
    'list_recent_calls': ('GET', '/v3/calls/recent', ('limit', 'starting_after', 'ending_before'), (), True),
    'get_call': ('GET', '/v3/calls/{call_id}', (), (), False),
    'list_conversations': ('GET', '/v3/conversations', ('limit', 'starting_after', 'ending_before'), (), True),
    'get_conversation': ('GET', '/v3/conversations/{conversation_id}', (), (), False),
    'list_conversation_items': ('GET', '/v3/conversations/{conversation_id}/items', ('limit',), (), True),
    'create_sms_conversation': ('POST', '/v3/conversations/sms/create-conversation', (), ('number_id', 'recipient', 'text'), False),
    'send_sms': ('POST', '/v3/conversations/{conversation_id}/sms', (), ('text',), False),
    'search_phonebook': ('GET', '/v3/phonebook/entities', ('q', 'limit', 'entity_type'), (), True),
    'get_contact': ('GET', '/v3/phonebook/contacts/{contact_id}', (), (), False),
    'create_contact': ('POST', '/v3/phonebook/contacts', (), ('contact_name', 'organization_id'), False),
    'update_contact': ('POST', '/v3/phonebook/contacts/{contact_id}', (), ('contact_name', 'organization_id'), False),
    'delete_contact': ('DELETE', '/v3/phonebook/contacts/{contact_id}', (), (), False),
    'list_comments': ('GET', '/v3/comments/{item_id}', ('limit', 'starting_after', 'ending_before'), (), True),
    'create_comment': ('POST', '/v3/comments/{item_id}', (), ('text',), False),
    'list_queues': ('GET', '/v3/queues', (), (), True),
    'get_queue': ('GET', '/v3/queues/{queue_id}', (), (), False),
    'list_recordings': ('GET', '/v3/recordings', ('limit', 'starting_after', 'ending_before'), (), True),
    'get_recording': ('GET', '/v3/recordings/{recording_id}', (), (), False),
    'list_voicemails': ('GET', '/v3/voicemails', ('limit', 'starting_after', 'ending_before'), (), True),
    'get_voicemail': ('GET', '/v3/voicemails/{voicemail_id}', (), (), False),
    'update_voicemail': ('POST', '/v3/voicemails/{voicemail_id}', (), ('status',), False),
    'list_tags': ('GET', '/v3/tags', ('limit', 'starting_after', 'ending_before'), (), True),
    'create_tag': ('POST', '/v3/tags', (), ('name',), False),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()}
    return value


class TelzioNode(WorkflowNode):
    integration_type = "automation-telzio"
    connection_evidence = ConnectionEvidence(
        noun="Telzio users", operation="list_users",
        label_keys=("username", "email", "first_name", "user_id"),
    )

    @classmethod
    def get_config_model(cls):
        return TelzioFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Telzio token")
        config = self.config.config
        token = self.config.credentials.token
        method, path, query_fields, form_fields, listing = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        # Encode path values independently; no caller-controlled URLs or routes.
        path = path.format(**{key: quote(str(value), safe="") for key, value in values.items()})
        params = {key: values[key] for key in query_fields if key in values}
        form = {key: values[key] for key in form_fields if key in values}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(
                    method, BASE + path, params=params,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    **({"data": form} if form_fields else {}),
                )
        except httpx.RequestError:
            result = {"status": "error", "message": "Telzio request could not be completed",
                      "write_outcome": "unknown" if method != "GET" else None}
        else:
            if response.status_code != 200:
                # Preserve provider rejection text for the common connect seam.
                result = {"status": "error", "http_status": response.status_code,
                          "message": response.text[:4000],
                          "write_outcome": "unknown" if method != "GET" and response.status_code >= 500 else None}
            elif config.operation == "delete_contact":
                result = {"status": "success", "http_status": 200, "data": {"deleted_contact_id": values["contact_id"]}}
            else:
                try:
                    payload = response.json()
                    if not isinstance(payload, dict) or "error" in payload or "errors" in payload:
                        raise ValueError("Unexpected Telzio response")
                    if listing and payload.get("data") is not None and not isinstance(payload["data"], list):
                        raise ValueError("Unexpected Telzio list response")
                    # Keep provider paging fields and nullable data unchanged.
                    result = {"status": "success", "http_status": 200, "data": payload}
                except (ValueError, TypeError):
                    result = {"status": "error", "message": "Telzio returned an unexpected response",
                              "write_outcome": "unknown" if method != "GET" else None}
        result = _redact(result, token)
        await self.emit(result)
        return result
