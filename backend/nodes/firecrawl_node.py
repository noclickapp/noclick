"""
Firecrawl web scraping & crawling automation node.

Provides workflow integration with the Firecrawl v2 REST API for operations:
- Scraping: scrape a URL, get scrape status, batch scrape, get batch status/errors, cancel batch
- Crawling: crawl a site, get status/errors, cancel, list active, params preview
- Discovery: map a website, search the web
- Extraction: extract structured data, get extract status, autonomous agent, agent status/cancel
- Research: GitHub history and paper search / lookup endpoints
- Files: parse a file
- Interact sessions: create/list/execute/delete interactive sessions, attach to scrape jobs
- Monitors: create/list/update/run/delete monitors and inspect checks
- Usage & support: team usage/activity, endpoint feedback, support agent, docs search
- Webhook Triggers: receive async crawl / batch scrape / agent / monitor events

Authentication: API Key (Bearer token). Keys start with `fc-`.
API Base URL: https://api.firecrawl.dev/v2
Documentation: https://docs.firecrawl.dev/api-reference/v2-introduction

Crawl, batch scrape, extract and agent are asynchronous — the POST returns a
job `id` and you poll the GET status endpoint (or use webhooks) for results.
Scrape, map and search are synchronous.
"""

import json
import logging
import os
import time
from urllib.parse import urlparse
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import guarded_async_client
from utils.webhook_signatures import verify_hmac_sha256_hex

logger = logging.getLogger(__name__)

FIRECRAWL_API_BASE = "https://api.firecrawl.dev/v2"
FIRECRAWL_WEBHOOK_EVENT_ALL = "*"

FIRECRAWL_CRAWL_WEBHOOK_EVENTS: List[str] = [
    "crawl.started",
    "crawl.page",
    "crawl.completed",
]
FIRECRAWL_CRAWL_WEBHOOK_EVENT_NAMES: List[str] = [
    "Crawl started",
    "Crawl page",
    "Crawl completed",
]

FIRECRAWL_BATCH_SCRAPE_WEBHOOK_EVENTS: List[str] = [
    "batch_scrape.started",
    "batch_scrape.page",
    "batch_scrape.completed",
]
FIRECRAWL_BATCH_SCRAPE_WEBHOOK_EVENT_NAMES: List[str] = [
    "Batch scrape started",
    "Batch scrape page",
    "Batch scrape completed",
]

FIRECRAWL_AGENT_WEBHOOK_EVENTS: List[str] = [
    "agent.started",
    "agent.action",
    "agent.completed",
    "agent.failed",
    "agent.cancelled",
]
FIRECRAWL_AGENT_WEBHOOK_EVENT_NAMES: List[str] = [
    "Agent started",
    "Agent action",
    "Agent completed",
    "Agent failed",
    "Agent cancelled",
]

FIRECRAWL_MONITOR_WEBHOOK_EVENTS: List[str] = [
    "monitor.page",
    "monitor.check.completed",
]
FIRECRAWL_MONITOR_WEBHOOK_EVENT_NAMES: List[str] = [
    "Monitor page",
    "Monitor check completed",
]

FIRECRAWL_PUBLISHED_WEBHOOK_EVENTS: List[str] = [
    FIRECRAWL_WEBHOOK_EVENT_ALL,
    *FIRECRAWL_CRAWL_WEBHOOK_EVENTS,
    *FIRECRAWL_BATCH_SCRAPE_WEBHOOK_EVENTS,
    *FIRECRAWL_AGENT_WEBHOOK_EVENTS,
    *FIRECRAWL_MONITOR_WEBHOOK_EVENTS,
]
FIRECRAWL_PUBLISHED_WEBHOOK_EVENT_NAMES: List[str] = [
    "Any published Firecrawl webhook",
    *FIRECRAWL_CRAWL_WEBHOOK_EVENT_NAMES,
    *FIRECRAWL_BATCH_SCRAPE_WEBHOOK_EVENT_NAMES,
    *FIRECRAWL_AGENT_WEBHOOK_EVENT_NAMES,
    *FIRECRAWL_MONITOR_WEBHOOK_EVENT_NAMES,
]

FIRECRAWL_TRIGGER_FAMILY_PREFIXES: Dict[str, Optional[str]] = {
    "receive_webhook": None,
    "on_crawl_event": "crawl.",
    "on_batch_scrape_event": "batch_scrape.",
    "on_agent_event": "agent.",
    "on_monitor_event": "monitor.",
}


# ============================================================================
# Credential Schema
# ============================================================================


class FirecrawlAPIKeyCredential(BaseModel):
    """API Key credential for Firecrawl."""

    credential_type: Literal["firecrawl_api_key"] = Field(
        "firecrawl_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Firecrawl API key (starts with fc-) from the dashboard API Keys page",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://www.firecrawl.dev/app/api-keys"}
    )


FirecrawlCredential = FirecrawlAPIKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class FirecrawlScrapeConfig(BaseModel):
    """Scrape a single URL and return content as markdown / HTML / links."""

    operation: Literal["scrape"] = Field(
        "scrape",
        json_schema_extra={
            "const": "scrape",
            "ui:hidden": True,
            "x-category": "Scraping",
            "x-is-trigger": False,
            "x-display-name": "Scrape URL",
        },
        title="Scrape URL",
    )
    url: str = Field(..., title="URL", description="The URL to scrape")
    formats: str = Field(
        "markdown",
        title="Formats",
        description="Output formats to return, comma-separated",
        json_schema_extra={
            "enum": ["markdown", "html", "rawHtml", "links", "screenshot", "summary"],
            "x-enum-searchable": True,
        },
    )
    only_main_content: str = Field(
        "true",
        title="Only Main Content",
        description="Strip navigation, footers and other boilerplate",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    wait_for: Optional[str] = Field(
        None,
        title="Wait For (ms)",
        description="Milliseconds to wait for the page to render before scraping",
    )


class FirecrawlGetScrapeConfig(BaseModel):
    """Poll an async scrape job by id."""

    operation: Literal["get_scrape"] = Field(
        "get_scrape",
        json_schema_extra={
            "const": "get_scrape",
            "ui:hidden": True,
            "x-category": "Scraping",
            "x-is-trigger": False,
            "x-display-name": "Get Scrape Status",
        },
        title="Get Scrape Status",
    )
    job_id: str = Field(..., title="Job ID", description="The scrape job id")


class FirecrawlBatchScrapeConfig(BaseModel):
    """Submit many URLs to scrape asynchronously; returns a job id."""

    operation: Literal["batch_scrape"] = Field(
        "batch_scrape",
        json_schema_extra={
            "const": "batch_scrape",
            "ui:hidden": True,
            "x-category": "Scraping",
            "x-is-trigger": False,
            "x-display-name": "Batch Scrape",
        },
        title="Batch Scrape",
    )
    urls: str = Field(
        ..., title="URLs", description="URLs to scrape, comma-separated"
    )
    formats: str = Field(
        "markdown",
        title="Formats",
        description="Output formats to return, comma-separated",
        json_schema_extra={
            "enum": ["markdown", "html", "rawHtml", "links", "screenshot", "summary"],
            "x-enum-searchable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        description="Optional URL to receive batch_scrape job events",
    )
    webhook_events: Optional[str] = Field(
        None,
        title="Webhook Events",
        description="Optional comma-separated webhook events to send: started, page, completed, failed",
    )
    webhook_headers_json: Optional[str] = Field(
        None,
        title="Webhook Headers (JSON)",
        description='Optional JSON object of headers to send with webhook deliveries, e.g. `{\"X-Source\":\"noclick\"}`',
        json_schema_extra={"ui:widget": "textarea"},
    )
    webhook_metadata_json: Optional[str] = Field(
        None,
        title="Webhook Metadata (JSON)",
        description='Optional JSON object echoed back in webhook payload metadata, e.g. `{\"workflow\":\"demo\"}`',
        json_schema_extra={"ui:widget": "textarea"},
    )


class FirecrawlGetBatchScrapeConfig(BaseModel):
    """Poll a batch scrape job by id."""

    operation: Literal["get_batch_scrape"] = Field(
        "get_batch_scrape",
        json_schema_extra={
            "const": "get_batch_scrape",
            "ui:hidden": True,
            "x-category": "Scraping",
            "x-is-trigger": False,
            "x-display-name": "Get Batch Scrape Status",
        },
        title="Get Batch Scrape Status",
    )
    job_id: str = Field(..., title="Job ID", description="The batch scrape job id")


class FirecrawlCancelBatchScrapeConfig(BaseModel):
    """Cancel an in-progress batch scrape job."""

    operation: Literal["cancel_batch_scrape"] = Field(
        "cancel_batch_scrape",
        json_schema_extra={
            "const": "cancel_batch_scrape",
            "ui:hidden": True,
            "x-category": "Scraping",
            "x-is-trigger": False,
            "x-display-name": "Cancel Batch Scrape",
        },
        title="Cancel Batch Scrape",
    )
    job_id: str = Field(..., title="Job ID", description="The batch scrape job id")


class FirecrawlGetBatchScrapeErrorsConfig(BaseModel):
    """Retrieve per-URL errors for a batch scrape job."""

    operation: Literal["get_batch_scrape_errors"] = Field(
        "get_batch_scrape_errors",
        json_schema_extra={
            "const": "get_batch_scrape_errors",
            "ui:hidden": True,
            "x-category": "Scraping",
            "x-is-trigger": False,
            "x-display-name": "Get Batch Scrape Errors",
        },
        title="Get Batch Scrape Errors",
    )
    job_id: str = Field(..., title="Job ID", description="The batch scrape job id")


class FirecrawlCrawlConfig(BaseModel):
    """Start an async crawl of a site from a starting URL; returns a job id."""

    operation: Literal["crawl"] = Field(
        "crawl",
        json_schema_extra={
            "const": "crawl",
            "ui:hidden": True,
            "x-category": "Crawling",
            "x-is-trigger": False,
            "x-display-name": "Crawl Website",
        },
        title="Crawl Website",
    )
    url: str = Field(..., title="Start URL", description="The URL to start crawling from")
    limit: Optional[str] = Field(
        None, title="Limit", description="Maximum number of pages to crawl"
    )
    max_discovery_depth: Optional[str] = Field(
        None, title="Max Depth", description="Maximum link depth to follow from the start URL"
    )
    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        description="Optional URL to receive crawl job events",
    )
    webhook_events: Optional[str] = Field(
        None,
        title="Webhook Events",
        description="Optional comma-separated webhook events to send: started, page, completed, failed",
    )
    webhook_headers_json: Optional[str] = Field(
        None,
        title="Webhook Headers (JSON)",
        description='Optional JSON object of headers to send with webhook deliveries, e.g. `{\"X-Source\":\"noclick\"}`',
        json_schema_extra={"ui:widget": "textarea"},
    )
    webhook_metadata_json: Optional[str] = Field(
        None,
        title="Webhook Metadata (JSON)",
        description='Optional JSON object echoed back in webhook payload metadata, e.g. `{\"workflow\":\"demo\"}`',
        json_schema_extra={"ui:widget": "textarea"},
    )


class FirecrawlGetCrawlConfig(BaseModel):
    """Poll a crawl job's status by id."""

    operation: Literal["get_crawl"] = Field(
        "get_crawl",
        json_schema_extra={
            "const": "get_crawl",
            "ui:hidden": True,
            "x-category": "Crawling",
            "x-is-trigger": False,
            "x-display-name": "Get Crawl Status",
        },
        title="Get Crawl Status",
    )
    job_id: str = Field(..., title="Job ID", description="The crawl job id")


class FirecrawlCancelCrawlConfig(BaseModel):
    """Cancel an in-progress crawl job."""

    operation: Literal["cancel_crawl"] = Field(
        "cancel_crawl",
        json_schema_extra={
            "const": "cancel_crawl",
            "ui:hidden": True,
            "x-category": "Crawling",
            "x-is-trigger": False,
            "x-display-name": "Cancel Crawl",
        },
        title="Cancel Crawl",
    )
    job_id: str = Field(..., title="Job ID", description="The crawl job id")


class FirecrawlGetCrawlErrorsConfig(BaseModel):
    """Retrieve per-URL errors and robots.txt-blocked URLs for a crawl job."""

    operation: Literal["get_crawl_errors"] = Field(
        "get_crawl_errors",
        json_schema_extra={
            "const": "get_crawl_errors",
            "ui:hidden": True,
            "x-category": "Crawling",
            "x-is-trigger": False,
            "x-display-name": "Get Crawl Errors",
        },
        title="Get Crawl Errors",
    )
    job_id: str = Field(..., title="Job ID", description="The crawl job id")


class FirecrawlListActiveCrawlsConfig(BaseModel):
    """List all currently running crawl jobs for the account."""

    operation: Literal["list_active_crawls"] = Field(
        "list_active_crawls",
        json_schema_extra={
            "const": "list_active_crawls",
            "ui:hidden": True,
            "x-category": "Crawling",
            "x-is-trigger": False,
            "x-display-name": "List Active Crawls",
        },
        title="List Active Crawls",
    )


class FirecrawlCrawlParamsPreviewConfig(BaseModel):
    """Generate suggested crawl parameters from a natural-language prompt + URL."""

    operation: Literal["crawl_params_preview"] = Field(
        "crawl_params_preview",
        json_schema_extra={
            "const": "crawl_params_preview",
            "ui:hidden": True,
            "x-category": "Crawling",
            "x-is-trigger": False,
            "x-display-name": "Crawl Params Preview",
        },
        title="Crawl Params Preview",
    )
    url: str = Field(..., title="URL", description="The URL to generate crawl params for")
    prompt: str = Field(
        ..., title="Prompt", description="Natural-language description of what to crawl"
    )


class FirecrawlMapConfig(BaseModel):
    """Quickly return a complete list of URLs discovered on a website."""

    operation: Literal["map"] = Field(
        "map",
        json_schema_extra={
            "const": "map",
            "ui:hidden": True,
            "x-category": "Discovery",
            "x-is-trigger": False,
            "x-display-name": "Map Website",
        },
        title="Map Website",
    )
    url: str = Field(..., title="URL", description="The website to map")
    search: Optional[str] = Field(
        None, title="Search", description="Filter discovered URLs by this search term"
    )
    limit: Optional[str] = Field(
        None, title="Limit", description="Maximum number of URLs to return"
    )


class FirecrawlSearchConfig(BaseModel):
    """Web search returning results, optionally with full-page content scraped."""

    operation: Literal["search"] = Field(
        "search",
        json_schema_extra={
            "const": "search",
            "ui:hidden": True,
            "x-category": "Discovery",
            "x-is-trigger": False,
            "x-display-name": "Search the Web",
        },
        title="Search the Web",
    )
    query: str = Field(..., title="Query", description="The search query")
    limit: Optional[str] = Field(
        None, title="Limit", description="Maximum number of results to return"
    )
    scrape_content: str = Field(
        "false",
        title="Scrape Result Content",
        description="Also scrape full page content for each result",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class FirecrawlSearchResearchGithubConfig(BaseModel):
    """Search GitHub history."""

    operation: Literal["search_research_github"] = Field(
        "search_research_github",
        json_schema_extra={
            "const": "search_research_github",
            "ui:hidden": True,
            "x-category": "Research",
            "x-is-trigger": False,
            "x-display-name": "Search GitHub History",
        },
        title="Search GitHub History",
    )
    query: str = Field(..., title="Query", description="Research query")
    k: Optional[str] = Field(
        None, title="Limit", description="Maximum number of results to return"
    )


class FirecrawlSearchResearchPapersConfig(BaseModel):
    """Search academic papers."""

    operation: Literal["search_research_papers"] = Field(
        "search_research_papers",
        json_schema_extra={
            "const": "search_research_papers",
            "ui:hidden": True,
            "x-category": "Research",
            "x-is-trigger": False,
            "x-display-name": "Search Papers",
        },
        title="Search Papers",
    )
    query: str = Field(..., title="Query", description="Research query")
    k: Optional[str] = Field(None, title="Limit", description="Maximum papers to return")
    authors: Optional[str] = Field(
        None, title="Authors", description="Author names to filter by"
    )
    categories: Optional[str] = Field(
        None, title="Categories", description="Comma-separated paper categories"
    )
    from_date: Optional[str] = Field(
        None, title="From Date", description="Lower ISO 8601 publication date bound"
    )
    to_date: Optional[str] = Field(
        None, title="To Date", description="Upper ISO 8601 publication date bound"
    )


class FirecrawlGetResearchPaperConfig(BaseModel):
    """Inspect or read a paper."""

    operation: Literal["get_research_paper"] = Field(
        "get_research_paper",
        json_schema_extra={
            "const": "get_research_paper",
            "ui:hidden": True,
            "x-category": "Research",
            "x-is-trigger": False,
            "x-display-name": "Get Paper",
        },
        title="Get Paper",
    )
    paper_id: str = Field(..., title="Paper ID", description="Paper identifier")
    query: Optional[str] = Field(
        None, title="Query", description="Optional refinement query for the paper lookup"
    )
    k: Optional[str] = Field(None, title="Limit", description="Optional result limit")


class FirecrawlGetSimilarResearchPapersConfig(BaseModel):
    """Find related papers."""

    operation: Literal["get_similar_research_papers"] = Field(
        "get_similar_research_papers",
        json_schema_extra={
            "const": "get_similar_research_papers",
            "ui:hidden": True,
            "x-category": "Research",
            "x-is-trigger": False,
            "x-display-name": "Find Related Papers",
        },
        title="Find Related Papers",
    )
    paper_id: str = Field(..., title="Paper ID", description="Paper identifier")
    intent: str = Field(
        ...,
        title="Intent",
        description="Natural-language intent for ranking or filtering related papers",
    )
    mode: str = Field(
        "similar",
        title="Mode",
        description="Relationship mode for related papers",
        json_schema_extra={
            "enum": ["similar", "citers", "references"],
            "x-enum-searchable": True,
        },
    )
    k: Optional[str] = Field(None, title="Limit", description="Maximum related papers to return")
    rerank: str = Field(
        "false",
        title="Rerank",
        description="Whether to rerank the related papers",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    anchor: Optional[str] = Field(
        None, title="Anchor", description="Optional anchor text for the similarity search"
    )


class FirecrawlExtractConfig(BaseModel):
    """LLM-powered structured extraction from URLs (async; returns a job id).

    Deprecated by Firecrawl in favor of the agent operation.
    """

    operation: Literal["extract"] = Field(
        "extract",
        json_schema_extra={
            "const": "extract",
            "ui:hidden": True,
            "x-category": "Extraction",
            "x-is-trigger": False,
            "x-display-name": "Extract Structured Data",
        },
        title="Extract Structured Data",
    )
    urls: str = Field(
        ..., title="URLs", description="URLs to extract from, comma-separated"
    )
    prompt: Optional[str] = Field(
        None, title="Prompt", description="Natural-language description of the data to extract"
    )
    output_schema: Optional[str] = Field(
        None,
        title="JSON Schema",
        description="JSON schema describing the structured output (as JSON text)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        description="Optional URL to receive extract job events",
    )
    webhook_events: Optional[str] = Field(
        None,
        title="Webhook Events",
        description="Optional comma-separated webhook events to send, if enabled for your Firecrawl account",
    )
    webhook_headers_json: Optional[str] = Field(
        None,
        title="Webhook Headers (JSON)",
        description='Optional JSON object of headers to send with webhook deliveries, e.g. `{\"X-Source\":\"noclick\"}`',
        json_schema_extra={"ui:widget": "textarea"},
    )
    webhook_metadata_json: Optional[str] = Field(
        None,
        title="Webhook Metadata (JSON)",
        description='Optional JSON object echoed back in webhook payload metadata, e.g. `{\"workflow\":\"demo\"}`',
        json_schema_extra={"ui:widget": "textarea"},
    )


class FirecrawlGetExtractConfig(BaseModel):
    """Poll an extract job by id. Deprecated."""

    operation: Literal["get_extract"] = Field(
        "get_extract",
        json_schema_extra={
            "const": "get_extract",
            "ui:hidden": True,
            "x-category": "Extraction",
            "x-is-trigger": False,
            "x-display-name": "Get Extract Status",
        },
        title="Get Extract Status",
    )
    job_id: str = Field(..., title="Job ID", description="The extract job id")


class FirecrawlAgentConfig(BaseModel):
    """Autonomous AI web data gathering from a prompt + schema (async)."""

    operation: Literal["agent"] = Field(
        "agent",
        json_schema_extra={
            "const": "agent",
            "ui:hidden": True,
            "x-category": "Extraction",
            "x-is-trigger": False,
            "x-display-name": "Agent (Autonomous Extract)",
        },
        title="Agent (Autonomous Extract)",
    )
    prompt: str = Field(
        ..., title="Prompt", description="Natural-language description of the data to gather"
    )
    output_schema: Optional[str] = Field(
        None,
        title="JSON Schema",
        description="JSON schema describing the structured output (as JSON text)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    urls: Optional[str] = Field(
        None,
        title="Seed URLs",
        description="Optional seed URLs to ground the search, comma-separated",
    )
    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        description="Optional URL to receive agent job events",
    )
    webhook_events: Optional[str] = Field(
        None,
        title="Webhook Events",
        description="Optional comma-separated webhook events to send: started, action, completed, failed, cancelled",
    )
    webhook_headers_json: Optional[str] = Field(
        None,
        title="Webhook Headers (JSON)",
        description='Optional JSON object of headers to send with webhook deliveries, e.g. `{\"X-Source\":\"noclick\"}`',
        json_schema_extra={"ui:widget": "textarea"},
    )
    webhook_metadata_json: Optional[str] = Field(
        None,
        title="Webhook Metadata (JSON)",
        description='Optional JSON object echoed back in webhook payload metadata, e.g. `{\"workflow\":\"demo\"}`',
        json_schema_extra={"ui:widget": "textarea"},
    )


class FirecrawlGetAgentConfig(BaseModel):
    """Poll an agent job by id."""

    operation: Literal["get_agent"] = Field(
        "get_agent",
        json_schema_extra={
            "const": "get_agent",
            "ui:hidden": True,
            "x-category": "Extraction",
            "x-is-trigger": False,
            "x-display-name": "Get Agent Status",
        },
        title="Get Agent Status",
    )
    job_id: str = Field(..., title="Job ID", description="The agent job id")


class FirecrawlCancelAgentConfig(BaseModel):
    """Cancel an in-progress agent job."""

    operation: Literal["cancel_agent"] = Field(
        "cancel_agent",
        json_schema_extra={
            "const": "cancel_agent",
            "ui:hidden": True,
            "x-category": "Extraction",
            "x-is-trigger": False,
            "x-display-name": "Cancel Agent",
        },
        title="Cancel Agent",
    )
    job_id: str = Field(..., title="Job ID", description="The agent job id")


class FirecrawlParseConfig(BaseModel):
    """Parse a remote file (PDF, DOCX, etc.) into markdown or other formats."""

    operation: Literal["parse"] = Field(
        "parse",
        json_schema_extra={
            "const": "parse",
            "ui:hidden": True,
            "x-category": "Files",
            "x-is-trigger": False,
            "x-display-name": "Parse a File",
        },
        title="Parse a File",
    )
    url: str = Field(
        ..., title="File URL", description="The URL of the file to parse"
    )
    formats: str = Field(
        "markdown",
        title="Formats",
        description="Output formats to return, comma-separated",
        json_schema_extra={
            "enum": ["markdown", "html", "rawHtml"],
            "x-enum-searchable": True,
        },
    )


class FirecrawlCreateInteractConfig(BaseModel):
    """Create a Firecrawl interact session."""

    operation: Literal["create_interact_session"] = Field(
        "create_interact_session",
        json_schema_extra={
            "const": "create_interact_session",
            "ui:hidden": True,
            "x-category": "Interact",
            "x-is-trigger": False,
            "x-display-name": "Create Interact Session",
        },
        title="Create Interact Session",
    )
    ttl: Optional[str] = Field(
        None, title="TTL (seconds)", description="Total time-to-live for the interact session"
    )
    activity_ttl: Optional[str] = Field(
        None,
        title="Activity TTL (seconds)",
        description="Idle timeout before the interact session is destroyed",
    )
    stream_web_view: str = Field(
        "true",
        title="Stream Web View",
        description="Whether to stream a live browser view",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    profile_name: Optional[str] = Field(
        None,
        title="Profile Name",
        description="Persistent profile name to reuse browser storage across sessions",
    )
    profile_save_changes: str = Field(
        "true",
        title="Save Profile Changes",
        description="Whether profile changes should be saved when the session closes",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class FirecrawlListInteractConfig(BaseModel):
    """List active Firecrawl interact sessions."""

    operation: Literal["list_interact_sessions"] = Field(
        "list_interact_sessions",
        json_schema_extra={
            "const": "list_interact_sessions",
            "ui:hidden": True,
            "x-category": "Interact",
            "x-is-trigger": False,
            "x-display-name": "List Interact Sessions",
        },
        title="List Interact Sessions",
    )
    status: Optional[str] = Field(
        None, title="Status", description="Optional interact session status filter"
    )


class FirecrawlExecuteInteractConfig(BaseModel):
    """Execute code in a Firecrawl interact session."""

    operation: Literal["execute_interact_session"] = Field(
        "execute_interact_session",
        json_schema_extra={
            "const": "execute_interact_session",
            "ui:hidden": True,
            "x-category": "Interact",
            "x-is-trigger": False,
            "x-display-name": "Execute in Interact Session",
        },
        title="Execute in Interact Session",
    )
    session_id: str = Field(
        ..., title="Session ID", description="The interact session id"
    )
    code: str = Field(
        ...,
        title="Code",
        description="Code to execute in the interact session",
        json_schema_extra={"ui:widget": "textarea"},
    )
    language: str = Field(
        "node",
        title="Language",
        description="Execution language",
        json_schema_extra={
            "enum": ["python", "node", "bash"],
            "x-enum-searchable": True,
        },
    )
    timeout: Optional[str] = Field(
        None, title="Timeout (seconds)", description="Execution timeout in seconds"
    )


class FirecrawlDeleteInteractConfig(BaseModel):
    """Delete a Firecrawl interact session."""

    operation: Literal["delete_interact_session"] = Field(
        "delete_interact_session",
        json_schema_extra={
            "const": "delete_interact_session",
            "ui:hidden": True,
            "x-category": "Interact",
            "x-is-trigger": False,
            "x-display-name": "Delete Interact Session",
        },
        title="Delete Interact Session",
    )
    session_id: str = Field(
        ..., title="Session ID", description="The interact session id"
    )


class FirecrawlScrapeInteractConfig(BaseModel):
    """Execute code in the scrape-bound interact session."""

    operation: Literal["scrape_interact"] = Field(
        "scrape_interact",
        json_schema_extra={
            "const": "scrape_interact",
            "ui:hidden": True,
            "x-category": "Interact",
            "x-is-trigger": False,
            "x-display-name": "Interact With Scrape Job",
        },
        title="Interact With Scrape Job",
    )
    job_id: str = Field(..., title="Job ID", description="The scrape job id")
    code: str = Field(
        ...,
        title="Code",
        description="Code to execute in the scrape-bound interact session",
        json_schema_extra={"ui:widget": "textarea"},
    )
    language: str = Field(
        "node",
        title="Language",
        description="Execution language",
        json_schema_extra={
            "enum": ["python", "node", "bash"],
            "x-enum-searchable": True,
        },
    )
    timeout: Optional[str] = Field(
        None, title="Timeout (seconds)", description="Execution timeout in seconds"
    )
    origin: Optional[str] = Field(
        None, title="Origin", description="Optional origin label for execution telemetry"
    )


class FirecrawlStopScrapeInteractConfig(BaseModel):
    """Stop the scrape-bound interact session."""

    operation: Literal["stop_scrape_interact"] = Field(
        "stop_scrape_interact",
        json_schema_extra={
            "const": "stop_scrape_interact",
            "ui:hidden": True,
            "x-category": "Interact",
            "x-is-trigger": False,
            "x-display-name": "Stop Scrape Interaction",
        },
        title="Stop Scrape Interaction",
    )
    job_id: str = Field(..., title="Job ID", description="The scrape job id")


class FirecrawlCreditUsageConfig(BaseModel):
    """Return remaining credits for the account."""

    operation: Literal["credit_usage"] = Field(
        "credit_usage",
        json_schema_extra={
            "const": "credit_usage",
            "ui:hidden": True,
            "x-category": "Usage",
            "x-is-trigger": False,
            "x-display-name": "Get Credit Usage",
        },
        title="Get Credit Usage",
    )


class FirecrawlTokenUsageConfig(BaseModel):
    """Return LLM token usage (for extract/agent operations)."""

    operation: Literal["token_usage"] = Field(
        "token_usage",
        json_schema_extra={
            "const": "token_usage",
            "ui:hidden": True,
            "x-category": "Usage",
            "x-is-trigger": False,
            "x-display-name": "Get Token Usage",
        },
        title="Get Token Usage",
    )


class FirecrawlCreditUsageHistoricalConfig(BaseModel):
    """Return historical credit usage for the account's team."""

    operation: Literal["credit_usage_historical"] = Field(
        "credit_usage_historical",
        json_schema_extra={
            "const": "credit_usage_historical",
            "ui:hidden": True,
            "x-category": "Usage",
            "x-is-trigger": False,
            "x-display-name": "Get Historical Credit Usage",
        },
        title="Get Historical Credit Usage",
    )
    by_api_key: str = Field(
        "false",
        title="Group By API Key",
        description="Return historical usage grouped by API key",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class FirecrawlTokenUsageHistoricalConfig(BaseModel):
    """Return historical token usage for the account's team."""

    operation: Literal["token_usage_historical"] = Field(
        "token_usage_historical",
        json_schema_extra={
            "const": "token_usage_historical",
            "ui:hidden": True,
            "x-category": "Usage",
            "x-is-trigger": False,
            "x-display-name": "Get Historical Token Usage",
        },
        title="Get Historical Token Usage",
    )
    by_api_key: str = Field(
        "false",
        title="Group By API Key",
        description="Return historical usage grouped by API key",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class FirecrawlQueueStatusConfig(BaseModel):
    """Inspect the account's current job queue depth/status."""

    operation: Literal["queue_status"] = Field(
        "queue_status",
        json_schema_extra={
            "const": "queue_status",
            "ui:hidden": True,
            "x-category": "Usage",
            "x-is-trigger": False,
            "x-display-name": "Get Queue Status",
        },
        title="Get Queue Status",
    )


class FirecrawlTeamActivityConfig(BaseModel):
    """List recent API activity for the authenticated team."""

    operation: Literal["team_activity"] = Field(
        "team_activity",
        json_schema_extra={
            "const": "team_activity",
            "ui:hidden": True,
            "x-category": "Usage",
            "x-is-trigger": False,
            "x-display-name": "List Team Activity",
        },
        title="List Team Activity",
    )
    endpoint: Optional[str] = Field(
        None,
        title="Endpoint Filter",
        description="Optional endpoint name to filter activity by",
    )
    limit: Optional[str] = Field(
        None,
        title="Limit",
        description="Maximum number of activity records to return",
    )
    cursor: Optional[str] = Field(
        None,
        title="Cursor",
        description="Pagination cursor from a previous response",
    )


class FirecrawlEndpointFeedbackConfig(BaseModel):
    """Submit feedback for a v2 job."""

    operation: Literal["submit_feedback"] = Field(
        "submit_feedback",
        json_schema_extra={
            "const": "submit_feedback",
            "ui:hidden": True,
            "x-category": "Support",
            "x-is-trigger": False,
            "x-display-name": "Submit Endpoint Feedback",
        },
        title="Submit Endpoint Feedback",
    )
    endpoint: str = Field(
        ...,
        title="Endpoint",
        description="Endpoint family being rated",
        json_schema_extra={
            "enum": ["search", "scrape", "parse", "map"],
            "x-enum-searchable": True,
        },
    )
    job_id: str = Field(..., title="Job ID", description="The v2 job id")
    rating: str = Field(
        ...,
        title="Rating",
        description="Overall feedback rating",
        json_schema_extra={
            "enum": ["good", "partial", "bad"],
            "x-enum-searchable": True,
        },
    )
    valuable_sources_json: Optional[str] = Field(
        None,
        title="Valuable Sources (JSON)",
        description='JSON array like `[{"url":"https://...","reason":"..."}]`',
        json_schema_extra={"ui:widget": "textarea"},
    )
    missing_content_json: Optional[str] = Field(
        None,
        title="Missing Content (JSON)",
        description='JSON array like `[{"topic":"...","description":"..."}]`',
        json_schema_extra={"ui:widget": "textarea"},
    )
    query_suggestions: Optional[str] = Field(
        None, title="Query Suggestions", description="Suggestions for better query phrasing"
    )
    origin: Optional[str] = Field(
        "api", title="Origin", description="Feedback origin label"
    )
    integration: Optional[str] = Field(
        None, title="Integration", description="Optional integration label"
    )
    issues_json: Optional[str] = Field(
        None,
        title="Issues (JSON)",
        description='JSON array of issue codes like `["bad-markdown","missing-content"]`',
        json_schema_extra={"ui:widget": "textarea"},
    )
    tags_json: Optional[str] = Field(
        None,
        title="Tags (JSON)",
        description='JSON array of tags like `["production","customer-report"]`',
        json_schema_extra={"ui:widget": "textarea"},
    )
    note: Optional[str] = Field(
        None, title="Note", description="Freeform note about the issue"
    )
    url: Optional[str] = Field(
        None, title="URL", description="URL related to the feedback"
    )
    page_numbers_json: Optional[str] = Field(
        None,
        title="Page Numbers (JSON)",
        description="JSON array of page numbers",
        json_schema_extra={"ui:widget": "textarea"},
    )
    metadata_json: Optional[str] = Field(
        None,
        title="Metadata (JSON)",
        description="Small endpoint-specific metadata object",
        json_schema_extra={"ui:widget": "textarea"},
    )


class FirecrawlSearchFeedbackConfig(BaseModel):
    """Submit feedback for a search job."""

    operation: Literal["submit_search_feedback"] = Field(
        "submit_search_feedback",
        json_schema_extra={
            "const": "submit_search_feedback",
            "ui:hidden": True,
            "x-category": "Support",
            "x-is-trigger": False,
            "x-display-name": "Submit Search Feedback",
        },
        title="Submit Search Feedback",
    )
    job_id: str = Field(..., title="Job ID", description="The search job id")
    rating: str = Field(
        ...,
        title="Rating",
        description="Overall feedback rating",
        json_schema_extra={
            "enum": ["good", "partial", "bad"],
            "x-enum-searchable": True,
        },
    )
    valuable_sources_json: Optional[str] = Field(
        None,
        title="Valuable Sources (JSON)",
        description='JSON array like `[{"url":"https://...","reason":"..."}]`',
        json_schema_extra={"ui:widget": "textarea"},
    )
    missing_content_json: Optional[str] = Field(
        None,
        title="Missing Content (JSON)",
        description='JSON array like `[{"topic":"...","description":"..."}]`',
        json_schema_extra={"ui:widget": "textarea"},
    )
    query_suggestions: Optional[str] = Field(
        None, title="Query Suggestions", description="Suggestions for better query phrasing"
    )
    origin: Optional[str] = Field(
        "api", title="Origin", description="Feedback origin label"
    )
    integration: Optional[str] = Field(
        None, title="Integration", description="Optional integration label"
    )


class FirecrawlSupportAskConfig(BaseModel):
    """Ask the Firecrawl support agent."""

    operation: Literal["support_ask"] = Field(
        "support_ask",
        json_schema_extra={
            "const": "support_ask",
            "ui:hidden": True,
            "x-category": "Support",
            "x-is-trigger": False,
            "x-display-name": "Ask Firecrawl Support",
        },
        title="Ask Firecrawl Support",
    )
    question: str = Field(..., title="Question", description="Support question to ask")
    rationale: Optional[str] = Field(
        None, title="Rationale", description="Optional context about what you are trying to accomplish"
    )


class FirecrawlSupportDocsSearchConfig(BaseModel):
    """Search Firecrawl docs with citations."""

    operation: Literal["support_docs_search"] = Field(
        "support_docs_search",
        json_schema_extra={
            "const": "support_docs_search",
            "ui:hidden": True,
            "x-category": "Support",
            "x-is-trigger": False,
            "x-display-name": "Search Firecrawl Docs",
        },
        title="Search Firecrawl Docs",
    )
    question: str = Field(..., title="Question", description="Documentation question to answer")


class FirecrawlCreateMonitorConfig(BaseModel):
    """Create a monitor."""

    operation: Literal["create_monitor"] = Field(
        "create_monitor",
        json_schema_extra={
            "const": "create_monitor",
            "ui:hidden": True,
            "x-category": "Monitoring",
            "x-is-trigger": False,
            "x-display-name": "Create Monitor",
        },
        title="Create Monitor",
    )
    name: str = Field(..., title="Name", description="Monitor name")
    schedule_json: str = Field(
        ...,
        title="Schedule (JSON)",
        description='JSON object like `{"text":"every 30 minutes","timezone":"UTC"}`',
        json_schema_extra={"ui:widget": "textarea"},
    )
    targets_json: str = Field(
        ...,
        title="Targets (JSON)",
        description="JSON array of monitor targets",
        json_schema_extra={"ui:widget": "textarea"},
    )
    webhook_json: Optional[str] = Field(
        None,
        title="Webhook (JSON)",
        description="Optional monitor webhook object",
        json_schema_extra={"ui:widget": "textarea"},
    )
    notification_json: Optional[str] = Field(
        None,
        title="Notification (JSON)",
        description="Optional monitor notification object",
        json_schema_extra={"ui:widget": "textarea"},
    )
    retention_days: Optional[str] = Field(
        None, title="Retention Days", description="Days of monitor data to retain"
    )
    goal: Optional[str] = Field(
        None, title="Goal", description="Plain-language goal for judging meaningful changes"
    )
    judge_enabled: Optional[str] = Field(
        None,
        title="Judge Enabled",
        description="Whether to enable change judging",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class FirecrawlListMonitorsConfig(BaseModel):
    """List monitors."""

    operation: Literal["list_monitors"] = Field(
        "list_monitors",
        json_schema_extra={
            "const": "list_monitors",
            "ui:hidden": True,
            "x-category": "Monitoring",
            "x-is-trigger": False,
            "x-display-name": "List Monitors",
        },
        title="List Monitors",
    )
    limit: Optional[str] = Field(None, title="Limit", description="Maximum monitors to return")
    offset: Optional[str] = Field(None, title="Offset", description="Pagination offset")


class FirecrawlGetMonitorConfig(BaseModel):
    """Get a monitor."""

    operation: Literal["get_monitor"] = Field(
        "get_monitor",
        json_schema_extra={
            "const": "get_monitor",
            "ui:hidden": True,
            "x-category": "Monitoring",
            "x-is-trigger": False,
            "x-display-name": "Get Monitor",
        },
        title="Get Monitor",
    )
    monitor_id: str = Field(..., title="Monitor ID", description="Monitor identifier")


class FirecrawlUpdateMonitorConfig(BaseModel):
    """Update a monitor."""

    operation: Literal["update_monitor"] = Field(
        "update_monitor",
        json_schema_extra={
            "const": "update_monitor",
            "ui:hidden": True,
            "x-category": "Monitoring",
            "x-is-trigger": False,
            "x-display-name": "Update Monitor",
        },
        title="Update Monitor",
    )
    monitor_id: str = Field(..., title="Monitor ID", description="Monitor identifier")
    update_json: str = Field(
        ...,
        title="Update Payload (JSON)",
        description="Partial monitor update payload",
        json_schema_extra={"ui:widget": "textarea"},
    )


class FirecrawlDeleteMonitorConfig(BaseModel):
    """Delete a monitor."""

    operation: Literal["delete_monitor"] = Field(
        "delete_monitor",
        json_schema_extra={
            "const": "delete_monitor",
            "ui:hidden": True,
            "x-category": "Monitoring",
            "x-is-trigger": False,
            "x-display-name": "Delete Monitor",
        },
        title="Delete Monitor",
    )
    monitor_id: str = Field(..., title="Monitor ID", description="Monitor identifier")


class FirecrawlListMonitorChecksConfig(BaseModel):
    """List checks for a monitor."""

    operation: Literal["list_monitor_checks"] = Field(
        "list_monitor_checks",
        json_schema_extra={
            "const": "list_monitor_checks",
            "ui:hidden": True,
            "x-category": "Monitoring",
            "x-is-trigger": False,
            "x-display-name": "List Monitor Checks",
        },
        title="List Monitor Checks",
    )
    monitor_id: str = Field(..., title="Monitor ID", description="Monitor identifier")
    limit: Optional[str] = Field(None, title="Limit", description="Maximum checks to return")
    offset: Optional[str] = Field(None, title="Offset", description="Pagination offset")
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Optional check status filter",
        json_schema_extra={
            "enum": ["queued", "running", "completed", "failed", "partial", "skipped_overlap"],
            "x-enum-searchable": True,
        },
    )


class FirecrawlGetMonitorCheckConfig(BaseModel):
    """Get a single monitor check and page details."""

    operation: Literal["get_monitor_check"] = Field(
        "get_monitor_check",
        json_schema_extra={
            "const": "get_monitor_check",
            "ui:hidden": True,
            "x-category": "Monitoring",
            "x-is-trigger": False,
            "x-display-name": "Get Monitor Check",
        },
        title="Get Monitor Check",
    )
    monitor_id: str = Field(..., title="Monitor ID", description="Monitor identifier")
    check_id: str = Field(..., title="Check ID", description="Monitor check identifier")
    limit: Optional[str] = Field(
        None, title="Limit", description="Maximum page results to return"
    )
    skip: Optional[str] = Field(None, title="Skip", description="Page results offset")
    status: Optional[str] = Field(
        None,
        title="Page Status",
        description="Optional page status filter",
        json_schema_extra={
            "enum": ["same", "new", "changed", "removed", "error"],
            "x-enum-searchable": True,
        },
    )


class FirecrawlRunMonitorConfig(BaseModel):
    """Run a monitor immediately."""

    operation: Literal["run_monitor"] = Field(
        "run_monitor",
        json_schema_extra={
            "const": "run_monitor",
            "ui:hidden": True,
            "x-category": "Monitoring",
            "x-is-trigger": False,
            "x-display-name": "Run Monitor",
        },
        title="Run Monitor",
    )
    monitor_id: str = Field(..., title="Monitor ID", description="Monitor identifier")


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class FirecrawlWebhookTriggerBase(BaseModel):
    """Shared settings for Firecrawl inbound webhook triggers."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Reference this URL in a Crawl / Batch Scrape / Monitor webhook field, or any other Firecrawl webhook-capable operation",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None,
        title="Webhook Signing Secret",
        description="Optional Firecrawl webhook secret used to verify X-Firecrawl-Signature",
        json_schema_extra={"ui:widget": "password"},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})


class FirecrawlReceiveWebhookConfig(FirecrawlWebhookTriggerBase):
    """Receive any published Firecrawl webhook event.

    Firecrawl webhooks are configured per-job by adding a `webhook` object to a
    crawl / batch / extract request or to a monitor definition. Firecrawl also
    accepts webhook objects on `/agent` in live API testing, and publishes
    agent webhook payloads in its webhook OpenAPI. The trigger therefore accepts
    any Firecrawl webhook, but only crawl / batch scrape / agent / monitor have
    a published event taxonomy suitable for decomposed trigger variants.
    """

    operation: Literal["receive_webhook"] = Field(
        "receive_webhook",
        json_schema_extra={
            "const": "receive_webhook",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Any Firecrawl Event",
        },
        title="On Any Firecrawl Event",
    )
    event_type: str = Field(
        FIRECRAWL_WEBHOOK_EVENT_ALL,
        title="Event Type",
        description="Optional exact Firecrawl event type filter. Leave on 'Any published Firecrawl webhook' to accept every event family.",
        json_schema_extra={
            "enum": FIRECRAWL_PUBLISHED_WEBHOOK_EVENTS,
            "enumNames": FIRECRAWL_PUBLISHED_WEBHOOK_EVENT_NAMES,
            "x-enum-searchable": True,
        },
    )


class FirecrawlOnCrawlEventConfig(FirecrawlWebhookTriggerBase):
    """Receive Firecrawl crawl webhook events."""

    operation: Literal["on_crawl_event"] = Field(
        "on_crawl_event",
        json_schema_extra={
            "const": "on_crawl_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Crawl Event",
        },
        title="On Crawl Event",
    )
    event_type: str = Field(
        FIRECRAWL_WEBHOOK_EVENT_ALL,
        title="Crawl Event Type",
        description="Which crawl event should fire this workflow. 'Any crawl event' also matches future crawl-prefixed events such as crawl.failed.",
        json_schema_extra={
            "enum": [FIRECRAWL_WEBHOOK_EVENT_ALL, *FIRECRAWL_CRAWL_WEBHOOK_EVENTS],
            "enumNames": ["Any crawl event", *FIRECRAWL_CRAWL_WEBHOOK_EVENT_NAMES],
            "x-enum-searchable": True,
        },
    )


class FirecrawlOnBatchScrapeEventConfig(FirecrawlWebhookTriggerBase):
    """Receive Firecrawl batch scrape webhook events."""

    operation: Literal["on_batch_scrape_event"] = Field(
        "on_batch_scrape_event",
        json_schema_extra={
            "const": "on_batch_scrape_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Batch Scrape Event",
        },
        title="On Batch Scrape Event",
    )
    event_type: str = Field(
        FIRECRAWL_WEBHOOK_EVENT_ALL,
        title="Batch Scrape Event Type",
        description="Which batch scrape event should fire this workflow. 'Any batch scrape event' also matches future batch_scrape-prefixed events such as batch_scrape.failed.",
        json_schema_extra={
            "enum": [FIRECRAWL_WEBHOOK_EVENT_ALL, *FIRECRAWL_BATCH_SCRAPE_WEBHOOK_EVENTS],
            "enumNames": ["Any batch scrape event", *FIRECRAWL_BATCH_SCRAPE_WEBHOOK_EVENT_NAMES],
            "x-enum-searchable": True,
        },
    )


class FirecrawlOnAgentEventConfig(FirecrawlWebhookTriggerBase):
    """Receive Firecrawl agent webhook events."""

    operation: Literal["on_agent_event"] = Field(
        "on_agent_event",
        json_schema_extra={
            "const": "on_agent_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Agent Event",
        },
        title="On Agent Event",
    )
    event_type: str = Field(
        FIRECRAWL_WEBHOOK_EVENT_ALL,
        title="Agent Event Type",
        description="Which agent event should fire this workflow. Firecrawl publishes these payloads in its webhook OpenAPI.",
        json_schema_extra={
            "enum": [FIRECRAWL_WEBHOOK_EVENT_ALL, *FIRECRAWL_AGENT_WEBHOOK_EVENTS],
            "enumNames": ["Any agent event", *FIRECRAWL_AGENT_WEBHOOK_EVENT_NAMES],
            "x-enum-searchable": True,
        },
    )


class FirecrawlOnMonitorEventConfig(FirecrawlWebhookTriggerBase):
    """Receive Firecrawl monitor webhook events."""

    operation: Literal["on_monitor_event"] = Field(
        "on_monitor_event",
        json_schema_extra={
            "const": "on_monitor_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Monitor Event",
        },
        title="On Monitor Event",
    )
    event_type: str = Field(
        FIRECRAWL_WEBHOOK_EVENT_ALL,
        title="Monitor Event Type",
        description="Which monitor event should fire this workflow.",
        json_schema_extra={
            "enum": [FIRECRAWL_WEBHOOK_EVENT_ALL, *FIRECRAWL_MONITOR_WEBHOOK_EVENTS],
            "enumNames": ["Any monitor event", *FIRECRAWL_MONITOR_WEBHOOK_EVENT_NAMES],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Discriminated Union
# ============================================================================


FirecrawlConfig = Annotated[
    Union[
        FirecrawlScrapeConfig,
        FirecrawlGetScrapeConfig,
        FirecrawlBatchScrapeConfig,
        FirecrawlGetBatchScrapeConfig,
        FirecrawlCancelBatchScrapeConfig,
        FirecrawlGetBatchScrapeErrorsConfig,
        FirecrawlCrawlConfig,
        FirecrawlGetCrawlConfig,
        FirecrawlCancelCrawlConfig,
        FirecrawlGetCrawlErrorsConfig,
        FirecrawlListActiveCrawlsConfig,
        FirecrawlCrawlParamsPreviewConfig,
        FirecrawlMapConfig,
        FirecrawlSearchConfig,
        FirecrawlSearchResearchGithubConfig,
        FirecrawlSearchResearchPapersConfig,
        FirecrawlGetResearchPaperConfig,
        FirecrawlGetSimilarResearchPapersConfig,
        FirecrawlExtractConfig,
        FirecrawlGetExtractConfig,
        FirecrawlAgentConfig,
        FirecrawlGetAgentConfig,
        FirecrawlCancelAgentConfig,
        FirecrawlParseConfig,
        FirecrawlCreateInteractConfig,
        FirecrawlListInteractConfig,
        FirecrawlExecuteInteractConfig,
        FirecrawlDeleteInteractConfig,
        FirecrawlScrapeInteractConfig,
        FirecrawlStopScrapeInteractConfig,
        FirecrawlCreditUsageConfig,
        FirecrawlTokenUsageConfig,
        FirecrawlCreditUsageHistoricalConfig,
        FirecrawlTokenUsageHistoricalConfig,
        FirecrawlQueueStatusConfig,
        FirecrawlTeamActivityConfig,
        FirecrawlEndpointFeedbackConfig,
        FirecrawlSearchFeedbackConfig,
        FirecrawlSupportAskConfig,
        FirecrawlSupportDocsSearchConfig,
        FirecrawlCreateMonitorConfig,
        FirecrawlListMonitorsConfig,
        FirecrawlGetMonitorConfig,
        FirecrawlUpdateMonitorConfig,
        FirecrawlDeleteMonitorConfig,
        FirecrawlListMonitorChecksConfig,
        FirecrawlGetMonitorCheckConfig,
        FirecrawlRunMonitorConfig,
        FirecrawlReceiveWebhookConfig,
        FirecrawlOnCrawlEventConfig,
        FirecrawlOnBatchScrapeEventConfig,
        FirecrawlOnAgentEventConfig,
        FirecrawlOnMonitorEventConfig,
    ],
    Discriminator("operation"),
]


class FirecrawlNodeConfig(NodeConfig[FirecrawlConfig, FirecrawlCredential]):
    """Full configuration for the Firecrawl node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _optional_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return int(value)


def _optional_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def _parse_json(value: Optional[str], field: str) -> Optional[Any]:
    if not value:
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid JSON in {field}: {e}")


def _inbound_firecrawl_event_type(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        event_type = payload.get("type") or payload.get("event")
        if event_type:
            return str(event_type)
        webhook_meta = payload.get("_webhook")
        if isinstance(webhook_meta, dict):
            headers = webhook_meta.get("headers") or {}
            for key, value in headers.items():
                if str(key).lower() in ("x-firecrawl-event",):
                    return str(value)
    return None


def _firecrawl_trigger_matches(
    operation: Optional[str], selected_event_type: Optional[str], event_type: Optional[str]
) -> bool:
    if selected_event_type and selected_event_type != FIRECRAWL_WEBHOOK_EVENT_ALL:
        return event_type == selected_event_type
    prefix = FIRECRAWL_TRIGGER_FAMILY_PREFIXES.get(operation or "")
    if not prefix:
        return True
    return bool(event_type and event_type.startswith(prefix))


async def _firecrawl_request(
    api_key: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    files: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Firecrawl v2 request and return a structured result."""
    url = f"{FIRECRAWL_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
    }
    if not files:
        headers["Content-Type"] = "application/json"
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}
    if data:
        data = {k: v for k, v in data.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
                data=data,
                files=files,
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = err.get("error") or err.get("message") or str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[FirecrawlNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
            else:
                try:
                    payload = response.json()
                    # Firecrawl v2 wraps results in {success, data, ...}
                    data = payload.get("data", payload) if isinstance(payload, dict) else payload
                except Exception:
                    data = {"raw": response.text}
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[FirecrawlNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class FirecrawlNode(WorkflowNode):
    """Firecrawl web scraping & crawling automation node."""

    edit_examples = [
        "Scrape a product page and return it as markdown",
        "Crawl an entire documentation site and collect every page",
        "Map all the URLs on a competitor's website",
        "Search the web for recent news and scrape the top results",
        "Extract structured pricing data from a list of URLs",
        "Trigger a workflow when an async crawl job completes",
    ]

    @classmethod
    def get_config_model(cls):
        return FirecrawlNodeConfig

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        event_type = _inbound_firecrawl_event_type(payload)
        operation = (config or {}).get("operation")
        selected_event_type = (config or {}).get("event_type") or FIRECRAWL_WEBHOOK_EVENT_ALL
        if _firecrawl_trigger_matches(operation, selected_event_type, event_type):
            return payload
        return None

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, FirecrawlNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(
            op,
            (
                FirecrawlReceiveWebhookConfig,
                FirecrawlOnCrawlEventConfig,
                FirecrawlOnBatchScrapeEventConfig,
                FirecrawlOnAgentEventConfig,
                FirecrawlOnMonitorEventConfig,
            ),
        ):
            event_type = _inbound_firecrawl_event_type(inputs)
            if not _firecrawl_trigger_matches(op.operation, getattr(op, "event_type", None), event_type):
                selected_event_type = getattr(op, "event_type", FIRECRAWL_WEBHOOK_EVENT_ALL)
                label = selected_event_type or FIRECRAWL_WEBHOOK_EVENT_ALL
                return {
                    "status": "skipped",
                    "action": op.operation,
                    "event_type": event_type,
                    "reason": f"Event '{event_type}' does not match trigger filter '{label}'",
                    "data": {"webhook_url": op.webhook_url},
                    "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
                }
            return {
                "status": "success",
                "action": op.operation,
                "event_type": event_type,
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Firecrawl API key.")
        api_key = credentials.api_key

        handlers = {
            "scrape": self._scrape,
            "get_scrape": self._get_scrape,
            "batch_scrape": self._batch_scrape,
            "get_batch_scrape": self._get_batch_scrape,
            "cancel_batch_scrape": self._cancel_batch_scrape,
            "get_batch_scrape_errors": self._get_batch_scrape_errors,
            "crawl": self._crawl,
            "get_crawl": self._get_crawl,
            "cancel_crawl": self._cancel_crawl,
            "get_crawl_errors": self._get_crawl_errors,
            "list_active_crawls": self._list_active_crawls,
            "crawl_params_preview": self._crawl_params_preview,
            "map": self._map,
            "search": self._search,
            "search_research_github": self._search_research_github,
            "search_research_papers": self._search_research_papers,
            "get_research_paper": self._get_research_paper,
            "get_similar_research_papers": self._get_similar_research_papers,
            "extract": self._extract,
            "get_extract": self._get_extract,
            "agent": self._agent,
            "get_agent": self._get_agent,
            "cancel_agent": self._cancel_agent,
            "parse": self._parse,
            "create_interact_session": self._create_interact_session,
            "list_interact_sessions": self._list_interact_sessions,
            "execute_interact_session": self._execute_interact_session,
            "delete_interact_session": self._delete_interact_session,
            "scrape_interact": self._scrape_interact,
            "stop_scrape_interact": self._stop_scrape_interact,
            "credit_usage": self._credit_usage,
            "token_usage": self._token_usage,
            "credit_usage_historical": self._credit_usage_historical,
            "token_usage_historical": self._token_usage_historical,
            "queue_status": self._queue_status,
            "team_activity": self._team_activity,
            "submit_feedback": self._submit_feedback,
            "submit_search_feedback": self._submit_search_feedback,
            "support_ask": self._support_ask,
            "support_docs_search": self._support_docs_search,
            "create_monitor": self._create_monitor,
            "list_monitors": self._list_monitors,
            "get_monitor": self._get_monitor,
            "update_monitor": self._update_monitor,
            "delete_monitor": self._delete_monitor,
            "list_monitor_checks": self._list_monitor_checks,
            "get_monitor_check": self._get_monitor_check,
            "run_monitor": self._run_monitor,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Scraping handlers
    # ------------------------------------------------------------------
    async def _scrape(self, c: FirecrawlScrapeConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "url": c.url,
            "formats": _comma_list(c.formats),
            "onlyMainContent": c.only_main_content == "true",
            "waitFor": _optional_int(c.wait_for),
        }
        return await _firecrawl_request(api_key, "POST", "/scrape", json_body=body, action_name="scrape")

    async def _get_scrape(self, c: FirecrawlGetScrapeConfig, api_key: str) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key, "GET", f"/scrape/{c.job_id}", action_name="get_scrape"
        )

    async def _batch_scrape(self, c: FirecrawlBatchScrapeConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "urls": _comma_list(c.urls),
            "formats": _comma_list(c.formats),
        }
        if c.webhook_url:
            webhook: Dict[str, Any] = {
                "url": c.webhook_url,
                "events": _comma_list(c.webhook_events),
                "headers": _parse_json(c.webhook_headers_json, "Webhook Headers (JSON)"),
                "metadata": _parse_json(c.webhook_metadata_json, "Webhook Metadata (JSON)"),
            }
            body["webhook"] = {k: v for k, v in webhook.items() if v is not None}
        return await _firecrawl_request(
            api_key, "POST", "/batch/scrape", json_body=body, action_name="batch_scrape"
        )

    async def _get_batch_scrape(self, c: FirecrawlGetBatchScrapeConfig, api_key: str) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key, "GET", f"/batch/scrape/{c.job_id}", action_name="get_batch_scrape"
        )

    async def _cancel_batch_scrape(self, c: FirecrawlCancelBatchScrapeConfig, api_key: str) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key, "DELETE", f"/batch/scrape/{c.job_id}", action_name="cancel_batch_scrape"
        )

    async def _get_batch_scrape_errors(
        self, c: FirecrawlGetBatchScrapeErrorsConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key, "GET", f"/batch/scrape/{c.job_id}/errors", action_name="get_batch_scrape_errors"
        )

    # ------------------------------------------------------------------
    # Crawling handlers
    # ------------------------------------------------------------------
    async def _crawl(self, c: FirecrawlCrawlConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "url": c.url,
            "limit": _optional_int(c.limit),
            "maxDiscoveryDepth": _optional_int(c.max_discovery_depth),
        }
        if c.webhook_url:
            webhook: Dict[str, Any] = {
                "url": c.webhook_url,
                "events": _comma_list(c.webhook_events),
                "headers": _parse_json(c.webhook_headers_json, "Webhook Headers (JSON)"),
                "metadata": _parse_json(c.webhook_metadata_json, "Webhook Metadata (JSON)"),
            }
            body["webhook"] = {k: v for k, v in webhook.items() if v is not None}
        return await _firecrawl_request(api_key, "POST", "/crawl", json_body=body, action_name="crawl")

    async def _get_crawl(self, c: FirecrawlGetCrawlConfig, api_key: str) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key, "GET", f"/crawl/{c.job_id}", action_name="get_crawl"
        )

    async def _cancel_crawl(self, c: FirecrawlCancelCrawlConfig, api_key: str) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key, "DELETE", f"/crawl/{c.job_id}", action_name="cancel_crawl"
        )

    async def _get_crawl_errors(self, c: FirecrawlGetCrawlErrorsConfig, api_key: str) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key, "GET", f"/crawl/{c.job_id}/errors", action_name="get_crawl_errors"
        )

    async def _list_active_crawls(self, c: FirecrawlListActiveCrawlsConfig, api_key: str) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key, "GET", "/crawl/active", action_name="list_active_crawls"
        )

    async def _crawl_params_preview(
        self, c: FirecrawlCrawlParamsPreviewConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {"url": c.url, "prompt": c.prompt}
        return await _firecrawl_request(
            api_key, "POST", "/crawl/params-preview", json_body=body, action_name="crawl_params_preview"
        )

    # ------------------------------------------------------------------
    # Discovery handlers
    # ------------------------------------------------------------------
    async def _map(self, c: FirecrawlMapConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "url": c.url,
            "search": c.search,
            "limit": _optional_int(c.limit),
        }
        return await _firecrawl_request(api_key, "POST", "/map", json_body=body, action_name="map")

    async def _search(self, c: FirecrawlSearchConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "query": c.query,
            "limit": _optional_int(c.limit),
        }
        if c.scrape_content == "true":
            body["scrapeOptions"] = {"formats": ["markdown"]}
        return await _firecrawl_request(api_key, "POST", "/search", json_body=body, action_name="search")

    async def _search_research_github(
        self, c: FirecrawlSearchResearchGithubConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key,
            "GET",
            "/search/research/github",
            params={"query": c.query, "k": _optional_int(c.k)},
            action_name="search_research_github",
        )

    async def _search_research_papers(
        self, c: FirecrawlSearchResearchPapersConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key,
            "GET",
            "/search/research/papers",
            params={
                "query": c.query,
                "k": _optional_int(c.k),
                "authors": c.authors,
                "categories": c.categories,
                "from": c.from_date,
                "to": c.to_date,
            },
            action_name="search_research_papers",
        )

    async def _get_research_paper(
        self, c: FirecrawlGetResearchPaperConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key,
            "GET",
            f"/search/research/papers/{c.paper_id}",
            params={"query": c.query, "k": _optional_int(c.k)},
            action_name="get_research_paper",
        )

    async def _get_similar_research_papers(
        self, c: FirecrawlGetSimilarResearchPapersConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key,
            "GET",
            f"/search/research/papers/{c.paper_id}/similar",
            params={
                "intent": c.intent,
                "mode": c.mode,
                "k": _optional_int(c.k),
                "rerank": _optional_bool(c.rerank),
                "anchor": c.anchor,
            },
            action_name="get_similar_research_papers",
        )

    # ------------------------------------------------------------------
    # Extraction handlers
    # ------------------------------------------------------------------
    async def _extract(self, c: FirecrawlExtractConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "urls": _comma_list(c.urls),
            "prompt": c.prompt,
            "schema": _parse_json(c.output_schema, "JSON Schema"),
        }
        if c.webhook_url:
            webhook: Dict[str, Any] = {
                "url": c.webhook_url,
                "events": _comma_list(c.webhook_events),
                "headers": _parse_json(c.webhook_headers_json, "Webhook Headers (JSON)"),
                "metadata": _parse_json(c.webhook_metadata_json, "Webhook Metadata (JSON)"),
            }
            body["webhook"] = {k: v for k, v in webhook.items() if v is not None}
        return await _firecrawl_request(api_key, "POST", "/extract", json_body=body, action_name="extract")

    async def _get_extract(self, c: FirecrawlGetExtractConfig, api_key: str) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key, "GET", f"/extract/{c.job_id}", action_name="get_extract"
        )

    async def _agent(self, c: FirecrawlAgentConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "prompt": c.prompt,
            "schema": _parse_json(c.output_schema, "JSON Schema"),
            "urls": _comma_list(c.urls),
        }
        if c.webhook_url:
            webhook: Dict[str, Any] = {
                "url": c.webhook_url,
                "events": _comma_list(c.webhook_events),
                "headers": _parse_json(c.webhook_headers_json, "Webhook Headers (JSON)"),
                "metadata": _parse_json(c.webhook_metadata_json, "Webhook Metadata (JSON)"),
            }
            body["webhook"] = {k: v for k, v in webhook.items() if v is not None}
        return await _firecrawl_request(api_key, "POST", "/agent", json_body=body, action_name="agent")

    async def _get_agent(self, c: FirecrawlGetAgentConfig, api_key: str) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key, "GET", f"/agent/{c.job_id}", action_name="get_agent"
        )

    async def _cancel_agent(self, c: FirecrawlCancelAgentConfig, api_key: str) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key, "DELETE", f"/agent/{c.job_id}", action_name="cancel_agent"
        )

    # ------------------------------------------------------------------
    # File handler
    # ------------------------------------------------------------------
    async def _parse(self, c: FirecrawlParseConfig, api_key: str) -> Dict[str, Any]:
        start = time.time()
        try:
            async with guarded_async_client(timeout=60.0, follow_redirects=True) as client:
                response = await client.get(c.url)
                response.raise_for_status()
                file_bytes = response.content
                content_type = response.headers.get("content-type", "application/octet-stream")
        except Exception as e:
            message = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[FirecrawlNode] File download failed (parse): {message}")
            return {
                "status": "error",
                "action": "parse",
                "error": f"Failed to download file URL: {message}",
                "status_code": 400,
                "timing_ms": {"file_download": round((time.time() - start) * 1000, 2)},
            }

        parsed = urlparse(c.url)
        filename = os.path.basename(parsed.path) or "upload.bin"
        options = {"formats": _comma_list(c.formats)}
        result = await _firecrawl_request(
            api_key,
            "POST",
            "/parse",
            data={"options": json.dumps(options)},
            files={"file": (filename, file_bytes, content_type)},
            action_name="parse",
        )
        result["timing_ms"] = {
            "file_download": round((time.time() - start) * 1000, 2),
            **result.get("timing_ms", {}),
        }
        return result

    # ------------------------------------------------------------------
    # Interact session handlers
    # ------------------------------------------------------------------
    async def _create_interact_session(
        self, c: FirecrawlCreateInteractConfig, api_key: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "ttl": _optional_int(c.ttl),
            "activityTtl": _optional_int(c.activity_ttl),
            "streamWebView": _optional_bool(c.stream_web_view),
        }
        if c.profile_name:
            body["profile"] = {
                "name": c.profile_name,
                "saveChanges": _optional_bool(c.profile_save_changes),
            }
        return await _firecrawl_request(
            api_key, "POST", "/interact", json_body=body, action_name="create_interact_session"
        )

    async def _list_interact_sessions(
        self, c: FirecrawlListInteractConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key,
            "GET",
            "/interact",
            params={"status": c.status},
            action_name="list_interact_sessions",
        )

    async def _execute_interact_session(
        self, c: FirecrawlExecuteInteractConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "code": c.code,
            "language": c.language,
            "timeout": _optional_int(c.timeout),
        }
        return await _firecrawl_request(
            api_key,
            "POST",
            f"/interact/{c.session_id}/execute",
            json_body=body,
            action_name="execute_interact_session",
        )

    async def _delete_interact_session(
        self, c: FirecrawlDeleteInteractConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key,
            "DELETE",
            f"/interact/{c.session_id}",
            action_name="delete_interact_session",
        )

    async def _scrape_interact(
        self, c: FirecrawlScrapeInteractConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "code": c.code,
            "language": c.language,
            "timeout": _optional_int(c.timeout),
            "origin": c.origin,
        }
        return await _firecrawl_request(
            api_key,
            "POST",
            f"/scrape/{c.job_id}/interact",
            json_body=body,
            action_name="scrape_interact",
        )

    async def _stop_scrape_interact(
        self, c: FirecrawlStopScrapeInteractConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key,
            "DELETE",
            f"/scrape/{c.job_id}/interact",
            action_name="stop_scrape_interact",
        )

    # ------------------------------------------------------------------
    # Usage handlers
    # ------------------------------------------------------------------
    async def _credit_usage(self, c: FirecrawlCreditUsageConfig, api_key: str) -> Dict[str, Any]:
        return await _firecrawl_request(api_key, "GET", "/team/credit-usage", action_name="credit_usage")

    async def _token_usage(self, c: FirecrawlTokenUsageConfig, api_key: str) -> Dict[str, Any]:
        return await _firecrawl_request(api_key, "GET", "/team/token-usage", action_name="token_usage")

    async def _credit_usage_historical(
        self, c: FirecrawlCreditUsageHistoricalConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key,
            "GET",
            "/team/credit-usage/historical",
            params={"byApiKey": c.by_api_key == "true"},
            action_name="credit_usage_historical",
        )

    async def _token_usage_historical(
        self, c: FirecrawlTokenUsageHistoricalConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key,
            "GET",
            "/team/token-usage/historical",
            params={"byApiKey": c.by_api_key == "true"},
            action_name="token_usage_historical",
        )

    async def _queue_status(self, c: FirecrawlQueueStatusConfig, api_key: str) -> Dict[str, Any]:
        return await _firecrawl_request(api_key, "GET", "/team/queue-status", action_name="queue_status")

    async def _team_activity(self, c: FirecrawlTeamActivityConfig, api_key: str) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key,
            "GET",
            "/team/activity",
            params={
                "endpoint": c.endpoint,
                "limit": _optional_int(c.limit),
                "cursor": c.cursor,
            },
            action_name="team_activity",
        )

    async def _submit_feedback(
        self, c: FirecrawlEndpointFeedbackConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "endpoint": c.endpoint,
            "jobId": c.job_id,
            "rating": c.rating,
            "valuableSources": _parse_json(c.valuable_sources_json, "Valuable Sources (JSON)"),
            "missingContent": _parse_json(c.missing_content_json, "Missing Content (JSON)"),
            "querySuggestions": c.query_suggestions,
            "origin": c.origin,
            "integration": c.integration,
            "issues": _parse_json(c.issues_json, "Issues (JSON)"),
            "tags": _parse_json(c.tags_json, "Tags (JSON)"),
            "note": c.note,
            "url": c.url,
            "pageNumbers": _parse_json(c.page_numbers_json, "Page Numbers (JSON)"),
            "metadata": _parse_json(c.metadata_json, "Metadata (JSON)"),
        }
        return await _firecrawl_request(
            api_key, "POST", "/feedback", json_body=body, action_name="submit_feedback"
        )

    async def _submit_search_feedback(
        self, c: FirecrawlSearchFeedbackConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "rating": c.rating,
            "valuableSources": _parse_json(c.valuable_sources_json, "Valuable Sources (JSON)"),
            "missingContent": _parse_json(c.missing_content_json, "Missing Content (JSON)"),
            "querySuggestions": c.query_suggestions,
            "origin": c.origin,
            "integration": c.integration,
        }
        return await _firecrawl_request(
            api_key,
            "POST",
            f"/search/{c.job_id}/feedback",
            json_body=body,
            action_name="submit_search_feedback",
        )

    async def _support_ask(
        self, c: FirecrawlSupportAskConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {"question": c.question, "rationale": c.rationale}
        return await _firecrawl_request(
            api_key, "POST", "/support/ask", json_body=body, action_name="support_ask"
        )

    async def _support_docs_search(
        self, c: FirecrawlSupportDocsSearchConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {"question": c.question}
        return await _firecrawl_request(
            api_key,
            "POST",
            "/support/docs-search",
            json_body=body,
            action_name="support_docs_search",
        )

    async def _create_monitor(
        self, c: FirecrawlCreateMonitorConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "schedule": _parse_json(c.schedule_json, "Schedule (JSON)"),
            "targets": _parse_json(c.targets_json, "Targets (JSON)"),
            "webhook": _parse_json(c.webhook_json, "Webhook (JSON)"),
            "notification": _parse_json(c.notification_json, "Notification (JSON)"),
            "retentionDays": _optional_int(c.retention_days),
            "goal": c.goal,
            "judgeEnabled": _optional_bool(c.judge_enabled),
        }
        return await _firecrawl_request(
            api_key, "POST", "/monitor", json_body=body, action_name="create_monitor"
        )

    async def _list_monitors(
        self, c: FirecrawlListMonitorsConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key,
            "GET",
            "/monitor",
            params={"limit": _optional_int(c.limit), "offset": _optional_int(c.offset)},
            action_name="list_monitors",
        )

    async def _get_monitor(self, c: FirecrawlGetMonitorConfig, api_key: str) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key, "GET", f"/monitor/{c.monitor_id}", action_name="get_monitor"
        )

    async def _update_monitor(
        self, c: FirecrawlUpdateMonitorConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key,
            "PATCH",
            f"/monitor/{c.monitor_id}",
            json_body=_parse_json(c.update_json, "Update Payload (JSON)"),
            action_name="update_monitor",
        )

    async def _delete_monitor(
        self, c: FirecrawlDeleteMonitorConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key, "DELETE", f"/monitor/{c.monitor_id}", action_name="delete_monitor"
        )

    async def _list_monitor_checks(
        self, c: FirecrawlListMonitorChecksConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key,
            "GET",
            f"/monitor/{c.monitor_id}/checks",
            params={
                "limit": _optional_int(c.limit),
                "offset": _optional_int(c.offset),
                "status": c.status,
            },
            action_name="list_monitor_checks",
        )

    async def _get_monitor_check(
        self, c: FirecrawlGetMonitorCheckConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key,
            "GET",
            f"/monitor/{c.monitor_id}/checks/{c.check_id}",
            params={
                "limit": _optional_int(c.limit),
                "skip": _optional_int(c.skip),
                "status": c.status,
            },
            action_name="get_monitor_check",
        )

    async def _run_monitor(
        self, c: FirecrawlRunMonitorConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _firecrawl_request(
            api_key, "POST", f"/monitor/{c.monitor_id}/run", action_name="run_monitor"
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify Firecrawl's ``X-Firecrawl-Signature: sha256=<hex>`` header."""
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True
        return verify_hmac_sha256_hex(
            body,
            secret,
            headers.get("x-firecrawl-signature", ""),
            prefix="sha256=",
        )
