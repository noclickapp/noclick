"""Bookeo permissions: https://www.bookeo.com/api/setup/."""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
FAMILIES = {"bookeo_oauth", "bookeo_api_key", "bookeo_bearer_token"}
BOOKEO_SCOPES = ScopeRegistry("bookeo", {
        **{op: ScopeRequirement((), credential_types=tuple(sorted(FAMILIES)),
            note="Settings metadata requires authentication; no separate settings scope is published.")
            for op in ("get_business", "list_products", "list_resources", "list_people_categories", "list_languages")},
        "get_key_permissions": ScopeRequirement((), credential_types=("bookeo_api_key",),
            note="API-key metadata is unavailable to Bearer/OAuth credentials."),
        "list_availability": ScopeRequirement(("availability_r",), credential_types=tuple(sorted(FAMILIES))),
        **{op: ScopeRequirement(("customers_rwd_all",), credential_types=tuple(sorted(FAMILIES)),
            note="Uses the full-account customer grant selected at connect; narrower read/own alternatives may also authorize individual methods.")
            for op in ("list_customers", "get_customer", "create_customer", "update_customer", "delete_customer")},
        **{op: ScopeRequirement(("bookings_rwd_all",), credential_types=tuple(sorted(FAMILIES)),
            note="Uses the full-account booking grant selected at connect; narrower read/own alternatives may also authorize individual methods.")
            for op in ("list_bookings", "get_booking", "cancel_booking")},
        "create_booking": ScopeRequirement(("bookings_rwd_all", "customers_rwd_all", "availability_r"),
            credential_types=tuple(sorted(FAMILIES)), note="Reads the customer and availability before reserving the fixed event."),
    })
