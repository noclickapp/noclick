"""BulkSMS JSON REST API v1 operations (published contract version 1.1.0)."""
from __future__ import annotations

import base64
import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.bulksms.com/v1"

class BulkSMSComAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="BulkSMS.com API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.bulksms.com/developer/json/v1/#section/Authentication",
            "x-credential-instructions": "In BulkSMS.com, open Settings > Developer Settings > API Tokens. Paste the token ID and token secret. NoClick uses these as HTTP Basic credentials and checks your profile."})
    credential_type: Literal["bulksmscom_api_token"] = Field("bulksmscom_api_token", json_schema_extra={"ui:hidden": True})
    token_id: str = Field(..., title="Token ID", min_length=1, json_schema_extra={"ui:widget": "password"})
    token_secret: str = Field(..., title="Token secret", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("token_id", "token_secret", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(ord(c) < 33 or ord(c) == 127 for c in value) or (info.field_name == "token_id" and ":" in value):
            raise ValueError("Paste the token value without a header, colon in the ID, or whitespace")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class GetProfile(_Input):
    """Read your account profile, credit balance and quota."""
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra={"ui:hidden": True})

class SendMessages(_Input):
    """Submit an SMS to one or more international numbers; submission does not prove delivery."""
    operation: Literal["send_messages"] = Field("send_messages", json_schema_extra={"ui:hidden": True})
    to: list[str] = Field(..., min_length=1, max_length=1000, title="Recipient numbers", description="International phone numbers, including country code.")
    body: str = Field(..., min_length=1, title="Message text")
    sender_address: str | None = Field(None, title="Sender address", description="Approved international number or alphanumeric sender.")
    encoding: Literal["TEXT", "UNICODE"] | None = None
    routing_group: Literal["ECONOMY", "STANDARD", "PREMIUM"] | None = None
    user_supplied_id: str | None = None
    long_message_max_parts: int | None = Field(None, ge=1, le=99)
    delivery_reports: Literal["ALL", "ERRORS", "NONE"] | None = None
    auto_unicode: bool | None = None
    deduplication_id: int | None = Field(None, description="Reuse the same positive ID when retrying the same submission.", ge=1)
    schedule_date: str | None = Field(None, description="ISO 8601 date-time with seconds and UTC offset.")
    schedule_description: str | None = None

    @field_validator("to")
    @classmethod
    def numbers(cls, value):
        if any(not re.fullmatch(r"\+?[0-9]{3,20}", n) for n in value):
            raise ValueError("Use international phone numbers with country codes")
        return value

    @field_validator("schedule_date")
    @classmethod
    def date(cls, value):
        if value is not None:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(Z|[+-][0-9]{2}:[0-9]{2})", value):
                raise ValueError("Use a date-time with seconds and timezone")
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

class ListMessages(_Input):
    """Read a bounded message page; use an id filter to fetch subsequent pages."""
    operation: Literal["list_messages"] = Field("list_messages", json_schema_extra={"ui:hidden": True})
    limit: int = Field(100, ge=1, le=1000)
    filter: str | None = Field(None, description="Unencoded clauses, e.g. type=SENT&id<123456. NoClick URL-encodes this once.")
    sort_order: Literal["ASCENDING"] | None = Field(None, description="Omit for the default descending order.")

class _MessageID(_Input):
    message_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")

class GetMessage(_MessageID):
    """Read one sent or received message by ID."""
    operation: Literal["get_message"] = Field("get_message", json_schema_extra={"ui:hidden": True})

class ListRelatedMessages(_MessageID):
    """Read replies related to a sent message."""
    operation: Literal["list_related_messages"] = Field("list_related_messages", json_schema_extra={"ui:hidden": True})

class ListBlockedNumbers(_Input):
    """Read a bounded blocked-number page; continue with last id plus one as min_id."""
    operation: Literal["list_blocked_numbers"] = Field("list_blocked_numbers", json_schema_extra={"ui:hidden": True})
    min_id: int = Field(0, ge=0)
    limit: int = Field(100, ge=1, le=10000)

class CreateBlockedNumbers(_Input):
    """Block up to 1000 phone numbers from receiving messages from your account."""
    operation: Literal["create_blocked_numbers"] = Field("create_blocked_numbers", json_schema_extra={"ui:hidden": True})
    phone_numbers: list[str] = Field(..., min_length=1, max_length=1000)
    _numbers = field_validator("phone_numbers")(SendMessages.numbers.__func__)

class ListWebhooks(_Input):
    """List your account's registered message webhooks."""
    operation: Literal["list_webhooks"] = Field("list_webhooks", json_schema_extra={"ui:hidden": True})

class _WebhookID(_Input):
    webhook_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")

class GetWebhook(_WebhookID):
    """Read a registered webhook."""
    operation: Literal["get_webhook"] = Field("get_webhook", json_schema_extra={"ui:hidden": True})

class DeleteWebhook(_WebhookID):
    """Delete a registered webhook."""
    operation: Literal["delete_webhook"] = Field("delete_webhook", json_schema_extra={"ui:hidden": True})

class _WebhookEntry(_Input):
    name: str = Field(..., min_length=1)
    url: str = Field(..., pattern=r"^https?://[^\s]+$", title="Webhook URL")
    trigger_scope: Literal["SENT", "RECEIVED"]
    contact_email_address: str | None = Field(None, description="Optional problem-report email address; null disables email.")
    invoke_option: Literal["ONE", "MANY"] = "MANY"
    active: bool = Field(True, description="BulkSMS validates active URLs by POSTing an empty array.")
    on_web_app: bool = True

class CreateWebhook(_WebhookEntry):
    """Register a status or inbound-message webhook with BulkSMS."""
    operation: Literal["create_webhook"] = Field("create_webhook", json_schema_extra={"ui:hidden": True})

class UpdateWebhook(_WebhookEntry, _WebhookID):
    """Replace a webhook's settings with the supplied values."""
    operation: Literal["update_webhook"] = Field("update_webhook", json_schema_extra={"ui:hidden": True})

BulkSMSComConfig = Annotated[Union[GetProfile, SendMessages, ListMessages, GetMessage,
    ListRelatedMessages, ListBlockedNumbers, CreateBlockedNumbers, ListWebhooks,
    GetWebhook, CreateWebhook, UpdateWebhook, DeleteWebhook], Field(discriminator="operation")]

class BulkSMSComFullConfig(NodeConfig[BulkSMSComConfig, BulkSMSComAPITokenCredential]):
    pass

ROUTES = {
    "get_profile": ("GET", "/profile"),
    "send_messages": ("POST", "/messages"),
    "list_messages": ("GET", "/messages"),
    "get_message": ("GET", "/messages/{message_id}"),
    "list_related_messages": ("GET", "/messages/{message_id}/relatedReceivedMessages"),
    "list_blocked_numbers": ("GET", "/blocked-numbers"),
    "create_blocked_numbers": ("POST", "/blocked-numbers"),
    "list_webhooks": ("GET", "/webhooks"),
    "get_webhook": ("GET", "/webhooks/{webhook_id}"),
    "create_webhook": ("POST", "/webhooks"),
    "update_webhook": ("POST", "/webhooks/{webhook_id}"),
    "delete_webhook": ("DELETE", "/webhooks/{webhook_id}"),
}

class BulkSMSComNode(WorkflowNode):
    integration_type = "automation-bulksmscom"
    connection_evidence = ConnectionEvidence(
        noun="BulkSMS.com profile", identity_operation="get_profile", identity_keys=("username", "id")
    )

    @classmethod
    def get_config_model(cls):
        return BulkSMSComFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a BulkSMS.com API token")
        method, path = ROUTES[config.operation]
        for name in ("message_id", "webhook_id"):
            if hasattr(config, name):
                path = path.replace("{" + name + "}", quote(getattr(config, name), safe=""))
        params, body = {}, None
        if isinstance(config, SendMessages):
            body = [{"to": [{"type": "INTERNATIONAL", "address": number} for number in config.to], "body": config.body}]
            for src, dest in {"encoding": "encoding", "routing_group": "routingGroup", "user_supplied_id": "userSuppliedId", "long_message_max_parts": "longMessageMaxParts", "delivery_reports": "deliveryReports"}.items():
                value = getattr(config, src)
                if value is not None: body[0][dest] = value
            if config.sender_address is not None:
                body[0]["from"] = {"type": "ALPHANUMERIC" if not re.fullmatch(r"\+?[0-9]+", config.sender_address) else "INTERNATIONAL", "address": config.sender_address}
            for src, dest in {"auto_unicode": "auto-unicode", "deduplication_id": "deduplication-id", "schedule_date": "schedule-date", "schedule_description": "schedule-description"}.items():
                value = getattr(config, src)
                if value is not None: params[dest] = str(value).lower() if isinstance(value, bool) else value
        elif isinstance(config, ListMessages):
            params = {"limit": config.limit}
            if config.filter is not None: params["filter"] = config.filter
            if config.sort_order is not None: params["sortOrder"] = config.sort_order
        elif isinstance(config, ListBlockedNumbers):
            params = {"min-id": config.min_id, "limit": config.limit}
        elif isinstance(config, CreateBlockedNumbers):
            body = config.phone_numbers
        elif isinstance(config, _WebhookEntry):
            body = {"name": config.name, "url": config.url, "triggerScope": config.trigger_scope,
                "invokeOption": config.invoke_option,
                "active": config.active, "onWebApp": config.on_web_app}
            if config.contact_email_address is not None:
                body["contactEmailAddress"] = config.contact_email_address
        auth = base64.b64encode((credential.token_id + ":" + credential.token_secret).encode()).decode()
        headers = {"Authorization": "Basic " + auth, "Content-Type": "application/json", "Accept": "application/json"}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params, headers=headers, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            try:
                error = response.json()
                detail = error.get("detail") or error.get("title") or "BulkSMS.com rejected the request"
            except (ValueError, AttributeError):
                detail = "BulkSMS.com returned HTTP " + str(response.status_code)
            detail = str(detail).replace(credential.token_id, "[redacted]").replace(credential.token_secret, "[redacted]").replace(auth, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": detail}
        if config.operation in {"delete_webhook", "create_blocked_numbers"}:
            return {"status": "success", "http_status": response.status_code, "acknowledged": True}
        data = response.json()
        list_ops = {"send_messages", "list_messages", "list_related_messages", "list_blocked_numbers", "list_webhooks"}
        if not isinstance(data, list if config.operation in list_ops else dict):
            raise ValueError("Unexpected BulkSMS.com response shape")
        if config.operation == "get_profile" and any(
            not isinstance(data.get(key), str) or not data[key].strip() for key in ("id", "username")
        ):
            raise ValueError("BulkSMS.com profile did not identify an account")
        return {"status": "success", "http_status": response.status_code, "data": data}
