"""Fixed Join It v1 operations; filtered reads use the published memberships GET.

Pinned contract: https://dash.readme.com/api/v1/api-registry/g3cj8jymnof3z2k
"""
OPERATIONS = {
    "list_memberships": ("GET", "/memberships"),
    "get_membership": ("GET", "/memberships"),
    "find_memberships_by_email": ("GET", "/memberships"),
    "create_membership": ("POST", "/memberships"),
    "list_internal_memberships": ("GET", "/memberships_internal"),
    "list_payments": ("GET", "/payments"),
    "record_payment": ("POST", "/payments"),
    "list_membership_types": ("GET", "/membership_types"),
    "get_organization": ("GET", "/details"),
    "verify_membership": ("GET", "/verify_membership"),
}
