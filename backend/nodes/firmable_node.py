"""Firmable enrichment API v1.0.0, https://docs.firmable.com/api-reference/openapi.json.

All operations retrieve data, including the POST search. One call returns one page;
callers explicitly carry search offsets or technology cursors into the next run.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.firmable.com"
COUNTRY = Literal["AU", "NZ", "SG", "MY", "ID", "PH", "HK", "JP", "VN", "KR", "TH", "US", "CA"]
FILTER = Literal["industry", "location", "hq_location", "company_size", "global_company_size", "revenue", "company_type", "year_founded", "is_mnc", "b2b_vs_b2c", "target_market", "multiple_locations", "job_posts", "keywords", "services", "products", "position", "seniority", "department", "skills", "current_role_duration", "people_location"]


class FirmableAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Firmable API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.firmable.com/dashboard/profile?selected=integrations&connection=api",
        "x-credential-instructions": "Create an API key in Firmable under Profile → Integrations → API, then paste it here without the Bearer prefix. Enrichment and search can use Firmable credits; Tech Intelligence requires an eligible plan. The free filter-options connection check proves the key is accepted, not account identity or access to paid endpoints.",
    })
    credential_type: Literal["firmable_api_key"] = Field("firmable_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the Firmable API key, without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, str_strip_whitespace=True)


class _Company(_Input):
    country: COUNTRY | None = Field(None, description="Market-specific company data; Firmable defaults to AU when omitted.")


class CompanyByID(_Company):
    """Look up one company using id."""
    operation: Literal["enrich_company_by_id"] = Field("enrich_company_by_id", json_schema_extra={"ui:hidden": True})
    company_id: str = Field(..., min_length=1, max_length=2048, description="Firmable id; for example f000000117274.")


class CompanyByDomain(_Company):
    """Look up one company using fqdn."""
    operation: Literal["enrich_company_by_domain"] = Field("enrich_company_by_domain", json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., min_length=1, max_length=2048, description="Firmable fqdn; for example smec.com.")


class CompanyByLinkedInSlug(_Company):
    """Look up one company using ln_slug."""
    operation: Literal["enrich_company_by_linkedin_slug"] = Field("enrich_company_by_linkedin_slug", json_schema_extra={"ui:hidden": True})
    linkedin_slug: str = Field(..., min_length=1, max_length=2048, description="Firmable ln_slug; for example smec.")


class CompanyByLinkedInURL(_Company):
    """Look up one company using ln_url."""
    operation: Literal["enrich_company_by_linkedin_url"] = Field("enrich_company_by_linkedin_url", json_schema_extra={"ui:hidden": True})
    linkedin_url: str = Field(..., min_length=1, max_length=2048, description="Firmable ln_url; for example https://www.linkedin.com/company/smec/.")


class CompanyByABN(_Company):
    """Look up one company using abn."""
    operation: Literal["enrich_company_by_abn"] = Field("enrich_company_by_abn", json_schema_extra={"ui:hidden": True})
    abn: str = Field(..., min_length=1, max_length=2048, description="Firmable abn; for example 47065475149.")


class CompanyByWebsite(_Company):
    """Look up one company using website."""
    operation: Literal["enrich_company_by_website"] = Field("enrich_company_by_website", json_schema_extra={"ui:hidden": True})
    website: str = Field(..., min_length=1, max_length=2048, description="Firmable website; for example https://www.smec.com.")


class PersonByID(_Input):
    """Look up one person using id."""
    operation: Literal["enrich_person_by_id"] = Field("enrich_person_by_id", json_schema_extra={"ui:hidden": True})
    person_id: str = Field(..., min_length=1, max_length=2048, description="Firmable id; for example fp000000067890.")


class PersonByLinkedInSlug(_Input):
    """Look up one person using ln_slug."""
    operation: Literal["enrich_person_by_linkedin_slug"] = Field("enrich_person_by_linkedin_slug", json_schema_extra={"ui:hidden": True})
    linkedin_slug: str = Field(..., min_length=1, max_length=2048, description="Firmable ln_slug; for example chathchw.")


class PersonByLinkedInURL(_Input):
    """Look up one person using ln_url."""
    operation: Literal["enrich_person_by_linkedin_url"] = Field("enrich_person_by_linkedin_url", json_schema_extra={"ui:hidden": True})
    linkedin_url: str = Field(..., min_length=1, max_length=2048, description="Firmable ln_url; for example https://www.linkedin.com/in/chathchw/.")


class PersonByWorkEmail(_Input):
    """Look up one person using work_email."""
    operation: Literal["enrich_person_by_work_email"] = Field("enrich_person_by_work_email", json_schema_extra={"ui:hidden": True})
    work_email: str = Field(..., min_length=1, max_length=2048, description="Firmable work_email; for example ******@firmable.com.")


class PersonByPersonalEmail(_Input):
    """Look up one person using personal_email."""
    operation: Literal["enrich_person_by_personal_email"] = Field("enrich_person_by_personal_email", json_schema_extra={"ui:hidden": True})
    personal_email: str = Field(..., min_length=1, max_length=2048, description="Firmable personal_email; for example ******@gmail.com.")


class SearchPeople(_Input):
    """Search a company's people; the POST retrieves data without creating records."""
    operation: Literal["search_people"] = Field("search_people", json_schema_extra={"ui:hidden": True})
    company_id: str = Field(..., min_length=1, max_length=200, description="Firmable company ID, for example f000000117274.")
    country: COUNTRY | None = Field(None, description="Search market; Firmable defaults to AU.")
    position: str | None = Field(None, min_length=1, max_length=500)
    seniority: str | None = Field(None, min_length=1, max_length=200)
    department: str | None = Field(None, min_length=1, max_length=200)
    offset: int = Field(0, ge=0, description="Search offset. Sent as the documented string field 'from'.")
    size: int = Field(10, ge=1, description="Page size. Sent as a string; no automatic pagination.")


class ListFilterOptions(_Input):
    """Read accepted filter codes and markets. This endpoint is not charged."""
    operation: Literal["list_filter_options"] = Field("list_filter_options", json_schema_extra={"ui:hidden": True})
    identifiers: list[FILTER] | None = Field(None, min_length=1, description="Omit for every filter; sent comma-separated.")
    search: str | None = Field(None, min_length=1, max_length=100)
    offset: int | None = Field(None, ge=0, description="Page offset; pages contain 20 values.")
    level_one: str | None = Field(None, pattern=r"^l1:[A-Za-z]+$", description="Top-level industry code, for example l1:J.")

    @model_validator(mode="after")
    def paging(self):
        pageable = self.identifiers and len(self.identifiers) == 1 and self.identifiers[0] in {"industry", "location", "hq_location", "people_location"}
        if (self.search is not None or self.offset is not None) and not pageable:
            raise ValueError("Search and offset require exactly one pageable filter: industry, location, hq_location or people_location")
        if self.level_one is not None and self.identifiers != ["industry"]:
            raise ValueError("Top-level industry code requires identifiers = industry")
        return self


class GetTechIntelligence(_Input):
    """Read technologies for a company; requires Tech Intelligence on the plan."""
    operation: Literal["get_tech_intelligence"] = Field("get_tech_intelligence", json_schema_extra={"ui:hidden": True})
    company_id: str = Field(..., min_length=1, max_length=200, description="Firmable company ID, for example f000000740279.")
    cursor: str | None = Field(None, min_length=1, max_length=10000, description="Opaque next_cursor returned by the previous page; omit for the first page.")

FirmableConfig = Annotated[Union[CompanyByID, CompanyByDomain, CompanyByLinkedInSlug, CompanyByLinkedInURL, CompanyByABN, CompanyByWebsite, PersonByID, PersonByLinkedInSlug, PersonByLinkedInURL, PersonByWorkEmail, PersonByPersonalEmail, SearchPeople, ListFilterOptions, GetTechIntelligence], Field(discriminator="operation")]


class FirmableFullConfig(NodeConfig[FirmableConfig, FirmableAPIKeyCredential]):
    pass


# Every action maps to exactly one endpoint in the pinned provider contract.
LOOKUPS = {
    "enrich_company_by_id": ("/company", "id", "company_id"),
    "enrich_company_by_domain": ("/company", "fqdn", "domain"),
    "enrich_company_by_linkedin_slug": ("/company", "ln_slug", "linkedin_slug"),
    "enrich_company_by_linkedin_url": ("/company", "ln_url", "linkedin_url"),
    "enrich_company_by_abn": ("/company", "abn", "abn"),
    "enrich_company_by_website": ("/company", "website", "website"),
    "enrich_person_by_id": ("/people", "id", "person_id"),
    "enrich_person_by_linkedin_slug": ("/people", "ln_slug", "linkedin_slug"),
    "enrich_person_by_linkedin_url": ("/people", "ln_url", "linkedin_url"),
    "enrich_person_by_work_email": ("/people", "work_email", "work_email"),
    "enrich_person_by_personal_email": ("/people", "personal_email", "personal_email"),
}


class FirmableNode(WorkflowNode):
    integration_type = "automation-firmable"
    connection_evidence = ConnectionEvidence(noun="Firmable filter options", operation="list_filter_options", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return FirmableFullConfig

    async def execute(self, inputs):
        full = self.config
        if not isinstance(full, FirmableFullConfig) or full.credentials is None:
            raise ValueError("Connect a Firmable API key")
        cfg = full.config
        params, body, method = {}, None, "GET"
        if cfg.operation in LOOKUPS:
            path, parameter, field = LOOKUPS[cfg.operation]
            params[parameter] = getattr(cfg, field)
            if isinstance(cfg, _Company) and cfg.country is not None:
                params["country"] = cfg.country
        elif isinstance(cfg, SearchPeople):
            path, method = "/people/search", "POST"
            body = {"companyId": cfg.company_id, "from": str(cfg.offset), "size": str(cfg.size)}
            for field, key in (("country", "selectedCountry"), ("position", "position"), ("seniority", "seniority"), ("department", "department")):
                if getattr(cfg, field) is not None:
                    body[key] = getattr(cfg, field)
        elif isinstance(cfg, ListFilterOptions):
            path = "/filter-options"
            if cfg.identifiers is not None:
                params["identifiers"] = ",".join(cfg.identifiers)
            for field, key in (("search", "search"), ("offset", "offset"), ("level_one", "levelOne")):
                if getattr(cfg, field) is not None:
                    params[key] = getattr(cfg, field)
        elif isinstance(cfg, GetTechIntelligence):
            path, params = "/tech-intel", {"id": cfg.company_id}
            if cfg.cursor is not None:
                params["cursor"] = cfg.cursor
        else:
            raise ValueError("Unsupported Firmable operation")
        key = full.credentials.api_key
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params, json=body,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
        except httpx.HTTPError:
            raise ValueError("Firmable request could not be completed; try again") from None
        try:
            data = response.json()
        except ValueError:
            raise ValueError(f"Firmable returned HTTP {response.status_code} with an unexpected response") from None
        if not 200 <= response.status_code < 300 or isinstance(data, dict) and (data.get("error")):
            detail = data.get("message") or data.get("error") if isinstance(data, dict) else None
            detail = detail if isinstance(detail, str) else "Request rejected"
            raise ValueError(f"Firmable HTTP {response.status_code}: {detail.replace(key, '[redacted]')[:1000]}")
        if not isinstance(data, dict):
            raise ValueError("Firmable returned an unexpected JSON shape")
        if path == "/filter-options" and (not isinstance(data.get("filters"), list) or not isinstance(data.get("markets"), list)):
            raise ValueError("Firmable filter options are missing filters or markets")
        if path == "/people/search" and not (isinstance(data.get("records"), list) or data.get("success") is False and data.get("totalPeople") == 0):
            raise ValueError("Firmable search response is missing records")
        if path == "/tech-intel" and not isinstance(data.get("tech_intelligence"), list):
            raise ValueError("Firmable technology response is missing tech_intelligence")
        return {"status": "success", "data": data}
