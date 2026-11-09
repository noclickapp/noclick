"""Bitly grants access without named scopes.
https://dev.bitly.com/docs/getting-started/authentication/
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.bitly_operations import OPERATIONS


BITLY_SCOPES = ScopeRegistry(provider="bitly", requirements={
    name: ScopeRequirement() for name in (*OPERATIONS,
        "get_user", "list_groups", "get_group", "list_bitlinks", "shorten_link",
        "create_bitlink", "get_bitlink", "update_bitlink", "delete_bitlink",
        "expand_link", "get_engagements", "get_countries", "get_platform_limits", "on_engagement")
})
