"""Wiza v1 operations from https://docs.wiza.co/swagger/v1/openapi.yaml."""
from __future__ import annotations
from typing import Annotated, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://wiza.co"

class WizaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Wiza API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.wiza.co/account-access/generate-api-key",
        "x-credential-instructions": "Paste your Wiza API key. NoClick sends it as a Bearer token to wiza.co. Connecting reads your remaining credits. Searches and enrichment can consume API credits. Starting a reveal or list returns a job; check its status with the corresponding get operation."})
    credential_type: Literal["wiza_api_key"] = Field("wiza_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})
    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Contact(Input):
    full_name: str | None = None
    company: str | None = None
    domain: str | None = None
    profile_url: str | None = None
    email: str | None = None
    @model_validator(mode="after")
    def contact(self):
        if sum((bool(self.profile_url), bool(self.email), bool(self.full_name and (self.company or self.domain)))) != 1:
            raise ValueError("Supply only a LinkedIn URL, only an email, or a full name with company/domain")
        return self

class FilterValue(Input):
    v: str = Field(..., min_length=1)
    s: Literal["i", "e"] | None = None

class ProspectFilters(Input):
    first_name: list[str] | None = None
    last_name: list[str] | None = None
    job_title: list[FilterValue] | None = None
    job_company: list[FilterValue] | None = None
    company_size: list[Literal["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5001-10000", "10001+"]] | None = None
    linkedin_slug: list[str] | None = None

class CompanyFilters(Input):
    company_linkedin_id: list[FilterValue] | None = None
    company_summary: list[FilterValue] | None = None
    company_industry: list[str] | None = None
    technologies: list[FilterValue] | None = None
    year_founded_start: int | None = None
    year_founded_end: int | None = None

def _json(value, model):
    try:
        return TypeAdapter(model).validate_json(value)
    except Exception:
        raise ValueError("Use documented Wiza JSON fields and values") from None

class GetCredits(Input):
    """Read remaining email, phone, export and API credits."""
    operation: Literal["get_credits"] = "get_credits"

class GetList(Input):
    """Get list processing status and details."""
    operation: Literal["get_list"] = "get_list"
    id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")

class GetListContacts(GetList):
    """Get enriched contacts for a list and segment."""
    operation: Literal["get_list_contacts"] = "get_list_contacts"
    segment: Literal["people", "valid", "risky"] = "people"

class GetIndividualReveal(GetList):
    """Get the status and results of an individual reveal."""
    operation: Literal["get_individual_reveal"] = "get_individual_reveal"

class StartIndividualReveal(Input):
    """Start a contact enrichment job; this may consume credits."""
    operation: Literal["start_individual_reveal"] = "start_individual_reveal"
    contact_json: str = Field(..., description='One input: {"profile_url":"https://www.linkedin.com/in/stephen-hakami-5babb21b0/"}, {"email":"stephen@wiza.co"}, or full_name and company/domain.', json_schema_extra={"ui:widget": "code_editor"})
    enrichment_level: Literal["none", "partial", "phone", "full"] = "partial"
    accept_work: bool = True
    accept_personal: bool = False
    fair_key: str | None = Field(None, max_length=200, description="Optional stable subgroup identifier for fair throughput distribution.")
    @field_validator("contact_json")
    @classmethod
    def contact(cls, value):
        _json(value, Contact)
        return value

class CreateList(Input):
    """Start bulk enrichment for up to 2500 contacts; this may consume credits."""
    operation: Literal["create_list"] = "create_list"
    name: str = Field(..., min_length=1, max_length=250)
    items_json: str = Field(..., description="JSON array of contacts, each using email, LinkedIn URL, or full name with company/domain.", json_schema_extra={"ui:widget": "code_editor"})
    enrichment_level: Literal["none", "partial", "full"] = "partial"
    accept_work: bool = True
    accept_personal: bool = False
    accept_generic: bool = False
    skip_duplicates: bool = True
    @field_validator("items_json")
    @classmethod
    def items(cls, value):
        if not 1 <= len(_json(value, list[Contact])) <= 2500:
            raise ValueError("Supply 1 to 2500 contacts")
        return value

class SearchProspects(Input):
    """Search prospects using name, title, company, size or LinkedIn filters."""
    operation: Literal["search_prospects"] = "search_prospects"
    filters_json: str = Field(..., description='JSON filters: first_name, last_name, job_title, job_company, company_size, linkedin_slug. Example: {"job_company":[{"v":"Wiza","s":"i"}]}', json_schema_extra={"ui:widget": "code_editor"})
    size: int = Field(10, ge=0, le=30)
    @field_validator("filters_json")
    @classmethod
    def filters(cls, value):
        if not any(_json(value, ProspectFilters).model_dump(exclude_none=True).values()):
            raise ValueError("Supply at least one prospect filter")
        return value

class CreateProspectList(Input):
    """Create an enrichment list from prospect search; this may consume credits."""
    operation: Literal["create_prospect_list"] = "create_prospect_list"
    filters_json: str = Field(..., description=SearchProspects.model_fields["filters_json"].description, json_schema_extra={"ui:widget": "code_editor"})

    @field_validator("filters_json")
    @classmethod
    def filters(cls, value):
        return SearchProspects.filters(value)

    name: str = Field(..., min_length=1, max_length=250)
    max_profiles: int = Field(10, ge=1, le=2500)
    enrichment_level: Literal["none", "partial", "full"] = "partial"
    accept_work: bool = True
    accept_personal: bool = False
    accept_generic: bool = False
    skip_duplicates: bool = True

class ContinueProspectSearch(Input):
    """Continue a previously created prospect list search."""
    operation: Literal["continue_prospect_search"] = "continue_prospect_search"
    id: int = Field(..., ge=1)
    max_profiles: int = Field(10, ge=1, le=2500)

class SearchCompanies(Input):
    """Search companies or fetch the next page; returned companies consume credits."""
    operation: Literal["search_companies"] = "search_companies"
    filters_json: str | None = Field(None, description="JSON filters: company_linkedin_id, company_summary, company_industry, technologies, year_founded_start/end. Omit when paging.", json_schema_extra={"ui:widget": "code_editor"})
    page_token: str | None = Field(None, min_length=1, description="Opaque token returned by the previous company search; omit filters when paging.")
    size: int = Field(10, ge=1, le=30)
    @field_validator("filters_json")
    @classmethod
    def filters(cls, value):
        if value is not None and not any(_json(value, CompanyFilters).model_dump(exclude_none=True).values()):
            raise ValueError("Supply at least one company filter")
        return value
    @model_validator(mode="after")
    def search_mode(self):
        if bool(self.filters_json) == bool(self.page_token):
            raise ValueError("Supply filters for a new search or page_token for the next page")
        return self

class SearchLocations(Input):
    """Find location names and boundaries accepted by Wiza filters."""
    operation: Literal["search_locations"] = "search_locations"
    query: str = Field(..., min_length=3, max_length=200)

class SearchTechnologies(SearchLocations):
    """Find technology names and slugs for company searches."""
    operation: Literal["search_technologies"] = "search_technologies"

class EnrichCompany(Input):
    """Enrich a company immediately; successful results consume credits."""
    operation: Literal["enrich_company"] = "enrich_company"
    company_name: str | None = Field(None, min_length=1)
    company_domain: str | None = Field(None, min_length=1)
    company_linkedin_id: str | None = Field(None, min_length=1)
    company_linkedin_slug: str | None = Field(None, min_length=1)
    @model_validator(mode="after")
    def identifier(self):
        if not any((self.company_name, self.company_domain, self.company_linkedin_id, self.company_linkedin_slug)):
            raise ValueError("Supply a company name, domain, LinkedIn ID or slug")
        return self

Operation = Annotated[Union[GetCredits, GetList, GetListContacts, GetIndividualReveal,
    StartIndividualReveal, CreateList, SearchProspects, CreateProspectList,
    ContinueProspectSearch, SearchCompanies, SearchLocations, SearchTechnologies,
    EnrichCompany], Field(discriminator="operation")]

class WizaConfig(NodeConfig[Operation, WizaAPIKeyCredential]):
    pass

ROUTES = {
    "get_credits": ("GET", "/api/meta/credits"),
    "get_list": ("GET", "/api/lists/{id}"),
    "get_list_contacts": ("GET", "/api/lists/{id}/contacts"),
    "get_individual_reveal": ("GET", "/api/individual_reveals/{id}"),
    "start_individual_reveal": ("POST", "/api/individual_reveals"),
    "create_list": ("POST", "/api/lists"),
    "search_prospects": ("POST", "/api/prospects/search"),
    "create_prospect_list": ("POST", "/api/prospects/create_prospect_list"),
    "continue_prospect_search": ("POST", "/api/prospects/continue_search"),
    "search_companies": ("POST", "/api/accounts/search"),
    "search_locations": ("GET", "/api/meta/location_autocomplete"),
    "search_technologies": ("GET", "/api/meta/technology_autocomplete"),
    "enrich_company": ("POST", "/api/company_enrichments"),
}

def request_parts(op):
    method, path = ROUTES[op.operation]
    if "{id}" in path:
        path = path.replace("{id}", quote(op.id, safe=""))
    query, body = {}, None
    if isinstance(op, GetListContacts):
        query["segment"] = op.segment
    elif isinstance(op, SearchLocations):
        query["query"] = op.query
    elif isinstance(op, StartIndividualReveal):
        body = {"individual_reveal": _json(op.contact_json, Contact).model_dump(exclude_none=True),
            "enrichment_level": op.enrichment_level, "email_options": {"accept_work": op.accept_work, "accept_personal": op.accept_personal}}
        if op.fair_key is not None:
            body["reveal_options"] = {"fair_key": op.fair_key}
    elif isinstance(op, CreateList):
        body = {"list": {"name": op.name, "items": [c.model_dump(exclude_none=True) for c in _json(op.items_json, list[Contact])],
            "enrichment_level": op.enrichment_level, "skip_duplicates": op.skip_duplicates,
            "email_options": {k: getattr(op, k) for k in ("accept_work", "accept_personal", "accept_generic")}}}
    elif isinstance(op, CreateProspectList):
        body = {"filters": _json(op.filters_json, ProspectFilters).model_dump(exclude_none=True),
            "list": {"name": op.name, "max_profiles": op.max_profiles, "enrichment_level": op.enrichment_level,
            "skip_duplicates": op.skip_duplicates, "email_options": {k: getattr(op, k) for k in ("accept_work", "accept_personal", "accept_generic")}}}
    elif isinstance(op, SearchProspects):
        body = {"filters": _json(op.filters_json, ProspectFilters).model_dump(exclude_none=True), "size": op.size}
    elif isinstance(op, ContinueProspectSearch):
        body = {"id": op.id, "max_profiles": op.max_profiles}
    elif isinstance(op, SearchCompanies):
        body = {"size": op.size}
        if op.page_token:
            body["page_token"] = op.page_token
        else:
            body["filters"] = _json(op.filters_json, CompanyFilters).model_dump(exclude_none=True)
    elif isinstance(op, EnrichCompany):
        body = op.model_dump(exclude_none=True, exclude={"operation"})
    return method, path, query, body

class WizaNode(WorkflowNode):
    integration_type = "automation-wiza"
    connection_evidence = ConnectionEvidence(operation="get_credits", noun="Wiza credit balance")
    @classmethod
    def get_config_model(cls):
        return WizaConfig
    async def execute(self, inputs):
        if self.config.credentials is None:
            raise ValueError("Connect a Wiza API key")
        op = self.config.config
        method, path, params, body = request_parts(op)
        token = self.config.credentials.api_key
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params or None, json=body,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        try:
            payload = response.json()
        except (ValueError, UnicodeError):
            raise ValueError("Wiza returned a non-JSON response") from None
        if not isinstance(payload, dict):
            raise ValueError("Wiza returned an unexpected response")
        status = payload.get("status")
        code = status.get("code") if isinstance(status, dict) else status
        if response.is_error or (isinstance(code, int) and code >= 400):
            message = status.get("message") if isinstance(status, dict) else payload.get("message")
            output = {"status": "error", "http_status": response.status_code, "message": str(message or "Wiza request failed").replace(token, "[redacted]")}
        elif not 200 <= response.status_code < 300:
            raise ValueError("Wiza request was redirected or not accepted")
        else:
            if isinstance(op, GetCredits):
                credits = payload.get("credits")
                if not isinstance(credits, dict) or not any(k in credits for k in ("api_credits", "email_credits", "phone_credits", "export_credits")):
                    raise ValueError("Wiza did not return an account credit balance")
            output = {"status": "success", "operation": op.operation, "data": payload}
        await self.emit(output)
        return output
