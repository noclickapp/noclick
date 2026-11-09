"""Currents API v1: all five operations in the provider's published contract.

News is shared content: a successful read proves key acceptance, not identity.
Each operation requests one page; callers explicitly choose the next page.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.currentsapi.services/v1"
ROUTES = {
    "search_news": "/search",
    "get_latest_news": "/latest-news",
    "list_languages": "/available/languages",
    "list_regions": "/available/regions",
    "list_categories": "/available/categories",
}


class CurrentsApiKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Currents API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://currentsapi.services/en/profile",
            "x-credential-instructions": "Copy your API key from the Currents account dashboard. Paste the key without the Bearer prefix. A latest-news read checks key acceptance; it does not identify your account.",
        },
    )
    credential_type: Literal["currents_api_key"] = Field("currents_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the Currents API key, without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _NewsFilters(_Input):
    language: str | None = Field(None, description="Language code from List Languages. Provider default: en.")
    category: str | None = Field(None, description="Comma-separated legacy v1 categories from List Categories.")
    country: str | None = Field(None, description="Country code from List Regions.")
    page_number: int = Field(1, ge=1, le=180, description="One page per run. Increase explicitly to retrieve another page.")
    page_size: int = Field(20, ge=1, le=300, description="Free plan supports up to 20; larger pages need a paid plan.")
    type: Literal[1, 2, 3] | None = Field(None, title="Article Type", description="1: news, 2: articles, 3: discussion.")
    domain: str | None = Field(None, description="Include a source domain, for example reuters.com.")
    domain_not: str | None = Field(None, description="Exclude a source domain.")
    author: str | None = None


class SearchNews(_NewsFilters):
    """Search news by keywords, boolean query, date range and source filters."""
    operation: Literal["search_news"] = "search_news"
    keywords: str | None = Field(None, description="Words, quoted phrases, OR and -exclusions. Takes priority over query.")
    query: str | None = Field(None, description="Boolean AND, OR, NOT, parentheses and quoted phrases.")
    start_date: str | None = Field(None, description="RFC 3339 timestamp; history and date span depend on your plan.", json_schema_extra={"format": "date-time"})
    end_date: str | None = Field(None, description="RFC 3339 timestamp.", json_schema_extra={"format": "date-time"})
    limit: int | None = Field(None, ge=1, le=300, description="Additional result cap, still limited by your plan.")
    has_image: bool = Field(False, description="Only include articles with images. Disabled omits this presence filter.")
    has_description: bool = Field(False, description="Only include articles with descriptions. Disabled omits this presence filter.")

    @field_validator("start_date", "end_date")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})", value):
                raise ValueError("Use an RFC 3339 timestamp including its timezone")
            datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
        return value


class GetLatestNews(_NewsFilters):
    """Get recent headlines with language, country, category and source filters."""
    operation: Literal["get_latest_news"] = "get_latest_news"


class ListLanguages(_Input):
    """List language names and query codes."""
    operation: Literal["list_languages"] = "list_languages"


class ListRegions(_Input):
    """List region names and country query codes."""
    operation: Literal["list_regions"] = "list_regions"


class ListCategories(_Input):
    """List the legacy v1 category codes in source-count order."""
    operation: Literal["list_categories"] = "list_categories"


CurrentsApiOperation = Annotated[Union[SearchNews, GetLatestNews, ListLanguages, ListRegions, ListCategories], Field(discriminator="operation")]


class CurrentsApiConfig(NodeConfig[CurrentsApiOperation, CurrentsApiKeyCredential]):
    pass


class CurrentsApiNode(WorkflowNode):
    integration_type = "automation-currents-api"
    connection_evidence = ConnectionEvidence(
        noun="news headlines", operation="get_latest_news", proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return CurrentsApiConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Currents API key")
        config = self.config.config
        key = self.config.credentials.api_key
        params = config.model_dump(exclude={"operation"}, exclude_none=True)
        # These are presence filters: even has_image=false means filter enabled.
        for field in ("has_image", "has_description"):
            if params.get(field) is False:
                params.pop(field)
        params = {k: "true" if v is True else v for k, v in params.items()}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(
                    "GET", BASE_URL + ROUTES[config.operation], params=params,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                )
            try:
                body = response.json()
            except ValueError:
                body = None
            if response.status_code != 200 or (isinstance(body, dict) and body.get("status") != "ok"):
                message = body.get("msg") if isinstance(body, dict) else None
                result = {"status": "error", "success": False, "http_status": response.status_code,
                          "message": message.replace(key, "[redacted]") if isinstance(message, str) else "Currents API request failed"}
                if response.status_code == 429:
                    result["retry_after"] = response.headers.get("Retry-After")
            else:
                self._validate_response(config.operation, body)
                result = {**body, "status": "success", "success": True}
        except httpx.HTTPError:
            result = {"status": "error", "success": False, "message": "Currents API could not be reached"}
        await self.emit(result)
        return result

    @staticmethod
    def _validate_response(operation, body):
        if not isinstance(body, dict) or body.get("status") != "ok":
            raise ValueError("Expected a successful Currents API JSON response")
        if operation in {"search_news", "get_latest_news"}:
            if not isinstance(body.get("news"), list) or any(not isinstance(row, dict) for row in body["news"]) or type(body.get("page")) is not int:
                raise ValueError("Expected Currents news and page fields")
        else:
            field = operation.removeprefix("list_")
            value = body.get(field)
            if field == "categories":
                valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
            else:
                valid = isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in value.items())
            if not valid:
                raise ValueError("Expected Currents " + field + " codes")
