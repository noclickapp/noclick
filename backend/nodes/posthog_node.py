"""
PostHog product-analytics automation node.

PostHog has TWO API surfaces, both handled here:
- Ingestion API (event capture / flag evaluation): host ``{region}.i.posthog.com``,
  auth = the PUBLIC project API key (``phc_...``) sent in the JSON body. POST-only,
  no rate limit. Used by capture / batch / identify / group-identify / flag-eval.
- Private REST API (analytics + management): host ``{region}.posthog.com/api``,
  auth = a PERSONAL API key (``phx_...``) as a Bearer token. Full CRUD across
  feature flags, persons, cohorts, annotations, insights, dashboards, actions,
  surveys, session recordings, experiments, definitions, the HogQL Query API, and
  everything else via a generic passthrough.

Auth is API keys (entered manually), not an OAuth flow — PostHog's OAuth is
CIMD-based and niche; personal + project API keys are the standard integration
path. One credential carries the region/host, both keys, and the numeric project
(team) id.

Trigger: PostHog has no native per-resource webhooks, but its CDP "Hog Function"
webhook destination POSTs a templated body to an external URL when a matching
event fires — the node provisions one pointing at a NoClick webhook URL.

REST paths use ``/api/projects/{project_id}/...``; PostHog is migrating some
resources to ``/api/environments/`` but the projects alias still works for all,
so it is used uniformly here.

Docs: https://posthog.com/docs/api
"""

import json
import logging
import re
import time
from typing import Dict, Any, List, Optional, Literal, Union, Annotated
from urllib.parse import parse_qsl
from pydantic import BaseModel, Field, ConfigDict, Discriminator

import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.core.dynamic_options import load_paginated_options
from nodes.oauth.posthog_oauth import (
    POSTHOG_DEFAULT_SCOPES,
    normalize_posthog_oauth_base_url,
)
from nodes.scopes.posthog import POSTHOG_SCOPES
from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)


# Per-event trigger operations → the exact PostHog event name each fires on
# (the ``id`` in a Hog Function event filter). ``on_custom_event`` is the
# catch-all whose event name comes from its ``event_name`` config field.
_TRIGGER_OP_EVENTS = {
    "on_pageview": "$pageview",
    "on_pageleave": "$pageleave",
    "on_autocapture": "$autocapture",
    "on_rageclick": "$rageclick",
    "on_identify": "$identify",
    "on_group_identify": "$groupidentify",
    "on_set_person_properties": "$set",
    "on_feature_flag_called": "$feature_flag_called",
    "on_survey_shown": "survey shown",
    "on_survey_sent": "survey sent",
    "on_survey_dismissed": "survey dismissed",
    "on_exception": "$exception",
    "on_web_vitals": "$web_vitals",
    "on_screen": "$screen",
}
_TRIGGER_OPS = set(_TRIGGER_OP_EVENTS) | {"on_custom_event"}


def _hosts(region: str, custom_host: Optional[str]) -> tuple:
    """Return (rest_base, ingestion_base) for the configured region.

    US:  https://us.posthog.com/api        + https://us.i.posthog.com
    EU:  https://eu.posthog.com/api        + https://eu.i.posthog.com
    custom/self-hosted: one host for both.
    """
    region = (region or "us").lower()
    if region == "eu":
        return "https://eu.posthog.com", "https://eu.i.posthog.com"
    if region == "custom" and custom_host:
        h = custom_host.rstrip("/")
        if "://" not in h:
            h = f"https://{h}"
        return h, h
    return "https://us.posthog.com", "https://us.i.posthog.com"


# ============================================================================
# Credential Schema
# ============================================================================


_REGION_FIELD = Field(
    "us",
    title="Region",
    description="PostHog Cloud region, or 'custom' for a self-hosted instance",
    json_schema_extra={"x-enum-searchable": True, "enumNames": ["US Cloud", "EU Cloud", "Self-hosted / Custom"]},
)
_HOST_FIELD = Field(
    None,
    title="Custom Host",
    description="Self-hosted base URL (e.g. https://posthog.mycompany.com) — required when Region is 'custom'",
)


class PostHogPersonalApiKeyCredential(BaseModel):
    """PostHog Personal API Key — for the REST / query / management API.

    The personal key (``phx_...``, a Bearer token) authenticates every management
    and analytics operation, and the numeric Project ID scopes the API paths
    (``/api/projects/{id}/...``). This is the credential for everything except raw
    event capture (which uses a Project API Key credential instead).
    """

    credential_type: Literal["posthog_personal_api_key"] = Field(
        "posthog_personal_api_key", json_schema_extra={"ui:hidden": True}
    )
    region: Literal["us", "eu", "custom"] = _REGION_FIELD
    personal_api_key: str = Field(
        ...,
        title="Personal API Key",
        description="Personal API key (phx_...). PostHog → Settings → Personal API keys.",
        json_schema_extra={"ui:widget": "password"},
    )
    project_id: Optional[str] = Field(
        None,
        title="Project ID (optional)",
        description="Numeric project (team) ID. Leave blank to use your default project — it's auto-detected from the API key. Set it only to target a specific project when the key can access several.",
    )
    host: Optional[str] = _HOST_FIELD

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://app.posthog.com/settings/user-api-keys",
            "x-help-text": "Create a Personal API key at Settings → Personal API keys. The Project ID auto-detects from your default project — only set it to target a specific one.",
        }
    )


class PostHogProjectApiKeyCredential(BaseModel):
    """PostHog Project API Key — for event ingestion (capture) only.

    The project key (``phc_...``) is the PUBLIC, write-only key used to capture
    events, identify people, and evaluate flags via the ingestion API. It cannot
    read or manage data — use a Personal API Key credential for that.
    """

    credential_type: Literal["posthog_project_api_key"] = Field(
        "posthog_project_api_key", json_schema_extra={"ui:hidden": True}
    )
    region: Literal["us", "eu", "custom"] = _REGION_FIELD
    project_api_key: str = Field(
        ...,
        title="Project API Key",
        description="Public project API key (phc_...). PostHog → Project Settings → Project API Key.",
        json_schema_extra={"ui:widget": "password"},
    )
    host: Optional[str] = _HOST_FIELD

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://app.posthog.com/settings/project",
            "x-help-text": "Find the Project API Key (phc_...) in Project Settings — it's the write-only key used for event capture.",
        }
    )


class PostHogOAuthCredential(BaseModel):
    """OAuth 2.0 credential for PostHog (authorization_code + PKCE).

    Tokens come from the consent flow, not entered manually. ``base_url`` is the
    region's data-plane host (resolved from userinfo at connect); ``project_id`` is
    the numeric project id. Access tokens (pha_) last ~10h and are auto-refreshed
    via the rotating refresh token (phr_). OAuth covers the REST/query/management
    API; event capture still needs a project API key (use the API-key credential).
    """

    credential_type: Literal["posthog_oauth"] = Field(
        "posthog_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    base_url: Optional[str] = Field(None, title="Base URL", description="Region data-plane host, e.g. https://us.posthog.com")
    project_id: Optional[str] = Field(
        None, title="Project ID",
        description="Numeric project (team) ID. Required for REST ops.",
    )
    email: Optional[str] = Field(None, title="Account Email")
    name: Optional[str] = Field(None, title="Account Name")
    # Access level chosen on PostHog's consent screen. A team-scoped grant 403s
    # on org-level endpoints, so scoped_teams is the authoritative project
    # resolver for such credentials (captured from the token response).
    scoped_teams: Optional[List[int]] = Field(None, json_schema_extra={"ui:hidden": True})
    scoped_organizations: Optional[List[str]] = Field(None, json_schema_extra={"ui:hidden": True})

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "posthog",
            # The authorize route requests exactly this list, so mirror it rather
            # than restating it — an empty literal here made the scope-coverage
            # check unable to see what PostHog actually asks for.
            "x-oauth-scopes": list(POSTHOG_DEFAULT_SCOPES),
            "x-credential-url": "https://posthog.com/docs/api/oauth",
        }
    )


PostHogCredential = Union[PostHogPersonalApiKeyCredential, PostHogProjectApiKeyCredential, PostHogOAuthCredential]


# ============================================================================
# Operation config helpers
# ============================================================================


def _op(op: str, category: str, display: str, keywords: Optional[Any] = None,
        *, creates: Optional[str] = None, id_path: str = "data.id") -> Any:
    extra: Dict[str, Any] = {
        "const": op, "ui:hidden": True, "x-category": category,
        "x-is-trigger": False, "x-display-name": display,
    }
    if keywords:
        extra["x-keywords"] = keywords
    if creates:
        # Marks a resource-creating op for the builder's inline "Create new …"
        # affordance (matched to a dropdown field with the same x-resource-type)
        # + the agent-create auto-extend writeback (x-resource-id-path).
        extra["x-creates-resource"] = True
        extra["x-resource-type"] = creates
        extra["x-resource-id-path"] = id_path
    return Field(op, json_schema_extra=extra, title=display)


def _limit() -> Any:
    return Field(None, title="Limit", description="Max results per page")


def _offset() -> Any:
    return Field(None, title="Offset", description="Offset for pagination")


def _props() -> Any:
    return Field(None, title="Properties (JSON)", description="Event/person properties as a JSON object",
                 json_schema_extra={"ui:widget": "textarea"})


def _body() -> Any:
    return Field(None, title="Body (JSON)", description="Request body as JSON",
                 json_schema_extra={"ui:widget": "textarea"})


def _dyn(field_name: str, placeholder: str, custom_placeholder: str,
         depends_on: Optional[str] = None, resource_type: Optional[str] = None) -> Dict[str, Any]:
    """x-dynamic-options metadata: a searchable dropdown backed by
    ``load_field_options``, with free-text fallback for pasting a raw id.
    ``resource_type`` links the picker to a create op of the same type so the
    builder can offer an inline "Create new …" affordance."""
    opts: Dict[str, Any] = {
        "field_name": field_name, "placeholder": placeholder, "searchable": True,
        "allow_custom": True, "custom_placeholder": custom_placeholder,
    }
    if depends_on:
        opts["depends_on"] = depends_on
    extra: Dict[str, Any] = {"x-dynamic-options": opts}
    if resource_type:
        extra["x-resource-type"] = resource_type
    return extra


def _id(title: str, field_name: str, resource: str, *, required: bool = True,
        description: Optional[str] = None, resource_type: Optional[str] = None) -> Any:
    """A resource-id field rendered as a dynamic dropdown (search + paste-id)."""
    return Field(
        ... if required else None, title=title, description=description,
        json_schema_extra=_dyn(field_name, f"Select a {resource}…", f"Or paste a {resource} id",
                               resource_type=resource_type),
    )


def _date(title: str, description: str, *, required: bool = False) -> Any:
    """ISO 8601 date/time field rendered with the date-picker widget."""
    return Field(
        ... if required else None, title=title, description=description,
        json_schema_extra={"ui:widget": "datetime"},
    )


# ============================================================================
# Ingestion ops
# ============================================================================


class PostHogCaptureConfig(BaseModel):
    """Capture a single event."""
    operation: Literal["capture_event"] = _op("capture_event", "Ingestion", "Capture Event", ["track event", "send event", "log event"])
    event: str = Field(..., title="Event Name", description="Event name, e.g. 'user signed up'")
    distinct_id: str = Field(..., title="Distinct ID", description="The user/entity identifier")
    properties: Optional[str] = _props()
    timestamp: Optional[str] = _date("Timestamp", "Optional event time (defaults to now)")


class PostHogBatchCaptureConfig(BaseModel):
    """Capture a batch of events."""
    operation: Literal["batch_capture"] = _op("batch_capture", "Ingestion", "Batch Capture", ["bulk events", "many events"])
    batch: str = Field(..., title="Batch (JSON array)", description='JSON array of events, each {"event","distinct_id","properties","timestamp"}',
                       json_schema_extra={"ui:widget": "textarea"})
    historical_migration: str = Field("false", title="Historical Migration", json_schema_extra={
        "enum": ["false", "true"], "enumNames": ["No", "Yes"], "x-enum-searchable": True})


class PostHogIdentifyConfig(BaseModel):
    """Identify a person and set their properties ($identify)."""
    operation: Literal["identify"] = _op("identify", "Ingestion", "Identify Person", ["set user properties", "identify user"])
    distinct_id: str = Field(..., title="Distinct ID", description="The user/entity identifier")
    set_properties: Optional[str] = Field(None, title="Set Properties (JSON)", description="Person properties to set ($set)",
                                          json_schema_extra={"ui:widget": "textarea"})
    set_once_properties: Optional[str] = Field(None, title="Set Once Properties (JSON)", description="Person properties to set only if unset ($set_once)",
                                               json_schema_extra={"ui:widget": "textarea"})


class PostHogGroupIdentifyConfig(BaseModel):
    """Set properties on a group ($groupidentify)."""
    operation: Literal["group_identify"] = _op("group_identify", "Ingestion", "Group Identify", ["set group properties"])
    group_type: str = Field(..., title="Group Type", description="e.g. company, organization")
    group_key: str = Field(..., title="Group Key", description="The group's unique key")
    properties: Optional[str] = Field(None, title="Group Properties (JSON)", description='Properties to set on the group, e.g. {"name": "Acme"}', json_schema_extra={"ui:widget": "textarea"})


class PostHogEvaluateFlagsConfig(BaseModel):
    """Evaluate feature flags for a person."""
    operation: Literal["evaluate_flags"] = _op("evaluate_flags", "Ingestion", "Evaluate Feature Flags", ["decide", "check flags"])
    distinct_id: str = Field(..., title="Distinct ID", description="The user/entity identifier")
    groups: Optional[str] = Field(None, title="Groups (JSON)", description='e.g. {"company":"acme"}', json_schema_extra={"ui:widget": "textarea"})
    person_properties: Optional[str] = Field(None, title="Person Properties (JSON)", description='Property overrides for flag evaluation, e.g. {"plan": "pro"}', json_schema_extra={"ui:widget": "textarea"})


# ============================================================================
# Query API
# ============================================================================


class PostHogRunQueryConfig(BaseModel):
    """Run a HogQL / structured query via the Query API (the universal read primitive)."""
    operation: Literal["run_query"] = _op("run_query", "Query", "Run Query (HogQL)", ["sql", "hogql", "analytics query", "trends", "funnel"])
    hogql: Optional[str] = Field(None, title="HogQL", description="Raw HogQL, e.g. SELECT event, count() FROM events GROUP BY event",
                                 json_schema_extra={"ui:widget": "textarea"})
    query_json: Optional[str] = Field(None, title="Query JSON", description="Full structured query node (overrides HogQL), e.g. a TrendsQuery",
                                      json_schema_extra={"ui:widget": "textarea"})


class PostHogListEventsConfig(BaseModel):
    """List recent events."""
    operation: Literal["list_events"] = _op("list_events", "Events", "List Events", ["recent events", "event stream"])
    event: Optional[str] = Field(None, title="Event Name Filter", description="Only this event, e.g. 'user signed up'")
    distinct_id: Optional[str] = Field(None, title="Distinct ID Filter", description="Only events from this user/entity")
    after: Optional[str] = _date("After", "Only events at or after this time")
    before: Optional[str] = _date("Before", "Only events at or before this time")
    limit: Optional[str] = _limit()


# ============================================================================
# Generic CRUD helper configs (per resource)
# ============================================================================


class PostHogListFeatureFlagsConfig(BaseModel):
    operation: Literal["list_feature_flags"] = _op("list_feature_flags", "Feature Flags", "List Feature Flags", ["flags"])
    limit: Optional[str] = _limit(); offset: Optional[str] = _offset()


class PostHogGetFeatureFlagConfig(BaseModel):
    operation: Literal["get_feature_flag"] = _op("get_feature_flag", "Feature Flags", "Get Feature Flag")
    flag_id: str = _id("Feature Flag", "flag_id", "feature flag", resource_type="posthog_feature_flag")


class PostHogCreateFeatureFlagConfig(BaseModel):
    operation: Literal["create_feature_flag"] = _op("create_feature_flag", "Feature Flags", "Create Feature Flag", ["new flag"], creates="posthog_feature_flag")
    key: str = Field(..., title="Key", description="Flag key")
    name: Optional[str] = Field(None, title="Name", description="Human-readable flag name")
    active: str = Field("true", title="Active", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Active", "Inactive"], "x-enum-searchable": True})
    filters_json: Optional[str] = Field(None, title="Filters (JSON)", description="Release-condition filters as JSON", json_schema_extra={"ui:widget": "textarea"})


class PostHogUpdateFeatureFlagConfig(BaseModel):
    operation: Literal["update_feature_flag"] = _op("update_feature_flag", "Feature Flags", "Update Feature Flag")
    flag_id: str = _id("Feature Flag", "flag_id", "feature flag", resource_type="posthog_feature_flag")
    body_json: str = Field(..., title="Fields (JSON)", description="Fields to update as JSON, e.g. {\"active\": false}", json_schema_extra={"ui:widget": "textarea"})


class PostHogDeleteFeatureFlagConfig(BaseModel):
    operation: Literal["delete_feature_flag"] = _op("delete_feature_flag", "Feature Flags", "Delete Feature Flag")
    flag_id: str = _id("Feature Flag", "flag_id", "feature flag", resource_type="posthog_feature_flag")


class PostHogListPersonsConfig(BaseModel):
    operation: Literal["list_persons"] = _op("list_persons", "Persons", "List Persons", ["users", "people"])
    search: Optional[str] = Field(None, title="Search", description="Search by distinct id / email / name")
    limit: Optional[str] = _limit(); offset: Optional[str] = _offset()


class PostHogGetPersonConfig(BaseModel):
    operation: Literal["get_person"] = _op("get_person", "Persons", "Get Person")
    person_id: str = _id("Person", "person_id", "person")


class PostHogUpdatePersonConfig(BaseModel):
    operation: Literal["update_person"] = _op("update_person", "Persons", "Update Person")
    person_id: str = _id("Person", "person_id", "person")
    properties: str = Field(..., title="Properties (JSON)", description="Properties to set", json_schema_extra={"ui:widget": "textarea"})


class PostHogDeletePersonConfig(BaseModel):
    operation: Literal["delete_person"] = _op("delete_person", "Persons", "Delete Person", ["gdpr delete user"])
    person_id: str = _id("Person", "person_id", "person")


class PostHogListCohortsConfig(BaseModel):
    operation: Literal["list_cohorts"] = _op("list_cohorts", "Cohorts", "List Cohorts")
    limit: Optional[str] = _limit(); offset: Optional[str] = _offset()


class PostHogGetCohortConfig(BaseModel):
    operation: Literal["get_cohort"] = _op("get_cohort", "Cohorts", "Get Cohort")
    cohort_id: str = _id("Cohort", "cohort_id", "cohort", resource_type="posthog_cohort")


class PostHogCreateCohortConfig(BaseModel):
    operation: Literal["create_cohort"] = _op("create_cohort", "Cohorts", "Create Cohort", creates="posthog_cohort")
    name: str = Field(..., title="Name", description="A descriptive name")
    body_json: Optional[str] = Field(None, title="Definition (JSON)", description="Cohort groups/filters as JSON", json_schema_extra={"ui:widget": "textarea"})


class PostHogUpdateCohortConfig(BaseModel):
    operation: Literal["update_cohort"] = _op("update_cohort", "Cohorts", "Update Cohort")
    cohort_id: str = _id("Cohort", "cohort_id", "cohort", resource_type="posthog_cohort")
    body_json: str = Field(..., title="Fields (JSON)", description='Fields to change, e.g. {"name": "New name"}', json_schema_extra={"ui:widget": "textarea"})


class PostHogDeleteCohortConfig(BaseModel):
    operation: Literal["delete_cohort"] = _op("delete_cohort", "Cohorts", "Delete Cohort")
    cohort_id: str = _id("Cohort", "cohort_id", "cohort", resource_type="posthog_cohort")


class PostHogListCohortPersonsConfig(BaseModel):
    operation: Literal["list_cohort_persons"] = _op("list_cohort_persons", "Cohorts", "List Cohort Persons")
    cohort_id: str = _id("Cohort", "cohort_id", "cohort", resource_type="posthog_cohort")
    limit: Optional[str] = _limit()


class PostHogListAnnotationsConfig(BaseModel):
    operation: Literal["list_annotations"] = _op("list_annotations", "Annotations", "List Annotations")
    limit: Optional[str] = _limit(); offset: Optional[str] = _offset()


class PostHogCreateAnnotationConfig(BaseModel):
    operation: Literal["create_annotation"] = _op("create_annotation", "Annotations", "Create Annotation", ["mark deploy", "add note"], creates="posthog_annotation")
    content: str = Field(..., title="Content", description="The annotation text, e.g. 'Deployed v2.1'")
    date_marker: Optional[str] = _date("Date", "The moment this annotation marks (defaults to now)")


class PostHogUpdateAnnotationConfig(BaseModel):
    operation: Literal["update_annotation"] = _op("update_annotation", "Annotations", "Update Annotation")
    annotation_id: str = _id("Annotation", "annotation_id", "annotation", resource_type="posthog_annotation")
    body_json: str = Field(..., title="Fields (JSON)", description='Fields to change, e.g. {"name": "New name"}', json_schema_extra={"ui:widget": "textarea"})


class PostHogDeleteAnnotationConfig(BaseModel):
    operation: Literal["delete_annotation"] = _op("delete_annotation", "Annotations", "Delete Annotation")
    annotation_id: str = _id("Annotation", "annotation_id", "annotation", resource_type="posthog_annotation")


class PostHogListInsightsConfig(BaseModel):
    operation: Literal["list_insights"] = _op("list_insights", "Insights", "List Insights")
    limit: Optional[str] = _limit(); offset: Optional[str] = _offset()


class PostHogGetInsightConfig(BaseModel):
    operation: Literal["get_insight"] = _op("get_insight", "Insights", "Get Insight")
    insight_id: str = _id("Insight", "insight_id", "insight", resource_type="posthog_insight")


class PostHogCreateInsightConfig(BaseModel):
    operation: Literal["create_insight"] = _op("create_insight", "Insights", "Create Insight", creates="posthog_insight")
    name: str = Field(..., title="Name", description="A descriptive name")
    body_json: str = Field(..., title="Query/Filters (JSON)", description="Insight query or filters as JSON", json_schema_extra={"ui:widget": "textarea"})


class PostHogDeleteInsightConfig(BaseModel):
    operation: Literal["delete_insight"] = _op("delete_insight", "Insights", "Delete Insight")
    insight_id: str = _id("Insight", "insight_id", "insight", resource_type="posthog_insight")


class PostHogListDashboardsConfig(BaseModel):
    operation: Literal["list_dashboards"] = _op("list_dashboards", "Dashboards", "List Dashboards")
    limit: Optional[str] = _limit(); offset: Optional[str] = _offset()


class PostHogGetDashboardConfig(BaseModel):
    operation: Literal["get_dashboard"] = _op("get_dashboard", "Dashboards", "Get Dashboard")
    dashboard_id: str = _id("Dashboard", "dashboard_id", "dashboard", resource_type="posthog_dashboard")


class PostHogCreateDashboardConfig(BaseModel):
    operation: Literal["create_dashboard"] = _op("create_dashboard", "Dashboards", "Create Dashboard", creates="posthog_dashboard")
    name: str = Field(..., title="Name", description="A descriptive name")
    description: Optional[str] = Field(None, title="Description", description="Optional description")


class PostHogDeleteDashboardConfig(BaseModel):
    operation: Literal["delete_dashboard"] = _op("delete_dashboard", "Dashboards", "Delete Dashboard")
    dashboard_id: str = _id("Dashboard", "dashboard_id", "dashboard", resource_type="posthog_dashboard")


class PostHogListActionsConfig(BaseModel):
    operation: Literal["list_actions"] = _op("list_actions", "Actions", "List Actions")
    limit: Optional[str] = _limit()


class PostHogGetActionConfig(BaseModel):
    operation: Literal["get_action"] = _op("get_action", "Actions", "Get Action")
    action_id: str = _id("Action", "action_id", "action", resource_type="posthog_action")


class PostHogCreateActionConfig(BaseModel):
    operation: Literal["create_action"] = _op("create_action", "Actions", "Create Action", creates="posthog_action")
    name: str = Field(..., title="Name", description="A descriptive name")
    body_json: Optional[str] = Field(None, title="Steps (JSON)", description="Action steps as JSON", json_schema_extra={"ui:widget": "textarea"})


class PostHogListSurveysConfig(BaseModel):
    operation: Literal["list_surveys"] = _op("list_surveys", "Surveys", "List Surveys")
    limit: Optional[str] = _limit()


class PostHogGetSurveyConfig(BaseModel):
    operation: Literal["get_survey"] = _op("get_survey", "Surveys", "Get Survey")
    survey_id: str = _id("Survey", "survey_id", "survey", resource_type="posthog_survey")


class PostHogListRecordingsConfig(BaseModel):
    operation: Literal["list_session_recordings"] = _op("list_session_recordings", "Session Replay", "List Session Recordings", ["replays", "recordings"])
    limit: Optional[str] = _limit()


class PostHogGetRecordingConfig(BaseModel):
    operation: Literal["get_session_recording"] = _op("get_session_recording", "Session Replay", "Get Session Recording")
    recording_id: str = Field(..., title="Recording ID", description="The session recording id")


class PostHogDeleteRecordingConfig(BaseModel):
    operation: Literal["delete_session_recording"] = _op("delete_session_recording", "Session Replay", "Delete Session Recording")
    recording_id: str = Field(..., title="Recording ID", description="The session recording id")


class PostHogListExperimentsConfig(BaseModel):
    operation: Literal["list_experiments"] = _op("list_experiments", "Experiments", "List Experiments", ["ab tests"])
    limit: Optional[str] = _limit()


class PostHogGetExperimentConfig(BaseModel):
    operation: Literal["get_experiment"] = _op("get_experiment", "Experiments", "Get Experiment")
    experiment_id: str = _id("Experiment", "experiment_id", "experiment", resource_type="posthog_experiment")


class PostHogListEventDefinitionsConfig(BaseModel):
    operation: Literal["list_event_definitions"] = _op("list_event_definitions", "Definitions", "List Event Definitions")
    search: Optional[str] = Field(None, title="Search", description="Filter event names by substring"); limit: Optional[str] = _limit()


class PostHogListPropertyDefinitionsConfig(BaseModel):
    operation: Literal["list_property_definitions"] = _op("list_property_definitions", "Definitions", "List Property Definitions")
    search: Optional[str] = Field(None, title="Search", description="Filter property names by substring"); limit: Optional[str] = _limit()


# ---- Insights / Dashboards updates ----
class PostHogUpdateInsightConfig(BaseModel):
    operation: Literal["update_insight"] = _op("update_insight", "Insights", "Update Insight")
    insight_id: str = _id("Insight", "insight_id", "insight", resource_type="posthog_insight")
    body_json: str = Field(..., title="Fields (JSON)", description='Fields to change, e.g. {"name": "New name"}', json_schema_extra={"ui:widget": "textarea"})


class PostHogUpdateDashboardConfig(BaseModel):
    operation: Literal["update_dashboard"] = _op("update_dashboard", "Dashboards", "Update Dashboard")
    dashboard_id: str = _id("Dashboard", "dashboard_id", "dashboard", resource_type="posthog_dashboard")
    body_json: str = Field(..., title="Fields (JSON)", description='Fields to change, e.g. {"name": "New name"}', json_schema_extra={"ui:widget": "textarea"})


# ---- Feature flag evaluation helpers ----
class PostHogFlagLocalEvaluationConfig(BaseModel):
    operation: Literal["feature_flag_local_evaluation"] = _op("feature_flag_local_evaluation", "Feature Flags", "Get Local Evaluation Payload", ["flag definitions"])
    project_token: Optional[str] = Field(
        None, title="Project API Key (phc_)",
        description="Required by this endpoint unless the credential is a phs_-prefixed key. Uses the credential's project key automatically when available.",
        json_schema_extra={"ui:widget": "password"},
    )


class PostHogMyFlagsConfig(BaseModel):
    operation: Literal["list_my_feature_flags"] = _op("list_my_feature_flags", "Feature Flags", "List My Feature Flags")


# ---- Persons merge / split / bulk ----
class PostHogSplitPersonConfig(BaseModel):
    operation: Literal["split_person"] = _op("split_person", "Persons", "Split Person")
    person_id: str = _id("Person", "person_id", "person")
    main_distinct_id: Optional[str] = Field(None, title="Main Distinct ID", description="Distinct id to keep as the primary person")


class PostHogBulkDeletePersonsConfig(BaseModel):
    operation: Literal["bulk_delete_persons"] = _op("bulk_delete_persons", "Persons", "Bulk Delete Persons", ["gdpr bulk delete"])
    ids_json: Optional[str] = Field(None, title="Person IDs (JSON array)", description='Person UUIDs to delete, e.g. ["018f…","018a…"]', json_schema_extra={"ui:widget": "textarea"})
    distinct_ids_json: Optional[str] = Field(None, title="Distinct IDs (JSON array)", description='Distinct ids to delete, e.g. ["user_1","user_2"]', json_schema_extra={"ui:widget": "textarea"})


# ---- Experiments lifecycle ----
class PostHogCreateExperimentConfig(BaseModel):
    operation: Literal["create_experiment"] = _op("create_experiment", "Experiments", "Create Experiment", ["ab test"], creates="posthog_experiment")
    name: str = Field(..., title="Name", description="A descriptive name")
    feature_flag_key: str = Field(
        ..., title="Feature Flag Key",
        json_schema_extra=_dyn("feature_flag_key", "Select a feature flag…", "Or paste a flag key", resource_type="posthog_feature_flag"),
    )
    body_json: Optional[str] = Field(None, title="Config (JSON)", description="Extra experiment config as JSON", json_schema_extra={"ui:widget": "textarea"})


class PostHogUpdateExperimentConfig(BaseModel):
    operation: Literal["update_experiment"] = _op("update_experiment", "Experiments", "Update Experiment")
    experiment_id: str = _id("Experiment", "experiment_id", "experiment", resource_type="posthog_experiment")
    body_json: str = Field(..., title="Fields (JSON)", description='Fields to change, e.g. {"name": "New name"}', json_schema_extra={"ui:widget": "textarea"})


class PostHogExperimentActionConfig(BaseModel):
    operation: Literal["experiment_action"] = _op("experiment_action", "Experiments", "Experiment Action", ["launch", "pause", "resume", "end", "archive"])
    experiment_id: str = _id("Experiment", "experiment_id", "experiment", resource_type="posthog_experiment")
    action: Literal["launch", "pause", "resume", "end", "archive", "reset", "duplicate"] = Field(
        "launch", title="Action", json_schema_extra={"x-enum-searchable": True})


# ---- Surveys lifecycle ----
class PostHogCreateSurveyConfig(BaseModel):
    operation: Literal["create_survey"] = _op("create_survey", "Surveys", "Create Survey", creates="posthog_survey")
    name: str = Field(..., title="Name", description="A descriptive name")
    body_json: Optional[str] = Field(None, title="Config (JSON)", description="Survey type/questions as JSON", json_schema_extra={"ui:widget": "textarea"})


class PostHogUpdateSurveyConfig(BaseModel):
    operation: Literal["update_survey"] = _op("update_survey", "Surveys", "Update Survey")
    survey_id: str = _id("Survey", "survey_id", "survey", resource_type="posthog_survey")
    body_json: str = Field(..., title="Fields (JSON)", description='Fields to change, e.g. {"name": "New name"}', json_schema_extra={"ui:widget": "textarea"})


class PostHogSurveyActionConfig(BaseModel):
    operation: Literal["survey_action"] = _op("survey_action", "Surveys", "Survey Action", ["launch", "stop"])
    survey_id: str = _id("Survey", "survey_id", "survey", resource_type="posthog_survey")
    action: Literal["launch", "stop"] = Field("launch", title="Action", json_schema_extra={"x-enum-searchable": True})


class PostHogSurveyResponsesConfig(BaseModel):
    operation: Literal["get_survey_responses"] = _op("get_survey_responses", "Surveys", "Get Survey Responses")
    survey_id: str = _id("Survey", "survey_id", "survey", resource_type="posthog_survey")


class PostHogSurveyStatsConfig(BaseModel):
    operation: Literal["get_survey_stats"] = _op("get_survey_stats", "Surveys", "Get Survey Stats")
    survey_id: str = _id("Survey", "survey_id", "survey", resource_type="posthog_survey")


# ---- Groups ----
class PostHogListGroupTypesConfig(BaseModel):
    operation: Literal["list_group_types"] = _op("list_group_types", "Groups", "List Group Types")


class PostHogListGroupsConfig(BaseModel):
    operation: Literal["list_groups"] = _op("list_groups", "Groups", "List Groups")
    group_type_index: str = Field(
        ..., title="Group Type", description="0-based index of the group type",
        json_schema_extra=_dyn("group_type_index", "Select a group type…", "Or paste a group type index"),
    )
    search: Optional[str] = Field(None, title="Search", description="Filter by group key"); limit: Optional[str] = _limit()


class PostHogFindGroupConfig(BaseModel):
    operation: Literal["find_group"] = _op("find_group", "Groups", "Find Group")
    group_type_index: str = Field(
        ..., title="Group Type",
        json_schema_extra=_dyn("group_type_index", "Select a group type…", "Or paste a group type index"),
    )
    group_key: str = Field(..., title="Group Key", description="The group's unique key, e.g. acme-inc")


# ---- Cohort membership (static) ----
class PostHogAddPersonsToCohortConfig(BaseModel):
    operation: Literal["add_persons_to_cohort"] = _op("add_persons_to_cohort", "Cohorts", "Add Persons to Static Cohort")
    cohort_id: str = _id("Cohort", "cohort_id", "cohort", resource_type="posthog_cohort")
    body_json: str = Field(..., title="Persons (JSON)", description='e.g. {"person_ids":["<person uuid>", …]}', json_schema_extra={"ui:widget": "textarea"})


# ---- Notebooks ----
class PostHogListNotebooksConfig(BaseModel):
    operation: Literal["list_notebooks"] = _op("list_notebooks", "Notebooks", "List Notebooks")
    limit: Optional[str] = _limit()


class PostHogGetNotebookConfig(BaseModel):
    operation: Literal["get_notebook"] = _op("get_notebook", "Notebooks", "Get Notebook")
    notebook_id: str = _id("Notebook", "notebook_id", "notebook", resource_type="posthog_notebook")


class PostHogCreateNotebookConfig(BaseModel):
    operation: Literal["create_notebook"] = _op("create_notebook", "Notebooks", "Create Notebook", creates="posthog_notebook", id_path="data.short_id")
    title: Optional[str] = Field(None, title="Title", description="Notebook title")
    content_json: Optional[str] = Field(None, title="Content (JSON)", description="Notebook content as a ProseMirror JSON doc", json_schema_extra={"ui:widget": "textarea"})


# ---- Early access features ----
class PostHogListEarlyAccessConfig(BaseModel):
    operation: Literal["list_early_access_features"] = _op("list_early_access_features", "Early Access", "List Early Access Features")
    limit: Optional[str] = _limit()


class PostHogCreateEarlyAccessConfig(BaseModel):
    operation: Literal["create_early_access_feature"] = _op("create_early_access_feature", "Early Access", "Create Early Access Feature")
    name: str = Field(..., title="Name", description="A descriptive name")
    stage: Literal["draft", "concept", "alpha", "beta", "general-availability"] = Field(
        "concept", title="Stage", json_schema_extra={"x-enum-searchable": True})
    description: Optional[str] = Field(None, title="Description", description="Optional description")
    body_json: Optional[str] = Field(None, title="Extra Config (JSON)", description="Additional fields as JSON (optional)", json_schema_extra={"ui:widget": "textarea"})


# ---- Batch exports ----
class PostHogListBatchExportsConfig(BaseModel):
    operation: Literal["list_batch_exports"] = _op("list_batch_exports", "Batch Exports", "List Batch Exports")
    limit: Optional[str] = _limit()


class PostHogGetBatchExportConfig(BaseModel):
    operation: Literal["get_batch_export"] = _op("get_batch_export", "Batch Exports", "Get Batch Export")
    batch_export_id: str = _id("Batch Export", "batch_export_id", "batch export")


# ---- Destinations (CDP / hog functions) ----
def _destination_id(desc: str = "The destination (hog function)") -> Any:
    return Field(..., title="Destination", description=desc,
                 json_schema_extra=_dyn("destination_id", "Select a destination…", "Or paste a destination id", resource_type="posthog_destination"))


class PostHogListDestinationsConfig(BaseModel):
    operation: Literal["list_destinations"] = _op("list_destinations", "Destinations", "List Destinations", ["cdp", "hog functions", "exports"])
    hog_type: Optional[str] = Field(None, title="Type", description="Filter by kind (blank = destinations)", json_schema_extra={
        "enum": ["", "destination", "transformation", "site_destination"], "x-enum-searchable": True})
    search: Optional[str] = Field(None, title="Search", description="Filter by name (optional)")
    limit: Optional[str] = _limit()


class PostHogGetDestinationConfig(BaseModel):
    operation: Literal["get_destination"] = _op("get_destination", "Destinations", "Get Destination")
    destination_id: str = _destination_id()


class PostHogCreateDestinationConfig(BaseModel):
    operation: Literal["create_destination"] = _op("create_destination", "Destinations", "Create Destination", ["new export", "connect slack", "send events to"], creates="posthog_destination")
    template_id: str = Field(
        ..., title="Template", description="The destination kind (Slack, Webhook, HubSpot, …)",
        json_schema_extra=_dyn("template_id", "Select a destination template…", "Or paste a template id"))
    name: str = Field(..., title="Name", description="A descriptive name")
    inputs_json: str = Field(
        ..., title="Inputs (JSON)",
        description='The template\'s inputs, e.g. {"url":"https://…","method":"POST"} — plain values are wrapped into PostHog\'s {"value": …} shape automatically',
        json_schema_extra={"ui:widget": "textarea"})
    filters_json: Optional[str] = Field(
        None, title="Event Filters (JSON)",
        description='Optional, e.g. {"events":[{"id":"$pageview","type":"events"}]} — blank fires on all events',
        json_schema_extra={"ui:widget": "textarea"})
    enabled: str = Field("true", title="Enabled", description="Start the destination immediately", json_schema_extra={
        "enum": ["true", "false"], "enumNames": ["Enabled", "Disabled"], "x-enum-searchable": True})


class PostHogUpdateDestinationConfig(BaseModel):
    operation: Literal["update_destination"] = _op("update_destination", "Destinations", "Update Destination")
    destination_id: str = _destination_id()
    body_json: str = Field(..., title="Fields (JSON)", description='Fields to change, e.g. {"name":"New","inputs":{…},"filters":{…}}', json_schema_extra={"ui:widget": "textarea"})


class PostHogSetDestinationEnabledConfig(BaseModel):
    operation: Literal["set_destination_enabled"] = _op("set_destination_enabled", "Destinations", "Enable/Disable Destination", ["pause destination", "resume destination"])
    destination_id: str = _destination_id()
    enabled: str = Field(..., title="State", json_schema_extra={
        "enum": ["true", "false"], "enumNames": ["Enabled", "Disabled"], "x-enum-searchable": True})


class PostHogDeleteDestinationConfig(BaseModel):
    operation: Literal["delete_destination"] = _op("delete_destination", "Destinations", "Delete Destination")
    destination_id: str = _destination_id()


class PostHogListDestinationTemplatesConfig(BaseModel):
    operation: Literal["list_destination_templates"] = _op("list_destination_templates", "Destinations", "List Destination Templates", ["catalog", "available destinations"])
    search: Optional[str] = Field(None, title="Search", description="Filter templates by name (optional)")
    limit: Optional[str] = _limit()


class PostHogDestinationLogsConfig(BaseModel):
    operation: Literal["get_destination_logs"] = _op("get_destination_logs", "Destinations", "Get Destination Logs", ["delivery logs", "why failing"])
    destination_id: str = _destination_id("The destination whose delivery logs to read")
    level: Optional[str] = Field(None, title="Level", description="Only entries at this level (optional)", json_schema_extra={
        "enum": ["", "DEBUG", "LOG", "INFO", "WARN", "ERROR"], "x-enum-searchable": True})
    search: Optional[str] = Field(None, title="Search", description="Filter log messages (optional)")
    limit: Optional[str] = _limit()


class PostHogDestinationMetricsConfig(BaseModel):
    operation: Literal["get_destination_metrics"] = _op("get_destination_metrics", "Destinations", "Get Destination Metrics", ["succeeded failed counts", "delivery health"])
    destination_id: str = _destination_id("The destination whose delivery totals to read")
    after: Optional[str] = Field(None, title="Since", description="Window, e.g. -24h or -7d (default -7d)")


# ---- Activity log ----
class PostHogActivityLogConfig(BaseModel):
    operation: Literal["list_activity_log"] = _op("list_activity_log", "Advanced", "List Activity Log")
    limit: Optional[str] = _limit()


# ---- Organization ----
class PostHogListOrgMembersConfig(BaseModel):
    operation: Literal["list_org_members"] = _op("list_org_members", "Organization", "List Org Members")
    limit: Optional[str] = _limit()


class PostHogListOrgInvitesConfig(BaseModel):
    operation: Literal["list_org_invites"] = _op("list_org_invites", "Organization", "List Org Invites")


class PostHogCreateOrgInviteConfig(BaseModel):
    operation: Literal["create_org_invite"] = _op("create_org_invite", "Organization", "Invite Org Member")
    target_email: str = Field(..., title="Email", description="Email address to invite, e.g. teammate@company.com")
    level: Optional[str] = Field(None, title="Level", description="Membership level (e.g. 1=member, 8=admin)")


class PostHogListProjectsConfig(BaseModel):
    operation: Literal["list_projects"] = _op("list_projects", "Organization", "List Projects")


class PostHogListRolesConfig(BaseModel):
    operation: Literal["list_roles"] = _op("list_roles", "Organization", "List Roles")


class PostHogRawRequestConfig(BaseModel):
    """Call any authenticated PostHog REST endpoint (covers the huge long tail)."""
    operation: Literal["raw_request"] = _op("raw_request", "Advanced", "Custom Request")
    method: Literal["GET", "POST", "PATCH", "PUT", "DELETE"] = Field("GET", title="Method")
    path: str = Field(..., title="Path", description="Path after the host, e.g. /api/projects/{id}/hog_functions/. {project_id} is substituted.")
    query_params: Optional[str] = Field(None, title="Query Parameters", description="e.g. limit=100&offset=0")
    body_json: Optional[str] = _body()


# ============================================================================
# Trigger (Hog Function webhook destination)
# ============================================================================


def _trigger_op(op: str, display: str, keywords: Any) -> Any:
    return Field(op, title=display, json_schema_extra={
        "const": op, "ui:hidden": True, "x-is-trigger": True,
        "x-category": "Triggers", "x-display-name": display, "x-keywords": keywords,
    })


def _webhook_url() -> Any:
    return Field(default=None, title="Webhook URL",
                 json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


# Each trigger fires on one PostHog event (via a Hog Function webhook
# destination provisioned by this node). The event is fixed per operation
# (see ``_TRIGGER_OP_EVENTS``) — no event-name field needed — except the
# catch-all ``on_custom_event`` below.
class _PostHogTriggerBase(WebhookTriggerConfigBase):
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    webhook_url: Optional[str] = _webhook_url()


class PostHogOnPageviewConfig(_PostHogTriggerBase):
    """Fires on every pageview ($pageview)."""
    operation: Literal["on_pageview"] = _trigger_op("on_pageview", "On Pageview", ["$pageview", "page view", "page visit"])


class PostHogOnPageleaveConfig(_PostHogTriggerBase):
    """Fires when a user leaves a page ($pageleave)."""
    operation: Literal["on_pageleave"] = _trigger_op("on_pageleave", "On Page Leave", ["$pageleave", "page exit"])


class PostHogOnAutocaptureConfig(_PostHogTriggerBase):
    """Fires on any autocaptured interaction ($autocapture)."""
    operation: Literal["on_autocapture"] = _trigger_op("on_autocapture", "On Autocapture", ["$autocapture", "click", "interaction"])


class PostHogOnRageclickConfig(_PostHogTriggerBase):
    """Fires when PostHog detects a rageclick ($rageclick)."""
    operation: Literal["on_rageclick"] = _trigger_op("on_rageclick", "On Rageclick", ["$rageclick", "frustration"])


class PostHogOnIdentifyConfig(_PostHogTriggerBase):
    """Fires when a person is identified ($identify)."""
    operation: Literal["on_identify"] = _trigger_op("on_identify", "On Identify", ["$identify", "user identified", "new user"])


class PostHogOnGroupIdentifyConfig(_PostHogTriggerBase):
    """Fires when a group is identified ($groupidentify)."""
    operation: Literal["on_group_identify"] = _trigger_op("on_group_identify", "On Group Identify", ["$groupidentify", "group updated"])


class PostHogOnSetPersonPropsConfig(_PostHogTriggerBase):
    """Fires when person properties are set ($set)."""
    operation: Literal["on_set_person_properties"] = _trigger_op("on_set_person_properties", "On Set Person Properties", ["$set", "person property changed"])


class PostHogOnFeatureFlagCalledConfig(_PostHogTriggerBase):
    """Fires when a feature flag is evaluated ($feature_flag_called)."""
    operation: Literal["on_feature_flag_called"] = _trigger_op("on_feature_flag_called", "On Feature Flag Called", ["$feature_flag_called", "flag evaluated"])


class PostHogOnSurveyShownConfig(_PostHogTriggerBase):
    """Fires when a survey is shown to a user (survey shown)."""
    operation: Literal["on_survey_shown"] = _trigger_op("on_survey_shown", "On Survey Shown", ["survey shown", "survey displayed"])


class PostHogOnSurveySentConfig(_PostHogTriggerBase):
    """Fires when a survey response is submitted (survey sent)."""
    operation: Literal["on_survey_sent"] = _trigger_op("on_survey_sent", "On Survey Response", ["survey sent", "survey submitted", "survey response"])


class PostHogOnSurveyDismissedConfig(_PostHogTriggerBase):
    """Fires when a survey is dismissed (survey dismissed)."""
    operation: Literal["on_survey_dismissed"] = _trigger_op("on_survey_dismissed", "On Survey Dismissed", ["survey dismissed", "survey closed"])


class PostHogOnExceptionConfig(_PostHogTriggerBase):
    """Fires when an exception/error is captured ($exception)."""
    operation: Literal["on_exception"] = _trigger_op("on_exception", "On Exception", ["$exception", "error tracking", "crash"])


class PostHogOnWebVitalsConfig(_PostHogTriggerBase):
    """Fires on a web-vitals measurement ($web_vitals)."""
    operation: Literal["on_web_vitals"] = _trigger_op("on_web_vitals", "On Web Vitals", ["$web_vitals", "performance", "core web vitals"])


class PostHogOnScreenConfig(_PostHogTriggerBase):
    """Fires on a mobile screen view ($screen)."""
    operation: Literal["on_screen"] = _trigger_op("on_screen", "On Screen View (Mobile)", ["$screen", "mobile screen"])


class PostHogOnCustomEventConfig(_PostHogTriggerBase):
    """Fires on a custom event you name (or every event with '*')."""
    operation: Literal["on_custom_event"] = _trigger_op("on_custom_event", "On Custom Event", ["when event", "on track", "custom event", "event ingested"])
    event_name: str = Field(
        ..., title="Event Name",
        description="The event to fire on. Pick one of your project's events, or type a new name (use '*' for all events).",
        json_schema_extra=_dyn("event_name", "Select an event…", "Or type an event name / *"),
    )
    # Mirror of the event the provider-side filter was registered with —
    # webhook_registration_stale compares it to event_name to detect edits.
    registered_event_name: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


_TRIGGER_CONFIGS = (
    PostHogOnPageviewConfig, PostHogOnPageleaveConfig, PostHogOnAutocaptureConfig, PostHogOnRageclickConfig,
    PostHogOnIdentifyConfig, PostHogOnGroupIdentifyConfig, PostHogOnSetPersonPropsConfig,
    PostHogOnFeatureFlagCalledConfig, PostHogOnSurveyShownConfig, PostHogOnSurveySentConfig,
    PostHogOnSurveyDismissedConfig, PostHogOnExceptionConfig, PostHogOnWebVitalsConfig, PostHogOnScreenConfig,
    PostHogOnCustomEventConfig,
)


# ============================================================================
# Discriminated union
# ============================================================================

_ACTION_CONFIGS = (
    PostHogCaptureConfig, PostHogBatchCaptureConfig, PostHogIdentifyConfig, PostHogGroupIdentifyConfig,
    PostHogEvaluateFlagsConfig, PostHogRunQueryConfig, PostHogListEventsConfig,
    PostHogListFeatureFlagsConfig, PostHogGetFeatureFlagConfig, PostHogCreateFeatureFlagConfig,
    PostHogUpdateFeatureFlagConfig, PostHogDeleteFeatureFlagConfig,
    PostHogListPersonsConfig, PostHogGetPersonConfig, PostHogUpdatePersonConfig, PostHogDeletePersonConfig,
    PostHogListCohortsConfig, PostHogGetCohortConfig, PostHogCreateCohortConfig, PostHogUpdateCohortConfig,
    PostHogDeleteCohortConfig, PostHogListCohortPersonsConfig,
    PostHogListAnnotationsConfig, PostHogCreateAnnotationConfig, PostHogUpdateAnnotationConfig, PostHogDeleteAnnotationConfig,
    PostHogListInsightsConfig, PostHogGetInsightConfig, PostHogCreateInsightConfig, PostHogDeleteInsightConfig,
    PostHogListDashboardsConfig, PostHogGetDashboardConfig, PostHogCreateDashboardConfig, PostHogDeleteDashboardConfig,
    PostHogListActionsConfig, PostHogGetActionConfig, PostHogCreateActionConfig,
    PostHogListSurveysConfig, PostHogGetSurveyConfig,
    PostHogListRecordingsConfig, PostHogGetRecordingConfig, PostHogDeleteRecordingConfig,
    PostHogListExperimentsConfig, PostHogGetExperimentConfig,
    PostHogListEventDefinitionsConfig, PostHogListPropertyDefinitionsConfig,
    PostHogUpdateInsightConfig, PostHogUpdateDashboardConfig,
    PostHogFlagLocalEvaluationConfig, PostHogMyFlagsConfig,
    PostHogSplitPersonConfig, PostHogBulkDeletePersonsConfig,
    PostHogCreateExperimentConfig, PostHogUpdateExperimentConfig, PostHogExperimentActionConfig,
    PostHogCreateSurveyConfig, PostHogUpdateSurveyConfig, PostHogSurveyActionConfig,
    PostHogSurveyResponsesConfig, PostHogSurveyStatsConfig,
    PostHogListGroupTypesConfig, PostHogListGroupsConfig, PostHogFindGroupConfig,
    PostHogAddPersonsToCohortConfig,
    PostHogListNotebooksConfig, PostHogGetNotebookConfig, PostHogCreateNotebookConfig,
    PostHogListEarlyAccessConfig, PostHogCreateEarlyAccessConfig,
    PostHogListBatchExportsConfig, PostHogGetBatchExportConfig,
    PostHogListDestinationsConfig, PostHogGetDestinationConfig, PostHogCreateDestinationConfig,
    PostHogUpdateDestinationConfig, PostHogSetDestinationEnabledConfig, PostHogDeleteDestinationConfig,
    PostHogListDestinationTemplatesConfig, PostHogDestinationLogsConfig, PostHogDestinationMetricsConfig,
    PostHogActivityLogConfig,
    PostHogListOrgMembersConfig, PostHogListOrgInvitesConfig, PostHogCreateOrgInviteConfig,
    PostHogListProjectsConfig, PostHogListRolesConfig,
    PostHogRawRequestConfig,
)

PostHogConfig = Annotated[
    Union[tuple(_ACTION_CONFIGS) + _TRIGGER_CONFIGS],
    Discriminator("operation"),
]


class PostHogNodeConfig(NodeConfig[PostHogConfig, PostHogCredential]):
    """Full configuration for the PostHog node including credentials."""
    pass


# ============================================================================
# HTTP helpers
# ============================================================================


def _parse_json(raw: Optional[str], field: str) -> Any:
    if raw in (None, ""):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must be valid JSON: {exc.msg}") from exc


def _safe_int(value: Any, field_name: str) -> int:
    """Coerce a user-supplied pagination value to int, raising a clear error."""
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ValueError(f"'{field_name}' must be a whole number, got {value!r}")


def _parse_query(raw: Optional[str]) -> Dict[str, str]:
    if not raw:
        return {}
    return {k: v for k, v in parse_qsl(raw.lstrip("?"), keep_blank_values=True)}


def _scope_error_hint(detail: str) -> str:
    """Translate PostHog permission_denied errors into actionable guidance.

    Mirrors the Slack/Google 'missing scope → reconnect' pattern: PostHog's 403
    bodies name the exact missing scope or the scoping restriction, so surface
    what to change instead of a bare permission error.
    """
    if "missing required scope" in detail:
        m = re.search(r"scope '([^']+)'", detail)
        scope = m.group(1) if m else "required"
        return (
            f"Not enough scopes: this PostHog credential is missing the '{scope}' scope. "
            "Edit the personal API key's scopes in PostHog (Settings → Personal API keys) "
            "or reconnect the OAuth credential with that access, then retry."
        )
    if "does not have access to the requested project" in detail:
        return (
            f"{detail} This credential was granted access to specific projects only — "
            "set the credential's Project ID to one it can access, or re-grant it access to this project."
        )
    if "does not have access to the requested organization" in detail:
        return (
            f"{detail} This credential was granted access to specific organizations only — "
            "reconnect it with access to this organization."
        )
    if "scoped projects are only supported on project-based endpoints" in detail:
        return (
            "Not enough access: this operation needs organization-level access, but the credential "
            "is scoped to specific projects. Use an all-access or organization-scoped credential "
            "for organization operations."
        )
    return detail


async def _rest_request(
    cred: Dict[str, Any], method: str, path: str,
    params: Optional[Dict[str, Any]] = None, json_body: Optional[Any] = None,
    action_name: str = "request", quiet_statuses: tuple = (),
) -> Dict[str, Any]:
    """Authenticated PostHog REST request. Bearer is the OAuth access token
    (pha_) or the personal API key (phx_); host is the OAuth base_url or the
    region-derived REST host."""
    token = cred.get("access_token") or cred.get("personal_api_key")
    if not token:
        return {"status": "error", "action": action_name, "status_code": 401,
                "error": "This operation needs a Personal API Key (phx_...) or OAuth connection on the PostHog credential."}
    if cred.get("base_url"):
        try:
            rest_base = normalize_posthog_oauth_base_url(str(cred["base_url"]))
        except ValueError as e:
            return {
                "status": "error",
                "action": action_name,
                "status_code": 400,
                "error": str(e),
                "timing_ms": {"api_request": 0.0},
            }
    else:
        rest_base, _ = _hosts(cred.get("region"), cred.get("host"))
    project_id = cred.get("project_id")
    path = path.replace("{project_id}", str(project_id or "")).replace("{id}", str(project_id or ""))
    url = f"{rest_base}{path if path.startswith('/') else '/' + path}"

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
    if isinstance(json_body, dict):
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}
        # PostHog 500s on a non-numeric limit/offset; validate before sending.
        # It accepts the numeric string form, so we validate rather than mutate.
        for _pk in ("limit", "offset"):
            if _pk in params:
                try:
                    _safe_int(params[_pk], _pk)
                except ValueError as e:
                    return {"status": "error", "action": action_name, "status_code": 400,
                            "error": str(e), "timing_ms": {"api_request": 0.0}}

    start = time.time()
    async with guarded_async_client(timeout=60.0) as client:
        try:
            resp = await client.request(method=method, url=url, headers=headers, params=params, json=json_body)
            api_ms = round((time.time() - start) * 1000, 2)
            if resp.status_code >= 400:
                try:
                    err = resp.json()
                except Exception:
                    err = None
                message = (err.get("detail") or err.get("error") or err) if isinstance(err, dict) else resp.text
                if resp.status_code == 403 and isinstance(err, dict) and err.get("code") == "permission_denied":
                    message = _scope_error_hint(str(message))
                if resp.status_code in quiet_statuses:
                    # Expected-by-caller status (e.g. deleting an already-gone
                    # hog function) — not an ERROR-worthy event.
                    logger.info(f"[PostHogNode] {action_name}: HTTP {resp.status_code} (expected) {str(message)[:120]}")
                else:
                    logger.error(f"[PostHogNode] API error ({action_name}): {message}")
                return {"status": "error", "action": action_name, "error": message,
                        "status_code": resp.status_code, "timing_ms": {"api_request": api_ms}}
            if resp.status_code == 204 or not resp.content:
                data: Any = {"success": True}
            else:
                try:
                    data = resp.json()
                except Exception:
                    data = {"raw": resp.text}
            return {"status": "success", "action": action_name, "data": data,
                    "status_code": resp.status_code, "timing_ms": {"api_request": api_ms}}
        except httpx.TimeoutException:
            return {"status": "error", "action": action_name, "error": "Request timed out", "status_code": 408,
                    "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)}}
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[PostHogNode] Request failed ({action_name}): {msg}")
            return {"status": "error", "action": action_name, "error": msg, "status_code": 500,
                    "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)}}


async def _ingest_request(cred: Dict[str, Any], path: str, body: Dict[str, Any], action_name: str) -> Dict[str, Any]:
    """Ingestion request (project API key in body, .i. host, POST-only, no auth header)."""
    project_key = cred.get("project_api_key")
    if not project_key:
        return {"status": "error", "action": action_name, "status_code": 401,
                "error": "Event ingestion needs a Project API Key (phc_...) on the PostHog credential."}
    _, ingest_base = _hosts(cred.get("region"), cred.get("host"))
    url = f"{ingest_base}{path}"
    body = {**body, "api_key": project_key}

    start = time.time()
    async with guarded_async_client(timeout=30.0) as client:
        try:
            resp = await client.post(url, json=body, headers={"Content-Type": "application/json"})
            api_ms = round((time.time() - start) * 1000, 2)
            if resp.status_code >= 400:
                return {"status": "error", "action": action_name, "error": resp.text,
                        "status_code": resp.status_code, "timing_ms": {"api_request": api_ms}}
            try:
                data = resp.json() if resp.content else {"status": 1}
            except Exception:
                data = {"raw": resp.text}
            return {"status": "success", "action": action_name, "data": data,
                    "status_code": resp.status_code, "timing_ms": {"api_request": api_ms}}
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            return {"status": "error", "action": action_name, "error": msg, "status_code": 500,
                    "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)}}


def _proj(cred: Dict[str, Any], resource: str) -> str:
    return f"/api/projects/{cred.get('project_id')}/{resource}"


async def _default_project_id(cred: Dict[str, Any]) -> Optional[str]:
    """Resolve the project the credential should act on.

    Order: the credential's ``scoped_teams`` (a team-scoped OAuth grant names its
    projects in the token response and 403s on org endpoints) → the org's first
    project (unscoped credentials) → ``/api/users/@me/`` (the user endpoint is
    exempt from team scoping, so it still works for project-scoped personal API
    keys where the org route is forbidden)."""
    scoped = cred.get("scoped_teams")
    if isinstance(scoped, (list, tuple)) and scoped:
        return str(scoped[0])
    result = await _rest_request(cred, "GET", "/api/organizations/@current/projects/", action_name="resolve_project")
    if result.get("status") == "success":
        results = (result.get("data") or {}).get("results", [])
        return str(results[0]["id"]) if results and results[0].get("id") is not None else None
    me = await _rest_request(cred, "GET", "/api/users/@me/", action_name="resolve_project_me")
    team = ((me.get("data") or {}).get("team") or {}) if me.get("status") == "success" else {}
    return str(team["id"]) if team.get("id") is not None else None


# Dynamic-dropdown fields: field_name -> (project-scoped REST resource,
# label candidate keys in priority order, id key used as the option value).
_DYNAMIC_FIELDS: Dict[str, tuple] = {
    "flag_id": ("feature_flags", ("name", "key"), "id"),
    "feature_flag_key": ("feature_flags", ("name", "key"), "key"),
    "person_id": ("persons", ("name", "distinct_ids", "id"), "id"),
    "cohort_id": ("cohorts", ("name",), "id"),
    "annotation_id": ("annotations", ("content",), "id"),
    "insight_id": ("insights", ("name", "derived_name"), "id"),
    "dashboard_id": ("dashboards", ("name",), "id"),
    "action_id": ("actions", ("name",), "id"),
    "survey_id": ("surveys", ("name",), "id"),
    "experiment_id": ("experiments", ("name",), "id"),
    "notebook_id": ("notebooks", ("title",), "short_id"),
    "batch_export_id": ("batch_exports", ("name",), "id"),
    "event_name": ("event_definitions", ("name",), "name"),
    "destination_id": ("hog_functions", ("name",), "id"),
    "template_id": ("hog_function_templates", ("name",), "id"),
}


# ============================================================================
# Node
# ============================================================================


class PostHogNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """PostHog product-analytics node — ingestion + REST + HogQL + webhook trigger."""

    # Hog-function deliveries carry no signature — the unguessable webhook URL is
    # the capability. Without this flag the mixin's idempotency guard demands a
    # persisted secret and therefore NEVER holds: every config-panel open would
    # re-register a fresh destination and orphan the previous one.
    webhook_signing_secret_not_issued = True
    # Re-registrations (operation/credential/event_name change) REPLACE the
    # previous hog function: the mixin tears it down via
    # _unregister_external_webhook (404-tolerant) before registering the new one.
    webhook_replace_stale_endpoint = True

    edit_examples = [
        "Capture a 'signup' event for a user",
        "Run a HogQL query for daily active users",
        "Create a feature flag and roll it out to 50%",
        "Add an annotation marking a deploy",
        "When a 'purchase' event fires, notify the team",
    ]

    scope_registry = POSTHOG_SCOPES
    connection_evidence = ConnectionEvidence(
        field="dashboard_id",
        noun="dashboards",
    )

    @classmethod
    def get_config_model(cls):
        return PostHogNodeConfig

    # ---- OAuth token freshening (rotating refresh) ----
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring PostHog OAuth token at load. No-op for API keys."""
        if not credential_data or credential_data.get("credential_type") != "posthog_oauth":
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.posthog_oauth import refresh_access_token
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="posthog",
        )

    async def _ensure_fresh_token(self, credentials) -> None:
        if not isinstance(credentials, PostHogOAuthCredential):
            return
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.posthog_oauth import refresh_access_token
        from utils.database_pool import get_native_pool

        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            pool=get_native_pool(),
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=cred_dict,
            refresh=refresh_access_token, provider="posthog", caller_path="execute",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]

    async def _resolve_project_id(self, cred: Dict[str, Any]) -> Optional[str]:
        """Resolve the default project id (first accessible project), cached per
        node instance."""
        cached = getattr(self, "_pid_cache", None)
        if cached is not None:
            return cached
        pid = await _default_project_id(cred)
        self._pid_cache = pid
        return pid

    # ---- Dynamic dropdown options ----
    @classmethod
    async def load_field_options(
        cls, field_name: str, credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None, search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Populate x-dynamic-options dropdowns from the PostHog REST API."""
        cred = dict(credential_data or {})
        if not (cred.get("personal_api_key") or cred.get("access_token")):
            return {"options": []}
        if not cred.get("project_id"):
            cred["project_id"] = await _default_project_id(cred)
        if not cred.get("project_id"):
            return {"options": []}

        # Group types are a flat list on a distinct endpoint (index is the value).
        if field_name == "group_type_index":
            result = await _rest_request(cred, "GET", _proj(cred, "groups_types/"), action_name="list_group_types")
            rows = result.get("data") if result.get("status") == "success" else None
            options = []
            for r in rows or []:
                if not isinstance(r, dict) or r.get("group_type_index") is None:
                    continue
                idx = r["group_type_index"]
                options.append({"label": str(r.get("group_type") or f"Group {idx}"), "value": str(idx)})
            return {"options": options}

        spec = _DYNAMIC_FIELDS.get(field_name)
        if not spec:
            return {"options": []}
        resource, label_keys, value_key = spec

        async def fetch_page(cursor: Optional[str]):
            try:
                offset = int(cursor or "0")
            except ValueError:
                offset = 0
            result = await _rest_request(
                cred, "GET", _proj(cred, f"{resource}/"),
                params={"limit": 100, "offset": offset}, action_name=f"list_{resource}",
            )
            if result.get("status") != "success":
                return [], None
            rows = (result.get("data") or {}).get("results") or []
            options = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                val = row.get(value_key)
                if val is None:
                    continue
                label = None
                for k in label_keys:
                    v = row.get(k)
                    if isinstance(v, list):
                        v = v[0] if v else None
                    if v:
                        label = v
                        break
                options.append({"label": str(label or val), "value": str(val)})
            next_cursor = str(offset + 100) if len(rows) >= 100 else None
            return options, next_cursor

        return await load_paginated_options(
            fetch_page, page_token=page_token, search=search,
            fields=("label", "value"), log_label=f"PostHogNode.{field_name}",
        )

    # ---- Webhook trigger via Hog Function destination ----
    @classmethod
    def _trigger_event_for(cls, config: Dict[str, Any]) -> Optional[str]:
        """The event a trigger config fires on: the op's fixed event, the typed
        event_name for on_custom_event ('*' = all events), or None when the
        custom event hasn't been entered yet."""
        op = (config or {}).get("operation")
        if op == "on_custom_event":
            return (config or {}).get("event_name") or None
        return _TRIGGER_OP_EVENTS.get(op, "*")

    @classmethod
    def webhook_registration_stale(cls, config: Dict[str, Any], webhook_data: Dict[str, Any]) -> bool:
        """Re-register when the custom event name changed since registration.

        The mixin's row guard only detects operation/credential changes;
        on_custom_event's provider-side filter also depends on config.event_name,
        mirrored back as ``registered_event_name`` at registration time.
        """
        if (config or {}).get("operation") != "on_custom_event":
            return False
        current = (config or {}).get("event_name")
        registered = (config or {}).get("registered_event_name")
        # No event typed yet → nothing better to register; unknown mirror with a
        # typed event → assume stale so the filter converges to what's configured.
        return bool(current) and current != registered

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Delivery-time event scoping backstop.

        The hog-function filter is authoritative provider-side, but it can be
        stale (registered before event_name was typed, or the name was edited
        after registration) — in the worst case a match-all destination fires on
        EVERY project event. Re-check the delivered event against the trigger's
        configured event so a stale provider filter can't fire the workflow.
        Non-hog envelopes (no string 'event' key, e.g. manual test posts) pass.
        """
        expected = cls._trigger_event_for(config or {})
        if expected == "*":
            return True  # explicit opt-in to all events
        if expected is None:
            # on_custom_event with no event typed: registration now refuses this,
            # so an active registration here is a legacy MATCH-ALL destination —
            # drop deliveries until the user configures the event.
            return False
        delivered = payload.get("event") if isinstance(payload, dict) else None
        if not isinstance(delivered, str):
            return True
        return delivered == expected

    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "event_name": (config or {}).get("event_name"),
        }

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id) -> Dict[str, Any]:
        cred = credential or {}
        if not (cred.get("personal_api_key") or cred.get("access_token")):
            raise ValueError("Registering a PostHog trigger needs a Personal API Key or OAuth connection on the credential")
        if not cred.get("project_id"):
            cred = {**cred, "project_id": await _default_project_id(cred)}
        op = (config or {}).get("operation")
        event_name = cls._trigger_event_for(config or {})
        if op == "on_custom_event" and not event_name:
            # Registering without a name would mint a MATCH-ALL destination that
            # fires the workflow on every project event — the config panel loads
            # this field before the user has typed the event, so fail loudly and
            # let the retry pick up the typed value ('*' opts into all events).
            raise ValueError(
                "Set the Event Name field first — the trigger registers for that "
                "specific event (enter '*' to fire on all events)."
            )

        # Stale-endpoint replacement (deleting the previous hog function before
        # this create) is owned by the mixin via webhook_replace_stale_endpoint —
        # it calls _unregister_external_webhook with the freshest known id.

        filters: Dict[str, Any] = {}
        if event_name and event_name != "*":
            filters["events"] = [{"id": event_name, "type": "events"}]
        body = {
            "type": "destination",
            "name": f"NoClick trigger ({event_name})",
            "enabled": True,
            "template_id": "template-webhook",
            "filters": filters,
            "inputs": {
                "url": {"value": webhook_url},
                "method": {"value": "POST"},
                "body": {"value": {"event": "{event.event}", "distinct_id": "{event.distinct_id}",
                                   "properties": "{event.properties}", "timestamp": "{event.timestamp}"}},
            },
        }
        result = await _rest_request(cred, "POST", _proj(cred, "hog_functions/"), json_body=body, action_name="create_hog_function")
        if result.get("status") != "success":
            raise ValueError(f"PostHog trigger registration failed: {result.get('error')}")
        fid = (result.get("data") or {}).get("id")
        if not fid:
            raise ValueError("PostHog did not return a hog function id")
        # registered_event_name mirrors what the provider-side filter was built
        # with — webhook_registration_stale compares it to config.event_name so
        # an edited custom event re-registers on the next panel load.
        return {"external_webhook_id": fid, "registered_event_name": event_name}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id) -> None:
        cred = credential or {}
        fid = (config or {}).get("external_webhook_id")
        if not (cred.get("personal_api_key") or cred.get("access_token")) or not fid:
            return
        if not cred.get("project_id"):
            cred = {**cred, "project_id": await _default_project_id(cred)}
        # Soft-delete: PATCH deleted:true (a raw DELETE is rejected for personal
        # API keys). 404 = already gone = converged (double-teardowns are normal:
        # panel re-register + operation-change hook can both fire) — only a real
        # failure raises so the choke point records a possibly-live endpoint.
        result = await _rest_request(cred, "PATCH", _proj(cred, f"hog_functions/{fid}/"),
                                     json_body={"deleted": True}, action_name="delete_hog_function",
                                     quiet_statuses=(404,))
        if result.get("status") != "success" and result.get("status_code") != 404:
            raise ValueError(f"Failed to remove PostHog hog function: {result.get('error')}")

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]) -> bool:
        """PostHog Hog Function webhook destinations do not HMAC-sign their
        payloads — the unguessable NoClick webhook URL (the row id) is the
        capability. Accept the delivery."""
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        payload = output if isinstance(output, dict) else {}
        return {"text": f"PostHog event:\n{json.dumps(payload, default=str)[:6000]}", "conversation_key": None}

    # ---- Execute ----
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start = time.time()
        config = self.config
        if not config or not isinstance(config, PostHogNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if op.operation in _TRIGGER_OPS:
            return {"status": "success", "action": op.operation, "data": inputs or {},
                    "timing_ms": {"total": round((time.time() - start) * 1000, 2)}}

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add a PostHog API-key or OAuth credential.")
        await self._ensure_fresh_token(credentials)
        cred = credentials.model_dump()

        # Auto-detect the project id from the key when the user didn't set one
        # (management ops need it for the /api/projects/{id}/ paths).
        if not cred.get("project_id") and (cred.get("personal_api_key") or cred.get("access_token")):
            cred["project_id"] = await self._resolve_project_id(cred)

        handlers = {
            "capture_event": self._capture, "batch_capture": self._batch_capture,
            "identify": self._identify, "group_identify": self._group_identify,
            "evaluate_flags": self._evaluate_flags, "run_query": self._run_query, "list_events": self._list_events,
            "list_feature_flags": self._list_feature_flags, "get_feature_flag": self._get_feature_flag,
            "create_feature_flag": self._create_feature_flag, "update_feature_flag": self._update_feature_flag,
            "delete_feature_flag": self._delete_feature_flag,
            "list_persons": self._list_persons, "get_person": self._get_person,
            "update_person": self._update_person, "delete_person": self._delete_person,
            "list_cohorts": self._list_cohorts, "get_cohort": self._get_cohort, "create_cohort": self._create_cohort,
            "update_cohort": self._update_cohort, "delete_cohort": self._delete_cohort, "list_cohort_persons": self._list_cohort_persons,
            "list_annotations": self._list_annotations, "create_annotation": self._create_annotation,
            "update_annotation": self._update_annotation, "delete_annotation": self._delete_annotation,
            "list_insights": self._list_insights, "get_insight": self._get_insight,
            "create_insight": self._create_insight, "delete_insight": self._delete_insight,
            "list_dashboards": self._list_dashboards, "get_dashboard": self._get_dashboard,
            "create_dashboard": self._create_dashboard, "delete_dashboard": self._delete_dashboard,
            "list_actions": self._list_actions, "get_action": self._get_action, "create_action": self._create_action,
            "list_surveys": self._list_surveys, "get_survey": self._get_survey,
            "list_session_recordings": self._list_recordings, "get_session_recording": self._get_recording,
            "delete_session_recording": self._delete_recording,
            "list_experiments": self._list_experiments, "get_experiment": self._get_experiment,
            "list_event_definitions": self._list_event_definitions, "list_property_definitions": self._list_property_definitions,
            "update_insight": self._update_insight_op, "update_dashboard": self._update_dashboard_op,
            "feature_flag_local_evaluation": self._flag_local_eval, "list_my_feature_flags": self._my_flags,
            "split_person": self._split_person, "bulk_delete_persons": self._bulk_delete_persons,
            "create_experiment": self._create_experiment, "update_experiment": self._update_experiment,
            "experiment_action": self._experiment_action,
            "create_survey": self._create_survey, "update_survey": self._update_survey,
            "survey_action": self._survey_action, "get_survey_responses": self._survey_responses,
            "get_survey_stats": self._survey_stats,
            "list_group_types": self._list_group_types, "list_groups": self._list_groups, "find_group": self._find_group,
            "add_persons_to_cohort": self._add_persons_to_cohort,
            "list_notebooks": self._list_notebooks, "get_notebook": self._get_notebook, "create_notebook": self._create_notebook,
            "list_early_access_features": self._list_early_access, "create_early_access_feature": self._create_early_access,
            "list_batch_exports": self._list_batch_exports, "get_batch_export": self._get_batch_export,
            "list_destinations": self._list_destinations, "get_destination": self._get_destination,
            "create_destination": self._create_destination, "update_destination": self._update_destination,
            "set_destination_enabled": self._set_destination_enabled, "delete_destination": self._delete_destination,
            "list_destination_templates": self._list_destination_templates,
            "get_destination_logs": self._destination_logs, "get_destination_metrics": self._destination_metrics,
            "list_activity_log": self._list_activity_log,
            "list_org_members": self._list_org_members, "list_org_invites": self._list_org_invites,
            "create_org_invite": self._create_org_invite, "list_projects": self._list_projects, "list_roles": self._list_roles,
            "raw_request": self._raw_request,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")
        result = await handler(op, cred)
        result["timing_ms"] = {**result.get("timing_ms", {}), "total": round((time.time() - start) * 1000, 2)}
        return result

    # ---- Ingestion handlers ----
    async def _capture(self, c, cred):
        body = {"event": c.event, "distinct_id": c.distinct_id, "properties": _parse_json(c.properties, "Properties") or {}}
        if c.timestamp:
            body["timestamp"] = c.timestamp
        return await _ingest_request(cred, "/i/v0/e/", body, "capture_event")

    async def _batch_capture(self, c, cred):
        batch = _parse_json(c.batch, "Batch")
        if not isinstance(batch, list):
            raise ValueError("Batch must be a JSON array of events")
        return await _ingest_request(cred, "/batch/", {"batch": batch, "historical_migration": c.historical_migration == "true"}, "batch_capture")

    async def _identify(self, c, cred):
        props: Dict[str, Any] = {}
        s = _parse_json(c.set_properties, "Set Properties")
        so = _parse_json(c.set_once_properties, "Set Once Properties")
        if isinstance(s, dict):
            props["$set"] = s
        if isinstance(so, dict):
            props["$set_once"] = so
        return await _ingest_request(cred, "/i/v0/e/", {"event": "$identify", "distinct_id": c.distinct_id, "properties": props}, "identify")

    async def _group_identify(self, c, cred):
        props = {"$group_type": c.group_type, "$group_key": c.group_key, "$group_set": _parse_json(c.properties, "Group Properties") or {}}
        return await _ingest_request(cred, "/i/v0/e/", {"event": "$groupidentify", "distinct_id": f"{c.group_type}_{c.group_key}", "properties": props}, "group_identify")

    async def _evaluate_flags(self, c, cred):
        body = {"distinct_id": c.distinct_id}
        g = _parse_json(c.groups, "Groups"); pp = _parse_json(c.person_properties, "Person Properties")
        if isinstance(g, dict):
            body["groups"] = g
        if isinstance(pp, dict):
            body["person_properties"] = pp
        return await _ingest_request(cred, "/flags?v=2", body, "evaluate_flags")

    # ---- Query ----
    async def _run_query(self, c, cred):
        query = _parse_json(c.query_json, "Query JSON")
        if query is None:
            if not c.hogql:
                raise ValueError("Provide either HogQL or a Query JSON node")
            query = {"kind": "HogQLQuery", "query": c.hogql}
        return await _rest_request(cred, "POST", _proj(cred, "query/"), json_body={"query": query}, action_name="run_query")

    async def _list_events(self, c, cred):
        params = {"event": c.event, "distinct_id": c.distinct_id, "after": c.after, "before": c.before, "limit": c.limit}
        return await _rest_request(cred, "GET", _proj(cred, "events/"), params=params, action_name="list_events")

    # ---- Feature flags ----
    async def _list_feature_flags(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "feature_flags/"), params={"limit": c.limit, "offset": c.offset}, action_name="list_feature_flags")

    async def _get_feature_flag(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, f"feature_flags/{c.flag_id}/"), action_name="get_feature_flag")

    async def _create_feature_flag(self, c, cred):
        body = {"key": c.key, "name": c.name, "active": c.active == "true", "filters": _parse_json(c.filters_json, "Filters") or {"groups": [{"properties": [], "rollout_percentage": 100}]}}
        return await _rest_request(cred, "POST", _proj(cred, "feature_flags/"), json_body=body, action_name="create_feature_flag")

    async def _update_feature_flag(self, c, cred):
        return await _rest_request(cred, "PATCH", _proj(cred, f"feature_flags/{c.flag_id}/"), json_body=_parse_json(c.body_json, "Fields"), action_name="update_feature_flag")

    async def _delete_feature_flag(self, c, cred):
        return await _rest_request(cred, "PATCH", _proj(cred, f"feature_flags/{c.flag_id}/"), json_body={"deleted": True}, action_name="delete_feature_flag")

    # ---- Persons ----
    async def _list_persons(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "persons/"), params={"search": c.search, "limit": c.limit, "offset": c.offset}, action_name="list_persons")

    async def _get_person(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, f"persons/{c.person_id}/"), action_name="get_person")

    async def _update_person(self, c, cred):
        return await _rest_request(cred, "PATCH", _proj(cred, f"persons/{c.person_id}/"), json_body={"properties": _parse_json(c.properties, "Properties")}, action_name="update_person")

    async def _delete_person(self, c, cred):
        return await _rest_request(cred, "DELETE", _proj(cred, f"persons/{c.person_id}/"), action_name="delete_person")

    # ---- Cohorts ----
    async def _list_cohorts(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "cohorts/"), params={"limit": c.limit, "offset": c.offset}, action_name="list_cohorts")

    async def _get_cohort(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, f"cohorts/{c.cohort_id}/"), action_name="get_cohort")

    async def _create_cohort(self, c, cred):
        body = {"name": c.name}
        extra = _parse_json(c.body_json, "Definition")
        if isinstance(extra, dict):
            body.update(extra)
        return await _rest_request(cred, "POST", _proj(cred, "cohorts/"), json_body=body, action_name="create_cohort")

    async def _update_cohort(self, c, cred):
        return await _rest_request(cred, "PATCH", _proj(cred, f"cohorts/{c.cohort_id}/"), json_body=_parse_json(c.body_json, "Fields"), action_name="update_cohort")

    async def _delete_cohort(self, c, cred):
        return await _rest_request(cred, "PATCH", _proj(cred, f"cohorts/{c.cohort_id}/"), json_body={"deleted": True}, action_name="delete_cohort")

    async def _list_cohort_persons(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, f"cohorts/{c.cohort_id}/persons/"), params={"limit": c.limit}, action_name="list_cohort_persons")

    # ---- Annotations ----
    async def _list_annotations(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "annotations/"), params={"limit": c.limit, "offset": c.offset}, action_name="list_annotations")

    async def _create_annotation(self, c, cred):
        body = {"content": c.content}
        if c.date_marker:
            body["date_marker"] = c.date_marker
        return await _rest_request(cred, "POST", _proj(cred, "annotations/"), json_body=body, action_name="create_annotation")

    async def _update_annotation(self, c, cred):
        return await _rest_request(cred, "PATCH", _proj(cred, f"annotations/{c.annotation_id}/"), json_body=_parse_json(c.body_json, "Fields"), action_name="update_annotation")

    async def _delete_annotation(self, c, cred):
        return await _rest_request(cred, "PATCH", _proj(cred, f"annotations/{c.annotation_id}/"), json_body={"deleted": True}, action_name="delete_annotation")

    # ---- Insights ----
    async def _list_insights(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "insights/"), params={"limit": c.limit, "offset": c.offset}, action_name="list_insights")

    async def _get_insight(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, f"insights/{c.insight_id}/"), action_name="get_insight")

    async def _create_insight(self, c, cred):
        body = {"name": c.name}
        extra = _parse_json(c.body_json, "Query/Filters")
        if isinstance(extra, dict):
            body.update(extra)
        return await _rest_request(cred, "POST", _proj(cred, "insights/"), json_body=body, action_name="create_insight")

    async def _delete_insight(self, c, cred):
        return await _rest_request(cred, "PATCH", _proj(cred, f"insights/{c.insight_id}/"), json_body={"deleted": True}, action_name="delete_insight")

    # ---- Dashboards ----
    async def _list_dashboards(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "dashboards/"), params={"limit": c.limit, "offset": c.offset}, action_name="list_dashboards")

    async def _get_dashboard(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, f"dashboards/{c.dashboard_id}/"), action_name="get_dashboard")

    async def _create_dashboard(self, c, cred):
        return await _rest_request(cred, "POST", _proj(cred, "dashboards/"), json_body={"name": c.name, "description": c.description}, action_name="create_dashboard")

    async def _delete_dashboard(self, c, cred):
        return await _rest_request(cred, "PATCH", _proj(cred, f"dashboards/{c.dashboard_id}/"), json_body={"deleted": True}, action_name="delete_dashboard")

    # ---- Actions ----
    async def _list_actions(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "actions/"), params={"limit": c.limit}, action_name="list_actions")

    async def _get_action(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, f"actions/{c.action_id}/"), action_name="get_action")

    async def _create_action(self, c, cred):
        body = {"name": c.name}
        extra = _parse_json(c.body_json, "Steps")
        if isinstance(extra, dict):
            body.update(extra)
        elif isinstance(extra, list):
            body["steps"] = extra
        return await _rest_request(cred, "POST", _proj(cred, "actions/"), json_body=body, action_name="create_action")

    # ---- Surveys ----
    async def _list_surveys(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "surveys/"), params={"limit": c.limit}, action_name="list_surveys")

    async def _get_survey(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, f"surveys/{c.survey_id}/"), action_name="get_survey")

    # ---- Session recordings ----
    async def _list_recordings(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "session_recordings/"), params={"limit": c.limit}, action_name="list_session_recordings")

    async def _get_recording(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, f"session_recordings/{c.recording_id}/"), action_name="get_session_recording")

    async def _delete_recording(self, c, cred):
        return await _rest_request(cred, "DELETE", _proj(cred, f"session_recordings/{c.recording_id}/"), action_name="delete_session_recording")

    # ---- Experiments ----
    async def _list_experiments(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "experiments/"), params={"limit": c.limit}, action_name="list_experiments")

    async def _get_experiment(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, f"experiments/{c.experiment_id}/"), action_name="get_experiment")

    # ---- Definitions ----
    async def _list_event_definitions(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "event_definitions/"), params={"search": c.search, "limit": c.limit}, action_name="list_event_definitions")

    async def _list_property_definitions(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "property_definitions/"), params={"search": c.search, "limit": c.limit}, action_name="list_property_definitions")

    # ---- Passthrough ----
    # ---- Insights / Dashboards updates ----
    async def _update_insight_op(self, c, cred):
        return await _rest_request(cred, "PATCH", _proj(cred, f"insights/{c.insight_id}/"), json_body=_parse_json(c.body_json, "Fields"), action_name="update_insight")

    async def _update_dashboard_op(self, c, cred):
        return await _rest_request(cred, "PATCH", _proj(cred, f"dashboards/{c.dashboard_id}/"), json_body=_parse_json(c.body_json, "Fields"), action_name="update_dashboard")

    # ---- Feature flag evaluation ----
    async def _flag_local_eval(self, c, cred):
        # Local evaluation lives at the project-less /api/feature_flag/local_evaluation/
        # and requires the project token (unless auth is a phs_ key). Prefer the
        # credential's project key, else the inline token on the op.
        token = cred.get("project_api_key") or getattr(c, "project_token", None)
        params = {"token": token} if token else None
        return await _rest_request(cred, "GET", "/api/feature_flag/local_evaluation/", params=params, action_name="feature_flag_local_evaluation")

    async def _my_flags(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "feature_flags/my_flags/"), action_name="list_my_feature_flags")

    # ---- Persons ----
    async def _split_person(self, c, cred):
        body = {"main_distinct_id": c.main_distinct_id} if c.main_distinct_id else {}
        return await _rest_request(cred, "POST", _proj(cred, f"persons/{c.person_id}/split/"), json_body=body, action_name="split_person")

    async def _bulk_delete_persons(self, c, cred):
        body: Dict[str, Any] = {}
        ids = _parse_json(c.ids_json, "Person IDs")
        dids = _parse_json(c.distinct_ids_json, "Distinct IDs")
        if isinstance(ids, list):
            body["ids"] = ids
        if isinstance(dids, list):
            body["distinct_ids"] = dids
        return await _rest_request(cred, "POST", _proj(cred, "persons/bulk_delete/"), json_body=body, action_name="bulk_delete_persons")

    # ---- Experiments ----
    async def _create_experiment(self, c, cred):
        body = {"name": c.name, "feature_flag_key": c.feature_flag_key}
        extra = _parse_json(c.body_json, "Config")
        if isinstance(extra, dict):
            body.update(extra)
        return await _rest_request(cred, "POST", _proj(cred, "experiments/"), json_body=body, action_name="create_experiment")

    async def _update_experiment(self, c, cred):
        return await _rest_request(cred, "PATCH", _proj(cred, f"experiments/{c.experiment_id}/"), json_body=_parse_json(c.body_json, "Fields"), action_name="update_experiment")

    async def _experiment_action(self, c, cred):
        return await _rest_request(cred, "POST", _proj(cred, f"experiments/{c.experiment_id}/{c.action}/"), action_name=f"experiment_{c.action}")

    # ---- Surveys ----
    async def _create_survey(self, c, cred):
        body = {"name": c.name}
        extra = _parse_json(c.body_json, "Config")
        if isinstance(extra, dict):
            body.update(extra)
        body.setdefault("type", "popover")
        return await _rest_request(cred, "POST", _proj(cred, "surveys/"), json_body=body, action_name="create_survey")

    async def _update_survey(self, c, cred):
        return await _rest_request(cred, "PATCH", _proj(cred, f"surveys/{c.survey_id}/"), json_body=_parse_json(c.body_json, "Fields"), action_name="update_survey")

    async def _survey_action(self, c, cred):
        return await _rest_request(cred, "POST", _proj(cred, f"surveys/{c.survey_id}/{c.action}/"), action_name=f"survey_{c.action}")

    async def _survey_responses(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, f"surveys/{c.survey_id}/responses/"), action_name="get_survey_responses")

    async def _survey_stats(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, f"surveys/{c.survey_id}/stats/"), action_name="get_survey_stats")

    # ---- Groups ----
    async def _list_group_types(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "groups_types/"), action_name="list_group_types")

    async def _list_groups(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "groups/"), params={"group_type_index": c.group_type_index, "search": c.search, "limit": c.limit}, action_name="list_groups")

    async def _find_group(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "groups/find/"), params={"group_type_index": c.group_type_index, "group_key": c.group_key}, action_name="find_group")

    # ---- Cohort membership ----
    async def _add_persons_to_cohort(self, c, cred):
        # PATCH with {"person_ids": [...]} — POST 405s and the key is person_ids,
        # not person_uuids (probed live 2026-07-17). Accept the old key gracefully.
        body = _parse_json(c.body_json, "Persons") or {}
        if isinstance(body, dict) and "person_uuids" in body and "person_ids" not in body:
            body["person_ids"] = body.pop("person_uuids")
        return await _rest_request(cred, "PATCH", _proj(cred, f"cohorts/{c.cohort_id}/add_persons_to_static_cohort/"), json_body=body, action_name="add_persons_to_cohort")

    # ---- Notebooks ----
    async def _list_notebooks(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "notebooks/"), params={"limit": c.limit}, action_name="list_notebooks")

    async def _get_notebook(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, f"notebooks/{c.notebook_id}/"), action_name="get_notebook")

    async def _create_notebook(self, c, cred):
        body: Dict[str, Any] = {}
        if c.title:
            body["title"] = c.title
        content = _parse_json(c.content_json, "Content")
        if content is not None:
            body["content"] = content
        return await _rest_request(cred, "POST", _proj(cred, "notebooks/"), json_body=body, action_name="create_notebook")

    # ---- Early access ----
    async def _list_early_access(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "early_access_feature/"), params={"limit": c.limit}, action_name="list_early_access_features")

    async def _create_early_access(self, c, cred):
        body = {"name": c.name, "stage": c.stage, "description": c.description or ""}
        extra = _parse_json(c.body_json, "Extra Config")
        if isinstance(extra, dict):
            body.update(extra)
        return await _rest_request(cred, "POST", _proj(cred, "early_access_feature/"), json_body=body, action_name="create_early_access_feature")

    # ---- Destinations (CDP / hog functions) ----
    @staticmethod
    def _hog_inputs(raw: Optional[str]) -> Dict[str, Any]:
        """Normalize user inputs into PostHog's {key: {"value": …}} shape —
        plain values are wrapped so users can write {"url": "https://…"}."""
        parsed = _parse_json(raw, "Inputs") or {}
        if not isinstance(parsed, dict):
            raise ValueError("Inputs must be a JSON object")
        return {k: (v if isinstance(v, dict) and "value" in v else {"value": v}) for k, v in parsed.items()}

    async def _list_destinations(self, c, cred):
        params = {"types": c.hog_type or "destination", "search": c.search, "limit": c.limit}
        return await _rest_request(cred, "GET", _proj(cred, "hog_functions/"), params=params, action_name="list_destinations")

    async def _get_destination(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, f"hog_functions/{c.destination_id}/"), action_name="get_destination")

    async def _create_destination(self, c, cred):
        body = {
            "type": "destination",
            "template_id": c.template_id,
            "name": c.name,
            "enabled": c.enabled == "true",
            "inputs": self._hog_inputs(c.inputs_json),
            "filters": _parse_json(c.filters_json, "Event Filters") or {},
        }
        return await _rest_request(cred, "POST", _proj(cred, "hog_functions/"), json_body=body, action_name="create_destination")

    async def _update_destination(self, c, cred):
        body = _parse_json(c.body_json, "Fields")
        if isinstance(body, dict) and isinstance(body.get("inputs"), dict):
            body["inputs"] = {k: (v if isinstance(v, dict) and "value" in v else {"value": v})
                              for k, v in body["inputs"].items()}
        return await _rest_request(cred, "PATCH", _proj(cred, f"hog_functions/{c.destination_id}/"), json_body=body, action_name="update_destination")

    async def _set_destination_enabled(self, c, cred):
        return await _rest_request(cred, "PATCH", _proj(cred, f"hog_functions/{c.destination_id}/"),
                                   json_body={"enabled": c.enabled == "true"}, action_name="set_destination_enabled")

    async def _delete_destination(self, c, cred):
        # Hog functions soft-delete via PATCH (raw DELETE is rejected for personal keys).
        return await _rest_request(cred, "PATCH", _proj(cred, f"hog_functions/{c.destination_id}/"),
                                   json_body={"deleted": True}, action_name="delete_destination")

    async def _list_destination_templates(self, c, cred):
        # The endpoint IGNORES ?search= (verified live) — fetch the catalog and
        # substring-filter client-side on name/id, like the dropdown does.
        params = {"limit": 500 if c.search else c.limit}
        result = await _rest_request(cred, "GET", _proj(cred, "hog_function_templates/"),
                                     params=params, action_name="list_destination_templates")
        if result.get("status") == "success" and c.search:
            rows = (result.get("data") or {}).get("results", [])
            q = c.search.lower()
            filtered = [t for t in rows if q in str(t.get("name", "")).lower() or q in str(t.get("id", "")).lower()]
            try:
                lim = int(c.limit) if c.limit else None
            except ValueError:
                lim = None
            result["data"] = {"results": filtered[:lim] if lim else filtered, "count": len(filtered)}
        return result

    async def _destination_logs(self, c, cred):
        params = {"level": c.level, "search": c.search, "limit": c.limit}
        return await _rest_request(cred, "GET", _proj(cred, f"hog_functions/{c.destination_id}/logs/"), params=params, action_name="get_destination_logs")

    async def _destination_metrics(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, f"hog_functions/{c.destination_id}/metrics/totals/"),
                                   params={"after": c.after or "-7d"}, action_name="get_destination_metrics")

    # ---- Batch exports ----
    async def _list_batch_exports(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "batch_exports/"), params={"limit": c.limit}, action_name="list_batch_exports")

    async def _get_batch_export(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, f"batch_exports/{c.batch_export_id}/"), action_name="get_batch_export")

    # ---- Activity log ----
    async def _list_activity_log(self, c, cred):
        return await _rest_request(cred, "GET", _proj(cred, "activity_log/"), params={"limit": c.limit}, action_name="list_activity_log")

    # ---- Organization (org-scoped, not project) ----
    async def _list_org_members(self, c, cred):
        return await _rest_request(cred, "GET", "/api/organizations/@current/members/", params={"limit": c.limit}, action_name="list_org_members")

    async def _list_org_invites(self, c, cred):
        return await _rest_request(cred, "GET", "/api/organizations/@current/invites/", action_name="list_org_invites")

    async def _create_org_invite(self, c, cred):
        body: Dict[str, Any] = {"target_email": c.target_email}
        if c.level:
            body["level"] = int(c.level)
        return await _rest_request(cred, "POST", "/api/organizations/@current/invites/", json_body=body, action_name="create_org_invite")

    async def _list_projects(self, c, cred):
        return await _rest_request(cred, "GET", "/api/organizations/@current/projects/", action_name="list_projects")

    async def _list_roles(self, c, cred):
        return await _rest_request(cred, "GET", "/api/organizations/@current/roles/", action_name="list_roles")

    # ---- Passthrough ----
    async def _raw_request(self, c, cred):
        path = c.path if c.path.startswith("/") else f"/{c.path}"
        if "://" in path:
            raise ValueError("Path must be relative (no scheme), e.g. /api/projects/{project_id}/hog_functions/")
        return await _rest_request(cred, c.method, path, params=_parse_query(c.query_params),
                                   json_body=_parse_json(c.body_json, "Body"), action_name="raw_request")
