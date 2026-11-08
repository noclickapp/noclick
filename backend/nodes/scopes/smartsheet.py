"""Smartsheet OAuth permissions from the official OAuth guide."""

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

READ = ("list_sheets", "get_sheet", "list_columns", "get_column",
        "get_row", "list_discussions", "get_discussion", "list_workspaces", "get_workspace")
WRITE = ("add_rows", "update_rows", "delete_rows", "create_discussion", "create_comment")
ADMIN = ("update_sheet", "add_column", "update_column", "delete_column")

SMARTSHEET_SCOPES = ScopeRegistry(provider="smartsheet", requirements={
    # OAuth guide: current-user identity is available regardless of access scopes.
    "get_current_user": ScopeRequirement(scopes=()),
    **{name: ScopeRequirement(scopes=("READ_SHEETS",)) for name in READ},
    **{name: ScopeRequirement(scopes=("WRITE_SHEETS",)) for name in WRITE},
    **{name: ScopeRequirement(scopes=("ADMIN_SHEETS",)) for name in ADMIN},
    "create_sheet": ScopeRequirement(scopes=("CREATE_SHEETS",)),
    "delete_sheet": ScopeRequirement(scopes=("DELETE_SHEETS",)),
})
