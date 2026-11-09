"""Operation scopes copied from https://reflect.app/openapi.json (0.1.0).

Reflect also lets users generate a personal access token from its OAuth
credentials page; this integration uses that manual token, not an OAuth flow.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

REFLECT_SCOPES = ScopeRegistry("reflect", {
    "list_graphs": ScopeRequirement(scopes=("read:graph",)),
    "get_current_user": ScopeRequirement(scopes=("read:graph", "write:graph")),
    "list_books": ScopeRequirement(scopes=("write:graph", "read:graph")),
    "list_links": ScopeRequirement(scopes=("read:graph",)),
    "create_link": ScopeRequirement(scopes=("write:graph", "read:graph")),
    "append_daily_note": ScopeRequirement(scopes=("write:graph",)),
    "create_note": ScopeRequirement(scopes=("write:graph",)),
})
