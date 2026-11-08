"""CompanyEnrich v2 enrichment/search and v1 saved company lists.

Contract: official API registry versions 2.0.0 and 1.0.0. Each operation
makes exactly one request. Search results retain provider cursors; callers
explicitly request subsequent pages. Enrichment and searches may spend credits.
"""
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.companyenrich.com"


class CompanyenrichAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="CompanyEnrich API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://companyenrich.com/dashboard",
            "x-credential-instructions": "Paste your CompanyEnrich API token. NoClick sends it as a bearer token to api.companyenrich.com. The current-user endpoint verifies the account; enrichment and search operations can consume credits.",
        })
    credential_type: Literal["companyenrich_api_token"] = Field("companyenrich_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API token, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


CompanyExpansion = Literal["financial", "keywords", "naicsCodes", "technologies", "workforce"]
Domain = Annotated[str, Field(min_length=1, max_length=1024)]


class _CompanyExpansion(_Input):
    expand: list[CompanyExpansion] | None = Field(None, description="Additional company data to include")


class _CompanyQuery(_Input):
    query: str | None = Field(None, max_length=250, description="Company name or text filter")
    domain: str | None = None
    country: str | None = None
    keywords: str | None = None
    technologies: str | None = None
    semantic_query: str | None = Field(None, min_length=1, max_length=500, description="Semantic company description")
    lookalike_domains: list[Domain] | None = Field(None, min_length=1, max_length=10)


class _CompanySearch(_CompanyQuery):
    page_size: int = Field(20, ge=1, le=100)
    cursor: str | None = Field(None, max_length=1024, description="nextCursor from the previous response; retain the same filters")
    expand: list[CompanyExpansion] | None = None


class _PersonQuery(_Input):
    query: str | None = Field(None, max_length=250)
    domain: str | None = None
    country: str | None = None
    position: str | None = None


class _PersonSearch(_PersonQuery):
    page_size: int = Field(20, ge=1, le=100)
    cursor: str | None = Field(None, max_length=1024, description="nextCursor from the previous response; retain the same filters")
    expand: list[Literal["education"]] | None = None


class GetCurrentUser(_Input):
    """Read account ID, credits and capabilities."""
    operation: Literal["get_current_user"] = "get_current_user"


class GetCompany(_CompanyExpansion):
    """Retrieve a company by its CompanyEnrich UUID."""
    operation: Literal["get_company"] = "get_company"
    company_id: UUID


class EnrichCompanyDomain(_CompanyExpansion):
    """Enrich a company domain. May consume credits or schedule enrichment."""
    operation: Literal["enrich_company_domain"] = "enrich_company_domain"
    domain: Domain
    wait_for_enrichment: StrictBool = True


class EnrichCompanyProperties(_CompanyExpansion):
    """Enrich a company using its name and optional LinkedIn URL."""
    operation: Literal["enrich_company_properties"] = "enrich_company_properties"
    name: str = Field(..., min_length=1, max_length=250)
    linkedin_url: AnyHttpUrl | None = Field(None, max_length=2048)


class BatchEnrichCompanies(_CompanyExpansion):
    """Enrich one to fifty domains in one request; may consume credits."""
    operation: Literal["batch_enrich_companies"] = "batch_enrich_companies"
    domains: list[Domain] = Field(..., min_length=1, max_length=50)
    wait_for_enrichment: StrictBool = True


class GetCompanyWorkforce(_Input):
    """Retrieve workforce insights by domain, with explicit history cursor."""
    operation: Literal["get_company_workforce"] = "get_company_workforce"
    domain: Domain
    cursor: str | None = Field(None, max_length=1024)


class SearchCompanies(_CompanySearch):
    """Search one company page with text, semantic or lookalike filters."""
    operation: Literal["search_companies"] = "search_companies"


class CountCompanies(_CompanyQuery):
    """Count matching companies without retrieving full profiles."""
    operation: Literal["count_companies"] = "count_companies"


class PreviewCompanies(_CompanyQuery):
    """Preview companies matching the search criteria."""
    operation: Literal["preview_companies"] = "preview_companies"


class SearchPeople(_PersonSearch):
    """Search one page of people using domain, title, country or text."""
    operation: Literal["search_people"] = "search_people"


class CountPeople(_PersonQuery):
    """Count people matching the search criteria."""
    operation: Literal["count_people"] = "count_people"


class PreviewPeople(_PersonQuery):
    """Preview people matching the search criteria."""
    operation: Literal["preview_people"] = "preview_people"


class GetPerson(_Input):
    """Retrieve a person by their numeric CompanyEnrich ID."""
    operation: Literal["get_person"] = "get_person"
    person_id: StrictInt
    expand: list[Literal["education"]] | None = None


class EnrichPerson(_Input):
    """Enrich a person by email; may consume credits."""
    operation: Literal["enrich_person"] = "enrich_person"
    email: str = Field(..., min_length=1, max_length=320)
    expand: list[Literal["education"]] | None = None


class FindPersonEmail(_Input):
    """Find a person's work email (provider beta); may consume credits."""
    operation: Literal["find_person_email"] = "find_person_email"
    person_id: StrictInt
    domain: Domain | None = None


class ListCompanyLists(_Input):
    """Read the account's saved company lists."""
    operation: Literal["list_company_lists"] = "list_company_lists"


class GetCompanyList(_Input):
    """Read metadata for a saved company list."""
    operation: Literal["get_company_list"] = "get_company_list"
    list_id: UUID


class CreateCompanyList(_Input):
    """Create a saved company list from a v1 text/semantic search."""
    operation: Literal["create_company_list"] = "create_company_list"
    name: str = Field(..., min_length=1, max_length=1024)
    count: int = Field(..., ge=1, le=10000)
    query: str = Field(..., min_length=1, max_length=250)
    semantic_query: str | None = Field(None, max_length=500)
    countries: list[str] | None = None
    keywords: list[str] | None = None
    technologies: list[str] | None = None


class UpdateCompanyList(_Input):
    """Rename a saved company list."""
    operation: Literal["update_company_list"] = "update_company_list"
    list_id: UUID
    name: str = Field(..., min_length=1)


class DeleteCompanyList(_Input):
    """Delete a saved company list and return the provider's boolean result."""
    operation: Literal["delete_company_list"] = "delete_company_list"
    list_id: UUID


CompanyenrichConfig = Annotated[Union[
    GetCurrentUser, GetCompany, EnrichCompanyDomain, EnrichCompanyProperties,
    BatchEnrichCompanies, GetCompanyWorkforce, SearchCompanies, CountCompanies,
    PreviewCompanies, SearchPeople, CountPeople, PreviewPeople, GetPerson,
    EnrichPerson, FindPersonEmail, ListCompanyLists, GetCompanyList,
    CreateCompanyList, UpdateCompanyList, DeleteCompanyList,
], Field(discriminator="operation")]


class CompanyenrichFullConfig(NodeConfig[CompanyenrichConfig, CompanyenrichAPITokenCredential]):
    pass


# One operation maps to one published contract endpoint. No generic URL escape hatch.
ROUTES = {
    "get_current_user": ("GET", "/v2/me"),
    "get_company": ("GET", "/v2/companies/{company_id}"),
    "enrich_company_domain": ("GET", "/v2/companies/enrich"),
    "enrich_company_properties": ("POST", "/v2/companies/enrich"),
    "batch_enrich_companies": ("POST", "/v2/companies/enrich/batch"),
    "get_company_workforce": ("GET", "/v2/companies/workforce"),
    "search_companies": ("POST", "/v2/companies/search"),
    "count_companies": ("POST", "/v2/companies/search/count"),
    "preview_companies": ("POST", "/v2/companies/search/preview"),
    "search_people": ("POST", "/v2/people/search"),
    "count_people": ("POST", "/v2/people/search/count"),
    "preview_people": ("POST", "/v2/people/search/preview"),
    "get_person": ("GET", "/v2/people/{person_id}"),
    "enrich_person": ("POST", "/v2/people/enrich"),
    "find_person_email": ("GET", "/v2/people/{person_id}/email"),
    "list_company_lists": ("GET", "/lists/companies"),
    "get_company_list": ("GET", "/lists/companies/{list_id}"),
    "create_company_list": ("POST", "/lists/companies"),
    "update_company_list": ("PUT", "/lists/companies/{list_id}"),
    "delete_company_list": ("DELETE", "/lists/companies/{list_id}"),
}
WIRE_NAMES = {"page_size": "pageSize", "wait_for_enrichment": "waitForEnrichment", "linkedin_url": "linkedinUrl"}


def request_parts(config):
    method, path = ROUTES[config.operation]
    data = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
    for key in ("company_id", "person_id", "list_id"):
        if key in data:
            path = path.replace("{" + key + "}", str(data.pop(key)))
    if isinstance(config, (_CompanyQuery, _PersonQuery)):
        fields = ("query", "domain", "country", "keywords", "technologies") if isinstance(config, _CompanyQuery) else ("query", "domain", "country", "position")
        filters = {k: data.pop(k) for k in fields if k in data}
        if filters:
            data["filter"] = filters
        if "semantic_query" in data:
            data["semantic"] = {"query": data.pop("semantic_query")}
        if "lookalike_domains" in data:
            data["lookalike"] = {"domains": data.pop("lookalike_domains")}
    if isinstance(config, CreateCompanyList):
        data = {"name": data.pop("name"), "count": data.pop("count"), "search": {("semanticQuery" if k == "semantic_query" else k): v for k, v in data.items()}}
    data = {WIRE_NAMES.get(k, k): v for k, v in data.items()}
    params = []
    if method == "GET":
        for key, value in data.items():
            for item in value if isinstance(value, list) else [value]:
                params.append((key, str(item).lower() if isinstance(item, bool) else str(item)))
    return method, path, params, data if method in {"POST", "PUT"} else None


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class CompanyenrichNode(WorkflowNode):
    integration_type = "automation-companyenrich"
    connection_evidence = ConnectionEvidence(noun="CompanyEnrich account", identity_operation="get_current_user", identity_keys=("userId",))

    @classmethod
    def get_config_model(cls):
        return CompanyenrichFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a CompanyEnrich API token")
        token = self.config.credentials.api_token
        config = self.config.config
        method, path, params, body = request_parts(config)
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            try:
                error = response.json()
                message = error.get("detail") or error.get("title") or "CompanyEnrich rejected the request"
            except (ValueError, AttributeError):
                message = "CompanyEnrich returned an unsuccessful response"
            return {"status": "error", "http_status": response.status_code, "error": _redact(str(message), token)}
        data = response.json()
        if config.operation == "delete_company_list":
            if type(data) is not bool:
                raise ValueError("CompanyEnrich returned an invalid deletion result")
        elif not isinstance(data, dict):
            raise ValueError("CompanyEnrich returned an invalid JSON object")
        if config.operation == "get_current_user" and not data.get("userId"):
            raise ValueError("CompanyEnrich returned no account identity")
        return {"status": "success", "data": _redact(data, token)}
