"""Delegated Microsoft Graph permissions for Entra directory automation.

Each requirement cites its operation's Microsoft Learn permission table.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

ROOT = "https://graph.microsoft.com/"
DOCS = "https://learn.microsoft.com/en-us/graph/api/"


def permission(scope, page):
    return ScopeRequirement(scopes=(ROOT + scope,), note=DOCS + page + "?view=graph-rest-1.0")


ENTRA_SCOPES = ScopeRegistry(
    provider="microsoft-entra-id",
    requirements={
        "get_me": permission("User.Read", "user-get"),
        **{op: permission("User.ReadWrite.All", page) for op, page in {
            "list_users": "user-list", "get_user": "user-get",
            "create_user": "user-post-users", "update_user": "user-update",
            "delete_user": "user-delete", "list_user_memberships": "user-list-memberof",
        }.items()},
        "update_user": ScopeRequirement(
            scopes=(ROOT + "User.ReadWrite.All", ROOT + "User.EnableDisableAccount.All", ROOT + "User.Read.All"),
            note=DOCS + "user-update?view=graph-rest-1.0#permissions-for-specific-scenarios",
        ),
        **{op: permission("Group.ReadWrite.All", page) for op, page in {
            "list_groups": "group-list", "get_group": "group-get",
            "create_group": "group-post-groups", "update_group": "group-update",
            "delete_group": "group-delete", "list_group_members": "group-list-members",
            "add_group_user": "group-post-members", "remove_group_member": "group-delete-members",
        }.items()},
        "list_applications": permission("Application.Read.All", "application-list"),
        "list_service_principals": permission("Application.Read.All", "serviceprincipal-list"),
        "list_organizations": permission("Organization.Read.All", "organization-list"),
        "list_subscribed_skus": permission("Organization.Read.All", "subscribedsku-list"),
    },
    extra_scopes={"default": ("offline_access",)},
)
