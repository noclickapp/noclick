"""API-key scopes from Humanitix v1.30.1 x-hx-scope declarations.

https://api.humanitix.com/v1/documentation/json
These describe key permissions; no OAuth consent or token introspection exists.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

HUMANITIX_SCOPES = ScopeRegistry(provider="humanitix", requirements={
    "list_events": ScopeRequirement(scopes=("events:read",)),
    "get_event": ScopeRequirement(scopes=("events:read",)),
    "get_event_check_in_count": ScopeRequirement(scopes=("tickets:read",)),
    "list_orders": ScopeRequirement(scopes=("orders:read",)),
    "get_order": ScopeRequirement(scopes=("orders:read",)),
    "list_tickets": ScopeRequirement(scopes=("tickets:read",)),
    "get_ticket": ScopeRequirement(scopes=("tickets:read",)),
    "check_in_ticket": ScopeRequirement(scopes=("tickets:checkin",)),
    "check_out_ticket": ScopeRequirement(scopes=("tickets:checkin",)),
    "list_tags": ScopeRequirement(scopes=("events:read",)),
    "get_tag": ScopeRequirement(scopes=("events:read",)),
    "list_global_events": ScopeRequirement(scopes=("global:read",)),
    "list_global_event_dates": ScopeRequirement(scopes=("global:read",)),
})
