"""
PagerDuty incident management automation node.

Provides workflow integration with the PagerDuty REST API v2 for operations including:
- Incidents: list, get, create, update, manage (bulk), snooze, merge
- Incident details: notes (list/create), status updates, alerts, log entries, add responders
- Services: list, get, create, update
- Schedules / on-call: list schedules, get schedule, list on-calls
- Escalation policies: list, create
- Users: list, get, create, get current user
- Teams: list
- Maintenance windows: list, create
- Events API v2: send an alert event (trigger / acknowledge / resolve)
- Webhook subscriptions: list, create
- Priorities: list
- Webhook Trigger: fire when an incident event is delivered (triggered, acknowledged, resolved, ...)

Authentication: OAuth 2.0 (Bearer, tokens prefixed `pdus+_`/`pdeu+_`) or an API key
(REST API token, passed as `Authorization: Token token=<KEY>`). The header format is
auto-detected from the token prefix in `_pagerduty_request`.
API Base URL: https://api.pagerduty.com  (Events API v2: https://events.pagerduty.com/v2/enqueue)
Documentation: https://developer.pagerduty.com/api-reference/
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.scopes.pagerduty import PAGERDUTY_SCOPES
from nodes.oauth.pagerduty_oauth import PAGERDUTY_DEFAULT_SCOPES

logger = logging.getLogger(__name__)

PAGERDUTY_API_BASE = "https://api.pagerduty.com"
PAGERDUTY_EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"

# Region-aware base URLs. PagerDuty EU accounts live on *.eu.pagerduty.com; a
# US-hardcoded base silently fails for them. The credential's ``region`` field
# sets a ContextVar per execution so the module-level request helper (and all
# handlers) resolve the right host without threading base_url through every
# signature.
from contextvars import ContextVar  # noqa: E402

_PD_REGION: ContextVar[str] = ContextVar("pd_region", default="us")


def _rest_base() -> str:
    return "https://api.eu.pagerduty.com" if _PD_REGION.get() == "eu" else PAGERDUTY_API_BASE


def _events_base() -> str:
    return "https://events.eu.pagerduty.com" if _PD_REGION.get() == "eu" else "https://events.pagerduty.com"


def _events_enqueue_url() -> str:
    return f"{_events_base()}/v2/enqueue"

# V3 webhook subscription event types the trigger subscribes to.
WEBHOOK_TRIGGER_EVENTS = [
    "incident.triggered",
    "incident.acknowledged",
    "incident.resolved",
    "incident.reassigned",
    "incident.escalated",
    "incident.annotated",
]


# ============================================================================
# Credential Schema
# ============================================================================


class PagerDutyOAuthCredential(BaseModel):
    """OAuth 2.0 credential for PagerDuty (authorization_code flow).

    Tokens are obtained via the OAuth flow, not entered manually. PagerDuty
    access tokens are prefixed ``pdus+_`` / ``pdeu+_`` and used as Bearer tokens;
    they are auto-refreshed via the refresh token on expiry.

    Register an OAuth app at: https://developer.pagerduty.com/docs/register-an-app
    """

    credential_type: Literal["pagerduty_oauth"] = Field(
        "pagerduty_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="PagerDuty OAuth access token (Bearer).",
        json_schema_extra={"ui:widget": "password"},
    )
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    name: Optional[str] = Field(None, title="User Name")
    email: Optional[str] = Field(None, title="Account Email")
    from_email: Optional[str] = Field(
        None,
        title="From Email",
        description=(
            "Email of the PagerDuty user actions act as. Optional for OAuth user "
            "tokens, which already act as the authorizing user."
        ),
    )
    region: Optional[str] = Field(
        "us",
        title="Region",
        description="PagerDuty data region. Use 'eu' for EU service region accounts (*.eu.pagerduty.com).",
        json_schema_extra={
            "enum": ["us", "eu"],
            "enumNames": ["US", "EU"],
            "x-enum-searchable": True,
        },
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "pagerduty",
            "x-oauth-scopes": PAGERDUTY_DEFAULT_SCOPES,
            "x-oauth-supports-custom-client": True,
            "x-oauth-custom-client-help": (
                "Optionally bring your own PagerDuty OAuth app. Register one at "
                "https://developer.pagerduty.com/docs/register-an-app, set its "
                "redirect URI to NoClick's PagerDuty callback, and paste its "
                "client ID and secret here. Leave blank to use NoClick's shared "
                "PagerDuty app."
            ),
            "x-credential-url": "https://developer.pagerduty.com/docs/register-an-app",
        }
    )


class PagerDutyApiKeyCredential(BaseModel):
    """REST API key credential for PagerDuty."""

    credential_type: Literal["pagerduty_api_key"] = Field(
        "pagerduty_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description=(
            "A PagerDuty REST API key. Account admins create a General Access key under "
            "Integrations -> API Access Keys; users create a personal token under "
            "My Profile -> User Settings -> Create API User Token."
        ),
        json_schema_extra={"ui:widget": "password"},
    )
    from_email: Optional[str] = Field(
        None,
        title="From Email",
        description=(
            "Email of the PagerDuty user actions act as. Required by account-level API keys "
            "for write actions like creating incidents or users. Leave blank for User API Tokens."
        ),
    )
    region: Optional[str] = Field(
        "us",
        title="Region",
        description="PagerDuty data region. Use 'eu' for EU service region accounts (*.eu.pagerduty.com).",
        json_schema_extra={
            "enum": ["us", "eu"],
            "enumNames": ["US", "EU"],
            "x-enum-searchable": True,
        },
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://support.pagerduty.com/docs/api-access-keys"
        }
    )


# OAuth first so it is the default choice when a user adds a credential, with the
# REST API key as the simplest always-working self-serve path.
PagerDutyCredential = Union[PagerDutyOAuthCredential, PagerDutyApiKeyCredential]


# ============================================================================
# Operation Configs
# ============================================================================


class PagerDutyListIncidentsConfig(BaseModel):
    """List incidents, optionally filtered by status, service, team, urgency, or date range."""

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
    statuses: Optional[str] = Field(
        None,
        title="Status",
        description="Filter by incident status",
        json_schema_extra={
            "enum": ["", "triggered", "acknowledged", "resolved"],
            "enumNames": ["Any", "Triggered", "Acknowledged", "Resolved"],
            "x-enum-searchable": True,
        },
    )
    urgencies: Optional[str] = Field(
        None,
        title="Urgency",
        description="Filter by urgency",
        json_schema_extra={
            "enum": ["", "high", "low"],
            "enumNames": ["Any", "High", "Low"],
            "x-enum-searchable": True,
        },
    )
    service_ids: Optional[str] = Field(
        None,
        title="Service",
        description="Filter to incidents on this service",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_ids",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID(s), comma-separated",
            }
        },
    )
    team_ids: Optional[str] = Field(
        None,
        title="Team",
        description="Filter to incidents owned by this team",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "team_ids",
                "placeholder": "Select a team...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste team ID(s), comma-separated",
            }
        },
    )
    since: Optional[str] = Field(
        None, title="Since", description="ISO 8601 lower bound on the created_at range"
    )
    until: Optional[str] = Field(
        None, title="Until", description="ISO 8601 upper bound on the created_at range"
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of incidents to return (1-100)"
    )


class PagerDutyGetIncidentConfig(BaseModel):
    """Retrieve a single incident by its ID."""

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


class PagerDutyCreateIncidentConfig(BaseModel):
    """Create a new incident on a service (requires the From Email credential field)."""

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
    title: str = Field(..., title="Title", description="A succinct description of the incident")
    service_id: str = Field(
        ...,
        title="Service",
        description="The service the incident belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )
    urgency: Optional[str] = Field(
        None,
        title="Urgency",
        description="Incident urgency (defaults to the service's setting)",
        json_schema_extra={
            "enum": ["", "high", "low"],
            "enumNames": ["Default", "High", "Low"],
            "x-enum-searchable": True,
        },
    )
    body_details: Optional[str] = Field(
        None,
        title="Details",
        description="Additional incident details / body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    escalation_policy_id: Optional[str] = Field(
        None,
        title="Escalation Policy",
        description="Delegate to this escalation policy (optional)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "escalation_policy_id",
                "placeholder": "Select an escalation policy...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste escalation policy ID",
            }
        },
    )
    priority_id: Optional[str] = Field(
        None,
        title="Priority",
        description="Assign this priority (optional)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "priority_id",
                "placeholder": "Select a priority...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste priority ID",
            }
        },
    )


class PagerDutyUpdateIncidentConfig(BaseModel):
    """Update a single incident (acknowledge, resolve, reassign, set priority, etc.)."""

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
    status: Optional[str] = Field(
        None,
        title="Status",
        description="New status (acknowledged or resolved)",
        json_schema_extra={
            "enum": ["", "acknowledged", "resolved"],
            "enumNames": ["No change", "Acknowledge", "Resolve"],
            "x-enum-searchable": True,
        },
    )
    urgency: Optional[str] = Field(
        None,
        title="Urgency",
        description="Change urgency (optional)",
        json_schema_extra={
            "enum": ["", "high", "low"],
            "enumNames": ["No change", "High", "Low"],
            "x-enum-searchable": True,
        },
    )
    priority_id: Optional[str] = Field(
        None,
        title="Priority",
        description="Set the incident priority (optional)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "priority_id",
                "placeholder": "Select a priority...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste priority ID",
            }
        },
    )
    escalation_policy_id: Optional[str] = Field(
        None,
        title="Escalation Policy",
        description="Reassign to this escalation policy (optional)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "escalation_policy_id",
                "placeholder": "Select an escalation policy...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste escalation policy ID",
            }
        },
    )
    resolution: Optional[str] = Field(
        None, title="Resolution", description="A resolution note when resolving (optional)"
    )


class PagerDutyManageIncidentsConfig(BaseModel):
    """Bulk-update the status of multiple incidents at once."""

    operation: Literal["manage_incidents"] = Field(
        "manage_incidents",
        json_schema_extra={
            "const": "manage_incidents",
            "ui:hidden": True,
            "x-category": "Incidents",
            "x-is-trigger": False,
            "x-display-name": "Manage Incidents (Bulk)",
        },
        title="Manage Incidents (Bulk)",
    )
    incident_ids: str = Field(
        ..., title="Incident IDs", description="Incident IDs to update, comma-separated"
    )
    status: str = Field(
        "resolved",
        title="Status",
        description="The status to apply to all listed incidents",
        json_schema_extra={
            "enum": ["acknowledged", "resolved"],
            "enumNames": ["Acknowledge", "Resolve"],
            "x-enum-searchable": True,
        },
    )


class PagerDutySnoozeIncidentConfig(BaseModel):
    """Snooze an incident for a number of seconds."""

    operation: Literal["snooze_incident"] = Field(
        "snooze_incident",
        json_schema_extra={
            "const": "snooze_incident",
            "ui:hidden": True,
            "x-category": "Incidents",
            "x-is-trigger": False,
            "x-display-name": "Snooze Incident",
        },
        title="Snooze Incident",
    )
    incident_id: str = Field(
        ..., title="Incident ID", description="The ID of the incident to snooze"
    )
    duration: str = Field(
        "3600", title="Duration (seconds)", description="How long to snooze the incident, in seconds"
    )


class PagerDutyMergeIncidentsConfig(BaseModel):
    """Merge other incidents into a target incident."""

    operation: Literal["merge_incidents"] = Field(
        "merge_incidents",
        json_schema_extra={
            "const": "merge_incidents",
            "ui:hidden": True,
            "x-category": "Incidents",
            "x-is-trigger": False,
            "x-display-name": "Merge Incidents",
        },
        title="Merge Incidents",
    )
    incident_id: str = Field(
        ..., title="Target Incident ID", description="The incident other incidents are merged into"
    )
    source_incident_ids: str = Field(
        ..., title="Source Incident IDs", description="Incident IDs to merge in, comma-separated"
    )


class PagerDutyListNotesConfig(BaseModel):
    """List the notes attached to an incident."""

    operation: Literal["list_notes"] = Field(
        "list_notes",
        json_schema_extra={
            "const": "list_notes",
            "ui:hidden": True,
            "x-category": "Incident Details",
            "x-is-trigger": False,
            "x-display-name": "List Notes",
        },
        title="List Notes",
    )
    incident_id: str = Field(
        ..., title="Incident ID", description="The incident whose notes to list"
    )


class PagerDutyCreateNoteConfig(BaseModel):
    """Add a note to an incident."""

    operation: Literal["create_note"] = Field(
        "create_note",
        json_schema_extra={
            "const": "create_note",
            "ui:hidden": True,
            "x-category": "Incident Details",
            "x-is-trigger": False,
            "x-display-name": "Create Note",
        },
        title="Create Note",
    )
    incident_id: str = Field(
        ..., title="Incident ID", description="The incident to add the note to"
    )
    content: str = Field(
        ...,
        title="Note",
        description="The note content",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyCreateStatusUpdateConfig(BaseModel):
    """Post a status update to an incident."""

    operation: Literal["create_status_update"] = Field(
        "create_status_update",
        json_schema_extra={
            "const": "create_status_update",
            "ui:hidden": True,
            "x-category": "Incident Details",
            "x-is-trigger": False,
            "x-display-name": "Create Status Update",
        },
        title="Create Status Update",
    )
    incident_id: str = Field(
        ..., title="Incident ID", description="The incident to post a status update to"
    )
    message: str = Field(
        ...,
        title="Message",
        description="The status update message",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyListAlertsConfig(BaseModel):
    """List the alerts associated with an incident."""

    operation: Literal["list_alerts"] = Field(
        "list_alerts",
        json_schema_extra={
            "const": "list_alerts",
            "ui:hidden": True,
            "x-category": "Incident Details",
            "x-is-trigger": False,
            "x-display-name": "List Alerts",
        },
        title="List Alerts",
    )
    incident_id: str = Field(
        ..., title="Incident ID", description="The incident whose alerts to list"
    )


class PagerDutyListLogEntriesConfig(BaseModel):
    """List the timeline log entries for an incident."""

    operation: Literal["list_log_entries"] = Field(
        "list_log_entries",
        json_schema_extra={
            "const": "list_log_entries",
            "ui:hidden": True,
            "x-category": "Incident Details",
            "x-is-trigger": False,
            "x-display-name": "List Log Entries",
        },
        title="List Log Entries",
    )
    incident_id: str = Field(
        ..., title="Incident ID", description="The incident whose log entries to list"
    )


class PagerDutyAddRespondersConfig(BaseModel):
    """Request additional responders on an incident."""

    operation: Literal["add_responders"] = Field(
        "add_responders",
        json_schema_extra={
            "const": "add_responders",
            "ui:hidden": True,
            "x-category": "Incident Details",
            "x-is-trigger": False,
            "x-display-name": "Add Responders",
        },
        title="Add Responders",
    )
    incident_id: str = Field(
        ..., title="Incident ID", description="The incident to add responders to"
    )
    user_ids: Optional[str] = Field(
        None,
        title="Users",
        description="Users to request as responders",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_ids",
                "placeholder": "Select user(s)...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID(s), comma-separated",
            }
        },
    )
    escalation_policy_ids: Optional[str] = Field(
        None,
        title="Escalation Policies",
        description="Escalation policies to request responders from",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "escalation_policy_ids",
                "placeholder": "Select escalation policies...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste escalation policy ID(s), comma-separated",
            }
        },
    )
    message: str = Field(
        ..., title="Message", description="The message sent to the requested responders"
    )
    requester_id: Optional[str] = Field(
        None,
        title="Requester (User ID)",
        description="User making the request (required by PagerDuty). Defaults to the credential's From user.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "requester_id",
                "placeholder": "Defaults to the From user…",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a user ID",
            }
        },
    )


class PagerDutyListServicesConfig(BaseModel):
    """List technical services."""

    operation: Literal["list_services"] = Field(
        "list_services",
        json_schema_extra={
            "const": "list_services",
            "ui:hidden": True,
            "x-category": "Services",
            "x-is-trigger": False,
            "x-display-name": "List Services",
        },
        title="List Services",
    )
    query: Optional[str] = Field(
        None, title="Query", description="Filter services by name (optional)"
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of services to return (1-100)"
    )


class PagerDutyGetServiceConfig(BaseModel):
    """Retrieve a single service by ID."""

    operation: Literal["get_service"] = Field(
        "get_service",
        json_schema_extra={
            "const": "get_service",
            "ui:hidden": True,
            "x-category": "Services",
            "x-is-trigger": False,
            "x-display-name": "Get Service",
        },
        title="Get Service",
    )
    service_id: str = Field(
        ...,
        title="Service",
        description="The service to retrieve",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )


class PagerDutyCreateServiceConfig(BaseModel):
    """Create a new technical service."""

    operation: Literal["create_service"] = Field(
        "create_service",
        json_schema_extra={
            "const": "create_service",
            "x-creates-resource": True,
            "x-resource-type": "pagerduty_service",
            "x-resource-id-path": "data.service.id",
            "ui:hidden": True,
            "x-category": "Services",
            "x-is-trigger": False,
            "x-display-name": "Create Service",
        },
        title="Create Service",
    )
    name: str = Field(..., title="Name", description="The name of the new service")
    escalation_policy_id: str = Field(
        ...,
        title="Escalation Policy",
        description="The escalation policy this service uses",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "escalation_policy_id",
                "placeholder": "Select an escalation policy...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste escalation policy ID",
            }
        },
    )
    description: Optional[str] = Field(
        None, title="Description", description="A description of the service (optional)"
    )


class PagerDutyUpdateServiceConfig(BaseModel):
    """Update an existing service."""

    operation: Literal["update_service"] = Field(
        "update_service",
        json_schema_extra={
            "const": "update_service",
            "ui:hidden": True,
            "x-category": "Services",
            "x-is-trigger": False,
            "x-display-name": "Update Service",
        },
        title="Update Service",
    )
    service_id: str = Field(..., title="Service ID", description="The ID of the service to update")
    name: Optional[str] = Field(None, title="Name", description="New service name (optional)")
    description: Optional[str] = Field(
        None, title="Description", description="New service description (optional)"
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="New service status (optional)",
        json_schema_extra={
            "enum": ["", "active", "warning", "critical", "maintenance", "disabled"],
            "enumNames": ["No change", "Active", "Warning", "Critical", "Maintenance", "Disabled"],
            "x-enum-searchable": True,
        },
    )


class PagerDutyListSchedulesConfig(BaseModel):
    """List on-call schedules."""

    operation: Literal["list_schedules"] = Field(
        "list_schedules",
        json_schema_extra={
            "const": "list_schedules",
            "ui:hidden": True,
            "x-category": "Schedules & On-Call",
            "x-is-trigger": False,
            "x-display-name": "List Schedules",
        },
        title="List Schedules",
    )
    query: Optional[str] = Field(
        None, title="Query", description="Filter schedules by name (optional)"
    )


class PagerDutyGetScheduleConfig(BaseModel):
    """Retrieve a single schedule, optionally within a time range."""

    operation: Literal["get_schedule"] = Field(
        "get_schedule",
        json_schema_extra={
            "const": "get_schedule",
            "ui:hidden": True,
            "x-category": "Schedules & On-Call",
            "x-is-trigger": False,
            "x-display-name": "Get Schedule",
        },
        title="Get Schedule",
    )
    schedule_id: str = Field(
        ...,
        title="Schedule",
        description="The schedule to retrieve",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "schedule_id",
                "placeholder": "Select a schedule...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste schedule ID",
            }
        },
    )
    since: Optional[str] = Field(
        None, title="Since", description="ISO 8601 start of the time range to render (optional)"
    )
    until: Optional[str] = Field(
        None, title="Until", description="ISO 8601 end of the time range to render (optional)"
    )


class PagerDutyListOnCallsConfig(BaseModel):
    """List who is on-call, filterable by user, schedule, or escalation policy."""

    operation: Literal["list_oncalls"] = Field(
        "list_oncalls",
        json_schema_extra={
            "const": "list_oncalls",
            "ui:hidden": True,
            "x-category": "Schedules & On-Call",
            "x-is-trigger": False,
            "x-display-name": "List On-Calls",
        },
        title="List On-Calls",
    )
    schedule_ids: Optional[str] = Field(
        None,
        title="Schedules",
        description="Filter on-calls to these schedules",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "schedule_ids",
                "placeholder": "Select schedule(s)...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste schedule ID(s), comma-separated",
            }
        },
    )
    user_ids: Optional[str] = Field(
        None,
        title="Users",
        description="Filter on-calls to these users",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_ids",
                "placeholder": "Select user(s)...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID(s), comma-separated",
            }
        },
    )
    escalation_policy_ids: Optional[str] = Field(
        None,
        title="Escalation Policies",
        description="Filter on-calls to these escalation policies",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "escalation_policy_ids",
                "placeholder": "Select escalation policies...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste escalation policy ID(s), comma-separated",
            }
        },
    )
    since: Optional[str] = Field(
        None, title="Since", description="ISO 8601 start of the on-call window (optional)"
    )
    until: Optional[str] = Field(
        None, title="Until", description="ISO 8601 end of the on-call window (optional)"
    )


class PagerDutyListEscalationPoliciesConfig(BaseModel):
    """List escalation policies."""

    operation: Literal["list_escalation_policies"] = Field(
        "list_escalation_policies",
        json_schema_extra={
            "const": "list_escalation_policies",
            "ui:hidden": True,
            "x-category": "Escalation Policies",
            "x-is-trigger": False,
            "x-display-name": "List Escalation Policies",
        },
        title="List Escalation Policies",
    )
    query: Optional[str] = Field(
        None, title="Query", description="Filter escalation policies by name (optional)"
    )


class PagerDutyCreateEscalationPolicyConfig(BaseModel):
    """Create an escalation policy with a single escalation rule."""

    operation: Literal["create_escalation_policy"] = Field(
        "create_escalation_policy",
        json_schema_extra={
            "const": "create_escalation_policy",
            "x-creates-resource": True,
            "x-resource-type": "pagerduty_escalation_policy",
            "x-resource-id-path": "data.escalation_policy.id",
            "ui:hidden": True,
            "x-category": "Escalation Policies",
            "x-is-trigger": False,
            "x-display-name": "Create Escalation Policy",
        },
        title="Create Escalation Policy",
    )
    name: str = Field(..., title="Name", description="The name of the escalation policy")
    escalation_target_id: str = Field(
        ...,
        title="Escalation Target",
        description="The user or schedule notified by the first escalation rule",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "escalation_target_id",
                "placeholder": "Select a target...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a user/schedule ID",
                "depends_on": "escalation_target_type",
            }
        },
    )
    escalation_target_type: str = Field(
        "user_reference",
        title="Target Type",
        description="Whether the target is a user or a schedule",
        json_schema_extra={
            "enum": ["user_reference", "schedule_reference"],
            "enumNames": ["User", "Schedule"],
            "x-enum-searchable": True,
        },
    )
    escalation_delay_in_minutes: str = Field(
        "30",
        title="Escalation Delay (minutes)",
        description="Minutes before escalating to the next rule",
    )


class PagerDutyListUsersConfig(BaseModel):
    """List users in the account."""

    operation: Literal["list_users"] = Field(
        "list_users",
        json_schema_extra={
            "const": "list_users",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "List Users",
        },
        title="List Users",
    )
    query: Optional[str] = Field(
        None, title="Query", description="Filter users by name or email (optional)"
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of users to return (1-100)"
    )


class PagerDutyGetUserConfig(BaseModel):
    """Retrieve a single user by ID."""

    operation: Literal["get_user"] = Field(
        "get_user",
        json_schema_extra={
            "const": "get_user",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Get User",
        },
        title="Get User",
    )
    user_id: str = Field(
        ...,
        title="User",
        description="The user to retrieve",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            }
        },
    )


class PagerDutyCreateUserConfig(BaseModel):
    """Create a new user (requires the From Email credential field)."""

    operation: Literal["create_user"] = Field(
        "create_user",
        json_schema_extra={
            "const": "create_user",
            "x-creates-resource": True,
            "x-resource-type": "pagerduty_user",
            "x-resource-id-path": "data.user.id",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Create User",
        },
        title="Create User",
    )
    name: str = Field(..., title="Name", description="The new user's full name")
    email: str = Field(..., title="Email", description="The new user's email address")
    role: Optional[str] = Field(
        None,
        title="Role",
        description="The user's account role (optional)",
        json_schema_extra={
            "enum": ["", "admin", "user", "limited_user", "observer", "restricted_access"],
            "enumNames": ["Default", "Admin", "User", "Limited User", "Observer", "Restricted Access"],
            "x-enum-searchable": True,
        },
    )


class PagerDutyGetCurrentUserConfig(BaseModel):
    """Retrieve the user associated with the API token."""

    operation: Literal["get_current_user"] = Field(
        "get_current_user",
        json_schema_extra={
            "const": "get_current_user",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Get Current User",
        },
        title="Get Current User",
    )


class PagerDutyListTeamsConfig(BaseModel):
    """List teams in the account."""

    operation: Literal["list_teams"] = Field(
        "list_teams",
        json_schema_extra={
            "const": "list_teams",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "List Teams",
        },
        title="List Teams",
    )
    query: Optional[str] = Field(
        None, title="Query", description="Filter teams by name (optional)"
    )


class PagerDutyListMaintenanceWindowsConfig(BaseModel):
    """List maintenance windows."""

    operation: Literal["list_maintenance_windows"] = Field(
        "list_maintenance_windows",
        json_schema_extra={
            "const": "list_maintenance_windows",
            "ui:hidden": True,
            "x-category": "Maintenance Windows",
            "x-is-trigger": False,
            "x-display-name": "List Maintenance Windows",
        },
        title="List Maintenance Windows",
    )
    filter: Optional[str] = Field(
        None,
        title="Filter",
        description="Limit to windows in a particular state (optional)",
        json_schema_extra={
            "enum": ["", "past", "future", "ongoing", "open"],
            "enumNames": ["All", "Past", "Future", "Ongoing", "Open"],
            "x-enum-searchable": True,
        },
    )


class PagerDutyCreateMaintenanceWindowConfig(BaseModel):
    """Schedule a maintenance window for one or more services."""

    operation: Literal["create_maintenance_window"] = Field(
        "create_maintenance_window",
        json_schema_extra={
            "const": "create_maintenance_window",
            "x-creates-resource": True,
            "x-resource-type": "pagerduty_maintenance_window",
            "x-resource-id-path": "data.maintenance_window.id",
            "ui:hidden": True,
            "x-category": "Maintenance Windows",
            "x-is-trigger": False,
            "x-display-name": "Create Maintenance Window",
        },
        title="Create Maintenance Window",
    )
    service_ids: str = Field(
        ...,
        title="Services",
        description="Services to put in maintenance",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_ids",
                "placeholder": "Select service(s)...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID(s), comma-separated",
            }
        },
    )
    start_time: str = Field(
        ..., title="Start Time", description="ISO 8601 start of the maintenance window"
    )
    end_time: str = Field(
        ..., title="End Time", description="ISO 8601 end of the maintenance window"
    )
    description: Optional[str] = Field(
        None, title="Description", description="A description of the maintenance window (optional)"
    )


class PagerDutySendEventConfig(BaseModel):
    """Send an alert event via the Events API v2 (trigger / acknowledge / resolve)."""

    operation: Literal["send_event"] = Field(
        "send_event",
        json_schema_extra={
            "const": "send_event",
            "ui:hidden": True,
            "x-category": "Events API",
            "x-is-trigger": False,
            "x-display-name": "Send Alert Event",
        },
        title="Send Alert Event",
    )
    routing_key: str = Field(
        ...,
        title="Integration Key",
        description="The 32-character Events API v2 integration (routing) key for the target service",
        json_schema_extra={"ui:widget": "password"},
    )
    event_action: str = Field(
        "trigger",
        title="Event Action",
        description="Whether to trigger a new alert or act on an existing one",
        json_schema_extra={
            "enum": ["trigger", "acknowledge", "resolve"],
            "enumNames": ["Trigger", "Acknowledge", "Resolve"],
            "x-enum-searchable": True,
        },
    )
    summary: Optional[str] = Field(
        None,
        title="Summary",
        description="A brief description of the problem (required when triggering)",
    )
    source: Optional[str] = Field(
        None,
        title="Source",
        description="The affected host or component (required when triggering)",
    )
    severity: Optional[str] = Field(
        "critical",
        title="Severity",
        description="The perceived severity (required when triggering)",
        json_schema_extra={
            "enum": ["critical", "error", "warning", "info"],
            "enumNames": ["Critical", "Error", "Warning", "Info"],
            "x-enum-searchable": True,
        },
    )
    dedup_key: Optional[str] = Field(
        None,
        title="Dedup Key",
        description="Deduplication key. Required for acknowledge/resolve; returned when triggering",
    )


class PagerDutyListWebhookSubscriptionsConfig(BaseModel):
    """List configured V3 webhook subscriptions."""

    operation: Literal["list_webhook_subscriptions"] = Field(
        "list_webhook_subscriptions",
        json_schema_extra={
            "const": "list_webhook_subscriptions",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "List Webhook Subscriptions",
        },
        title="List Webhook Subscriptions",
    )


class PagerDutyCreateWebhookSubscriptionConfig(BaseModel):
    """Register a V3 webhook subscription to deliver events to a URL."""

    operation: Literal["create_webhook_subscription"] = Field(
        "create_webhook_subscription",
        json_schema_extra={
            "const": "create_webhook_subscription",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Create Webhook Subscription",
        },
        title="Create Webhook Subscription",
    )
    delivery_url: str = Field(
        ..., title="Delivery URL", description="The HTTPS endpoint that receives event payloads"
    )
    events: str = Field(
        "incident.triggered,incident.resolved",
        title="Events",
        description="Event types to subscribe to, comma-separated (e.g. incident.triggered)",
    )
    service_id: Optional[str] = Field(
        None,
        title="Service",
        description="Scope the subscription to a single service (optional; account-wide if blank)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )


class PagerDutyListPrioritiesConfig(BaseModel):
    """List incident priorities defined on the account."""

    operation: Literal["list_priorities"] = Field(
        "list_priorities",
        json_schema_extra={
            "const": "list_priorities",
            "ui:hidden": True,
            "x-category": "Reference",
            "x-is-trigger": False,
            "x-display-name": "List Priorities",
        },
        title="List Priorities",
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class PagerDutyIncidentTriggerConfig(BaseModel):
    """Fire the workflow when an incident event is delivered (triggered, acknowledged, resolved...)."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_incident_event"] = Field(
        "on_incident_event",
        json_schema_extra={
            "const": "on_incident_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Incident Event",
        },
        title="On Incident Event",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="PagerDuty posts incident events here. A V3 webhook subscription is registered automatically when you connect credentials.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ---------------------------------------------------------------------------
# Family: incidents-extended
# ---------------------------------------------------------------------------


class PagerDutyGetAlertConfig(BaseModel):
    """Retrieve a single alert on an incident by its ID."""

    operation: Literal["get_alert"] = Field(
        "get_alert",
        json_schema_extra={"const": "get_alert", "ui:hidden": True, "x-category": "Incident Details", "x-is-trigger": False, "x-display-name": "Get Alert"},
        title="Get Alert",
    )
    incident_id: str = Field(..., title="Incident ID", description="The incident the alert belongs to")
    alert_id: str = Field(..., title="Alert ID", description="The alert to retrieve")


class PagerDutyUpdateAlertConfig(BaseModel):
    """Resolve an alert or reassociate it to a different incident."""

    operation: Literal["update_alert"] = Field(
        "update_alert",
        json_schema_extra={"const": "update_alert", "ui:hidden": True, "x-category": "Incident Details", "x-is-trigger": False, "x-display-name": "Update Alert"},
        title="Update Alert",
    )
    incident_id: str = Field(..., title="Incident ID", description="The incident the alert currently belongs to")
    alert_id: str = Field(..., title="Alert ID", description="The alert to update")
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Set the alert status",
        json_schema_extra={
            "enum": ["", "triggered", "resolved"],
            "enumNames": ["No change", "Triggered", "Resolved"],
            "x-enum-searchable": True,
        },
    )
    new_incident_id: Optional[str] = Field(
        None,
        title="Reassociate to Incident",
        description="Move the alert onto this incident (optional)",
    )


class PagerDutyManageAlertsConfig(BaseModel):
    """Bulk resolve or reassociate multiple alerts on an incident."""

    operation: Literal["manage_alerts"] = Field(
        "manage_alerts",
        json_schema_extra={"const": "manage_alerts", "ui:hidden": True, "x-category": "Incident Details", "x-is-trigger": False, "x-display-name": "Manage Alerts (Bulk)"},
        title="Manage Alerts (Bulk)",
    )
    incident_id: str = Field(..., title="Incident ID", description="The incident whose alerts to update")
    alert_ids: str = Field(..., title="Alert IDs", description="Alert IDs to update, comma-separated")
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Set the status on all listed alerts",
        json_schema_extra={
            "enum": ["", "triggered", "resolved"],
            "enumNames": ["No change", "Triggered", "Resolved"],
            "x-enum-searchable": True,
        },
    )
    new_incident_id: Optional[str] = Field(
        None,
        title="Reassociate to Incident",
        description="Move all listed alerts onto this incident (optional)",
    )


class PagerDutyGetIncidentCustomFieldsConfig(BaseModel):
    """Get the custom field values set on an incident."""

    operation: Literal["get_incident_custom_fields"] = Field(
        "get_incident_custom_fields",
        json_schema_extra={"const": "get_incident_custom_fields", "ui:hidden": True, "x-category": "Incident Details", "x-is-trigger": False, "x-display-name": "Get Incident Custom Field Values"},
        title="Get Incident Custom Field Values",
    )
    incident_id: str = Field(..., title="Incident ID", description="The incident whose custom field values to fetch")


class PagerDutyUpdateIncidentCustomFieldsConfig(BaseModel):
    """Set custom field values on an incident."""

    operation: Literal["update_incident_custom_fields"] = Field(
        "update_incident_custom_fields",
        json_schema_extra={"const": "update_incident_custom_fields", "ui:hidden": True, "x-category": "Incident Details", "x-is-trigger": False, "x-display-name": "Update Incident Custom Field Values"},
        title="Update Incident Custom Field Values",
    )
    incident_id: str = Field(..., title="Incident ID", description="The incident whose custom field values to set")
    custom_fields: str = Field(
        ...,
        title="Custom Field Values",
        description='A JSON array of field-value objects, e.g. [{"id": "PXYZ123", "value": "production"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyListRelatedChangeEventsConfig(BaseModel):
    """List change events related to an incident."""

    operation: Literal["list_related_change_events"] = Field(
        "list_related_change_events",
        json_schema_extra={"const": "list_related_change_events", "ui:hidden": True, "x-category": "Incident Details", "x-is-trigger": False, "x-display-name": "List Related Change Events"},
        title="List Related Change Events",
    )
    incident_id: str = Field(..., title="Incident ID", description="The incident whose related change events to list")


class PagerDutyGetPastIncidentsConfig(BaseModel):
    """List past incidents similar to this one."""

    operation: Literal["get_past_incidents"] = Field(
        "get_past_incidents",
        json_schema_extra={"const": "get_past_incidents", "ui:hidden": True, "x-category": "Incident Details", "x-is-trigger": False, "x-display-name": "Get Past Incidents"},
        title="Get Past Incidents",
    )
    incident_id: str = Field(..., title="Incident ID", description="The incident to find past similar incidents for")
    limit: Optional[str] = Field(
        "5", title="Limit", description="Max number of past incidents to return (1-5)"
    )


class PagerDutyGetRelatedIncidentsConfig(BaseModel):
    """List incidents related to this one."""

    operation: Literal["get_related_incidents"] = Field(
        "get_related_incidents",
        json_schema_extra={"const": "get_related_incidents", "ui:hidden": True, "x-category": "Incident Details", "x-is-trigger": False, "x-display-name": "Get Related Incidents"},
        title="Get Related Incidents",
    )
    incident_id: str = Field(..., title="Incident ID", description="The incident to find related incidents for")


class PagerDutyGetOutlierIncidentConfig(BaseModel):
    """Get outlier information for an incident relative to its service's history."""

    operation: Literal["get_outlier_incident"] = Field(
        "get_outlier_incident",
        json_schema_extra={"const": "get_outlier_incident", "ui:hidden": True, "x-category": "Incident Details", "x-is-trigger": False, "x-display-name": "Get Outlier Incident"},
        title="Get Outlier Incident",
    )
    incident_id: str = Field(..., title="Incident ID", description="The incident to get outlier analysis for")


class PagerDutyListStatusUpdateSubscribersConfig(BaseModel):
    """List the users and teams subscribed to an incident's status updates."""

    operation: Literal["list_status_update_subscribers"] = Field(
        "list_status_update_subscribers",
        json_schema_extra={"const": "list_status_update_subscribers", "ui:hidden": True, "x-category": "Incident Details", "x-is-trigger": False, "x-display-name": "List Status Update Subscribers"},
        title="List Status Update Subscribers",
    )
    incident_id: str = Field(..., title="Incident ID", description="The incident whose subscribers to list")


class PagerDutyAddStatusUpdateSubscribersConfig(BaseModel):
    """Subscribe users or teams to an incident's status updates."""

    operation: Literal["add_status_update_subscribers"] = Field(
        "add_status_update_subscribers",
        json_schema_extra={"const": "add_status_update_subscribers", "ui:hidden": True, "x-category": "Incident Details", "x-is-trigger": False, "x-display-name": "Add Status Update Subscribers"},
        title="Add Status Update Subscribers",
    )
    incident_id: str = Field(..., title="Incident ID", description="The incident to add subscribers to")
    subscriber_ids: str = Field(
        ..., title="Subscriber IDs", description="User or team IDs to subscribe, comma-separated"
    )
    subscriber_type: str = Field(
        "user",
        title="Subscriber Type",
        description="Whether the IDs refer to users or teams",
        json_schema_extra={
            "enum": ["user", "team"],
            "enumNames": ["User", "Team"],
            "x-enum-searchable": True,
        },
    )


class PagerDutyRemoveStatusUpdateSubscriberConfig(BaseModel):
    """Unsubscribe users or teams from an incident's status updates."""

    operation: Literal["remove_status_update_subscriber"] = Field(
        "remove_status_update_subscriber",
        json_schema_extra={"const": "remove_status_update_subscriber", "ui:hidden": True, "x-category": "Incident Details", "x-is-trigger": False, "x-display-name": "Remove Status Update Subscriber"},
        title="Remove Status Update Subscriber",
    )
    incident_id: str = Field(..., title="Incident ID", description="The incident to remove subscribers from")
    subscriber_ids: str = Field(
        ..., title="Subscriber IDs", description="User or team IDs to unsubscribe, comma-separated"
    )
    subscriber_type: str = Field(
        "user",
        title="Subscriber Type",
        description="Whether the IDs refer to users or teams",
        json_schema_extra={
            "enum": ["user", "team"],
            "enumNames": ["User", "Team"],
            "x-enum-searchable": True,
        },
    )


class PagerDutyListGlobalLogEntriesConfig(BaseModel):
    """List log entries across the whole account (all incidents)."""

    operation: Literal["list_global_log_entries"] = Field(
        "list_global_log_entries",
        json_schema_extra={"const": "list_global_log_entries", "ui:hidden": True, "x-category": "Incident Details", "x-is-trigger": False, "x-display-name": "List Log Entries (Account)"},
        title="List Log Entries (Account)",
    )
    since: Optional[str] = Field(
        None, title="Since", description="ISO 8601 lower bound on the created_at range (optional)"
    )
    until: Optional[str] = Field(
        None, title="Until", description="ISO 8601 upper bound on the created_at range (optional)"
    )
    team_ids: Optional[str] = Field(
        None,
        title="Team",
        description="Filter to log entries for these teams",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "team_ids",
                "placeholder": "Select a team...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste team ID(s), comma-separated",
            }
        },
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of log entries to return (1-100)"
    )


class PagerDutyGetLogEntryConfig(BaseModel):
    """Retrieve a single log entry by its ID."""

    operation: Literal["get_log_entry"] = Field(
        "get_log_entry",
        json_schema_extra={"const": "get_log_entry", "ui:hidden": True, "x-category": "Incident Details", "x-is-trigger": False, "x-display-name": "Get Log Entry"},
        title="Get Log Entry",
    )
    log_entry_id: str = Field(..., title="Log Entry ID", description="The log entry to retrieve")


# ---------------------------------------------------------------------------
# Family: services-full
# ---------------------------------------------------------------------------


class PagerDutyDeleteServiceConfig(BaseModel):
    """Delete a service and all its integrations."""

    operation: Literal["delete_service"] = Field(
        "delete_service",
        json_schema_extra={
            "const": "delete_service",
            "ui:hidden": True,
            "x-category": "Services",
            "x-is-trigger": False,
            "x-display-name": "Delete Service",
        },
        title="Delete Service",
    )
    service_id: str = Field(
        ...,
        title="Service",
        description="The service to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )


class PagerDutyAssociateServiceDependenciesConfig(BaseModel):
    """Associate one or more service dependency relationships (dependent -> supporting)."""

    operation: Literal["associate_service_dependencies"] = Field(
        "associate_service_dependencies",
        json_schema_extra={
            "const": "associate_service_dependencies",
            "ui:hidden": True,
            "x-category": "Service Dependencies",
            "x-is-trigger": False,
            "x-display-name": "Associate Service Dependencies",
        },
        title="Associate Service Dependencies",
    )
    relationships: str = Field(
        ...,
        title="Relationships (JSON)",
        description=(
            'A JSON array of dependency relationships. Each item has a "dependent_service" '
            'and a "supporting_service", each an object with "id" and "type" '
            '(technical_service_reference or business_service_reference). Example: '
            '[{"dependent_service":{"id":"PBIZ001","type":"business_service_reference"},'
            '"supporting_service":{"id":"PTECH01","type":"technical_service_reference"}}]'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyDisassociateServiceDependenciesConfig(BaseModel):
    """Remove one or more service dependency relationships."""

    operation: Literal["disassociate_service_dependencies"] = Field(
        "disassociate_service_dependencies",
        json_schema_extra={
            "const": "disassociate_service_dependencies",
            "ui:hidden": True,
            "x-category": "Service Dependencies",
            "x-is-trigger": False,
            "x-display-name": "Disassociate Service Dependencies",
        },
        title="Disassociate Service Dependencies",
    )
    relationships: str = Field(
        ...,
        title="Relationships (JSON)",
        description=(
            'A JSON array of dependency relationships to remove. Each item has a '
            '"dependent_service" and a "supporting_service", each an object with "id" and '
            '"type" (technical_service_reference or business_service_reference).'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyGetTechnicalServiceDependenciesConfig(BaseModel):
    """List the dependencies of a technical service."""

    operation: Literal["get_technical_service_dependencies"] = Field(
        "get_technical_service_dependencies",
        json_schema_extra={
            "const": "get_technical_service_dependencies",
            "ui:hidden": True,
            "x-category": "Service Dependencies",
            "x-is-trigger": False,
            "x-display-name": "Get Technical Service Dependencies",
        },
        title="Get Technical Service Dependencies",
    )
    service_id: str = Field(
        ...,
        title="Technical Service",
        description="The technical service whose dependencies to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )


class PagerDutyGetBusinessServiceDependenciesConfig(BaseModel):
    """List the dependencies of a business service."""

    operation: Literal["get_business_service_dependencies"] = Field(
        "get_business_service_dependencies",
        json_schema_extra={
            "const": "get_business_service_dependencies",
            "ui:hidden": True,
            "x-category": "Service Dependencies",
            "x-is-trigger": False,
            "x-display-name": "Get Business Service Dependencies",
        },
        title="Get Business Service Dependencies",
    )
    business_service_id: str = Field(
        ...,
        title="Business Service ID",
        description="The ID of the business service whose dependencies to list",
    )


class PagerDutyCreateServiceIntegrationConfig(BaseModel):
    """Add an integration (e.g. Events API v2) to a service."""

    operation: Literal["create_service_integration"] = Field(
        "create_service_integration",
        json_schema_extra={
            "const": "create_service_integration",
            "ui:hidden": True,
            "x-category": "Service Integrations",
            "x-is-trigger": False,
            "x-display-name": "Create Service Integration",
        },
        title="Create Service Integration",
    )
    service_id: str = Field(
        ...,
        title="Service",
        description="The service to add the integration to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )
    integration_type: str = Field(
        "events_api_v2_inbound_integration",
        title="Integration Type",
        description="The type of integration to create",
        json_schema_extra={
            "enum": [
                "events_api_v2_inbound_integration",
                "generic_events_api_inbound_integration",
                "generic_email_inbound_integration",
                "aws_cloudwatch_inbound_integration",
                "event_transformer_api_inbound_integration",
                "cloudkick_inbound_integration",
                "keynote_inbound_integration",
                "nagios_inbound_integration",
                "pingdom_inbound_integration",
                "sql_monitor_inbound_integration",
            ],
            "enumNames": [
                "Events API v2",
                "Events API v1",
                "Integration via Email",
                "AWS CloudWatch",
                "Custom Event Transformer",
                "Cloudkick",
                "Keynote",
                "Nagios",
                "Pingdom",
                "SQL Monitor",
            ],
            "x-enum-searchable": True,
        },
    )
    name: Optional[str] = Field(
        None, title="Name", description="A name for the integration (optional)"
    )
    integration_email: Optional[str] = Field(
        None,
        title="Integration Email",
        description="The inbound email address (required for email integrations)",
    )
    vendor_id: Optional[str] = Field(
        None,
        title="Vendor ID",
        description="The ID of the vendor for this integration (optional)",
    )


class PagerDutyGetServiceIntegrationConfig(BaseModel):
    """Retrieve a single integration on a service."""

    operation: Literal["get_service_integration"] = Field(
        "get_service_integration",
        json_schema_extra={
            "const": "get_service_integration",
            "ui:hidden": True,
            "x-category": "Service Integrations",
            "x-is-trigger": False,
            "x-display-name": "Get Service Integration",
        },
        title="Get Service Integration",
    )
    service_id: str = Field(
        ...,
        title="Service",
        description="The service the integration belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )
    integration_id: str = Field(
        ..., title="Integration ID", description="The ID of the integration to retrieve"
    )


class PagerDutyUpdateServiceIntegrationConfig(BaseModel):
    """Update an existing integration on a service."""

    operation: Literal["update_service_integration"] = Field(
        "update_service_integration",
        json_schema_extra={
            "const": "update_service_integration",
            "ui:hidden": True,
            "x-category": "Service Integrations",
            "x-is-trigger": False,
            "x-display-name": "Update Service Integration",
        },
        title="Update Service Integration",
    )
    service_id: str = Field(
        ...,
        title="Service",
        description="The service the integration belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )
    integration_id: str = Field(
        ..., title="Integration ID", description="The ID of the integration to update"
    )
    integration_type: str = Field(
        "events_api_v2_inbound_integration",
        title="Integration Type",
        description="The integration type (PagerDuty requires this on update)",
        json_schema_extra={
            "enum": [
                "events_api_v2_inbound_integration",
                "generic_events_api_inbound_integration",
                "generic_email_inbound_integration",
                "aws_cloudwatch_inbound_integration",
                "event_transformer_api_inbound_integration",
                "cloudkick_inbound_integration",
                "keynote_inbound_integration",
                "nagios_inbound_integration",
                "pingdom_inbound_integration",
                "sql_monitor_inbound_integration",
            ],
            "enumNames": [
                "Events API v2",
                "Events API v1",
                "Integration via Email",
                "AWS CloudWatch",
                "Custom Event Transformer",
                "Cloudkick",
                "Keynote",
                "Nagios",
                "Pingdom",
                "SQL Monitor",
            ],
            "x-enum-searchable": True,
        },
    )
    name: Optional[str] = Field(
        None, title="Name", description="New integration name (optional)"
    )
    integration_email: Optional[str] = Field(
        None,
        title="Integration Email",
        description="New inbound email address for email integrations (optional)",
    )
    vendor_id: Optional[str] = Field(
        None, title="Vendor ID", description="New vendor ID for this integration (optional)"
    )


class PagerDutyListServiceEventRulesConfig(BaseModel):
    """List the event rules configured on a service."""

    operation: Literal["list_service_event_rules"] = Field(
        "list_service_event_rules",
        json_schema_extra={
            "const": "list_service_event_rules",
            "ui:hidden": True,
            "x-category": "Service Event Rules",
            "x-is-trigger": False,
            "x-display-name": "List Service Event Rules",
        },
        title="List Service Event Rules",
    )
    service_id: str = Field(
        ...,
        title="Service",
        description="The service whose event rules to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )


class PagerDutyCreateServiceEventRuleConfig(BaseModel):
    """Create an event rule on a service."""

    operation: Literal["create_service_event_rule"] = Field(
        "create_service_event_rule",
        json_schema_extra={
            "const": "create_service_event_rule",
            "ui:hidden": True,
            "x-category": "Service Event Rules",
            "x-is-trigger": False,
            "x-display-name": "Create Service Event Rule",
        },
        title="Create Service Event Rule",
    )
    service_id: str = Field(
        ...,
        title="Service",
        description="The service to add the event rule to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )
    conditions: Optional[str] = Field(
        None,
        title="Conditions (JSON)",
        description=(
            'A JSON object with "operator" (and/or) and "subconditions". Example: '
            '{"operator":"and","subconditions":[{"operator":"contains",'
            '"parameters":{"path":"payload.summary","value":"cpu"}}]}'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    actions: Optional[str] = Field(
        None,
        title="Actions (JSON)",
        description=(
            'A JSON object of actions to apply. Example: '
            '{"annotate":{"value":"note"},"severity":{"value":"critical"},'
            '"suppress":{"value":false}}'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    position: Optional[str] = Field(
        None,
        title="Position",
        description="Zero-based position of the rule in evaluation order (optional)",
    )
    disabled: Optional[str] = Field(
        None,
        title="Disabled",
        description="Whether the rule is disabled",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Default", "Yes (disabled)", "No (enabled)"],
            "x-enum-searchable": True,
        },
    )


class PagerDutyGetServiceEventRuleConfig(BaseModel):
    """Retrieve a single event rule from a service."""

    operation: Literal["get_service_event_rule"] = Field(
        "get_service_event_rule",
        json_schema_extra={
            "const": "get_service_event_rule",
            "ui:hidden": True,
            "x-category": "Service Event Rules",
            "x-is-trigger": False,
            "x-display-name": "Get Service Event Rule",
        },
        title="Get Service Event Rule",
    )
    service_id: str = Field(
        ...,
        title="Service",
        description="The service the event rule belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )
    rule_id: str = Field(
        ..., title="Rule ID", description="The ID of the event rule to retrieve"
    )


class PagerDutyUpdateServiceEventRuleConfig(BaseModel):
    """Update an existing event rule on a service."""

    operation: Literal["update_service_event_rule"] = Field(
        "update_service_event_rule",
        json_schema_extra={
            "const": "update_service_event_rule",
            "ui:hidden": True,
            "x-category": "Service Event Rules",
            "x-is-trigger": False,
            "x-display-name": "Update Service Event Rule",
        },
        title="Update Service Event Rule",
    )
    service_id: str = Field(
        ...,
        title="Service",
        description="The service the event rule belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )
    rule_id: str = Field(
        ..., title="Rule ID", description="The ID of the event rule to update"
    )
    conditions: Optional[str] = Field(
        None,
        title="Conditions (JSON)",
        description=(
            'A JSON object with "operator" (and/or) and "subconditions" (optional). '
            'Replaces the rule conditions when provided.'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    actions: Optional[str] = Field(
        None,
        title="Actions (JSON)",
        description="A JSON object of actions (optional). Replaces the rule actions when provided.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    position: Optional[str] = Field(
        None,
        title="Position",
        description="Zero-based position of the rule in evaluation order (optional)",
    )
    disabled: Optional[str] = Field(
        None,
        title="Disabled",
        description="Whether the rule is disabled",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["No change", "Yes (disabled)", "No (enabled)"],
            "x-enum-searchable": True,
        },
    )


class PagerDutyDeleteServiceEventRuleConfig(BaseModel):
    """Delete an event rule from a service."""

    operation: Literal["delete_service_event_rule"] = Field(
        "delete_service_event_rule",
        json_schema_extra={
            "const": "delete_service_event_rule",
            "ui:hidden": True,
            "x-category": "Service Event Rules",
            "x-is-trigger": False,
            "x-display-name": "Delete Service Event Rule",
        },
        title="Delete Service Event Rule",
    )
    service_id: str = Field(
        ...,
        title="Service",
        description="The service the event rule belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )
    rule_id: str = Field(
        ..., title="Rule ID", description="The ID of the event rule to delete"
    )


# ---------------------------------------------------------------------------
# Family: schedules-full
# ---------------------------------------------------------------------------


class PagerDutyCreateScheduleConfig(BaseModel):
    """Create an on-call schedule from a full schedule definition (JSON)."""

    operation: Literal["create_schedule"] = Field(
        "create_schedule",
        json_schema_extra={
            "const": "create_schedule",
            "x-creates-resource": True,
            "x-resource-type": "pagerduty_schedule",
            "x-resource-id-path": "data.schedule.id",
            "ui:hidden": True,
            "x-category": "Schedules & On-Call",
            "x-is-trigger": False,
            "x-display-name": "Create Schedule",
        },
        title="Create Schedule",
    )
    schedule: str = Field(
        ...,
        title="Schedule Definition (JSON)",
        description=(
            "The schedule object as JSON (the request's inner \"schedule\" value). Must include "
            "time_zone and schedule_layers, e.g. "
            "{\"name\":\"Daytime\",\"time_zone\":\"America/New_York\",\"schedule_layers\":[...]}."
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyUpdateScheduleConfig(BaseModel):
    """Replace an existing schedule with a full schedule definition (JSON)."""

    operation: Literal["update_schedule"] = Field(
        "update_schedule",
        json_schema_extra={
            "const": "update_schedule",
            "ui:hidden": True,
            "x-category": "Schedules & On-Call",
            "x-is-trigger": False,
            "x-display-name": "Update Schedule",
        },
        title="Update Schedule",
    )
    schedule_id: str = Field(
        ...,
        title="Schedule",
        description="The schedule to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "schedule_id",
                "placeholder": "Select a schedule...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste schedule ID",
            }
        },
    )
    schedule: str = Field(
        ...,
        title="Schedule Definition (JSON)",
        description=(
            "The full schedule object as JSON (the request's inner \"schedule\" value). PUT replaces "
            "the schedule, so include time_zone and schedule_layers."
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyDeleteScheduleConfig(BaseModel):
    """Delete an on-call schedule."""

    operation: Literal["delete_schedule"] = Field(
        "delete_schedule",
        json_schema_extra={
            "const": "delete_schedule",
            "ui:hidden": True,
            "x-category": "Schedules & On-Call",
            "x-is-trigger": False,
            "x-display-name": "Delete Schedule",
        },
        title="Delete Schedule",
    )
    schedule_id: str = Field(
        ...,
        title="Schedule",
        description="The schedule to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "schedule_id",
                "placeholder": "Select a schedule...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste schedule ID",
            }
        },
    )


class PagerDutyPreviewScheduleConfig(BaseModel):
    """Preview the rendered on-call entries for a schedule definition without saving it."""

    operation: Literal["preview_schedule"] = Field(
        "preview_schedule",
        json_schema_extra={
            "const": "preview_schedule",
            "ui:hidden": True,
            "x-category": "Schedules & On-Call",
            "x-is-trigger": False,
            "x-display-name": "Preview Schedule",
        },
        title="Preview Schedule",
    )
    schedule: str = Field(
        ...,
        title="Schedule Definition (JSON)",
        description=(
            "The schedule object as JSON (the request's inner \"schedule\" value) to render. "
            "Include time_zone and schedule_layers."
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    since: Optional[str] = Field(
        None, title="Since", description="ISO 8601 start of the range to render (optional)"
    )
    until: Optional[str] = Field(
        None, title="Until", description="ISO 8601 end of the range to render (optional)"
    )
    overflow: Optional[str] = Field(
        "false",
        title="Overflow",
        description="Include on-call entries that extend beyond the since/until bounds",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class PagerDutyListUsersOnScheduleConfig(BaseModel):
    """List the users on-call in a schedule over a time range."""

    operation: Literal["list_users_on_schedule"] = Field(
        "list_users_on_schedule",
        json_schema_extra={
            "const": "list_users_on_schedule",
            "ui:hidden": True,
            "x-category": "Schedules & On-Call",
            "x-is-trigger": False,
            "x-display-name": "List Users On Schedule",
        },
        title="List Users On Schedule",
    )
    schedule_id: str = Field(
        ...,
        title="Schedule",
        description="The schedule whose on-call users to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "schedule_id",
                "placeholder": "Select a schedule...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste schedule ID",
            }
        },
    )
    since: Optional[str] = Field(
        None, title="Since", description="ISO 8601 start of the range (optional)"
    )
    until: Optional[str] = Field(
        None, title="Until", description="ISO 8601 end of the range (optional)"
    )


class PagerDutyListOverridesConfig(BaseModel):
    """List overrides on a schedule within a time range."""

    operation: Literal["list_overrides"] = Field(
        "list_overrides",
        json_schema_extra={
            "const": "list_overrides",
            "ui:hidden": True,
            "x-category": "Schedules & On-Call",
            "x-is-trigger": False,
            "x-display-name": "List Overrides",
        },
        title="List Overrides",
    )
    schedule_id: str = Field(
        ...,
        title="Schedule",
        description="The schedule whose overrides to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "schedule_id",
                "placeholder": "Select a schedule...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste schedule ID",
            }
        },
    )
    since: Optional[str] = Field(
        None, title="Since", description="ISO 8601 start of the range (max 3-month span)"
    )
    until: Optional[str] = Field(
        None, title="Until", description="ISO 8601 end of the range"
    )
    editable: Optional[str] = Field(
        "false",
        title="Editable Only",
        description="Only return future, editable overrides",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class PagerDutyCreateOverrideConfig(BaseModel):
    """Create an on-call override for a user over a time range."""

    operation: Literal["create_override"] = Field(
        "create_override",
        json_schema_extra={
            "const": "create_override",
            "ui:hidden": True,
            "x-category": "Schedules & On-Call",
            "x-is-trigger": False,
            "x-display-name": "Create Override",
        },
        title="Create Override",
    )
    schedule_id: str = Field(
        ...,
        title="Schedule",
        description="The schedule to add the override to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "schedule_id",
                "placeholder": "Select a schedule...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste schedule ID",
            }
        },
    )
    user_id: str = Field(
        ...,
        title="User",
        description="The user who covers the override",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            }
        },
    )
    start: str = Field(
        ..., title="Start", description="ISO 8601 start of the override"
    )
    end: str = Field(
        ..., title="End", description="ISO 8601 end of the override"
    )


class PagerDutyDeleteOverrideConfig(BaseModel):
    """Remove an override from a schedule."""

    operation: Literal["delete_override"] = Field(
        "delete_override",
        json_schema_extra={
            "const": "delete_override",
            "ui:hidden": True,
            "x-category": "Schedules & On-Call",
            "x-is-trigger": False,
            "x-display-name": "Delete Override",
        },
        title="Delete Override",
    )
    schedule_id: str = Field(
        ...,
        title="Schedule",
        description="The schedule the override belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "schedule_id",
                "placeholder": "Select a schedule...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste schedule ID",
            }
        },
    )
    override_id: str = Field(
        ..., title="Override ID", description="The ID of the override to delete"
    )


class PagerDutyGetEscalationPolicyConfig(BaseModel):
    """Retrieve a single escalation policy by ID."""

    operation: Literal["get_escalation_policy"] = Field(
        "get_escalation_policy",
        json_schema_extra={
            "const": "get_escalation_policy",
            "ui:hidden": True,
            "x-category": "Escalation Policies",
            "x-is-trigger": False,
            "x-display-name": "Get Escalation Policy",
        },
        title="Get Escalation Policy",
    )
    escalation_policy_id: str = Field(
        ...,
        title="Escalation Policy",
        description="The escalation policy to retrieve",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "escalation_policy_id",
                "placeholder": "Select an escalation policy...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste escalation policy ID",
            }
        },
    )


class PagerDutyUpdateEscalationPolicyConfig(BaseModel):
    """Update an escalation policy's name, description, or escalation rules."""

    operation: Literal["update_escalation_policy"] = Field(
        "update_escalation_policy",
        json_schema_extra={
            "const": "update_escalation_policy",
            "ui:hidden": True,
            "x-category": "Escalation Policies",
            "x-is-trigger": False,
            "x-display-name": "Update Escalation Policy",
        },
        title="Update Escalation Policy",
    )
    escalation_policy_id: str = Field(
        ...,
        title="Escalation Policy",
        description="The escalation policy to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "escalation_policy_id",
                "placeholder": "Select an escalation policy...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste escalation policy ID",
            }
        },
    )
    name: Optional[str] = Field(
        None, title="Name", description="New escalation policy name (optional)"
    )
    description: Optional[str] = Field(
        None, title="Description", description="New description (optional)"
    )
    escalation_rules: Optional[str] = Field(
        None,
        title="Escalation Rules (JSON)",
        description=(
            "Replacement escalation_rules array as JSON (optional), e.g. "
            "[{\"escalation_delay_in_minutes\":30,\"targets\":[{\"id\":\"PABC123\",\"type\":\"user_reference\"}]}]."
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyDeleteEscalationPolicyConfig(BaseModel):
    """Delete an escalation policy."""

    operation: Literal["delete_escalation_policy"] = Field(
        "delete_escalation_policy",
        json_schema_extra={
            "const": "delete_escalation_policy",
            "ui:hidden": True,
            "x-category": "Escalation Policies",
            "x-is-trigger": False,
            "x-display-name": "Delete Escalation Policy",
        },
        title="Delete Escalation Policy",
    )
    escalation_policy_id: str = Field(
        ...,
        title="Escalation Policy",
        description="The escalation policy to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "escalation_policy_id",
                "placeholder": "Select an escalation policy...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste escalation policy ID",
            }
        },
    )


# ---------------------------------------------------------------------------
# Family: users-teams-full
# ---------------------------------------------------------------------------


class PagerDutyUpdateUserConfig(BaseModel):
    """Update an existing user's profile (requires the From Email credential field)."""

    operation: Literal["update_user"] = Field(
        "update_user",
        json_schema_extra={
            "const": "update_user",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Update User",
        },
        title="Update User",
    )
    user_id: str = Field(
        ...,
        title="User",
        description="The user to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            }
        },
    )
    name: Optional[str] = Field(None, title="Name", description="New full name (optional)")
    email: Optional[str] = Field(None, title="Email", description="New email address (optional)")
    role: Optional[str] = Field(
        None,
        title="Role",
        description="New account role (optional)",
        json_schema_extra={
            "enum": ["", "admin", "user", "limited_user", "observer", "restricted_access", "read_only_user", "read_only_limited_user"],
            "enumNames": ["No change", "Admin", "User", "Limited User", "Observer", "Restricted Access", "Read-Only User", "Read-Only Limited User"],
            "x-enum-searchable": True,
        },
    )
    time_zone: Optional[str] = Field(
        None, title="Time Zone", description="Preferred time zone name, e.g. America/New_York (optional)"
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="A short description / job title (optional)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyDeleteUserConfig(BaseModel):
    """Delete a user from the account (requires the From Email credential field)."""

    operation: Literal["delete_user"] = Field(
        "delete_user",
        json_schema_extra={
            "const": "delete_user",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Delete User",
        },
        title="Delete User",
    )
    user_id: str = Field(
        ...,
        title="User",
        description="The user to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            }
        },
    )


class PagerDutyListContactMethodsConfig(BaseModel):
    """List a user's contact methods (email, phone, SMS, push)."""

    operation: Literal["list_contact_methods"] = Field(
        "list_contact_methods",
        json_schema_extra={
            "const": "list_contact_methods",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "List Contact Methods",
        },
        title="List Contact Methods",
    )
    user_id: str = Field(
        ...,
        title="User",
        description="The user whose contact methods to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            }
        },
    )


class PagerDutyCreateContactMethodConfig(BaseModel):
    """Add a contact method to a user (requires the From Email credential field)."""

    operation: Literal["create_contact_method"] = Field(
        "create_contact_method",
        json_schema_extra={
            "const": "create_contact_method",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Create Contact Method",
        },
        title="Create Contact Method",
    )
    user_id: str = Field(
        ...,
        title="User",
        description="The user to add the contact method to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            }
        },
    )
    type: str = Field(
        "email_contact_method",
        title="Type",
        description="The kind of contact method to create",
        json_schema_extra={
            "enum": ["email_contact_method", "phone_contact_method", "sms_contact_method"],
            "enumNames": ["Email", "Phone", "SMS"],
            "x-enum-searchable": True,
        },
    )
    label: str = Field(..., title="Label", description="A label for the contact method, e.g. \"Work\" or \"Mobile\"")
    address: str = Field(
        ..., title="Address", description="The email address or phone number (digits only for phone/SMS)"
    )
    country_code: Optional[str] = Field(
        None, title="Country Code", description="The 1-3 digit calling code (required for phone/SMS, e.g. 1)"
    )


class PagerDutyGetContactMethodConfig(BaseModel):
    """Retrieve a single contact method of a user."""

    operation: Literal["get_contact_method"] = Field(
        "get_contact_method",
        json_schema_extra={
            "const": "get_contact_method",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Get Contact Method",
        },
        title="Get Contact Method",
    )
    user_id: str = Field(
        ...,
        title="User",
        description="The user the contact method belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            }
        },
    )
    contact_method_id: str = Field(
        ..., title="Contact Method ID", description="The ID of the contact method to retrieve"
    )


class PagerDutyUpdateContactMethodConfig(BaseModel):
    """Update a user's contact method (requires the From Email credential field)."""

    operation: Literal["update_contact_method"] = Field(
        "update_contact_method",
        json_schema_extra={
            "const": "update_contact_method",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Update Contact Method",
        },
        title="Update Contact Method",
    )
    user_id: str = Field(
        ...,
        title="User",
        description="The user the contact method belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            }
        },
    )
    contact_method_id: str = Field(
        ..., title="Contact Method ID", description="The ID of the contact method to update"
    )
    type: str = Field(
        "email_contact_method",
        title="Type",
        description="The contact method type (must match the existing method)",
        json_schema_extra={
            "enum": ["email_contact_method", "phone_contact_method", "sms_contact_method"],
            "enumNames": ["Email", "Phone", "SMS"],
            "x-enum-searchable": True,
        },
    )
    label: Optional[str] = Field(None, title="Label", description="New label (optional)")
    address: Optional[str] = Field(None, title="Address", description="New email/phone address (optional)")
    country_code: Optional[str] = Field(
        None, title="Country Code", description="New 1-3 digit calling code for phone/SMS (optional)"
    )


class PagerDutyDeleteContactMethodConfig(BaseModel):
    """Delete a user's contact method (requires the From Email credential field)."""

    operation: Literal["delete_contact_method"] = Field(
        "delete_contact_method",
        json_schema_extra={
            "const": "delete_contact_method",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Delete Contact Method",
        },
        title="Delete Contact Method",
    )
    user_id: str = Field(
        ...,
        title="User",
        description="The user the contact method belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            }
        },
    )
    contact_method_id: str = Field(
        ..., title="Contact Method ID", description="The ID of the contact method to delete"
    )


class PagerDutyListNotificationRulesConfig(BaseModel):
    """List a user's notification rules."""

    operation: Literal["list_notification_rules"] = Field(
        "list_notification_rules",
        json_schema_extra={
            "const": "list_notification_rules",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "List Notification Rules",
        },
        title="List Notification Rules",
    )
    user_id: str = Field(
        ...,
        title="User",
        description="The user whose notification rules to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            }
        },
    )


class PagerDutyCreateNotificationRuleConfig(BaseModel):
    """Add a notification rule to a user (requires the From Email credential field)."""

    operation: Literal["create_notification_rule"] = Field(
        "create_notification_rule",
        json_schema_extra={
            "const": "create_notification_rule",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Create Notification Rule",
        },
        title="Create Notification Rule",
    )
    user_id: str = Field(
        ...,
        title="User",
        description="The user to add the notification rule to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            }
        },
    )
    contact_method_id: str = Field(
        ..., title="Contact Method ID", description="The contact method this rule notifies"
    )
    contact_method_type: str = Field(
        "email_contact_method_reference",
        title="Contact Method Type",
        description="The reference type of the contact method",
        json_schema_extra={
            "enum": ["email_contact_method_reference", "phone_contact_method_reference", "sms_contact_method_reference", "push_notification_contact_method_reference"],
            "enumNames": ["Email", "Phone", "SMS", "Push"],
            "x-enum-searchable": True,
        },
    )
    start_delay_in_minutes: str = Field(
        "0", title="Start Delay (minutes)", description="Minutes to wait before firing this rule"
    )
    urgency: str = Field(
        "high",
        title="Urgency",
        description="Which incident urgency this rule applies to",
        json_schema_extra={
            "enum": ["high", "low"],
            "enumNames": ["High", "Low"],
            "x-enum-searchable": True,
        },
    )


class PagerDutyGetNotificationRuleConfig(BaseModel):
    """Retrieve a single notification rule of a user."""

    operation: Literal["get_notification_rule"] = Field(
        "get_notification_rule",
        json_schema_extra={
            "const": "get_notification_rule",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Get Notification Rule",
        },
        title="Get Notification Rule",
    )
    user_id: str = Field(
        ...,
        title="User",
        description="The user the notification rule belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            }
        },
    )
    notification_rule_id: str = Field(
        ..., title="Notification Rule ID", description="The ID of the notification rule to retrieve"
    )


class PagerDutyUpdateNotificationRuleConfig(BaseModel):
    """Update a user's notification rule (requires the From Email credential field)."""

    operation: Literal["update_notification_rule"] = Field(
        "update_notification_rule",
        json_schema_extra={
            "const": "update_notification_rule",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Update Notification Rule",
        },
        title="Update Notification Rule",
    )
    user_id: str = Field(
        ...,
        title="User",
        description="The user the notification rule belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            }
        },
    )
    notification_rule_id: str = Field(
        ..., title="Notification Rule ID", description="The ID of the notification rule to update"
    )
    start_delay_in_minutes: Optional[str] = Field(
        None, title="Start Delay (minutes)", description="New delay before firing, in minutes (optional)"
    )
    urgency: Optional[str] = Field(
        None,
        title="Urgency",
        description="New urgency this rule applies to (optional)",
        json_schema_extra={
            "enum": ["", "high", "low"],
            "enumNames": ["No change", "High", "Low"],
            "x-enum-searchable": True,
        },
    )
    contact_method_id: Optional[str] = Field(
        None, title="Contact Method ID", description="Point the rule at a different contact method (optional)"
    )
    contact_method_type: str = Field(
        "email_contact_method_reference",
        title="Contact Method Type",
        description="The reference type of the contact method (used only when changing it)",
        json_schema_extra={
            "enum": ["email_contact_method_reference", "phone_contact_method_reference", "sms_contact_method_reference", "push_notification_contact_method_reference"],
            "enumNames": ["Email", "Phone", "SMS", "Push"],
            "x-enum-searchable": True,
        },
    )


class PagerDutyDeleteNotificationRuleConfig(BaseModel):
    """Delete a user's notification rule (requires the From Email credential field)."""

    operation: Literal["delete_notification_rule"] = Field(
        "delete_notification_rule",
        json_schema_extra={
            "const": "delete_notification_rule",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Delete Notification Rule",
        },
        title="Delete Notification Rule",
    )
    user_id: str = Field(
        ...,
        title="User",
        description="The user the notification rule belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            }
        },
    )
    notification_rule_id: str = Field(
        ..., title="Notification Rule ID", description="The ID of the notification rule to delete"
    )


class PagerDutyGetTeamConfig(BaseModel):
    """Retrieve a single team by ID."""

    operation: Literal["get_team"] = Field(
        "get_team",
        json_schema_extra={
            "const": "get_team",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Get Team",
        },
        title="Get Team",
    )
    team_id: str = Field(..., title="Team ID", description="The ID of the team to retrieve")


class PagerDutyCreateTeamConfig(BaseModel):
    """Create a new team (requires the From Email credential field)."""

    operation: Literal["create_team"] = Field(
        "create_team",
        json_schema_extra={
            "const": "create_team",
            "x-creates-resource": True,
            "x-resource-type": "pagerduty_team",
            "x-resource-id-path": "data.team.id",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Create Team",
        },
        title="Create Team",
    )
    name: str = Field(..., title="Name", description="The name of the new team")
    description: Optional[str] = Field(
        None, title="Description", description="A description of the team (optional)"
    )


class PagerDutyUpdateTeamConfig(BaseModel):
    """Update an existing team (requires the From Email credential field)."""

    operation: Literal["update_team"] = Field(
        "update_team",
        json_schema_extra={
            "const": "update_team",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Update Team",
        },
        title="Update Team",
    )
    team_id: str = Field(..., title="Team ID", description="The ID of the team to update")
    name: Optional[str] = Field(None, title="Name", description="New team name (optional)")
    description: Optional[str] = Field(
        None, title="Description", description="New team description (optional)"
    )


class PagerDutyDeleteTeamConfig(BaseModel):
    """Delete a team (requires the From Email credential field)."""

    operation: Literal["delete_team"] = Field(
        "delete_team",
        json_schema_extra={
            "const": "delete_team",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Delete Team",
        },
        title="Delete Team",
    )
    team_id: str = Field(..., title="Team ID", description="The ID of the team to delete")


class PagerDutyListTeamMembersConfig(BaseModel):
    """List the members of a team along with their roles."""

    operation: Literal["list_team_members"] = Field(
        "list_team_members",
        json_schema_extra={
            "const": "list_team_members",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "List Team Members",
        },
        title="List Team Members",
    )
    team_id: str = Field(..., title="Team ID", description="The team whose members to list")


class PagerDutyAddTeamMemberConfig(BaseModel):
    """Add a user to a team with a role (requires the From Email credential field)."""

    operation: Literal["add_team_member"] = Field(
        "add_team_member",
        json_schema_extra={
            "const": "add_team_member",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Add Team Member",
        },
        title="Add Team Member",
    )
    team_id: str = Field(..., title="Team ID", description="The team to add the user to")
    user_id: str = Field(
        ...,
        title="User",
        description="The user to add to the team",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            }
        },
    )
    role: str = Field(
        "manager",
        title="Role",
        description="The user's role on the team",
        json_schema_extra={
            "enum": ["observer", "responder", "manager"],
            "enumNames": ["Observer", "Responder", "Manager"],
            "x-enum-searchable": True,
        },
    )


class PagerDutyRemoveTeamMemberConfig(BaseModel):
    """Remove a user from a team (requires the From Email credential field)."""

    operation: Literal["remove_team_member"] = Field(
        "remove_team_member",
        json_schema_extra={
            "const": "remove_team_member",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Remove Team Member",
        },
        title="Remove Team Member",
    )
    team_id: str = Field(..., title="Team ID", description="The team to remove the user from")
    user_id: str = Field(
        ...,
        title="User",
        description="The user to remove from the team",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            }
        },
    )


class PagerDutyAssociateTeamEscalationPolicyConfig(BaseModel):
    """Associate an escalation policy with a team (requires the From Email credential field)."""

    operation: Literal["associate_team_escalation_policy"] = Field(
        "associate_team_escalation_policy",
        json_schema_extra={
            "const": "associate_team_escalation_policy",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Associate Escalation Policy",
        },
        title="Associate Escalation Policy",
    )
    team_id: str = Field(..., title="Team ID", description="The team to associate the escalation policy with")
    escalation_policy_id: str = Field(
        ...,
        title="Escalation Policy",
        description="The escalation policy to associate",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "escalation_policy_id",
                "placeholder": "Select an escalation policy...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste escalation policy ID",
            }
        },
    )


class PagerDutyRemoveTeamEscalationPolicyConfig(BaseModel):
    """Remove an escalation policy's association with a team (requires the From Email credential field)."""

    operation: Literal["remove_team_escalation_policy"] = Field(
        "remove_team_escalation_policy",
        json_schema_extra={
            "const": "remove_team_escalation_policy",
            "ui:hidden": True,
            "x-category": "Users & Teams",
            "x-is-trigger": False,
            "x-display-name": "Remove Escalation Policy",
        },
        title="Remove Escalation Policy",
    )
    team_id: str = Field(..., title="Team ID", description="The team to remove the escalation policy from")
    escalation_policy_id: str = Field(
        ...,
        title="Escalation Policy",
        description="The escalation policy to disassociate",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "escalation_policy_id",
                "placeholder": "Select an escalation policy...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste escalation policy ID",
            }
        },
    )


# ---------------------------------------------------------------------------
# Family: maintenance-webhooks-full
# ---------------------------------------------------------------------------


class PagerDutyGetMaintenanceWindowConfig(BaseModel):
    """Retrieve a single maintenance window by ID."""

    operation: Literal["get_maintenance_window"] = Field(
        "get_maintenance_window",
        json_schema_extra={
            "const": "get_maintenance_window",
            "ui:hidden": True,
            "x-category": "Maintenance Windows",
            "x-is-trigger": False,
            "x-display-name": "Get Maintenance Window",
        },
        title="Get Maintenance Window",
    )
    maintenance_window_id: str = Field(
        ..., title="Maintenance Window ID", description="The ID of the maintenance window to retrieve"
    )


class PagerDutyUpdateMaintenanceWindowConfig(BaseModel):
    """Update a maintenance window's time range, affected services, or description."""

    operation: Literal["update_maintenance_window"] = Field(
        "update_maintenance_window",
        json_schema_extra={
            "const": "update_maintenance_window",
            "ui:hidden": True,
            "x-category": "Maintenance Windows",
            "x-is-trigger": False,
            "x-display-name": "Update Maintenance Window",
        },
        title="Update Maintenance Window",
    )
    maintenance_window_id: str = Field(
        ..., title="Maintenance Window ID", description="The ID of the maintenance window to update"
    )
    start_time: Optional[str] = Field(
        None, title="Start Time", description="New ISO 8601 start time (optional)"
    )
    end_time: Optional[str] = Field(
        None, title="End Time", description="New ISO 8601 end time (optional)"
    )
    service_ids: Optional[str] = Field(
        None,
        title="Services",
        description="Replace the affected services (optional)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_ids",
                "placeholder": "Select service(s)...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID(s), comma-separated",
            }
        },
    )
    description: Optional[str] = Field(
        None, title="Description", description="New maintenance window description (optional)"
    )


class PagerDutyDeleteMaintenanceWindowConfig(BaseModel):
    """Delete (cancel) a maintenance window."""

    operation: Literal["delete_maintenance_window"] = Field(
        "delete_maintenance_window",
        json_schema_extra={
            "const": "delete_maintenance_window",
            "ui:hidden": True,
            "x-category": "Maintenance Windows",
            "x-is-trigger": False,
            "x-display-name": "Delete Maintenance Window",
        },
        title="Delete Maintenance Window",
    )
    maintenance_window_id: str = Field(
        ..., title="Maintenance Window ID", description="The ID of the maintenance window to delete"
    )


class PagerDutyGetWebhookSubscriptionConfig(BaseModel):
    """Retrieve a single V3 webhook subscription by ID."""

    operation: Literal["get_webhook_subscription"] = Field(
        "get_webhook_subscription",
        json_schema_extra={
            "const": "get_webhook_subscription",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Get Webhook Subscription",
        },
        title="Get Webhook Subscription",
    )
    webhook_subscription_id: str = Field(
        ..., title="Webhook Subscription ID", description="The ID of the webhook subscription to retrieve"
    )


class PagerDutyUpdateWebhookSubscriptionConfig(BaseModel):
    """Update a V3 webhook subscription's delivery URL, events, or description."""

    operation: Literal["update_webhook_subscription"] = Field(
        "update_webhook_subscription",
        json_schema_extra={
            "const": "update_webhook_subscription",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Update Webhook Subscription",
        },
        title="Update Webhook Subscription",
    )
    webhook_subscription_id: str = Field(
        ..., title="Webhook Subscription ID", description="The ID of the webhook subscription to update"
    )
    delivery_url: Optional[str] = Field(
        None, title="Delivery URL", description="New HTTPS endpoint that receives event payloads (optional)"
    )
    events: Optional[str] = Field(
        None,
        title="Events",
        description="Replace the subscribed event types, comma-separated (e.g. incident.triggered) (optional)",
    )
    description: Optional[str] = Field(
        None, title="Description", description="New subscription description (optional)"
    )


class PagerDutyDeleteWebhookSubscriptionConfig(BaseModel):
    """Delete a V3 webhook subscription."""

    operation: Literal["delete_webhook_subscription"] = Field(
        "delete_webhook_subscription",
        json_schema_extra={
            "const": "delete_webhook_subscription",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Delete Webhook Subscription",
        },
        title="Delete Webhook Subscription",
    )
    webhook_subscription_id: str = Field(
        ..., title="Webhook Subscription ID", description="The ID of the webhook subscription to delete"
    )


class PagerDutyEnableWebhookSubscriptionConfig(BaseModel):
    """Enable (activate) a V3 webhook subscription."""

    operation: Literal["enable_webhook_subscription"] = Field(
        "enable_webhook_subscription",
        json_schema_extra={
            "const": "enable_webhook_subscription",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Enable Webhook Subscription",
        },
        title="Enable Webhook Subscription",
    )
    webhook_subscription_id: str = Field(
        ..., title="Webhook Subscription ID", description="The ID of the webhook subscription to enable"
    )


class PagerDutyDisableWebhookSubscriptionConfig(BaseModel):
    """Disable (deactivate) a V3 webhook subscription."""

    operation: Literal["disable_webhook_subscription"] = Field(
        "disable_webhook_subscription",
        json_schema_extra={
            "const": "disable_webhook_subscription",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Disable Webhook Subscription",
        },
        title="Disable Webhook Subscription",
    )
    webhook_subscription_id: str = Field(
        ..., title="Webhook Subscription ID", description="The ID of the webhook subscription to disable"
    )


class PagerDutyPingWebhookSubscriptionConfig(BaseModel):
    """Send a test (ping) event to a V3 webhook subscription's delivery URL."""

    operation: Literal["ping_webhook_subscription"] = Field(
        "ping_webhook_subscription",
        json_schema_extra={
            "const": "ping_webhook_subscription",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Ping Webhook Subscription",
        },
        title="Ping Webhook Subscription",
    )
    webhook_subscription_id: str = Field(
        ..., title="Webhook Subscription ID", description="The ID of the webhook subscription to test"
    )


class PagerDutyListExtensionsConfig(BaseModel):
    """List extensions (outbound integrations attached to services)."""

    operation: Literal["list_extensions"] = Field(
        "list_extensions",
        json_schema_extra={
            "const": "list_extensions",
            "ui:hidden": True,
            "x-category": "Extensions",
            "x-is-trigger": False,
            "x-display-name": "List Extensions",
        },
        title="List Extensions",
    )
    query: Optional[str] = Field(
        None, title="Query", description="Filter extensions by name (optional)"
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of extensions to return (1-100)"
    )


class PagerDutyCreateExtensionConfig(BaseModel):
    """Create an extension attaching an outbound integration (schema) to one or more services."""

    operation: Literal["create_extension"] = Field(
        "create_extension",
        json_schema_extra={
            "const": "create_extension",
            "x-creates-resource": True,
            "x-resource-type": "pagerduty_extension",
            "x-resource-id-path": "data.extension.id",
            "ui:hidden": True,
            "x-category": "Extensions",
            "x-is-trigger": False,
            "x-display-name": "Create Extension",
        },
        title="Create Extension",
    )
    name: str = Field(..., title="Name", description="The name of the extension")
    extension_schema_id: str = Field(
        ...,
        title="Extension Schema ID",
        description="The extension schema (vendor) this extension implements. Use List Extension Schemas to find IDs.",
    )
    service_ids: str = Field(
        ...,
        title="Services",
        description="Services this extension is attached to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_ids",
                "placeholder": "Select service(s)...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID(s), comma-separated",
            }
        },
    )
    endpoint_url: Optional[str] = Field(
        None,
        title="Endpoint URL",
        description="The URL events are delivered to (required by webhook-style schemas)",
    )


class PagerDutyGetExtensionConfig(BaseModel):
    """Retrieve a single extension by ID."""

    operation: Literal["get_extension"] = Field(
        "get_extension",
        json_schema_extra={
            "const": "get_extension",
            "ui:hidden": True,
            "x-category": "Extensions",
            "x-is-trigger": False,
            "x-display-name": "Get Extension",
        },
        title="Get Extension",
    )
    extension_id: str = Field(
        ..., title="Extension ID", description="The ID of the extension to retrieve"
    )


class PagerDutyUpdateExtensionConfig(BaseModel):
    """Update an extension's name, endpoint URL, schema, or attached services."""

    operation: Literal["update_extension"] = Field(
        "update_extension",
        json_schema_extra={
            "const": "update_extension",
            "ui:hidden": True,
            "x-category": "Extensions",
            "x-is-trigger": False,
            "x-display-name": "Update Extension",
        },
        title="Update Extension",
    )
    extension_id: str = Field(
        ..., title="Extension ID", description="The ID of the extension to update"
    )
    name: Optional[str] = Field(None, title="Name", description="New extension name (optional)")
    endpoint_url: Optional[str] = Field(
        None, title="Endpoint URL", description="New delivery URL (optional)"
    )
    extension_schema_id: Optional[str] = Field(
        None,
        title="Extension Schema ID",
        description="Change the extension schema (vendor) it implements (optional)",
    )
    service_ids: Optional[str] = Field(
        None,
        title="Services",
        description="Replace the attached services (optional)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_ids",
                "placeholder": "Select service(s)...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID(s), comma-separated",
            }
        },
    )


class PagerDutyDeleteExtensionConfig(BaseModel):
    """Delete an extension."""

    operation: Literal["delete_extension"] = Field(
        "delete_extension",
        json_schema_extra={
            "const": "delete_extension",
            "ui:hidden": True,
            "x-category": "Extensions",
            "x-is-trigger": False,
            "x-display-name": "Delete Extension",
        },
        title="Delete Extension",
    )
    extension_id: str = Field(
        ..., title="Extension ID", description="The ID of the extension to delete"
    )


class PagerDutyEnableExtensionConfig(BaseModel):
    """Enable a temporarily disabled extension."""

    operation: Literal["enable_extension"] = Field(
        "enable_extension",
        json_schema_extra={
            "const": "enable_extension",
            "ui:hidden": True,
            "x-category": "Extensions",
            "x-is-trigger": False,
            "x-display-name": "Enable Extension",
        },
        title="Enable Extension",
    )
    extension_id: str = Field(
        ..., title="Extension ID", description="The ID of the extension to enable"
    )


class PagerDutyListExtensionSchemasConfig(BaseModel):
    """List available extension schemas (outbound integration vendors)."""

    operation: Literal["list_extension_schemas"] = Field(
        "list_extension_schemas",
        json_schema_extra={
            "const": "list_extension_schemas",
            "ui:hidden": True,
            "x-category": "Extensions",
            "x-is-trigger": False,
            "x-display-name": "List Extension Schemas",
        },
        title="List Extension Schemas",
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of extension schemas to return (1-100)"
    )


class PagerDutyGetExtensionSchemaConfig(BaseModel):
    """Retrieve a single extension schema by ID."""

    operation: Literal["get_extension_schema"] = Field(
        "get_extension_schema",
        json_schema_extra={
            "const": "get_extension_schema",
            "ui:hidden": True,
            "x-category": "Extensions",
            "x-is-trigger": False,
            "x-display-name": "Get Extension Schema",
        },
        title="Get Extension Schema",
    )
    extension_schema_id: str = Field(
        ..., title="Extension Schema ID", description="The ID of the extension schema to retrieve"
    )


# ---------------------------------------------------------------------------
# Family: event-orchestrations
# ---------------------------------------------------------------------------


class PagerDutyListEventOrchestrationsConfig(BaseModel):
    """List all Event Orchestrations on the account."""

    operation: Literal["list_event_orchestrations"] = Field(
        "list_event_orchestrations",
        json_schema_extra={
            "const": "list_event_orchestrations",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "List Event Orchestrations",
        },
        title="List Event Orchestrations",
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of orchestrations to return (1-100)"
    )


class PagerDutyGetEventOrchestrationConfig(BaseModel):
    """Retrieve a single Event Orchestration by ID."""

    operation: Literal["get_event_orchestration"] = Field(
        "get_event_orchestration",
        json_schema_extra={
            "const": "get_event_orchestration",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "Get Event Orchestration",
        },
        title="Get Event Orchestration",
    )
    orchestration_id: str = Field(
        ..., title="Orchestration ID", description="The Event Orchestration to retrieve"
    )


class PagerDutyCreateEventOrchestrationConfig(BaseModel):
    """Create a new Event Orchestration."""

    operation: Literal["create_event_orchestration"] = Field(
        "create_event_orchestration",
        json_schema_extra={
            "const": "create_event_orchestration",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "Create Event Orchestration",
        },
        title="Create Event Orchestration",
    )
    name: str = Field(..., title="Name", description="The name of the Event Orchestration")
    description: Optional[str] = Field(
        None, title="Description", description="A description of what the orchestration is used for (optional)"
    )
    team_id: Optional[str] = Field(
        None,
        title="Team ID",
        description="Reference to the team that owns the orchestration (optional)",
    )


class PagerDutyUpdateEventOrchestrationConfig(BaseModel):
    """Update an existing Event Orchestration's name or description."""

    operation: Literal["update_event_orchestration"] = Field(
        "update_event_orchestration",
        json_schema_extra={
            "const": "update_event_orchestration",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "Update Event Orchestration",
        },
        title="Update Event Orchestration",
    )
    orchestration_id: str = Field(
        ..., title="Orchestration ID", description="The Event Orchestration to update"
    )
    name: Optional[str] = Field(None, title="Name", description="New name (optional)")
    description: Optional[str] = Field(
        None, title="Description", description="New description (optional)"
    )


class PagerDutyDeleteEventOrchestrationConfig(BaseModel):
    """Delete an Event Orchestration by ID."""

    operation: Literal["delete_event_orchestration"] = Field(
        "delete_event_orchestration",
        json_schema_extra={
            "const": "delete_event_orchestration",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "Delete Event Orchestration",
        },
        title="Delete Event Orchestration",
    )
    orchestration_id: str = Field(
        ..., title="Orchestration ID", description="The Event Orchestration to delete"
    )


class PagerDutyGetOrchestrationRouterConfig(BaseModel):
    """Get the Router (the top-level routing rules) of an Event Orchestration."""

    operation: Literal["get_orchestration_router"] = Field(
        "get_orchestration_router",
        json_schema_extra={
            "const": "get_orchestration_router",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "Get Orchestration Router",
        },
        title="Get Orchestration Router",
    )
    orchestration_id: str = Field(
        ..., title="Orchestration ID", description="The Event Orchestration whose Router to fetch"
    )


class PagerDutyUpdateOrchestrationRouterConfig(BaseModel):
    """Replace the Router rules of an Event Orchestration."""

    operation: Literal["update_orchestration_router"] = Field(
        "update_orchestration_router",
        json_schema_extra={
            "const": "update_orchestration_router",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "Update Orchestration Router",
        },
        title="Update Orchestration Router",
    )
    orchestration_id: str = Field(
        ..., title="Orchestration ID", description="The Event Orchestration whose Router to update"
    )
    orchestration_path: str = Field(
        ...,
        title="Orchestration Path (JSON)",
        description='Full router orchestration_path object as JSON (e.g. {"sets": [...], "catch_all": {...}}). Replaces the existing router.',
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyGetOrchestrationGlobalConfig(BaseModel):
    """Get the Global orchestration rules of an Event Orchestration."""

    operation: Literal["get_orchestration_global"] = Field(
        "get_orchestration_global",
        json_schema_extra={
            "const": "get_orchestration_global",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "Get Orchestration Global",
        },
        title="Get Orchestration Global",
    )
    orchestration_id: str = Field(
        ..., title="Orchestration ID", description="The Event Orchestration whose Global rules to fetch"
    )


class PagerDutyUpdateOrchestrationGlobalConfig(BaseModel):
    """Replace the Global orchestration rules of an Event Orchestration."""

    operation: Literal["update_orchestration_global"] = Field(
        "update_orchestration_global",
        json_schema_extra={
            "const": "update_orchestration_global",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "Update Orchestration Global",
        },
        title="Update Orchestration Global",
    )
    orchestration_id: str = Field(
        ..., title="Orchestration ID", description="The Event Orchestration whose Global rules to update"
    )
    orchestration_path: str = Field(
        ...,
        title="Orchestration Path (JSON)",
        description='Full global orchestration_path object as JSON (e.g. {"sets": [...], "catch_all": {...}}). Replaces the existing global rules.',
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyGetServiceOrchestrationConfig(BaseModel):
    """Get the Service Orchestration rules for a service."""

    operation: Literal["get_service_orchestration"] = Field(
        "get_service_orchestration",
        json_schema_extra={
            "const": "get_service_orchestration",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "Get Service Orchestration",
        },
        title="Get Service Orchestration",
    )
    service_id: str = Field(
        ...,
        title="Service",
        description="The service whose orchestration rules to fetch",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )


class PagerDutyUpdateServiceOrchestrationConfig(BaseModel):
    """Replace the Service Orchestration rules for a service."""

    operation: Literal["update_service_orchestration"] = Field(
        "update_service_orchestration",
        json_schema_extra={
            "const": "update_service_orchestration",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "Update Service Orchestration",
        },
        title="Update Service Orchestration",
    )
    service_id: str = Field(
        ...,
        title="Service",
        description="The service whose orchestration rules to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )
    orchestration_path: str = Field(
        ...,
        title="Orchestration Path (JSON)",
        description='Full service orchestration_path object as JSON (e.g. {"sets": [...], "catch_all": {...}}). Replaces the existing service orchestration.',
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyGetServiceOrchestrationActiveConfig(BaseModel):
    """Get whether Service Orchestration is active (routing events) for a service."""

    operation: Literal["get_service_orchestration_active"] = Field(
        "get_service_orchestration_active",
        json_schema_extra={
            "const": "get_service_orchestration_active",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "Get Service Orchestration Active",
        },
        title="Get Service Orchestration Active",
    )
    service_id: str = Field(
        ...,
        title="Service",
        description="The service whose active status to fetch",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )


class PagerDutySetServiceOrchestrationActiveConfig(BaseModel):
    """Enable or disable Service Orchestration routing for a service."""

    operation: Literal["set_service_orchestration_active"] = Field(
        "set_service_orchestration_active",
        json_schema_extra={
            "const": "set_service_orchestration_active",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "Set Service Orchestration Active",
        },
        title="Set Service Orchestration Active",
    )
    service_id: str = Field(
        ...,
        title="Service",
        description="The service whose active status to set",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "service_id",
                "placeholder": "Select a service...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste service ID",
            }
        },
    )
    active: str = Field(
        "true",
        title="Active",
        description="Whether Service Orchestration routes events for this service",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class PagerDutyListOrchestrationIntegrationsConfig(BaseModel):
    """List the integrations (event routing keys) of an Event Orchestration."""

    operation: Literal["list_orchestration_integrations"] = Field(
        "list_orchestration_integrations",
        json_schema_extra={
            "const": "list_orchestration_integrations",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "List Orchestration Integrations",
        },
        title="List Orchestration Integrations",
    )
    orchestration_id: str = Field(
        ..., title="Orchestration ID", description="The Event Orchestration whose integrations to list"
    )


class PagerDutyCreateOrchestrationIntegrationConfig(BaseModel):
    """Create a new integration (event routing key) on an Event Orchestration."""

    operation: Literal["create_orchestration_integration"] = Field(
        "create_orchestration_integration",
        json_schema_extra={
            "const": "create_orchestration_integration",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "Create Orchestration Integration",
        },
        title="Create Orchestration Integration",
    )
    orchestration_id: str = Field(
        ..., title="Orchestration ID", description="The Event Orchestration to add the integration to"
    )
    label: str = Field(..., title="Label", description="A name/label for the new integration")


class PagerDutyGetOrchestrationIntegrationConfig(BaseModel):
    """Retrieve a single integration of an Event Orchestration."""

    operation: Literal["get_orchestration_integration"] = Field(
        "get_orchestration_integration",
        json_schema_extra={
            "const": "get_orchestration_integration",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "Get Orchestration Integration",
        },
        title="Get Orchestration Integration",
    )
    orchestration_id: str = Field(
        ..., title="Orchestration ID", description="The Event Orchestration the integration belongs to"
    )
    integration_id: str = Field(
        ..., title="Integration ID", description="The integration to retrieve"
    )


class PagerDutyUpdateOrchestrationIntegrationConfig(BaseModel):
    """Update the label of an Event Orchestration integration."""

    operation: Literal["update_orchestration_integration"] = Field(
        "update_orchestration_integration",
        json_schema_extra={
            "const": "update_orchestration_integration",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "Update Orchestration Integration",
        },
        title="Update Orchestration Integration",
    )
    orchestration_id: str = Field(
        ..., title="Orchestration ID", description="The Event Orchestration the integration belongs to"
    )
    integration_id: str = Field(
        ..., title="Integration ID", description="The integration to update"
    )
    label: str = Field(..., title="Label", description="The new label for the integration")


class PagerDutyDeleteOrchestrationIntegrationConfig(BaseModel):
    """Delete an integration from an Event Orchestration."""

    operation: Literal["delete_orchestration_integration"] = Field(
        "delete_orchestration_integration",
        json_schema_extra={
            "const": "delete_orchestration_integration",
            "ui:hidden": True,
            "x-category": "Event Orchestrations",
            "x-is-trigger": False,
            "x-display-name": "Delete Orchestration Integration",
        },
        title="Delete Orchestration Integration",
    )
    orchestration_id: str = Field(
        ..., title="Orchestration ID", description="The Event Orchestration the integration belongs to"
    )
    integration_id: str = Field(
        ..., title="Integration ID", description="The integration to delete"
    )


class PagerDutyListRulesetsConfig(BaseModel):
    """List legacy Event Rulesets on the account."""

    operation: Literal["list_rulesets"] = Field(
        "list_rulesets",
        json_schema_extra={
            "const": "list_rulesets",
            "ui:hidden": True,
            "x-category": "Event Rulesets (Legacy)",
            "x-is-trigger": False,
            "x-display-name": "List Rulesets",
        },
        title="List Rulesets",
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of rulesets to return (1-100)"
    )


class PagerDutyCreateRulesetConfig(BaseModel):
    """Create a new legacy Event Ruleset."""

    operation: Literal["create_ruleset"] = Field(
        "create_ruleset",
        json_schema_extra={
            "const": "create_ruleset",
            "ui:hidden": True,
            "x-category": "Event Rulesets (Legacy)",
            "x-is-trigger": False,
            "x-display-name": "Create Ruleset",
        },
        title="Create Ruleset",
    )
    name: str = Field(..., title="Name", description="The name of the ruleset")


class PagerDutyGetRulesetConfig(BaseModel):
    """Retrieve a single legacy Event Ruleset by ID."""

    operation: Literal["get_ruleset"] = Field(
        "get_ruleset",
        json_schema_extra={
            "const": "get_ruleset",
            "ui:hidden": True,
            "x-category": "Event Rulesets (Legacy)",
            "x-is-trigger": False,
            "x-display-name": "Get Ruleset",
        },
        title="Get Ruleset",
    )
    ruleset_id: str = Field(..., title="Ruleset ID", description="The ruleset to retrieve")


class PagerDutyUpdateRulesetConfig(BaseModel):
    """Update a legacy Event Ruleset's name."""

    operation: Literal["update_ruleset"] = Field(
        "update_ruleset",
        json_schema_extra={
            "const": "update_ruleset",
            "ui:hidden": True,
            "x-category": "Event Rulesets (Legacy)",
            "x-is-trigger": False,
            "x-display-name": "Update Ruleset",
        },
        title="Update Ruleset",
    )
    ruleset_id: str = Field(..., title="Ruleset ID", description="The ruleset to update")
    name: Optional[str] = Field(None, title="Name", description="New ruleset name (optional)")


class PagerDutyDeleteRulesetConfig(BaseModel):
    """Delete a legacy Event Ruleset by ID."""

    operation: Literal["delete_ruleset"] = Field(
        "delete_ruleset",
        json_schema_extra={
            "const": "delete_ruleset",
            "ui:hidden": True,
            "x-category": "Event Rulesets (Legacy)",
            "x-is-trigger": False,
            "x-display-name": "Delete Ruleset",
        },
        title="Delete Ruleset",
    )
    ruleset_id: str = Field(..., title="Ruleset ID", description="The ruleset to delete")


class PagerDutyListRulesetRulesConfig(BaseModel):
    """List the event rules of a legacy Ruleset."""

    operation: Literal["list_ruleset_rules"] = Field(
        "list_ruleset_rules",
        json_schema_extra={
            "const": "list_ruleset_rules",
            "ui:hidden": True,
            "x-category": "Event Rulesets (Legacy)",
            "x-is-trigger": False,
            "x-display-name": "List Ruleset Rules",
        },
        title="List Ruleset Rules",
    )
    ruleset_id: str = Field(..., title="Ruleset ID", description="The ruleset whose rules to list")


class PagerDutyCreateRulesetRuleConfig(BaseModel):
    """Create an event rule on a legacy Ruleset."""

    operation: Literal["create_ruleset_rule"] = Field(
        "create_ruleset_rule",
        json_schema_extra={
            "const": "create_ruleset_rule",
            "ui:hidden": True,
            "x-category": "Event Rulesets (Legacy)",
            "x-is-trigger": False,
            "x-display-name": "Create Ruleset Rule",
        },
        title="Create Ruleset Rule",
    )
    ruleset_id: str = Field(..., title="Ruleset ID", description="The ruleset to add the rule to")
    rule: str = Field(
        ...,
        title="Rule (JSON)",
        description='The event rule object as JSON (e.g. {"conditions": {...}, "actions": {...}}).',
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyGetRulesetRuleConfig(BaseModel):
    """Retrieve a single event rule from a legacy Ruleset."""

    operation: Literal["get_ruleset_rule"] = Field(
        "get_ruleset_rule",
        json_schema_extra={
            "const": "get_ruleset_rule",
            "ui:hidden": True,
            "x-category": "Event Rulesets (Legacy)",
            "x-is-trigger": False,
            "x-display-name": "Get Ruleset Rule",
        },
        title="Get Ruleset Rule",
    )
    ruleset_id: str = Field(..., title="Ruleset ID", description="The ruleset the rule belongs to")
    rule_id: str = Field(..., title="Rule ID", description="The rule to retrieve")


class PagerDutyUpdateRulesetRuleConfig(BaseModel):
    """Update an event rule on a legacy Ruleset."""

    operation: Literal["update_ruleset_rule"] = Field(
        "update_ruleset_rule",
        json_schema_extra={
            "const": "update_ruleset_rule",
            "ui:hidden": True,
            "x-category": "Event Rulesets (Legacy)",
            "x-is-trigger": False,
            "x-display-name": "Update Ruleset Rule",
        },
        title="Update Ruleset Rule",
    )
    ruleset_id: str = Field(..., title="Ruleset ID", description="The ruleset the rule belongs to")
    rule_id: str = Field(..., title="Rule ID", description="The rule to update")
    rule: str = Field(
        ...,
        title="Rule (JSON)",
        description='The updated event rule object as JSON (e.g. {"conditions": {...}, "actions": {...}}).',
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyDeleteRulesetRuleConfig(BaseModel):
    """Delete an event rule from a legacy Ruleset."""

    operation: Literal["delete_ruleset_rule"] = Field(
        "delete_ruleset_rule",
        json_schema_extra={
            "const": "delete_ruleset_rule",
            "ui:hidden": True,
            "x-category": "Event Rulesets (Legacy)",
            "x-is-trigger": False,
            "x-display-name": "Delete Ruleset Rule",
        },
        title="Delete Ruleset Rule",
    )
    ruleset_id: str = Field(..., title="Ruleset ID", description="The ruleset the rule belongs to")
    rule_id: str = Field(..., title="Rule ID", description="The rule to delete")


# ---------------------------------------------------------------------------
# Family: response-automation-workflows
# ---------------------------------------------------------------------------


class PagerDutyListResponsePlaysConfig(BaseModel):
    """List response plays, optionally filtered by name."""

    operation: Literal["list_response_plays"] = Field(
        "list_response_plays",
        json_schema_extra={"const": "list_response_plays", "ui:hidden": True, "x-category": "Response Plays", "x-is-trigger": False, "x-display-name": "List Response Plays"},
        title="List Response Plays",
    )
    query: Optional[str] = Field(None, title="Query", description="Filter response plays by name (optional)")


class PagerDutyGetResponsePlayConfig(BaseModel):
    """Retrieve a single response play by ID."""

    operation: Literal["get_response_play"] = Field(
        "get_response_play",
        json_schema_extra={"const": "get_response_play", "ui:hidden": True, "x-category": "Response Plays", "x-is-trigger": False, "x-display-name": "Get Response Play"},
        title="Get Response Play",
    )
    response_play_id: str = Field(..., title="Response Play ID", description="The response play to retrieve")


class PagerDutyCreateResponsePlayConfig(BaseModel):
    """Create a response play (requires the From Email credential field)."""

    operation: Literal["create_response_play"] = Field(
        "create_response_play",
        json_schema_extra={"const": "create_response_play", "ui:hidden": True,
            "x-creates-resource": True,
            "x-resource-type": "pagerduty_response_play",
            "x-resource-id-path": "data.response_play.id", "x-category": "Response Plays", "x-is-trigger": False, "x-display-name": "Create Response Play"},
        title="Create Response Play",
    )
    name: str = Field(..., title="Name", description="The name of the response play")
    description: Optional[str] = Field(None, title="Description", description="A description of the response play (optional)")
    additional_fields_json: Optional[str] = Field(
        None,
        title="Advanced Fields (JSON)",
        description="Optional JSON object merged into the response_play body (subscribers, responders, escalation_rules, conference_number, runnability, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyUpdateResponsePlayConfig(BaseModel):
    """Update an existing response play (requires the From Email credential field)."""

    operation: Literal["update_response_play"] = Field(
        "update_response_play",
        json_schema_extra={"const": "update_response_play", "ui:hidden": True, "x-category": "Response Plays", "x-is-trigger": False, "x-display-name": "Update Response Play"},
        title="Update Response Play",
    )
    response_play_id: str = Field(..., title="Response Play ID", description="The response play to update")
    name: Optional[str] = Field(None, title="Name", description="New response play name (optional)")
    description: Optional[str] = Field(None, title="Description", description="New description (optional)")
    additional_fields_json: Optional[str] = Field(
        None,
        title="Advanced Fields (JSON)",
        description="Optional JSON object merged into the response_play body (subscribers, responders, escalation_rules, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyDeleteResponsePlayConfig(BaseModel):
    """Delete a response play (requires the From Email credential field)."""

    operation: Literal["delete_response_play"] = Field(
        "delete_response_play",
        json_schema_extra={"const": "delete_response_play", "ui:hidden": True, "x-category": "Response Plays", "x-is-trigger": False, "x-display-name": "Delete Response Play"},
        title="Delete Response Play",
    )
    response_play_id: str = Field(..., title="Response Play ID", description="The response play to delete")


class PagerDutyRunResponsePlayConfig(BaseModel):
    """Run a response play against an incident (requires the From Email credential field)."""

    operation: Literal["run_response_play"] = Field(
        "run_response_play",
        json_schema_extra={"const": "run_response_play", "ui:hidden": True, "x-category": "Response Plays", "x-is-trigger": False, "x-display-name": "Run Response Play"},
        title="Run Response Play",
    )
    response_play_id: str = Field(..., title="Response Play ID", description="The response play to run")
    incident_id: str = Field(..., title="Incident ID", description="The incident to run the response play on")


class PagerDutyListAutomationActionsConfig(BaseModel):
    """List automation actions, optionally filtered by name."""

    operation: Literal["list_automation_actions"] = Field(
        "list_automation_actions",
        json_schema_extra={"const": "list_automation_actions", "ui:hidden": True, "x-category": "Automation Actions", "x-is-trigger": False, "x-display-name": "List Automation Actions"},
        title="List Automation Actions",
    )
    query: Optional[str] = Field(None, title="Query", description="Filter automation actions by name (optional)")
    limit: Optional[str] = Field("25", title="Limit", description="Max number of actions to return (1-100)")


class PagerDutyGetAutomationActionConfig(BaseModel):
    """Retrieve a single automation action by ID."""

    operation: Literal["get_automation_action"] = Field(
        "get_automation_action",
        json_schema_extra={"const": "get_automation_action", "ui:hidden": True, "x-category": "Automation Actions", "x-is-trigger": False, "x-display-name": "Get Automation Action"},
        title="Get Automation Action",
    )
    action_id: str = Field(..., title="Action ID", description="The automation action to retrieve")


class PagerDutyCreateAutomationActionConfig(BaseModel):
    """Create an automation action (requires the From Email credential field)."""

    operation: Literal["create_automation_action"] = Field(
        "create_automation_action",
        json_schema_extra={"const": "create_automation_action", "ui:hidden": True, "x-category": "Automation Actions", "x-is-trigger": False, "x-display-name": "Create Automation Action"},
        title="Create Automation Action",
    )
    name: str = Field(..., title="Name", description="The name of the automation action")
    action_type: str = Field(
        "process_automation",
        title="Action Type",
        description="The type of automation action",
        json_schema_extra={"enum": ["process_automation", "script"], "enumNames": ["Process Automation", "Script"], "x-enum-searchable": True},
    )
    runner_id: str = Field(..., title="Runner ID", description="The automation action runner that executes this action")
    description: Optional[str] = Field(None, title="Description", description="A description of the action (optional)")
    action_data_json: Optional[str] = Field(
        None,
        title="Action Data (JSON)",
        description="JSON action_data_reference (e.g. {\"process_automation_job_id\": \"...\"} or {\"script\": \"...\", \"invocation_command\": \"...\"})",
        json_schema_extra={"ui:widget": "textarea"},
    )
    only_invocable_on_unresolved_incidents: Optional[str] = Field(
        None,
        title="Only On Unresolved Incidents",
        description="Restrict invocation to unresolved incidents",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class PagerDutyUpdateAutomationActionConfig(BaseModel):
    """Update an existing automation action (requires the From Email credential field)."""

    operation: Literal["update_automation_action"] = Field(
        "update_automation_action",
        json_schema_extra={"const": "update_automation_action", "ui:hidden": True, "x-category": "Automation Actions", "x-is-trigger": False, "x-display-name": "Update Automation Action"},
        title="Update Automation Action",
    )
    action_id: str = Field(..., title="Action ID", description="The automation action to update")
    name: Optional[str] = Field(None, title="Name", description="New action name (optional)")
    description: Optional[str] = Field(None, title="Description", description="New description (optional)")
    additional_fields_json: Optional[str] = Field(
        None,
        title="Advanced Fields (JSON)",
        description="Optional JSON object merged into the action body (runner, action_data_reference, action_classification, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyDeleteAutomationActionConfig(BaseModel):
    """Delete an automation action (requires the From Email credential field)."""

    operation: Literal["delete_automation_action"] = Field(
        "delete_automation_action",
        json_schema_extra={"const": "delete_automation_action", "ui:hidden": True, "x-category": "Automation Actions", "x-is-trigger": False, "x-display-name": "Delete Automation Action"},
        title="Delete Automation Action",
    )
    action_id: str = Field(..., title="Action ID", description="The automation action to delete")


class PagerDutyInvokeAutomationActionConfig(BaseModel):
    """Invoke an automation action, optionally against an incident (requires the From Email credential field)."""

    operation: Literal["invoke_automation_action"] = Field(
        "invoke_automation_action",
        json_schema_extra={"const": "invoke_automation_action", "ui:hidden": True, "x-category": "Automation Actions", "x-is-trigger": False, "x-display-name": "Invoke Automation Action"},
        title="Invoke Automation Action",
    )
    action_id: str = Field(..., title="Action ID", description="The automation action to invoke")
    incident_id: Optional[str] = Field(None, title="Incident ID", description="Invoke in the context of this incident (optional)")
    inputs_json: Optional[str] = Field(
        None,
        title="Inputs (JSON)",
        description="Optional JSON array of input parameters, e.g. [{\"name\": \"param\", \"value\": \"x\"}]",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyListInvocationsConfig(BaseModel):
    """List automation action invocations, optionally filtered by action."""

    operation: Literal["list_invocations"] = Field(
        "list_invocations",
        json_schema_extra={"const": "list_invocations", "ui:hidden": True, "x-category": "Automation Actions", "x-is-trigger": False, "x-display-name": "List Invocations"},
        title="List Invocations",
    )
    action_id: Optional[str] = Field(None, title="Action ID", description="Filter invocations to this automation action (optional)")


class PagerDutyGetInvocationConfig(BaseModel):
    """Retrieve a single automation action invocation by ID."""

    operation: Literal["get_invocation"] = Field(
        "get_invocation",
        json_schema_extra={"const": "get_invocation", "ui:hidden": True, "x-category": "Automation Actions", "x-is-trigger": False, "x-display-name": "Get Invocation"},
        title="Get Invocation",
    )
    invocation_id: str = Field(..., title="Invocation ID", description="The invocation to retrieve")


class PagerDutyListRunnersConfig(BaseModel):
    """List automation action runners."""

    operation: Literal["list_runners"] = Field(
        "list_runners",
        json_schema_extra={"const": "list_runners", "ui:hidden": True, "x-category": "Automation Runners", "x-is-trigger": False, "x-display-name": "List Runners"},
        title="List Runners",
    )
    query: Optional[str] = Field(None, title="Query", description="Filter runners by name (optional)")


class PagerDutyGetRunnerConfig(BaseModel):
    """Retrieve a single automation action runner by ID."""

    operation: Literal["get_runner"] = Field(
        "get_runner",
        json_schema_extra={"const": "get_runner", "ui:hidden": True, "x-category": "Automation Runners", "x-is-trigger": False, "x-display-name": "Get Runner"},
        title="Get Runner",
    )
    runner_id: str = Field(..., title="Runner ID", description="The runner to retrieve")


class PagerDutyCreateRunnerConfig(BaseModel):
    """Create an automation action runner (requires the From Email credential field)."""

    operation: Literal["create_runner"] = Field(
        "create_runner",
        json_schema_extra={"const": "create_runner", "ui:hidden": True, "x-category": "Automation Runners", "x-is-trigger": False, "x-display-name": "Create Runner"},
        title="Create Runner",
    )
    name: str = Field(..., title="Name", description="The name of the runner")
    runner_type: str = Field(
        "runbook",
        title="Runner Type",
        description="The type of runner",
        json_schema_extra={"enum": ["runbook", "sidecar"], "enumNames": ["Runbook Automation", "Sidecar"], "x-enum-searchable": True},
    )
    runbook_base_uri: Optional[str] = Field(None, title="Runbook Base URI", description="The base URI of the Runbook Automation instance (required for runbook runners)")
    runbook_api_key: Optional[str] = Field(
        None,
        title="Runbook API Key",
        description="API key for the Runbook Automation instance (required for runbook runners)",
        json_schema_extra={"ui:widget": "password"},
    )
    description: Optional[str] = Field(None, title="Description", description="A description of the runner (optional)")


class PagerDutyUpdateRunnerConfig(BaseModel):
    """Update an existing automation action runner (requires the From Email credential field)."""

    operation: Literal["update_runner"] = Field(
        "update_runner",
        json_schema_extra={"const": "update_runner", "ui:hidden": True, "x-category": "Automation Runners", "x-is-trigger": False, "x-display-name": "Update Runner"},
        title="Update Runner",
    )
    runner_id: str = Field(..., title="Runner ID", description="The runner to update")
    name: Optional[str] = Field(None, title="Name", description="New runner name (optional)")
    description: Optional[str] = Field(None, title="Description", description="New description (optional)")
    additional_fields_json: Optional[str] = Field(
        None,
        title="Advanced Fields (JSON)",
        description="Optional JSON object merged into the runner body (runbook_base_uri, runbook_api_key, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyDeleteRunnerConfig(BaseModel):
    """Delete an automation action runner (requires the From Email credential field)."""

    operation: Literal["delete_runner"] = Field(
        "delete_runner",
        json_schema_extra={"const": "delete_runner", "ui:hidden": True, "x-category": "Automation Runners", "x-is-trigger": False, "x-display-name": "Delete Runner"},
        title="Delete Runner",
    )
    runner_id: str = Field(..., title="Runner ID", description="The runner to delete")


class PagerDutyListIncidentWorkflowsConfig(BaseModel):
    """List incident workflows, optionally filtered by name."""

    operation: Literal["list_incident_workflows"] = Field(
        "list_incident_workflows",
        json_schema_extra={"const": "list_incident_workflows", "ui:hidden": True, "x-category": "Incident Workflows", "x-is-trigger": False, "x-display-name": "List Incident Workflows"},
        title="List Incident Workflows",
    )
    query: Optional[str] = Field(None, title="Query", description="Filter incident workflows by name (optional)")


class PagerDutyGetIncidentWorkflowConfig(BaseModel):
    """Retrieve a single incident workflow by ID."""

    operation: Literal["get_incident_workflow"] = Field(
        "get_incident_workflow",
        json_schema_extra={"const": "get_incident_workflow", "ui:hidden": True, "x-category": "Incident Workflows", "x-is-trigger": False, "x-display-name": "Get Incident Workflow"},
        title="Get Incident Workflow",
    )
    incident_workflow_id: str = Field(..., title="Incident Workflow ID", description="The incident workflow to retrieve")


class PagerDutyCreateIncidentWorkflowConfig(BaseModel):
    """Create an incident workflow (requires the From Email credential field)."""

    operation: Literal["create_incident_workflow"] = Field(
        "create_incident_workflow",
        json_schema_extra={"const": "create_incident_workflow", "ui:hidden": True, "x-category": "Incident Workflows", "x-is-trigger": False, "x-display-name": "Create Incident Workflow"},
        title="Create Incident Workflow",
    )
    name: str = Field(..., title="Name", description="The name of the incident workflow")
    description: Optional[str] = Field(None, title="Description", description="A description of the workflow (optional)")
    steps_json: Optional[str] = Field(
        None,
        title="Steps (JSON)",
        description="JSON array of workflow steps, e.g. [{\"name\": \"...\", \"action\": \"...\", \"inputs\": [...]}]",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyUpdateIncidentWorkflowConfig(BaseModel):
    """Update an existing incident workflow (requires the From Email credential field)."""

    operation: Literal["update_incident_workflow"] = Field(
        "update_incident_workflow",
        json_schema_extra={"const": "update_incident_workflow", "ui:hidden": True, "x-category": "Incident Workflows", "x-is-trigger": False, "x-display-name": "Update Incident Workflow"},
        title="Update Incident Workflow",
    )
    incident_workflow_id: str = Field(..., title="Incident Workflow ID", description="The incident workflow to update")
    name: Optional[str] = Field(None, title="Name", description="New workflow name (optional)")
    description: Optional[str] = Field(None, title="Description", description="New description (optional)")
    steps_json: Optional[str] = Field(
        None,
        title="Steps (JSON)",
        description="Optional JSON array of workflow steps to replace the existing steps",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyDeleteIncidentWorkflowConfig(BaseModel):
    """Delete an incident workflow (requires the From Email credential field)."""

    operation: Literal["delete_incident_workflow"] = Field(
        "delete_incident_workflow",
        json_schema_extra={"const": "delete_incident_workflow", "ui:hidden": True, "x-category": "Incident Workflows", "x-is-trigger": False, "x-display-name": "Delete Incident Workflow"},
        title="Delete Incident Workflow",
    )
    incident_workflow_id: str = Field(..., title="Incident Workflow ID", description="The incident workflow to delete")


class PagerDutyStartIncidentWorkflowConfig(BaseModel):
    """Start an incident workflow instance on an incident (requires the From Email credential field)."""

    operation: Literal["start_incident_workflow"] = Field(
        "start_incident_workflow",
        json_schema_extra={"const": "start_incident_workflow", "ui:hidden": True, "x-category": "Incident Workflows", "x-is-trigger": False, "x-display-name": "Start Incident Workflow"},
        title="Start Incident Workflow",
    )
    incident_workflow_id: str = Field(..., title="Incident Workflow ID", description="The incident workflow to start")
    incident_id: str = Field(..., title="Incident ID", description="The incident to run the workflow instance on")


class PagerDutyListIncidentWorkflowTriggersConfig(BaseModel):
    """List incident workflow triggers, optionally filtered by workflow name."""

    operation: Literal["list_incident_workflow_triggers"] = Field(
        "list_incident_workflow_triggers",
        json_schema_extra={"const": "list_incident_workflow_triggers", "ui:hidden": True, "x-category": "Workflow Triggers", "x-is-trigger": False, "x-display-name": "List Workflow Triggers"},
        title="List Workflow Triggers",
    )
    workflow_name_contains: Optional[str] = Field(None, title="Workflow Name Contains", description="Filter to triggers whose workflow name contains this text (optional)")


class PagerDutyGetIncidentWorkflowTriggerConfig(BaseModel):
    """Retrieve a single incident workflow trigger by ID."""

    operation: Literal["get_incident_workflow_trigger"] = Field(
        "get_incident_workflow_trigger",
        json_schema_extra={"const": "get_incident_workflow_trigger", "ui:hidden": True, "x-category": "Workflow Triggers", "x-is-trigger": False, "x-display-name": "Get Workflow Trigger"},
        title="Get Workflow Trigger",
    )
    trigger_id: str = Field(..., title="Trigger ID", description="The workflow trigger to retrieve")


class PagerDutyCreateIncidentWorkflowTriggerConfig(BaseModel):
    """Create an incident workflow trigger (requires the From Email credential field)."""

    operation: Literal["create_incident_workflow_trigger"] = Field(
        "create_incident_workflow_trigger",
        json_schema_extra={"const": "create_incident_workflow_trigger", "ui:hidden": True, "x-category": "Workflow Triggers", "x-is-trigger": False, "x-display-name": "Create Workflow Trigger"},
        title="Create Workflow Trigger",
    )
    incident_workflow_id: str = Field(..., title="Incident Workflow ID", description="The incident workflow this trigger starts")
    trigger_type: str = Field(
        "manual",
        title="Trigger Type",
        description="How the trigger fires",
        json_schema_extra={"enum": ["manual", "conditional"], "enumNames": ["Manual", "Conditional"], "x-enum-searchable": True},
    )
    condition: Optional[str] = Field(None, title="Condition", description="PCL condition expression (required for conditional triggers)")
    subscribed_to_all_services: Optional[str] = Field(
        None,
        title="Subscribe To All Services",
        description="Apply this trigger across all services",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    service_ids: Optional[str] = Field(
        None,
        title="Services",
        description="Scope the trigger to these services (ignored if subscribed to all services)",
        json_schema_extra={"x-dynamic-options": {"field_name": "service_ids", "placeholder": "Select service(s)...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste service ID(s), comma-separated"}},
    )


class PagerDutyUpdateIncidentWorkflowTriggerConfig(BaseModel):
    """Update an existing incident workflow trigger (requires the From Email credential field)."""

    operation: Literal["update_incident_workflow_trigger"] = Field(
        "update_incident_workflow_trigger",
        json_schema_extra={"const": "update_incident_workflow_trigger", "ui:hidden": True, "x-category": "Workflow Triggers", "x-is-trigger": False, "x-display-name": "Update Workflow Trigger"},
        title="Update Workflow Trigger",
    )
    trigger_id: str = Field(..., title="Trigger ID", description="The workflow trigger to update")
    condition: Optional[str] = Field(None, title="Condition", description="New PCL condition expression (optional)")
    subscribed_to_all_services: Optional[str] = Field(
        None,
        title="Subscribe To All Services",
        description="Apply this trigger across all services",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    service_ids: Optional[str] = Field(
        None,
        title="Services",
        description="Scope the trigger to these services (optional)",
        json_schema_extra={"x-dynamic-options": {"field_name": "service_ids", "placeholder": "Select service(s)...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste service ID(s), comma-separated"}},
    )


class PagerDutyDeleteIncidentWorkflowTriggerConfig(BaseModel):
    """Delete an incident workflow trigger (requires the From Email credential field)."""

    operation: Literal["delete_incident_workflow_trigger"] = Field(
        "delete_incident_workflow_trigger",
        json_schema_extra={"const": "delete_incident_workflow_trigger", "ui:hidden": True, "x-category": "Workflow Triggers", "x-is-trigger": False, "x-display-name": "Delete Workflow Trigger"},
        title="Delete Workflow Trigger",
    )
    trigger_id: str = Field(..., title="Trigger ID", description="The workflow trigger to delete")


class PagerDutyAssociateTriggerServiceConfig(BaseModel):
    """Associate a workflow trigger with a service (requires the From Email credential field)."""

    operation: Literal["associate_trigger_service"] = Field(
        "associate_trigger_service",
        json_schema_extra={"const": "associate_trigger_service", "ui:hidden": True, "x-category": "Workflow Triggers", "x-is-trigger": False, "x-display-name": "Associate Trigger With Service"},
        title="Associate Trigger With Service",
    )
    trigger_id: str = Field(..., title="Trigger ID", description="The workflow trigger to associate")
    service_id: str = Field(
        ...,
        title="Service",
        description="The service to associate the trigger with",
        json_schema_extra={"x-dynamic-options": {"field_name": "service_id", "placeholder": "Select a service...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste service ID"}},
    )


class PagerDutyDisassociateTriggerServiceConfig(BaseModel):
    """Disassociate a workflow trigger from a service (requires the From Email credential field)."""

    operation: Literal["disassociate_trigger_service"] = Field(
        "disassociate_trigger_service",
        json_schema_extra={"const": "disassociate_trigger_service", "ui:hidden": True, "x-category": "Workflow Triggers", "x-is-trigger": False, "x-display-name": "Disassociate Trigger From Service"},
        title="Disassociate Trigger From Service",
    )
    trigger_id: str = Field(..., title="Trigger ID", description="The workflow trigger to disassociate")
    service_id: str = Field(
        ...,
        title="Service",
        description="The service to remove from the trigger",
        json_schema_extra={"x-dynamic-options": {"field_name": "service_id", "placeholder": "Select a service...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste service ID"}},
    )


# ---------------------------------------------------------------------------
# Family: business-status
# ---------------------------------------------------------------------------


class PagerDutyListBusinessServicesConfig(BaseModel):
    """List business services on the account."""

    operation: Literal["list_business_services"] = Field(
        "list_business_services",
        json_schema_extra={"const": "list_business_services", "ui:hidden": True, "x-category": "Business Services", "x-is-trigger": False, "x-display-name": "List Business Services"},
        title="List Business Services",
    )
    limit: Optional[str] = Field("25", title="Limit", description="Max number of business services to return (1-100)")
    offset: Optional[str] = Field(None, title="Offset", description="Pagination offset")


class PagerDutyGetBusinessServiceConfig(BaseModel):
    """Get a business service by ID."""

    operation: Literal["get_business_service"] = Field(
        "get_business_service",
        json_schema_extra={"const": "get_business_service", "ui:hidden": True, "x-category": "Business Services", "x-is-trigger": False, "x-display-name": "Get Business Service"},
        title="Get Business Service",
    )
    business_service_id: str = Field(..., title="Business Service ID", description="The business service to fetch")


class PagerDutyCreateBusinessServiceConfig(BaseModel):
    """Create a business service."""

    operation: Literal["create_business_service"] = Field(
        "create_business_service",
        json_schema_extra={"const": "create_business_service", "ui:hidden": True,
            "x-creates-resource": True,
            "x-resource-type": "pagerduty_business_service",
            "x-resource-id-path": "data.business_service.id", "x-category": "Business Services", "x-is-trigger": False, "x-display-name": "Create Business Service"},
        title="Create Business Service",
    )
    name: str = Field(..., title="Name", description="The name of the business service")
    description: Optional[str] = Field(None, title="Description", description="A description of the business service (optional)")
    point_of_contact: Optional[str] = Field(None, title="Point of Contact", description="The business service's point of contact (optional)")
    team_id: Optional[str] = Field(None, title="Team ID", description="The team that owns this business service (optional)")


class PagerDutyUpdateBusinessServiceConfig(BaseModel):
    """Update an existing business service."""

    operation: Literal["update_business_service"] = Field(
        "update_business_service",
        json_schema_extra={"const": "update_business_service", "ui:hidden": True, "x-category": "Business Services", "x-is-trigger": False, "x-display-name": "Update Business Service"},
        title="Update Business Service",
    )
    business_service_id: str = Field(..., title="Business Service ID", description="The business service to update")
    name: Optional[str] = Field(None, title="Name", description="New name (optional)")
    description: Optional[str] = Field(None, title="Description", description="New description (optional)")
    point_of_contact: Optional[str] = Field(None, title="Point of Contact", description="New point of contact (optional)")
    team_id: Optional[str] = Field(None, title="Team ID", description="Reassign to this owning team (optional)")


class PagerDutyDeleteBusinessServiceConfig(BaseModel):
    """Delete a business service."""

    operation: Literal["delete_business_service"] = Field(
        "delete_business_service",
        json_schema_extra={"const": "delete_business_service", "ui:hidden": True, "x-category": "Business Services", "x-is-trigger": False, "x-display-name": "Delete Business Service"},
        title="Delete Business Service",
    )
    business_service_id: str = Field(..., title="Business Service ID", description="The business service to delete")


class PagerDutyListBusinessServiceSubscribersConfig(BaseModel):
    """List the subscribers of a business service."""

    operation: Literal["list_business_service_subscribers"] = Field(
        "list_business_service_subscribers",
        json_schema_extra={"const": "list_business_service_subscribers", "ui:hidden": True, "x-category": "Business Services", "x-is-trigger": False, "x-display-name": "List Business Service Subscribers"},
        title="List Business Service Subscribers",
    )
    business_service_id: str = Field(..., title="Business Service ID", description="The business service whose subscribers to list")


class PagerDutyCreateBusinessServiceSubscribersConfig(BaseModel):
    """Subscribe users or teams to a business service's status updates."""

    operation: Literal["create_business_service_subscribers"] = Field(
        "create_business_service_subscribers",
        json_schema_extra={"const": "create_business_service_subscribers", "ui:hidden": True, "x-category": "Business Services", "x-is-trigger": False, "x-display-name": "Add Business Service Subscribers"},
        title="Add Business Service Subscribers",
    )
    business_service_id: str = Field(..., title="Business Service ID", description="The business service to subscribe to")
    subscriber_ids: str = Field(..., title="Subscriber IDs", description="User or team IDs to subscribe, comma-separated")
    subscriber_type: str = Field("user", title="Subscriber Type", description="Whether the subscribers are users or teams",
        json_schema_extra={"enum": ["user", "team"], "enumNames": ["User", "Team"], "x-enum-searchable": True})


class PagerDutyRemoveBusinessServiceSubscribersConfig(BaseModel):
    """Unsubscribe users or teams from a business service."""

    operation: Literal["remove_business_service_subscribers"] = Field(
        "remove_business_service_subscribers",
        json_schema_extra={"const": "remove_business_service_subscribers", "ui:hidden": True, "x-category": "Business Services", "x-is-trigger": False, "x-display-name": "Remove Business Service Subscribers"},
        title="Remove Business Service Subscribers",
    )
    business_service_id: str = Field(..., title="Business Service ID", description="The business service to unsubscribe from")
    subscriber_ids: str = Field(..., title="Subscriber IDs", description="User or team IDs to unsubscribe, comma-separated")
    subscriber_type: str = Field("user", title="Subscriber Type", description="Whether the subscribers are users or teams",
        json_schema_extra={"enum": ["user", "team"], "enumNames": ["User", "Team"], "x-enum-searchable": True})


class PagerDutyListBusinessServiceImpactsConfig(BaseModel):
    """List the current impacts on business services (which are affected by active incidents)."""

    operation: Literal["list_business_service_impacts"] = Field(
        "list_business_service_impacts",
        json_schema_extra={"const": "list_business_service_impacts", "ui:hidden": True, "x-category": "Business Services", "x-is-trigger": False, "x-display-name": "List Business Service Impacts"},
        title="List Business Service Impacts",
    )
    ids: Optional[str] = Field(None, title="Business Service IDs", description="Limit to these business service IDs, comma-separated (optional)")
    additional_fields: Optional[str] = Field(None, title="Additional Fields", description="Extra fields to include, comma-separated (e.g. business_service.priority) (optional)")


class PagerDutyListBusinessServiceImpactorsConfig(BaseModel):
    """List the technical services currently impacting business services."""

    operation: Literal["list_business_service_impactors"] = Field(
        "list_business_service_impactors",
        json_schema_extra={"const": "list_business_service_impactors", "ui:hidden": True, "x-category": "Business Services", "x-is-trigger": False, "x-display-name": "List Business Service Impactors"},
        title="List Business Service Impactors",
    )
    ids: Optional[str] = Field(None, title="Business Service IDs", description="Limit to impactors of these business service IDs, comma-separated (optional)")


class PagerDutyGetPriorityThresholdsConfig(BaseModel):
    """Get the account's business-service priority thresholds."""

    operation: Literal["get_priority_thresholds"] = Field(
        "get_priority_thresholds",
        json_schema_extra={"const": "get_priority_thresholds", "ui:hidden": True, "x-category": "Business Services", "x-is-trigger": False, "x-display-name": "Get Priority Thresholds"},
        title="Get Priority Thresholds",
    )


class PagerDutySetPriorityThresholdConfig(BaseModel):
    """Set the account's business-service priority threshold (the priority at which an incident counts as impacting)."""

    operation: Literal["set_priority_threshold"] = Field(
        "set_priority_threshold",
        json_schema_extra={"const": "set_priority_threshold", "ui:hidden": True, "x-category": "Business Services", "x-is-trigger": False, "x-display-name": "Set Priority Threshold"},
        title="Set Priority Threshold",
    )
    priority_id: str = Field(..., title="Priority", description="The priority used as the impact threshold",
        json_schema_extra={"x-dynamic-options": {"field_name": "priority_id", "placeholder": "Select a priority…", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste a priority ID"}})
    order: str = Field(..., title="Order", description="The numeric rank (order) of the threshold priority")


class PagerDutyDeletePriorityThresholdsConfig(BaseModel):
    """Delete (reset) the account's business-service priority thresholds."""

    operation: Literal["delete_priority_thresholds"] = Field(
        "delete_priority_thresholds",
        json_schema_extra={"const": "delete_priority_thresholds", "ui:hidden": True, "x-category": "Business Services", "x-is-trigger": False, "x-display-name": "Delete Priority Thresholds"},
        title="Delete Priority Thresholds",
    )


class PagerDutyListStatusDashboardsConfig(BaseModel):
    """List status dashboards."""

    operation: Literal["list_status_dashboards"] = Field(
        "list_status_dashboards",
        json_schema_extra={"const": "list_status_dashboards", "ui:hidden": True, "x-category": "Status Dashboards", "x-is-trigger": False, "x-display-name": "List Status Dashboards"},
        title="List Status Dashboards",
    )


class PagerDutyGetStatusDashboardConfig(BaseModel):
    """Get a status dashboard by ID."""

    operation: Literal["get_status_dashboard"] = Field(
        "get_status_dashboard",
        json_schema_extra={"const": "get_status_dashboard", "ui:hidden": True, "x-category": "Status Dashboards", "x-is-trigger": False, "x-display-name": "Get Status Dashboard"},
        title="Get Status Dashboard",
    )
    status_dashboard_id: str = Field(..., title="Status Dashboard ID", description="The status dashboard to fetch")


class PagerDutyGetStatusDashboardBySlugConfig(BaseModel):
    """Get a status dashboard by its URL slug."""

    operation: Literal["get_status_dashboard_by_slug"] = Field(
        "get_status_dashboard_by_slug",
        json_schema_extra={"const": "get_status_dashboard_by_slug", "ui:hidden": True, "x-category": "Status Dashboards", "x-is-trigger": False, "x-display-name": "Get Status Dashboard by Slug"},
        title="Get Status Dashboard by Slug",
    )
    url_slug: str = Field(..., title="URL Slug", description="The URL slug of the status dashboard")


class PagerDutyGetStatusDashboardServiceImpactsConfig(BaseModel):
    """Get the service impacts shown on a status dashboard."""

    operation: Literal["get_status_dashboard_service_impacts"] = Field(
        "get_status_dashboard_service_impacts",
        json_schema_extra={"const": "get_status_dashboard_service_impacts", "ui:hidden": True, "x-category": "Status Dashboards", "x-is-trigger": False, "x-display-name": "Get Status Dashboard Service Impacts"},
        title="Get Status Dashboard Service Impacts",
    )
    status_dashboard_id: str = Field(..., title="Status Dashboard ID", description="The status dashboard whose service impacts to fetch")
    additional_fields: Optional[str] = Field(None, title="Additional Fields", description="Extra fields to include, comma-separated (optional)")


class PagerDutyListStatusPagesConfig(BaseModel):
    """List status pages."""

    operation: Literal["list_status_pages"] = Field(
        "list_status_pages",
        json_schema_extra={"const": "list_status_pages", "ui:hidden": True, "x-category": "Status Pages", "x-is-trigger": False, "x-display-name": "List Status Pages"},
        title="List Status Pages",
    )
    status_page_type: Optional[str] = Field(None, title="Type", description="Filter by status page type (optional)",
        json_schema_extra={"enum": ["", "public", "private"], "enumNames": ["Any", "Public", "Private"], "x-enum-searchable": True})


class PagerDutyListStatusPagePostsConfig(BaseModel):
    """List the posts on a status page."""

    operation: Literal["list_status_page_posts"] = Field(
        "list_status_page_posts",
        json_schema_extra={"const": "list_status_page_posts", "ui:hidden": True, "x-category": "Status Pages", "x-is-trigger": False, "x-display-name": "List Status Page Posts"},
        title="List Status Page Posts",
    )
    status_page_id: str = Field(..., title="Status Page ID", description="The status page whose posts to list")
    post_type: Optional[str] = Field(None, title="Post Type", description="Filter by post type (optional)",
        json_schema_extra={"enum": ["", "incident", "maintenance"], "enumNames": ["Any", "Incident", "Maintenance"], "x-enum-searchable": True})


class PagerDutyCreateStatusPagePostConfig(BaseModel):
    """Create a post (incident or maintenance) on a status page."""

    operation: Literal["create_status_page_post"] = Field(
        "create_status_page_post",
        json_schema_extra={"const": "create_status_page_post", "ui:hidden": True, "x-category": "Status Pages", "x-is-trigger": False, "x-display-name": "Create Status Page Post"},
        title="Create Status Page Post",
    )
    status_page_id: str = Field(..., title="Status Page ID", description="The status page to post to")
    title: str = Field(..., title="Title", description="The post title")
    post_type: str = Field("incident", title="Post Type", description="Whether this is an incident or a maintenance post",
        json_schema_extra={"enum": ["incident", "maintenance"], "enumNames": ["Incident", "Maintenance"], "x-enum-searchable": True})
    starts_at: str = Field(..., title="Starts At", description="ISO 8601 start time of the post")
    ends_at: str = Field(..., title="Ends At", description="ISO 8601 end time of the post")
    updates: str = Field(..., title="Updates (JSON)", description="JSON array of post update objects (at least one initial update). Each needs message, status, severity, impacted_services, update_frequency_ms, notify_subscribers",
        json_schema_extra={"ui:widget": "textarea"})


class PagerDutyGetStatusPagePostConfig(BaseModel):
    """Get a single status page post."""

    operation: Literal["get_status_page_post"] = Field(
        "get_status_page_post",
        json_schema_extra={"const": "get_status_page_post", "ui:hidden": True, "x-category": "Status Pages", "x-is-trigger": False, "x-display-name": "Get Status Page Post"},
        title="Get Status Page Post",
    )
    status_page_id: str = Field(..., title="Status Page ID", description="The status page the post belongs to")
    post_id: str = Field(..., title="Post ID", description="The post to fetch")


class PagerDutyUpdateStatusPagePostConfig(BaseModel):
    """Update a status page post. PagerDuty requires the full post representation on update."""

    operation: Literal["update_status_page_post"] = Field(
        "update_status_page_post",
        json_schema_extra={"const": "update_status_page_post", "ui:hidden": True, "x-category": "Status Pages", "x-is-trigger": False, "x-display-name": "Update Status Page Post"},
        title="Update Status Page Post",
    )
    status_page_id: str = Field(..., title="Status Page ID", description="The status page the post belongs to")
    post_id: str = Field(..., title="Post ID", description="The post to update")
    title: str = Field(..., title="Title", description="The post title")
    post_type: str = Field("incident", title="Post Type", description="Whether this is an incident or a maintenance post",
        json_schema_extra={"enum": ["incident", "maintenance"], "enumNames": ["Incident", "Maintenance"], "x-enum-searchable": True})
    starts_at: str = Field(..., title="Starts At", description="ISO 8601 start time of the post")
    ends_at: str = Field(..., title="Ends At", description="ISO 8601 end time of the post")


class PagerDutyDeleteStatusPagePostConfig(BaseModel):
    """Delete a status page post."""

    operation: Literal["delete_status_page_post"] = Field(
        "delete_status_page_post",
        json_schema_extra={"const": "delete_status_page_post", "ui:hidden": True, "x-category": "Status Pages", "x-is-trigger": False, "x-display-name": "Delete Status Page Post"},
        title="Delete Status Page Post",
    )
    status_page_id: str = Field(..., title="Status Page ID", description="The status page the post belongs to")
    post_id: str = Field(..., title="Post ID", description="The post to delete")


class PagerDutyListStatusPagePostUpdatesConfig(BaseModel):
    """List the updates on a status page post."""

    operation: Literal["list_status_page_post_updates"] = Field(
        "list_status_page_post_updates",
        json_schema_extra={"const": "list_status_page_post_updates", "ui:hidden": True, "x-category": "Status Pages", "x-is-trigger": False, "x-display-name": "List Status Page Post Updates"},
        title="List Status Page Post Updates",
    )
    status_page_id: str = Field(..., title="Status Page ID", description="The status page the post belongs to")
    post_id: str = Field(..., title="Post ID", description="The post whose updates to list")


class PagerDutyCreateStatusPagePostUpdateConfig(BaseModel):
    """Add an update to a status page post."""

    operation: Literal["create_status_page_post_update"] = Field(
        "create_status_page_post_update",
        json_schema_extra={"const": "create_status_page_post_update", "ui:hidden": True, "x-category": "Status Pages", "x-is-trigger": False, "x-display-name": "Create Status Page Post Update"},
        title="Create Status Page Post Update",
    )
    status_page_id: str = Field(..., title="Status Page ID", description="The status page the post belongs to")
    post_id: str = Field(..., title="Post ID", description="The post to add an update to")
    post_update: str = Field(..., title="Post Update (JSON)", description="JSON object for the post update (message, status, severity, impacted_services, update_frequency_ms, notify_subscribers)",
        json_schema_extra={"ui:widget": "textarea"})


class PagerDutyGetStatusPagePostUpdateConfig(BaseModel):
    """Get a single status page post update."""

    operation: Literal["get_status_page_post_update"] = Field(
        "get_status_page_post_update",
        json_schema_extra={"const": "get_status_page_post_update", "ui:hidden": True, "x-category": "Status Pages", "x-is-trigger": False, "x-display-name": "Get Status Page Post Update"},
        title="Get Status Page Post Update",
    )
    status_page_id: str = Field(..., title="Status Page ID", description="The status page the post belongs to")
    post_id: str = Field(..., title="Post ID", description="The post the update belongs to")
    post_update_id: str = Field(..., title="Post Update ID", description="The post update to fetch")


class PagerDutyUpdateStatusPagePostUpdateConfig(BaseModel):
    """Update a status page post update. PagerDuty requires the full post-update representation."""

    operation: Literal["update_status_page_post_update"] = Field(
        "update_status_page_post_update",
        json_schema_extra={"const": "update_status_page_post_update", "ui:hidden": True, "x-category": "Status Pages", "x-is-trigger": False, "x-display-name": "Update Status Page Post Update"},
        title="Update Status Page Post Update",
    )
    status_page_id: str = Field(..., title="Status Page ID", description="The status page the post belongs to")
    post_id: str = Field(..., title="Post ID", description="The post the update belongs to")
    post_update_id: str = Field(..., title="Post Update ID", description="The post update to update")
    post_update: str = Field(..., title="Post Update (JSON)", description="JSON object for the post update (message, status, severity, impacted_services, update_frequency_ms, notify_subscribers)",
        json_schema_extra={"ui:widget": "textarea"})


class PagerDutyDeleteStatusPagePostUpdateConfig(BaseModel):
    """Delete a status page post update."""

    operation: Literal["delete_status_page_post_update"] = Field(
        "delete_status_page_post_update",
        json_schema_extra={"const": "delete_status_page_post_update", "ui:hidden": True, "x-category": "Status Pages", "x-is-trigger": False, "x-display-name": "Delete Status Page Post Update"},
        title="Delete Status Page Post Update",
    )
    status_page_id: str = Field(..., title="Status Page ID", description="The status page the post belongs to")
    post_id: str = Field(..., title="Post ID", description="The post the update belongs to")
    post_update_id: str = Field(..., title="Post Update ID", description="The post update to delete")


class PagerDutyListStatusPageSubscriptionsConfig(BaseModel):
    """List the subscriptions on a status page."""

    operation: Literal["list_status_page_subscriptions"] = Field(
        "list_status_page_subscriptions",
        json_schema_extra={"const": "list_status_page_subscriptions", "ui:hidden": True, "x-category": "Status Pages", "x-is-trigger": False, "x-display-name": "List Status Page Subscriptions"},
        title="List Status Page Subscriptions",
    )
    status_page_id: str = Field(..., title="Status Page ID", description="The status page whose subscriptions to list")
    channel: Optional[str] = Field(None, title="Channel", description="Filter by subscription channel (optional)",
        json_schema_extra={"enum": ["", "webhook", "email"], "enumNames": ["Any", "Webhook", "Email"], "x-enum-searchable": True})


class PagerDutyCreateStatusPageSubscriptionConfig(BaseModel):
    """Create a subscription to a status page (or one of its services/posts)."""

    operation: Literal["create_status_page_subscription"] = Field(
        "create_status_page_subscription",
        json_schema_extra={"const": "create_status_page_subscription", "ui:hidden": True, "x-category": "Status Pages", "x-is-trigger": False, "x-display-name": "Create Status Page Subscription"},
        title="Create Status Page Subscription",
    )
    status_page_id: str = Field(..., title="Status Page ID", description="The status page to subscribe on")
    channel: str = Field("email", title="Channel", description="How the subscriber is notified",
        json_schema_extra={"enum": ["email", "webhook"], "enumNames": ["Email", "Webhook"], "x-enum-searchable": True})
    contact: str = Field(..., title="Contact", description="The subscriber's contact — an email address or a webhook URL")
    subscribable_object_id: str = Field(..., title="Subscribable Object ID", description="The ID of the object being subscribed to (the status page, a status page service, or a post)")
    subscribable_object_type: str = Field("status_page", title="Subscribable Object Type", description="The type of object being subscribed to",
        json_schema_extra={"enum": ["status_page", "status_page_service", "status_page_post"], "enumNames": ["Status Page", "Status Page Service", "Status Page Post"], "x-enum-searchable": True})


class PagerDutyGetStatusPageSubscriptionConfig(BaseModel):
    """Get a single status page subscription."""

    operation: Literal["get_status_page_subscription"] = Field(
        "get_status_page_subscription",
        json_schema_extra={"const": "get_status_page_subscription", "ui:hidden": True, "x-category": "Status Pages", "x-is-trigger": False, "x-display-name": "Get Status Page Subscription"},
        title="Get Status Page Subscription",
    )
    status_page_id: str = Field(..., title="Status Page ID", description="The status page the subscription belongs to")
    subscription_id: str = Field(..., title="Subscription ID", description="The subscription to fetch")


class PagerDutyDeleteStatusPageSubscriptionConfig(BaseModel):
    """Delete a status page subscription."""

    operation: Literal["delete_status_page_subscription"] = Field(
        "delete_status_page_subscription",
        json_schema_extra={"const": "delete_status_page_subscription", "ui:hidden": True, "x-category": "Status Pages", "x-is-trigger": False, "x-display-name": "Delete Status Page Subscription"},
        title="Delete Status Page Subscription",
    )
    status_page_id: str = Field(..., title="Status Page ID", description="The status page the subscription belongs to")
    subscription_id: str = Field(..., title="Subscription ID", description="The subscription to delete")


# ---------------------------------------------------------------------------
# Family: analytics-audit-changes
# ---------------------------------------------------------------------------


class PagerDutyIncidentMetricsConfig(BaseModel):
    """Aggregated incident metrics (MTTA, MTTR, counts) across the account for a time range."""

    operation: Literal["analytics_incident_metrics"] = Field(
        "analytics_incident_metrics",
        json_schema_extra={"const": "analytics_incident_metrics", "ui:hidden": True, "x-category": "Analytics", "x-is-trigger": False, "x-display-name": "Aggregated Incident Metrics"},
        title="Aggregated Incident Metrics",
    )
    filters: Optional[str] = Field(
        None,
        title="Filters (JSON)",
        description='JSON filters object. Usually requires created_at_start and created_at_end, e.g. {"created_at_start":"2026-06-01T00:00:00Z","created_at_end":"2026-06-30T00:00:00Z","service_ids":["PSVC123"]}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    time_zone: Optional[str] = Field(None, title="Time Zone", description="IANA time zone for the results (e.g. Etc/UTC)")
    aggregate_unit: Optional[str] = Field(
        None,
        title="Aggregate Unit",
        description="Bucket the results by time unit (optional)",
        json_schema_extra={"enum": ["", "day", "week", "month"], "enumNames": ["None", "Day", "Week", "Month"], "x-enum-searchable": True},
    )
    order: Optional[str] = Field(
        None,
        title="Order",
        description="Sort direction (optional)",
        json_schema_extra={"enum": ["", "asc", "desc"], "enumNames": ["Default", "Ascending", "Descending"], "x-enum-searchable": True},
    )
    order_by: Optional[str] = Field(None, title="Order By", description="Metric field to sort by (optional)")


class PagerDutyIncidentMetricsByDimensionConfig(BaseModel):
    """Incident metrics broken down by service, team, or escalation policy."""

    operation: Literal["analytics_incident_metrics_by_dimension"] = Field(
        "analytics_incident_metrics_by_dimension",
        json_schema_extra={"const": "analytics_incident_metrics_by_dimension", "ui:hidden": True, "x-category": "Analytics", "x-is-trigger": False, "x-display-name": "Incident Metrics by Service/Team/EP"},
        title="Incident Metrics by Service/Team/EP",
    )
    dimension: str = Field(
        "services",
        title="Group By",
        description="Which dimension to break the metrics down by",
        json_schema_extra={"enum": ["services", "teams", "escalation_policies"], "enumNames": ["Service", "Team", "Escalation Policy"], "x-enum-searchable": True},
    )
    aggregate_all: str = Field(
        "false",
        title="Aggregate All",
        description="Aggregate a single row across the whole dimension instead of one row per entity",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    filters: Optional[str] = Field(
        None,
        title="Filters (JSON)",
        description='JSON filters object. Usually requires created_at_start and created_at_end, e.g. {"created_at_start":"2026-06-01T00:00:00Z","created_at_end":"2026-06-30T00:00:00Z","team_ids":["PTEAM1"]}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    time_zone: Optional[str] = Field(None, title="Time Zone", description="IANA time zone for the results (e.g. Etc/UTC)")
    aggregate_unit: Optional[str] = Field(
        None,
        title="Aggregate Unit",
        description="Bucket the results by time unit (optional)",
        json_schema_extra={"enum": ["", "day", "week", "month"], "enumNames": ["None", "Day", "Week", "Month"], "x-enum-searchable": True},
    )
    order: Optional[str] = Field(
        None,
        title="Order",
        description="Sort direction (optional)",
        json_schema_extra={"enum": ["", "asc", "desc"], "enumNames": ["Default", "Ascending", "Descending"], "x-enum-searchable": True},
    )
    order_by: Optional[str] = Field(None, title="Order By", description="Metric field to sort by (optional)")


class PagerDutyRawIncidentsConfig(BaseModel):
    """List raw per-incident analytics records for a time range."""

    operation: Literal["analytics_raw_incidents"] = Field(
        "analytics_raw_incidents",
        json_schema_extra={"const": "analytics_raw_incidents", "ui:hidden": True, "x-category": "Analytics", "x-is-trigger": False, "x-display-name": "Raw Incidents"},
        title="Raw Incidents",
    )
    filters: Optional[str] = Field(
        None,
        title="Filters (JSON)",
        description='JSON filters object. Usually requires created_at_start and created_at_end, e.g. {"created_at_start":"2026-06-01T00:00:00Z","created_at_end":"2026-06-30T00:00:00Z"}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    starting_after: Optional[str] = Field(None, title="Starting After", description="Cursor for the next page (from the previous response's last row, optional)")
    ending_before: Optional[str] = Field(None, title="Ending Before", description="Cursor for the previous page (optional)")
    order: Optional[str] = Field(
        None,
        title="Order",
        description="Sort direction (optional)",
        json_schema_extra={"enum": ["", "asc", "desc"], "enumNames": ["Default", "Ascending", "Descending"], "x-enum-searchable": True},
    )
    order_by: Optional[str] = Field(
        None,
        title="Order By",
        description="Field to sort by (optional)",
        json_schema_extra={"enum": ["", "created_at", "seconds_to_resolve"], "enumNames": ["Default", "Created At", "Seconds to Resolve"], "x-enum-searchable": True},
    )
    limit: Optional[str] = Field(None, title="Limit", description="Max number of records to return (optional)")
    time_zone: Optional[str] = Field(None, title="Time Zone", description="IANA time zone for the results (e.g. Etc/UTC)")


class PagerDutyGetRawIncidentConfig(BaseModel):
    """Get the raw analytics record for a single incident by ID."""

    operation: Literal["get_raw_incident"] = Field(
        "get_raw_incident",
        json_schema_extra={"const": "get_raw_incident", "ui:hidden": True, "x-category": "Analytics", "x-is-trigger": False, "x-display-name": "Get Raw Incident"},
        title="Get Raw Incident",
    )
    incident_id: str = Field(..., title="Incident ID", description="The ID of the incident to fetch analytics for")


class PagerDutyRawIncidentResponsesConfig(BaseModel):
    """List the responder-response analytics records for a single incident."""

    operation: Literal["get_raw_incident_responses"] = Field(
        "get_raw_incident_responses",
        json_schema_extra={"const": "get_raw_incident_responses", "ui:hidden": True, "x-category": "Analytics", "x-is-trigger": False, "x-display-name": "Raw Incident Responses"},
        title="Raw Incident Responses",
    )
    incident_id: str = Field(..., title="Incident ID", description="The ID of the incident whose response records to list")


class PagerDutyResponderMetricsConfig(BaseModel):
    """Aggregated responder metrics, overall or grouped by team."""

    operation: Literal["analytics_responder_metrics"] = Field(
        "analytics_responder_metrics",
        json_schema_extra={"const": "analytics_responder_metrics", "ui:hidden": True, "x-category": "Analytics", "x-is-trigger": False, "x-display-name": "Responder Metrics"},
        title="Responder Metrics",
    )
    group_by: str = Field(
        "all",
        title="Group By",
        description="Aggregate across all responders or break down by team",
        json_schema_extra={"enum": ["all", "teams"], "enumNames": ["All Responders", "By Team"], "x-enum-searchable": True},
    )
    filters: Optional[str] = Field(
        None,
        title="Filters (JSON)",
        description='JSON filters object. Usually requires date_range_start and date_range_end, e.g. {"date_range_start":"2026-06-01T00:00:00Z","date_range_end":"2026-06-30T00:00:00Z","team_ids":["PTEAM1"]}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    time_zone: Optional[str] = Field(None, title="Time Zone", description="IANA time zone for the results (e.g. Etc/UTC)")
    order: Optional[str] = Field(
        None,
        title="Order",
        description="Sort direction (optional)",
        json_schema_extra={"enum": ["", "asc", "desc"], "enumNames": ["Default", "Ascending", "Descending"], "x-enum-searchable": True},
    )
    order_by: Optional[str] = Field(None, title="Order By", description="Metric field to sort by (optional)")


class PagerDutyListAuditRecordsConfig(BaseModel):
    """List account audit trail records (cursor-paginated)."""

    operation: Literal["list_audit_records"] = Field(
        "list_audit_records",
        json_schema_extra={"const": "list_audit_records", "ui:hidden": True, "x-category": "Audit", "x-is-trigger": False, "x-display-name": "List Audit Records"},
        title="List Audit Records",
    )
    since: Optional[str] = Field(None, title="Since", description="ISO 8601 lower bound on the execution time (optional)")
    until: Optional[str] = Field(None, title="Until", description="ISO 8601 upper bound on the execution time (optional)")
    cursor: Optional[str] = Field(None, title="Cursor", description="Cursor from a prior response's next_cursor for the next page (optional)")
    limit: Optional[str] = Field(None, title="Limit", description="Max number of records to return (optional)")
    root_resource_types: Optional[str] = Field(
        None,
        title="Root Resource Types",
        description="Filter to these root resource types, comma-separated (e.g. services,teams,users,schedules,escalation_policies)",
    )
    actions: Optional[str] = Field(
        None,
        title="Actions",
        description="Filter to these actions, comma-separated (e.g. create,update,delete)",
    )


class PagerDutySendChangeEventConfig(BaseModel):
    """Send a change event via the Events API v2 change endpoint (deploys, config changes)."""

    operation: Literal["send_change_event"] = Field(
        "send_change_event",
        json_schema_extra={"const": "send_change_event", "ui:hidden": True, "x-category": "Change Events", "x-is-trigger": False, "x-display-name": "Send Change Event"},
        title="Send Change Event",
    )
    routing_key: str = Field(
        ...,
        title="Integration Key",
        description="The 32-character Events API v2 integration (routing) key for the target service",
        json_schema_extra={"ui:widget": "password"},
    )
    summary: str = Field(..., title="Summary", description="A brief description of the change (e.g. 'Deployed v1.2.3')")
    source: Optional[str] = Field(None, title="Source", description="The source of the change, e.g. the deploy pipeline or host (optional)")
    custom_details: Optional[str] = Field(
        None,
        title="Custom Details (JSON)",
        description='Additional free-form change details as a JSON object, e.g. {"build":"1.2.3","env":"prod"}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyListChangeEventsConfig(BaseModel):
    """List change events across the account."""

    operation: Literal["list_change_events"] = Field(
        "list_change_events",
        json_schema_extra={"const": "list_change_events", "ui:hidden": True, "x-category": "Change Events", "x-is-trigger": False, "x-display-name": "List Change Events"},
        title="List Change Events",
    )
    team_ids: Optional[str] = Field(
        None,
        title="Team",
        description="Filter to change events owned by this team",
        json_schema_extra={"x-dynamic-options": {"field_name": "team_ids", "placeholder": "Select a team...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste team ID(s), comma-separated"}},
    )
    integration_ids: Optional[str] = Field(None, title="Integration IDs", description="Filter to these integration IDs, comma-separated (optional)")
    since: Optional[str] = Field(None, title="Since", description="ISO 8601 lower bound on the created_at range (optional)")
    until: Optional[str] = Field(None, title="Until", description="ISO 8601 upper bound on the created_at range (optional)")
    limit: Optional[str] = Field(None, title="Limit", description="Max number of change events to return (optional)")


class PagerDutyListServiceChangeEventsConfig(BaseModel):
    """List change events for a specific service."""

    operation: Literal["list_service_change_events"] = Field(
        "list_service_change_events",
        json_schema_extra={"const": "list_service_change_events", "ui:hidden": True, "x-category": "Change Events", "x-is-trigger": False, "x-display-name": "List Service Change Events"},
        title="List Service Change Events",
    )
    service_id: str = Field(
        ...,
        title="Service",
        description="The service whose change events to list",
        json_schema_extra={"x-dynamic-options": {"field_name": "service_id", "placeholder": "Select a service...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste service ID"}},
    )
    team_ids: Optional[str] = Field(
        None,
        title="Team",
        description="Filter to change events owned by this team (optional)",
        json_schema_extra={"x-dynamic-options": {"field_name": "team_ids", "placeholder": "Select a team...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste team ID(s), comma-separated"}},
    )
    integration_ids: Optional[str] = Field(None, title="Integration IDs", description="Filter to these integration IDs, comma-separated (optional)")
    since: Optional[str] = Field(None, title="Since", description="ISO 8601 lower bound on the created_at range (optional)")
    until: Optional[str] = Field(None, title="Until", description="ISO 8601 upper bound on the created_at range (optional)")
    limit: Optional[str] = Field(None, title="Limit", description="Max number of change events to return (optional)")


# ---------------------------------------------------------------------------
# Family: reference-misc
# ---------------------------------------------------------------------------


class PagerDutyListCustomFieldsConfig(BaseModel):
    """List incident custom field definitions on the account."""

    operation: Literal["list_custom_fields"] = Field(
        "list_custom_fields",
        json_schema_extra={"const": "list_custom_fields", "ui:hidden": True, "x-category": "Custom Fields", "x-is-trigger": False, "x-display-name": "List Custom Fields"},
        title="List Custom Fields",
    )


class PagerDutyCreateCustomFieldConfig(BaseModel):
    """Create an incident custom field definition."""

    operation: Literal["create_custom_field"] = Field(
        "create_custom_field",
        json_schema_extra={"const": "create_custom_field", "ui:hidden": True, "x-category": "Custom Fields", "x-is-trigger": False, "x-display-name": "Create Custom Field"},
        title="Create Custom Field",
    )
    name: str = Field(..., title="Name", description="Internal field name (lowercase ASCII, digits, underscores; no spaces)")
    display_name: str = Field(..., title="Display Name", description="Human-readable field name")
    data_type: str = Field(
        "string", title="Data Type", description="The kind of data this field stores",
        json_schema_extra={"enum": ["boolean", "integer", "float", "string", "datetime", "url"], "enumNames": ["Boolean", "Integer", "Float", "String", "Datetime", "URL"], "x-enum-searchable": True},
    )
    field_type: str = Field(
        "single_value", title="Field Type", description="Single/multi value and whether values are restricted to fixed options",
        json_schema_extra={"enum": ["single_value", "single_value_fixed", "multi_value", "multi_value_fixed"], "enumNames": ["Single Value", "Single Value (Fixed Options)", "Multi Value", "Multi Value (Fixed Options)"], "x-enum-searchable": True},
    )
    description: Optional[str] = Field(None, title="Description", description="A description of the data this field contains (optional)")
    default_value: Optional[str] = Field(None, title="Default Value", description="Default value for the field (optional)")
    enabled: Optional[str] = Field(
        None, title="Enabled", description="Whether the field is enabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class PagerDutyGetCustomFieldConfig(BaseModel):
    """Retrieve a single incident custom field by ID."""

    operation: Literal["get_custom_field"] = Field(
        "get_custom_field",
        json_schema_extra={"const": "get_custom_field", "ui:hidden": True, "x-category": "Custom Fields", "x-is-trigger": False, "x-display-name": "Get Custom Field"},
        title="Get Custom Field",
    )
    field_id: str = Field(..., title="Field ID", description="The custom field to retrieve")


class PagerDutyUpdateCustomFieldConfig(BaseModel):
    """Update an incident custom field (name, data_type and field_type are immutable)."""

    operation: Literal["update_custom_field"] = Field(
        "update_custom_field",
        json_schema_extra={"const": "update_custom_field", "ui:hidden": True, "x-category": "Custom Fields", "x-is-trigger": False, "x-display-name": "Update Custom Field"},
        title="Update Custom Field",
    )
    field_id: str = Field(..., title="Field ID", description="The custom field to update")
    display_name: Optional[str] = Field(None, title="Display Name", description="New human-readable name (optional)")
    description: Optional[str] = Field(None, title="Description", description="New description (optional)")
    default_value: Optional[str] = Field(None, title="Default Value", description="New default value (optional)")
    enabled: Optional[str] = Field(
        None, title="Enabled", description="Enable or disable the field (optional)",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class PagerDutyDeleteCustomFieldConfig(BaseModel):
    """Delete an incident custom field."""

    operation: Literal["delete_custom_field"] = Field(
        "delete_custom_field",
        json_schema_extra={"const": "delete_custom_field", "ui:hidden": True, "x-category": "Custom Fields", "x-is-trigger": False, "x-display-name": "Delete Custom Field"},
        title="Delete Custom Field",
    )
    field_id: str = Field(..., title="Field ID", description="The custom field to delete")


class PagerDutyListFieldOptionsConfig(BaseModel):
    """List the fixed value options for a custom field."""

    operation: Literal["list_field_options"] = Field(
        "list_field_options",
        json_schema_extra={"const": "list_field_options", "ui:hidden": True, "x-category": "Custom Fields", "x-is-trigger": False, "x-display-name": "List Field Options"},
        title="List Field Options",
    )
    field_id: str = Field(..., title="Field ID", description="The custom field whose options to list")


class PagerDutyCreateFieldOptionConfig(BaseModel):
    """Add a fixed value option to a custom field."""

    operation: Literal["create_field_option"] = Field(
        "create_field_option",
        json_schema_extra={"const": "create_field_option", "ui:hidden": True, "x-category": "Custom Fields", "x-is-trigger": False, "x-display-name": "Create Field Option"},
        title="Create Field Option",
    )
    field_id: str = Field(..., title="Field ID", description="The custom field to add the option to")
    value: str = Field(..., title="Value", description="The option value (max 100 characters)")


class PagerDutyGetFieldOptionConfig(BaseModel):
    """Retrieve a single custom field option by ID."""

    operation: Literal["get_field_option"] = Field(
        "get_field_option",
        json_schema_extra={"const": "get_field_option", "ui:hidden": True, "x-category": "Custom Fields", "x-is-trigger": False, "x-display-name": "Get Field Option"},
        title="Get Field Option",
    )
    field_id: str = Field(..., title="Field ID", description="The parent custom field")
    field_option_id: str = Field(..., title="Field Option ID", description="The option to retrieve")


class PagerDutyUpdateFieldOptionConfig(BaseModel):
    """Update the value of a custom field option."""

    operation: Literal["update_field_option"] = Field(
        "update_field_option",
        json_schema_extra={"const": "update_field_option", "ui:hidden": True, "x-category": "Custom Fields", "x-is-trigger": False, "x-display-name": "Update Field Option"},
        title="Update Field Option",
    )
    field_id: str = Field(..., title="Field ID", description="The parent custom field")
    field_option_id: str = Field(..., title="Field Option ID", description="The option to update")
    value: str = Field(..., title="Value", description="The new option value (max 100 characters)")


class PagerDutyDeleteFieldOptionConfig(BaseModel):
    """Delete a custom field option."""

    operation: Literal["delete_field_option"] = Field(
        "delete_field_option",
        json_schema_extra={"const": "delete_field_option", "ui:hidden": True, "x-category": "Custom Fields", "x-is-trigger": False, "x-display-name": "Delete Field Option"},
        title="Delete Field Option",
    )
    field_id: str = Field(..., title="Field ID", description="The parent custom field")
    field_option_id: str = Field(..., title="Field Option ID", description="The option to delete")


class PagerDutyListTemplatesConfig(BaseModel):
    """List status-update templates, optionally filtered by type."""

    operation: Literal["list_templates"] = Field(
        "list_templates",
        json_schema_extra={"const": "list_templates", "ui:hidden": True, "x-category": "Templates", "x-is-trigger": False, "x-display-name": "List Templates"},
        title="List Templates",
    )
    template_type: Optional[str] = Field(
        None, title="Template Type", description="Filter by template type (optional)",
        json_schema_extra={"enum": ["", "status_update"], "enumNames": ["All", "Status Update"], "x-enum-searchable": True},
    )


class PagerDutyCreateTemplateConfig(BaseModel):
    """Create a status-update template."""

    operation: Literal["create_template"] = Field(
        "create_template",
        json_schema_extra={"const": "create_template", "ui:hidden": True, "x-category": "Templates", "x-is-trigger": False, "x-display-name": "Create Template"},
        title="Create Template",
    )
    name: str = Field(..., title="Name", description="The template name")
    template_type: str = Field(
        "status_update", title="Template Type", description="The kind of template",
        json_schema_extra={"enum": ["status_update"], "enumNames": ["Status Update"], "x-enum-searchable": True},
    )
    description: Optional[str] = Field(None, title="Description", description="A description of the template (optional)")
    templated_fields: Optional[str] = Field(
        None, title="Templated Fields", description='JSON object of templated fields, e.g. {"subject": "...", "body": "..."} (optional)',
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyGetTemplateConfig(BaseModel):
    """Retrieve a single template by ID."""

    operation: Literal["get_template"] = Field(
        "get_template",
        json_schema_extra={"const": "get_template", "ui:hidden": True, "x-category": "Templates", "x-is-trigger": False, "x-display-name": "Get Template"},
        title="Get Template",
    )
    template_id: str = Field(..., title="Template ID", description="The template to retrieve")


class PagerDutyUpdateTemplateConfig(BaseModel):
    """Update an existing template."""

    operation: Literal["update_template"] = Field(
        "update_template",
        json_schema_extra={"const": "update_template", "ui:hidden": True, "x-category": "Templates", "x-is-trigger": False, "x-display-name": "Update Template"},
        title="Update Template",
    )
    template_id: str = Field(..., title="Template ID", description="The template to update")
    name: Optional[str] = Field(None, title="Name", description="New template name (optional)")
    description: Optional[str] = Field(None, title="Description", description="New description (optional)")
    templated_fields: Optional[str] = Field(
        None, title="Templated Fields", description='JSON object of templated fields to replace (optional)',
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyDeleteTemplateConfig(BaseModel):
    """Delete a template."""

    operation: Literal["delete_template"] = Field(
        "delete_template",
        json_schema_extra={"const": "delete_template", "ui:hidden": True, "x-category": "Templates", "x-is-trigger": False, "x-display-name": "Delete Template"},
        title="Delete Template",
    )
    template_id: str = Field(..., title="Template ID", description="The template to delete")


class PagerDutyRenderTemplateConfig(BaseModel):
    """Render a status-update template against an incident."""

    operation: Literal["render_template"] = Field(
        "render_template",
        json_schema_extra={"const": "render_template", "ui:hidden": True, "x-category": "Templates", "x-is-trigger": False, "x-display-name": "Render Template"},
        title="Render Template",
    )
    template_id: str = Field(..., title="Template ID", description="The template to render")
    incident_id: str = Field(..., title="Incident ID", description="The incident to render the template against")
    message: Optional[str] = Field(
        None, title="Message Override", description="Override the status update message (optional)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PagerDutyListTagsConfig(BaseModel):
    """List tags, optionally filtered by a name query."""

    operation: Literal["list_tags"] = Field(
        "list_tags",
        json_schema_extra={"const": "list_tags", "ui:hidden": True, "x-category": "Tags", "x-is-trigger": False, "x-display-name": "List Tags"},
        title="List Tags",
    )
    query: Optional[str] = Field(None, title="Query", description="Filter tags by label (optional)")
    limit: Optional[str] = Field("25", title="Limit", description="Max number of tags to return (1-100)")


class PagerDutyCreateTagConfig(BaseModel):
    """Create a tag with a label."""

    operation: Literal["create_tag"] = Field(
        "create_tag",
        json_schema_extra={"const": "create_tag", "ui:hidden": True, "x-category": "Tags", "x-is-trigger": False, "x-display-name": "Create Tag"},
        title="Create Tag",
    )
    label: str = Field(..., title="Label", description="The tag label")


class PagerDutyGetTagConfig(BaseModel):
    """Retrieve a single tag by ID."""

    operation: Literal["get_tag"] = Field(
        "get_tag",
        json_schema_extra={"const": "get_tag", "ui:hidden": True, "x-category": "Tags", "x-is-trigger": False, "x-display-name": "Get Tag"},
        title="Get Tag",
    )
    tag_id: str = Field(..., title="Tag ID", description="The tag to retrieve")


class PagerDutyDeleteTagConfig(BaseModel):
    """Delete a tag."""

    operation: Literal["delete_tag"] = Field(
        "delete_tag",
        json_schema_extra={"const": "delete_tag", "ui:hidden": True, "x-category": "Tags", "x-is-trigger": False, "x-display-name": "Delete Tag"},
        title="Delete Tag",
    )
    tag_id: str = Field(..., title="Tag ID", description="The tag to delete")


class PagerDutyGetTagsForEntityConfig(BaseModel):
    """Get the tags assigned to a user, team, or escalation policy."""

    operation: Literal["get_tags_for_entity"] = Field(
        "get_tags_for_entity",
        json_schema_extra={"const": "get_tags_for_entity", "ui:hidden": True, "x-category": "Tags", "x-is-trigger": False, "x-display-name": "Get Tags for Entity"},
        title="Get Tags for Entity",
    )
    entity_type: str = Field(
        "users", title="Entity Type", description="The kind of entity to read tags from",
        json_schema_extra={"enum": ["users", "teams", "escalation_policies"], "enumNames": ["Users", "Teams", "Escalation Policies"], "x-enum-searchable": True},
    )
    entity_id: str = Field(..., title="Entity ID", description="The ID of the user/team/escalation policy")


class PagerDutyChangeTagsConfig(BaseModel):
    """Add and/or remove tags on a user, team, or escalation policy."""

    operation: Literal["change_tags"] = Field(
        "change_tags",
        json_schema_extra={"const": "change_tags", "ui:hidden": True, "x-category": "Tags", "x-is-trigger": False, "x-display-name": "Assign / Remove Tags"},
        title="Assign / Remove Tags",
    )
    entity_type: str = Field(
        "users", title="Entity Type", description="The kind of entity to change tags on",
        json_schema_extra={"enum": ["users", "teams", "escalation_policies"], "enumNames": ["Users", "Teams", "Escalation Policies"], "x-enum-searchable": True},
    )
    entity_id: str = Field(..., title="Entity ID", description="The ID of the user/team/escalation policy")
    add_tag_ids: Optional[str] = Field(None, title="Add Tag IDs", description="Existing tag IDs to assign, comma-separated")
    add_tag_labels: Optional[str] = Field(None, title="Add New Tags", description="Labels of new tags to create and assign, comma-separated")
    remove_tag_ids: Optional[str] = Field(None, title="Remove Tag IDs", description="Tag IDs to unassign, comma-separated")


class PagerDutyListVendorsConfig(BaseModel):
    """List integration vendors known to PagerDuty."""

    operation: Literal["list_vendors"] = Field(
        "list_vendors",
        json_schema_extra={"const": "list_vendors", "ui:hidden": True, "x-category": "Vendors", "x-is-trigger": False, "x-display-name": "List Vendors"},
        title="List Vendors",
    )
    limit: Optional[str] = Field("25", title="Limit", description="Max number of vendors to return (1-100)")


class PagerDutyGetVendorConfig(BaseModel):
    """Retrieve a single vendor by ID."""

    operation: Literal["get_vendor"] = Field(
        "get_vendor",
        json_schema_extra={"const": "get_vendor", "ui:hidden": True, "x-category": "Vendors", "x-is-trigger": False, "x-display-name": "Get Vendor"},
        title="Get Vendor",
    )
    vendor_id: str = Field(..., title="Vendor ID", description="The vendor to retrieve")


class PagerDutyListAddonsConfig(BaseModel):
    """List installed add-ons, optionally filtered by type."""

    operation: Literal["list_addons"] = Field(
        "list_addons",
        json_schema_extra={"const": "list_addons", "ui:hidden": True, "x-category": "Add-ons", "x-is-trigger": False, "x-display-name": "List Add-ons"},
        title="List Add-ons",
    )
    filter: Optional[str] = Field(
        None, title="Filter", description="Limit to add-ons of a particular type (optional)",
        json_schema_extra={"enum": ["", "full_page_addon", "incident_show_addon"], "enumNames": ["All", "Full Page", "Incident Show"], "x-enum-searchable": True},
    )


class PagerDutyCreateAddonConfig(BaseModel):
    """Install an add-on that embeds a URL in the PagerDuty UI."""

    operation: Literal["create_addon"] = Field(
        "create_addon",
        json_schema_extra={"const": "create_addon", "ui:hidden": True, "x-category": "Add-ons", "x-is-trigger": False, "x-display-name": "Create Add-on"},
        title="Create Add-on",
    )
    addon_type: str = Field(
        "full_page_addon", title="Type", description="Where the add-on appears",
        json_schema_extra={"enum": ["full_page_addon", "incident_show_addon"], "enumNames": ["Full Page", "Incident Show"], "x-enum-searchable": True},
    )
    name: str = Field(..., title="Name", description="The add-on name (max 100 characters)")
    src: str = Field(..., title="Source URL", description="The HTTPS URL embedded in an iframe in the PagerDuty UI")
    service_ids: Optional[str] = Field(
        None, title="Services", description="Restrict an incident-show add-on to these services (optional)",
        json_schema_extra={"x-dynamic-options": {"field_name": "service_ids", "placeholder": "Select service(s)...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste service ID(s), comma-separated"}},
    )


class PagerDutyGetAddonConfig(BaseModel):
    """Retrieve a single add-on by ID."""

    operation: Literal["get_addon"] = Field(
        "get_addon",
        json_schema_extra={"const": "get_addon", "ui:hidden": True, "x-category": "Add-ons", "x-is-trigger": False, "x-display-name": "Get Add-on"},
        title="Get Add-on",
    )
    addon_id: str = Field(..., title="Add-on ID", description="The add-on to retrieve")


class PagerDutyUpdateAddonConfig(BaseModel):
    """Update an installed add-on (full replacement — all fields required)."""

    operation: Literal["update_addon"] = Field(
        "update_addon",
        json_schema_extra={"const": "update_addon", "ui:hidden": True, "x-category": "Add-ons", "x-is-trigger": False, "x-display-name": "Update Add-on"},
        title="Update Add-on",
    )
    addon_id: str = Field(..., title="Add-on ID", description="The add-on to update")
    addon_type: str = Field(
        "full_page_addon", title="Type", description="Where the add-on appears",
        json_schema_extra={"enum": ["full_page_addon", "incident_show_addon"], "enumNames": ["Full Page", "Incident Show"], "x-enum-searchable": True},
    )
    name: str = Field(..., title="Name", description="The add-on name (max 100 characters)")
    src: str = Field(..., title="Source URL", description="The HTTPS URL embedded in an iframe in the PagerDuty UI")


class PagerDutyDeleteAddonConfig(BaseModel):
    """Delete an installed add-on."""

    operation: Literal["delete_addon"] = Field(
        "delete_addon",
        json_schema_extra={"const": "delete_addon", "ui:hidden": True, "x-category": "Add-ons", "x-is-trigger": False, "x-display-name": "Delete Add-on"},
        title="Delete Add-on",
    )
    addon_id: str = Field(..., title="Add-on ID", description="The add-on to delete")


class PagerDutyListAbilitiesConfig(BaseModel):
    """List the abilities (feature entitlements) the account has."""

    operation: Literal["list_abilities"] = Field(
        "list_abilities",
        json_schema_extra={"const": "list_abilities", "ui:hidden": True, "x-category": "Reference", "x-is-trigger": False, "x-display-name": "List Abilities"},
        title="List Abilities",
    )


class PagerDutyTestAbilityConfig(BaseModel):
    """Test whether the account has a specific ability (returns success if enabled)."""

    operation: Literal["test_ability"] = Field(
        "test_ability",
        json_schema_extra={"const": "test_ability", "ui:hidden": True, "x-category": "Reference", "x-is-trigger": False, "x-display-name": "Test Ability"},
        title="Test Ability",
    )
    ability_id: str = Field(..., title="Ability", description="The ability to test (e.g. sso, teams, advanced_reports)")


class PagerDutyListNotificationsConfig(BaseModel):
    """List notifications sent during a required time range."""

    operation: Literal["list_notifications"] = Field(
        "list_notifications",
        json_schema_extra={"const": "list_notifications", "ui:hidden": True, "x-category": "Reference", "x-is-trigger": False, "x-display-name": "List Notifications"},
        title="List Notifications",
    )
    since: str = Field(..., title="Since", description="ISO 8601 start of the range (required; max 3 months span)")
    until: str = Field(..., title="Until", description="ISO 8601 end of the range (required; max 3 months span)")
    filter: Optional[str] = Field(
        None, title="Filter", description="Limit to a notification channel (optional)",
        json_schema_extra={"enum": ["", "sms_notification", "email_notification", "phone_notification", "push_notification"], "enumNames": ["All", "SMS", "Email", "Phone", "Push"], "x-enum-searchable": True},
    )
    time_zone: Optional[str] = Field(None, title="Time Zone", description="Time zone for the returned timestamps (optional)")
    limit: Optional[str] = Field("25", title="Limit", description="Max number of notifications to return (1-100)")


class PagerDutyListLicensesConfig(BaseModel):
    """List the licenses available on the account."""

    operation: Literal["list_licenses"] = Field(
        "list_licenses",
        json_schema_extra={"const": "list_licenses", "ui:hidden": True, "x-category": "Reference", "x-is-trigger": False, "x-display-name": "List Licenses"},
        title="List Licenses",
    )


class PagerDutyListLicenseAllocationsConfig(BaseModel):
    """List how licenses are allocated across users."""

    operation: Literal["list_license_allocations"] = Field(
        "list_license_allocations",
        json_schema_extra={"const": "list_license_allocations", "ui:hidden": True, "x-category": "Reference", "x-is-trigger": False, "x-display-name": "List License Allocations"},
        title="List License Allocations",
    )
    limit: Optional[str] = Field("25", title="Limit", description="Max number of allocations to return (1-100)")


class PagerDutyPausedIncidentReportAlertsConfig(BaseModel):
    """Report the alerts that were paused (auto-pause / intelligent alert grouping) in a range."""

    operation: Literal["paused_incident_report_alerts"] = Field(
        "paused_incident_report_alerts",
        json_schema_extra={"const": "paused_incident_report_alerts", "ui:hidden": True, "x-category": "Reference", "x-is-trigger": False, "x-display-name": "Paused Incident Report: Alerts"},
        title="Paused Incident Report: Alerts",
    )
    since: Optional[str] = Field(None, title="Since", description="ISO 8601 start of the range (optional; defaults to last month)")
    until: Optional[str] = Field(None, title="Until", description="ISO 8601 end of the range (optional)")
    service_id: Optional[str] = Field(
        None, title="Service", description="Restrict the report to a single service (optional)",
        json_schema_extra={"x-dynamic-options": {"field_name": "service_id", "placeholder": "Select a service...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste service ID"}},
    )
    suspended_by: Optional[str] = Field(
        None, title="Suspended By", description="Filter by what paused the alert (optional)",
        json_schema_extra={"enum": ["", "auto_pause", "rules"], "enumNames": ["All", "Auto-Pause", "Rules"], "x-enum-searchable": True},
    )


class PagerDutyPausedIncidentReportCountsConfig(BaseModel):
    """Report aggregate counts of paused alerts in a range."""

    operation: Literal["paused_incident_report_counts"] = Field(
        "paused_incident_report_counts",
        json_schema_extra={"const": "paused_incident_report_counts", "ui:hidden": True, "x-category": "Reference", "x-is-trigger": False, "x-display-name": "Paused Incident Report: Counts"},
        title="Paused Incident Report: Counts",
    )
    since: Optional[str] = Field(None, title="Since", description="ISO 8601 start of the range (optional; defaults to last month)")
    until: Optional[str] = Field(None, title="Until", description="ISO 8601 end of the range (optional)")
    service_id: Optional[str] = Field(
        None, title="Service", description="Restrict the report to a single service (optional)",
        json_schema_extra={"x-dynamic-options": {"field_name": "service_id", "placeholder": "Select a service...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste service ID"}},
    )
    suspended_by: Optional[str] = Field(
        None, title="Suspended By", description="Filter by what paused the alert (optional)",
        json_schema_extra={"enum": ["", "auto_pause", "rules"], "enumNames": ["All", "Auto-Pause", "Rules"], "x-enum-searchable": True},
    )


# ============================================================================
# Discriminated Union
# ============================================================================


PagerDutyConfig = Annotated[
    Union[
        PagerDutyListIncidentsConfig,
        PagerDutyGetIncidentConfig,
        PagerDutyCreateIncidentConfig,
        PagerDutyUpdateIncidentConfig,
        PagerDutyManageIncidentsConfig,
        PagerDutySnoozeIncidentConfig,
        PagerDutyMergeIncidentsConfig,
        PagerDutyListNotesConfig,
        PagerDutyCreateNoteConfig,
        PagerDutyCreateStatusUpdateConfig,
        PagerDutyListAlertsConfig,
        PagerDutyListLogEntriesConfig,
        PagerDutyAddRespondersConfig,
        PagerDutyListServicesConfig,
        PagerDutyGetServiceConfig,
        PagerDutyCreateServiceConfig,
        PagerDutyUpdateServiceConfig,
        PagerDutyListSchedulesConfig,
        PagerDutyGetScheduleConfig,
        PagerDutyListOnCallsConfig,
        PagerDutyListEscalationPoliciesConfig,
        PagerDutyCreateEscalationPolicyConfig,
        PagerDutyListUsersConfig,
        PagerDutyGetUserConfig,
        PagerDutyCreateUserConfig,
        PagerDutyGetCurrentUserConfig,
        PagerDutyListTeamsConfig,
        PagerDutyListMaintenanceWindowsConfig,
        PagerDutyCreateMaintenanceWindowConfig,
        PagerDutySendEventConfig,
        PagerDutyListWebhookSubscriptionsConfig,
        PagerDutyCreateWebhookSubscriptionConfig,
        PagerDutyListPrioritiesConfig,
        PagerDutyIncidentTriggerConfig,
        PagerDutyGetAlertConfig,
        PagerDutyUpdateAlertConfig,
        PagerDutyManageAlertsConfig,
        PagerDutyGetIncidentCustomFieldsConfig,
        PagerDutyUpdateIncidentCustomFieldsConfig,
        PagerDutyListRelatedChangeEventsConfig,
        PagerDutyGetPastIncidentsConfig,
        PagerDutyGetRelatedIncidentsConfig,
        PagerDutyGetOutlierIncidentConfig,
        PagerDutyListStatusUpdateSubscribersConfig,
        PagerDutyAddStatusUpdateSubscribersConfig,
        PagerDutyRemoveStatusUpdateSubscriberConfig,
        PagerDutyListGlobalLogEntriesConfig,
        PagerDutyGetLogEntryConfig,
        PagerDutyDeleteServiceConfig,
        PagerDutyAssociateServiceDependenciesConfig,
        PagerDutyDisassociateServiceDependenciesConfig,
        PagerDutyGetTechnicalServiceDependenciesConfig,
        PagerDutyGetBusinessServiceDependenciesConfig,
        PagerDutyCreateServiceIntegrationConfig,
        PagerDutyGetServiceIntegrationConfig,
        PagerDutyUpdateServiceIntegrationConfig,
        PagerDutyListServiceEventRulesConfig,
        PagerDutyCreateServiceEventRuleConfig,
        PagerDutyGetServiceEventRuleConfig,
        PagerDutyUpdateServiceEventRuleConfig,
        PagerDutyDeleteServiceEventRuleConfig,
        PagerDutyCreateScheduleConfig,
        PagerDutyUpdateScheduleConfig,
        PagerDutyDeleteScheduleConfig,
        PagerDutyPreviewScheduleConfig,
        PagerDutyListUsersOnScheduleConfig,
        PagerDutyListOverridesConfig,
        PagerDutyCreateOverrideConfig,
        PagerDutyDeleteOverrideConfig,
        PagerDutyGetEscalationPolicyConfig,
        PagerDutyUpdateEscalationPolicyConfig,
        PagerDutyDeleteEscalationPolicyConfig,
        PagerDutyUpdateUserConfig,
        PagerDutyDeleteUserConfig,
        PagerDutyListContactMethodsConfig,
        PagerDutyCreateContactMethodConfig,
        PagerDutyGetContactMethodConfig,
        PagerDutyUpdateContactMethodConfig,
        PagerDutyDeleteContactMethodConfig,
        PagerDutyListNotificationRulesConfig,
        PagerDutyCreateNotificationRuleConfig,
        PagerDutyGetNotificationRuleConfig,
        PagerDutyUpdateNotificationRuleConfig,
        PagerDutyDeleteNotificationRuleConfig,
        PagerDutyGetTeamConfig,
        PagerDutyCreateTeamConfig,
        PagerDutyUpdateTeamConfig,
        PagerDutyDeleteTeamConfig,
        PagerDutyListTeamMembersConfig,
        PagerDutyAddTeamMemberConfig,
        PagerDutyRemoveTeamMemberConfig,
        PagerDutyAssociateTeamEscalationPolicyConfig,
        PagerDutyRemoveTeamEscalationPolicyConfig,
        PagerDutyGetMaintenanceWindowConfig,
        PagerDutyUpdateMaintenanceWindowConfig,
        PagerDutyDeleteMaintenanceWindowConfig,
        PagerDutyGetWebhookSubscriptionConfig,
        PagerDutyUpdateWebhookSubscriptionConfig,
        PagerDutyDeleteWebhookSubscriptionConfig,
        PagerDutyEnableWebhookSubscriptionConfig,
        PagerDutyDisableWebhookSubscriptionConfig,
        PagerDutyPingWebhookSubscriptionConfig,
        PagerDutyListExtensionsConfig,
        PagerDutyCreateExtensionConfig,
        PagerDutyGetExtensionConfig,
        PagerDutyUpdateExtensionConfig,
        PagerDutyDeleteExtensionConfig,
        PagerDutyEnableExtensionConfig,
        PagerDutyListExtensionSchemasConfig,
        PagerDutyGetExtensionSchemaConfig,
        PagerDutyListEventOrchestrationsConfig,
        PagerDutyGetEventOrchestrationConfig,
        PagerDutyCreateEventOrchestrationConfig,
        PagerDutyUpdateEventOrchestrationConfig,
        PagerDutyDeleteEventOrchestrationConfig,
        PagerDutyGetOrchestrationRouterConfig,
        PagerDutyUpdateOrchestrationRouterConfig,
        PagerDutyGetOrchestrationGlobalConfig,
        PagerDutyUpdateOrchestrationGlobalConfig,
        PagerDutyGetServiceOrchestrationConfig,
        PagerDutyUpdateServiceOrchestrationConfig,
        PagerDutyGetServiceOrchestrationActiveConfig,
        PagerDutySetServiceOrchestrationActiveConfig,
        PagerDutyListOrchestrationIntegrationsConfig,
        PagerDutyCreateOrchestrationIntegrationConfig,
        PagerDutyGetOrchestrationIntegrationConfig,
        PagerDutyUpdateOrchestrationIntegrationConfig,
        PagerDutyDeleteOrchestrationIntegrationConfig,
        PagerDutyListRulesetsConfig,
        PagerDutyCreateRulesetConfig,
        PagerDutyGetRulesetConfig,
        PagerDutyUpdateRulesetConfig,
        PagerDutyDeleteRulesetConfig,
        PagerDutyListRulesetRulesConfig,
        PagerDutyCreateRulesetRuleConfig,
        PagerDutyGetRulesetRuleConfig,
        PagerDutyUpdateRulesetRuleConfig,
        PagerDutyDeleteRulesetRuleConfig,
        PagerDutyListResponsePlaysConfig,
        PagerDutyGetResponsePlayConfig,
        PagerDutyCreateResponsePlayConfig,
        PagerDutyUpdateResponsePlayConfig,
        PagerDutyDeleteResponsePlayConfig,
        PagerDutyRunResponsePlayConfig,
        PagerDutyListAutomationActionsConfig,
        PagerDutyGetAutomationActionConfig,
        PagerDutyCreateAutomationActionConfig,
        PagerDutyUpdateAutomationActionConfig,
        PagerDutyDeleteAutomationActionConfig,
        PagerDutyInvokeAutomationActionConfig,
        PagerDutyListInvocationsConfig,
        PagerDutyGetInvocationConfig,
        PagerDutyListRunnersConfig,
        PagerDutyGetRunnerConfig,
        PagerDutyCreateRunnerConfig,
        PagerDutyUpdateRunnerConfig,
        PagerDutyDeleteRunnerConfig,
        PagerDutyListIncidentWorkflowsConfig,
        PagerDutyGetIncidentWorkflowConfig,
        PagerDutyCreateIncidentWorkflowConfig,
        PagerDutyUpdateIncidentWorkflowConfig,
        PagerDutyDeleteIncidentWorkflowConfig,
        PagerDutyStartIncidentWorkflowConfig,
        PagerDutyListIncidentWorkflowTriggersConfig,
        PagerDutyGetIncidentWorkflowTriggerConfig,
        PagerDutyCreateIncidentWorkflowTriggerConfig,
        PagerDutyUpdateIncidentWorkflowTriggerConfig,
        PagerDutyDeleteIncidentWorkflowTriggerConfig,
        PagerDutyAssociateTriggerServiceConfig,
        PagerDutyDisassociateTriggerServiceConfig,
        PagerDutyListBusinessServicesConfig,
        PagerDutyGetBusinessServiceConfig,
        PagerDutyCreateBusinessServiceConfig,
        PagerDutyUpdateBusinessServiceConfig,
        PagerDutyDeleteBusinessServiceConfig,
        PagerDutyListBusinessServiceSubscribersConfig,
        PagerDutyCreateBusinessServiceSubscribersConfig,
        PagerDutyRemoveBusinessServiceSubscribersConfig,
        PagerDutyListBusinessServiceImpactsConfig,
        PagerDutyListBusinessServiceImpactorsConfig,
        PagerDutyGetPriorityThresholdsConfig,
        PagerDutySetPriorityThresholdConfig,
        PagerDutyDeletePriorityThresholdsConfig,
        PagerDutyListStatusDashboardsConfig,
        PagerDutyGetStatusDashboardConfig,
        PagerDutyGetStatusDashboardBySlugConfig,
        PagerDutyGetStatusDashboardServiceImpactsConfig,
        PagerDutyListStatusPagesConfig,
        PagerDutyListStatusPagePostsConfig,
        PagerDutyCreateStatusPagePostConfig,
        PagerDutyGetStatusPagePostConfig,
        PagerDutyUpdateStatusPagePostConfig,
        PagerDutyDeleteStatusPagePostConfig,
        PagerDutyListStatusPagePostUpdatesConfig,
        PagerDutyCreateStatusPagePostUpdateConfig,
        PagerDutyGetStatusPagePostUpdateConfig,
        PagerDutyUpdateStatusPagePostUpdateConfig,
        PagerDutyDeleteStatusPagePostUpdateConfig,
        PagerDutyListStatusPageSubscriptionsConfig,
        PagerDutyCreateStatusPageSubscriptionConfig,
        PagerDutyGetStatusPageSubscriptionConfig,
        PagerDutyDeleteStatusPageSubscriptionConfig,
        PagerDutyIncidentMetricsConfig,
        PagerDutyIncidentMetricsByDimensionConfig,
        PagerDutyRawIncidentsConfig,
        PagerDutyGetRawIncidentConfig,
        PagerDutyRawIncidentResponsesConfig,
        PagerDutyResponderMetricsConfig,
        PagerDutyListAuditRecordsConfig,
        PagerDutySendChangeEventConfig,
        PagerDutyListChangeEventsConfig,
        PagerDutyListServiceChangeEventsConfig,
        PagerDutyListCustomFieldsConfig,
        PagerDutyCreateCustomFieldConfig,
        PagerDutyGetCustomFieldConfig,
        PagerDutyUpdateCustomFieldConfig,
        PagerDutyDeleteCustomFieldConfig,
        PagerDutyListFieldOptionsConfig,
        PagerDutyCreateFieldOptionConfig,
        PagerDutyGetFieldOptionConfig,
        PagerDutyUpdateFieldOptionConfig,
        PagerDutyDeleteFieldOptionConfig,
        PagerDutyListTemplatesConfig,
        PagerDutyCreateTemplateConfig,
        PagerDutyGetTemplateConfig,
        PagerDutyUpdateTemplateConfig,
        PagerDutyDeleteTemplateConfig,
        PagerDutyRenderTemplateConfig,
        PagerDutyListTagsConfig,
        PagerDutyCreateTagConfig,
        PagerDutyGetTagConfig,
        PagerDutyDeleteTagConfig,
        PagerDutyGetTagsForEntityConfig,
        PagerDutyChangeTagsConfig,
        PagerDutyListVendorsConfig,
        PagerDutyGetVendorConfig,
        PagerDutyListAddonsConfig,
        PagerDutyCreateAddonConfig,
        PagerDutyGetAddonConfig,
        PagerDutyUpdateAddonConfig,
        PagerDutyDeleteAddonConfig,
        PagerDutyListAbilitiesConfig,
        PagerDutyTestAbilityConfig,
        PagerDutyListNotificationsConfig,
        PagerDutyListLicensesConfig,
        PagerDutyListLicenseAllocationsConfig,
        PagerDutyPausedIncidentReportAlertsConfig,
        PagerDutyPausedIncidentReportCountsConfig,
    ],
    Discriminator("operation"),
]


class PagerDutyNodeConfig(NodeConfig[PagerDutyConfig, PagerDutyCredential]):
    """Full configuration for the PagerDuty node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _token_from_credential(credential: Any) -> Optional[str]:
    """Resolve the bearer token from either credential type.

    API-key credentials store it in ``api_key``; OAuth credentials store it in
    ``access_token``. Accepts a Pydantic model or a decrypted credential dict.
    """
    if credential is None:
        return None
    get = credential.get if isinstance(credential, dict) else lambda k: getattr(credential, k, None)
    return get("access_token") or get("api_key")


def _ref(rid: str, rtype: str) -> Dict[str, str]:
    """Build a PagerDuty resource reference object."""
    return {"id": rid, "type": rtype}


def _safe_int(value: Any, field_name: str) -> int:
    """Coerce a config string to int, raising a descriptive ValueError instead
    of an unguarded ValueError/TypeError that would escape execute()."""
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ValueError(f"'{field_name}' must be a whole number, got {value!r}")


def _safe_json(value: Any, field_name: str) -> Any:
    """Parse a config JSON string, raising a descriptive ValueError instead of an
    unguarded JSONDecodeError/TypeError that would escape execute()."""
    try:
        return json.loads(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"'{field_name}' must be valid JSON: {e}")


async def _pagerduty_request(
    api_key: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    from_email: Optional[str] = None,
    action_name: str = "request",
    base_url: Optional[str] = None,
    use_token_auth: bool = True,
) -> Dict[str, Any]:
    """Make an authenticated PagerDuty request and return a structured result.

    REST API keys use ``Authorization: Token token=<KEY>``; OAuth access tokens
    (prefixed ``pdus+_`` / ``pdeu+_``) use ``Authorization: Bearer <token>``. The
    header format is auto-detected from the token prefix so the whole handler
    layer can stay credential-type agnostic. The Events API v2 host authenticates
    via a routing_key in the body, so callers send ``use_token_auth=False`` for it.
    """
    url = endpoint if endpoint.startswith("http") else f"{base_url or _rest_base()}{endpoint}"
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/vnd.pagerduty+json;version=2",
    }
    if use_token_auth:
        if api_key and api_key.startswith(("pdus+_", "pdeu+_")):
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            headers["Authorization"] = f"Token token={api_key}"
    if from_email:
        headers["From"] = from_email

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
            if response.status_code >= 400:
                try:
                    err = response.json()
                    error_block = err.get("error") if isinstance(err, dict) else None
                    if isinstance(error_block, dict):
                        message = error_block.get("message", str(error_block))
                        errors = error_block.get("errors")
                        if errors:
                            message = f"{message}: {errors}"
                    else:
                        message = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[PagerDutyNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204 or not response.content:
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
            logger.error(f"[PagerDutyNode] Request failed ({action_name}): {msg}")
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


class PagerDutyNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """PagerDuty incident management automation node."""

    edit_examples = [
        "List all triggered incidents on the payments service",
        "Create a high-urgency incident when a monitor fails",
        "Acknowledge or resolve an incident from a workflow",
        "Add a note or status update to an incident",
        "Find who is currently on-call for a schedule",
        "Trigger a workflow whenever an incident is triggered or resolved",
    ]

    scope_registry = PAGERDUTY_SCOPES
    connection_evidence = ConnectionEvidence(
        field="escalation_policy_id",
        noun="escalation policies",
    )

    @classmethod
    def get_config_model(cls):
        return PagerDutyNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring PagerDuty OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating REST API keys (which carry
        no refresh_token)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.pagerduty_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="pagerduty",
        )

    async def _ensure_fresh_token(self, credentials: "PagerDutyCredential") -> None:
        """Refresh an expired PagerDuty OAuth token in place before an API call.
        REST API keys carry no refresh_token and are left untouched."""
        if not isinstance(credentials, PagerDutyOAuthCredential):
            return

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.pagerduty_oauth import refresh_access_token

        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="pagerduty",
            caller_path="execute",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]

    # ------------------------------------------------------------------
    # Dynamic options (top-level listable resources)
    # ------------------------------------------------------------------
    # Maps each dynamic field to the LIST endpoint and its response wrapper key.
    # All are top-level resources the API lists without a parent id.
    _DYNAMIC_RESOURCES: Dict[str, tuple] = {
        "service_id": ("/services", "services"),
        "service_ids": ("/services", "services"),
        "team_ids": ("/teams", "teams"),
        "priority_id": ("/priorities", "priorities"),
        "escalation_policy_id": ("/escalation_policies", "escalation_policies"),
        "escalation_policy_ids": ("/escalation_policies", "escalation_policies"),
        "schedule_id": ("/schedules", "schedules"),
        "schedule_ids": ("/schedules", "schedules"),
        "user_id": ("/users", "users"),
        "user_ids": ("/users", "users"),
        "requester_id": ("/users", "users"),
        "team_id": ("/teams", "teams"),
        "business_service_id": ("/business_services", "business_services"),
        "orchestration_id": ("/event_orchestrations", "orchestrations"),
        "maintenance_window_id": ("/maintenance_windows", "maintenance_windows"),
        "webhook_subscription_id": ("/webhook_subscriptions", "webhook_subscriptions"),
        "external_webhook_id": ("/webhook_subscriptions", "webhook_subscriptions"),
        "extension_id": ("/extensions", "extensions"),
        "extension_schema_id": ("/extension_schemas", "extension_schemas"),
        "response_play_id": ("/response_plays", "response_plays"),
        "vendor_id": ("/vendors", "vendors"),
        "incident_id": ("/incidents", "incidents"),
        "incident_ids": ("/incidents", "incidents"),
    }

    # Inline "Create new <resource>" builder affordances: singular pickers whose
    # resource has a create op. Every create returns data.<singular>.id and the
    # picker stores str(id), so the ids line up.
    _FIELD_RESOURCE_TYPE: Dict[str, str] = {
        "service_id": "pagerduty_service",
        "escalation_policy_id": "pagerduty_escalation_policy",
        "schedule_id": "pagerduty_schedule",
        "user_id": "pagerduty_user",
        "team_id": "pagerduty_team",
        "business_service_id": "pagerduty_business_service",
        "maintenance_window_id": "pagerduty_maintenance_window",
        "extension_id": "pagerduty_extension",
        "response_play_id": "pagerduty_response_play",
    }

    # ISO 8601 date-time fields that render with the datetime picker widget.
    # (``expires_at`` is deliberately excluded — it's an internal OAuth field.)
    _DATETIME_FIELDS = frozenset(
        {"since", "until", "start_time", "end_time", "start", "end", "ends_at", "starts_at"}
    )

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        context = context or {}
        # escalation_target_id picks users OR schedules depending on the
        # sibling escalation_target_type field on the same operation.
        if field_name == "escalation_target_id":
            target_type = context.get("escalation_target_type") or "user_reference"
            endpoint, wrapper = (
                ("/schedules", "schedules")
                if target_type == "schedule_reference"
                else ("/users", "users")
            )
        else:
            resource = cls._DYNAMIC_RESOURCES.get(field_name)
            if not resource:
                return {"options": []}
            endpoint, wrapper = resource

        # credential_data is already loaded, decrypted and freshened by the
        # workflow handler; just resolve the bearer token + region from it.
        api_key = _token_from_credential(credential_data)
        if not api_key:
            return {"options": []}
        _PD_REGION.set(str((credential_data.get("region") if isinstance(credential_data, dict) else None) or "us").lower())

        params: Dict[str, Any] = {"limit": 100}
        if search:
            params["query"] = search
        result = await _pagerduty_request(
            api_key, "GET", endpoint, params=params, action_name=f"list_{wrapper}"
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        rows = data.get(wrapper, []) if isinstance(data, dict) else []
        options = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            rid = row.get("id")
            label = (
                row.get("name")
                or row.get("summary")
                or row.get("title")
                or row.get("label")
                or row.get("email")
                or rid
            )
            if rid:
                options.append({"label": str(label), "value": str(rid)})
        return {"options": options}

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Inject searchable dropdowns for every field that names a listable
        resource (``_DYNAMIC_RESOURCES``), so operations added later get an
        account-populated picker without per-field boilerplate. Fields that
        already declare ``x-dynamic-options`` (e.g. the escalation-target
        picker) are left untouched."""
        schema = super().get_config_schema()

        def _noun(fname: str) -> str:
            return fname.removesuffix("_ids").removesuffix("_id").replace("_", " ")

        def walk(node):
            if isinstance(node, dict):
                props = node.get("properties")
                if isinstance(props, dict):
                    for fname, fschema in props.items():
                        if not isinstance(fschema, dict) or fschema.get("ui:hidden"):
                            continue
                        if (
                            fname in cls._DYNAMIC_RESOURCES
                            and "x-dynamic-options" not in fschema
                        ):
                            noun = _noun(fname)
                            article = "an" if noun[:1] in "aeiou" else "a"
                            fschema["x-dynamic-options"] = {
                                "field_name": fname,
                                "placeholder": f"Select {article} {noun}…",
                                "searchable": True,
                                "allow_custom": True,
                                "custom_placeholder": f"Or paste {article} {noun} ID",
                            }
                        elif fname in cls._DATETIME_FIELDS and "ui:widget" not in fschema:
                            fschema["ui:widget"] = "datetime"
                        rt = cls._FIELD_RESOURCE_TYPE.get(fname)
                        if rt and "x-resource-type" not in fschema:
                            fschema["x-resource-type"] = rt
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(schema)
        return schema

    # ------------------------------------------------------------------
    # Webhook trigger registration (V3 webhook subscriptions)
    # ------------------------------------------------------------------
    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        api_key = _token_from_credential(credential)
        if not api_key:
            raise ValueError("A PagerDuty credential is required to register the trigger")
        body = {
            "webhook_subscription": {
                "type": "webhook_subscription",
                "delivery_method": {
                    "type": "http_delivery_method",
                    "url": webhook_url,
                },
                "events": WEBHOOK_TRIGGER_EVENTS,
                "filter": {"type": "account_reference"},
            }
        }
        result = await _pagerduty_request(
            api_key,
            "POST",
            "/webhook_subscriptions",
            json_body=body,
            action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"PagerDuty webhook registration failed: {result.get('error')}")
        data = result.get("data") or {}
        sub = data.get("webhook_subscription", {}) if isinstance(data, dict) else {}
        external_id = sub.get("id")
        # The signing secret is only returned (in delivery_method.secret) on creation.
        delivery = sub.get("delivery_method", {}) if isinstance(sub, dict) else {}
        secret = delivery.get("secret") if isinstance(delivery, dict) else None
        return {
            "external_webhook_id": str(external_id) if external_id else None,
            "signing_secret": secret,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        api_key = _token_from_credential(credential or {})
        if not external_id or not api_key:
            return
        await _pagerduty_request(
            api_key,
            "DELETE",
            f"/webhook_subscriptions/{external_id}",
            action_name="unregister_webhook",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored — accept (trigger not yet armed)
        sent = headers.get("x-pagerduty-signature")
        if not sent:
            return False
        expected = "v1=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        # The header may carry multiple comma-separated signatures.
        candidates = [s.strip() for s in sent.split(",")]
        return any(hmac.compare_digest(expected, c) for c in candidates)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, PagerDutyNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, PagerDutyIncidentTriggerConfig):
            return {
                "status": "success",
                "action": "on_incident_event",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your PagerDuty API key.")
        await self._ensure_fresh_token(credentials)
        api_key = _token_from_credential(credentials)
        from_email = credentials.from_email
        _PD_REGION.set((getattr(credentials, "region", None) or "us").lower())

        handlers = {
            "list_incidents": self._list_incidents,
            "get_incident": self._get_incident,
            "create_incident": self._create_incident,
            "update_incident": self._update_incident,
            "manage_incidents": self._manage_incidents,
            "snooze_incident": self._snooze_incident,
            "merge_incidents": self._merge_incidents,
            "list_notes": self._list_notes,
            "create_note": self._create_note,
            "create_status_update": self._create_status_update,
            "list_alerts": self._list_alerts,
            "list_log_entries": self._list_log_entries,
            "add_responders": self._add_responders,
            "list_services": self._list_services,
            "get_service": self._get_service,
            "create_service": self._create_service,
            "update_service": self._update_service,
            "list_schedules": self._list_schedules,
            "get_schedule": self._get_schedule,
            "list_oncalls": self._list_oncalls,
            "list_escalation_policies": self._list_escalation_policies,
            "create_escalation_policy": self._create_escalation_policy,
            "list_users": self._list_users,
            "get_user": self._get_user,
            "create_user": self._create_user,
            "get_current_user": self._get_current_user,
            "list_teams": self._list_teams,
            "list_maintenance_windows": self._list_maintenance_windows,
            "create_maintenance_window": self._create_maintenance_window,
            "send_event": self._send_event,
            "list_webhook_subscriptions": self._list_webhook_subscriptions,
            "create_webhook_subscription": self._create_webhook_subscription,
            "list_priorities": self._list_priorities,
            "get_alert": self._get_alert,
            "update_alert": self._update_alert,
            "manage_alerts": self._manage_alerts,
            "get_incident_custom_fields": self._get_incident_custom_fields,
            "update_incident_custom_fields": self._update_incident_custom_fields,
            "list_related_change_events": self._list_related_change_events,
            "get_past_incidents": self._get_past_incidents,
            "get_related_incidents": self._get_related_incidents,
            "get_outlier_incident": self._get_outlier_incident,
            "list_status_update_subscribers": self._list_status_update_subscribers,
            "add_status_update_subscribers": self._add_status_update_subscribers,
            "remove_status_update_subscriber": self._remove_status_update_subscriber,
            "list_global_log_entries": self._list_global_log_entries,
            "get_log_entry": self._get_log_entry,
            "delete_service": self._delete_service,
            "associate_service_dependencies": self._associate_service_dependencies,
            "disassociate_service_dependencies": self._disassociate_service_dependencies,
            "get_technical_service_dependencies": self._get_technical_service_dependencies,
            "get_business_service_dependencies": self._get_business_service_dependencies,
            "create_service_integration": self._create_service_integration,
            "get_service_integration": self._get_service_integration,
            "update_service_integration": self._update_service_integration,
            "list_service_event_rules": self._list_service_event_rules,
            "create_service_event_rule": self._create_service_event_rule,
            "get_service_event_rule": self._get_service_event_rule,
            "update_service_event_rule": self._update_service_event_rule,
            "delete_service_event_rule": self._delete_service_event_rule,
            "create_schedule": self._create_schedule,
            "update_schedule": self._update_schedule,
            "delete_schedule": self._delete_schedule,
            "preview_schedule": self._preview_schedule,
            "list_users_on_schedule": self._list_users_on_schedule,
            "list_overrides": self._list_overrides,
            "create_override": self._create_override,
            "delete_override": self._delete_override,
            "get_escalation_policy": self._get_escalation_policy,
            "update_escalation_policy": self._update_escalation_policy,
            "delete_escalation_policy": self._delete_escalation_policy,
            "update_user": self._update_user,
            "delete_user": self._delete_user,
            "list_contact_methods": self._list_contact_methods,
            "create_contact_method": self._create_contact_method,
            "get_contact_method": self._get_contact_method,
            "update_contact_method": self._update_contact_method,
            "delete_contact_method": self._delete_contact_method,
            "list_notification_rules": self._list_notification_rules,
            "create_notification_rule": self._create_notification_rule,
            "get_notification_rule": self._get_notification_rule,
            "update_notification_rule": self._update_notification_rule,
            "delete_notification_rule": self._delete_notification_rule,
            "get_team": self._get_team,
            "create_team": self._create_team,
            "update_team": self._update_team,
            "delete_team": self._delete_team,
            "list_team_members": self._list_team_members,
            "add_team_member": self._add_team_member,
            "remove_team_member": self._remove_team_member,
            "associate_team_escalation_policy": self._associate_team_escalation_policy,
            "remove_team_escalation_policy": self._remove_team_escalation_policy,
            "get_maintenance_window": self._get_maintenance_window,
            "update_maintenance_window": self._update_maintenance_window,
            "delete_maintenance_window": self._delete_maintenance_window,
            "get_webhook_subscription": self._get_webhook_subscription,
            "update_webhook_subscription": self._update_webhook_subscription,
            "delete_webhook_subscription": self._delete_webhook_subscription,
            "enable_webhook_subscription": self._enable_webhook_subscription,
            "disable_webhook_subscription": self._disable_webhook_subscription,
            "ping_webhook_subscription": self._ping_webhook_subscription,
            "list_extensions": self._list_extensions,
            "create_extension": self._create_extension,
            "get_extension": self._get_extension,
            "update_extension": self._update_extension,
            "delete_extension": self._delete_extension,
            "enable_extension": self._enable_extension,
            "list_extension_schemas": self._list_extension_schemas,
            "get_extension_schema": self._get_extension_schema,
            "list_event_orchestrations": self._list_event_orchestrations,
            "get_event_orchestration": self._get_event_orchestration,
            "create_event_orchestration": self._create_event_orchestration,
            "update_event_orchestration": self._update_event_orchestration,
            "delete_event_orchestration": self._delete_event_orchestration,
            "get_orchestration_router": self._get_orchestration_router,
            "update_orchestration_router": self._update_orchestration_router,
            "get_orchestration_global": self._get_orchestration_global,
            "update_orchestration_global": self._update_orchestration_global,
            "get_service_orchestration": self._get_service_orchestration,
            "update_service_orchestration": self._update_service_orchestration,
            "get_service_orchestration_active": self._get_service_orchestration_active,
            "set_service_orchestration_active": self._set_service_orchestration_active,
            "list_orchestration_integrations": self._list_orchestration_integrations,
            "create_orchestration_integration": self._create_orchestration_integration,
            "get_orchestration_integration": self._get_orchestration_integration,
            "update_orchestration_integration": self._update_orchestration_integration,
            "delete_orchestration_integration": self._delete_orchestration_integration,
            "list_rulesets": self._list_rulesets,
            "create_ruleset": self._create_ruleset,
            "get_ruleset": self._get_ruleset,
            "update_ruleset": self._update_ruleset,
            "delete_ruleset": self._delete_ruleset,
            "list_ruleset_rules": self._list_ruleset_rules,
            "create_ruleset_rule": self._create_ruleset_rule,
            "get_ruleset_rule": self._get_ruleset_rule,
            "update_ruleset_rule": self._update_ruleset_rule,
            "delete_ruleset_rule": self._delete_ruleset_rule,
            "list_response_plays": self._list_response_plays,
            "get_response_play": self._get_response_play,
            "create_response_play": self._create_response_play,
            "update_response_play": self._update_response_play,
            "delete_response_play": self._delete_response_play,
            "run_response_play": self._run_response_play,
            "list_automation_actions": self._list_automation_actions,
            "get_automation_action": self._get_automation_action,
            "create_automation_action": self._create_automation_action,
            "update_automation_action": self._update_automation_action,
            "delete_automation_action": self._delete_automation_action,
            "invoke_automation_action": self._invoke_automation_action,
            "list_invocations": self._list_invocations,
            "get_invocation": self._get_invocation,
            "list_runners": self._list_runners,
            "get_runner": self._get_runner,
            "create_runner": self._create_runner,
            "update_runner": self._update_runner,
            "delete_runner": self._delete_runner,
            "list_incident_workflows": self._list_incident_workflows,
            "get_incident_workflow": self._get_incident_workflow,
            "create_incident_workflow": self._create_incident_workflow,
            "update_incident_workflow": self._update_incident_workflow,
            "delete_incident_workflow": self._delete_incident_workflow,
            "start_incident_workflow": self._start_incident_workflow,
            "list_incident_workflow_triggers": self._list_incident_workflow_triggers,
            "get_incident_workflow_trigger": self._get_incident_workflow_trigger,
            "create_incident_workflow_trigger": self._create_incident_workflow_trigger,
            "update_incident_workflow_trigger": self._update_incident_workflow_trigger,
            "delete_incident_workflow_trigger": self._delete_incident_workflow_trigger,
            "associate_trigger_service": self._associate_trigger_service,
            "disassociate_trigger_service": self._disassociate_trigger_service,
            "list_business_services": self._list_business_services,
            "get_business_service": self._get_business_service,
            "create_business_service": self._create_business_service,
            "update_business_service": self._update_business_service,
            "delete_business_service": self._delete_business_service,
            "list_business_service_subscribers": self._list_business_service_subscribers,
            "create_business_service_subscribers": self._create_business_service_subscribers,
            "remove_business_service_subscribers": self._remove_business_service_subscribers,
            "list_business_service_impacts": self._list_business_service_impacts,
            "list_business_service_impactors": self._list_business_service_impactors,
            "get_priority_thresholds": self._get_priority_thresholds,
            "set_priority_threshold": self._set_priority_threshold,
            "delete_priority_thresholds": self._delete_priority_thresholds,
            "list_status_dashboards": self._list_status_dashboards,
            "get_status_dashboard": self._get_status_dashboard,
            "get_status_dashboard_by_slug": self._get_status_dashboard_by_slug,
            "get_status_dashboard_service_impacts": self._get_status_dashboard_service_impacts,
            "list_status_pages": self._list_status_pages,
            "list_status_page_posts": self._list_status_page_posts,
            "create_status_page_post": self._create_status_page_post,
            "get_status_page_post": self._get_status_page_post,
            "update_status_page_post": self._update_status_page_post,
            "delete_status_page_post": self._delete_status_page_post,
            "list_status_page_post_updates": self._list_status_page_post_updates,
            "create_status_page_post_update": self._create_status_page_post_update,
            "get_status_page_post_update": self._get_status_page_post_update,
            "update_status_page_post_update": self._update_status_page_post_update,
            "delete_status_page_post_update": self._delete_status_page_post_update,
            "list_status_page_subscriptions": self._list_status_page_subscriptions,
            "create_status_page_subscription": self._create_status_page_subscription,
            "get_status_page_subscription": self._get_status_page_subscription,
            "delete_status_page_subscription": self._delete_status_page_subscription,
            "analytics_incident_metrics": self._analytics_incident_metrics,
            "analytics_incident_metrics_by_dimension": self._analytics_incident_metrics_by_dimension,
            "analytics_raw_incidents": self._analytics_raw_incidents,
            "get_raw_incident": self._get_raw_incident,
            "get_raw_incident_responses": self._get_raw_incident_responses,
            "analytics_responder_metrics": self._analytics_responder_metrics,
            "list_audit_records": self._list_audit_records,
            "send_change_event": self._send_change_event,
            "list_change_events": self._list_change_events,
            "list_service_change_events": self._list_service_change_events,
            "list_custom_fields": self._list_custom_fields,
            "create_custom_field": self._create_custom_field,
            "get_custom_field": self._get_custom_field,
            "update_custom_field": self._update_custom_field,
            "delete_custom_field": self._delete_custom_field,
            "list_field_options": self._list_field_options,
            "create_field_option": self._create_field_option,
            "get_field_option": self._get_field_option,
            "update_field_option": self._update_field_option,
            "delete_field_option": self._delete_field_option,
            "list_templates": self._list_templates,
            "create_template": self._create_template,
            "get_template": self._get_template,
            "update_template": self._update_template,
            "delete_template": self._delete_template,
            "render_template": self._render_template,
            "list_tags": self._list_tags,
            "create_tag": self._create_tag,
            "get_tag": self._get_tag,
            "delete_tag": self._delete_tag,
            "get_tags_for_entity": self._get_tags_for_entity,
            "change_tags": self._change_tags,
            "list_vendors": self._list_vendors,
            "get_vendor": self._get_vendor,
            "list_addons": self._list_addons,
            "create_addon": self._create_addon,
            "get_addon": self._get_addon,
            "update_addon": self._update_addon,
            "delete_addon": self._delete_addon,
            "list_abilities": self._list_abilities,
            "test_ability": self._test_ability,
            "list_notifications": self._list_notifications,
            "list_licenses": self._list_licenses,
            "list_license_allocations": self._list_license_allocations,
            "paused_incident_report_alerts": self._paused_incident_report_alerts,
            "paused_incident_report_counts": self._paused_incident_report_counts,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        try:
            result = await handler(op, api_key, from_email)
        except ValueError as e:
            # Config-coercion / JSON-parse failures surface as the node's
            # structured error dict, consistent with API errors.
            return {
                "status": "error",
                "action": op.operation,
                "error": str(e),
                "status_code": 400,
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Incident handlers
    # ------------------------------------------------------------------
    async def _list_incidents(self, c: PagerDutyListIncidentsConfig, api_key, from_email) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "statuses[]": c.statuses or None,
            "urgencies[]": c.urgencies or None,
            "service_ids[]": _comma_list(c.service_ids),
            "team_ids[]": _comma_list(c.team_ids),
            "since": c.since,
            "until": c.until,
            "limit": c.limit,
        }
        return await _pagerduty_request(
            api_key, "GET", "/incidents", params=params, action_name="list_incidents"
        )

    async def _get_incident(self, c: PagerDutyGetIncidentConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/incidents/{c.incident_id}", action_name="get_incident"
        )

    async def _create_incident(self, c: PagerDutyCreateIncidentConfig, api_key, from_email) -> Dict[str, Any]:
        incident: Dict[str, Any] = {
            "type": "incident",
            "title": c.title,
            "service": _ref(c.service_id, "service_reference"),
        }
        if c.urgency:
            incident["urgency"] = c.urgency
        if c.body_details:
            incident["body"] = {"type": "incident_body", "details": c.body_details}
        if c.escalation_policy_id:
            incident["escalation_policy"] = _ref(c.escalation_policy_id, "escalation_policy_reference")
        if c.priority_id:
            incident["priority"] = _ref(c.priority_id, "priority_reference")
        return await _pagerduty_request(
            api_key, "POST", "/incidents", json_body={"incident": incident},
            from_email=from_email, action_name="create_incident",
        )

    async def _update_incident(self, c: PagerDutyUpdateIncidentConfig, api_key, from_email) -> Dict[str, Any]:
        incident: Dict[str, Any] = {"type": "incident"}
        if c.status:
            incident["status"] = c.status
        if c.urgency:
            incident["urgency"] = c.urgency
        if c.priority_id:
            incident["priority"] = _ref(c.priority_id, "priority_reference")
        if c.escalation_policy_id:
            incident["escalation_policy"] = _ref(c.escalation_policy_id, "escalation_policy_reference")
        if c.resolution:
            incident["resolution"] = c.resolution
        return await _pagerduty_request(
            api_key, "PUT", f"/incidents/{c.incident_id}", json_body={"incident": incident},
            from_email=from_email, action_name="update_incident",
        )

    async def _manage_incidents(self, c: PagerDutyManageIncidentsConfig, api_key, from_email) -> Dict[str, Any]:
        incidents = [
            {"id": iid, "type": "incident_reference", "status": c.status}
            for iid in (_comma_list(c.incident_ids) or [])
        ]
        return await _pagerduty_request(
            api_key, "PUT", "/incidents", json_body={"incidents": incidents},
            from_email=from_email, action_name="manage_incidents",
        )

    async def _snooze_incident(self, c: PagerDutySnoozeIncidentConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "POST", f"/incidents/{c.incident_id}/snooze",
            json_body={"duration": _safe_int(c.duration, "duration")},
            from_email=from_email, action_name="snooze_incident",
        )

    async def _merge_incidents(self, c: PagerDutyMergeIncidentsConfig, api_key, from_email) -> Dict[str, Any]:
        source = [
            {"id": iid, "type": "incident_reference"}
            for iid in (_comma_list(c.source_incident_ids) or [])
        ]
        return await _pagerduty_request(
            api_key, "PUT", f"/incidents/{c.incident_id}/merge",
            json_body={"source_incidents": source},
            from_email=from_email, action_name="merge_incidents",
        )

    async def _list_notes(self, c: PagerDutyListNotesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/incidents/{c.incident_id}/notes", action_name="list_notes"
        )

    async def _create_note(self, c: PagerDutyCreateNoteConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "POST", f"/incidents/{c.incident_id}/notes",
            json_body={"note": {"content": c.content}},
            from_email=from_email, action_name="create_note",
        )

    async def _create_status_update(self, c: PagerDutyCreateStatusUpdateConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "POST", f"/incidents/{c.incident_id}/status_updates",
            json_body={"message": c.message},
            from_email=from_email, action_name="create_status_update",
        )

    async def _list_alerts(self, c: PagerDutyListAlertsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/incidents/{c.incident_id}/alerts", action_name="list_alerts"
        )

    async def _list_log_entries(self, c: PagerDutyListLogEntriesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/incidents/{c.incident_id}/log_entries", action_name="list_log_entries"
        )

    async def _add_responders(self, c: PagerDutyAddRespondersConfig, api_key, from_email) -> Dict[str, Any]:
        targets: List[Dict[str, Any]] = []
        for uid in (_comma_list(c.user_ids) or []):
            targets.append({"responder_request_target": _ref(uid, "user_reference")})
        for eid in (_comma_list(c.escalation_policy_ids) or []):
            targets.append(
                {"responder_request_target": _ref(eid, "escalation_policy_reference")}
            )
        # PagerDuty REQUIRES requester_id (a user id). Use the explicit config
        # value, else resolve the From user's id from their email.
        requester_id = c.requester_id or None
        if not requester_id and from_email:
            lookup = await _pagerduty_request(
                api_key, "GET", "/users", params={"query": from_email, "limit": 1},
                action_name="resolve_requester",
            )
            users = (lookup.get("data") or {}).get("users") or []
            if users:
                requester_id = users[0].get("id")
        body = {"requester_id": requester_id, "message": c.message, "responder_request_targets": targets}
        return await _pagerduty_request(
            api_key, "POST", f"/incidents/{c.incident_id}/responder_requests",
            json_body=body, from_email=from_email, action_name="add_responders",
        )

    # ------------------------------------------------------------------
    # Service handlers
    # ------------------------------------------------------------------
    async def _list_services(self, c: PagerDutyListServicesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", "/services",
            params={"query": c.query, "limit": c.limit}, action_name="list_services",
        )

    async def _get_service(self, c: PagerDutyGetServiceConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/services/{c.service_id}", action_name="get_service"
        )

    async def _create_service(self, c: PagerDutyCreateServiceConfig, api_key, from_email) -> Dict[str, Any]:
        service: Dict[str, Any] = {
            "type": "service",
            "name": c.name,
            "escalation_policy": _ref(c.escalation_policy_id, "escalation_policy_reference"),
        }
        if c.description:
            service["description"] = c.description
        return await _pagerduty_request(
            api_key, "POST", "/services", json_body={"service": service},
            action_name="create_service",
        )

    async def _update_service(self, c: PagerDutyUpdateServiceConfig, api_key, from_email) -> Dict[str, Any]:
        service: Dict[str, Any] = {"type": "service"}
        if c.name:
            service["name"] = c.name
        if c.description:
            service["description"] = c.description
        if c.status:
            service["status"] = c.status
        return await _pagerduty_request(
            api_key, "PUT", f"/services/{c.service_id}", json_body={"service": service},
            action_name="update_service",
        )

    # ------------------------------------------------------------------
    # Schedule / on-call handlers
    # ------------------------------------------------------------------
    async def _list_schedules(self, c: PagerDutyListSchedulesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", "/schedules", params={"query": c.query}, action_name="list_schedules"
        )

    async def _get_schedule(self, c: PagerDutyGetScheduleConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/schedules/{c.schedule_id}",
            params={"since": c.since, "until": c.until}, action_name="get_schedule",
        )

    async def _list_oncalls(self, c: PagerDutyListOnCallsConfig, api_key, from_email) -> Dict[str, Any]:
        params = {
            "schedule_ids[]": _comma_list(c.schedule_ids),
            "user_ids[]": _comma_list(c.user_ids),
            "escalation_policy_ids[]": _comma_list(c.escalation_policy_ids),
            "since": c.since,
            "until": c.until,
        }
        return await _pagerduty_request(
            api_key, "GET", "/oncalls", params=params, action_name="list_oncalls"
        )

    # ------------------------------------------------------------------
    # Escalation policy handlers
    # ------------------------------------------------------------------
    async def _list_escalation_policies(self, c: PagerDutyListEscalationPoliciesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", "/escalation_policies", params={"query": c.query},
            action_name="list_escalation_policies",
        )

    async def _create_escalation_policy(self, c: PagerDutyCreateEscalationPolicyConfig, api_key, from_email) -> Dict[str, Any]:
        policy = {
            "type": "escalation_policy",
            "name": c.name,
            "escalation_rules": [
                {
                    "escalation_delay_in_minutes": _safe_int(c.escalation_delay_in_minutes, "escalation_delay_in_minutes"),
                    "targets": [_ref(c.escalation_target_id, c.escalation_target_type)],
                }
            ],
        }
        return await _pagerduty_request(
            api_key, "POST", "/escalation_policies", json_body={"escalation_policy": policy},
            from_email=from_email, action_name="create_escalation_policy",
        )

    # ------------------------------------------------------------------
    # User / team handlers
    # ------------------------------------------------------------------
    async def _list_users(self, c: PagerDutyListUsersConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", "/users", params={"query": c.query, "limit": c.limit},
            action_name="list_users",
        )

    async def _get_user(self, c: PagerDutyGetUserConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/users/{c.user_id}", action_name="get_user"
        )

    async def _create_user(self, c: PagerDutyCreateUserConfig, api_key, from_email) -> Dict[str, Any]:
        user: Dict[str, Any] = {"type": "user", "name": c.name, "email": c.email}
        if c.role:
            user["role"] = c.role
        return await _pagerduty_request(
            api_key, "POST", "/users", json_body={"user": user},
            from_email=from_email, action_name="create_user",
        )

    async def _get_current_user(self, c: PagerDutyGetCurrentUserConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", "/users/me", action_name="get_current_user"
        )

    async def _list_teams(self, c: PagerDutyListTeamsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", "/teams", params={"query": c.query}, action_name="list_teams"
        )

    # ------------------------------------------------------------------
    # Maintenance window handlers
    # ------------------------------------------------------------------
    async def _list_maintenance_windows(self, c: PagerDutyListMaintenanceWindowsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", "/maintenance_windows", params={"filter": c.filter or None},
            action_name="list_maintenance_windows",
        )

    async def _create_maintenance_window(self, c: PagerDutyCreateMaintenanceWindowConfig, api_key, from_email) -> Dict[str, Any]:
        window: Dict[str, Any] = {
            "type": "maintenance_window",
            "start_time": c.start_time,
            "end_time": c.end_time,
            "services": [_ref(sid, "service_reference") for sid in (_comma_list(c.service_ids) or [])],
        }
        if c.description:
            window["description"] = c.description
        return await _pagerduty_request(
            api_key, "POST", "/maintenance_windows", json_body={"maintenance_window": window},
            from_email=from_email, action_name="create_maintenance_window",
        )

    # ------------------------------------------------------------------
    # Events API v2 handler
    # ------------------------------------------------------------------
    async def _send_event(self, c: PagerDutySendEventConfig, api_key, from_email) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "routing_key": c.routing_key,
            "event_action": c.event_action,
        }
        if c.dedup_key:
            body["dedup_key"] = c.dedup_key
        if c.event_action == "trigger":
            body["payload"] = {
                "summary": c.summary,
                "source": c.source,
                "severity": c.severity,
            }
        return await _pagerduty_request(
            api_key, "POST", _events_enqueue_url(), json_body=body,
            action_name="send_event", use_token_auth=False,
        )

    # ------------------------------------------------------------------
    # Webhook subscription handlers
    # ------------------------------------------------------------------
    async def _list_webhook_subscriptions(self, c: PagerDutyListWebhookSubscriptionsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", "/webhook_subscriptions", action_name="list_webhook_subscriptions"
        )

    async def _create_webhook_subscription(self, c: PagerDutyCreateWebhookSubscriptionConfig, api_key, from_email) -> Dict[str, Any]:
        filter_block: Dict[str, Any] = {"type": "account_reference"}
        if c.service_id:
            filter_block = {"type": "service_reference", "id": c.service_id}
        body = {
            "webhook_subscription": {
                "type": "webhook_subscription",
                "delivery_method": {"type": "http_delivery_method", "url": c.delivery_url},
                "events": _comma_list(c.events) or [],
                "filter": filter_block,
            }
        }
        return await _pagerduty_request(
            api_key, "POST", "/webhook_subscriptions", json_body=body,
            action_name="create_webhook_subscription",
        )

    # ------------------------------------------------------------------
    # Reference handlers
    # ------------------------------------------------------------------
    async def _list_priorities(self, c: PagerDutyListPrioritiesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", "/priorities", action_name="list_priorities"
        )

    # --- incidents-extended ---
    async def _get_alert(self, c: PagerDutyGetAlertConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/incidents/{c.incident_id}/alerts/{c.alert_id}", action_name="get_alert"
        )

    async def _update_alert(self, c: PagerDutyUpdateAlertConfig, api_key, from_email) -> Dict[str, Any]:
        alert: Dict[str, Any] = {"type": "alert"}
        if c.status:
            alert["status"] = c.status
        if c.new_incident_id:
            alert["incident"] = _ref(c.new_incident_id, "incident_reference")
        return await _pagerduty_request(
            api_key, "PUT", f"/incidents/{c.incident_id}/alerts/{c.alert_id}",
            json_body={"alert": alert}, from_email=from_email, action_name="update_alert",
        )

    async def _manage_alerts(self, c: PagerDutyManageAlertsConfig, api_key, from_email) -> Dict[str, Any]:
        incident_ref = _ref(c.new_incident_id, "incident_reference") if c.new_incident_id else None
        alerts: List[Dict[str, Any]] = []
        for aid in (_comma_list(c.alert_ids) or []):
            alert: Dict[str, Any] = {"id": aid, "type": "alert"}
            if c.status:
                alert["status"] = c.status
            if incident_ref:
                alert["incident"] = incident_ref
            alerts.append(alert)
        return await _pagerduty_request(
            api_key, "PUT", f"/incidents/{c.incident_id}/alerts",
            json_body={"alerts": alerts}, from_email=from_email, action_name="manage_alerts",
        )

    async def _get_incident_custom_fields(self, c: PagerDutyGetIncidentCustomFieldsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/incidents/{c.incident_id}/custom_fields/values",
            action_name="get_incident_custom_fields",
        )

    async def _update_incident_custom_fields(self, c: PagerDutyUpdateIncidentCustomFieldsConfig, api_key, from_email) -> Dict[str, Any]:
        try:
            fields = json.loads(c.custom_fields)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Custom Field Values must be a valid JSON array: {e}")
        return await _pagerduty_request(
            api_key, "PUT", f"/incidents/{c.incident_id}/custom_fields/values",
            json_body={"custom_fields": fields}, from_email=from_email,
            action_name="update_incident_custom_fields",
        )

    async def _list_related_change_events(self, c: PagerDutyListRelatedChangeEventsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/incidents/{c.incident_id}/related_change_events",
            action_name="list_related_change_events",
        )

    async def _get_past_incidents(self, c: PagerDutyGetPastIncidentsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/incidents/{c.incident_id}/past_incidents",
            params={"limit": c.limit}, action_name="get_past_incidents",
        )

    async def _get_related_incidents(self, c: PagerDutyGetRelatedIncidentsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/incidents/{c.incident_id}/related_incidents",
            action_name="get_related_incidents",
        )

    async def _get_outlier_incident(self, c: PagerDutyGetOutlierIncidentConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/incidents/{c.incident_id}/outlier_incident",
            action_name="get_outlier_incident",
        )

    async def _list_status_update_subscribers(self, c: PagerDutyListStatusUpdateSubscribersConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/incidents/{c.incident_id}/status_updates/subscribers",
            action_name="list_status_update_subscribers",
        )

    async def _add_status_update_subscribers(self, c: PagerDutyAddStatusUpdateSubscribersConfig, api_key, from_email) -> Dict[str, Any]:
        subscribers = [
            {"subscriber_id": sid, "subscriber_type": c.subscriber_type}
            for sid in (_comma_list(c.subscriber_ids) or [])
        ]
        return await _pagerduty_request(
            api_key, "POST", f"/incidents/{c.incident_id}/status_updates/subscribers",
            json_body={"subscribers": subscribers}, from_email=from_email,
            action_name="add_status_update_subscribers",
        )

    async def _remove_status_update_subscriber(self, c: PagerDutyRemoveStatusUpdateSubscriberConfig, api_key, from_email) -> Dict[str, Any]:
        subscribers = [
            {"subscriber_id": sid, "subscriber_type": c.subscriber_type}
            for sid in (_comma_list(c.subscriber_ids) or [])
        ]
        return await _pagerduty_request(
            api_key, "POST", f"/incidents/{c.incident_id}/status_updates/unsubscribe",
            json_body={"subscribers": subscribers}, from_email=from_email,
            action_name="remove_status_update_subscriber",
        )

    async def _list_global_log_entries(self, c: PagerDutyListGlobalLogEntriesConfig, api_key, from_email) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "since": c.since,
            "until": c.until,
            "team_ids[]": _comma_list(c.team_ids),
            "limit": c.limit,
        }
        return await _pagerduty_request(
            api_key, "GET", "/log_entries", params=params, action_name="list_global_log_entries"
        )

    async def _get_log_entry(self, c: PagerDutyGetLogEntryConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/log_entries/{c.log_entry_id}", action_name="get_log_entry"
        )

    # --- services-full ---
    async def _delete_service(self, c: PagerDutyDeleteServiceConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/services/{c.service_id}", from_email=from_email, action_name="delete_service")

    async def _associate_service_dependencies(self, c: PagerDutyAssociateServiceDependenciesConfig, api_key, from_email) -> Dict[str, Any]:
        try:
            relationships = json.loads(c.relationships)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in Relationships: {e}")
        return await _pagerduty_request(api_key, "POST", "/service_dependencies/associate", json_body={"relationships": relationships}, from_email=from_email, action_name="associate_service_dependencies")

    async def _disassociate_service_dependencies(self, c: PagerDutyDisassociateServiceDependenciesConfig, api_key, from_email) -> Dict[str, Any]:
        try:
            relationships = json.loads(c.relationships)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in Relationships: {e}")
        return await _pagerduty_request(api_key, "POST", "/service_dependencies/disassociate", json_body={"relationships": relationships}, from_email=from_email, action_name="disassociate_service_dependencies")

    async def _get_technical_service_dependencies(self, c: PagerDutyGetTechnicalServiceDependenciesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/service_dependencies/technical_services/{c.service_id}", action_name="get_technical_service_dependencies")

    async def _get_business_service_dependencies(self, c: PagerDutyGetBusinessServiceDependenciesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/service_dependencies/business_services/{c.business_service_id}", action_name="get_business_service_dependencies")

    async def _create_service_integration(self, c: PagerDutyCreateServiceIntegrationConfig, api_key, from_email) -> Dict[str, Any]:
        integration = {"type": c.integration_type}
        if c.name: integration["name"] = c.name
        if c.integration_email: integration["integration_email"] = c.integration_email
        if c.vendor_id: integration["vendor"] = _ref(c.vendor_id, "vendor_reference")
        return await _pagerduty_request(api_key, "POST", f"/services/{c.service_id}/integrations", json_body={"integration": integration}, from_email=from_email, action_name="create_service_integration")

    async def _get_service_integration(self, c: PagerDutyGetServiceIntegrationConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/services/{c.service_id}/integrations/{c.integration_id}", action_name="get_service_integration")

    async def _update_service_integration(self, c: PagerDutyUpdateServiceIntegrationConfig, api_key, from_email) -> Dict[str, Any]:
        integration = {"type": c.integration_type}
        if c.name: integration["name"] = c.name
        if c.integration_email: integration["integration_email"] = c.integration_email
        if c.vendor_id: integration["vendor"] = _ref(c.vendor_id, "vendor_reference")
        return await _pagerduty_request(api_key, "PUT", f"/services/{c.service_id}/integrations/{c.integration_id}", json_body={"integration": integration}, from_email=from_email, action_name="update_service_integration")

    async def _list_service_event_rules(self, c: PagerDutyListServiceEventRulesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/services/{c.service_id}/rules", action_name="list_service_event_rules")

    async def _create_service_event_rule(self, c: PagerDutyCreateServiceEventRuleConfig, api_key, from_email) -> Dict[str, Any]:
        rule: Dict[str, Any] = {}
        if c.conditions:
            try:
                rule["conditions"] = json.loads(c.conditions)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in Conditions: {e}")
        if c.actions:
            try:
                rule["actions"] = json.loads(c.actions)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in Actions: {e}")
        if c.position not in (None, ""):
            rule["position"] = _safe_int(c.position, "position")
        if c.disabled:
            rule["disabled"] = c.disabled == "true"
        return await _pagerduty_request(api_key, "POST", f"/services/{c.service_id}/rules", json_body={"rule": rule}, from_email=from_email, action_name="create_service_event_rule")

    async def _get_service_event_rule(self, c: PagerDutyGetServiceEventRuleConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/services/{c.service_id}/rules/{c.rule_id}", action_name="get_service_event_rule")

    async def _update_service_event_rule(self, c: PagerDutyUpdateServiceEventRuleConfig, api_key, from_email) -> Dict[str, Any]:
        rule: Dict[str, Any] = {}
        if c.conditions:
            try:
                rule["conditions"] = json.loads(c.conditions)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in Conditions: {e}")
        if c.actions:
            try:
                rule["actions"] = json.loads(c.actions)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in Actions: {e}")
        if c.position not in (None, ""):
            rule["position"] = _safe_int(c.position, "position")
        if c.disabled:
            rule["disabled"] = c.disabled == "true"
        return await _pagerduty_request(api_key, "PUT", f"/services/{c.service_id}/rules/{c.rule_id}", json_body={"rule": rule}, from_email=from_email, action_name="update_service_event_rule")

    async def _delete_service_event_rule(self, c: PagerDutyDeleteServiceEventRuleConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/services/{c.service_id}/rules/{c.rule_id}", from_email=from_email, action_name="delete_service_event_rule")

    # --- schedules-full ---
    async def _create_schedule(self, c: PagerDutyCreateScheduleConfig, api_key, from_email) -> Dict[str, Any]:
        try:
            schedule = json.loads(c.schedule)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid JSON in Schedule Definition: {e}")
        return await _pagerduty_request(api_key, "POST", "/schedules", json_body={"schedule": schedule}, from_email=from_email, action_name="create_schedule")

    async def _update_schedule(self, c: PagerDutyUpdateScheduleConfig, api_key, from_email) -> Dict[str, Any]:
        try:
            schedule = json.loads(c.schedule)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid JSON in Schedule Definition: {e}")
        return await _pagerduty_request(api_key, "PUT", f"/schedules/{c.schedule_id}", json_body={"schedule": schedule}, from_email=from_email, action_name="update_schedule")

    async def _delete_schedule(self, c: PagerDutyDeleteScheduleConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/schedules/{c.schedule_id}", from_email=from_email, action_name="delete_schedule")

    async def _preview_schedule(self, c: PagerDutyPreviewScheduleConfig, api_key, from_email) -> Dict[str, Any]:
        try:
            schedule = json.loads(c.schedule)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid JSON in Schedule Definition: {e}")
        params = {"since": c.since, "until": c.until}
        if c.overflow == "true":
            params["overflow"] = "true"
        return await _pagerduty_request(api_key, "POST", "/schedules/preview", params=params, json_body={"schedule": schedule}, action_name="preview_schedule")

    async def _list_users_on_schedule(self, c: PagerDutyListUsersOnScheduleConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/schedules/{c.schedule_id}/users", params={"since": c.since, "until": c.until}, action_name="list_users_on_schedule")

    async def _list_overrides(self, c: PagerDutyListOverridesConfig, api_key, from_email) -> Dict[str, Any]:
        params = {"since": c.since, "until": c.until}
        if c.editable == "true":
            params["editable"] = "true"
        return await _pagerduty_request(api_key, "GET", f"/schedules/{c.schedule_id}/overrides", params=params, action_name="list_overrides")

    async def _create_override(self, c: PagerDutyCreateOverrideConfig, api_key, from_email) -> Dict[str, Any]:
        override = {"start": c.start, "end": c.end, "user": _ref(c.user_id, "user_reference")}
        return await _pagerduty_request(api_key, "POST", f"/schedules/{c.schedule_id}/overrides", json_body={"overrides": [override]}, from_email=from_email, action_name="create_override")

    async def _delete_override(self, c: PagerDutyDeleteOverrideConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/schedules/{c.schedule_id}/overrides/{c.override_id}", from_email=from_email, action_name="delete_override")

    async def _get_escalation_policy(self, c: PagerDutyGetEscalationPolicyConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/escalation_policies/{c.escalation_policy_id}", action_name="get_escalation_policy")

    async def _update_escalation_policy(self, c: PagerDutyUpdateEscalationPolicyConfig, api_key, from_email) -> Dict[str, Any]:
        policy: Dict[str, Any] = {"type": "escalation_policy"}
        if c.name:
            policy["name"] = c.name
        if c.description:
            policy["description"] = c.description
        if c.escalation_rules:
            try:
                policy["escalation_rules"] = json.loads(c.escalation_rules)
            except (ValueError, TypeError) as e:
                raise ValueError(f"Invalid JSON in Escalation Rules: {e}")
        return await _pagerduty_request(api_key, "PUT", f"/escalation_policies/{c.escalation_policy_id}", json_body={"escalation_policy": policy}, from_email=from_email, action_name="update_escalation_policy")

    async def _delete_escalation_policy(self, c: PagerDutyDeleteEscalationPolicyConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/escalation_policies/{c.escalation_policy_id}", from_email=from_email, action_name="delete_escalation_policy")

    # --- users-teams-full ---
    async def _update_user(self, c: PagerDutyUpdateUserConfig, api_key, from_email) -> Dict[str, Any]:
        user = {"type": "user"}
        if c.name:
            user["name"] = c.name
        if c.email:
            user["email"] = c.email
        if c.role:
            user["role"] = c.role
        if c.time_zone:
            user["time_zone"] = c.time_zone
        if c.description:
            user["description"] = c.description
        return await _pagerduty_request(api_key, "PUT", f"/users/{c.user_id}", json_body={"user": user}, from_email=from_email, action_name="update_user")

    async def _delete_user(self, c: PagerDutyDeleteUserConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/users/{c.user_id}", from_email=from_email, action_name="delete_user")

    async def _list_contact_methods(self, c: PagerDutyListContactMethodsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/users/{c.user_id}/contact_methods", action_name="list_contact_methods")

    async def _create_contact_method(self, c: PagerDutyCreateContactMethodConfig, api_key, from_email) -> Dict[str, Any]:
        cm = {"type": c.type, "label": c.label, "address": c.address}
        if c.country_code:
            cm["country_code"] = _safe_int(c.country_code, "country_code")
        return await _pagerduty_request(api_key, "POST", f"/users/{c.user_id}/contact_methods", json_body={"contact_method": cm}, from_email=from_email, action_name="create_contact_method")

    async def _get_contact_method(self, c: PagerDutyGetContactMethodConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/users/{c.user_id}/contact_methods/{c.contact_method_id}", action_name="get_contact_method")

    async def _update_contact_method(self, c: PagerDutyUpdateContactMethodConfig, api_key, from_email) -> Dict[str, Any]:
        cm = {"type": c.type}
        if c.label:
            cm["label"] = c.label
        if c.address:
            cm["address"] = c.address
        if c.country_code:
            cm["country_code"] = _safe_int(c.country_code, "country_code")
        return await _pagerduty_request(api_key, "PUT", f"/users/{c.user_id}/contact_methods/{c.contact_method_id}", json_body={"contact_method": cm}, from_email=from_email, action_name="update_contact_method")

    async def _delete_contact_method(self, c: PagerDutyDeleteContactMethodConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/users/{c.user_id}/contact_methods/{c.contact_method_id}", from_email=from_email, action_name="delete_contact_method")

    async def _list_notification_rules(self, c: PagerDutyListNotificationRulesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/users/{c.user_id}/notification_rules", action_name="list_notification_rules")

    async def _create_notification_rule(self, c: PagerDutyCreateNotificationRuleConfig, api_key, from_email) -> Dict[str, Any]:
        rule = {
            "type": "assignment_notification_rule",
            "start_delay_in_minutes": _safe_int(c.start_delay_in_minutes, "start_delay_in_minutes"),
            "urgency": c.urgency,
            "contact_method": _ref(c.contact_method_id, c.contact_method_type),
        }
        return await _pagerduty_request(api_key, "POST", f"/users/{c.user_id}/notification_rules", json_body={"notification_rule": rule}, from_email=from_email, action_name="create_notification_rule")

    async def _get_notification_rule(self, c: PagerDutyGetNotificationRuleConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/users/{c.user_id}/notification_rules/{c.notification_rule_id}", action_name="get_notification_rule")

    async def _update_notification_rule(self, c: PagerDutyUpdateNotificationRuleConfig, api_key, from_email) -> Dict[str, Any]:
        rule = {"type": "assignment_notification_rule"}
        if c.start_delay_in_minutes:
            rule["start_delay_in_minutes"] = _safe_int(c.start_delay_in_minutes, "start_delay_in_minutes")
        if c.urgency:
            rule["urgency"] = c.urgency
        if c.contact_method_id:
            rule["contact_method"] = _ref(c.contact_method_id, c.contact_method_type)
        return await _pagerduty_request(api_key, "PUT", f"/users/{c.user_id}/notification_rules/{c.notification_rule_id}", json_body={"notification_rule": rule}, from_email=from_email, action_name="update_notification_rule")

    async def _delete_notification_rule(self, c: PagerDutyDeleteNotificationRuleConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/users/{c.user_id}/notification_rules/{c.notification_rule_id}", from_email=from_email, action_name="delete_notification_rule")

    async def _get_team(self, c: PagerDutyGetTeamConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/teams/{c.team_id}", action_name="get_team")

    async def _create_team(self, c: PagerDutyCreateTeamConfig, api_key, from_email) -> Dict[str, Any]:
        team = {"type": "team", "name": c.name}
        if c.description:
            team["description"] = c.description
        return await _pagerduty_request(api_key, "POST", "/teams", json_body={"team": team}, from_email=from_email, action_name="create_team")

    async def _update_team(self, c: PagerDutyUpdateTeamConfig, api_key, from_email) -> Dict[str, Any]:
        team = {"type": "team"}
        if c.name:
            team["name"] = c.name
        if c.description:
            team["description"] = c.description
        return await _pagerduty_request(api_key, "PUT", f"/teams/{c.team_id}", json_body={"team": team}, from_email=from_email, action_name="update_team")

    async def _delete_team(self, c: PagerDutyDeleteTeamConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/teams/{c.team_id}", from_email=from_email, action_name="delete_team")

    async def _list_team_members(self, c: PagerDutyListTeamMembersConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/teams/{c.team_id}/members", action_name="list_team_members")

    async def _add_team_member(self, c: PagerDutyAddTeamMemberConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "PUT", f"/teams/{c.team_id}/users/{c.user_id}", json_body={"role": c.role}, from_email=from_email, action_name="add_team_member")

    async def _remove_team_member(self, c: PagerDutyRemoveTeamMemberConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/teams/{c.team_id}/users/{c.user_id}", from_email=from_email, action_name="remove_team_member")

    async def _associate_team_escalation_policy(self, c: PagerDutyAssociateTeamEscalationPolicyConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "PUT", f"/teams/{c.team_id}/escalation_policies/{c.escalation_policy_id}", from_email=from_email, action_name="associate_team_escalation_policy")

    async def _remove_team_escalation_policy(self, c: PagerDutyRemoveTeamEscalationPolicyConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/teams/{c.team_id}/escalation_policies/{c.escalation_policy_id}", from_email=from_email, action_name="remove_team_escalation_policy")

    # --- maintenance-webhooks-full ---
    async def _get_maintenance_window(self, c: PagerDutyGetMaintenanceWindowConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/maintenance_windows/{c.maintenance_window_id}",
            action_name="get_maintenance_window",
        )

    async def _update_maintenance_window(self, c: PagerDutyUpdateMaintenanceWindowConfig, api_key, from_email) -> Dict[str, Any]:
        window: Dict[str, Any] = {"type": "maintenance_window"}
        if c.start_time:
            window["start_time"] = c.start_time
        if c.end_time:
            window["end_time"] = c.end_time
        if c.description:
            window["description"] = c.description
        services = _comma_list(c.service_ids)
        if services:
            window["services"] = [_ref(sid, "service_reference") for sid in services]
        return await _pagerduty_request(
            api_key, "PUT", f"/maintenance_windows/{c.maintenance_window_id}",
            json_body={"maintenance_window": window}, from_email=from_email,
            action_name="update_maintenance_window",
        )

    async def _delete_maintenance_window(self, c: PagerDutyDeleteMaintenanceWindowConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "DELETE", f"/maintenance_windows/{c.maintenance_window_id}",
            from_email=from_email, action_name="delete_maintenance_window",
        )

    async def _get_webhook_subscription(self, c: PagerDutyGetWebhookSubscriptionConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/webhook_subscriptions/{c.webhook_subscription_id}",
            action_name="get_webhook_subscription",
        )

    async def _update_webhook_subscription(self, c: PagerDutyUpdateWebhookSubscriptionConfig, api_key, from_email) -> Dict[str, Any]:
        sub: Dict[str, Any] = {"type": "webhook_subscription"}
        if c.description:
            sub["description"] = c.description
        events = _comma_list(c.events)
        if events:
            sub["events"] = events
        if c.delivery_url:
            sub["delivery_method"] = {"type": "http_delivery_method", "url": c.delivery_url}
        return await _pagerduty_request(
            api_key, "PUT", f"/webhook_subscriptions/{c.webhook_subscription_id}",
            json_body={"webhook_subscription": sub}, from_email=from_email,
            action_name="update_webhook_subscription",
        )

    async def _delete_webhook_subscription(self, c: PagerDutyDeleteWebhookSubscriptionConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "DELETE", f"/webhook_subscriptions/{c.webhook_subscription_id}",
            from_email=from_email, action_name="delete_webhook_subscription",
        )

    async def _enable_webhook_subscription(self, c: PagerDutyEnableWebhookSubscriptionConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "POST", f"/webhook_subscriptions/{c.webhook_subscription_id}/enable",
            from_email=from_email, action_name="enable_webhook_subscription",
        )

    async def _disable_webhook_subscription(self, c: PagerDutyDisableWebhookSubscriptionConfig, api_key, from_email) -> Dict[str, Any]:
        # PagerDuty has no /disable endpoint (404); disable via PUT active=false.
        return await _pagerduty_request(
            api_key, "PUT", f"/webhook_subscriptions/{c.webhook_subscription_id}",
            json_body={"webhook_subscription": {"type": "webhook_subscription", "active": False}},
            from_email=from_email, action_name="disable_webhook_subscription",
        )

    async def _ping_webhook_subscription(self, c: PagerDutyPingWebhookSubscriptionConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "POST", f"/webhook_subscriptions/{c.webhook_subscription_id}/ping",
            from_email=from_email, action_name="ping_webhook_subscription",
        )

    async def _list_extensions(self, c: PagerDutyListExtensionsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", "/extensions", params={"query": c.query, "limit": c.limit},
            action_name="list_extensions",
        )

    async def _create_extension(self, c: PagerDutyCreateExtensionConfig, api_key, from_email) -> Dict[str, Any]:
        extension: Dict[str, Any] = {
            "type": "extension",
            "name": c.name,
            "extension_schema": _ref(c.extension_schema_id, "extension_schema_reference"),
            "extension_objects": [
                _ref(sid, "service_reference") for sid in (_comma_list(c.service_ids) or [])
            ],
        }
        if c.endpoint_url:
            extension["endpoint_url"] = c.endpoint_url
        return await _pagerduty_request(
            api_key, "POST", "/extensions", json_body={"extension": extension},
            from_email=from_email, action_name="create_extension",
        )

    async def _get_extension(self, c: PagerDutyGetExtensionConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/extensions/{c.extension_id}", action_name="get_extension"
        )

    async def _update_extension(self, c: PagerDutyUpdateExtensionConfig, api_key, from_email) -> Dict[str, Any]:
        extension: Dict[str, Any] = {"type": "extension"}
        if c.name:
            extension["name"] = c.name
        if c.endpoint_url:
            extension["endpoint_url"] = c.endpoint_url
        if c.extension_schema_id:
            extension["extension_schema"] = _ref(c.extension_schema_id, "extension_schema_reference")
        services = _comma_list(c.service_ids)
        if services:
            extension["extension_objects"] = [_ref(sid, "service_reference") for sid in services]
        return await _pagerduty_request(
            api_key, "PUT", f"/extensions/{c.extension_id}", json_body={"extension": extension},
            from_email=from_email, action_name="update_extension",
        )

    async def _delete_extension(self, c: PagerDutyDeleteExtensionConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "DELETE", f"/extensions/{c.extension_id}",
            from_email=from_email, action_name="delete_extension",
        )

    async def _enable_extension(self, c: PagerDutyEnableExtensionConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "POST", f"/extensions/{c.extension_id}/enable",
            from_email=from_email, action_name="enable_extension",
        )

    async def _list_extension_schemas(self, c: PagerDutyListExtensionSchemasConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", "/extension_schemas", params={"limit": c.limit},
            action_name="list_extension_schemas",
        )

    async def _get_extension_schema(self, c: PagerDutyGetExtensionSchemaConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/extension_schemas/{c.extension_schema_id}",
            action_name="get_extension_schema",
        )

    # --- event-orchestrations ---
    async def _list_event_orchestrations(self, c: PagerDutyListEventOrchestrationsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", "/event_orchestrations", params={"limit": c.limit},
            action_name="list_event_orchestrations",
        )

    async def _get_event_orchestration(self, c: PagerDutyGetEventOrchestrationConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/event_orchestrations/{c.orchestration_id}",
            action_name="get_event_orchestration",
        )

    async def _create_event_orchestration(self, c: PagerDutyCreateEventOrchestrationConfig, api_key, from_email) -> Dict[str, Any]:
        orchestration: Dict[str, Any] = {"name": c.name}
        if c.description:
            orchestration["description"] = c.description
        if c.team_id:
            orchestration["team"] = _ref(c.team_id, "team_reference")
        return await _pagerduty_request(
            api_key, "POST", "/event_orchestrations",
            json_body={"orchestration": orchestration},
            from_email=from_email, action_name="create_event_orchestration",
        )

    async def _update_event_orchestration(self, c: PagerDutyUpdateEventOrchestrationConfig, api_key, from_email) -> Dict[str, Any]:
        orchestration: Dict[str, Any] = {}
        if c.name:
            orchestration["name"] = c.name
        if c.description:
            orchestration["description"] = c.description
        return await _pagerduty_request(
            api_key, "PUT", f"/event_orchestrations/{c.orchestration_id}",
            json_body={"orchestration": orchestration},
            from_email=from_email, action_name="update_event_orchestration",
        )

    async def _delete_event_orchestration(self, c: PagerDutyDeleteEventOrchestrationConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "DELETE", f"/event_orchestrations/{c.orchestration_id}",
            from_email=from_email, action_name="delete_event_orchestration",
        )

    async def _get_orchestration_router(self, c: PagerDutyGetOrchestrationRouterConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/event_orchestrations/{c.orchestration_id}/router",
            action_name="get_orchestration_router",
        )

    async def _update_orchestration_router(self, c: PagerDutyUpdateOrchestrationRouterConfig, api_key, from_email) -> Dict[str, Any]:
        try:
            path = json.loads(c.orchestration_path)
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"orchestration_path must be valid JSON: {e}")
        return await _pagerduty_request(
            api_key, "PUT", f"/event_orchestrations/{c.orchestration_id}/router",
            json_body={"orchestration_path": path},
            from_email=from_email, action_name="update_orchestration_router",
        )

    async def _get_orchestration_global(self, c: PagerDutyGetOrchestrationGlobalConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/event_orchestrations/{c.orchestration_id}/global",
            action_name="get_orchestration_global",
        )

    async def _update_orchestration_global(self, c: PagerDutyUpdateOrchestrationGlobalConfig, api_key, from_email) -> Dict[str, Any]:
        try:
            path = json.loads(c.orchestration_path)
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"orchestration_path must be valid JSON: {e}")
        return await _pagerduty_request(
            api_key, "PUT", f"/event_orchestrations/{c.orchestration_id}/global",
            json_body={"orchestration_path": path},
            from_email=from_email, action_name="update_orchestration_global",
        )

    async def _get_service_orchestration(self, c: PagerDutyGetServiceOrchestrationConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/event_orchestrations/services/{c.service_id}",
            action_name="get_service_orchestration",
        )

    async def _update_service_orchestration(self, c: PagerDutyUpdateServiceOrchestrationConfig, api_key, from_email) -> Dict[str, Any]:
        try:
            path = json.loads(c.orchestration_path)
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"orchestration_path must be valid JSON: {e}")
        return await _pagerduty_request(
            api_key, "PUT", f"/event_orchestrations/services/{c.service_id}",
            json_body={"orchestration_path": path},
            from_email=from_email, action_name="update_service_orchestration",
        )

    async def _get_service_orchestration_active(self, c: PagerDutyGetServiceOrchestrationActiveConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/event_orchestrations/services/{c.service_id}/active",
            action_name="get_service_orchestration_active",
        )

    async def _set_service_orchestration_active(self, c: PagerDutySetServiceOrchestrationActiveConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "PUT", f"/event_orchestrations/services/{c.service_id}/active",
            json_body={"active": c.active == "true"},
            from_email=from_email, action_name="set_service_orchestration_active",
        )

    async def _list_orchestration_integrations(self, c: PagerDutyListOrchestrationIntegrationsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/event_orchestrations/{c.orchestration_id}/integrations",
            action_name="list_orchestration_integrations",
        )

    async def _create_orchestration_integration(self, c: PagerDutyCreateOrchestrationIntegrationConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "POST", f"/event_orchestrations/{c.orchestration_id}/integrations",
            json_body={"integration": {"label": c.label}},
            from_email=from_email, action_name="create_orchestration_integration",
        )

    async def _get_orchestration_integration(self, c: PagerDutyGetOrchestrationIntegrationConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/event_orchestrations/{c.orchestration_id}/integrations/{c.integration_id}",
            action_name="get_orchestration_integration",
        )

    async def _update_orchestration_integration(self, c: PagerDutyUpdateOrchestrationIntegrationConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "PUT", f"/event_orchestrations/{c.orchestration_id}/integrations/{c.integration_id}",
            json_body={"integration": {"label": c.label}},
            from_email=from_email, action_name="update_orchestration_integration",
        )

    async def _delete_orchestration_integration(self, c: PagerDutyDeleteOrchestrationIntegrationConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "DELETE", f"/event_orchestrations/{c.orchestration_id}/integrations/{c.integration_id}",
            from_email=from_email, action_name="delete_orchestration_integration",
        )

    async def _list_rulesets(self, c: PagerDutyListRulesetsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", "/rulesets", params={"limit": c.limit},
            action_name="list_rulesets",
        )

    async def _create_ruleset(self, c: PagerDutyCreateRulesetConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "POST", "/rulesets",
            json_body={"ruleset": {"name": c.name}},
            from_email=from_email, action_name="create_ruleset",
        )

    async def _get_ruleset(self, c: PagerDutyGetRulesetConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/rulesets/{c.ruleset_id}", action_name="get_ruleset"
        )

    async def _update_ruleset(self, c: PagerDutyUpdateRulesetConfig, api_key, from_email) -> Dict[str, Any]:
        ruleset: Dict[str, Any] = {}
        if c.name:
            ruleset["name"] = c.name
        return await _pagerduty_request(
            api_key, "PUT", f"/rulesets/{c.ruleset_id}",
            json_body={"ruleset": ruleset},
            from_email=from_email, action_name="update_ruleset",
        )

    async def _delete_ruleset(self, c: PagerDutyDeleteRulesetConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "DELETE", f"/rulesets/{c.ruleset_id}",
            from_email=from_email, action_name="delete_ruleset",
        )

    async def _list_ruleset_rules(self, c: PagerDutyListRulesetRulesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/rulesets/{c.ruleset_id}/rules",
            action_name="list_ruleset_rules",
        )

    async def _create_ruleset_rule(self, c: PagerDutyCreateRulesetRuleConfig, api_key, from_email) -> Dict[str, Any]:
        try:
            rule = json.loads(c.rule)
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"rule must be valid JSON: {e}")
        return await _pagerduty_request(
            api_key, "POST", f"/rulesets/{c.ruleset_id}/rules",
            json_body={"rule": rule},
            from_email=from_email, action_name="create_ruleset_rule",
        )

    async def _get_ruleset_rule(self, c: PagerDutyGetRulesetRuleConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/rulesets/{c.ruleset_id}/rules/{c.rule_id}",
            action_name="get_ruleset_rule",
        )

    async def _update_ruleset_rule(self, c: PagerDutyUpdateRulesetRuleConfig, api_key, from_email) -> Dict[str, Any]:
        try:
            rule = json.loads(c.rule)
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"rule must be valid JSON: {e}")
        return await _pagerduty_request(
            api_key, "PUT", f"/rulesets/{c.ruleset_id}/rules/{c.rule_id}",
            json_body={"rule": rule},
            from_email=from_email, action_name="update_ruleset_rule",
        )

    async def _delete_ruleset_rule(self, c: PagerDutyDeleteRulesetRuleConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "DELETE", f"/rulesets/{c.ruleset_id}/rules/{c.rule_id}",
            from_email=from_email, action_name="delete_ruleset_rule",
        )

    # --- response-automation-workflows ---
    async def _list_response_plays(self, c: PagerDutyListResponsePlaysConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/response_plays", params={"query": c.query}, action_name="list_response_plays")

    async def _get_response_play(self, c: PagerDutyGetResponsePlayConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/response_plays/{c.response_play_id}", action_name="get_response_play")

    async def _create_response_play(self, c: PagerDutyCreateResponsePlayConfig, api_key, from_email) -> Dict[str, Any]:
        response_play = {"type": "response_play", "name": c.name}
        if c.description:
            response_play["description"] = c.description
        if c.additional_fields_json:
            try:
                extra = json.loads(c.additional_fields_json)
            except (ValueError, TypeError) as e:
                raise ValueError(f"additional_fields_json must be valid JSON: {e}")
            if not isinstance(extra, dict):
                raise ValueError("additional_fields_json must be a JSON object")
            response_play.update(extra)
        return await _pagerduty_request(api_key, "POST", "/response_plays", json_body={"response_play": response_play}, from_email=from_email, action_name="create_response_play")

    async def _update_response_play(self, c: PagerDutyUpdateResponsePlayConfig, api_key, from_email) -> Dict[str, Any]:
        response_play = {"type": "response_play"}
        if c.name:
            response_play["name"] = c.name
        if c.description:
            response_play["description"] = c.description
        if c.additional_fields_json:
            try:
                extra = json.loads(c.additional_fields_json)
            except (ValueError, TypeError) as e:
                raise ValueError(f"additional_fields_json must be valid JSON: {e}")
            if not isinstance(extra, dict):
                raise ValueError("additional_fields_json must be a JSON object")
            response_play.update(extra)
        return await _pagerduty_request(api_key, "PUT", f"/response_plays/{c.response_play_id}", json_body={"response_play": response_play}, from_email=from_email, action_name="update_response_play")

    async def _delete_response_play(self, c: PagerDutyDeleteResponsePlayConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/response_plays/{c.response_play_id}", from_email=from_email, action_name="delete_response_play")

    async def _run_response_play(self, c: PagerDutyRunResponsePlayConfig, api_key, from_email) -> Dict[str, Any]:
        body = {"incident": _ref(c.incident_id, "incident_reference")}
        return await _pagerduty_request(api_key, "POST", f"/response_plays/{c.response_play_id}/run", json_body=body, from_email=from_email, action_name="run_response_play")

    async def _list_automation_actions(self, c: PagerDutyListAutomationActionsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/automation_actions/actions", params={"query": c.query, "limit": c.limit}, action_name="list_automation_actions")

    async def _get_automation_action(self, c: PagerDutyGetAutomationActionConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/automation_actions/actions/{c.action_id}", action_name="get_automation_action")

    async def _create_automation_action(self, c: PagerDutyCreateAutomationActionConfig, api_key, from_email) -> Dict[str, Any]:
        action = {"name": c.name, "action_type": c.action_type, "runner": c.runner_id}
        if c.description:
            action["description"] = c.description
        if c.action_data_json:
            try:
                action["action_data_reference"] = json.loads(c.action_data_json)
            except (ValueError, TypeError) as e:
                raise ValueError(f"action_data_json must be valid JSON: {e}")
        if c.only_invocable_on_unresolved_incidents:
            action["only_invocable_on_unresolved_incidents"] = c.only_invocable_on_unresolved_incidents == "true"
        return await _pagerduty_request(api_key, "POST", "/automation_actions/actions", json_body={"action": action}, from_email=from_email, action_name="create_automation_action")

    async def _update_automation_action(self, c: PagerDutyUpdateAutomationActionConfig, api_key, from_email) -> Dict[str, Any]:
        action = {}
        if c.name:
            action["name"] = c.name
        if c.description:
            action["description"] = c.description
        if c.additional_fields_json:
            try:
                extra = json.loads(c.additional_fields_json)
            except (ValueError, TypeError) as e:
                raise ValueError(f"additional_fields_json must be valid JSON: {e}")
            if not isinstance(extra, dict):
                raise ValueError("additional_fields_json must be a JSON object")
            action.update(extra)
        return await _pagerduty_request(api_key, "PUT", f"/automation_actions/actions/{c.action_id}", json_body={"action": action}, from_email=from_email, action_name="update_automation_action")

    async def _delete_automation_action(self, c: PagerDutyDeleteAutomationActionConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/automation_actions/actions/{c.action_id}", from_email=from_email, action_name="delete_automation_action")

    async def _invoke_automation_action(self, c: PagerDutyInvokeAutomationActionConfig, api_key, from_email) -> Dict[str, Any]:
        invocation = {}
        if c.incident_id:
            invocation["incident"] = _ref(c.incident_id, "incident_reference")
        if c.inputs_json:
            try:
                invocation["inputs"] = json.loads(c.inputs_json)
            except (ValueError, TypeError) as e:
                raise ValueError(f"inputs_json must be valid JSON: {e}")
        return await _pagerduty_request(api_key, "POST", f"/automation_actions/actions/{c.action_id}/invocations", json_body={"invocation": invocation}, from_email=from_email, action_name="invoke_automation_action")

    async def _list_invocations(self, c: PagerDutyListInvocationsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/automation_actions/invocations", params={"action_id": c.action_id}, action_name="list_invocations")

    async def _get_invocation(self, c: PagerDutyGetInvocationConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/automation_actions/invocations/{c.invocation_id}", action_name="get_invocation")

    async def _list_runners(self, c: PagerDutyListRunnersConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/automation_actions/runners", params={"query": c.query}, action_name="list_runners")

    async def _get_runner(self, c: PagerDutyGetRunnerConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/automation_actions/runners/{c.runner_id}", action_name="get_runner")

    async def _create_runner(self, c: PagerDutyCreateRunnerConfig, api_key, from_email) -> Dict[str, Any]:
        runner = {"name": c.name, "runner_type": c.runner_type}
        if c.description:
            runner["description"] = c.description
        if c.runbook_base_uri:
            runner["runbook_base_uri"] = c.runbook_base_uri
        if c.runbook_api_key:
            runner["runbook_api_key"] = c.runbook_api_key
        return await _pagerduty_request(api_key, "POST", "/automation_actions/runners", json_body={"runner": runner}, from_email=from_email, action_name="create_runner")

    async def _update_runner(self, c: PagerDutyUpdateRunnerConfig, api_key, from_email) -> Dict[str, Any]:
        runner = {}
        if c.name:
            runner["name"] = c.name
        if c.description:
            runner["description"] = c.description
        if c.additional_fields_json:
            try:
                extra = json.loads(c.additional_fields_json)
            except (ValueError, TypeError) as e:
                raise ValueError(f"additional_fields_json must be valid JSON: {e}")
            if not isinstance(extra, dict):
                raise ValueError("additional_fields_json must be a JSON object")
            runner.update(extra)
        return await _pagerduty_request(api_key, "PUT", f"/automation_actions/runners/{c.runner_id}", json_body={"runner": runner}, from_email=from_email, action_name="update_runner")

    async def _delete_runner(self, c: PagerDutyDeleteRunnerConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/automation_actions/runners/{c.runner_id}", from_email=from_email, action_name="delete_runner")

    async def _list_incident_workflows(self, c: PagerDutyListIncidentWorkflowsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/incident_workflows", params={"query": c.query}, action_name="list_incident_workflows")

    async def _get_incident_workflow(self, c: PagerDutyGetIncidentWorkflowConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/incident_workflows/{c.incident_workflow_id}", action_name="get_incident_workflow")

    async def _create_incident_workflow(self, c: PagerDutyCreateIncidentWorkflowConfig, api_key, from_email) -> Dict[str, Any]:
        workflow = {"type": "incident_workflow", "name": c.name}
        if c.description:
            workflow["description"] = c.description
        if c.steps_json:
            try:
                workflow["steps"] = json.loads(c.steps_json)
            except (ValueError, TypeError) as e:
                raise ValueError(f"steps_json must be valid JSON: {e}")
        return await _pagerduty_request(api_key, "POST", "/incident_workflows", json_body={"incident_workflow": workflow}, from_email=from_email, action_name="create_incident_workflow")

    async def _update_incident_workflow(self, c: PagerDutyUpdateIncidentWorkflowConfig, api_key, from_email) -> Dict[str, Any]:
        workflow = {"type": "incident_workflow"}
        if c.name:
            workflow["name"] = c.name
        if c.description:
            workflow["description"] = c.description
        if c.steps_json:
            try:
                workflow["steps"] = json.loads(c.steps_json)
            except (ValueError, TypeError) as e:
                raise ValueError(f"steps_json must be valid JSON: {e}")
        return await _pagerduty_request(api_key, "PUT", f"/incident_workflows/{c.incident_workflow_id}", json_body={"incident_workflow": workflow}, from_email=from_email, action_name="update_incident_workflow")

    async def _delete_incident_workflow(self, c: PagerDutyDeleteIncidentWorkflowConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/incident_workflows/{c.incident_workflow_id}", from_email=from_email, action_name="delete_incident_workflow")

    async def _start_incident_workflow(self, c: PagerDutyStartIncidentWorkflowConfig, api_key, from_email) -> Dict[str, Any]:
        body = {"incident_workflow_instance": {"incident": _ref(c.incident_id, "incident_reference")}}
        return await _pagerduty_request(api_key, "POST", f"/incident_workflows/{c.incident_workflow_id}/instances", json_body=body, from_email=from_email, action_name="start_incident_workflow")

    async def _list_incident_workflow_triggers(self, c: PagerDutyListIncidentWorkflowTriggersConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/incident_workflows/triggers", params={"workflow_name_contains": c.workflow_name_contains}, action_name="list_incident_workflow_triggers")

    async def _get_incident_workflow_trigger(self, c: PagerDutyGetIncidentWorkflowTriggerConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/incident_workflows/triggers/{c.trigger_id}", action_name="get_incident_workflow_trigger")

    async def _create_incident_workflow_trigger(self, c: PagerDutyCreateIncidentWorkflowTriggerConfig, api_key, from_email) -> Dict[str, Any]:
        trigger = {"trigger_type": c.trigger_type, "workflow": _ref(c.incident_workflow_id, "workflow_reference")}
        if c.condition:
            trigger["condition"] = c.condition
        if c.subscribed_to_all_services:
            trigger["subscribed_to_all_services"] = c.subscribed_to_all_services == "true"
        services = _comma_list(c.service_ids)
        if services:
            trigger["services"] = [_ref(s, "service_reference") for s in services]
        return await _pagerduty_request(api_key, "POST", "/incident_workflows/triggers", json_body={"trigger": trigger}, from_email=from_email, action_name="create_incident_workflow_trigger")

    async def _update_incident_workflow_trigger(self, c: PagerDutyUpdateIncidentWorkflowTriggerConfig, api_key, from_email) -> Dict[str, Any]:
        trigger = {}
        if c.condition:
            trigger["condition"] = c.condition
        if c.subscribed_to_all_services:
            trigger["subscribed_to_all_services"] = c.subscribed_to_all_services == "true"
        services = _comma_list(c.service_ids)
        if services:
            trigger["services"] = [_ref(s, "service_reference") for s in services]
        return await _pagerduty_request(api_key, "PUT", f"/incident_workflows/triggers/{c.trigger_id}", json_body={"trigger": trigger}, from_email=from_email, action_name="update_incident_workflow_trigger")

    async def _delete_incident_workflow_trigger(self, c: PagerDutyDeleteIncidentWorkflowTriggerConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/incident_workflows/triggers/{c.trigger_id}", from_email=from_email, action_name="delete_incident_workflow_trigger")

    async def _associate_trigger_service(self, c: PagerDutyAssociateTriggerServiceConfig, api_key, from_email) -> Dict[str, Any]:
        body = {"service": _ref(c.service_id, "service_reference")}
        return await _pagerduty_request(api_key, "POST", f"/incident_workflows/triggers/{c.trigger_id}/services", json_body=body, from_email=from_email, action_name="associate_trigger_service")

    async def _disassociate_trigger_service(self, c: PagerDutyDisassociateTriggerServiceConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/incident_workflows/triggers/{c.trigger_id}/services/{c.service_id}", from_email=from_email, action_name="disassociate_trigger_service")

    # --- business-status ---
    async def _list_business_services(self, c: PagerDutyListBusinessServicesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/business_services", params={"limit": c.limit, "offset": c.offset}, action_name="list_business_services")

    async def _get_business_service(self, c: PagerDutyGetBusinessServiceConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/business_services/{c.business_service_id}", action_name="get_business_service")

    async def _create_business_service(self, c: PagerDutyCreateBusinessServiceConfig, api_key, from_email) -> Dict[str, Any]:
        bs: Dict[str, Any] = {"type": "business_service", "name": c.name}
        if c.description: bs["description"] = c.description
        if c.point_of_contact: bs["point_of_contact"] = c.point_of_contact
        if c.team_id: bs["team"] = _ref(c.team_id, "team_reference")
        return await _pagerduty_request(api_key, "POST", "/business_services", json_body={"business_service": bs}, from_email=from_email, action_name="create_business_service")

    async def _update_business_service(self, c: PagerDutyUpdateBusinessServiceConfig, api_key, from_email) -> Dict[str, Any]:
        bs: Dict[str, Any] = {"type": "business_service"}
        if c.name: bs["name"] = c.name
        if c.description: bs["description"] = c.description
        if c.point_of_contact: bs["point_of_contact"] = c.point_of_contact
        if c.team_id: bs["team"] = _ref(c.team_id, "team_reference")
        return await _pagerduty_request(api_key, "PUT", f"/business_services/{c.business_service_id}", json_body={"business_service": bs}, from_email=from_email, action_name="update_business_service")

    async def _delete_business_service(self, c: PagerDutyDeleteBusinessServiceConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/business_services/{c.business_service_id}", from_email=from_email, action_name="delete_business_service")

    async def _list_business_service_subscribers(self, c: PagerDutyListBusinessServiceSubscribersConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/business_services/{c.business_service_id}/subscribers", action_name="list_business_service_subscribers")

    async def _create_business_service_subscribers(self, c: PagerDutyCreateBusinessServiceSubscribersConfig, api_key, from_email) -> Dict[str, Any]:
        subs = [{"subscriber_id": sid, "subscriber_type": c.subscriber_type} for sid in (_comma_list(c.subscriber_ids) or [])]
        return await _pagerduty_request(api_key, "POST", f"/business_services/{c.business_service_id}/subscribers", json_body={"subscribers": subs}, from_email=from_email, action_name="create_business_service_subscribers")

    async def _remove_business_service_subscribers(self, c: PagerDutyRemoveBusinessServiceSubscribersConfig, api_key, from_email) -> Dict[str, Any]:
        subs = [{"subscriber_id": sid, "subscriber_type": c.subscriber_type} for sid in (_comma_list(c.subscriber_ids) or [])]
        return await _pagerduty_request(api_key, "POST", f"/business_services/{c.business_service_id}/unsubscribe", json_body={"subscribers": subs}, from_email=from_email, action_name="remove_business_service_subscribers")

    async def _list_business_service_impacts(self, c: PagerDutyListBusinessServiceImpactsConfig, api_key, from_email) -> Dict[str, Any]:
        params = {"ids[]": _comma_list(c.ids), "additional_fields[]": _comma_list(c.additional_fields)}
        return await _pagerduty_request(api_key, "GET", "/business_services/impacts", params=params, action_name="list_business_service_impacts")

    async def _list_business_service_impactors(self, c: PagerDutyListBusinessServiceImpactorsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/business_services/impactors", params={"ids[]": _comma_list(c.ids)}, action_name="list_business_service_impactors")

    async def _get_priority_thresholds(self, c: PagerDutyGetPriorityThresholdsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/business_services/priority_thresholds", action_name="get_priority_thresholds")

    async def _set_priority_threshold(self, c: PagerDutySetPriorityThresholdConfig, api_key, from_email) -> Dict[str, Any]:
        gt = {"id": c.priority_id, "order": _safe_int(c.order, "order")}
        return await _pagerduty_request(api_key, "PUT", "/business_services/priority_thresholds", json_body={"global_threshold": gt}, from_email=from_email, action_name="set_priority_threshold")

    async def _delete_priority_thresholds(self, c: PagerDutyDeletePriorityThresholdsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", "/business_services/priority_thresholds", from_email=from_email, action_name="delete_priority_thresholds")

    async def _list_status_dashboards(self, c: PagerDutyListStatusDashboardsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/status_dashboards", action_name="list_status_dashboards")

    async def _get_status_dashboard(self, c: PagerDutyGetStatusDashboardConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/status_dashboards/{c.status_dashboard_id}", action_name="get_status_dashboard")

    async def _get_status_dashboard_by_slug(self, c: PagerDutyGetStatusDashboardBySlugConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/status_dashboards/url_slugs/{c.url_slug}", action_name="get_status_dashboard_by_slug")

    async def _get_status_dashboard_service_impacts(self, c: PagerDutyGetStatusDashboardServiceImpactsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/status_dashboards/{c.status_dashboard_id}/service_impacts", params={"additional_fields[]": _comma_list(c.additional_fields)}, action_name="get_status_dashboard_service_impacts")

    async def _list_status_pages(self, c: PagerDutyListStatusPagesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/status_pages", params={"status_page_type": c.status_page_type or None}, action_name="list_status_pages")

    async def _list_status_page_posts(self, c: PagerDutyListStatusPagePostsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/status_pages/{c.status_page_id}/posts", params={"post_type": c.post_type or None}, action_name="list_status_page_posts")

    async def _create_status_page_post(self, c: PagerDutyCreateStatusPagePostConfig, api_key, from_email) -> Dict[str, Any]:
        try:
            updates = json.loads(c.updates)
        except Exception as e:
            raise ValueError(f"Updates must be valid JSON: {e}")
        post = {
            "type": "status_page_post",
            "title": c.title,
            "post_type": c.post_type,
            "starts_at": c.starts_at,
            "ends_at": c.ends_at,
            "updates": updates,
            "status_page": _ref(c.status_page_id, "status_page"),
        }
        return await _pagerduty_request(api_key, "POST", f"/status_pages/{c.status_page_id}/posts", json_body={"post": post}, from_email=from_email, action_name="create_status_page_post")

    async def _get_status_page_post(self, c: PagerDutyGetStatusPagePostConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/status_pages/{c.status_page_id}/posts/{c.post_id}", action_name="get_status_page_post")

    async def _update_status_page_post(self, c: PagerDutyUpdateStatusPagePostConfig, api_key, from_email) -> Dict[str, Any]:
        post = {
            "type": "status_page_post",
            "title": c.title,
            "post_type": c.post_type,
            "starts_at": c.starts_at,
            "ends_at": c.ends_at,
            "status_page": _ref(c.status_page_id, "status_page"),
        }
        return await _pagerduty_request(api_key, "PUT", f"/status_pages/{c.status_page_id}/posts/{c.post_id}", json_body={"post": post}, from_email=from_email, action_name="update_status_page_post")

    async def _delete_status_page_post(self, c: PagerDutyDeleteStatusPagePostConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/status_pages/{c.status_page_id}/posts/{c.post_id}", from_email=from_email, action_name="delete_status_page_post")

    async def _list_status_page_post_updates(self, c: PagerDutyListStatusPagePostUpdatesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/status_pages/{c.status_page_id}/posts/{c.post_id}/post_updates", action_name="list_status_page_post_updates")

    async def _create_status_page_post_update(self, c: PagerDutyCreateStatusPagePostUpdateConfig, api_key, from_email) -> Dict[str, Any]:
        try:
            body = json.loads(c.post_update)
        except Exception as e:
            raise ValueError(f"Post update must be valid JSON: {e}")
        return await _pagerduty_request(api_key, "POST", f"/status_pages/{c.status_page_id}/posts/{c.post_id}/post_updates", json_body={"post_update": body}, from_email=from_email, action_name="create_status_page_post_update")

    async def _get_status_page_post_update(self, c: PagerDutyGetStatusPagePostUpdateConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/status_pages/{c.status_page_id}/posts/{c.post_id}/post_updates/{c.post_update_id}", action_name="get_status_page_post_update")

    async def _update_status_page_post_update(self, c: PagerDutyUpdateStatusPagePostUpdateConfig, api_key, from_email) -> Dict[str, Any]:
        try:
            body = json.loads(c.post_update)
        except Exception as e:
            raise ValueError(f"Post update must be valid JSON: {e}")
        return await _pagerduty_request(api_key, "PUT", f"/status_pages/{c.status_page_id}/posts/{c.post_id}/post_updates/{c.post_update_id}", json_body={"post_update": body}, from_email=from_email, action_name="update_status_page_post_update")

    async def _delete_status_page_post_update(self, c: PagerDutyDeleteStatusPagePostUpdateConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/status_pages/{c.status_page_id}/posts/{c.post_id}/post_updates/{c.post_update_id}", from_email=from_email, action_name="delete_status_page_post_update")

    async def _list_status_page_subscriptions(self, c: PagerDutyListStatusPageSubscriptionsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/status_pages/{c.status_page_id}/subscriptions", params={"channel": c.channel or None}, action_name="list_status_page_subscriptions")

    async def _create_status_page_subscription(self, c: PagerDutyCreateStatusPageSubscriptionConfig, api_key, from_email) -> Dict[str, Any]:
        subscription = {
            "type": "status_page_subscription",
            "channel": c.channel,
            "contact": c.contact,
            "status_page": _ref(c.status_page_id, "status_page"),
            "subscribable_object": _ref(c.subscribable_object_id, c.subscribable_object_type),
        }
        return await _pagerduty_request(api_key, "POST", f"/status_pages/{c.status_page_id}/subscriptions", json_body={"subscription": subscription}, from_email=from_email, action_name="create_status_page_subscription")

    async def _get_status_page_subscription(self, c: PagerDutyGetStatusPageSubscriptionConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/status_pages/{c.status_page_id}/subscriptions/{c.subscription_id}", action_name="get_status_page_subscription")

    async def _delete_status_page_subscription(self, c: PagerDutyDeleteStatusPageSubscriptionConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/status_pages/{c.status_page_id}/subscriptions/{c.subscription_id}", from_email=from_email, action_name="delete_status_page_subscription")

    # --- analytics-audit-changes ---
    async def _analytics_incident_metrics(self, c: PagerDutyIncidentMetricsConfig, api_key, from_email) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "filters": _safe_json(c.filters, "filters") if c.filters else None,
            "time_zone": c.time_zone or None,
            "aggregate_unit": c.aggregate_unit or None,
            "order": c.order or None,
            "order_by": c.order_by or None,
        }
        return await _pagerduty_request(
            api_key, "POST", "/analytics/metrics/incidents/all", json_body=body,
            action_name="analytics_incident_metrics",
        )

    async def _analytics_incident_metrics_by_dimension(self, c: PagerDutyIncidentMetricsByDimensionConfig, api_key, from_email) -> Dict[str, Any]:
        endpoint = f"/analytics/metrics/incidents/{c.dimension}"
        if c.aggregate_all == "true":
            endpoint += "/all"
        body: Dict[str, Any] = {
            "filters": _safe_json(c.filters, "filters") if c.filters else None,
            "time_zone": c.time_zone or None,
            "aggregate_unit": c.aggregate_unit or None,
            "order": c.order or None,
            "order_by": c.order_by or None,
        }
        return await _pagerduty_request(
            api_key, "POST", endpoint, json_body=body,
            action_name="analytics_incident_metrics_by_dimension",
        )

    async def _analytics_raw_incidents(self, c: PagerDutyRawIncidentsConfig, api_key, from_email) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "filters": _safe_json(c.filters, "filters") if c.filters else None,
            "starting_after": c.starting_after or None,
            "ending_before": c.ending_before or None,
            "order": c.order or None,
            "order_by": c.order_by or None,
            "limit": _safe_int(c.limit, "limit") if c.limit else None,
            "time_zone": c.time_zone or None,
        }
        return await _pagerduty_request(
            api_key, "POST", "/analytics/raw/incidents", json_body=body,
            action_name="analytics_raw_incidents",
        )

    async def _get_raw_incident(self, c: PagerDutyGetRawIncidentConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/analytics/raw/incidents/{c.incident_id}",
            action_name="get_raw_incident",
        )

    async def _get_raw_incident_responses(self, c: PagerDutyRawIncidentResponsesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(
            api_key, "GET", f"/analytics/raw/incidents/{c.incident_id}/responses",
            action_name="get_raw_incident_responses",
        )

    async def _analytics_responder_metrics(self, c: PagerDutyResponderMetricsConfig, api_key, from_email) -> Dict[str, Any]:
        endpoint = "/analytics/metrics/responders/all" if c.group_by == "all" else "/analytics/metrics/responders/teams"
        body: Dict[str, Any] = {
            "filters": _safe_json(c.filters, "filters") if c.filters else None,
            "time_zone": c.time_zone or None,
            "order": c.order or None,
            "order_by": c.order_by or None,
        }
        return await _pagerduty_request(
            api_key, "POST", endpoint, json_body=body,
            action_name="analytics_responder_metrics",
        )

    async def _list_audit_records(self, c: PagerDutyListAuditRecordsConfig, api_key, from_email) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "since": c.since,
            "until": c.until,
            "cursor": c.cursor,
            "limit": c.limit,
            "root_resource_types[]": _comma_list(c.root_resource_types),
            "actions[]": _comma_list(c.actions),
        }
        return await _pagerduty_request(
            api_key, "GET", "/audit/records", params=params, action_name="list_audit_records"
        )

    async def _send_change_event(self, c: PagerDutySendChangeEventConfig, api_key, from_email) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"summary": c.summary}
        if c.source:
            payload["source"] = c.source
        if c.custom_details:
            payload["custom_details"] = _safe_json(c.custom_details, "custom_details")
        body = {"routing_key": c.routing_key, "payload": payload}
        return await _pagerduty_request(
            api_key, "POST", "/v2/change/enqueue", json_body=body,
            base_url="https://events.pagerduty.com", action_name="send_change_event",
            use_token_auth=False,
        )

    async def _list_change_events(self, c: PagerDutyListChangeEventsConfig, api_key, from_email) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "team_ids[]": _comma_list(c.team_ids),
            "integration_ids[]": _comma_list(c.integration_ids),
            "since": c.since,
            "until": c.until,
            "limit": c.limit,
        }
        return await _pagerduty_request(
            api_key, "GET", "/change_events", params=params, action_name="list_change_events"
        )

    async def _list_service_change_events(self, c: PagerDutyListServiceChangeEventsConfig, api_key, from_email) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "team_ids[]": _comma_list(c.team_ids),
            "integration_ids[]": _comma_list(c.integration_ids),
            "since": c.since,
            "until": c.until,
            "limit": c.limit,
        }
        return await _pagerduty_request(
            api_key, "GET", f"/services/{c.service_id}/change_events", params=params,
            action_name="list_service_change_events",
        )

    # --- reference-misc ---
    async def _list_custom_fields(self, c: PagerDutyListCustomFieldsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/incidents/custom_fields", action_name="list_custom_fields")

    async def _create_custom_field(self, c: PagerDutyCreateCustomFieldConfig, api_key, from_email) -> Dict[str, Any]:
        field = {"type": "field", "name": c.name, "display_name": c.display_name, "data_type": c.data_type, "field_type": c.field_type}
        if c.description: field["description"] = c.description
        if c.default_value: field["default_value"] = c.default_value
        if c.enabled: field["enabled"] = c.enabled == "true"
        return await _pagerduty_request(api_key, "POST", "/incidents/custom_fields", json_body={"field": field}, from_email=from_email, action_name="create_custom_field")

    async def _get_custom_field(self, c: PagerDutyGetCustomFieldConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/incidents/custom_fields/{c.field_id}", action_name="get_custom_field")

    async def _update_custom_field(self, c: PagerDutyUpdateCustomFieldConfig, api_key, from_email) -> Dict[str, Any]:
        field = {"type": "field"}
        if c.display_name: field["display_name"] = c.display_name
        if c.description: field["description"] = c.description
        if c.default_value: field["default_value"] = c.default_value
        if c.enabled: field["enabled"] = c.enabled == "true"
        return await _pagerduty_request(api_key, "PUT", f"/incidents/custom_fields/{c.field_id}", json_body={"field": field}, from_email=from_email, action_name="update_custom_field")

    async def _delete_custom_field(self, c: PagerDutyDeleteCustomFieldConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/incidents/custom_fields/{c.field_id}", from_email=from_email, action_name="delete_custom_field")

    async def _list_field_options(self, c: PagerDutyListFieldOptionsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/incidents/custom_fields/{c.field_id}/field_options", action_name="list_field_options")

    async def _create_field_option(self, c: PagerDutyCreateFieldOptionConfig, api_key, from_email) -> Dict[str, Any]:
        body = {"field_option": {"data": {"data_type": "string", "value": c.value}}}
        return await _pagerduty_request(api_key, "POST", f"/incidents/custom_fields/{c.field_id}/field_options", json_body=body, from_email=from_email, action_name="create_field_option")

    async def _get_field_option(self, c: PagerDutyGetFieldOptionConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/incidents/custom_fields/{c.field_id}/field_options/{c.field_option_id}", action_name="get_field_option")

    async def _update_field_option(self, c: PagerDutyUpdateFieldOptionConfig, api_key, from_email) -> Dict[str, Any]:
        body = {"field_option": {"id": c.field_option_id, "type": "field_option", "data": {"data_type": "string", "value": c.value}}}
        return await _pagerduty_request(api_key, "PUT", f"/incidents/custom_fields/{c.field_id}/field_options/{c.field_option_id}", json_body=body, from_email=from_email, action_name="update_field_option")

    async def _delete_field_option(self, c: PagerDutyDeleteFieldOptionConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/incidents/custom_fields/{c.field_id}/field_options/{c.field_option_id}", from_email=from_email, action_name="delete_field_option")

    async def _list_templates(self, c: PagerDutyListTemplatesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/templates", params={"template_type": c.template_type}, action_name="list_templates")

    async def _create_template(self, c: PagerDutyCreateTemplateConfig, api_key, from_email) -> Dict[str, Any]:
        template = {"template_type": c.template_type, "name": c.name}
        if c.description: template["description"] = c.description
        if c.templated_fields:
            try:
                template["templated_fields"] = json.loads(c.templated_fields)
            except json.JSONDecodeError as e:
                raise ValueError(f"Templated Fields must be valid JSON: {e}")
        return await _pagerduty_request(api_key, "POST", "/templates", json_body={"template": template}, from_email=from_email, action_name="create_template")

    async def _get_template(self, c: PagerDutyGetTemplateConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/templates/{c.template_id}", action_name="get_template")

    async def _update_template(self, c: PagerDutyUpdateTemplateConfig, api_key, from_email) -> Dict[str, Any]:
        template = {"template_type": "status_update"}
        if c.name: template["name"] = c.name
        if c.description: template["description"] = c.description
        if c.templated_fields:
            try:
                template["templated_fields"] = json.loads(c.templated_fields)
            except json.JSONDecodeError as e:
                raise ValueError(f"Templated Fields must be valid JSON: {e}")
        return await _pagerduty_request(api_key, "PUT", f"/templates/{c.template_id}", json_body={"template": template}, from_email=from_email, action_name="update_template")

    async def _delete_template(self, c: PagerDutyDeleteTemplateConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/templates/{c.template_id}", from_email=from_email, action_name="delete_template")

    async def _render_template(self, c: PagerDutyRenderTemplateConfig, api_key, from_email) -> Dict[str, Any]:
        body = {"incident_id": c.incident_id}
        if c.message:
            body["status_update"] = {"message": c.message}
        return await _pagerduty_request(api_key, "POST", f"/templates/{c.template_id}/render", json_body=body, action_name="render_template")

    async def _list_tags(self, c: PagerDutyListTagsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/tags", params={"query": c.query, "limit": c.limit}, action_name="list_tags")

    async def _create_tag(self, c: PagerDutyCreateTagConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "POST", "/tags", json_body={"tag": {"type": "tag", "label": c.label}}, from_email=from_email, action_name="create_tag")

    async def _get_tag(self, c: PagerDutyGetTagConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/tags/{c.tag_id}", action_name="get_tag")

    async def _delete_tag(self, c: PagerDutyDeleteTagConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/tags/{c.tag_id}", from_email=from_email, action_name="delete_tag")

    async def _get_tags_for_entity(self, c: PagerDutyGetTagsForEntityConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/{c.entity_type}/{c.entity_id}/tags", action_name="get_tags_for_entity")

    async def _change_tags(self, c: PagerDutyChangeTagsConfig, api_key, from_email) -> Dict[str, Any]:
        add = [_ref(tid, "tag_reference") for tid in (_comma_list(c.add_tag_ids) or [])]
        add += [{"type": "tag", "label": lbl} for lbl in (_comma_list(c.add_tag_labels) or [])]
        remove = [_ref(tid, "tag_reference") for tid in (_comma_list(c.remove_tag_ids) or [])]
        body = {}
        if add: body["add"] = add
        if remove: body["remove"] = remove
        return await _pagerduty_request(api_key, "POST", f"/{c.entity_type}/{c.entity_id}/change_tags", json_body=body, from_email=from_email, action_name="change_tags")

    async def _list_vendors(self, c: PagerDutyListVendorsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/vendors", params={"limit": c.limit}, action_name="list_vendors")

    async def _get_vendor(self, c: PagerDutyGetVendorConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/vendors/{c.vendor_id}", action_name="get_vendor")

    async def _list_addons(self, c: PagerDutyListAddonsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/addons", params={"filter": c.filter}, action_name="list_addons")

    async def _create_addon(self, c: PagerDutyCreateAddonConfig, api_key, from_email) -> Dict[str, Any]:
        addon = {"type": c.addon_type, "name": c.name, "src": c.src}
        services = _comma_list(c.service_ids)
        if services:
            addon["services"] = [_ref(s, "service_reference") for s in services]
        return await _pagerduty_request(api_key, "POST", "/addons", json_body={"addon": addon}, from_email=from_email, action_name="create_addon")

    async def _get_addon(self, c: PagerDutyGetAddonConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/addons/{c.addon_id}", action_name="get_addon")

    async def _update_addon(self, c: PagerDutyUpdateAddonConfig, api_key, from_email) -> Dict[str, Any]:
        addon = {"type": c.addon_type, "name": c.name, "src": c.src}
        return await _pagerduty_request(api_key, "PUT", f"/addons/{c.addon_id}", json_body={"addon": addon}, from_email=from_email, action_name="update_addon")

    async def _delete_addon(self, c: PagerDutyDeleteAddonConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "DELETE", f"/addons/{c.addon_id}", from_email=from_email, action_name="delete_addon")

    async def _list_abilities(self, c: PagerDutyListAbilitiesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/abilities", action_name="list_abilities")

    async def _test_ability(self, c: PagerDutyTestAbilityConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", f"/abilities/{c.ability_id}", action_name="test_ability")

    async def _list_notifications(self, c: PagerDutyListNotificationsConfig, api_key, from_email) -> Dict[str, Any]:
        params = {"since": c.since, "until": c.until, "filter": c.filter, "time_zone": c.time_zone, "limit": c.limit}
        return await _pagerduty_request(api_key, "GET", "/notifications", params=params, action_name="list_notifications")

    async def _list_licenses(self, c: PagerDutyListLicensesConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/licenses", action_name="list_licenses")

    async def _list_license_allocations(self, c: PagerDutyListLicenseAllocationsConfig, api_key, from_email) -> Dict[str, Any]:
        return await _pagerduty_request(api_key, "GET", "/license_allocations", params={"limit": c.limit}, action_name="list_license_allocations")

    async def _paused_incident_report_alerts(self, c: PagerDutyPausedIncidentReportAlertsConfig, api_key, from_email) -> Dict[str, Any]:
        params = {"since": c.since, "until": c.until, "service_id": c.service_id, "suspended_by": c.suspended_by}
        return await _pagerduty_request(api_key, "GET", "/paused_incident_reports/alerts", params=params, action_name="paused_incident_report_alerts")

    async def _paused_incident_report_counts(self, c: PagerDutyPausedIncidentReportCountsConfig, api_key, from_email) -> Dict[str, Any]:
        params = {"since": c.since, "until": c.until, "service_id": c.service_id, "suspended_by": c.suspended_by}
        return await _pagerduty_request(api_key, "GET", "/paused_incident_reports/counts", params=params, action_name="paused_incident_report_counts")
