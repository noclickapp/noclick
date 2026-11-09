"""Scopes from each selected Cvent EA operation's security declaration."""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from nodes.cvent_operations import CVENT_OPERATIONS

CVENT_SCOPES = ScopeRegistry(
    provider="cvent", enforcement=Enforcement.STRICT,
    requirements={name: ScopeRequirement(tuple(spec["scopes"]) + (("event/registration-types:read",) if name in {"list_attendees", "get_attendee"} else ())) for name, spec in CVENT_OPERATIONS.items()},
)
