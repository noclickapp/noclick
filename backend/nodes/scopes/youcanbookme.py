"""Native API-key read families; no invented OAuth grants or entitlement."""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

YOUCANBOOKME_SCOPES = ScopeRegistry("youcanbookme", {
    operation: ScopeRequirement(credential_types=("youcanbookme_api_key",), note="Uses the current issued account API key, protected account/profile ancestry and operation admission. Team/trial entitlement is unknown.")
    for operation in ("test_connection", "get_account_scope", "list_profiles", "get_profile", "list_team_members", "get_team_member", "list_appointment_types", "get_appointment_type", "get_booking", "query_bookings")
})
