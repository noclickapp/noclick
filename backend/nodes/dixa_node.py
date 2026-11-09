"""Dixa v1 support actions and signed internal-note notifications.

Routes and request fields follow Dixa's published v1 OpenAPI contract. The
webhook payload follows its published delivery-log example and payload guide.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE_URL = "https://dev.dixa.io"


class DixaAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Dixa API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.dixa.io/docs/tutorial-create-an-api-token",
        "x-credential-instructions": "In Dixa, open Settings > Integrations > API tokens and create a token with access to the actions you need. Paste the token here without an Authorization prefix. Activating a trigger also requires webhook integration permissions.",
    })
    credential_type: Literal["dixa_api_token"] = Field("dixa_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a header prefix or whitespace")
        return value


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    fields: dict
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()


def text(title, *, required=False, **kwargs):
    return (str if required else str | None, Field(... if required else None, title=title, min_length=1, max_length=10000, **kwargs))


def uid(title):
    return (UUID, Field(..., title=title))


CONVERSATION = {"conversation_id": (int, Field(..., title="Conversation ID", ge=1, le=9223372036854775807))}
USER = {"user_id": uid("End user ID")}
PAGE = {
    "page_limit": (int, Field(50, title="Page size", ge=1, le=100)),
    "page_key": text("Page key", description="Copy the opaque pageKey from Dixa's next pagination link. Leave empty for the first page."),
}
CONTACT = {name: text(label) for name, label in {
    "display_name": "Display name", "email": "Email", "phone_number": "Phone number",
    "first_name": "First name", "last_name": "Last name", "external_id": "External ID",
}.items()}
CONTACT["display_name"] = text("Display name", required=True)

OPERATIONS = {
    "get_organization": Operation("GET", "/v1/organization", {}),
    "get_conversation": Operation("GET", "/v1/conversations/{conversation_id}", CONVERSATION),
    "search_conversations": Operation("GET", "/v1/search/conversations", {**PAGE, "query": text("Search text", required=True), "exact_match": (bool, Field(False, title="Exact match"))}, ("page_limit", "page_key", "query", "exact_match")),
    "list_messages": Operation("GET", "/v1/conversations/{conversation_id}/messages", CONVERSATION),
    "send_reply": Operation("POST", "/v1/conversations/{conversation_id}/messages", {**CONVERSATION, "agent_id": uid("Sending agent ID"), "message": text("Reply text", required=True)}),
    "list_notes": Operation("GET", "/v1/conversations/{conversation_id}/notes", CONVERSATION),
    "add_note": Operation("POST", "/v1/conversations/{conversation_id}/notes", {**CONVERSATION, "message": text("Note", required=True), "agent_id": (UUID | None, Field(None, title="Author agent ID"))}, body=("message", "agent_id")),
    "close_conversation": Operation("PUT", "/v1/conversations/{conversation_id}/close", CONVERSATION),
    "reopen_conversation": Operation("PUT", "/v1/conversations/{conversation_id}/reopen", CONVERSATION),
    "tag_conversation": Operation("PUT", "/v1/conversations/{conversation_id}/tags/{tag_id}", {**CONVERSATION, "tag_id": uid("Tag ID")}),
    "untag_conversation": Operation("DELETE", "/v1/conversations/{conversation_id}/tags/{tag_id}", {**CONVERSATION, "tag_id": uid("Tag ID")}),
    "list_conversation_tags": Operation("GET", "/v1/conversations/{conversation_id}/tags", CONVERSATION),
    "list_end_users": Operation("GET", "/v1/endusers", {**PAGE, "email": text("Email filter"), "phone": text("Phone filter"), "external_id": text("External ID filter")}, ("page_limit", "page_key", "email", "phone", "external_id")),
    "get_end_user": Operation("GET", "/v1/endusers/{user_id}", USER),
    "create_end_user": Operation("POST", "/v1/endusers", CONTACT, body=tuple(CONTACT)),
    "patch_end_user": Operation("PATCH", "/v1/endusers/{user_id}", {**USER, **CONTACT}, body=tuple(CONTACT)),
    "list_end_user_conversations": Operation("GET", "/v1/endusers/{user_id}/conversations", {**USER, **PAGE}, ("page_limit", "page_key")),
    "list_agents": Operation("GET", "/v1/agents", {**PAGE, "email": text("Email filter")}, ("page_limit", "page_key", "email")),
    "list_queues": Operation("GET", "/v1/queues", {}),
    "list_teams": Operation("GET", "/v1/teams", {}),
    "list_tags": Operation("GET", "/v1/tags", {"include_deactivated": (bool, Field(False, title="Include deactivated tags"))}, ("include_deactivated",)),
    "create_tag": Operation("POST", "/v1/tags", {"name": text("Tag name", required=True), "color": text("Color", pattern=r"^#[0-9A-Fa-f]{6}$")}, body=("name", "color")),
}
WIRE_NAMES = {"page_limit": "pageLimit", "page_key": "pageKey", "exact_match": "exactMatch", "external_id": "externalId", "display_name": "displayName", "phone_number": "phoneNumber", "first_name": "firstName", "last_name": "lastName", "agent_id": "agentId", "include_deactivated": "includeDeactivated"}


class ActionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


def make_config(name, op):
    label = name.replace("_", " ").title()
    return create_model("Dixa" + name.title().replace("_", "") + "Config", __base__=ActionConfig, __module__=__name__,
        operation=(Literal[name], Field(name, title=label, json_schema_extra={"ui:hidden": True, "x-display-name": label, "x-is-trigger": False, "x-category": "Actions"})), **op.fields)


CONFIG_MODELS = {name: make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class DixaOnNoteAddedConfig(WebhookTriggerConfigBase):
    operation: Literal["on_note_added"] = Field("on_note_added", title="On Internal Note Added", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On Internal Note Added", "x-category": "Triggers"})
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


DixaConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (DixaOnNoteAddedConfig,)], Field(discriminator="operation")]


class DixaNodeConfig(NodeConfig[DixaConfig, DixaAPITokenCredential]):
    pass


class DixaNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-dixa"
    connection_evidence = ConnectionEvidence(noun="organization", operation="get_organization", identity_operation="get_organization")
    edit_examples = ["Find conversations about a refund", "Add an internal note", "Reply to a customer", "Create an end user", "Notify me when an internal note is added"]

    @classmethod
    def get_config_model(cls):
        return DixaNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        token = DixaAPITokenCredential.model_validate(credential).api_token
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, json=body,
                headers={"Authorization": token, "Accept": "application/json"})
        if response.is_error:
            try:
                detail = response.json().get("message", "Request failed")
            except (ValueError, AttributeError):
                detail = "Request failed"
            raise ValueError(f"Dixa API {response.status_code}: {str(detail).replace(token, '[redacted]')}")
        if response.is_redirect:
            raise ValueError("Dixa returned an unexpected redirect")
        if response.status_code == 204:
            return {"acknowledged": True}
        result = response.json()
        if not isinstance(result, dict) or "data" not in result:
            raise ValueError("Dixa returned an unexpected response envelope")
        return result

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Dixa API token")
        config = self.config.config
        name = config.operation
        if name == "on_note_added":
            return self.no_event_output(name)
        op = OPERATIONS[name]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = op.path
        for key in re.findall(r"\{(\w+)\}", path):
            path = path.replace("{" + key + "}", quote(str(values[key]), safe=""))
        params = {WIRE_NAMES.get(k, k): values[k] for k in op.query if k in values}
        body = {WIRE_NAMES.get(k, k): values[k] for k in op.body if k in values} if op.body else None
        if name == "send_reply":
            body = {"_type": "Outbound", "agentId": values["agent_id"], "content": {"_type": "Text", "value": values["message"]}, "attachments": [], "cc": [], "bcc": []}
        result = await self._request(self.config.credentials.model_dump(), op.method, path, params=params, body=body)
        await self.emit(result)
        return result

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        if config.get("operation") != "on_note_added":
            raise ValueError("Select the internal note trigger")
        result = await cls._request(credential, "POST", "/v1/webhooks", body={
            "name": f"NoClick {node_id}", "url": webhook_url, "events": ["ConversationNoteAdded"],
            "authorization": {"_type": "NoAuth"}, "customHeaders": {}, "enabled": True,
        })
        subscription = result["data"]
        identifier = str(UUID(subscription["id"]))
        # Dixa issues HEX. Normalize its decoded bytes to base64 for stored state;
        # verification always uses those same bytes, never the hex text as key.
        try:
            key = bytes.fromhex(subscription["secretKey"])
            if not key:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("Dixa returned a non-hex webhook secretKey") from None
        return {"external_webhook_id": identifier, "signing_secret": base64.b64encode(key).decode("ascii")}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = config.get("external_webhook_id")
        if identifier:
            await cls._request(credential, "DELETE", "/v1/webhooks/" + str(UUID(str(identifier))))

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        try:
            key = base64.b64decode(config.get("signing_secret", ""), validate=True)
            if not key:
                return False
            header = next((v for k, v in headers.items() if k.lower() == "x-dixa-signature"), "")
            match = re.fullmatch(r"t=(\d+),v1=([0-9a-f]{64})", header)
            if not match:
                return False
            timestamp, signature = match.groups()
            expected = hmac.new(key, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
            return hmac.compare_digest(signature, expected)
        except (TypeError, ValueError):
            return False

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return config.get("operation") == "on_note_added" and payload.get("event_fqn") == "CONVERSATION_NOTE_ADDED"

    @classmethod
    def resolve_agent_event(cls, output):
        if output.get("event_fqn") != "CONVERSATION_NOTE_ADDED":
            return super().resolve_agent_event(output)
        data = output.get("data") or {}
        conversation = data.get("conversation") or {}
        organization = output.get("organization") or {}
        author = data.get("author") or {}
        requester = conversation.get("requester") or {}
        csid = conversation.get("csid")
        text = (f"{author.get('name') or author.get('id') or 'An agent'} added an internal note to Dixa conversation {csid} "
                f"in {organization.get('name') or organization.get('id')}.\n"
                f"Customer: {requester.get('name') or requester.get('id')}; channel: {conversation.get('channel')}.\n"
                f"Note: {data.get('text') or '(no text)'}\n"
                f"Conversation ID: {csid}; note ID: {data.get('note_id')}; author ID: {author.get('id')}; "
                f"requester ID: {requester.get('id')}; event ID: {output.get('event_id')}.")
        return {"text": text, "conversation_key": f"dixa:{organization.get('id')}:{csid}", "title": f"Dixa note on conversation {csid}"}
