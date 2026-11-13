"""Context.dev research and website monitoring through the published v1 API.

Each operation makes one fixed API call; pagination and queued runs remain explicit.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.context.dev/v1"


class ContextDevAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Context Dev API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://context.dev/dashboard/api-keys",
            "x-credential-instructions": "Paste a secret API key from Context.dev → Dashboard → API keys. Use a full-access key or enable the permissions for your selected operations, including logs:read for the connection usage read. Requests that research websites or run monitors can consume credits.",
        },
    )
    credential_type: Literal["context_dev_api_key"] = Field("context_dev_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, repr=False, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API key as text")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_ids(cls, value, info):
        if info.field_name in {"monitor_id", "run_id"} and not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
            raise ValueError("Use a single Context.dev resource ID")
        return value


class _URLInput(_Input):
    url: str = Field(..., min_length=1, description="Public HTTP or HTTPS URL.")

    @field_validator("url")
    @classmethod
    def public_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use an HTTP or HTTPS URL without embedded credentials")
        return value


class ScrapeWeb(_URLInput):
    """Read a page as Markdown; inspect the per-format code in the response."""
    operation: Literal["scrape_web"] = Field("scrape_web", json_schema_extra={"ui:hidden": True})
    max_age_ms: int = Field(259200000, ge=0, le=31536000000, description="Cache age in milliseconds; 0 requests a fresh page.")


class SearchWeb(_Input):
    """Search the web and return result URLs and snippets."""
    operation: Literal["search_web"] = Field("search_web", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=500)
    num_results: int = Field(10, ge=1, le=100)
    freshness: Literal["last_24_hours", "last_week", "last_month", "last_year"] | None = None


class MapURLs(_Input):
    """Discover URLs for a domain in one bounded response."""
    operation: Literal["map_urls"] = Field("map_urls", json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., min_length=3, description="Domain such as stripe.com.")
    max_links: int = Field(1000, ge=1, le=100000)
    include_subdomains: bool = False
    search: str | None = Field(None, min_length=2, max_length=200)


class CrawlWebsite(_URLInput):
    """Crawl a bounded number of pages; partial results remain visible."""
    operation: Literal["crawl_website"] = Field("crawl_website", json_schema_extra={"ui:hidden": True})
    max_pages: int = Field(10, ge=1, le=500)
    max_depth: int = Field(1, ge=0)
    use_main_content_only: bool = True


class AnswerResearch(_Input):
    """Research a task with source URLs and an optional example answer shape."""
    operation: Literal["answer_research"] = Field("answer_research", json_schema_extra={"ui:hidden": True})
    task: str = Field(..., min_length=1, max_length=2000)
    mode: Literal["fast", "ultra"] = "fast"
    json_format: dict | None = Field(None, description="Example answer object, not JSON Schema.")


class SearchNews(_Input):
    """Search news by a natural-language query with explicit cursor pagination."""
    operation: Literal["search_news"] = Field("search_news", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=2, max_length=1000)
    limit: int = Field(10, ge=1, le=100)
    cursor: str | None = Field(None, max_length=300)


class RetrieveBrand(_Input):
    """Retrieve company branding by domain."""
    operation: Literal["retrieve_brand"] = Field("retrieve_brand", json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., min_length=3)


class SearchBrands(_Input):
    """Find brands by a name or domain prefix."""
    operation: Literal["search_brands"] = Field("search_brands", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=100)


class EnrichPerson(_Input):
    """Enrich a person identified by a business email; free emails are rejected by Context.dev."""
    operation: Literal["enrich_person"] = Field("enrich_person", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class GetUsage(_Input):
    """Read the connected organization's credit balance and current usage."""
    operation: Literal["get_usage"] = Field("get_usage", json_schema_extra={"ui:hidden": True})


class GetUsageHistory(_Input):
    """Read usage buckets; omitted dates use the provider's documented window."""
    operation: Literal["get_usage_history"] = Field("get_usage_history", json_schema_extra={"ui:hidden": True})
    interval: Literal["hour", "day", "month"] = "day"
    group_by: Literal["path", "key_id", "status_code"] | None = None
    from_time: str | None = Field(None, description="Inclusive ISO 8601 start timestamp.")
    to_time: str | None = Field(None, description="ISO 8601 end timestamp.")

    @field_validator("from_time", "to_time")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Include the timestamp's timezone")
        return value

    @model_validator(mode="after")
    def window(self):
        if self.from_time and self.to_time:
            start = datetime.fromisoformat(self.from_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(self.to_time.replace("Z", "+00:00"))
            if not 0 < (end - start).total_seconds() <= (7 if self.interval == "hour" else 366) * 86400:
                raise ValueError("Use an increasing window of at most 7 days for hour, or 366 days for day/month")
        return self


class _Page(_Input):
    limit: int = Field(25, ge=1, le=100)
    cursor: str | None = Field(None, description="Opaque cursor returned by the previous response; keep all other filters the same.")


class ListMonitors(_Page):
    """List account monitors with optional search and lifecycle filters."""
    operation: Literal["list_monitors"] = Field("list_monitors", json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, max_length=200)
    status: Literal["active", "paused", "failed"] | None = None


class _Monitor(_Input):
    monitor_id: str = Field(..., min_length=1, max_length=200)


class GetMonitor(_Monitor):
    """Read one monitor's configuration and state."""
    operation: Literal["get_monitor"] = Field("get_monitor", json_schema_extra={"ui:hidden": True})


class CreateMonitor(_URLInput):
    """Create a page monitor with a daily schedule; Context.dev queues its baseline run."""
    operation: Literal["create_monitor"] = Field("create_monitor", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=200)
    instructions: str | None = Field(None, min_length=1, max_length=2000, description="Optional semantic change goal; omitted uses exact detection.")
    frequency_days: int = Field(1, ge=1, le=365, description="Run every this many days.")


class UpdateMonitor(_Monitor):
    """Rename, pause, or resume a monitor without replacing its target."""
    operation: Literal["update_monitor"] = Field("update_monitor", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=200)
    status: Literal["active", "paused"] | None = None

    @model_validator(mode="after")
    def change(self):
        if self.name is None and self.status is None:
            raise ValueError("Provide a name or status to change")
        return self


class DeleteMonitor(_Monitor):
    """Delete a monitor and stop future runs and webhook retries."""
    operation: Literal["delete_monitor"] = Field("delete_monitor", json_schema_extra={"ui:hidden": True})


class RunMonitor(_Monitor):
    """Queue one monitor run; an accepted request is not a completed run."""
    operation: Literal["run_monitor"] = Field("run_monitor", json_schema_extra={"ui:hidden": True})


class ListMonitorRuns(_Monitor, _Page):
    """Read one page of runs for a monitor."""
    operation: Literal["list_monitor_runs"] = Field("list_monitor_runs", json_schema_extra={"ui:hidden": True})
    status: Literal["queued", "running", "completed", "failed", "skipped"] | None = None


class GetMonitorRun(_Monitor):
    """Read status, timing and results for a selected monitor run."""
    operation: Literal["get_monitor_run"] = Field("get_monitor_run", json_schema_extra={"ui:hidden": True})
    run_id: str = Field(..., min_length=1, max_length=200)


class ListMonitorChanges(_Monitor, _Page):
    """Read one page of detected changes for a monitor."""
    operation: Literal["list_monitor_changes"] = Field("list_monitor_changes", json_schema_extra={"ui:hidden": True})
    tag: str | None = None


# Context.dev's own MCP server: agents get its tools through a person's Context.dev sign-in.
ContextDevMcpCredential = mcp_credential("context_dev", "https://mcp.context.dev/mcp", app="Context.dev")
ContextDevCredential = Union[ContextDevAPIKeyCredential, ContextDevMcpCredential]


ContextDevConfig = Annotated[Union[
    ScrapeWeb, SearchWeb, MapURLs, CrawlWebsite, AnswerResearch, SearchNews,
    RetrieveBrand, SearchBrands, EnrichPerson, GetUsage, GetUsageHistory,
    ListMonitors, GetMonitor, CreateMonitor, UpdateMonitor, DeleteMonitor,
    RunMonitor, ListMonitorRuns, GetMonitorRun, ListMonitorChanges,
], Field(discriminator="operation")]


class ContextDevFullConfig(NodeConfig[ContextDevConfig, ContextDevCredential]):
    pass


# Fixed routes prevent user input or provider-returned pagination URLs changing the destination.
ROUTES = {
    "scrape_web": ("POST", "/web/scrape"),
    "search_web": ("POST", "/web/search"),
    "map_urls": ("GET", "/web/urls"),
    "crawl_website": ("POST", "/web/crawl"),
    "answer_research": ("POST", "/web/answers"),
    "search_news": ("POST", "/news/search"),
    "retrieve_brand": ("POST", "/brand/retrieve"),
    "search_brands": ("GET", "/brand/search"),
    "enrich_person": ("POST", "/people/enrich"),
    "get_usage": ("GET", "/org/usage"),
    "get_usage_history": ("GET", "/org/usage/history"),
    "list_monitors": ("GET", "/monitors"),
    "get_monitor": ("GET", "/monitors/{monitor_id}"),
    "create_monitor": ("POST", "/monitors"),
    "update_monitor": ("PATCH", "/monitors/{monitor_id}"),
    "delete_monitor": ("DELETE", "/monitors/{monitor_id}"),
    "run_monitor": ("POST", "/monitors/{monitor_id}/run"),
    "list_monitor_runs": ("GET", "/monitors/{monitor_id}/runs"),
    "get_monitor_run": ("GET", "/monitors/{monitor_id}/runs/{run_id}"),
    "list_monitor_changes": ("GET", "/monitors/{monitor_id}/changes"),
}
ALIASES = {"max_age_ms": "maxAgeMs", "num_results": "numResults", "max_links": "maxLinks",
           "include_subdomains": "includeSubdomains", "max_pages": "maxPages", "max_depth": "maxDepth",
           "use_main_content_only": "useMainContentOnly", "from_time": "from", "to_time": "to"}


def request_parts(config):
    method, route = ROUTES[config.operation]
    for name in ("monitor_id", "run_id"):
        if "{" + name + "}" in route:
            route = route.replace("{" + name + "}", quote(getattr(config, name), safe=""))
    payload = {ALIASES.get(k, k): v for k, v in config.model_dump(exclude_none=True).items()
               if k not in {"operation", "monitor_id", "run_id"}}
    if config.operation == "scrape_web":
        payload["formats"] = {"markdown": True}
    elif config.operation == "retrieve_brand":
        payload["type"] = "by_domain"
    elif config.operation == "search_news":
        payload["searchBy"] = {"type": "natural_language", "query": payload.pop("query")}
    elif config.operation == "create_monitor":
        payload["target"] = {"type": "page", "url": payload.pop("url")}
        if "instructions" in payload:
            payload["target"]["instructions"] = payload.pop("instructions")
        payload["schedule"] = {"type": "interval", "frequency": payload.pop("frequency_days"), "unit": "days"}
    return method, route, payload


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class ContextDevNode(WorkflowNode):
    integration_type = "automation-context-dev"
    credential_provider_labels = {"context_dev": "Context.dev Account"}
    connection_evidence = ConnectionEvidence(noun="organization credit usage", operation="get_usage")

    @classmethod
    def get_config_model(cls):
        return ContextDevFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Context Dev API key")
        key = self.config.credentials.api_key
        config = self.config.config
        method, route, payload = request_parts(config)
        kwargs = {"params": {k: str(v).lower() if isinstance(v, bool) else v for k, v in payload.items()}} if method == "GET" else ({"json": payload} if payload else {})
        async with guarded_async_client(timeout=180, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + route,
                headers={"Authorization": "Bearer " + key, "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection for connection evidence; never reflect a key.
            try:
                error = response.json()
            except ValueError:
                error = "Context.dev returned a non-JSON error"
            output = {"status": "error", "success": False, "http_status": response.status_code, "status_code": response.status_code,
                      "error": _redact(error, key)}
        else:
            if len(response.content) > 20_000_000:
                raise ValueError("Context.dev response exceeds the 20 MB limit")
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Context.dev returned invalid JSON") from None
            if not isinstance(data, dict):
                raise ValueError("Context.dev returned an unexpected JSON shape")
            output = {"status": "success", "http_status": response.status_code, "data": _redact(data, key)}
        await self.emit(output)
        return output
