"""Mobile Message v2 SMS, contact and list automation from the published OpenAPI.

Each action maps to one documented endpoint; account webhooks deliver inbound
SMS/opt-outs and multipart delivery receipts without assuming arrival order.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from datetime import date
from typing import Annotated, Any, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE = "https://api.mobilemessage.com.au"
CREDENTIAL = "mobile_message_ca21345_api"
DOCS = "https://mobilemessage.com.au/api-documentation"


class MobileMessageCredential(BaseModel):
    model_config = ConfigDict(title="Mobile Message API", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "api_key",
        "x-credential-url": "https://app.mobilemessage.com.au/",
        "x-credential-instructions": "In Mobile Message, open Settings → API and copy an API username and password. These are API credentials, not your dashboard login. For signed triggers, also paste the Webhook Signing Secret from that page. Leave that field empty only if signing is disabled on the account.",
    })
    credential_type: Literal["mobile_message_ca21345_api"] = Field(CREDENTIAL, json_schema_extra={"ui:hidden": True})
    api_username: str = Field(..., min_length=1, title="API username")
    api_password: str = Field(..., min_length=1, title="API password", json_schema_extra={"ui:widget": "password"})
    webhook_signing_secret: str | None = Field(None, title="Webhook signing secret", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_username", "api_password", "webhook_signing_secret", mode="before")
    @classmethod
    def credential_text(cls, value, info):
        if value is None and info.field_name == "webhook_signing_secret":
            return None
        value = clean_secret(value, field_name=info.field_name)
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("API credentials must not contain control characters")
        if info.field_name == "api_username" and ":" in value:
            raise ValueError("The API username must not contain a colon")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def valid_selection(self):
        operation = getattr(self, "operation", None)
        if operation in {"cancel_scheduled_messages", "get_link_tracking"}:
            if sum(getattr(self, key, None) is not None for key in ("message_id", "send_id", "custom_ref")) != 1:
                raise ValueError("Supply exactly one of message_id, send_id or custom_ref")
        if operation in {"add_list_member", "remove_list_member"}:
            if sum(getattr(self, key, None) is not None for key in ("contact_id", "number")) != 1:
                raise ValueError("Supply exactly one contact_id or number")
        if operation == "update_contact" and not self.model_dump(exclude_none=True, exclude={"operation", "contact_id"}):
            raise ValueError("Supply at least one contact field to update")
        return self


def text(title, required=False, description=""):
    return (str if required else str | None, Field(... if required else None, title=title,
            min_length=1 if required else None, description=description))


def identifier(title, required=False):
    return (int if required else int | None, Field(... if required else None, title=title, ge=1))


PAGE = {"limit": (int, Field(50, ge=1, le=200, title="Page size")),
        "offset": (int, Field(0, ge=0, title="Offset"))}
DATES = {"from_date": (date | None, Field(None, title="From date", description="Inclusive UTC date")),
         "to_date": (date | None, Field(None, title="To date", description="Exclusive UTC date"))}
CONTACT_FIELDS = {key: text(key.replace("_", " ").title())
                  for key in ("number", "first_name", "last_name", "company", "other", "field_1", "field_2", "field_3", "field_4", "field_5")}
SEND_OPTIONS = {
    "enable_unicode": (bool, Field(False, description="Enable UCS-2; otherwise the provider strips non-GSM characters.")),
    "max_parts": (int, Field(10, ge=1, le=99, description="Maximum SMS parts charged per message.")),
    "ignore_unsubscribes": (bool, Field(False, description="Explicitly bypass the account unsubscribe list.")),
    "shorten_urls": (Union[bool, Literal["auto"], None], Field(None, description="Omit to use the account default; auto falls back to original links.")),
}
SELECTOR = {"message_id": (UUID | None, Field(None, title="Message ID")),
            "send_id": identifier("Send ID"), "custom_ref": text("Custom reference")}
MEMBER = {"list_id": identifier("List ID", True), "contact_id": identifier("Contact ID"), "number": text("Phone number")}


class Message(Input):
    to: str = Field(..., min_length=1, title="Recipient", description="Australian local or international phone number.")
    message: str = Field(..., min_length=1, title="SMS content")
    sender: str = Field(..., min_length=1, title="Sender ID", description="An active sender on your Mobile Message account.")
    custom_ref: str | None = None
    unicode: bool | None = Field(None, description="Override Unicode for this message.")
    scheduled_for: str | None = Field(None, description="UTC ISO 8601 datetime. Values less than 60 seconds ahead send immediately.")
    shorten_urls: Union[bool, Literal["auto"], None] = None


# Explicit endpoint and field catalog, not a user-supplied HTTP interface.
# name: (label, method, path, fields); GET fields become query, others JSON.
OPERATIONS = {
    "send_messages": ("Send SMS Messages", "POST", "/v1/messages", {
        "messages": (list[Message], Field(..., min_length=1, max_length=10000, title="Messages", json_schema_extra={"ui:widget": "json"})),
        **SEND_OPTIONS, "idempotency_key": (str | None, Field(None, max_length=255, description="Reuse with identical content within 24 hours to avoid duplicate sends."))}),
    "get_messages": ("Get Messages or Sent History", "GET", "/v1/messages", {
        "message_id": SELECTOR["message_id"], "custom_ref": text("Custom reference"),
        "status": (Literal["pending", "scheduled", "sent", "delivered", "failed", "cancelled"] | None, None), **DATES, **PAGE}),
    "cancel_scheduled_messages": ("Cancel Scheduled Messages", "DELETE", "/v1/messages", SELECTOR),
    "send_to_list": ("Send SMS to Contact List", "POST", "/v1/list-send", {
        "list_id": identifier("List ID", True), "sender": text("Sender ID", True), "message": text("SMS content", True),
        "custom_ref": text("Custom reference"), **SEND_OPTIONS,
        "scheduled_for": text("Scheduled for", description="UTC ISO 8601 datetime. Values less than 60 seconds ahead send immediately."),
        "stagger_minutes": (int | None, Field(None, ge=1)),
        "idempotency_key": (str | None, Field(None, max_length=255, description="Reuse with identical content within 24 hours to avoid duplicate sends."))}),
    "get_send": ("Get Send Status", "GET", "/v1/sends", {"send_id": identifier("Send ID", True)}),
    "get_link_tracking": ("Get Link Click Results", "GET", "/v1/link-tracking", {
        **SELECTOR, "include": (Literal["recipients"] | None, None), "clicked": (bool | None, None), **PAGE}),
    "list_contacts": ("List Contacts", "GET", "/v1/contacts", {**CONTACT_FIELDS, **PAGE}),
    "create_contact": ("Create Contact", "POST", "/v1/contacts", {**CONTACT_FIELDS, "number": text("Phone number", True)}),
    "update_contact": ("Update Contact", "PATCH", "/v1/contacts", {"contact_id": identifier("Contact ID", True), **CONTACT_FIELDS}),
    "delete_contact": ("Delete Contact", "DELETE", "/v1/contacts", {"contact_id": identifier("Contact ID", True)}),
    "list_lists": ("List Contact Lists", "GET", "/v1/lists", {}),
    "create_list": ("Create Contact List", "POST", "/v1/lists", {"name": text("List name", True)}),
    "rename_list": ("Rename Contact List", "PATCH", "/v1/lists", {"list_id": identifier("List ID", True), "name": text("New list name", True)}),
    "delete_list": ("Delete Contact List", "DELETE", "/v1/lists", {
        "list_id": identifier("List ID", True), "delete_contacts": (bool, Field(False, description="Also permanently delete every contact in this list."))}),
    "list_members": ("List Contacts in List", "GET", "/v1/list-contacts", {"list_id": identifier("List ID", True), **PAGE}),
    "add_list_member": ("Add Contact to List", "POST", "/v1/list-contacts", MEMBER),
    "remove_list_member": ("Remove Contact from List", "DELETE", "/v1/list-contacts", MEMBER),
    "list_unsubscribes": ("List Unsubscribed Numbers", "GET", "/v1/unsubscribes", {"number": text("Phone number"), **PAGE}),
    "add_unsubscribe": ("Unsubscribe Number", "POST", "/v1/unsubscribes", {"number": text("Phone number", True)}),
    "remove_unsubscribe": ("Resubscribe Number", "DELETE", "/v1/unsubscribes", {"number": text("Phone number", True)}),
    "get_account_balance": ("Get Account Credit Balance", "GET", "/v1/account", {}),
    "list_senders": ("List Sender IDs", "GET", "/v1/senders", {}),
    "list_inbound": ("List Inbound SMS", "GET", "/v1/inbound", {**DATES, **PAGE}),
}

CONFIG_MODELS = {}
for name, (label, method, path, fields) in OPERATIONS.items():
    model = create_model("MobileMessage" + name.title().replace("_", "") + "Config", __base__=Input, __module__=__name__,
        operation=(Literal[name], Field(name, title=label, json_schema_extra={
            "ui:hidden": True, "x-display-name": label, "x-is-trigger": False,
            "x-category": "Messages" if path in {"/v1/messages", "/v1/list-send", "/v1/sends", "/v1/link-tracking", "/v1/inbound"} else "Contacts and Account",
        })), **fields)
    CONFIG_MODELS[name] = model
    globals()[model.__name__] = model


class OnInboundSMS(WebhookTriggerConfigBase):
    operation: Literal["on_inbound_sms"] = Field("on_inbound_sms", title="On Inbound SMS or Opt-out", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On Inbound SMS or Opt-out", "x-category": "Triggers", "x-is-trigger": True})
    replace_webhook_url: str | None = Field(None, title="Existing webhook URL to replace", description="Optional: paste the exact existing URL to explicitly replace it. Leave empty to refuse replacement.")
    webhook_url: str | None = Field(None, title="Webhook URL", description="One inbound URL per account; an existing different URL must be removed first.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class OnDeliveryReceipt(WebhookTriggerConfigBase):
    operation: Literal["on_delivery_receipt"] = Field("on_delivery_receipt", title="On SMS Delivery Receipt", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On SMS Delivery Receipt", "x-category": "Triggers", "x-is-trigger": True})
    replace_webhook_url: str | None = Field(None, title="Existing webhook URL to replace", description="Optional: paste the exact existing URL to explicitly replace it. Leave empty to refuse replacement.")
    webhook_url: str | None = Field(None, title="Webhook URL", description="One status URL per account; receipts arrive once per message part.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


MobileMessageConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (OnInboundSMS, OnDeliveryReceipt)], Field(discriminator="operation")]


class MobileMessageNodeConfig(NodeConfig[MobileMessageConfig, MobileMessageCredential]):
    pass


class MobileMessageNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-mobile-message-ca21345"
    connection_evidence = ConnectionEvidence(operation="list_lists", noun="contact lists")
    webhook_signing_secret_not_issued = True  # Optional secret is generated in the dashboard, not by registration.

    @classmethod
    def get_config_model(cls):
        return MobileMessageNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None, idempotency_key=None):
        credential = MobileMessageCredential.model_validate(credential)
        auth = base64.b64encode(f"{credential.api_username}:{credential.api_password}".encode()).decode()
        headers = {"Authorization": "Basic " + auth, "Accept": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            async with httpx.AsyncClient(timeout=45, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params, json=body, headers=headers)
        except httpx.HTTPError:
            raise ValueError("Mobile Message request did not complete; inspect send history before retrying a write") from None
        try:
            data = response.json()
        except ValueError:
            raise ValueError(f"Mobile Message returned a non-JSON response (HTTP {response.status_code})") from None
        if not isinstance(data, dict):
            raise ValueError("Mobile Message returned an unexpected response")
        if not 200 <= response.status_code < 300 or "error" in data:
            error = str(data.get("error") or "Request failed")
            # Preserve provider rejection text without echoing any supplied secrets.
            for secret in (credential.api_username, credential.api_password, credential.webhook_signing_secret):
                if secret:
                    error = error.replace(secret, "[redacted]")
            raise ValueError(f"Mobile Message HTTP {response.status_code}: {error}")
        return data

    async def execute(self, inputs):
        op = self.config.config
        if op.operation in {"on_inbound_sms", "on_delivery_receipt"}:
            payload = self.node_data.get("config", {}).get("_triggerPayload")
            return payload if payload else self.no_event_output(op.operation, "Waiting for a Mobile Message webhook")
        if not self.config.credentials:
            raise ValueError("Connect a Mobile Message API credential")
        _, method, path, _ = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        key = values.pop("idempotency_key", None)
        for source, target in (("from_date", "from"), ("to_date", "to")):
            if source in values:
                values[target] = values.pop(source)
        data = await self._request(self.config.credentials.model_dump(), method, path,
            params=values if method == "GET" else None,
            body=values if method != "GET" else None, idempotency_key=key)
        # Keep the provider envelope and per-message error statuses intact: HTTP 200 is not delivery.
        return {"operation": op.operation, "data": data}

    @classmethod
    def _webhook_type(cls, config):
        operation = (config or {}).get("operation")
        if operation not in {"on_inbound_sms", "on_delivery_receipt"}:
            raise ValueError("Choose a Mobile Message trigger")
        return "inbound" if operation == "on_inbound_sms" else "status"

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        kind = cls._webhook_type(config)
        current = await cls._request(credential, "GET", "/v1/webhooks")
        previous = current.get("webhooks", {}).get(kind)
        if previous and previous != webhook_url and previous != config.get("replace_webhook_url"):
            raise ValueError(f"Mobile Message already has a different {kind} webhook URL. Remove it in Settings → API or paste that exact URL in Existing webhook URL to replace.")
        secret = credential.get("webhook_signing_secret")
        if current.get("has_signing_secret") and not secret:
            raise ValueError("Paste the account Webhook Signing Secret in the Mobile Message credential")
        if secret and not current.get("has_signing_secret"):
            raise ValueError("Enable webhook signing in Mobile Message Settings → API before using this secret")
        await cls._request(credential, "POST", "/v1/webhooks", body={"type": kind, "url": webhook_url})
        return {"external_webhook_id": kind, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if not credential or not config.get("external_webhook_id"):
            return
        # Teardown may follow an operation change: the registration's stored type
        # owns the endpoint, rather than the operation currently in the editor.
        kind = config["external_webhook_id"]
        if kind not in {"inbound", "status"}:
            raise ValueError("Unknown Mobile Message webhook registration type")
        expected_url = config.get("webhook_url")
        if config.get("webhook_id"):
            from utils.webhook_delivery import get_webhook_url
            expected_url = get_webhook_url(str(config["webhook_id"]))
        if not expected_url:
            raise ValueError("The registered Mobile Message webhook URL is needed for safe cleanup")
        current = await cls._request(credential, "GET", "/v1/webhooks")
        if current.get("webhooks", {}).get(kind) == expected_url:
            await cls._request(credential, "DELETE", "/v1/webhooks", body={"type": kind})

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"replace_webhook_url": (config or {}).get("replace_webhook_url")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        headers = {key.lower(): str(value) for key, value in headers.items()}
        secret = (config or {}).get("signing_secret")
        if not secret:
            return not headers.get("x-mm-signature") and not headers.get("x-mm-timestamp")
        stamp, signature = headers.get("x-mm-timestamp", ""), headers.get("x-mm-signature", "")
        if not re.fullmatch(r"[0-9]{1,12}", stamp) or abs(time.time() - int(stamp)) > 300:
            return False
        if not re.fullmatch(r"[0-9a-f]{64}", signature):
            return False
        expected = hmac.new(str(secret).encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        # Inspect the common envelope first; each event family's unique fields are read only after routing.
        if not isinstance(payload, dict) or not all(isinstance(payload.get(k), str) for k in ("to", "sender", "message", "received_at")):
            return False
        if cls._webhook_type(config) == "inbound":
            return "type" in payload and payload.get("type") in {"inbound", "unsubscribe"}
        return "status" in payload and payload.get("status") in {"delivered", "failed"}

    @classmethod
    def resolve_agent_event(cls, output):
        if "type" in output and output.get("type") in {"inbound", "unsubscribe"}:
            kind = "opted out" if output["type"] == "unsubscribe" else "sent an SMS"
            ref = output.get("original_custom_ref") or ""
            original = output.get("original_message_id") or ""
            text = (f"Mobile Message: {output.get('sender')} {kind} to {output.get('to')} at {output.get('received_at')}.\n"
                    f"SMS: {output.get('message')}\nOriginal message ID: {original}; custom reference: {ref}.\n"
                    "To reply, use send_messages with the sender number as to and your receiving number as sender. Respect opt-outs.")
            return {"text": text, "conversation_key": f"mobile-message:{output.get('to')}:{output.get('sender')}"}
        if "status" in output and output.get("status") in {"delivered", "failed"}:
            mid = output.get("message_id") or ""
            text = (f"Mobile Message SMS {output.get('status')}: from {output.get('sender')} to {output.get('to')} at {output.get('received_at')}.\n"
                    f"SMS: {output.get('message')}\nMessage ID: {mid}; custom reference: {output.get('custom_ref') or ''}; "
                    f"part {output.get('part_number')} of {output.get('total_parts')}.\n"
                    "Use get_messages with message_id to inspect the whole message; this receipt covers one part.")
            return {"text": text, "conversation_key": f"mobile-message:{mid}"}
        return None
