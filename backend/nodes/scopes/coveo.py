"""API-key family admission; provider privileges are checked from the current token."""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

OPERATIONS = ("test_connection", "get_organization", "list_sources", "get_source", "list_source_item_types", "list_source_schedules", "list_fields", "get_field", "search", "query_facets", "full_refresh_source", "incremental_refresh_source", "rebuild_source", "pause_source_refresh", "resume_source_refresh", "set_push_source_status")
COVEO_SCOPES = ScopeRegistry("coveo", {
    op: ScopeRequirement(credential_types=("coveo_api_key",), note="Actual saved organization/API key, protected endpoint permission and current policy required; no OAuth identity, guessed grants or entitlement.")
    for op in OPERATIONS
})
