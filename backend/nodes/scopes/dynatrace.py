"""Account API token scopes from https://api.dynatrace.com/openapi.json (1.0).

Keeping per-action scopes here makes connection evidence explain access accurately.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

DYNATRACE_SCOPES = ScopeRegistry(
    provider="dynatrace",
    extra_scopes={"default": ("openid", "profile", "offline_access")},
    requirements={
        "list_users": ScopeRequirement(scopes=('account-idm-read',)),
        "create_user": ScopeRequirement(scopes=('account-idm-write',)),
        "get_user_groups": ScopeRequirement(scopes=('account-idm-read',)),
        "add_user_to_groups": ScopeRequirement(scopes=('account-idm-write',)),
        "remove_user": ScopeRequirement(scopes=('account-idm-write',)),
        "replace_user_groups": ScopeRequirement(scopes=('account-idm-write',)),
        "remove_user_from_groups": ScopeRequirement(scopes=('account-idm-write',)),
        "list_groups": ScopeRequirement(scopes=('account-idm-read',)),
        "create_group": ScopeRequirement(scopes=('account-idm-write',)),
        "update_group": ScopeRequirement(scopes=('account-idm-write',)),
        "delete_group": ScopeRequirement(scopes=('account-idm-write',)),
        "list_group_members": ScopeRequirement(scopes=('account-idm-read',)),
        "list_policies": ScopeRequirement(scopes=('iam-policies-management',)),
        "get_policy": ScopeRequirement(scopes=('iam-policies-management',)),
        "create_policy": ScopeRequirement(scopes=('iam-policies-management',)),
        "update_policy": ScopeRequirement(scopes=('iam-policies-management',)),
        "delete_policy": ScopeRequirement(scopes=('iam-policies-management',)),
        "list_environments": ScopeRequirement(scopes=('account-env-read',)),
        "list_subscriptions": ScopeRequirement(scopes=('account-uac-read',)),
        "get_subscription": ScopeRequirement(scopes=('account-uac-read',)),
        "list_audit_logs": ScopeRequirement(scopes=('account-audit-logs-read',)),
        "on_new_audit_event": ScopeRequirement(scopes=('account-audit-logs-read',)),
    },
)
