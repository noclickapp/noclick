"""urlscan.io API v1: explicit operations backed by the published OpenAPI contract.

API keys are sent only to the fixed provider host. Calls return one page; search
sort values and hostname pageState are preserved for caller-driven pagination.
Writes are never retried, and a submission acknowledgement is not a finished scan.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://urlscan.io"
CONTRACT_URL = "https://docs.urlscan.io/_bundle/apis/urlscan-openapi.json?download"


class UrlscanioAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="urlscan.io API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://urlscan.io/user/profile/",
            "x-credential-instructions": "Paste your urlscan.io API key from your profile. NoClick checks the current user. Pro operations need a urlscan Pro plan and the key's permissions; connecting does not verify write access.",
        })
    credential_type: Literal["urlscanio_api_key"] = Field("urlscanio_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Pro(_Input):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"x-requires-tier": "pro", "x-tier-label": "urlscan Pro"})


class _ScanID(_Input):
    scan_id: str = Field(..., description="UUID of the scan result", json_schema_extra={"format": "uuid"})

    @field_validator("scan_id")
    @classmethod
    def scan_uuid(cls, value):
        return str(UUID(value))


class GetUser(_Input):
    operation: Literal["get_user"] = "get_user"


class SubmitScan(_Input):
    """Submit a URL once. The response acknowledges a queued scan; poll get_result later."""
    operation: Literal["submit_scan"] = "submit_scan"
    url: str = Field(..., json_schema_extra={"format": "uri"})
    visibility: Literal["public", "unlisted", "private"] = Field("private", description="Public scans expose the URL and page contents to everyone. Private scans need available quota.")
    country: str | None = Field(None, pattern="^[a-z]{2}$")
    tags: list[Annotated[str, Field(max_length=30)]] | None = Field(None, max_length=10)
    referer: str | None = None
    customagent: str | None = None

    @field_validator("url")
    @classmethod
    def scan_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Use an absolute HTTP or HTTPS URL")
        return value


class Search(_Input):
    """Retrieve one page. Pass the last result's comma-separated sort values as search_after."""
    operation: Literal["search"] = "search"
    q: str = Field(..., min_length=1, description="Elasticsearch query string, e.g. page.domain:example.com")
    size: int = Field(100, ge=1, le=10000)
    search_after: str | None = None
    datasource: Literal["scans", "hostnames", "incidents", "notifications", "certificates"] = "scans"
    collapse: str | None = None


class GetResult(_ScanID):
    """Read a completed scan. A 404 may mean it is still processing; retry explicitly later."""
    operation: Literal["get_result"] = "get_result"


class UpdateVisibility(_ScanID, _Pro):
    """Change visibility of your/team scan. 'deleted' removes it from view."""
    operation: Literal["update_visibility"] = "update_visibility"
    visibility: Literal["public", "unlisted", "private", "deleted"]


class ResetVisibility(_ScanID, _Pro):
    operation: Literal["reset_visibility"] = "reset_visibility"


class GetCountries(_Input):
    operation: Literal["get_countries"] = "get_countries"


class GetQuotas(_Input):
    operation: Literal["get_quotas"] = "get_quotas"


class GetAvailableBrands(_Pro):
    operation: Literal["get_available_brands"] = "get_available_brands"


class GetBrandSummary(_Pro):
    operation: Literal["get_brand_summary"] = "get_brand_summary"


class GetHostnameHistory(_Input):
    operation: Literal["get_hostname_history"] = "get_hostname_history"
    hostname: str = Field(..., min_length=1, max_length=253)
    limit: int = Field(1000, ge=10, le=10000)
    pageState: str | None = Field(None, description="Opaque pageState from the previous response")


class GetSimilarResults(_ScanID, _Pro):
    operation: Literal["get_similar_results"] = "get_similar_results"
    q: str | None = None
    size: int = Field(100, ge=1, le=10000)
    search_after: str | None = None


class ListSavedSearches(_Pro):
    operation: Literal["list_saved_searches"] = "list_saved_searches"


class _SavedSearch(_Pro):
    datasource: Literal["hostnames", "scans"]
    name: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    description: str | None = None
    longDescription: str | None = None
    permissions: list[Literal["public:read", "team:read", "team:write"]] | None = None
    tlp: Literal["red", "amber+strict", "amber", "green", "clear"] | None = None
    usertags: list[str] | None = None


class CreateSavedSearch(_SavedSearch):
    operation: Literal["create_saved_search"] = "create_saved_search"


class UpdateSavedSearch(_SavedSearch):
    operation: Literal["update_saved_search"] = "update_saved_search"
    search_id: str = Field(..., min_length=1, max_length=512)


class DeleteSavedSearch(_Pro):
    operation: Literal["delete_saved_search"] = "delete_saved_search"
    search_id: str = Field(..., min_length=1, max_length=512)


class ListSubscriptions(_Pro):
    operation: Literal["list_subscriptions"] = "list_subscriptions"


class ListChannels(_Pro):
    operation: Literal["list_channels"] = "list_channels"


UrlscanioConfig = Annotated[Union[GetUser, SubmitScan, Search, GetResult,
    UpdateVisibility, ResetVisibility, GetCountries, GetQuotas, GetAvailableBrands,
    GetBrandSummary, GetHostnameHistory, GetSimilarResults, ListSavedSearches,
    CreateSavedSearch, UpdateSavedSearch, DeleteSavedSearch, ListSubscriptions,
    ListChannels], Field(discriminator="operation")]


class UrlscanioFullConfig(NodeConfig[UrlscanioConfig, UrlscanioAPIKeyCredential]):
    pass


# Exactly one published contract operation per exposed operation.
ROUTES = {
    "get_user": ("GET", "/user/username"),
    "submit_scan": ("POST", "/api/v1/scan"),
    "search": ("GET", "/api/v1/search"),
    "get_result": ("GET", "/api/v1/result/{scan_id}/"),
    "update_visibility": ("PUT", "/api/v1/result/{scan_id}/visibility/"),
    "reset_visibility": ("DELETE", "/api/v1/result/{scan_id}/visibility/"),
    "get_countries": ("GET", "/api/v1/availableCountries"),
    "get_quotas": ("GET", "/api/v1/quotas"),
    "get_available_brands": ("GET", "/api/v1/pro/availableBrands"),
    "get_brand_summary": ("GET", "/api/v1/pro/brands"),
    "get_hostname_history": ("GET", "/api/v1/hostname/{hostname}"),
    "get_similar_results": ("GET", "/api/v1/pro/result/{scan_id}/similar/"),
    "list_saved_searches": ("GET", "/api/v1/user/searches/"),
    "create_saved_search": ("POST", "/api/v1/user/searches/"),
    "update_saved_search": ("PUT", "/api/v1/user/searches/{search_id}/"),
    "delete_saved_search": ("DELETE", "/api/v1/user/searches/{search_id}/"),
    "list_subscriptions": ("GET", "/api/v1/user/subscriptions/"),
    "list_channels": ("GET", "/api/v1/user/channels/"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class UrlscanioNode(WorkflowNode):
    integration_type = "automation-urlscanio"
    connection_evidence = ConnectionEvidence(noun="urlscan.io account", identity_operation="get_user",
        identity_keys=("username", "name", "email"))

    @classmethod
    def get_config_model(cls):
        return UrlscanioFullConfig

    async def execute(self, inputs):
        if self.config.credentials is None:
            raise ValueError("Connect a urlscan.io API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for name in ("scan_id", "hostname", "search_id"):
            if "{" + name + "}" in path:
                value = values.pop(name)
                if value in {".", ".."}:
                    raise ValueError("Use a resource identifier, not a path segment")
                path = path.replace("{" + name + "}", quote(value, safe=""))
        body, params = None, None
        if method == "GET":
            params = values
        elif method in {"POST", "PUT"}:
            body = {"search": values} if op.operation in {"create_saved_search", "update_saved_search"} else values
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, params=params, json=body,
                    headers={"api-key": secret, "Accept": "application/json"})
        except httpx.RequestError:
            raise ValueError("urlscan.io request did not complete; inspect any write before retrying") from None
        if not 200 <= response.status_code < 300:
            # Never return a provider error body: it may echo credentials or page contents.
            raise ValueError(f"urlscan.io HTTP {response.status_code}; no automatic retry was made")
        if len(response.content) > 20_000_000:
            raise ValueError("urlscan.io response exceeds the 20 MB limit")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Expected a JSON response from urlscan.io") from None
        if not isinstance(data, (dict, list)) or (isinstance(data, dict) and (data.get("error") or data.get("status") == "error")):
            raise ValueError("urlscan.io returned an error or unexpected response")
        output = _redact({"status": "success", "operation": op.operation,
            "http_status": response.status_code, "data": data}, secret)
        await self.emit(output)
        return output
