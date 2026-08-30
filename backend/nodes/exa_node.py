"""
Exa AI search & web-retrieval automation node.

Provides workflow integration with the Exa REST API for operations including:
- Search: neural/keyword/auto web search, get contents, answer, find similar
- Agent runs: create/get/list/cancel asynchronous deep-research agent runs
- Monitors: create/list/get/update/delete/trigger scheduled recurring searches
- Websets: create/get/list/update/delete websets, items, enrichments, webhooks, events
- Team management: create/list API keys, get API-key usage
- Webhook Trigger: fire when a Monitor delivers new search results

Authentication: API Key via the `x-api-key` header (Exa has no OAuth 2.0 flow).
Search/contents/answer/find_similar can also run credential-less on NoClick's
platform key (EXA_API_KEY), metered to credits from the response's costDollars.
API Base URL: https://api.exa.ai  (Websets live under /websets/v0)
Documentation: https://exa.ai/docs/reference/getting-started
"""

import hashlib
import hmac
import logging
import os
import time
from decimal import Decimal
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin

logger = logging.getLogger(__name__)

EXA_API_BASE = "https://api.exa.ai"

from nodes.core.platform_billing import platform_keyed_operation, require_platform_key

# Runs on NoClick's Exa key when no credential is attached (nodes/core/platform_billing.py).
PLATFORM_KEYED = platform_keyed_operation("EXA_API_KEY", byok=True)

# Synchronous ops that may run on NoClick's platform key with no user credential,
# metered from the response's in-band costDollars. Async/recurring surfaces
# (agent runs, websets, monitors) stay BYOK-only — their spend accrues outside
# the node execution, so a platform key there would fund untracked usage.
PLATFORM_METERED_OPERATIONS = {"search", "get_contents", "answer", "find_similar"}


# ============================================================================
# Credential Schema
# ============================================================================


class ExaApiKeyCredential(BaseModel):
    """API Key credential for Exa."""

    credential_type: Literal["exa_api_key"] = Field(
        "exa_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Exa API key from the API Dashboard (dashboard.exa.ai/api-keys). Sent as the x-api-key header.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://dashboard.exa.ai/api-keys"}
    )


ExaCredential = ExaApiKeyCredential


# ============================================================================
# Operation Configs — Search
# ============================================================================


class ExaSearchConfig(BaseModel):
    """Search the web with Exa's neural/keyword/auto search."""

    model_config = ConfigDict(json_schema_extra=PLATFORM_KEYED)

    operation: Literal["search"] = Field(
        "search",
        json_schema_extra={
            "const": "search",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search",
        },
        title="Search",
    )
    query: str = Field(..., title="Query", description="The search query string")
    search_type: Optional[str] = Field(
        "auto",
        title="Search Type",
        description="How to interpret the query",
        json_schema_extra={
            "enum": ["auto", "neural", "keyword", "fast"],
            "enumNames": ["Auto", "Neural", "Keyword", "Fast"],
            "x-enum-searchable": True,
        },
    )
    num_results: Optional[str] = Field(
        "10", title="Number of Results", description="How many results to return (1-100)"
    )
    category: Optional[str] = Field(
        None,
        title="Category",
        description="Restrict to a data category (e.g. company, research paper, news, pdf)",
    )
    include_domains: Optional[str] = Field(
        None, title="Include Domains", description="Only these domains, comma-separated"
    )
    exclude_domains: Optional[str] = Field(
        None, title="Exclude Domains", description="Exclude these domains, comma-separated"
    )
    include_text: str = Field(
        "false",
        title="Include Page Text",
        description="Return parsed page text inline with each result",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class ExaGetContentsConfig(BaseModel):
    """Retrieve clean, LLM-ready parsed content for a list of URLs."""

    model_config = ConfigDict(json_schema_extra=PLATFORM_KEYED)

    operation: Literal["get_contents"] = Field(
        "get_contents",
        json_schema_extra={
            "const": "get_contents",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Get Contents",
        },
        title="Get Contents",
    )
    urls: str = Field(
        ..., title="URLs", description="URLs to fetch content for, comma-separated"
    )
    include_text: str = Field(
        "true",
        title="Include Text",
        description="Return full parsed page text",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    include_highlights: str = Field(
        "false",
        title="Include Highlights",
        description="Return relevant highlighted snippets",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    include_summary: str = Field(
        "false",
        title="Include Summary",
        description="Return an LLM-generated summary of each page",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    livecrawl: Optional[str] = Field(
        None,
        title="Live Crawl",
        description="Content freshness mode",
        json_schema_extra={
            "enum": ["", "never", "fallback", "always", "preferred"],
            "enumNames": ["Default", "Never", "Fallback", "Always", "Preferred"],
            "x-enum-searchable": True,
        },
    )


class ExaAnswerConfig(BaseModel):
    """Get an LLM-generated answer grounded with citations from an Exa search."""

    model_config = ConfigDict(json_schema_extra=PLATFORM_KEYED)

    operation: Literal["answer"] = Field(
        "answer",
        json_schema_extra={
            "const": "answer",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Answer",
        },
        title="Answer",
    )
    query: str = Field(..., title="Question", description="The question to answer")
    include_text: str = Field(
        "false",
        title="Include Source Text",
        description="Include the full text of the citation sources in the response",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class ExaFindSimilarConfig(BaseModel):
    """Find pages semantically similar to a given URL."""

    model_config = ConfigDict(json_schema_extra=PLATFORM_KEYED)

    operation: Literal["find_similar"] = Field(
        "find_similar",
        json_schema_extra={
            "const": "find_similar",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Find Similar",
        },
        title="Find Similar",
    )
    url: str = Field(..., title="URL", description="The URL to find similar pages for")
    num_results: Optional[str] = Field(
        "10", title="Number of Results", description="How many similar results to return (1-100)"
    )
    exclude_source_domain: str = Field(
        "false",
        title="Exclude Source Domain",
        description="Exclude results from the same domain as the source URL",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


# ============================================================================
# Operation Configs — Agent Runs
# ============================================================================


class ExaCreateAgentRunConfig(BaseModel):
    """Create an asynchronous Agent run for deep research, list-building, or enrichment."""

    operation: Literal["create_agent_run"] = Field(
        "create_agent_run",
        json_schema_extra={
            "const": "create_agent_run",
            "ui:hidden": True,
            "x-category": "Agent",
            "x-is-trigger": False,
            "x-display-name": "Create Agent Run",
        },
        title="Create Agent Run",
    )
    query: str = Field(
        ..., title="Query", description="The research question or task for the agent run"
    )
    model: Optional[str] = Field(
        None, title="Model", description="Optional model override for the agent run"
    )


class ExaGetAgentRunConfig(BaseModel):
    """Retrieve an Agent run by ID (status, output, citations)."""

    operation: Literal["get_agent_run"] = Field(
        "get_agent_run",
        json_schema_extra={
            "const": "get_agent_run",
            "ui:hidden": True,
            "x-category": "Agent",
            "x-is-trigger": False,
            "x-display-name": "Get Agent Run",
        },
        title="Get Agent Run",
    )
    run_id: str = Field(..., title="Run ID", description="The ID of the agent run to retrieve")


class ExaListAgentRunsConfig(BaseModel):
    """Retrieve a paginated list of Agent runs for your team."""

    operation: Literal["list_agent_runs"] = Field(
        "list_agent_runs",
        json_schema_extra={
            "const": "list_agent_runs",
            "ui:hidden": True,
            "x-category": "Agent",
            "x-is-trigger": False,
            "x-display-name": "List Agent Runs",
        },
        title="List Agent Runs",
    )
    limit: Optional[str] = Field("25", title="Limit", description="Max number of runs to return")
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class ExaCancelAgentRunConfig(BaseModel):
    """Cancel a queued or running Agent run."""

    operation: Literal["cancel_agent_run"] = Field(
        "cancel_agent_run",
        json_schema_extra={
            "const": "cancel_agent_run",
            "ui:hidden": True,
            "x-category": "Agent",
            "x-is-trigger": False,
            "x-display-name": "Cancel Agent Run",
        },
        title="Cancel Agent Run",
    )
    run_id: str = Field(..., title="Run ID", description="The ID of the agent run to cancel")


# ============================================================================
# Operation Configs — Monitors
# ============================================================================


class ExaCreateMonitorConfig(BaseModel):
    """Create a Monitor that runs a recurring Exa search and delivers results to a webhook."""

    operation: Literal["create_monitor"] = Field(
        "create_monitor",
        json_schema_extra={
            "const": "create_monitor",
            "ui:hidden": True,
            "x-category": "Monitors",
            "x-is-trigger": False,
            "x-display-name": "Create Monitor",
            "x-creates-resource": True,
            "x-resource-type": "exa_monitor",
            "x-resource-id-path": "data.id",
        },
        title="Create Monitor",
    )
    query: str = Field(..., title="Query", description="The recurring search query")
    webhook_url: str = Field(
        ..., title="Webhook URL", description="URL that monitor results are POSTed to"
    )
    name: Optional[str] = Field(None, title="Name", description="Optional name for the monitor")


class ExaListMonitorsConfig(BaseModel):
    """List all monitors for the authenticated team."""

    operation: Literal["list_monitors"] = Field(
        "list_monitors",
        json_schema_extra={
            "const": "list_monitors",
            "ui:hidden": True,
            "x-category": "Monitors",
            "x-is-trigger": False,
            "x-display-name": "List Monitors",
        },
        title="List Monitors",
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")
    limit: Optional[str] = Field("25", title="Limit", description="Max number of monitors to return")


class ExaGetMonitorConfig(BaseModel):
    """Retrieve a single monitor by ID."""

    operation: Literal["get_monitor"] = Field(
        "get_monitor",
        json_schema_extra={
            "const": "get_monitor",
            "ui:hidden": True,
            "x-category": "Monitors",
            "x-is-trigger": False,
            "x-display-name": "Get Monitor",
        },
        title="Get Monitor",
    )
    monitor_id: str = Field(
        ...,
        title="Monitor",
        description="The monitor to retrieve",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "monitor_id",
                "placeholder": "Select a monitor...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste monitor ID",
            },
            "x-resource-type": "exa_monitor",
        },
    )


class ExaUpdateMonitorConfig(BaseModel):
    """Update an existing monitor (schedule, search config)."""

    operation: Literal["update_monitor"] = Field(
        "update_monitor",
        json_schema_extra={
            "const": "update_monitor",
            "ui:hidden": True,
            "x-category": "Monitors",
            "x-is-trigger": False,
            "x-display-name": "Update Monitor",
        },
        title="Update Monitor",
    )
    monitor_id: str = Field(
        ...,
        title="Monitor",
        description="The monitor to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "monitor_id",
                "placeholder": "Select a monitor...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste monitor ID",
            },
            "x-resource-type": "exa_monitor",
        },
    )
    query: Optional[str] = Field(None, title="Query", description="New search query")
    name: Optional[str] = Field(None, title="Name", description="New monitor name")


class ExaDeleteMonitorConfig(BaseModel):
    """Delete a monitor (irreversible)."""

    operation: Literal["delete_monitor"] = Field(
        "delete_monitor",
        json_schema_extra={
            "const": "delete_monitor",
            "ui:hidden": True,
            "x-category": "Monitors",
            "x-is-trigger": False,
            "x-display-name": "Delete Monitor",
        },
        title="Delete Monitor",
    )
    monitor_id: str = Field(
        ...,
        title="Monitor",
        description="The monitor to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "monitor_id",
                "placeholder": "Select a monitor...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste monitor ID",
            },
            "x-resource-type": "exa_monitor",
        },
    )


class ExaTriggerMonitorConfig(BaseModel):
    """Trigger a monitor run immediately regardless of schedule."""

    operation: Literal["trigger_monitor"] = Field(
        "trigger_monitor",
        json_schema_extra={
            "const": "trigger_monitor",
            "ui:hidden": True,
            "x-category": "Monitors",
            "x-is-trigger": False,
            "x-display-name": "Trigger Monitor",
        },
        title="Trigger Monitor",
    )
    monitor_id: str = Field(
        ...,
        title="Monitor",
        description="The monitor to trigger",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "monitor_id",
                "placeholder": "Select a monitor...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste monitor ID",
            },
            "x-resource-type": "exa_monitor",
        },
    )


class ExaListMonitorRunsConfig(BaseModel):
    """List runs for a monitor (reverse-chronological)."""

    operation: Literal["list_monitor_runs"] = Field(
        "list_monitor_runs",
        json_schema_extra={
            "const": "list_monitor_runs",
            "ui:hidden": True,
            "x-category": "Monitors",
            "x-is-trigger": False,
            "x-display-name": "List Monitor Runs",
        },
        title="List Monitor Runs",
    )
    monitor_id: str = Field(
        ...,
        title="Monitor",
        description="The monitor whose runs to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "monitor_id",
                "placeholder": "Select a monitor...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste monitor ID",
            },
            "x-resource-type": "exa_monitor",
        },
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


# ============================================================================
# Operation Configs — Websets
# ============================================================================


class ExaCreateWebsetConfig(BaseModel):
    """Create a Webset (search + optional enrichment); begins processing automatically."""

    operation: Literal["create_webset"] = Field(
        "create_webset",
        json_schema_extra={
            "const": "create_webset",
            "ui:hidden": True,
            "x-category": "Websets",
            "x-is-trigger": False,
            "x-display-name": "Create Webset",
        },
        title="Create Webset",
    )
    query: str = Field(..., title="Search Query", description="The search query for the webset")
    count: Optional[str] = Field(
        "10", title="Count", description="Target number of verified items"
    )


class ExaGetWebsetConfig(BaseModel):
    """Retrieve a Webset by ID."""

    operation: Literal["get_webset"] = Field(
        "get_webset",
        json_schema_extra={
            "const": "get_webset",
            "ui:hidden": True,
            "x-category": "Websets",
            "x-is-trigger": False,
            "x-display-name": "Get Webset",
        },
        title="Get Webset",
    )
    webset_id: str = Field(..., title="Webset ID", description="The ID of the webset to retrieve")
    expand_items: Optional[bool] = Field(
        False, title="Expand Items", description="Include the webset's items inline"
    )


class ExaListWebsetsConfig(BaseModel):
    """List all Websets for the team."""

    operation: Literal["list_websets"] = Field(
        "list_websets",
        json_schema_extra={
            "const": "list_websets",
            "ui:hidden": True,
            "x-category": "Websets",
            "x-is-trigger": False,
            "x-display-name": "List Websets",
        },
        title="List Websets",
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")
    limit: Optional[str] = Field("25", title="Limit", description="Max number of websets to return")


class ExaUpdateWebsetConfig(BaseModel):
    """Update a Webset's metadata/configuration."""

    operation: Literal["update_webset"] = Field(
        "update_webset",
        json_schema_extra={
            "const": "update_webset",
            "ui:hidden": True,
            "x-category": "Websets",
            "x-is-trigger": False,
            "x-display-name": "Update Webset",
        },
        title="Update Webset",
    )
    webset_id: str = Field(..., title="Webset ID", description="The ID of the webset to update")
    metadata: Optional[str] = Field(
        None,
        title="Metadata (JSON)",
        description="JSON object of metadata to set on the webset",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ExaDeleteWebsetConfig(BaseModel):
    """Delete a Webset."""

    operation: Literal["delete_webset"] = Field(
        "delete_webset",
        json_schema_extra={
            "const": "delete_webset",
            "ui:hidden": True,
            "x-category": "Websets",
            "x-is-trigger": False,
            "x-display-name": "Delete Webset",
        },
        title="Delete Webset",
    )
    webset_id: str = Field(..., title="Webset ID", description="The ID of the webset to delete")


class ExaListWebsetItemsConfig(BaseModel):
    """List the verified/enriched result items in a Webset."""

    operation: Literal["list_webset_items"] = Field(
        "list_webset_items",
        json_schema_extra={
            "const": "list_webset_items",
            "ui:hidden": True,
            "x-category": "Websets",
            "x-is-trigger": False,
            "x-display-name": "List Webset Items",
        },
        title="List Webset Items",
    )
    webset_id: str = Field(..., title="Webset ID", description="The ID of the webset")
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")
    limit: Optional[str] = Field("25", title="Limit", description="Max number of items to return")


class ExaCreateWebsetEnrichmentConfig(BaseModel):
    """Add an enrichment column (extract/classify a field) to a Webset."""

    operation: Literal["create_webset_enrichment"] = Field(
        "create_webset_enrichment",
        json_schema_extra={
            "const": "create_webset_enrichment",
            "ui:hidden": True,
            "x-category": "Websets",
            "x-is-trigger": False,
            "x-display-name": "Create Webset Enrichment",
        },
        title="Create Webset Enrichment",
    )
    webset_id: str = Field(..., title="Webset ID", description="The ID of the webset")
    description: str = Field(
        ..., title="Description", description="What to extract or classify for each item"
    )
    enrichment_format: Optional[str] = Field(
        "text",
        title="Format",
        description="The enrichment output format",
        json_schema_extra={
            "enum": ["text", "date", "number", "options", "email", "phone"],
            "enumNames": ["Text", "Date", "Number", "Options", "Email", "Phone"],
            "x-enum-searchable": True,
        },
    )


class ExaCreateWebsetWebhookConfig(BaseModel):
    """Register a webhook to receive Websets event notifications."""

    operation: Literal["create_webset_webhook"] = Field(
        "create_webset_webhook",
        json_schema_extra={
            "const": "create_webset_webhook",
            "ui:hidden": True,
            "x-category": "Websets",
            "x-is-trigger": False,
            "x-display-name": "Create Webset Webhook",
        },
        title="Create Webset Webhook",
    )
    webhook_url: str = Field(
        ..., title="Webhook URL", description="URL that Websets events are POSTed to"
    )
    events: Optional[str] = Field(
        None,
        title="Events",
        description="Event types to subscribe to, comma-separated (default: all)",
    )


class ExaListWebsetsEventsConfig(BaseModel):
    """List events that have occurred (webset/item/enrichment lifecycle)."""

    operation: Literal["list_websets_events"] = Field(
        "list_websets_events",
        json_schema_extra={
            "const": "list_websets_events",
            "ui:hidden": True,
            "x-category": "Websets",
            "x-is-trigger": False,
            "x-display-name": "List Websets Events",
        },
        title="List Websets Events",
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")
    limit: Optional[str] = Field("25", title="Limit", description="Max number of events to return")




# ============================================================================
# Webhook Trigger Config
# ============================================================================


class ExaMonitorTriggerConfig(BaseModel):
    """Fire the workflow when an Exa Monitor delivers new search results.

    A Monitor (recurring scheduled search) is created via the Exa API and
    configured to POST results to this node's webhook URL.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_monitor_results"] = Field(
        "on_monitor_results",
        json_schema_extra={
            "const": "on_monitor_results",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Monitor Results",
        },
        title="On Monitor Results",
    )
    monitor_query: str = Field(
        ...,
        title="Search Query",
        description="The recurring search query the monitor runs",
    )
    cadence: str = Field(
        "0 9 * * *",
        title="Cadence (Cron)",
        description="How often the monitor runs, as a cron expression (default: daily at 9am UTC)",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Exa posts new monitor results here. Registered automatically when you connect credentials.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    monitor_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


ExaConfig = Annotated[
    Union[
        ExaSearchConfig,
        ExaGetContentsConfig,
        ExaAnswerConfig,
        ExaFindSimilarConfig,
        ExaCreateAgentRunConfig,
        ExaGetAgentRunConfig,
        ExaListAgentRunsConfig,
        ExaCancelAgentRunConfig,
        ExaCreateMonitorConfig,
        ExaListMonitorsConfig,
        ExaGetMonitorConfig,
        ExaUpdateMonitorConfig,
        ExaDeleteMonitorConfig,
        ExaTriggerMonitorConfig,
        ExaListMonitorRunsConfig,
        ExaCreateWebsetConfig,
        ExaGetWebsetConfig,
        ExaListWebsetsConfig,
        ExaUpdateWebsetConfig,
        ExaDeleteWebsetConfig,
        ExaListWebsetItemsConfig,
        ExaCreateWebsetEnrichmentConfig,
        ExaCreateWebsetWebhookConfig,
        ExaListWebsetsEventsConfig,
        ExaMonitorTriggerConfig,
    ],
    Discriminator("operation"),
]


class ExaNodeConfig(NodeConfig[ExaConfig, ExaCredential]):
    """Full configuration for the Exa node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


async def _exa_request(
    api_key: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Exa request and return a structured result.

    Auth is the `x-api-key` header (NOT Authorization: Bearer). Endpoint paths
    that start with /websets resolve under the same base host.
    """
    url = f"{EXA_API_BASE}{endpoint}"
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    if isinstance(err, dict):
                        message = err.get("error") or err.get("message") or str(err)
                        if isinstance(message, dict):
                            message = message.get("message") or str(message)
                    else:
                        message = str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[ExaNode] API error ({action_name}): {message}")
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
                    data = response.json()
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
            logger.error(f"[ExaNode] Request failed ({action_name}): {msg}")
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


class ExaNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Exa AI search & web-retrieval automation node."""

    edit_examples = [
        "Search the web for recent articles about AI agents",
        "Get clean parsed content for a list of URLs",
        "Answer a question with cited sources from the web",
        "Find pages similar to a competitor's homepage",
        "Trigger a workflow whenever a scheduled Exa monitor finds new results",
    ]

    @classmethod
    def get_config_model(cls):
        return ExaNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (monitors)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        user_id: str,
        config_data: Dict[str, Any],
        credential_ids: Optional[Dict[str, str]] = None,
        pool=None,
    ) -> Dict[str, Any]:
        if field_name != "monitor_id":
            return {"options": []}
        from utils.credential_loader import load_credential

        credential_id = next((cid for cid in (credential_ids or {}).values() if cid), None)
        credential = await load_credential(pool, user_id, credential_id) if credential_id else None
        if not credential:
            return {"options": []}
        api_key = credential.get("api_key")
        result = await _exa_request(
            api_key, "GET", "/monitors", params={"limit": "100"}, action_name="list_monitors"
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        monitors = data.get("data") if isinstance(data, dict) else data
        if not isinstance(monitors, list):
            monitors = []
        options = []
        for m in monitors:
            if not isinstance(m, dict):
                continue
            mid = m.get("id")
            label = m.get("query") or m.get("name") or f"Monitor {mid}"
            if mid is not None:
                options.append({"label": str(label), "value": str(mid)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Webhook trigger registration (Monitors)
    # ------------------------------------------------------------------
    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "monitor_query": (config or {}).get("monitor_query"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        api_key = credential.get("api_key")
        if not api_key:
            raise ValueError("An Exa API key is required to register the trigger")
        query = (config or {}).get("monitor_query")
        if not query:
            raise ValueError("A search query is required to create the monitor")
        result = await _exa_request(
            api_key,
            "POST",
            "/monitors",
            json_body={"search": {"query": query}, "webhook": {"url": webhook_url}},
            action_name="register_monitor",
        )
        if result.get("status") != "success":
            raise ValueError(f"Exa monitor registration failed: {result.get('error')}")
        data = result.get("data") or {}
        monitor_id = data.get("id") if isinstance(data, dict) else None
        # Use the API-provided webhookSecret for signature verification
        signing_secret = data.get("webhookSecret") if isinstance(data, dict) else None
        return {
            "external_webhook_id": str(monitor_id) if monitor_id else None,
            "monitor_id": str(monitor_id) if monitor_id else None,
            "signing_secret": signing_secret,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        monitor_id = (config or {}).get("external_webhook_id") or (config or {}).get("monitor_id")
        api_key = (credential or {}).get("api_key")
        if not monitor_id or not api_key:
            return
        await _exa_request(
            api_key, "DELETE", f"/monitors/{monitor_id}", action_name="unregister_monitor"
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored — accept (trigger not yet armed)
        sent = (
            headers.get("exa-signature")
            or headers.get("x-exa-signature")
            or headers.get("svix-signature")
        )
        if not sent:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sent)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, ExaNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, ExaMonitorTriggerConfig):
            return {
                "status": "success",
                "action": "on_monitor_results",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        platform_keyed = credentials is None and op.operation in PLATFORM_METERED_OPERATIONS
        if platform_keyed:
            if not self.user_id:
                raise ValueError("[ExaNode] No user context — cannot meter Exa usage.")
            api_key = self._get_platform_api_key()
            from billing.usage_tracker import usage_tracker

            await usage_tracker.enforce_credit_gate(
                self.user_id,
                organization_id=self.organization_id,
                sio=self.sio,
                sid=self.sid,
                user_resource=False,
                surface="exa",
            )
        elif credentials:
            api_key = credentials.api_key
        else:
            raise ValueError("Credentials are required. Add your Exa API key.")

        handlers = {
            "search": self._search,
            "get_contents": self._get_contents,
            "answer": self._answer,
            "find_similar": self._find_similar,
            "create_agent_run": self._create_agent_run,
            "get_agent_run": self._get_agent_run,
            "list_agent_runs": self._list_agent_runs,
            "cancel_agent_run": self._cancel_agent_run,
            "create_monitor": self._create_monitor,
            "list_monitors": self._list_monitors,
            "get_monitor": self._get_monitor,
            "update_monitor": self._update_monitor,
            "delete_monitor": self._delete_monitor,
            "trigger_monitor": self._trigger_monitor,
            "list_monitor_runs": self._list_monitor_runs,
            "create_webset": self._create_webset,
            "get_webset": self._get_webset,
            "list_websets": self._list_websets,
            "update_webset": self._update_webset,
            "delete_webset": self._delete_webset,
            "list_webset_items": self._list_webset_items,
            "create_webset_enrichment": self._create_webset_enrichment,
            "create_webset_webhook": self._create_webset_webhook,
            "list_websets_events": self._list_websets_events,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key)
        if platform_keyed and result.get("status") == "success":
            await self._track_platform_usage(op.operation, result)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Platform-keyed billing
    # ------------------------------------------------------------------
    @staticmethod
    def _get_platform_api_key() -> str:
        return require_platform_key("EXA_API_KEY", "Exa", byok=True)

    async def _track_platform_usage(self, operation: str, result: Dict[str, Any]) -> None:
        """Bill a NoClick-keyed call from the response's in-band costDollars.

        A metered response without costDollars is a hard error — silently
        booking $0 is the failure mode this path exists to prevent.
        """
        from billing.markup import (
            apply_exa_markup,
            round_up_to_credit_step,
        )
        from billing.schema import UsageEventData
        from billing.usage_tracker import usage_tracker

        data = result.get("data")
        cost_obj = data.get("costDollars") if isinstance(data, dict) else None
        cost = cost_obj.get("total") if isinstance(cost_obj, dict) else None
        if cost is None:
            raise ValueError(
                f"Exa response for '{operation}' has no costDollars — "
                "cannot meter platform-keyed usage"
            )
        raw = Decimal(str(cost))
        charged = round_up_to_credit_step(apply_exa_markup(raw))
        # Raw runner + org id; track_usage_event resolves the org owner
        # centrally (organization attribution policy choke point).
        await usage_tracker.track_usage_event(
            UsageEventData(
                user_id=self.user_id,
                total_cost=charged,
                usage_type="api_usage",
                usage_subtype="exa/search_api",
                quantity=Decimal("1"),
                unit_type="requests",
                user_resource=False,
                organization_id=self.organization_id,
                metadata={
                    "provider": "exa",
                    "operation": operation,
                    "raw_cost_usd": float(raw),
                    "charged_cost_usd": float(charged),
                },
            ),
            sio=self.sio,
            sid=self.sid,
        )

    # ------------------------------------------------------------------
    # Handlers — Search
    # ------------------------------------------------------------------
    async def _search(self, c: ExaSearchConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "query": c.query,
            "type": c.search_type or None,
            "numResults": int(c.num_results) if c.num_results and str(c.num_results).isdigit() else None,
            "category": c.category or None,
            "includeDomains": _comma_list(c.include_domains),
            "excludeDomains": _comma_list(c.exclude_domains),
        }
        if c.include_text == "true":
            body["contents"] = {"text": True}
        return await _exa_request(api_key, "POST", "/search", json_body=body, action_name="search")

    async def _get_contents(self, c: ExaGetContentsConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"urls": _comma_list(c.urls)}
        if c.include_text == "true":
            body["text"] = True
        if c.include_highlights == "true":
            body["highlights"] = True
        if c.include_summary == "true":
            body["summary"] = True
        if c.livecrawl:
            body["livecrawl"] = c.livecrawl
        return await _exa_request(api_key, "POST", "/contents", json_body=body, action_name="get_contents")

    async def _answer(self, c: ExaAnswerConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"query": c.query, "text": c.include_text == "true"}
        return await _exa_request(api_key, "POST", "/answer", json_body=body, action_name="answer")

    async def _find_similar(self, c: ExaFindSimilarConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "url": c.url,
            "numResults": int(c.num_results) if c.num_results and str(c.num_results).isdigit() else None,
            "excludeSourceDomain": c.exclude_source_domain == "true",
        }
        return await _exa_request(api_key, "POST", "/findSimilar", json_body=body, action_name="find_similar")

    # ------------------------------------------------------------------
    # Handlers — Agent Runs
    # ------------------------------------------------------------------
    async def _create_agent_run(self, c: ExaCreateAgentRunConfig, api_key: str) -> Dict[str, Any]:
        body = {"query": c.query, "model": c.model or None}
        return await _exa_request(api_key, "POST", "/agent/runs", json_body=body, action_name="create_agent_run")

    async def _get_agent_run(self, c: ExaGetAgentRunConfig, api_key: str) -> Dict[str, Any]:
        return await _exa_request(api_key, "GET", f"/agent/runs/{c.run_id}", action_name="get_agent_run")

    async def _list_agent_runs(self, c: ExaListAgentRunsConfig, api_key: str) -> Dict[str, Any]:
        return await _exa_request(
            api_key, "GET", "/agent/runs",
            params={"limit": c.limit, "cursor": c.cursor}, action_name="list_agent_runs"
        )

    async def _cancel_agent_run(self, c: ExaCancelAgentRunConfig, api_key: str) -> Dict[str, Any]:
        return await _exa_request(
            api_key, "POST", f"/agent/runs/{c.run_id}/cancel", action_name="cancel_agent_run"
        )

    # ------------------------------------------------------------------
    # Handlers — Monitors
    # ------------------------------------------------------------------
    async def _create_monitor(self, c: ExaCreateMonitorConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "search": {"query": c.query},
            "webhook": {"url": c.webhook_url},
        }
        if c.name:
            body["name"] = c.name
        return await _exa_request(api_key, "POST", "/monitors", json_body=body, action_name="create_monitor")

    async def _list_monitors(self, c: ExaListMonitorsConfig, api_key: str) -> Dict[str, Any]:
        return await _exa_request(
            api_key, "GET", "/monitors",
            params={"cursor": c.cursor, "limit": c.limit}, action_name="list_monitors"
        )

    async def _get_monitor(self, c: ExaGetMonitorConfig, api_key: str) -> Dict[str, Any]:
        return await _exa_request(api_key, "GET", f"/monitors/{c.monitor_id}", action_name="get_monitor")

    async def _update_monitor(self, c: ExaUpdateMonitorConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if c.query:
            body["search"] = {"query": c.query}
        if c.name:
            body["name"] = c.name
        return await _exa_request(
            api_key, "PATCH", f"/monitors/{c.monitor_id}", json_body=body, action_name="update_monitor"
        )

    async def _delete_monitor(self, c: ExaDeleteMonitorConfig, api_key: str) -> Dict[str, Any]:
        return await _exa_request(
            api_key, "DELETE", f"/monitors/{c.monitor_id}", action_name="delete_monitor"
        )

    async def _trigger_monitor(self, c: ExaTriggerMonitorConfig, api_key: str) -> Dict[str, Any]:
        return await _exa_request(
            api_key, "POST", f"/monitors/{c.monitor_id}/runs", action_name="trigger_monitor"
        )

    async def _list_monitor_runs(self, c: ExaListMonitorRunsConfig, api_key: str) -> Dict[str, Any]:
        return await _exa_request(
            api_key, "GET", f"/monitors/{c.monitor_id}/runs",
            params={"cursor": c.cursor}, action_name="list_monitor_runs"
        )

    # ------------------------------------------------------------------
    # Handlers — Websets
    # ------------------------------------------------------------------
    async def _create_webset(self, c: ExaCreateWebsetConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "search": {
                "query": c.query,
                "count": int(c.count) if c.count and str(c.count).isdigit() else None,
            }
        }
        return await _exa_request(
            api_key, "POST", "/websets/v0/websets", json_body=body, action_name="create_webset"
        )

    async def _get_webset(self, c: ExaGetWebsetConfig, api_key: str) -> Dict[str, Any]:
        params = {"expand": "items"} if c.expand_items else None
        return await _exa_request(
            api_key, "GET", f"/websets/v0/websets/{c.webset_id}", params=params, action_name="get_webset"
        )

    async def _list_websets(self, c: ExaListWebsetsConfig, api_key: str) -> Dict[str, Any]:
        return await _exa_request(
            api_key, "GET", "/websets/v0/websets",
            params={"cursor": c.cursor, "limit": c.limit}, action_name="list_websets"
        )

    async def _update_webset(self, c: ExaUpdateWebsetConfig, api_key: str) -> Dict[str, Any]:
        import json as _json

        body: Dict[str, Any] = {}
        if c.metadata:
            body["metadata"] = _json.loads(c.metadata)
        return await _exa_request(
            api_key, "POST", f"/websets/v0/websets/{c.webset_id}", json_body=body, action_name="update_webset"
        )

    async def _delete_webset(self, c: ExaDeleteWebsetConfig, api_key: str) -> Dict[str, Any]:
        return await _exa_request(
            api_key, "DELETE", f"/websets/v0/websets/{c.webset_id}", action_name="delete_webset"
        )

    async def _list_webset_items(self, c: ExaListWebsetItemsConfig, api_key: str) -> Dict[str, Any]:
        return await _exa_request(
            api_key, "GET", f"/websets/v0/websets/{c.webset_id}/items",
            params={"cursor": c.cursor, "limit": c.limit}, action_name="list_webset_items"
        )

    async def _create_webset_enrichment(
        self, c: ExaCreateWebsetEnrichmentConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {"description": c.description, "format": c.enrichment_format or "text"}
        return await _exa_request(
            api_key, "POST", f"/websets/v0/websets/{c.webset_id}/enrichments",
            json_body=body, action_name="create_webset_enrichment"
        )

    async def _create_webset_webhook(
        self, c: ExaCreateWebsetWebhookConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {"url": c.webhook_url, "events": _comma_list(c.events)}
        return await _exa_request(
            api_key, "POST", "/websets/v0/webhooks", json_body=body, action_name="create_webset_webhook"
        )

    async def _list_websets_events(self, c: ExaListWebsetsEventsConfig, api_key: str) -> Dict[str, Any]:
        return await _exa_request(
            api_key, "GET", "/websets/v0/events",
            params={"cursor": c.cursor, "limit": c.limit}, action_name="list_websets_events"
        )

