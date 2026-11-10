"""RocketReach contact discovery and enrichment against the published v2 API.

API-key authentication and fixed routes keep requests on the provider's API.
Updated-person polling uses documented search filters and scoped shared state.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://api.rocketreach.co/api/v2"
FAMILY = "rocket_reach_api_key"
DOCS = "https://docs.rocketreach.co/openapi/index.yaml"


class RocketReachAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="RocketReach API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://rocketreach.co/account?section=nav_gen_api",
            "x-credential-instructions": "Copy your API key from RocketReach Account Settings → My API Key and paste it here. Your plan controls standard and Universal API access. NoClick verifies the key by reading your account.",
        })
    credential_type: Literal["rocket_reach_api_key"] = Field("rocket_reach_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class PersonQuery(Input):
    company_domain: list[str] | None = Field(None, description="Employer domains, e.g. rocketreach.co")
    company_name: list[str] | None = None
    current_title: list[str] | None = None
    geo: list[str] | None = None
    name: list[str] | None = None
    email: list[str] | None = None
    skills: list[str] | None = None
    management_levels: list[str] | None = None
    department: list[str] | None = None
    job_change_signal: list[str] | None = None
    update_time: list[str] | None = Field(None, description="Updated since date, e.g. [2025-01-01]")


class CompanyQuery(Input):
    domain: list[str] | None = None
    name: list[str] | None = None
    geo: list[str] | None = None
    industry: list[str] | None = None
    employees: list[str] | None = None
    revenue: list[str] | None = None
    techstack: list[str] | None = None
    keyword: list[str] | None = None


class SearchPeople(Input):
    query: PersonQuery = Field(..., title="Search filters")
    start: int = Field(1, ge=1, le=10000, description="One-based result offset. Request the next page explicitly.")
    page_size: int = Field(10, ge=1, le=100)
    order_by: Literal["relevance", "popularity", "score"] = "relevance"


class SearchCompanies(Input):
    query: CompanyQuery = Field(..., title="Search filters")
    start: int = Field(1, ge=1, le=10000)
    page_size: int = Field(10, ge=1, le=100)
    order_by: Literal["relevance", "popularity", "score"] = "relevance"


class PersonMatch(Input):
    id: int | None = Field(None, gt=0, title="RocketReach profile ID")
    name: str | None = Field(None, min_length=1)
    current_employer: str | None = Field(None, min_length=1)
    title: str | None = Field(None, min_length=1)
    linkedin_url: str | None = Field(None, min_length=1)
    email: EmailStr | None = None
    phone: str | None = Field(None, min_length=1)
    npi_number: int | None = Field(None, gt=0)
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def match(self):
        if not (self.id or self.linkedin_url or self.email or self.phone or self.npi_number or (self.name and self.current_employer)):
            raise ValueError("Supply an ID, LinkedIn URL, email, phone, NPI, or name with current employer")
        return self


class StandardPerson(PersonMatch):
    lookup_type: Literal["standard", "premium", "premium (feeds disabled)", "bulk", "phone", "enrich"] = "standard"


class UniversalPerson(PersonMatch):
    reveal_phone: bool = False
    reveal_professional_email: bool = False
    reveal_personal_email: bool = False
    reveal_detailed_person_enrichment: bool = False
    reveal_healthcare_enrichment: bool = False


class LookupPerson(StandardPerson):
    return_cached_emails: bool = True
    webhook_id: int | None = Field(None, gt=0, description="Existing webhook ID configured in RocketReach settings")


class LookupUniversalPerson(UniversalPerson):
    return_cached_emails: bool = True
    webhook_id: int | None = Field(None, gt=0)


class LookupCompany(Input):
    id: int | None = Field(None, gt=0, title="RocketReach company ID")
    domain: str | None = Field(None, min_length=1)
    name: str | None = Field(None, min_length=1)
    linkedin_url: str | None = Field(None, min_length=1)
    ticker: str | None = Field(None, min_length=1)

    @model_validator(mode="after")
    def match(self):
        if not any((self.id, self.domain, self.name, self.linkedin_url, self.ticker)):
            raise ValueError("Supply a company ID, domain, name, LinkedIn URL or ticker")
        return self


class LookupStatus(Input):
    ids: list[int] | None = Field(None, min_length=1, max_length=100, description="Profile IDs; sent as repeated ids query parameters")
    rr_request_id: str | None = Field(None, min_length=1, description="RR-Request-ID returned by lookup or bulk lookup; takes priority over IDs")

    @model_validator(mode="after")
    def match(self):
        if not self.ids and not self.rr_request_id:
            raise ValueError("Supply profile IDs or a RocketReach request ID")
        return self


class BulkPeople(Input):
    queries: list[StandardPerson] = Field(..., min_length=1, max_length=100, title="People to enrich")
    profile_list: str = Field("API Bulk Lookup", description="RocketReach list receiving the enriched contacts")
    webhook_id: int | None = Field(None, gt=0)


class BulkUniversalPeople(Input):
    queries: list[UniversalPerson] = Field(..., min_length=1, max_length=100)
    profile_list: str = "API Bulk Lookup"
    webhook_id: int | None = Field(None, gt=0)


class VerifyEmail(Input):
    email: EmailStr = Field(..., max_length=254)


class GetAccountConfig(Input):
    operation: Literal["get_account"] = Field("get_account", title="Get account", json_schema_extra={"ui:hidden": True})


class CreatePersonSearchConfig(SearchPeople):
    operation: Literal["create_person_search"] = Field("create_person_search", title="Search people", json_schema_extra={"ui:hidden": True})


class CreateCompanySearchConfig(SearchCompanies):
    operation: Literal["create_company_search"] = Field("create_company_search", title="Search companies", json_schema_extra={"ui:hidden": True})


class CreatePersonLookupConfig(LookupPerson):
    operation: Literal["create_person_lookup"] = Field("create_person_lookup", title="Look up person", json_schema_extra={"ui:hidden": True})


class CheckPersonLookupStatusConfig(LookupStatus):
    operation: Literal["check_person_lookup_status"] = Field("check_person_lookup_status", title="Check people lookup status", json_schema_extra={"ui:hidden": True})


class CreateCompanyLookupConfig(LookupCompany):
    operation: Literal["create_company_lookup"] = Field("create_company_lookup", title="Look up company", json_schema_extra={"ui:hidden": True})


class CreatePersonAndCompanyLookupConfig(LookupPerson):
    operation: Literal["create_person_and_company_lookup"] = Field("create_person_and_company_lookup", title="Look up person and company", json_schema_extra={"ui:hidden": True})


class CreatePersonBulkLookupConfig(BulkPeople):
    operation: Literal["create_person_bulk_lookup"] = Field("create_person_bulk_lookup", title="Bulk enrich people", json_schema_extra={"ui:hidden": True})


class CreateEmailVerifyConfig(VerifyEmail):
    operation: Literal["create_email_verify"] = Field("create_email_verify", title="Verify email", json_schema_extra={"ui:hidden": True})


class GetUniversalAccountConfig(Input):
    operation: Literal["get_universal_account"] = Field("get_universal_account", title="Get Universal account", json_schema_extra={"ui:hidden": True})


class CreateUniversalPersonSearchConfig(SearchPeople):
    operation: Literal["create_universal_person_search"] = Field("create_universal_person_search", title="Search Universal people", json_schema_extra={"ui:hidden": True})


class CreateUniversalCompanySearchConfig(SearchCompanies):
    operation: Literal["create_universal_company_search"] = Field("create_universal_company_search", title="Search Universal companies", json_schema_extra={"ui:hidden": True})


class CreateUniversalPersonLookupConfig(LookupUniversalPerson):
    operation: Literal["create_universal_person_lookup"] = Field("create_universal_person_lookup", title="Look up Universal person", json_schema_extra={"ui:hidden": True})


class CreateUniversalPersonBulkLookupConfig(BulkUniversalPeople):
    operation: Literal["create_universal_person_bulk_lookup"] = Field("create_universal_person_bulk_lookup", title="Bulk enrich Universal people", json_schema_extra={"ui:hidden": True})


class CreateUniversalCompanyLookupConfig(LookupCompany):
    operation: Literal["create_universal_company_lookup"] = Field("create_universal_company_lookup", title="Look up Universal company", json_schema_extra={"ui:hidden": True})


class CheckUniversalPersonLookupStatusConfig(LookupStatus):
    operation: Literal["check_universal_person_lookup_status"] = Field("check_universal_person_lookup_status", title="Check Universal people lookup status", json_schema_extra={"ui:hidden": True})


class UpdatedPeople(PollTriggerConfigBase):
    updated_since: str = Field(..., description="Poll profiles updated since this YYYY-MM-DD date. Use a recent date and narrow filters; at most 10,000 matches can be watched.")
    query: PersonQuery = Field(default_factory=PersonQuery, title="People filters", description="Optional filters. updated_since controls update_time.")

    @field_validator("updated_since")
    @classmethod
    def since(cls, value):
        date.fromisoformat(value)
        if len(value) != 10:
            raise ValueError("Use YYYY-MM-DD")
        return value


class OnUpdatedPersonConfig(UpdatedPeople):
    operation: Literal["on_updated_person"] = Field("on_updated_person", title="On new or updated person", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})


class OnUpdatedUniversalPersonConfig(UpdatedPeople):
    operation: Literal["on_updated_universal_person"] = Field("on_updated_universal_person", title="On new or updated Universal person", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})


RocketReachConfig = Annotated[Union[
    GetAccountConfig,
    CreatePersonSearchConfig,
    CreateCompanySearchConfig,
    CreatePersonLookupConfig,
    CheckPersonLookupStatusConfig,
    CreateCompanyLookupConfig,
    CreatePersonAndCompanyLookupConfig,
    CreatePersonBulkLookupConfig,
    CreateEmailVerifyConfig,
    GetUniversalAccountConfig,
    CreateUniversalPersonSearchConfig,
    CreateUniversalCompanySearchConfig,
    CreateUniversalPersonLookupConfig,
    CreateUniversalPersonBulkLookupConfig,
    CreateUniversalCompanyLookupConfig,
    CheckUniversalPersonLookupStatusConfig,
    OnUpdatedPersonConfig,
    OnUpdatedUniversalPersonConfig
], Field(discriminator="operation")]


class RocketReachNodeConfig(NodeConfig[RocketReachConfig, RocketReachAPIKeyCredential]):
    pass


# Each action maps to one published operation; polling uses the corresponding search.
ROUTES = {
    "get_account": ("GET", "/account/", "account"),
    "create_person_search": ("POST", "/person/search", "list"),
    "create_company_search": ("POST", "/searchCompany", "list"),
    "create_person_lookup": ("GET", "/person/lookup", "object"),
    "check_person_lookup_status": ("GET", "/person/checkStatus", "list"),
    "create_company_lookup": ("GET", "/company/lookup/", "object"),
    "create_person_and_company_lookup": ("GET", "/profile-company/lookup", "object"),
    "create_person_bulk_lookup": ("POST", "/bulkLookup", "accepted"),
    "create_email_verify": ("POST", "/email/verify/", "object"),
    "get_universal_account": ("GET", "/universal/account/", "account"),
    "create_universal_person_search": ("POST", "/universal/person/search", "list"),
    "create_universal_company_search": ("POST", "/universal/company/search", "list"),
    "create_universal_person_lookup": ("GET", "/universal/person/lookup", "object"),
    "create_universal_person_bulk_lookup": ("POST", "/universal/person/bulk_lookup", "accepted"),
    "create_universal_company_lookup": ("GET", "/universal/company/lookup", "object"),
    "check_universal_person_lookup_status": ("GET", "/universal/person/check_status", "list"),
}
TRIGGERS = {"on_updated_person": "create_person_search", "on_updated_universal_person": "create_universal_person_search"}


def _redact(value, token):
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items() if k.lower() not in {"api_key", "api-key", "authorization", "access_token"}}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    return value


class RocketReachNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-rocket-reach"
    connection_evidence = ConnectionEvidence(noun="RocketReach account", identity_operation="get_account", identity_keys=("email", "first_name", "id"))

    @classmethod
    def get_config_model(cls):
        return RocketReachNodeConfig

    async def _request(self, operation, values):
        method, path, shape = ROUTES[operation]
        token = self.config.credentials.api_key
        kwargs = {"headers": {"Api-Key": token, "Accept": "application/json"}}
        if method == "POST":
            kwargs["json"] = values
        else:
            params = []
            for key, value in values.items():
                if isinstance(value, list):
                    params.extend((key, str(v)) for v in value)
                else:
                    params.append((key, json.dumps(value, separators=(",", ":")) if isinstance(value, (dict, bool)) else str(value)))
            kwargs["params"] = params
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, **kwargs)
        if response.status_code not in ({200, 201} if method == "POST" else {200}):
            # No retry: lookups and bulk enrichments may consume credits.
            text = _redact(response.text[:2000], token)
            raise ValueError(f"RocketReach HTTP {response.status_code}: {text}")
        if shape == "accepted":
            return {"accepted": True, "rr_request_id": response.headers.get("RR-Request-ID"), "completion_verified": False}
        if len(response.content) > 10_000_000:
            raise ValueError("RocketReach response exceeds 10 MB")
        body = response.json()
        if isinstance(body, dict) and any(body.get(k) for k in ("error", "errors", "detail")):
            raise ValueError("RocketReach: " + str(_redact(body, token))[:2000])
        if shape == "list":
            if not isinstance(body, list) or any(not isinstance(row, dict) for row in body):
                raise ValueError("Expected a RocketReach list of records")
        elif not isinstance(body, dict):
            raise ValueError("Expected a RocketReach object")
        if shape == "account" and (type(body.get("id")) is not int or body["id"] <= 0):
            raise ValueError("RocketReach account identity is missing")
        return {"data": body, "rr_request_id": response.headers.get("RR-Request-ID")}

    async def _poll(self, config):
        query = config.query.model_dump(exclude_none=True)
        query["update_time"] = [config.updated_since]
        people = []
        for start in range(1, 10001, 100):
            result = await self._request(TRIGGERS[config.operation], {"query": query, "start": start, "page_size": 100, "order_by": "relevance"})
            rows = result["data"]
            if len(rows) > 100:
                raise ValueError("RocketReach exceeded the requested page size")
            people.extend(rows)
            if len(rows) < 100:
                break
        else:
            raise ValueError("RocketReach polling reached 10,000 results; narrow filters or use a more recent date")
        identities = set()
        for row in people:
            if type(row.get("id")) is not int or row["id"] <= 0 or not isinstance(row.get("update_time"), str):
                raise ValueError("RocketReach polling requires profile ID and update_time")
            timestamp = datetime.fromisoformat(row["update_time"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("RocketReach update_time must include a timezone")
            identity = str(row["id"]) + ":" + timestamp.isoformat()
            if row["id"] in identities:
                raise ValueError("RocketReach repeated a profile across search pages")
            identities.add(row["id"])
        fresh = await self._filter_unseen(people, lambda row: str(row["id"]) + ":" + datetime.fromisoformat(row["update_time"].replace("Z", "+00:00")).isoformat())
        return {"people": fresh, "new_or_updated_count": len(fresh)}

    @classmethod
    def resolve_agent_event(cls, output):
        people = output.get("people") if isinstance(output, dict) else None
        if not isinstance(people, list):
            return super().resolve_agent_event(output)
        if not people:
            return None
        lines = [f"- {p.get('name') or 'Person'}: {p.get('current_title') or ''} at {p.get('current_employer') or ''}; profile {p['id']}, updated {p['update_time']}; {p.get('linkedin_url') or ''}" for p in people[:20]]
        return {"text": f"RocketReach: {len(people)} new or updated people matching your search.\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a RocketReach API key")
        config = self.config.config
        if config.operation in TRIGGERS:
            result = await self._poll(config)
        else:
            values = config.model_dump(exclude={"operation"}, exclude_none=True)
            result = await self._request(config.operation, values)
            if config.operation in {"create_person_search", "create_company_search", "create_universal_person_search", "create_universal_company_search"}:
                result["start"] = config.start
                result["page_size"] = config.page_size
                # The contract returns an array, not a total or continuation token.
                result["next_start"] = config.start + config.page_size if len(result["data"]) == config.page_size and config.start + config.page_size <= 10000 else None
        output = _redact({"status": "success", "operation": config.operation, **result}, self.config.credentials.api_key)
        await self.emit(output)
        return output
