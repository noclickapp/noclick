"""Sentry operation → API scope requirements.

Sentry scopes a token per resource and verb: ``<resource>:read`` for GET,
``<resource>:write`` for PUT/POST, ``<resource>:admin`` for DELETE
(https://docs.sentry.io/api/permissions/). Each endpoint page publishes the set
it accepts as "requires ONE of the following scopes", so a requirement here
records the LEAST-PRIVILEGE member of that documented set — never the union,
which would over-declare.

Two provider quirks shape the table:

- **Releases have their own scope.** ``project:releases`` appears in the
  accepted set for every release and deploy endpoint, so the whole family
  declares it rather than the broader project scopes.
- **Crons and Discover are org-level.** Monitor LISTs and Discover/session
  queries run under ``org:read``, while a specific monitor is addressed with the
  project scopes, matching what each endpoint documents.

Trigger operations (``on_error``, ``on_alert``) register a project SERVICE HOOK
at ``POST /projects/{org}/{proj}/hooks/`` (``project:write``) and tear it down
with ``DELETE`` (``project:admin``), so they declare both — a token with only
``project:write`` registers a hook it can never remove.

The alert-rule operations are deliberately unmapped: Sentry retired the
``/api/alerts/`` docs category (every endpoint page 404s today, replaced by
detectors/workflows), so there is no current published scope for the
``/rules/`` and ``/alert-rules/`` paths the node still calls. Guessing them is
exactly the failure mode this table exists to prevent.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


_BY_SCOPE: dict[tuple[str, ...], tuple[str, ...]] = {
    # Organizations, dashboards, Discover and release-health sessions all hang
    # off the org resource.
    ("org:read",): (
        "get_dashboard",
        "get_organization",
        "list_dashboards",
        "list_monitors",
        "list_organizations",
        "list_projects",
        "list_sessions",
        "list_teams",
        "query_discover",
    ),
    ("org:write",): (
        "create_dashboard",
        "create_monitor",
        "delete_dashboard",
    ),
    ("project:read",): (
        "get_event",
        "get_monitor",
        "get_project",
        "get_service_hook",
        "list_checkins",
        "list_project_events",
        "list_project_keys",
        "list_service_hooks",
        "list_team_projects",
    ),
    ("project:write",): (
        "add_project_to_team",
        "create_project",
        "delete_monitor",
        "remove_project_from_team",
        "update_monitor",
        "update_project",
    ),
    ("project:admin",): (
        "delete_project",
        "delete_service_hook",
    ),
    ("project:releases",): (
        "create_deploy",
        "create_release",
        "delete_release",
        "get_release",
        "list_deploys",
        "list_releases",
        "update_release",
    ),
    ("team:read",): ("get_team",),
    ("team:write",): ("create_team",),
    ("team:admin",): ("delete_team",),
    ("member:read",): ("get_member", "list_members"),
    ("member:write",): ("invite_member", "remove_member", "update_member"),
    ("event:read",): (
        "get_issue",
        "get_latest_event",
        "list_issue_events",
        "list_issues",
    ),
    ("event:write",): ("update_issue",),
    ("event:admin",): ("delete_issue",),
    # Service-hook register + deregister, both on the trigger's lifecycle.
    ("project:write", "project:admin"): ("on_alert", "on_error"),
}


_REQUIREMENTS: dict[str, ScopeRequirement] = {}
for _scopes, _ops in _BY_SCOPE.items():
    for _op in _ops:
        _REQUIREMENTS[_op] = _s(*_scopes)


SENTRY_SCOPES = ScopeRegistry(
    provider="sentry",
    requirements=_REQUIREMENTS,
    unmapped=(
        # Sentry removed the /api/alerts/ docs category; the pages for these
        # endpoints 404 today (superseded by detectors/workflows), so no current
        # published scope exists for /rules/ or /alert-rules/.
        "create_issue_alert",
        "delete_issue_alert",
        "get_issue_alert",
        "list_issue_alerts",
        "update_issue_alert",
        "create_metric_alert",
        "delete_metric_alert",
        "get_metric_alert",
        "list_metric_alerts",
        "update_metric_alert",
        # /organizations/{org}/events-stats/ is undocumented — the published
        # timeseries endpoint is now /events-timeseries/, a different path.
        "events_stats",
        # Arbitrary caller-supplied path; the scope depends on what they call.
        "raw_request",
    ),
)
