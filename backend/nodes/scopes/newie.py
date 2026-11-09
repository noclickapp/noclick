"""Scopes verified against https://api.newie.app/openapi.json (0.1.0).
Customer email search also requires read:customer_contacts per the authentication guide.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

NEWIE_SCOPES = ScopeRegistry(
    provider="newie",
    requirements={
        "get_current_user": ScopeRequirement(()),
        "get_organization": ScopeRequirement(("read:organization",)),
        "list_offerings": ScopeRequirement(("read:offerings",)),
        "get_offering": ScopeRequirement(("read:offerings",)),
        "update_offering": ScopeRequirement(("manage:offerings", "read:offerings")),
        "list_customers": ScopeRequirement(
            ("read:customers", "read:customer_contacts")
        ),
        "get_customer": ScopeRequirement(("read:customers",)),
        "update_customer": ScopeRequirement(("manage:subscriptions", "read:customers")),
        "get_customer_overview": ScopeRequirement(("read:customers",)),
        "list_purchases": ScopeRequirement(("read:purchases",)),
        "get_purchase": ScopeRequirement(("read:purchases",)),
        "list_subscriptions": ScopeRequirement(("read:subscriptions",)),
        "get_subscription": ScopeRequirement(("read:subscriptions",)),
        "update_subscription": ScopeRequirement(
            ("manage:subscriptions", "read:subscriptions")
        ),
        "list_payments": ScopeRequirement(("read:payments",)),
        "get_payment": ScopeRequirement(("read:payments",)),
        "update_payment": ScopeRequirement(("manage:payments", "read:payments")),
        "list_payouts": ScopeRequirement(("read:payouts",)),
        "get_payout": ScopeRequirement(("read:payouts",)),
        "get_offerings_report": ScopeRequirement(("read:offerings",)),
        "get_subscriptions_report": ScopeRequirement(("read:subscriptions",)),
        "get_payments_report": ScopeRequirement(("read:payments",)),
    },
    extra_scopes={"default": ("openid", "profile", "offline_access")},
)
