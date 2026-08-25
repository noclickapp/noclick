"""
Datadog observability automation node.

Provides workflow integration with the Datadog REST API for operations including:
- Monitors: create, get, list, update, delete, mute, unmute, search
- Events: post, get, list, search
- Metrics: submit, query timeseries, query (legacy), list active, get metadata
- Logs: send, search, aggregate
- Dashboards: create, get, list, update, delete
- Incidents: create, list, update
- Downtimes: create, cancel, list, get, update
- SLOs: create, get, list, update, delete, get history
- Hosts: list, get totals, mute, unmute
- Tags: get, add, update, delete host tags
- Service Checks: submit
- Synthetics: list, get, trigger, pause/resume

Authentication: API key + Application key (header-based: DD-API-KEY + DD-APPLICATION-KEY).
Datadog OAuth 2.0 exists but is gated to integration/marketplace partners, so the
generic node uses key-based auth. The base host is site-specific (US1/US3/US5/EU/AP1/
AP2/GovCloud) and selectable on the credential.

API Base URL: https://api.datadoghq.com (US1 default; per-site override)
Documentation: https://docs.datadoghq.com/api/latest/
"""

import json
import logging
import time
import uuid as uuid_module
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Literal, Union, Annotated, Type
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.schedule_registration import CronScheduleTriggerMixin
from nodes.cron_trigger_node import (
    ScheduleConfig,
    schedule_to_cron,
    schedule_to_interval_ms,
)

logger = logging.getLogger(__name__)

# Datadog site -> API host. The base URL is site-specific; hardcoding US1 breaks
# EU / AP / Gov customers, so the user picks a site on the credential.
DATADOG_SITES = {
    "datadoghq.com": "https://api.datadoghq.com",
    "us3.datadoghq.com": "https://api.us3.datadoghq.com",
    "us5.datadoghq.com": "https://api.us5.datadoghq.com",
    "datadoghq.eu": "https://api.datadoghq.eu",
    "ap1.datadoghq.com": "https://api.ap1.datadoghq.com",
    "ap2.datadoghq.com": "https://api.ap2.datadoghq.com",
    "ddog-gov.com": "https://api.ddog-gov.com",
}

# Log intake uses a separate hostname per site — NOT the api.* host.
DATADOG_LOG_INTAKE = {
    "datadoghq.com": "https://http-intake.logs.datadoghq.com",
    "us3.datadoghq.com": "https://http-intake.logs.us3.datadoghq.com",
    "us5.datadoghq.com": "https://http-intake.logs.us5.datadoghq.com",
    "datadoghq.eu": "https://http-intake.logs.datadoghq.eu",
    "ap1.datadoghq.com": "https://http-intake.logs.ap1.datadoghq.com",
    "ap2.datadoghq.com": "https://http-intake.logs.ap2.datadoghq.com",
    "ddog-gov.com": "https://http-intake.logs.ddog-gov.com",
}
DEFAULT_SITE = "datadoghq.com"


# ============================================================================
# Credential Schema
# ============================================================================


class DatadogApiKeyCredential(BaseModel):
    """API key + Application key credential for Datadog."""

    credential_type: Literal["datadog_api_key"] = Field(
        "datadog_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Datadog API key (DD-API-KEY) from Organization Settings -> API Keys",
        json_schema_extra={"ui:widget": "password"},
    )
    app_key: str = Field(
        ...,
        title="Application Key",
        description="Your Datadog Application key (DD-APPLICATION-KEY) from Organization Settings -> Application Keys. Required for read/query endpoints.",
        json_schema_extra={"ui:widget": "password"},
    )
    site: str = Field(
        DEFAULT_SITE,
        title="Datadog Site",
        description="The Datadog site your org is on (US1, EU, etc.). Pick the one shown in your Datadog URL.",
        json_schema_extra={
            "enum": list(DATADOG_SITES.keys()),
            "enumNames": [
                "US1 (datadoghq.com)",
                "US3 (us3.datadoghq.com)",
                "US5 (us5.datadoghq.com)",
                "EU (datadoghq.eu)",
                "AP1 (ap1.datadoghq.com)",
                "AP2 (ap2.datadoghq.com)",
                "GovCloud (ddog-gov.com)",
            ],
            "x-enum-searchable": True,
        },
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://app.datadoghq.com/organization-settings/api-keys"
        }
    )


DatadogCredential = DatadogApiKeyCredential


# ============================================================================
# Operation Configs — Monitors
# ============================================================================


class DatadogCreateMonitorConfig(BaseModel):
    """Create an alert/metric monitor."""

    operation: Literal["create_monitor"] = Field(
        "create_monitor",
        json_schema_extra={
            "const": "create_monitor",
            "ui:hidden": True,
            "x-category": "Monitors",
            "x-is-trigger": False,
            "x-display-name": "Create Monitor",
            "x-creates-resource": True,
            "x-resource-type": "datadog_monitor",
            "x-resource-id-path": "data.id",
        },
        title="Create Monitor",
    )
    name: str = Field(..., title="Name", description="Display name of the monitor")
    type: str = Field(
        "metric alert",
        title="Type",
        description="Monitor type",
        json_schema_extra={
            "enum": [
                "metric alert",
                "query alert",
                "service check",
                "event alert",
                "log alert",
                "process alert",
                "trace-analytics alert",
                "rum alert",
            ],
            "x-enum-searchable": True,
        },
    )
    query: str = Field(
        ...,
        title="Query",
        description="The monitor query (e.g. avg(last_5m):avg:system.cpu.user{*} > 80)",
    )
    message: Optional[str] = Field(
        None,
        title="Message",
        description="Notification message sent when the monitor triggers (supports @-notifications)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Monitor tags, comma-separated (e.g. env:prod,team:core)"
    )
    options_json: Optional[str] = Field(
        None,
        title="Options (JSON)",
        description='Optional monitor options as JSON (e.g. {"thresholds": {"critical": 80}})',
        json_schema_extra={"ui:widget": "textarea"},
    )


class DatadogGetMonitorConfig(BaseModel):
    """Fetch a single monitor's details."""

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
            "x-resource-type": "datadog_monitor",
        },
    )


class DatadogListMonitorsConfig(BaseModel):
    """List all monitors, optionally filtered."""

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
    tags: Optional[str] = Field(
        None, title="Tags", description="Filter by monitor tags, comma-separated"
    )
    monitor_tags: Optional[str] = Field(
        None, title="Monitor Tags", description="Filter by tags assigned via the UI, comma-separated"
    )
    name: Optional[str] = Field(None, title="Name", description="Filter by monitor name substring")
    page_size: Optional[str] = Field(
        "50", title="Limit", description="Max monitors per page (default 50)"
    )


class DatadogUpdateMonitorConfig(BaseModel):
    """Edit an existing monitor."""

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
            "x-resource-type": "datadog_monitor",
        },
    )
    name: Optional[str] = Field(None, title="Name", description="New display name")
    query: Optional[str] = Field(None, title="Query", description="New monitor query")
    message: Optional[str] = Field(
        None,
        title="Message",
        description="New notification message",
        json_schema_extra={"ui:widget": "textarea"},
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="New monitor tags, comma-separated"
    )


class DatadogDeleteMonitorConfig(BaseModel):
    """Delete a monitor."""

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
            "x-resource-type": "datadog_monitor",
        },
    )


class DatadogMuteMonitorConfig(BaseModel):
    """Silence a monitor, optionally scoped and timed."""

    operation: Literal["mute_monitor"] = Field(
        "mute_monitor",
        json_schema_extra={
            "const": "mute_monitor",
            "ui:hidden": True,
            "x-category": "Monitors",
            "x-is-trigger": False,
            "x-display-name": "Mute Monitor",
        },
        title="Mute Monitor",
    )
    monitor_id: str = Field(
        ...,
        title="Monitor",
        description="The monitor to mute",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "monitor_id",
                "placeholder": "Select a monitor...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste monitor ID",
            },
            "x-resource-type": "datadog_monitor",
        },
    )
    scope: Optional[str] = Field(
        None, title="Scope", description="Scope to mute (e.g. host:myhost). Omit to mute everything."
    )
    end: Optional[str] = Field(
        None, title="End", description="POSIX timestamp when the mute should end (optional)"
    )


class DatadogUnmuteMonitorConfig(BaseModel):
    """Re-enable a muted monitor."""

    operation: Literal["unmute_monitor"] = Field(
        "unmute_monitor",
        json_schema_extra={
            "const": "unmute_monitor",
            "ui:hidden": True,
            "x-category": "Monitors",
            "x-is-trigger": False,
            "x-display-name": "Unmute Monitor",
        },
        title="Unmute Monitor",
    )
    monitor_id: str = Field(
        ...,
        title="Monitor",
        description="The monitor to unmute",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "monitor_id",
                "placeholder": "Select a monitor...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste monitor ID",
            },
            "x-resource-type": "datadog_monitor",
        },
    )
    scope: Optional[str] = Field(
        None, title="Scope", description="Scope to unmute (e.g. host:myhost). Omit to unmute all."
    )


class DatadogSearchMonitorsConfig(BaseModel):
    """Search monitors by query string."""

    operation: Literal["search_monitors"] = Field(
        "search_monitors",
        json_schema_extra={
            "const": "search_monitors",
            "ui:hidden": True,
            "x-category": "Monitors",
            "x-is-trigger": False,
            "x-display-name": "Search Monitors",
        },
        title="Search Monitors",
    )
    query: str = Field(
        ...,
        title="Query",
        description="Search query (e.g. type:metric status:Alert). See Datadog monitor search syntax.",
    )
    page: Optional[str] = Field("0", title="Page", description="Page number (0-indexed)")
    per_page: Optional[str] = Field(
        "30", title="Per Page", description="Results per page (default 30)"
    )


# ============================================================================
# Operation Configs — Events
# ============================================================================


class DatadogPostEventConfig(BaseModel):
    """Post an event to the event stream."""

    operation: Literal["post_event"] = Field(
        "post_event",
        json_schema_extra={
            "const": "post_event",
            "ui:hidden": True,
            "x-category": "Events",
            "x-is-trigger": False,
            "x-display-name": "Post Event",
        },
        title="Post Event",
    )
    title: str = Field(..., title="Title", description="Event title")
    text: str = Field(
        ...,
        title="Text",
        description="Event body text (supports Markdown)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Event tags, comma-separated (e.g. env:prod,service:api)"
    )
    alert_type: str = Field(
        "info",
        title="Alert Type",
        json_schema_extra={
            "enum": ["info", "success", "warning", "error"],
            "enumNames": ["Info", "Success", "Warning", "Error"],
            "x-enum-searchable": True,
        },
    )
    priority: str = Field(
        "normal",
        title="Priority",
        json_schema_extra={
            "enum": ["normal", "low"],
            "enumNames": ["Normal", "Low"],
            "x-enum-searchable": True,
        },
    )
    host: Optional[str] = Field(None, title="Host", description="Hostname to associate with the event. Optional.")
    aggregation_key: Optional[str] = Field(
        None, title="Aggregation Key", description="Key to group related events together. Optional."
    )


class DatadogGetEventConfig(BaseModel):
    """Fetch a single event."""

    operation: Literal["get_event"] = Field(
        "get_event",
        json_schema_extra={
            "const": "get_event",
            "ui:hidden": True,
            "x-category": "Events",
            "x-is-trigger": False,
            "x-display-name": "Get Event",
        },
        title="Get Event",
    )
    event_id: str = Field(..., title="Event ID", description="The ID of the event to retrieve")


class DatadogListEventsConfig(BaseModel):
    """List events in a time range."""

    operation: Literal["list_events"] = Field(
        "list_events",
        json_schema_extra={
            "const": "list_events",
            "ui:hidden": True,
            "x-category": "Events",
            "x-is-trigger": False,
            "x-display-name": "List Events",
        },
        title="List Events",
    )
    filter_from: Optional[str] = Field(
        None,
        title="From",
        description="Lower time bound (e.g. now-1h, or ISO 8601 / epoch). Optional.",
    )
    filter_to: Optional[str] = Field(
        None, title="To", description="Upper time bound (e.g. now). Optional."
    )
    filter_query: Optional[str] = Field(
        None, title="Query", description="Event search query to filter results. Optional."
    )
    page_limit: Optional[str] = Field(
        "20", title="Limit", description="Max events to return (default 20)"
    )


class DatadogSearchEventsConfig(BaseModel):
    """Query events with a structured filter."""

    operation: Literal["search_events"] = Field(
        "search_events",
        json_schema_extra={
            "const": "search_events",
            "ui:hidden": True,
            "x-category": "Events",
            "x-is-trigger": False,
            "x-display-name": "Search Events",
        },
        title="Search Events",
    )
    query: str = Field(
        ..., title="Query", description="Event search query (e.g. source:nagios status:error)"
    )
    filter_from: str = Field(
        "now-1h", title="From", description="Lower time bound (e.g. now-1h)"
    )
    filter_to: str = Field("now", title="To", description="Upper time bound (e.g. now)")
    page_limit: Optional[str] = Field(
        "20", title="Limit", description="Max events to return (default 20)"
    )


# ============================================================================
# Operation Configs — Trigger (poll-based)
# ============================================================================


class DatadogOnNewEventConfig(BaseModel):
    """Poll the Events API v2 for new events matching a query (poll-based trigger).

    Datadog has no consumer-facing webhook subscription API, so this trigger
    polls ``GET /api/v2/events`` on a schedule. New events are deduplicated via a
    cursor on the last-seen event id so already-emitted events never re-fire.
    """

    operation: Literal["on_new_event"] = Field(
        "on_new_event",
        json_schema_extra={
            "const": "on_new_event",
            "ui:hidden": True,
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On New Event",
        },
        title="On New Event",
    )
    query: str = Field(
        "",
        title="Event Query",
        description="Event search query to filter which events trigger the workflow (e.g. 'status:error source:nagios'). Leave blank to match all events.",
        json_schema_extra={"placeholder": "status:error (optional)"},
    )
    schedule: Optional[ScheduleConfig] = Field(
        default=ScheduleConfig(frequency="minutes", interval=5),
        title="Check Frequency",
        description="How often to poll Datadog for new events",
        json_schema_extra={
            "ui:widget": "schedule",
            "x-exclude-frequencies": ["seconds"],
        },
    )
    max_results: int = Field(
        25,
        title="Max Events",
        description="Maximum number of events to fetch per check (1-100)",
        ge=1,
        le=100,
    )
    # Cursor for dedup — the id of the most recently emitted event.
    last_seen_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    # Hidden operational fields for webhook/schedule management.
    webhook_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:widget": "webhook", "ui:hidden": True, "ui:loadValue": True, "ui:copyable": True},
    )
    schedule_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    next_run: Optional[str] = Field(
        default=None,
        title="Next Check",
        json_schema_extra={"ui:widget": "nextRun"},
    )
    interval_ms: Optional[int] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    is_active: Optional[bool] = Field(
        default=True,
        json_schema_extra={"ui:hidden": True},
    )


# ============================================================================
# Operation Configs — Metrics
# ============================================================================


class DatadogSubmitMetricsConfig(BaseModel):
    """Submit metric data points (time series)."""

    operation: Literal["submit_metrics"] = Field(
        "submit_metrics",
        json_schema_extra={
            "const": "submit_metrics",
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-is-trigger": False,
            "x-display-name": "Submit Metrics",
        },
        title="Submit Metrics",
    )
    metric: str = Field(
        ..., title="Metric Name", description="The metric name (e.g. my.app.requests)"
    )
    value: str = Field(..., title="Value", description="The numeric metric value to submit")
    timestamp: Optional[str] = Field(
        None,
        title="Timestamp",
        description="POSIX timestamp for the point. Defaults to now if omitted.",
    )
    metric_type: str = Field(
        "gauge",
        title="Type",
        description="Metric type",
        json_schema_extra={
            "enum": ["gauge", "count", "rate"],
            "enumNames": ["Gauge", "Count", "Rate"],
            "x-enum-searchable": True,
        },
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Metric tags, comma-separated (e.g. env:prod)"
    )


class DatadogQueryTimeseriesConfig(BaseModel):
    """Cross-product timeseries data query (v2)."""

    operation: Literal["query_timeseries"] = Field(
        "query_timeseries",
        json_schema_extra={
            "const": "query_timeseries",
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-is-trigger": False,
            "x-display-name": "Query Timeseries",
        },
        title="Query Timeseries",
    )
    query: str = Field(
        ..., title="Query", description="The metrics query (e.g. avg:system.cpu.user{*})"
    )
    from_ms: str = Field(
        ..., title="From (ms)", description="Start of the query window in epoch milliseconds"
    )
    to_ms: str = Field(
        ..., title="To (ms)", description="End of the query window in epoch milliseconds"
    )


class DatadogQueryMetricsConfig(BaseModel):
    """Query metric points over a time range (legacy v1)."""

    operation: Literal["query_metrics"] = Field(
        "query_metrics",
        json_schema_extra={
            "const": "query_metrics",
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-is-trigger": False,
            "x-display-name": "Query Metrics (Legacy)",
        },
        title="Query Metrics (Legacy)",
    )
    query: str = Field(
        ..., title="Query", description="The metrics query (e.g. system.cpu.idle{*})"
    )
    from_ts: str = Field(
        ..., title="From", description="Start of the query window as a POSIX timestamp (seconds)"
    )
    to_ts: str = Field(
        ..., title="To", description="End of the query window as a POSIX timestamp (seconds)"
    )


class DatadogListMetricsConfig(BaseModel):
    """List metrics actively reporting since a timestamp."""

    operation: Literal["list_metrics"] = Field(
        "list_metrics",
        json_schema_extra={
            "const": "list_metrics",
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-is-trigger": False,
            "x-display-name": "List Active Metrics",
        },
        title="List Active Metrics",
    )
    from_ts: str = Field(
        ...,
        title="From",
        description="POSIX timestamp (seconds); only metrics reporting after this are returned",
    )
    host: Optional[str] = Field(
        None, title="Host", description="Filter to metrics reported by this host (optional)"
    )


class DatadogGetMetricMetadataConfig(BaseModel):
    """Fetch metadata for a metric."""

    operation: Literal["get_metric_metadata"] = Field(
        "get_metric_metadata",
        json_schema_extra={
            "const": "get_metric_metadata",
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-is-trigger": False,
            "x-display-name": "Get Metric Metadata",
        },
        title="Get Metric Metadata",
    )
    metric_name: str = Field(
        ..., title="Metric Name", description="The metric to fetch metadata for"
    )


# ============================================================================
# Operation Configs — Logs
# ============================================================================


class DatadogSendLogsConfig(BaseModel):
    """Submit a log entry to the intake."""

    operation: Literal["send_logs"] = Field(
        "send_logs",
        json_schema_extra={
            "const": "send_logs",
            "ui:hidden": True,
            "x-category": "Logs",
            "x-is-trigger": False,
            "x-display-name": "Send Logs",
        },
        title="Send Logs",
    )
    message: str = Field(
        ...,
        title="Message",
        description="The log message",
        json_schema_extra={"ui:widget": "textarea"},
    )
    ddsource: Optional[str] = Field(
        None, title="Source", description="Log source (e.g. python, nginx). Optional."
    )
    service: Optional[str] = Field(
        None, title="Service", description="Originating service name. Optional."
    )
    ddtags: Optional[str] = Field(
        None, title="Tags", description="Log tags, comma-separated (e.g. env:prod). Optional."
    )
    hostname: Optional[str] = Field(
        None, title="Hostname", description="Originating hostname. Optional."
    )


class DatadogSearchLogsConfig(BaseModel):
    """Search log events (v2 query)."""

    operation: Literal["search_logs"] = Field(
        "search_logs",
        json_schema_extra={
            "const": "search_logs",
            "ui:hidden": True,
            "x-category": "Logs",
            "x-is-trigger": False,
            "x-display-name": "Search Logs",
        },
        title="Search Logs",
    )
    query: str = Field(
        ..., title="Query", description="Log search query (e.g. service:api status:error)"
    )
    filter_from: str = Field("now-15m", title="From", description="Lower time bound (e.g. now-15m)")
    filter_to: str = Field("now", title="To", description="Upper time bound (e.g. now)")
    page_limit: Optional[str] = Field(
        "25", title="Limit", description="Max log events to return (default 25)"
    )


class DatadogAggregateLogsConfig(BaseModel):
    """Aggregate/group log events."""

    operation: Literal["aggregate_logs"] = Field(
        "aggregate_logs",
        json_schema_extra={
            "const": "aggregate_logs",
            "ui:hidden": True,
            "x-category": "Logs",
            "x-is-trigger": False,
            "x-display-name": "Aggregate Logs",
        },
        title="Aggregate Logs",
    )
    query: str = Field(
        ..., title="Query", description="Log search query to aggregate over"
    )
    filter_from: str = Field("now-15m", title="From", description="Lower time bound (e.g. now-15m)")
    filter_to: str = Field("now", title="To", description="Upper time bound (e.g. now)")
    compute_json: Optional[str] = Field(
        None,
        title="Compute (JSON)",
        description='Aggregation spec as JSON list (e.g. [{"aggregation": "count"}]). Defaults to count.',
        json_schema_extra={"ui:widget": "textarea"},
    )
    group_by: Optional[str] = Field(
        None,
        title="Group By",
        description="Facets to group by, comma-separated (e.g. service,status). Optional.",
    )


# ============================================================================
# Operation Configs — Dashboards
# ============================================================================


class DatadogCreateDashboardConfig(BaseModel):
    """Create a dashboard."""

    operation: Literal["create_dashboard"] = Field(
        "create_dashboard",
        json_schema_extra={
            "const": "create_dashboard",
            "ui:hidden": True,
            "x-category": "Dashboards",
            "x-is-trigger": False,
            "x-display-name": "Create Dashboard",
            "x-creates-resource": True,
            "x-resource-type": "datadog_dashboard",
            "x-resource-id-path": "data.id",
        },
        title="Create Dashboard",
    )
    title: str = Field(..., title="Title", description="Dashboard title")
    layout_type: str = Field(
        "ordered",
        title="Layout Type",
        description="Dashboard layout",
        json_schema_extra={
            "enum": ["ordered", "free"],
            "enumNames": ["Ordered (timeboard)", "Free (screenboard)"],
            "x-enum-searchable": True,
        },
    )
    widgets_json: Optional[str] = Field(
        None,
        title="Widgets (JSON)",
        description='Widget definitions as a JSON list. Defaults to empty (e.g. [{"definition": {...}}]).',
        json_schema_extra={"ui:widget": "textarea"},
    )
    description: Optional[str] = Field(
        None, title="Description", description="Dashboard description (optional)"
    )


class DatadogGetDashboardConfig(BaseModel):
    """Fetch a dashboard definition."""

    operation: Literal["get_dashboard"] = Field(
        "get_dashboard",
        json_schema_extra={
            "const": "get_dashboard",
            "ui:hidden": True,
            "x-category": "Dashboards",
            "x-is-trigger": False,
            "x-display-name": "Get Dashboard",
        },
        title="Get Dashboard",
    )
    dashboard_id: str = Field(
        ...,
        title="Dashboard",
        description="The dashboard to retrieve",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "dashboard_id",
                "placeholder": "Select a dashboard...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste dashboard ID",
            },
            "x-resource-type": "datadog_dashboard",
        },
    )


class DatadogListDashboardsConfig(BaseModel):
    """List all dashboards."""

    operation: Literal["list_dashboards"] = Field(
        "list_dashboards",
        json_schema_extra={
            "const": "list_dashboards",
            "ui:hidden": True,
            "x-category": "Dashboards",
            "x-is-trigger": False,
            "x-display-name": "List Dashboards",
        },
        title="List Dashboards",
    )
    filter_shared: Optional[str] = Field(
        None,
        title="Shared Only",
        description="Only return shared dashboards",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Any", "Shared only", "Not shared"],
            "x-enum-searchable": True,
        },
    )


class DatadogUpdateDashboardConfig(BaseModel):
    """Update a dashboard."""

    operation: Literal["update_dashboard"] = Field(
        "update_dashboard",
        json_schema_extra={
            "const": "update_dashboard",
            "ui:hidden": True,
            "x-category": "Dashboards",
            "x-is-trigger": False,
            "x-display-name": "Update Dashboard",
        },
        title="Update Dashboard",
    )
    dashboard_id: str = Field(
        ...,
        title="Dashboard",
        description="The dashboard to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "dashboard_id",
                "placeholder": "Select a dashboard...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste dashboard ID",
            },
            "x-resource-type": "datadog_dashboard",
        },
    )
    title: str = Field(..., title="Title", description="New dashboard title")
    layout_type: str = Field(
        "ordered",
        title="Layout Type",
        description="Dashboard layout",
        json_schema_extra={
            "enum": ["ordered", "free"],
            "enumNames": ["Ordered (timeboard)", "Free (screenboard)"],
            "x-enum-searchable": True,
        },
    )
    widgets_json: Optional[str] = Field(
        None,
        title="Widgets (JSON)",
        description="Widget definitions as a JSON list. Defaults to empty.",
        json_schema_extra={"ui:widget": "textarea"},
    )


class DatadogDeleteDashboardConfig(BaseModel):
    """Delete a dashboard."""

    operation: Literal["delete_dashboard"] = Field(
        "delete_dashboard",
        json_schema_extra={
            "const": "delete_dashboard",
            "ui:hidden": True,
            "x-category": "Dashboards",
            "x-is-trigger": False,
            "x-display-name": "Delete Dashboard",
        },
        title="Delete Dashboard",
    )
    dashboard_id: str = Field(
        ...,
        title="Dashboard",
        description="The dashboard to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "dashboard_id",
                "placeholder": "Select a dashboard...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste dashboard ID",
            },
            "x-resource-type": "datadog_dashboard",
        },
    )


# ============================================================================
# Operation Configs — Incidents
# ============================================================================


class DatadogCreateIncidentConfig(BaseModel):
    """Open an incident."""

    operation: Literal["create_incident"] = Field(
        "create_incident",
        json_schema_extra={
            "const": "create_incident",
            "ui:hidden": True,
            "x-category": "Incidents",
            "x-is-trigger": False,
            "x-display-name": "Create Incident",
        },
        title="Create Incident",
    )
    title: str = Field(..., title="Title", description="Incident title")
    customer_impacted: str = Field(
        "false",
        title="Customer Impacted",
        description="Whether customers are impacted",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class DatadogListIncidentsConfig(BaseModel):
    """List incidents."""

    operation: Literal["list_incidents"] = Field(
        "list_incidents",
        json_schema_extra={
            "const": "list_incidents",
            "ui:hidden": True,
            "x-category": "Incidents",
            "x-is-trigger": False,
            "x-display-name": "List Incidents",
        },
        title="List Incidents",
    )
    page_size: Optional[str] = Field(
        "10", title="Limit", description="Max incidents per page (default 10)"
    )
    page_offset: Optional[str] = Field(
        "0", title="Offset", description="Result offset for pagination (default 0)"
    )


class DatadogUpdateIncidentConfig(BaseModel):
    """Update incident fields/state."""

    operation: Literal["update_incident"] = Field(
        "update_incident",
        json_schema_extra={
            "const": "update_incident",
            "ui:hidden": True,
            "x-category": "Incidents",
            "x-is-trigger": False,
            "x-display-name": "Update Incident",
        },
        title="Update Incident",
    )
    incident_id: str = Field(
        ..., title="Incident ID", description="The ID of the incident to update"
    )
    title: Optional[str] = Field(None, title="Title", description="New incident title")
    state: Optional[str] = Field(
        None,
        title="State",
        description="New incident state",
        json_schema_extra={
            "enum": ["", "active", "stable", "resolved"],
            "enumNames": ["No change", "Active", "Stable", "Resolved"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Operation Configs — Downtimes
# ============================================================================


class DatadogCreateDowntimeConfig(BaseModel):
    """Schedule a monitor downtime."""

    operation: Literal["create_downtime"] = Field(
        "create_downtime",
        json_schema_extra={
            "const": "create_downtime",
            "ui:hidden": True,
            "x-category": "Downtimes",
            "x-is-trigger": False,
            "x-display-name": "Create Downtime",
        },
        title="Create Downtime",
    )
    scope: str = Field(
        "*",
        title="Scope",
        description="Host/environment scope to mute (e.g. env:staging, host:myhost). Use * for all.",
    )
    monitor_id: Optional[str] = Field(
        None,
        title="Monitor ID",
        description="Silence only this specific monitor (leave blank for all monitors)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "monitor_id",
                "placeholder": "Select a monitor...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste monitor ID",
            },
            "x-resource-type": "datadog_monitor",
        },
    )
    monitor_tags: Optional[str] = Field(
        None,
        title="Monitor Tags",
        description="Silence only monitors matching these tags, comma-separated (e.g. env:prod,team:infra). Ignored when Monitor ID is set.",
    )
    message: Optional[str] = Field(
        None, title="Message", description="Message attached to the downtime (optional)"
    )
    start: Optional[str] = Field(
        None,
        title="Start",
        description="POSIX timestamp for when the downtime starts. Defaults to now.",
    )
    end: Optional[str] = Field(
        None,
        title="End",
        description="POSIX timestamp for when the downtime ends. Omit for an indefinite downtime.",
    )


class DatadogCancelDowntimeConfig(BaseModel):
    """Cancel a scheduled downtime."""

    operation: Literal["cancel_downtime"] = Field(
        "cancel_downtime",
        json_schema_extra={
            "const": "cancel_downtime",
            "ui:hidden": True,
            "x-category": "Downtimes",
            "x-is-trigger": False,
            "x-display-name": "Cancel Downtime",
        },
        title="Cancel Downtime",
    )
    downtime_id: str = Field(
        ..., title="Downtime ID", description="The ID of the downtime to cancel"
    )


class DatadogListDowntimesConfig(BaseModel):
    """List scheduled downtimes."""

    operation: Literal["list_downtimes"] = Field(
        "list_downtimes",
        json_schema_extra={
            "const": "list_downtimes",
            "ui:hidden": True,
            "x-category": "Downtimes",
            "x-is-trigger": False,
            "x-display-name": "List Downtimes",
        },
        title="List Downtimes",
    )
    current_only: Optional[str] = Field(
        None,
        title="Current Only",
        description="Filter to only active downtimes (true/false)",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["All", "Active only", "All including ended"],
            "x-enum-searchable": True,
        },
    )


class DatadogGetDowntimeConfig(BaseModel):
    """Get a downtime by ID."""

    operation: Literal["get_downtime"] = Field(
        "get_downtime",
        json_schema_extra={
            "const": "get_downtime",
            "ui:hidden": True,
            "x-category": "Downtimes",
            "x-is-trigger": False,
            "x-display-name": "Get Downtime",
        },
        title="Get Downtime",
    )
    downtime_id: str = Field(..., title="Downtime ID", description="The downtime ID to retrieve")


class DatadogUpdateDowntimeConfig(BaseModel):
    """Update an existing downtime."""

    operation: Literal["update_downtime"] = Field(
        "update_downtime",
        json_schema_extra={
            "const": "update_downtime",
            "ui:hidden": True,
            "x-category": "Downtimes",
            "x-is-trigger": False,
            "x-display-name": "Update Downtime",
        },
        title="Update Downtime",
    )
    downtime_id: str = Field(..., title="Downtime ID", description="The downtime to update")
    scope: Optional[str] = Field(
        None, title="Scope", description="New scope (e.g. env:staging). Optional."
    )
    message: Optional[str] = Field(None, title="Message", description="New message. Optional.")
    end: Optional[str] = Field(
        None, title="End", description="New POSIX timestamp for the downtime end. Optional."
    )


# ============================================================================
# Operation Configs — SLOs
# ============================================================================


class DatadogCreateSLOConfig(BaseModel):
    """Create a Service Level Objective."""

    operation: Literal["create_slo"] = Field(
        "create_slo",
        json_schema_extra={
            "const": "create_slo",
            "ui:hidden": True,
            "x-category": "SLOs",
            "x-is-trigger": False,
            "x-display-name": "Create SLO",
        },
        title="Create SLO",
    )
    name: str = Field(..., title="Name", description="SLO display name")
    type: str = Field(
        "metric",
        title="Type",
        description="SLO type",
        json_schema_extra={
            "enum": ["metric", "monitor"],
            "enumNames": ["Metric-based", "Monitor-based"],
            "x-enum-searchable": True,
        },
    )
    target: str = Field(
        "99.9",
        title="Target (%)",
        description="SLO target percentage (e.g. 99.9 for 99.9%)",
    )
    timeframe: str = Field(
        "7d",
        title="Timeframe",
        description="Evaluation window",
        json_schema_extra={
            "enum": ["7d", "30d", "90d"],
            "enumNames": ["7 days", "30 days", "90 days"],
            "x-enum-searchable": True,
        },
    )
    description: Optional[str] = Field(None, title="Description", description="Optional description")
    tags: Optional[str] = Field(None, title="Tags", description="Comma-separated tags")
    query_numerator: Optional[str] = Field(
        None,
        title="Numerator Query",
        description="For metric SLOs: the good-events metric query",
    )
    query_denominator: Optional[str] = Field(
        None,
        title="Denominator Query",
        description="For metric SLOs: the total-events metric query",
    )
    monitor_ids: Optional[str] = Field(
        None,
        title="Monitor IDs",
        description="For monitor SLOs: comma-separated monitor IDs",
    )


class DatadogGetSLOConfig(BaseModel):
    """Get an SLO by ID."""

    operation: Literal["get_slo"] = Field(
        "get_slo",
        json_schema_extra={
            "const": "get_slo",
            "ui:hidden": True,
            "x-category": "SLOs",
            "x-is-trigger": False,
            "x-display-name": "Get SLO",
        },
        title="Get SLO",
    )
    slo_id: str = Field(..., title="SLO ID", description="The SLO to retrieve")


class DatadogListSLOsConfig(BaseModel):
    """List all SLOs."""

    operation: Literal["list_slos"] = Field(
        "list_slos",
        json_schema_extra={
            "const": "list_slos",
            "ui:hidden": True,
            "x-category": "SLOs",
            "x-is-trigger": False,
            "x-display-name": "List SLOs",
        },
        title="List SLOs",
    )
    tags_query: Optional[str] = Field(
        None, title="Tags Filter", description="Filter by tags (e.g. env:prod)"
    )
    limit: Optional[str] = Field("25", title="Limit", description="Max SLOs to return")
    offset: Optional[str] = Field(None, title="Offset", description="Pagination offset")


class DatadogUpdateSLOConfig(BaseModel):
    """Update an existing SLO."""

    operation: Literal["update_slo"] = Field(
        "update_slo",
        json_schema_extra={
            "const": "update_slo",
            "ui:hidden": True,
            "x-category": "SLOs",
            "x-is-trigger": False,
            "x-display-name": "Update SLO",
        },
        title="Update SLO",
    )
    slo_id: str = Field(..., title="SLO ID", description="The SLO to update")
    name: Optional[str] = Field(None, title="Name", description="New display name. Optional.")
    target: Optional[str] = Field(None, title="Target (%)", description="New target percentage. Optional.")
    description: Optional[str] = Field(None, title="Description", description="New description. Optional.")
    tags: Optional[str] = Field(None, title="Tags", description="New tags, comma-separated. Optional.")


class DatadogDeleteSLOConfig(BaseModel):
    """Delete an SLO."""

    operation: Literal["delete_slo"] = Field(
        "delete_slo",
        json_schema_extra={
            "const": "delete_slo",
            "ui:hidden": True,
            "x-category": "SLOs",
            "x-is-trigger": False,
            "x-display-name": "Delete SLO",
        },
        title="Delete SLO",
    )
    slo_id: str = Field(..., title="SLO ID", description="The SLO to delete")


class DatadogGetSLOHistoryConfig(BaseModel):
    """Get SLO performance history."""

    operation: Literal["get_slo_history"] = Field(
        "get_slo_history",
        json_schema_extra={
            "const": "get_slo_history",
            "ui:hidden": True,
            "x-category": "SLOs",
            "x-is-trigger": False,
            "x-display-name": "Get SLO History",
        },
        title="Get SLO History",
    )
    slo_id: str = Field(..., title="SLO ID", description="The SLO to fetch history for")
    from_ts: str = Field(..., title="From (POSIX)", description="Start of range as POSIX timestamp")
    to_ts: str = Field(..., title="To (POSIX)", description="End of range as POSIX timestamp")


# ============================================================================
# Operation Configs — Hosts
# ============================================================================


class DatadogListHostsConfig(BaseModel):
    """List infrastructure hosts."""

    operation: Literal["list_hosts"] = Field(
        "list_hosts",
        json_schema_extra={
            "const": "list_hosts",
            "ui:hidden": True,
            "x-category": "Hosts",
            "x-is-trigger": False,
            "x-display-name": "List Hosts",
        },
        title="List Hosts",
    )
    filter: Optional[str] = Field(
        None, title="Filter", description="Filter query (e.g. env:prod)"
    )
    count: Optional[str] = Field("100", title="Count", description="Max hosts to return")
    start: Optional[str] = Field(None, title="Start", description="Pagination offset")
    from_ts: Optional[str] = Field(
        None, title="From (POSIX)", description="Only return hosts active since this timestamp"
    )


class DatadogGetHostTotalsConfig(BaseModel):
    """Get total active host counts."""

    operation: Literal["get_host_totals"] = Field(
        "get_host_totals",
        json_schema_extra={
            "const": "get_host_totals",
            "ui:hidden": True,
            "x-category": "Hosts",
            "x-is-trigger": False,
            "x-display-name": "Get Host Totals",
        },
        title="Get Host Totals",
    )
    from_ts: Optional[str] = Field(
        None,
        title="From (POSIX)",
        description="Return host count for a specific historical time. Defaults to now.",
    )


class DatadogMuteHostConfig(BaseModel):
    """Mute a host to silence its alerts."""

    operation: Literal["mute_host"] = Field(
        "mute_host",
        json_schema_extra={
            "const": "mute_host",
            "ui:hidden": True,
            "x-category": "Hosts",
            "x-is-trigger": False,
            "x-display-name": "Mute Host",
        },
        title="Mute Host",
    )
    host_name: str = Field(..., title="Hostname", description="The hostname to mute")
    message: Optional[str] = Field(None, title="Message", description="Reason for muting")
    end: Optional[str] = Field(
        None, title="End (POSIX)", description="When to automatically unmute (POSIX timestamp)"
    )
    override: Optional[str] = Field(
        "false",
        title="Override",
        description="Whether to override an existing mute",
        json_schema_extra={
            "enum": ["false", "true"],
            "enumNames": ["No", "Yes"],
            "x-enum-searchable": True,
        },
    )


class DatadogUnmuteHostConfig(BaseModel):
    """Unmute a host."""

    operation: Literal["unmute_host"] = Field(
        "unmute_host",
        json_schema_extra={
            "const": "unmute_host",
            "ui:hidden": True,
            "x-category": "Hosts",
            "x-is-trigger": False,
            "x-display-name": "Unmute Host",
        },
        title="Unmute Host",
    )
    host_name: str = Field(..., title="Hostname", description="The hostname to unmute")


# ============================================================================
# Operation Configs — Tags
# ============================================================================


class DatadogGetHostTagsConfig(BaseModel):
    """Get tags for a specific host."""

    operation: Literal["get_host_tags"] = Field(
        "get_host_tags",
        json_schema_extra={
            "const": "get_host_tags",
            "ui:hidden": True,
            "x-category": "Tags",
            "x-is-trigger": False,
            "x-display-name": "Get Host Tags",
        },
        title="Get Host Tags",
    )
    host_name: str = Field(..., title="Hostname", description="The host to get tags for")
    source: Optional[str] = Field(
        None, title="Source", description="Tag source filter (e.g. chef, puppet). Optional."
    )


class DatadogAddHostTagsConfig(BaseModel):
    """Add tags to a host."""

    operation: Literal["add_host_tags"] = Field(
        "add_host_tags",
        json_schema_extra={
            "const": "add_host_tags",
            "ui:hidden": True,
            "x-category": "Tags",
            "x-is-trigger": False,
            "x-display-name": "Add Host Tags",
        },
        title="Add Host Tags",
    )
    host_name: str = Field(..., title="Hostname", description="The host to tag")
    tags: str = Field(..., title="Tags", description="Comma-separated tags to add (e.g. env:prod,team:infra)")
    source: Optional[str] = Field(None, title="Source", description="Tag source identifier. Optional.")


class DatadogUpdateHostTagsConfig(BaseModel):
    """Replace all tags on a host."""

    operation: Literal["update_host_tags"] = Field(
        "update_host_tags",
        json_schema_extra={
            "const": "update_host_tags",
            "ui:hidden": True,
            "x-category": "Tags",
            "x-is-trigger": False,
            "x-display-name": "Update Host Tags",
        },
        title="Update Host Tags",
    )
    host_name: str = Field(..., title="Hostname", description="The host to update tags on")
    tags: str = Field(
        ..., title="Tags", description="Comma-separated tags that will REPLACE all existing tags"
    )
    source: Optional[str] = Field(None, title="Source", description="Tag source identifier. Optional.")


class DatadogDeleteHostTagsConfig(BaseModel):
    """Remove all tags from a host."""

    operation: Literal["delete_host_tags"] = Field(
        "delete_host_tags",
        json_schema_extra={
            "const": "delete_host_tags",
            "ui:hidden": True,
            "x-category": "Tags",
            "x-is-trigger": False,
            "x-display-name": "Delete Host Tags",
        },
        title="Delete Host Tags",
    )
    host_name: str = Field(..., title="Hostname", description="The host to remove tags from")
    source: Optional[str] = Field(None, title="Source", description="Tag source to remove. Optional.")


# ============================================================================
# Operation Configs — Service Checks
# ============================================================================


class DatadogSubmitServiceCheckConfig(BaseModel):
    """Post a service check run."""

    operation: Literal["submit_service_check"] = Field(
        "submit_service_check",
        json_schema_extra={
            "const": "submit_service_check",
            "ui:hidden": True,
            "x-category": "Service Checks",
            "x-is-trigger": False,
            "x-display-name": "Submit Service Check",
        },
        title="Submit Service Check",
    )
    check: str = Field(
        ..., title="Check Name", description="The service check name (e.g. app.is_healthy)"
    )
    host_name: str = Field(..., title="Hostname", description="The hostname submitting the check")
    status: str = Field(
        "0",
        title="Status",
        description="Check status code",
        json_schema_extra={
            "enum": ["0", "1", "2", "3"],
            "enumNames": ["OK (0)", "Warning (1)", "Critical (2)", "Unknown (3)"],
            "x-enum-searchable": True,
        },
    )
    message: Optional[str] = Field(
        None, title="Message", description="Check message (max 500 chars; ignored for OK status)"
    )
    tags: Optional[str] = Field(None, title="Tags", description="Comma-separated tags")
    timestamp: Optional[str] = Field(
        None, title="Timestamp", description="POSIX timestamp of the check. Defaults to now."
    )


# ============================================================================
# Operation Configs — Synthetics
# ============================================================================


class DatadogListSyntheticsConfig(BaseModel):
    """List synthetic tests."""

    operation: Literal["list_synthetics"] = Field(
        "list_synthetics",
        json_schema_extra={
            "const": "list_synthetics",
            "ui:hidden": True,
            "x-category": "Synthetics",
            "x-is-trigger": False,
            "x-display-name": "List Synthetic Tests",
        },
        title="List Synthetic Tests",
    )
    location_names: Optional[str] = Field(
        None, title="Locations", description="Comma-separated location names to filter by. Optional."
    )


class DatadogGetSyntheticsConfig(BaseModel):
    """Get a synthetic test configuration."""

    operation: Literal["get_synthetics"] = Field(
        "get_synthetics",
        json_schema_extra={
            "const": "get_synthetics",
            "ui:hidden": True,
            "x-category": "Synthetics",
            "x-is-trigger": False,
            "x-display-name": "Get Synthetic Test",
        },
        title="Get Synthetic Test",
    )
    public_id: str = Field(
        ..., title="Test Public ID", description="The synthetic test public ID (e.g. abc-123-xyz)"
    )


class DatadogTriggerSyntheticsConfig(BaseModel):
    """Trigger one or more synthetic tests to run immediately."""

    operation: Literal["trigger_synthetics"] = Field(
        "trigger_synthetics",
        json_schema_extra={
            "const": "trigger_synthetics",
            "ui:hidden": True,
            "x-category": "Synthetics",
            "x-is-trigger": False,
            "x-display-name": "Trigger Synthetic Tests",
        },
        title="Trigger Synthetic Tests",
    )
    public_ids: str = Field(
        ...,
        title="Test IDs",
        description="Comma-separated public IDs of tests to trigger (e.g. abc-123-xyz,def-456-uvw)",
    )


class DatadogPauseSyntheticsConfig(BaseModel):
    """Pause or resume a synthetic test."""

    operation: Literal["pause_synthetics"] = Field(
        "pause_synthetics",
        json_schema_extra={
            "const": "pause_synthetics",
            "ui:hidden": True,
            "x-category": "Synthetics",
            "x-is-trigger": False,
            "x-display-name": "Pause/Resume Synthetic Test",
        },
        title="Pause/Resume Synthetic Test",
    )
    public_id: str = Field(..., title="Test Public ID", description="The synthetic test to pause/resume")
    new_status: str = Field(
        "paused",
        title="Action",
        description="Set the test status",
        json_schema_extra={
            "enum": ["paused", "live"],
            "enumNames": ["Pause", "Resume (live)"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Discriminated Union
# ============================================================================


DatadogConfig = Annotated[
    Union[
        DatadogCreateMonitorConfig,
        DatadogGetMonitorConfig,
        DatadogListMonitorsConfig,
        DatadogUpdateMonitorConfig,
        DatadogDeleteMonitorConfig,
        DatadogMuteMonitorConfig,
        DatadogUnmuteMonitorConfig,
        DatadogSearchMonitorsConfig,
        DatadogPostEventConfig,
        DatadogGetEventConfig,
        DatadogListEventsConfig,
        DatadogSearchEventsConfig,
        DatadogOnNewEventConfig,
        DatadogSubmitMetricsConfig,
        DatadogQueryTimeseriesConfig,
        DatadogQueryMetricsConfig,
        DatadogListMetricsConfig,
        DatadogGetMetricMetadataConfig,
        DatadogSendLogsConfig,
        DatadogSearchLogsConfig,
        DatadogAggregateLogsConfig,
        DatadogCreateDashboardConfig,
        DatadogGetDashboardConfig,
        DatadogListDashboardsConfig,
        DatadogUpdateDashboardConfig,
        DatadogDeleteDashboardConfig,
        DatadogCreateIncidentConfig,
        DatadogListIncidentsConfig,
        DatadogUpdateIncidentConfig,
        DatadogCreateDowntimeConfig,
        DatadogCancelDowntimeConfig,
        DatadogListDowntimesConfig,
        DatadogGetDowntimeConfig,
        DatadogUpdateDowntimeConfig,
        DatadogCreateSLOConfig,
        DatadogGetSLOConfig,
        DatadogListSLOsConfig,
        DatadogUpdateSLOConfig,
        DatadogDeleteSLOConfig,
        DatadogGetSLOHistoryConfig,
        DatadogListHostsConfig,
        DatadogGetHostTotalsConfig,
        DatadogMuteHostConfig,
        DatadogUnmuteHostConfig,
        DatadogGetHostTagsConfig,
        DatadogAddHostTagsConfig,
        DatadogUpdateHostTagsConfig,
        DatadogDeleteHostTagsConfig,
        DatadogSubmitServiceCheckConfig,
        DatadogListSyntheticsConfig,
        DatadogGetSyntheticsConfig,
        DatadogTriggerSyntheticsConfig,
        DatadogPauseSyntheticsConfig,
    ],
    Discriminator("operation"),
]


class DatadogNodeConfig(NodeConfig[DatadogConfig, DatadogCredential]):
    """Full configuration for the Datadog node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _base_url(site: Optional[str]) -> str:
    return DATADOG_SITES.get(site or DEFAULT_SITE, DATADOG_SITES[DEFAULT_SITE])


async def _datadog_request(
    api_key: str,
    app_key: Optional[str],
    site: Optional[str],
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Datadog request and return a structured result.

    Datadog uses header auth: DD-API-KEY on every request, DD-APPLICATION-KEY on
    read/query endpoints. Submission endpoints (metrics/logs/events post) work
    with just DD-API-KEY, but sending the app key too is harmless.
    """
    url = f"{_base_url(site)}{endpoint}"
    headers = {
        "DD-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    if app_key:
        headers["DD-APPLICATION-KEY"] = app_key

    if json_body is not None and isinstance(json_body, dict):
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    errors = err.get("errors") if isinstance(err, dict) else None
                    if isinstance(errors, list) and errors:
                        message = "; ".join(str(e) for e in errors)
                    else:
                        message = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[DatadogNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204 or not response.text:
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
            logger.error(f"[DatadogNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


def _parse_json_field(value: Optional[str], field_name: str) -> Any:
    """Parse a user-provided JSON string field; raise a clear error if malformed."""
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in '{field_name}': {e}")


# ============================================================================
# Node Implementation
# ============================================================================


class DatadogNode(CronScheduleTriggerMixin, WorkflowNode):
    """Datadog observability automation node."""

    schedule_trigger_operations = ("on_new_event",)
    schedule_source = "datadog_trigger"

    edit_examples = [
        "Create a CPU monitor that alerts when usage exceeds 80%",
        "Post a deployment event to the Datadog event stream",
        "Submit a custom metric value with tags",
        "Search error logs from the last 15 minutes",
        "Open an incident and mark customers as impacted",
        "Mute a noisy monitor during a maintenance window",
    ]

    @classmethod
    def get_config_model(cls):
        return DatadogNodeConfig

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """The Datadog trigger is poll-based: the webhook is a wake-up signal, not
        data. Return None for the poll op so execute() runs and polls the Events
        API; other ops keep the default passthrough behaviour."""
        if config.get("operation") == "on_new_event":
            return None
        return payload

    def trigger_produced_no_event(self, output: Dict[str, Any]) -> bool:
        """On a scheduled tick with no new events, skip downstream nodes."""
        return (
            output.get("operation") == "on_new_event"
            and not output.get("events")
        )

    def trigger_emitted_event(self, output):
        """Fresh events emitted → executor stamps _pollFired so a wired agent
        receives them on any run source."""
        return (
            isinstance(output, dict)
            and output.get("operation") == "on_new_event"
            and bool(output.get("events"))
        )

    # load_field_value (webhook + schedule registration) is inherited from
    # CronScheduleTriggerMixin — it converges through reconcile_node.

    # ------------------------------------------------------------------
    # Dynamic options (monitors + dashboards)
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
        if field_name not in ("monitor_id", "dashboard_id"):
            return {"options": []}
        if not credential_data:
            return {"options": []}
        api_key = credential_data.get("api_key")
        app_key = credential_data.get("app_key")
        site = credential_data.get("site")
        if not api_key:
            return {"options": []}

        if field_name == "monitor_id":
            params: Dict[str, Any] = {"page_size": 100}
            if search:
                params["name"] = search
            result = await _datadog_request(
                api_key, app_key, site, "GET", "/api/v1/monitor",
                params=params, action_name="list_monitors",
            )
            if result.get("status") != "success":
                return {"options": []}
            monitors = result.get("data") or []
            options = []
            if isinstance(monitors, list):
                for m in monitors:
                    if not isinstance(m, dict):
                        continue
                    mid = m.get("id")
                    name = m.get("name") or f"Monitor {mid}"
                    if mid is not None:
                        options.append({"label": str(name), "value": str(mid)})
            return {"options": options}

        # dashboard_id
        result = await _datadog_request(
            api_key, app_key, site, "GET", "/api/v1/dashboard", action_name="list_dashboards"
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        dashboards = data.get("dashboards") if isinstance(data, dict) else []
        options = []
        for d in dashboards or []:
            if not isinstance(d, dict):
                continue
            did = d.get("id")
            title = d.get("title") or f"Dashboard {did}"
            if did is not None:
                if not search or search.lower() in title.lower():
                    options.append({"label": str(title), "value": str(did)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, DatadogNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Datadog API key and Application key.")
        api_key = credentials.api_key
        app_key = credentials.app_key
        site = credentials.site

        handlers = {
            "create_monitor": self._create_monitor,
            "get_monitor": self._get_monitor,
            "list_monitors": self._list_monitors,
            "update_monitor": self._update_monitor,
            "delete_monitor": self._delete_monitor,
            "mute_monitor": self._mute_monitor,
            "unmute_monitor": self._unmute_monitor,
            "search_monitors": self._search_monitors,
            "post_event": self._post_event,
            "get_event": self._get_event,
            "list_events": self._list_events,
            "search_events": self._search_events,
            "on_new_event": self._poll_new_events,
            "submit_metrics": self._submit_metrics,
            "query_timeseries": self._query_timeseries,
            "query_metrics": self._query_metrics,
            "list_metrics": self._list_metrics,
            "get_metric_metadata": self._get_metric_metadata,
            "send_logs": self._send_logs,
            "search_logs": self._search_logs,
            "aggregate_logs": self._aggregate_logs,
            "create_dashboard": self._create_dashboard,
            "get_dashboard": self._get_dashboard,
            "list_dashboards": self._list_dashboards,
            "update_dashboard": self._update_dashboard,
            "delete_dashboard": self._delete_dashboard,
            "create_incident": self._create_incident,
            "list_incidents": self._list_incidents,
            "update_incident": self._update_incident,
            "create_downtime": self._create_downtime,
            "cancel_downtime": self._cancel_downtime,
            "list_downtimes": self._list_downtimes,
            "get_downtime": self._get_downtime,
            "update_downtime": self._update_downtime,
            "create_slo": self._create_slo,
            "get_slo": self._get_slo,
            "list_slos": self._list_slos,
            "update_slo": self._update_slo,
            "delete_slo": self._delete_slo,
            "get_slo_history": self._get_slo_history,
            "list_hosts": self._list_hosts,
            "get_host_totals": self._get_host_totals,
            "mute_host": self._mute_host,
            "unmute_host": self._unmute_host,
            "get_host_tags": self._get_host_tags,
            "add_host_tags": self._add_host_tags,
            "update_host_tags": self._update_host_tags,
            "delete_host_tags": self._delete_host_tags,
            "submit_service_check": self._submit_service_check,
            "list_synthetics": self._list_synthetics,
            "get_synthetics": self._get_synthetics,
            "trigger_synthetics": self._trigger_synthetics,
            "pause_synthetics": self._pause_synthetics,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key, app_key, site)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Monitor handlers
    # ------------------------------------------------------------------
    async def _create_monitor(self, c: DatadogCreateMonitorConfig, api_key, app_key, site):
        body: Dict[str, Any] = {
            "name": c.name,
            "type": c.type,
            "query": c.query,
            "message": c.message,
            "tags": _comma_list(c.tags),
            "options": _parse_json_field(c.options_json, "Options (JSON)"),
        }
        return await _datadog_request(
            api_key, app_key, site, "POST", "/api/v1/monitor", json_body=body,
            action_name="create_monitor",
        )

    async def _get_monitor(self, c: DatadogGetMonitorConfig, api_key, app_key, site):
        return await _datadog_request(
            api_key, app_key, site, "GET", f"/api/v1/monitor/{c.monitor_id}",
            action_name="get_monitor",
        )

    async def _list_monitors(self, c: DatadogListMonitorsConfig, api_key, app_key, site):
        params = {
            "tags": (",".join(t) if (t := _comma_list(c.tags)) else None),
            "monitor_tags": (",".join(t) if (t := _comma_list(c.monitor_tags)) else None),
            "name": c.name,
            "page_size": c.page_size,
        }
        return await _datadog_request(
            api_key, app_key, site, "GET", "/api/v1/monitor", params=params,
            action_name="list_monitors",
        )

    async def _update_monitor(self, c: DatadogUpdateMonitorConfig, api_key, app_key, site):
        body = {
            "name": c.name,
            "query": c.query,
            "message": c.message,
            "tags": _comma_list(c.tags),
        }
        return await _datadog_request(
            api_key, app_key, site, "PUT", f"/api/v1/monitor/{c.monitor_id}", json_body=body,
            action_name="update_monitor",
        )

    async def _delete_monitor(self, c: DatadogDeleteMonitorConfig, api_key, app_key, site):
        return await _datadog_request(
            api_key, app_key, site, "DELETE", f"/api/v1/monitor/{c.monitor_id}",
            action_name="delete_monitor",
        )

    async def _mute_monitor(self, c: DatadogMuteMonitorConfig, api_key, app_key, site):
        end_ts = None
        if c.end:
            try:
                end_ts = int(float(c.end))
            except (ValueError, TypeError):
                raise ValueError(f"Invalid 'End' timestamp: {c.end!r}. Provide a POSIX timestamp (e.g. 1750000000).")
        body = {
            "scope": c.scope,
            "end": end_ts,
        }
        return await _datadog_request(
            api_key, app_key, site, "POST", f"/api/v1/monitor/{c.monitor_id}/mute",
            json_body=body, action_name="mute_monitor",
        )

    async def _unmute_monitor(self, c: DatadogUnmuteMonitorConfig, api_key, app_key, site):
        return await _datadog_request(
            api_key, app_key, site, "POST", f"/api/v1/monitor/{c.monitor_id}/unmute",
            json_body={"scope": c.scope}, action_name="unmute_monitor",
        )

    async def _search_monitors(self, c: DatadogSearchMonitorsConfig, api_key, app_key, site):
        params = {"query": c.query, "page": c.page, "per_page": c.per_page}
        return await _datadog_request(
            api_key, app_key, site, "GET", "/api/v1/monitor/search", params=params,
            action_name="search_monitors",
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    async def _post_event(self, c: DatadogPostEventConfig, api_key, app_key, site):
        # Use the v1 endpoint — broadly available on all plans and account types.
        # The v2 POST /api/v2/events requires the events_write scope which is not
        # granted on all trial/free accounts. v1 read endpoints remain on v2.
        body: Dict[str, Any] = {
            "title": c.title,
            "text": c.text,
            "alert_type": c.alert_type,
            "priority": c.priority,
        }
        tags = _comma_list(c.tags)
        if tags:
            body["tags"] = tags
        if c.host:
            body["host"] = c.host
        if c.aggregation_key:
            body["aggregation_key"] = c.aggregation_key
        return await _datadog_request(
            api_key, app_key, site, "POST", "/api/v1/events", json_body=body,
            action_name="post_event",
        )

    async def _get_event(self, c: DatadogGetEventConfig, api_key, app_key, site):
        # v1 integer event IDs (returned by post_event) are not in the v2 UUID namespace;
        # use the v1 endpoint so get_event composes correctly with post_event output.
        return await _datadog_request(
            api_key, app_key, site, "GET", f"/api/v1/events/{c.event_id}",
            action_name="get_event",
        )

    async def _list_events(self, c: DatadogListEventsConfig, api_key, app_key, site):
        params = {
            "filter[from]": c.filter_from,
            "filter[to]": c.filter_to,
            "filter[query]": c.filter_query,
            "page[limit]": c.page_limit,
        }
        return await _datadog_request(
            api_key, app_key, site, "GET", "/api/v2/events", params=params,
            action_name="list_events",
        )

    async def _search_events(self, c: DatadogSearchEventsConfig, api_key, app_key, site):
        body = {
            "filter": {"query": c.query, "from": c.filter_from, "to": c.filter_to},
            "page": {"limit": int(c.page_limit) if c.page_limit and str(c.page_limit).isdigit() else 20},
        }
        return await _datadog_request(
            api_key, app_key, site, "POST", "/api/v2/events/search", json_body=body,
            action_name="search_events",
        )

    async def _poll_new_events(self, c: DatadogOnNewEventConfig, api_key, app_key, site):
        """Poll the Events API v2 for events matching a query newly posted.

        Events are returned newest-first; we cursor on the most-recently-seen
        event id (persisted in durable node state) and emit only events that
        appear after it. The first poll baselines (records the cursor, emits
        nothing) so the trigger only fires for events posted afterwards.

        We also persist last_seen_ts_ms (epoch ms of the newest seen event) and use
        it as filter[from] on subsequent polls so the cursor event is always within
        the query window — even after a gap longer than 1 hour.
        """
        # Read the persisted cursor to size the query window (filter[from]).
        # The authoritative dedup re-reads state under CAS inside the mutator
        # below, so a slightly stale window here is harmless — it only widens.
        state = await self._load_node_state()
        last_seen_ts_ms: Optional[int] = state.get("last_seen_ts_ms")

        # Use the stored timestamp as filter[from] so the window always contains
        # the cursor event regardless of how long ago the last poll ran.
        # Cap at 24 h to avoid fetching very old event history after a long pause.
        # Events v2 filter[from] requires ISO 8601 — epoch-ms integers are rejected.
        if last_seen_ts_ms is not None:
            cap_ms = int((time.time() - 86400) * 1000)
            ts_ms = max(last_seen_ts_ms, cap_ms)
            filter_from: str = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S+00:00"
            )
        else:
            filter_from = "now-1h"

        params = {
            "filter[query]": c.query or None,
            "filter[from]": filter_from,
            "filter[to]": "now",
            "page[limit]": c.max_results,
            "sort": "-timestamp",
        }
        result = await _datadog_request(
            api_key, app_key, site, "GET", "/api/v2/events", params=params,
            action_name="on_new_event",
        )
        if result.get("status") != "success":
            return result

        data = result.get("data") or {}
        events = data.get("data") if isinstance(data, dict) else []
        if not isinstance(events, list):
            events = []

        newest_id = events[0].get("id") if events and isinstance(events[0], dict) else None

        # Extract the timestamp of the newest event and convert to epoch ms.
        # Events v2 attributes.timestamp is an ISO 8601 string; fall back to
        # treating it as a numeric epoch-seconds value for older/custom sources.
        def _event_ts_ms(event: Dict[str, Any]) -> Optional[int]:
            ts = event.get("attributes", {}).get("timestamp")
            if ts is None:
                return None
            try:
                # Primary: ISO 8601 string (Events v2 format)
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                return int(dt.timestamp() * 1000)
            except (TypeError, ValueError):
                pass
            try:
                # Fallback: numeric epoch seconds
                return int(float(ts) * 1000)
            except (TypeError, ValueError):
                pass
            return None

        newest_ts_ms = _event_ts_ms(events[0]) if events and isinstance(events[0], dict) else None
        # Fallback timestamp captured once (before the mutator) so the cursor
        # write is deterministic across CAS retries.
        cursor_ts_ms = newest_ts_ms or int(time.time() * 1000)
        timing = result.get("timing_ms", {})

        # Pure read-modify-write of the dedup cursor: no network / side effects,
        # so _update_node_state may re-run it on CAS contention. Returns
        # (new_state|None, output); None persists nothing (cursor unchanged).
        def mutator(state: Dict[str, Any]):
            # Cursor: prefer durable node state, falling back to the config field.
            last_seen_id = state.get("last_seen_id", c.last_seen_id)
            # Distinguishes "never ran" from "ran but found no events yet".
            baselined: bool = state.get("baselined", False)

            # First poll → baseline only: record the cursor, emit nothing.
            # Always persist state (even when no events found) so the next poll
            # knows the baseline ran and emits any events it finds as real triggers.
            if last_seen_id is None and not baselined:
                new_state = {
                    "last_seen_id": newest_id,
                    "last_seen_ts_ms": cursor_ts_ms,
                    "baselined": True,
                }
                return new_state, {
                    "status": "success",
                    "operation": "on_new_event",
                    "events": [],
                    "new_count": 0,
                    "query": c.query,
                    "last_seen_id": newest_id,
                    "timing_ms": timing,
                }

            # Emit events newer than the cursor.
            # If baseline ran but found no events (last_seen_id is None), all
            # events in this poll are new — emit them all.
            new_events = []
            if last_seen_id is None:
                new_events = [e for e in events if isinstance(e, dict)]
            else:
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    if event.get("id") == last_seen_id:
                        break
                    new_events.append(event)

            output = {
                "status": "success",
                "operation": "on_new_event",
                "events": new_events,
                "new_count": len(new_events),
                "query": c.query,
                "last_seen_id": newest_id or last_seen_id,
                "timing_ms": timing,
            }

            if newest_id is not None and newest_id != last_seen_id:
                new_state = {
                    "last_seen_id": newest_id,
                    "last_seen_ts_ms": cursor_ts_ms,
                    "baselined": True,
                }
                return new_state, output
            return None, output  # cursor unchanged → nothing to persist

        # skip_result: a transient state I/O failure or CAS exhaustion skips this
        # tick cleanly (state untouched, no emit, run neither fails nor alerts).
        return await self._update_node_state(
            mutator,
            skip_result={
                "status": "success",
                "operation": "on_new_event",
                "events": [],
                "new_count": 0,
                "query": c.query,
                "last_seen_id": None,
                "timing_ms": timing,
            },
        )

    # ------------------------------------------------------------------
    # Metric handlers
    # ------------------------------------------------------------------
    async def _submit_metrics(self, c: DatadogSubmitMetricsConfig, api_key, app_key, site):
        if c.timestamp:
            try:
                ts = int(float(c.timestamp))
            except (ValueError, TypeError):
                raise ValueError(f"Invalid timestamp: {c.timestamp!r}. Provide a POSIX timestamp (e.g. 1750000000).")
        else:
            ts = int(time.time())
        type_map = {"count": 1, "rate": 2, "gauge": 3}
        point = {"timestamp": ts, "value": float(c.value)}
        series_item: Dict[str, Any] = {
            "metric": c.metric,
            "type": type_map.get(c.metric_type, 3),
            "points": [point],
        }
        tags = _comma_list(c.tags)
        if tags:
            series_item["tags"] = tags
        body = {"series": [series_item]}
        return await _datadog_request(
            api_key, app_key, site, "POST", "/api/v2/series", json_body=body,
            action_name="submit_metrics",
        )

    async def _query_timeseries(self, c: DatadogQueryTimeseriesConfig, api_key, app_key, site):
        try:
            from_ms = int(c.from_ms)
            to_ms = int(c.to_ms)
        except (ValueError, TypeError):
            raise ValueError(
                f"'From (ms)' and 'To (ms)' must be epoch millisecond integers, "
                f"got from={c.from_ms!r}, to={c.to_ms!r}."
            )
        body = {
            "data": {
                "type": "timeseries_request",
                "attributes": {
                    "from": from_ms,
                    "to": to_ms,
                    "queries": [
                        {
                            "name": "a",
                            "data_source": "metrics",
                            "query": c.query,
                        }
                    ],
                    "formulas": [{"formula": "a"}],
                },
            }
        }
        return await _datadog_request(
            api_key, app_key, site, "POST", "/api/v2/query/timeseries", json_body=body,
            action_name="query_timeseries",
        )

    async def _query_metrics(self, c: DatadogQueryMetricsConfig, api_key, app_key, site):
        params = {"query": c.query, "from": c.from_ts, "to": c.to_ts}
        return await _datadog_request(
            api_key, app_key, site, "GET", "/api/v1/query", params=params,
            action_name="query_metrics",
        )

    async def _list_metrics(self, c: DatadogListMetricsConfig, api_key, app_key, site):
        params = {"from": c.from_ts, "host": c.host}
        return await _datadog_request(
            api_key, app_key, site, "GET", "/api/v1/metrics", params=params,
            action_name="list_metrics",
        )

    async def _get_metric_metadata(self, c: DatadogGetMetricMetadataConfig, api_key, app_key, site):
        return await _datadog_request(
            api_key, app_key, site, "GET", f"/api/v1/metrics/{c.metric_name}",
            action_name="get_metric_metadata",
        )

    # ------------------------------------------------------------------
    # Log handlers
    # ------------------------------------------------------------------
    async def _send_logs(self, c: DatadogSendLogsConfig, api_key, app_key, site):
        entry: Dict[str, Any] = {"message": c.message}
        if c.ddsource:
            entry["ddsource"] = c.ddsource
        if c.service:
            entry["service"] = c.service
        if c.ddtags:
            entry["ddtags"] = ",".join(_comma_list(c.ddtags) or [])
        if c.hostname:
            entry["hostname"] = c.hostname
        return await self._send_logs_request(api_key, site, [entry])

    async def _send_logs_request(self, api_key, site, entries: List[Dict[str, Any]]):
        # Logs use a separate intake hostname (http-intake.logs.*), not api.*
        intake_base = DATADOG_LOG_INTAKE.get(site or DEFAULT_SITE, DATADOG_LOG_INTAKE[DEFAULT_SITE])
        url = f"{intake_base}/api/v2/logs"
        headers = {"DD-API-KEY": api_key, "Content-Type": "application/json"}
        start = time.time()
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(
                    method="POST", url=url, headers=headers, json=entries
                )
                api_ms = round((time.time() - start) * 1000, 2)
                if response.status_code >= 400:
                    try:
                        err = response.json()
                        message = err.get("errors") or err.get("message") or str(err)
                    except Exception:
                        message = response.text
                    if isinstance(message, (list, dict)):
                        message = str(message)
                    message = message.encode("ascii", errors="replace").decode("ascii")
                    logger.error(f"[DatadogNode] API error (send_logs): {message}")
                    return {
                        "status": "error",
                        "action": "send_logs",
                        "error": message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": api_ms},
                    }
                try:
                    data = response.json() if response.text else {"success": True}
                except Exception:
                    data = {"success": True}
                return {
                    "status": "success",
                    "action": "send_logs",
                    "data": data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": "send_logs",
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
                }
            except Exception as e:
                msg = str(e).encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[DatadogNode] Request failed (send_logs): {msg}")
                return {
                    "status": "error",
                    "action": "send_logs",
                    "error": msg,
                    "status_code": 500,
                    "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
                }

    async def _search_logs(self, c: DatadogSearchLogsConfig, api_key, app_key, site):
        body = {
            "filter": {"query": c.query, "from": c.filter_from, "to": c.filter_to},
            "page": {"limit": int(c.page_limit) if c.page_limit and str(c.page_limit).isdigit() else 25},
        }
        return await _datadog_request(
            api_key, app_key, site, "POST", "/api/v2/logs/events/search", json_body=body,
            action_name="search_logs",
        )

    async def _aggregate_logs(self, c: DatadogAggregateLogsConfig, api_key, app_key, site):
        compute = _parse_json_field(c.compute_json, "Compute (JSON)") or [{"aggregation": "count"}]
        body: Dict[str, Any] = {
            "filter": {"query": c.query, "from": c.filter_from, "to": c.filter_to},
            "compute": compute,
        }
        group_by = _comma_list(c.group_by)
        if group_by:
            body["group_by"] = [{"facet": f} for f in group_by]
        return await _datadog_request(
            api_key, app_key, site, "POST", "/api/v2/logs/analytics/aggregate", json_body=body,
            action_name="aggregate_logs",
        )

    # ------------------------------------------------------------------
    # Dashboard handlers
    # ------------------------------------------------------------------
    async def _create_dashboard(self, c: DatadogCreateDashboardConfig, api_key, app_key, site):
        body = {
            "title": c.title,
            "layout_type": c.layout_type,
            "widgets": _parse_json_field(c.widgets_json, "Widgets (JSON)") or [],
            "description": c.description,
        }
        return await _datadog_request(
            api_key, app_key, site, "POST", "/api/v1/dashboard", json_body=body,
            action_name="create_dashboard",
        )

    async def _get_dashboard(self, c: DatadogGetDashboardConfig, api_key, app_key, site):
        return await _datadog_request(
            api_key, app_key, site, "GET", f"/api/v1/dashboard/{c.dashboard_id}",
            action_name="get_dashboard",
        )

    async def _list_dashboards(self, c: DatadogListDashboardsConfig, api_key, app_key, site):
        params = {"filter[shared]": c.filter_shared or None}
        return await _datadog_request(
            api_key, app_key, site, "GET", "/api/v1/dashboard", params=params,
            action_name="list_dashboards",
        )

    async def _update_dashboard(self, c: DatadogUpdateDashboardConfig, api_key, app_key, site):
        # Dashboard PUT is a full replace — must always include widgets.
        # When widgets_json is blank, fetch existing widgets rather than sending []
        # (which would silently delete every widget on the dashboard).
        if c.widgets_json is not None:
            widgets = _parse_json_field(c.widgets_json, "Widgets (JSON)") or []
        else:
            get_result = await _datadog_request(
                api_key, app_key, site, "GET", f"/api/v1/dashboard/{c.dashboard_id}",
                action_name="get_dashboard",
            )
            if get_result.get("status") != "success":
                return get_result
            widgets = (get_result.get("data") or {}).get("widgets", [])
        body = {
            "title": c.title,
            "layout_type": c.layout_type,
            "widgets": widgets,
        }
        return await _datadog_request(
            api_key, app_key, site, "PUT", f"/api/v1/dashboard/{c.dashboard_id}", json_body=body,
            action_name="update_dashboard",
        )

    async def _delete_dashboard(self, c: DatadogDeleteDashboardConfig, api_key, app_key, site):
        return await _datadog_request(
            api_key, app_key, site, "DELETE", f"/api/v1/dashboard/{c.dashboard_id}",
            action_name="delete_dashboard",
        )

    # ------------------------------------------------------------------
    # Incident handlers
    # ------------------------------------------------------------------
    async def _create_incident(self, c: DatadogCreateIncidentConfig, api_key, app_key, site):
        body = {
            "data": {
                "type": "incidents",
                "attributes": {
                    "title": c.title,
                    "customer_impacted": c.customer_impacted == "true",
                },
            }
        }
        return await _datadog_request(
            api_key, app_key, site, "POST", "/api/v2/incidents", json_body=body,
            action_name="create_incident",
        )

    async def _list_incidents(self, c: DatadogListIncidentsConfig, api_key, app_key, site):
        params = {"page[size]": c.page_size, "page[offset]": c.page_offset}
        return await _datadog_request(
            api_key, app_key, site, "GET", "/api/v2/incidents", params=params,
            action_name="list_incidents",
        )

    async def _update_incident(self, c: DatadogUpdateIncidentConfig, api_key, app_key, site):
        attributes: Dict[str, Any] = {}
        if c.title:
            attributes["title"] = c.title
        if c.state:
            attributes["state"] = c.state
        body = {
            "data": {
                "type": "incidents",
                "id": c.incident_id,
                "attributes": attributes,
            }
        }
        return await _datadog_request(
            api_key, app_key, site, "PATCH", f"/api/v2/incidents/{c.incident_id}", json_body=body,
            action_name="update_incident",
        )

    # ------------------------------------------------------------------
    # Downtime handlers
    # ------------------------------------------------------------------
    async def _create_downtime(self, c: DatadogCreateDowntimeConfig, api_key, app_key, site):
        # Uses v1 downtime API — simpler and broadly available on all account types.
        # v2 requires a 'monitor_identifier' union type that is not supported on trial accounts.
        scope_list = [s.strip() for s in c.scope.split(",") if s.strip()] or ["*"]
        body: Dict[str, Any] = {"scope": scope_list}
        if c.monitor_id:
            try:
                body["monitor_id"] = int(c.monitor_id)
            except (ValueError, TypeError):
                raise ValueError(f"Monitor ID must be a number, got: {c.monitor_id!r}")
        elif c.monitor_tags:
            tags = _comma_list(c.monitor_tags)
            if tags:
                body["monitor_tags"] = tags
        if c.message:
            body["message"] = c.message
        if c.start:
            try:
                body["start"] = int(float(c.start))
            except (ValueError, TypeError):
                raise ValueError(f"Start must be a POSIX timestamp, got: {c.start!r}")
        if c.end:
            try:
                body["end"] = int(float(c.end))
            except (ValueError, TypeError):
                raise ValueError(f"End must be a POSIX timestamp, got: {c.end!r}")
        return await _datadog_request(
            api_key, app_key, site, "POST", "/api/v1/downtime", json_body=body,
            action_name="create_downtime",
        )

    async def _cancel_downtime(self, c: DatadogCancelDowntimeConfig, api_key, app_key, site):
        return await _datadog_request(
            api_key, app_key, site, "DELETE", f"/api/v1/downtime/{c.downtime_id}",
            action_name="cancel_downtime",
        )

    async def _list_downtimes(self, c: DatadogListDowntimesConfig, api_key, app_key, site):
        params: Dict[str, Any] = {}
        if c.current_only and c.current_only in ("true", "false"):
            params["current_only"] = c.current_only
        return await _datadog_request(
            api_key, app_key, site, "GET", "/api/v1/downtime", params=params or None,
            action_name="list_downtimes",
        )

    async def _get_downtime(self, c: DatadogGetDowntimeConfig, api_key, app_key, site):
        return await _datadog_request(
            api_key, app_key, site, "GET", f"/api/v1/downtime/{c.downtime_id}",
            action_name="get_downtime",
        )

    async def _update_downtime(self, c: DatadogUpdateDowntimeConfig, api_key, app_key, site):
        body: Dict[str, Any] = {}
        if c.scope:
            body["scope"] = [s.strip() for s in c.scope.split(",") if s.strip()]
        if c.message:
            body["message"] = c.message
        if c.end:
            try:
                body["end"] = int(float(c.end))
            except (ValueError, TypeError):
                raise ValueError(f"End must be a POSIX timestamp, got: {c.end!r}")
        return await _datadog_request(
            api_key, app_key, site, "PUT", f"/api/v1/downtime/{c.downtime_id}",
            json_body=body, action_name="update_downtime",
        )

    # ------------------------------------------------------------------
    # SLO handlers
    # ------------------------------------------------------------------
    async def _create_slo(self, c: DatadogCreateSLOConfig, api_key, app_key, site):
        try:
            target_val = float(c.target)
        except (ValueError, TypeError):
            raise ValueError(f"Target must be a number (e.g. 99.9), got: {c.target!r}")
        body: Dict[str, Any] = {
            "name": c.name,
            "type": c.type,
            "description": c.description,
            "tags": _comma_list(c.tags),
            "thresholds": [{"target": target_val, "timeframe": c.timeframe}],
        }
        if c.type == "metric":
            if not c.query_numerator or not c.query_denominator:
                raise ValueError("Metric SLOs require both 'Numerator Query' and 'Denominator Query'.")
            body["query"] = {"numerator": c.query_numerator, "denominator": c.query_denominator}
        else:
            ids = [int(i.strip()) for i in c.monitor_ids.split(",") if i.strip().isdigit()] if c.monitor_ids else []
            if not ids:
                raise ValueError("Monitor SLOs require at least one Monitor ID.")
            body["monitor_ids"] = ids
        return await _datadog_request(
            api_key, app_key, site, "POST", "/api/v1/slo", json_body=body, action_name="create_slo",
        )

    async def _get_slo(self, c: DatadogGetSLOConfig, api_key, app_key, site):
        return await _datadog_request(
            api_key, app_key, site, "GET", f"/api/v1/slo/{c.slo_id}", action_name="get_slo",
        )

    async def _list_slos(self, c: DatadogListSLOsConfig, api_key, app_key, site):
        params: Dict[str, Any] = {}
        if c.tags_query:
            params["tags_query"] = c.tags_query
        if c.limit:
            params["limit"] = c.limit
        if c.offset:
            params["offset"] = c.offset
        return await _datadog_request(
            api_key, app_key, site, "GET", "/api/v1/slo", params=params or None, action_name="list_slos",
        )

    async def _update_slo(self, c: DatadogUpdateSLOConfig, api_key, app_key, site):
        # PUT requires the full SLO body; fetch first, then merge changes.
        get_result = await _datadog_request(
            api_key, app_key, site, "GET", f"/api/v1/slo/{c.slo_id}", action_name="get_slo",
        )
        if get_result.get("status") != "success":
            return get_result
        existing = (get_result.get("data") or {}).get("data", {})
        body: Dict[str, Any] = {
            "name": c.name or existing.get("name"),
            "type": existing.get("type"),
            "thresholds": existing.get("thresholds", []),
            "description": c.description if c.description is not None else existing.get("description"),
            "tags": _comma_list(c.tags) if c.tags is not None else existing.get("tags"),
        }
        if c.target:
            try:
                target_val = float(c.target)
                body["thresholds"] = [{"target": target_val, "timeframe": t.get("timeframe", "7d")} for t in body["thresholds"]]
            except (ValueError, TypeError):
                raise ValueError(f"Target must be a number (e.g. 99.9), got: {c.target!r}")
        # Carry over type-specific fields from existing
        if existing.get("query"):
            body["query"] = existing["query"]
        elif existing.get("monitor_ids"):
            body["monitor_ids"] = existing["monitor_ids"]
        return await _datadog_request(
            api_key, app_key, site, "PUT", f"/api/v1/slo/{c.slo_id}", json_body=body, action_name="update_slo",
        )

    async def _delete_slo(self, c: DatadogDeleteSLOConfig, api_key, app_key, site):
        return await _datadog_request(
            api_key, app_key, site, "DELETE", f"/api/v1/slo/{c.slo_id}", action_name="delete_slo",
        )

    async def _get_slo_history(self, c: DatadogGetSLOHistoryConfig, api_key, app_key, site):
        try:
            from_ts = int(float(c.from_ts))
            to_ts = int(float(c.to_ts))
        except (ValueError, TypeError):
            raise ValueError(f"'From' and 'To' must be POSIX timestamps, got from={c.from_ts!r}, to={c.to_ts!r}.")
        params = {"from_ts": from_ts, "to_ts": to_ts}
        return await _datadog_request(
            api_key, app_key, site, "GET", f"/api/v1/slo/{c.slo_id}/history", params=params,
            action_name="get_slo_history",
        )

    # ------------------------------------------------------------------
    # Host handlers
    # ------------------------------------------------------------------
    async def _list_hosts(self, c: DatadogListHostsConfig, api_key, app_key, site):
        params: Dict[str, Any] = {}
        if c.filter:
            params["filter"] = c.filter
        if c.count:
            params["count"] = c.count
        if c.start:
            params["start"] = c.start
        if c.from_ts:
            try:
                params["from"] = int(float(c.from_ts))
            except (ValueError, TypeError):
                raise ValueError(f"'From' must be a POSIX timestamp, got: {c.from_ts!r}")
        return await _datadog_request(
            api_key, app_key, site, "GET", "/api/v1/hosts", params=params or None, action_name="list_hosts",
        )

    async def _get_host_totals(self, c: DatadogGetHostTotalsConfig, api_key, app_key, site):
        params: Dict[str, Any] = {}
        if c.from_ts:
            try:
                params["from"] = int(float(c.from_ts))
            except (ValueError, TypeError):
                raise ValueError(f"'From' must be a POSIX timestamp, got: {c.from_ts!r}")
        return await _datadog_request(
            api_key, app_key, site, "GET", "/api/v1/hosts/totals", params=params or None,
            action_name="get_host_totals",
        )

    async def _mute_host(self, c: DatadogMuteHostConfig, api_key, app_key, site):
        body: Dict[str, Any] = {}
        if c.message:
            body["message"] = c.message
        if c.end:
            try:
                body["end"] = int(float(c.end))
            except (ValueError, TypeError):
                raise ValueError(f"'End' must be a POSIX timestamp, got: {c.end!r}")
        body["override"] = c.override == "true"
        return await _datadog_request(
            api_key, app_key, site, "POST", f"/api/v1/host/{c.host_name}/mute",
            json_body=body, action_name="mute_host",
        )

    async def _unmute_host(self, c: DatadogUnmuteHostConfig, api_key, app_key, site):
        return await _datadog_request(
            api_key, app_key, site, "POST", f"/api/v1/host/{c.host_name}/unmute",
            json_body={}, action_name="unmute_host",
        )

    # ------------------------------------------------------------------
    # Tag handlers
    # ------------------------------------------------------------------
    async def _get_host_tags(self, c: DatadogGetHostTagsConfig, api_key, app_key, site):
        params = {"source": c.source} if c.source else None
        return await _datadog_request(
            api_key, app_key, site, "GET", f"/api/v1/tags/hosts/{c.host_name}",
            params=params, action_name="get_host_tags",
        )

    async def _add_host_tags(self, c: DatadogAddHostTagsConfig, api_key, app_key, site):
        tags = _comma_list(c.tags) or []
        body: Dict[str, Any] = {"tags": tags}
        params = {"source": c.source} if c.source else None
        return await _datadog_request(
            api_key, app_key, site, "POST", f"/api/v1/tags/hosts/{c.host_name}",
            json_body=body, params=params, action_name="add_host_tags",
        )

    async def _update_host_tags(self, c: DatadogUpdateHostTagsConfig, api_key, app_key, site):
        tags = _comma_list(c.tags) or []
        body: Dict[str, Any] = {"tags": tags}
        params = {"source": c.source} if c.source else None
        return await _datadog_request(
            api_key, app_key, site, "PUT", f"/api/v1/tags/hosts/{c.host_name}",
            json_body=body, params=params, action_name="update_host_tags",
        )

    async def _delete_host_tags(self, c: DatadogDeleteHostTagsConfig, api_key, app_key, site):
        params = {"source": c.source} if c.source else None
        return await _datadog_request(
            api_key, app_key, site, "DELETE", f"/api/v1/tags/hosts/{c.host_name}",
            params=params, action_name="delete_host_tags",
        )

    # ------------------------------------------------------------------
    # Service Check handler
    # ------------------------------------------------------------------
    async def _submit_service_check(self, c: DatadogSubmitServiceCheckConfig, api_key, app_key, site):
        entry: Dict[str, Any] = {
            "check": c.check,
            "host_name": c.host_name,
            "status": int(c.status),
        }
        if c.message:
            entry["message"] = c.message[:500]
        tags = _comma_list(c.tags)
        if tags:
            entry["tags"] = tags
        if c.timestamp:
            try:
                entry["timestamp"] = int(float(c.timestamp))
            except (ValueError, TypeError):
                raise ValueError(f"'Timestamp' must be a POSIX timestamp, got: {c.timestamp!r}")
        return await _datadog_request(
            api_key, app_key, site, "POST", "/api/v1/check_run",
            json_body=[entry], action_name="submit_service_check",
        )

    # ------------------------------------------------------------------
    # Synthetics handlers
    # ------------------------------------------------------------------
    async def _list_synthetics(self, c: DatadogListSyntheticsConfig, api_key, app_key, site):
        params: Dict[str, Any] = {}
        if c.location_names:
            params["location_names"] = c.location_names
        return await _datadog_request(
            api_key, app_key, site, "GET", "/api/v1/synthetics/tests", params=params or None,
            action_name="list_synthetics",
        )

    async def _get_synthetics(self, c: DatadogGetSyntheticsConfig, api_key, app_key, site):
        return await _datadog_request(
            api_key, app_key, site, "GET", f"/api/v1/synthetics/tests/{c.public_id}",
            action_name="get_synthetics",
        )

    async def _trigger_synthetics(self, c: DatadogTriggerSyntheticsConfig, api_key, app_key, site):
        ids = [i.strip() for i in c.public_ids.split(",") if i.strip()]
        if not ids:
            raise ValueError("At least one test public ID is required.")
        body = {"tests": [{"public_id": pid} for pid in ids]}
        return await _datadog_request(
            api_key, app_key, site, "POST", "/api/v1/synthetics/tests/trigger",
            json_body=body, action_name="trigger_synthetics",
        )

    async def _pause_synthetics(self, c: DatadogPauseSyntheticsConfig, api_key, app_key, site):
        body = {"new_status": c.new_status}
        return await _datadog_request(
            api_key, app_key, site, "PUT", f"/api/v1/synthetics/tests/{c.public_id}/status",
            json_body=body, action_name="pause_synthetics",
        )
