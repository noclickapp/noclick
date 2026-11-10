"""Pledge API v1 donations, fundraisers, charity search and signed events.

Routes and payloads follow Pledge's published OpenAPI 1.0.1. A primary API key
connects by hand and also authenticates webhook deliveries as Pledge documents.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from decimal import Decimal
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

DOCS = "https://developer.pledge.to/"
TOPICS = ("donation/created", "organization_request/approved", "organization_request/declined")
TRIGGER = "on_event"


class PledgeAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Pledge API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.pledge.to/impact-hub/direct/apis/keys",
        "x-credential-instructions": "Paste your primary API key from Impact Hub. Pledge uses this key for bearer authentication and webhook signatures. Choose Sandbox only for a sandbox account and key.",
    })
    credential_type: Literal["pledge_api_key"] = Field("pledge_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Primary API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    environment: Literal["production", "sandbox"] = Field("production", title="Environment")

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Primary API Key")
        if any(c.isspace() for c in value) or len(value) > 4096:
            raise ValueError("Paste only the primary API key without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DonationFields(_Input):
    email: str = Field(..., min_length=1, json_schema_extra={"format": "email"})
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    amount: str = Field(..., pattern=r"^[0-9]+(?:\.[0-9]+)?$", description="Donation amount as a decimal string, for example 0.25. Creates a real donation billed to your payment method.")
    organization_id: UUID
    phone_number: str | None = None
    metadata: str | None = None
    send_tax_receipt: bool | None = Field(None, description="Ask Pledge to email a tax receipt to the donor.")

    @field_validator("amount")
    @classmethod
    def positive(cls, value):
        if Decimal(value) <= 0:
            raise ValueError("Donation amount must be positive")
        return value


class Organizer(_Input):
    email: str = Field(..., json_schema_extra={"format": "email"})
    first_name: str | None = None
    last_name: str | None = None


class FundraiserFields(_Input):
    organization_ids: list[UUID] = Field(..., min_length=1, description="Nonprofit beneficiaries. This operation uses Pledge's multiple-organizations fundraiser form.")
    name: str | None = None
    donation_flow: Literal["express", "guided"] | None = None
    start_time: str | None = Field(None, json_schema_extra={"format": "date-time"})
    end_time: str | None = Field(None, json_schema_extra={"format": "date-time"})
    goal: str | None = Field(None, description="Decimal fundraising goal.")
    organizers: list[Organizer] | None = Field(None, description="Organizers Pledge may notify of fundraiser events.")


class CalculatorFields(_Input):
    name: str
    icon: Literal["food", "animals", "arts", "clean-energy", "clean-water", "natural-disaster", "disease-medicine", "dress", "economic-growth", "education", "employment", "environment", "gender-equality", "gift", "health", "housing", "human-rights", "lgbtqia", "philanthropy", "spirituality", "ribbon", "veterans", "other"]
    color: str = Field(..., pattern=r"^#[0-9a-fA-F]{6}$")
    formula: str
    description: str
    style: Literal["background", "foreground"] | None = None
    organization_ids: list[UUID] | None = None
    currency_symbol: str | None = None
    info: str | None = None


class OrganizationRequestFields(_Input):
    ngo_id: str = Field(..., description="Government-issued nonprofit identifier.")


class WebhookFields(_Input):
    url: str = Field(..., json_schema_extra={"format": "uri"}, description="HTTPS address to receive Pledge event deliveries.")


# Each entry maps to exactly one operation in the provider's OpenAPI contract.
# Method, path and query fields are fixed; callers cannot supply an arbitrary route.
OPERATIONS = {
    "list_donations": ("GET", "/donations", "Donations"),
    "create_donation": ("POST", "/donations", "Donations"),
    "get_donation": ("GET", "/donations/{id}", "Donations"),
    "create_fundraiser": ("POST", "/fundraisers", "Fundraisers"),
    "get_fundraiser": ("GET", "/fundraisers/{id}", "Fundraisers"),
    "update_fundraiser": ("PATCH", "/fundraisers/{id}", "Fundraisers"),
    "place_fundraiser": ("PUT", "/fundraisers/{id}", "Fundraisers"),
    "list_impact_calculators": ("GET", "/impact_calculators", "Impact Calculators"),
    "create_impact_calculator": ("POST", "/impact_calculators", "Impact Calculators"),
    "get_impact_calculator": ("GET", "/impact_calculators/{id}", "Impact Calculators"),
    "update_impact_calculator": ("PATCH", "/impact_calculators/{id}", "Impact Calculators"),
    "search_organizations": ("GET", "/organizations", "Organizations"),
    "request_organization": ("POST", "/organizations", "Organizations"),
    "get_organization": ("GET", "/organizations/{id}", "Organizations"),
    "list_webhooks": ("GET", "/webhooks", "Webhooks"),
    "create_webhook": ("POST", "/webhooks", "Webhooks"),
    "get_webhook": ("GET", "/webhooks/{id}", "Webhooks"),
    "delete_webhook": ("DELETE", "/webhooks/{id}", "Webhooks"),
}
BODY_MODELS = {
    "create_donation": DonationFields,
    "create_fundraiser": FundraiserFields,
    "update_fundraiser": FundraiserFields,
    "place_fundraiser": FundraiserFields,
    "create_impact_calculator": CalculatorFields,
    "update_impact_calculator": CalculatorFields,
    "request_organization": OrganizationRequestFields,
    "create_webhook": WebhookFields,
}
MODELS = {}
for _name, (_method, _path, _category) in OPERATIONS.items():
    _label = _name.replace("_", " ").title()
    _fields = {"operation": (Literal[_name], Field(_name, title=_label, json_schema_extra={
        "ui:hidden": True, "x-display-name": _label, "x-category": _category,
    }))}
    if "{id}" in _path:
        _fields["id"] = (str, Field(..., min_length=1, max_length=256, title="Resource ID", pattern=r"^[A-Za-z0-9_-]+$"))
    if _name == "create_fundraiser":
        _fields["id"] = (str | None, Field(None, max_length=256, pattern=r"^[A-Za-z0-9_-]+$", description="Optional external fundraiser ID; otherwise Pledge generates one."))
    if _name.startswith("list_") or _name == "search_organizations":
        _fields["page"] = (int, Field(1, ge=1, description="Page number. Return one page per run; inspect next/previous in the provider response."))
    if _name == "search_organizations":
        _fields.update({"per": (int, Field(25, ge=1)), "cause_id": (int | None, None)})
        for _key in ("q", "ngo_id", "region", "postal_code", "country", "lat", "lon"):
            _fields[_key] = (str | None, None)
    MODELS[_name] = create_model("Pledge" + _label.replace(" ", "") + "Config", __base__=BODY_MODELS.get(_name, _Input), **_fields)


class _Trigger(WebhookTriggerConfigBase):
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True,
    })


class PledgeOnEventConfig(_Trigger):
    operation: Literal["on_event"] = Field("on_event", title="On Pledge Event", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Pledge Event",
    })
    event_type: Literal["all", "donation/created", "organization_request/approved", "organization_request/declined"] = Field(
        "all", title="Event Type", description="Pledge delivers all topics to each endpoint. Choose which ones start this workflow.")


MODELS[TRIGGER] = PledgeOnEventConfig

PledgeConfig = Annotated[Union[tuple(MODELS.values())], Field(discriminator="operation")]


class PledgeNodeConfig(NodeConfig[PledgeConfig, PledgeAPIKeyCredential]):
    pass


class PledgeNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-pledge"
    connection_evidence = ConnectionEvidence(operation="list_donations", noun="donations", label_keys=("email", "id"))
    webhook_replace_stale_endpoint = True

    @classmethod
    def get_config_model(cls):
        return PledgeNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        cred = PledgeAPIKeyCredential.model_validate(credential)
        host = "api-staging.pledge.to" if cred.environment == "sandbox" else "api.pledge.to"
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, f"https://{host}/v1{path}", params=params, json=body,
                headers={"Authorization": f"Bearer {cred.api_key}", "Accept": "application/json"})
        if response.is_error or response.is_redirect:
            # Provider errors are returned verbatim after removing the credential.
            detail = response.text.replace(cred.api_key, "[redacted]")[:1500]
            raise ValueError(f"Pledge API {response.status_code}: {detail}")
        return response.json() if response.content else {"deleted": True}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Pledge primary API key")
        op = self.config.config
        if op.operation == TRIGGER:
            result = self.resolve_trigger_payload(inputs, op.model_dump())
            if result is None:
                return {"status": "no_event", "skipped": True}
        else:
            method, path, _ = OPERATIONS[op.operation]
            values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
            if "{id}" in path:
                path = path.replace("{id}", quote(values.pop("id"), safe=""))
            data = await self._request(self.config.credentials.model_dump(), method, path,
                params=values if method == "GET" else None,
                body=values if method in {"POST", "PATCH", "PUT"} else None)
            result = {"status": "success", "operation": op.operation, "data": data}
        await self.emit(result)
        return result

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        cred = PledgeAPIKeyCredential.model_validate(credential)
        if config.get("operation") != TRIGGER:
            raise ValueError("Choose a supported Pledge trigger")
        endpoint = await cls._request(cred.model_dump(), "POST", "/webhooks", body={"url": webhook_url})
        if not endpoint.get("id"):
            raise ValueError("Pledge did not return a webhook endpoint ID")
        # Pledge signs all topics using the account's PRIMARY key, not a new secret.
        return {"external_webhook_id": str(endpoint["id"]), "signing_secret": cred.api_key}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = config.get("external_webhook_id")
        if identifier and credential:
            await cls._request(credential, "DELETE", "/webhooks/" + quote(str(identifier), safe=""))

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict, config: dict) -> bool:
        secret = config.get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "pledgeling-signature"), "")
        if not isinstance(secret, str) or not secret or not isinstance(signature, str):
            return False
        expected = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
        return hmac.compare_digest(expected, signature)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        if config.get("operation") != TRIGGER or not isinstance(payload, dict):
            return False
        topic = payload.get("topic")
        selected = config.get("event_type") or "all"
        return isinstance(topic, str) and bool(topic) and (selected == "all" or selected == topic)

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if not cls.filter_trigger_payload(payload, config):
            return None
        topic = payload["topic"]
        if not isinstance(payload.get("data"), dict):
            return None
        return {"topic": topic, "data": payload["data"]}

    @classmethod
    def should_propagate_output(cls, output, config):
        return not output.get("skipped", False)

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return None
        topic = output.get("topic")
        record = output.get("data")
        if not isinstance(topic, str) or not topic or not isinstance(record, dict):
            return None
        if topic == "donation/created":
            name = " ".join(str(record.get(k) or "") for k in ("first_name", "last_name")).strip()
            identifier = record.get("id")
            text = f"Pledge donation created: {name} ({record.get('email')}) donated {record.get('amount')} to organization {record.get('organization_id')}."
            text += f"\nDonation ID: {identifier}. Fundraiser ID: {record.get('external_id')}. Status: {record.get('status')}."
            text += f"\nUse get_donation with id={identifier} to inspect this donation."
        elif topic in {"organization_request/approved", "organization_request/declined"}:
            identifier = record.get("ngo_id")
            text = f"Pledge organization request {topic.rsplit('/', 1)[-1]}: nonprofit {identifier}, status {record.get('status')}."
            if topic == "organization_request/declined":
                text += f"\nReason: {record.get('reason') or 'No reason supplied'}."
            text += f"\nUse search_organizations with ngo_id={identifier} to look up the nonprofit."
        else:
            # The contract allows arbitrary topics. Preserve future provider events
            # without interpreting their data as donations or charity requests.
            identifier = None
            text = f"Pledge event {topic}:\n{json.dumps(record, ensure_ascii=False, default=str)[:6000]}"
        return {"text": text, "title": "Pledge " + topic.replace("/", " "), "conversation_key": str(identifier) if identifier else None}
