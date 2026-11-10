"""Talkroute API v2 operations and webhook triggers.

Contract: https://apidocs.talkroute.com/talkroute-api-ref.json (2.0.2).
Each action issues one request. Lists return the provider pagination envelope.
The published webhook contract specifies JSON delivery without a signature
header or signing secret; the per-workflow webhook URL is the delivery capability.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE_URL = "https://api.talkroute.com/api"


class TalkrouteAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Talkroute API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://apidocs.talkroute.com/",
        "x-credential-instructions": "Paste your Talkroute API key (tr_live_ followed by 64 hexadecimal characters). NoClick sends it as a Bearer token to api.talkroute.com. Your key must permit the operations you choose.",
    })
    credential_type: Literal["talkroute_api_key"] = Field("talkroute_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def text(title, required=False, **kwargs):
    return (str if required else Optional[str], Field(... if required else None, title=title, min_length=1, **kwargs))


def resource(title):
    return text(title, True, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")


def optional(typ, title, **kwargs):
    return (Optional[typ], Field(None, title=title, **kwargs))


PAGE = {"page": (int, Field(1, ge=1, title="Page")), "pageSize": (int, Field(50, ge=1, le=100, title="Page size"))}
ID = {"id": resource("Resource ID")}
CONVERSATION = {"conversationId": text("Conversation ID", True, pattern=r"^1[2-9]\d{2}[2-9]\d{6}-(1[2-9]\d{2}[2-9]\d{6}|[2-9]\d{4,5})$", description="Talkroute number-contact number, without plus signs")}
READ = {"read": (Literal["read", "unread"], Field("read", title="Mark as"))}
CONTACT = {
    "name": text("Name", max_length=100), "emails": optional(list[str], "Email addresses"),
    "company": text("Company", max_length=100), "role": text("Role", max_length=100),
    "url": text("Website", max_length=600), "notes": text("Notes"), "isFavorite": optional(bool, "Favorite"),
}


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    category: str
    fields: dict
    query: tuple = ()
    body: tuple = ()


OPERATIONS = {
    "get_account": Operation("GET", "/v2/account", "Account", {}),
    "list_virtual_numbers": Operation("GET", "/v2/virtual-numbers", "Numbers", PAGE, tuple(PAGE)),
    "get_virtual_number": Operation("GET", "/v2/virtual-numbers/{id}", "Numbers", ID),
    "list_voice_mailboxes": Operation("GET", "/v2/voice-mailboxes", "Voicemail", PAGE, tuple(PAGE)),
    "list_voicemails": Operation("GET", "/v2/voice-messages", "Voicemail", PAGE, tuple(PAGE)),
    "get_voicemail": Operation("GET", "/v2/voice-messages/{id}", "Voicemail", ID),
    "get_voicemail_audio": Operation("GET", "/v2/voice-messages/{id}/audio-url", "Voicemail", ID),
    "mark_voicemails_read": Operation("PATCH", "/v2/voice-messages/read/{read}", "Voicemail", {
        **READ, "ids": (list[int], Field(..., min_length=1, title="Voicemail IDs"))}, body=("ids",)),
    "list_conversations": Operation("GET", "/v2/text-conversations", "Messaging", {
        **PAGE, "since": text("Last message after", description="ISO 8601 date-time or Unix timestamp"),
        "before": text("Last message before"), "unread": optional(bool, "Unread only")}, (*PAGE, "since", "before", "unread")),
    "list_messages": Operation("GET", "/v2/text-conversations/{conversationId}/messages", "Messaging", {**CONVERSATION, **PAGE}, tuple(PAGE)),
    "send_text": Operation("POST", "/v2/text-conversations/{conversationId}", "Messaging", {
        **CONVERSATION, "body": text("Message", True)}, body=("body",)),
    "mark_conversation_messages_read": Operation("PATCH", "/v2/text-conversations/{conversationId}/messages/{read}", "Messaging", {
        **CONVERSATION, **READ, "id": (list[str], Field(..., min_length=1, title="Message IDs"))}, body=("id",)),
    "get_message": Operation("GET", "/v2/text-conversations/{conversationId}/messages/{id}", "Messaging", {**CONVERSATION, **ID}),
    "delete_message": Operation("DELETE", "/v2/text-conversations/{conversationId}/messages/{id}", "Messaging", {**CONVERSATION, **ID}),
    "list_contacts": Operation("GET", "/v2/contacts", "Contacts", {
        "contactName": text("Name contains"), "favorite": optional(bool, "Favorites only")}, ("contactName", "favorite")),
    "get_contact": Operation("GET", "/v2/contacts/{id}", "Contacts", ID),
    "create_contact": Operation("POST", "/v2/contacts", "Contacts", {
        **CONTACT, "name": text("Name", True, max_length=100)}, body=tuple(CONTACT)),
    "update_contact": Operation("PATCH", "/v2/contacts/{id}", "Contacts", {**ID, **CONTACT}, body=tuple(CONTACT)),
    "delete_contact": Operation("DELETE", "/v2/contacts/{id}", "Contacts", ID),
    "add_contact_phone": Operation("POST", "/v2/contacts/{id}/phone-numbers", "Contacts", {
        **ID, "phoneNumber": text("Phone number", True),
        "type": (Literal["Mobile", "Office", "Home", "Other"], Field(..., title="Phone type"))}, body=("phoneNumber", "type")),
    "list_call_history": Operation("GET", "/v2/call-history", "Calls", {
        **PAGE, "after": text("Calls after"), "before": text("Calls before"),
        "direction": optional(Literal["inbound", "outbound"], "Direction"),
        "result": optional(Literal["answered", "missed", "hangup"], "Result"),
        "callerNumber": text("Caller number")}, (*PAGE, "after", "before", "direction", "result", "callerNumber")),
    "list_forwarding_numbers": Operation("GET", "/v2/forwarding-numbers", "Numbers", PAGE, tuple(PAGE)),
}
TRIGGERS = {"on_new_text_message": "new_text_message", "on_new_call_record": "new_call_record", "on_new_voicemail": "new_voicemail"}


def make_model(name, fields, category, trigger=False):
    base = WebhookTriggerConfigBase if trigger else _Input
    return create_model("Talkroute" + "".join(p.title() for p in name.split("_")) + "Config", __base__=base, __module__=__name__,
        operation=(Literal[name], Field(name, title=name.replace("_", " ").title(), json_schema_extra={
            "ui:hidden": True, "x-category": category, "x-is-trigger": trigger, "x-display-name": name.replace("_", " ").title()})), **fields)


CONFIG_MODELS = {name: make_model(name, op.fields, op.category) for name, op in OPERATIONS.items()}
CONFIG_MODELS.update({name: make_model(name, {
    "webhook_url": (Optional[str], Field(None, title="Webhook URL", description="Registered with Talkroute automatically", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})),
}, "Triggers", True) for name in TRIGGERS})
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
TalkrouteOperation = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class TalkrouteNodeConfig(NodeConfig[TalkrouteOperation, TalkrouteAPIKeyCredential]):
    pass


class TalkrouteNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-talkroute"
    connection_evidence = ConnectionEvidence(operation="get_account", noun="account", identity_operation="get_account")
    webhook_signing_secret_not_issued = True

    @classmethod
    def get_config_model(cls):
        return TalkrouteNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        key = TalkrouteAPIKeyCredential.model_validate(credential).api_key
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, json=body,
                headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
        if response.is_error or response.is_redirect:
            try:
                detail = response.json().get("message", "Request failed")
            except (ValueError, AttributeError):
                detail = "Request failed"
            raise ValueError(f"Talkroute API error {response.status_code}: {str(detail).replace(key, '[redacted]')}")
        if response.status_code == 204:
            return {"ok": True}
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected a Talkroute JSON object")
        return data

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        op = self.config.config
        name = op.operation
        if name in TRIGGERS:
            return self.no_event_output(name)
        if self.config.credentials is None:
            raise ValueError("Connect a Talkroute API key")
        spec = OPERATIONS[name]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        for field, value in values.items():
            path = path.replace("{" + field + "}", quote(str(value), safe=""))
        params = {field: values[field] for field in spec.query if field in values}
        # Explicit false is a supported boolean query value, serialized in lowercase.
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        body = {field: values[field] for field in spec.body if field in values}
        if name == "update_contact" and not body:
            raise ValueError("Choose at least one contact field to update")
        data = await self._request(self.config.credentials.model_dump(), spec.method, path,
            params=params or None, body=body if spec.body else None)
        return {"status": "success", "operation": name, **data}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = TRIGGERS.get(config.get("operation"))
        if not event:
            raise ValueError("Choose a Talkroute trigger")
        result = await cls._request(credential, "POST", "/v2/subscriptions", body={"hookUrl": webhook_url, "type": event})
        subscription = result.get("data")
        if not isinstance(subscription, dict) or not subscription.get("id"):
            raise ValueError("Talkroute did not return a subscription ID")
        return {"external_webhook_id": str(subscription["id"])}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        sid = config.get("external_webhook_id")
        if sid and credential:
            await cls._request(credential, "DELETE", "/v2/subscriptions/" + quote(str(sid), safe=""))

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # No signature scheme, signature header or secret is in the published contract.
        return True

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        # Each subscription has its own URL. Structural keys also keep event families separate.
        event = TRIGGERS.get(config.get("operation"))
        return isinstance(payload, dict) and (
            (event == "new_text_message" and "from_number" in payload and "to_number" in payload)
            or (event == "new_voicemail" and "mailbox_name" in payload)
            or (event == "new_call_record" and "direction" in payload and "caller_number" in payload))

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"status": "success", "operation": config["operation"], "event_type": TRIGGERS[config["operation"]],
            "data": {k: v for k, v in payload.items() if k != "_webhook"}}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") not in TRIGGERS:
            return super().resolve_agent_event(output)
        event, data = output["event_type"], output["data"]
        if event == "new_text_message":
            sender, recipient = data.get("from_number", "Unknown sender"), data.get("to_number", "Unknown recipient")
            incoming = data.get("direction") == "incoming"
            local, outside = (recipient, sender) if incoming else (sender, recipient)
            conversation = str(local).lstrip("+") + "-" + str(outside).lstrip("+")
            text = f"Talkroute text message from {sender} to {recipient} at {data.get('datetime', '')}:\n{data.get('body', '')}\nConversation ID: {conversation}. Use send_text or list_messages with this conversationId."
            return {"text": text, "conversation_key": conversation, "title": f"Text from {sender}"}
        caller, called = data.get("caller_number", "Unknown caller"), data.get("called_number", "Unknown number")
        text = f"Talkroute {'voicemail' if event == 'new_voicemail' else 'call'} from {caller} to {called} at {data.get('datetime', '')}; result {data.get('call_result', '')}; duration {data.get('duration', 0)} seconds."
        if event == "new_voicemail":
            text += f"\nMailbox: {data.get('mailbox_name', '')}\n{data.get('transcription', '')}\nUse list_voicemails to find the voicemail ID; the event does not include it."
        else:
            text += f"\nCaller name: {data.get('caller_cname', '')}; direction {data.get('direction', '')}. Use list_call_history filtered by callerNumber and time to find the record."
        return {"text": text, "conversation_key": f"{called}:{caller}", "title": f"Talkroute {event}: {caller}"}
