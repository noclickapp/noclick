"""Fiber AI 1.44.0 prospecting and audience operations.

Contract: https://api.fiber.ai/openapi.json
Each operation makes one request. Page cursors and asynchronous job states are
returned unchanged; no automatic enrichment, export, notification or retry runs.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.fiber.ai"
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class FiberAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Fiber API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://fiber.ai/app/api",
            "x-credential-instructions": "Open Fiber → API, create an API key, and paste the key. Searches and enrichment use your Fiber credits; listing audiences is free."})
    credential_type: Literal["fiber_api_key"] = Field("fiber_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() or ord(c) < 33 for c in value):
            raise ValueError("Paste the API key without spaces or an authentication prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class FiberKeywords(_Input):
    containsAll: list[str] | None = None
    containsAny: list[str] | None = None
    containsNone: list[str] | None = None


class FiberNames(_Input):
    anyOf: list[str] | None = None
    noneOf: list[str] | None = None


class FiberEmployeeCount(_Input):
    lowerBoundExclusive: int | None = Field(None, ge=0)
    upperBoundInclusive: int | None = Field(None, ge=0)


class FiberCompanySearchParams(_Input):
    """Common company filters, combined by Fiber; omit a field to leave it unfiltered."""
    domains: list[str] | None = None
    nameLike: FiberNames | None = None
    employeeCountV2: FiberEmployeeCount | None = None
    keywords: FiberKeywords | None = None


class FiberPersonName(_Input):
    name: str


class FiberPersonNames(_Input):
    anyOf: list[FiberPersonName]


class FiberPeopleSearchParams(_Input):
    """Common person filters, combined by Fiber."""
    fuzzyName: FiberPersonNames | None = None
    keywords: FiberKeywords | None = None
    openToWork: bool | None = None
    hasWorkEmailOnFile: bool | None = None
    hasPhoneOnFile: bool | None = None


class _Audience(_Input):
    audience_id: str = Field(..., title="Audience", min_length=1, max_length=512,
        json_schema_extra={"x-dynamic-options": {"field_name": "audience_id"}})

    @field_validator("audience_id")
    @classmethod
    def identifier(cls, value):
        if value in {".", ".."} or any(ord(c) < 33 for c in value) or any(c in value for c in "/\\%?#"):
            raise ValueError("Use an audience ID, without a URL or path")
        return value


class _AudiencePage(_Audience):
    pageSize: int = Field(100, ge=1, le=500, title="Page size")
    cursor: str | None = Field(None, max_length=8192, description="Use nextCursor from the previous page of this same audience and operation.")


class FiberListAudiencesConfig(_Input):
    operation: Literal["list_audiences"] = Field("list_audiences", json_schema_extra={"ui:hidden": True})


class FiberCreateAudienceConfig(_Input):
    operation: Literal["create_audience"] = Field("create_audience", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=200)
    creationMethod: Literal["NORMAL", "START_FROM_PROSPECTS"] = "NORMAL"


class FiberGetAudienceStatusConfig(_Audience):
    operation: Literal["get_audience_status"] = Field("get_audience_status", json_schema_extra={"ui:hidden": True})


class FiberArchiveAudienceConfig(_Audience):
    """Archive the selected audience; this is a write."""
    operation: Literal["archive_audience"] = Field("archive_audience", json_schema_extra={"ui:hidden": True})


class FiberListAudienceCompaniesConfig(_AudiencePage):
    operation: Literal["list_audience_companies"] = Field("list_audience_companies", json_schema_extra={"ui:hidden": True})


class FiberListAudienceProspectsConfig(_AudiencePage):
    operation: Literal["list_audience_prospects"] = Field("list_audience_prospects", json_schema_extra={"ui:hidden": True})


class FiberUpdateAudienceSearchParamsConfig(_Audience):
    operation: Literal["update_audience_search_params"] = Field("update_audience_search_params", json_schema_extra={"ui:hidden": True})
    companySearchParams: FiberCompanySearchParams | None = Field(None, json_schema_extra=JSON_EDITOR)
    prospectSearchParams: FiberPeopleSearchParams | None = Field(None, json_schema_extra=JSON_EDITOR)


class FiberBuildAudienceConfig(_Audience):
    """Start the audience build. Poll Get Audience Status for completion."""
    operation: Literal["build_audience"] = Field("build_audience", json_schema_extra={"ui:hidden": True})


class FiberGetEnrichmentStatusConfig(_Audience):
    operation: Literal["get_enrichment_status"] = Field("get_enrichment_status", json_schema_extra={"ui:hidden": True})


class FiberEnrichmentTypes(_Input):
    getWorkEmails: bool = True
    getPersonalEmails: bool = False
    getPhoneNumbers: bool = False


class _Enrichment(_Audience):
    maxProspectsToEnrich: int = Field(..., ge=1, description="Maximum prospects for this run. Fiber credits may be charged.")
    enrichmentType: FiberEnrichmentTypes = Field(..., json_schema_extra=JSON_EDITOR)
    runCompanyLiveEnrichment: bool = False
    runProfileLiveEnrichment: bool = False
    runProfileSalesNav: bool = False
    runContactEnrichment: bool = True


class FiberEstimateEnrichmentConfig(_Enrichment):
    operation: Literal["estimate_enrichment"] = Field("estimate_enrichment", json_schema_extra={"ui:hidden": True})


class FiberStartEnrichmentConfig(_Enrichment):
    """Start paid enrichment. Poll Get Enrichment Status for completion."""
    operation: Literal["start_enrichment"] = Field("start_enrichment", json_schema_extra={"ui:hidden": True})


class _CompanySearch(_Input):
    searchParams: FiberCompanySearchParams = Field(..., json_schema_extra=JSON_EDITOR)


class _PeopleSearch(_Input):
    searchParams: FiberPeopleSearchParams = Field(default_factory=FiberPeopleSearchParams, json_schema_extra=JSON_EDITOR)


class FiberSearchCompaniesConfig(_CompanySearch):
    operation: Literal["search_companies"] = Field("search_companies", json_schema_extra={"ui:hidden": True})
    pageSize: int = Field(25, ge=1, le=1000)
    cursor: str | None = Field(None, max_length=8192, description="Cursor from the previous company search with the same filters.")
    includeCount: bool = False


class FiberCountCompaniesConfig(_CompanySearch):
    operation: Literal["count_companies"] = Field("count_companies", json_schema_extra={"ui:hidden": True})


class FiberSearchPeopleConfig(_PeopleSearch):
    operation: Literal["search_people"] = Field("search_people", json_schema_extra={"ui:hidden": True})
    pageSize: int = Field(25, ge=1, le=1000)
    cursor: str | None = Field(None, max_length=8192, description="Cursor from the previous people search with the same filters.")
    includeCount: bool = False


class FiberCountPeopleConfig(_PeopleSearch):
    operation: Literal["count_people"] = Field("count_people", json_schema_extra={"ui:hidden": True})


class FiberCompanyIdentifier(_Input):
    identifier: Literal["linkedinUrl", "linkedinSlug", "linkedinOrgId", "domain"]
    value: str = Field(..., min_length=1)

    @field_validator("value")
    @classmethod
    def numeric(cls, value, info):
        if info.data.get("identifier") == "linkedinOrgId" and not re.fullmatch(r"\d+", value):
            raise ValueError("LinkedIn organization IDs contain digits only")
        return value


class FiberPersonIdentifier(_Input):
    identifier: Literal["linkedinUrl", "linkedinSlug", "linkedinUserId", "entityUrn"]
    value: str = Field(..., min_length=1)

    @field_validator("value")
    @classmethod
    def numeric(cls, value, info):
        if info.data.get("identifier") == "linkedinUserId" and not re.fullmatch(r"\d+", value):
            raise ValueError("LinkedIn user IDs contain digits only")
        return value


class FiberResolveCompaniesConfig(_Input):
    operation: Literal["resolve_companies"] = Field("resolve_companies", json_schema_extra={"ui:hidden": True})
    companies: list[FiberCompanyIdentifier] = Field(..., min_length=1, max_length=100, json_schema_extra=JSON_EDITOR)


class FiberResolvePeopleConfig(_Input):
    operation: Literal["resolve_people"] = Field("resolve_people", json_schema_extra={"ui:hidden": True})
    people: list[FiberPersonIdentifier] = Field(..., min_length=1, max_length=100, json_schema_extra=JSON_EDITOR)


class FiberValidateEmailConfig(_Input):
    operation: Literal["validate_email"] = Field("validate_email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=3, max_length=320, json_schema_extra={"format": "email"})


class FiberFindWorkEmailConfig(_Input):
    operation: Literal["find_work_email"] = Field("find_work_email", json_schema_extra={"ui:hidden": True})
    full_name: str = Field(..., min_length=1, title="Full name")
    company_domain: str = Field(..., min_length=1, title="Company domain")


FiberConfig = Annotated[Union[
    FiberListAudiencesConfig, FiberCreateAudienceConfig, FiberGetAudienceStatusConfig,
    FiberArchiveAudienceConfig, FiberListAudienceCompaniesConfig, FiberListAudienceProspectsConfig,
    FiberUpdateAudienceSearchParamsConfig, FiberBuildAudienceConfig, FiberGetEnrichmentStatusConfig,
    FiberEstimateEnrichmentConfig, FiberStartEnrichmentConfig, FiberSearchCompaniesConfig,
    FiberCountCompaniesConfig, FiberSearchPeopleConfig, FiberCountPeopleConfig,
    FiberResolveCompaniesConfig, FiberResolvePeopleConfig, FiberValidateEmailConfig,
    FiberFindWorkEmailConfig,
], Field(discriminator="operation")]


class FiberFullConfig(NodeConfig[FiberConfig, FiberAPIKeyCredential]):
    pass


ROUTES = {
    "list_audiences": ("GET", "/v1/audiences"),
    "create_audience": ("POST", "/v1/audiences/create"),
    "get_audience_status": ("GET", "/v1/audiences/{audience_id}/status"),
    "archive_audience": ("DELETE", "/v1/audiences/{audience_id}"),
    "list_audience_companies": ("GET", "/v1/audiences/{audience_id}/companies"),
    "list_audience_prospects": ("GET", "/v1/audiences/{audience_id}/prospects"),
    "update_audience_search_params": ("PATCH", "/v1/audiences/{audience_id}/search-params"),
    "build_audience": ("POST", "/v1/audiences/{audience_id}/build"),
    "get_enrichment_status": ("GET", "/v1/audiences/{audience_id}/enrichment/status"),
    "estimate_enrichment": ("POST", "/v1/audiences/{audience_id}/enrichment/estimate"),
    "start_enrichment": ("POST", "/v1/audiences/{audience_id}/enrich"),
    "search_companies": ("POST", "/v1/company-search"),
    "count_companies": ("POST", "/v1/company-count"),
    "search_people": ("POST", "/v1/people-search"),
    "count_people": ("POST", "/v1/people-search/count"),
    "resolve_companies": ("POST", "/v1/company-resolve"),
    "resolve_people": ("POST", "/v1/person-resolve"),
    "validate_email": ("POST", "/v1/validate-email/single"),
    "find_work_email": ("POST", "/v1/contact-details/basic-work-email"),
}


def _redact(value, secret):
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items() if k.lower().replace("_", "") not in {"apikey", "authorization", "accesstoken"}}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    return value


class FiberNode(WorkflowNode):
    integration_type = "automation-fiber"
    connection_evidence = ConnectionEvidence(operation="list_audiences", noun="Fiber audiences")

    @classmethod
    def get_config_model(cls):
        return FiberFullConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        if field_name != "audience_id" or page_token:
            raise ValueError("Unknown Fiber field or continuation token")
        from nodes.core.registry import NodeFactory
        node = NodeFactory.create_node(node_id="fiber-audiences", node_type=cls.integration_type,
            node_data={"config": {"operation": "list_audiences"}, "credentials": credential_data})
        result = await node.execute({})
        if result.get("status") != "success":
            raise ValueError("Fiber audiences could not be loaded")
        rows = result["data"]["audiences"]
        return {"options": [{"value": row["audienceId"], "label": row["name"]} for row in rows
            if not search or search.casefold() in row["name"].casefold()], "next_page_token": None}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Fiber API key")
        credential = self.config.credentials
        config = self.config.config
        method, path = ROUTES[config.operation]
        fields = config.model_dump(exclude_none=True)
        fields.pop("operation")
        audience_id = fields.pop("audience_id", None)
        if audience_id is not None:
            path = path.format(audience_id=quote(audience_id, safe=""))
        if config.operation == "find_work_email":
            fields = {"name": {"mode": "fullName", "fullName": config.full_name},
                "company": {"mode": "domain", "domain": config.company_domain}}
        fields["apiKey"] = credential.api_key
        try:
            async with guarded_async_client(timeout=180, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Accept": "application/json"},
                    **({"params": fields} if method in {"GET", "DELETE"} else {"json": fields}))
        except (httpx.HTTPError, OSError):
            return {"status": "error", "operation": config.operation,
                "error": "Fiber request did not complete; check the provider before retrying a write"}
        if response.status_code != 200:
            return _redact({"status": "error", "operation": config.operation,
                "http_status": response.status_code, "error": response.text[:2000] or "Fiber rejected the request"}, credential.api_key)
        if len(response.content) > 10 * 1024 * 1024:
            raise ValueError("Fiber response exceeds 10 MB; reduce the page size")
        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected a JSON response from Fiber")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Fiber returned invalid JSON") from None
        if not isinstance(body, dict):
            raise ValueError("Fiber returned an invalid response envelope")
        if body.get("error") or body.get("errors"):
            return _redact({"status": "error", "operation": config.operation, "error": body}, credential.api_key)
        data = body.get("output")
        if not isinstance(data, dict):
            raise ValueError("Fiber response is missing its output object")
        if config.operation == "list_audiences":
            rows = data.get("audiences")
            if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("audienceId"), str) or not isinstance(row.get("name"), str) for row in rows):
                raise ValueError("Fiber returned an invalid audience list")
        return _redact({"status": "success", "operation": config.operation,
            "data": data, "charge_info": body.get("chargeInfo"),
            "warnings": body.get("warnings"), "advice": body.get("advice")}, credential.api_key)
