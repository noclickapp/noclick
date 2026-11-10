"""Tavily web search, extraction, site discovery, and research node.

API reference: https://docs.tavily.com/documentation/api-reference/introduction
Tavily's REST API authenticates with a bearer API key, not OAuth.
"""

from __future__ import annotations

import json
import time
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


API_BASE = "https://api.tavily.com"


def _operation(name: str, category: str, display: str) -> dict[str, Any]:
    return {
        "const": name,
        "ui:hidden": True,
        "x-category": category,
        "x-is-trigger": False,
        "x-display-name": display,
    }


def _choice(values: list[str]) -> dict[str, Any]:
    return {"enum": values, "enumNames": [v.replace("_", " ").title() for v in values], "x-enum-searchable": True}


class TavilyApiKeyCredential(BaseModel):
    """Tavily API key from the account dashboard."""

    credential_type: Literal["tavily_api_key"] = Field(
        "tavily_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Create an API key in your Tavily dashboard.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://app.tavily.com/home"}
    )


class TavilySearchConfig(BaseModel):
    """Search the current web, with optional source and date filters."""

    operation: Literal["search"] = Field("search", title="Search", json_schema_extra=_operation("search", "Search", "Search Web"))
    query: str = Field(..., title="Query", description="Question or search query.")
    search_depth: str = Field("advanced", title="Search Depth", description="Advanced is more relevant and costs two credits; other depths cost one.", json_schema_extra=_choice(["advanced", "basic", "fast", "ultra-fast"]))
    topic: str = Field("general", title="Topic", json_schema_extra=_choice(["general", "news", "finance"]))
    max_results: int = Field(5, ge=0, le=20, title="Maximum Results")
    chunks_per_source: int = Field(3, ge=1, le=3, title="Chunks per Source")
    time_range: Optional[str] = Field(None, title="Time Range", json_schema_extra=_choice(["day", "week", "month", "year"]))
    start_date: Optional[str] = Field(None, title="Start Date", description="YYYY-MM-DD")
    end_date: Optional[str] = Field(None, title="End Date", description="YYYY-MM-DD")
    include_domains: Optional[str] = Field(None, title="Include Domains", description="Comma-separated domains; limits results to these sites.")
    exclude_domains: Optional[str] = Field(None, title="Exclude Domains", description="Comma-separated domains to omit.")
    include_domains_mode: Optional[str] = Field(None, title="Include Domains Mode", json_schema_extra=_choice(["restrict", "prefer"]))
    include_answer: bool = Field(False, title="Include Generated Answer")
    include_raw_content: bool = Field(False, title="Include Full Page Content")
    include_images: bool = Field(False, title="Include Images")
    include_image_descriptions: bool = Field(False, title="Describe Images")
    include_favicon: bool = Field(False, title="Include Favicons")
    include_published_date: bool = Field(False, title="Include Published Date")
    filter_by_published_date: bool = Field(False, title="Require Published Date in Range")
    country: Optional[str] = Field(None, title="Country", description="Country name to boost for general searches.")
    language: Optional[str] = Field(None, title="Language", description="ISO language code or language name.")
    filter_by_language: bool = Field(False, title="Strict Language Filter")
    auto_parameters: bool = Field(False, title="Auto Select Parameters", description="Tavily may select advanced depth, which costs two credits.")
    exact_match: bool = Field(False, title="Exact Phrase Match")
    safe_search: bool = Field(False, title="Safe Search")
    include_usage: bool = Field(True, title="Include Credit Usage")


class TavilyExtractConfig(BaseModel):
    """Extract clean text or Markdown from up to 20 URLs."""

    operation: Literal["extract"] = Field("extract", title="Extract", json_schema_extra=_operation("extract", "Content", "Extract Pages"))
    urls: str = Field(..., title="URLs", description="One URL per line, or comma-separated (maximum 20).", json_schema_extra={"ui:widget": "textarea"})
    query: Optional[str] = Field(None, title="Relevant Content Query", description="Rerank extracted chunks for this intent.")
    chunks_per_source: int = Field(3, ge=1, le=5, title="Chunks per Source")
    extract_depth: str = Field("basic", title="Extract Depth", json_schema_extra=_choice(["basic", "advanced"]))
    format: str = Field("markdown", title="Format", json_schema_extra=_choice(["markdown", "text"]))
    include_images: bool = Field(False, title="Include Images")
    include_favicon: bool = Field(False, title="Include Favicons")
    timeout: Optional[float] = Field(None, ge=1, le=60, title="Timeout (Seconds)")
    include_usage: bool = Field(True, title="Include Credit Usage")


class _TraversalConfig(BaseModel):
    url: str = Field(..., title="Root URL", description="Website to explore, e.g. https://docs.example.com.")
    instructions: Optional[str] = Field(None, title="Instructions", description="Describe which pages matter; this increases mapping credit cost.")
    max_depth: int = Field(1, ge=1, le=5, title="Maximum Depth")
    max_breadth: int = Field(20, ge=1, le=500, title="Maximum Breadth")
    limit: int = Field(50, ge=1, title="Page Limit")
    select_paths: Optional[str] = Field(None, title="Include Path Patterns", description="Regex patterns, one per line.", json_schema_extra={"ui:widget": "textarea"})
    exclude_paths: Optional[str] = Field(None, title="Exclude Path Patterns", description="Regex patterns, one per line.", json_schema_extra={"ui:widget": "textarea"})
    select_domains: Optional[str] = Field(None, title="Include Domain Patterns", description="Regex patterns, one per line.")
    exclude_domains: Optional[str] = Field(None, title="Exclude Domain Patterns", description="Regex patterns, one per line.")
    allow_external: bool = Field(True, title="Include External Links")
    timeout: int = Field(150, ge=10, le=150, title="Tavily Timeout (Seconds)")
    include_usage: bool = Field(True, title="Include Credit Usage")


class TavilyCrawlConfig(_TraversalConfig):
    """Traverse a website and return extracted page content."""

    operation: Literal["crawl"] = Field("crawl", title="Crawl", json_schema_extra=_operation("crawl", "Content", "Crawl Website"))
    chunks_per_source: int = Field(3, ge=1, le=5, title="Chunks per Source")
    extract_depth: str = Field("basic", title="Extract Depth", json_schema_extra=_choice(["basic", "advanced"]))
    format: str = Field("markdown", title="Format", json_schema_extra=_choice(["markdown", "text"]))
    include_images: bool = Field(False, title="Include Images")
    include_favicon: bool = Field(False, title="Include Favicons")


class TavilyMapConfig(_TraversalConfig):
    """Discover a website's URLs without extracting their contents."""

    operation: Literal["map"] = Field("map", title="Map", json_schema_extra=_operation("map", "Content", "Map Website"))


class TavilyCreateResearchConfig(BaseModel):
    """Start an asynchronous cited research report."""

    operation: Literal["create_research"] = Field("create_research", title="Create Research", json_schema_extra=_operation("create_research", "Research", "Start Research"))
    input: str = Field(..., title="Research Task", json_schema_extra={"ui:widget": "textarea"})
    model: str = Field("auto", title="Model", json_schema_extra=_choice(["auto", "mini", "pro"]))
    citation_format: str = Field("numbered", title="Citation Format", json_schema_extra=_choice(["numbered", "mla", "apa", "chicago"]))
    output_length: str = Field("standard", title="Output Length", json_schema_extra=_choice(["short", "standard", "long"]))
    include_domains: Optional[str] = Field(None, title="Preferred Domains", description="Comma-separated, up to 20.")
    exclude_domains: Optional[str] = Field(None, title="Blocked Domains", description="Comma-separated, up to 20.")
    output_schema: Optional[str] = Field(None, title="Output JSON Schema", description="Optional JSON Schema object for structured results.", json_schema_extra={"ui:widget": "textarea"})
    files: Optional[str] = Field(None, title="Attached Files JSON", description="JSON array of up to five {name, data, type} objects; data must be base64 encoded.", json_schema_extra={"ui:widget": "textarea"})


class TavilyGetResearchConfig(BaseModel):
    """Get research status and the completed report by request ID."""

    operation: Literal["get_research"] = Field("get_research", title="Get Research", json_schema_extra=_operation("get_research", "Research", "Get Research Result"))
    request_id: str = Field(..., title="Request ID")
    include_usage: bool = Field(True, title="Include Credit Usage")


class TavilyGetUsageConfig(BaseModel):
    """Get API-key and account usage for connection verification."""

    operation: Literal["get_usage"] = Field("get_usage", title="Get Usage", json_schema_extra=_operation("get_usage", "Account", "Get Usage"))
    project_id: Optional[str] = Field(None, title="Project ID", description="Optional project whose usage to read.")


class TavilySubmitFeedbackConfig(BaseModel):
    """Submit relevance feedback about a search request or session."""

    operation: Literal["submit_feedback"] = Field("submit_feedback", title="Submit Feedback", json_schema_extra=_operation("submit_feedback", "Account", "Submit Search Feedback"))
    request_id: Optional[str] = Field(None, title="Search Request ID")
    session_id: Optional[str] = Field(None, title="Session ID")
    agent_score: Optional[str] = Field(None, title="Agent Score", description="Numeric score or short label.")
    human_score: Optional[str] = Field(None, title="Human Score", description="Numeric score or short label.")
    comment: Optional[str] = Field(None, title="Comment", json_schema_extra={"ui:widget": "textarea"})
    response_delivered: Optional[str] = Field(None, title="Answer Delivered", json_schema_extra={"ui:widget": "textarea"})
    used_ids: Optional[str] = Field(None, title="Used Result IDs", description="Comma-separated result IDs.")
    used_urls: Optional[str] = Field(None, title="Used Result URLs", description="One URL per line.", json_schema_extra={"ui:widget": "textarea"})
    used_citations: Optional[str] = Field(None, title="Used Citations", description="One quoted content snippet per line.", json_schema_extra={"ui:widget": "textarea"})
    extra_scores: Optional[str] = Field(None, title="Extra Scores JSON", description="Array of {label, value} objects.", json_schema_extra={"ui:widget": "textarea"})
    urls_scores: Optional[str] = Field(None, title="Result Scores JSON", description="Array of per-result score objects.", json_schema_extra={"ui:widget": "textarea"})


class TavilyGetLogsConfig(BaseModel):
    """Read per-request usage logs (paid Tavily plans)."""

    operation: Literal["get_logs"] = Field("get_logs", title="Get Logs", json_schema_extra=_operation("get_logs", "Account", "Get Request Logs"))
    limit: int = Field(20, ge=1, title="Limit")
    start_date: Optional[str] = Field(None, title="Start Date", description="YYYY-MM-DD")
    end_date: Optional[str] = Field(None, title="End Date", description="YYYY-MM-DD")
    endpoints: Optional[str] = Field(None, title="Endpoints", description="Comma-separated endpoint names.")
    project_id: Optional[str] = Field(None, title="Project ID")
    filter_by_api_key: bool = Field(True, title="Only This API Key")


class TavilyGetOrgUsageConfig(BaseModel):
    """Read organization usage as an organization owner."""

    operation: Literal["get_org_usage"] = Field("get_org_usage", title="Get Organization Usage", json_schema_extra=_operation("get_org_usage", "Account", "Get Organization Usage"))
    organization_name: str = Field(..., title="Organization Name", description="Exact case-sensitive organization name.")
    start_date: Optional[str] = Field(None, title="Start Date", description="YYYY-MM-DD")
    end_date: Optional[str] = Field(None, title="End Date", description="YYYY-MM-DD")
    project_id: Optional[str] = Field(None, title="Project ID")
    depth: Optional[str] = Field(None, title="Depth", json_schema_extra=_choice(["basic", "advanced", "fast", "ultra-fast", "mini", "pro", "auto"]))


TavilyConfig = Annotated[
    Union[
        TavilySearchConfig,
        TavilyExtractConfig,
        TavilyCrawlConfig,
        TavilyMapConfig,
        TavilyCreateResearchConfig,
        TavilyGetResearchConfig,
        TavilyGetUsageConfig,
        TavilySubmitFeedbackConfig,
        TavilyGetLogsConfig,
        TavilyGetOrgUsageConfig,
    ],
    Discriminator("operation"),
]


class TavilyNodeConfig(NodeConfig[TavilyConfig, TavilyApiKeyCredential]):
    pass


def _string_list(value: Optional[str], *, lines_only: bool = False) -> Optional[list[str]]:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except ValueError:
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    separator = "\n" if lines_only else ","
    normalized = value.replace("\r", "")
    if not lines_only:
        normalized = normalized.replace("\n", ",")
    return [item.strip() for item in normalized.split(separator) if item.strip()]


def _body(config: BaseModel) -> dict[str, Any]:
    data = config.model_dump(exclude={"operation"}, exclude_none=True)
    for name in ("urls", "include_domains", "exclude_domains", "select_paths", "exclude_paths", "select_domains", "used_ids", "used_urls", "used_citations", "endpoints"):
        if name in data and isinstance(data[name], str):
            data[name] = _string_list(data[name], lines_only=name in {"select_paths", "exclude_paths", "select_domains", "used_urls", "used_citations"})
    if isinstance(config, TavilyExtractConfig):
        if not data.get("urls"):
            raise ValueError("At least one URL is required")
        if len(data["urls"]) > 20:
            raise ValueError("Tavily Extract accepts at most 20 URLs")
    if isinstance(config, TavilyCreateResearchConfig):
        for key, label, expected_type in (("output_schema", "Output JSON Schema", dict), ("files", "Attached Files", list)):
            if data.get(key):
                try:
                    data[key] = json.loads(data[key])
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{label} must be valid JSON") from exc
                if not isinstance(data[key], expected_type):
                    raise ValueError(f"{label} must be a JSON {expected_type.__name__}")
        if len(data.get("files") or []) > 5:
            raise ValueError("Attached Files accepts at most five files")
        for key in ("include_domains", "exclude_domains"):
            if len(data.get(key) or []) > 20:
                raise ValueError(f"{key} accepts at most 20 domains")
        data["stream"] = False  # workflow execution expects JSON, not SSE
    if isinstance(config, TavilySubmitFeedbackConfig):
        if not data.get("request_id") and not data.get("session_id"):
            raise ValueError("A search request ID or session ID is required")
        for key in ("extra_scores", "urls_scores"):
            if data.get(key):
                try:
                    data[key] = json.loads(data[key])
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{key} must be valid JSON") from exc
    return data


class TavilyNode(WorkflowNode):
    """Tavily REST API operations for web-grounded workflows."""
    integration_type = "automation-tavily"
    credential_provider_labels = {"tavily": "Tavily Account"}

    edit_examples = [
        "Search the web for current information about a topic",
        "Extract clean text from these URLs",
        "Map a documentation site before crawling it",
        "Create a cited research report and retrieve it by request ID",
    ]

    connection_evidence = ConnectionEvidence(
        identity_operation="get_usage", noun="Tavily account", proves="reachability"
    )

    @classmethod
    def get_config_model(cls):
        return TavilyNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config = self.config
        if not isinstance(config, TavilyNodeConfig):
            raise ValueError("Valid Tavily node configuration is required")
        if not config.credentials or not config.credentials.api_key:
            raise ValueError("Connect a Tavily API key before running this node")

        op = config.config
        action = op.operation
        started = time.monotonic()
        if action == "get_research":
            method, path, body = "GET", f"/research/{quote(op.request_id, safe='')}", None
            params = {"include_usage": op.include_usage}
        elif action == "get_usage":
            method, path, body, params = "GET", "/usage", None, None
        else:
            method = "POST"
            path = {
                "create_research": "/research",
                "submit_feedback": "/feedback",
                "get_logs": "/logs",
                "get_org_usage": "/org-usage",
            }.get(action, f"/{action}")
            body, params = _body(op), None

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.request(
                    method,
                    f"{API_BASE}{path}",
                    headers={
                        "Authorization": f"Bearer {config.credentials.api_key}",
                        **({"X-Project-ID": op.project_id} if isinstance(op, TavilyGetUsageConfig) and op.project_id else {}),
                    },
                    json=body,
                    params=params,
                )
            elapsed = round((time.monotonic() - started) * 1000, 2)
            try:
                payload = response.json()
            except ValueError:
                payload = {"message": response.text[:1000]}
            if response.is_error:
                message = payload.get("detail") or payload.get("error") or payload.get("message") if isinstance(payload, dict) else str(payload)
                return {"status": "error", "action": action, "status_code": response.status_code, "error": str(message), "timing_ms": {"api_request": elapsed}}
            return {"status": "success", "action": action, "data": payload, "timing_ms": {"api_request": elapsed}}
        except httpx.HTTPError as exc:
            return {"status": "error", "action": action, "status_code": 500, "error": str(exc), "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)}}
