"""Jira operation → OAuth scope requirements.

Derived from Atlassian's published OpenAPI specs — the Jira platform
(``swagger-v3.v3.json``) and Jira Software / Agile (``swagger.v3.json``)
documents — by resolving each operation's handler to the REST endpoint it calls
and reading that endpoint's ``security`` entry. Every scope here is Atlassian's
own declaration, not an inference.

Jira mints ONE token, so there is a single variant. Two scope families coexist
on it:

- **Classic** (``read:jira-work``, ``write:jira-work``, ``read:jira-user``,
  ``manage:jira-project``, ``manage:jira-configuration``,
  ``manage:jira-webhook``) — what the platform REST v3 endpoints declare.
- **Granular** (``read:board-scope:jira-software``, ``read:sprint:jira-software``,
  …) — what the Agile endpoints declare. A classic scope does NOT cover them,
  which is why the node requests both sets.

``manage:jira-configuration`` is the gap this table exposed: 52 operations
declare it and the node did not request it, so they could only ever return 403.
They are now mapped, which pulls the scope into the derived connect request —
existing credentials must be reconnected before those operations work.

The connect-time request is DERIVED from this table (``JIRA_REQUESTED_SCOPES``)
and consumed by ``JiraOAuthCredential``'s ``x-oauth-scopes`` and by
``nodes.oauth.atlassian_oauth.JIRA_WORKFLOW_SCOPES``, so the requested list
cannot drift from the operations that need it. ``offline_access`` is the one
scope no endpoint implies — it governs refresh-token issuance — so it is
declared as an ``extra_scopes`` entry rather than hung off an operation.

This table also replaces ``JiraNode._required_oauth_scopes_for_operation``: the
runtime pre-flight in ``_ensure_operation_scopes`` now looks the operation up
here instead of running an isinstance chain over a dozen Agile config classes,
so there is one source of truth for "what does this operation need".
"""

from __future__ import annotations

from nodes.core.oauth_scopes import DEFAULT_VARIANT, ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- read: issues, projects, versions, components, filters, dashboards, worklogs --
    "check_user_permissions": _s("read:jira-work"),
    "download_attachment": _s("read:jira-work"),
    "get_attachment_human_readable": _s("read:jira-work"),
    "get_attachment_metadata": _s("read:jira-work"),
    "get_component": _s("read:jira-work"),
    "get_component_issue_count": _s("read:jira-work"),
    "get_current_user_permissions": _s("read:jira-work"),
    "get_dashboard": _s("read:jira-work"),
    "get_filter": _s("read:jira-work"),
    "get_issue": _s("read:jira-work"),
    "get_issue_changelog": _s("read:jira-work"),
    "get_issue_comment": _s("read:jira-work"),
    "get_issue_labels": _s("read:jira-work"),
    "get_issue_link": _s("read:jira-work"),
    "get_issue_link_type": _s("read:jira-work"),
    "get_issue_property": _s("read:jira-work"),
    "get_issue_type": _s("read:jira-work"),
    "get_issue_votes": _s("read:jira-work"),
    "get_jql_autocomplete_suggestions": _s("read:jira-work"),
    "get_permission_scheme": _s("read:jira-work"),
    "get_priority": _s("read:jira-work"),
    "get_project_category": _s("read:jira-work"),
    "get_project_role": _s("read:jira-work"),
    "get_resolution": _s("read:jira-work"),
    "get_status": _s("read:jira-work"),
    "get_version": _s("read:jira-work"),
    "get_version_issue_counts": _s("read:jira-work"),
    "get_version_unresolved_count": _s("read:jira-work"),
    "get_worklog": _s("read:jira-work"),
    "list_dashboards": _s("read:jira-work"),
    "list_deleted_worklog_ids": _s("read:jira-work"),
    "list_fields": _s("read:jira-work"),
    "list_issue_attachments": _s("read:jira-work"),
    "list_issue_comments": _s("read:jira-work"),
    "list_issue_link_types": _s("read:jira-work"),
    "list_issue_property_keys": _s("read:jira-work"),
    "list_issue_remote_links": _s("read:jira-work"),
    "list_issue_transitions": _s("read:jira-work"),
    "list_issue_types": _s("read:jira-work"),
    "list_issue_watchers": _s("read:jira-work"),
    "list_issue_worklogs": _s("read:jira-work"),
    "list_permission_schemes": _s("read:jira-work"),
    "list_priorities": _s("read:jira-work"),
    "list_project_avatars": _s("read:jira-work"),
    "list_project_categories": _s("read:jira-work"),
    "list_project_components": _s("read:jira-work"),
    "list_project_issue_types": _s("read:jira-work"),
    "list_project_roles": _s("read:jira-work"),
    "list_project_versions": _s("read:jira-work"),
    "list_projects": _s("read:jira-work"),
    "list_resolutions": _s("read:jira-work"),
    "list_statuses": _s("read:jira-work"),
    "list_updated_worklog_ids": _s("read:jira-work"),
    "list_worklog_property_keys": _s("read:jira-work"),
    "search_filters": _s("read:jira-work"),
    "search_issues_with_jql": _s("read:jira-work"),
    "search_projects": _s("read:jira-work"),
    "validate_jql_query": _s("read:jira-work"),

    # -- write: issues, comments, worklogs, attachments, filters, dashboards --
    "add_attachment_to_issue": _s("write:jira-work"),
    "add_comment_to_issue": _s("write:jira-work"),
    "add_vote_to_issue": _s("write:jira-work"),
    "add_watcher_to_issue": _s("write:jira-work"),
    "add_worklog_to_issue": _s("write:jira-work"),
    "assign_issue_to_user": _s("write:jira-work"),
    "bulk_create_issues": _s("write:jira-work"),
    "bulk_delete_issues": _s("write:jira-work"),
    "bulk_update_issues": _s("write:jira-work"),
    "create_dashboard": _s("write:jira-work"),
    "create_issue": _s("write:jira-work"),
    "create_jql_filter": _s("write:jira-work"),
    "create_remote_link_on_issue": _s("write:jira-work"),
    "delete_attachment": _s("write:jira-work"),
    "delete_dashboard": _s("write:jira-work"),
    "delete_filter": _s("write:jira-work"),
    "delete_issue": _s("write:jira-work"),
    "delete_issue_comment": _s("write:jira-work"),
    "delete_issue_link": _s("write:jira-work"),
    "delete_issue_property": _s("write:jira-work"),
    "delete_remote_link": _s("write:jira-work"),
    "delete_user_property": _s("write:jira-work"),
    "delete_worklog": _s("write:jira-work"),
    "link_two_issues": _s("write:jira-work"),
    "remove_vote_from_issue": _s("write:jira-work"),
    "remove_watcher_from_issue": _s("write:jira-work"),
    "replace_issue_labels": _s("write:jira-work"),
    "send_issue_notification": _s("write:jira-work"),
    "set_issue_property": _s("write:jira-work"),
    "set_user_property": _s("write:jira-work"),
    "transition_issue_status": _s("write:jira-work"),
    "update_dashboard": _s("write:jira-work"),
    "update_filter": _s("write:jira-work"),
    "update_issue": _s("write:jira-work"),
    "update_issue_comment": _s("write:jira-work"),
    "update_worklog": _s("write:jira-work"),

    # -- project-level administration: components, versions, screens, roles --
    "archive_project": _s("manage:jira-project"),
    "create_project_category": _s("manage:jira-project"),
    "create_project_component": _s("manage:jira-project"),
    "create_project_version": _s("manage:jira-project"),
    "delete_component": _s("manage:jira-project"),
    "delete_project_category": _s("manage:jira-project"),
    "delete_version": _s("manage:jira-project"),
    "get_issue_security_scheme": _s("manage:jira-project"),
    "get_screen": _s("manage:jira-project"),
    "list_issue_security_schemes": _s("manage:jira-project"),
    "list_screen_tab_fields": _s("manage:jira-project"),
    "list_screen_tabs": _s("manage:jira-project"),
    "list_screens": _s("manage:jira-project"),
    "list_workflows": _s("manage:jira-project"),
    "merge_project_versions": _s("manage:jira-project"),
    "move_version_position": _s("manage:jira-project"),
    "remove_actors_from_project_role": _s("manage:jira-project"),
    "update_component": _s("manage:jira-project"),
    "update_project_category": _s("manage:jira-project"),
    "update_version": _s("manage:jira-project"),

    # -- user and group directory reads --
    "get_current_user": _s("read:jira-user"),
    "get_global_configuration": _s("read:jira-user"),
    "get_group": _s("read:jira-user"),
    "get_user": _s("read:jira-user"),
    "get_user_property": _s("read:jira-user"),
    "list_groups": _s("read:jira-user"),
    "list_user_groups": _s("read:jira-user"),
    "list_user_properties": _s("read:jira-user"),
    "search_users": _s("read:jira-user"),

    # -- webhook triggers — register/refresh/delete via POST /rest/api/3/webhook --
    "on_comment_added": _s("manage:jira-webhook", "read:jira-work"),
    "on_issue_created": _s("manage:jira-webhook", "read:jira-work"),
    "on_issue_deleted": _s("manage:jira-webhook", "read:jira-work"),
    "on_issue_updated": _s("manage:jira-webhook", "read:jira-work"),

    # -- Jira Software (Agile): boards, sprints, epics. Granular scopes only;
    #    the classic read:jira-work does not cover /rest/agile/1.0. --
    "get_board": _s("read:board-scope:jira-software", "read:issue-details:jira"),
    "get_board_backlog": _s(
        "read:board-scope:jira-software",
        "read:issue-details:jira",
    ),
    "list_board_issues": _s(
        "read:board-scope:jira-software",
        "read:issue-details:jira",
    ),

    "create_sprint": _s("write:sprint:jira-software"),
    "move_issues_to_sprint": _s("write:sprint:jira-software"),
    "update_sprint": _s("write:sprint:jira-software"),
    "get_sprint": _s("read:sprint:jira-software"),
    "list_board_sprints": _s("read:sprint:jira-software"),

    "delete_sprint": _s("delete:sprint:jira-software"),
    "list_boards": _s("read:board-scope:jira-software", "read:project:jira"),
    "get_epic": _s("read:epic:jira-software"),
    "list_epic_issues": _s(
        "read:epic:jira-software",
        "read:issue-details:jira",
        "read:jql:jira",
    ),
    "list_sprint_issues": _s(
        "read:issue-details:jira",
        "read:jql:jira",
        "read:sprint:jira-software",
    ),

    # -- endpoints spanning two scope families --
    "get_project": _s("read:jira-user", "read:jira-work"),
    "add_labels_to_issue": _s("read:jira-work", "write:jira-work"),
    "move_issues_to_epic": _s("write:epic:jira-software"),

    # -- no scope beyond authentication --
    "get_jira_server_info": _s(),
}


# -- instance-wide configuration administration: issue types and their schemes,
#    statuses, priorities, resolutions, field configurations, notification and
#    workflow schemes, groups and group membership, audit log, application
#    properties, user preferences. Atlassian declares
#    `manage:jira-configuration` on every one of these. --
_CONFIGURATION_OPS: tuple[str, ...] = (
    "add_actors_to_project_role",
    "add_user_to_group",
    "create_custom_field",
    "create_group",
    "create_issue_link_type",
    "create_issue_type",
    "create_issue_type_scheme",
    "create_permission_scheme",
    "create_priority",
    "create_resolution",
    "create_status",
    "delete_group",
    "delete_issue_link_type",
    "delete_issue_type",
    "delete_issue_type_scheme",
    "delete_permission_scheme",
    "delete_priority",
    "delete_resolution",
    "delete_status",
    "get_application_property",
    "get_audit_log",
    "get_current_user_preferences",
    "get_field_configuration",
    "get_field_configuration_scheme",
    "get_issue_security_level",
    "get_issue_type_scheme",
    "get_issue_type_screen_scheme",
    "get_jira_license_info",
    "get_notification_scheme",
    "get_priority_scheme",
    "get_workflow_scheme",
    "list_all_permissions",
    "list_application_properties",
    "list_field_configuration_schemes",
    "list_field_configurations",
    "list_group_members",
    "list_issue_type_avatars",
    "list_issue_type_schemes",
    "list_issue_type_screen_schemes",
    "list_notification_schemes",
    "list_priority_schemes",
    "list_workflow_schemes",
    "remove_user_from_group",
    "restore_archived_project",
    "set_application_property",
    "set_current_user_preference",
    "update_issue_link_type",
    "update_issue_type",
    "update_issue_type_scheme",
    "update_priority",
    "update_resolution",
    "update_status",
)

for _op in _CONFIGURATION_OPS:
    _REQUIREMENTS[_op] = _s("manage:jira-configuration")


JIRA_SCOPES = ScopeRegistry(
    provider="jira",
    requirements=_REQUIREMENTS,
    unmapped=(
        # `_get_workflow` calls GET /rest/api/3/workflow?workflowName=, the
        # removed "Get all workflows" endpoint. It is absent from Atlassian's
        # current spec, so no scope is documented for it.
        "get_workflow",
    ),
    # Refresh-token issuance, not an endpoint permission.
    extra_scopes={DEFAULT_VARIANT: ("offline_access",)},
)

#: Scopes requested at connect time, derived from the table above.
JIRA_REQUESTED_SCOPES: list[str] = JIRA_SCOPES.declared_scopes()

#: User-facing remedy for a credential that predates a scope this table needs.
RECONNECT_HINT = (
    "Reconnect the Jira account in the credentials tab to grant the updated "
    "scopes."
)
