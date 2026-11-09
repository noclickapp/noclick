"""Teamwork API access is bounded by installation and user permissions, not scopes.

The Teamwork app login flow issues a permanent installation-bound token; the
developer portal selects Projects as a product instead of per-endpoint OAuth
scopes. The catalog is the operation coverage ratchet for this node.
"""

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.teamwork_operations import OPERATIONS

TEAMWORK_SCOPES = ScopeRegistry(
    provider="teamwork",
    requirements={
        name: ScopeRequirement()
        for name in (
            *OPERATIONS,
            "on_project_created",
            "on_tasklist_created",
            "on_tasklist_updated",
            "on_time_created",
            "on_time_updated",
        )
    },
)
