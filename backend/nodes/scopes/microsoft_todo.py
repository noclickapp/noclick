"""Microsoft To Do → OAuth scope requirements (Graph's shared notes are in microsoft.py)."""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.scopes.microsoft import _graph


# ===========================================================================
# Microsoft To Do  (automation-microsoft-todo)
# ===========================================================================
# Requests: Tasks.Read, Tasks.ReadWrite, User.Read, offline_access.

_TASKS_READ = _graph("Tasks.Read")
_TASKS_WRITE = _graph("Tasks.ReadWrite")

_TODO_REQUIREMENTS: dict[str, ScopeRequirement] = {
    "list_task_lists": _TASKS_READ,  # user: List todoTaskLists
    "get_task_list": _TASKS_READ,  # Get todoTaskList
    "create_task_list": _TASKS_WRITE,  # user: Create todoTaskList
    "update_task_list": _TASKS_WRITE,  # Update todoTaskList
    # Delete todoTaskList prints Tasks.Read as least privileged and
    # Tasks.ReadWrite as higher; the write permission is the honest one.
    "delete_task_list": _TASKS_WRITE,
    "list_tasks": _TASKS_READ,  # todoTaskList: List tasks
    "get_task": _TASKS_READ,  # Get todoTask
    "create_task": _TASKS_WRITE,  # todoTaskList: Create task
    "update_task": _TASKS_WRITE,  # Update todoTask
    "delete_task": _TASKS_WRITE,  # Delete todoTask
}

MICROSOFT_TODO_SCOPES = ScopeRegistry(
    provider="microsoft-todo",
    requirements=_TODO_REQUIREMENTS,
)
