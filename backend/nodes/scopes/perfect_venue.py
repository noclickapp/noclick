"""Perfect Venue scopes, verified against the published v1.5.0 contract.

https://docs.perfectvenue.com/#section/Authentication/Scopes
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement, Enforcement

PERFECT_VENUE_SCOPES = ScopeRegistry(
    provider="perfect-venue",
    requirements={
        **{op: ScopeRequirement(("read",)) for op in (
            "list_venues", "get_venue", "list_events", "get_event", "get_contact")},
        **{op: ScopeRequirement(("write",)) for op in (
            "create_contact", "update_contact", "create_event", "update_event")},
        "list_contacts": ScopeRequirement(("contacts_read",)),
        "list_users": ScopeRequirement(("users_read",)),
        "get_user": ScopeRequirement(("users_read",)),
    },
    extra_scopes={"default": ("public",)},
    enforcement=Enforcement.STRICT,
)
