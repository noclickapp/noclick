"""Google Tasks → OAuth scope requirements (Google's shared scope notes are in google.py)."""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry
from nodes.scopes.google import _table


TASKS = "https://www.googleapis.com/auth/tasks"


# ---------------------------------------------------------------------------
# Tasks — tasks/v1 throughout.
# ---------------------------------------------------------------------------
GOOGLE_TASKS_SCOPES = ScopeRegistry(
    provider="google-tasks",
    requirements=_table(
        {
            TASKS: (
                # task lists
                "list_all_task_lists",
                "fetch_task_list",
                "create_new_task_list",
                "update_task_list_metadata",
                "delete_task_list",
                # tasks
                "list_tasks_in_list",
                "fetch_task_from_list",
                "create_new_task",
                "update_task_in_list",
                "delete_task_from_list",
                "move_task_to_position",
                "clear_completed_tasks",
            ),
        }
    ),
)
