"""BetterContact v2 enrichment and prospect searches with a manually supplied API key."""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.bettercontact_operations import (
    RequestModel, NewLeadsEnrichment, LeadFinderRequest, CompanyFinderRequest,
    EnrichCompanyRequest,
)
from utils.ssrf import guarded_async_client

BASE = "https://app.bettercontact.rocks/api/v2"


class BettercontactAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Bettercontact API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.bettercontact.rocks/api_requests",
            "x-credential-instructions": "Copy your API key from BetterContact's API section and paste it here. NoClick sends it in the X-API-Key header. Connecting reads your account email and credit balance.",
        })
    credential_type: Literal["bettercontact_api_key"] = Field("bettercontact_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not isinstance(value, str) or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class GetAccount(RequestModel):
    """Read the account email and remaining credits."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class CreateEnrichment(NewLeadsEnrichment):
    """Start email, phone or LinkedIn profile enrichment for 1–100 leads. Consumes credits."""
    operation: Literal["create_enrichment"] = Field("create_enrichment", json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def identifiers(self):
        for lead in self.data:
            if not (lead.company or lead.company_domain):
                raise ValueError("Each lead needs a company or company_domain")
            if self.enrich_profile and not lead.linkedin_url:
                raise ValueError("Profile enrichment needs each lead's linkedin_url")
        if self.push_contact_individually and not self.contact_webhook:
            raise ValueError("Individual delivery needs contact_webhook")
        return self


def _has_value(value):
    if isinstance(value, dict):
        return any(_has_value(v) for k, v in value.items() if k not in {"exact_match", "limit_per_company"})
    if isinstance(value, list):
        return any(_has_value(v) for v in value)
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


class CreateLeadFinderSearch(LeadFinderRequest):
    """Start a lead search; paginate by keeping limit fixed and increasing offset. May consume credits."""
    operation: Literal["create_lead_finder_search"] = Field("create_lead_finder_search", json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def criteria(self):
        if not _has_value(self.filters.model_dump(exclude_none=True)):
            raise ValueError("Provide at least one nonempty lead search filter")
        return self


class CreateCompanyFinderSearch(CompanyFinderRequest):
    """Start a company search; paginate with limit and offset. Consumes search credits; no webhooks."""
    operation: Literal["create_company_finder_search"] = Field("create_company_finder_search", json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def criteria(self):
        if not _has_value(self.filters.model_dump(exclude_none=True)):
            raise ValueError("Provide at least one nonempty company search filter")
        return self


class RequestID(RequestModel):
    request_id: str = Field(..., min_length=1, max_length=512, description="The id or request_id returned by the matching create action.")

    @field_validator("request_id")
    @classmethod
    def identifier(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 33 for c in value):
            raise ValueError("Use the request ID returned by BetterContact")
        return value


class GetEnrichment(RequestID):
    """Read one enrichment job. Only status terminated means processing is finished."""
    operation: Literal["get_enrichment"] = Field("get_enrichment", json_schema_extra={"ui:hidden": True})


class GetLeadFinderSearch(RequestID):
    """Read a lead search job; on_hold needs more credits, processing needs another read later."""
    operation: Literal["get_lead_finder_search"] = Field("get_lead_finder_search", json_schema_extra={"ui:hidden": True})


class GetCompanyFinderSearch(RequestID):
    """Read a company search job; terminated can have an empty companies array."""
    operation: Literal["get_company_finder_search"] = Field("get_company_finder_search", json_schema_extra={"ui:hidden": True})


class EnrichCompany(EnrichCompanyRequest):
    """Look up a company profile synchronously by domain or LinkedIn URL; consumes no credits."""
    operation: Literal["enrich_company"] = Field("enrich_company", json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def identifier(self):
        if not (self.company_domain or self.company_linkedin_url):
            raise ValueError("Provide company_domain or company_linkedin_url")
        return self


class EnrichLeadByLinkedin(RequestModel):
    """Look up a lead profile by LinkedIn URL; costs 0.1 credit when found. No email or phone is returned."""
    operation: Literal["enrich_lead_by_linkedin"] = Field("enrich_lead_by_linkedin", json_schema_extra={"ui:hidden": True})
    linkedin_url: str = Field(..., min_length=1, description="Public LinkedIn profile URL.")


class EnrichLeadByName(RequestModel):
    """Look up a lead profile by name and company domain; costs 0.1 credit when found."""
    operation: Literal["enrich_lead_by_name"] = Field("enrich_lead_by_name", json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    company_domain: str = Field(..., min_length=1)
    company: str | None = None


BettercontactConfig = Annotated[Union[
    GetAccount, CreateEnrichment, GetEnrichment, CreateLeadFinderSearch, GetLeadFinderSearch,
    CreateCompanyFinderSearch, GetCompanyFinderSearch, EnrichCompany, EnrichLeadByLinkedin, EnrichLeadByName,
], Field(discriminator="operation")]


class BettercontactFullConfig(NodeConfig[BettercontactConfig, BettercontactAPIKeyCredential]):
    pass


ROUTES = {
    "get_account": ("GET", "/account"),
    "create_enrichment": ("POST", "/async"),
    "get_enrichment": ("GET", "/async/{request_id}"),
    "create_lead_finder_search": ("POST", "/lead_finder/async"),
    "get_lead_finder_search": ("GET", "/lead_finder/async/{request_id}"),
    "create_company_finder_search": ("POST", "/company_finder/async"),
    "get_company_finder_search": ("GET", "/company_finder/async/{request_id}"),
    "enrich_company": ("POST", "/enrich_profile/company"),
    "enrich_lead_by_linkedin": ("POST", "/enrich_profile/lead"),
    "enrich_lead_by_name": ("POST", "/enrich_profile/lead"),
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items() if k.lower() not in {"api_key", "x-api-key"}}
    return value


class BettercontactNode(WorkflowNode):
    integration_type = "automation-bettercontact"
    connection_evidence = ConnectionEvidence(noun="BetterContact account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return BettercontactFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a BetterContact API key")
        credential = self.config.credentials
        op = self.config.config
        method, path = ROUTES[op.operation]
        if "{request_id}" in path:
            path = path.replace("{request_id}", quote(op.request_id, safe=""))
        payload = op.model_dump(exclude={"operation"}, exclude_none=True) if method == "POST" else None
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"X-API-Key": credential.api_key, "Accept": "application/json"},
                **({"json": payload} if payload is not None else {}))
        try:
            body = response.json()
        except ValueError:
            body = None
        if not 200 <= response.status_code < 300 or not isinstance(body, dict) or body.get("success") is False or body.get("error"):
            message = body.get("error") or body.get("message") if isinstance(body, dict) else None
            return {"status": "error", "http_status": response.status_code,
                "error": _redact(str(message or "BetterContact returned an unexpected response"), credential.api_key)}
        result = {"status": "success", "data": _redact(body, credential.api_key)}
        if isinstance(op, (GetEnrichment, GetLeadFinderSearch, GetCompanyFinderSearch)):
            result["request_status"] = body.get("status")
            result["complete"] = body.get("status") == "terminated"
        if isinstance(op, GetAccount):
            if body.get("success") is not True or not isinstance(body.get("email"), str) or not isinstance(body.get("credits_left"), (int, float)):
                raise ValueError("BetterContact account response is missing its identity or balance")
            result["email"] = body["email"]
            result["credits_left"] = body["credits_left"]
        return result
