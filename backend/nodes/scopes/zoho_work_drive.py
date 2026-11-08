"""Scopes from Zoho's WorkDrive OAS v1.0 and each operation's published docs.

https://github.com/zoho/zohoworkdrive-oas/tree/e372b16eaabf43d755884cababfb867f64a0be9c/v1.0
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement

ZOHO_WORK_DRIVE_SCOPES = ScopeRegistry(
    provider="zoho_work_drive",
    requirements={
        "get_user": ScopeRequirement(("WorkDrive.users.READ",)),
        "list_teams": ScopeRequirement(("WorkDrive.users.READ",)),
        "get_team": ScopeRequirement(("WorkDrive.team.READ",)),
        "list_team_folders": ScopeRequirement(("WorkDrive.teamfolders.READ",)),
        "get_team_folder": ScopeRequirement(("WorkDrive.teamfolders.READ",)),
        **{op: ScopeRequirement(("WorkDrive.files.READ",)) for op in (
            "list_files", "get_file", "list_versions", "list_comments", "list_links")},
        **{op: ScopeRequirement(("WorkDrive.files.CREATE",)) for op in (
            "create_folder", "copy_file")},
        **{op: ScopeRequirement(("WorkDrive.files.UPDATE",)) for op in (
            "rename_file", "move_file", "trash_file", "restore_file")},
        "get_comment": ScopeRequirement(("WorkDrive.comments.READ",)),
        "create_comment": ScopeRequirement(("WorkDrive.comments.CREATE",)),
        "edit_comment": ScopeRequirement(("WorkDrive.comments.UPDATE",)),
        "delete_comment": ScopeRequirement(("WorkDrive.comments.DELETE",)),
        "get_link": ScopeRequirement(("WorkDrive.links.READ",)),
        "revoke_link": ScopeRequirement(("WorkDrive.links.DELETE",)),
        "search_files": ScopeRequirement(("ZohoSearch.securesearch.READ", "WorkDrive.team.READ")),
    },
    enforcement=Enforcement.STRICT,
)
