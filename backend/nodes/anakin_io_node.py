"""Anakin API 1.1.0: https://anakin.io/openapi.json.

Each operation makes one documented request. Async submissions return job handles;
use the corresponding get-result operation later rather than replaying submissions.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client, SSRFError

BASE_URL = "https://api.anakin.io/v1"


class AnakinIoCredential(BaseModel):
    model_config = ConfigDict(
        title="Anakin Io API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://anakin.io/dashboard",
            "x-credential-instructions": "Copy your API key from the Anakin dashboard. Requests use the X-API-Key header.",
        },
    )
    credential_type: Literal["anakin_io_api_key"] = Field(
        "anakin_io_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Paste the API key from your Anakin dashboard.",
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value):
        value = value.strip()
        if not value or any(
            ch.isspace() or ord(ch) < 33 or ord(ch) == 127 for ch in value
        ):
            raise ValueError("Paste an Anakin API key without whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, hide_input_in_errors=True
    )

    @model_validator(mode="after")
    def documented_constraints(self):
        values = self.model_dump(by_alias=True, exclude_none=True)
        for key in ("jobId", "id", "slug"):
            if key in values and (
                not values[key].strip()
                or values[key] in {".", ".."}
                or any(ord(c) < 32 for c in values[key])
            ):
                raise ValueError("A nonempty provider resource identifier is required")
        if values.get("watchMode") == "specific_data" and not values.get(
            "outputSchema"
        ):
            raise ValueError("Specific-data monitors require outputSchema")
        if values.get("scope") == "wire" and not values.get("wireActionId"):
            raise ValueError("Wire monitors require wireActionId")
        return self


class AnakinScrapeUrlConfig(_Operation):
    operation: Literal["scrape_url"] = Field(
        "scrape_url",
        title="Extract Website Data",
        description="Submit a URL to scrape. Returns a job ID — poll GET /url-scraper/{jobId} (with a delay in between) to fetch the completed markdown/JSON.",
        json_schema_extra={"ui:hidden": True},
    )
    url: str = Field(
        ...,
        title="Url",
        description="The full URL of the website to extract data from.",
        min_length=1,
        json_schema_extra={"format": "uri"},
    )
    country: str = Field(
        "us", title="Country", description="Proxy country code, e.g. us, gb, de."
    )
    useBrowser: bool = Field(
        False,
        title="Use Browser",
        description="Use a headless browser — best for JS-heavy sites.",
    )
    generateJson: bool = Field(
        False,
        title="Generate Json",
        description="AI-extract structured JSON from the page content.",
    )
    forceFresh: bool = Field(
        False,
        title="Force Fresh",
        description="Bypass the cache and force a fresh extraction.",
    )
    sessionId: str | None = Field(
        None,
        title="Session Id",
        description="Reuse an existing authenticated browser session (see Browser Sessions) instead of an anonymous request.",
    )
    sessionName: str | None = Field(
        None,
        title="Session Name",
        description="Human-readable name of a saved browser session — alternative to sessionId.",
    )


class AnakinScrapeUrlSyncConfig(_Operation):
    operation: Literal["scrape_url_sync"] = Field(
        "scrape_url_sync",
        title="Scrape a URL and Wait for the Result",
        description='Scrapes a single URL and returns the result in the same response, so no polling is needed. Takes the same body as POST /url-scraper. If the scrape takes longer than about 90 seconds, the response is a 202 with an `id` and a non-terminal `status`; fetch the result later with GET /url-scraper/{jobId}. A failed scrape also returns 200 with `status: "failed"`, so check `status`. Limited to 20 requests per minute.',
        json_schema_extra={"ui:hidden": True},
    )
    url: str = Field(
        ...,
        title="Url",
        description="The full URL of the website to extract data from.",
        min_length=1,
        json_schema_extra={"format": "uri"},
    )
    country: str = Field(
        "us", title="Country", description="Proxy country code, e.g. us, gb, de."
    )
    useBrowser: bool = Field(
        False,
        title="Use Browser",
        description="Use a headless browser — best for JS-heavy sites.",
    )
    generateJson: bool = Field(
        False,
        title="Generate Json",
        description="AI-extract structured JSON from the page content.",
    )
    forceFresh: bool = Field(
        False,
        title="Force Fresh",
        description="Bypass the cache and force a fresh extraction.",
    )
    sessionId: str | None = Field(
        None,
        title="Session Id",
        description="Reuse an existing authenticated browser session (see Browser Sessions) instead of an anonymous request.",
    )
    sessionName: str | None = Field(
        None,
        title="Session Name",
        description="Human-readable name of a saved browser session — alternative to sessionId.",
    )


class AnakinGetScrapeResultConfig(_Operation):
    operation: Literal["get_scrape_result"] = Field(
        "get_scrape_result",
        title="Get Scrape Result",
        description="Fetch the status and results of a scrape job started by Extract Website Data.",
        json_schema_extra={"ui:hidden": True},
    )
    jobId: str = Field(
        ...,
        title="Job Id",
        description="The jobId returned by Extract Website Data.",
        min_length=1,
    )


class AnakinSearchConfig(_Operation):
    operation: Literal["search"] = Field(
        "search",
        title="Perform AI Search",
        description="AI-powered web search with citations. Synchronous — returns immediately, no polling needed. Costs 3 credits per call.",
        json_schema_extra={"ui:hidden": True},
    )
    prompt: str = Field(
        ..., title="Prompt", description="The search query or question.", min_length=1
    )
    limit: int = Field(
        5,
        title="Limit",
        description="Maximum number of results to return (default 5, max 20).",
        ge=1,
        le=20,
    )


class AnakinStartResearchConfig(_Operation):
    operation: Literal["start_research"] = Field(
        "start_research",
        title="Start Agentic Search",
        description="Start a multi-stage AI research pipeline: search, scrape citations, extract structured data. Returns a job ID — poll GET /agentic-search/{jobId} (with a delay in between, this can take minutes) to fetch the report. Costs 10 credits.",
        json_schema_extra={"ui:hidden": True},
    )
    prompt: str = Field(
        ...,
        title="Prompt",
        description="The research question or topic (max 8KB).",
        min_length=1,
    )
    useBrowser: bool = Field(
        True,
        title="Use Browser",
        description="Use a headless browser for citation scraping — matches the API default.",
    )
    output_schema: dict[str, Any] | None = Field(
        None,
        title="Schema",
        description="Optional JSON Schema describing the structured_data shape you want back.",
        alias="schema",
    )


class AnakinGetResearchResultConfig(_Operation):
    operation: Literal["get_research_result"] = Field(
        "get_research_result",
        title="Get Agentic Search Result",
        description="Fetch the status and results of an agentic search job started by Start Agentic Search.",
        json_schema_extra={"ui:hidden": True},
    )
    jobId: str = Field(
        ...,
        title="Job Id",
        description="The job_id returned by Start Agentic Search.",
        min_length=1,
    )


class AnakinMapSiteConfig(_Operation):
    operation: Literal["map_site"] = Field(
        "map_site",
        title="Map a Site's URLs",
        description="Discover all reachable URLs under a given site — internal links, external links, and counts. Submit a URL to map. Returns a job ID — poll GET /map/{jobId} (with a delay in between) to fetch the completed link list.",
        json_schema_extra={"ui:hidden": True},
    )
    url: str = Field(
        ...,
        title="Url",
        description="The starting URL for discovery (typically a homepage or section root).",
        min_length=1,
        json_schema_extra={"format": "uri"},
    )
    limit: int = Field(
        100, title="Limit", description="Maximum number of URLs to return overall."
    )
    depth: int = Field(
        2,
        title="Depth",
        description="How many link-hops from the starting URL to follow.",
    )
    limitPerLevel: int = Field(
        100,
        title="Limit Per Level",
        description="Maximum URLs collected per depth level (controls breadth).",
    )
    includeSubdomains: bool = Field(
        False,
        title="Include Subdomains",
        description="Include URLs on subdomains of the starting host.",
    )
    includeExternalLinks: bool = Field(
        False,
        title="Include External Links",
        description="Also collect (but do not follow) external links.",
    )
    useBrowser: bool = Field(
        False,
        title="Use Browser",
        description="Use a headless browser — best for JS-heavy sites.",
    )
    search: str | None = Field(
        None,
        title="Search",
        description="Optional keyword filter — only return URLs whose path/title matches.",
    )


class AnakinGetMapResultConfig(_Operation):
    operation: Literal["get_map_result"] = Field(
        "get_map_result",
        title="Get Map Result",
        description="Fetch the status and results of a map job started by Map a Site's URLs.",
        json_schema_extra={"ui:hidden": True},
    )
    jobId: str = Field(
        ...,
        title="Job Id",
        description="The jobId returned by Map a Site's URLs.",
        min_length=1,
    )


class AnakinCrawlSiteConfig(_Operation):
    operation: Literal["crawl_site"] = Field(
        "crawl_site",
        title="Crawl a Site",
        description="Bulk-fetch markdown across a site — catalog ingestion, site-wide RAG corpora. Submit a URL to crawl. Returns a job ID — poll GET /crawl/{jobId} (with a delay in between) to fetch the completed pages.",
        json_schema_extra={"ui:hidden": True},
    )
    url: str = Field(
        ...,
        title="Url",
        description="The starting URL to crawl from.",
        min_length=1,
        json_schema_extra={"format": "uri"},
    )
    maxPages: int = Field(
        10, title="Max Pages", description="Hard cap on pages fetched."
    )
    depth: int = Field(
        1, title="Depth", description="Link-hops from the starting URL to follow."
    )
    country: str = Field(
        "us", title="Country", description="Proxy country code, e.g. us, gb, de."
    )
    useBrowser: bool = Field(
        False,
        title="Use Browser",
        description="Render each page in a headless browser (for SPAs).",
    )
    includePatterns: list[str] | None = Field(
        None,
        title="Include Patterns",
        description="Glob/regex patterns. Only URLs matching at least one pattern are fetched.",
    )
    excludePatterns: list[str] | None = Field(
        None,
        title="Exclude Patterns",
        description="Glob/regex patterns. URLs matching any pattern are skipped.",
    )
    sessionId: str | None = Field(
        None,
        title="Session Id",
        description="Reuse an existing authenticated browser session (see Browser Sessions) instead of an anonymous request.",
    )
    sessionName: str | None = Field(
        None,
        title="Session Name",
        description="Human-readable name of a saved browser session — alternative to sessionId.",
    )


class AnakinGetCrawlResultConfig(_Operation):
    operation: Literal["get_crawl_result"] = Field(
        "get_crawl_result",
        title="Get Crawl Result",
        description="Fetch the status and results of a crawl job started by Crawl a Site.",
        json_schema_extra={"ui:hidden": True},
    )
    jobId: str = Field(
        ...,
        title="Job Id",
        description="The jobId returned by Crawl a Site.",
        min_length=1,
    )


class AnakinDiscoverWireActionsConfig(_Operation):
    operation: Literal["discover_wire_actions"] = Field(
        "discover_wire_actions",
        title="Discover Wire Actions",
        description="Find Wire actions for a task from a natural-language intent. Wire is a catalog of pre-built automation actions across hundreds of websites (Amazon, Walmart, LinkedIn, Airbnb, Zillow, and others) — read actions extract data, write actions perform interactions. Many read actions need no authentication. Returns ranked candidate actions, each with its action_id, type (read/write), required/optional params, credit cost, and whether auth is needed. Run a returned action with Run a Wire Action.",
        json_schema_extra={"ui:hidden": True},
    )
    q: str = Field(
        ...,
        title="Q",
        description='The intent in natural language, e.g. "top phones on walmart", "search airbnb listings in Lisbon", "a linkedin profile\'s work history".',
        min_length=1,
    )
    limit: int = Field(
        5, title="Limit", description="Maximum number of candidate actions to return."
    )


class AnakinListWireCatalogsConfig(_Operation):
    operation: Literal["list_wire_catalogs"] = Field(
        "list_wire_catalogs",
        title="List Wire Catalogs",
        description="List every website supported by Wire and its action count.",
        json_schema_extra={"ui:hidden": True},
    )


class AnakinGetWireCatalogConfig(_Operation):
    operation: Literal["get_wire_catalog"] = Field(
        "get_wire_catalog",
        title="Get a Wire Catalog",
        description="Get one catalog's full action list with exact parameter schemas, each action's type (read/write), auth mode (none/optional/required), and credit cost — plus the login fields for credentials-mode sites.",
        json_schema_extra={"ui:hidden": True},
    )
    slug: str = Field(
        ...,
        title="Slug",
        description='Catalog slug to inspect, e.g. "walmart".',
        min_length=1,
    )


class AnakinRunWireActionConfig(_Operation):
    operation: Literal["run_wire_action"] = Field(
        "run_wire_action",
        title="Run a Wire Action",
        description="Run a Wire action by its action_id — either a READ action that extracts data (search listings, fetch a product's price/specs/reviews, read a profile) or a WRITE action that performs a state-changing interaction (submit a form, add to cart). The action's type, reported by Discover Wire Actions and Get a Wire Catalog, determines which kind it is. params must match that action's parameter schema; omit for actions that take none. Some actions complete synchronously and return their data inline in this same response; others return {status, job_id} — poll GET /wire/jobs/{jobId} for those. Does not execute payments or transfer funds; such actions are refused.",
        json_schema_extra={"ui:hidden": True},
    )
    action_id: str = Field(
        ...,
        title="Action Id",
        description="The action to run (from Discover Wire Actions or Get a Wire Catalog).",
        min_length=1,
    )
    params: dict[str, Any] | None = Field(
        None,
        title="Params",
        description="The action's input parameters. Shape depends on the action — use its parameter schema from discovery. Omit for actions that take none.",
    )
    credential_id: str | None = Field(
        None,
        title="Credential Id",
        description='Required when the action\'s auth_mode is "required"; honored when "optional"; ignored when "none". Get one from List Wire Identities or Sign In to a Wire Site.',
    )
    identity_id: str | None = Field(
        None,
        title="Identity Id",
        description="Optional identity selector — the server resolves a credential from it (alternative to credential_id).",
    )


class AnakinGetWireJobConfig(_Operation):
    operation: Literal["get_wire_job"] = Field(
        "get_wire_job",
        title="Get Wire Job Status",
        description="Fetch the status and result of an asynchronous Wire action job started by Run a Wire Action.",
        json_schema_extra={"ui:hidden": True},
    )
    jobId: str = Field(
        ...,
        title="Job Id",
        description="The job_id returned by Run a Wire Action.",
        min_length=1,
    )


class AnakinListWireIdentitiesConfig(_Operation):
    operation: Literal["list_wire_identities"] = Field(
        "list_wire_identities",
        title="List Wire Identities",
        description='List your saved Wire identities and their credentials. An identity is a named account on a site; each credential\'s id is the credential_id passed to Run a Wire Action for actions whose auth_mode is "required". Optionally filter by catalog_id.',
        json_schema_extra={"ui:hidden": True},
    )
    catalog_id: str | None = Field(
        None,
        title="Catalog Id",
        description="Optional — restrict to identities for a single catalog.",
    )


class AnakinBuildWireActionConfig(_Operation):
    operation: Literal["build_wire_action"] = Field(
        "build_wire_action",
        title="Build a New Wire Action",
        description='Request a brand-new Wire action for a website that isn\'t in the catalog yet. Describe the site (website_url) and what the action should do or extract (goal); Wire generates and auto-tests a scraper, then publishes it. Asynchronous (returns status "pending") and charges credits, refunded automatically if the build fails.',
        json_schema_extra={"ui:hidden": True},
    )
    website_url: str = Field(
        ...,
        title="Website Url",
        description="The site to build an action for. The domain is extracted automatically.",
        min_length=1,
    )
    goal: str = Field(
        ...,
        title="Goal",
        description="Natural-language description of what the action should do or extract. Be specific — the builder synthesizes the scraper from this.",
        min_length=1,
    )
    catalog_id: str | None = Field(
        None,
        title="Catalog Id",
        description="Optional — attach to an existing catalog instead of creating one.",
    )
    visibility: Literal["private", "public"] = Field(
        "private", title="Visibility", description="Action visibility."
    )
    force: bool = Field(
        False,
        title="Force",
        description="Build even if similar actions already exist for the domain (otherwise the request is rejected with ACTION_EXISTS).",
    )
    actions: list[str] | None = Field(
        None,
        title="Actions",
        description='Optional list of separate capabilities to build, each as its own action, for example "search products".',
    )
    country: str | None = Field(
        None,
        title="Country",
        description='Optional 2-letter country code to build and test from, for example "US".',
    )


class AnakinCreateMonitorConfig(_Operation):
    operation: Literal["create_monitor"] = Field(
        "create_monitor",
        title="Create a Website Monitor",
        description='Create a scheduled website monitor that checks a URL every intervalMinutes (min 15) and records a change when the content differs — optionally alerting a webhook or email. scope "page" (default) watches one URL; "site" crawls the site each run and tracks pages added/removed/changed; "wire" runs a Wire action each check and diffs its JSON. watchMode "full_page" (2 credits/check) compares the whole page; "specific_data" (3 credits/check) extracts only the fields in outputSchema with AI — ideal for price/stock/status tracking. aiMode (+1 credit/check) filters out trivial noise and summarizes real changes. Active-monitor caps per plan: Free 5, Pro 20, Scale 100.',
        json_schema_extra={"ui:hidden": True},
    )
    url: str = Field(
        ...,
        title="Url",
        description="The URL to watch (root URL for site scope; the Wire site's URL for wire scope).",
        min_length=1,
        json_schema_extra={"format": "uri"},
    )
    intervalMinutes: int = Field(
        ...,
        title="Interval Minutes",
        description="Check frequency in minutes. Minimum 15.",
        ge=15,
    )
    scope: Literal["page", "site", "wire"] = Field(
        "page",
        title="Scope",
        description="What to monitor: one page (default), a whole site, or a Wire action.",
    )
    watchMode: Literal["full_page", "specific_data"] = Field(
        "full_page",
        title="Watch Mode",
        description="Compare the whole page (default) or only the fields in outputSchema, extracted with AI.",
    )
    watchFormat: Literal["markdown", "html", "cleaned_html"] = Field(
        "markdown",
        title="Watch Format",
        description="Format compared in full_page mode. Defaults to markdown.",
    )
    outputSchema: dict[str, Any] | None = Field(
        None,
        title="Output Schema",
        description='JSON Schema of the fields to track. Required when watchMode is "specific_data".',
    )
    aiMode: bool = Field(
        False,
        title="Ai Mode",
        description="AI meaningful-change filtering: ignores trivial noise (ads, timestamps) and summarizes real changes. +1 credit per check.",
    )
    aiGoal: str | None = Field(
        None,
        title="Ai Goal",
        description='Natural-language description of which changes count as meaningful (used with aiMode), e.g. "only when the price drops or it goes out of stock".',
    )
    useBrowser: bool = Field(
        False,
        title="Use Browser",
        description="Render checks with a stealth headless browser (needed for JS-heavy pages). Forced true when sessionId is set.",
    )
    country: str = Field(
        "us",
        title="Country",
        description='Two-letter proxy country code. Defaults to "us".',
    )
    sessionId: str | None = Field(
        None,
        title="Session Id",
        description="Saved browser-session ID for monitoring login-protected pages (see List Browser Sessions).",
    )
    isActive: bool = Field(
        True,
        title="Is Active",
        description="Start running immediately. Defaults to true.",
    )
    expiresAt: str | None = Field(
        None,
        title="Expires At",
        description="Optional end date (ISO 8601 timestamp or YYYY-MM-DD); the monitor auto-pauses when it passes.",
    )
    alertWebhookUrl: str | None = Field(
        None,
        title="Alert Webhook Url",
        description="Webhook URL that receives signed change alerts.",
    )
    alertEmails: str | None = Field(
        None,
        title="Alert Emails",
        description="Comma-separated email recipients for change alerts.",
    )
    maxPages: int | None = Field(
        None,
        title="Max Pages",
        description="Site scope: max pages crawled per run.",
        ge=1,
    )
    maxDepth: int | None = Field(
        None,
        title="Max Depth",
        description="Site scope: crawl depth (1–5). Defaults to 2.",
        ge=1,
        le=5,
    )
    includePatterns: list[str] | None = Field(
        None,
        title="Include Patterns",
        description="Site scope: glob patterns or hand-picked same-site URLs to track.",
    )
    excludePatterns: list[str] | None = Field(
        None, title="Exclude Patterns", description="Site scope: glob patterns to skip."
    )
    wireActionId: str | None = Field(
        None,
        title="Wire Action Id",
        description='Wire scope (required there): the Wire action run each check, e.g. "amazon.search_products" (see Discover Wire Actions).',
    )
    wireCatalogSlug: str | None = Field(
        None,
        title="Wire Catalog Slug",
        description="Wire scope: catalogue slug of the Wire site.",
    )
    wireCredentialId: str | None = Field(
        None,
        title="Wire Credential Id",
        description="Wire scope: credential ID when the action needs auth (see List Wire Identities).",
    )
    wireParams: dict[str, Any] | None = Field(
        None,
        title="Wire Params",
        description="Wire scope: parameters passed to the action each check.",
    )
    wireWatchPaths: list[str] | None = Field(
        None,
        title="Wire Watch Paths",
        description="Wire scope: JSON paths to diff instead of the whole response.",
    )


class AnakinListMonitorsConfig(_Operation):
    operation: Literal["list_monitors"] = Field(
        "list_monitors",
        title="List Website Monitors",
        description="List your website monitors.",
        json_schema_extra={"ui:hidden": True},
    )


class AnakinGetMonitorConfig(_Operation):
    operation: Literal["get_monitor"] = Field(
        "get_monitor",
        title="Get a Website Monitor",
        description="Fetch one monitor's full configuration and status (next/last check time, active state, per-check credit cost, alert settings).",
        json_schema_extra={"ui:hidden": True},
    )
    id: str = Field(..., title="Id", description="The monitor ID.", min_length=1)


class AnakinDeleteMonitorConfig(_Operation):
    operation: Literal["delete_monitor"] = Field(
        "delete_monitor",
        title="Delete a Website Monitor",
        description="Permanently remove a monitor and its change history. Irreversible.",
        json_schema_extra={"ui:hidden": True},
    )
    id: str = Field(..., title="Id", description="The monitor ID.", min_length=1)


class AnakinGetMonitorChangesConfig(_Operation):
    operation: Literal["get_monitor_changes"] = Field(
        "get_monitor_changes",
        title="Get Monitor Changes",
        description="Get the detected changes for a monitor — each entry records when the watched content differed from the previous check, with a diff/summary (and the AI change summary when aiMode is on).",
        json_schema_extra={"ui:hidden": True},
    )
    id: str = Field(..., title="Id", description="The monitor ID.", min_length=1)


class AnakinPauseMonitorConfig(_Operation):
    operation: Literal["pause_monitor"] = Field(
        "pause_monitor",
        title="Pause a Website Monitor",
        description="Stop scheduled checks for a monitor.",
        json_schema_extra={"ui:hidden": True},
    )
    id: str = Field(..., title="Id", description="The monitor ID.", min_length=1)


class AnakinResumeMonitorConfig(_Operation):
    operation: Literal["resume_monitor"] = Field(
        "resume_monitor",
        title="Resume a Website Monitor",
        description="Restart scheduled checks for a paused monitor. May hit the plan's active-monitor cap.",
        json_schema_extra={"ui:hidden": True},
    )
    id: str = Field(..., title="Id", description="The monitor ID.", min_length=1)


class AnakinRunMonitorConfig(_Operation):
    operation: Literal["run_monitor"] = Field(
        "run_monitor",
        title="Run a Website Monitor Now",
        description="Trigger an immediate out-of-schedule check. Billed like a normal check.",
        json_schema_extra={"ui:hidden": True},
    )
    id: str = Field(..., title="Id", description="The monitor ID.", min_length=1)


# Anakin's own MCP server: agents get its tools through a person's Anakin sign-in.
AnakinIoMcpCredential = mcp_credential("anakin_io", "https://mcp.anakin.io/mcp", app="Anakin")


Operation = Annotated[
    Union[
        AnakinScrapeUrlConfig,
        AnakinScrapeUrlSyncConfig,
        AnakinGetScrapeResultConfig,
        AnakinSearchConfig,
        AnakinStartResearchConfig,
        AnakinGetResearchResultConfig,
        AnakinMapSiteConfig,
        AnakinGetMapResultConfig,
        AnakinCrawlSiteConfig,
        AnakinGetCrawlResultConfig,
        AnakinDiscoverWireActionsConfig,
        AnakinListWireCatalogsConfig,
        AnakinGetWireCatalogConfig,
        AnakinRunWireActionConfig,
        AnakinGetWireJobConfig,
        AnakinListWireIdentitiesConfig,
        AnakinBuildWireActionConfig,
        AnakinCreateMonitorConfig,
        AnakinListMonitorsConfig,
        AnakinGetMonitorConfig,
        AnakinDeleteMonitorConfig,
        AnakinGetMonitorChangesConfig,
        AnakinPauseMonitorConfig,
        AnakinResumeMonitorConfig,
        AnakinRunMonitorConfig,
    ],
    Field(discriminator="operation"),
]


class AnakinIoNodeConfig(NodeConfig[Operation, Union[AnakinIoCredential, AnakinIoMcpCredential]]):
    pass


ROUTES = {
    "scrape_url": {
        "method": "POST",
        "path": "/url-scraper",
        "path_fields": [],
        "query_fields": [],
        "body_fields": [
            "url",
            "country",
            "useBrowser",
            "generateJson",
            "forceFresh",
            "sessionId",
            "sessionName",
        ],
        "statuses": [202],
        "array": False,
    },
    "scrape_url_sync": {
        "method": "POST",
        "path": "/url-scraper/scrape",
        "path_fields": [],
        "query_fields": [],
        "body_fields": [
            "url",
            "country",
            "useBrowser",
            "generateJson",
            "forceFresh",
            "sessionId",
            "sessionName",
        ],
        "statuses": [200, 202],
        "array": False,
    },
    "get_scrape_result": {
        "method": "GET",
        "path": "/url-scraper/{jobId}",
        "path_fields": ["jobId"],
        "query_fields": [],
        "body_fields": [],
        "statuses": [200],
        "array": False,
    },
    "search": {
        "method": "POST",
        "path": "/search",
        "path_fields": [],
        "query_fields": [],
        "body_fields": ["prompt", "limit"],
        "statuses": [200],
        "array": False,
    },
    "start_research": {
        "method": "POST",
        "path": "/agentic-search",
        "path_fields": [],
        "query_fields": [],
        "body_fields": ["prompt", "useBrowser", "schema"],
        "statuses": [202],
        "array": False,
    },
    "get_research_result": {
        "method": "GET",
        "path": "/agentic-search/{jobId}",
        "path_fields": ["jobId"],
        "query_fields": [],
        "body_fields": [],
        "statuses": [200],
        "array": False,
    },
    "map_site": {
        "method": "POST",
        "path": "/map",
        "path_fields": [],
        "query_fields": [],
        "body_fields": [
            "url",
            "limit",
            "depth",
            "limitPerLevel",
            "includeSubdomains",
            "includeExternalLinks",
            "useBrowser",
            "search",
        ],
        "statuses": [202],
        "array": False,
    },
    "get_map_result": {
        "method": "GET",
        "path": "/map/{jobId}",
        "path_fields": ["jobId"],
        "query_fields": [],
        "body_fields": [],
        "statuses": [200],
        "array": False,
    },
    "crawl_site": {
        "method": "POST",
        "path": "/crawl",
        "path_fields": [],
        "query_fields": [],
        "body_fields": [
            "url",
            "maxPages",
            "depth",
            "country",
            "useBrowser",
            "includePatterns",
            "excludePatterns",
            "sessionId",
            "sessionName",
        ],
        "statuses": [202],
        "array": False,
    },
    "get_crawl_result": {
        "method": "GET",
        "path": "/crawl/{jobId}",
        "path_fields": ["jobId"],
        "query_fields": [],
        "body_fields": [],
        "statuses": [200],
        "array": False,
    },
    "discover_wire_actions": {
        "method": "GET",
        "path": "/wire/resolve",
        "path_fields": [],
        "query_fields": ["q", "limit"],
        "body_fields": [],
        "statuses": [200],
        "array": False,
    },
    "list_wire_catalogs": {
        "method": "GET",
        "path": "/wire/catalog",
        "path_fields": [],
        "query_fields": [],
        "body_fields": [],
        "statuses": [200],
        "array": False,
    },
    "get_wire_catalog": {
        "method": "GET",
        "path": "/wire/catalog/{slug}",
        "path_fields": ["slug"],
        "query_fields": [],
        "body_fields": [],
        "statuses": [200],
        "array": False,
    },
    "run_wire_action": {
        "method": "POST",
        "path": "/wire/task",
        "path_fields": [],
        "query_fields": [],
        "body_fields": ["action_id", "params", "credential_id", "identity_id"],
        "statuses": [200],
        "array": False,
    },
    "get_wire_job": {
        "method": "GET",
        "path": "/wire/jobs/{jobId}",
        "path_fields": ["jobId"],
        "query_fields": [],
        "body_fields": [],
        "statuses": [200],
        "array": False,
    },
    "list_wire_identities": {
        "method": "GET",
        "path": "/wire/identities",
        "path_fields": [],
        "query_fields": ["catalog_id"],
        "body_fields": [],
        "statuses": [200],
        "array": False,
    },
    "build_wire_action": {
        "method": "POST",
        "path": "/wire/build-request",
        "path_fields": [],
        "query_fields": [],
        "body_fields": [
            "website_url",
            "goal",
            "catalog_id",
            "visibility",
            "force",
            "actions",
            "country",
        ],
        "statuses": [202],
        "array": False,
    },
    "create_monitor": {
        "method": "POST",
        "path": "/monitors",
        "path_fields": [],
        "query_fields": [],
        "body_fields": [
            "url",
            "intervalMinutes",
            "scope",
            "watchMode",
            "watchFormat",
            "outputSchema",
            "aiMode",
            "aiGoal",
            "useBrowser",
            "country",
            "sessionId",
            "isActive",
            "expiresAt",
            "alertWebhookUrl",
            "alertEmails",
            "maxPages",
            "maxDepth",
            "includePatterns",
            "excludePatterns",
            "wireActionId",
            "wireCatalogSlug",
            "wireCredentialId",
            "wireParams",
            "wireWatchPaths",
        ],
        "statuses": [201],
        "array": False,
    },
    "list_monitors": {
        "method": "GET",
        "path": "/monitors",
        "path_fields": [],
        "query_fields": [],
        "body_fields": [],
        "statuses": [200],
        "array": True,
    },
    "get_monitor": {
        "method": "GET",
        "path": "/monitors/{id}",
        "path_fields": ["id"],
        "query_fields": [],
        "body_fields": [],
        "statuses": [200],
        "array": False,
    },
    "delete_monitor": {
        "method": "DELETE",
        "path": "/monitors/{id}",
        "path_fields": ["id"],
        "query_fields": [],
        "body_fields": [],
        "statuses": [200],
        "array": False,
    },
    "get_monitor_changes": {
        "method": "GET",
        "path": "/monitors/{id}/changes",
        "path_fields": ["id"],
        "query_fields": [],
        "body_fields": [],
        "statuses": [200],
        "array": False,
    },
    "pause_monitor": {
        "method": "POST",
        "path": "/monitors/{id}/pause",
        "path_fields": ["id"],
        "query_fields": [],
        "body_fields": [],
        "statuses": [200],
        "array": False,
    },
    "resume_monitor": {
        "method": "POST",
        "path": "/monitors/{id}/resume",
        "path_fields": ["id"],
        "query_fields": [],
        "body_fields": [],
        "statuses": [200],
        "array": False,
    },
    "run_monitor": {
        "method": "POST",
        "path": "/monitors/{id}/run",
        "path_fields": ["id"],
        "query_fields": [],
        "body_fields": [],
        "statuses": [200],
        "array": False,
    },
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact(item, token)
            for key, item in value.items()
            if key not in {"alertWebhookSecret", "api_key", "apiKey"}
        }
    return value


class AnakinIoNode(WorkflowNode):
    integration_type = "automation-anakin-io"
    credential_provider_labels = {"anakin_io": "Anakin Account"}
    connection_evidence = ConnectionEvidence(noun="monitors", operation="list_monitors")

    @classmethod
    def get_config_model(cls):
        return AnakinIoNodeConfig

    async def execute(self, inputs):
        config = self.config.config
        if not self.config.credentials:
            raise ValueError("Connect an Anakin Io API key")
        token = self.config.credentials.api_key
        route = ROUTES[config.operation]
        values = config.model_dump(
            by_alias=True, exclude_none=True, exclude={"operation"}
        )
        path = route["path"]
        for key in route["path_fields"]:
            path = path.replace("{" + key + "}", quote(values[key], safe=""))
        params = {key: values[key] for key in route["query_fields"] if key in values}
        body = {key: values[key] for key in route["body_fields"] if key in values}
        output = {"operation": config.operation}
        try:
            async with guarded_async_client(
                verify=True,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(110.0),
            ) as client:
                response = await client.request(
                    route["method"],
                    BASE_URL + path,
                    headers={"X-API-Key": token, "Accept": "application/json"},
                    params=params,
                    **({"json": body} if route["body_fields"] else {}),
                )
            if response.status_code not in route["statuses"]:
                # Preserve definitive provider refusals for the manual-connect seam.
                try:
                    detail = response.json()
                    message = (
                        detail.get("message") or detail.get("error")
                        if isinstance(detail, dict)
                        else None
                    )
                except ValueError:
                    message = None
                return {
                    **output,
                    "status": "error",
                    "http_status": response.status_code,
                    "error": _redact(message, token)
                    if isinstance(message, str)
                    else "Anakin did not accept the request (HTTP "
                    + str(response.status_code)
                    + ")",
                }
            payload = response.json()
            if not isinstance(payload, list if route["array"] else dict):
                raise ValueError("Unexpected Anakin response shape")
            if isinstance(payload, list) and not all(
                isinstance(item, dict) for item in payload
            ):
                raise ValueError("Unexpected monitor list")
            data = _redact(payload, token)
            if isinstance(payload, dict) and (
                payload.get("error")
                or payload.get("success") is False
                or payload.get("status") in {"failed", "error", "timed_out"}
            ):
                return {
                    **output,
                    "status": "error",
                    "data": data,
                    "error": data.get("error") or "Anakin reported a failed job",
                }
            return {
                **output,
                "status": "success",
                "http_status": response.status_code,
                **({"items": data} if route["array"] else {"data": data}),
            }
        except (httpx.HTTPError, SSRFError, ValueError):
            return {
                **output,
                "status": "error",
                "error": "Anakin request could not be confirmed; inspect job or monitor state before retrying a write",
            }
