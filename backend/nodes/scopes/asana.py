"""Asana operation → OAuth scope requirements.

Asana's OAuth model has two mutually exclusive modes, and this app uses the
first: an app registered with **Full permissions** authorizes with the single
``default`` scope, which Asana documents as access to every endpoint the
authorizing user can reach. The alternative — granular ``<resource>:<action>``
scopes (``tasks:read``, ``projects:write``, …) — cannot be combined with Full
permissions, and Asana states that "scopes are not yet available for every
Asana API endpoint", so several operations here would have no granular
equivalent to declare.

That makes the table flat by construction: every operation requires exactly
``default``, and there is no scope this node calls but never requests. The
value of listing them individually is the ratchet — a new operation added
without an entry shows up as uncovered rather than silently inheriting a
blanket grant. If this app ever migrates to granular scopes, this file is where
the per-operation split gets written, and the coverage test will name every
operation that still needs one.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

#: Asana's "Full permissions" scope — access to every endpoint the user can reach.
FULL_ACCESS = "default"

#: Every operation the node dispatches. Asana's PAT credential is unscoped and
#: the OAuth credential holds `default`, so all of them resolve identically.
_OPERATIONS: tuple[str, ...] = (
    "add_comment",
    "add_custom_field_to_project",
    "add_followers",
    "add_goal_followers",
    "add_portfolio_item",
    "add_portfolio_members",
    "add_project_followers",
    "add_project_member",
    "add_tag_to_task",
    "add_task_dependencies",
    "add_task_dependents",
    "add_task_to_project",
    "add_task_to_section",
    "add_team_member",
    "add_workspace_user",
    "create_custom_field",
    "create_goal",
    "create_portfolio",
    "create_project",
    "create_project_brief",
    "create_project_from_template",
    "create_project_status",
    "create_section",
    "create_status_update",
    "create_subtask",
    "create_tag",
    "create_task",
    "create_task_from_template",
    "create_time_tracking_entry",
    "delete_attachment",
    "delete_custom_field",
    "delete_goal",
    "delete_portfolio",
    "delete_project",
    "delete_project_brief",
    "delete_project_status",
    "delete_section",
    "delete_status_update",
    "delete_story",
    "delete_tag",
    "delete_task",
    "delete_time_tracking_entry",
    "duplicate_project",
    "duplicate_task",
    "get_custom_field",
    "get_goal",
    "get_goal_parent_goals",
    "get_job",
    "get_me",
    "get_portfolio",
    "get_portfolio_items",
    "get_project",
    "get_project_brief",
    "get_project_custom_fields",
    "get_project_members",
    "get_project_statuses",
    "get_project_task_counts",
    "get_section",
    "get_section_tasks",
    "get_status_updates",
    "get_story",
    "get_tag",
    "get_tags_for_task",
    "get_task",
    "get_task_attachments",
    "get_task_dependencies",
    "get_task_dependents",
    "get_task_projects",
    "get_tasks_for_tag",
    "get_team",
    "get_team_members",
    "get_time_tracking_entries",
    "get_user",
    "get_user_task_list",
    "get_user_task_list_tasks",
    "list_comments",
    "list_custom_fields",
    "list_goals",
    "list_portfolios",
    "list_project_tasks",
    "list_project_templates",
    "list_projects",
    "list_sections",
    "list_subtasks",
    "list_tags",
    "list_task_templates",
    "list_teams",
    "list_users",
    "list_workspace_members",
    "list_workspaces",
    "on_resource_change",
    "remove_custom_field_from_project",
    "remove_followers",
    "remove_goal_followers",
    "remove_portfolio_item",
    "remove_portfolio_members",
    "remove_project_followers",
    "remove_project_member",
    "remove_tag_from_task",
    "remove_task_dependencies",
    "remove_task_dependents",
    "remove_task_from_project",
    "remove_team_member",
    "remove_workspace_user",
    "save_project_as_template",
    "search_tasks",
    "set_goal_metric",
    "set_task_custom_field",
    "set_task_parent",
    "trigger_rule",
    "typeahead_search",
    "update_custom_field",
    "update_goal",
    "update_goal_metric",
    "update_portfolio",
    "update_project",
    "update_project_brief",
    "update_section",
    "update_story",
    "update_tag",
    "update_task",
    "update_time_tracking_entry",
)

_REQUIREMENTS = {
    operation: ScopeRequirement(scopes=(FULL_ACCESS,)) for operation in _OPERATIONS
}

ASANA_SCOPES = ScopeRegistry(
    provider="asana",
    requirements=_REQUIREMENTS,
)
