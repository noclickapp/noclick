"""You.com Web Search 1.0.0: https://you.com/docs/api-reference/search/v1-search.

The pinned contract publishes one read-only POST operation. Search variants are
parameters of that operation, not fabricated API operations. No OAuth is needed.
"""
from __future__ import annotations

from datetime import date
import re
from typing import Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret


class YousearchAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Yousearch API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://you.com/platform",
            "x-credential-instructions": "Create an API key in the You.com platform and paste it here. Connecting makes one small search request, which may use API credits. Public search proves key acceptance, not account identity.",
        })
    credential_type: Literal["yousearch_api_key"] = Field("yousearch_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class YousearchSearchConfig(BaseModel):
    """Search web and news, optionally extracting highlights or full pages."""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    operation: Literal["search_web"] = Field("search_web", json_schema_extra={
        "ui:hidden": True, "x-display-name": "Search Web and News",
        "x-category": "Search", "x-is-trigger": False,
        "x-keywords": ["research", "news", "highlights", "web search"],
    })
    query: str = Field(..., min_length=1, title="Search Query")
    count: int = Field(10, ge=1, le=100, title="Maximum Results")
    offset: int = Field(0, ge=0, le=9, description="Page index in multiples of count, from 0 to 9. Set the next index explicitly; a full page does not guarantee more results.")
    freshness: Optional[str] = Field(None, description="day, week, month, year, or YYYY-MM-DDtoYYYY-MM-DD")
    country: Optional[Literal['AR', 'AU', 'AT', 'BE', 'BR', 'CA', 'CL', 'DK', 'FI', 'FR', 'DE', 'HK', 'IN', 'ID', 'IT', 'JP', 'KR', 'MY', 'MX', 'NL', 'NZ', 'NO', 'CN', 'PL', 'PT', 'PH', 'RU', 'SA', 'ZA', 'ES', 'SE', 'CH', 'TW', 'TR', 'GB', 'US']] = Field(None, title="Country")
    language: Literal['AR', 'EU', 'BN', 'BG', 'CA', 'ZH-HANS', 'ZH-HANT', 'HR', 'CS', 'DA', 'NL', 'EN', 'EN-GB', 'ET', 'FI', 'FR', 'GL', 'DE', 'EL', 'GU', 'HE', 'HI', 'HU', 'IS', 'IT', 'JA', 'KN', 'KO', 'LV', 'LT', 'MS', 'ML', 'MR', 'NB', 'PL', 'PT-BR', 'PT-PT', 'PA', 'RO', 'RU', 'SR', 'SK', 'SL', 'ES', 'SV', 'TA', 'TE', 'TH', 'TR', 'UK', 'VI'] = Field("EN", title="Language")
    safesearch: Literal["off", "moderate", "strict"] = "moderate"
    knowledge: Optional[Literal["core"]] = Field(None, description="Request licensed knowledge results. Omitted when no relevant results exist.")
    include_domains: Optional[str] = Field(None, description="Comma-separated domain allowlist, up to 500. Cannot combine with exclude or boost domains.")
    exclude_domains: Optional[str] = Field(None, description="Comma-separated domain denylist, up to 5000.")
    boost_domains: Optional[str] = Field(None, description="Comma-separated domains to boost, up to 500. May combine with exclude domains.")
    strict_operators: bool = Field(False, description="Enforce search operators exactly. Has no effect with highlights.")
    extraction_mode: Optional[Literal["highlights", "full_page"]] = Field(None,
        description="Omit for snippets. Extraction may incur additional API charges.")
    extraction_source: Optional[Literal["blend", "cache", "fetch"]] = Field(None,
        description="Full-page extraction only: cached and live, cache only, or always fetch.")
    total_max_tokens: Optional[int] = Field(None, ge=1024, le=8192,
        description="Highlights only: token budget shared across all results.")
    extraction_formats: Optional[Literal["markdown", "html", "both"]] = Field(None,
        description="Full-page extraction only; defaults to Markdown at the provider.")
    crawl_timeout: Optional[int] = Field(None, ge=1, le=60,
        description="Maximum crawl wait in seconds; valid only for full-page extraction.")

    @field_validator("freshness")
    @classmethod
    def valid_freshness(cls, value):
        if value is None or value in {"day", "week", "month", "year"}:
            return value
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}to\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Use day, week, month, year, or YYYY-MM-DDtoYYYY-MM-DD")
        start, end = map(date.fromisoformat, value.split("to"))
        if start > end:
            raise ValueError("Freshness start must not follow end")
        return value

    @field_validator("include_domains", "exclude_domains", "boost_domains")
    @classmethod
    def valid_domains(cls, value, info):
        if value is None:
            return value
        domains = [item.strip() for item in value.split(",")]
        maximum = 5000 if info.field_name == "exclude_domains" else 500
        if not all(domains) or len(domains) > maximum:
            raise ValueError(f"Provide 1 to {maximum} comma-separated domains")
        return ",".join(domains)

    @model_validator(mode="after")
    def supported_combinations(self):
        if self.include_domains and (self.exclude_domains or self.boost_domains):
            raise ValueError("Include domains cannot combine with exclude or boost domains")
        if self.extraction_mode == "highlights" and self.count > 50:
            raise ValueError("Highlights supports at most 50 results")
        if self.extraction_mode != "highlights" and self.total_max_tokens is not None:
            raise ValueError("Highlight token budget requires highlights extraction")
        if self.extraction_mode != "full_page" and any(v is not None for v in
                (self.extraction_source, self.extraction_formats, self.crawl_timeout)):
            raise ValueError("Extraction source, formats and crawl timeout require full-page extraction")
        return self

    def request_body(self):
        body = self.model_dump(exclude_none=True, exclude={"operation", "extraction_mode",
            "extraction_source", "extraction_formats", "total_max_tokens"})
        for name in ("include_domains", "exclude_domains", "boost_domains"):
            if name in body:
                body[name] = body[name].split(",")
        if self.extraction_mode:
            extraction = {"extraction_mode": self.extraction_mode}
            if self.extraction_source:
                extraction["extraction_source"] = self.extraction_source
            if self.total_max_tokens is not None:
                extraction["highlights"] = {"total_max_tokens": self.total_max_tokens}
            if self.extraction_formats:
                formats = ["markdown", "html"] if self.extraction_formats == "both" else [self.extraction_formats]
                extraction["full_page"] = {"extraction_formats": formats}
            body["extraction"] = extraction
        return body


# You.com's own MCP server: agents get its tools through a person's You.com sign-in.
YousearchMcpCredential = mcp_credential("yousearch", "https://api.you.com/mcp", app="You.com")
YousearchCredential = Union[YousearchAPIKeyCredential, YousearchMcpCredential]


class YousearchNodeConfig(NodeConfig[YousearchSearchConfig, YousearchCredential]):
    pass


class YousearchNode(WorkflowNode):
    integration_type = "automation-yousearch"
    credential_provider_labels = {"yousearch": "You.com Account"}
    connection_evidence = ConnectionEvidence(operation="search_web", noun="search results",
        operation_arguments={"query": "You.com", "count": 1}, proves="reachability")
    edit_examples = ["Find recent news about a topic", "Extract highlights from search results",
        "Search within selected domains", "Retrieve full pages as Markdown"]

    @classmethod
    def get_config_model(cls):
        return YousearchNodeConfig

    async def execute(self, inputs):
        config = self.config
        if not config.credentials:
            raise ValueError("Connect a Yousearch API key before searching")
        key = config.credentials.api_key
        try:
            async with httpx.AsyncClient(timeout=90.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request("POST", "https://ydc-index.io/v1/search",
                    headers={"X-API-Key": key, "Accept": "application/json"},
                    json=config.config.request_body())
            try:
                payload = response.json()
            except ValueError:
                return {"status": "error", "status_code": response.status_code,
                    "error": "Yousearch returned a non-JSON response"}
            if response.status_code != 200:
                message = (payload.get("detail") or payload.get("message") or payload.get("error")) if isinstance(payload, dict) else None
                return {"status": "error", "status_code": response.status_code,
                    "error": str(message or f"Yousearch HTTP {response.status_code}").replace(key, "[redacted]")}
            if not isinstance(payload, dict):
                return {"status": "error", "error": "Yousearch returned an unexpected response shape"}
            return {"status": "success", "data": payload}
        except httpx.HTTPError as exc:
            return {"status": "error", "error": str(exc).replace(key, "[redacted]")}
