"""TidyHQ grants access through organisation roles, with no named OAuth scopes.

https://docs.tidyhq.com/guides/getting-started
https://api.tidyhq.com/v2/openapi.json (empty scopes in each OAuth flow).
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

TIDY_SCOPES = ScopeRegistry(provider="tidy", requirements={
    "get_current_contact": ScopeRequirement(()),
    "get_organization": ScopeRequirement(()),
    "list_contacts": ScopeRequirement(()),
    "get_contact": ScopeRequirement(()),
    "create_contact": ScopeRequirement(()),
    "update_contact": ScopeRequirement(()),
    "delete_contact": ScopeRequirement(()),
    "list_groups": ScopeRequirement(()),
    "get_group": ScopeRequirement(()),
    "list_memberships": ScopeRequirement(()),
    "get_membership": ScopeRequirement(()),
    "list_subscriptions": ScopeRequirement(()),
    "get_subscription": ScopeRequirement(()),
    "list_membership_subscriptions": ScopeRequirement(()),
    "create_membership_subscription": ScopeRequirement(()),
    "update_membership_subscription": ScopeRequirement(()),
    "list_membership_levels": ScopeRequirement(()),
    "get_membership_level": ScopeRequirement(()),
    "list_events": ScopeRequirement(()),
    "get_event": ScopeRequirement(()),
    "list_invoices": ScopeRequirement(()),
    "get_invoice": ScopeRequirement(()),
})
