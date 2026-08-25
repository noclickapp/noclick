"""monday.com operation → OAuth scope requirements.

Verified against the per-query "Required scope" lines in monday.com's API
reference (developer.monday.com/api-reference). monday mints one token and its
scopes follow a flat ``<resource>:<action>`` shape, so each operation maps to
the scope of the GraphQL query or mutation its handler sends.

Two things are not obvious from the operation names:

- **Scope follows the resource being touched, not the object named in the
  operation.** ``create_or_get_tag`` is a ``boards:write`` mutation even though
  reading tags is ``tags:read``; folders live under ``workspaces:*``, not a
  folders scope of their own; and subitems, groups and columns are all just
  board data.
- **Some handlers span two resources.** ``get_updates`` reads updates through
  an ``items`` query, so it needs both ``boards:read`` and ``updates:read``.

``account:read`` is requested but no operation here needs it; ``Enforcement.SUBSET``
leaves it alone rather than dropping a scope live credentials already hold.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- boards, groups, columns, items, subitems: all board data ---------
    "get_board": _s("boards:read"),
    "list_boards": _s("boards:read"),
    "list_groups": _s("boards:read"),
    "get_items": _s("boards:read"),
    "list_items": _s("boards:read"),
    "get_subitems": _s("boards:read"),
    "query_items_by_column": _s("boards:read"),
    "create_board": _s("boards:write"),
    "update_board": _s("boards:write"),
    "archive_board": _s("boards:write"),
    "delete_board": _s("boards:write"),
    "duplicate_board": _s("boards:write"),
    "create_group": _s("boards:write"),
    "update_group": _s("boards:write"),
    "archive_group": _s("boards:write"),
    "delete_group": _s("boards:write"),
    "duplicate_group": _s("boards:write"),
    "create_column": _s("boards:write"),
    "rename_column": _s("boards:write"),
    "delete_column": _s("boards:write"),
    "change_column_value": _s("boards:write"),
    "change_simple_column_value": _s("boards:write"),
    "change_multiple_column_values": _s("boards:write"),
    "create_item": _s("boards:write"),
    "create_subitem": _s("boards:write"),
    "duplicate_item": _s("boards:write"),
    "archive_item": _s("boards:write"),
    "delete_item": _s("boards:write"),
    "move_item_to_group": _s("boards:write"),
    "move_item_to_board": _s("boards:write"),
    # Board subscriber mutations are board writes (documented on the Users page).
    "add_users_to_board": _s("boards:write"),
    "remove_users_from_board": _s("boards:write"),
    # Tags are read with tags:read but minted through a board write.
    "create_or_get_tag": _s("boards:write"),

    # -- workspaces and folders -------------------------------------------
    "list_workspaces": _s("workspaces:read"),
    "create_workspace": _s("workspaces:write"),
    "update_workspace": _s("workspaces:write"),
    "delete_workspace": _s("workspaces:write"),
    "list_folders": _s("workspaces:read"),
    "create_folder": _s("workspaces:write"),
    "update_folder": _s("workspaces:write"),
    "delete_folder": _s("workspaces:write"),

    # -- updates -----------------------------------------------------------
    # Reads the `updates` field through an `items` query, so both apply.
    "get_updates": _s("boards:read", "updates:read"),
    "create_update": _s("updates:write"),
    "edit_update": _s("updates:write"),
    "delete_update": _s("updates:write"),
    "like_update": _s("updates:write"),
    "unlike_update": _s("updates:write"),
    # The Updates page documents updates:write for clear_item_updates while the
    # Items page documents boards:write for the same mutation; require both.
    "clear_item_updates": _s("boards:write", "updates:write"),

    # -- docs ---------------------------------------------------------------
    "get_docs": _s("docs:read"),
    "create_doc": _s("docs:write"),
    "create_doc_block": _s("docs:write"),
    "update_doc_block": _s("docs:write"),
    "delete_doc_block": _s("docs:write"),

    # -- people: users, teams, self ----------------------------------------
    "get_me": _s("me:read"),
    "list_users": _s("users:read"),
    "get_teams": _s("teams:read"),
    "create_team": _s("teams:write"),
    "delete_team": _s("teams:write"),
    "add_users_to_team": _s("teams:write"),
    "remove_users_from_team": _s("teams:write"),

    # -- assets, tags, notifications ---------------------------------------
    "get_assets": _s("assets:read"),
    "get_tags": _s("tags:read"),
    "create_notification": _s("notifications:write"),

    # -- webhooks (the trigger registers/deletes one per board) ------------
    "list_webhooks": _s("webhooks:read"),
    "create_webhook": _s("webhooks:write"),
    "delete_webhook": _s("webhooks:write"),
    "on_board_event": _s("webhooks:write", "boards:read"),
}

MONDAY_SCOPES = ScopeRegistry(
    provider="monday",
    requirements=_REQUIREMENTS,
    unmapped=(
        # monday documents `boards:write` for the other board-subscriber
        # mutations but publishes no "Required scope" line for this one.
        "add_teams_to_board",
    ),
)
