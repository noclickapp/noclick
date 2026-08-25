"""
Parallel web-research automation node.

Provides workflow integration with Parallel (https://parallel.ai) — web search
and research APIs built for AI agents:
- Search:   one-shot web search, page extraction
- Tasks:    deep research / enrichment task runs and task groups
- FindAll:  entity discovery, enrichment, and fast entity search
- Monitors: continuous web change tracking
- Chat:     OpenAI-compatible chat completions backed by web research
- Webhook Trigger: receive Task / Monitor completion events

Authentication: API Key (x-api-key header — NOT Authorization: Bearer)
API Base URL: https://api.parallel.ai
  - Search / Extract / Tasks / Monitors live under /v1
  - FindAll / Chat live under /v1beta
Documentation: https://docs.parallel.ai
"""

import base64
import hashlib
import hmac
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.parallel import PARALLEL_SCOPES

logger = logging.getLogger(__name__)

PARALLEL_API_BASE = "https://api.parallel.ai"

# Task processors (depth / cost / latency tiers).
TASK_PROCESSORS = [
    "lite", "base", "core", "core2x", "pro", "ultra", "ultra2x", "ultra4x", "ultra8x"
]


# ============================================================================
# Credential Schema
# ============================================================================


class ParallelApiKeyCredential(BaseModel):
    """API Key credential for Parallel."""

    credential_type: Literal["parallel_api_key"] = Field(
        "parallel_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Parallel API key from platform.parallel.ai. Sent in the x-api-key header.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://platform.parallel.ai"}
    )


class ParallelOAuthCredential(BaseModel):
    """OAuth credential for Parallel (Authorization Code + PKCE).

    The access_token IS the user's permanent Parallel API key — no refresh
    token is issued and the token does not expire.
    """

    credential_type: Literal["parallel_oauth"] = Field(
        "parallel_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="Parallel API key obtained via OAuth — used as the x-api-key header.",
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "parallel",
        "x-oauth-scopes": ["key:read"],
        "x-credential-url": "https://platform.parallel.ai",
    })


ParallelCredential = Union[ParallelApiKeyCredential, ParallelOAuthCredential]


# ============================================================================
# Operation Configs — Search
# ============================================================================


class ParallelSearchConfig(BaseModel):
    """Run a one-shot web search returning ranked URLs with LLM excerpts."""

    operation: Literal["search"] = Field(
        "search",
        json_schema_extra={
            "const": "search",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search the Web",
        },
        title="Search the Web",
    )
    search_queries: str = Field(
        ...,
        title="Search Queries",
        description="Keyword queries, one per line — at least one is required",
        json_schema_extra={"ui:widget": "textarea"},
    )
    objective: Optional[str] = Field(
        None,
        title="Objective",
        description="Optional natural-language description of what you're looking for, used to rank results",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ParallelExtractConfig(BaseModel):
    """Extract clean markdown excerpts from a list of URLs."""

    operation: Literal["extract"] = Field(
        "extract",
        json_schema_extra={
            "const": "extract",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Extract Page Content",
        },
        title="Extract Page Content",
    )
    urls: str = Field(
        ...,
        title="URLs",
        description="Page URLs to extract, one per line",
        json_schema_extra={"ui:widget": "textarea"},
    )
    objective: Optional[str] = Field(
        None,
        title="Objective",
        description="Optional focus describing what content to prioritize",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Operation Configs — Tasks
# ============================================================================


class ParallelCreateTaskRunConfig(BaseModel):
    """Start a deep-research / enrichment task run."""

    operation: Literal["create_task_run"] = Field(
        "create_task_run",
        json_schema_extra={
            "const": "create_task_run",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Create Task Run",
        },
        title="Create Task Run",
    )
    input: str = Field(
        ...,
        title="Input",
        description="The research question or enrichment input for the task",
        json_schema_extra={"ui:widget": "textarea"},
    )
    processor: str = Field(
        "core",
        title="Processor",
        description="Depth / cost / latency tier",
        json_schema_extra={
            "enum": TASK_PROCESSORS,
            "x-enum-searchable": True,
        },
    )
    output_schema: Optional[str] = Field(
        None,
        title="Output Schema (JSON)",
        description="Optional JSON Schema describing the desired structured output",
        json_schema_extra={"ui:widget": "textarea"},
    )
    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        description="Optional URL to POST the task_run.status event to on completion",
    )


class ParallelGetTaskRunConfig(BaseModel):
    """Retrieve a task run object and its status."""

    operation: Literal["get_task_run"] = Field(
        "get_task_run",
        json_schema_extra={
            "const": "get_task_run",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Get Task Run",
        },
        title="Get Task Run",
    )
    run_id: str = Field(..., title="Run ID", description="The task run id to retrieve")


class ParallelGetTaskRunResultConfig(BaseModel):
    """Retrieve a completed task run result (blocks until the run finishes or timeout expires)."""

    operation: Literal["get_task_run_result"] = Field(
        "get_task_run_result",
        json_schema_extra={
            "const": "get_task_run_result",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Get Task Run Result",
        },
        title="Get Task Run Result",
    )
    run_id: str = Field(..., title="Run ID", description="The task run id to fetch the result for")
    timeout_seconds: Optional[str] = Field(
        None,
        title="Timeout (seconds)",
        description="How long to wait for completion before returning a 408 (default: 600). Deep-research tasks with 'ultra' processors may need the full 600 seconds.",
    )


class ParallelGetTaskRunInputConfig(BaseModel):
    """Retrieve the original input submitted for a task run."""

    operation: Literal["get_task_run_input"] = Field(
        "get_task_run_input",
        json_schema_extra={
            "const": "get_task_run_input",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Get Task Run Input",
        },
        title="Get Task Run Input",
    )
    run_id: str = Field(..., title="Run ID", description="The task run id to fetch the input for")


class ParallelGetTaskRunEventsConfig(BaseModel):
    """Stream real-time progress events for an individual task run via SSE."""

    operation: Literal["get_task_run_events"] = Field(
        "get_task_run_events",
        json_schema_extra={
            "const": "get_task_run_events",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Stream Task Run Events",
        },
        title="Stream Task Run Events",
    )
    run_id: str = Field(..., title="Run ID", description="The task run id to stream events for")


class ParallelCreateTaskGroupConfig(BaseModel):
    """Create a batch group to run many task runs together."""

    operation: Literal["create_task_group"] = Field(
        "create_task_group",
        json_schema_extra={
            "const": "create_task_group",
            "ui:hidden": True,
            "x-category": "Task Groups",
            "x-is-trigger": False,
            "x-display-name": "Create Task Group",
        },
        title="Create Task Group",
    )
    metadata: Optional[str] = Field(
        None,
        title="Metadata (JSON)",
        description="Optional JSON object of metadata to attach to the group",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ParallelAddRunsToGroupConfig(BaseModel):
    """Add one or more task runs to an existing group."""

    operation: Literal["add_runs_to_group"] = Field(
        "add_runs_to_group",
        json_schema_extra={
            "const": "add_runs_to_group",
            "ui:hidden": True,
            "x-category": "Task Groups",
            "x-is-trigger": False,
            "x-display-name": "Add Runs to Task Group",
        },
        title="Add Runs to Task Group",
    )
    taskgroup_id: str = Field(..., title="Task Group ID", description="The group to add runs to")
    inputs: str = Field(
        ...,
        title="Inputs",
        description="Run inputs, one per line — each becomes a run in the group",
        json_schema_extra={"ui:widget": "textarea"},
    )
    processor: str = Field(
        "core",
        title="Processor",
        description="Depth / cost / latency tier applied to each run",
        json_schema_extra={
            "enum": TASK_PROCESSORS,
            "x-enum-searchable": True,
        },
    )


class ParallelGetGroupRunsConfig(BaseModel):
    """List runs in a task group."""

    operation: Literal["get_group_runs"] = Field(
        "get_group_runs",
        json_schema_extra={
            "const": "get_group_runs",
            "ui:hidden": True,
            "x-category": "Task Groups",
            "x-is-trigger": False,
            "x-display-name": "Fetch Task Group Runs",
        },
        title="Fetch Task Group Runs",
    )
    taskgroup_id: str = Field(..., title="Task Group ID", description="The group to list runs for")
    status: Optional[str] = Field(
        None, title="Status Filter", description="Filter runs by status (optional)"
    )
    include_input: str = Field(
        "false",
        title="Include Input",
        description="Include each run's input in the response",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    include_output: str = Field(
        "false",
        title="Include Output",
        description="Include each run's output in the response",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class ParallelGetGroupEventsConfig(BaseModel):
    """Stream real-time events for a task group while runs are active (SSE)."""

    operation: Literal["get_group_events"] = Field(
        "get_group_events",
        json_schema_extra={
            "const": "get_group_events",
            "ui:hidden": True,
            "x-category": "Task Groups",
            "x-is-trigger": False,
            "x-display-name": "Stream Task Group Events",
        },
        title="Stream Task Group Events",
    )
    taskgroup_id: str = Field(..., title="Task Group ID", description="The group to stream events for")
    last_event_id: Optional[str] = Field(
        None,
        title="Last Event ID",
        description="Resume from a specific event ID (cursor from a previous response).",
    )


class ParallelGetTaskGroupConfig(BaseModel):
    """Retrieve a task group's status and aggregate progress."""

    operation: Literal["get_task_group"] = Field(
        "get_task_group",
        json_schema_extra={
            "const": "get_task_group",
            "ui:hidden": True,
            "x-category": "Task Groups",
            "x-is-trigger": False,
            "x-display-name": "Get Task Group",
        },
        title="Get Task Group",
    )
    taskgroup_id: str = Field(..., title="Task Group ID", description="The group to retrieve")


class ParallelGetTaskGroupRunConfig(BaseModel):
    """Retrieve a single run within a task group."""

    operation: Literal["get_task_group_run"] = Field(
        "get_task_group_run",
        json_schema_extra={
            "const": "get_task_group_run",
            "ui:hidden": True,
            "x-category": "Task Groups",
            "x-is-trigger": False,
            "x-display-name": "Get Task Group Run",
        },
        title="Get Task Group Run",
    )
    taskgroup_id: str = Field(..., title="Task Group ID", description="The group the run belongs to")
    run_id: str = Field(..., title="Run ID", description="The specific run to retrieve")


# ============================================================================
# Operation Configs — FindAll
# ============================================================================


class ParallelCreateFindAllConfig(BaseModel):
    """Discover verified entities matching plain-language criteria."""

    operation: Literal["create_findall_run"] = Field(
        "create_findall_run",
        json_schema_extra={
            "const": "create_findall_run",
            "ui:hidden": True,
            "x-category": "FindAll",
            "x-is-trigger": False,
            "x-display-name": "Create FindAll Run",
        },
        title="Create FindAll Run",
    )
    objective: str = Field(
        ...,
        title="Objective",
        description="Plain-language description of the entities to discover",
        json_schema_extra={"ui:widget": "textarea"},
    )
    entity_type: str = Field(
        ...,
        title="Entity Type",
        description="The kind of entity to find (e.g. company, person, funded_startups)",
    )
    generator: str = Field(
        "base",
        title="Generator",
        description="Research depth for entity discovery",
        json_schema_extra={
            "enum": ["base", "core", "pro", "preview"],
            "enumNames": ["Base", "Core", "Pro", "Preview"],
            "x-enum-searchable": True,
        },
    )
    match_conditions: str = Field(
        ...,
        title="Match Conditions (JSON)",
        description='JSON array of condition objects, each with "name" and "description" keys. Example: [{"name": "funded", "description": "Company has raised venture funding"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    match_limit: str = Field(
        ...,
        title="Match Limit",
        description="Maximum number of entities to find (integer as string, e.g. '10')",
    )
    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        description="Optional URL to POST completion events to",
    )


class ParallelCreateFindAllSpecConfig(BaseModel):
    """Transform a natural-language objective into a structured FindAll spec (suggested starting point)."""

    operation: Literal["create_findall_spec"] = Field(
        "create_findall_spec",
        json_schema_extra={
            "const": "create_findall_spec",
            "ui:hidden": True,
            "x-category": "FindAll",
            "x-is-trigger": False,
            "x-display-name": "Generate FindAll Spec",
        },
        title="Generate FindAll Spec",
    )
    objective: str = Field(
        ...,
        title="Objective",
        description="Plain-language description of what entities to find — returns a structured spec you can use with Create FindAll Run",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ParallelGetFindAllConfig(BaseModel):
    """Poll a FindAll run's status."""

    operation: Literal["get_findall_run"] = Field(
        "get_findall_run",
        json_schema_extra={
            "const": "get_findall_run",
            "ui:hidden": True,
            "x-category": "FindAll",
            "x-is-trigger": False,
            "x-display-name": "Get FindAll Run Status",
        },
        title="Get FindAll Run Status",
    )
    findall_id: str = Field(..., title="FindAll Run ID", description="The FindAll run id to poll")


class ParallelGetFindAllResultConfig(BaseModel):
    """Get discovered entities / candidates for a FindAll run."""

    operation: Literal["get_findall_result"] = Field(
        "get_findall_result",
        json_schema_extra={
            "const": "get_findall_result",
            "ui:hidden": True,
            "x-category": "FindAll",
            "x-is-trigger": False,
            "x-display-name": "Get FindAll Run Result",
        },
        title="Get FindAll Run Result",
    )
    findall_id: str = Field(..., title="FindAll Run ID", description="The FindAll run id")


class ParallelEnrichFindAllConfig(BaseModel):
    """Add column enrichments to a FindAll run's discovered entities."""

    operation: Literal["enrich_findall"] = Field(
        "enrich_findall",
        json_schema_extra={
            "const": "enrich_findall",
            "ui:hidden": True,
            "x-category": "FindAll",
            "x-is-trigger": False,
            "x-display-name": "Add FindAll Enrichment",
        },
        title="Add FindAll Enrichment",
    )
    findall_id: str = Field(..., title="FindAll Run ID", description="The FindAll run id")
    enrichments: str = Field(
        ...,
        title="Enrichments",
        description="Enrichment column descriptions, one per line",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ParallelExtendFindAllConfig(BaseModel):
    """Find more entities beyond the original match limit."""

    operation: Literal["extend_findall"] = Field(
        "extend_findall",
        json_schema_extra={
            "const": "extend_findall",
            "ui:hidden": True,
            "x-category": "FindAll",
            "x-is-trigger": False,
            "x-display-name": "Extend FindAll Run",
        },
        title="Extend FindAll Run",
    )
    findall_id: str = Field(..., title="FindAll Run ID", description="The FindAll run id")
    match_limit: Optional[str] = Field(
        None, title="Additional Match Limit", description="Additional number of entities to find"
    )


class ParallelCancelFindAllConfig(BaseModel):
    """Cancel an in-progress FindAll run."""

    operation: Literal["cancel_findall"] = Field(
        "cancel_findall",
        json_schema_extra={
            "const": "cancel_findall",
            "ui:hidden": True,
            "x-category": "FindAll",
            "x-is-trigger": False,
            "x-display-name": "Cancel FindAll Run",
        },
        title="Cancel FindAll Run",
    )
    findall_id: str = Field(..., title="FindAll Run ID", description="The FindAll run id to cancel")


class ParallelEntitySearchConfig(BaseModel):
    """Synchronous real-time people / company lookup."""

    operation: Literal["entity_search"] = Field(
        "entity_search",
        json_schema_extra={
            "const": "entity_search",
            "ui:hidden": True,
            "x-category": "FindAll",
            "x-is-trigger": False,
            "x-display-name": "Fast Entity Search",
        },
        title="Fast Entity Search",
    )
    query: str = Field(
        ...,
        title="Query",
        description="Plain-language query describing the person or company to find",
        json_schema_extra={"ui:widget": "textarea"},
    )
    entity_type: str = Field(
        ...,
        title="Entity Type",
        description="Whether to search for people or companies",
        json_schema_extra={
            "enum": ["people", "companies"],
            "enumNames": ["People", "Companies"],
            "x-enum-searchable": True,
        },
    )
    objective: str = Field(
        ...,
        title="Objective",
        description="What you want to find out about the entity (e.g. 'Find the CEO of Anthropic')",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Operation Configs — Monitors
# ============================================================================


class ParallelCreateMonitorConfig(BaseModel):
    """Set up continuous web tracking."""

    operation: Literal["create_monitor"] = Field(
        "create_monitor",
        json_schema_extra={
            "const": "create_monitor",
            "ui:hidden": True,
            "x-category": "Monitors",
            "x-is-trigger": False,
            "x-display-name": "Create Monitor",
            "x-creates-resource": True,
            "x-resource-type": "parallel_monitor",
            "x-resource-id-path": "monitor_id",
        },
        title="Create Monitor",
    )
    type: str = Field(
        "event_stream",
        title="Monitor Type",
        description="The kind of monitor to create",
        json_schema_extra={
            "enum": ["event_stream", "snapshot"],
            "enumNames": ["Event Stream (track web changes)", "Snapshot (compare task run outputs)"],
            "x-enum-searchable": True,
        },
    )
    frequency: str = Field(
        "1d",
        title="Frequency",
        description="How often the monitor runs. Use <number><unit> format: '1d' (daily), '12h' (every 12 hours), '1w' (weekly), '2h' (every 2 hours).",
        json_schema_extra={"ui:placeholder": "e.g. 1d, 12h, 1w"},
    )
    settings: str = Field(
        ...,
        title="Settings (JSON)",
        description=(
            'Monitor-type-specific settings as JSON. '
            'event_stream: {"query": "search terms"} — optional advanced: {"query": "...", "advanced_settings": {"location": "us"}}. '
            'snapshot: {"task_run_id": "<completed_task_run_id>"} — requires a completed task run id as baseline.'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        description="Optional URL to POST detected-change events to",
    )


class ParallelListMonitorsConfig(BaseModel):
    """List monitors (cursor pagination)."""

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
    type: Optional[str] = Field(None, title="Type Filter", description="Filter by monitor type")
    status: Optional[str] = Field(None, title="Status Filter", description="Filter by status")
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")
    limit: Optional[str] = Field(None, title="Limit", description="Max monitors to return")


class ParallelGetMonitorConfig(BaseModel):
    """Retrieve a single monitor."""

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
        ..., title="Monitor ID", description="The monitor id to retrieve",
        json_schema_extra={"x-dynamic-options": {"field_name": "monitor_id", "placeholder": "Select a monitor...", "searchable": True}, "x-resource-type": "parallel_monitor"},
    )


class ParallelUpdateMonitorConfig(BaseModel):
    """Update a monitor's config."""

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
        ..., title="Monitor ID", description="The monitor id to update",
        json_schema_extra={"x-dynamic-options": {"field_name": "monitor_id", "placeholder": "Select a monitor...", "searchable": True}, "x-resource-type": "parallel_monitor"},
    )
    frequency: Optional[str] = Field(
        None,
        title="Frequency",
        description="New check frequency (e.g. '1d', '12h', '2w'). Leave blank to keep current.",
    )
    type: Optional[str] = Field(
        None,
        title="Monitor Type",
        description="Required when updating settings. Must match the monitor's original type: 'event_stream' or 'snapshot'.",
        json_schema_extra={"enum": ["event_stream", "snapshot"]},
    )
    settings: Optional[str] = Field(
        None,
        title="Settings (JSON)",
        description=(
            "JSON object with updated monitor settings. Requires 'type' to also be set. "
            "For event_stream: {\"query\": \"your search query\"}. "
            "Advanced: {\"query\": \"...\", \"advanced_settings\": {\"location\": \"us\", \"source_policy\": {\"include_domains\": [...]}}}. "
            "Note: 'objective' is not a valid field — use 'query' only."
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class ParallelListMonitorEventsConfig(BaseModel):
    """List detected change events for a monitor."""

    operation: Literal["list_monitor_events"] = Field(
        "list_monitor_events",
        json_schema_extra={
            "const": "list_monitor_events",
            "ui:hidden": True,
            "x-category": "Monitors",
            "x-is-trigger": False,
            "x-display-name": "List Monitor Events",
        },
        title="List Monitor Events",
    )
    monitor_id: str = Field(
        ..., title="Monitor ID", description="The monitor id",
        json_schema_extra={"x-dynamic-options": {"field_name": "monitor_id", "placeholder": "Select a monitor...", "searchable": True}, "x-resource-type": "parallel_monitor"},
    )
    event_group_id: Optional[str] = Field(
        None,
        title="Event Group ID",
        description="Filter to a specific execution's event group (from a webhook payload's data.event.event_group_id).",
    )
    include_completions: str = Field(
        "false",
        title="Include Completions",
        description="Include 'completion' events (runs that found no changes).",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    next_cursor: Optional[str] = Field(
        None,
        title="Next Cursor",
        description="Pagination cursor from a previous response to fetch the next page.",
    )


class ParallelTriggerMonitorConfig(BaseModel):
    """Manually trigger a monitor check now."""

    operation: Literal["trigger_monitor"] = Field(
        "trigger_monitor",
        json_schema_extra={
            "const": "trigger_monitor",
            "ui:hidden": True,
            "x-category": "Monitors",
            "x-is-trigger": False,
            "x-display-name": "Trigger Monitor Run",
        },
        title="Trigger Monitor Run",
    )
    monitor_id: str = Field(
        ..., title="Monitor ID", description="The monitor id to trigger",
        json_schema_extra={"x-dynamic-options": {"field_name": "monitor_id", "placeholder": "Select a monitor...", "searchable": True}, "x-resource-type": "parallel_monitor"},
    )


class ParallelCancelMonitorConfig(BaseModel):
    """Stop / cancel a monitor."""

    operation: Literal["cancel_monitor"] = Field(
        "cancel_monitor",
        json_schema_extra={
            "const": "cancel_monitor",
            "ui:hidden": True,
            "x-category": "Monitors",
            "x-is-trigger": False,
            "x-display-name": "Cancel Monitor",
        },
        title="Cancel Monitor",
    )
    monitor_id: str = Field(
        ..., title="Monitor ID", description="The monitor id to cancel",
        json_schema_extra={"x-dynamic-options": {"field_name": "monitor_id", "placeholder": "Select a monitor...", "searchable": True}, "x-resource-type": "parallel_monitor"},
    )


class ParallelSimulateMonitorEventConfig(BaseModel):
    """Simulate a monitor event to test webhook delivery without waiting for a real run."""

    operation: Literal["simulate_monitor_event"] = Field(
        "simulate_monitor_event",
        json_schema_extra={
            "const": "simulate_monitor_event",
            "ui:hidden": True,
            "x-category": "Monitors",
            "x-is-trigger": False,
            "x-display-name": "Simulate Monitor Event",
        },
        title="Simulate Monitor Event",
    )
    monitor_id: str = Field(
        ..., title="Monitor ID", description="The monitor to simulate an event for",
        json_schema_extra={"x-dynamic-options": {"field_name": "monitor_id", "placeholder": "Select a monitor...", "searchable": True}, "x-resource-type": "parallel_monitor"},
    )


# ============================================================================
# Operation Configs — Chat
# ============================================================================


class ParallelChatCompletionsConfig(BaseModel):
    """OpenAI-compatible chat completion backed by Parallel web research (Beta)."""

    operation: Literal["chat_completions"] = Field(
        "chat_completions",
        json_schema_extra={
            "const": "chat_completions",
            "ui:hidden": True,
            "x-category": "Chat",
            "x-is-trigger": False,
            "x-display-name": "Chat Completions",
        },
        title="Chat Completions",
    )
    prompt: str = Field(
        ...,
        title="Prompt",
        description="The user message to send to the chat model",
        json_schema_extra={"ui:widget": "textarea"},
    )
    model: str = Field(
        "speed",
        title="Model",
        description="The Parallel chat model to use. 'speed' is fastest (~3s); 'lite'/'base'/'core' are research-grade with citations (10s–5min).",
        json_schema_extra={
            "enum": ["speed", "lite", "base", "core"],
            "enumNames": ["Speed (~3s, no citations)", "Lite (research)", "Base (research)", "Core (deep research)"],
            "x-enum-searchable": True,
        },
    )
    system_prompt: Optional[str] = Field(
        None,
        title="System Prompt",
        description="Optional system message to steer the response",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class ParallelReceiveWebhookConfig(BaseModel):
    """Receive Task / Monitor completion events from Parallel.

    Parallel webhooks are configured inline on create requests (no separate
    registerable webhook API), so this provisions a NoClick webhook URL that the
    user supplies in the `webhook` object when creating a Task or Monitor.
    HMAC signature verification is supported.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["receive_webhook"] = Field(
        "receive_webhook",
        json_schema_extra={
            "const": "receive_webhook",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "Receive Webhook Events",
        },
        title="Receive Webhook Events",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Use this URL as the `webhook.url` when you create a Task run or Monitor in Parallel.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None,
        title="Signing Secret",
        description="The webhook signing secret from Parallel — used to verify event signatures",
        json_schema_extra={"ui:widget": "password"},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


ParallelConfig = Annotated[
    Union[
        ParallelSearchConfig,
        ParallelExtractConfig,
        ParallelCreateTaskRunConfig,
        ParallelGetTaskRunConfig,
        ParallelGetTaskRunResultConfig,
        ParallelGetTaskRunInputConfig,
        ParallelGetTaskRunEventsConfig,
        ParallelCreateTaskGroupConfig,
        ParallelAddRunsToGroupConfig,
        ParallelGetGroupRunsConfig,
        ParallelGetGroupEventsConfig,
        ParallelGetTaskGroupConfig,
        ParallelGetTaskGroupRunConfig,
        ParallelCreateFindAllConfig,
        ParallelCreateFindAllSpecConfig,
        ParallelGetFindAllConfig,
        ParallelGetFindAllResultConfig,
        ParallelEnrichFindAllConfig,
        ParallelExtendFindAllConfig,
        ParallelCancelFindAllConfig,
        ParallelEntitySearchConfig,
        ParallelCreateMonitorConfig,
        ParallelListMonitorsConfig,
        ParallelGetMonitorConfig,
        ParallelUpdateMonitorConfig,
        ParallelListMonitorEventsConfig,
        ParallelTriggerMonitorConfig,
        ParallelCancelMonitorConfig,
        ParallelSimulateMonitorEventConfig,
        ParallelChatCompletionsConfig,
        ParallelReceiveWebhookConfig,
    ],
    Discriminator("operation"),
]


class ParallelNodeConfig(NodeConfig[ParallelConfig, ParallelCredential]):
    """Full configuration for the Parallel node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _lines(value: Optional[str]) -> Optional[List[str]]:
    """Split a multi-line string into a list of non-empty stripped lines."""
    if not value:
        return None
    parts = [p.strip() for p in value.splitlines() if p.strip()]
    return parts or None


def _parse_json(value: Optional[str], field_name: str) -> Optional[Any]:
    """Parse a JSON string field, raising ValueError with a clear message on failure."""
    if not value or not value.strip():
        return None
    import json

    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in '{field_name}': {e}")


async def _parallel_request(
    api_key: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """Make an authenticated Parallel request and return a structured result.

    Parallel authenticates via the `x-api-key` header (NOT Authorization: Bearer).
    """
    url = f"{PARALLEL_API_BASE}{endpoint}"
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }
    if json_body is not None:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    if isinstance(err, dict):
                        detail = err.get("error") or err.get("detail") or err.get("message")
                        if isinstance(detail, dict):
                            message = detail.get("message") or str(detail)
                        else:
                            message = detail or str(err)
                    else:
                        message = str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[ParallelNode] API error ({action_name}): {message}")
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
            logger.error(f"[ParallelNode] Request failed ({action_name}): {msg}")
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


class ParallelNode(WorkflowNode):
    """Parallel web-research automation node."""

    edit_examples = [
        "Search the web for recent funding rounds in the AI agents space",
        "Run a deep research task on a company and return structured findings",
        "Find all Series B SaaS companies hiring for ML roles",
        "Monitor a competitor's pricing page and trigger a workflow when it changes",
        "Extract the clean markdown content of a list of article URLs",
    ]

    scope_registry = PARALLEL_SCOPES
    connection_evidence = ConnectionEvidence(
        field="monitor_id",
        noun="monitors",
    )

    @classmethod
    def get_config_model(cls):
        return ParallelNodeConfig

    # ------------------------------------------------------------------
    # Webhook URL provisioning (inline-configured webhooks, dashboard-style)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Provision the internal webhook URL for the receive_webhook trigger.

        Parallel webhooks are supplied inline in Task/Monitor create requests, so
        this only mints our inbound URL — the user pastes it into the `webhook`
        object when creating a run.
        """
        if field_name != "webhook_url":
            return {"value": None}

        from utils.webhook_manager import WebhookManager

        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )
        return {
            "values": {
                "webhook_id": webhook_data.get("webhook_id"),
                "webhook_url": webhook_data.get("webhook_url"),
                "relay_connected": webhook_data.get("relay_connected"),
                "is_production": webhook_data.get("is_production"),
            }
        }

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify a Parallel webhook's HMAC-SHA256 signature.

        Parallel signs the string "{webhook-id}.{webhook-timestamp}.{raw_body}"
        with the account-level signing secret and sends the base64-encoded digest
        as "v1,<digest>" in the `webhook-signature` header. Multiple active
        signing keys produce space-separated "v1,<sig>" values; any one match
        is sufficient.

        If no secret is stored, the trigger is not yet armed — accept.
        """
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True
        webhook_id = headers.get("webhook-id") or headers.get("Webhook-Id", "")
        webhook_ts = headers.get("webhook-timestamp") or headers.get("Webhook-Timestamp", "")
        sent = headers.get("webhook-signature") or headers.get("Webhook-Signature", "")
        if not sent or not webhook_id or not webhook_ts:
            return False
        signed_payload = f"{webhook_id}.{webhook_ts}.".encode() + body
        expected = base64.b64encode(
            hmac.new(secret.encode(), signed_payload, hashlib.sha256).digest()
        ).decode()
        for part in sent.split():
            if part.startswith("v1,") and hmac.compare_digest(expected, part[3:]):
                return True
        return False

    # ------------------------------------------------------------------
    # Dynamic options
    # ------------------------------------------------------------------

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Populate monitor_id dropdowns by listing the user's monitors."""
        if field_name != "monitor_id":
            return {"options": [], "next_page_token": None}

        api_key = credential_data.get("api_key") or credential_data.get("access_token", "")
        if not api_key:
            return {"options": [], "next_page_token": None}

        params: Dict[str, Any] = {"limit": "50"}
        if page_token:
            params["cursor"] = page_token
        if search:
            params["search"] = search

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{PARALLEL_API_BASE}/v1/monitors",
                headers={"x-api-key": api_key, "Content-Type": "application/json"},
                params=params,
            )
        if resp.status_code != 200:
            return {"options": [], "next_page_token": None}

        data = resp.json()
        monitors = data.get("monitors", [])
        options = []
        for m in monitors:
            mid = m.get("monitor_id") or m.get("id", "")
            status = m.get("status", "")
            mtype = m.get("type", "")
            query = (m.get("settings") or {}).get("query", "")
            label_parts = [mtype, query or mid, f"({status})"] if query else [mtype, mid, f"({status})"]
            options.append({"value": mid, "label": " — ".join(p for p in label_parts if p)})

        next_cursor = data.get("next_cursor")
        return {"options": options, "next_page_token": next_cursor}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, ParallelNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, ParallelReceiveWebhookConfig):
            return {
                "status": "success",
                "action": "receive_webhook",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Parallel API key or connect via OAuth.")
        if isinstance(credentials, ParallelOAuthCredential):
            api_key = credentials.access_token
        else:
            api_key = credentials.api_key

        handlers = {
            "search": self._search,
            "extract": self._extract,
            "create_task_run": self._create_task_run,
            "get_task_run": self._get_task_run,
            "get_task_run_result": self._get_task_run_result,
            "get_task_run_input": self._get_task_run_input,
            "get_task_run_events": self._get_task_run_events,
            "create_task_group": self._create_task_group,
            "add_runs_to_group": self._add_runs_to_group,
            "get_group_runs": self._get_group_runs,
            "get_group_events": self._get_group_events,
            "get_task_group": self._get_task_group,
            "get_task_group_run": self._get_task_group_run,
            "create_findall_run": self._create_findall_run,
            "create_findall_spec": self._create_findall_spec,
            "get_findall_run": self._get_findall_run,
            "get_findall_result": self._get_findall_result,
            "enrich_findall": self._enrich_findall,
            "extend_findall": self._extend_findall,
            "cancel_findall": self._cancel_findall,
            "entity_search": self._entity_search,
            "create_monitor": self._create_monitor,
            "list_monitors": self._list_monitors,
            "get_monitor": self._get_monitor,
            "update_monitor": self._update_monitor,
            "list_monitor_events": self._list_monitor_events,
            "trigger_monitor": self._trigger_monitor,
            "cancel_monitor": self._cancel_monitor,
            "simulate_monitor_event": self._simulate_monitor_event,
            "chat_completions": self._chat_completions,
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
    # Handlers — Search
    # ------------------------------------------------------------------
    async def _search(self, c: ParallelSearchConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "search_queries": _lines(c.search_queries),
            "objective": c.objective,
        }
        return await _parallel_request(
            api_key, "POST", "/v1/search", json_body=body, action_name="search"
        )

    async def _extract(self, c: ParallelExtractConfig, api_key: str) -> Dict[str, Any]:
        body = {"urls": _lines(c.urls), "objective": c.objective}
        return await _parallel_request(
            api_key, "POST", "/v1/extract", json_body=body, action_name="extract"
        )

    # ------------------------------------------------------------------
    # Handlers — Tasks
    # ------------------------------------------------------------------
    async def _create_task_run(self, c: ParallelCreateTaskRunConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "input": c.input,
            "processor": c.processor,
        }
        output_schema = _parse_json(c.output_schema, "output_schema")
        if output_schema is not None:
            body["output_schema"] = output_schema
        if c.webhook_url:
            body["webhook"] = {"url": c.webhook_url, "event_types": ["task_run.status"]}
        return await _parallel_request(
            api_key, "POST", "/v1/tasks/runs", json_body=body, action_name="create_task_run"
        )

    async def _get_task_run(self, c: ParallelGetTaskRunConfig, api_key: str) -> Dict[str, Any]:
        return await _parallel_request(
            api_key, "GET", f"/v1/tasks/runs/{c.run_id}", action_name="get_task_run"
        )

    async def _get_task_run_result(
        self, c: ParallelGetTaskRunResultConfig, api_key: str
    ) -> Dict[str, Any]:
        api_timeout = int(c.timeout_seconds) if c.timeout_seconds and c.timeout_seconds.isdigit() else 600
        params = {"timeout": api_timeout} if c.timeout_seconds else None
        # Add a 30-second buffer so httpx doesn't cut off before Parallel returns a 408.
        return await _parallel_request(
            api_key, "GET", f"/v1/tasks/runs/{c.run_id}/result",
            params=params, action_name="get_task_run_result",
            timeout=api_timeout + 30,
        )

    async def _get_task_run_input(
        self, c: ParallelGetTaskRunInputConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _parallel_request(
            api_key, "GET", f"/v1/tasks/runs/{c.run_id}/input", action_name="get_task_run_input"
        )

    async def _get_task_run_events(self, c: ParallelGetTaskRunEventsConfig, api_key: str) -> Dict[str, Any]:
        """Stream progress events for a single task run via SSE and return as a list."""
        import httpx as _httpx
        import time as _time
        import json as _json

        url = f"https://api.parallel.ai/v1/tasks/runs/{c.run_id}/events"
        headers = {"x-api-key": api_key, "Accept": "text/event-stream"}
        start = _time.time()
        try:
            async with _httpx.AsyncClient(timeout=300.0) as client:
                response = await client.get(url, headers=headers)
                api_ms = round((_time.time() - start) * 1000, 2)
                if response.status_code >= 400:
                    try:
                        message = response.json().get("error", {}).get("message") or response.text
                    except Exception:
                        message = response.text
                    return {"status": "error", "action": "get_task_run_events", "error": message,
                            "status_code": response.status_code, "timing_ms": {"api_request": api_ms}}
                events = []
                for line in response.text.splitlines():
                    if line.startswith("data:"):
                        try:
                            events.append(_json.loads(line[5:].strip()))
                        except _json.JSONDecodeError:
                            pass
                return {"status": "success", "action": "get_task_run_events",
                        "data": {"events": events, "count": len(events)},
                        "status_code": response.status_code, "timing_ms": {"api_request": api_ms}}
        except _httpx.TimeoutException:
            return {"status": "error", "action": "get_task_run_events", "error": "Request timed out",
                    "status_code": 408, "timing_ms": {"api_request": round((_time.time() - start) * 1000, 2)}}
        except Exception as e:
            return {"status": "error", "action": "get_task_run_events", "error": str(e),
                    "status_code": 500, "timing_ms": {"api_request": round((_time.time() - start) * 1000, 2)}}

    async def _create_task_group(
        self, c: ParallelCreateTaskGroupConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {"metadata": _parse_json(c.metadata, "metadata")}
        return await _parallel_request(
            api_key, "POST", "/v1/tasks/groups", json_body=body, action_name="create_task_group"
        )

    async def _add_runs_to_group(
        self, c: ParallelAddRunsToGroupConfig, api_key: str
    ) -> Dict[str, Any]:
        runs = [
            {"input": inp, "processor": c.processor} for inp in (_lines(c.inputs) or [])
        ]
        body = {"inputs": runs}
        return await _parallel_request(
            api_key,
            "POST",
            f"/v1/tasks/groups/{c.taskgroup_id}/runs",
            json_body=body,
            action_name="add_runs_to_group",
        )

    async def _get_group_runs(self, c: ParallelGetGroupRunsConfig, api_key: str) -> Dict[str, Any]:
        import json as _json
        import time as _time
        params = {k: v for k, v in {
            "status": c.status,
            "include_input": "true" if c.include_input == "true" else None,
            "include_output": "true" if c.include_output == "true" else None,
        }.items() if v}
        url = f"{PARALLEL_API_BASE}/v1/tasks/groups/{c.taskgroup_id}/runs"
        headers = {"x-api-key": api_key, "Content-Type": "application/json"}
        start = _time.time()
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.get(url, headers=headers, params=params)
                api_ms = round((_time.time() - start) * 1000, 2)
                if response.status_code >= 400:
                    try:
                        err = response.json()
                        message = err.get("error", {}).get("message") or str(err)
                    except Exception:
                        message = response.text
                    return {"status": "error", "action": "get_group_runs", "error": message,
                            "status_code": response.status_code, "timing_ms": {"api_request": api_ms}}
                # The endpoint streams SSE (text/event-stream) — parse events into a list.
                runs = []
                for line in response.text.splitlines():
                    if line.startswith("data:"):
                        try:
                            event = _json.loads(line[5:].strip())
                            if event.get("run"):
                                runs.append(event["run"])
                            elif isinstance(event, dict):
                                runs.append(event)
                        except _json.JSONDecodeError:
                            pass
                return {"status": "success", "action": "get_group_runs",
                        "data": {"runs": runs, "count": len(runs)},
                        "status_code": response.status_code, "timing_ms": {"api_request": api_ms}}
            except httpx.TimeoutException:
                return {"status": "error", "action": "get_group_runs", "error": "Request timed out",
                        "status_code": 408, "timing_ms": {"api_request": round((_time.time() - start) * 1000, 2)}}
            except Exception as e:
                return {"status": "error", "action": "get_group_runs", "error": str(e),
                        "status_code": 500, "timing_ms": {"api_request": round((_time.time() - start) * 1000, 2)}}

    async def _get_group_events(self, c: ParallelGetGroupEventsConfig, api_key: str) -> Dict[str, Any]:
        """Stream events for a task group via SSE and return as a list."""
        import httpx as _httpx
        import time as _time
        import json as _json

        url = f"https://api.parallel.ai/v1/tasks/groups/{c.taskgroup_id}/events"
        headers = {"x-api-key": api_key, "Accept": "text/event-stream"}
        params: Dict[str, Any] = {}
        if c.last_event_id:
            params["last_event_id"] = c.last_event_id
        start = _time.time()
        try:
            async with _httpx.AsyncClient(timeout=300.0) as client:
                response = await client.get(url, headers=headers, params=params or None)
                api_ms = round((_time.time() - start) * 1000, 2)
                if response.status_code >= 400:
                    try:
                        message = response.json().get("error", {}).get("message") or response.text
                    except Exception:
                        message = response.text
                    return {"status": "error", "action": "get_group_events", "error": message,
                            "status_code": response.status_code, "timing_ms": {"api_request": api_ms}}
                events = []
                last_id = None
                for line in response.text.splitlines():
                    if line.startswith("id:"):
                        last_id = line[3:].strip()
                    elif line.startswith("data:"):
                        try:
                            events.append(_json.loads(line[5:].strip()))
                        except _json.JSONDecodeError:
                            pass
                return {"status": "success", "action": "get_group_events",
                        "data": {"events": events, "count": len(events), "last_event_id": last_id},
                        "status_code": response.status_code, "timing_ms": {"api_request": api_ms}}
        except _httpx.TimeoutException:
            return {"status": "error", "action": "get_group_events", "error": "Request timed out",
                    "status_code": 408, "timing_ms": {"api_request": round((_time.time() - start) * 1000, 2)}}
        except Exception as e:
            return {"status": "error", "action": "get_group_events", "error": str(e),
                    "status_code": 500, "timing_ms": {"api_request": round((_time.time() - start) * 1000, 2)}}

    async def _get_task_group(self, c: ParallelGetTaskGroupConfig, api_key: str) -> Dict[str, Any]:
        return await _parallel_request(
            api_key, "GET", f"/v1/tasks/groups/{c.taskgroup_id}", action_name="get_task_group"
        )

    async def _get_task_group_run(
        self, c: ParallelGetTaskGroupRunConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _parallel_request(
            api_key,
            "GET",
            f"/v1/tasks/groups/{c.taskgroup_id}/runs/{c.run_id}",
            action_name="get_task_group_run",
        )

    # ------------------------------------------------------------------
    # Handlers — FindAll
    # ------------------------------------------------------------------
    async def _create_findall_run(
        self, c: ParallelCreateFindAllConfig, api_key: str
    ) -> Dict[str, Any]:
        match_conditions = _parse_json(c.match_conditions, "match_conditions")
        body: Dict[str, Any] = {
            "objective": c.objective,
            "entity_type": c.entity_type,
            "generator": c.generator,
            "match_conditions": match_conditions,
            "match_limit": int(c.match_limit) if c.match_limit and c.match_limit.isdigit() else None,
        }
        if c.webhook_url:
            body["webhook"] = {
                "url": c.webhook_url,
                "event_types": ["findall.run.completed", "findall.run.failed", "findall.run.cancelled"],
            }
        return await _parallel_request(
            api_key, "POST", "/v1beta/findall/runs", json_body=body, action_name="create_findall_run"
        )

    async def _create_findall_spec(
        self, c: ParallelCreateFindAllSpecConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {"objective": c.objective}
        return await _parallel_request(
            api_key, "POST", "/v1beta/findall/ingest", json_body=body, action_name="create_findall_spec"
        )

    async def _get_findall_run(self, c: ParallelGetFindAllConfig, api_key: str) -> Dict[str, Any]:
        return await _parallel_request(
            api_key, "GET", f"/v1beta/findall/runs/{c.findall_id}", action_name="get_findall_run"
        )

    async def _get_findall_result(
        self, c: ParallelGetFindAllResultConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _parallel_request(
            api_key,
            "GET",
            f"/v1beta/findall/runs/{c.findall_id}/result",
            action_name="get_findall_result",
        )

    async def _enrich_findall(self, c: ParallelEnrichFindAllConfig, api_key: str) -> Dict[str, Any]:
        body = {"enrichments": _lines(c.enrichments)}
        return await _parallel_request(
            api_key,
            "POST",
            f"/v1beta/findall/runs/{c.findall_id}/enrich",
            json_body=body,
            action_name="enrich_findall",
        )

    async def _extend_findall(self, c: ParallelExtendFindAllConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "match_limit": int(c.match_limit) if c.match_limit and c.match_limit.isdigit() else None
        }
        return await _parallel_request(
            api_key,
            "POST",
            f"/v1beta/findall/runs/{c.findall_id}/extend",
            json_body=body,
            action_name="extend_findall",
        )

    async def _cancel_findall(self, c: ParallelCancelFindAllConfig, api_key: str) -> Dict[str, Any]:
        return await _parallel_request(
            api_key,
            "POST",
            f"/v1beta/findall/runs/{c.findall_id}/cancel",
            action_name="cancel_findall",
        )

    async def _entity_search(self, c: ParallelEntitySearchConfig, api_key: str) -> Dict[str, Any]:
        body = {"query": c.query, "entity_type": c.entity_type, "objective": c.objective}
        return await _parallel_request(
            api_key,
            "POST",
            "/v1beta/findall/entity-search",
            json_body=body,
            action_name="entity_search",
        )

    # ------------------------------------------------------------------
    # Handlers — Monitors
    # ------------------------------------------------------------------
    async def _create_monitor(self, c: ParallelCreateMonitorConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "type": c.type,
            "frequency": c.frequency,
            "settings": _parse_json(c.settings, "settings"),
        }
        if c.webhook_url:
            body["webhook"] = {
                "url": c.webhook_url,
                "event_types": ["monitor.event.detected", "monitor.execution.completed", "monitor.execution.failed"],
            }
        return await _parallel_request(
            api_key, "POST", "/v1/monitors", json_body=body, action_name="create_monitor"
        )

    async def _list_monitors(self, c: ParallelListMonitorsConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "type": c.type,
            "status": c.status,
            "cursor": c.cursor,
            "limit": c.limit,
        }
        return await _parallel_request(
            api_key, "GET", "/v1/monitors", params=params, action_name="list_monitors"
        )

    async def _get_monitor(self, c: ParallelGetMonitorConfig, api_key: str) -> Dict[str, Any]:
        return await _parallel_request(
            api_key, "GET", f"/v1/monitors/{c.monitor_id}", action_name="get_monitor"
        )

    async def _update_monitor(self, c: ParallelUpdateMonitorConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if c.frequency:
            body["frequency"] = c.frequency
        if c.settings:
            if not c.type:
                raise ValueError("'type' is required when updating 'settings' (e.g. 'event_stream').")
            body["type"] = c.type
            body["settings"] = _parse_json(c.settings, "settings")
        elif c.type:
            body["type"] = c.type
        if not body:
            raise ValueError("Provide at least one of 'frequency', 'type', or 'settings' to update.")
        return await _parallel_request(
            api_key,
            "POST",
            f"/v1/monitors/{c.monitor_id}/update",
            json_body=body,
            action_name="update_monitor",
        )

    async def _list_monitor_events(
        self, c: ParallelListMonitorEventsConfig, api_key: str
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if c.event_group_id:
            params["event_group_id"] = c.event_group_id
        if c.include_completions == "true":
            params["include_completions"] = "true"
        if c.next_cursor:
            params["next_cursor"] = c.next_cursor
        return await _parallel_request(
            api_key,
            "GET",
            f"/v1/monitors/{c.monitor_id}/events",
            params=params or None,
            action_name="list_monitor_events",
        )

    async def _trigger_monitor(self, c: ParallelTriggerMonitorConfig, api_key: str) -> Dict[str, Any]:
        return await _parallel_request(
            api_key,
            "POST",
            f"/v1/monitors/{c.monitor_id}/trigger",
            action_name="trigger_monitor",
        )

    async def _cancel_monitor(self, c: ParallelCancelMonitorConfig, api_key: str) -> Dict[str, Any]:
        return await _parallel_request(
            api_key,
            "POST",
            f"/v1/monitors/{c.monitor_id}/cancel",
            action_name="cancel_monitor",
        )

    async def _simulate_monitor_event(
        self, c: ParallelSimulateMonitorEventConfig, api_key: str
    ) -> Dict[str, Any]:
        # No request body — the endpoint takes no parameters, just the monitor_id in the path.
        return await _parallel_request(
            api_key,
            "POST",
            f"/v1alpha/monitors/{c.monitor_id}/simulate_event",
            action_name="simulate_monitor_event",
        )

    # ------------------------------------------------------------------
    # Handlers — Chat
    # ------------------------------------------------------------------
    async def _chat_completions(
        self, c: ParallelChatCompletionsConfig, api_key: str
    ) -> Dict[str, Any]:
        messages = []
        if c.system_prompt:
            messages.append({"role": "system", "content": c.system_prompt})
        messages.append({"role": "user", "content": c.prompt})
        body = {"model": c.model, "messages": messages}
        return await _parallel_request(
            api_key,
            "POST",
            "/v1beta/chat/completions",
            json_body=body,
            action_name="chat_completions",
        )
