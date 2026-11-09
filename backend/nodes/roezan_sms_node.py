"""Roezan SMS API 1.9.2: one documented request per operation.

Contract: https://developer.roezan.com/openapi.json
A queued send is not delivery confirmation. Writes are never automatically retried.
Cursor reads return one page and preserve the provider's opaque next_cursor.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.roezan.com"
ResourceID = Annotated[int, Field(gt=0)]
Phone = Annotated[str, Field(min_length=1, max_length=64)]
Text = Annotated[str, Field(min_length=1)]


class RoezanSMSAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Roezan SMS API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.roezan.com/docs",
            "x-credential-instructions": "Paste your Roezan account API key. NoClick sends it in the x-api-key header to app.roezan.com. The connection check reads your account's sending numbers.",
        })
    credential_type: Literal["roezan_sms_api_key"] = Field("roezan_sms_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)


class ContactFields(Input):
    phone: Phone
    firstName: str | None = None
    lastName: str | None = None
    email: str | None = None


class SendMessage(ContactFields):
    """Queue one SMS or MMS; acknowledgement does not confirm delivery."""
    operation: Literal["send_message"] = "send_message"
    message: Text | None = None
    media: list[str] | None = Field(None, min_length=1)
    countryCode: str | None = Field(None, pattern="^[A-Z]{2}$")
    from_number: str | None = Field(None, alias="from", pattern=r"^\+[1-9]\d{1,14}$", description="Optional sending number from list_senders, in E.164 format.")
    idempotency_key: str | None = Field(None, min_length=1, description="Unique per request. Reuse only for an identical retry within 24 hours.")

    @model_validator(mode="after")
    def content(self):
        if not self.message and not self.media:
            raise ValueError("Provide a message or media URLs")
        return self


class ListSenders(Input):
    """Read the account's sending phone numbers."""
    operation: Literal["list_senders"] = "list_senders"


class ListLists(Input):
    """Read lists belonging to the account."""
    operation: Literal["list_lists"] = "list_lists"


class ListFields(Input):
    """Read the account's custom field definitions."""
    operation: Literal["list_fields"] = "list_fields"


class ListTags(Input):
    """Read tags and the provider's pagination metadata."""
    operation: Literal["list_tags"] = "list_tags"


class SubscribeContact(ContactFields):
    """Queue creation or subscription of a contact to a list."""
    operation: Literal["subscribe_contact"] = "subscribe_contact"
    list: Text = Field(..., description="List ID from list_lists.")


class UnsubscribeContact(Input):
    """Queue removal of a contact from a list."""
    operation: Literal["unsubscribe_contact"] = "unsubscribe_contact"
    phone: Phone
    list: Text


class UpsertContact(ContactFields):
    """Create or update a contact; list and tag changes are asynchronous."""
    operation: Literal["upsert_contact"] = "upsert_contact"
    lists: list[ResourceID] | None = None
    tags: list[ResourceID] | None = None


class GetContact(Input):
    """Find a contact by phone, with email as a fallback."""
    operation: Literal["get_contact"] = "get_contact"
    phone: Phone | None = None
    email: Text | None = None

    @model_validator(mode="after")
    def lookup(self):
        if not self.phone and not self.email:
            raise ValueError("Provide a phone number or email address")
        return self


class AddContactTags(Input):
    """Queue the addition of tags to a contact."""
    operation: Literal["add_contact_tags"] = "add_contact_tags"
    phone: Phone
    tagIds: list[ResourceID] = Field(..., min_length=1)


class RemoveContactTag(Input):
    """Queue removal of one tag from a contact."""
    operation: Literal["remove_contact_tag"] = "remove_contact_tag"
    phone: Phone
    tagId: ResourceID


class ContactID(Input):
    contact_id: ResourceID


class BroadcastID(Input):
    broadcast_id: ResourceID


class GetContactMessages(ContactID):
    """Read one page of conversation history; pass next_cursor back unchanged."""
    operation: Literal["get_contact_messages"] = "get_contact_messages"
    cursor: str | None = None
    limit: int = Field(50, ge=1, le=100)
    source: Literal["conversation", "broadcast", "automation", "event_reminder", "bot", "keyword", "list_autoresponse", "activecampaign", "highlevel", "hubspot", "make", "zapier", "integration"] | None = None
    direction: Literal["inbound", "outbound"] | None = None
    createdAtFrom: date | None = None
    createdAtTo: date | None = None

    @model_validator(mode="after")
    def date_range(self):
        if (self.createdAtFrom is None) != (self.createdAtTo is None):
            raise ValueError("Provide both date range bounds")
        if self.createdAtFrom and self.createdAtFrom > self.createdAtTo:
            raise ValueError("End date must be on or after start date")
        return self


class GetBroadcastRecipients(BroadcastID):
    """Read one page of broadcast recipients and delivery results."""
    operation: Literal["get_broadcast_recipients"] = "get_broadcast_recipients"
    cursor: str | None = None
    limit: int = Field(50, ge=1, le=100)


class CreateBroadcast(Input):
    """Create a draft. This operation does not schedule or send the broadcast."""
    operation: Literal["create_broadcast"] = "create_broadcast"
    name: Text
    list_ids: list[ResourceID] = Field(..., min_length=1, max_length=100)
    message: Text
    media: list[str] | None = Field(None, max_length=10)
    scheduled_time: str | None = Field(None, description="Optional intended time stored on the draft, not a send request. Use YYYY-MM-DD HH:mm[:ss] or ISO date/time.")
    scheduled_timezone: str | None = Field(None, description="IANA timezone; provider defaults to America/New_York.")
    idempotency_key: str | None = Field(None, min_length=1)

    @model_validator(mode="after")
    def timezone_requires_time(self):
        if self.scheduled_timezone and not self.scheduled_time:
            raise ValueError("A timezone requires a scheduled time")
        return self


class PreviewBroadcast(BroadcastID):
    """Queue a real test message to one phone from a draft or scheduled broadcast."""
    operation: Literal["preview_broadcast"] = "preview_broadcast"
    phone: Phone
    idempotency_key: str | None = Field(None, min_length=1)


class ScheduleBroadcast(BroadcastID):
    """Confirm a draft's stored time, supply a new time, or explicitly send now."""
    operation: Literal["schedule_broadcast"] = "schedule_broadcast"
    scheduled_time: str | None = None
    scheduled_timezone: str | None = None
    send_now: bool | None = Field(None, description="Set true only to send immediately. Omit to use the draft's stored intent.")
    idempotency_key: str | None = Field(None, min_length=1)

    @model_validator(mode="after")
    def timing(self):
        if self.send_now and self.scheduled_time:
            raise ValueError("Choose a scheduled time or send_now, not both")
        return self


class CancelBroadcast(BroadcastID):
    """Cancel a pending broadcast, reverting it to a draft."""
    operation: Literal["cancel_broadcast"] = "cancel_broadcast"
    idempotency_key: str | None = Field(None, min_length=1)


class GetBroadcast(BroadcastID):
    """Read status and delivery, reply and opt-out counts."""
    operation: Literal["get_broadcast"] = "get_broadcast"


class GetContactLists(ContactID):
    """Read a contact's subscribed lists."""
    operation: Literal["get_contact_lists"] = "get_contact_lists"


RoezanSMSConfig = Annotated[Union[
    SendMessage, ListSenders, ListLists, ListFields, ListTags, SubscribeContact,
    UnsubscribeContact, UpsertContact, GetContact, AddContactTags, RemoveContactTag,
    GetContactMessages, GetBroadcastRecipients, CreateBroadcast, PreviewBroadcast,
    ScheduleBroadcast, CancelBroadcast, GetBroadcast, GetContactLists,
], Field(discriminator="operation")]


class RoezanSMSFullConfig(NodeConfig[RoezanSMSConfig, RoezanSMSAPIKeyCredential]):
    pass


# Fixed provider paths only. Resource placeholders are positive integer config fields.
OPERATIONS = {
    "send_message": ("POST", "/api/integrations/message/send"),
    "list_senders": ("GET", "/api/integrations/senders"),
    "list_lists": ("GET", "/api/integrations/lists"),
    "list_fields": ("GET", "/api/integrations/fields"),
    "list_tags": ("GET", "/api/integrations/tags"),
    "subscribe_contact": ("POST", "/api/integrations/lists/subscribe"),
    "unsubscribe_contact": ("PUT", "/api/integrations/lists/unsubscribe"),
    "upsert_contact": ("POST", "/api/integrations/contacts"),
    "get_contact": ("GET", "/api/integrations/contacts"),
    "add_contact_tags": ("POST", "/api/integrations/contacts/tags"),
    "remove_contact_tag": ("DELETE", "/api/integrations/contacts/tags"),
    "get_contact_messages": ("GET", "/api/integrations/contacts/{contact_id}/messages"),
    "get_broadcast_recipients": ("GET", "/api/integrations/broadcasts/{broadcast_id}/recipients"),
    "create_broadcast": ("POST", "/api/integrations/broadcasts"),
    "preview_broadcast": ("POST", "/api/integrations/broadcasts/{broadcast_id}/preview"),
    "schedule_broadcast": ("POST", "/api/integrations/broadcasts/{broadcast_id}/schedule"),
    "cancel_broadcast": ("POST", "/api/integrations/broadcasts/{broadcast_id}/cancel"),
    "get_broadcast": ("GET", "/api/integrations/broadcasts/{broadcast_id}"),
    "get_contact_lists": ("GET", "/api/integrations/contacts/{contact_id}/lists"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


class RoezanSMSNode(WorkflowNode):
    integration_type = "automation-roezan-sms"
    connection_evidence = ConnectionEvidence(noun="sending numbers", operation="list_senders", label_keys=("label", "numberE164", "number", "id"))

    @classmethod
    def get_config_model(cls):
        return RoezanSMSFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, RoezanSMSFullConfig) or not self.config.credentials:
            return {"status": "error", "error": "Connect a Roezan SMS API key"}
        op = self.config.config
        secret = self.config.credentials.api_key
        method, template = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", by_alias=True, exclude_none=True)
        path = template.format(**values)
        headers = {"x-api-key": secret, "Accept": "application/json"}
        key = values.pop("idempotency_key", None)
        if key:
            headers["Idempotency-Key"] = key
        for field in ("operation", "contact_id", "broadcast_id"):
            values.pop(field, None)
        kwargs = {"params": values} if method == "GET" else ({"json": values} if values or op.operation == "schedule_broadcast" else {})
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers, **kwargs)
        except httpx.RequestError:
            return {"status": "error", "error": "Roezan request did not complete. For a write, inspect the account before retrying; its outcome may be unknown."}
        try:
            body = response.json() if response.content else None
        except ValueError:
            return {"status": "error", "http_status": response.status_code, "error": "Roezan returned an unexpected non-JSON response"}
        body = _redact(body, secret)
        failed = isinstance(body, dict) and (body.get("success") is False or bool(body.get("error")))
        if not 200 <= response.status_code < 300 or failed:
            message = (body.get("message") or body.get("error")) if isinstance(body, dict) else None
            return {"status": "error", "http_status": response.status_code,
                "error": message or "Roezan rejected the request", "data": body,
                "retry_after": response.headers.get("Retry-After")}
        if op.operation == "list_senders" and (not isinstance(body, dict) or not isinstance(body.get("senders"), list)):
            return {"status": "error", "http_status": response.status_code, "error": "Unexpected Roezan sending numbers response"}
        return {"status": "success", "http_status": response.status_code, "data": body}
