"""
Calendly scheduling automation node.

Integrates the Calendly REST API v2 (https://api.calendly.com) for scheduling
automation: event types, scheduled events + invitees, availability, organization
membership/invitations, no-shows, scheduling links, routing forms, groups,
activity log, data compliance, plus a generic REST passthrough for the long tail
(contacts, shares, outgoing communications, and anything Calendly ships next).

Native webhooks are exposed as triggers (invitee.created / invitee.canceled /
no-show / routing-form-submission / contact.*) via the external-webhook mixin.

Authentication (both are Bearer tokens):
- OAuth 2.0 (authorization_code) — the shared NoClick app; access tokens last
  ~2h and refresh tokens are SINGLE-USE / rotating (persisted every refresh).
- Personal Access Token (PAT) — for single-account/internal use.

Key Calendly conventions:
- URI-as-ID: resources are referenced by their FULL URI, never a bare UUID
  (e.g. user=https://api.calendly.com/users/AAAA). Store/emit URIs verbatim.
- Cursor pagination: ``count`` (max 100) + ``page_token``.
- Datetimes are ISO 8601 UTC (Z-suffixed).

Documentation: https://developer.calendly.com/api-docs
"""

import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Dict, Any, Optional, Literal, Union, Annotated
from urllib.parse import parse_qsl
from pydantic import BaseModel, Field, ConfigDict, Discriminator

import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.scheduling import CALENDLY_SCOPES
from utils.ssrf import assert_exact_url_origin, guarded_async_client

logger = logging.getLogger(__name__)

CALENDLY_API_BASE = "https://api.calendly.com"

# Webhook events Calendly supports (the POST /webhook_subscriptions `events`
# enum). No `invitee.rescheduled` — a reschedule fires canceled + created.
_TRIGGER_EVENTS = {
    "on_invitee_created": "invitee.created",
    "on_invitee_canceled": "invitee.canceled",
    "on_invitee_no_show_created": "invitee_no_show.created",
    "on_invitee_no_show_deleted": "invitee_no_show.deleted",
    "on_routing_form_submission_created": "routing_form_submission.created",
    "on_contact_created": "contact.created",
    "on_contact_updated": "contact.updated",
    "on_contact_deleted": "contact.deleted",
}


def _dyn(field_name: str, noun: str, depends_on: Optional[str] = None) -> Dict[str, Any]:
    spec: Dict[str, Any] = {
        "field_name": field_name,
        "placeholder": f"Select a {noun}...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste the full URI",
    }
    if depends_on:
        spec["depends_on"] = depends_on
    return spec


# ============================================================================
# Credential Schemas
# ============================================================================


class CalendlyOAuthCredential(BaseModel):
    """OAuth 2.0 credential for Calendly (authorization_code flow).

    Tokens are obtained via the consent flow, not entered manually. Access tokens
    expire ~2h and are auto-refreshed via the rotating refresh token.
    """

    credential_type: Literal["calendly_oauth"] = Field(
        "calendly_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="Calendly OAuth access token (Bearer).",
        json_schema_extra={"ui:widget": "password"},
    )
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    owner: Optional[str] = Field(None, title="User URI")
    organization: Optional[str] = Field(None, title="Organization URI")
    email: Optional[str] = Field(None, title="Account Email")
    name: Optional[str] = Field(None, title="Account Name")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "calendly",
            # Calendly's 2026 granular-scope token strings aren't publicly
            # documented; the registered app's access governs (see
            # calendly_oauth.get_calendly_auth_url).
            "x-oauth-scopes": [],
            "x-credential-url": "https://developer.calendly.com/",
        }
    )


class CalendlyPATCredential(BaseModel):
    """Personal Access Token credential for Calendly.

    Create at Calendly → Integrations → API & Webhooks. Used as a Bearer token;
    the node resolves the current user/organization URIs from /users/me on demand.
    """

    credential_type: Literal["calendly_pat"] = Field(
        "calendly_pat", json_schema_extra={"ui:hidden": True}
    )
    personal_access_token: str = Field(
        ...,
        title="Personal Access Token",
        description="Your Calendly Personal Access Token",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://calendly.com/integrations/api_webhooks",
            "x-help-text": "Calendly → Integrations → API & Webhooks → Generate token.",
        }
    )


CalendlyCredential = Union[CalendlyOAuthCredential, CalendlyPATCredential]


# ============================================================================
# Shared field helpers
# ============================================================================


def _count_field(default: str = "20") -> Any:
    return Field(default, title="Count", description="Page size (max 100)")


def _page_token_field() -> Any:
    return Field(None, title="Page Token", description="Opaque cursor for the next page")


# ============================================================================
# Operation Configs — Users
# ============================================================================


def _op_field(op: str, category: str, display: str, keywords: Optional[Any] = None) -> Any:
    extra: Dict[str, Any] = {
        "const": op,
        "ui:hidden": True,
        "x-category": category,
        "x-is-trigger": False,
        "x-display-name": display,
    }
    if keywords:
        extra["x-keywords"] = keywords
    return Field(op, json_schema_extra=extra, title=display)


class CalendlyGetCurrentUserConfig(BaseModel):
    """Get the authenticated user (/users/me)."""
    operation: Literal["get_current_user"] = _op_field(
        "get_current_user", "Users", "Get Current User", ["whoami", "me", "current account"]
    )


class CalendlyGetUserConfig(BaseModel):
    """Get a user by URI or UUID."""
    operation: Literal["get_user"] = _op_field("get_user", "Users", "Get User")
    user: str = Field(
        ..., title="User", description="User URI or UUID",
        json_schema_extra={"x-dynamic-options": _dyn("user", "user")},
    )


# ---- Event Types ----


class CalendlyListEventTypesConfig(BaseModel):
    """List event types for a user or organization."""
    operation: Literal["list_event_types"] = _op_field(
        "list_event_types", "Event Types", "List Event Types", ["meeting types", "booking pages"]
    )
    user: Optional[str] = Field(None, title="User URI", description="Scope to a user (defaults to the connected user)",
                                json_schema_extra={"x-dynamic-options": _dyn("user", "user")})
    organization: Optional[str] = Field(None, title="Organization URI", description="Scope to an organization instead of a user")
    active: Optional[str] = Field(None, title="Active", json_schema_extra={
        "enum": ["", "true", "false"], "enumNames": ["Any", "Active only", "Inactive only"], "x-enum-searchable": True})
    count: Optional[str] = _count_field()
    page_token: Optional[str] = _page_token_field()


class CalendlyGetEventTypeConfig(BaseModel):
    """Get a single event type."""
    operation: Literal["get_event_type"] = _op_field("get_event_type", "Event Types", "Get Event Type")
    event_type: str = Field(..., title="Event Type", description="Event Type URI or UUID",
                            json_schema_extra={"x-dynamic-options": _dyn("event_type", "event type")})


class CalendlyListEventTypeAvailableTimesConfig(BaseModel):
    """List bookable time slots for an event type (window must be future, <=7 days)."""
    operation: Literal["list_event_type_available_times"] = _op_field(
        "list_event_type_available_times", "Event Types", "List Available Times", ["open slots", "availability"]
    )
    event_type: str = Field(..., title="Event Type", description="Event Type URI",
                            json_schema_extra={"x-dynamic-options": _dyn("event_type", "event type")})
    start_time: str = Field(..., title="Start Time", description="ISO 8601 start (future)")
    end_time: str = Field(..., title="End Time", description="ISO 8601 end (<=7 days after start)")


# ---- Scheduled Events ----


class CalendlyListScheduledEventsConfig(BaseModel):
    """List scheduled events (meetings)."""
    operation: Literal["list_scheduled_events"] = _op_field(
        "list_scheduled_events", "Scheduled Events", "List Scheduled Events", ["meetings", "bookings", "appointments"]
    )
    user: Optional[str] = Field(None, title="User URI", description="Scope to a user (defaults to the connected user)",
                                json_schema_extra={"x-dynamic-options": _dyn("user", "user")})
    organization: Optional[str] = Field(None, title="Organization URI", description="Scope to an organization")
    invitee_email: Optional[str] = Field(None, title="Invitee Email", description="Filter by invitee email")
    status: Optional[str] = Field(None, title="Status", json_schema_extra={
        "enum": ["", "active", "canceled"], "enumNames": ["Any", "Active", "Canceled"], "x-enum-searchable": True})
    min_start_time: Optional[str] = Field(None, title="Min Start Time", description="ISO 8601")
    max_start_time: Optional[str] = Field(None, title="Max Start Time", description="ISO 8601")
    sort: Optional[str] = Field(None, title="Sort", description="e.g. start_time:asc")
    count: Optional[str] = _count_field()
    page_token: Optional[str] = _page_token_field()


class CalendlyGetScheduledEventConfig(BaseModel):
    """Get a single scheduled event."""
    operation: Literal["get_scheduled_event"] = _op_field("get_scheduled_event", "Scheduled Events", "Get Scheduled Event")
    scheduled_event: str = Field(..., title="Scheduled Event", description="Scheduled Event URI or UUID")


class CalendlyCancelScheduledEventConfig(BaseModel):
    """Cancel a scheduled event (fires invitee.canceled)."""
    operation: Literal["cancel_scheduled_event"] = _op_field(
        "cancel_scheduled_event", "Scheduled Events", "Cancel Scheduled Event", ["cancel meeting"]
    )
    scheduled_event: str = Field(..., title="Scheduled Event", description="Scheduled Event URI or UUID")
    reason: Optional[str] = Field(None, title="Reason", description="Cancellation reason (<=10000 chars)")


class CalendlyListEventInviteesConfig(BaseModel):
    """List invitees of a scheduled event."""
    operation: Literal["list_event_invitees"] = _op_field(
        "list_event_invitees", "Scheduled Events", "List Event Invitees", ["attendees", "guests"]
    )
    scheduled_event: str = Field(..., title="Scheduled Event", description="Scheduled Event URI or UUID")
    status: Optional[str] = Field(None, title="Status", json_schema_extra={
        "enum": ["", "active", "canceled"], "enumNames": ["Any", "Active", "Canceled"], "x-enum-searchable": True})
    email: Optional[str] = Field(None, title="Email", description="Filter by invitee email")
    count: Optional[str] = _count_field()
    page_token: Optional[str] = _page_token_field()


class CalendlyGetEventInviteeConfig(BaseModel):
    """Get a single invitee of a scheduled event."""
    operation: Literal["get_event_invitee"] = _op_field("get_event_invitee", "Scheduled Events", "Get Event Invitee")
    scheduled_event: str = Field(..., title="Scheduled Event", description="Scheduled Event URI or UUID")
    invitee: str = Field(..., title="Invitee", description="Invitee URI or UUID")


# ---- No-shows ----


class CalendlyCreateNoShowConfig(BaseModel):
    """Mark an invitee as a no-show."""
    operation: Literal["create_no_show"] = _op_field("create_no_show", "No-Shows", "Mark No-Show", ["didn't attend"])
    invitee: str = Field(..., title="Invitee URI", description="Full invitee URI to mark as a no-show")


class CalendlyGetNoShowConfig(BaseModel):
    """Get a no-show record."""
    operation: Literal["get_no_show"] = _op_field("get_no_show", "No-Shows", "Get No-Show")
    no_show: str = Field(..., title="No-Show", description="Invitee No-Show URI or UUID")


class CalendlyDeleteNoShowConfig(BaseModel):
    """Undo a no-show marking."""
    operation: Literal["delete_no_show"] = _op_field("delete_no_show", "No-Shows", "Undo No-Show")
    no_show: str = Field(..., title="No-Show", description="Invitee No-Show URI or UUID")


# ---- Organizations / Memberships / Invitations ----


class CalendlyGetOrganizationConfig(BaseModel):
    """Get an organization."""
    operation: Literal["get_organization"] = _op_field("get_organization", "Organization", "Get Organization")
    organization: Optional[str] = Field(None, title="Organization URI", description="Defaults to the connected organization")


class CalendlyListMembershipsConfig(BaseModel):
    """List organization memberships (members)."""
    operation: Literal["list_organization_memberships"] = _op_field(
        "list_organization_memberships", "Organization", "List Memberships", ["team members", "users in org"]
    )
    organization: Optional[str] = Field(None, title="Organization URI", description="Defaults to the connected organization")
    user: Optional[str] = Field(None, title="User URI", description="Filter to a single user",
                                json_schema_extra={"x-dynamic-options": _dyn("user", "user")})
    email: Optional[str] = Field(None, title="Email", description="Filter by member email")
    count: Optional[str] = _count_field()
    page_token: Optional[str] = _page_token_field()


class CalendlyGetMembershipConfig(BaseModel):
    """Get an organization membership."""
    operation: Literal["get_organization_membership"] = _op_field(
        "get_organization_membership", "Organization", "Get Membership"
    )
    membership: str = Field(..., title="Membership", description="Organization Membership URI or UUID")


class CalendlyRemoveMembershipConfig(BaseModel):
    """Remove a user from the organization."""
    operation: Literal["remove_organization_membership"] = _op_field(
        "remove_organization_membership", "Organization", "Remove Member", ["kick user", "revoke access"]
    )
    membership: str = Field(..., title="Membership", description="Organization Membership URI or UUID")


class CalendlyListInvitationsConfig(BaseModel):
    """List organization invitations."""
    operation: Literal["list_organization_invitations"] = _op_field(
        "list_organization_invitations", "Organization", "List Invitations"
    )
    organization: Optional[str] = Field(None, title="Organization URI", description="Defaults to the connected organization")
    status: Optional[str] = Field(None, title="Status", json_schema_extra={
        "enum": ["", "pending", "accepted", "declined"],
        "enumNames": ["Any", "Pending", "Accepted", "Declined"], "x-enum-searchable": True})
    email: Optional[str] = Field(None, title="Email")
    count: Optional[str] = _count_field()
    page_token: Optional[str] = _page_token_field()


class CalendlyCreateInvitationConfig(BaseModel):
    """Invite a user to the organization."""
    operation: Literal["create_organization_invitation"] = _op_field(
        "create_organization_invitation", "Organization", "Invite User", ["add member", "send invite"]
    )
    organization: Optional[str] = Field(None, title="Organization URI", description="Defaults to the connected organization")
    email: str = Field(..., title="Email", description="Email address to invite")


class CalendlyRevokeInvitationConfig(BaseModel):
    """Revoke a pending organization invitation."""
    operation: Literal["revoke_organization_invitation"] = _op_field(
        "revoke_organization_invitation", "Organization", "Revoke Invitation"
    )
    organization: Optional[str] = Field(None, title="Organization URI", description="Defaults to the connected organization")
    invitation: str = Field(..., title="Invitation", description="Invitation URI or UUID")


# ---- Scheduling ----


class CalendlyCreateSchedulingLinkConfig(BaseModel):
    """Create a single-use scheduling link for an event type."""
    operation: Literal["create_scheduling_link"] = _op_field(
        "create_scheduling_link", "Scheduling", "Create Scheduling Link", ["one-time booking link"]
    )
    owner: str = Field(..., title="Event Type URI", description="Event Type URI the link books",
                       json_schema_extra={"x-dynamic-options": _dyn("event_type", "event type")})


class CalendlyCreateShareConfig(BaseModel):
    """Create a shareable, customization-limited copy of an event type."""
    operation: Literal["create_share"] = _op_field("create_share", "Scheduling", "Create Share")
    event_type: str = Field(..., title="Event Type URI", description="Event Type URI to share",
                            json_schema_extra={"x-dynamic-options": _dyn("event_type", "event type")})
    body_json: Optional[str] = Field(None, title="Overrides (JSON)", description="Optional share overrides as JSON",
                                     json_schema_extra={"ui:widget": "textarea"})


# ---- Availability ----


class CalendlyListAvailabilitySchedulesConfig(BaseModel):
    """List a user's availability schedules."""
    operation: Literal["list_user_availability_schedules"] = _op_field(
        "list_user_availability_schedules", "Availability", "List Availability Schedules"
    )
    user: Optional[str] = Field(None, title="User URI", description="Defaults to the connected user",
                                json_schema_extra={"x-dynamic-options": _dyn("user", "user")})


class CalendlyListBusyTimesConfig(BaseModel):
    """List a user's busy times (window must be future, <=7 days)."""
    operation: Literal["list_user_busy_times"] = _op_field(
        "list_user_busy_times", "Availability", "List Busy Times", ["blocked time", "unavailable"]
    )
    user: Optional[str] = Field(None, title="User URI", description="Defaults to the connected user",
                                json_schema_extra={"x-dynamic-options": _dyn("user", "user")})
    start_time: str = Field(..., title="Start Time", description="ISO 8601 (future)")
    end_time: str = Field(..., title="End Time", description="ISO 8601 (<=7 days after start)")


# ---- Routing Forms ----


class CalendlyListRoutingFormsConfig(BaseModel):
    """List routing forms (Teams+)."""
    operation: Literal["list_routing_forms"] = _op_field("list_routing_forms", "Routing", "List Routing Forms")
    organization: Optional[str] = Field(None, title="Organization URI", description="Defaults to the connected organization")
    count: Optional[str] = _count_field()
    page_token: Optional[str] = _page_token_field()


class CalendlyListRoutingSubmissionsConfig(BaseModel):
    """List routing form submissions (Teams+)."""
    operation: Literal["list_routing_form_submissions"] = _op_field(
        "list_routing_form_submissions", "Routing", "List Routing Form Submissions"
    )
    form: str = Field(..., title="Routing Form URI", description="Routing Form URI")
    count: Optional[str] = _count_field()
    page_token: Optional[str] = _page_token_field()


# ---- Groups (Teams/Enterprise) ----


class CalendlyListGroupsConfig(BaseModel):
    """List groups (Teams/Enterprise)."""
    operation: Literal["list_groups"] = _op_field("list_groups", "Groups", "List Groups")
    organization: Optional[str] = Field(None, title="Organization URI", description="Defaults to the connected organization")
    count: Optional[str] = _count_field()
    page_token: Optional[str] = _page_token_field()


class CalendlyListGroupRelationshipsConfig(BaseModel):
    """List group relationships (group membership is exposed only here)."""
    operation: Literal["list_group_relationships"] = _op_field(
        "list_group_relationships", "Groups", "List Group Relationships", ["group members"]
    )
    organization: Optional[str] = Field(None, title="Organization URI", description="Scope by organization")
    owner: Optional[str] = Field(None, title="Owner URI", description="Scope by owner")
    group: Optional[str] = Field(None, title="Group URI", description="Scope by group")
    count: Optional[str] = _count_field()
    page_token: Optional[str] = _page_token_field()


# ---- Enterprise: activity log + data compliance ----


class CalendlyListActivityLogConfig(BaseModel):
    """List organization activity log entries (Enterprise)."""
    operation: Literal["list_activity_log"] = _op_field("list_activity_log", "Enterprise", "List Activity Log")
    organization: Optional[str] = Field(None, title="Organization URI", description="Defaults to the connected organization")
    search_term: Optional[str] = Field(None, title="Search")
    min_occurred_at: Optional[str] = Field(None, title="From", description="ISO 8601")
    max_occurred_at: Optional[str] = Field(None, title="To", description="ISO 8601")
    sort: Optional[str] = Field(None, title="Sort", description="e.g. occurred_at:desc")
    count: Optional[str] = _count_field()
    page_token: Optional[str] = _page_token_field()


class CalendlyDeleteInviteeDataConfig(BaseModel):
    """GDPR-delete invitee data by email (Enterprise)."""
    operation: Literal["delete_invitee_data"] = _op_field(
        "delete_invitee_data", "Enterprise", "Delete Invitee Data", ["gdpr", "erase invitee"]
    )
    emails: str = Field(..., title="Emails", description="Comma-separated invitee emails to delete")


class CalendlyDeleteEventDataConfig(BaseModel):
    """Delete scheduled-event data by time range (Enterprise)."""
    operation: Literal["delete_event_data"] = _op_field(
        "delete_event_data", "Enterprise", "Delete Event Data", ["gdpr", "erase events"]
    )
    start_time: str = Field(..., title="Start Time", description="ISO 8601 range start")
    end_time: str = Field(..., title="End Time", description="ISO 8601 range end")


# ---- Generic passthrough ----


class CalendlyCustomRequestConfig(BaseModel):
    """Call any authenticated Calendly REST endpoint (covers the long tail:
    contacts, outgoing communications, analytics, and anything new)."""
    operation: Literal["custom_request"] = _op_field("custom_request", "Advanced", "Custom Request")
    method: Literal["GET", "POST", "PATCH", "DELETE"] = Field("GET", title="Method")
    path: str = Field(..., title="Path", description="Path after https://api.calendly.com, e.g. /contacts or /event_types/UUID")
    query_params: Optional[str] = Field(None, title="Query Parameters", description="e.g. organization=...&count=100")
    body_json: Optional[str] = Field(None, title="JSON Body", description="Optional JSON body for POST/PATCH",
                                     json_schema_extra={"ui:widget": "textarea"})


# ============================================================================
# Webhook Trigger Configs
# ============================================================================


class _CalendlyTriggerBase(WebhookTriggerConfigBase):
    """Shared fields for Calendly webhook triggers.

    Calendly webhook subscriptions are scoped to a user or the whole
    organization. `scope=organization` needs Owner/Admin; routing-form and
    contact events are organization-scoped only.
    """

    scope: Literal["user", "organization"] = Field(
        "organization",
        title="Scope",
        description="Fire for the whole organization (Owner/Admin) or just the connected user. Routing-form/contact events are organization-scoped only.",
        json_schema_extra={"x-enum-searchable": True, "enumNames": ["Organization", "User"]},
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )


def _trigger_op(op: str, display: str, keywords: Any) -> Any:
    return Field(
        op,
        title=display,
        json_schema_extra={
            "const": op, "ui:hidden": True, "x-is-trigger": True,
            "x-category": "Triggers", "x-display-name": display, "x-keywords": keywords,
        },
    )


class CalendlyOnInviteeCreatedConfig(_CalendlyTriggerBase):
    """Fires when someone books a meeting (invitee.created)."""
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_invitee_created"] = _trigger_op(
        "on_invitee_created", "On Invitee Created", ["new booking", "meeting scheduled", "someone booked"])


class CalendlyOnInviteeCanceledConfig(_CalendlyTriggerBase):
    """Fires when a booking is canceled (invitee.canceled)."""
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_invitee_canceled"] = _trigger_op(
        "on_invitee_canceled", "On Invitee Canceled", ["cancellation", "meeting canceled", "booking canceled"])


class CalendlyOnNoShowCreatedConfig(_CalendlyTriggerBase):
    """Fires when an invitee is marked a no-show."""
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_invitee_no_show_created"] = _trigger_op(
        "on_invitee_no_show_created", "On No-Show Marked", ["no show", "didn't attend"])


class CalendlyOnNoShowDeletedConfig(_CalendlyTriggerBase):
    """Fires when a no-show marking is removed."""
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_invitee_no_show_deleted"] = _trigger_op(
        "on_invitee_no_show_deleted", "On No-Show Undone", ["no show removed"])


class CalendlyOnRoutingSubmissionConfig(_CalendlyTriggerBase):
    """Fires when a routing form is submitted (organization scope only)."""
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_routing_form_submission_created"] = _trigger_op(
        "on_routing_form_submission_created", "On Routing Form Submission", ["routing form submitted", "lead routed"])


class CalendlyOnContactCreatedConfig(_CalendlyTriggerBase):
    """Fires when a CRM contact is created."""
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_contact_created"] = _trigger_op(
        "on_contact_created", "On Contact Created", ["new contact"])


class CalendlyOnContactUpdatedConfig(_CalendlyTriggerBase):
    """Fires when a CRM contact is updated."""
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_contact_updated"] = _trigger_op(
        "on_contact_updated", "On Contact Updated", ["contact changed"])


class CalendlyOnContactDeletedConfig(_CalendlyTriggerBase):
    """Fires when a CRM contact is deleted."""
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_contact_deleted"] = _trigger_op(
        "on_contact_deleted", "On Contact Deleted", ["contact removed"])


# ============================================================================
# Discriminated Union
# ============================================================================

_ACTION_CONFIGS = (
    CalendlyGetCurrentUserConfig, CalendlyGetUserConfig,
    CalendlyListEventTypesConfig, CalendlyGetEventTypeConfig, CalendlyListEventTypeAvailableTimesConfig,
    CalendlyListScheduledEventsConfig, CalendlyGetScheduledEventConfig, CalendlyCancelScheduledEventConfig,
    CalendlyListEventInviteesConfig, CalendlyGetEventInviteeConfig,
    CalendlyCreateNoShowConfig, CalendlyGetNoShowConfig, CalendlyDeleteNoShowConfig,
    CalendlyGetOrganizationConfig, CalendlyListMembershipsConfig, CalendlyGetMembershipConfig,
    CalendlyRemoveMembershipConfig, CalendlyListInvitationsConfig, CalendlyCreateInvitationConfig,
    CalendlyRevokeInvitationConfig,
    CalendlyCreateSchedulingLinkConfig, CalendlyCreateShareConfig,
    CalendlyListAvailabilitySchedulesConfig, CalendlyListBusyTimesConfig,
    CalendlyListRoutingFormsConfig, CalendlyListRoutingSubmissionsConfig,
    CalendlyListGroupsConfig, CalendlyListGroupRelationshipsConfig,
    CalendlyListActivityLogConfig, CalendlyDeleteInviteeDataConfig, CalendlyDeleteEventDataConfig,
    CalendlyCustomRequestConfig,
)

_TRIGGER_CONFIGS = (
    CalendlyOnInviteeCreatedConfig, CalendlyOnInviteeCanceledConfig,
    CalendlyOnNoShowCreatedConfig, CalendlyOnNoShowDeletedConfig,
    CalendlyOnRoutingSubmissionConfig,
    CalendlyOnContactCreatedConfig, CalendlyOnContactUpdatedConfig, CalendlyOnContactDeletedConfig,
)

CalendlyConfig = Annotated[
    Union[tuple(_ACTION_CONFIGS) + tuple(_TRIGGER_CONFIGS)],
    Discriminator("operation"),
]


class CalendlyNodeConfig(NodeConfig[CalendlyConfig, CalendlyCredential]):
    """Full configuration for the Calendly node including credentials."""
    pass


# ============================================================================
# Module-level HTTP helpers
# ============================================================================


def _bearer(credential: Dict[str, Any]) -> Optional[str]:
    return credential.get("access_token") or credential.get("personal_access_token")


def _uuid_tail(value: str) -> str:
    """Return the last path segment (UUID) from a URI, or the value itself."""
    return value.rstrip("/").rsplit("/", 1)[-1] if value else value


def _as_uri(resource: str, value: str) -> str:
    """Coerce a bare UUID into a full, provider-bound Calendly URI."""
    if not value:
        return value
    if value.startswith("http://") or value.startswith("https://"):
        assert_exact_url_origin(value, CALENDLY_API_BASE)
        return value
    return f"{CALENDLY_API_BASE}/{resource}/{value}"


def _parse_query(raw: Optional[str]) -> Dict[str, str]:
    if not raw:
        return {}
    return {k: v for k, v in parse_qsl(raw.lstrip("?"), keep_blank_values=True)}


def _parse_json(raw: Optional[str], field: str) -> Any:
    if raw in (None, ""):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must be valid JSON: {exc.msg}") from exc


async def _calendly_request(
    credential: Dict[str, Any],
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Calendly REST request and return a structured result."""
    # Every caller reaches this single credential-attachment choke point.
    # Validate before reading or formatting the bearer token.
    assert_exact_url_origin(url, CALENDLY_API_BASE)
    token = _bearer(credential)
    if not token:
        return {"status": "error", "action": action_name, "error": "Calendly credential is missing an access token", "status_code": 401}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if isinstance(json_body, dict):
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with guarded_async_client(timeout=45.0) as client:
        try:
            response = await client.request(method=method, url=url, headers=headers, params=params, json=json_body)
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = err.get("message") or err.get("title") or err
                    details = err.get("details")
                except Exception:
                    message, details = response.text, None
                logger.error(f"[CalendlyNode] API error ({action_name}): {message}")
                return {
                    "status": "error", "action": action_name, "error": message,
                    "details": details, "status_code": response.status_code,
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
                "status": "success", "action": action_name, "data": data,
                "status_code": response.status_code, "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {"status": "error", "action": action_name, "error": "Request timed out", "status_code": 408,
                    "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)}}
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[CalendlyNode] Request failed ({action_name}): {msg}")
            return {"status": "error", "action": action_name, "error": msg, "status_code": 500,
                    "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)}}


# ============================================================================
# Node Implementation
# ============================================================================


class CalendlyNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Calendly scheduling automation node (REST v2 + native webhook triggers)."""

    edit_examples = [
        "List all upcoming Calendly meetings",
        "Get the invitees of a scheduled event",
        "Cancel a scheduled meeting",
        "List my event types",
        "When someone books a meeting, add them to a CRM",
    ]

    scope_registry = CALENDLY_SCOPES
    connection_evidence = ConnectionEvidence(
        field="event_type",
        noun="event types",
    )
    @classmethod
    def get_config_model(cls):
        return CalendlyNodeConfig

    # ------------------------------------------------------------------
    # OAuth freshening (rotating refresh)
    # ------------------------------------------------------------------
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring Calendly OAuth token at load. No-op for PAT."""
        if not credential_data or credential_data.get("credential_type") != "calendly_oauth":
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.calendly_oauth import refresh_access_token
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="calendly",
        )

    async def _ensure_fresh_token(self, credentials: "CalendlyCredential") -> None:
        if not isinstance(credentials, CalendlyOAuthCredential):
            return
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.calendly_oauth import refresh_access_token
        from utils.database_pool import get_native_pool

        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            pool=get_native_pool(),
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="calendly",
            caller_path="execute",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]

    # ------------------------------------------------------------------
    # Current-user/org resolution (URI-as-ID defaults) — cached per instance
    # ------------------------------------------------------------------
    async def _resolve_me(self, credential: Dict[str, Any]) -> Dict[str, Any]:
        cached = getattr(self, "_me_cache", None)
        if cached is not None:
            return cached
        owner = credential.get("owner")
        organization = credential.get("organization")
        if owner and organization:
            self._me_cache = {"user": owner, "organization": organization}
            return self._me_cache
        result = await _calendly_request(credential, "GET", f"{CALENDLY_API_BASE}/users/me", action_name="get_current_user")
        resource = (result.get("data") or {}).get("resource", {}) if result.get("status") == "success" else {}
        self._me_cache = {
            "user": owner or resource.get("uri"),
            "organization": organization or resource.get("current_organization"),
        }
        return self._me_cache

    async def _default_user(self, credential: Dict[str, Any], provided: Optional[str]) -> Optional[str]:
        if provided:
            return _as_uri("users", provided)
        return (await self._resolve_me(credential)).get("user")

    async def _default_org(self, credential: Dict[str, Any], provided: Optional[str]) -> Optional[str]:
        if provided:
            return _as_uri("organizations", provided)
        return (await self._resolve_me(credential)).get("organization")

    # ------------------------------------------------------------------
    # Dynamic options
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        credential = credential_data or {}
        if field_name not in ("user", "event_type"):
            return {"options": [], "next_page_token": None}
        if not _bearer(credential):
            raise ValueError("Connect a Calendly account to load options")

        # Resolve org/user context for scoping.
        me = await _calendly_request(credential, "GET", f"{CALENDLY_API_BASE}/users/me", action_name="get_current_user")
        me_res = (me.get("data") or {}).get("resource", {}) if me.get("status") == "success" else {}
        org = credential.get("organization") or me_res.get("current_organization")
        user_uri = credential.get("owner") or me_res.get("uri")

        params: Dict[str, Any] = {"count": "100"}
        if page_token:
            params["page_token"] = page_token

        if field_name == "user":
            # List members of the org → their user URIs.
            params["organization"] = org
            url = f"{CALENDLY_API_BASE}/organization_memberships"
            result = await _calendly_request(credential, "GET", url, params=params, action_name="list_organization_memberships")
            rows = (result.get("data") or {}).get("collection", []) if result.get("status") == "success" else []
            options = []
            for row in rows:
                u = (row or {}).get("user") or {}
                if u.get("uri"):
                    options.append({"label": u.get("name") or u.get("email") or u["uri"], "value": u["uri"]})
        else:  # event_type
            params["user"] = user_uri
            url = f"{CALENDLY_API_BASE}/event_types"
            result = await _calendly_request(credential, "GET", url, params=params, action_name="list_event_types")
            rows = (result.get("data") or {}).get("collection", []) if result.get("status") == "success" else []
            options = [{"label": r.get("name") or r.get("uri"), "value": r.get("uri")} for r in rows if r.get("uri")]

        if result.get("status") != "success":
            raise ValueError(f"Failed to load Calendly options: {result.get('error')}")
        next_token = ((result.get("data") or {}).get("pagination") or {}).get("next_page_token")
        from nodes.core.dynamic_options import filter_options_by_search
        return {
            "options": filter_options_by_search(options, search, fields=("label", "value")),
            "next_page_token": next_token,
        }

    # ------------------------------------------------------------------
    # Webhook trigger lifecycle
    # ------------------------------------------------------------------
    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "scope": (config or {}).get("scope"),
        }

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id) -> Dict[str, Any]:
        if not _bearer(credential or {}):
            raise ValueError("Calendly credential is missing an access token")
        op = (config or {}).get("operation")
        event = _TRIGGER_EVENTS.get(op)
        if not event:
            raise ValueError(f"Unknown Calendly trigger operation: {op}")

        # This value can arrive from a persisted graph. Validate it before any
        # credentialed provider request, including the /users/me lookup below.
        existing = (config or {}).get("external_webhook_id")
        existing_uri = (
            _as_uri("webhook_subscriptions", str(existing)) if existing else None
        )

        scope = (config or {}).get("scope") or "organization"
        # Contact + routing-form events are organization-scoped only.
        if event.startswith("contact.") or event == "routing_form_submission.created":
            scope = "organization"

        # Resolve org (+ user for user scope) from the credential / /users/me.
        me = await _calendly_request(credential, "GET", f"{CALENDLY_API_BASE}/users/me", action_name="get_current_user")
        me_res = (me.get("data") or {}).get("resource", {}) if me.get("status") == "success" else {}
        organization = (credential or {}).get("organization") or me_res.get("current_organization")
        user_uri = (credential or {}).get("owner") or me_res.get("uri")
        if not organization:
            raise ValueError("Could not resolve the Calendly organization for this credential")

        # Drop a stale subscription from a previous registration (create is not idempotent).
        if existing_uri:
            try:
                await _calendly_request(credential, "DELETE", existing_uri,
                                        action_name="delete_webhook_subscription")
            except Exception as e:
                logger.warning(f"[CalendlyNode] Could not remove stale webhook: {e}")

        signing_key = secrets.token_hex(32)
        body: Dict[str, Any] = {
            "url": webhook_url,
            "events": [event],
            "organization": organization,
            "scope": scope,
            "signing_key": signing_key,
        }
        if scope == "user":
            if not user_uri:
                raise ValueError("Could not resolve the Calendly user for a user-scoped webhook")
            body["user"] = user_uri

        result = await _calendly_request(credential, "POST", f"{CALENDLY_API_BASE}/webhook_subscriptions",
                                         json_body=body, action_name="create_webhook_subscription")
        if result.get("status") != "success":
            raise ValueError(f"Calendly webhook registration failed: {result.get('error')}")
        raw_uri = ((result.get("data") or {}).get("resource") or {}).get("uri")
        if not raw_uri:
            raise ValueError("Calendly did not return a webhook subscription URI")
        uri = _as_uri("webhook_subscriptions", str(raw_uri))
        return {"signing_secret": signing_key, "external_webhook_id": uri}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id) -> None:
        webhook_id = (config or {}).get("external_webhook_id")
        if not credential or not _bearer(credential) or not webhook_id:
            return
        await _calendly_request(credential, "DELETE", _as_uri("webhook_subscriptions", str(webhook_id)),
                                action_name="delete_webhook_subscription")

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]) -> bool:
        """Verify Calendly's ``Calendly-Webhook-Signature: t=…,v1=…`` header
        (HMAC-SHA256 of ``{t}.{raw_body}`` with the subscription signing key)."""
        secret = (config or {}).get("signing_secret")
        if not secret:
            return False
        sig_header = headers.get("calendly-webhook-signature") or headers.get("Calendly-Webhook-Signature")
        if not sig_header:
            return False
        parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
        timestamp, provided = parts.get("t"), parts.get("v1")
        if not timestamp or not provided:
            return False
        signed_payload = f"{timestamp}.".encode() + body
        expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, provided)

    @classmethod
    def resolve_agent_event(cls, output):
        """Translate a fired Calendly webhook into an agent turn."""
        payload = output if isinstance(output, dict) else {}
        event = payload.get("event")
        text = json.dumps(payload, default=str)[:6000]
        return {"text": f"Calendly event {event}:\n{text}" if event else text, "conversation_key": None}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, CalendlyNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        # Triggers: the webhook delivery IS the data — pass the fired payload through.
        if (op.operation in _TRIGGER_EVENTS):
            return {
                "status": "success", "action": op.operation,
                "data": inputs or {},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Connect a Calendly OAuth or Personal Access Token credential.")
        await self._ensure_fresh_token(credentials)
        cred = credentials.model_dump()
        self._me_cache = None

        handlers = {
            "get_current_user": self._get_current_user,
            "get_user": self._get_user,
            "list_event_types": self._list_event_types,
            "get_event_type": self._get_event_type,
            "list_event_type_available_times": self._list_event_type_available_times,
            "list_scheduled_events": self._list_scheduled_events,
            "get_scheduled_event": self._get_scheduled_event,
            "cancel_scheduled_event": self._cancel_scheduled_event,
            "list_event_invitees": self._list_event_invitees,
            "get_event_invitee": self._get_event_invitee,
            "create_no_show": self._create_no_show,
            "get_no_show": self._get_no_show,
            "delete_no_show": self._delete_no_show,
            "get_organization": self._get_organization,
            "list_organization_memberships": self._list_memberships,
            "get_organization_membership": self._get_membership,
            "remove_organization_membership": self._remove_membership,
            "list_organization_invitations": self._list_invitations,
            "create_organization_invitation": self._create_invitation,
            "revoke_organization_invitation": self._revoke_invitation,
            "create_scheduling_link": self._create_scheduling_link,
            "create_share": self._create_share,
            "list_user_availability_schedules": self._list_availability_schedules,
            "list_user_busy_times": self._list_busy_times,
            "list_routing_forms": self._list_routing_forms,
            "list_routing_form_submissions": self._list_routing_submissions,
            "list_groups": self._list_groups,
            "list_group_relationships": self._list_group_relationships,
            "list_activity_log": self._list_activity_log,
            "delete_invitee_data": self._delete_invitee_data,
            "delete_event_data": self._delete_event_data,
            "custom_request": self._custom_request,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, cred)
        result["timing_ms"] = {**result.get("timing_ms", {}), "total": round((time.time() - start_time) * 1000, 2)}
        return result

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    async def _get_current_user(self, c, cred):
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/users/me", action_name="get_current_user")

    async def _get_user(self, c, cred):
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/users/{_uuid_tail(c.user)}", action_name="get_user")

    async def _list_event_types(self, c, cred):
        params = {"active": c.active, "count": c.count, "page_token": c.page_token}
        if c.organization:
            params["organization"] = _as_uri("organizations", c.organization)
        else:
            params["user"] = await self._default_user(cred, c.user)
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/event_types", params=params, action_name="list_event_types")

    async def _get_event_type(self, c, cred):
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/event_types/{_uuid_tail(c.event_type)}", action_name="get_event_type")

    async def _list_event_type_available_times(self, c, cred):
        params = {"event_type": _as_uri("event_types", c.event_type), "start_time": c.start_time, "end_time": c.end_time}
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/event_type_available_times", params=params, action_name="list_event_type_available_times")

    async def _list_scheduled_events(self, c, cred):
        params = {
            "invitee_email": c.invitee_email, "status": c.status,
            "min_start_time": c.min_start_time, "max_start_time": c.max_start_time,
            "sort": c.sort, "count": c.count, "page_token": c.page_token,
        }
        if c.organization:
            params["organization"] = _as_uri("organizations", c.organization)
        else:
            params["user"] = await self._default_user(cred, c.user)
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/scheduled_events", params=params, action_name="list_scheduled_events")

    async def _get_scheduled_event(self, c, cred):
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/scheduled_events/{_uuid_tail(c.scheduled_event)}", action_name="get_scheduled_event")

    async def _cancel_scheduled_event(self, c, cred):
        body = {"reason": c.reason} if c.reason else None
        url = f"{CALENDLY_API_BASE}/scheduled_events/{_uuid_tail(c.scheduled_event)}/cancellation"
        return await _calendly_request(cred, "POST", url, json_body=body, action_name="cancel_scheduled_event")

    async def _list_event_invitees(self, c, cred):
        params = {"status": c.status, "email": c.email, "count": c.count, "page_token": c.page_token}
        url = f"{CALENDLY_API_BASE}/scheduled_events/{_uuid_tail(c.scheduled_event)}/invitees"
        return await _calendly_request(cred, "GET", url, params=params, action_name="list_event_invitees")

    async def _get_event_invitee(self, c, cred):
        url = f"{CALENDLY_API_BASE}/scheduled_events/{_uuid_tail(c.scheduled_event)}/invitees/{_uuid_tail(c.invitee)}"
        return await _calendly_request(cred, "GET", url, action_name="get_event_invitee")

    async def _create_no_show(self, c, cred):
        # invitee must be a full invitee URI (…/scheduled_events/{ev}/invitees/{inv}).
        return await _calendly_request(cred, "POST", f"{CALENDLY_API_BASE}/invitee_no_shows",
                                       json_body={"invitee": c.invitee}, action_name="create_no_show")

    async def _get_no_show(self, c, cred):
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/invitee_no_shows/{_uuid_tail(c.no_show)}", action_name="get_no_show")

    async def _delete_no_show(self, c, cred):
        return await _calendly_request(cred, "DELETE", f"{CALENDLY_API_BASE}/invitee_no_shows/{_uuid_tail(c.no_show)}", action_name="delete_no_show")

    async def _get_organization(self, c, cred):
        org = await self._default_org(cred, c.organization)
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/organizations/{_uuid_tail(org)}", action_name="get_organization")

    async def _list_memberships(self, c, cred):
        params = {"organization": await self._default_org(cred, c.organization), "email": c.email,
                  "count": c.count, "page_token": c.page_token}
        if c.user:
            params["user"] = _as_uri("users", c.user)
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/organization_memberships", params=params, action_name="list_organization_memberships")

    async def _get_membership(self, c, cred):
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/organization_memberships/{_uuid_tail(c.membership)}", action_name="get_organization_membership")

    async def _remove_membership(self, c, cred):
        return await _calendly_request(cred, "DELETE", f"{CALENDLY_API_BASE}/organization_memberships/{_uuid_tail(c.membership)}", action_name="remove_organization_membership")

    async def _list_invitations(self, c, cred):
        org = await self._default_org(cred, c.organization)
        params = {"status": c.status, "email": c.email, "count": c.count, "page_token": c.page_token}
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/organizations/{_uuid_tail(org)}/invitations", params=params, action_name="list_organization_invitations")

    async def _create_invitation(self, c, cred):
        org = await self._default_org(cred, c.organization)
        return await _calendly_request(cred, "POST", f"{CALENDLY_API_BASE}/organizations/{_uuid_tail(org)}/invitations",
                                       json_body={"email": c.email}, action_name="create_organization_invitation")

    async def _revoke_invitation(self, c, cred):
        org = await self._default_org(cred, c.organization)
        url = f"{CALENDLY_API_BASE}/organizations/{_uuid_tail(org)}/invitations/{_uuid_tail(c.invitation)}"
        return await _calendly_request(cred, "DELETE", url, action_name="revoke_organization_invitation")

    async def _create_scheduling_link(self, c, cred):
        body = {"max_event_count": 1, "owner": _as_uri("event_types", c.owner), "owner_type": "EventType"}
        return await _calendly_request(cred, "POST", f"{CALENDLY_API_BASE}/scheduling_links", json_body=body, action_name="create_scheduling_link")

    async def _create_share(self, c, cred):
        body = {"event_type": _as_uri("event_types", c.event_type)}
        overrides = _parse_json(c.body_json, "Overrides JSON")
        if isinstance(overrides, dict):
            body.update(overrides)
        return await _calendly_request(cred, "POST", f"{CALENDLY_API_BASE}/shares", json_body=body, action_name="create_share")

    async def _list_availability_schedules(self, c, cred):
        params = {"user": await self._default_user(cred, c.user)}
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/user_availability_schedules", params=params, action_name="list_user_availability_schedules")

    async def _list_busy_times(self, c, cred):
        params = {"user": await self._default_user(cred, c.user), "start_time": c.start_time, "end_time": c.end_time}
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/user_busy_times", params=params, action_name="list_user_busy_times")

    async def _list_routing_forms(self, c, cred):
        params = {"organization": await self._default_org(cred, c.organization), "count": c.count, "page_token": c.page_token}
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/routing_forms", params=params, action_name="list_routing_forms")

    async def _list_routing_submissions(self, c, cred):
        params = {"form": _as_uri("routing_forms", c.form), "count": c.count, "page_token": c.page_token}
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/routing_form_submissions", params=params, action_name="list_routing_form_submissions")

    async def _list_groups(self, c, cred):
        params = {"organization": await self._default_org(cred, c.organization), "count": c.count, "page_token": c.page_token}
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/groups", params=params, action_name="list_groups")

    async def _list_group_relationships(self, c, cred):
        params = {"count": c.count, "page_token": c.page_token}
        if c.organization:
            params["organization"] = _as_uri("organizations", c.organization)
        if c.owner:
            params["owner"] = c.owner
        if c.group:
            params["group"] = _as_uri("groups", c.group)
        if "organization" not in params and "owner" not in params and "group" not in params:
            params["organization"] = await self._default_org(cred, None)
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/group_relationships", params=params, action_name="list_group_relationships")

    async def _list_activity_log(self, c, cred):
        params = {
            "organization": await self._default_org(cred, c.organization),
            "search_term": c.search_term, "min_occurred_at": c.min_occurred_at,
            "max_occurred_at": c.max_occurred_at, "sort": c.sort, "count": c.count, "page_token": c.page_token,
        }
        return await _calendly_request(cred, "GET", f"{CALENDLY_API_BASE}/activity_log_entries", params=params, action_name="list_activity_log")

    async def _delete_invitee_data(self, c, cred):
        emails = [e.strip() for e in (c.emails or "").split(",") if e.strip()]
        return await _calendly_request(cred, "POST", f"{CALENDLY_API_BASE}/data_compliance/deletion/invitees",
                                       json_body={"emails": emails}, action_name="delete_invitee_data")

    async def _delete_event_data(self, c, cred):
        body = {"start_time": c.start_time, "end_time": c.end_time}
        return await _calendly_request(cred, "POST", f"{CALENDLY_API_BASE}/data_compliance/deletion/events",
                                       json_body=body, action_name="delete_event_data")

    async def _custom_request(self, c, cred):
        path = c.path if c.path.startswith("/") else f"/{c.path}"
        if "://" in path:
            raise ValueError("Path must be relative (no scheme), e.g. /event_types")
        params = _parse_query(c.query_params)
        body = _parse_json(c.body_json, "JSON Body")
        return await _calendly_request(cred, c.method, f"{CALENDLY_API_BASE}{path}", params=params, json_body=body, action_name="custom_request")
