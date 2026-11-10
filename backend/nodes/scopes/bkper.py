"""Every Bkper v5 operation requires Google userinfo.email (official OpenAPI)."""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.bkper_operations import OPERATIONS
BKPER_SCOPES = ScopeRegistry("bkper", {
    name: ScopeRequirement(scopes=("https://www.googleapis.com/auth/userinfo.email",))
    for name in (*OPERATIONS, "on_book_event")
})
