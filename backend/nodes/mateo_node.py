"""Mateo's published legacy API v1: contacts, lists, deals and messaging.

Each action uses one pinned OpenAPI operation. Webhook examples and delivery
security are documented at docs.getmateo.com/webhooks/setting-up-webhooks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE_URL = "https://integration.getmateo.com/api/v1"


class MateoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Mateo API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.getmateo.com/introduction",
        "x-credential-instructions": "Paste your Mateo API key without the Bearer prefix. This connects to Mateo's legacy API v1; your key must permit the contacts read used to check the connection.",
    })
    credential_type: Literal["mateo_api_key"] = Field("mateo_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=8192, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


def text(title, required=False):
    return (str if required else Optional[str], Field(... if required else None, title=title, min_length=1, max_length=10000))


def identifier(title, required=True):
    return (UUID if required else Optional[UUID], Field(... if required else None, title=title))


PAGE = {
    "limit": (int, Field(50, title="Page Size", ge=1, le=1000)),
    "offset": (int, Field(0, title="Page Offset", ge=0)),
}
CONTACT = {"full_name": text("Full Name"), "email": text("Email"), "sms": text("SMS Number"),
           "whatsapp": text("WhatsApp Number"), "external_id": text("External ID")}
DEAL = {"name": text("Deal Name", True), "contact_id": identifier("Contact ID"),
        "type_key": text("Deal Type Key", True), "status_key": text("Deal Status Key", True),
        "value": (Optional[float], Field(None, title="Value")),
        "currency": (Literal["EUR", "CHF", "USD"], Field("EUR", title="Currency"))}
MEMBERSHIP = {"contact_id": identifier("Contact ID"), "contact_list_id": identifier("Contact List ID")}


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    category: str
    fields: dict
    filters: tuple[str, ...] = ()


OPERATIONS = {
    "list_contacts": Operation("GET", "/contact", "Contacts", {**PAGE, "email": text("Exact Email"), "external_id": text("Exact External ID")}, ("email", "external_id")),
    "create_contact": Operation("POST", "/contact", "Contacts", {**CONTACT, "full_name": text("Full Name", True)}),
    "update_contact": Operation("PATCH", "/contact", "Contacts", {"id": identifier("Contact ID"), **CONTACT}, ("id",)),
    "delete_contact": Operation("DELETE", "/contact", "Contacts", {"id": identifier("Contact ID")}, ("id",)),
    "list_contact_lists": Operation("GET", "/contact_list", "Contact Lists", PAGE),
    "create_contact_list": Operation("POST", "/contact_list", "Contact Lists", {"name": text("List Name", True)}),
    "update_contact_list": Operation("PATCH", "/contact_list", "Contact Lists", {"id": identifier("List ID"), "name": text("List Name", True)}, ("id",)),
    "delete_contact_list": Operation("DELETE", "/contact_list", "Contact Lists", {"id": identifier("List ID")}, ("id",)),
    "list_contact_list_contacts": Operation("GET", "/contact_list_contact", "Contact Lists", {**PAGE, "contact_list_id": identifier("Contact List ID")}, ("contact_list_id",)),
    "add_contact_to_list": Operation("POST", "/contact_list_contact", "Contact Lists", MEMBERSHIP),
    "remove_contact_from_list": Operation("DELETE", "/contact_list_contact", "Contact Lists", MEMBERSHIP, ("contact_id", "contact_list_id")),
    "list_contact_notes": Operation("GET", "/contact_note", "Contact Notes", {**PAGE, "contact_id": identifier("Contact ID")}, ("contact_id",)),
    "create_contact_note": Operation("POST", "/contact_note", "Contact Notes", {"contact_id": identifier("Contact ID"), "text": text("Note", True)}),
    "update_contact_note": Operation("PATCH", "/contact_note", "Contact Notes", {"id": identifier("Note ID"), "text": text("Note", True)}, ("id",)),
    "delete_contact_note": Operation("DELETE", "/contact_note", "Contact Notes", {"id": identifier("Note ID")}, ("id",)),
    "list_deals": Operation("GET", "/deal", "Deals", {**PAGE, "contact_id": identifier("Contact ID", False)}, ("contact_id",)),
    "create_deal": Operation("POST", "/deal", "Deals", DEAL),
    "update_deal": Operation("PATCH", "/deal", "Deals", {"id": identifier("Deal ID"), "status_key": text("Deal Status Key", True), "name": text("Deal Name"), "value": (Optional[float], Field(None, title="Value"))}, ("id",)),
    "list_channels": Operation("GET", "/channel", "Messaging", PAGE),
    "list_messages": Operation("GET", "/message", "Messaging", {**PAGE, "conversation_id": identifier("Conversation ID", False)}, ("conversation_id",)),
    "send_message": Operation("POST", "/send_message", "Messaging", {
        "channel_id": identifier("Sending Channel ID"), "contact_id": identifier("Recipient Contact ID"),
        "text": text("Message", True), "subject": text("Subject")}),
    "list_conversations": Operation("GET", "/conversation", "Conversations", {**PAGE, "contact_id": identifier("Contact ID", False)}, ("contact_id",)),
    "update_conversation": Operation("PATCH", "/conversation", "Conversations", {
        "id": identifier("Conversation ID"), "status": (Literal["open", "closed", "archived"], Field(..., title="Status")),
        "assignee_id": identifier("Assignee ID", False)}, ("id",)),
}


def _model(name, spec):
    label = name.replace("_", " ").title()
    return create_model("Mateo" + label.replace(" ", "") + "Config", __base__=_Input, __module__=__name__,
        operation=(Literal[name], Field(name, title=label, json_schema_extra={
            "x-display-name": label, "x-category": spec.category, "x-is-trigger": False, "ui:hidden": True})), **spec.fields)


CONFIG_MODELS = {name: _model(name, spec) for name, spec in OPERATIONS.items()}
globals().update({m.__name__: m for m in CONFIG_MODELS.values()})
TRIGGERS = {"on_contact_created": "contact.created", "on_contact_updated": "contact_details.updated",
            "on_contact_deleted": "contact.deleted", "on_form_completed": "form_submission.completed"}
TRIGGER_MODELS = {}
for _name in TRIGGERS:
    _label = _name.replace("_", " ").title()
    _cls = create_model("Mateo" + _label.replace(" ", "") + "Config", __base__=WebhookTriggerConfigBase, __module__=__name__,
        operation=(Literal[_name], Field(_name, title=_label, json_schema_extra={
            "x-display-name": _label, "x-category": "Triggers", "x-is-trigger": True, "ui:hidden": True})),
        webhook_url=(Optional[str], Field(None, title="Webhook URL", description="Registered with Mateo automatically. Mateo delivers unsigned events to this private URL.",
            json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})))
    TRIGGER_MODELS[_name] = _cls
    globals()[_cls.__name__] = _cls

MateoConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + tuple(TRIGGER_MODELS.values())], Field(discriminator="operation")]


class MateoNodeConfig(NodeConfig[MateoConfig, MateoAPIKeyCredential]):
    pass


class MateoNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-mateo"
    webhook_signing_secret_not_issued = True
    connection_evidence = ConnectionEvidence(operation="list_contacts", noun="contacts", label_keys=("display_name", "full_name", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return MateoNodeConfig

    @staticmethod
    async def _request(key, method, path, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            try:
                response = await client.request(method, BASE_URL + path, params=params, json=body,
                    headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
            except httpx.HTTPError:
                raise ValueError("Mateo request did not complete; inspect Mateo before retrying a write") from None
        if not 200 <= response.status_code < 300:
            try:
                message = response.json().get("message") or "Request failed"
            except (ValueError, AttributeError):
                message = "Request failed"
            raise ValueError(f"Mateo API {response.status_code}: {str(message).replace(key, '[redacted]')}")
        try:
            data = response.json() if response.content else None
        except ValueError:
            raise ValueError("Mateo returned invalid JSON; inspect Mateo before retrying a write") from None
        return data

    async def execute(self, inputs):
        if self.config is None:
            raise ValueError("Configure Mateo")
        op = self.config.config
        if op.operation in TRIGGERS:
            return self.no_event_output(op.operation)
        if self.config.credentials is None:
            raise ValueError("Connect a Mateo API key")
        spec = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        params = {k: "eq." + str(values.pop(k)) for k in spec.filters if k in values}
        body = None
        if spec.method == "GET":
            params.update(values)
        elif spec.method != "DELETE":
            body = values
            if op.operation == "update_contact" and not body:
                raise ValueError("Provide a contact field to update")
            if op.operation == "send_message":
                body = {"from": values["channel_id"], "to": [{"contact_id": values["contact_id"]}],
                        "text": values["text"], **({"subject": values["subject"]} if "subject" in values else {})}
        data = await self._request(self.config.credentials.api_key, spec.method, spec.path, params=params, body=body)
        if spec.method == "GET" and not isinstance(data, list):
            raise ValueError("Mateo returned an unexpected list response")
        output = {"status": "success", "operation": op.operation, "data": data}
        if spec.method == "GET":
            output.update({"offset": op.offset, "limit": op.limit, "next_offset": op.offset + len(data) if len(data) == op.limit else None})
        await self.emit(output)
        return output

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = TRIGGERS.get(config.get("operation"))
        if event is None:
            raise ValueError("Choose a Mateo trigger")
        key = MateoAPIKeyCredential.model_validate(credential).api_key
        # Supplying our own ID allows cleanup even when the documented response is 204.
        webhook_id = str(uuid4())
        await cls._request(key, "POST", "/webhook", body={"id": webhook_id, "name": f"NoClick {node_id}",
            "source": "authenticated", "active": True, "target_url": webhook_url, "headers": {}, "method": "POST", "event": event})
        return {"external_webhook_id": webhook_id}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if not config.get("external_webhook_id"):
            return
        identifier = str(UUID(str(config["external_webhook_id"])))
        key = MateoAPIKeyCredential.model_validate(credential).api_key
        await cls._request(key, "DELETE", "/webhook", params={"id": "eq." + identifier})

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # Mateo documents optional caller-configured headers, with no delivery signature.
        # The private, unguessable NoClick webhook URL is the capability for this mode.
        return True

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        if config.get("operation") == "on_form_completed":
            return "form_id" in payload and payload.get("status") == "completed"
        return "id" in payload and "full_name" in payload

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"status": "success", "event_type": TRIGGERS[config["operation"]], "data": payload}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("event_type") not in TRIGGERS.values():
            return super().resolve_agent_event(output)
        data = output["data"]
        kind = output["event_type"]
        if kind == "form_submission.completed":
            contact_id = data.get("contact_id")
            text = (f"Mateo form completed: {data.get('form_id')} by contact {contact_id}.\n"
                    f"Organisation: {data.get('organisation_id')}. Conversation: {data.get('in_conversation_id')}. Completed at {data.get('finalised_at')}.\n"
                    f"Answers: {data.get('element_submissions')}\nTo act: create_contact_note contact_id={contact_id}, or list_conversations contact_id={contact_id}.")
            return {"text": text, "conversation_key": str(contact_id), "title": "Mateo form completed"}
        contact_id = data.get("id")
        name = data.get("full_name") or data.get("display_name") or contact_id
        text = (f"Mateo {kind}: {name} (contact {contact_id}).\n"
                f"Organisation: {data.get('organisation_id')}. Email: {data.get('email')}; WhatsApp: {data.get('whatsapp')}.\n"
                f"To act: list_conversations contact_id={contact_id}, or create_contact_note contact_id={contact_id}.")
        if kind == "contact.deleted":
            text = text[:text.index("To act:")] + f"To act: reconcile removed contact {contact_id} in connected systems."
        return {"text": text, "conversation_key": str(contact_id), "title": f"Mateo {kind}: {name}"}
