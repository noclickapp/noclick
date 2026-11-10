"""Funnelchat v0: fixed API operations and signed conversation webhooks.

Contract: https://developers-portal.funnelchat.app/specs/funnelchat.json
Webhook verification: https://developers-portal.funnelchat.app/ia/recibir-mensajes.md
Lists return a single provider page, including its pagination metadata.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE_URL = "https://api.funnelchat.com"
DOCS = "https://developers-portal.funnelchat.app/docs/recibir-mensajes/"


class FunnelchatAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Funnelchat API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://accounts.funnelchat.app/desarrolladores",
            "x-credential-instructions": "Paste the full API key, including its id|fc_live_ prefix, from Developers → Create key. Select read/write permissions for the areas you automate. Triggers also need Webhooks → Manage and Contacts and conversations → View. Keys are workspace-specific. NoClick checks the key by reading your WhatsApp numbers."})
    credential_type: Literal["funnelchat_api_key"] = Field("funnelchat_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the full API key, without Authorization or Bearer")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def semantic_requirements(self):
        op = getattr(self, "operation", "")
        if op in {"create_contact", "upsert_contact"} and not getattr(self, "phone", None):
            raise ValueError("Provide a phone number with its country code")
        if op in {"send_message", "send_template"}:
            if not any(getattr(self, k, None) for k in ("contact_id", "phone", "whatsapp_id")):
                raise ValueError("Provide a contact ID, phone number or WhatsApp ID")
        if op == "update_contact" and not self.model_fields_set - {"operation", "contact"}:
            raise ValueError("Provide a contact field to update")
        return self


class CustomFieldValue(Input):
    id: int = Field(..., ge=1, title="Custom field ID")
    value: str = Field(..., description="Always text, including numbers and dates; use the field's documented format.")


class TemplateVariables(Input):
    body: list[Optional[str]] = Field(default_factory=list, max_length=100)


# Each entry is one published operation; fields and dispatch share this fixed table.
@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    category: str
    fields: dict
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    shape: str = "object"


def text(title, *, required=False, **kw):
    return (str if required else Optional[str], Field(... if required else None, title=title, **kw))


def integer(title, *, required=False, **kw):
    return (int if required else Optional[int], Field(... if required else None, title=title, **kw))


def boolean(title):
    return (Optional[bool], Field(None, title=title))


def choice(title, values):
    return (Optional[Literal[tuple(values)]], Field(None, title=title))


PAGE = {"perPage": (int, Field(25, ge=1, le=100, title="Page size"))}
ORDER = {"orderByMethod": choice("Sort direction", ("asc", "desc"))}
CONTACT = {"contact": integer("Contact ID", required=True, ge=1)}
PROFILE = {"name": text("Name", max_length=255), "email": text("Email", max_length=255), "phone": text("Phone with country code", max_length=20)}
RECIPIENT = {"contact_id": integer("Contact ID", ge=1), "phone": text("Phone with country code", max_length=255), "whatsapp_id": text("WhatsApp ID", max_length=255)}
TAG_FIELDS = {"name": text("Tag name", required=True, max_length=254), "description": text("Description", max_length=1024), "color": text("Color", max_length=191)}
FIELD_VALUES = {"custom_fields": (Optional[list[CustomFieldValue]], Field(None, max_length=100, title="Custom field values"))}

OPERATIONS = {
    "list_contacts": Operation("GET", "/api/v1/contacts", "Contacts", {**PAGE, **PROFILE, **ORDER,
        "created_from": text("Created from", json_schema_extra={"format": "date-time"}),
        "created_to": text("Created to", json_schema_extra={"format": "date-time"}),
        "orderBy": choice("Sort field", ("id", "name", "email", "phone", "created_at", "updated_at"))},
        query=("perPage", "name", "email", "phone", "created_from", "created_to", "orderBy", "orderByMethod")),
    "get_contact": Operation("GET", "/api/v1/contacts/{contact}", "Contacts", CONTACT),
    "create_contact": Operation("POST", "/api/v1/contacts", "Contacts", {**PROFILE, "phone": text("Phone with country code", required=True, min_length=1), **FIELD_VALUES}, body=("name", "email", "phone", "custom_fields")),
    "upsert_contact": Operation("POST", "/api/v1/contacts/update-or-create", "Contacts", {**PROFILE, "phone": text("Phone with country code", required=True), **FIELD_VALUES}, body=("name", "email", "phone", "custom_fields")),
    "update_contact": Operation("PUT", "/api/v1/contacts/{contact}", "Contacts", {**CONTACT, **PROFILE,
        "notes": text("Notes", max_length=2500), "adviser_id": integer("Advisor ID", ge=1),
        "active_conversation": boolean("Conversation open"), "favorite": boolean("Favorite"),
        "manually_unread": boolean("Mark unread"), "can_execute_flows": boolean("Allow flows")},
        body=("name", "email", "phone", "notes", "adviser_id", "active_conversation", "favorite", "manually_unread", "can_execute_flows")),
    "add_contact_tag": Operation("POST", "/api/v1/contacts/add-tags", "Tags", {
        "contactId": integer("Contact ID", required=True, ge=1), "tag_id": integer("Tag ID", required=True, ge=1)}, shape="tag"),
    "remove_contact_tag": Operation("POST", "/api/v1/contacts/remove-tags", "Tags", {
        "contactId": integer("Contact ID", required=True, ge=1), "tag_id": integer("Tag ID", required=True, ge=1)}, shape="tag"),
    "list_tags": Operation("GET", "/api/v1/tags", "Tags", {**PAGE, **ORDER, "name": text("Tag name")}, query=("perPage", "name", "orderByMethod")),
    "create_tag": Operation("POST", "/api/v1/tags", "Tags", TAG_FIELDS, body=("name", "description", "color")),
    "update_tag": Operation("PUT", "/api/v1/tags/{tag}", "Tags", {"tag": integer("Tag ID", required=True, ge=1), **TAG_FIELDS}, body=("name", "description", "color")),
    "list_custom_fields": Operation("GET", "/api/v1/custom-fields", "Custom Fields", {**PAGE, "name": text("Field name")}, query=("perPage", "name")),
    "create_custom_field": Operation("POST", "/api/v1/custom-fields", "Custom Fields", {
        "name": text("Field name", required=True, max_length=254), "description": text("Description", max_length=1000),
        "type": (Literal[0, 1, 2, 3, 4], Field(..., title="Field type", description="0 Text, 1 Number, 2 Date, 3 URL, 4 Alphanumeric"))}, body=("name", "description", "type")),
    "set_contact_custom_field": Operation("POST", "/api/v1/contacts/attach-custom-field", "Custom Fields", {
        "contactId": integer("Contact ID", required=True, ge=1), "customFieldId": integer("Custom field ID", required=True, ge=1),
        "value": text("Value", required=True, description="Always text. Numbers: 99.90; dates: YYYY-MM-DD; URLs: full https:// URL.")},
        body=("contactId", "customFieldId", "value"), shape="array"),
    "remove_contact_custom_field": Operation("POST", "/api/v1/contacts/detach-custom-field", "Custom Fields", {
        "contactId": integer("Contact ID", required=True, ge=1), "customFieldId": integer("Custom field ID", required=True, ge=1)},
        body=("contactId", "customFieldId"), shape="array"),
    "list_conversations": Operation("GET", "/api/v1/conversations", "Conversations", {**PAGE,
        "cursor": text("Cursor"), "updated_since": text("Updated since"), "contactId": integer("Contact ID", ge=1),
        "deviceId": integer("Device ID", ge=1), "unreadMessages": boolean("Only unread"), "activeConversation": boolean("Only open conversations")},
        query=("perPage", "cursor", "updated_since", "contactId", "deviceId", "unreadMessages", "activeConversation")),
    "list_messages": Operation("GET", "/api/v1/contacts/{contactId}/messages", "Messages", {**PAGE,
        "contactId": integer("Contact ID", required=True, ge=1), "cursor": text("Cursor"), "updated_since": text("Updated since")},
        query=("perPage", "cursor", "updated_since")),
    "send_message": Operation("POST", "/api/v1/message/send-message", "Messages", {**RECIPIENT,
        "device_id": integer("Device ID", required=True, ge=1), "text": text("Message", required=True, min_length=1),
        "note": boolean("Internal note"), "client_reference": text("Client reference", max_length=64, pattern=r"^[\x21-\x7E]{1,64}$")},
        body=("device_id", "contact_id", "phone", "whatsapp_id", "text", "note", "client_reference")),
    "list_templates": Operation("GET", "/api/v1/templates", "Templates", {**PAGE, "name": text("Template name"), "deviceId": integer("Device ID", ge=1)}, query=("perPage", "name", "deviceId")),
    "send_template": Operation("POST", "/api/v1/devices/{device}/templates/{template}/send-template", "Templates", {**RECIPIENT,
        "device": integer("Device ID", required=True, ge=1), "template": text("Template ID", required=True, min_length=1),
        "template_variables": (Optional[TemplateVariables], Field(None, title="Template variables")),
        "client_reference": text("Client reference", max_length=64, pattern=r"^[\x21-\x7E]{1,64}$")},
        body=("contact_id", "phone", "whatsapp_id", "template_variables", "client_reference")),
    "list_flows": Operation("GET", "/api/v1/flows", "Flows", {**PAGE, **ORDER, "name": text("Flow name"),
        "status": choice("Status", ("active", "inactive"))}, query=("perPage", "name", "status", "orderByMethod")),
    "list_devices": Operation("GET", "/api/v1/devices", "Devices", {"external_reference": text("External reference", max_length=255)}, query=("external_reference",)),
    "get_device": Operation("GET", "/api/v1/devices/{device}", "Devices", {"device": integer("Device ID", required=True, ge=1)}),
}


def _config(name, spec):
    label = name.replace("_", " ").title()
    return create_model("Funnelchat" + name.title().replace("_", "") + "Config", __base__=Input, __module__=__name__,
        operation=(Literal[name], Field(name, title=label, json_schema_extra={"ui:hidden": True,
            "x-display-name": label, "x-category": spec.category, "x-is-trigger": False})), **spec.fields)


CONFIG_MODELS = {name: _config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
WEBHOOK_EVENTS = ("message.received", "message.status_changed", "contact.created", "contact.updated",
    "contact.tag_added", "contact.tag_removed", "conversation.closed", "conversation.assigned", "flow.completed", "flow.failed", "whatsapp_form.completed")


class FunnelchatOnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", title="On Funnelchat event", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Funnelchat Event"})
    event_type: Literal[*WEBHOOK_EVENTS] = Field("message.received", title="Event type")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", description="Registered automatically with Funnelchat.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


FunnelchatConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (FunnelchatOnEventConfig,)], Field(discriminator="operation")]


class FunnelchatNodeConfig(NodeConfig[FunnelchatConfig, FunnelchatAPIKeyCredential]):
    pass


class FunnelchatNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-funnelchat"
    connection_evidence = ConnectionEvidence(operation="list_devices", noun="WhatsApp numbers", label_keys=("name", "phone", "id"))
    webhook_replace_stale_endpoint = True
    edit_examples = ["Send a WhatsApp message with Funnelchat", "Create or update a Funnelchat contact", "When a contact replies, start this workflow"]

    @classmethod
    def get_config_model(cls):
        return FunnelchatNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        key = FunnelchatAPIKeyCredential.model_validate(credential).api_key
        # Paths are fixed above; identifiers are percent-encoded, and redirects never carry a key.
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, params=params,
                json=body, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
        if response.status_code >= 300:
            try:
                payload = response.json()
                detail = payload.get("message") or payload.get("error") if isinstance(payload, dict) else None
            except ValueError:
                detail = None
            message = str(detail or "Request failed").replace(key, "[redacted]")
            raise ValueError(f"Funnelchat API error {response.status_code}: {message}")
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            raise ValueError("Funnelchat returned a non-JSON response") from None

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Funnelchat API key")
        op = self.config.config
        if isinstance(op, FunnelchatOnEventConfig):
            return self.no_event_output("on_event")
        spec = OPERATIONS[op.operation]
        # exclude_unset keeps intentional nulls in updates while omitting untouched optional fields.
        values = op.model_dump(exclude_unset=True, exclude={"operation"})
        params = {k: getattr(op, k) for k in spec.query if getattr(op, k) is not None}
        path = spec.path
        for key in re.findall(r"\{([^}]+)\}", path):
            path = path.replace("{" + key + "}", quote(str(getattr(op, key)), safe=""))
        body = {k: values[k] for k in spec.body if k in values}
        if spec.shape == "tag":
            body = [{"contactId": op.contactId, "tag": {"id": op.tag_id}}]
        elif spec.shape == "array":
            body = [body]
        data = await self._request(self.config.credentials.model_dump(), spec.method, path,
            params=params or None, body=body if spec.method != "GET" else None)
        # These bulk endpoints return per-item failures with HTTP 200.
        if spec.shape in {"tag", "array"} and isinstance(data, list):
            if any(isinstance(row, dict) and isinstance(row.get("status"), int) and row["status"] >= 400 for row in data):
                return {"status": "error", "operation": op.operation, "data": data, "message": "Funnelchat rejected a requested change"}
        return {"status": "success", "operation": op.operation, "data": data}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = (config or {}).get("event_type", "message.received")
        if event not in WEBHOOK_EVENTS:
            raise ValueError("Choose a supported Funnelchat event")
        data = await cls._request(credential, "POST", "/api/v1/webhooks", body={"url": webhook_url, "events": [event]})
        if not isinstance(data, dict) or not data.get("id") or not data.get("secret"):
            raise ValueError("Funnelchat did not return the subscription ID and signing secret")
        return {"external_webhook_id": str(data["id"]), "signing_secret": data["secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = (config or {}).get("external_webhook_id")
        if identifier and credential:
            await cls._request(credential, "DELETE", "/api/v1/webhooks/" + quote(str(identifier), safe=""))

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "message.received")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        header = next((v for k, v in headers.items() if k.lower() == "x-funnelchat-signature"), "")
        if not isinstance(secret, str) or not secret or not isinstance(header, str):
            return False
        timestamps, signatures = [], []
        for part in header.split(","):
            name, separator, value = part.strip().partition("=")
            if separator and name == "t": timestamps.append(value)
            if separator and name == "v1": signatures.append(value)
        if len(timestamps) != 1 or not re.fullmatch(r"[0-9]{1,12}", timestamps[0]):
            return False
        timestamp = timestamps[0]
        if abs(int(time.time()) - int(timestamp)) > 300:
            return False
        expected = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256).hexdigest()
        return any(re.fullmatch(r"[a-f0-9]{64}", sig) and hmac.compare_digest(expected, sig) for sig in signatures)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return isinstance(payload, dict) and payload.get("type") == (config or {}).get("event_type", "message.received")

    @classmethod
    def should_propagate_output(cls, output, config):
        event = output.get("data") if isinstance(output.get("data"), dict) and "status" in output else output
        if (config or {}).get("operation") == "on_event":
            return isinstance(event, dict) and event.get("type") == (config or {}).get("event_type", "message.received")
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        event = output.get("data") if isinstance(output.get("data"), dict) and "status" in output else output
        if not isinstance(event, dict) or event.get("type") not in WEBHOOK_EVENTS:
            return None
        data = event.get("data")
        if not isinstance(data, dict):
            return None
        contact = data.get("contact") if isinstance(data.get("contact"), dict) else {}
        contact_id = contact.get("id") or data.get("contact_id")
        who = contact.get("name") or contact.get("phone") or str(contact_id or "Contact")
        title = f"Funnelchat {event['type']}: {who}"
        lines = [title]
        kind = event["type"]
        if kind == "message.received":
            message = data.get("message") or {}
            receiver = data.get("receiver") or {}
            lines += [f"Message: {message.get('text') or message.get('type')}",
                f"Message ID: {message.get('id')}; device ID: {data.get('device_id')}; received at: {receiver.get('phone')}"]
            if message.get("media"):
                lines.append("Media: " + json.dumps(message["media"], ensure_ascii=False))
        elif kind == "message.status_changed":
            lines += [f"Message {data.get('message_id')}: {data.get('previous_status')} → {data.get('status')}",
                f"Device ID: {data.get('device_id')}; reference: {data.get('client_reference')}"]
            if data.get("error"):
                lines.append("Provider error: " + json.dumps(data["error"], ensure_ascii=False))
        elif kind == "contact.updated":
            lines += ["Changed: " + ", ".join(data.get("changed") or []),
                "Custom fields: " + json.dumps(data.get("custom_fields") or [], ensure_ascii=False)]
        elif kind in {"contact.tag_added", "contact.tag_removed"}:
            tag = data.get("tag") or {}
            lines.append(f"Tag: {tag.get('name')} (ID {tag.get('id')}); source: {data.get('source')}")
        elif kind == "conversation.assigned":
            assignee = data.get("assignee") or {}
            lines.append(f"Assigned to: {assignee.get('name')} ({assignee.get('type')})")
        elif kind in {"flow.completed", "flow.failed"}:
            flow = data.get("flow") or {}
            lines.append(f"Flow: {flow.get('name')} (ID {flow.get('id')})")
            if kind == "flow.failed":
                lines.append(f"Reason: {data.get('reason')}")
        elif kind == "whatsapp_form.completed":
            form = data.get("form") or {}
            lines += [f"Form: {form.get('name')} (ID {form.get('id')}; version {form.get('version_id')})",
                f"Device ID: {data.get('device_id')}; message ID: {data.get('message_id')}",
                "Answers: " + json.dumps(data.get("answers") or [], ensure_ascii=False)]
        if contact:
            lines.append("Contact: " + json.dumps(contact, ensure_ascii=False))
        lines.append(f"Event ID: {event.get('id')}; occurred at: {event.get('occurred_at')}")
        if contact_id:
            lines.append(f"Contact ID: {contact_id}. Use get_contact or send_message to follow up.")
        text = "\n".join(lines)[:8000]
        return {"text": text, "title": title, "conversation_key": str(contact_id or event.get("id", ""))}
