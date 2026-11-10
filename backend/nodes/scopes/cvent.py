"""Scopes from each selected Cvent EA operation's security declaration."""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from nodes.cvent_operations import CVENT_OPERATIONS, CVENT_POLL_TRIGGERS

_REQUIREMENTS = {
    name: ScopeRequirement(tuple(spec["scopes"]) + (
        ("event/registration-types:read",) if name in {"list_attendees", "get_attendee"} else ()))
    for name, spec in CVENT_OPERATIONS.items()
}
_REQUIREMENTS.update({
    name: ScopeRequirement(tuple(CVENT_OPERATIONS[target]["scopes"]))
    for name, target in CVENT_POLL_TRIGGERS.items()
})
CVENT_SCOPES = ScopeRegistry(
    provider="cvent", enforcement=Enforcement.STRICT, requirements=_REQUIREMENTS,
)
