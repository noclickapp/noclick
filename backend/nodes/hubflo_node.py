"""Hubflo v2 client operations and signed contact/company webhook triggers.

The provider's published OpenAPI defines the fixed routes, pasted API key and
HMAC protocol. Delivery bodies are retained without inventing resource fields.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.hubflo_operations import CONFIG_MODELS, OPERATIONS

BASE = "https://app.hubflo.com"
EVENT_OPERATIONS = {"on_contact_created": "contact_created", "on_company_created": "company_created"}


class HubfloAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Hubflo API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.hubflo.com/organizations/",
            "x-credential-instructions": "In Hubflo, open organization settings → Integrations → Generate key. Paste the API key here. NoClick sends it as a bearer token to app.hubflo.com.",
        },
    )
    credential_type: Literal["hubflo_api_key"] = Field("hubflo_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class HubfloOnContactCreatedConfig(WebhookTriggerConfigBase):
    """Register a webhook for newly created contacts."""
    operation: Literal["on_contact_created"] = Field("on_contact_created", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "New Contact"})
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class HubfloOnCompanyCreatedConfig(WebhookTriggerConfigBase):
    """Register a webhook for newly created companies."""
    operation: Literal["on_company_created"] = Field("on_company_created", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "New Company"})
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


HubfloConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (
    HubfloOnContactCreatedConfig, HubfloOnCompanyCreatedConfig)], Field(discriminator="operation")]


class HubfloNodeConfig(NodeConfig[HubfloConfig, HubfloAPIKeyCredential]):
    pass


class HubfloNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-hubflo"
    connection_evidence = ConnectionEvidence(operation="get_organization", noun="organization",
                                               identity_operation="get_organization")

    @classmethod
    def get_config_model(cls):
        return HubfloNodeConfig

    @staticmethod
    async def _request(api_key: str, method: str, path: str, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json",
                         "Content-Type": "application/json"})
        if not response.is_success:
            try:
                message = response.json().get("message") or response.reason_phrase
            except (ValueError, AttributeError):
                message = response.reason_phrase
            # Keep the provider's rejection useful while never echoing a credential.
            raise ValueError(f"Hubflo API {response.status_code}: {str(message).replace(api_key, '[redacted]')}")
        return (response.json() if response.content else {}), response.headers

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = EVENT_OPERATIONS.get((config or {}).get("operation"))
        if event is None:
            raise ValueError("Choose a Hubflo trigger")
        key = HubfloAPIKeyCredential.model_validate(credential).api_key
        data, _ = await cls._request(key, "POST", "/api/v2/webhooks",
                                   body={"url": webhook_url, "event_names": [event]})
        if not isinstance(data, dict) or not data.get("id") or not data.get("secret"):
            raise ValueError("Hubflo did not return a webhook ID and signing secret")
        return {"external_webhook_id": data["id"], "signing_secret": data["secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        webhook_id = (config or {}).get("external_webhook_id")
        if webhook_id and credential:
            key = HubfloAPIKeyCredential.model_validate(credential).api_key
            await cls._request(key, "DELETE", "/api/v2/webhooks/" + quote(str(webhook_id), safe=""))

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        secret = (config or {}).get("signing_secret")
        received = next((v for k, v in headers.items() if k.lower() == "x-hubflo-signature"), "")
        if not isinstance(secret, str) or not secret or not isinstance(received, str):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return len(received) == 64 and received.isascii() and hmac.compare_digest(expected, received)

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        event = EVENT_OPERATIONS.get((config or {}).get("operation"))
        if event is None:
            return None
        # Hubflo chooses the subscription at registration. Its delivery example
        # has no event_name field, so carry the configured event beside the body.
        return {"event_name": event, "data": payload}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("event_name") not in EVENT_OPERATIONS.values():
            return None
        payload = output.get("data")
        if not isinstance(payload, dict):
            return None
        delivery = payload.get("webhook_delivery_id")
        when = payload.get("webhook_delivery_created_at")
        content = payload.get("data")
        label = output["event_name"].replace("_", " ")
        return {
            "title": f"Hubflo: {label}",
            "text": f"Hubflo reported {label}.\nDelivery: {delivery}\nAt: {when}\n"
                    f"Content: {json.dumps(content, ensure_ascii=False)}\n"
                    "Use list_contacts or list_companies to find the record before acting; "
                    "the documented delivery does not identify the person or resource ID.",
            "conversation_key": str(delivery),
        }

    async def execute(self, inputs):
        op = self.config.config
        if op.operation in EVENT_OPERATIONS:
            return self.no_event_output(op.operation)
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Hubflo account")
        method, path, query_fields, body_fields = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            identifier = str(values.pop("id"))
            if identifier in {".", ".."} or any(c in identifier for c in "/?#\\"):
                raise ValueError("Use a single Hubflo resource ID")
            path = path.replace("{id}", quote(identifier, safe=""))
        params = {key: values[key] for key in query_fields if key in values}
        body = {key: values[key] for key in body_fields if key in values}
        for key in body_fields:
            if key.startswith("recurrence_") and key in op.model_fields_set and getattr(op, key) is None:
                body[key] = None
        data, headers = await self._request(credential.api_key, method, path, params=params or None,
                                          body=body if method in {"POST", "PATCH"} else None)
        result = {"status": "success", "operation": op.operation, "data": data}
        if op.operation.startswith("list_"):
            next_page = headers.get("X-Next-Page")
            result["next_page"] = int(next_page) if next_page and next_page.isdigit() else None
            result["page"] = op.page
        return result
