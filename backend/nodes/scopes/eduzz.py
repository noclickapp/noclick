"""Eduzz permission requirements from the pinned OpenAPI 2.0.0 contract.

https://developers.eduzz.com/api/openapi
These permissions are enabled on the user's app; a pasted token has no local
scope-grant claim. Eduzz enforces its granted permissions on each request.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

EDUZZ_SCOPES = ScopeRegistry(provider="eduzz", requirements={
    # "none" in the published spec is a sentinel, not a permission to request:
    # https://developers.eduzz.com/reference/api/get-accounts-v1-me
    'get_account': ScopeRequirement(()),
    'list_sales': ScopeRequirement(('myeduzz_sales_read',)),
    'get_sale': ScopeRequirement(('myeduzz_sales_read',)),
    'list_products': ScopeRequirement(('myeduzz_products_read',)),
    'get_product': ScopeRequirement(('myeduzz_products_read',)),
    'list_customers': ScopeRequirement(('myeduzz_customers_read',)),
    'get_customer': ScopeRequirement(('myeduzz_customers_read',)),
    'list_subscriptions': ScopeRequirement(('myeduzz_subscriptions_read',)),
    'get_subscription': ScopeRequirement(('myeduzz_subscriptions_read',)),
    'list_subscription_invoices': ScopeRequirement(('myeduzz_subscriptions_read',)),
    'cancel_subscriptions': ScopeRequirement(('myeduzz_subscriptions_write',)),
    'reactivate_subscription': ScopeRequirement(('myeduzz_subscriptions_write',)),
    'change_subscription_billing_day': ScopeRequirement(('myeduzz_subscriptions_write',)),
    'list_students': ScopeRequirement(('nutror_my_students_read',)),
    'get_student': ScopeRequirement(('nutror_my_students_read',)),
    'list_student_enrollments': ScopeRequirement(('nutror_my_students_read',)),
    'block_enrollment': ScopeRequirement(('nutror_my_students_write',)),
    'extend_enrollment_access': ScopeRequirement(('nutror_my_students_write',)),
    'list_schools': ScopeRequirement(('alpaclass_team_read',)),
    'create_school_student': ScopeRequirement(('alpaclass_team_write',)),
    'on_event': ScopeRequirement(('webhook_read', 'webhook_write')),
    'get_webhook_secret': ScopeRequirement(('webhook_read',)),
    'activate_webhook': ScopeRequirement(('webhook_write',)),
    'delete_webhook': ScopeRequirement(('webhook_write',)),
})
