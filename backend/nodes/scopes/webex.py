"""User-level OAuth scopes for the Webex action catalog.

Scope reference: https://developer.webex.com/docs/integration-scopes. Admin and compliance endpoints are
excluded from the catalog, so ordinary users can authorize this grant.
"""

from __future__ import annotations

from nodes.webex_operations import WEBEX_CATALOG

from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement


_catalog = WEBEX_CATALOG
_family_scopes = {
    "Rooms": "spark:rooms", "Messages": "spark:messages",
    "Memberships": "spark:memberships", "Teams": "spark:teams",
    "Team Memberships": "spark:team_memberships",
    "People": "spark:people", "Webhooks": "spark:webhooks",
    "Meetings": "meeting:schedules", "Invitees": "meeting:schedules",
    "Recordings": "meeting:recordings",
}


def _scope_for(operation: dict) -> str:
    family = _family_scopes[operation["category"]]
    # Webex's People endpoints in this catalog are read only.
    suffix = "read" if operation["method"] == "GET" else "write"
    return f"{family}_{suffix}"


WEBEX_SCOPES = ScopeRegistry(
    provider="webex",
    requirements={
        "on_new_message": ScopeRequirement(scopes=("spark:webhooks_write", "spark:messages_read")),
        "on_meeting_ended": ScopeRequirement(scopes=("spark:webhooks_write", "meeting:schedules_read")),
        "on_new_recording": ScopeRequirement(scopes=("spark:webhooks_write", "meeting:recordings_read")),
        **{
            operation["name"]: ScopeRequirement(scopes=(_scope_for(operation),))
            for operation in _catalog["operations"]
        },
    },
    enforcement=Enforcement.STRICT,
    # Webex requires this scope for access to encrypted message content when
    # an integration constructs its own authorization URL.
    extra_scopes={"default": ("spark:kms",)},
)
