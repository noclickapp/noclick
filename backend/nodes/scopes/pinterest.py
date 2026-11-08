"""Pinterest requirements from the checked-in v5 OpenAPI operation catalog.

MSOT is a restricted beta granted through a Pinterest account manager. Its
scope must never be requested by the standard OAuth connection flow.
"""
from nodes.pinterest_operations import OPERATIONS

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

MSOT_TIER = "pinterest_msot_beta"
MSOT_MESSAGE = (
    "MSOT requires Pinterest restricted beta access through your Pinterest account "
    "manager and a connection granted msot:write. Standard OAuth connections do not request it."
)
PINTEREST_SCOPES = ScopeRegistry(
    provider="pinterest",
    requirements={
        name: ScopeRequirement(
            scopes=spec["scopes"],
            tier=MSOT_TIER if "msot:write" in spec["scopes"] else "standard",
            note=MSOT_MESSAGE if "msot:write" in spec["scopes"] else "",
        )
        for name, spec in OPERATIONS.items()
    },
)


def granted_scopes(credential_data):
    """Pinterest returns comma-separated grants; also accept whitespace separators."""
    return (credential_data.get("scope") or "").replace(",", " ").split()
