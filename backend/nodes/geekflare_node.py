"""Geekflare API v1: fixed API-key routes for web data and crawl jobs.

Contract: https://api.geekflare.com/auth/swagger-ui-json (1.0.0).
Authentication and origin: https://docs.geekflare.com/intro.
Each operation issues one request; job creation is never retried automatically.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.geekflare.com"


class GeekflareAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Geekflare API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://dash.geekflare.com/",
            "x-credential-instructions": "Copy your API key from the Geekflare dashboard. NoClick sends it as x-api-key to api.geekflare.com. Connecting reads your crawl jobs without starting a crawl."})
    credential_type: Literal["geekflare_api_key"] = Field("geekflare_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _URL(_Input):
    url: str = Field(..., title="Target URL", description="Public HTTP or HTTPS URL to inspect.", max_length=8192)

    @field_validator("url")
    @classmethod
    def target(cls, value):
        p = urlsplit(value)
        if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password or any(ord(c) < 33 for c in value):
            raise ValueError("Use a complete HTTP or HTTPS URL without embedded credentials")
        return value


class _Render(_URL):
    device: Literal["desktop", "mobile"] = Field("desktop", title="Device")
    blockAds: bool = Field(True, title="Block Ads")
    renderJS: bool = Field(True, title="Render JavaScript")


class _Job(_Input):
    id: str = Field(..., title="Job ID", min_length=1, max_length=256)

    @field_validator("id")
    @classmethod
    def job(cls, value):
        if value in {".", ".."} or any(not (c.isascii() and (c.isalnum() or c in "_-")) for c in value):
            raise ValueError("Paste a single Geekflare job ID")
        return value


class _Page(_Input):
    offset: int = Field(0, title="Offset", ge=0)
    limit: int = Field(20, title="Page Size", ge=1, le=100)


class _Discover(_URL):
    maxDepth: int = Field(3, title="Maximum Depth", ge=0, le=20)
    maxPages: int = Field(100, title="Maximum Pages", ge=1, le=500)
    includeExternal: bool = Field(False, title="Include External Links")
    allowPatterns: list[str] | None = Field(None, title="Allowed URL Patterns")
    denyPatterns: list[str] | None = Field(None, title="Denied URL Patterns")
    timeout: int = Field(99, title="Timeout (Seconds)", ge=1, le=300)


class ScrapeMetadata(_Render):
    operation: Literal["scrape_metadata"] = Field("scrape_metadata", title="Scrape Metadata", json_schema_extra={"ui:hidden": True})
    format: Literal["json", "markdown"] = Field("json", title="Output Format")


class ScrapeWebpage(_Render):
    operation: Literal["scrape_webpage"] = Field("scrape_webpage", title="Scrape Webpage", json_schema_extra={"ui:hidden": True})
    format: list[Literal["html", "markdown", "json", "markdown-llm", "html-llm", "text", "text-llm"]] = Field(default_factory=lambda: ["markdown"], title="Output Formats")


class LookupDNS(_URL):
    operation: Literal["lookup_dns"] = Field("lookup_dns", title="Look Up DNS Records", json_schema_extra={"ui:hidden": True})
    types: list[Literal["A", "AAAA", "CNAME", "MX", "CAA", "NS", "SOA", "SRV", "TXT"]] | None = Field(None, title="Record Types")


class CheckSite(_URL):
    operation: Literal["check_site"] = Field("check_site", title="Check Site Status", json_schema_extra={"ui:hidden": True})
    followRedirect: bool = Field(False, title="Follow Redirects")


class CheckRedirects(_URL):
    operation: Literal["check_redirects"] = Field("check_redirects", title="Check Redirect Chain", json_schema_extra={"ui:hidden": True})


class CheckBrokenLinks(_URL):
    operation: Literal["check_broken_links"] = Field("check_broken_links", title="Check Broken Links", json_schema_extra={"ui:hidden": True})
    followRedirect: bool = Field(False, title="Follow Redirects")


class ScanTLS(_URL):
    operation: Literal["scan_tls"] = Field("scan_tls", title="Scan TLS Configuration", json_schema_extra={"ui:hidden": True})


class MeasureTTFB(_URL):
    operation: Literal["measure_ttfb"] = Field("measure_ttfb", title="Measure Time to First Byte", json_schema_extra={"ui:hidden": True})
    followRedirect: bool = Field(False, title="Follow Redirects")


class MeasureLoadTime(_URL):
    operation: Literal["measure_load_time"] = Field("measure_load_time", title="Measure Page Load Time", json_schema_extra={"ui:hidden": True})
    followRedirect: bool = Field(False, title="Follow Redirects")


class GetHTTPHeaders(_URL):
    operation: Literal["get_http_headers"] = Field("get_http_headers", title="Get HTTP Headers", json_schema_extra={"ui:hidden": True})
    followRedirect: bool = Field(False, title="Follow Redirects")


class CheckDNSSEC(_URL):
    operation: Literal["check_dnssec"] = Field("check_dnssec", title="Check DNSSEC", json_schema_extra={"ui:hidden": True})


class PingHost(_URL):
    operation: Literal["ping_host"] = Field("ping_host", title="Ping Host", json_schema_extra={"ui:hidden": True})


class AuditLighthouse(_URL):
    operation: Literal["audit_lighthouse"] = Field("audit_lighthouse", title="Run Lighthouse Audit", json_schema_extra={"ui:hidden": True})
    device: Literal["desktop", "mobile"] = Field("desktop", title="Device")
    followRedirect: bool = Field(False, title="Follow Redirects")
    parameters: list[str] | None = Field(None, title="Extra Lighthouse Parameters")


class SearchWeb(_Input):
    operation: Literal["search_web"] = Field("search_web", title="Search Web or News", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., title="Search Query", min_length=1, max_length=2048)
    limit: int = Field(10, title="Result Limit", ge=1, le=100)
    source: Literal["web", "news", "images"] = Field("web", title="Search Source")
    format: Literal["json", "markdown", "html"] = Field("json", title="Output Format")
    scrape: bool = Field(False, title="Scrape Result Pages")
    groundedAnswer: bool = Field(False, title="Generate Grounded Answer")


class GetBrand(_URL):
    operation: Literal["get_brand"] = Field("get_brand", title="Get Brand Data", json_schema_extra={"ui:hidden": True})
    refresh: bool = Field(False, title="Refresh Cached Brand Data")
    mode: Literal["standard", "enriched"] = Field("standard", title="Brand Detail Level")


class DiscoverLinks(_Discover):
    operation: Literal["discover_links"] = Field("discover_links", title="Discover Links", json_schema_extra={"ui:hidden": True})


class StartDiscovery(_Discover):
    operation: Literal["start_discovery"] = Field("start_discovery", title="Start Discovery Job", json_schema_extra={"ui:hidden": True})


class GetDiscovery(_Job):
    operation: Literal["get_discovery"] = Field("get_discovery", title="Get Discovery Job", json_schema_extra={"ui:hidden": True})


class StartCrawl(_Discover):
    operation: Literal["start_crawl"] = Field("start_crawl", title="Start Crawl Job", json_schema_extra={"ui:hidden": True})
    format: Literal["markdown", "html"] = Field("markdown", title="Page Output Format")
    renderJS: bool = Field(True, title="Render JavaScript")
    blockAds: bool = Field(True, title="Block Ads")


class ListCrawls(_Page):
    operation: Literal["list_crawls"] = Field("list_crawls", title="List Crawl Jobs", json_schema_extra={"ui:hidden": True})
    status: Literal["queued", "running", "completed", "failed", "cancelled"] | None = Field(None, title="Job Status")


class GetCrawl(_Job, _Page):
    operation: Literal["get_crawl"] = Field("get_crawl", title="Get Crawl Job and Pages", json_schema_extra={"ui:hidden": True})


class CancelCrawl(_Job):
    operation: Literal["cancel_crawl"] = Field("cancel_crawl", title="Cancel Crawl Job", json_schema_extra={"ui:hidden": True})


GeekflareOperation = Annotated[Union[
    ScrapeMetadata, ScrapeWebpage, LookupDNS, CheckSite, CheckRedirects, CheckBrokenLinks, ScanTLS, MeasureTTFB, MeasureLoadTime, GetHTTPHeaders, CheckDNSSEC, PingHost, AuditLighthouse, SearchWeb, GetBrand, DiscoverLinks, StartDiscovery, GetDiscovery, StartCrawl, ListCrawls, GetCrawl, CancelCrawl
], Field(discriminator="operation")]


class GeekflareFullConfig(NodeConfig[GeekflareOperation, GeekflareAPIKeyCredential]):
    pass


ROUTES = {
    "scrape_metadata": ("POST", "/metascraping"),
    "scrape_webpage": ("POST", "/webscraping"),
    "lookup_dns": ("POST", "/dnsrecord"),
    "check_site": ("POST", "/up"),
    "check_redirects": ("POST", "/redirectcheck"),
    "check_broken_links": ("POST", "/brokenlink"),
    "scan_tls": ("POST", "/tlsscan"),
    "measure_ttfb": ("POST", "/ttfb"),
    "measure_load_time": ("POST", "/loadtime"),
    "get_http_headers": ("POST", "/httpheader"),
    "check_dnssec": ("POST", "/dnssec"),
    "ping_host": ("POST", "/ping"),
    "audit_lighthouse": ("POST", "/lighthouse"),
    "search_web": ("POST", "/search"),
    "get_brand": ("POST", "/brand"),
    "discover_links": ("POST", "/discovery"),
    "start_discovery": ("POST", "/discovery/async"),
    "get_discovery": ("GET", "/discovery/async/{id}"),
    "start_crawl": ("POST", "/crawl"),
    "list_crawls": ("GET", "/crawl"),
    "get_crawl": ("GET", "/crawl/{id}"),
    "cancel_crawl": ("POST", "/crawl/{id}/cancel"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items() if k not in {"webhookSecret", "api_key", "apiKey"}}
    return value


class GeekflareNode(WorkflowNode):
    integration_type = "automation-geekflare"
    connection_evidence = ConnectionEvidence(operation="list_crawls", noun="crawl jobs")

    @classmethod
    def get_config_model(cls):
        return GeekflareFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, GeekflareFullConfig) or self.config.credentials is None:
            raise ValueError("Connect a Geekflare API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation", "id"})
        if hasattr(op, "id"):
            path = path.replace("{id}", quote(op.id, safe=""))
        # The provider accepts JSON on POST, query parameters on GET.
        kwargs = {"params": values} if method == "GET" else ({"json": values} if values else {})
        async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=180) as client:
            response = await client.request(method, BASE + path,
                headers={"x-api-key": key, "Accept": "application/json"}, **kwargs)
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Geekflare returned a non-JSON response") from None
        if not 200 <= response.status_code < 300:
            message = body.get("message", "Geekflare rejected the request") if isinstance(body, dict) else "Geekflare rejected the request"
            raise ValueError(f"Geekflare HTTP {response.status_code}: {_redact(str(message), key)}")
        if not isinstance(body, dict):
            raise ValueError("Geekflare returned an invalid response envelope")
        if body.get("apiStatus") == "failure" or (isinstance(body.get("apiCode"), (int, float)) and body["apiCode"] >= 400):
            raise ValueError("Geekflare: " + _redact(str(body.get("message", "Request failed")), key))
        if op.operation == "list_crawls":
            if not isinstance(body.get("items"), list) or not isinstance(body.get("pagination"), dict):
                raise ValueError("Geekflare returned an incomplete crawl list")
        elif op.operation in {"start_crawl", "get_crawl", "cancel_crawl", "start_discovery", "get_discovery"}:
            if not isinstance(body.get("id"), str) or not isinstance(body.get("status"), str):
                raise ValueError("Geekflare returned an incomplete job response")
            if hasattr(op, "id") and body["id"] != op.id:
                raise ValueError("Geekflare returned a different job")
        elif body.get("apiStatus") != "success" or "data" not in body:
            raise ValueError("Geekflare did not confirm a successful result")
        # Preserve the documented JSON envelope, including pagination and partial
        # job states. A queued job is not reported as a completed crawl.
        return _redact(body, key)
