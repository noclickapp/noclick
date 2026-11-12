"""FullEnrich v2 contact enrichment, prospect search and sub-account management.

Each operation makes one documented API request; asynchronous enrichment results
are fetched explicitly so workflows can choose their own wait and retry policy.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://app.fullenrich.com/api/v2"


class FullenrichAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Fullenrich API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.fullenrich.com/app/api",
            "x-credential-instructions": "In FullEnrich, open API and copy an API key. Paste the key here without the Bearer prefix. NoClick verifies the key by reading its workspace ID.",
        })
    credential_type: Literal["fullenrich_api_key"] = Field("fullenrich_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, repr=False, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix or spaces")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class VerifyKey(Input):
    """Read the workspace associated with this API key."""
    operation: Literal["verify_api_key"] = "verify_api_key"


class GetCredits(Input):
    """Read the current spendable credit balance."""
    operation: Literal["get_credits"] = "get_credits"


# FullEnrich's own MCP server: agents get its tools through a person's FullEnrich sign-in.
FullenrichMcpCredential = mcp_credential("fullenrich", "https://mcp.fullenrich.com/mcp", app="FullEnrich")
FullenrichCredential = Union[FullenrichAPIKeyCredential, FullenrichMcpCredential]


EnrichField = Literal["contact.work_emails", "contact.personal_emails", "contact.phones"]


class Contact(Input):
    first_name: str | None = None
    last_name: str | None = None
    domain: str | None = None
    company_name: str | None = None
    linkedin_url: str | None = None
    enrich_fields: list[EnrichField] = Field(..., min_length=1)
    custom: dict[str, str] | None = Field(None, max_length=10)

    @model_validator(mode="after")
    def identifier(self):
        if not self.linkedin_url and not (self.first_name and self.last_name and (self.domain or self.company_name)):
            raise ValueError("Supply a LinkedIn URL or a first name, last name and company domain/name")
        if self.custom and any(len(v) > 100 for v in self.custom.values()):
            raise ValueError("Custom values may have at most 100 characters")
        return self


class WebhookEvents(Input):
    contact_finished: str | None = None


class BulkInput(Input):
    name: str = Field(..., min_length=1, description="Batch name shown in FullEnrich")
    webhook_url: str | None = None
    webhook_events: WebhookEvents | None = None
    silent_fail: bool = Field(False, description="Skip invalid contacts instead of failing the entire batch")


class EnrichContacts(BulkInput):
    """Start an asynchronous contact enrichment batch."""
    operation: Literal["enrich_contacts"] = "enrich_contacts"
    data: list[Contact] = Field(..., min_length=1, max_length=100)


class EnrichmentID(Input):
    enrichment_id: UUID = Field(..., description="enrichment_id returned by the batch creation operation")


class GetEnrichment(EnrichmentID):
    """Fetch the status and results of a contact enrichment batch."""
    operation: Literal["get_enrichment"] = "get_enrichment"
    force_results: bool = Field(False, description="Return partial results even before the batch finishes")


class ReverseContact(Input):
    email: str = Field(..., min_length=1)
    custom: dict[str, str] | None = Field(None, max_length=10)

    @field_validator("custom")
    @classmethod
    def custom_values(cls, value):
        if value and any(len(v) > 100 for v in value.values()):
            raise ValueError("Custom values may have at most 100 characters")
        return value


class ReverseEmails(BulkInput):
    """Start an asynchronous reverse lookup from email addresses."""
    operation: Literal["reverse_emails"] = "reverse_emails"
    data: list[ReverseContact] = Field(..., min_length=1, max_length=100)


class GetReverseLookup(EnrichmentID):
    """Fetch a reverse email lookup batch and its profiles."""
    operation: Literal["get_reverse_lookup"] = "get_reverse_lookup"


class TextFilter(Input):
    value: str = Field(..., min_length=1)
    exact_match: bool = False
    exclude: bool = False


class RangeFilter(Input):
    min: int | None = None
    max: int | None = None
    exclude: bool = False

    @model_validator(mode="after")
    def ordered(self):
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("Minimum must not exceed maximum")
        return self


class Search(Input):
    limit: int = Field(10, ge=1, le=100)
    offset: int = Field(0, ge=0, le=10000)
    search_after: str | None = Field(None, description="Copy metadata.search_after from the previous response to continue beyond 10,000 results")


class SearchPeople(Search):
    """Search prospect profiles; returns one page and metadata for continuation."""
    operation: Literal["search_people"] = "search_people"
    person_names: list[TextFilter] | None = None
    person_locations: list[TextFilter] | None = None
    current_company_names: list[TextFilter] | None = None
    current_company_domains: list[TextFilter] | None = None
    current_company_industries: list[TextFilter] | None = None
    current_company_headcounts: list[RangeFilter] | None = None
    current_position_titles: list[TextFilter] | None = None


class SearchCompanies(Search):
    """Search company profiles; returns one page and metadata for continuation."""
    operation: Literal["search_companies"] = "search_companies"
    names: list[TextFilter] | None = None
    domains: list[TextFilter] | None = None
    industries: list[TextFilter] | None = None
    technologies: list[TextFilter] | None = None
    headquarters_locations: list[TextFilter] | None = None
    headcounts: list[RangeFilter] | None = None


class LookupPerson(Input):
    """Look up a person using a professional profile or name and company."""
    operation: Literal["lookup_person"] = "lookup_person"
    person_name: str | None = None
    person_professional_network_url: str | None = None
    person_professional_network_id: int | None = None
    company_domain: str | None = None
    company_professional_network_url: str | None = None
    company_professional_network_id: int | None = None

    @model_validator(mode="after")
    def identifier(self):
        if not any([self.person_name, self.person_professional_network_url, self.person_professional_network_id]):
            raise ValueError("Supply a person name or professional network URL/ID")
        return self


class LookupCompany(Input):
    """Look up a company by domain or professional network URL/ID."""
    operation: Literal["lookup_company"] = "lookup_company"
    domain: str | None = None
    professional_network_url: str | None = None
    professional_network_id: int | None = None

    @model_validator(mode="after")
    def identifier(self):
        if not any([self.domain, self.professional_network_url, self.professional_network_id]):
            raise ValueError("Supply a company domain or professional network URL/ID")
        return self


class CreateSubAccount(Input):
    """Create a named sub-account within the workspace."""
    operation: Literal["create_sub_account"] = "create_sub_account"
    name: str = Field(..., min_length=1, max_length=255)


class ListSubAccounts(Input):
    """List active sub-accounts, optionally including archived accounts."""
    operation: Literal["list_sub_accounts"] = "list_sub_accounts"
    archived: bool = False


class SubAccountID(Input):
    sub_account_id: UUID


class GetSubAccount(SubAccountID):
    """Read one sub-account."""
    operation: Literal["get_sub_account"] = "get_sub_account"


class UpdateSubAccount(SubAccountID):
    """Rename, archive or restore a sub-account."""
    operation: Literal["update_sub_account"] = "update_sub_account"
    name: str | None = Field(None, min_length=1, max_length=255)
    archived: bool | None = None

    @model_validator(mode="after")
    def has_change(self):
        if self.name is None and self.archived is None:
            raise ValueError("Supply a name or archived flag")
        return self


FullenrichOperation = Annotated[Union[
    VerifyKey, GetCredits, EnrichContacts, GetEnrichment, ReverseEmails,
    GetReverseLookup, SearchPeople, SearchCompanies, LookupPerson, LookupCompany,
    CreateSubAccount, ListSubAccounts, GetSubAccount, UpdateSubAccount,
], Field(discriminator="operation")]


class FullenrichConfig(NodeConfig[FullenrichOperation, FullenrichCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# The public v2 contract pins one endpoint per node operation.
OPERATIONS = {
    "verify_api_key": ("GET", "/account/keys/verify"),
    "get_credits": ("GET", "/account/credits"),
    "enrich_contacts": ("POST", "/contact/enrich/bulk"),
    "get_enrichment": ("GET", "/contact/enrich/bulk/{enrichment_id}"),
    "reverse_emails": ("POST", "/contact/reverse/email/bulk"),
    "get_reverse_lookup": ("GET", "/contact/reverse/email/bulk/{enrichment_id}"),
    "search_people": ("POST", "/people/search"),
    "search_companies": ("POST", "/company/search"),
    "lookup_person": ("POST", "/people/lookup"),
    "lookup_company": ("POST", "/company/lookup"),
    "create_sub_account": ("POST", "/sub-accounts"),
    "list_sub_accounts": ("GET", "/sub-accounts"),
    "get_sub_account": ("GET", "/sub-accounts/{sub_account_id}"),
    "update_sub_account": ("POST", "/sub-accounts/{sub_account_id}"),
}


class FullenrichNode(WorkflowNode):
    integration_type = "automation-fullenrich"
    credential_provider_labels = {"fullenrich": "FullEnrich Account"}
    connection_evidence = ConnectionEvidence(
        noun="workspace", identity_operation="verify_api_key", identity_keys=("workspace_id",))

    @classmethod
    def get_config_model(cls):
        return FullenrichConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a FullEnrich API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, route = OPERATIONS[config.operation]
        body = config.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        for field in ("enrichment_id", "sub_account_id"):
            if field in body:
                route = route.replace("{" + field + "}", quote(body.pop(field), safe=""))
        params = {}
        for field, wire in (("silent_fail", "silentFail"), ("force_results", "forceResults"), ("archived", "archived")):
            if field in body and (method == "GET" or field == "silent_fail"):
                params[wire] = str(body.pop(field)).lower()
        if body.get("search_after"):
            body.pop("offset", None)
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + route,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                    params=params, **({"json": body} if method == "POST" else {}))
        except httpx.HTTPError:
            # Writes are never retried here: a timeout can follow an accepted batch.
            raise ValueError("FullEnrich request did not complete; inspect the dashboard before retrying a write") from None
        try:
            data = response.json()
        except ValueError:
            raise ValueError("FullEnrich returned a non-JSON response") from None
        if response.is_error or (isinstance(data, dict) and str(data.get("code", "")).startswith("error.")):
            message = data.get("message", "FullEnrich rejected the request") if isinstance(data, dict) else "FullEnrich rejected the request"
            return {"status": "error", "http_status": response.status_code,
                    "error": str(message).replace(key, "[redacted]")}
        if not response.is_success or not isinstance(data, (dict, list)):
            raise ValueError("FullEnrich returned an unexpected response")
        if config.operation == "verify_api_key" and (not isinstance(data, dict) or not data.get("workspace_id")):
            raise ValueError("FullEnrich did not return the key's workspace ID")
        output = {"status": "success", "data": data}
        await self.emit(output)
        return output
