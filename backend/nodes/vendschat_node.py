"""Vendschat Integration API v1, pinned to the provider's published OpenAPI.

Official reference: https://docs.vendschat.com/api-reference/overview
Webhooks: https://docs.vendschat.com/integrations/webhooks-guide
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE_URL = "https://api.vendschat.com/v1"


def operation(name, title, category):
    return Field(name, title=title, json_schema_extra={"ui:hidden": True, "x-category": category})


def channel_picker():
    return {"x-dynamic-options": {"field_name": "channel_id", "allow_custom": True}}


class VendschatAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Vendschat API Key", json_schema_extra={
        "x-credential-url": "https://docs.vendschat.com/integrations/api-keys-and-rest-api",
        "x-credential-instructions": "On Growth or Advanced, open Settings → Workspace → Integrations → n8n, Make, or Zapier and create an API key. Paste the key shown once. Advanced accounts can also use Settings → Workspace → API Keys."})
    credential_type: Literal["vendschat_api_key"] = Field("vendschat_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})


class GetWorkspace(BaseModel):
    operation: Literal["get_workspace"] = operation("get_workspace", "Get Workspace", "Account")


class ListChannels(BaseModel):
    operation: Literal["list_channels"] = operation("list_channels", "List Active Channels", "Messages")


class ListTemplates(BaseModel):
    operation: Literal["list_templates"] = operation("list_templates", "List Approved Templates", "Messages")
    channel_id: int = Field(..., title="Channel", json_schema_extra=channel_picker())


class GetTemplate(ListTemplates):
    operation: Literal["get_template"] = operation("get_template", "Get Template Variable Fields", "Messages")
    id: int = Field(..., title="Template ID", json_schema_extra={"x-dynamic-options": {
        "field_name": "template_id", "depends_on": ["channel_id"], "allow_custom": True}})


class ContactIdentifier(BaseModel):
    identifier_type: Literal["contact_id", "email", "phone_number"] = Field(..., title="Find Contact By")
    identifier_value: str = Field(..., min_length=1, title="Contact Identifier", description="Contact ID, email address, or phone number, matching Find Contact By.")


class SendMessage(ContactIdentifier):
    operation: Literal["send_message"] = operation("send_message", "Send Message", "Messages")
    channel_mode: Literal["last_interacted", "specific"] = Field("last_interacted", title="Channel Selection")
    channel_id: int | None = Field(None, title="Channel", json_schema_extra=channel_picker())
    content_mode: Literal["text", "attachment"] | None = Field(None, title="Content Mode", description="Required for the last interacted channel.")
    message_type: str | None = Field(None, title="Message Type", description="For a specific channel: text, template, image, video, audio, or document.")
    text: str | None = Field(None, title="Message Text", json_schema_extra={"ui:widget": "textarea"})
    attachment_type: Literal["image", "video", "audio", "document"] | None = None
    media_url: str | None = Field(None, title="Media URL")
    caption: str | None = None
    filename: str | None = None
    template_id: int | None = Field(None, title="Template ID")
    template_variables: dict[str, str] | None = Field(None, title="Template Variables", description="Keys from Get Template Variable Fields, such as body_1.")

    @model_validator(mode="after")
    def valid_message(self):
        if self.channel_mode == "specific":
            if self.channel_id is None or not self.message_type:
                raise ValueError("Choose a channel and message type for a specific-channel send")
            kind = self.message_type
        else:
            if not self.content_mode:
                raise ValueError("Choose content mode for a last-interacted-channel send")
            kind = self.content_mode
        if kind == "text" and not self.text:
            raise ValueError("Enter message text")
        if kind == "template" and self.template_id is None:
            raise ValueError("Choose a template")
        if kind in {"attachment", "image", "video", "audio", "document"} and not self.media_url:
            raise ValueError("Supply a media URL")
        if kind == "attachment" and not self.attachment_type:
            raise ValueError("Choose an attachment type")
        return self


class LookupContact(ContactIdentifier):
    operation: Literal["lookup_contact"] = operation("lookup_contact", "Lookup Contact", "Contacts")


class ContactFields(BaseModel):
    name: str | None = None
    phone_number: str | None = None
    email: str | None = None
    note: str | None = Field(None, json_schema_extra={"ui:widget": "textarea"})
    country: str | None = None
    language: str | None = None
    custom_fields: dict[str, Any] | None = None


class CreateContact(ContactFields):
    operation: Literal["create_contact"] = operation("create_contact", "Create Contact", "Contacts")
    phone_number: str = Field(..., min_length=1, title="Phone Number")
    email: str = Field(..., min_length=1, title="Email")


class UpdateContact(ContactIdentifier, ContactFields):
    operation: Literal["update_contact"] = operation("update_contact", "Update Contact", "Contacts")


class DeleteContact(ContactIdentifier):
    operation: Literal["delete_contact"] = operation("delete_contact", "Delete Contact", "Contacts")


class SetContactNote(ContactIdentifier):
    operation: Literal["set_contact_note"] = operation("set_contact_note", "Set Contact Note", "Contacts")
    note: str | None = Field(..., title="Note", description="Use null to clear the note.", json_schema_extra={"ui:widget": "textarea"})


class ContactLabels(ContactIdentifier):
    label_ids: list[int] | None = Field(None, title="Label IDs")
    labels: str | list[str | int] | None = Field(None, title="Labels", description="Comma-separated names or an array of names/IDs. Missing names are created when adding labels.")


class AddContactLabels(ContactLabels):
    operation: Literal["add_contact_labels"] = operation("add_contact_labels", "Add Contact Labels", "Contacts")


class RemoveContactLabels(ContactLabels):
    operation: Literal["remove_contact_labels"] = operation("remove_contact_labels", "Remove Contact Labels", "Contacts")


class ListLabels(BaseModel):
    operation: Literal["list_labels"] = operation("list_labels", "List Workspace Labels", "Contacts")


class ListWebhookEvents(BaseModel):
    operation: Literal["list_webhook_events"] = operation("list_webhook_events", "List Webhook Event Catalog", "Webhooks")


class OnIncomingWhatsAppText(WebhookTriggerConfigBase):
    operation: Literal["on_incoming_whatsapp_text"] = Field("on_incoming_whatsapp_text", title="On Incoming WhatsApp Text", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True})
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


VendschatOperation = Annotated[Union[GetWorkspace, ListChannels, ListTemplates, GetTemplate, SendMessage,
    LookupContact, CreateContact, UpdateContact, DeleteContact, SetContactNote, AddContactLabels,
    RemoveContactLabels, ListLabels, ListWebhookEvents, OnIncomingWhatsAppText], Field(discriminator="operation")]


class VendschatNodeConfig(NodeConfig[VendschatOperation, VendschatAPIKeyCredential]):
    pass


# One request per action, with no implicit follow-up writes or retries.
ROUTES = {
    "get_workspace": ("GET", "/integrations/me"),
    "list_channels": ("GET", "/integrations/messages/channels"),
    "list_templates": ("GET", "/integrations/messages/templates"),
    "get_template": ("GET", "/integrations/messages/templates/{id}"),
    "send_message": ("POST", "/integrations/messages/send"),
    "lookup_contact": ("POST", "/integrations/contacts/lookup"),
    "create_contact": ("POST", "/integrations/contacts"),
    "update_contact": ("PATCH", "/integrations/contacts"),
    "delete_contact": ("DELETE", "/integrations/contacts"),
    "set_contact_note": ("PUT", "/integrations/contacts/note"),
    "add_contact_labels": ("POST", "/integrations/contacts/labels/add"),
    "remove_contact_labels": ("POST", "/integrations/contacts/labels/remove"),
    "list_labels": ("GET", "/integrations/labels"),
    "list_webhook_events": ("GET", "/integrations/webhooks/events"),
}
EVENT = "incoming.whatsapp.messages.text"


class VendschatNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-vendschat"
    connection_evidence = ConnectionEvidence(field="channel_id", noun="channels", identity_operation="get_workspace")

    @classmethod
    def get_config_model(cls):
        return VendschatNodeConfig

    @staticmethod
    async def _request(api_key, method, path, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, json=body,
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
        if response.is_error or response.is_redirect:
            try:
                error = response.json().get("error")
                detail = error.get("message") if isinstance(error, dict) else error
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"Vendschat API error {response.status_code}: {detail or 'request failed'}")
        data = response.json()
        if isinstance(data, dict) and (data.get("error")):
            error = data.get("error")
            detail = error.get("message") if isinstance(error, dict) else error
            raise ValueError(f"Vendschat API error: {detail or 'request failed'}")
        return data

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        credential = VendschatAPIKeyCredential.model_validate(credential_data)
        if field_name == "channel_id":
            data = await cls._request(credential.api_key, "GET", "/integrations/messages/channels")
            options = [{"value": row["id"], "label": row.get("display_name") or str(row["id"])} for row in data["channels"]]
        elif field_name == "template_id":
            channel_id = (context or {}).get("channel_id")
            if channel_id is None:
                return {"options": [], "next_page_token": None}
            data = await cls._request(credential.api_key, "GET", "/integrations/messages/templates", params={"channel_id": int(channel_id)})
            options = [{"value": row["id"], "label": row.get("name") or str(row["id"])} for row in data["templates"]]
        else:
            return {"options": [], "next_page_token": None}
        if search:
            options = [row for row in options if search.casefold() in row["label"].casefold()]
        return {"options": options, "next_page_token": None}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        key = VendschatAPIKeyCredential.model_validate(credential).api_key
        # Integration API subscriptions require one of zapier/make/n8n as a source.
        # Use its HTTP/n8n profile; the destination name identifies NoClick.
        data = await cls._request(key, "POST", "/integrations/webhooks/subscribe", body={
            "url": webhook_url, "events": [EVENT], "source": "n8n", "name": f"NoClick {node_id}", "payload_style": "snapshot"})
        if not data.get("id") or not data.get("signing_secret"):
            raise ValueError("Vendschat did not return a webhook ID and signing secret")
        return {"external_webhook_id": str(data["id"]), "signing_secret": data["signing_secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        webhook_id = (config or {}).get("external_webhook_id")
        if webhook_id is None:
            return
        # The published delete parameter is an integer, even though create returns a string.
        webhook_id = int(webhook_id)
        key = VendschatAPIKeyCredential.model_validate(credential).api_key
        await cls._request(key, "DELETE", f"/integrations/webhooks/{webhook_id}")

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict) -> bool:
        secret = (config or {}).get("signing_secret")
        headers = {key.lower(): value for key, value in headers.items()}
        timestamp = headers.get("x-vendschat-timestamp", "")
        signature = headers.get("x-vendschat-signature", "")
        if not secret or not timestamp.isdigit() or abs(time.time() - int(timestamp)) > 300:
            return False
        expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("type") == EVENT

    @classmethod
    def resolve_agent_event(cls, output):
        # Only the envelope is documented. Preserve data without inventing message,
        # sender or thread fields; richer provider snapshots remain available to the agent.
        if not isinstance(output, dict) or output.get("type") != EVENT:
            return None
        workspace_id = output.get("workspace_id")
        text = (f"New WhatsApp text received in Vendschat workspace {workspace_id}.\n"
                f"Event {output.get('id')} at {output.get('created_at')}.\n"
                "Delivery data: " + json.dumps(output.get("data", {}), ensure_ascii=False)[:6000] +
                "\nUse lookup_contact and send_message with the contact identifier in the delivery data to respond.")
        return {"text": text, "title": "New Vendschat WhatsApp message", "conversation_key": None}

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Vendschat API key")
        config = self.config.config
        if isinstance(config, OnIncomingWhatsAppText):
            return {"status": "success", "operation": config.operation, "data": inputs}
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        # A null note is meaningful, unlike an unset optional field.
        if isinstance(config, SetContactNote):
            values["note"] = config.note
        if isinstance(config, UpdateContact):
            for key in config.model_fields_set - {"operation"}:
                if getattr(config, key) is None:
                    values[key] = None
        if isinstance(config, GetTemplate):
            path = path.replace("{id}", str(values.pop("id")))
        data = await self._request(credential.api_key, method, path,
            params=values or None if method == "GET" else None,
            body=values if method != "GET" else None)
        return {"status": "success", "operation": config.operation, "data": data}
