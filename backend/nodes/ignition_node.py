"""Automate Ignition practice records with a manually supplied Ignition API key.

Each operation makes one documented Core API v1 request. Writes preserve omitted
fields, explicit clearing and caller-supplied idempotency keys without retries.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, ClassVar, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.ignitionapp.com/rest/v1"
DOCS = "https://developers.ignitionapp.com/docs/core/"


class IgnitionAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Ignition API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://go.ignitionapp.com/settings/developers",
        "x-credential-instructions": "An admin must enable the Ignition API in Settings → Labs, then create an API key in Developer hub. Paste the key without Bearer. Include practice:read for the connection check. Select clients:read/write, services:read/write, proposals:read/write, invoices:read, payments:read and tax_rates:read as needed for your operations. The key acts with its creator's permissions.",
    })
    credential_type: Literal["ignition_api_key"] = Field("ignition_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Payload(_Input):
    nullable_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def explicit_nulls(self):
        for name in self.model_fields_set - self.nullable_fields:
            if getattr(self, name) is None:
                raise ValueError(f"Omit {name} instead of sending null")
        return self


# Ignition's own MCP server: agents get its tools through a person's Ignition sign-in.
IgnitionMcpCredential = mcp_credential("ignition", "https://mcp.ignitionapp.com/mcp", app="Ignition")
IgnitionCredential = Union[IgnitionAPIKeyCredential, IgnitionMcpCredential]


Slug = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")]


class Address(_Payload):
    line1: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None


class ClientFields(_Payload):
    nullable_fields = frozenset({"phone", "website", "tax_number", "company_number", "business_structure", "notes", "external_id"})
    name: str | None = None
    phone: str | None = None
    website: str | None = None
    tax_number: str | None = None
    company_number: str | None = None
    business_structure: str | None = None
    notes: str | None = None
    external_id: str | None = None
    address: Address | None = None
    postal_address: Address | None = None


class NewClientContact(_Payload):
    name: str = Field(..., min_length=1)
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    is_primary: bool | None = None
    receives_invoice_emails: bool | None = None


class ClientCreateBody(ClientFields):
    name: str = Field(..., min_length=1)
    contacts: list[NewClientContact] = Field(..., min_length=1)


class ContactBody(NewClientContact):
    nullable_fields = frozenset({"external_id"})
    external_id: str | None = None
    salutation: str | None = None
    addressee: str | None = None


PriceType = Literal["fixed", "unit", "minimum", "range", "included"]
BillingMode = Literal["upfront", "on_completion", "recurring", "estimate", "included"]


class ServiceFields(_Payload):
    name: str | None = None
    description: str | None = None
    terms: str | None = None
    billing_mode: BillingMode | None = None
    price_type: PriceType | None = None
    amount_cents: int | None = None
    unit_name: str | None = None
    minimum_cents: int | None = None
    maximum_cents: int | None = None
    tax_rate_slug: Slug | None = None


class ServiceCreateBody(ServiceFields):
    name: str = Field(..., min_length=1)
    price_type: PriceType
    tax_rate_slug: Slug


class ProposalFields(_Payload):
    name: str | None = None
    personalised_message: str | None = None
    next_steps_message: str | None = None
    start_on: Literal["acceptance", "date"] | None = None
    start_date: date | None = None
    contract_term: Literal["ongoing", "fixed"] | None = None
    minimum_contract_length: int | None = Field(None, ge=1)
    auto_expiring: bool | None = None
    auto_expire_days: int | None = Field(None, ge=1)
    email_template_slug: str | None = None
    terms_template_slug: str | None = None
    sender_user_slug: str | None = None
    service_price_display: str | None = None
    proposal_value_display: str | None = None
    one_time_date_display: str | None = None

    @model_validator(mode="after")
    def required_companions(self):
        if self.start_on == "date" and self.start_date is None:
            raise ValueError("Supply start_date when start_on is date")
        if self.contract_term == "fixed" and self.minimum_contract_length is None:
            raise ValueError("Supply minimum_contract_length for a fixed contract")
        if self.auto_expiring is True and self.auto_expire_days is None:
            raise ValueError("Supply auto_expire_days when auto_expiring is true")
        return self


class ProposalCreateBody(ProposalFields):
    template_slug: Slug
    client_slug: Slug
    contract_term: Literal["ongoing", "fixed"] = "ongoing"


class _Page(_Input):
    limit: int = Field(100, ge=1, le=100)
    starting_after: Slug | None = None
    ending_before: Slug | None = None
    sort: str | None = Field(None, description="One documented sort field for this endpoint, optionally prefixed with -.")

    @model_validator(mode="after")
    def one_cursor(self):
        if self.starting_after and self.ending_before:
            raise ValueError("Use only one pagination cursor")
        return self


class GetPractice(_Input):
    operation: Literal["get_practice"] = "get_practice"


class ListClients(_Page):
    operation: Literal["list_clients"] = "list_clients"
    name: str | None = None
    state: Literal["lead", "active", "inactive", "archived"] | None = None
    external_id: str | None = None
    reference: str | None = None
    tag: str | None = None
    partner_slug: Slug | None = None


class _Client(_Input):
    client_slug: Slug


class _Write(_Input):
    idempotency_key: str | None = Field(None, max_length=255, pattern=r"^[\x21-\x7e]+$", description="Reuse this key only when retrying the same write. NoClick makes one attempt.")


class GetClient(_Client):
    operation: Literal["get_client"] = "get_client"


class CreateClient(_Write):
    operation: Literal["create_client"] = "create_client"
    data: ClientCreateBody = Field(..., description="Client and at least one contact. A nonblank external_id enables upsert.")


class UpdateClient(_Write, _Client):
    operation: Literal["update_client"] = "update_client"
    data: ClientFields = Field(..., description="Omit fields to preserve; send null for nullable scalar fields to clear.")


class ArchiveClient(_Write, _Client):
    operation: Literal["archive_client"] = "archive_client"


class RestoreClient(_Write, _Client):
    operation: Literal["restore_client"] = "restore_client"


class ListContacts(_Page, _Client):
    operation: Literal["list_contacts"] = "list_contacts"
    external_id: str | None = None


class GetContact(_Input):
    operation: Literal["get_contact"] = "get_contact"
    contact_slug: Slug


class CreateContact(_Write, _Client):
    operation: Literal["create_contact"] = "create_contact"
    data: ContactBody


class UpdateContact(_Write):
    operation: Literal["update_contact"] = "update_contact"
    contact_slug: Slug
    data: ContactBody = Field(..., description="Name is required even on PATCH. A null external_id clears its stored value.")


class ListServices(_Page):
    operation: Literal["list_services"] = "list_services"


class GetService(_Input):
    operation: Literal["get_service"] = "get_service"
    service_slug: Slug


class CreateService(_Write):
    operation: Literal["create_service"] = "create_service"
    data: ServiceCreateBody


class UpdateService(_Write):
    operation: Literal["update_service"] = "update_service"
    service_slug: Slug
    data: ServiceFields


class ListTaxRates(_Page):
    operation: Literal["list_tax_rates"] = "list_tax_rates"


class ListProposalTemplates(_Page):
    operation: Literal["list_proposal_templates"] = "list_proposal_templates"


class ListProposals(_Page):
    operation: Literal["list_proposals"] = "list_proposals"
    state: Literal["draft", "awaiting_acceptance", "accepted", "completed", "lost"] | None = None
    client_slug: Slug | None = None


class GetProposal(_Input):
    operation: Literal["get_proposal"] = "get_proposal"
    proposal_slug: Slug


class CreateProposal(_Write):
    operation: Literal["create_proposal"] = "create_proposal"
    data: ProposalCreateBody = Field(..., description="Create a draft from an existing template and client. Sending is a separate action.")


class UpdateProposal(_Write):
    operation: Literal["update_proposal"] = "update_proposal"
    proposal_slug: Slug
    data: ProposalFields = Field(..., description="Edit a draft; use empty strings to clear text or reset templates. Null is not accepted.")


class SendProposal(_Write):
    operation: Literal["send_proposal"] = "send_proposal"
    proposal_slug: Slug = Field(..., description="Sends this proposal to its client by email.")


class ListInvoices(_Page):
    operation: Literal["list_invoices"] = "list_invoices"
    state: Literal["issued", "archived", "voided"] | None = None
    payment_state: Literal["unpaid", "partially_paid", "paid"] | None = None
    client_slug: Slug | None = None


class GetInvoice(_Input):
    operation: Literal["get_invoice"] = "get_invoice"
    invoice_slug: Slug


class ListPayments(_Page):
    operation: Literal["list_payments"] = "list_payments"
    state: str | None = None
    failed_only: bool | None = None


IgnitionOperation = Annotated[Union[GetPractice, ListClients, GetClient, CreateClient,
    UpdateClient, ArchiveClient, RestoreClient, ListContacts, GetContact, CreateContact,
    UpdateContact, ListServices, GetService, CreateService, UpdateService, ListTaxRates,
    ListProposalTemplates, ListProposals, GetProposal, CreateProposal, UpdateProposal,
    SendProposal, ListInvoices, GetInvoice, ListPayments], Field(discriminator="operation")]


class IgnitionConfig(NodeConfig[IgnitionOperation, IgnitionCredential]):
    pass


# Fixed routes keep every operation tied to exactly one published API operation.
ROUTES = {
    "get_practice": ("GET", "/practice", "practice"),
    "list_clients": ("GET", "/clients", "client"),
    "get_client": ("GET", "/clients/{client_slug}", "client"),
    "create_client": ("POST", "/clients", "client"),
    "update_client": ("PATCH", "/clients/{client_slug}", "client"),
    "archive_client": ("POST", "/clients/{client_slug}/archive", "client"),
    "restore_client": ("POST", "/clients/{client_slug}/restore", "client"),
    "list_contacts": ("GET", "/clients/{client_slug}/contacts", "contact"),
    "get_contact": ("GET", "/contacts/{contact_slug}", "contact"),
    "create_contact": ("POST", "/clients/{client_slug}/contacts", "contact"),
    "update_contact": ("PATCH", "/contacts/{contact_slug}", "contact"),
    "list_services": ("GET", "/services", "service"),
    "get_service": ("GET", "/services/{service_slug}", "service"),
    "create_service": ("POST", "/services", "service"),
    "update_service": ("PATCH", "/services/{service_slug}", "service"),
    "list_tax_rates": ("GET", "/tax_rates", "tax_rate"),
    "list_proposal_templates": ("GET", "/proposal_templates", "proposal_template"),
    "list_proposals": ("GET", "/proposals", "proposal"),
    "get_proposal": ("GET", "/proposals/{proposal_slug}", "proposal"),
    "create_proposal": ("POST", "/proposals", "proposal"),
    "update_proposal": ("PATCH", "/proposals/{proposal_slug}", "proposal"),
    "send_proposal": ("POST", "/proposals/{proposal_slug}/send", "proposal"),
    "list_invoices": ("GET", "/invoices", "invoice"),
    "get_invoice": ("GET", "/invoices/{invoice_slug}", "invoice"),
    "list_payments": ("GET", "/payments", "payment"),
}


def _resource(value, kind):
    if not isinstance(value, dict) or value.get("object") != kind or not isinstance(value.get("slug"), str) or not value["slug"]:
        raise ValueError("Ignition returned an unexpected resource")
    return value


class IgnitionNode(WorkflowNode):
    integration_type = "automation-ignition"
    credential_provider_labels = {"ignition": "Ignition Account"}
    connection_evidence = ConnectionEvidence(noun="Ignition practice", identity_operation="get_practice")

    @classmethod
    def get_config_model(cls):
        return IgnitionConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Ignition API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, route, kind = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation", "data", "idempotency_key"})
        for name in tuple(values):
            marker = "{" + name + "}"
            if marker in route:
                route = route.replace(marker, quote(str(values.pop(name)), safe=""))
        headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
        if getattr(config, "idempotency_key", None):
            headers["Idempotency-Key"] = config.idempotency_key
        body = config.data.model_dump(mode="json", exclude_unset=True) if hasattr(config, "data") else None
        if isinstance(config, CreateProposal):
            # Default explicitly overrides Ignition's fixed-term default.
            body.setdefault("contract_term", config.data.contract_term)
        kwargs = {"params": values}
        if body is not None:
            kwargs["json"] = body
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + route, headers=headers, **kwargs)
        except httpx.RequestError:
            raise ValueError("Ignition request did not complete; a write may have been applied. Check Ignition before retrying with the same idempotency key.") from None
        if not response.is_success:
            try:
                error = response.json().get("error", {})
                message = error.get("message") or f"Ignition HTTP {response.status_code}"
                code = error.get("code")
            except (ValueError, AttributeError):
                message, code = f"Ignition HTTP {response.status_code}", None
            output = {"status": "error", "http_status": response.status_code, "error": str(message).replace(key, "[redacted]"), "code": code}
            if "Retry-After" in response.headers:
                output["retry_after"] = response.headers["Retry-After"]
            return output
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Ignition returned an invalid JSON response") from None
        if config.operation.startswith("list_"):
            if not isinstance(payload, dict) or payload.get("object") != "list" or not isinstance(payload.get("data"), list) or type(payload.get("has_more")) is not bool:
                raise ValueError("Ignition returned an unexpected list envelope")
            for row in payload["data"]:
                _resource(row, kind)
            if payload["has_more"] and not payload["data"]:
                raise ValueError("Ignition returned a nonadvancing page")
            data = payload["data"]
            backwards = getattr(config, "ending_before", None) is not None
            output = {"status": "success", "data": data, "has_more": payload["has_more"],
                "next_starting_after": data[-1]["slug"] if data and payload["has_more"] and not backwards else None,
                "next_ending_before": data[0]["slug"] if data and payload["has_more"] and backwards else None}
        else:
            output = {"status": "success", "data": _resource(payload, kind)}
        await self.emit(output)
        return output
