"""API-key access requirements for eSputnik's read operations."""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement

ESPUTNIK_SCOPES = ScopeRegistry(
    provider="esputnik",
    enforcement=Enforcement.STRICT,
    requirements={
        operation: ScopeRequirement(
            scopes=(),
            credential_types=("esputnik_api_key",),
            note="HTTP Basic API key; access is determined by the provider, without OAuth scopes.",
        )
        for operation in (
            "get_account_info", "get_additional_fields", "search_contacts",
            "get_contact", "list_broadcasts", "get_broadcast",
        )
    },
)
