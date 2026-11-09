"""PreciseFP scopes follow the provider's current published API reference.

The identity endpoint now requires login, whereas the older Swagger says users.
Source: https://app.precisefp.com/docs/api/#operation--user-get
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

PRECISEFP_SCOPES = ScopeRegistry(provider="precisefp", requirements={
    "get_current_user": ScopeRequirement(scopes=("login",)),
    "list_accounts": ScopeRequirement(scopes=("accounts",)),
    "get_account": ScopeRequirement(scopes=("accounts",)),
    "create_account": ScopeRequirement(scopes=("accounts",)),
    "update_account": ScopeRequirement(scopes=("accounts",)),
    "delete_account": ScopeRequirement(scopes=("accounts",)),
    "get_account_member": ScopeRequirement(scopes=("accounts",)),
    "list_contacts": ScopeRequirement(scopes=("accounts",)),
    "get_contact": ScopeRequirement(scopes=("accounts",)),
    "create_contact": ScopeRequirement(scopes=("accounts",)),
    "update_contact": ScopeRequirement(scopes=("accounts",)),
    "delete_contact": ScopeRequirement(scopes=("accounts",)),
    "list_assets": ScopeRequirement(scopes=("accounts",)),
    "list_liabilities": ScopeRequirement(scopes=("accounts",)),
    "list_goals": ScopeRequirement(scopes=("accounts",)),
    "list_family": ScopeRequirement(scopes=("accounts",)),
    "list_insurance": ScopeRequirement(scopes=("accounts",)),
    "list_documents": ScopeRequirement(scopes=("accounts",)),
})
