"""Todoist permissions: https://developer.todoist.com/api/v1/#tag/OAuth"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

TODOIST_SCOPES = ScopeRegistry(
    provider="todoist",
    requirements={**{name: ScopeRequirement(scopes=(
        "project:delete" if name == "delete_project" else
        "data:delete" if name.startswith("delete_") else "data:read_write",))
        for name in (
            'get_user', 'list_projects', 'search_projects', 'list_archived_projects',
            'get_project', 'create_project', 'update_project', 'archive_project',
            'unarchive_project', 'delete_project', 'list_sections', 'search_sections',
            'get_section', 'create_section', 'update_section', 'archive_section',
            'unarchive_section', 'delete_section', 'list_tasks', 'filter_tasks',
            'get_task', 'create_task', 'quick_add_task', 'update_task',
            'move_task', 'close_task', 'reopen_task', 'delete_task',
            'list_labels', 'search_labels', 'get_label', 'create_label',
            'update_label', 'delete_label', 'list_comments', 'get_comment',
            'create_comment', 'update_comment', 'delete_comment',
        )},
        "on_new_task": ScopeRequirement(scopes=("data:read_write",))},
)
