"""Notion operation → OAuth scope requirements.

Notion has no OAuth scopes. Its authorization URL takes ``client_id``,
``redirect_uri``, ``response_type`` and ``owner`` — there is no ``scope``
parameter, which is why the node's ``x-oauth-scopes`` is empty and must stay
that way.

Access is governed by two things Notion controls outside the token:

- **Capabilities** (read/update/insert content, read/insert comments, user
  information) are configured on the integration in Notion's developer portal,
  not requested per connect. They are a build-time property of the NoClick
  integration, so no operation can declare one as a scope.
- **Page-level sharing.** Even a fully capable integration sees only the pages
  and databases a user has explicitly shared with it, and "a connection's
  capabilities will never supersede a user's."

So every operation below requires authentication and nothing more, which is what
an empty ``scopes`` tuple means (same as Slack's ``auth.test``). The table is
still exhaustive: it exists so a newly added Notion operation cannot slip in
without someone re-checking that Notion still has no scopes.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

#: Notion defines no scope strings; access comes from integration capabilities
#: and page-level sharing, neither of which is expressible as a scope.
_NO_SCOPE = ScopeRequirement()

_OPERATIONS: tuple[str, ...] = (
    "append_children_to_block",
    "create_file_upload",
    "create_notion_page",
    "create_page_comment",
    "create_page_database",
    "delete_notion_block",
    "delete_page_comment",
    "fetch_block_children",
    "fetch_bot_integration_user",
    "fetch_database_metadata",
    "fetch_database_view",
    "fetch_notion_block",
    "fetch_page_comment",
    "fetch_page_properties",
    "fetch_page_property",
    "fetch_workspace_user",
    "get_async_task_status",
    "list_block_comments",
    "list_database_views",
    "list_workspace_users",
    "on_comment_created",
    "on_database_created",
    "on_database_item",
    "on_page_created",
    "on_page_updated",
    "query_notion_database",
    "search_pages_and_databases",
    "update_block_content",
    "update_database_metadata",
    "update_database_view",
    "update_page_comment",
    "update_page_properties",
)


NOTION_SCOPES = ScopeRegistry(
    provider="notion",
    requirements={operation: _NO_SCOPE for operation in _OPERATIONS},
)
