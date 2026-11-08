"""Datagma enrichment API, pinned to the provider's published v3.11 contract.

All ten published operations are GETs. Enrichment may consume Datagma credits.
https://datagmaapi.readme.io/openapi/62023bddd851480038992924
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


API_BASE = "https://gateway.datagma.net"
ROUTES = {
    "get_credit": "/api/ingress/v1/mine",
    "find_work_email": "/api/ingress/v8/findEmail",
    "enrich": "/api/ingress/v2/full",
    "detect_job_change": "/api/ingress/v4/update",
    "find_people": "/api/ingress/v1/find_people",
    "search_phone_numbers": "/api/ingress/v1/search",
    "reverse_phone_lookup": "/api/ingress/v1/reverse_phone_lookup",
    "reverse_email_lookup": "/api/ingress/v1/reverse_email",
    "get_twitter_by_username": "/api/ingress/v1/twitter/by_username",
    "get_twitter_by_email": "/api/ingress/v1/twitter/by_email",
}


class DatagmaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Datagma API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.datagma.com/user-api",
            "x-credential-instructions": "Open Datagma → API, copy your API key, and paste it here. Enrichment requests can consume Datagma credits.",
        },
    )
    credential_type: Literal["datagma_api_key"] = Field("datagma_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        return clean_secret(value, field_name="API key")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetCredit(_Input):
    """Get the connected account's credit balance."""
    operation: Literal["get_credit"] = Field("get_credit", json_schema_extra={"ui:hidden": True})
    email: str | None = Field(None, description="Optional account email.")


class FindWorkEmail(_Input):
    """Find a verified work email from a name and company name, domain or company LinkedIn URL."""
    operation: Literal["find_work_email"] = Field("find_work_email", json_schema_extra={"ui:hidden": True})
    firstName: str | None = Field(None, title="First name")
    lastName: str | None = Field(None, title="Last name")
    fullName: str | None = Field(None, title="Full name", description="Instead of first and last name.")
    company: str | None = Field(None, description="Company name or domain.")
    linkedInSlug: str | None = Field(None, title="Company LinkedIn URL", description="Company URL, e.g. https://www.linkedin.com/company/livestorm/. Datagma extracts the company domain.")


class Enrich(_Input):
    """Enrich a person or company; optional enrichments can cost additional credits."""
    operation: Literal["enrich"] = Field("enrich", json_schema_extra={"ui:hidden": True})
    data: str | None = Field(None, description="Email, LinkedIn URL, name with company, company name, website or French SIREN.")
    companyKeyword: str | None = Field(None, title="Company keyword")
    countryCode: str | None = Field(None, title="Country code")
    firstName: str | None = Field(None, title="First name")
    lastName: str | None = Field(None, title="Last name")
    fullName: str | None = Field(None, title="Full name")
    companyPremium: bool | None = Field(None, title="Company LinkedIn information")
    companyFull: bool | None = Field(None, title="Company financial information")
    companyFrench: bool | None = Field(None, title="French company information")
    personFull: bool | None = Field(None, title="Full person profile")
    phoneFull: bool | None = Field(None, title="Find cell phone", description="Use phone search instead when an email or social profile is available.")
    deepTraffic: bool | None = Field(None, title="Website traffic information")
    debug: bool | None = Field(None, description="Include results normally filtered by Datagma.")


class DetectJobChange(_Input):
    """Check whether a person still works at their last known company."""
    operation: Literal["detect_job_change"] = Field("detect_job_change", json_schema_extra={"ui:hidden": True})
    firstName: str | None = Field(None, title="First name")
    lastName: str | None = Field(None, title="Last name")
    fullName: str | None = Field(None, title="Full name")
    companyName: str | None = Field(None, title="Last known company")
    jobTitle: str | None = Field(None, title="Last known job title")


class FindPeople(_Input):
    """Find up to ten people by job title and company; successful searches cost ten credits."""
    operation: Literal["find_people"] = Field("find_people", json_schema_extra={"ui:hidden": True})
    currentJobTitle: str | None = Field(None, title="Job titles", description="Join alternatives with OR, e.g. head of OR chief OR CEO.")
    linkedinId: str | None = Field(None, title="Company LinkedIn ID")
    domain: str | None = Field(None, description="Company domain, e.g. algolia.com.")
    currentCompanies: str | None = Field(None, title="Company name")
    countries: str | None = Field(None, description="Lowercase country names, e.g. france.")
    fuzzy: bool | None = Field(None, description="Allow approximate matches.")
    debug: bool | None = Field(None, description="Disable non-relevant job-title filtering.")


class SearchPhoneNumbers(_Input):
    """Find mobile phone numbers using an email and/or social profile."""
    operation: Literal["search_phone_numbers"] = Field("search_phone_numbers", json_schema_extra={"ui:hidden": True})
    email: str | None = None
    username: str | None = Field(None, description="Social profile URL; Sales Navigator URLs are unsupported.")
    minimumMatch: float | None = Field(None, title="Minimum match", description="Datagma recommends 1 for accuracy.")
    whatsapp_check: bool | None = Field(None, title="Check WhatsApp", description="Check if the mobile number has a WhatsApp account.")


class ReversePhoneLookup(_Input):
    """Look up a person from a phone number."""
    operation: Literal["reverse_phone_lookup"] = Field("reverse_phone_lookup", json_schema_extra={"ui:hidden": True})
    number: str = Field(..., min_length=1, title="Phone number")
    code: str | None = Field(None, description="Country code including plus, e.g. +33.")


class ReverseEmailLookup(_Input):
    """Look up a personal email outside the EU; use enrich for work emails."""
    operation: Literal["reverse_email_lookup"] = Field("reverse_email_lookup", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)


class GetTwitterByUsername(_Input):
    """Get a Twitter profile from a case-sensitive username or LinkedIn URL."""
    operation: Literal["get_twitter_by_username"] = Field("get_twitter_by_username", json_schema_extra={"ui:hidden": True})
    username: str | None = Field(None, description="Case-sensitive Twitter username.")
    linkedin: str | None = Field(None, title="LinkedIn profile", description="Without https, e.g. linkedin.com/in/raphaelazot.")


class GetTwitterByEmail(_Input):
    """Get a Twitter profile from an email address."""
    operation: Literal["get_twitter_by_email"] = Field("get_twitter_by_email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)


DatagmaOperation = Annotated[Union[
    GetCredit, FindWorkEmail, Enrich, DetectJobChange, FindPeople, SearchPhoneNumbers,
    ReversePhoneLookup, ReverseEmailLookup, GetTwitterByUsername, GetTwitterByEmail,
], Field(discriminator="operation")]


class DatagmaConfig(NodeConfig[DatagmaOperation, DatagmaAPIKeyCredential]):
    pass


def _redact(value: Any, key: str) -> Any:
    # Credit responses can echo apiId; neither it nor a URL quoting it may escape.
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items() if k.lower() not in {"apiid", "api_key"}}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    if isinstance(value, str):
        from urllib.parse import quote, quote_plus
        for secret in {key, quote(key, safe=""), quote_plus(key)}:
            value = value.replace(secret, "[redacted]")
    return value


class DatagmaNode(WorkflowNode):
    integration_type = "automation-datagma"
    connection_evidence = ConnectionEvidence(
        noun="account", identity_operation="get_credit", identity_keys=("email", "id"),
    )
    edit_examples = ["Find work emails for these leads", "Enrich a company domain", "Check whether a contact changed jobs"]

    @classmethod
    def get_config_model(cls):
        return DatagmaConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Datagma API key")
        key = self.config.credentials.api_key
        op = self.config.config
        params = op.model_dump(exclude={"operation"}, exclude_none=True)
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        params["apiId"] = key
        try:
            async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=60) as client:
                response = await client.get(API_BASE + ROUTES[op.operation], params=params, headers={"Accept": "application/json"})
        except httpx.RequestError:
            raise ValueError("Datagma request could not be completed") from None
        try:
            body = response.json()
        except ValueError:
            raise ValueError(f"Datagma returned a non-JSON response (HTTP {response.status_code})") from None
        body = _redact(body, key)
        if response.status_code != 200:
            raise ValueError(f"Datagma (HTTP {response.status_code}): {body}")
        if not isinstance(body, dict):
            raise ValueError("Datagma returned an invalid response object")
        code = body.get("httpStatusCode")
        status = str(body.get("status", "")).lower()
        if (body.get("error") or body.get("errors") or body.get("success") is False
                or status in {"error", "failed", "failure", "unauthorized", "forbidden"}
                or isinstance(code, (int, float)) and code >= 400
                or body.get("code") and body.get("message")):
            raise ValueError(f"Datagma: {body}")
        if op.operation == "get_credit" and not any(k in body for k in ("id", "email", "currentCredit", "plan")):
            raise ValueError("Datagma did not return account credit information")
        output = {"status": "success", "data": body}
        await self.emit(output)
        return output
