"""Mural public API operation scopes, from developers.mural.co/public/docs/scopes."""

from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement


def _s(scope: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=(scope,))


_GROUPS = {
    "identity:read": ("get_me",),
    "workspaces:read": ("list_workspaces",),
    "rooms:read": ("list_rooms", "get_room", "list_folders"),
    "rooms:write": ("create_room", "update_room", "delete_room", "create_folder"),
    "murals:read": ("list_room_murals", "list_workspace_murals", "get_mural",
                    "search_murals", "list_widgets", "get_widget"),
    "murals:write": ("create_mural", "duplicate_mural", "update_mural", "delete_mural",
                     "create_sticky_note", "create_sticky_notes", "update_sticky_note",
                     "delete_widget", "create_comment", "create_mural_from_template"),
    "templates:read": ("list_templates", "list_workspace_templates"),
    "templates:write": ("create_template", "delete_template"),
    "users:read": ("list_room_users",),
}

MURAL_SCOPES = ScopeRegistry(
    provider="mural",
    requirements={name: _s(scope) for scope, names in _GROUPS.items() for name in names},
    # The generic sign-in verifies the account through /users/me.
    extra_scopes={"default": ("identity:read",)},
    enforcement=Enforcement.STRICT,
)
