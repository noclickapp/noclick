"""
Sentry (error-tracking / APM) automation node.

Covers Sentry's public REST API (``/api/0/``): organizations, projects, teams,
issues, events, releases + deploys, members, issue-alert rules, metric-alert
rules, crons/monitors, dashboards, Discover queries, and service hooks — plus a
push trigger backed by Sentry **service hooks** (project webhooks) for
``event.created`` (On Error) and ``event.alert`` (On Alert). Service hooks are
the ONLY REST-registerable per-URL webhook Sentry offers, so those two events are
the full per-node trigger surface — richer resource.action events (issue.resolved,
comment.*, metric_alert.*) live only on the integration platform, which uses one
static app-level URL (no per-node registration). Deliveries are signed with
``X-ServiceHook-Signature`` = HMAC-SHA256(raw body, hook secret) — a DIFFERENT
header + key than the integration platform's ``Sentry-Hook-Signature``.

Authentication (two methods):
- **Auth token** (primary): a Bearer token — a User Auth Token, an Org Auth Token
  (``sntrys_…``), or an Internal Integration token. Scopes are chosen when the
  token is minted. The organization slug scopes most endpoints.
- **OAuth 2.0**: standard authorization-code flow via a shared NoClick OAuth app.

Region-aware: SaaS orgs live in a region (US / US2 / EU) — the credential picks
the host (``sentry.io`` default, ``us2.sentry.io``, ``de.sentry.io``) or a custom
self-hosted base URL. Paths are identical across regions.

Pagination is cursor-based via the ``Link`` header (rel="next"; results="true";
cursor=…) — dynamic-option dropdowns follow it.

Docs: https://docs.sentry.io/api/
"""

import hashlib
import hmac
import json
import logging
import re
import time
from typing import Dict, Any, Optional, Literal, Union, Annotated
from urllib.parse import parse_qsl
from pydantic import BaseModel, Field, ConfigDict, Discriminator

import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.core.dynamic_options import load_paginated_options
from nodes.oauth.sentry_oauth import SENTRY_DEFAULT_SCOPES
from nodes.scopes.sentry import SENTRY_SCOPES

logger = logging.getLogger(__name__)

# Service-hook event → trigger operation.
_TRIGGER_OP_EVENTS = {"on_error": "event.created", "on_alert": "event.alert"}
_TRIGGER_OPS = set(_TRIGGER_OP_EVENTS)

_REGION_HOSTS = {"us": "https://sentry.io", "us2": "https://us2.sentry.io", "de": "https://de.sentry.io"}


def _host(region: Optional[str], custom_host: Optional[str]) -> str:
    region = (region or "us").lower()
    if region == "custom" and custom_host:
        h = custom_host.rstrip("/")
        return h if "://" in h else f"https://{h}"
    return _REGION_HOSTS.get(region, "https://sentry.io")


# ============================================================================
# Credentials
# ============================================================================

_REGION_FIELD = Field(
    "us", title="Region",
    description="Where your Sentry organization's data lives (or 'custom' for self-hosted)",
    json_schema_extra={"x-enum-searchable": True,
                       "enumNames": ["US (sentry.io)", "US2", "EU (Germany)", "Self-hosted / Custom"]},
)
_HOST_FIELD = Field(
    None, title="Custom Host",
    description="Self-hosted base URL (e.g. https://sentry.mycompany.com) — required when Region is 'custom'",
)


class SentryAuthTokenCredential(BaseModel):
    """Sentry auth token (Bearer) — the simplest, unrestricted path.

    Use a User Auth Token, an Org Auth Token (``sntrys_…``), or an Internal
    Integration token. Mint one in Sentry → Settings → Auth Tokens (or User
    Settings → User Auth Tokens) with the scopes your operations need.
    """

    credential_type: Literal["sentry_auth_token"] = Field("sentry_auth_token", json_schema_extra={"ui:hidden": True})
    region: Literal["us", "us2", "de", "custom"] = _REGION_FIELD
    host: Optional[str] = _HOST_FIELD
    auth_token: str = Field(
        ..., title="Auth Token",
        description="A Sentry auth token (User/Org/Internal-Integration). Sent as a Bearer token.",
        json_schema_extra={"ui:widget": "password"},
    )
    organization_slug: str = Field(
        ..., title="Organization Slug",
        description="Your Sentry org slug (the part in the URL: sentry.io/organizations/<slug>/)",
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://sentry.io/settings/auth-tokens/",
        "x-help-text": "Create an auth token at Settings → Auth Tokens. Enter your org slug (from the Sentry URL).",
    })


class SentryOAuthCredential(BaseModel):
    """OAuth 2.0 credential for Sentry (authorization-code flow).

    Tokens come from the consent flow, not entered manually. Access tokens last
    ~30 days and auto-refresh. The organization slug auto-detects from the first
    accessible org when left blank.
    """

    credential_type: Literal["sentry_oauth"] = Field("sentry_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    region: Literal["us", "us2", "de", "custom"] = _REGION_FIELD
    host: Optional[str] = _HOST_FIELD
    organization_slug: Optional[str] = Field(
        None, title="Organization Slug",
        description="Leave blank to use your default org — it's auto-detected from the token.",
    )
    name: Optional[str] = Field(None, title="Account Name")
    email: Optional[str] = Field(None, title="Account Email")

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "sentry",
        # Mirrors nodes/oauth/sentry_oauth.py:SENTRY_DEFAULT_SCOPES, which is what
        # actually rides the authorize URL — an empty list here fell through to
        # that same default on both sides, so nothing about the consent request
        # changes. Declaring it makes the list checkable against SENTRY_SCOPES.
        # Imported, not copied: the authorize-URL builder falls through to this
        # same constant (`scopes or SENTRY_DEFAULT_SCOPES`), so sharing it makes
        # the declared list and the requested list structurally unable to drift.
        "x-oauth-scopes": list(SENTRY_DEFAULT_SCOPES),
        "x-credential-url": "https://docs.sentry.io/api/auth/",
    })


SentryCredential = Union[SentryAuthTokenCredential, SentryOAuthCredential]


# ============================================================================
# Operation config helpers
# ============================================================================


# Inline "Create new <resource>" builder affordances: a create op declares the
# resource it produces (+ where its id/slug lands in the response), and the
# matching picker fields declare the same resource type. Sentry keys projects/
# teams/monitors by slug, dashboards/alert-rules by id.
_CREATES_RESOURCE: Dict[str, tuple] = {
    "create_project": ("sentry_project", "data.slug"),
    "create_team": ("sentry_team", "data.slug"),
    "create_monitor": ("sentry_monitor", "data.slug"),
    "create_dashboard": ("sentry_dashboard", "data.id"),
    "create_metric_alert": ("sentry_metric_alert", "data.id"),
    "create_issue_alert": ("sentry_issue_alert", "data.id"),
}
_FIELD_RESOURCE_TYPE: Dict[str, str] = {
    "project_slug": "sentry_project",
    "team_slug": "sentry_team",
    "monitor_slug": "sentry_monitor",
    "dashboard_id": "sentry_dashboard",
    "alert_rule_id": "sentry_metric_alert",
    "rule_id": "sentry_issue_alert",
}


def _op(op: str, category: str, display: str, keywords: Optional[Any] = None) -> Any:
    extra: Dict[str, Any] = {"const": op, "ui:hidden": True, "x-category": category,
                             "x-is-trigger": False, "x-display-name": display}
    if keywords:
        extra["x-keywords"] = keywords
    if op in _CREATES_RESOURCE:
        rt, id_path = _CREATES_RESOURCE[op]
        extra["x-creates-resource"] = True
        extra["x-resource-type"] = rt
        extra["x-resource-id-path"] = id_path
    return Field(op, json_schema_extra=extra, title=display)


def _dyn(field_name: str, placeholder: str, custom_ph: str, depends_on: Optional[str] = None) -> Dict[str, Any]:
    opts = {"field_name": field_name, "placeholder": placeholder, "searchable": True,
            "allow_custom": True, "custom_placeholder": custom_ph}
    if depends_on:
        opts["depends_on"] = depends_on
    extra: Dict[str, Any] = {"x-dynamic-options": opts}
    rt = _FIELD_RESOURCE_TYPE.get(field_name)
    if rt:
        extra["x-resource-type"] = rt
    return extra


def _project(*, required: bool = True) -> Any:
    return Field(... if required else None, title="Project", description="The Sentry project",
                 json_schema_extra=_dyn("project_slug", "Select a project…", "Or paste a project slug"))


def _team(*, required: bool = True) -> Any:
    return Field(... if required else None, title="Team", description="The Sentry team",
                 json_schema_extra=_dyn("team_slug", "Select a team…", "Or paste a team slug"))


def _issue() -> Any:
    return Field(..., title="Issue", description="The Sentry issue",
                 json_schema_extra=_dyn("issue_id", "Select an issue…", "Or paste an issue id"))


def _limit() -> Any:
    return Field(None, title="Limit", description="Max results per page (≤100)")


def _body(title: str = "Body (JSON)", desc: str = "Request body as JSON") -> Any:
    return Field(None, title=title, description=desc, json_schema_extra={"ui:widget": "textarea"})


# ---- Organizations ----
class SentryListOrgsConfig(BaseModel):
    operation: Literal["list_organizations"] = _op("list_organizations", "Organizations", "List Organizations", ["orgs"])
    limit: Optional[str] = _limit()


class SentryGetOrgConfig(BaseModel):
    operation: Literal["get_organization"] = _op("get_organization", "Organizations", "Get Organization")


# ---- Projects ----
class SentryListProjectsConfig(BaseModel):
    operation: Literal["list_projects"] = _op("list_projects", "Projects", "List Projects", ["apps"])
    limit: Optional[str] = _limit()


class SentryGetProjectConfig(BaseModel):
    operation: Literal["get_project"] = _op("get_project", "Projects", "Get Project")
    project_slug: str = _project()


class SentryCreateProjectConfig(BaseModel):
    operation: Literal["create_project"] = _op("create_project", "Projects", "Create Project", ["new project"])
    team_slug: str = _team()
    name: str = Field(..., title="Name", description="The new project's name")
    platform: Optional[str] = Field(None, title="Platform", description="e.g. python, javascript, node (optional)")


class SentryUpdateProjectConfig(BaseModel):
    operation: Literal["update_project"] = _op("update_project", "Projects", "Update Project")
    project_slug: str = _project()
    body_json: str = Field(..., title="Fields (JSON)", description='e.g. {"name":"New","platform":"python"}', json_schema_extra={"ui:widget": "textarea"})


class SentryDeleteProjectConfig(BaseModel):
    operation: Literal["delete_project"] = _op("delete_project", "Projects", "Delete Project")
    project_slug: str = _project()


class SentryListProjectKeysConfig(BaseModel):
    operation: Literal["list_project_keys"] = _op("list_project_keys", "Projects", "List Client Keys (DSNs)", ["dsn"])
    project_slug: str = _project()


# ---- Teams ----
class SentryListTeamsConfig(BaseModel):
    operation: Literal["list_teams"] = _op("list_teams", "Teams", "List Teams")
    limit: Optional[str] = _limit()


class SentryGetTeamConfig(BaseModel):
    operation: Literal["get_team"] = _op("get_team", "Teams", "Get Team")
    team_slug: str = _team()


class SentryCreateTeamConfig(BaseModel):
    operation: Literal["create_team"] = _op("create_team", "Teams", "Create Team")
    name: str = Field(..., title="Name", description="The new team's name")


class SentryDeleteTeamConfig(BaseModel):
    operation: Literal["delete_team"] = _op("delete_team", "Teams", "Delete Team")
    team_slug: str = _team()


class SentryListTeamProjectsConfig(BaseModel):
    operation: Literal["list_team_projects"] = _op("list_team_projects", "Teams", "List Team Projects")
    team_slug: str = _team()


class SentryAddProjectToTeamConfig(BaseModel):
    operation: Literal["add_project_to_team"] = _op("add_project_to_team", "Teams", "Add Project to Team")
    project_slug: str = _project()
    team_slug: str = _team()


class SentryRemoveProjectFromTeamConfig(BaseModel):
    operation: Literal["remove_project_from_team"] = _op("remove_project_from_team", "Teams", "Remove Project from Team")
    project_slug: str = _project()
    team_slug: str = _team()


# ---- Issues ----
class SentryListIssuesConfig(BaseModel):
    operation: Literal["list_issues"] = _op("list_issues", "Issues", "List Issues", ["errors", "problems", "search issues"])
    query: Optional[str] = Field(None, title="Query", description="Sentry search, e.g. is:unresolved level:error")
    project_slug: Optional[str] = _project(required=False)
    stats_period: Optional[str] = Field(None, title="Stats Period", description="e.g. 24h, 14d")
    environment: Optional[str] = Field(None, title="Environment", description="Filter to an environment (optional)",
                                       json_schema_extra=_dyn("environment", "Select an environment…", "Or paste an environment name"))
    sort: Optional[str] = Field(None, title="Sort", json_schema_extra={
        "enum": ["", "date", "new", "priority", "freq", "user"], "x-enum-searchable": True})
    limit: Optional[str] = _limit()


class SentryGetIssueConfig(BaseModel):
    operation: Literal["get_issue"] = _op("get_issue", "Issues", "Get Issue")
    issue_id: str = _issue()


class SentryUpdateIssueConfig(BaseModel):
    operation: Literal["update_issue"] = _op("update_issue", "Issues", "Update Issue", ["resolve", "ignore", "assign"])
    issue_id: str = _issue()
    status: Optional[str] = Field(None, title="Status", json_schema_extra={
        "enum": ["", "resolved", "unresolved", "ignored", "muted", "resolvedInNextRelease"], "x-enum-searchable": True})
    assigned_to: Optional[str] = Field(None, title="Assign To", description="Username, email, or team:<id> (optional)")
    body_json: Optional[str] = _body("Extra Fields (JSON)", 'Other fields, e.g. {"priority":"high","isBookmarked":true}')


class SentryDeleteIssueConfig(BaseModel):
    operation: Literal["delete_issue"] = _op("delete_issue", "Issues", "Delete Issue")
    issue_id: str = _issue()


class SentryListIssueEventsConfig(BaseModel):
    operation: Literal["list_issue_events"] = _op("list_issue_events", "Issues", "List Issue Events")
    issue_id: str = _issue()
    limit: Optional[str] = _limit()


class SentryLatestEventConfig(BaseModel):
    operation: Literal["get_latest_event"] = _op("get_latest_event", "Issues", "Get Latest Event")
    issue_id: str = _issue()


# ---- Events ----
class SentryListEventsConfig(BaseModel):
    operation: Literal["list_project_events"] = _op("list_project_events", "Events", "List Project Events")
    project_slug: str = _project()
    limit: Optional[str] = _limit()


class SentryGetEventConfig(BaseModel):
    operation: Literal["get_event"] = _op("get_event", "Events", "Get Event")
    project_slug: str = _project()
    event_id: str = Field(..., title="Event ID", description="The event id (or 'latest'/'oldest')")


# ---- Releases ----
class SentryListReleasesConfig(BaseModel):
    operation: Literal["list_releases"] = _op("list_releases", "Releases", "List Releases")
    query: Optional[str] = Field(None, title="Query", description="Filter by version substring (optional)")
    limit: Optional[str] = _limit()


class SentryCreateReleaseConfig(BaseModel):
    operation: Literal["create_release"] = _op("create_release", "Releases", "Create Release", ["deploy", "version"])
    version: str = Field(..., title="Version", description="Release version/identifier, e.g. 1.2.3 or a git sha")
    projects: str = Field(..., title="Projects", description="Comma-separated project slugs this release applies to")
    body_json: Optional[str] = _body("Extra Config (JSON)", 'Optional, e.g. {"refs":[{"repository":"org/repo","commit":"sha"}]}')


class SentryGetReleaseConfig(BaseModel):
    operation: Literal["get_release"] = _op("get_release", "Releases", "Get Release")
    version: str = Field(..., title="Version", description="The release version",
                         json_schema_extra=_dyn("release_version", "Select a release…", "Or paste a version"))


class SentryUpdateReleaseConfig(BaseModel):
    operation: Literal["update_release"] = _op("update_release", "Releases", "Update Release")
    version: str = Field(..., title="Version",
                         json_schema_extra=_dyn("release_version", "Select a release…", "Or paste a version"))
    body_json: str = Field(..., title="Fields (JSON)", description='e.g. {"ref":"…","refs":[…]}', json_schema_extra={"ui:widget": "textarea"})


class SentryDeleteReleaseConfig(BaseModel):
    operation: Literal["delete_release"] = _op("delete_release", "Releases", "Delete Release")
    version: str = Field(..., title="Version",
                         json_schema_extra=_dyn("release_version", "Select a release…", "Or paste a version"))


class SentryListDeploysConfig(BaseModel):
    operation: Literal["list_deploys"] = _op("list_deploys", "Releases", "List Deploys")
    version: str = Field(..., title="Version",
                         json_schema_extra=_dyn("release_version", "Select a release…", "Or paste a version"))


class SentryCreateDeployConfig(BaseModel):
    operation: Literal["create_deploy"] = _op("create_deploy", "Releases", "Create Deploy")
    version: str = Field(..., title="Version",
                         json_schema_extra=_dyn("release_version", "Select a release…", "Or paste a version"))
    environment: str = Field(..., title="Environment", description="e.g. production, staging")
    body_json: Optional[str] = _body("Extra Config (JSON)", 'Optional, e.g. {"name":"…","url":"…"}')


# ---- Members ----
class SentryListMembersConfig(BaseModel):
    operation: Literal["list_members"] = _op("list_members", "Members", "List Members", ["users", "people"])
    limit: Optional[str] = _limit()


class SentryInviteMemberConfig(BaseModel):
    operation: Literal["invite_member"] = _op("invite_member", "Members", "Invite Member", ["add user"])
    email: str = Field(..., title="Email", description="Email address to invite")
    org_role: Optional[str] = Field(None, title="Org Role", description="Organization role for the new member", json_schema_extra={
        "enum": ["", "member", "admin", "manager", "owner", "billing"], "x-enum-searchable": True})
    body_json: Optional[str] = _body("Extra Config (JSON)", 'Optional, e.g. {"teamRoles":[{"teamSlug":"eng","role":"contributor"}]}')


class SentryGetMemberConfig(BaseModel):
    operation: Literal["get_member"] = _op("get_member", "Members", "Get Member")
    member_id: str = Field(..., title="Member", json_schema_extra=_dyn("member_id", "Select a member…", "Or paste a member id"))


class SentryUpdateMemberConfig(BaseModel):
    operation: Literal["update_member"] = _op("update_member", "Members", "Update Member")
    member_id: str = Field(..., title="Member", json_schema_extra=_dyn("member_id", "Select a member…", "Or paste a member id"))
    body_json: str = Field(..., title="Fields (JSON)", description='e.g. {"orgRole":"manager"}', json_schema_extra={"ui:widget": "textarea"})


class SentryRemoveMemberConfig(BaseModel):
    operation: Literal["remove_member"] = _op("remove_member", "Members", "Remove Member")
    member_id: str = Field(..., title="Member", json_schema_extra=_dyn("member_id", "Select a member…", "Or paste a member id"))


# ---- Issue alert rules ----
class SentryListIssueAlertsConfig(BaseModel):
    operation: Literal["list_issue_alerts"] = _op("list_issue_alerts", "Alerts", "List Issue Alert Rules", ["rules"])
    project_slug: str = _project()


class SentryCreateIssueAlertConfig(BaseModel):
    operation: Literal["create_issue_alert"] = _op("create_issue_alert", "Alerts", "Create Issue Alert Rule")
    project_slug: str = _project()
    body_json: str = Field(..., title="Rule (JSON)", description='Alert rule definition, e.g. {"name":"…","conditions":[…],"actions":[…],"frequency":30}', json_schema_extra={"ui:widget": "textarea"})


class SentryGetIssueAlertConfig(BaseModel):
    operation: Literal["get_issue_alert"] = _op("get_issue_alert", "Alerts", "Get Issue Alert Rule")
    project_slug: str = _project()
    rule_id: str = Field(..., title="Rule", json_schema_extra=_dyn("rule_id", "Select a rule…", "Or paste a rule id", depends_on="project_slug"))


class SentryUpdateIssueAlertConfig(BaseModel):
    operation: Literal["update_issue_alert"] = _op("update_issue_alert", "Alerts", "Update Issue Alert Rule")
    project_slug: str = _project()
    rule_id: str = Field(..., title="Rule", json_schema_extra=_dyn("rule_id", "Select a rule…", "Or paste a rule id", depends_on="project_slug"))
    body_json: str = Field(..., title="Rule (JSON)", description="The FULL updated rule — Sentry replaces it wholesale, so include name, conditions, and actions (a rule with no action is rejected)", json_schema_extra={"ui:widget": "textarea"})


class SentryDeleteIssueAlertConfig(BaseModel):
    operation: Literal["delete_issue_alert"] = _op("delete_issue_alert", "Alerts", "Delete Issue Alert Rule")
    project_slug: str = _project()
    rule_id: str = Field(..., title="Rule", json_schema_extra=_dyn("rule_id", "Select a rule…", "Or paste a rule id", depends_on="project_slug"))


# ---- Metric alert rules ----
class SentryListMetricAlertsConfig(BaseModel):
    operation: Literal["list_metric_alerts"] = _op("list_metric_alerts", "Alerts", "List Metric Alert Rules")
    limit: Optional[str] = _limit()


class SentryCreateMetricAlertConfig(BaseModel):
    operation: Literal["create_metric_alert"] = _op("create_metric_alert", "Alerts", "Create Metric Alert Rule")
    body_json: str = Field(..., title="Rule (JSON)", description='Metric alert definition (name, aggregate, timeWindow, triggers, projects, …)', json_schema_extra={"ui:widget": "textarea"})


class SentryGetMetricAlertConfig(BaseModel):
    operation: Literal["get_metric_alert"] = _op("get_metric_alert", "Alerts", "Get Metric Alert Rule")
    alert_rule_id: str = Field(..., title="Metric Alert Rule", json_schema_extra=_dyn("alert_rule_id", "Select a metric alert…", "Or paste an alert rule id"))


class SentryUpdateMetricAlertConfig(BaseModel):
    operation: Literal["update_metric_alert"] = _op("update_metric_alert", "Alerts", "Update Metric Alert Rule")
    alert_rule_id: str = Field(..., title="Metric Alert Rule", json_schema_extra=_dyn("alert_rule_id", "Select a metric alert…", "Or paste an alert rule id"))
    body_json: str = Field(..., title="Fields (JSON)", json_schema_extra={"ui:widget": "textarea"})


class SentryDeleteMetricAlertConfig(BaseModel):
    operation: Literal["delete_metric_alert"] = _op("delete_metric_alert", "Alerts", "Delete Metric Alert Rule")
    alert_rule_id: str = Field(..., title="Metric Alert Rule", json_schema_extra=_dyn("alert_rule_id", "Select a metric alert…", "Or paste an alert rule id"))


# ---- Monitors (crons) ----
class SentryListMonitorsConfig(BaseModel):
    operation: Literal["list_monitors"] = _op("list_monitors", "Crons", "List Monitors", ["cron", "scheduled jobs"])
    limit: Optional[str] = _limit()


class SentryCreateMonitorConfig(BaseModel):
    operation: Literal["create_monitor"] = _op("create_monitor", "Crons", "Create Monitor")
    body_json: str = Field(..., title="Monitor (JSON)", description='e.g. {"name":"…","project":"my-project","config":{"schedule":"0 * * * *","schedule_type":"crontab"}}', json_schema_extra={"ui:widget": "textarea"})


class SentryGetMonitorConfig(BaseModel):
    operation: Literal["get_monitor"] = _op("get_monitor", "Crons", "Get Monitor")
    monitor_slug: str = Field(..., title="Monitor", json_schema_extra=_dyn("monitor_slug", "Select a monitor…", "Or paste a monitor slug"))


class SentryUpdateMonitorConfig(BaseModel):
    operation: Literal["update_monitor"] = _op("update_monitor", "Crons", "Update Monitor")
    monitor_slug: str = Field(..., title="Monitor", json_schema_extra=_dyn("monitor_slug", "Select a monitor…", "Or paste a monitor slug"))
    body_json: str = Field(..., title="Fields (JSON)", json_schema_extra={"ui:widget": "textarea"})


class SentryDeleteMonitorConfig(BaseModel):
    operation: Literal["delete_monitor"] = _op("delete_monitor", "Crons", "Delete Monitor")
    monitor_slug: str = Field(..., title="Monitor", json_schema_extra=_dyn("monitor_slug", "Select a monitor…", "Or paste a monitor slug"))


class SentryListCheckinsConfig(BaseModel):
    operation: Literal["list_checkins"] = _op("list_checkins", "Crons", "List Monitor Check-ins")
    monitor_slug: str = Field(..., title="Monitor", json_schema_extra=_dyn("monitor_slug", "Select a monitor…", "Or paste a monitor slug"))
    limit: Optional[str] = _limit()


# ---- Dashboards ----
class SentryListDashboardsConfig(BaseModel):
    operation: Literal["list_dashboards"] = _op("list_dashboards", "Dashboards", "List Dashboards")
    limit: Optional[str] = _limit()


class SentryCreateDashboardConfig(BaseModel):
    operation: Literal["create_dashboard"] = _op("create_dashboard", "Dashboards", "Create Dashboard")
    body_json: str = Field(..., title="Dashboard (JSON)", description='e.g. {"title":"My dashboard","widgets":[…]}', json_schema_extra={"ui:widget": "textarea"})


class SentryGetDashboardConfig(BaseModel):
    operation: Literal["get_dashboard"] = _op("get_dashboard", "Dashboards", "Get Dashboard")
    dashboard_id: str = Field(..., title="Dashboard", json_schema_extra=_dyn("dashboard_id", "Select a dashboard…", "Or paste a dashboard id"))


class SentryDeleteDashboardConfig(BaseModel):
    operation: Literal["delete_dashboard"] = _op("delete_dashboard", "Dashboards", "Delete Dashboard")
    dashboard_id: str = Field(..., title="Dashboard", json_schema_extra=_dyn("dashboard_id", "Select a dashboard…", "Or paste a dashboard id"))


# ---- Discover / stats ----
class SentryDiscoverConfig(BaseModel):
    operation: Literal["query_discover"] = _op("query_discover", "Discover", "Query Events (Discover)", ["analytics", "search events", "explore"])
    field: str = Field(..., title="Fields", description="Comma-separated columns, e.g. title,count(),project")
    query: Optional[str] = Field(None, title="Query", description="Sentry search filter (optional)")
    stats_period: Optional[str] = Field(None, title="Stats Period", description="e.g. 24h, 14d")
    project_slug: Optional[str] = _project(required=False)
    environment: Optional[str] = Field(None, title="Environment", description="Filter to an environment (optional)",
                                       json_schema_extra=_dyn("environment", "Select an environment…", "Or paste an environment name"))
    dataset: Optional[str] = Field(None, title="Dataset", json_schema_extra={
        "enum": ["", "errors", "transactions", "spans", "logs"], "x-enum-searchable": True})
    limit: Optional[str] = _limit()


class SentryEventsStatsConfig(BaseModel):
    operation: Literal["events_stats"] = _op("events_stats", "Discover", "Events Time Series (Stats)")
    y_axis: str = Field(..., title="Y-Axis", description="Aggregate to plot, e.g. count() or p95(transaction.duration)")
    query: Optional[str] = Field(None, title="Query", description="Sentry search filter (optional)")
    stats_period: Optional[str] = Field(None, title="Stats Period", description="e.g. 24h, 14d")
    interval: Optional[str] = Field(None, title="Interval", description="Bucket size, e.g. 1h, 1d")


class SentrySessionsConfig(BaseModel):
    operation: Literal["list_sessions"] = _op("list_sessions", "Discover", "Release Health (Sessions)", ["release health", "crash rate"])
    field: str = Field("sum(session)", title="Fields", description="e.g. sum(session), crash_free_rate(session)")
    stats_period: Optional[str] = Field(None, title="Stats Period", description="e.g. 24h, 14d")
    project_slug: Optional[str] = _project(required=False)
    environment: Optional[str] = Field(None, title="Environment", description="Filter to an environment (optional)",
                                       json_schema_extra=_dyn("environment", "Select an environment…", "Or paste an environment name"))


# ---- Service hooks (management) ----
class SentryListServiceHooksConfig(BaseModel):
    operation: Literal["list_service_hooks"] = _op("list_service_hooks", "Service Hooks", "List Service Hooks", ["webhooks"])
    project_slug: str = _project()


class SentryGetServiceHookConfig(BaseModel):
    operation: Literal["get_service_hook"] = _op("get_service_hook", "Service Hooks", "Get Service Hook")
    project_slug: str = _project()
    hook_id: str = Field(..., title="Service Hook",
                         json_schema_extra=_dyn("hook_id", "Select a service hook…", "Or paste a hook id", depends_on="project_slug"))


class SentryDeleteServiceHookConfig(BaseModel):
    operation: Literal["delete_service_hook"] = _op("delete_service_hook", "Service Hooks", "Delete Service Hook")
    project_slug: str = _project()
    hook_id: str = Field(..., title="Service Hook",
                         json_schema_extra=_dyn("hook_id", "Select a service hook…", "Or paste a hook id", depends_on="project_slug"))


# ---- Raw passthrough ----
class SentryRawRequestConfig(BaseModel):
    operation: Literal["raw_request"] = _op("raw_request", "Advanced", "Custom Request")
    method: Literal["GET", "POST", "PUT", "DELETE"] = Field("GET", title="Method")
    path: str = Field(..., title="Path", description="Path after the host, e.g. /api/0/organizations/{org}/projects/. {org} is substituted.")
    query_params: Optional[str] = Field(None, title="Query Parameters", description="e.g. per_page=100&cursor=0:100:0")
    body_json: Optional[str] = _body()


# ============================================================================
# Triggers (service hooks)
# ============================================================================


def _trigger_op(op: str, display: str, keywords: Any) -> Any:
    return Field(op, title=display, json_schema_extra={
        "const": op, "ui:hidden": True, "x-is-trigger": True,
        "x-category": "Triggers", "x-display-name": display, "x-keywords": keywords})


class _SentryTriggerBase(WebhookTriggerConfigBase):
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    project_slug: str = _project()
    webhook_url: Optional[str] = Field(default=None, title="Webhook URL",
                                       json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class SentryOnErrorConfig(_SentryTriggerBase):
    """Fires on every new error event in the project (service-hook event.created)."""
    operation: Literal["on_error"] = _trigger_op("on_error", "On Error Event", ["event.created", "new error", "exception"])


class SentryOnAlertConfig(_SentryTriggerBase):
    """Fires when a project alert rule triggers (service-hook event.alert)."""
    operation: Literal["on_alert"] = _trigger_op("on_alert", "On Alert", ["event.alert", "alert triggered"])


# ============================================================================
# Discriminated union
# ============================================================================

_ACTION_CONFIGS = (
    SentryListOrgsConfig, SentryGetOrgConfig,
    SentryListProjectsConfig, SentryGetProjectConfig, SentryCreateProjectConfig, SentryUpdateProjectConfig,
    SentryDeleteProjectConfig, SentryListProjectKeysConfig,
    SentryListTeamsConfig, SentryGetTeamConfig, SentryCreateTeamConfig, SentryDeleteTeamConfig,
    SentryListTeamProjectsConfig, SentryAddProjectToTeamConfig, SentryRemoveProjectFromTeamConfig,
    SentryListIssuesConfig, SentryGetIssueConfig, SentryUpdateIssueConfig, SentryDeleteIssueConfig,
    SentryListIssueEventsConfig, SentryLatestEventConfig,
    SentryListEventsConfig, SentryGetEventConfig,
    SentryListReleasesConfig, SentryCreateReleaseConfig, SentryGetReleaseConfig, SentryUpdateReleaseConfig,
    SentryDeleteReleaseConfig, SentryListDeploysConfig, SentryCreateDeployConfig,
    SentryListMembersConfig, SentryInviteMemberConfig, SentryGetMemberConfig, SentryUpdateMemberConfig, SentryRemoveMemberConfig,
    SentryListIssueAlertsConfig, SentryCreateIssueAlertConfig, SentryGetIssueAlertConfig, SentryUpdateIssueAlertConfig, SentryDeleteIssueAlertConfig,
    SentryListMetricAlertsConfig, SentryCreateMetricAlertConfig, SentryGetMetricAlertConfig, SentryUpdateMetricAlertConfig, SentryDeleteMetricAlertConfig,
    SentryListMonitorsConfig, SentryCreateMonitorConfig, SentryGetMonitorConfig, SentryUpdateMonitorConfig, SentryDeleteMonitorConfig, SentryListCheckinsConfig,
    SentryListDashboardsConfig, SentryCreateDashboardConfig, SentryGetDashboardConfig, SentryDeleteDashboardConfig,
    SentryDiscoverConfig, SentryEventsStatsConfig, SentrySessionsConfig,
    SentryListServiceHooksConfig, SentryGetServiceHookConfig, SentryDeleteServiceHookConfig,
    SentryRawRequestConfig,
)
_TRIGGER_CONFIGS = (SentryOnErrorConfig, SentryOnAlertConfig)

SentryConfig = Annotated[Union[_ACTION_CONFIGS + _TRIGGER_CONFIGS], Discriminator("operation")]


class SentryNodeConfig(NodeConfig[SentryConfig, SentryCredential]):
    """Full Sentry node configuration including credentials."""
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


def _parse_query(raw: Optional[str]) -> Dict[str, str]:
    if not raw:
        return {}
    return {k: v for k, v in parse_qsl(raw.lstrip("?"), keep_blank_values=True)}


_LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next";\s*results="(true|false)";\s*cursor="([^"]*)"')


def _next_cursor(link_header: Optional[str]) -> Optional[str]:
    """Extract the next cursor from Sentry's Link header (None if no more pages)."""
    if not link_header:
        return None
    m = _LINK_NEXT_RE.search(link_header)
    if m and m.group(2) == "true":
        return m.group(3)
    return None


async def _rest_request(cred: Dict[str, Any], method: str, path: str,
                        params: Optional[Dict[str, Any]] = None, json_body: Optional[Any] = None,
                        action_name: str = "request") -> Dict[str, Any]:
    """Authenticated Sentry REST request. Bearer = OAuth access token or auth token."""
    token = cred.get("access_token") or cred.get("auth_token")
    if not token:
        return {"status": "error", "action": action_name, "status_code": 401,
                "error": "This operation needs a Sentry auth token or OAuth connection."}
    base = _host(cred.get("region"), cred.get("host"))
    path = path.replace("{org}", str(cred.get("organization_slug") or ""))
    url = f"{base}{path if path.startswith('/') else '/' + path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if isinstance(json_body, dict):
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with guarded_async_client(timeout=60.0) as client:
        try:
            resp = await client.request(method=method, url=url, headers=headers, params=params, json=json_body)
            api_ms = round((time.time() - start) * 1000, 2)
            if resp.status_code >= 400:
                try:
                    err = resp.json()
                    message = err.get("detail") or err.get("error") or err if isinstance(err, dict) else err
                except Exception:
                    message = resp.text
                if not isinstance(message, str):
                    message = json.dumps(message)
                logger.error(f"[SentryNode] API error ({action_name}): {message}")
                return {"status": "error", "action": action_name, "error": message,
                        "status_code": resp.status_code, "timing_ms": {"api_request": api_ms}}
            if resp.status_code == 204 or not resp.content:
                data: Any = {"success": True}
            else:
                try:
                    data = resp.json()
                except Exception:
                    data = {"raw": resp.text}
            return {"status": "success", "action": action_name, "data": data, "status_code": resp.status_code,
                    "next_cursor": _next_cursor(resp.headers.get("Link")), "timing_ms": {"api_request": api_ms}}
        except httpx.TimeoutException:
            return {"status": "error", "action": action_name, "error": "Request timed out", "status_code": 408}
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[SentryNode] Request failed ({action_name}): {msg}")
            return {"status": "error", "action": action_name, "error": msg, "status_code": 500}


def _org_path(cred: Dict[str, Any], resource: str) -> str:
    return f"/api/0/organizations/{cred.get('organization_slug')}/{resource}"


def _proj_path(cred: Dict[str, Any], project: str, resource: str) -> str:
    return f"/api/0/projects/{cred.get('organization_slug')}/{project}/{resource}"


async def _default_org(cred: Dict[str, Any]) -> Optional[str]:
    """First accessible org slug (so OAuth users needn't type it)."""
    result = await _rest_request(cred, "GET", "/api/0/organizations/", params={"per_page": 1}, action_name="resolve_org")
    rows = result.get("data") if result.get("status") == "success" else None
    return rows[0].get("slug") if isinstance(rows, list) and rows and rows[0].get("slug") else None


# Dropdown field_name -> (org-scoped resource, value key, label candidate keys)
_DYNAMIC_ORG_FIELDS: Dict[str, tuple] = {
    "project_slug": ("projects", "slug", ("name", "slug")),
    "team_slug": ("teams", "slug", ("name", "slug")),
    "issue_id": ("issues", "id", ("title", "shortId")),
    "release_version": ("releases", "version", ("shortVersion", "version")),
    "member_id": ("members", "id", ("email", "name")),
    "monitor_slug": ("monitors", "slug", ("name", "slug")),
    "alert_rule_id": ("alert-rules", "id", ("name",)),
    "dashboard_id": ("dashboards", "id", ("title",)),
    "environment": ("environments", "name", ("name",)),
}

# Project-scoped dropdowns (need a project_slug from the sibling field via context).
_DYNAMIC_PROJECT_FIELDS: Dict[str, tuple] = {
    "rule_id": ("rules", "id", ("name",)),
    "hook_id": ("hooks", "id", ("url",)),
}


# ============================================================================
# Node
# ============================================================================


class SentryNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Sentry error-tracking node — REST across issues/projects/releases/alerts/monitors + service-hook triggers."""

    edit_examples = [
        "List unresolved Sentry issues for a project",
        "Resolve a Sentry issue when a fix is deployed",
        "Create a Sentry release and mark a deploy",
        "Trigger a workflow when a new error is captured in Sentry",
        "Query Sentry Discover for the top errors this week",
    ]

    scope_registry = SENTRY_SCOPES
    connection_evidence = ConnectionEvidence(
        field="project_slug",
        noun="projects",
    )

    @classmethod
    def get_config_model(cls):
        return SentryNodeConfig

    # ---- OAuth freshening ----
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data or credential_data.get("credential_type") != "sentry_oauth":
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.sentry_oauth import refresh_access_token
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="sentry",
        )

    async def _ensure_fresh_token(self, credentials) -> None:
        if not isinstance(credentials, SentryOAuthCredential):
            return
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.sentry_oauth import refresh_access_token
        from utils.database_pool import get_native_pool
        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            pool=get_native_pool(), credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=cred_dict, refresh=refresh_access_token,
            provider="sentry", caller_path="execute",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]

    async def _resolve_org(self, cred: Dict[str, Any]) -> Optional[str]:
        cached = getattr(self, "_org_cache", None)
        if cached is not None:
            return cached
        org = await _default_org(cred)
        self._org_cache = org
        return org

    # ---- Dynamic dropdowns ----
    @classmethod
    async def load_field_options(cls, field_name: str, credential_data: Dict[str, Any],
                                 context: Optional[Dict[str, Any]] = None,
                                 page_token: Optional[str] = None, search: Optional[str] = None) -> Dict[str, Any]:
        cred = dict(credential_data or {})
        if not (cred.get("auth_token") or cred.get("access_token")):
            return {"options": []}

        # organization_slug lists every accessible org (not org-scoped).
        if field_name == "organization_slug":
            async def fetch_orgs(cursor):
                r = await _rest_request(cred, "GET", "/api/0/organizations/",
                                        params={"per_page": 100, "cursor": cursor}, action_name="list_orgs")
                rows = r.get("data") if r.get("status") == "success" else []
                opts = [{"label": o.get("name") or o.get("slug"), "value": o.get("slug")}
                        for o in (rows or []) if isinstance(o, dict) and o.get("slug")]
                return opts, r.get("next_cursor")
            return await load_paginated_options(fetch_orgs, page_token=page_token, search=search, log_label="SentryNode.org")

        if not cred.get("organization_slug"):
            cred["organization_slug"] = await _default_org(cred)
        if not cred.get("organization_slug"):
            return {"options": []}

        # Project-scoped fields (rules, service hooks) depend on the chosen project.
        if field_name in _DYNAMIC_PROJECT_FIELDS:
            project = (context or {}).get("project_slug")
            if not project:
                return {"options": []}
            resource, value_key, label_keys = _DYNAMIC_PROJECT_FIELDS[field_name]
            path = _proj_path(cred, project, resource)
        elif field_name in _DYNAMIC_ORG_FIELDS:
            resource, value_key, label_keys = _DYNAMIC_ORG_FIELDS[field_name]
            path = _org_path(cred, resource)
        else:
            return {"options": []}

        async def fetch_page(cursor):
            r = await _rest_request(cred, "GET", f"{path}/", params={"per_page": 100, "cursor": cursor}, action_name=f"list_{field_name}")
            if r.get("status") != "success":
                return [], None
            rows = r.get("data") or []
            options = []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                val = row.get(value_key)
                if val is None:
                    continue
                label = next((row[k] for k in label_keys if row.get(k)), None)
                options.append({"label": str(label or val), "value": str(val)})
            return options, r.get("next_cursor")

        return await load_paginated_options(fetch_page, page_token=page_token, search=search,
                                            fields=("label", "value"), log_label=f"SentryNode.{field_name}")

    # ---- Service-hook trigger ----
    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "project_slug": (config or {}).get("project_slug"),
        }

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id) -> Dict[str, Any]:
        cred = dict(credential or {})
        if not (cred.get("auth_token") or cred.get("access_token")):
            raise ValueError("Registering a Sentry trigger needs an auth token or OAuth connection")
        if not cred.get("organization_slug"):
            cred["organization_slug"] = await _default_org(cred)
        cfg = config or {}
        project = cfg.get("project_slug")
        if not project:
            raise ValueError("A project is required to register a Sentry trigger")
        event = _TRIGGER_OP_EVENTS.get(cfg.get("operation"), "event.alert")
        body = {"url": webhook_url, "events": [event]}
        result = await _rest_request(cred, "POST", _proj_path(cred, project, "hooks") + "/", json_body=body, action_name="create_service_hook")
        if result.get("status") != "success":
            raise ValueError(f"Sentry trigger registration failed: {result.get('error')}")
        data = result.get("data") or {}
        hook_id = data.get("id")
        if not hook_id:
            raise ValueError("Sentry did not return a service hook id")
        return {"external_webhook_id": str(hook_id), "signing_secret": data.get("secret")}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id) -> None:
        cred = dict(credential or {})
        cfg = config or {}
        hook_id = cfg.get("external_webhook_id")
        project = cfg.get("project_slug")
        if not (cred.get("auth_token") or cred.get("access_token")) or not hook_id or not project:
            return
        if not cred.get("organization_slug"):
            cred["organization_slug"] = await _default_org(cred)
        result = await _rest_request(cred, "DELETE", _proj_path(cred, project, f"hooks/{hook_id}") + "/", action_name="delete_service_hook")
        if result.get("status") != "success" and result.get("status_code") != 404:
            raise ValueError(f"Failed to remove Sentry service hook: {result.get('error')}")

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]) -> bool:
        """Verify a Sentry service-hook delivery.

        Service hooks sign with ``X-ServiceHook-Signature`` = HMAC-SHA256(raw
        body, hook secret) as a hex digest (the ``X-ServiceHook-Timestamp``
        header is NOT part of the signature). This is a DIFFERENT header + key
        than the integration-platform ``Sentry-Hook-Signature`` (which keys on
        the app client secret) — do not conflate them.
        """
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # pre-registration / no secret stored — don't hard-block
        sig = next((v for k, v in (headers or {}).items()
                    if k.lower() == "x-servicehook-signature"), None)
        if not sig:
            return False
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)

    @classmethod
    def resolve_agent_event(cls, output):
        payload = output if isinstance(output, dict) else {}
        return {"text": f"Sentry event:\n{json.dumps(payload, default=str)[:6000]}", "conversation_key": None}

    # ---- Execute ----
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start = time.time()
        config = self.config
        if not config or not isinstance(config, SentryNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if op.operation in _TRIGGER_OPS:
            return {"status": "success", "action": op.operation, "data": inputs or {},
                    "timing_ms": {"total": round((time.time() - start) * 1000, 2)}}

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add a Sentry auth token or OAuth credential.")
        await self._ensure_fresh_token(credentials)
        cred = credentials.model_dump()
        if not cred.get("organization_slug") and cred.get("access_token"):
            cred["organization_slug"] = await self._resolve_org(cred)

        handler = self._HANDLERS.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")
        result = await handler(self, op, cred)
        if isinstance(result, dict):
            result["timing_ms"] = {**result.get("timing_ms", {}), "total": round((time.time() - start) * 1000, 2)}
        return result

    # ---- Organizations ----
    async def _list_orgs(self, c, cred):
        return await _rest_request(cred, "GET", "/api/0/organizations/", params={"per_page": c.limit}, action_name="list_organizations")

    async def _get_org(self, c, cred):
        return await _rest_request(cred, "GET", "/api/0/organizations/{org}/", action_name="get_organization")

    # ---- Projects ----
    async def _list_projects(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, "projects") + "/", params={"per_page": c.limit}, action_name="list_projects")

    async def _get_project(self, c, cred):
        return await _rest_request(cred, "GET", _proj_path(cred, c.project_slug, "") , action_name="get_project")

    async def _create_project(self, c, cred):
        body = {"name": c.name}
        if c.platform:
            body["platform"] = c.platform
        return await _rest_request(cred, "POST", f"/api/0/teams/{cred.get('organization_slug')}/{c.team_slug}/projects/", json_body=body, action_name="create_project")

    async def _update_project(self, c, cred):
        return await _rest_request(cred, "PUT", _proj_path(cred, c.project_slug, ""), json_body=_parse_json(c.body_json, "Fields"), action_name="update_project")

    async def _delete_project(self, c, cred):
        return await _rest_request(cred, "DELETE", _proj_path(cred, c.project_slug, ""), action_name="delete_project")

    async def _list_project_keys(self, c, cred):
        return await _rest_request(cred, "GET", _proj_path(cred, c.project_slug, "keys") + "/", action_name="list_project_keys")

    # ---- Teams ----
    async def _list_teams(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, "teams") + "/", params={"per_page": c.limit}, action_name="list_teams")

    async def _get_team(self, c, cred):
        return await _rest_request(cred, "GET", f"/api/0/teams/{cred.get('organization_slug')}/{c.team_slug}/", action_name="get_team")

    async def _create_team(self, c, cred):
        return await _rest_request(cred, "POST", _org_path(cred, "teams") + "/", json_body={"name": c.name}, action_name="create_team")

    async def _delete_team(self, c, cred):
        return await _rest_request(cred, "DELETE", f"/api/0/teams/{cred.get('organization_slug')}/{c.team_slug}/", action_name="delete_team")

    async def _list_team_projects(self, c, cred):
        return await _rest_request(cred, "GET", f"/api/0/teams/{cred.get('organization_slug')}/{c.team_slug}/projects/", action_name="list_team_projects")

    async def _add_project_to_team(self, c, cred):
        return await _rest_request(cred, "POST", _proj_path(cred, c.project_slug, f"teams/{c.team_slug}") + "/", action_name="add_project_to_team")

    async def _remove_project_from_team(self, c, cred):
        return await _rest_request(cred, "DELETE", _proj_path(cred, c.project_slug, f"teams/{c.team_slug}") + "/", action_name="remove_project_from_team")

    # ---- Issues ----
    async def _list_issues(self, c, cred):
        params = {"query": c.query, "project": None, "statsPeriod": c.stats_period,
                  "environment": c.environment, "sort": c.sort, "per_page": c.limit}
        if c.project_slug:
            params["query"] = f"{c.query or ''} project:{c.project_slug}".strip()
        return await _rest_request(cred, "GET", _org_path(cred, "issues") + "/", params=params, action_name="list_issues")

    async def _get_issue(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, f"issues/{c.issue_id}") + "/", action_name="get_issue")

    async def _update_issue(self, c, cred):
        body: Dict[str, Any] = {}
        if c.status:
            body["status"] = c.status
        if c.assigned_to:
            body["assignedTo"] = c.assigned_to
        extra = _parse_json(c.body_json, "Extra Fields")
        if isinstance(extra, dict):
            body.update(extra)
        return await _rest_request(cred, "PUT", _org_path(cred, f"issues/{c.issue_id}") + "/", json_body=body, action_name="update_issue")

    async def _delete_issue(self, c, cred):
        return await _rest_request(cred, "DELETE", _org_path(cred, f"issues/{c.issue_id}") + "/", action_name="delete_issue")

    async def _list_issue_events(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, f"issues/{c.issue_id}/events") + "/", params={"per_page": c.limit}, action_name="list_issue_events")

    async def _get_latest_event(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, f"issues/{c.issue_id}/events/latest") + "/", action_name="get_latest_event")

    # ---- Events ----
    async def _list_events(self, c, cred):
        return await _rest_request(cred, "GET", _proj_path(cred, c.project_slug, "events") + "/", params={"per_page": c.limit}, action_name="list_project_events")

    async def _get_event(self, c, cred):
        return await _rest_request(cred, "GET", _proj_path(cred, c.project_slug, f"events/{c.event_id}") + "/", action_name="get_event")

    # ---- Releases ----
    async def _list_releases(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, "releases") + "/", params={"query": c.query, "per_page": c.limit}, action_name="list_releases")

    async def _create_release(self, c, cred):
        body: Dict[str, Any] = {"version": c.version, "projects": [p.strip() for p in c.projects.split(",") if p.strip()]}
        extra = _parse_json(c.body_json, "Extra Config")
        if isinstance(extra, dict):
            body.update(extra)
        return await _rest_request(cred, "POST", _org_path(cred, "releases") + "/", json_body=body, action_name="create_release")

    async def _get_release(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, f"releases/{c.version}") + "/", action_name="get_release")

    async def _update_release(self, c, cred):
        return await _rest_request(cred, "PUT", _org_path(cred, f"releases/{c.version}") + "/", json_body=_parse_json(c.body_json, "Fields"), action_name="update_release")

    async def _delete_release(self, c, cred):
        return await _rest_request(cred, "DELETE", _org_path(cred, f"releases/{c.version}") + "/", action_name="delete_release")

    async def _list_deploys(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, f"releases/{c.version}/deploys") + "/", action_name="list_deploys")

    async def _create_deploy(self, c, cred):
        body = {"environment": c.environment}
        extra = _parse_json(c.body_json, "Extra Config")
        if isinstance(extra, dict):
            body.update(extra)
        return await _rest_request(cred, "POST", _org_path(cred, f"releases/{c.version}/deploys") + "/", json_body=body, action_name="create_deploy")

    # ---- Members ----
    async def _list_members(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, "members") + "/", params={"per_page": c.limit}, action_name="list_members")

    async def _invite_member(self, c, cred):
        body: Dict[str, Any] = {"email": c.email}
        if c.org_role:
            body["orgRole"] = c.org_role
        extra = _parse_json(c.body_json, "Extra Config")
        if isinstance(extra, dict):
            body.update(extra)
        return await _rest_request(cred, "POST", _org_path(cred, "members") + "/", json_body=body, action_name="invite_member")

    async def _get_member(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, f"members/{c.member_id}") + "/", action_name="get_member")

    async def _update_member(self, c, cred):
        return await _rest_request(cred, "PUT", _org_path(cred, f"members/{c.member_id}") + "/", json_body=_parse_json(c.body_json, "Fields"), action_name="update_member")

    async def _remove_member(self, c, cred):
        return await _rest_request(cred, "DELETE", _org_path(cred, f"members/{c.member_id}") + "/", action_name="remove_member")

    # ---- Issue alert rules ----
    async def _list_issue_alerts(self, c, cred):
        return await _rest_request(cred, "GET", _proj_path(cred, c.project_slug, "rules") + "/", action_name="list_issue_alerts")

    async def _create_issue_alert(self, c, cred):
        return await _rest_request(cred, "POST", _proj_path(cred, c.project_slug, "rules") + "/", json_body=_parse_json(c.body_json, "Rule"), action_name="create_issue_alert")

    async def _get_issue_alert(self, c, cred):
        return await _rest_request(cred, "GET", _proj_path(cred, c.project_slug, f"rules/{c.rule_id}") + "/", action_name="get_issue_alert")

    async def _update_issue_alert(self, c, cred):
        return await _rest_request(cred, "PUT", _proj_path(cred, c.project_slug, f"rules/{c.rule_id}") + "/", json_body=_parse_json(c.body_json, "Fields"), action_name="update_issue_alert")

    async def _delete_issue_alert(self, c, cred):
        return await _rest_request(cred, "DELETE", _proj_path(cred, c.project_slug, f"rules/{c.rule_id}") + "/", action_name="delete_issue_alert")

    # ---- Metric alert rules ----
    async def _list_metric_alerts(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, "alert-rules") + "/", params={"per_page": c.limit}, action_name="list_metric_alerts")

    async def _create_metric_alert(self, c, cred):
        return await _rest_request(cred, "POST", _org_path(cred, "alert-rules") + "/", json_body=_parse_json(c.body_json, "Rule"), action_name="create_metric_alert")

    async def _get_metric_alert(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, f"alert-rules/{c.alert_rule_id}") + "/", action_name="get_metric_alert")

    async def _update_metric_alert(self, c, cred):
        return await _rest_request(cred, "PUT", _org_path(cred, f"alert-rules/{c.alert_rule_id}") + "/", json_body=_parse_json(c.body_json, "Fields"), action_name="update_metric_alert")

    async def _delete_metric_alert(self, c, cred):
        return await _rest_request(cred, "DELETE", _org_path(cred, f"alert-rules/{c.alert_rule_id}") + "/", action_name="delete_metric_alert")

    # ---- Monitors ----
    async def _list_monitors(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, "monitors") + "/", params={"per_page": c.limit}, action_name="list_monitors")

    async def _create_monitor(self, c, cred):
        return await _rest_request(cred, "POST", _org_path(cred, "monitors") + "/", json_body=_parse_json(c.body_json, "Monitor"), action_name="create_monitor")

    async def _get_monitor(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, f"monitors/{c.monitor_slug}") + "/", action_name="get_monitor")

    async def _update_monitor(self, c, cred):
        return await _rest_request(cred, "PUT", _org_path(cred, f"monitors/{c.monitor_slug}") + "/", json_body=_parse_json(c.body_json, "Fields"), action_name="update_monitor")

    async def _delete_monitor(self, c, cred):
        return await _rest_request(cred, "DELETE", _org_path(cred, f"monitors/{c.monitor_slug}") + "/", action_name="delete_monitor")

    async def _list_checkins(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, f"monitors/{c.monitor_slug}/checkins") + "/", params={"per_page": c.limit}, action_name="list_checkins")

    # ---- Dashboards ----
    async def _list_dashboards(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, "dashboards") + "/", params={"per_page": c.limit}, action_name="list_dashboards")

    async def _create_dashboard(self, c, cred):
        return await _rest_request(cred, "POST", _org_path(cred, "dashboards") + "/", json_body=_parse_json(c.body_json, "Dashboard"), action_name="create_dashboard")

    async def _get_dashboard(self, c, cred):
        return await _rest_request(cred, "GET", _org_path(cred, f"dashboards/{c.dashboard_id}") + "/", action_name="get_dashboard")

    async def _delete_dashboard(self, c, cred):
        return await _rest_request(cred, "DELETE", _org_path(cred, f"dashboards/{c.dashboard_id}") + "/", action_name="delete_dashboard")

    # ---- Discover / stats ----
    async def _query_discover(self, c, cred):
        params: Dict[str, Any] = {"field": [f.strip() for f in c.field.split(",") if f.strip()],
                                  "query": c.query, "statsPeriod": c.stats_period, "dataset": c.dataset,
                                  "environment": c.environment, "per_page": c.limit}
        if c.project_slug:
            params["project"] = c.project_slug
        return await _rest_request(cred, "GET", _org_path(cred, "events") + "/", params=params, action_name="query_discover")

    async def _events_stats(self, c, cred):
        params = {"yAxis": c.y_axis, "query": c.query, "statsPeriod": c.stats_period, "interval": c.interval}
        return await _rest_request(cred, "GET", _org_path(cred, "events-stats") + "/", params=params, action_name="events_stats")

    async def _list_sessions(self, c, cred):
        params: Dict[str, Any] = {"field": [f.strip() for f in c.field.split(",") if f.strip()],
                                  "statsPeriod": c.stats_period, "environment": c.environment}
        if c.project_slug:
            params["project"] = c.project_slug
        return await _rest_request(cred, "GET", _org_path(cred, "sessions") + "/", params=params, action_name="list_sessions")

    # ---- Service hooks ----
    async def _list_service_hooks(self, c, cred):
        return await _rest_request(cred, "GET", _proj_path(cred, c.project_slug, "hooks") + "/", action_name="list_service_hooks")

    async def _get_service_hook(self, c, cred):
        return await _rest_request(cred, "GET", _proj_path(cred, c.project_slug, f"hooks/{c.hook_id}") + "/", action_name="get_service_hook")

    async def _delete_service_hook(self, c, cred):
        return await _rest_request(cred, "DELETE", _proj_path(cred, c.project_slug, f"hooks/{c.hook_id}") + "/", action_name="delete_service_hook")

    # ---- Passthrough ----
    async def _raw_request(self, c, cred):
        path = c.path if c.path.startswith("/") else f"/{c.path}"
        if "://" in path:
            raise ValueError("Path must be relative (no scheme), e.g. /api/0/organizations/{org}/projects/")
        return await _rest_request(cred, c.method, path, params=_parse_query(c.query_params),
                                   json_body=_parse_json(c.body_json, "Body"), action_name="raw_request")

    _HANDLERS = {
        "list_organizations": _list_orgs, "get_organization": _get_org,
        "list_projects": _list_projects, "get_project": _get_project, "create_project": _create_project,
        "update_project": _update_project, "delete_project": _delete_project, "list_project_keys": _list_project_keys,
        "list_teams": _list_teams, "get_team": _get_team, "create_team": _create_team, "delete_team": _delete_team,
        "list_team_projects": _list_team_projects, "add_project_to_team": _add_project_to_team,
        "remove_project_from_team": _remove_project_from_team,
        "list_issues": _list_issues, "get_issue": _get_issue, "update_issue": _update_issue, "delete_issue": _delete_issue,
        "list_issue_events": _list_issue_events, "get_latest_event": _get_latest_event,
        "list_project_events": _list_events, "get_event": _get_event,
        "list_releases": _list_releases, "create_release": _create_release, "get_release": _get_release,
        "update_release": _update_release, "delete_release": _delete_release,
        "list_deploys": _list_deploys, "create_deploy": _create_deploy,
        "list_members": _list_members, "invite_member": _invite_member, "get_member": _get_member,
        "update_member": _update_member, "remove_member": _remove_member,
        "list_issue_alerts": _list_issue_alerts, "create_issue_alert": _create_issue_alert, "get_issue_alert": _get_issue_alert,
        "update_issue_alert": _update_issue_alert, "delete_issue_alert": _delete_issue_alert,
        "list_metric_alerts": _list_metric_alerts, "create_metric_alert": _create_metric_alert, "get_metric_alert": _get_metric_alert,
        "update_metric_alert": _update_metric_alert, "delete_metric_alert": _delete_metric_alert,
        "list_monitors": _list_monitors, "create_monitor": _create_monitor, "get_monitor": _get_monitor,
        "update_monitor": _update_monitor, "delete_monitor": _delete_monitor, "list_checkins": _list_checkins,
        "list_dashboards": _list_dashboards, "create_dashboard": _create_dashboard, "get_dashboard": _get_dashboard,
        "delete_dashboard": _delete_dashboard,
        "query_discover": _query_discover, "events_stats": _events_stats, "list_sessions": _list_sessions,
        "list_service_hooks": _list_service_hooks, "get_service_hook": _get_service_hook, "delete_service_hook": _delete_service_hook,
        "raw_request": _raw_request,
    }
