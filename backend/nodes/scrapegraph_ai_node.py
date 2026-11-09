"""ScrapeGraphAI v2 automation, pinned to the provider's published HTTP contract.

Each operation sends exactly one request. Crawls are asynchronous: callers poll
get_crawl and page through list_crawl_pages explicitly; writes are never retried.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://v2-api.scrapegraphai.com"
FAMILY = "scrapegraph_ai_api_key"
UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
ResourceID = Annotated[str, Field(pattern=UUID_PATTERN, description="UUID returned by ScrapeGraphAI.")]
Format = Literal["markdown", "html", "links", "images", "summary", "json", "branding", "screenshot"]
Mode = Literal["normal", "reader", "prune"]


class ScrapegraphAIAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Scrapegraph AI API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.scrapegraphai.com/",
            "x-credential-instructions": "Paste your ScrapeGraphAI API key from the dashboard. NoClick sends it in the SGAI-APIKEY header to the v2 API. Connecting reads the email associated with your key.",
        })
    credential_type: Literal["scrapegraph_ai_api_key"] = Field("scrapegraph_ai_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def urls(cls, value, info):
        if info.field_name in {"url", "webhook_url"} and value is not None:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Use an HTTP or HTTPS URL without embedded credentials")
        return value


class _Fetch(_Input):
    fetch_mode: Literal["auto", "fast", "js"] = Field("auto", description="auto chooses the provider; js renders JavaScript.")
    timeout_ms: int = Field(60000, ge=1000, le=60000)
    wait_ms: int = Field(0, ge=0, le=30000)


class _SessionFetch(_Fetch):
    session_id: str | None = Field(None, min_length=1, max_length=128, description="Optional SGAI-Session-Id groups requests in history.")


class _Formats(_Fetch):
    formats: list[Format] = Field(default_factory=lambda: ["markdown"], min_length=1, max_length=8, description="Requested output types. Screenshot output is a provider URL.")


class ScrapeURL(_SessionFetch):
    """Scrape one URL into selected formats. Format errors remain in the output."""
    operation: Literal["scrape_url"] = "scrape_url"
    url: str = Field(..., min_length=1, max_length=8000)
    formats: list[Format] = Field(default_factory=lambda: ["markdown"], min_length=1, max_length=8)


class Extract(_SessionFetch):
    """Extract structured JSON from exactly one URL, HTML or Markdown source."""
    operation: Literal["extract"] = "extract"
    prompt: str = Field(..., min_length=1, max_length=10000)
    url: str | None = Field(None, min_length=1, max_length=8000)
    html: str | None = Field(None, min_length=1, max_length=1000000, json_schema_extra={"ui:widget": "textarea"})
    markdown: str | None = Field(None, min_length=1, max_length=1000000, json_schema_extra={"ui:widget": "textarea"})
    mode: Mode = "normal"
    json_schema: str | None = Field(None, description="Optional JSON Schema object as JSON text.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @field_validator("json_schema")
    @classmethod
    def schema_object(cls, value):
        if value is not None:
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError):
                raise ValueError("Provide a JSON Schema object") from None
            if not isinstance(parsed, dict):
                raise ValueError("Provide a JSON Schema object")
        return value

    @model_validator(mode="after")
    def source(self):
        if sum(getattr(self, k) is not None for k in ("url", "html", "markdown")) != 1:
            raise ValueError("Supply exactly one URL, HTML or Markdown source")
        return self


class Search(_SessionFetch):
    """Search and scrape a bounded number of results."""
    operation: Literal["search"] = "search"
    query: str = Field(..., min_length=1, max_length=500)
    num_results: int = Field(3, ge=1, le=20)
    format: Literal["html", "markdown"] = "markdown"
    mode: Mode = "prune"
    location_geo_code: str | None = Field(None, max_length=10)
    time_range: Literal["past_hour", "past_24_hours", "past_week", "past_month", "past_year"] | None = None


class ListHistory(_Input):
    """Read one page of this account's request history."""
    operation: Literal["list_history"] = "list_history"
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)
    service: Literal["scrape", "extract", "search", "monitor", "crawl"] | None = None
    session_id: str | None = Field(None, min_length=1, max_length=128)


class GetHistory(_Input):
    """Read a single request, including its stored parameters and result."""
    operation: Literal["get_history"] = "get_history"
    history_id: ResourceID


class CreateMonitor(_Formats):
    """Create a recurring scrape. The provider bills scheduled runs."""
    operation: Literal["create_monitor"] = "create_monitor"
    url: str = Field(..., min_length=1, max_length=8000)
    interval: str = Field(..., min_length=1, max_length=100, description="5-field cron expression, for example 0 */6 * * *.")
    name: str = Field(..., min_length=1, max_length=200)
    webhook_url: str | None = Field(None, min_length=1, max_length=8000, description="Optional destination for provider change notifications.")


class ListMonitors(_Input):
    """List this account's monitors (the API returns an unpaginated array)."""
    operation: Literal["list_monitors"] = "list_monitors"


class _Monitor(_Input):
    monitor_id: ResourceID


class GetMonitor(_Monitor):
    """Read one monitor and its schedule configuration."""
    operation: Literal["get_monitor"] = "get_monitor"


class UpdateMonitor(_Monitor):
    """Change a monitor name, interval, output formats or notification destination."""
    operation: Literal["update_monitor"] = "update_monitor"
    name: str | None = Field(None, max_length=200)
    interval: str | None = Field(None, min_length=1, max_length=100)
    formats: list[Format] | None = Field(None, min_length=1, max_length=8)
    webhook_url: str | None = Field(None, min_length=1, max_length=8000)
    clear_webhook: bool = Field(False, description="Send webhookUrl: null to remove the destination.")

    @model_validator(mode="after")
    def changes(self):
        if self.clear_webhook and self.webhook_url is not None:
            raise ValueError("Choose a webhook URL or clear it")
        if not self.clear_webhook and all(getattr(self, k) is None for k in ("name", "interval", "formats", "webhook_url")):
            raise ValueError("Provide at least one monitor change")
        return self


class DeleteMonitor(_Monitor):
    """Delete a monitor and stop its future scheduled runs."""
    operation: Literal["delete_monitor"] = "delete_monitor"


class GetMonitorActivity(_Monitor):
    """Read one page of monitor ticks; pass nextCursor to the next call."""
    operation: Literal["get_monitor_activity"] = "get_monitor_activity"
    cursor: str | None = Field(None, description="ISO 8601 timestamp returned as nextCursor.")
    limit: int = Field(20, ge=1, le=100)

    @field_validator("cursor")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise ValueError("Use an ISO 8601 timestamp with a timezone") from None
        return value


class PauseMonitor(_Monitor):
    """Pause future monitor ticks."""
    operation: Literal["pause_monitor"] = "pause_monitor"


class ResumeMonitor(_Monitor):
    """Resume a paused monitor's scheduled ticks."""
    operation: Literal["resume_monitor"] = "resume_monitor"


class StartCrawl(_Formats):
    """Start a bounded asynchronous crawl; poll get_crawl for progress."""
    operation: Literal["start_crawl"] = "start_crawl"
    url: str = Field(..., min_length=1, max_length=8000)
    session_id: str | None = Field(None, min_length=1, max_length=128)
    max_depth: int | None = Field(2, ge=0, description="Null allows unlimited depth within the page limit.")
    max_pages: int = Field(50, ge=1, le=1000)
    max_links_per_page: int = Field(10, ge=1)
    allow_external: bool = False
    include_patterns: list[str] | None = None
    exclude_patterns: list[str] | None = None


class _Crawl(_Input):
    crawl_id: ResourceID


class GetCrawl(_Crawl):
    """Read crawl status and the provider's current page summary."""
    operation: Literal["get_crawl"] = "get_crawl"


class DeleteCrawl(_Crawl):
    """Delete the selected crawl."""
    operation: Literal["delete_crawl"] = "delete_crawl"


class ListCrawlPages(_Crawl):
    """Read one page of crawl results using the provider's numeric cursor."""
    operation: Literal["list_crawl_pages"] = "list_crawl_pages"
    cursor: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=100)


class StopCrawl(_Crawl):
    """Request a running crawl to stop; this is an acknowledgement."""
    operation: Literal["stop_crawl"] = "stop_crawl"


class ResumeCrawl(_Crawl):
    """Request a paused crawl to resume; poll get_crawl for progress."""
    operation: Literal["resume_crawl"] = "resume_crawl"


class GetCredits(_Input):
    """Read remaining and used credits and crawl/monitor job limits."""
    operation: Literal["get_credits"] = "get_credits"


class GetAccount(_Input):
    """Validate the key and read its account email."""
    operation: Literal["get_account"] = "get_account"


ScrapegraphAIConfig = Annotated[Union[
    ScrapeURL, Extract, Search, ListHistory, GetHistory, CreateMonitor, ListMonitors,
    GetMonitor, UpdateMonitor, DeleteMonitor, GetMonitorActivity, PauseMonitor,
    ResumeMonitor, StartCrawl, GetCrawl, DeleteCrawl, ListCrawlPages, StopCrawl,
    ResumeCrawl, GetCredits, GetAccount,
], Field(discriminator="operation")]


class ScrapegraphAIFullConfig(NodeConfig[ScrapegraphAIConfig, ScrapegraphAIAPIKeyCredential]):
    pass


# (method, route, path ID field); one operation always maps to one endpoint.
ROUTES = {
    "scrape_url": ("POST", "/api/scrape", None),
    "extract": ("POST", "/api/extract", None),
    "search": ("POST", "/api/search", None),
    "list_history": ("GET", "/api/history", None),
    "get_history": ("GET", "/api/history/{id}", "history_id"),
    "create_monitor": ("POST", "/api/monitor", None),
    "list_monitors": ("GET", "/api/monitor", None),
    "get_monitor": ("GET", "/api/monitor/{id}", "monitor_id"),
    "update_monitor": ("PATCH", "/api/monitor/{id}", "monitor_id"),
    "delete_monitor": ("DELETE", "/api/monitor/{id}", "monitor_id"),
    "get_monitor_activity": ("GET", "/api/monitor/{id}/activity", "monitor_id"),
    "pause_monitor": ("POST", "/api/monitor/{id}/pause", "monitor_id"),
    "resume_monitor": ("POST", "/api/monitor/{id}/resume", "monitor_id"),
    "start_crawl": ("POST", "/api/crawl", None),
    "get_crawl": ("GET", "/api/crawl/{id}", "crawl_id"),
    "delete_crawl": ("DELETE", "/api/crawl/{id}", "crawl_id"),
    "list_crawl_pages": ("GET", "/api/crawl/{id}/pages", "crawl_id"),
    "stop_crawl": ("POST", "/api/crawl/{id}/stop", "crawl_id"),
    "resume_crawl": ("POST", "/api/crawl/{id}/resume", "crawl_id"),
    "get_credits": ("GET", "/api/credits", None),
    "get_account": ("GET", "/api/validate", None),
}
WIRE_NAMES = {"num_results": "numResults", "location_geo_code": "locationGeoCode", "time_range": "timeRange",
    "session_id": "sessionId", "webhook_url": "webhookUrl", "max_depth": "maxDepth", "max_pages": "maxPages",
    "max_links_per_page": "maxLinksPerPage", "allow_external": "allowExternal",
    "include_patterns": "includePatterns", "exclude_patterns": "excludePatterns"}


class ScrapegraphAINode(WorkflowNode):
    integration_type = "automation-scrapegraph-ai"
    connection_evidence = ConnectionEvidence(noun="ScrapeGraphAI account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return ScrapegraphAIFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            return {"status": "error", "error": "Attach a ScrapeGraphAI API key"}
        op = self.config.config
        method, route, id_field = ROUTES[op.operation]
        if id_field:
            route = route.replace("{id}", quote(getattr(op, id_field), safe=""))
        headers = {"SGAI-APIKEY": credential.api_key, "Accept": "application/json"}
        fields = op.model_dump(exclude_none=True, exclude={"operation"})
        if id_field:
            fields.pop(id_field)
        if op.operation in {"scrape_url", "extract", "search", "start_crawl"}:
            session = fields.pop("session_id", None)
            if session:
                headers["SGAI-Session-Id"] = session
        if isinstance(op, _Fetch):
            fields["fetchConfig"] = {"mode": fields.pop("fetch_mode"), "timeout": fields.pop("timeout_ms"), "wait": fields.pop("wait_ms")}
        if "formats" in fields:
            fields["formats"] = [{"type": value} for value in fields["formats"]]
        if isinstance(op, Extract):
            schema = fields.pop("json_schema", None)
            if schema is not None:
                fields["schema"] = json.loads(schema)
        if isinstance(op, StartCrawl) and op.max_depth is None:
            fields["max_depth"] = None
        if isinstance(op, UpdateMonitor):
            clear = fields.pop("clear_webhook")
            if clear:
                fields["webhook_url"] = None
        fields = {WIRE_NAMES.get(k, k): v for k, v in fields.items()}
        kwargs = {"params": fields} if method == "GET" else {"json": fields} if fields else {}
        try:
            async with guarded_async_client(timeout=330, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route, headers=headers, **kwargs)
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if len(response.content) > 20000000 or content_type != "application/json":
                return {"status": "error", "http_status": response.status_code, "error": "Expected bounded JSON from ScrapeGraphAI"}
            data = response.json()
            if not 200 <= response.status_code < 300 or isinstance(data, dict) and "error" in data and "service" not in data:
                error = data.get("error") if isinstance(data, dict) else None
                message = error.get("message") if isinstance(error, dict) else None
                message = message if isinstance(message, str) else "ScrapeGraphAI request failed"
                return {"status": "error", "http_status": response.status_code, "error": message.replace(credential.api_key, "[redacted]")}
            if op.operation == "list_monitors":
                if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                    raise ValueError()
            elif not isinstance(data, dict):
                raise ValueError()
            if op.operation == "get_account":
                if not isinstance(data.get("email"), str) or "@" not in data["email"]:
                    raise ValueError()
                return {"status": "success", "email": data["email"], "data": data, "http_status": response.status_code}
            required = {
                "scrape_url": ("results", "metadata"), "extract": ("raw", "json", "usage", "metadata"),
                "search": ("results", "metadata"), "list_history": ("data", "pagination"),
                "get_history": ("id", "service", "status"), "get_monitor_activity": ("ticks", "nextCursor"),
                "list_crawl_pages": ("data", "pagination"), "get_credits": ("remaining", "used", "plan", "jobs"),
            }.get(op.operation)
            if required is None and "monitor" in op.operation and op.operation not in {"list_monitors", "delete_monitor"}:
                required = ("cronId", "scheduleId", "interval", "status", "config")
            if op.operation in {"get_crawl", "start_crawl"}:
                required = ("id", "status", "total", "finished", "pages")
            if required and not all(k in data for k in required):
                raise ValueError()
            if op.operation in {"delete_monitor", "delete_crawl", "stop_crawl", "resume_crawl"} and data.get("ok") is not True:
                raise ValueError()
            return {"status": "success", "data": data, "http_status": response.status_code}
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "error": "ScrapeGraphAI response was not confirmed; inspect writes before retrying"}
