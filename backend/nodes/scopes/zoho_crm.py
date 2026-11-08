"""Zoho CRM V8 scope map from the official endpoint reference."""

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


ZOHO_CRM_SCOPES = ScopeRegistry(
    provider="zoho_crm",
    requirements={
        "list_modules": ScopeRequirement(scopes=("ZohoCRM.settings.modules.READ",)),
        "list_fields": ScopeRequirement(scopes=("ZohoCRM.settings.fields.READ",)),
        "get_current_user": ScopeRequirement(scopes=("ZohoCRM.users.READ",)),
        "list_records": ScopeRequirement(scopes=("ZohoCRM.modules.ALL",)),
        "get_record": ScopeRequirement(scopes=("ZohoCRM.modules.ALL",)),
        "search_records": ScopeRequirement(scopes=("ZohoCRM.modules.ALL", "ZohoSearch.securesearch.READ")),
        "create_record": ScopeRequirement(scopes=("ZohoCRM.modules.ALL",)),
        "update_record": ScopeRequirement(scopes=("ZohoCRM.modules.ALL",)),
        "upsert_record": ScopeRequirement(scopes=("ZohoCRM.modules.ALL",)),
        "delete_record": ScopeRequirement(scopes=("ZohoCRM.modules.ALL",)),
    },
)
