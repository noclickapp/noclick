"""Universe documents public as its sole standard OAuth scope.

https://developers.universe.com/docs/authorizing-with-oauth
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

UNIVERSE_SCOPES = ScopeRegistry(provider="universe", requirements={
    name: ScopeRequirement(scopes=("public",)) for name in (
        "get_current_user", "get_token_info", "list_listings", "list_guestlists",
        "list_event_guestlist", "check_in", "create_access_key", "create_rate",
        "create_percent_discount", "create_fixed_discount",
    )
})
