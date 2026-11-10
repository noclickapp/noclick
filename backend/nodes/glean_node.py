"""Glean Client and Platform API operations from published OpenAPI contracts.

Preset webhooks use Glean's Standard Webhooks signature and managed lifecycle.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import time
from dataclasses import dataclass
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client, normalize_provider_https_origin


class GleanAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Glean API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developers.glean.com/api-info/client/authentication/glean-issued",
        "x-credential-instructions": "In Glean Admin Console → Platform → Client API Tokens, create a Glean-issued USER token for your email. Enable COLLECTIONS to verify the connection, plus SEARCH, DOCUMENTS, ANSWERS and SHORTCUTS for the actions you need, and TRIGGERS for preset events. Paste the token with your instance backend URL (https://yourcompany-be.glean.com). This connection accepts user-scoped Client API tokens; global and Indexing API tokens need a different setup.",
    })
    credential_type: Literal["glean_api_token"] = Field("glean_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    backend_url: str = Field(..., title="Instance backend URL", description="https://yourcompany-be.glean.com")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API token without the Bearer prefix")
        return value

    @field_validator("backend_url", mode="before")
    @classmethod
    def origin(cls, value):
        origin = normalize_provider_https_origin(value, "glean.com", field_name="Glean backend URL")
        if not re.fullmatch(r"https://[a-z0-9][a-z0-9-]*-be\.glean\.com", origin):
            raise ValueError("Use your instance backend URL: https://yourcompany-be.glean.com")
        return origin


class GleanInput(BaseModel):
    # Saved canvas config also carries labels and credential attachment metadata.
    # Only declared API fields survive parsing and enter the request body.
    model_config = ConfigDict(extra="ignore")


class GleanDocumentSpec(GleanInput):
    id: str = Field(..., min_length=1, title="Glean document ID")


class GleanCollectionItem(GleanInput):
    url: str = Field(..., min_length=1, title="Document URL")
    name: Optional[str] = None
    description: Optional[str] = None
    itemType: Literal["URL"] = "URL"


def text(title, required=False):
    return (str if required else Optional[str], Field(... if required else None, title=title, min_length=1))


def number(title, required=False):
    return (int if required else Optional[int], Field(... if required else None, title=title))


@dataclass(frozen=True)
class Operation:
    label: str
    path: str
    fields: dict
    method: str = "POST"
    container: Optional[str] = None
    query: tuple[str, ...] = ()


COLLECTION = {"id": number("Collection ID", True)}
ANSWER = {"id": number("Answer ID", True)}
SHORTCUT = {"id": number("Go Link ID", True)}
COLLECTION_WRITE = {"name": text("Collection name", True), "description": text("Description"), "parentId": number("Parent collection ID")}
ANSWER_WRITE = {"question": text("Question", True), "bodyText": text("Answer text", True)}
SHORTCUT_WRITE = {"inputAlias": text("Go Link alias", True), "destinationUrl": text("Destination URL", True), "description": text("Description")}
PAGE = {"page_size": (int, Field(50, ge=1, le=100, title="Page size")), "cursor": text("Next cursor")}
OPERATIONS = {
    "search": Operation("Search", "/rest/api/v1/search", {"query": text("Search query", True), "pageSize": (int, Field(10, ge=1, le=100)), "cursor": text("Next cursor")}),
    "get_documents": Operation("Get Documents", "/rest/api/v1/getdocuments", {"documentSpecs": (list[GleanDocumentSpec], Field(..., min_length=1, title="Documents", json_schema_extra={"ui:widget": "state_editor", "placeholder": "[]"}))}),
    "list_collections": Operation("List Collections", "/rest/api/v1/listcollections", {"query": text("Collection name contains")}),
    "get_collection": Operation("Get Collection", "/rest/api/v1/getcollection", {**COLLECTION, "withItems": (bool, Field(False, title="Include items"))}),
    "create_collection": Operation("Create Collection", "/rest/api/v1/createcollection", COLLECTION_WRITE),
    "update_collection": Operation("Update Collection", "/rest/api/v1/editcollection", {**COLLECTION, **COLLECTION_WRITE}),
    "delete_collections": Operation("Delete Collections", "/rest/api/v1/deletecollection", {"ids": (list[int], Field(..., min_length=1, title="Collection IDs", json_schema_extra={"ui:widget": "state_editor", "placeholder": "[]"}))}),
    "add_collection_items": Operation("Add Collection Items", "/rest/api/v1/addcollectionitems", {"collectionId": number("Collection ID", True), "addedCollectionItemDescriptors": (list[GleanCollectionItem], Field(..., min_length=1, title="Items", json_schema_extra={"ui:widget": "state_editor", "placeholder": "[]"}))}),
    "delete_collection_item": Operation("Remove Collection Item", "/rest/api/v1/deletecollectionitem", {"collectionId": number("Collection ID", True), "itemId": text("Item ID", True)}),
    "list_answers": Operation("List Answers", "/rest/api/v1/listanswers", {}),
    "get_answer": Operation("Get Answer", "/rest/api/v1/getanswer", ANSWER),
    "create_answer": Operation("Create Answer", "/rest/api/v1/createanswer", ANSWER_WRITE, container="data"),
    "update_answer": Operation("Update Answer", "/rest/api/v1/editanswer", {**ANSWER, **ANSWER_WRITE}),
    "delete_answer": Operation("Delete Answer", "/rest/api/v1/deleteanswer", ANSWER),
    "list_shortcuts": Operation("List Go Links", "/rest/api/v1/listshortcuts", {"pageSize": (int, Field(10, ge=1, le=100)), "cursor": text("Next cursor"), "query": text("Search Go Links")}),
    "get_shortcut": Operation("Get Go Link", "/rest/api/v1/getshortcut", SHORTCUT),
    "create_shortcut": Operation("Create Go Link", "/rest/api/v1/createshortcut", SHORTCUT_WRITE, container="data"),
    "update_shortcut": Operation("Update Go Link", "/rest/api/v1/updateshortcut", {**SHORTCUT, **SHORTCUT_WRITE}),
    "delete_shortcut": Operation("Delete Go Link", "/rest/api/v1/deleteshortcut", SHORTCUT),
    "list_trigger_presets": Operation("List Trigger Presets", "/api/trigger-presets", PAGE, method="GET", query=("page_size", "cursor")),
    "get_trigger_preset": Operation("Get Trigger Preset", "/api/trigger-presets/{preset_id}", {"preset_id": text("Preset ID", True)}, method="GET"),
}


def _model(name, spec):
    return create_model("Glean" + "".join(x.title() for x in name.split("_")) + "Config", __base__=GleanInput,
        operation=(Literal[name], Field(name, title=spec.label, json_schema_extra={"ui:hidden": True, "x-display-name": spec.label, "x-is-trigger": False})), **spec.fields)


CONFIG_MODELS = {name: _model(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class GleanOnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", title="On Glean Preset Event", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On Glean Preset Event", "x-category": "Triggers"})
    preset_id: str = Field(..., min_length=1, title="Preset ID", description="Use List Trigger Presets and Get Trigger Preset to find a preset and its required inputs.")
    inputs: dict[str, str] = Field(default_factory=dict, title="Preset inputs", description="Input names and values from Get Trigger Preset.", json_schema_extra={"ui:widget": "state_editor", "placeholder": "{}"})
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True, "ui:copyable": True})


GleanConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (GleanOnEventConfig,)], Field(discriminator="operation")]


class GleanNodeConfig(NodeConfig[GleanConfig, GleanAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class GleanNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-glean"
    connection_evidence = ConnectionEvidence(operation="list_collections", noun="collections", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return GleanNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, body=None, params=None):
        credential = GleanAPITokenCredential.model_validate(credential)
        headers = {"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"}
        # https://developers.glean.com/cookbook/customer-meeting-prep-trigger
        if path.startswith("/api/"):
            headers["x-glean-include-experimental"] = "true"
        async with guarded_async_client(timeout=45, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.backend_url + path, params=params, json=body,
                headers=headers)
        if response.status_code >= 300:
            # Preserve provider rejection text for connect, redacting the submitted token.
            detail = response.text.replace(credential.api_token, "[redacted]")[:2000]
            raise ValueError(f"Glean API error {response.status_code}: {detail}")
        return response.json() if response.content else {}

    async def execute(self, inputs):
        op = self.config.config
        if isinstance(op, GleanOnEventConfig):
            return self.resolve_trigger_payload(inputs, op.model_dump())
        if self.config.credentials is None:
            raise ValueError("Connect a Glean API token")
        spec = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        params = {key: values.pop(key) for key in spec.query if key in values}
        body = ({spec.container: values} if spec.container else values) if spec.method != "GET" else None
        data = await self._request(self.config.credentials.model_dump(), spec.method, path, body=body, params=params)
        result = {"status": "success", "operation": op.operation, "data": data}
        await self.emit(result)
        return result

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        op = GleanOnEventConfig.model_validate({**config, "webhook_url": webhook_url})
        result = await cls._request(credential, "POST", "/api/triggers", body={
            "preset_id": op.preset_id, "inputs": op.inputs, "delivery": {"webhook_url": webhook_url}})
        trigger = result["trigger"]
        if not trigger.get("trigger_id") or not trigger.get("signing_secret"):
            raise ValueError("Glean did not return the trigger ID and signing secret")
        try:
            secret = trigger["signing_secret"]
            if not secret.startswith("whsec_") or not base64.b64decode(secret[6:], validate=True):
                raise ValueError()
        except (ValueError, binascii.Error):
            # The secret cannot be retrieved later: remove a subscription we cannot verify.
            await cls._request(credential, "DELETE", "/api/triggers/" + quote(str(trigger["trigger_id"]), safe=""))
            raise ValueError("Glean returned an invalid Standard Webhooks signing secret") from None
        return {"external_webhook_id": trigger["trigger_id"], "signing_secret": trigger["signing_secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = config.get("external_webhook_id")
        if identifier:
            if not credential:
                raise ValueError("Connect Glean to remove its trigger")
            await cls._request(credential, "DELETE", "/api/triggers/" + quote(str(identifier), safe=""))

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"preset_id": config.get("preset_id"), "inputs": config.get("inputs", {})}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        headers = {k.lower(): v for k, v in headers.items()}
        secret = config.get("signing_secret", "")
        identifier, timestamp = headers.get("webhook-id", ""), headers.get("webhook-timestamp", "")
        signature = headers.get("webhook-signature", "")
        if not isinstance(secret, str) or not secret.startswith("whsec_") or not identifier or not str(timestamp).isdigit() or len(str(timestamp)) > 20:
            return False
        # https://developers.glean.com/guides/triggers/webhook-delivery
        if abs(time.time() - int(timestamp)) > 300:
            return False
        try:
            key = base64.b64decode(secret[6:], validate=True)
        except (ValueError, binascii.Error):
            return False
        message = identifier.encode() + b"." + str(timestamp).encode() + b"." + body
        expected = base64.b64encode(hmac.new(key, message, hashlib.sha256).digest()).decode()
        return bool(key) and any(part[3:].isascii() and hmac.compare_digest(part[3:], expected)
            for part in signature.split() if part.startswith("v1,"))

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if payload.get("version") != "1" or payload.get("event_type") not in {"DOCUMENT_CHANGE", "CONTENT_SCHEDULE"}:
            return {"status": "no_event"}
        if config.get("external_webhook_id") and payload.get("trigger_id") != config["external_webhook_id"]:
            return {"status": "no_event"}
        return payload

    @classmethod
    def resolve_agent_event(cls, output):
        if output.get("event_type") not in {"DOCUMENT_CHANGE", "CONTENT_SCHEDULE"}:
            return None
        lines = [f"Glean: {output.get('reason', '')} — {output.get('title', '')}",
            f"Source: {output.get('datasource', '')}; object: {output.get('doc_type', '')}",
            f"URL: {output.get('view_url', '')}", f"Document ID: {output.get('doc_id', '')}; trigger ID: {output.get('trigger_id', '')}"]
        details = [("At", output.get("event_time"))]
        if output["event_type"] == "DOCUMENT_CHANGE":
            facets = output.get("facets") or {}
            details += [("By", facets.get("from")), ("Channel", facets.get("channel")), ("Mentions", facets.get("mentions")),
                ("Content", output.get("content")), ("Content truncated", output.get("content_truncated"))]
        else:
            details += [("Schedule offset seconds", output.get("time_offset_seconds"))]
        for label, value in details:
            if value is not None:
                lines.append(f"{label}: {value}")
        lines.append("Use get_documents with this document ID to read the source content before acting.")
        return {"text": "\n".join(lines), "conversation_key": output.get("doc_id"), "title": output.get("title")}
