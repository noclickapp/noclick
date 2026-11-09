"""Serply's ten published v1 search endpoints, authenticated with a pasted API key.
Queries stay in the provider's path format and response JSON is preserved for workflows.
Connection evidence proves key acceptance only; the contract has no account identity API.
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

BASE_URL = "https://api.serply.io"
CREDENTIAL_TYPE = "serply_api_key"
HIDDEN = {"ui:hidden": True}


class SerplyApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Serply API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.serply.io/users/sign_in",
            "x-credential-instructions": "Paste your API key from the Serply dashboard. Connecting runs one Google search for search api and uses your search quota. This checks key acceptance; Serply does not expose account identity in its published API.",
        })
    credential_type: Literal["serply_api_key"] = Field("serply_api_key", json_schema_extra=HIDDEN)
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class SerplyQueryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    query: str = Field(..., min_length=1, max_length=8192, title="Encoded Search Query",
        description="Serply query path, for example q=search+api&num=100. Encode keyword spaces as + and URL values with percent escapes. This is sent in the path, not as HTTP query parameters.")

    @field_validator("query")
    @classmethod
    def valid_query(cls, value):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Search query must not contain control characters")
        return value


class SerplyHeaderQueryConfig(SerplyQueryConfig):
    device: Literal["desktop", "mobile"] | None = Field(None, title="Device",
        description="Optional X-User-Agent header. Serply defaults to desktop.")
    proxy_location: Literal["EU", "CA", "US", "IE", "GB", "FR", "DE", "SE", "IN", "JP", "KR", "SG", "AU", "BR"] | None = Field(None,
        title="Proxy Location", description="Optional X-Proxy-Location header.")


class SerplySearchGoogleConfig(SerplyHeaderQueryConfig):
    """Search Google using its dedicated published endpoint."""
    operation: Literal["search_google"] = Field("search_google", title="Search Google", json_schema_extra=HIDDEN)
    query: str = Field("q=search+api", max_length=8192, title="Encoded Search Query", description="Serply path query, for example q=search+api&num=100. Defaults to the documented search api example used when connecting.")


class SerplySearchBingConfig(SerplyHeaderQueryConfig):
    """Search Bing using its dedicated published endpoint."""
    operation: Literal["search_bing"] = Field("search_bing", title="Search Bing", json_schema_extra=HIDDEN)


class SerplySearchVideosConfig(SerplyHeaderQueryConfig):
    """Search Videos using its dedicated published endpoint."""
    operation: Literal["search_videos"] = Field("search_videos", title="Search Videos", json_schema_extra=HIDDEN)


class SerplySearchJobsConfig(SerplyQueryConfig):
    """Search Jobs using its dedicated published endpoint."""
    operation: Literal["search_jobs"] = Field("search_jobs", title="Search Jobs", json_schema_extra=HIDDEN)


class SerplySearchScholarConfig(SerplyHeaderQueryConfig):
    """Search Scholar using its dedicated published endpoint."""
    operation: Literal["search_scholar"] = Field("search_scholar", title="Search Scholar", json_schema_extra=HIDDEN)


class SerplySearchNewsConfig(SerplyHeaderQueryConfig):
    """Search News using its dedicated published endpoint."""
    operation: Literal["search_news"] = Field("search_news", title="Search News", json_schema_extra=HIDDEN)


class SerplySearchImagesConfig(SerplyHeaderQueryConfig):
    """Search Images using its dedicated published endpoint."""
    operation: Literal["search_images"] = Field("search_images", title="Search Images", json_schema_extra=HIDDEN)


class SerplyGetSerpRankConfig(SerplyHeaderQueryConfig):
    """Get SERP Rank using its dedicated published endpoint."""
    operation: Literal["get_serp_rank"] = Field("get_serp_rank", title="Get SERP Rank", json_schema_extra=HIDDEN)
    query: str = Field(..., min_length=1, max_length=8192, title="Encoded Search Query", description="Include domain or website as documented, for example q=serp+api&num=100&domain=serply.io. Percent-encode website URLs.")


class SerplyGetCrawlResultsConfig(SerplyHeaderQueryConfig):
    """Get Crawl Results using its dedicated published endpoint."""
    operation: Literal["get_crawl_results"] = Field("get_crawl_results", title="Get Crawl Results", json_schema_extra=HIDDEN)


class SerplySearchProductsConfig(SerplyHeaderQueryConfig):
    """Search Products using its dedicated published endpoint."""
    operation: Literal["search_products"] = Field("search_products", title="Search Products", json_schema_extra=HIDDEN)


SerplyConfig = Annotated[Union[
    SerplySearchGoogleConfig,
    SerplySearchBingConfig,
    SerplySearchVideosConfig,
    SerplySearchJobsConfig,
    SerplySearchScholarConfig,
    SerplySearchNewsConfig,
    SerplySearchImagesConfig,
    SerplyGetSerpRankConfig,
    SerplyGetCrawlResultsConfig,
    SerplySearchProductsConfig
], Field(discriminator="operation")]
ROUTES = {'search_google': '/v1/search/', 'search_bing': '/v1/b/search/', 'search_videos': '/v1/video/', 'search_jobs': '/v1/job/search/', 'search_scholar': '/v1/scholar/', 'search_news': '/v1/news/', 'search_images': '/v1/image/', 'get_serp_rank': '/v1/serp/', 'get_crawl_results': '/v1/crawl/', 'search_products': '/v1/product/search/'}


class SerplyFullConfig(NodeConfig[SerplyConfig, SerplyApiKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    return value


class SerplyNode(WorkflowNode):
    integration_type = "automation-serply"
    connection_evidence = ConnectionEvidence(
        noun="Serply search access", operation="search_google", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return SerplyFullConfig

    async def execute(self, inputs):
        parsed = self.config
        config, credential = parsed.config, parsed.credentials
        if credential is None:
            return {"status": "error", "error": "Connect a Serply API key"}
        headers = {"X-Api-Key": credential.api_key, "Accept": "application/json"}
        if isinstance(config, SerplyHeaderQueryConfig):
            if config.device is not None:
                headers["X-User-Agent"] = config.device
            if config.proxy_location is not None:
                headers["X-Proxy-Location"] = config.proxy_location
        # The query is a single path component. Keep the provider's encoded
        # q=...&... syntax, but prevent literal /, ? and # from altering the URL.
        path = ROUTES[config.operation] + quote(config.query, safe="=&+%")
        try:
            async with guarded_async_client(timeout=60.0, follow_redirects=False, trust_env=False) as client:
                response = await client.get(BASE_URL + path, headers=headers)
        except httpx.HTTPError:
            return {"status": "error", "error": "Serply request failed; try again later"}
        try:
            body = response.json()
        except ValueError:
            return {"status": "error", "http_status": response.status_code,
                "error": "Serply returned a non-JSON response"}
        body = _redact(body, credential.api_key)
        if response.status_code != 200:
            return {"status": "error", "http_status": response.status_code,
                "error": body if body else "Serply did not complete the request"}
        if not isinstance(body, dict):
            return {"status": "error", "error": "Serply returned an unexpected response shape"}
        if body.get("error") or body.get("errors") or body.get("detail"):
            return {"status": "error", "http_status": response.status_code,
                "error": body.get("error") or body.get("errors") or body.get("detail")}
        if config.operation == "search_google" and not isinstance(body.get("results"), list):
            return {"status": "error", "error": "Serply returned an unexpected response shape"}
        return {"status": "success", "data": body}
