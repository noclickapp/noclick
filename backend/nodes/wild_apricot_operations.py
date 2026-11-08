"""Wild Apricot Member/Public View API 9.08.0 operation boundaries.

Contract: https://api.wildapricot.org/ui/swagger/publicAccess
Every entry is exactly one API operation; no user-supplied URLs are accepted.
"""

OPERATIONS = {
    "list_accounts": ("GET", "/accounts"),
    "get_account": ("GET", "/accounts/{account_id}"),
    "list_contacts": ("GET", "/accounts/{account_id}/contacts"),
    "get_contact": ("GET", "/accounts/{account_id}/contacts/{contact_id}"),
    "get_my_contact": ("GET", "/accounts/{account_id}/contacts/me"),
    "update_my_contact": ("PUT", "/accounts/{account_id}/contacts/me"),
    "get_contact_fields": ("GET", "/accounts/{account_id}/contactfields"),
    "list_membership_levels": ("GET", "/accounts/{account_id}/membershiplevels"),
    "list_events": ("GET", "/accounts/{account_id}/events"),
    "get_event": ("GET", "/accounts/{account_id}/events/{event_id}"),
    "list_registrations": ("GET", "/accounts/{account_id}/eventregistrations"),
    "get_registration": ("GET", "/accounts/{account_id}/eventregistrations/{registration_id}"),
    "create_registration": ("POST", "/accounts/{account_id}/eventregistrations"),
    "delete_registration": ("DELETE", "/accounts/{account_id}/eventregistrations/{registration_id}"),
    "calculate_registration_costs": ("POST", "/rpc/{account_id}/CalculateEventRegistrationCosts"),
    "verify_registration_code": ("POST", "/rpc/{account_id}/verifyEventRegistrationCode"),
    "cancel_registration": ("POST", "/rpc/{account_id}/CancelEventRegistration"),
    "list_invoices": ("GET", "/accounts/{account_id}/invoices"),
    "list_payments": ("GET", "/accounts/{account_id}/payments"),
}
