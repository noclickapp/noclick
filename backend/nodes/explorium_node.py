"""Explorium AgentSource API (published OpenAPI 0.3.72).

Each operation makes one request. Search pagination is explicit; enrichment may
consume the connected account's credits. No webhook receiver is installed.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.explorium.ai"
BusinessId = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
ProspectId = Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
ResourceId = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]


class ExploriumAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Explorium API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://admin.explorium.ai/",
        "x-credential-instructions": "Copy your API key from the Explorium account console. NoClick sends it in the api_key header to api.explorium.ai. Search and enrichment use your Explorium plan and credits. Connection testing reads your account's credit balance.",
    })
    credential_type: Literal["explorium_api_key"] = Field("explorium_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste an API key without whitespace or control characters")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class BusinessMatch(Input):
    name: str | None = Field(None, max_length=256)
    domain: str | None = None
    url: str | None = None
    linkedin_url: str | None = None

    @model_validator(mode="after")
    def identifying_field(self):
        if not any((self.name, self.domain, self.url, self.linkedin_url)):
            raise ValueError("Supply a business name, domain or URL")
        return self


class ProspectMatch(Input):
    business_id: str | None = None
    full_name: str | None = None
    company_name: str | None = None
    email: str | None = None
    phone_number: str | None = None
    linkedin: str | None = None

    @model_validator(mode="after")
    def identifying_field(self):
        if not any((self.full_name, self.email, self.phone_number, self.linkedin)):
            raise ValueError("Supply a prospect name, email, phone or LinkedIn URL")
        return self


class BusinessIds(Input):
    values: list[BusinessId]
    negate: bool | None = None


class ProspectIds(Input):
    values: list[ProspectId]
    negate: bool | None = None


class Countries(Input):
    values: list[Annotated[str, Field(pattern=r"^[a-z]{2}$")]] = Field(..., description="Lowercase ISO alpha-2 country codes, for example us or ca.")
    negate: bool | None = None


class JobTitles(Input):
    values: list[str] = Field(..., max_length=300)
    negate: bool | None = None
    operator: Literal["or", "and"] | None = None
    include_related_job_titles: bool | None = None


class BusinessFilters(Input):
    business_id: BusinessIds | None = None
    country_code: Countries | None = None


class ProspectFilters(BusinessFilters):
    prospect_id: ProspectIds | None = None
    company_country_code: Countries | None = None
    job_title: JobTitles | None = None


class GetCredits(Input):
    operation: Literal["get_credits"] = "get_credits"


class MatchBusinesses(Input):
    operation: Literal["match_businesses"] = "match_businesses"
    businesses_to_match: list[BusinessMatch] = Field(..., min_length=1, max_length=50)


class MatchProspects(Input):
    operation: Literal["match_prospects"] = "match_prospects"
    prospects_to_match: list[ProspectMatch] = Field(..., min_length=1, max_length=50)


class Fetch(Input):
    mode: Literal["full", "preview"] = Field("full", description="Preview requires a custom paying plan. Full is the normal mode.")
    page_size: int = Field(25, ge=1, le=500)
    page: int | None = Field(None, ge=1)
    next_cursor: str | None = Field(None, description="Copy the cursor from the preceding response. Each run fetches one page.")


class FetchBusinesses(Fetch):
    operation: Literal["fetch_businesses"] = "fetch_businesses"
    filters: BusinessFilters | None = None
    exclude: list[BusinessId] | None = Field(None, max_length=1000)


class FetchProspects(Fetch):
    operation: Literal["fetch_prospects"] = "fetch_prospects"
    filters: ProspectFilters | None = None
    exclude: list[ProspectId] | None = Field(None, max_length=1000)


class BusinessStats(Input):
    operation: Literal["get_business_stats"] = "get_business_stats"
    filters: BusinessFilters


class ProspectStats(Input):
    operation: Literal["get_prospect_stats"] = "get_prospect_stats"
    filters: ProspectFilters


class BusinessEnrichment(Input):
    business_ids: BusinessId | Annotated[list[BusinessId], Field(min_length=1, max_length=50)]


class Firmographics(BusinessEnrichment):
    operation: Literal["enrich_firmographics"] = "enrich_firmographics"


class Technographics(BusinessEnrichment):
    operation: Literal["enrich_technographics"] = "enrich_technographics"


class Funding(BusinessEnrichment):
    operation: Literal["enrich_funding"] = "enrich_funding"


class WebsiteTraffic(BusinessEnrichment):
    operation: Literal["enrich_website_traffic"] = "enrich_website_traffic"


class Webstack(BusinessEnrichment):
    operation: Literal["enrich_webstack"] = "enrich_webstack"


class CompanyHierarchy(BusinessEnrichment):
    operation: Literal["enrich_company_hierarchy"] = "enrich_company_hierarchy"


class ProspectProfile(Input):
    operation: Literal["enrich_prospect_profile"] = "enrich_prospect_profile"
    prospect_ids: ProspectId | Annotated[list[ProspectId], Field(min_length=1, max_length=50)]


class ProspectContacts(Input):
    operation: Literal["enrich_prospect_contacts"] = "enrich_prospect_contacts"
    prospect_ids: ProspectId | Annotated[list[ProspectId], Field(min_length=1, max_length=50)]


class ListWebhooks(Input):
    operation: Literal["list_webhooks"] = "list_webhooks"
    status: Literal["active", "disabled"] | None = None


class CreateWebhook(Input):
    operation: Literal["create_webhook"] = "create_webhook"
    name: str = Field(..., min_length=1)
    webhook_url: str = Field(..., pattern=r"^https://[^\s]+$", max_length=65536, description="Public HTTPS receiver that you control. NoClick does not host this receiver.")
    description: str | None = None
    headers: list[str] | None = None
    payload_format: Literal["json", "stringified_json"] | None = None


class GetWebhook(Input):
    operation: Literal["get_webhook"] = "get_webhook"
    webhook_id: ResourceId


class UpdateWebhook(Input):
    operation: Literal["update_webhook"] = "update_webhook"
    webhook_id: ResourceId
    name: str | None = None
    description: str | None = None
    webhook_url: str | None = Field(None, pattern=r"^https://[^\s]+$", max_length=65536)
    headers: list[str] | None = None
    payload_format: Literal["json", "stringified_json"] | None = None
    status: Literal["active", "disabled"] | None = None


class DeleteWebhook(Input):
    operation: Literal["delete_webhook"] = "delete_webhook"
    webhook_id: ResourceId
    force: bool | None = Field(None, description="Allow deleting a webhook referenced by enrollments; returned enrollment IDs show the impact.")


class ListJobs(Input):
    operation: Literal["list_jobs"] = "list_jobs"
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "expired"] | None = None
    skip: int | None = Field(None, ge=0)


class GetJob(Input):
    operation: Literal["get_job"] = "get_job"
    job_id: ResourceId


class CancelJob(Input):
    operation: Literal["cancel_job"] = "cancel_job"
    job_id: ResourceId


Operation = Annotated[Union[GetCredits, MatchBusinesses, MatchProspects, FetchBusinesses, FetchProspects,
    BusinessStats, ProspectStats, Firmographics, Technographics, Funding, WebsiteTraffic, Webstack,
    CompanyHierarchy, ProspectProfile, ProspectContacts, ListWebhooks, CreateWebhook, GetWebhook,
    UpdateWebhook, DeleteWebhook, ListJobs, GetJob, CancelJob], Field(discriminator="operation")]


class ExploriumConfig(NodeConfig[Operation, ExploriumAPIKeyCredential]):
    pass


ROUTES = {
    "get_credits": ("GET", "/v2/credits"),
    "match_businesses": ("POST", "/v2/businesses/match"),
    "match_prospects": ("POST", "/v2/prospects/match"),
    "fetch_businesses": ("POST", "/v2/businesses"),
    "fetch_prospects": ("POST", "/v2/prospects"),
    "get_business_stats": ("POST", "/v2/businesses/stats"),
    "get_prospect_stats": ("POST", "/v2/prospects/stats"),
    "enrich_firmographics": ("POST", "/v2/businesses/firmographics/enrich"),
    "enrich_technographics": ("POST", "/v2/businesses/technographics/enrich"),
    "enrich_funding": ("POST", "/v2/businesses/funding_and_acquisition/enrich"),
    "enrich_website_traffic": ("POST", "/v2/businesses/website_traffic/enrich"),
    "enrich_webstack": ("POST", "/v2/businesses/webstack/enrich"),
    "enrich_company_hierarchy": ("POST", "/v2/businesses/company_hierarchies/enrich"),
    "enrich_prospect_profile": ("POST", "/v2/prospects/profiles/enrich"),
    "enrich_prospect_contacts": ("POST", "/v2/prospects/contact_information/enrich"),
    "list_webhooks": ("GET", "/v2/webhooks"),
    "create_webhook": ("POST", "/v2/webhooks"),
    "get_webhook": ("GET", "/v2/webhooks/{webhook_id}"),
    "update_webhook": ("PATCH", "/v2/webhooks/{webhook_id}"),
    "delete_webhook": ("DELETE", "/v2/webhooks/{webhook_id}"),
    "list_jobs": ("GET", "/v2/jobs"),
    "get_job": ("GET", "/v2/jobs/status/{job_id}"),
    "cancel_job": ("POST", "/v2/jobs/cancel/{job_id}"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


class ExploriumNode(WorkflowNode):
    integration_type = "automation-explorium"
    connection_evidence = ConnectionEvidence(noun="account credits", operation="get_credits", label_keys=("remaining_credits", "allocated_credits"))

    @classmethod
    def get_config_model(cls):
        return ExploriumConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Explorium API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        fields = op.model_dump(exclude={"operation"}, exclude_none=True)
        for name in ("webhook_id", "job_id"):
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", quote(fields.pop(name), safe=""))
        kwargs = {"json": fields} if method in {"POST", "PATCH"} and op.operation != "cancel_job" else {"params": fields}
        try:
            async with guarded_async_client(verify=True, trust_env=False, follow_redirects=False, timeout=httpx.Timeout(60)) as client:
                async with client.stream(method, BASE + path, headers={"api_key": secret, "Accept": "application/json"}, **kwargs) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 8 * 1024 * 1024:
                            raise ValueError("Explorium response exceeds 8 MiB")
                    try:
                        payload = json.loads(raw)
                    except (ValueError, UnicodeError):
                        raise ValueError("Explorium returned invalid JSON") from None
                    if not isinstance(payload, dict):
                        raise ValueError("Explorium returned an unexpected response shape")
                    if not 200 <= response.status_code < 300:
                        message = payload.get("detail") or payload.get("message") or payload.get("error")
                        output = {"status": "error", "success": False, "http_status": response.status_code,
                            "error": message if isinstance(message, str) else "Explorium rejected the request"}
                    else:
                        output = {"status": "success", "success": True, "data": payload}
        except httpx.HTTPError:
            raise ValueError("Explorium request could not be completed") from None
        output = _redact(output, secret)
        await self.emit(output)
        return output
