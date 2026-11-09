"""Ploid public API v2 people research, monitors and typed datasets.

Contract: https://api.ploid.com/v1/openapi.json (version 2.0.0).
Each operation performs one request; pagination and async run state are returned
unchanged so workflows can explicitly continue them. Paid POSTs are never retried.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.ploid.com"


class PloidAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Ploid API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://ploid.com/docs",
            "x-credential-instructions": "Create an API key in your Ploid account and paste it here. Enable account:read for the connection check, people:search for searches and datasets, people:enrich for contact enrichment, and the monitor permissions needed for your actions. Ploid charges ACU for research and monitor runs.",
        })
    credential_type: Literal["ploid_api_key"] = Field("ploid_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"}, repr=False)

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)


class _Id(_Input):
    @field_validator("monitor_id", "run_id", "dataset_id", mode="before", check_fields=False)
    @classmethod
    def identifier(cls, value, info):
        if info.field_name in {"monitor_id", "run_id", "dataset_id"}:
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,255}", value):
                raise ValueError("Use a single Ploid resource ID")
        return value


class _Paid(_Input):
    idempotency_key: str | None = Field(None, max_length=255,
        description="Reuse the same key for a retry of the same request within 24 hours to avoid duplicate charges.")


class _Filter(_Input):
    title: str | None = Field(None, min_length=1, max_length=200)
    company: str | None = Field(None, min_length=1, max_length=200)
    location: str | None = Field(None, min_length=1, max_length=200)
    industry: str | None = Field(None, min_length=1, max_length=200)
    seniority: str | None = Field(None, min_length=1, max_length=80)


class SearchPeople(_Paid):
    """Search people; return the provider's results and pagination metadata."""
    operation: Literal["search_people"] = "search_people"
    query: str = Field(..., min_length=1, max_length=4000)
    type: Literal["instant", "fast", "auto", "deep"] = "auto"
    num_results: int = Field(10, ge=1, le=150, description="Inline results only. For another page use meta.next_offset with instant or fast mode.")
    offset: int | None = Field(None, ge=0, le=149)
    filters: _Filter | None = None

    @model_validator(mode="after")
    def paging(self):
        if self.offset is not None and self.type not in {"instant", "fast"}:
            raise ValueError("Offset pagination requires instant or fast search")
        return self


class ResolvePerson(_Paid):
    """Identify a person from a name and at least one contextual hint."""
    operation: Literal["resolve_person"] = "resolve_person"
    name: str = Field(..., min_length=2, max_length=200)
    company: str | None = Field(None, min_length=1, max_length=200)
    role: str | None = Field(None, min_length=1, max_length=300)
    location: str | None = Field(None, min_length=1, max_length=200)
    work_email: str | None = Field(None, max_length=254, json_schema_extra={"format": "email"})

    @model_validator(mode="after")
    def hint(self):
        if not any((self.company, self.role, self.location, self.work_email)):
            raise ValueError("Supply a company, role, location or work email")
        return self


class ReverseEmail(_Input):
    """Find the person behind an email."""
    operation: Literal["reverse_email"] = "reverse_email"
    email: str = Field(..., max_length=254, json_schema_extra={"format": "email"})
    name: str | None = Field(None, min_length=2, max_length=200)
    fast_only: bool = False


class _PersonIdentifier(_Input):
    person_id: str | None = Field(None, min_length=1, max_length=500)
    linkedin_url: str | None = None
    name: str | None = Field(None, min_length=1, max_length=200)
    company_domain: str | None = Field(None, min_length=3, max_length=253)

    @model_validator(mode="after")
    def one_identifier(self):
        if sum((bool(self.person_id), bool(self.linkedin_url), bool(self.name or self.company_domain))) != 1 or bool(self.name) != bool(self.company_domain):
            raise ValueError("Supply person_id, linkedin_url, or both name and company_domain")
        return self


class GetPerson(_Paid):
    """Get an evidence-backed person record, including async status when returned."""
    operation: Literal["get_person"] = "get_person"
    identifier: _PersonIdentifier
    include: list[Literal["work_email", "personal_email", "phone"]] | None = Field(None, min_length=1, max_length=3)


class GetPersonRun(_Id):
    """Poll a deep person research run."""
    operation: Literal["get_person_run"] = "get_person_run"
    run_id: str


class CancelPersonRun(_Id):
    """Cancel a deep person research run."""
    operation: Literal["cancel_person_run"] = "cancel_person_run"
    run_id: str


class _Schedule(_Input):
    preset: Literal["hourly", "daily", "weekly"]
    timezone: str = "UTC"


class _MonitorOutput(_Input):
    type: Literal["text", "object"]
    description: str | None = None


class CompileMonitor(_Input):
    """Preview a monitor plan and output schema without creating it."""
    operation: Literal["compile_monitor"] = "compile_monitor"
    query: str = Field(..., min_length=1, max_length=1000)
    output: _MonitorOutput | None = None


class CreateMonitor(_Input):
    """Create a scheduled social monitor; scheduled runs consume ACU."""
    operation: Literal["create_monitor"] = "create_monitor"
    query: str = Field(..., min_length=1, max_length=1000)
    schedule: _Schedule
    name: str | None = Field(None, max_length=120)
    output: _MonitorOutput | None = None
    webhook_url: str | None = Field(None, json_schema_extra={"format": "uri"})
    webhook_secret: str | None = Field(None, min_length=16, max_length=256, json_schema_extra={"ui:widget": "password"})
    max_items_per_run: int = Field(25, ge=1, le=100)


class _Monitor(_Id):
    monitor_id: str


class _Page(_Input):
    cursor: str | None = Field(None, description="next_cursor from the preceding page; pagination is explicit.")
    limit: int = Field(50, ge=1, le=100)


class ListMonitors(_Page):
    """List the connected account's monitors."""
    operation: Literal["list_monitors"] = "list_monitors"


class GetMonitor(_Monitor):
    """Read a monitor."""
    operation: Literal["get_monitor"] = "get_monitor"


class UpdateMonitor(_Monitor):
    """Update, pause or resume a monitor; resuming enables paid scheduled runs."""
    operation: Literal["update_monitor"] = "update_monitor"
    name: str | None = Field(None, max_length=120)
    status: Literal["active", "paused"] | None = None
    query: str | None = Field(None, min_length=1, max_length=1000)
    schedule: _Schedule | None = None
    max_items_per_run: int | None = Field(None, ge=1, le=100)

    @model_validator(mode="after")
    def nonempty(self):
        if not any(getattr(self, k) is not None for k in ("name", "status", "query", "schedule", "max_items_per_run")):
            raise ValueError("Supply at least one monitor change")
        return self


class DeleteMonitor(_Monitor):
    """Delete (disable) a monitor."""
    operation: Literal["delete_monitor"] = "delete_monitor"


class RunMonitor(_Monitor):
    """Trigger a paid monitor run now."""
    operation: Literal["run_monitor"] = "run_monitor"


class TestMonitor(_Monitor):
    """Test what a monitor finds now; consumes research credits."""
    operation: Literal["test_monitor"] = "test_monitor"


class ListMonitorRuns(_Monitor, _Page):
    """List a monitor's runs, retaining the continuation cursor."""
    operation: Literal["list_monitor_runs"] = "list_monitor_runs"


class GetMonitorRun(_Monitor):
    """Read one monitor run."""
    operation: Literal["get_monitor_run"] = "get_monitor_run"
    run_id: str


class ListMonitorItems(_Monitor, _Page):
    """List emitted items, optionally limited to one run."""
    operation: Literal["list_monitor_items"] = "list_monitor_items"
    run_id: str | None = None


class DetectTechnologies(_Paid):
    """Detect a website's technology stack with evidence."""
    operation: Literal["detect_technologies"] = "detect_technologies"
    domain: str = Field(..., min_length=1, max_length=253)


class _Entity(_Input):
    type: Literal["person", "company", "custom"]


class _DatasetRow(_Input):
    name: str | None = Field(None, min_length=1, max_length=200)
    domain: str | None = Field(None, min_length=1, max_length=253)
    linkedin_url: str | None = Field(None, min_length=1, max_length=500)
    email: str | None = Field(None, max_length=320, json_schema_extra={"format": "email"})
    company: str | None = Field(None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def subject(self):
        if not any((self.name, self.domain, self.linkedin_url, self.email)):
            raise ValueError("Each row needs a name, domain, LinkedIn URL or email")
        return self


class _DatasetColumn(_Input):
    key: Union[Literal["name", "domain", "description", "founded_year", "headquarters", "headcount", "industry", "linkedin_url", "page_text", "socials.linkedin", "socials.x", "socials.instagram", "socials.youtube", "socials.tiktok", "socials.github", "title", "company", "location", "email.work", "email.personal", "phone", "website"], Annotated[str, Field(pattern=r"^custom\.[a-z0-9_]{1,60}$")]]
    description: str | None = Field(None, min_length=1, max_length=500)
    format: Literal["text", "date", "number", "options", "email", "phone", "url", "boolean", "range", "currency"] | None = None

    @model_validator(mode="after")
    def custom_description(self):
        if self.key.startswith("custom.") and not self.description:
            raise ValueError("Custom columns require a description")
        return self


class CreateDataset(_Paid):
    """Fill typed research columns for seeded rows; async mode returns a dataset ID."""
    operation: Literal["create_dataset"] = "create_dataset"
    entity: _Entity
    rows: list[_DatasetRow] = Field(..., min_length=1, max_length=2000)
    columns: list[_DatasetColumn] = Field(..., min_length=1, max_length=30)
    mode: Literal["sync", "async"] = "sync"
    deadline_ms: int = Field(20000, ge=1000, le=60000)
    include_unverified: bool = False

    @model_validator(mode="after")
    def bounds(self):
        if self.mode == "sync" and len(self.rows) > 25:
            raise ValueError("Sync datasets support at most 25 rows")
        if len({c.key for c in self.columns}) != len(self.columns):
            raise ValueError("Dataset column keys must be unique")
        return self


class GetDataset(_Id):
    """Get dataset progress and status."""
    operation: Literal["get_dataset"] = "get_dataset"
    dataset_id: str


class ListDatasetRows(_Id):
    """Read a page of dataset rows; retain pending and partial cell states."""
    operation: Literal["list_dataset_rows"] = "list_dataset_rows"
    dataset_id: str
    cursor: int | None = Field(None, ge=0)
    limit: int = Field(100, ge=1, le=500)


class EnrichPerson(_Paid):
    """Resolve contact fields for exactly one person identifier."""
    operation: Literal["enrich_person"] = "enrich_person"
    linkedin_url: str | None = None
    person_id: str | None = None
    email: str | None = None
    name: str | None = None
    company_domain: str | None = None
    fields: list[Literal["work_email", "personal_email", "phone", "linkedin_url"]] = Field(..., min_length=1, max_length=4)

    @model_validator(mode="after")
    def identifier(self):
        if sum((bool(self.linkedin_url), bool(self.person_id), bool(self.email), bool(self.name or self.company_domain))) != 1 or bool(self.name) != bool(self.company_domain):
            raise ValueError("Supply one identifier: LinkedIn URL, person ID, email, or name and company domain")
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("Contact fields must be unique")
        if "linkedin_url" in self.fields and not self.email:
            raise ValueError("Looking up a LinkedIn URL requires an email identifier")
        return self


class GetCredits(_Input):
    """Get workspace ACU balance and calling API key budget."""
    operation: Literal["get_credits"] = "get_credits"


class GetAccountUsage(_Input):
    """Get workspace usage and active API key context."""
    operation: Literal["get_account_usage"] = "get_account_usage"


class GetAccountProfile(_Input):
    """Read the signed-in user's profile to prove account access."""
    operation: Literal["get_account_profile"] = "get_account_profile"


PloidOperation = Annotated[Union[
    SearchPeople, ResolvePerson, ReverseEmail, GetPerson, GetPersonRun, CancelPersonRun,
    CompileMonitor, CreateMonitor, ListMonitors, GetMonitor, UpdateMonitor, DeleteMonitor,
    RunMonitor, TestMonitor, ListMonitorRuns, GetMonitorRun, ListMonitorItems,
    DetectTechnologies, CreateDataset, GetDataset, ListDatasetRows, EnrichPerson,
    GetCredits, GetAccountUsage, GetAccountProfile,
], Field(discriminator="operation")]


class PloidConfig(NodeConfig[PloidOperation, PloidAPIKeyCredential]):
    pass


# Each entry corresponds to exactly one operation in the pinned public contract.
ROUTES = {
    "search_people": ("POST", "/v1/search"),
    "resolve_person": ("POST", "/v1/resolve"),
    "reverse_email": ("POST", "/v1/reverse"),
    "get_person": ("POST", "/v1/person"),
    "get_person_run": ("GET", "/v1/person/runs/{run_id}"),
    "cancel_person_run": ("DELETE", "/v1/person/runs/{run_id}"),
    "compile_monitor": ("POST", "/v1/monitors/compile"),
    "create_monitor": ("POST", "/v1/monitors"),
    "list_monitors": ("GET", "/v1/monitors"),
    "get_monitor": ("GET", "/v1/monitors/{monitor_id}"),
    "update_monitor": ("PATCH", "/v1/monitors/{monitor_id}"),
    "delete_monitor": ("DELETE", "/v1/monitors/{monitor_id}"),
    "run_monitor": ("POST", "/v1/monitors/{monitor_id}/run"),
    "test_monitor": ("POST", "/v1/monitors/{monitor_id}/test"),
    "list_monitor_runs": ("GET", "/v1/monitors/{monitor_id}/runs"),
    "get_monitor_run": ("GET", "/v1/monitors/{monitor_id}/runs/{run_id}"),
    "list_monitor_items": ("GET", "/v1/monitors/{monitor_id}/items"),
    "detect_technologies": ("POST", "/v1/technographics"),
    "create_dataset": ("POST", "/v1/datasets"),
    "get_dataset": ("GET", "/v1/datasets/{dataset_id}"),
    "list_dataset_rows": ("GET", "/v1/datasets/{dataset_id}/rows"),
    "enrich_person": ("POST", "/v1/enrich"),
    "get_credits": ("GET", "/v1/account/credits"),
    "get_account_usage": ("GET", "/v1/account/usage"),
    "get_account_profile": ("GET", "/v1/account/profile"),
}


class PloidNode(WorkflowNode):
    integration_type = "automation-ploid"
    connection_evidence = ConnectionEvidence(noun="Ploid account", identity_operation="get_account_profile")

    @classmethod
    def get_config_model(cls):
        return PloidConfig

    @staticmethod
    def _guard_credential_type(config_data):
        credential = config_data.get("credentials") if isinstance(config_data, dict) else None
        if isinstance(credential, dict) and credential.get("credential_type", "ploid_api_key") != "ploid_api_key":
            raise ValueError("Attach a Ploid API key credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._guard_credential_type(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._guard_credential_type(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Ploid API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        payload = config.model_dump(exclude_none=True, exclude={"operation", "idempotency_key"})
        for key in ("monitor_id", "run_id", "dataset_id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(payload.pop(key), safe=""))
        headers = {"x-api-key": self.config.credentials.api_key, "Accept": "application/json"}
        if getattr(config, "idempotency_key", None):
            headers["Idempotency-Key"] = config.idempotency_key
        kwargs = {"params": payload} if method == "GET" else ({"json": payload} if payload else {})
        async with guarded_async_client(timeout=120, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers=headers, **kwargs)
        if not 200 <= response.status_code < 300:
            # Keep provider rejection text for connect, while redacting echoed secrets.
            detail = response.text[:2000].replace(self.config.credentials.api_key, "[redacted]")
            raise ValueError(f"Ploid HTTP {response.status_code}: {detail}")
        if response.status_code == 204 or (config.operation == "delete_monitor" and not response.content):
            return {"http_status": response.status_code}
        if "application/json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("Ploid returned a non-JSON response")
        body = response.json()
        if not isinstance(body, dict) or "error" in body or "errors" in body:
            raise ValueError("Ploid returned an unexpected response or error envelope")
        return body
