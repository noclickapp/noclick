"""Search1API search, extraction and crawl operations using a personal API key.

Each operation maps to one published endpoint; paid requests are never retried
or paginated implicitly. Account usage provides the credential connection proof.
Contract: https://api.search1api.com/openapi.json (1.0.0).
"""
from __future__ import annotations

import json

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client, SSRFError

BASE = "https://api.search1api.com"


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, validate_default=True)

    @field_validator("*", mode="after")
    @classmethod
    def public_url(cls, value, info):
        if info.field_name == "url" and value is not None:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Supply an HTTP or HTTPS page URL without credentials")
        return value


class Search1ApiKeyCredential(_Input):
    model_config = ConfigDict(title="Search1API API Key", extra="forbid", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.s1.dev", "x-credential-instructions": "Create an API key in your Search1API dashboard, then paste it here."})
    credential_type: Literal["search1api_api_key"] = Field("search1api_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False,
        description="Paste your Search1API API key without the Bearer prefix.", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str) or not value.strip() or any(c.isspace() for c in value.strip()):
            raise ValueError("Paste a single Search1API key without the Bearer prefix")
        return value.strip()




class Search1ApiSearchWebConfig(_Input):
    'Search the web using multiple search engines'
    operation: Literal['search_web'] = Field('search_web', json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1)
    search_service: Literal['google', 'bing', 'bingcn', 'duckduckgo', 'yahoo', 'yandex', 'youtube', 'x', 'reddit', 'github', 'arxiv', 'wechat', 'bilibili', 'imdb', 'wikipedia', 'grokipedia', '', 'baidu', '360', 'quark'] | None = Field(None)
    max_results: int = Field(5, ge=1, le=50)
    page: int = Field(1, ge=1, le=100)
    crawl_results: int = Field(0, ge=0, le=50)
    image: bool = Field(False)
    include_sites: list[str] = Field([])
    exclude_sites: list[str] = Field([])
    language: str | None = Field(None)
    time_range: Literal['day', 'week', 'month', 'year', ''] | None = Field(None)


class Search1ApiSearchMapsConfigLocation(_Input):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    zoom: float = Field(14, ge=3, le=30)


class Search1ApiSearchMapsConfig(_Input):
    'Search Google Maps for local businesses and places'
    operation: Literal['search_maps'] = Field('search_maps', json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=1000, description='Google Maps search phrase; leading and trailing whitespace is removed.')
    country: str = Field('us', pattern='^[a-zA-Z]{2}$', description='Two-letter country code, normalized to lowercase. Defaults to us.')
    language: str = Field('en', pattern='^[a-z]{2,3}(-[a-zA-Z]{2,4})?$', description='Result language, for example en, de or zh-CN. Defaults to en.')
    location: Search1ApiSearchMapsConfigLocation | None = Field(None, description='Search origin coordinates and map zoom (default 14). Required for page > 1. Latitude must be -90 to 90, longitude -180 to 180, and zoom 3 to 30. Example: {"latitude":40.7455,"longitude":-74.0083,"zoom":15}.')
    page: int = Field(1, ge=1, le=6, description='Page number, 1–6; default 1. Accepts an integer or canonical integer string such as "2". Empty strings use the default. Pages after the first require location.')
    max_results: int = Field(20, ge=1, le=20, description='Maximum places to return from this page, 1–20; default 20. Accepts an integer or canonical integer string such as "10". Empty strings use the default. Truncation does not reduce the page charge or carry places to the next page.')
    @model_validator(mode="after")
    def location_for_later_pages(self):
        if self.page > 1 and self.location is None:
            raise ValueError("Maps pages after the first require location coordinates")
        return self



class Search1ApiSearchNewsConfig(_Input):
    'Search news articles across multiple sources'
    operation: Literal['search_news'] = Field('search_news', json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1)
    search_service: Literal['google', 'bing', 'duckduckgo', 'yahoo', 'hackernews', '', 'reuters'] | None = Field(None)
    max_results: int = Field(5, ge=1, le=50)
    crawl_results: int = Field(0, ge=0, le=50)
    image: bool = Field(False)
    include_sites: list[str] = Field([])
    exclude_sites: list[str] = Field([])
    language: str | None = Field(None)
    time_range: Literal['day', 'week', 'month', 'year', ''] | None = Field(None)


class Search1ApiAskConfig(_Input):
    'Search the engines a natural-language request calls for'
    operation: Literal['ask'] = Field('ask', json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=500, description='What you are looking for, in natural language. Platform hints ("on Reddit", "papers") and time hints ("this week") steer engine and time-range selection.')


class Search1ApiCrawlPageConfig(_Input):
    'Crawl a URL and extract its content'
    operation: Literal['crawl_page'] = Field('crawl_page', json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, json_schema_extra={"format": "uri"})
    enableFallback: bool = Field(True)


class Search1ApiGetSitemapConfig(_Input):
    'Extract sitemap URLs from a website'
    operation: Literal['get_sitemap'] = Field('get_sitemap', json_schema_extra={"ui:hidden": True})
    url: str = Field(..., json_schema_extra={"format": "uri"})
    type: Literal['sitemap', 'all'] | None = Field(None)


class Search1ApiGetTrendingConfig(_Input):
    'Get trending topics from various platforms'
    operation: Literal['get_trending'] = Field('get_trending', json_schema_extra={"ui:hidden": True})
    search_service: str = Field(..., min_length=1)
    max_results: int | None = Field(None, ge=1)


class Search1ApiExtractContentConfig(_Input):
    'Extract structured content from a URL'
    operation: Literal['extract_content'] = Field('extract_content', json_schema_extra={"ui:hidden": True})
    url: str = Field(..., json_schema_extra={"format": "uri"})
    prompt: str | None = Field(None)
    response_format: dict[str, Any] | None = Field(None)


class Search1ApiStartDeepcrawlConfig(_Input):
    'Deep crawl a website across multiple pages'
    operation: Literal['start_deepcrawl'] = Field('start_deepcrawl', json_schema_extra={"ui:hidden": True})
    url: str = Field(..., json_schema_extra={"format": "uri"})
    type: Literal['sitemap', 'all'] | None = Field(None)
    max_pages: int | None = Field(None, ge=1, le=1000, description='Maximum number of pages to crawl, 1–1000; default 1000. Applied after include_paths/exclude_paths, in discovery order.')
    include_paths: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(None, max_length=20, description='Only crawl URLs whose path matches one of these rules (up to 20). A rule without * is a path prefix on segment boundaries: "/docs" matches /docs and /docs/api but not /docsearch. A rule with * must match the whole path, and * matches any characters including /, e.g. "/blog/*". Empty or omitted means every discovered URL.')
    exclude_paths: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(None, max_length=20, description='Skip URLs whose path matches one of these rules (up to 20), using the same syntax as include_paths. Exclusion wins over inclusion.')
    format: Literal['zip', 'json'] | None = Field(None, description='Result format; default "zip". "zip" packages the pages as Markdown files behind zipUrl. "json" returns pages: [{url, title, content}] in the completed status response, plus resultUrl for the same JSON file.')


class Search1ApiGetDeepcrawlStatusConfig(_Input):
    'Check deepcrawl task status'
    operation: Literal['get_deepcrawl_status'] = Field('get_deepcrawl_status', json_schema_extra={"ui:hidden": True})
    taskId: str = Field(..., min_length=1)

    @field_validator("taskId")
    @classmethod
    def task_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value):
            raise ValueError("Supply the taskId returned by start deepcrawl")
        return value


class Search1ApiGetUsageConfig(_Input):
    'Get API key usage statistics'
    operation: Literal['get_usage'] = Field('get_usage', json_schema_extra={"ui:hidden": True})
    period: Literal['day', 'week', 'month', 'year'] | None = Field(None)


class Search1ApiSubmitFeedbackConfigAgent(_Input):
    name: str | None = Field(None, max_length=128)
    model: str | None = Field(None, max_length=128)


class Search1ApiSubmitFeedbackConfig(_Input):
    'Report a Search1API problem or feature request. Submits a report to Search1API; omit credentials and private content.'
    operation: Literal['submit_feedback'] = Field('submit_feedback', json_schema_extra={"ui:hidden": True})
    message: str = Field(..., min_length=1, max_length=4000)
    intent: str | None = Field(None, max_length=2000)
    category: Literal['bug', 'feature_request', 'docs', 'other'] = Field('other')
    request_id: str | None = Field(None, max_length=256)
    agent: Search1ApiSubmitFeedbackConfigAgent | None = Field(None)


# Search1API's own MCP server: agents get its tools through a person's Search1API sign-in.
Search1apiMcpCredential = mcp_credential("search1api", "https://mcp.search1api.com/mcp", app="Search1API")
Search1Credential = Union[Search1ApiKeyCredential, Search1apiMcpCredential]


Search1ApiConfig = Annotated[Union[Search1ApiSearchWebConfig, Search1ApiSearchMapsConfig, Search1ApiSearchNewsConfig, Search1ApiAskConfig, Search1ApiCrawlPageConfig, Search1ApiGetSitemapConfig, Search1ApiGetTrendingConfig, Search1ApiExtractContentConfig, Search1ApiStartDeepcrawlConfig, Search1ApiGetDeepcrawlStatusConfig, Search1ApiGetUsageConfig, Search1ApiSubmitFeedbackConfig], Field(discriminator="operation")]


class Search1ApiFullConfig(NodeConfig[Search1ApiConfig, Search1Credential]):
    pass


ROUTES = {'search_web': ('POST', '/search', 200), 'search_maps': ('POST', '/maps', 200), 'search_news': ('POST', '/news', 200), 'ask': ('POST', '/ask', 200), 'crawl_page': ('POST', '/crawl', 200), 'get_sitemap': ('POST', '/sitemap', 200), 'get_trending': ('POST', '/trending', 200), 'extract_content': ('POST', '/extract', 200), 'start_deepcrawl': ('POST', '/deepcrawl', 202), 'get_deepcrawl_status': ('GET', '/deepcrawl/status/{taskId}', 200), 'get_usage': ('GET', '/usage', 200), 'submit_feedback': ('POST', '/feedback', 201)}
REQUIRED_RESPONSE_KEYS = {'search_web': ['searchParameters', 'results'], 'search_maps': ['searchParameters', 'results'], 'search_news': ['searchParameters', 'results'], 'ask': ['query', 'intent', 'results', 'errors'], 'crawl_page': ['crawlParameters', 'results'], 'get_sitemap': ['links'], 'get_trending': ['trendingParameters', 'results'], 'extract_content': ['success', 'extractParameters', 'results'], 'start_deepcrawl': ['taskId', 'status'], 'get_deepcrawl_status': ['taskId'], 'get_usage': ['usage', 'credential_type'], 'submit_feedback': ['id', 'status']}


class Search1ApiNode(WorkflowNode):
    integration_type = "automation-search1api"
    credential_provider_labels = {"search1api": "Search1API Account"}
    connection_evidence = ConnectionEvidence(noun="Search1API account usage", operation="get_usage")

    @classmethod
    def get_config_model(cls):
        return Search1ApiFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Search1API API key")
        config = self.config.config
        operation = config.operation
        method, path, expected = ROUTES[operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if operation == "get_deepcrawl_status":
            path = path.replace("{taskId}", quote(values.pop("taskId"), safe=""))
        if operation == "submit_feedback" and len(json.dumps(values, ensure_ascii=False).encode()) > 16384:
            raise ValueError("Feedback must fit within the provider's 16 KiB limit")
        kwargs = {"params": values} if method == "GET" else {"json": values}
        headers = {"Authorization": "Bearer " + self.config.credentials.api_key,
                   "Accept": "application/json"}
        try:
            async with guarded_async_client(timeout=65, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, headers=headers, **kwargs)
            if response.status_code != expected:
                # Preserve the provider's rejection for connect; no automatic retry of paid calls.
                message = "Search1API request failed"
                try:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        message = error["message"][:2000]
                except ValueError:
                    pass
                return {"status": "error", "operation": operation, "http_status": response.status_code, "error": message}
            if len(response.content) > 30_000_000:
                raise ValueError("Search1API response exceeded the size limit")
            mime = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
            if mime != "application/json":
                raise ValueError("Expected Search1API JSON")
            data = response.json()
            if not isinstance(data, dict) or any(k not in data for k in REQUIRED_RESPONSE_KEYS[operation]):
                raise ValueError("Incomplete Search1API response")
            if data.get("ok") is False or data.get("success") is False or (data.get("error") and operation != "get_deepcrawl_status"):
                return {"status": "error", "operation": operation, "error": data.get("message") or data.get("error") or "Search1API operation failed", "data": data}
            if operation == "get_usage" and (type(data["usage"]) is not int or data["usage"] < 0 or data["credential_type"] not in {"api_key", "oauth"}):
                raise ValueError("Invalid account usage response")
            # Keep provider job status separate from the node's execution status.
            return {"status": "success", "operation": operation, "data": data}
        except (ValueError, httpx.HTTPError, SSRFError):
            return {"status": "error", "operation": operation, "error": "Search1API response could not be confirmed"}
