"""Nextdoor Publish scopes, verified against the provider's scope reference.
https://developer.nextdoor.com/reference/sharing-get-authorization-code
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

NEXTDOOR_SCOPES = ScopeRegistry(
    provider="nextdoor",
    requirements={
        "get_account": ScopeRequirement(("profile:read",)),
        "list_profiles": ScopeRequirement(("profile:read",)),
        "list_posts": ScopeRequirement(("post:read",)),
        "on_new_post": ScopeRequirement(("post:read",)),
        "on_new_comment": ScopeRequirement(("post:read",)),
        "create_post": ScopeRequirement(("post:write",)),
        "create_listing": ScopeRequirement(("post:write",)),
        "set_listing_sold": ScopeRequirement(("post:write",)),
        "edit_post": ScopeRequirement(("post:write",)),
        "delete_post": ScopeRequirement(("post:write",)),
        "set_commenting": ScopeRequirement(("post:write",)),
        "create_comment": ScopeRequirement(("comment:write",)),
        "edit_comment": ScopeRequirement(("comment:write",)),
        "delete_comment": ScopeRequirement(("comment:write",)),
        "list_agency_boundaries": ScopeRequirement(("agency.boundary:read",)),
    },
    extra_scopes={"default": ("openid",)},
)
