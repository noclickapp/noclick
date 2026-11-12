"""Icypeas API 1.16.0: explicit searches, result reads and account credits.

Search creation may spend credits. Async acknowledgements are returned unchanged;
read_results is a separate action, with no polling or implicit retries.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class IcypeasAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Icypeas API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.icypeas.com/api",
            "x-credential-instructions": "Paste your Icypeas API key and account email. The key is sent as Authorization without a Bearer prefix. NoClick reads your subscription and remaining credits to check the connection. Searches and scraping can consume credits."})
    credential_type: Literal["icypeas_api_key"] = Field("icypeas_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})
    email: str = Field(..., title="Account email", min_length=3, max_length=320)

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value

    @field_validator("email")
    @classmethod
    def account_email(cls, value):
        value = value.strip()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter your Icypeas account email")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class SearchCustom(_Input):
    externalId: str | None = None
    webhookUrl: str | None = Field(None, description="Optional HTTPS endpoint Icypeas calls when the search finishes.", pattern=r"^https://[^/\s]+(?:/.*)?$")


class BulkCustom(_Input):
    webhookUrlItem: str | None = Field(None, pattern=r"^https://[^/\s]+(?:/.*)?$")
    webhookUrlBulkDone: str | None = Field(None, pattern=r"^https://[^/\s]+(?:/.*)?$")
    externalIds: list[str] | None = None
    includeResultsInWebhook: bool | None = None


class GetSubscription(_Input):
    """Read the connected account subscription and remaining credits (free)."""
    operation: Literal["get_subscription"] = "get_subscription"


class CreationDateSort(_Input):
    creationDate: float


class ReadBulkProgress(_Input):
    """Read a page of bulk search progress; pass the returned sorts explicitly."""
    operation: Literal["read_bulk_progress"] = "read_bulk_progress"
    limit: int = Field(10, ge=1, le=50)
    file: str | None = None
    status: Literal["in_progress", "done"] | None = None
    next: bool | None = None
    sorts: list[Union[CreationDateSort, tuple[float]]] | None = Field(None, description="Pass provider-returned sorts unchanged. The docs example uses one-element timestamp arrays; the OpenAPI schema describes creationDate objects.")


class CreateBulkSearch(_Input):
    """Submit up to 5,000 rows. This starts a search and can spend credits."""
    operation: Literal["create_bulk_search"] = "create_bulk_search"
    name: str = Field(..., min_length=1)
    task: Literal["domain-search", "email-search", "email-verification"]
    data: list[list[str]] = Field(..., min_length=1, max_length=5000)
    custom: BulkCustom | None = None

    @model_validator(mode="after")
    def rows(self):
        size = 3 if self.task == "email-search" else 1
        if any(len(row) != size for row in self.data):
            raise ValueError("Email search rows need first name, last name and company; other tasks need one value per row")
        if self.custom and self.custom.externalIds is not None and len(self.custom.externalIds) != len(self.data):
            raise ValueError("Supply one external ID per row")
        return self


class CreateDomainSearch(_Input):
    """Start an asynchronous domain search; read_results retrieves its result."""
    operation: Literal["create_domain_search"] = "create_domain_search"
    domainOrCompany: str = Field(..., min_length=1)
    custom: SearchCustom | None = None


class CreateEmailSearch(_Input):
    """Start a professional email search; at least one name must be supplied."""
    operation: Literal["create_email_search"] = "create_email_search"
    firstname: str = ""
    lastname: str = ""
    domainOrCompany: str = Field(..., min_length=1)
    custom: SearchCustom | None = None

    @model_validator(mode="after")
    def names(self):
        if not self.firstname.strip() and not self.lastname.strip():
            raise ValueError("Supply a first or last name")
        return self


class CreateEmailVerification(_Input):
    """Start an email verification search; this can spend credits."""
    operation: Literal["create_email_verification"] = "create_email_verification"
    email: str = Field(..., min_length=3)
    custom: SearchCustom | None = None


class CompanyInput(_Input):
    companyOrDomain: str = Field(..., min_length=1)


class ProfileInput(_Input):
    firstname: str = Field(..., min_length=1)
    lastname: str = Field(..., min_length=1)
    companyOrDomain: str | None = None
    jobTitle: str | None = None

    @model_validator(mode="after")
    def context(self):
        if not self.companyOrDomain and not self.jobTitle:
            raise ValueError("Supply a company/domain or job title")
        return self


class FindCompanyURL(CompanyInput):
    """Find a company's profile URL."""
    operation: Literal["find_company_url"] = "find_company_url"


class FindProfileURL(ProfileInput):
    """Find a person's profile URL."""
    operation: Literal["find_profile_url"] = "find_profile_url"


class FindURLs(_Input):
    """Find up to 50 company or profile URLs in one request."""
    operation: Literal["find_urls"] = "find_urls"
    type: Literal["company", "profile"]
    data: list[Union[CompanyInput, ProfileInput]] = Field(..., min_length=1, max_length=50)

    @model_validator(mode="after")
    def row_types(self):
        expected = CompanyInput if self.type == "company" else ProfileInput
        if any(not isinstance(row, expected) for row in self.data):
            raise ValueError("Rows must match the selected URL search type")
        return self


class ReadResults(_Input):
    """Read the first page or an exact single/bulk search. No implicit polling."""
    operation: Literal["read_results"] = "read_results"
    mode: Literal["single", "bulk"] | None = None
    id: str | None = None
    file: str | None = None
    limit: int = Field(10, ge=1, le=100)


class ReverseEmailLookup(_Input):
    """Look up the person behind one professional email address."""
    operation: Literal["reverse_email_lookup"] = "reverse_email_lookup"
    email: str = Field(..., min_length=3)


class ReverseEmailLookups(_Input):
    """Look up people behind 2 to 50 professional email addresses."""
    operation: Literal["reverse_email_lookups"] = "reverse_email_lookups"
    data: list[str] = Field(..., min_length=2, max_length=50)


class ScrapeCompany(_Input):
    """Scrape one company page; returns an acknowledgement or result."""
    operation: Literal["scrape_company"] = "scrape_company"
    url: str = Field(..., pattern=r"^https://(?:www\.)?linkedin\.com/company/[^\s]+$")


class ScrapeProfile(_Input):
    """Scrape one profile; returns an acknowledgement or result."""
    operation: Literal["scrape_profile"] = "scrape_profile"
    url: str = Field(..., pattern=r"^https://(?:www\.)?linkedin\.com/in/[^\s]+$")


class ScrapePages(_Input):
    """Submit up to 50 company or profile pages for scraping."""
    operation: Literal["scrape_pages"] = "scrape_pages"
    type: Literal["company", "profile"]
    data: list[str] = Field(..., min_length=1, max_length=50)

    @model_validator(mode="after")
    def urls(self):
        model = ScrapeCompany if self.type == "company" else ScrapeProfile
        for url in self.data:
            model(url=url)
        return self


# Icypeas's own MCP server: agents get its tools through a person's Icypeas sign-in.
IcypeasMcpCredential = mcp_credential("icypeas", "https://mcp.icypeas.com/mcp", app="Icypeas")
IcypeasCredential = Union[IcypeasAPIKeyCredential, IcypeasMcpCredential]


IcypeasConfig = Annotated[Union[GetSubscription, ReadBulkProgress, CreateBulkSearch,
    CreateDomainSearch, CreateEmailSearch, CreateEmailVerification, FindCompanyURL,
    FindProfileURL, FindURLs, ReadResults, ReverseEmailLookup, ReverseEmailLookups,
    ScrapeCompany, ScrapeProfile, ScrapePages], Field(discriminator="operation")]


class IcypeasFullConfig(NodeConfig[IcypeasConfig, IcypeasCredential]):
    pass


ROUTES = {
    "get_subscription": ("POST", "/a/actions/subscription-information"),
    "read_bulk_progress": ("POST", "/search-files/read"),
    "create_bulk_search": ("POST", "/bulk-search"),
    "create_domain_search": ("POST", "/domain-search"),
    "create_email_search": ("POST", "/email-search"),
    "create_email_verification": ("POST", "/email-verification"),
    "find_company_url": ("POST", "/url-search/company"),
    "find_profile_url": ("POST", "/url-search/profile"),
    "find_urls": ("POST", "/url-search"),
    "read_results": ("POST", "/bulk-single-searchs/read"),
    "reverse_email_lookup": ("POST", "/reverse-email-lookup"),
    "reverse_email_lookups": ("POST", "/reverse-email-lookups"),
    "scrape_company": ("GET", "/scrape/company"),
    "scrape_profile": ("GET", "/scrape/profile"),
    "scrape_pages": ("POST", "/scrape"),
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    return value


class IcypeasNode(WorkflowNode):
    integration_type = "automation-icypeas"
    credential_provider_labels = {"icypeas": "Icypeas Account"}
    connection_evidence = ConnectionEvidence(noun="Icypeas subscription", identity_operation="get_subscription", identity_keys=("userId",))

    @classmethod
    def get_config_model(cls):
        return IcypeasFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Icypeas API key and account email")
        op, credential = self.config.config, self.config.credentials
        method, path = ROUTES[op.operation]
        body = op.model_dump(exclude={"operation"}, exclude_none=True)
        if op.operation == "get_subscription":
            body = {"email": credential.email}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://app.icypeas.com/api" + path,
                    headers={"Authorization": credential.api_key, "Accept": "application/json", "Content-Type": "application/json"},
                    **({"params": body} if method == "GET" else {"json": body}))
            if not 200 <= response.status_code < 300:
                return {"status": "error", "http_status": response.status_code,
                    "message": _redact(self._error_message(response), credential.api_key)}
            data = response.json()
            if not isinstance(data, dict) or data.get("success") is False or data.get("validationErrors") or (op.operation != "get_subscription" and data.get("success") is not True):
                return {"status": "error", "message": "Icypeas rejected the request", "data": _redact(data, credential.api_key)}
            if op.operation == "get_subscription" and (not isinstance(data.get("userId"), str) or not data["userId"] or type(data.get("credits")) not in (int, float)):
                return {"status": "error", "message": "Icypeas subscription response was incomplete"}
            result = {"status": "success", "data": _redact(data, credential.api_key)}
            if op.operation == "get_subscription":
                result["userId"] = _redact(data["userId"], credential.api_key)
            await self.emit(result)
            return result
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "message": "Icypeas request could not be confirmed; inspect search history before retrying a credit-consuming action"}

    @staticmethod
    def _error_message(response):
        try:
            data = response.json()
            if isinstance(data, dict) and isinstance(data.get("message"), str):
                return data["message"]
        except ValueError:
            pass
        return "Icypeas request failed (HTTP " + str(response.status_code) + ")"
