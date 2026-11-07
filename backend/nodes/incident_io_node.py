"""
Incident.io incident management & on-call automation node.

Provides workflow integration with the incident.io REST API for operations
including:
- Incidents: list, get, create, edit; list incident updates
- Actions & follow-ups: list/get actions, list/get follow-ups
- Alerts: list, get, resolve, create alert event (HTTP source)
- Configuration: list severities, incident roles, custom fields
- Users: list, get
- On-call: list schedules, list schedule entries, create schedule override,
  list/create escalations
- Catalog (CMDB): list types, list/create/update entries
- Status pages: list/create status page incidents
- Workflows: list
- Webhook Trigger: receive incident/action/follow-up events

Authentication: API key (Bearer token). incident.io does NOT expose a public
OAuth 2.0 flow, so this is an API-key integration only.

API Base URL: https://api.incident.io  (resources are versioned per path:
/v1, /v2, /v3 — there is no single global version prefix).
Documentation: https://docs.incident.io/api-reference
"""

import base64
import binascii
import logging
import re
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import filter_options_by_search, load_paginated_options, require_credential_token
from utils.webhook_signatures import verify_svix

logger = logging.getLogger(__name__)

INCIDENT_IO_API_BASE = "https://api.incident.io"

# Webhook event types incident.io can deliver (configured in Settings ->
# Webhooks). The dashboard delivers ALL subscribed events to one URL with no
# per-NoClick-node filter, so the node filters by these at runtime against the
# inbound payload's `event_type` field. "*" means "fire on any event".
INCIDENT_IO_WEBHOOK_EVENTS = [
    "*",
    "public_incident.incident_created_v2",
    "public_incident.incident_updated_v2",
    "public_incident.incident_status_updated_v2",
    "public_incident.action_created_v1",
    "public_incident.action_updated_v1",
    "public_incident.follow_up_created_v1",
    "public_incident.follow_up_updated_v1",
    "public_incident.incident_membership_granted_v1",
    "public_incident.incident_membership_revoked_v1",
    "private_incident.incident_created_v2",
    "private_incident.incident_updated_v2",
    "private_incident.incident_status_updated_v2",
]
INCIDENT_IO_WEBHOOK_EVENT_NAMES = [
    "All events",
    "Incident created",
    "Incident updated",
    "Incident status updated",
    "Action created",
    "Action updated",
    "Follow-up created",
    "Follow-up updated",
    "Incident membership granted",
    "Incident membership revoked",
    "Private incident created",
    "Private incident updated",
    "Private incident status updated",
]


# ============================================================================
# Credential Schema
# ============================================================================


class IncidentIoApiKeyCredential(BaseModel):
    """API Key credential for incident.io."""

    credential_type: Literal["incident_io_api_key"] = Field(
        "incident_io_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your incident.io API key from Settings -> API keys. Passed as a Bearer token.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        title="incident.io API Key",
        json_schema_extra={
            "x-credential-url": "https://app.incident.io/~/settings/api-keys"
        }
    )


IncidentIoCredential = IncidentIoApiKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class IncidentIoListIncidentsConfig(BaseModel):
    """List incidents with optional status / severity filters and pagination."""

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
    status: Optional[str] = Field(
        None,
        title="Status (one of)",
        description="Filter to incidents whose status ID is one of these (comma-separated IDs)",
    )
    severity: Optional[str] = Field(
        None,
        title="Severity (one of)",
        description="Filter to incidents whose severity ID is one of these (comma-separated IDs)",
    )
    page_size: Optional[str] = Field(
        "25", title="Page Size", description="Max number of incidents to return (1-250)"
    )
    after: Optional[str] = Field(
        None, title="After (cursor)", description="Cursor: ID of the last record from the previous page"
    )
    # The credential collector reuses the standard options dispatcher for an
    # any-key identity proof. This field never appears in the node editor.
    identity_probe: Optional[str] = Field(
        None,
        json_schema_extra={
            "ui:hidden": True,
            "x-dynamic-options": {"field_name": "identity_probe"},
        },
    )


class IncidentIoGetIncidentConfig(BaseModel):
    """Retrieve a single incident by ID."""

    operation: Literal["get_incident"] = Field(
        "get_incident",
        json_schema_extra={
            "const": "get_incident",
            "ui:hidden": True,
            "x-category": "Incidents",
            "x-is-trigger": False,
            "x-display-name": "Get Incident",
        },
        title="Get Incident",
    )
    incident_id: str = Field(
        ..., title="Incident ID", description="The ID of the incident to retrieve"
    )


class IncidentIoCreateIncidentConfig(BaseModel):
    """Create a new incident."""

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
    name: str = Field(..., title="Name", description="Human-readable name for the incident")
    summary: Optional[str] = Field(
        None,
        title="Summary",
        description="A short description of the incident",
        json_schema_extra={"ui:widget": "textarea"},
    )
    severity_id: Optional[str] = Field(
        None,
        title="Severity",
        description="Severity to assign to the incident",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "severity_id",
                "placeholder": "Select a severity...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a severity ID",
            }
        },
    )
    incident_type_id: Optional[str] = Field(
        None, title="Incident Type ID", description="Incident type to assign (optional)"
    )
    mode: str = Field(
        "standard",
        title="Mode",
        description="Incident mode",
        json_schema_extra={
            "enum": ["standard", "retrospective", "test", "tutorial"],
            "enumNames": ["Standard", "Retrospective", "Test", "Tutorial"],
            "x-enum-searchable": True,
        },
    )
    visibility: str = Field(
        "public",
        title="Visibility",
        description="Whether the incident is public or private",
        json_schema_extra={
            "enum": ["public", "private"],
            "enumNames": ["Public", "Private"],
            "x-enum-searchable": True,
        },
    )
    idempotency_key: Optional[str] = Field(
        None,
        title="Idempotency Key",
        description="Unique key to avoid creating duplicate incidents on retries",
    )


class IncidentIoEditIncidentConfig(BaseModel):
    """Edit an existing incident's fields (POST .../actions/edit)."""

    operation: Literal["edit_incident"] = Field(
        "edit_incident",
        json_schema_extra={
            "const": "edit_incident",
            "ui:hidden": True,
            "x-category": "Incidents",
            "x-is-trigger": False,
            "x-display-name": "Edit Incident",
        },
        title="Edit Incident",
    )
    incident_id: str = Field(
        ..., title="Incident ID", description="The ID of the incident to edit"
    )
    name: Optional[str] = Field(None, title="Name", description="New incident name")
    summary: Optional[str] = Field(
        None,
        title="Summary",
        description="New incident summary",
        json_schema_extra={"ui:widget": "textarea"},
    )
    severity_id: Optional[str] = Field(
        None,
        title="Severity",
        description="New severity to assign",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "severity_id",
                "placeholder": "Select a severity...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a severity ID",
            }
        },
    )

    notify_incident_channel: bool = Field(
        False,
        title="Notify Incident Channel",
        description="Send Slack channel notifications about this edit",
    )


class IncidentIoListIncidentUpdatesConfig(BaseModel):
    """List the timeline of status/severity updates posted to incidents."""

    operation: Literal["list_incident_updates"] = Field(
        "list_incident_updates",
        json_schema_extra={
            "const": "list_incident_updates",
            "ui:hidden": True,
            "x-category": "Incidents",
            "x-is-trigger": False,
            "x-display-name": "List Incident Updates",
        },
        title="List Incident Updates",
    )
    incident_id: Optional[str] = Field(
        None, title="Incident ID", description="Filter updates to a single incident (optional)"
    )
    page_size: Optional[str] = Field("25", title="Page Size", description="Max records to return")
    after: Optional[str] = Field(None, title="After (cursor)", description="Pagination cursor")


class IncidentIoListActionsConfig(BaseModel):
    """List actions (tasks) created on incidents."""

    operation: Literal["list_actions"] = Field(
        "list_actions",
        json_schema_extra={
            "const": "list_actions",
            "ui:hidden": True,
            "x-category": "Actions & Follow-ups",
            "x-is-trigger": False,
            "x-display-name": "List Actions",
        },
        title="List Actions",
    )
    incident_id: Optional[str] = Field(
        None, title="Incident ID", description="Filter actions to a single incident (optional)"
    )


class IncidentIoGetActionConfig(BaseModel):
    """Retrieve a single action by ID."""

    operation: Literal["get_action"] = Field(
        "get_action",
        json_schema_extra={
            "const": "get_action",
            "ui:hidden": True,
            "x-category": "Actions & Follow-ups",
            "x-is-trigger": False,
            "x-display-name": "Get Action",
        },
        title="Get Action",
    )
    action_id: str = Field(..., title="Action ID", description="The ID of the action to retrieve")


class IncidentIoListFollowUpsConfig(BaseModel):
    """List post-incident follow-ups."""

    operation: Literal["list_follow_ups"] = Field(
        "list_follow_ups",
        json_schema_extra={
            "const": "list_follow_ups",
            "ui:hidden": True,
            "x-category": "Actions & Follow-ups",
            "x-is-trigger": False,
            "x-display-name": "List Follow-ups",
        },
        title="List Follow-ups",
    )
    incident_id: Optional[str] = Field(
        None, title="Incident ID", description="Filter follow-ups to a single incident (optional)"
    )


class IncidentIoGetFollowUpConfig(BaseModel):
    """Retrieve a single follow-up by ID."""

    operation: Literal["get_follow_up"] = Field(
        "get_follow_up",
        json_schema_extra={
            "const": "get_follow_up",
            "ui:hidden": True,
            "x-category": "Actions & Follow-ups",
            "x-is-trigger": False,
            "x-display-name": "Get Follow-up",
        },
        title="Get Follow-up",
    )
    follow_up_id: str = Field(
        ..., title="Follow-up ID", description="The ID of the follow-up to retrieve"
    )


class IncidentIoListAlertsConfig(BaseModel):
    """List ingested alerts."""

    operation: Literal["list_alerts"] = Field(
        "list_alerts",
        json_schema_extra={
            "const": "list_alerts",
            "ui:hidden": True,
            "x-category": "Alerts",
            "x-is-trigger": False,
            "x-display-name": "List Alerts",
        },
        title="List Alerts",
    )
    page_size: Optional[str] = Field("25", title="Page Size", description="Max records to return")
    after: Optional[str] = Field(None, title="After (cursor)", description="Pagination cursor")


class IncidentIoGetAlertConfig(BaseModel):
    """Retrieve a single alert by ID."""

    operation: Literal["get_alert"] = Field(
        "get_alert",
        json_schema_extra={
            "const": "get_alert",
            "ui:hidden": True,
            "x-category": "Alerts",
            "x-is-trigger": False,
            "x-display-name": "Get Alert",
        },
        title="Get Alert",
    )
    alert_id: str = Field(..., title="Alert ID", description="The ID of the alert to retrieve")


class IncidentIoResolveAlertConfig(BaseModel):
    """Mark an alert as resolved."""

    operation: Literal["resolve_alert"] = Field(
        "resolve_alert",
        json_schema_extra={
            "const": "resolve_alert",
            "ui:hidden": True,
            "x-category": "Alerts",
            "x-is-trigger": False,
            "x-display-name": "Resolve Alert",
        },
        title="Resolve Alert",
    )
    alert_id: str = Field(..., title="Alert ID", description="The ID of the alert to resolve")


class IncidentIoCreateAlertEventConfig(BaseModel):
    """Ingest an external alert event into an HTTP alert source."""

    operation: Literal["create_alert_event"] = Field(
        "create_alert_event",
        json_schema_extra={
            "const": "create_alert_event",
            "ui:hidden": True,
            "x-category": "Alerts",
            "x-is-trigger": False,
            "x-display-name": "Create Alert Event",
        },
        title="Create Alert Event",
    )
    alert_source_config_id: str = Field(
        ...,
        title="Alert Source Config ID",
        description="The ID of the configured HTTP alert source to ingest into",
    )
    title: str = Field(..., title="Title", description="Title of the alert event")
    status: str = Field(
        "firing",
        title="Status",
        description="Whether the alert is firing or resolved",
        json_schema_extra={
            "enum": ["firing", "resolved"],
            "enumNames": ["Firing", "Resolved"],
            "x-enum-searchable": True,
        },
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Longer description of the alert event",
        json_schema_extra={"ui:widget": "textarea"},
    )
    deduplication_key: Optional[str] = Field(
        None,
        title="Deduplication Key",
        description="Key used to deduplicate this alert against existing alerts",
    )


class IncidentIoListSeveritiesConfig(BaseModel):
    """List configured incident severities."""

    operation: Literal["list_severities"] = Field(
        "list_severities",
        json_schema_extra={
            "const": "list_severities",
            "ui:hidden": True,
            "x-category": "Configuration",
            "x-is-trigger": False,
            "x-display-name": "List Severities",
        },
        title="List Severities",
    )


class IncidentIoListIncidentRolesConfig(BaseModel):
    """List incident roles (e.g. Incident Lead, Comms)."""

    operation: Literal["list_incident_roles"] = Field(
        "list_incident_roles",
        json_schema_extra={
            "const": "list_incident_roles",
            "ui:hidden": True,
            "x-category": "Configuration",
            "x-is-trigger": False,
            "x-display-name": "List Incident Roles",
        },
        title="List Incident Roles",
    )


class IncidentIoListCustomFieldsConfig(BaseModel):
    """List custom fields used to enrich incidents."""

    operation: Literal["list_custom_fields"] = Field(
        "list_custom_fields",
        json_schema_extra={
            "const": "list_custom_fields",
            "ui:hidden": True,
            "x-category": "Configuration",
            "x-is-trigger": False,
            "x-display-name": "List Custom Fields",
        },
        title="List Custom Fields",
    )


class IncidentIoListUsersConfig(BaseModel):
    """List users in the organization."""

    operation: Literal["list_users"] = Field(
        "list_users",
        json_schema_extra={
            "const": "list_users",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "List Users",
        },
        title="List Users",
    )
    page_size: Optional[str] = Field("25", title="Page Size", description="Max records to return")
    after: Optional[str] = Field(None, title="After (cursor)", description="Pagination cursor")


class IncidentIoGetUserConfig(BaseModel):
    """Retrieve a single user by ID."""

    operation: Literal["get_user"] = Field(
        "get_user",
        json_schema_extra={
            "const": "get_user",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Get User",
        },
        title="Get User",
    )
    user_id: str = Field(..., title="User ID", description="The ID of the user to retrieve")


class IncidentIoListSchedulesConfig(BaseModel):
    """List on-call schedules."""

    operation: Literal["list_schedules"] = Field(
        "list_schedules",
        json_schema_extra={
            "const": "list_schedules",
            "ui:hidden": True,
            "x-category": "On-call",
            "x-is-trigger": False,
            "x-display-name": "List Schedules",
        },
        title="List Schedules",
    )


class IncidentIoListScheduleEntriesConfig(BaseModel):
    """List schedule entries (who is on call) overlapping a time window."""

    operation: Literal["list_schedule_entries"] = Field(
        "list_schedule_entries",
        json_schema_extra={
            "const": "list_schedule_entries",
            "ui:hidden": True,
            "x-category": "On-call",
            "x-is-trigger": False,
            "x-display-name": "List Schedule Entries",
        },
        title="List Schedule Entries",
    )
    schedule_id: str = Field(
        ...,
        title="Schedule",
        description="The schedule whose entries to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "schedule_id",
                "placeholder": "Select a schedule...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a schedule ID",
            }
        },
    )
    entry_window_start: Optional[str] = Field(
        None, title="Window Start", description="ISO 8601 start of the window to query"
    )
    entry_window_end: Optional[str] = Field(
        None, title="Window End", description="ISO 8601 end of the window to query"
    )


class IncidentIoCreateScheduleOverrideConfig(BaseModel):
    """Override a schedule (cover a shift) for a user/time range."""

    operation: Literal["create_schedule_override"] = Field(
        "create_schedule_override",
        json_schema_extra={
            "const": "create_schedule_override",
            "ui:hidden": True,
            "x-category": "On-call",
            "x-is-trigger": False,
            "x-display-name": "Create Schedule Override",
        },
        title="Create Schedule Override",
    )
    schedule_id: str = Field(
        ...,
        title="Schedule",
        description="The schedule to override",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "schedule_id",
                "placeholder": "Select a schedule...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a schedule ID",
            }
        },
    )
    rotation_id: str = Field(
        ..., title="Rotation ID", description="The rotation within the schedule to override"
    )
    layer_id: str = Field(
        ..., title="Layer ID", description="The rotation layer to override"
    )
    user_id: str = Field(
        ..., title="User ID", description="The user who will cover the override"
    )
    start_at: str = Field(..., title="Start At", description="ISO 8601 start of the override")
    end_at: str = Field(..., title="End At", description="ISO 8601 end of the override")


class IncidentIoListEscalationsConfig(BaseModel):
    """List on-call escalations."""

    operation: Literal["list_escalations"] = Field(
        "list_escalations",
        json_schema_extra={
            "const": "list_escalations",
            "ui:hidden": True,
            "x-category": "On-call",
            "x-is-trigger": False,
            "x-display-name": "List Escalations",
        },
        title="List Escalations",
    )
    page_size: Optional[str] = Field("25", title="Page Size", description="Max records to return")
    after: Optional[str] = Field(None, title="After (cursor)", description="Pagination cursor")


class IncidentIoCreateEscalationConfig(BaseModel):
    """Page someone / trigger an escalation."""

    operation: Literal["create_escalation"] = Field(
        "create_escalation",
        json_schema_extra={
            "const": "create_escalation",
            "ui:hidden": True,
            "x-category": "On-call",
            "x-is-trigger": False,
            "x-display-name": "Create Escalation",
        },
        title="Create Escalation",
    )
    title: str = Field(..., title="Title", description="Title shown to the person being paged")
    escalation_path_id: Optional[str] = Field(
        None,
        title="Escalation Path ID",
        description="The escalation path to page (optional if targeting users directly)",
    )
    idempotency_key: Optional[str] = Field(
        None,
        title="Idempotency Key",
        description="Unique key to avoid creating duplicate escalations on retries",
    )


class IncidentIoListCatalogTypesConfig(BaseModel):
    """List catalog (CMDB) types, e.g. Service, Team."""

    operation: Literal["list_catalog_types"] = Field(
        "list_catalog_types",
        json_schema_extra={
            "const": "list_catalog_types",
            "ui:hidden": True,
            "x-category": "Catalog",
            "x-is-trigger": False,
            "x-display-name": "List Catalog Types",
        },
        title="List Catalog Types",
    )


class IncidentIoListCatalogEntriesConfig(BaseModel):
    """List entries within a catalog type."""

    operation: Literal["list_catalog_entries"] = Field(
        "list_catalog_entries",
        json_schema_extra={
            "const": "list_catalog_entries",
            "ui:hidden": True,
            "x-category": "Catalog",
            "x-is-trigger": False,
            "x-display-name": "List Catalog Entries",
        },
        title="List Catalog Entries",
    )
    catalog_type_id: str = Field(
        ...,
        title="Catalog Type",
        description="The catalog type whose entries to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "catalog_type_id",
                "placeholder": "Select a catalog type...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a catalog type ID",
            }
        },
    )
    page_size: Optional[str] = Field("25", title="Page Size", description="Max records to return")
    after: Optional[str] = Field(None, title="After (cursor)", description="Pagination cursor")


class IncidentIoCreateCatalogEntryConfig(BaseModel):
    """Create a new catalog entry."""

    operation: Literal["create_catalog_entry"] = Field(
        "create_catalog_entry",
        json_schema_extra={
            "const": "create_catalog_entry",
            "ui:hidden": True,
            "x-category": "Catalog",
            "x-is-trigger": False,
            "x-display-name": "Create Catalog Entry",
        },
        title="Create Catalog Entry",
    )
    catalog_type_id: str = Field(
        ...,
        title="Catalog Type",
        description="The catalog type to create the entry under",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "catalog_type_id",
                "placeholder": "Select a catalog type...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a catalog type ID",
            }
        },
    )
    name: str = Field(..., title="Name", description="Display name of the catalog entry")
    external_id: Optional[str] = Field(
        None, title="External ID", description="An external identifier for the entry (optional)"
    )
    aliases: Optional[str] = Field(
        None, title="Aliases", description="Comma-separated aliases for the entry"
    )

    attribute_values: Dict[str, Any] = Field(
        ...,
        title="Attribute Values",
        description="Map attribute IDs to value or array_value bindings. Send {} for no attribute values; updating replaces existing values.",
    )


class IncidentIoUpdateCatalogEntryConfig(BaseModel):
    """Update an existing catalog entry."""

    operation: Literal["update_catalog_entry"] = Field(
        "update_catalog_entry",
        json_schema_extra={
            "const": "update_catalog_entry",
            "ui:hidden": True,
            "x-category": "Catalog",
            "x-is-trigger": False,
            "x-display-name": "Update Catalog Entry",
        },
        title="Update Catalog Entry",
    )
    catalog_entry_id: str = Field(
        ..., title="Catalog Entry ID", description="The ID of the catalog entry to update"
    )
    name: str = Field(..., title="Name", description="New display name of the catalog entry")
    external_id: Optional[str] = Field(
        None, title="External ID", description="An external identifier for the entry (optional)"
    )
    aliases: Optional[str] = Field(
        None, title="Aliases", description="Comma-separated aliases for the entry"
    )

    attribute_values: Dict[str, Any] = Field(
        ...,
        title="Attribute Values",
        description="Map attribute IDs to value or array_value bindings. Send {} for no attribute values; updating replaces existing values.",
    )


class IncidentIoListStatusPageIncidentsConfig(BaseModel):
    """List incidents published on a public status page."""

    operation: Literal["list_status_page_incidents"] = Field(
        "list_status_page_incidents",
        json_schema_extra={
            "const": "list_status_page_incidents",
            "ui:hidden": True,
            "x-category": "Status Pages",
            "x-is-trigger": False,
            "x-display-name": "List Status Page Incidents",
        },
        title="List Status Page Incidents",
    )
    status_page_id: str = Field(
        ..., title="Status Page ID", description="The status page whose incidents to list"
    )
    page_size: Optional[str] = Field("25", title="Page Size", description="Max records to return")
    after: Optional[str] = Field(None, title="After (cursor)", description="Pagination cursor")


class IncidentIoCreateStatusPageIncidentConfig(BaseModel):
    """Publish an incident to a status page."""

    operation: Literal["create_status_page_incident"] = Field(
        "create_status_page_incident",
        json_schema_extra={
            "const": "create_status_page_incident",
            "ui:hidden": True,
            "x-category": "Status Pages",
            "x-is-trigger": False,
            "x-display-name": "Create Status Page Incident",
        },
        title="Create Status Page Incident",
    )
    status_page_id: str = Field(
        ..., title="Status Page ID", description="The status page to publish the incident to"
    )
    name: str = Field(..., title="Name", description="Title of the status page incident")
    message: str = Field(
        ...,
        title="Message",
        description="The initial update message shown on the status page",
        json_schema_extra={"ui:widget": "textarea"},
    )
    incident_status: Literal["investigating", "identified", "monitoring", "resolved"] = Field(
        "investigating", title="Incident Status", description="Current status of the status page incident"
    )
    notify_subscribers: bool = Field(
        False, title="Notify Subscribers", description="Notify status page subscribers about this incident"
    )
    idempotency_key: str = Field(
        ...,
        title="Idempotency Key",
        description="Unique key to avoid creating duplicate status-page incidents on retries",
    )


class IncidentIoListWorkflowsConfig(BaseModel):
    """List configured automation workflows."""

    operation: Literal["list_workflows"] = Field(
        "list_workflows",
        json_schema_extra={
            "const": "list_workflows",
            "ui:hidden": True,
            "x-category": "Workflows",
            "x-is-trigger": False,
            "x-display-name": "List Workflows",
        },
        title="List Workflows",
    )


# ============================================================================
# Webhook Trigger Config (receiver — incident.io webhooks are dashboard-only)
# ============================================================================


class IncidentIoReceiveWebhookConfig(BaseModel):
    """Receive webhook events from incident.io (incident/action/follow-up events)."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_webhook_event"] = Field(
        "on_webhook_event",
        json_schema_extra={
            "const": "on_webhook_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "Receive Webhook Events",
        },
        title="Receive Webhook Events",
    )
    event_type: str = Field(
        "*",
        title="Trigger On Event",
        description=(
            "Which incident.io webhook event fires this workflow. incident.io "
            "delivers every subscribed event to one URL, so this filters the "
            "inbound payload by its `event_type`. Choose:\n"
            "- All events: fire on any delivered event\n"
            "- Incident created/updated/status updated: public incident lifecycle\n"
            "- Action created/updated, Follow-up created/updated: post-incident tasks\n"
            "- Incident membership granted/revoked: responder added/removed\n"
            "- Private incident created/updated/status updated: private-incident equivalents\n"
            "Make sure the matching event is enabled in incident.io Settings -> Webhooks."
        ),
        json_schema_extra={
            "enum": INCIDENT_IO_WEBHOOK_EVENTS,
            "enumNames": INCIDENT_IO_WEBHOOK_EVENT_NAMES,
            "x-enum-searchable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Add this URL as a webhook in incident.io Settings -> Webhooks and select which events to send",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        None,
        title="Signing Secret",
        description=(
            "Required to accept deliveries. Copy the whsec_ signing secret from "
            "this endpoint in incident.io Settings -> Webhooks."
        ),
        json_schema_extra={"ui:widget": "password", "ui:placeholder": "whsec_..."},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


IncidentIoConfig = Annotated[
    Union[
        IncidentIoListIncidentsConfig,
        IncidentIoGetIncidentConfig,
        IncidentIoCreateIncidentConfig,
        IncidentIoEditIncidentConfig,
        IncidentIoListIncidentUpdatesConfig,
        IncidentIoListActionsConfig,
        IncidentIoGetActionConfig,
        IncidentIoListFollowUpsConfig,
        IncidentIoGetFollowUpConfig,
        IncidentIoListAlertsConfig,
        IncidentIoGetAlertConfig,
        IncidentIoResolveAlertConfig,
        IncidentIoCreateAlertEventConfig,
        IncidentIoListSeveritiesConfig,
        IncidentIoListIncidentRolesConfig,
        IncidentIoListCustomFieldsConfig,
        IncidentIoListUsersConfig,
        IncidentIoGetUserConfig,
        IncidentIoListSchedulesConfig,
        IncidentIoListScheduleEntriesConfig,
        IncidentIoCreateScheduleOverrideConfig,
        IncidentIoListEscalationsConfig,
        IncidentIoCreateEscalationConfig,
        IncidentIoListCatalogTypesConfig,
        IncidentIoListCatalogEntriesConfig,
        IncidentIoCreateCatalogEntryConfig,
        IncidentIoUpdateCatalogEntryConfig,
        IncidentIoListStatusPageIncidentsConfig,
        IncidentIoCreateStatusPageIncidentConfig,
        IncidentIoListWorkflowsConfig,
        IncidentIoReceiveWebhookConfig,
    ],
    Discriminator("operation"),
]


class IncidentIoNodeConfig(NodeConfig[IncidentIoConfig, IncidentIoCredential]):
    """Full configuration for the incident.io node including credentials."""

    model_config = ConfigDict(title="Incident.io Node Configuration")


# ============================================================================
# HTTP Request Helper
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


async def _incident_io_request(
    api_key: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated incident.io request and return a structured result."""
    url = f"{INCIDENT_IO_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if json_body:
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
            if not 200 <= response.status_code < 300:
                # Never expose provider-controlled error bodies, including redirects.
                message = f"incident.io API returned HTTP {response.status_code}"
                logger.warning("[IncidentIoNode] API error (%s): HTTP %s", action_name, response.status_code)
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
                except ValueError:
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": "incident.io API returned a non-JSON response",
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": api_ms},
                    }
                if not isinstance(data, dict):
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": "incident.io API returned an unexpected response",
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": api_ms},
                    }
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
        except Exception:
            logger.warning("[IncidentIoNode] Request failed (%s)", action_name)
            return {
                "status": "error",
                "action": action_name,
                "error": "incident.io request failed",
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class IncidentIoNode(WorkflowNode):
    """incident.io incident management & on-call automation node."""

    integration_type = "automation-incident-io"

    edit_examples = [
        "Create a SEV2 incident when a critical alert fires",
        "List all open incidents and their severities",
        "Edit an incident to bump its severity and update the summary",
        "Page the on-call engineer by creating an escalation",
        "Publish an incident to the public status page",
        "Trigger a workflow whenever an incident is created or updated",
    ]

    connection_evidence = ConnectionEvidence(field="identity_probe", noun="API keys")

    @classmethod
    def get_config_model(cls):
        return IncidentIoNodeConfig

    # ------------------------------------------------------------------
    # Runtime event filtering
    # ------------------------------------------------------------------
    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Skip deliveries whose event type the user didn't subscribe to.

        incident.io's dashboard webhook delivers every enabled event to one URL
        with no per-NoClick-node subscription filter, so we filter here against
        the inbound payload's ``event_type``. ``"*"`` (or an unset selection)
        means "fire on any event".
        """
        if not isinstance(payload, dict) or not isinstance(payload.get("event_type"), str):
            return False
        selected = (config or {}).get("event_type") or "*"
        if selected == "*":
            return bool(payload["event_type"])
        return payload.get("event_type") == selected

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Accept only a fresh incident.io Svix signature for this endpoint."""
        secret = (config or {}).get("signing_secret")
        if not isinstance(secret, str) or not secret.startswith("whsec_"):
            return False
        try:
            decoded_secret = base64.b64decode(secret[len("whsec_"):], validate=True)
        except (ValueError, binascii.Error):
            return False
        if len(decoded_secret) < 16:
            return False
        webhook_id = headers.get("webhook-id", "")
        timestamp = headers.get("webhook-timestamp", "")
        signature = headers.get("webhook-signature", "")
        if not (isinstance(webhook_id, str) and 0 < len(webhook_id) <= 256):
            return False
        if not isinstance(timestamp, str) or not re.fullmatch(r"[0-9]{10,11}", timestamp):
            return False
        if not isinstance(signature, str) or len(signature) > 1024:
            return False
        return verify_svix(
            body=body,
            webhook_id=webhook_id,
            timestamp=timestamp,
            signature_header=signature,
            secret=secret,
        )

    # ------------------------------------------------------------------
    # Internal webhook URL provisioning (dashboard-configured webhooks)
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
        """Provision our inbound webhook URL — the user pastes it into incident.io."""
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

    # ------------------------------------------------------------------
    # Dynamic options and private credential identity proof
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Optional[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        loaders = {
            "severity_id": ("GET", "/v1/severities", "severities", "list_severities"),
            "schedule_id": ("GET", "/v2/schedules", "schedules", "list_schedules"),
            "catalog_type_id": ("GET", "/v3/catalog_types", "catalog_types", "list_catalog_types"),
        }
        if field_name not in loaders and field_name != "identity_probe":
            return {"options": []}

        api_key = require_credential_token(
            (credential_data or {}).get("api_key"), "Connect an incident.io API key to load options"
        )

        if field_name == "identity_probe":
            result = await _incident_io_request(api_key, "GET", "/v1/identity", action_name="identity_probe")
            if result.get("status") != "success":
                raise ValueError(result.get("error") or "incident.io identity could not be verified")
            identity = (result.get("data") or {}).get("identity")
            name = identity.get("name") if isinstance(identity, dict) else None
            if not isinstance(name, str) or not name.strip():
                raise ValueError("incident.io returned an unexpected identity response")
            # Only the documented nonsecret display name enters evidence.
            return {"options": [{"label": name.strip(), "value": name.strip()}]}

        method, endpoint, data_key, action = loaders[field_name]

        async def fetch_page(cursor: Optional[str]):
            params = {"after": cursor} if field_name == "schedule_id" and cursor else None
            result = await _incident_io_request(api_key, method, endpoint, params=params, action_name=action)
            if result.get("status") != "success":
                raise ValueError(result.get("error") or f"incident.io {field_name} options could not be loaded")
            data = result.get("data")
            items = data.get(data_key) if isinstance(data, dict) else None
            if not isinstance(items, list):
                raise ValueError(f"incident.io returned an unexpected {field_name} list")
            options = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_id = item.get("id")
                label = item.get("name") or item.get("display_name") or item_id
                if isinstance(item_id, str) and item_id:
                    options.append({"label": str(label), "value": item_id})
            meta = data.get("pagination_meta") if isinstance(data, dict) else None
            next_cursor = meta.get("after") if field_name == "schedule_id" and isinstance(meta, dict) else None
            return options, next_cursor if isinstance(next_cursor, str) and next_cursor else None

        if field_name == "schedule_id":
            return await load_paginated_options(
                fetch_page, page_token=page_token, search=search, log_label="incident_io_schedules"
            )
        options, _ = await fetch_page(None)
        return {"options": filter_options_by_search(options, search)}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, IncidentIoNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        # Webhook trigger mode — pass through the inbound event payload
        if isinstance(op, IncidentIoReceiveWebhookConfig):
            if not self.filter_trigger_payload(inputs, {"event_type": op.event_type}):
                return self.no_event_output("on_webhook_event")
            return {
                "status": "success",
                "action": "on_webhook_event",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your incident.io API key.")
        api_key = credentials.api_key

        handlers = {
            "list_incidents": self._list_incidents,
            "get_incident": self._get_incident,
            "create_incident": self._create_incident,
            "edit_incident": self._edit_incident,
            "list_incident_updates": self._list_incident_updates,
            "list_actions": self._list_actions,
            "get_action": self._get_action,
            "list_follow_ups": self._list_follow_ups,
            "get_follow_up": self._get_follow_up,
            "list_alerts": self._list_alerts,
            "get_alert": self._get_alert,
            "resolve_alert": self._resolve_alert,
            "create_alert_event": self._create_alert_event,
            "list_severities": self._list_severities,
            "list_incident_roles": self._list_incident_roles,
            "list_custom_fields": self._list_custom_fields,
            "list_users": self._list_users,
            "get_user": self._get_user,
            "list_schedules": self._list_schedules,
            "list_schedule_entries": self._list_schedule_entries,
            "create_schedule_override": self._create_schedule_override,
            "list_escalations": self._list_escalations,
            "create_escalation": self._create_escalation,
            "list_catalog_types": self._list_catalog_types,
            "list_catalog_entries": self._list_catalog_entries,
            "create_catalog_entry": self._create_catalog_entry,
            "update_catalog_entry": self._update_catalog_entry,
            "list_status_page_incidents": self._list_status_page_incidents,
            "create_status_page_incident": self._create_status_page_incident,
            "list_workflows": self._list_workflows,
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
    # Incident handlers
    # ------------------------------------------------------------------
    async def _list_incidents(self, c: IncidentIoListIncidentsConfig, api_key: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {"page_size": c.page_size, "after": c.after}
        if c.status:
            params["status[one_of]"] = _comma_list(c.status)
        if c.severity:
            params["severity[one_of]"] = _comma_list(c.severity)
        return await _incident_io_request(
            api_key, "GET", "/v2/incidents", params=params, action_name="list_incidents"
        )

    async def _get_incident(self, c: IncidentIoGetIncidentConfig, api_key: str) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", f"/v2/incidents/{c.incident_id}", action_name="get_incident"
        )

    async def _create_incident(self, c: IncidentIoCreateIncidentConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "summary": c.summary,
            "severity_id": c.severity_id,
            "incident_type_id": c.incident_type_id,
            "mode": c.mode,
            "visibility": c.visibility,
            "idempotency_key": c.idempotency_key,
        }
        return await _incident_io_request(
            api_key, "POST", "/v2/incidents", json_body=body, action_name="create_incident"
        )

    async def _edit_incident(self, c: IncidentIoEditIncidentConfig, api_key: str) -> Dict[str, Any]:
        incident: Dict[str, Any] = {
            "name": c.name,
            "summary": c.summary,
            "severity_id": c.severity_id,
        }
        incident = {k: v for k, v in incident.items() if v is not None}
        return await _incident_io_request(
            api_key,
            "POST",
            f"/v2/incidents/{c.incident_id}/actions/edit",
            json_body={"incident": incident, "notify_incident_channel": c.notify_incident_channel},
            action_name="edit_incident",
        )

    async def _list_incident_updates(
        self, c: IncidentIoListIncidentUpdatesConfig, api_key: str
    ) -> Dict[str, Any]:
        params = {"incident_id": c.incident_id, "page_size": c.page_size, "after": c.after}
        return await _incident_io_request(
            api_key, "GET", "/v2/incident_updates", params=params, action_name="list_incident_updates"
        )

    # ------------------------------------------------------------------
    # Actions & follow-ups
    # ------------------------------------------------------------------
    async def _list_actions(self, c: IncidentIoListActionsConfig, api_key: str) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", "/v2/actions", params={"incident_id": c.incident_id},
            action_name="list_actions",
        )

    async def _get_action(self, c: IncidentIoGetActionConfig, api_key: str) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", f"/v2/actions/{c.action_id}", action_name="get_action"
        )

    async def _list_follow_ups(self, c: IncidentIoListFollowUpsConfig, api_key: str) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", "/v2/follow_ups", params={"incident_id": c.incident_id},
            action_name="list_follow_ups",
        )

    async def _get_follow_up(self, c: IncidentIoGetFollowUpConfig, api_key: str) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", f"/v2/follow_ups/{c.follow_up_id}", action_name="get_follow_up"
        )

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------
    async def _list_alerts(self, c: IncidentIoListAlertsConfig, api_key: str) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", "/v2/alerts", params={"page_size": c.page_size, "after": c.after},
            action_name="list_alerts",
        )

    async def _get_alert(self, c: IncidentIoGetAlertConfig, api_key: str) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", f"/v2/alerts/{c.alert_id}", action_name="get_alert"
        )

    async def _resolve_alert(self, c: IncidentIoResolveAlertConfig, api_key: str) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "POST", f"/v2/alerts/{c.alert_id}/actions/resolve", action_name="resolve_alert"
        )

    async def _create_alert_event(
        self, c: IncidentIoCreateAlertEventConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "title": c.title,
            "status": c.status,
            "description": c.description,
            "deduplication_key": c.deduplication_key,
        }
        return await _incident_io_request(
            api_key,
            "POST",
            f"/v2/alert_events/http/{c.alert_source_config_id}",
            json_body=body,
            action_name="create_alert_event",
        )

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    async def _list_severities(self, c: IncidentIoListSeveritiesConfig, api_key: str) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", "/v1/severities", action_name="list_severities"
        )

    async def _list_incident_roles(
        self, c: IncidentIoListIncidentRolesConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", "/v2/incident_roles", action_name="list_incident_roles"
        )

    async def _list_custom_fields(
        self, c: IncidentIoListCustomFieldsConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", "/v2/custom_fields", action_name="list_custom_fields"
        )

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------
    async def _list_users(self, c: IncidentIoListUsersConfig, api_key: str) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", "/v2/users", params={"page_size": c.page_size, "after": c.after},
            action_name="list_users",
        )

    async def _get_user(self, c: IncidentIoGetUserConfig, api_key: str) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", f"/v2/users/{c.user_id}", action_name="get_user"
        )

    # ------------------------------------------------------------------
    # On-call
    # ------------------------------------------------------------------
    async def _list_schedules(self, c: IncidentIoListSchedulesConfig, api_key: str) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", "/v2/schedules", action_name="list_schedules"
        )

    async def _list_schedule_entries(
        self, c: IncidentIoListScheduleEntriesConfig, api_key: str
    ) -> Dict[str, Any]:
        params = {
            "schedule_id": c.schedule_id,
            "entry_window_start": c.entry_window_start,
            "entry_window_end": c.entry_window_end,
        }
        return await _incident_io_request(
            api_key, "GET", "/v2/schedule_entries", params=params, action_name="list_schedule_entries"
        )

    async def _create_schedule_override(
        self, c: IncidentIoCreateScheduleOverrideConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "schedule_id": c.schedule_id,
            "rotation_id": c.rotation_id,
            "layer_id": c.layer_id,
            "user": {"id": c.user_id},
            "start_at": c.start_at,
            "end_at": c.end_at,
        }
        return await _incident_io_request(
            api_key, "POST", "/v2/schedule_overrides", json_body=body,
            action_name="create_schedule_override",
        )

    async def _list_escalations(self, c: IncidentIoListEscalationsConfig, api_key: str) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", "/v2/escalations", params={"page_size": c.page_size, "after": c.after},
            action_name="list_escalations",
        )

    async def _create_escalation(
        self, c: IncidentIoCreateEscalationConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "title": c.title,
            "escalation_path_id": c.escalation_path_id,
            "idempotency_key": c.idempotency_key,
        }
        return await _incident_io_request(
            api_key, "POST", "/v2/escalations", json_body=body, action_name="create_escalation"
        )

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------
    async def _list_catalog_types(
        self, c: IncidentIoListCatalogTypesConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", "/v3/catalog_types", action_name="list_catalog_types"
        )

    async def _list_catalog_entries(
        self, c: IncidentIoListCatalogEntriesConfig, api_key: str
    ) -> Dict[str, Any]:
        params = {
            "catalog_type_id": c.catalog_type_id,
            "page_size": c.page_size,
            "after": c.after,
        }
        return await _incident_io_request(
            api_key, "GET", "/v3/catalog_entries", params=params, action_name="list_catalog_entries"
        )

    async def _create_catalog_entry(
        self, c: IncidentIoCreateCatalogEntryConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "catalog_type_id": c.catalog_type_id,
            "name": c.name,
            "external_id": c.external_id,
            "aliases": _comma_list(c.aliases),
            "attribute_values": c.attribute_values,
        }
        return await _incident_io_request(
            api_key, "POST", "/v3/catalog_entries", json_body=body,
            action_name="create_catalog_entry",
        )

    async def _update_catalog_entry(
        self, c: IncidentIoUpdateCatalogEntryConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "external_id": c.external_id,
            "aliases": _comma_list(c.aliases),
            "attribute_values": c.attribute_values,
        }
        return await _incident_io_request(
            api_key, "PUT", f"/v3/catalog_entries/{c.catalog_entry_id}", json_body=body,
            action_name="update_catalog_entry",
        )

    # ------------------------------------------------------------------
    # Status pages
    # ------------------------------------------------------------------
    async def _list_status_page_incidents(
        self, c: IncidentIoListStatusPageIncidentsConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", "/v2/status_page_incidents",
            params={"status_page_id": c.status_page_id, "page_size": c.page_size, "after": c.after},
            action_name="list_status_page_incidents",
        )

    async def _create_status_page_incident(
        self, c: IncidentIoCreateStatusPageIncidentConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "status_page_id": c.status_page_id,
            "name": c.name,
            "message": c.message,
            "incident_status": c.incident_status,
            "notify_subscribers": c.notify_subscribers,
            "idempotency_key": c.idempotency_key,
        }
        return await _incident_io_request(
            api_key, "POST", "/v2/status_page_incidents", json_body=body,
            action_name="create_status_page_incident",
        )

    # ------------------------------------------------------------------
    # Workflows
    # ------------------------------------------------------------------
    async def _list_workflows(self, c: IncidentIoListWorkflowsConfig, api_key: str) -> Dict[str, Any]:
        return await _incident_io_request(
            api_key, "GET", "/v2/workflows", action_name="list_workflows"
        )
