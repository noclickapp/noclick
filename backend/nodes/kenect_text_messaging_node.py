"""Kenect's published Integrations API, using a pasted key and secret.

Each operation makes one contract request. Lists return one page, and writes
report the provider acknowledgement without claiming message delivery.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://integrations-api.kenect.com"
DOCS_URL = BASE_URL + "/q/openapi"


class KenectAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Kenect Text Messaging API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": DOCS_URL,
            "x-credential-instructions": "Paste your Kenect integration API key, API secret and Kenect location ID. Obtain these from your Kenect integration administrator. NoClick sends X-Api-Key, X-Api-Secret and X-Location-Id to the Kenect Integrations API. Connecting reads the locations authorized for your key.",
        },
    )
    credential_type: Literal["kenect_text_messaging_api_key"] = Field(
        "kenect_text_messaging_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, max_length=4096, title="API secret", json_schema_extra={"ui:widget": "password"})
    kenect_location_id: str = Field(..., pattern=r"^[0-9]+$", max_length=30, title="Kenect location ID", description="The numeric Kenect location ID, sent as X-Location-Id.")

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="Kenect API credential")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the credential without a header or whitespace")
        return value


Text = Annotated[str, Field(min_length=1, max_length=10000, pattern=r"\S")]
Phone = Annotated[str, Field(min_length=1, max_length=40, pattern=r"\S", description="North American or international phone number, e.g. +15555555555.")]


def _field_title(name, field_info):
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name).replace("_", " ").title().replace(" Id", " ID")


class Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, field_title_generator=_field_title)


class Page(Input):
    limit: int = Field(100, ge=1, le=100, description="Records in this page; run again with a larger offset for another page.")
    offset: int = Field(0, ge=0)


class DateRange(Input):
    beginAt: str | None = Field(None, description="Messages sent since this timestamp, e.g. 2022-01-01T00:00:00Z.")
    endAt: str | None = Field(None, description="Messages sent until this timestamp.")


class ListLocations(Input):
    """List active locations authorized for the integration key."""
    operation: Literal["list_locations"] = Field("list_locations", json_schema_extra={"ui:hidden": True})
    organizationId: str | None = None


class ListUsers(Input):
    """List organization users, optionally restricted to the credential location."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    filterByLocationId: bool = False


class GetUser(Input):
    """Get a Kenect user by ID."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    userId: int = Field(..., ge=1)


class ListLeads(Page):
    """Read one page of leads; Kenect defaults to the past seven days."""
    operation: Literal["list_leads"] = Field("list_leads", json_schema_extra={"ui:hidden": True})
    startDate: str | None = None


class ListBroadcastMessages(DateRange):
    """Read one page of broadcast messages."""
    operation: Literal["list_broadcast_messages"] = Field("list_broadcast_messages", json_schema_extra={"ui:hidden": True})
    pageSize: int = Field(100, ge=1, le=100)
    page: int = Field(1, ge=1)


class ListConversations(Page, DateRange):
    """Read one page of conversations in the selected location."""
    operation: Literal["list_conversations"] = Field("list_conversations", json_schema_extra={"ui:hidden": True})


class ListMessagesByPhone(Page):
    """Read a page of messages for a contact's phone number."""
    operation: Literal["list_messages_by_phone"] = Field("list_messages_by_phone", json_schema_extra={"ui:hidden": True})
    phoneNumber: Phone


class GetConversationByPhone(Page):
    """Get a conversation and one page of its messages by phone number."""
    operation: Literal["get_conversation_by_phone"] = Field("get_conversation_by_phone", json_schema_extra={"ui:hidden": True})
    phoneNumber: Phone


class ListConversationsByContact(Page):
    """Read conversations by the contact ID in your external system."""
    operation: Literal["list_conversations_by_contact"] = Field("list_conversations_by_contact", json_schema_extra={"ui:hidden": True})
    contactExternalId: Text


class GetAttachmentInfo(Input):
    """Read attachment metadata; this operation does not download its URL."""
    operation: Literal["get_attachment_info"] = Field("get_attachment_info", json_schema_extra={"ui:hidden": True})
    attachmentId: int = Field(..., ge=1)
    messageId: int = Field(..., ge=1)


class Attachment(Input):
    name: Text = Field(..., description="The path returned by Kenect's pre-sign API after uploading the attachment.")


class SendMessage(Input):
    """Send a custom text message with optional already-uploaded attachments."""
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={"ui:hidden": True})
    contactPhone: Phone
    messageBody: Text
    contactName: str | None = None
    externalContactId: str | None = None
    sentByUserEmail: str | None = None
    attachments: list[Attachment] | None = None


class SendReviewRequest(Input):
    """Send a review request using the current, non-deprecated review endpoint."""
    operation: Literal["send_review_request"] = Field("send_review_request", json_schema_extra={"ui:hidden": True})
    phoneNumber: Phone
    messageBody: Text
    externalContactId: str | None = None
    firstName: str | None = None
    lastName: str | None = None
    email: str | None = None


class CreateLead(Input):
    """Submit a lead with an external lead ID for Kenect."""
    operation: Literal["create_lead"] = Field("create_lead", json_schema_extra={"ui:hidden": True})
    partnerLeadId: Text
    firstName: Text
    lastName: Text
    phoneNumber: Phone
    email: str | None = None
    inquiryText: str | None = None
    attachments: list[Attachment] | None = None


class NotifyEvent(Input):
    """Queue an event previously configured in Kenect for automated messaging."""
    operation: Literal["notify_event"] = Field("notify_event", json_schema_extra={"ui:hidden": True})
    eventName: Text
    phone: Phone
    recordId: Text
    assignedUserEmail: str | None = None
    externalContactId: str | None = None
    eventData: dict[str, str] | None = None


class Contact(Input):
    firstName: str
    lastName: str
    mobilePhone: Phone
    externalId: Text
    primaryEmail: str | None = None
    birthday: int | None = Field(None, description="Unix timestamp in milliseconds.")
    contactPhones: list[str] | None = None
    addressLine1: str | None = None
    addressLine2: str | None = None
    city: str | None = None
    state: str | None = None
    zipCode: str | None = None


class SyncContacts(Input):
    """Send a batch of up to 500 contacts to Kenect."""
    operation: Literal["sync_contacts"] = Field("sync_contacts", json_schema_extra={"ui:hidden": True})
    contacts: list[Contact] = Field(..., min_length=1, max_length=500)
    totalCount: int = Field(..., ge=1, description="Total contacts in the sync, possibly larger than this batch.")


KenectConfig = Annotated[Union[
    ListLocations, ListUsers, GetUser, ListLeads, ListBroadcastMessages,
    ListConversations, ListMessagesByPhone, GetConversationByPhone,
    ListConversationsByContact, GetAttachmentInfo, SendMessage,
    SendReviewRequest, CreateLead, NotifyEvent, SyncContacts,
], Field(discriminator="operation")]


class KenectFullConfig(NodeConfig[KenectConfig, KenectAPIKeyCredential]):
    pass


# Every entry is exactly one operation in Kenect's OpenAPI 1.0.1 contract.
ROUTES = {
    "list_locations": ("GET", "/api/v1/locations", list),
    "list_users": ("GET", "/api/v1/users", list),
    "get_user": ("GET", "/api/v1/users/{userId}", dict),
    "list_leads": ("GET", "/api/v1/lead", None),
    "list_broadcast_messages": ("GET", "/api/v1/broadcast-messages", dict),
    "list_conversations": ("GET", "/api/v1/messages", list),
    "list_messages_by_phone": ("GET", "/api/v1/messages/by-phone-number", list),
    "get_conversation_by_phone": ("GET", "/api/v1/messages/conversations/by-phone-number", dict),
    "list_conversations_by_contact": ("GET", "/api/v1/messages/conversations/by-contact-external-id", list),
    "get_attachment_info": ("GET", "/api/v1/messages/attachment-info", dict),
    "send_message": ("POST", "/api/v1/messages", dict),
    "send_review_request": ("POST", "/api/v1/reviews/review-request", dict),
    "create_lead": ("POST", "/api/v1/lead", dict),
    "notify_event": ("POST", "/api/v1/events/notify", None),
    "sync_contacts": ("POST", "/api/v1/contact/batch", None),
}


def _redact(value, credential):
    if isinstance(value, str):
        for secret in (credential.api_key, credential.api_secret):
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, credential) for item in value]
    if isinstance(value, dict):
        return {_redact(k, credential): _redact(v, credential) for k, v in value.items()}
    return value


class KenectTextMessagingNode(WorkflowNode):
    integration_type = "automation-kenect-text-messaging"
    connection_evidence = ConnectionEvidence(
        noun="Kenect locations", operation="list_locations",
        label_keys=("locationName", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return KenectFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, KenectFullConfig) or self.config.credentials is None:
            raise ValueError("Connect a Kenect API key and secret with a location ID")
        credential, op = self.config.credentials, self.config.config
        method, path, expected = ROUTES[op.operation]
        values = op.model_dump(exclude={"operation"}, exclude_none=True)
        if isinstance(op, GetUser):
            path = path.replace("{userId}", str(values.pop("userId")))
        headers = {"X-Api-Key": credential.api_key, "X-Api-Secret": credential.api_secret,
                   "X-Location-Id": credential.kenect_location_id, "Accept": "application/json"}
        # Only code-owned Kenect routes; redirects are refused so credentials
        # cannot be forwarded to another origin. Mutations are never retried.
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers,
                    **({"params": values} if method == "GET" else {"json": values}))
        except httpx.HTTPError:
            raise ValueError("Kenect request did not complete; inspect Kenect before retrying a write") from None
        if not 200 <= response.status_code < 300:
            detail = _redact(response.text[:2000], credential)
            return {"status": "error", "http_status": response.status_code,
                    "error": detail or "Kenect rejected the request"}
        if response.status_code == 204 or not response.content:
            if response.status_code != 204 and op.operation not in {"notify_event", "sync_contacts"}:
                raise ValueError("Kenect returned an empty response where JSON was expected")
            body = None
        else:
            try:
                body = response.json()
            except ValueError:
                raise ValueError("Kenect returned invalid JSON; inspect Kenect before retrying a write") from None
            if isinstance(body, dict) and (body.get("error") or body.get("success") is False):
                return {"status": "error", "http_status": response.status_code, "error": _redact(body, credential)}
            if expected is not None and not isinstance(body, expected):
                raise ValueError("Kenect returned an unexpected response shape")
        return {"status": "success", "operation": op.operation,
                "http_status": response.status_code, "data": _redact(body, credential)}
