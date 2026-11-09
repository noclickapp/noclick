"""Permissions for the PowerPoint drive-item operations.

Files.ReadWrite.All is the existing reusable Microsoft drive sign-in grant.
Reference: https://learn.microsoft.com/en-us/graph/permissions-reference#filesreadwriteall
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

POWERPOINT_SCOPES = ScopeRegistry(
    provider="microsoft-powerpoint",
    requirements={
        "get_account": ScopeRequirement(("https://graph.microsoft.com/User.Read",)),
        **{operation: ScopeRequirement(("https://graph.microsoft.com/Files.ReadWrite.All",)) for operation in (
            "get_my_drive", "get_root_folder", "list_presentations", "get_presentation",
            "rename_presentation", "move_presentation", "copy_presentation", "delete_presentation",
            "preview_presentation", "create_share_link", "list_permissions", "get_permission",
            "update_permission", "delete_permission", "list_versions", "get_version",
            "restore_version", "list_thumbnails",
        )},
    },
)
