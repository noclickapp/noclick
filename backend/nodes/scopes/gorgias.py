"""Gorgias operation scope requirements from the documented resource families.

Gorgias groups OAuth scopes by resource and read/write access. A few REST
families (files, phone, widgets, metric cards, and search) have no dedicated
scope; their requirements here use the resource family they expose. The
Gorgias server remains authoritative and may further restrict an app.
"""

from __future__ import annotations

from nodes.gorgias_operations import CATALOG

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

_OPERATIONS = CATALOG["operations"]

_RESOURCE = {
    "Account": "account",
    "Custom Fields": "custom_fields",
    "Customers": "customers",
    "Events": "events",
    "Files": "tickets",
    "Integrations": "integrations",
    "Jobs": "jobs",
    "Macros": "macros",
    "Metric Cards": "statistics",
    "Reporting Statistics": "statistics",
    "Rules": "rules",
    "Satisfaction Surveys": "satisfaction_survey",
    "Search": "tickets",
    "Statistics": "statistics",
    "Tags": "tags",
    "Teams": "users",
    "Ticket Messages": "tickets",
    "Tickets": "tickets",
    "Users": "users",
    "Views": "tickets",
    "Voice Call Events": "tickets",
    "Voice Call Recordings": "tickets",
    "Voice Calls": "tickets",
    "Widgets": "integrations",
}


def _scopes(op: dict) -> tuple[str, ...]:
    resource = _RESOURCE[op["category"]]
    mode = "read" if op["method"] == "GET" else "write"
    # Gorgias only publishes a statistics:read scope. Feedback is a write to
    # metric cards, but the API has no corresponding statistics:write scope.
    if resource == "statistics":
        return ("statistics:read",)
    if op["category"] == "Search":
        return ("tickets:read", "customers:read", "users:read")
    return (f"{resource}:{mode}",)


GORGIAS_SCOPES = ScopeRegistry(
    provider="gorgias",
    requirements={op["name"]: ScopeRequirement(scopes=_scopes(op)) for op in _OPERATIONS},
    extra_scopes={"default": ("openid", "email", "profile", "offline")},
)
