"""The Companies API v2 company enrichment, search and saved-list automation.

Each operation issues one documented request; paginated operations return one
provider page and its unchanged metadata so workflows can request the next page.
Contract: https://api.thecompaniesapi.com/v2/openapi (2.0.0).
Authentication: https://www.thecompaniesapi.com/api/authentication.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.thecompaniesapi.com"
CREDENTIAL_TYPE = "thecompaniesapi_api_token"


class ThecompaniesapiCredential(BaseModel):
    model_config = ConfigDict(title="The Companies API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.thecompaniesapi.com/settings/api-tokens",
            "x-credential-instructions": "Create an API token in The Companies API settings, then paste the token here without the Basic prefix. Company enrichment, search and AI operations may spend provider credits. NoClick checks the token by reading your saved lists, falling back to your current user.",
        })
    credential_type: Literal["thecompaniesapi_api_token"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, description="One provider page per execution. Use meta.lastPage to decide whether to increment page.")
    size: int = Field(20, ge=1, le=100)


class _Domain(_Input):
    domain: str = Field(..., min_length=1, max_length=253, description="Company domain, for example thecompaniesapi.com.")

    @field_validator("domain")
    @classmethod
    def domain_segment(cls, value):
        # Paths are encoded as one segment; dot segments are rejected explicitly.
        if value in {".", ".."} or any(c in value for c in "/?#\\") or any(c.isspace() for c in value):
            raise ValueError("Use a company domain without a URL, path or query")
        return value


class _ListId(_Input):
    list_id: int = Field(..., ge=1, description="Saved list ID from list_lists.")


class SegmentationCondition(_Input):
    """A documented v2 segmentation condition, sent as JSON rather than URL text."""
    attribute: Literal['about.businessType', 'about.industries', 'about.industry', 'about.name', 'about.totalEmployees', 'about.yearFounded', 'ai.search', 'analytics.monthlyVisitors', 'apps', 'codes.naics', 'codes.sic', 'contacts', 'domain.domain', 'domain.tld', 'finances.revenue', 'finances.stockExchange', 'locations.headquarters.city.code', 'locations.headquarters.continent.code', 'locations.headquarters.country.code', 'locations.headquarters.county.code', 'locations.headquarters.state.code', 'meta.listIds', 'meta.score', 'meta.syncedAt', 'socials', 'socials.linkedin.id', 'technologies.active', 'technologies.categories', 'urls']
    operator: Literal["and", "or"]
    sign: Literal["equals", "exactEquals", "greater", "lower", "notEquals"]
    values: list[Union[str, float]]
    blockedOperator: bool | None = None


class ThecompaniesapiGetUserConfig(_Input):
    """Read the authenticated current user."""
    operation: Literal["get_user"] = Field("get_user", title="Get User", json_schema_extra={"ui:hidden": True})


class ThecompaniesapiSearchCompaniesConfig(_Page):
    """Search companies with a JSON segmentation query."""
    operation: Literal["search_companies"] = Field("search_companies", title="Search Companies", json_schema_extra={"ui:hidden": True})
    search: str | None = None
    query: list[SegmentationCondition] | None = None
    simplified: bool | None = None


class ThecompaniesapiCountCompaniesConfig(_Input):
    """Count companies matching a JSON segmentation query."""
    operation: Literal["count_companies"] = Field("count_companies", title="Count Companies", json_schema_extra={"ui:hidden": True})
    search: str | None = None
    query: list[SegmentationCondition] | None = None


class ThecompaniesapiGetCompanyConfig(_Domain):
    """Enrich a company by domain; full profiles can spend provider credits."""
    operation: Literal["get_company"] = Field("get_company", title="Get Company", json_schema_extra={"ui:hidden": True})
    refresh: bool | None = None
    simplified: bool | None = None


class ThecompaniesapiSearchCompaniesByNameConfig(_Page):
    """Search company names."""
    operation: Literal["search_companies_by_name"] = Field("search_companies_by_name", title="Search Companies By Name", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    size: int = Field(20, ge=1, le=25)
    countries: str | None = None
    exact_words_match: bool | None = None
    simplified: bool | None = None


class ThecompaniesapiSearchCompaniesByPromptConfig(_Page):
    """Find companies with a natural-language prompt."""
    operation: Literal["search_companies_by_prompt"] = Field("search_companies_by_prompt", title="Search Companies By Prompt", json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., min_length=1)
    size: int = Field(20, ge=1, le=50)
    similarity: float | None = Field(None, ge=0, le=2)
    simplified: bool | None = None


class ThecompaniesapiSearchSimilarCompaniesConfig(_Page):
    """Find companies similar to the supplied domains."""
    operation: Literal["search_similar_companies"] = Field("search_similar_companies", title="Search Similar Companies", json_schema_extra={"ui:hidden": True})
    domains: list[str] = Field(..., min_length=1, max_length=100)
    proximity_term: Literal["close", "far", "near"] | None = None
    simplified: bool | None = None


class ThecompaniesapiGetCompanyByEmailConfig(_Input):
    """Enrich the company associated with an email."""
    operation: Literal["get_company_by_email"] = Field("get_company_by_email", title="Get Company By Email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)
    refresh: bool | None = None
    simplified: bool | None = None


class ThecompaniesapiGetCompanyBySocialConfig(_Input):
    """Enrich a company by its LinkedIn company URL."""
    operation: Literal["get_company_by_social"] = Field("get_company_by_social", title="Get Company By Social", json_schema_extra={"ui:hidden": True})
    linkedin: str = Field(..., min_length=1, json_schema_extra={"format": "uri"})
    refresh: bool | None = None
    simplified: bool | None = None


class ThecompaniesapiGetEmailPatternsConfig(_Domain):
    """Read a company’s email patterns."""
    operation: Literal["get_email_patterns"] = Field("get_email_patterns", title="Get Email Patterns", json_schema_extra={"ui:hidden": True})
    emails_count: bool | None = None
    precision: float | None = Field(None, ge=0, le=100)


class ThecompaniesapiGetCompanyContextConfig(_Domain):
    """Read company context and sources for research."""
    operation: Literal["get_company_context"] = Field("get_company_context", title="Get Company Context", json_schema_extra={"ui:hidden": True})


class ThecompaniesapiAskCompanyConfig(_Domain):
    """Ask a company research question using provider credits."""
    operation: Literal["ask_company"] = Field("ask_company", title="Ask Company", json_schema_extra={"ui:hidden": True})
    question: str = Field(..., min_length=1)
    explain: bool | None = None
    model: Literal["small", "large"] | None = None


class ThecompaniesapiSearchIndustriesConfig(_Page):
    """Search the industry catalog."""
    operation: Literal["search_industries"] = Field("search_industries", title="Search Industries", json_schema_extra={"ui:hidden": True})
    search: str | None = None


class ThecompaniesapiSearchTechnologiesConfig(_Page):
    """Search the technology catalog."""
    operation: Literal["search_technologies"] = Field("search_technologies", title="Search Technologies", json_schema_extra={"ui:hidden": True})
    search: str | None = None


class ThecompaniesapiListListsConfig(_Page):
    """Read your saved company lists."""
    operation: Literal["list_lists"] = Field("list_lists", title="List Lists", json_schema_extra={"ui:hidden": True})
    size: int = Field(20, ge=1, le=500)


class ThecompaniesapiCreateListConfig(_Input):
    """Create a saved company list."""
    operation: Literal["create_list"] = Field("create_list", title="Create List", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    dynamic: bool | None = None
    mail_frequency: Literal["disabled", "daily", "weekly", "monthly"] | None = None
    max_companies: int | None = Field(None, ge=0)
    query: list[SegmentationCondition] | None = None
    similar_domains: list[str] | None = None


class ThecompaniesapiUpdateListConfig(_ListId):
    """Update the supplied saved list."""
    operation: Literal["update_list"] = Field("update_list", title="Update List", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=255)
    dynamic: bool | None = None
    mail_frequency: Literal["disabled", "daily", "weekly", "monthly"] | None = None
    max_companies: int | None = Field(None, ge=0, le=1000000)
    query: list[SegmentationCondition] | None = None
    resync: bool | None = None


class ThecompaniesapiDeleteListConfig(_ListId):
    """Delete the supplied saved list."""
    operation: Literal["delete_list"] = Field("delete_list", title="Delete List", json_schema_extra={"ui:hidden": True})


class ThecompaniesapiListCompaniesInListConfig(_ListId, _Page):
    """Read one page of companies in a list, optionally segmented."""
    operation: Literal["list_companies_in_list"] = Field("list_companies_in_list", title="List Companies In List", json_schema_extra={"ui:hidden": True})
    query: list[SegmentationCondition] | None = None
    simplified: bool | None = None


class ThecompaniesapiGetCompanyInListConfig(_ListId, _Domain):
    """Read a company in the supplied list."""
    operation: Literal["get_company_in_list"] = Field("get_company_in_list", title="Get Company In List", json_schema_extra={"ui:hidden": True})


class ThecompaniesapiToggleCompaniesInListConfig(_ListId):
    """Attach or detach the supplied companies from a list."""
    operation: Literal["toggle_companies_in_list"] = Field("toggle_companies_in_list", title="Toggle Companies In List", json_schema_extra={"ui:hidden": True})
    action: Literal["attach", "detach"]
    domains: list[str] = Field(..., min_length=1)
    refresh: bool | None = None


ThecompaniesapiConfig = Annotated[Union[
    ThecompaniesapiGetUserConfig,
    ThecompaniesapiSearchCompaniesConfig,
    ThecompaniesapiCountCompaniesConfig,
    ThecompaniesapiGetCompanyConfig,
    ThecompaniesapiSearchCompaniesByNameConfig,
    ThecompaniesapiSearchCompaniesByPromptConfig,
    ThecompaniesapiSearchSimilarCompaniesConfig,
    ThecompaniesapiGetCompanyByEmailConfig,
    ThecompaniesapiGetCompanyBySocialConfig,
    ThecompaniesapiGetEmailPatternsConfig,
    ThecompaniesapiGetCompanyContextConfig,
    ThecompaniesapiAskCompanyConfig,
    ThecompaniesapiSearchIndustriesConfig,
    ThecompaniesapiSearchTechnologiesConfig,
    ThecompaniesapiListListsConfig,
    ThecompaniesapiCreateListConfig,
    ThecompaniesapiUpdateListConfig,
    ThecompaniesapiDeleteListConfig,
    ThecompaniesapiListCompaniesInListConfig,
    ThecompaniesapiGetCompanyInListConfig,
    ThecompaniesapiToggleCompaniesInListConfig
], Field(discriminator="operation")]


class ThecompaniesapiFullConfig(NodeConfig[ThecompaniesapiConfig, ThecompaniesapiCredential]):
    model_config = ConfigDict(title="The Companies API Node Configuration", hide_input_in_errors=True)


ROUTES = {'get_user': ('GET', '/v2/user', 'query'),
 'search_companies': ('POST', '/v2/companies', 'body'),
 'count_companies': ('POST', '/v2/companies/count', 'body'),
 'get_company': ('GET', '/v2/companies/{domain}', 'query'),
 'search_companies_by_name': ('GET', '/v2/companies/by-name', 'query'),
 'search_companies_by_prompt': ('GET', '/v2/companies/by-prompt', 'query'),
 'search_similar_companies': ('GET', '/v2/companies/similar', 'query'),
 'get_company_by_email': ('GET', '/v2/companies/by-email', 'query'),
 'get_company_by_social': ('GET', '/v2/companies/by-social', 'query'),
 'get_email_patterns': ('GET', '/v2/companies/{domain}/email-patterns', 'query'),
 'get_company_context': ('GET', '/v2/companies/{domain}/context', 'query'),
 'ask_company': ('POST', '/v2/companies/{domain}/ask', 'body'),
 'search_industries': ('GET', '/v2/industries', 'query'),
 'search_technologies': ('GET', '/v2/technologies', 'query'),
 'list_lists': ('GET', '/v2/lists', 'query'),
 'create_list': ('POST', '/v2/lists', 'body'),
 'update_list': ('PATCH', '/v2/lists/{listId}', 'body'),
 'delete_list': ('DELETE', '/v2/lists/{listId}', 'query'),
 'list_companies_in_list': ('POST', '/v2/lists/{listId}/companies', 'body'),
 'get_company_in_list': ('GET', '/v2/lists/{listId}/companies/{domain}', 'query'),
 'toggle_companies_in_list': ('PATCH', '/v2/lists/{listId}/companies/toggle', 'body')}

WIRE_NAMES = {'exact_words_match': 'exactWordsMatch',
 'proximity_term': 'proximityTerm',
 'emails_count': 'emailsCount',
 'mail_frequency': 'mailFrequency',
 'max_companies': 'maxCompanies',
 'similar_domains': 'similarDomains'}


class ThecompaniesapiNode(WorkflowNode):
    integration_type = "automation-thecompaniesapi"
    connection_evidence = ConnectionEvidence(
        noun="company lists", operation="list_lists", identity_operation="get_user",
        label_keys=("name", "fullName", "email", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return ThecompaniesapiFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, ThecompaniesapiFullConfig) or not self.config.credentials:
            raise ValueError("Connect a The Companies API token")
        config = self.config.config
        method, path, location = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if "list_id" in values:
            path = path.replace("{listId}", str(values.pop("list_id")))
        if "domain" in values:
            path = path.replace("{domain}", quote(values.pop("domain"), safe=""))
        values = {WIRE_NAMES.get(key, key): value for key, value in values.items()}
        # OpenAPI query arrays use form/explode: one key per value. JSON search
        # bodies preserve structured segmentation without ambiguous URL encoding.
        kwargs = {"json": values} if location == "body" else {"params": values}
        token = self.config.credentials.api_token
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Basic " + token, "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection text, but never an echoed secret.
            message = response.text.replace(token, "[redacted]")[:2000]
            raise httpx.HTTPStatusError(message or f"The Companies API HTTP {response.status_code}",
                request=response.request, response=response)
        if "json" not in response.headers.get("content-type", "").lower():
            raise ValueError("The Companies API did not return JSON")
        body = response.json()
        if not isinstance(body, (dict, list)):
            raise ValueError("The Companies API returned an unexpected response shape")
        if isinstance(body, dict) and ("error" in body or "errors" in body or
                (isinstance(body.get("status"), (int, float)) and body["status"] >= 400)):
            raise ValueError("The Companies API returned an error response")
        return body
