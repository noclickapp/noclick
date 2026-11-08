"""Miro REST API board scopes. https://developers.miro.com/docs/add-permission-scopes-to-your-app"""

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.miro_operations import OPERATIONS as BOARD_API_OPERATIONS


READ_OPERATIONS = (
    "get_token_context", "list_boards", "get_board", "list_board_members",
    "list_items", "get_item", "list_tags", "get_tag", "list_item_tags",
)
WRITE_OPERATIONS = (
    "create_board", "update_board", "delete_board", "share_board",
    "create_sticky_note", "update_sticky_note", "create_card", "update_card",
    "create_text", "delete_item", "create_tag", "attach_tag", "remove_tag",
)

MIRO_SCOPES = ScopeRegistry(
    provider="miro",
    requirements={
        **{name: ScopeRequirement(scopes=("boards:read",)) for name in READ_OPERATIONS},
        **{name: ScopeRequirement(scopes=("boards:write",)) for name in WRITE_OPERATIONS},
        **{name: ScopeRequirement(scopes=("boards:read" if op.method == "GET" else "boards:write",))
           for name, op in BOARD_API_OPERATIONS.items()},
    },
)
