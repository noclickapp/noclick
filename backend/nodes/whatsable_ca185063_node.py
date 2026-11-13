"""WhatsAble v1 operations, pinned to the provider's OpenAPI 1.0.0 contract.

Each execution sends one request to api.whatsable.app. Lists return one cursor
page. Send acknowledgements retain the provider status/error: HTTP 201 alone
never establishes delivery. API keys are manually supplied, not OAuth tokens.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

Id = Annotated[str, Field(min_length=1, max_length=64)]
Timestamp = Annotated[str, Field(json_schema_extra={"format": "date-time"})]


class WhatsAbleAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Whatsable API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.whatsable.app/v1/openapi.json",
            "x-credential-instructions": "In WhatsAble, open Settings > API keys and paste a live API key. Select the number access and scopes your operations need: numbers:read, templates:read, messages:read, messages:send, contacts:read, contacts:write and labels:write. The connection test reads the organization and API key with GET /v1/me; it does not verify all operation permissions.",
        })
    credential_type: Literal["whatsable_ca185063_api_key"] = Field("whatsable_ca185063_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False,
        description="Paste the key only, without the Bearer prefix.", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste an API key without spaces or header characters")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def validate_values(cls, value, info):
        if info.field_name.endswith("_id") and info.field_name != "wa_user_id" and value is not None:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
                raise ValueError("Use a single WhatsAble resource ID")
        if info.field_name in {"created_after", "created_before", "updated_after", "send_at"} and value is not None:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError("Use an RFC 3339 timestamp with an offset") from None
        return value


class _Page(_Input):
    limit: int = Field(25, ge=1, le=100, title="Page Size")
    cursor: str | None = Field(None, min_length=1, max_length=512, description="Paste next_cursor from the previous page. One page is returned per execution.")


class _Create(_Input):
    idempotency_key: str | None = Field(None, min_length=1, max_length=255,
        description="Reuse the same key only for a retry of the same body. WhatsAble remembers it for 24 hours.")

    @field_validator("idempotency_key")
    @classmethod
    def header(cls, value):
        if value is not None and any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("Use printable ASCII for the idempotency key")
        return value


class GetMe(_Input):
    """Read the organization, API key grants, number access and plan."""
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={"ui:hidden": True})


class ListNumbers(_Page):
    """List business numbers accessible to this key."""
    operation: Literal["list_numbers"] = Field("list_numbers", json_schema_extra={"ui:hidden": True})


class GetNumber(_Input):
    """Read a business number."""
    operation: Literal["get_number"] = Field("get_number", json_schema_extra={"ui:hidden": True})
    number_id: Id


class ListTemplates(_Page):
    """List message templates and optionally filter by number, name, language or status."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})
    number_id: Id | None = None
    name: str | None = Field(None, min_length=1, max_length=512)
    language: str | None = Field(None, min_length=1, max_length=15)
    status: str | None = Field(None, min_length=1, max_length=32)


class GetTemplate(_Input):
    """Read a template and the variables needed to send it."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})
    template_id: Id


class _Text(_Input):
    body: str = Field(..., min_length=1, max_length=4096)
    preview_url: bool | None = None


class _MediaHeader(_Input):
    url: str | None = Field(None, max_length=2000, json_schema_extra={"format": "uri"})
    media_id: Id | None = None
    filename: str | None = Field(None, min_length=1, max_length=240)

    @model_validator(mode="after")
    def source(self):
        if (self.url is None) == (self.media_id is None):
            raise ValueError("Supply exactly one of url and media_id for a media header")
        if self.url is not None:
            parsed = urlsplit(self.url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Use a public HTTPS media URL")
        return self


class _Template(_Input):
    id: Id
    variables: dict[str, Union[Annotated[str, Field(min_length=1, max_length=1024)], _MediaHeader]] = Field(default_factory=dict,
        description="Variables keyed by variables[].key from Get Template. Use a string for text or a url/media_id object for a media header.")

    @field_validator("variables")
    @classmethod
    def variable_keys(cls, value):
        if any(not 1 <= len(key) <= 64 or (isinstance(item, str) and not item.strip()) for key, item in value.items()):
            raise ValueError("Template variable keys must be 1–64 characters and values nonblank")
        return value


class _Message(_Create):
    to: str | None = Field(None, min_length=1, max_length=256,
        description="Recipient E.164 phone, Business-Scoped User ID or known @username.")
    conversation_id: Id | None = Field(None, description="Send into this existing conversation instead of supplying to.")
    from_number: str | None = Field(None, min_length=1, max_length=64,
        description="Business number ID or E.164 phone; omitted uses the key's default number.")
    type: Literal["text", "template"] = Field("text", description="Text needs an open 24-hour window. Templates must be approved.")
    text: _Text | None = None
    template: _Template | None = None

    @model_validator(mode="after")
    def content(self):
        if (self.to is None) == (self.conversation_id is None):
            raise ValueError("Supply exactly one of to and conversation_id")
        if (self.type == "text" and (self.text is None or self.template is not None)) or (self.type == "template" and (self.template is None or self.text is not None)):
            raise ValueError("Supply exactly the content selected by the message type")
        return self


class SendMessage(_Message):
    """Send text or a template. Inspect data.status and data.error even after HTTP 201."""
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={"ui:hidden": True})
    pause_ai: bool = Field(False, description="Pause the AI in the conversation when the send succeeds.")
    reply_to_message_id: Id | None = None

    @model_validator(mode="after")
    def reply(self):
        if self.type == "template" and self.reply_to_message_id is not None:
            raise ValueError("Template messages cannot quote another message")
        return self


class ListMessages(_Page):
    """List messages with their provider delivery status."""
    operation: Literal["list_messages"] = Field("list_messages", json_schema_extra={"ui:hidden": True})
    conversation_id: Id | None = None
    contact_id: Id | None = None
    number_id: Id | None = None
    direction: Literal["inbound", "outbound"] | None = None
    status: Literal["pending", "sent", "delivered", "read", "failed"] | None = None
    created_after: Timestamp | None = None
    created_before: Timestamp | None = None
    query: str | None = Field(None, min_length=1, max_length=100)


class GetMessage(_Input):
    """Read a message, including its current send status and error."""
    operation: Literal["get_message"] = Field("get_message", json_schema_extra={"ui:hidden": True})
    message_id: Id


class ListConversations(_Page):
    """List conversations, optionally filtering unread messages and session windows."""
    operation: Literal["list_conversations"] = Field("list_conversations", json_schema_extra={"ui:hidden": True})
    number_id: Id | None = None
    contact_id: Id | None = None
    label_id: Id | None = None
    updated_after: Timestamp | None = None
    query: str | None = Field(None, min_length=1, max_length=100)
    unread: Literal["true", "false"] | None = None
    window_open: Literal["true", "false"] | None = None
    awaiting_reply: Literal["true", "false"] | None = None
    figures_to_check: Literal["true", "false"] | None = None


class GetConversation(_Input):
    """Read a conversation and its 24-hour window."""
    operation: Literal["get_conversation"] = Field("get_conversation", json_schema_extra={"ui:hidden": True})
    conversation_id: Id


class GetConversationTimeline(_Page):
    """Read one page of messages, notes and other timeline entries."""
    operation: Literal["get_conversation_timeline"] = Field("get_conversation_timeline", json_schema_extra={"ui:hidden": True})
    conversation_id: Id
    types: str | None = Field(None, max_length=256, description="Comma-separated timeline entry types, as documented by WhatsAble.")
    created_after: Timestamp | None = None


class UpdateConversationUnread(_Input):
    """Mark a conversation read or unread in the inbox."""
    operation: Literal["update_conversation_unread"] = Field("update_conversation_unread", json_schema_extra={"ui:hidden": True})
    conversation_id: Id
    unread: bool


class CreateConversationNote(_Create):
    """Add an internal note visible only to the team."""
    operation: Literal["create_conversation_note"] = Field("create_conversation_note", json_schema_extra={"ui:hidden": True})
    conversation_id: Id
    body: str = Field(..., min_length=1, max_length=4000)


class _LabelCondition(_Input):
    include: list[Annotated[str, Field(min_length=1, max_length=128)]] | None = Field(None, min_length=1, max_length=1000)
    exclude: list[Annotated[str, Field(min_length=1, max_length=128)]] | None = Field(None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def choice(self):
        if (self.include is None) == (self.exclude is None):
            raise ValueError("Supply exactly one of include and exclude")
        return self


class _SendIf(_Input):
    no_reply: Literal["since_last_message", "never_replied", "20m", "45m", "3h", "6h", "12h", "24h", "48h", "72h"] | None = None
    labels: _LabelCondition | None = None


class ScheduleMessage(_Message):
    """Schedule text or a template. Text still needs an open window when it fires."""
    operation: Literal["schedule_message"] = Field("schedule_message", json_schema_extra={"ui:hidden": True})
    send_if: _SendIf | None = None
    send_at: Timestamp = Field(..., description="A future RFC 3339 instant with its UTC offset.")
    time_zone: str | None = Field(None, min_length=1, max_length=64, description="IANA time zone for display only; send_at supplies the sending instant.")


class ListScheduledMessages(_Page):
    """List scheduled messages and their outcomes."""
    operation: Literal["list_scheduled_messages"] = Field("list_scheduled_messages", json_schema_extra={"ui:hidden": True})
    status: Literal["pending", "sent", "suppressed", "failed", "cancelled", "missed"] | None = None
    conversation_id: Id | None = None
    number_id: Id | None = None


class GetScheduledMessage(_Input):
    """Read a scheduled message and how it ended."""
    operation: Literal["get_scheduled_message"] = Field("get_scheduled_message", json_schema_extra={"ui:hidden": True})
    scheduled_message_id: Id


class CancelScheduledMessage(_Create):
    """Cancel a pending scheduled message."""
    operation: Literal["cancel_scheduled_message"] = Field("cancel_scheduled_message", json_schema_extra={"ui:hidden": True})
    scheduled_message_id: Id


class ListContacts(_Page):
    """Find contacts by address, label, updated time or search text."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    phone: str | None = None
    wa_user_id: str | None = Field(None, pattern=r"^[A-Z]{2}\.[A-Za-z0-9]{8,128}$")
    username: str | None = Field(None, min_length=1, max_length=64)
    label_id: Id | None = None
    updated_after: Timestamp | None = None
    query: str | None = Field(None, min_length=1, max_length=100)


class CreateContact(_Create):
    """Find or create a contact by phone or Business-Scoped User ID."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    phone: str | None = Field(None, min_length=1)
    wa_user_id: str | None = Field(None, pattern=r"^[A-Z]{2}\.[A-Za-z0-9]{8,128}$")
    name: str | None = Field(None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def address(self):
        if (self.phone is None) == (self.wa_user_id is None):
            raise ValueError("Supply exactly one of phone and wa_user_id")
        return self


class GetContact(_Input):
    """Read a contact, labels and notes."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: Id


class UpdateContact(_Input):
    """Update a contact's name or notes. Null or an empty string clears a note."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: Id
    name: str | None = Field(None, min_length=1, max_length=200)
    note: str | None = Field(None, max_length=5000)
    automation_note: str | None = Field(None, max_length=5000)

    @model_validator(mode="after")
    def changed(self):
        if not self.model_fields_set.intersection({"name", "note", "automation_note"}):
            raise ValueError("Supply at least one contact field to change")
        return self


class AddContactLabel(_Create):
    """Add an existing label to a contact by its ID or exact name."""
    operation: Literal["add_contact_label"] = Field("add_contact_label", json_schema_extra={"ui:hidden": True})
    contact_id: Id
    label: str = Field(..., min_length=1, max_length=128)


class RemoveContactLabel(_Input):
    """Remove a label from a contact."""
    operation: Literal["remove_contact_label"] = Field("remove_contact_label", json_schema_extra={"ui:hidden": True})
    contact_id: Id
    label_id: Id


class ListLabels(_Page):
    """List labels available to the organization."""
    operation: Literal["list_labels"] = Field("list_labels", json_schema_extra={"ui:hidden": True})


class CreateLabel(_Create):
    """Create a label. Empty number_ids makes it available on every number."""
    operation: Literal["create_label"] = Field("create_label", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=60)
    color: Literal["label-1", "label-2", "label-3", "label-4", "label-5", "label-6"]
    description: str | None = Field(None, max_length=280)
    keywords: list[Annotated[str, Field(min_length=2, max_length=40)]] | None = Field(None, max_length=20)
    number_ids: list[Id] | None = Field(None, max_length=50)


# WhatsAble's own MCP server: agents get its tools through a person's WhatsAble sign-in.
WhatsableCa185063McpCredential = mcp_credential("whatsable_ca185063", "https://api.whatsable.app/mcp", app="WhatsAble")
WhatsAbleCredential = Union[WhatsAbleAPIKeyCredential, WhatsableCa185063McpCredential]


Operation = Annotated[Union[GetMe, ListNumbers, GetNumber, ListTemplates, GetTemplate,
    SendMessage, ListMessages, GetMessage, ListConversations, GetConversation,
    GetConversationTimeline, UpdateConversationUnread, CreateConversationNote,
    ScheduleMessage, ListScheduledMessages, GetScheduledMessage, CancelScheduledMessage,
    ListContacts, CreateContact, GetContact, UpdateContact, AddContactLabel,
    RemoveContactLabel, ListLabels, CreateLabel], Field(discriminator="operation")]


class WhatsAbleConfig(NodeConfig[Operation, WhatsAbleCredential]):
    pass


# One entry per provider operation. Values after the path are path parameters.
ROUTES = {
    "get_me": ("GET", "/v1/me", ()),
    "list_numbers": ("GET", "/v1/numbers", ()),
    "get_number": ("GET", "/v1/numbers/{number_id}", ("number_id",)),
    "list_templates": ("GET", "/v1/templates", ()),
    "get_template": ("GET", "/v1/templates/{template_id}", ("template_id",)),
    "send_message": ("POST", "/v1/messages", ()),
    "list_messages": ("GET", "/v1/messages", ()),
    "get_message": ("GET", "/v1/messages/{message_id}", ("message_id",)),
    "list_conversations": ("GET", "/v1/conversations", ()),
    "get_conversation": ("GET", "/v1/conversations/{conversation_id}", ("conversation_id",)),
    "get_conversation_timeline": ("GET", "/v1/conversations/{conversation_id}/timeline", ("conversation_id",)),
    "update_conversation_unread": ("PATCH", "/v1/conversations/{conversation_id}/unread", ("conversation_id",)),
    "create_conversation_note": ("POST", "/v1/conversations/{conversation_id}/notes", ("conversation_id",)),
    "schedule_message": ("POST", "/v1/scheduled-messages", ()),
    "list_scheduled_messages": ("GET", "/v1/scheduled-messages", ()),
    "get_scheduled_message": ("GET", "/v1/scheduled-messages/{scheduled_message_id}", ("scheduled_message_id",)),
    "cancel_scheduled_message": ("POST", "/v1/scheduled-messages/{scheduled_message_id}/cancel", ("scheduled_message_id",)),
    "list_contacts": ("GET", "/v1/contacts", ()),
    "create_contact": ("POST", "/v1/contacts", ()),
    "get_contact": ("GET", "/v1/contacts/{contact_id}", ("contact_id",)),
    "update_contact": ("PATCH", "/v1/contacts/{contact_id}", ("contact_id",)),
    "add_contact_label": ("POST", "/v1/contacts/{contact_id}/labels", ("contact_id",)),
    "remove_contact_label": ("DELETE", "/v1/contacts/{contact_id}/labels/{label_id}", ("contact_id", "label_id")),
    "list_labels": ("GET", "/v1/labels", ()),
    "create_label": ("POST", "/v1/labels", ()),
}


class WhatsAbleError(ValueError):
    def __init__(self, message, status=None, code=None):
        self.status, self.code = status, code
        super().__init__(message)


def _redact(value, secret):
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items() if key.lower() not in {"authorization", "access_token", "api_token"}}
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    return value.replace(secret, "[redacted]") if isinstance(value, str) else value


class WhatsAbleNode(WorkflowNode):
    integration_type = "automation-whatsable-ca185063"
    credential_provider_labels = {"whatsable_ca185063": "WhatsAble Account"}
    connection_evidence = ConnectionEvidence(noun="organization", identity_operation="get_me", identity_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return WhatsAbleConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a WhatsAble API key")
        config, credential = self.config.config, self.config.credentials
        method, template, path_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        route = template.format(**{field: quote(values[field], safe="") for field in path_fields})
        values = {key: value for key, value in values.items() if key not in {"operation", "idempotency_key", *path_fields}}
        if "from_number" in values:
            values["from"] = values.pop("from_number")
        # Notes can explicitly be cleared; an omitted note is never sent.
        if isinstance(config, UpdateContact):
            for field in ("note", "automation_note"):
                if field in config.model_fields_set:
                    values[field] = getattr(config, field)
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}
        if getattr(config, "idempotency_key", None):
            headers["Idempotency-Key"] = config.idempotency_key
        request = {"params": values} if method == "GET" else {"json": values} if values else {}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://api.whatsable.app" + route, headers=headers, **request)
            try:
                payload = response.json()
            except ValueError:
                raise WhatsAbleError("WhatsAble returned invalid JSON", response.status_code) from None
            if not 200 <= response.status_code < 300:
                error = payload.get("error", {}) if isinstance(payload, dict) else {}
                message = error.get("message") if isinstance(error, dict) else None
                code = error.get("code") if isinstance(error, dict) else None
                raise WhatsAbleError(message if isinstance(message, str) else "WhatsAble request failed", response.status_code, code)
            if not isinstance(payload, dict) or not isinstance(payload.get("object"), str):
                raise WhatsAbleError("WhatsAble returned an incomplete resource", response.status_code)
            if isinstance(config, _Page) and (not isinstance(payload.get("data"), list) or "next_cursor" not in payload):
                raise WhatsAbleError("WhatsAble returned an invalid cursor page", response.status_code)
            if isinstance(config, GetMe) and (not isinstance(payload.get("organization"), dict) or not payload["organization"].get("name")):
                raise WhatsAbleError("WhatsAble did not identify the organization", response.status_code)
            output = {"status": "success", "operation": config.operation, "http_status": response.status_code, "data": payload}
        except WhatsAbleError as exc:
            output = {"status": "error", "operation": config.operation, "error": str(exc), "error_code": exc.code, "http_status": exc.status}
        except httpx.HTTPError:
            output = {"status": "error", "operation": config.operation,
                "error": "WhatsAble request did not complete. Inspect the result before retrying a write; reuse its idempotency key."}
        output = _redact(output, credential.api_key)
        await self.emit(output)
        return output
