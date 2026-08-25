"""
Asana project-management automation node.

Provides workflow integration with the Asana REST API (v1.0) for operations:
- Users: get current user, list users
- Workspaces: list workspaces, list teams, list custom fields
- Projects: list, get, create, update, delete; list project tasks/sections
- Tasks: list/search, get, create, update, delete, duplicate, subtasks,
  project moves, followers, comments/stories (CRUD), tags, section placement,
  dependencies (add/remove/get)
- Tags: list, create, get tags for task, add/remove tag to task
- Sections: list, create, update, delete
- Webhook Trigger: fire the workflow when an Asana resource changes

Authentication: Bearer token — a Personal Access Token (PAT) or an OAuth 2.0
access token, both passed as ``Authorization: Bearer <token>``.
API Base URL: https://app.asana.com/api/1.0
Documentation: https://developers.asana.com/docs/overview

Asana wraps every write body in a top-level ``{"data": {...}}`` envelope and
returns reads as ``{"data": ...}``; the request helper handles both. All object
IDs are ``gid`` strings (not the legacy numeric id).
"""

import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.asana import ASANA_SCOPES
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.core.dynamic_options import filter_options_by_search, normalize_search
from utils.webhook_signatures import verify_hmac_sha256_hex

logger = logging.getLogger(__name__)

ASANA_API_BASE = "https://app.asana.com/api/1.0"

# Webhook event "action" types Asana stamps on every change event. The trigger's
# ``event_types`` field selects which of these fire the workflow; the same values
# become the ``filters`` array passed to ``POST /webhooks`` so Asana only delivers
# matching events (and are re-checked at runtime in ``filter_trigger_payload``).
# https://developers.asana.com/docs/webhooks-guide
ASANA_TRIGGER_ACTIONS = ["added", "changed", "removed", "deleted", "undeleted"]
ASANA_TRIGGER_ACTION_LABELS = [
    "Added (resource created)",
    "Changed (resource modified)",
    "Removed (detached from a parent)",
    "Deleted (resource deleted)",
    "Undeleted (deletion undone)",
]
# Sentinel selecting every action — Asana then delivers all event types (no filters).
ASANA_ALL_EVENTS = "*"


# ============================================================================
# Credential Schemas
# ============================================================================


class AsanaPATCredential(BaseModel):
    """Personal Access Token credential for Asana."""

    credential_type: Literal["asana_pat"] = Field(
        "asana_pat", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Personal Access Token",
        description="Your Asana Personal Access Token from the Developer Console (My Apps).",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://app.asana.com/0/my-apps"}
    )


class AsanaOAuthCredential(BaseModel):
    """OAuth 2.0 credential for Asana (authorization_code flow).

    Tokens are obtained via the OAuth flow, not entered manually. Asana access
    tokens expire after 1 hour and are auto-refreshed via the long-lived
    refresh token.

    Register an OAuth app at: https://app.asana.com/0/my-apps
    """

    credential_type: Literal["asana_oauth"] = Field(
        "asana_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="Asana OAuth access token (Bearer).",
        json_schema_extra={"ui:widget": "password"},
    )
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    name: Optional[str] = Field(None, title="User Name")
    email: Optional[str] = Field(None, title="Account Email")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "asana",
            # Asana OAuth uses a single 'default' scope that grants access to all
            # capabilities configured for the app. Granular resource-level scopes
            # (tasks:read etc.) do not exist in Asana's OAuth model.
            "x-oauth-scopes": ["default"],
            "x-credential-url": "https://app.asana.com/0/my-apps",
        }
    )


# OAuth first so it is the default choice when a user adds a credential, with the
# PAT as the simplest always-working self-serve path.
AsanaCredential = Union[AsanaOAuthCredential, AsanaPATCredential]


# ============================================================================
# Operation Configs
# ============================================================================


class AsanaGetMeConfig(BaseModel):
    """Get the authenticated user (handy for testing credentials)."""

    operation: Literal["get_me"] = Field(
        "get_me",
        json_schema_extra={
            "const": "get_me",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Get Current User",
        },
        title="Get Current User",
    )


class AsanaListWorkspacesConfig(BaseModel):
    """List workspaces and organizations the user can access."""

    operation: Literal["list_workspaces"] = Field(
        "list_workspaces",
        json_schema_extra={
            "const": "list_workspaces",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "List Workspaces",
        },
        title="List Workspaces",
    )


class AsanaListUsersConfig(BaseModel):
    """List users in a workspace (resolve assignees/followers)."""

    operation: Literal["list_users"] = Field(
        "list_users",
        json_schema_extra={
            "const": "list_users",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "List Users",
        },
        title="List Users",
    )
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The workspace to list users from.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )


class AsanaListTeamsConfig(BaseModel):
    """List teams in an organization."""

    operation: Literal["list_teams"] = Field(
        "list_teams",
        json_schema_extra={
            "const": "list_teams",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "List Teams",
        },
        title="List Teams",
    )
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The organization workspace to list teams from.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )


class AsanaListCustomFieldsConfig(BaseModel):
    """List custom fields available in a workspace."""

    operation: Literal["list_custom_fields"] = Field(
        "list_custom_fields",
        json_schema_extra={
            "const": "list_custom_fields",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "List Custom Fields",
        },
        title="List Custom Fields",
    )
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The workspace to list custom fields from.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )


class AsanaListProjectsConfig(BaseModel):
    """List projects, optionally filtered by workspace."""

    operation: Literal["list_projects"] = Field(
        "list_projects",
        json_schema_extra={
            "const": "list_projects",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "List Projects",
        },
        title="List Projects",
    )
    workspace_gid: Optional[str] = Field(
        None,
        title="Workspace",
        description="Filter projects to this workspace (optional).",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )
    archived: Optional[str] = Field(
        None,
        title="Archived",
        description="Filter by archived status.",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Any", "Archived only", "Active only"],
            "x-enum-searchable": True,
        },
    )
    limit: Optional[str] = Field(
        "100", title="Limit", description="Max number of projects to return (1-100)."
    )


class AsanaGetProjectConfig(BaseModel):
    """Get a single project's details."""

    operation: Literal["get_project"] = Field(
        "get_project",
        json_schema_extra={
            "const": "get_project",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Get Project",
        },
        title="Get Project",
    )
    project_gid: str = Field(
        ..., title="Project", description="The gid of the project to retrieve.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )


class AsanaCreateProjectConfig(BaseModel):
    """Create a new project in a workspace (optionally in a team)."""

    operation: Literal["create_project"] = Field(
        "create_project",
        json_schema_extra={
            "const": "create_project",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Create Project",
            "x-creates-resource": True,
            "x-resource-type": "asana_project",
            "x-resource-id-path": "data.gid",
        },
        title="Create Project",
    )
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The workspace to create the project in.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )
    name: str = Field(..., title="Name", description="The name of the new project.")
    notes: Optional[str] = Field(
        None,
        title="Notes",
        description="Project description / notes.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    team_gid: Optional[str] = Field(
        None,
        title="Team",
        description="The team to add the project to (required for organization workspaces).",
        json_schema_extra={"x-dynamic-options": {"field_name": "team_gid", "placeholder": "Select a team...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste team gid", "depends_on": "workspace_gid"}, "x-resource-type": "asana_team"},
    )


class AsanaUpdateProjectConfig(BaseModel):
    """Update a project's name, notes, or archived status."""

    operation: Literal["update_project"] = Field(
        "update_project",
        json_schema_extra={
            "const": "update_project",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Update Project",
        },
        title="Update Project",
    )
    project_gid: str = Field(
        ..., title="Project", description="The gid of the project to update.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )
    name: Optional[str] = Field(None, title="Name", description="New project name.")
    notes: Optional[str] = Field(
        None,
        title="Notes",
        description="New project notes.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    archived: Optional[str] = Field(
        None,
        title="Archived",
        description="Archive or unarchive the project.",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["No change", "Archive", "Unarchive"],
            "x-enum-searchable": True,
        },
    )


class AsanaDeleteProjectConfig(BaseModel):
    """Delete a project."""

    operation: Literal["delete_project"] = Field(
        "delete_project",
        json_schema_extra={
            "const": "delete_project",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Delete Project",
        },
        title="Delete Project",
    )
    project_gid: str = Field(
        ..., title="Project", description="The gid of the project to delete.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )


class AsanaListProjectTasksConfig(BaseModel):
    """List tasks belonging to a project."""

    operation: Literal["list_project_tasks"] = Field(
        "list_project_tasks",
        json_schema_extra={
            "const": "list_project_tasks",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "List Tasks in Project",
        },
        title="List Tasks in Project",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to list tasks from.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )
    completed_since: Optional[str] = Field(
        None,
        title="Completed Since",
        description="Only return tasks completed since this ISO 8601 time (use 'now' for incomplete only).",
    )
    limit: Optional[str] = Field(
        "100", title="Limit", description="Max number of tasks to return (1-100)."
    )


class AsanaListProjectSectionsConfig(BaseModel):
    """List sections within a project."""

    operation: Literal["list_sections"] = Field(
        "list_sections",
        json_schema_extra={
            "const": "list_sections",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "List Sections",
        },
        title="List Sections",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to list sections from.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )


class AsanaSearchTasksConfig(BaseModel):
    """Search tasks in a workspace by text."""

    operation: Literal["search_tasks"] = Field(
        "search_tasks",
        json_schema_extra={
            "const": "search_tasks",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Search Tasks",
        },
        title="Search Tasks",
    )
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The workspace to search within.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )
    text: Optional[str] = Field(
        None, title="Text", description="Full-text search query across task names/descriptions."
    )
    completed: Optional[str] = Field(
        None,
        title="Completed",
        description="Filter by completion status.",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Any", "Completed", "Incomplete"],
            "x-enum-searchable": True,
        },
    )
    limit: Optional[str] = Field(
        "50", title="Limit", description="Max number of tasks to return (1-100)."
    )


class AsanaGetTaskConfig(BaseModel):
    """Get a single task with its fields."""

    operation: Literal["get_task"] = Field(
        "get_task",
        json_schema_extra={
            "const": "get_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Get Task",
        },
        title="Get Task",
    )
    task_gid: str = Field(
        ..., title="Task GID", description="The gid of the task to retrieve."
    )


class AsanaCreateTaskConfig(BaseModel):
    """Create a task (name, notes, assignee, due date, projects)."""

    operation: Literal["create_task"] = Field(
        "create_task",
        json_schema_extra={
            "const": "create_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Create Task",
        },
        title="Create Task",
    )
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The workspace to create the task in.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )
    name: str = Field(..., title="Name", description="The name/title of the task.")
    notes: Optional[str] = Field(
        None,
        title="Notes",
        description="Task description / notes.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    assignee: Optional[str] = Field(
        None, title="Assignee", description="User gid or email to assign the task to."
    )
    due_on: Optional[str] = Field(
        None, title="Due On", description="Due date in YYYY-MM-DD format."
    )
    projects: Optional[str] = Field(
        None,
        title="Projects",
        description="Project gids to add the task to, comma-separated.",
    )


class AsanaUpdateTaskConfig(BaseModel):
    """Update a task (rename, reassign, complete, set due date)."""

    operation: Literal["update_task"] = Field(
        "update_task",
        json_schema_extra={
            "const": "update_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Update Task",
        },
        title="Update Task",
    )
    task_gid: str = Field(
        ..., title="Task GID", description="The gid of the task to update."
    )
    name: Optional[str] = Field(None, title="Name", description="New task name.")
    notes: Optional[str] = Field(
        None,
        title="Notes",
        description="New task notes.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    assignee: Optional[str] = Field(
        None, title="Assignee", description="User gid or email to reassign the task to."
    )
    due_on: Optional[str] = Field(
        None, title="Due On", description="New due date in YYYY-MM-DD format."
    )
    completed: Optional[str] = Field(
        None,
        title="Completed",
        description="Mark the task complete or incomplete.",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["No change", "Mark complete", "Mark incomplete"],
            "x-enum-searchable": True,
        },
    )


class AsanaDeleteTaskConfig(BaseModel):
    """Delete a task."""

    operation: Literal["delete_task"] = Field(
        "delete_task",
        json_schema_extra={
            "const": "delete_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Delete Task",
        },
        title="Delete Task",
    )
    task_gid: str = Field(
        ..., title="Task GID", description="The gid of the task to delete."
    )


class AsanaAddTaskToProjectConfig(BaseModel):
    """Add a task to a project (optionally into a section)."""

    operation: Literal["add_task_to_project"] = Field(
        "add_task_to_project",
        json_schema_extra={
            "const": "add_task_to_project",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Add Task to Project",
        },
        title="Add Task to Project",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to add.")
    project_gid: str = Field(
        ..., title="Project", description="The project to add the task to.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )
    section_gid: Optional[str] = Field(
        None, title="Section", description="Place the task in this section (optional).",
        json_schema_extra={"x-dynamic-options": {"field_name": "section_gid", "placeholder": "Select a section...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste section gid", "depends_on": "project_gid"}, "x-resource-type": "asana_section"},
    )


class AsanaRemoveTaskFromProjectConfig(BaseModel):
    """Remove a task from a project."""

    operation: Literal["remove_task_from_project"] = Field(
        "remove_task_from_project",
        json_schema_extra={
            "const": "remove_task_from_project",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Remove Task from Project",
        },
        title="Remove Task from Project",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to remove.")
    project_gid: str = Field(
        ..., title="Project", description="The project to remove the task from.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )


class AsanaListSubtasksConfig(BaseModel):
    """List a task's subtasks."""

    operation: Literal["list_subtasks"] = Field(
        "list_subtasks",
        json_schema_extra={
            "const": "list_subtasks",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "List Subtasks",
        },
        title="List Subtasks",
    )
    task_gid: str = Field(
        ..., title="Task GID", description="The parent task to list subtasks of."
    )


class AsanaCreateSubtaskConfig(BaseModel):
    """Create a subtask under a parent task."""

    operation: Literal["create_subtask"] = Field(
        "create_subtask",
        json_schema_extra={
            "const": "create_subtask",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Create Subtask",
        },
        title="Create Subtask",
    )
    task_gid: str = Field(
        ..., title="Parent Task GID", description="The parent task to add the subtask under."
    )
    name: str = Field(..., title="Name", description="The name of the subtask.")
    notes: Optional[str] = Field(
        None,
        title="Notes",
        description="Subtask description / notes.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    assignee: Optional[str] = Field(
        None, title="Assignee", description="User gid or email to assign the subtask to."
    )


class AsanaAddFollowersConfig(BaseModel):
    """Add followers to a task."""

    operation: Literal["add_followers"] = Field(
        "add_followers",
        json_schema_extra={
            "const": "add_followers",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Add Followers",
        },
        title="Add Followers",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to add followers to.")
    followers: str = Field(
        ...,
        title="Followers",
        description="User gids or emails to add as followers, comma-separated.",
    )


class AsanaRemoveFollowersConfig(BaseModel):
    """Remove followers from a task."""

    operation: Literal["remove_followers"] = Field(
        "remove_followers",
        json_schema_extra={
            "const": "remove_followers",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Remove Followers",
        },
        title="Remove Followers",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to remove followers from.")
    followers: str = Field(
        ...,
        title="Followers",
        description="User gids or emails to remove from followers, comma-separated.",
    )


class AsanaAddCommentConfig(BaseModel):
    """Add a comment (story) to a task."""

    operation: Literal["add_comment"] = Field(
        "add_comment",
        json_schema_extra={
            "const": "add_comment",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "Add Comment",
        },
        title="Add Comment",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to comment on.")
    text: str = Field(
        ...,
        title="Comment",
        description="The comment text to post on the task.",
        json_schema_extra={"ui:widget": "textarea"},
    )


class AsanaListCommentsConfig(BaseModel):
    """List stories (comments + activity) on a task."""

    operation: Literal["list_comments"] = Field(
        "list_comments",
        json_schema_extra={
            "const": "list_comments",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "List Comments",
        },
        title="List Comments",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to list comments/stories on.")


class AsanaAddTaskToSectionConfig(BaseModel):
    """Move/place a task into a project section."""

    operation: Literal["add_task_to_section"] = Field(
        "add_task_to_section",
        json_schema_extra={
            "const": "add_task_to_section",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Add Task to Section",
        },
        title="Add Task to Section",
    )
    section_gid: str = Field(
        ..., title="Section", description="The section to place the task in.",
        json_schema_extra={"x-dynamic-options": {"field_name": "section_gid", "placeholder": "Select a section...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste section gid"}, "x-resource-type": "asana_section"},
    )
    task_gid: str = Field(..., title="Task GID", description="The task to move into the section.")


class AsanaListTagsConfig(BaseModel):
    """List tags in a workspace."""

    operation: Literal["list_tags"] = Field(
        "list_tags",
        json_schema_extra={
            "const": "list_tags",
            "ui:hidden": True,
            "x-category": "Tags",
            "x-is-trigger": False,
            "x-display-name": "List Tags",
        },
        title="List Tags",
    )
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The workspace to list tags from.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )


class AsanaAddTagToTaskConfig(BaseModel):
    """Tag a task."""

    operation: Literal["add_tag_to_task"] = Field(
        "add_tag_to_task",
        json_schema_extra={
            "const": "add_tag_to_task",
            "ui:hidden": True,
            "x-category": "Tags",
            "x-is-trigger": False,
            "x-display-name": "Add Tag to Task",
        },
        title="Add Tag to Task",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to tag.")
    tag_gid: str = Field(
        ..., title="Tag", description="The tag to add to the task.",
        json_schema_extra={"x-dynamic-options": {"field_name": "tag_gid", "placeholder": "Select a tag...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste tag gid"}, "x-resource-type": "asana_tag"},
    )


class AsanaRemoveTagFromTaskConfig(BaseModel):
    """Remove a tag from a task."""

    operation: Literal["remove_tag_from_task"] = Field(
        "remove_tag_from_task",
        json_schema_extra={
            "const": "remove_tag_from_task",
            "ui:hidden": True,
            "x-category": "Tags",
            "x-is-trigger": False,
            "x-display-name": "Remove Tag from Task",
        },
        title="Remove Tag from Task",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to remove the tag from.")
    tag_gid: str = Field(
        ..., title="Tag", description="The tag to remove.",
        json_schema_extra={"x-dynamic-options": {"field_name": "tag_gid", "placeholder": "Select a tag...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste tag gid"}, "x-resource-type": "asana_tag"},
    )


class AsanaGetTagsForTaskConfig(BaseModel):
    """List all tags on a task."""

    operation: Literal["get_tags_for_task"] = Field(
        "get_tags_for_task",
        json_schema_extra={
            "const": "get_tags_for_task",
            "ui:hidden": True,
            "x-category": "Tags",
            "x-is-trigger": False,
            "x-display-name": "Get Tags for Task",
        },
        title="Get Tags for Task",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to retrieve tags from.")


class AsanaCreateTagConfig(BaseModel):
    """Create a new tag in a workspace."""

    operation: Literal["create_tag"] = Field(
        "create_tag",
        json_schema_extra={
            "const": "create_tag",
            "ui:hidden": True,
            "x-category": "Tags",
            "x-is-trigger": False,
            "x-display-name": "Create Tag",
            "x-creates-resource": True,
            "x-resource-type": "asana_tag",
            "x-resource-id-path": "data.gid",
        },
        title="Create Tag",
    )
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The workspace to create the tag in.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )
    name: str = Field(..., title="Name", description="The name of the new tag.")
    color: Optional[str] = Field(
        None,
        title="Color",
        description="Optional tag color (e.g. dark-pink, dark-green, dark-blue, dark-red, dark-teal, dark-brown, dark-orange, dark-purple, dark-warm-gray, light-pink, light-green, light-blue, light-red, light-teal, light-brown, light-orange, light-purple, light-warm-gray).",
    )


# ── Sections CRUD ─────────────────────────────────────────────────────────────

class AsanaCreateSectionConfig(BaseModel):
    """Create a section in a project."""

    operation: Literal["create_section"] = Field(
        "create_section",
        json_schema_extra={
            "const": "create_section",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Create Section",
            "x-creates-resource": True,
            "x-resource-type": "asana_section",
            "x-resource-id-path": "data.gid",
        },
        title="Create Section",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to add the section to.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )
    name: str = Field(..., title="Name", description="The name of the new section.")


class AsanaUpdateSectionConfig(BaseModel):
    """Rename or update a section."""

    operation: Literal["update_section"] = Field(
        "update_section",
        json_schema_extra={
            "const": "update_section",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Update Section",
        },
        title="Update Section",
    )
    section_gid: str = Field(..., title="Section GID", description="The section to update.")
    name: str = Field(..., title="Name", description="The new name for the section.")


class AsanaDeleteSectionConfig(BaseModel):
    """Delete a section from a project."""

    operation: Literal["delete_section"] = Field(
        "delete_section",
        json_schema_extra={
            "const": "delete_section",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Delete Section",
        },
        title="Delete Section",
    )
    section_gid: str = Field(..., title="Section GID", description="The section to delete.")


# ── Task dependencies ──────────────────────────────────────────────────────────

class AsanaGetTaskDependenciesConfig(BaseModel):
    """Get tasks that a task depends on (its dependencies)."""

    operation: Literal["get_task_dependencies"] = Field(
        "get_task_dependencies",
        json_schema_extra={
            "const": "get_task_dependencies",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Get Task Dependencies",
        },
        title="Get Task Dependencies",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to get dependencies for.")


class AsanaAddDependenciesToTaskConfig(BaseModel):
    """Set tasks that must be completed before this task (dependencies)."""

    operation: Literal["add_task_dependencies"] = Field(
        "add_task_dependencies",
        json_schema_extra={
            "const": "add_task_dependencies",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Add Task Dependencies",
        },
        title="Add Task Dependencies",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to add dependencies to.")
    dependencies: str = Field(
        ...,
        title="Dependency Task GIDs",
        description="Comma-separated GIDs of tasks that must be completed before this task.",
    )


class AsanaRemoveDependenciesFromTaskConfig(BaseModel):
    """Remove task dependencies."""

    operation: Literal["remove_task_dependencies"] = Field(
        "remove_task_dependencies",
        json_schema_extra={
            "const": "remove_task_dependencies",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Remove Task Dependencies",
        },
        title="Remove Task Dependencies",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to remove dependencies from.")
    dependencies: str = Field(
        ...,
        title="Dependency Task GIDs",
        description="Comma-separated GIDs of dependency tasks to remove.",
    )


# ── Duplicate task / project ───────────────────────────────────────────────────

class AsanaDuplicateTaskConfig(BaseModel):
    """Duplicate a task (optionally into the same project under a new name)."""

    operation: Literal["duplicate_task"] = Field(
        "duplicate_task",
        json_schema_extra={
            "const": "duplicate_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Duplicate Task",
        },
        title="Duplicate Task",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to duplicate.")
    name: str = Field(..., title="New Name", description="The name for the duplicated task.")
    include: Optional[str] = Field(
        None,
        title="Include",
        description=(
            "Comma-separated list of fields to carry into the copy. Options: "
            "assignee, attachments, dates, dependencies, followers, notes, parent, "
            "projects, subtasks, tags."
        ),
    )


class AsanaDuplicateProjectConfig(BaseModel):
    """Duplicate a project (creates an async Job — poll the returned job_gid for completion)."""

    operation: Literal["duplicate_project"] = Field(
        "duplicate_project",
        json_schema_extra={
            "const": "duplicate_project",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Duplicate Project",
        },
        title="Duplicate Project",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to duplicate.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )
    name: str = Field(..., title="New Name", description="The name for the duplicated project.")
    team: Optional[str] = Field(None, title="Team GID", description="The team for the new project (optional).")
    include: Optional[str] = Field(
        None,
        title="Include",
        description=(
            "Comma-separated list of fields to copy. Options: "
            "members, notes, task_assignee, task_attachments, task_dates, "
            "task_dependencies, task_followers, task_notes, task_projects, "
            "task_subtasks, task_tags."
        ),
    )


# ── Users (individual) ────────────────────────────────────────────────────────

class AsanaGetUserConfig(BaseModel):
    """Get a specific user by their gid."""

    operation: Literal["get_user"] = Field(
        "get_user",
        json_schema_extra={
            "const": "get_user",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Get User",
        },
        title="Get User",
    )
    user_gid: str = Field(
        ..., title="User GID / me", description="The user's gid, or 'me' for the authenticated user."
    )


# ── Sections (individual) ──────────────────────────────────────────────────────

class AsanaGetSectionConfig(BaseModel):
    """Get a single section by its gid."""

    operation: Literal["get_section"] = Field(
        "get_section",
        json_schema_extra={
            "const": "get_section",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Get Section",
        },
        title="Get Section",
    )
    section_gid: str = Field(
        ..., title="Section GID", description="The section's gid.",
        json_schema_extra={"x-dynamic-options": {"field_name": "section_gid", "placeholder": "Select a section...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste section gid"}, "x-resource-type": "asana_section"},
    )


# ── Tags — full CRUD ───────────────────────────────────────────────────────────

class AsanaGetTagConfig(BaseModel):
    """Get a tag by its gid."""

    operation: Literal["get_tag"] = Field(
        "get_tag",
        json_schema_extra={
            "const": "get_tag",
            "ui:hidden": True,
            "x-category": "Tags",
            "x-is-trigger": False,
            "x-display-name": "Get Tag",
        },
        title="Get Tag",
    )
    tag_gid: str = Field(
        ..., title="Tag", description="The tag's gid.",
        json_schema_extra={"x-dynamic-options": {"field_name": "tag_gid", "placeholder": "Select a tag...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste tag gid"}, "x-resource-type": "asana_tag"},
    )


class AsanaUpdateTagConfig(BaseModel):
    """Update a tag's name or color."""

    operation: Literal["update_tag"] = Field(
        "update_tag",
        json_schema_extra={
            "const": "update_tag",
            "ui:hidden": True,
            "x-category": "Tags",
            "x-is-trigger": False,
            "x-display-name": "Update Tag",
        },
        title="Update Tag",
    )
    tag_gid: str = Field(
        ..., title="Tag", description="The tag to update.",
        json_schema_extra={"x-dynamic-options": {"field_name": "tag_gid", "placeholder": "Select a tag...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste tag gid"}, "x-resource-type": "asana_tag"},
    )
    name: Optional[str] = Field(None, title="Name", description="New tag name.")
    color: Optional[str] = Field(
        None,
        title="Color",
        description="Tag color (e.g. dark-pink, dark-green, dark-blue, light-red, light-teal, light-orange, light-purple, none).",
    )


class AsanaDeleteTagConfig(BaseModel):
    """Delete a tag."""

    operation: Literal["delete_tag"] = Field(
        "delete_tag",
        json_schema_extra={
            "const": "delete_tag",
            "ui:hidden": True,
            "x-category": "Tags",
            "x-is-trigger": False,
            "x-display-name": "Delete Tag",
        },
        title="Delete Tag",
    )
    tag_gid: str = Field(
        ..., title="Tag", description="The tag to delete.",
        json_schema_extra={"x-dynamic-options": {"field_name": "tag_gid", "placeholder": "Select a tag...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste tag gid"}, "x-resource-type": "asana_tag"},
    )


# ── Task dependents (tasks that depend ON this task) ──────────────────────────

class AsanaGetTaskDependentsConfig(BaseModel):
    """Get tasks that depend on this task (dependents / blocking tasks)."""

    operation: Literal["get_task_dependents"] = Field(
        "get_task_dependents",
        json_schema_extra={
            "const": "get_task_dependents",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Get Task Dependents",
        },
        title="Get Task Dependents",
    )
    task_gid: str = Field(..., title="Task GID", description="The task whose dependents to retrieve.")


class AsanaAddTaskDependentsConfig(BaseModel):
    """Mark tasks as depending on this task (add dependents)."""

    operation: Literal["add_task_dependents"] = Field(
        "add_task_dependents",
        json_schema_extra={
            "const": "add_task_dependents",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Add Task Dependents",
        },
        title="Add Task Dependents",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to add dependents to.")
    dependents: str = Field(
        ...,
        title="Dependent Task GIDs",
        description="Comma-separated GIDs of tasks that depend on this task.",
    )


class AsanaRemoveTaskDependentsConfig(BaseModel):
    """Remove dependent tasks from this task."""

    operation: Literal["remove_task_dependents"] = Field(
        "remove_task_dependents",
        json_schema_extra={
            "const": "remove_task_dependents",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Remove Task Dependents",
        },
        title="Remove Task Dependents",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to remove dependents from.")
    dependents: str = Field(
        ...,
        title="Dependent Task GIDs",
        description="Comma-separated GIDs of dependent tasks to remove.",
    )


# ── Project status updates ─────────────────────────────────────────────────────

class AsanaGetProjectStatusesConfig(BaseModel):
    """List status updates on a project."""

    operation: Literal["get_project_statuses"] = Field(
        "get_project_statuses",
        json_schema_extra={
            "const": "get_project_statuses",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Get Project Statuses",
        },
        title="Get Project Statuses",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to get status updates for.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )


class AsanaCreateProjectStatusConfig(BaseModel):
    """Post a status update on a project (On Track, At Risk, Off Track)."""

    operation: Literal["create_project_status"] = Field(
        "create_project_status",
        json_schema_extra={
            "const": "create_project_status",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Create Project Status",
        },
        title="Create Project Status",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to post the status on.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )
    title: str = Field(..., title="Title", description="A short title for this status update.")
    text: str = Field(
        ...,
        title="Text",
        description="The longer status message.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    color: str = Field(
        "green",
        title="Color",
        description="The status color representing project health.",
        json_schema_extra={
            "enum": ["green", "yellow", "red", "blue"],
            "enumNames": ["On Track (green)", "At Risk (yellow)", "Off Track (red)", "No Status (blue)"],
            "x-enum-searchable": True,
        },
    )


class AsanaDeleteProjectStatusConfig(BaseModel):
    """Delete a project status update."""

    operation: Literal["delete_project_status"] = Field(
        "delete_project_status",
        json_schema_extra={
            "const": "delete_project_status",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Delete Project Status",
        },
        title="Delete Project Status",
    )
    project_status_gid: str = Field(
        ..., title="Project Status GID", description="The project status update to delete."
    )


# ── Teams — full management ────────────────────────────────────────────────────

class AsanaGetTeamConfig(BaseModel):
    """Get a team's details."""

    operation: Literal["get_team"] = Field(
        "get_team",
        json_schema_extra={
            "const": "get_team",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "Get Team",
        },
        title="Get Team",
    )
    team_gid: str = Field(
        ..., title="Team", description="The gid of the team to retrieve.",
        json_schema_extra={"x-dynamic-options": {"field_name": "team_gid", "placeholder": "Select a team...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste team gid"}, "x-resource-type": "asana_team"},
    )


class AsanaGetTeamMembersConfig(BaseModel):
    """List users in a team."""

    operation: Literal["get_team_members"] = Field(
        "get_team_members",
        json_schema_extra={
            "const": "get_team_members",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "Get Team Members",
        },
        title="Get Team Members",
    )
    team_gid: str = Field(
        ..., title="Team", description="The team to list members of.",
        json_schema_extra={"x-dynamic-options": {"field_name": "team_gid", "placeholder": "Select a team...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste team gid"}, "x-resource-type": "asana_team"},
    )


class AsanaAddTeamMemberConfig(BaseModel):
    """Add a user to a team."""

    operation: Literal["add_team_member"] = Field(
        "add_team_member",
        json_schema_extra={
            "const": "add_team_member",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "Add Team Member",
        },
        title="Add Team Member",
    )
    team_gid: str = Field(
        ..., title="Team", description="The team to add the user to.",
        json_schema_extra={"x-dynamic-options": {"field_name": "team_gid", "placeholder": "Select a team...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste team gid"}, "x-resource-type": "asana_team"},
    )
    user: str = Field(..., title="User GID / Email", description="The user's gid or email address.")


class AsanaRemoveTeamMemberConfig(BaseModel):
    """Remove a user from a team."""

    operation: Literal["remove_team_member"] = Field(
        "remove_team_member",
        json_schema_extra={
            "const": "remove_team_member",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "Remove Team Member",
        },
        title="Remove Team Member",
    )
    team_gid: str = Field(
        ..., title="Team", description="The team to remove the user from.",
        json_schema_extra={"x-dynamic-options": {"field_name": "team_gid", "placeholder": "Select a team...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste team gid"}, "x-resource-type": "asana_team"},
    )
    user: str = Field(..., title="User GID / Email", description="The user's gid or email address.")


# ── Project members ────────────────────────────────────────────────────────────

class AsanaGetProjectMembersConfig(BaseModel):
    """List members/memberships of a project."""

    operation: Literal["get_project_members"] = Field(
        "get_project_members",
        json_schema_extra={
            "const": "get_project_members",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Get Project Members",
        },
        title="Get Project Members",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to list members of.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )


class AsanaAddProjectMemberConfig(BaseModel):
    """Add users to a project as members."""

    operation: Literal["add_project_member"] = Field(
        "add_project_member",
        json_schema_extra={
            "const": "add_project_member",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Add Project Member",
        },
        title="Add Project Member",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to add members to.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )
    members: str = Field(
        ..., title="Members", description="Comma-separated user gids or emails to add."
    )


class AsanaRemoveProjectMemberConfig(BaseModel):
    """Remove users from a project."""

    operation: Literal["remove_project_member"] = Field(
        "remove_project_member",
        json_schema_extra={
            "const": "remove_project_member",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Remove Project Member",
        },
        title="Remove Project Member",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to remove members from.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )
    members: str = Field(
        ..., title="Members", description="Comma-separated user gids or emails to remove."
    )


# ── Attachments ────────────────────────────────────────────────────────────────

class AsanaGetTaskAttachmentsConfig(BaseModel):
    """List file attachments on a task."""

    operation: Literal["get_task_attachments"] = Field(
        "get_task_attachments",
        json_schema_extra={
            "const": "get_task_attachments",
            "ui:hidden": True,
            "x-category": "Attachments",
            "x-is-trigger": False,
            "x-display-name": "Get Task Attachments",
        },
        title="Get Task Attachments",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to list attachments of.")


class AsanaDeleteAttachmentConfig(BaseModel):
    """Delete a file attachment."""

    operation: Literal["delete_attachment"] = Field(
        "delete_attachment",
        json_schema_extra={
            "const": "delete_attachment",
            "ui:hidden": True,
            "x-category": "Attachments",
            "x-is-trigger": False,
            "x-display-name": "Delete Attachment",
        },
        title="Delete Attachment",
    )
    attachment_gid: str = Field(
        ..., title="Attachment GID", description="The attachment to delete."
    )


# ── Portfolios ─────────────────────────────────────────────────────────────────

class AsanaListPortfoliosConfig(BaseModel):
    """List portfolios accessible to a user in a workspace."""

    operation: Literal["list_portfolios"] = Field(
        "list_portfolios",
        json_schema_extra={
            "const": "list_portfolios",
            "ui:hidden": True,
            "x-category": "Portfolios",
            "x-is-trigger": False,
            "x-display-name": "List Portfolios",
        },
        title="List Portfolios",
    )
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The workspace to list portfolios in.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )
    owner: Optional[str] = Field(
        None,
        title="Owner",
        description="Filter by owner user gid (or 'me' for the authenticated user).",
    )


class AsanaGetPortfolioConfig(BaseModel):
    """Get a single portfolio's details."""

    operation: Literal["get_portfolio"] = Field(
        "get_portfolio",
        json_schema_extra={
            "const": "get_portfolio",
            "ui:hidden": True,
            "x-category": "Portfolios",
            "x-is-trigger": False,
            "x-display-name": "Get Portfolio",
        },
        title="Get Portfolio",
    )
    portfolio_gid: str = Field(
        ..., title="Portfolio GID", description="The portfolio to retrieve."
    )


class AsanaCreatePortfolioConfig(BaseModel):
    """Create a new portfolio."""

    operation: Literal["create_portfolio"] = Field(
        "create_portfolio",
        json_schema_extra={
            "const": "create_portfolio",
            "ui:hidden": True,
            "x-category": "Portfolios",
            "x-is-trigger": False,
            "x-display-name": "Create Portfolio",
        },
        title="Create Portfolio",
    )
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The workspace to create the portfolio in.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )
    name: str = Field(..., title="Name", description="The name of the portfolio.")
    public: Optional[str] = Field(
        None,
        title="Public",
        description="Whether the portfolio is visible to all workspace members.",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Default", "Public", "Private"],
            "x-enum-searchable": True,
        },
    )


class AsanaGetPortfolioItemsConfig(BaseModel):
    """List projects (items) in a portfolio."""

    operation: Literal["get_portfolio_items"] = Field(
        "get_portfolio_items",
        json_schema_extra={
            "const": "get_portfolio_items",
            "ui:hidden": True,
            "x-category": "Portfolios",
            "x-is-trigger": False,
            "x-display-name": "Get Portfolio Items",
        },
        title="Get Portfolio Items",
    )
    portfolio_gid: str = Field(
        ..., title="Portfolio GID", description="The portfolio to list items (projects) from."
    )


class AsanaAddPortfolioItemConfig(BaseModel):
    """Add a project to a portfolio."""

    operation: Literal["add_portfolio_item"] = Field(
        "add_portfolio_item",
        json_schema_extra={
            "const": "add_portfolio_item",
            "ui:hidden": True,
            "x-category": "Portfolios",
            "x-is-trigger": False,
            "x-display-name": "Add Item to Portfolio",
        },
        title="Add Item to Portfolio",
    )
    portfolio_gid: str = Field(
        ..., title="Portfolio GID", description="The portfolio to add the project to."
    )
    item: str = Field(
        ..., title="Project GID", description="The project to add to the portfolio.",
    )


class AsanaRemovePortfolioItemConfig(BaseModel):
    """Remove a project from a portfolio."""

    operation: Literal["remove_portfolio_item"] = Field(
        "remove_portfolio_item",
        json_schema_extra={
            "const": "remove_portfolio_item",
            "ui:hidden": True,
            "x-category": "Portfolios",
            "x-is-trigger": False,
            "x-display-name": "Remove Item from Portfolio",
        },
        title="Remove Item from Portfolio",
    )
    portfolio_gid: str = Field(
        ..., title="Portfolio GID", description="The portfolio to remove the project from."
    )
    item: str = Field(
        ..., title="Project GID", description="The project to remove from the portfolio.",
    )


# ── Project Templates ──────────────────────────────────────────────────────────

class AsanaListProjectTemplatesConfig(BaseModel):
    """List project templates available in a workspace or team."""

    operation: Literal["list_project_templates"] = Field(
        "list_project_templates",
        json_schema_extra={
            "const": "list_project_templates",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "List Project Templates",
        },
        title="List Project Templates",
    )
    workspace_gid: Optional[str] = Field(
        None,
        title="Workspace",
        description="Filter templates to this workspace.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )
    team_gid: Optional[str] = Field(
        None, title="Team GID", description="Filter templates to this team (alternative to workspace)."
    )


class AsanaCreateProjectFromTemplateConfig(BaseModel):
    """Instantiate a new project from a project template."""

    operation: Literal["create_project_from_template"] = Field(
        "create_project_from_template",
        json_schema_extra={
            "const": "create_project_from_template",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Create Project from Template",
        },
        title="Create Project from Template",
    )
    project_template_gid: str = Field(
        ..., title="Template GID", description="The project template to instantiate."
    )
    name: str = Field(..., title="Project Name", description="Name for the new project.")
    team: Optional[str] = Field(None, title="Team GID", description="Team to own the new project.")
    public: Optional[str] = Field(
        None,
        title="Public",
        description="Whether the new project is public to the team.",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Default", "Public", "Private"],
            "x-enum-searchable": True,
        },
    )


# ── Time Tracking ──────────────────────────────────────────────────────────────

class AsanaGetTimeTrackingEntriesConfig(BaseModel):
    """List time tracking entries on a task."""

    operation: Literal["get_time_tracking_entries"] = Field(
        "get_time_tracking_entries",
        json_schema_extra={
            "const": "get_time_tracking_entries",
            "ui:hidden": True,
            "x-category": "Time Tracking",
            "x-is-trigger": False,
            "x-display-name": "Get Time Tracking Entries",
        },
        title="Get Time Tracking Entries",
    )
    task_gid: str = Field(
        ..., title="Task GID", description="The task to list time tracking entries for."
    )


class AsanaCreateTimeTrackingEntryConfig(BaseModel):
    """Log a time entry on a task."""

    operation: Literal["create_time_tracking_entry"] = Field(
        "create_time_tracking_entry",
        json_schema_extra={
            "const": "create_time_tracking_entry",
            "ui:hidden": True,
            "x-category": "Time Tracking",
            "x-is-trigger": False,
            "x-display-name": "Create Time Tracking Entry",
        },
        title="Create Time Tracking Entry",
    )
    task_gid: str = Field(
        ..., title="Task GID", description="The task to log time on."
    )
    duration_minutes: str = Field(
        ..., title="Duration (minutes)", description="Time logged in minutes (e.g. 90 for 1h 30m)."
    )
    entered_on: Optional[str] = Field(
        None, title="Date", description="Date the time was logged, YYYY-MM-DD. Defaults to today."
    )


class AsanaDeleteTimeTrackingEntryConfig(BaseModel):
    """Delete a time tracking entry."""

    operation: Literal["delete_time_tracking_entry"] = Field(
        "delete_time_tracking_entry",
        json_schema_extra={
            "const": "delete_time_tracking_entry",
            "ui:hidden": True,
            "x-category": "Time Tracking",
            "x-is-trigger": False,
            "x-display-name": "Delete Time Tracking Entry",
        },
        title="Delete Time Tracking Entry",
    )
    time_tracking_entry_gid: str = Field(
        ..., title="Entry GID", description="The time tracking entry to delete."
    )


# ── User Task List (My Tasks) ──────────────────────────────────────────────────

class AsanaGetUserTaskListConfig(BaseModel):
    """Get a user's personal 'My Tasks' task list."""

    operation: Literal["get_user_task_list"] = Field(
        "get_user_task_list",
        json_schema_extra={
            "const": "get_user_task_list",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Get User Task List",
        },
        title="Get User Task List",
    )
    user_gid: str = Field(
        ..., title="User GID / me", description="The user's gid, or 'me' for the authenticated user."
    )
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The workspace to find the user's task list in.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )


class AsanaGetUserTaskListTasksConfig(BaseModel):
    """List tasks in a user's My Tasks list."""

    operation: Literal["get_user_task_list_tasks"] = Field(
        "get_user_task_list_tasks",
        json_schema_extra={
            "const": "get_user_task_list_tasks",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Get My Tasks",
        },
        title="Get My Tasks",
    )
    user_task_list_gid: str = Field(
        ..., title="Task List GID", description="The task list gid (from Get User Task List)."
    )
    completed_since: Optional[str] = Field(
        None, title="Completed Since", description="Only return tasks completed since this ISO 8601 time (use 'now' for incomplete tasks only)."
    )
    limit: Optional[str] = Field("100", title="Limit", description="Max tasks to return (1-100).")


# ── Goals ──────────────────────────────────────────────────────────────────────

class AsanaListGoalsConfig(BaseModel):
    """List goals in a workspace (requires premium/business plan)."""

    operation: Literal["list_goals"] = Field(
        "list_goals",
        json_schema_extra={
            "const": "list_goals",
            "ui:hidden": True,
            "x-category": "Goals",
            "x-is-trigger": False,
            "x-display-name": "List Goals",
        },
        title="List Goals",
    )
    workspace_gid: Optional[str] = Field(
        None,
        title="Workspace",
        description="Filter goals to this workspace.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )
    team_gid: Optional[str] = Field(None, title="Team GID", description="Filter goals to this team.")
    is_workspace_level: Optional[str] = Field(
        None,
        title="Workspace Level Only",
        description="Return only workspace-level (not team) goals.",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["All", "Workspace-level only", "Team goals only"],
            "x-enum-searchable": True,
        },
    )


class AsanaGetGoalConfig(BaseModel):
    """Get a single goal's details."""

    operation: Literal["get_goal"] = Field(
        "get_goal",
        json_schema_extra={
            "const": "get_goal",
            "ui:hidden": True,
            "x-category": "Goals",
            "x-is-trigger": False,
            "x-display-name": "Get Goal",
        },
        title="Get Goal",
    )
    goal_gid: str = Field(..., title="Goal GID", description="The goal to retrieve.")


class AsanaCreateGoalConfig(BaseModel):
    """Create a goal in a workspace or team."""

    operation: Literal["create_goal"] = Field(
        "create_goal",
        json_schema_extra={
            "const": "create_goal",
            "ui:hidden": True,
            "x-category": "Goals",
            "x-is-trigger": False,
            "x-display-name": "Create Goal",
        },
        title="Create Goal",
    )
    name: str = Field(..., title="Name", description="The goal name.")
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The workspace to create the goal in.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )
    notes: Optional[str] = Field(
        None, title="Notes", description="Goal description.", json_schema_extra={"ui:widget": "textarea"}
    )
    team_gid: Optional[str] = Field(
        None, title="Team GID", description="Team to associate the goal with (leave blank for workspace-level)."
    )
    due_on: Optional[str] = Field(None, title="Due On", description="Goal due date in YYYY-MM-DD format.")
    start_on: Optional[str] = Field(None, title="Start On", description="Goal start date in YYYY-MM-DD format.")


class AsanaUpdateGoalConfig(BaseModel):
    """Update a goal's name, status, notes, or dates."""

    operation: Literal["update_goal"] = Field(
        "update_goal",
        json_schema_extra={
            "const": "update_goal",
            "ui:hidden": True,
            "x-category": "Goals",
            "x-is-trigger": False,
            "x-display-name": "Update Goal",
        },
        title="Update Goal",
    )
    goal_gid: str = Field(..., title="Goal GID", description="The goal to update.")
    name: Optional[str] = Field(None, title="Name", description="New goal name.")
    notes: Optional[str] = Field(
        None, title="Notes", description="New goal notes.", json_schema_extra={"ui:widget": "textarea"}
    )
    due_on: Optional[str] = Field(None, title="Due On", description="New due date YYYY-MM-DD.")
    start_on: Optional[str] = Field(None, title="Start On", description="New start date YYYY-MM-DD.")
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Goal status color.",
        json_schema_extra={
            "enum": ["", "green", "yellow", "red", "missed", "achieved"],
            "enumNames": ["No change", "On Track", "At Risk", "Off Track", "Missed", "Achieved"],
            "x-enum-searchable": True,
        },
    )


class AsanaDeleteGoalConfig(BaseModel):
    """Delete a goal."""

    operation: Literal["delete_goal"] = Field(
        "delete_goal",
        json_schema_extra={
            "const": "delete_goal",
            "ui:hidden": True,
            "x-category": "Goals",
            "x-is-trigger": False,
            "x-display-name": "Delete Goal",
        },
        title="Delete Goal",
    )
    goal_gid: str = Field(..., title="Goal GID", description="The goal to delete.")


# ── Stories (individual) ───────────────────────────────────────────────────────

class AsanaGetStoryConfig(BaseModel):
    """Get a single story (comment or activity event) by its gid."""

    operation: Literal["get_story"] = Field(
        "get_story",
        json_schema_extra={
            "const": "get_story",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "Get Story / Comment",
        },
        title="Get Story / Comment",
    )
    story_gid: str = Field(..., title="Story GID", description="The story (comment/event) to retrieve.")


# ── Custom Fields ──────────────────────────────────────────────────────────────

class AsanaGetCustomFieldConfig(BaseModel):
    """Get a custom field definition."""

    operation: Literal["get_custom_field"] = Field(
        "get_custom_field",
        json_schema_extra={
            "const": "get_custom_field",
            "ui:hidden": True,
            "x-category": "Custom Fields",
            "x-is-trigger": False,
            "x-display-name": "Get Custom Field",
        },
        title="Get Custom Field",
    )
    custom_field_gid: str = Field(
        ..., title="Custom Field GID", description="The custom field definition to retrieve."
    )


class AsanaSetTaskCustomFieldConfig(BaseModel):
    """Set a custom field value on a task."""

    operation: Literal["set_task_custom_field"] = Field(
        "set_task_custom_field",
        json_schema_extra={
            "const": "set_task_custom_field",
            "ui:hidden": True,
            "x-category": "Custom Fields",
            "x-is-trigger": False,
            "x-display-name": "Set Task Custom Field",
        },
        title="Set Task Custom Field",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to update.")
    custom_field_gid: str = Field(
        ..., title="Custom Field GID", description="The gid of the custom field to set."
    )
    value: str = Field(
        ...,
        title="Value",
        description=(
            "The value to set. For text fields: the text string. "
            "For number fields: a number. For enum fields: the enum option gid. "
            "For multi-enum fields: comma-separated enum option gids."
        ),
    )


class AsanaAddCustomFieldToProjectConfig(BaseModel):
    """Add a custom field to a project."""

    operation: Literal["add_custom_field_to_project"] = Field(
        "add_custom_field_to_project",
        json_schema_extra={
            "const": "add_custom_field_to_project",
            "ui:hidden": True,
            "x-category": "Custom Fields",
            "x-is-trigger": False,
            "x-display-name": "Add Custom Field to Project",
        },
        title="Add Custom Field to Project",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to add the custom field to.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )
    custom_field_gid: str = Field(
        ..., title="Custom Field GID", description="The custom field to add."
    )
    is_important: Optional[str] = Field(
        None,
        title="Mark as Important",
        description="Whether this custom field is important (shows in list view).",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Default", "Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class AsanaRemoveCustomFieldFromProjectConfig(BaseModel):
    """Remove a custom field from a project."""

    operation: Literal["remove_custom_field_from_project"] = Field(
        "remove_custom_field_from_project",
        json_schema_extra={
            "const": "remove_custom_field_from_project",
            "ui:hidden": True,
            "x-category": "Custom Fields",
            "x-is-trigger": False,
            "x-display-name": "Remove Custom Field from Project",
        },
        title="Remove Custom Field from Project",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to remove the custom field from.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )
    custom_field_gid: str = Field(
        ..., title="Custom Field GID", description="The custom field to remove."
    )


# ── Workspace members ──────────────────────────────────────────────────────────

class AsanaListWorkspaceMembersConfig(BaseModel):
    """List all member records for a workspace."""

    operation: Literal["list_workspace_members"] = Field(
        "list_workspace_members",
        json_schema_extra={
            "const": "list_workspace_members",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "List Workspace Members",
        },
        title="List Workspace Members",
    )
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The workspace to list membership records from.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )


# ── Story / comment updates ────────────────────────────────────────────────────

class AsanaUpdateStoryConfig(BaseModel):
    """Edit the text of a comment (story) on a task."""

    operation: Literal["update_story"] = Field(
        "update_story",
        json_schema_extra={
            "const": "update_story",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Update Story / Comment",
        },
        title="Update Story / Comment",
    )
    story_gid: str = Field(..., title="Story GID", description="The story (comment) to edit.")
    text: str = Field(..., title="Text", description="The updated comment text.", json_schema_extra={"ui:widget": "textarea"})


class AsanaDeleteStoryConfig(BaseModel):
    """Delete a comment (story) from a task."""

    operation: Literal["delete_story"] = Field(
        "delete_story",
        json_schema_extra={
            "const": "delete_story",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Delete Story / Comment",
        },
        title="Delete Story / Comment",
    )
    story_gid: str = Field(..., title="Story GID", description="The story (comment) to delete.")


# ── Tasks (additional read paths) ─────────────────────────────────────────────

class AsanaGetTasksForTagConfig(BaseModel):
    """List tasks that have a specific tag."""

    operation: Literal["get_tasks_for_tag"] = Field(
        "get_tasks_for_tag",
        json_schema_extra={
            "const": "get_tasks_for_tag",
            "ui:hidden": True,
            "x-category": "Tags",
            "x-is-trigger": False,
            "x-display-name": "Get Tasks for Tag",
        },
        title="Get Tasks for Tag",
    )
    tag_gid: str = Field(
        ..., title="Tag", description="The tag whose tasks to retrieve.",
        json_schema_extra={"x-dynamic-options": {"field_name": "tag_gid", "placeholder": "Select a tag...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste tag gid"}, "x-resource-type": "asana_tag"},
    )
    limit: Optional[str] = Field("100", title="Limit", description="Max tasks to return (1-100).")


class AsanaGetTaskProjectsConfig(BaseModel):
    """List projects that a task belongs to."""

    operation: Literal["get_task_projects"] = Field(
        "get_task_projects",
        json_schema_extra={
            "const": "get_task_projects",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Get Projects for Task",
        },
        title="Get Projects for Task",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to list projects for.")


class AsanaGetSectionTasksConfig(BaseModel):
    """List tasks in a specific section."""

    operation: Literal["get_section_tasks"] = Field(
        "get_section_tasks",
        json_schema_extra={
            "const": "get_section_tasks",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Get Tasks in Section",
        },
        title="Get Tasks in Section",
    )
    section_gid: str = Field(
        ..., title="Section", description="The section to list tasks from.",
        json_schema_extra={"x-dynamic-options": {"field_name": "section_gid", "placeholder": "Select a section...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste section gid"}, "x-resource-type": "asana_section"},
    )
    limit: Optional[str] = Field("100", title="Limit", description="Max tasks to return (1-100).")


class AsanaGetProjectTaskCountsConfig(BaseModel):
    """Get task counts for a project (total, completed, incomplete, etc.)."""

    operation: Literal["get_project_task_counts"] = Field(
        "get_project_task_counts",
        json_schema_extra={
            "const": "get_project_task_counts",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Get Project Task Counts",
        },
        title="Get Project Task Counts",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to get task counts for.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )


class AsanaSetTaskParentConfig(BaseModel):
    """Set or change the parent task of a task (makes it a subtask)."""

    operation: Literal["set_task_parent"] = Field(
        "set_task_parent",
        json_schema_extra={
            "const": "set_task_parent",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Set Task Parent",
        },
        title="Set Task Parent",
    )
    task_gid: str = Field(..., title="Task GID", description="The task to reparent.")
    parent: Optional[str] = Field(
        None,
        title="Parent Task GID",
        description="The new parent task gid, or leave blank to make it a top-level task.",
    )


# ── Status Updates (modern API — supersedes project_statuses) ──────────────────

class AsanaGetStatusUpdatesConfig(BaseModel):
    """List status updates for a project, portfolio, or goal (modern API)."""

    operation: Literal["get_status_updates"] = Field(
        "get_status_updates",
        json_schema_extra={
            "const": "get_status_updates",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Get Status Updates",
        },
        title="Get Status Updates",
    )
    parent_gid: str = Field(
        ...,
        title="Parent GID",
        description="The gid of the project, portfolio, or goal to retrieve status updates for.",
    )
    limit: Optional[str] = Field("50", title="Limit", description="Max updates to return (1-100).")


class AsanaCreateStatusUpdateConfig(BaseModel):
    """Create a status update for a project, portfolio, or goal (modern API)."""

    operation: Literal["create_status_update"] = Field(
        "create_status_update",
        json_schema_extra={
            "const": "create_status_update",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Create Status Update",
        },
        title="Create Status Update",
    )
    parent_gid: str = Field(
        ...,
        title="Parent GID",
        description="The gid of the project, portfolio, or goal to post the update on.",
    )
    title: str = Field(..., title="Title", description="Short title for the status update.")
    text: str = Field(
        ..., title="Text", description="The status message body.", json_schema_extra={"ui:widget": "textarea"}
    )
    status_type: str = Field(
        "on_track",
        title="Status",
        description="The health/status color for this update.",
        json_schema_extra={
            "enum": ["on_track", "at_risk", "off_track", "at_completion", "achieved", "partial", "missed", "dropped", "no_status"],
            "enumNames": ["On Track", "At Risk", "Off Track", "At Completion", "Achieved", "Partial", "Missed", "Dropped", "No Status"],
            "x-enum-searchable": True,
        },
    )


class AsanaDeleteStatusUpdateConfig(BaseModel):
    """Delete a status update."""

    operation: Literal["delete_status_update"] = Field(
        "delete_status_update",
        json_schema_extra={
            "const": "delete_status_update",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Delete Status Update",
        },
        title="Delete Status Update",
    )
    status_update_gid: str = Field(
        ..., title="Status Update GID", description="The status update to delete."
    )


# ── Project Briefs ─────────────────────────────────────────────────────────────

class AsanaCreateProjectBriefConfig(BaseModel):
    """Create a project brief (rich-text overview for a project)."""

    operation: Literal["create_project_brief"] = Field(
        "create_project_brief",
        json_schema_extra={
            "const": "create_project_brief",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Create Project Brief",
        },
        title="Create Project Brief",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to create the brief for.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )
    title: str = Field(..., title="Title", description="The title of the project brief.")
    html_text: Optional[str] = Field(
        None,
        title="HTML Content",
        description="The rich-text body of the brief in HTML format.",
        json_schema_extra={"ui:widget": "textarea"},
    )


class AsanaGetProjectBriefConfig(BaseModel):
    """Get a project brief."""

    operation: Literal["get_project_brief"] = Field(
        "get_project_brief",
        json_schema_extra={
            "const": "get_project_brief",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Get Project Brief",
        },
        title="Get Project Brief",
    )
    project_brief_gid: str = Field(..., title="Brief GID", description="The project brief to retrieve.")


class AsanaUpdateProjectBriefConfig(BaseModel):
    """Update a project brief's title or content."""

    operation: Literal["update_project_brief"] = Field(
        "update_project_brief",
        json_schema_extra={
            "const": "update_project_brief",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Update Project Brief",
        },
        title="Update Project Brief",
    )
    project_brief_gid: str = Field(..., title="Brief GID", description="The project brief to update.")
    title: Optional[str] = Field(None, title="Title", description="New title for the brief.")
    html_text: Optional[str] = Field(
        None,
        title="HTML Content",
        description="New HTML content for the brief.",
        json_schema_extra={"ui:widget": "textarea"},
    )


class AsanaDeleteProjectBriefConfig(BaseModel):
    """Delete a project brief."""

    operation: Literal["delete_project_brief"] = Field(
        "delete_project_brief",
        json_schema_extra={
            "const": "delete_project_brief",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Delete Project Brief",
        },
        title="Delete Project Brief",
    )
    project_brief_gid: str = Field(..., title="Brief GID", description="The project brief to delete.")


# ── Custom Fields — full CRUD ──────────────────────────────────────────────────

class AsanaCreateCustomFieldConfig(BaseModel):
    """Create a custom field definition in a workspace."""

    operation: Literal["create_custom_field"] = Field(
        "create_custom_field",
        json_schema_extra={
            "const": "create_custom_field",
            "ui:hidden": True,
            "x-category": "Custom Fields",
            "x-is-trigger": False,
            "x-display-name": "Create Custom Field",
        },
        title="Create Custom Field",
    )
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The workspace to create the custom field in.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )
    name: str = Field(..., title="Name", description="The name of the custom field.")
    field_type: str = Field(
        "text",
        title="Field Type",
        description="The type of data this field stores.",
        json_schema_extra={
            "enum": ["text", "number", "enum", "multi_enum", "date", "people"],
            "enumNames": ["Text", "Number", "Enum (single select)", "Multi-enum (multi select)", "Date", "People"],
            "x-enum-searchable": True,
        },
    )
    description: Optional[str] = Field(None, title="Description", description="Help text for this field.")
    precision: Optional[str] = Field(
        None, title="Precision", description="For number fields: decimal precision (0-6)."
    )


class AsanaUpdateCustomFieldConfig(BaseModel):
    """Update a custom field's name, description, or settings."""

    operation: Literal["update_custom_field"] = Field(
        "update_custom_field",
        json_schema_extra={
            "const": "update_custom_field",
            "ui:hidden": True,
            "x-category": "Custom Fields",
            "x-is-trigger": False,
            "x-display-name": "Update Custom Field",
        },
        title="Update Custom Field",
    )
    custom_field_gid: str = Field(
        ..., title="Custom Field GID", description="The custom field to update."
    )
    name: Optional[str] = Field(None, title="Name", description="New name for the custom field.")
    description: Optional[str] = Field(None, title="Description", description="New description.")


class AsanaDeleteCustomFieldConfig(BaseModel):
    """Delete a custom field definition from the workspace."""

    operation: Literal["delete_custom_field"] = Field(
        "delete_custom_field",
        json_schema_extra={
            "const": "delete_custom_field",
            "ui:hidden": True,
            "x-category": "Custom Fields",
            "x-is-trigger": False,
            "x-display-name": "Delete Custom Field",
        },
        title="Delete Custom Field",
    )
    custom_field_gid: str = Field(
        ..., title="Custom Field GID", description="The custom field to delete."
    )


# ── Jobs ───────────────────────────────────────────────────────────────────────

class AsanaGetJobConfig(BaseModel):
    """Poll an async job (e.g. from duplicate_project / create_project_from_template).

    Returns the job status and a ``new_project`` link when complete.
    """

    operation: Literal["get_job"] = Field(
        "get_job",
        json_schema_extra={
            "const": "get_job",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Get Job Status",
        },
        title="Get Job Status",
    )
    job_gid: str = Field(..., title="Job GID", description="The gid of the async job to poll.")


# ── Save project as template ───────────────────────────────────────────────────

class AsanaSaveProjectAsTemplateConfig(BaseModel):
    """Save an existing project as a project template."""

    operation: Literal["save_project_as_template"] = Field(
        "save_project_as_template",
        json_schema_extra={
            "const": "save_project_as_template",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Save Project as Template",
        },
        title="Save Project as Template",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to save as a template.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )
    name: str = Field(..., title="Template Name", description="The name for the new template.")
    workspace_gid: Optional[str] = Field(
        None,
        title="Workspace",
        description="The workspace to scope the template to (required when team is not set).",
        json_schema_extra={"x-dynamic-options": {"field_name": "workspace_gid", "placeholder": "Select a workspace...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste workspace gid"}, "x-resource-type": "asana_workspace"},
    )
    public: Optional[str] = Field(
        None,
        title="Public",
        description="Whether the template is available to the entire workspace.",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Default", "Public", "Private"],
            "x-enum-searchable": True,
        },
    )
    team: Optional[str] = Field(None, title="Team GID", description="The team to scope the template to.")


# ── Update time tracking entry ─────────────────────────────────────────────────

class AsanaUpdateTimeTrackingEntryConfig(BaseModel):
    """Update the duration or date of an existing time tracking entry."""

    operation: Literal["update_time_tracking_entry"] = Field(
        "update_time_tracking_entry",
        json_schema_extra={
            "const": "update_time_tracking_entry",
            "ui:hidden": True,
            "x-category": "Time Tracking",
            "x-is-trigger": False,
            "x-display-name": "Update Time Tracking Entry",
        },
        title="Update Time Tracking Entry",
    )
    time_tracking_entry_gid: str = Field(
        ..., title="Entry GID", description="The time tracking entry to update."
    )
    duration_minutes: Optional[str] = Field(
        None, title="Duration (minutes)", description="New duration in minutes."
    )
    entered_on: Optional[str] = Field(
        None, title="Date", description="New date for the entry, YYYY-MM-DD."
    )


# ── Task Templates ────────────────────────────────────────────────────────────

class AsanaListTaskTemplatesConfig(BaseModel):
    """List task templates in a project."""

    operation: Literal["list_task_templates"] = Field(
        "list_task_templates",
        json_schema_extra={
            "const": "list_task_templates",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "List Task Templates",
        },
        title="List Task Templates",
    )
    project_gid: Optional[str] = Field(
        None, title="Project", description="Filter templates to this project.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )


class AsanaCreateTaskFromTemplateConfig(BaseModel):
    """Instantiate a task from a task template."""

    operation: Literal["create_task_from_template"] = Field(
        "create_task_from_template",
        json_schema_extra={
            "const": "create_task_from_template",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Create Task from Template",
        },
        title="Create Task from Template",
    )
    task_template_gid: str = Field(
        ..., title="Task Template GID", description="The task template to instantiate."
    )


# ── Typeahead search ───────────────────────────────────────────────────────────

class AsanaTypeaheadSearchConfig(BaseModel):
    """Search across all object types in a workspace (typeahead / autocomplete)."""

    operation: Literal["typeahead_search"] = Field(
        "typeahead_search",
        json_schema_extra={
            "const": "typeahead_search",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "Typeahead Search",
            "x-keywords": "search find autocomplete lookup objects",
        },
        title="Typeahead Search",
    )
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The workspace to search within.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )
    query: str = Field(..., title="Query", description="The search string (typeahead / prefix match).")
    resource_type: str = Field(
        "task",
        title="Resource Type",
        description="The type of object to search for.",
        json_schema_extra={
            "enum": ["task", "project", "section", "tag", "user", "portfolio", "goal"],
            "enumNames": ["Tasks", "Projects", "Sections", "Tags", "Users", "Portfolios", "Goals"],
            "x-enum-searchable": True,
        },
    )
    count: Optional[str] = Field("20", title="Max Results", description="Max number of results to return.")


# ── Goal extras ────────────────────────────────────────────────────────────────

class AsanaGetGoalParentGoalsConfig(BaseModel):
    """List parent goals for a goal (supporting relationship traversal)."""

    operation: Literal["get_goal_parent_goals"] = Field(
        "get_goal_parent_goals",
        json_schema_extra={
            "const": "get_goal_parent_goals",
            "ui:hidden": True,
            "x-category": "Goals",
            "x-is-trigger": False,
            "x-display-name": "Get Parent Goals",
        },
        title="Get Parent Goals",
    )
    goal_gid: str = Field(..., title="Goal GID", description="The goal to get parent goals for.")


class AsanaSetGoalMetricConfig(BaseModel):
    """Set a metric on a goal (defines how goal progress is measured)."""

    operation: Literal["set_goal_metric"] = Field(
        "set_goal_metric",
        json_schema_extra={
            "const": "set_goal_metric",
            "ui:hidden": True,
            "x-category": "Goals",
            "x-is-trigger": False,
            "x-display-name": "Set Goal Metric",
        },
        title="Set Goal Metric",
    )
    goal_gid: str = Field(..., title="Goal GID", description="The goal to set a metric on.")
    metric_type: str = Field(
        "number",
        title="Metric Type",
        description="How goal progress is measured.",
        json_schema_extra={
            "enum": ["number", "percentage", "currency"],
            "enumNames": ["Number", "Percentage", "Currency"],
            "x-enum-searchable": True,
        },
    )
    target_value: str = Field(
        ..., title="Target Value", description="The numeric target for the metric (e.g. 100)."
    )
    initial_value: Optional[str] = Field(
        None, title="Initial Value", description="Starting value (defaults to 0)."
    )
    unit: Optional[str] = Field(
        None, title="Unit", description="Unit label for number metrics (e.g. 'users', 'deals')."
    )


class AsanaUpdateGoalMetricConfig(BaseModel):
    """Update the current value of a goal's metric."""

    operation: Literal["update_goal_metric"] = Field(
        "update_goal_metric",
        json_schema_extra={
            "const": "update_goal_metric",
            "ui:hidden": True,
            "x-category": "Goals",
            "x-is-trigger": False,
            "x-display-name": "Update Goal Metric Value",
        },
        title="Update Goal Metric Value",
    )
    goal_gid: str = Field(..., title="Goal GID", description="The goal whose metric to update.")
    current_value: str = Field(
        ..., title="Current Value", description="The new current progress value."
    )


class AsanaAddGoalFollowersConfig(BaseModel):
    """Add followers / collaborators to a goal."""

    operation: Literal["add_goal_followers"] = Field(
        "add_goal_followers",
        json_schema_extra={
            "const": "add_goal_followers",
            "ui:hidden": True,
            "x-category": "Goals",
            "x-is-trigger": False,
            "x-display-name": "Add Goal Followers",
        },
        title="Add Goal Followers",
    )
    goal_gid: str = Field(..., title="Goal GID", description="The goal to add followers to.")
    followers: str = Field(
        ..., title="Followers", description="Comma-separated user gids or emails to add."
    )


class AsanaRemoveGoalFollowersConfig(BaseModel):
    """Remove followers / collaborators from a goal."""

    operation: Literal["remove_goal_followers"] = Field(
        "remove_goal_followers",
        json_schema_extra={
            "const": "remove_goal_followers",
            "ui:hidden": True,
            "x-category": "Goals",
            "x-is-trigger": False,
            "x-display-name": "Remove Goal Followers",
        },
        title="Remove Goal Followers",
    )
    goal_gid: str = Field(..., title="Goal GID", description="The goal to remove followers from.")
    followers: str = Field(
        ..., title="Followers", description="Comma-separated user gids or emails to remove."
    )


# ── Portfolio extras ───────────────────────────────────────────────────────────

class AsanaUpdatePortfolioConfig(BaseModel):
    """Update a portfolio's name or public setting."""

    operation: Literal["update_portfolio"] = Field(
        "update_portfolio",
        json_schema_extra={
            "const": "update_portfolio",
            "ui:hidden": True,
            "x-category": "Portfolios",
            "x-is-trigger": False,
            "x-display-name": "Update Portfolio",
        },
        title="Update Portfolio",
    )
    portfolio_gid: str = Field(..., title="Portfolio GID", description="The portfolio to update.")
    name: Optional[str] = Field(None, title="Name", description="New portfolio name.")
    public: Optional[str] = Field(
        None,
        title="Public",
        description="Whether the portfolio is visible to all workspace members.",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["No change", "Public", "Private"],
            "x-enum-searchable": True,
        },
    )


class AsanaDeletePortfolioConfig(BaseModel):
    """Delete a portfolio."""

    operation: Literal["delete_portfolio"] = Field(
        "delete_portfolio",
        json_schema_extra={
            "const": "delete_portfolio",
            "ui:hidden": True,
            "x-category": "Portfolios",
            "x-is-trigger": False,
            "x-display-name": "Delete Portfolio",
        },
        title="Delete Portfolio",
    )
    portfolio_gid: str = Field(..., title="Portfolio GID", description="The portfolio to delete.")


class AsanaAddPortfolioMembersConfig(BaseModel):
    """Add members to a portfolio."""

    operation: Literal["add_portfolio_members"] = Field(
        "add_portfolio_members",
        json_schema_extra={
            "const": "add_portfolio_members",
            "ui:hidden": True,
            "x-category": "Portfolios",
            "x-is-trigger": False,
            "x-display-name": "Add Portfolio Members",
        },
        title="Add Portfolio Members",
    )
    portfolio_gid: str = Field(..., title="Portfolio GID", description="The portfolio to add members to.")
    members: str = Field(
        ..., title="Members", description="Comma-separated user gids or emails to add."
    )


class AsanaRemovePortfolioMembersConfig(BaseModel):
    """Remove members from a portfolio."""

    operation: Literal["remove_portfolio_members"] = Field(
        "remove_portfolio_members",
        json_schema_extra={
            "const": "remove_portfolio_members",
            "ui:hidden": True,
            "x-category": "Portfolios",
            "x-is-trigger": False,
            "x-display-name": "Remove Portfolio Members",
        },
        title="Remove Portfolio Members",
    )
    portfolio_gid: str = Field(..., title="Portfolio GID", description="The portfolio to remove members from.")
    members: str = Field(
        ..., title="Members", description="Comma-separated user gids or emails to remove."
    )


# ── Project followers ──────────────────────────────────────────────────────────

class AsanaAddProjectFollowersConfig(BaseModel):
    """Add followers to a project."""

    operation: Literal["add_project_followers"] = Field(
        "add_project_followers",
        json_schema_extra={
            "const": "add_project_followers",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Add Project Followers",
        },
        title="Add Project Followers",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to add followers to.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )
    followers: str = Field(
        ..., title="Followers", description="Comma-separated user gids or emails to add."
    )


class AsanaRemoveProjectFollowersConfig(BaseModel):
    """Remove followers from a project."""

    operation: Literal["remove_project_followers"] = Field(
        "remove_project_followers",
        json_schema_extra={
            "const": "remove_project_followers",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Remove Project Followers",
        },
        title="Remove Project Followers",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to remove followers from.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )
    followers: str = Field(
        ..., title="Followers", description="Comma-separated user gids or emails to remove."
    )


# ── Workspace user management ──────────────────────────────────────────────────

class AsanaAddWorkspaceUserConfig(BaseModel):
    """Add a user (invite them) to a workspace or organization."""

    operation: Literal["add_workspace_user"] = Field(
        "add_workspace_user",
        json_schema_extra={
            "const": "add_workspace_user",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "Add Workspace User",
        },
        title="Add Workspace User",
    )
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The workspace to add the user to.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )
    user: str = Field(..., title="User GID / Email", description="The user to add.")


class AsanaRemoveWorkspaceUserConfig(BaseModel):
    """Remove a user from a workspace or organization."""

    operation: Literal["remove_workspace_user"] = Field(
        "remove_workspace_user",
        json_schema_extra={
            "const": "remove_workspace_user",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "Remove Workspace User",
        },
        title="Remove Workspace User",
    )
    workspace_gid: str = Field(
        ...,
        title="Workspace",
        description="The workspace to remove the user from.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workspace_gid",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workspace gid",
            },
            "x-resource-type": "asana_workspace",
        },
    )
    user: str = Field(..., title="User GID / Email", description="The user to remove.")


# ── Project custom field settings ──────────────────────────────────────────────

class AsanaGetProjectCustomFieldsConfig(BaseModel):
    """List custom field settings (definitions) attached to a project."""

    operation: Literal["get_project_custom_fields"] = Field(
        "get_project_custom_fields",
        json_schema_extra={
            "const": "get_project_custom_fields",
            "ui:hidden": True,
            "x-category": "Custom Fields",
            "x-is-trigger": False,
            "x-display-name": "Get Project Custom Fields",
        },
        title="Get Project Custom Fields",
    )
    project_gid: str = Field(
        ..., title="Project", description="The project to retrieve custom field settings from.",
        json_schema_extra={"x-dynamic-options": {"field_name": "project_gid", "placeholder": "Select a project...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste project gid"}, "x-resource-type": "asana_project"},
    )


# ── Trigger a rule ─────────────────────────────────────────────────────────────

class AsanaTriggerRuleConfig(BaseModel):
    """Trigger a rule that uses an 'incoming web request' trigger."""

    operation: Literal["trigger_rule"] = Field(
        "trigger_rule",
        json_schema_extra={
            "const": "trigger_rule",
            "ui:hidden": True,
            "x-category": "Workspaces",
            "x-is-trigger": False,
            "x-display-name": "Trigger Rule",
        },
        title="Trigger Rule",
    )
    rule_trigger_gid: str = Field(
        ..., title="Rule Trigger GID", description="The gid of the 'incoming web request' rule trigger."
    )
    action_data: Optional[str] = Field(
        None,
        title="Action Data (JSON)",
        description="Optional JSON object to pass as action data to the rule.",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class AsanaTriggerConfig(BaseModel):
    """Fire the workflow when an Asana resource changes.

    Asana webhooks are registered against the NoClick webhook URL via the Asana
    API; events arrive signed with ``X-Hook-Signature`` (hex HMAC-SHA256 keyed
    by the handshake secret).
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_resource_change"] = Field(
        "on_resource_change",
        json_schema_extra={
            "const": "on_resource_change",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Resource Change",
        },
        title="On Resource Change",
    )
    resource_gid: Optional[str] = Field(
        default=None,
        title="Resource to Watch",
        description=(
            "The gid of the Asana resource (task, project, section, etc.) to watch. "
            "When set, the trigger registers an Asana webhook (POST /webhooks) on it "
            "with your selected event filters."
        ),
    )
    event_types: str = Field(
        ASANA_ALL_EVENTS,
        title="Event Types",
        description=(
            "Comma-separated list of Asana event actions that fire this trigger. "
            "Use `*` (default) for all events. Options: "
            "`added` (a resource was created), `changed` (a resource was modified), "
            "`removed` (a resource was detached from a parent), "
            "`deleted` (a resource was deleted), `undeleted` (a deletion was undone). "
            "Selected actions become the webhook's `filters` so Asana only delivers "
            "matching events, and are re-checked on each inbound delivery."
        ),
        json_schema_extra={
            "enum": [ASANA_ALL_EVENTS, *ASANA_TRIGGER_ACTIONS],
            "enumNames": ["All events", *ASANA_TRIGGER_ACTION_LABELS],
            "x-enum-searchable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Register this URL as the target of an Asana webhook (POST /webhooks) on the resource you want to watch.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


AsanaConfig = Annotated[
    Union[
        # ── Users ───────────────────────────────────────────────────────────
        AsanaGetMeConfig,
        AsanaListUsersConfig,
        AsanaGetUserConfig,
        # ── Workspaces ──────────────────────────────────────────────────────
        AsanaListWorkspacesConfig,
        AsanaListTeamsConfig,
        AsanaListCustomFieldsConfig,
        AsanaListWorkspaceMembersConfig,
        AsanaAddWorkspaceUserConfig,
        AsanaRemoveWorkspaceUserConfig,
        AsanaTypeaheadSearchConfig,
        # ── Teams ───────────────────────────────────────────────────────────
        AsanaGetTeamConfig,
        AsanaGetTeamMembersConfig,
        AsanaAddTeamMemberConfig,
        AsanaRemoveTeamMemberConfig,
        # ── Projects ────────────────────────────────────────────────────────
        AsanaListProjectsConfig,
        AsanaGetProjectConfig,
        AsanaCreateProjectConfig,
        AsanaUpdateProjectConfig,
        AsanaDeleteProjectConfig,
        AsanaDuplicateProjectConfig,
        AsanaGetProjectMembersConfig,
        AsanaAddProjectMemberConfig,
        AsanaRemoveProjectMemberConfig,
        AsanaAddProjectFollowersConfig,
        AsanaRemoveProjectFollowersConfig,
        AsanaGetProjectTaskCountsConfig,
        AsanaGetProjectStatusesConfig,
        AsanaCreateProjectStatusConfig,
        AsanaDeleteProjectStatusConfig,
        AsanaGetStatusUpdatesConfig,
        AsanaCreateStatusUpdateConfig,
        AsanaDeleteStatusUpdateConfig,
        AsanaGetProjectBriefConfig,
        AsanaCreateProjectBriefConfig,
        AsanaUpdateProjectBriefConfig,
        AsanaDeleteProjectBriefConfig,
        AsanaListProjectTemplatesConfig,
        AsanaCreateProjectFromTemplateConfig,
        AsanaSaveProjectAsTemplateConfig,
        AsanaGetJobConfig,
        AsanaGetProjectCustomFieldsConfig,
        # ── Sections ────────────────────────────────────────────────────────
        AsanaListProjectSectionsConfig,
        AsanaGetSectionConfig,
        AsanaCreateSectionConfig,
        AsanaUpdateSectionConfig,
        AsanaDeleteSectionConfig,
        AsanaGetSectionTasksConfig,
        # ── Tasks ───────────────────────────────────────────────────────────
        AsanaSearchTasksConfig,
        AsanaGetTaskConfig,
        AsanaCreateTaskConfig,
        AsanaUpdateTaskConfig,
        AsanaDeleteTaskConfig,
        AsanaDuplicateTaskConfig,
        AsanaListProjectTasksConfig,
        AsanaAddTaskToProjectConfig,
        AsanaRemoveTaskFromProjectConfig,
        AsanaAddTaskToSectionConfig,
        AsanaSetTaskParentConfig,
        AsanaGetTaskProjectsConfig,
        AsanaListSubtasksConfig,
        AsanaCreateSubtaskConfig,
        AsanaGetTaskDependenciesConfig,
        AsanaAddDependenciesToTaskConfig,
        AsanaRemoveDependenciesFromTaskConfig,
        AsanaGetTaskDependentsConfig,
        AsanaAddTaskDependentsConfig,
        AsanaRemoveTaskDependentsConfig,
        AsanaAddFollowersConfig,
        AsanaRemoveFollowersConfig,
        AsanaGetTasksForTagConfig,
        AsanaListTaskTemplatesConfig,
        AsanaCreateTaskFromTemplateConfig,
        # ── Comments / Stories ───────────────────────────────────────────────
        AsanaAddCommentConfig,
        AsanaListCommentsConfig,
        AsanaGetStoryConfig,
        AsanaUpdateStoryConfig,
        AsanaDeleteStoryConfig,
        # ── Tags ────────────────────────────────────────────────────────────
        AsanaListTagsConfig,
        AsanaGetTagConfig,
        AsanaCreateTagConfig,
        AsanaUpdateTagConfig,
        AsanaDeleteTagConfig,
        AsanaAddTagToTaskConfig,
        AsanaRemoveTagFromTaskConfig,
        AsanaGetTagsForTaskConfig,
        # ── Custom Fields ────────────────────────────────────────────────────
        AsanaGetCustomFieldConfig,
        AsanaCreateCustomFieldConfig,
        AsanaUpdateCustomFieldConfig,
        AsanaDeleteCustomFieldConfig,
        AsanaSetTaskCustomFieldConfig,
        AsanaAddCustomFieldToProjectConfig,
        AsanaRemoveCustomFieldFromProjectConfig,
        # ── Attachments ─────────────────────────────────────────────────────
        AsanaGetTaskAttachmentsConfig,
        AsanaDeleteAttachmentConfig,
        # ── Time Tracking ────────────────────────────────────────────────────
        AsanaGetTimeTrackingEntriesConfig,
        AsanaCreateTimeTrackingEntryConfig,
        AsanaUpdateTimeTrackingEntryConfig,
        AsanaDeleteTimeTrackingEntryConfig,
        # ── User Task List (My Tasks) ─────────────────────────────────────────
        AsanaGetUserTaskListConfig,
        AsanaGetUserTaskListTasksConfig,
        # ── Portfolios ───────────────────────────────────────────────────────
        AsanaListPortfoliosConfig,
        AsanaGetPortfolioConfig,
        AsanaCreatePortfolioConfig,
        AsanaUpdatePortfolioConfig,
        AsanaDeletePortfolioConfig,
        AsanaGetPortfolioItemsConfig,
        AsanaAddPortfolioItemConfig,
        AsanaRemovePortfolioItemConfig,
        AsanaAddPortfolioMembersConfig,
        AsanaRemovePortfolioMembersConfig,
        # ── Goals ────────────────────────────────────────────────────────────
        AsanaListGoalsConfig,
        AsanaGetGoalConfig,
        AsanaCreateGoalConfig,
        AsanaUpdateGoalConfig,
        AsanaDeleteGoalConfig,
        AsanaGetGoalParentGoalsConfig,
        AsanaSetGoalMetricConfig,
        AsanaUpdateGoalMetricConfig,
        AsanaAddGoalFollowersConfig,
        AsanaRemoveGoalFollowersConfig,
        # ── Rules ────────────────────────────────────────────────────────────
        AsanaTriggerRuleConfig,
        # ── Trigger ──────────────────────────────────────────────────────────
        AsanaTriggerConfig,
    ],
    Discriminator("operation"),
]


class AsanaNodeConfig(NodeConfig[AsanaConfig, AsanaCredential]):
    """Full configuration for the Asana node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _selected_trigger_actions(event_types: Optional[str]) -> Optional[List[str]]:
    """Resolve the trigger's ``event_types`` config into the list of Asana action
    names to subscribe to. Returns ``None`` to mean "all events" — when the value
    is empty, the ``*`` sentinel, or any selection that includes ``*``. Unknown
    tokens are dropped; an all-unknown selection also falls back to all events."""
    parts = _comma_list(event_types)
    if not parts or ASANA_ALL_EVENTS in parts:
        return None
    actions = [p for p in parts if p in ASANA_TRIGGER_ACTIONS]
    return actions or None


def _token_from_credential(credential: Dict[str, Any]) -> Optional[str]:
    """Both PAT and OAuth credentials store the bearer token in access_token."""
    if not credential:
        return None
    return credential.get("access_token")


async def _asana_request(
    token: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Asana request and return a structured result.

    Asana wraps write bodies in ``{"data": {...}}`` and returns ``{"data": ...}``;
    *json_data* is the inner object — this helper wraps it in the envelope and
    unwraps the response.
    """
    url = f"{ASANA_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    body = None
    if json_data is not None:
        body = {"data": {k: v for k, v in json_data.items() if v is not None}}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=body
            )
            api_ms = round((time.time() - start) * 1000, 2)

            if response.status_code >= 400:
                try:
                    err = response.json()
                    errors = err.get("errors") if isinstance(err, dict) else None
                    if errors and isinstance(errors, list):
                        message = "; ".join(e.get("message", str(e)) for e in errors)
                    else:
                        message = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[AsanaNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }

            if response.status_code == 204:
                data: Any = {"success": True}
            else:
                try:
                    payload = response.json()
                    data = payload.get("data", payload) if isinstance(payload, dict) else payload
                except Exception:
                    data = {"raw": response.text}

            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[AsanaNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class AsanaNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Asana project-management automation node."""

    # Asana delivers the signing secret via an X-Hook-Secret handshake after
    # webhook creation, not in the registration response. The base mixin's
    # idempotency guard skips the signing_secret requirement for async providers.
    webhook_signing_secret_is_async = True

    edit_examples = [
        "Create an Asana task when a form is submitted",
        "List all incomplete tasks in a project",
        "Add a comment to a task when a deal is won",
        "Mark a task complete and reassign it",
        "Trigger a workflow whenever a task in a project changes",
    ]

    scope_registry = ASANA_SCOPES
    connection_evidence = ConnectionEvidence(
        field="workspace_gid",
        noun="workspaces",
    )

    @classmethod
    def get_config_model(cls):
        return AsanaNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring Asana OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating Personal Access Tokens
        (which carry no refresh_token)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.asana_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="asana",
        )

    async def _ensure_fresh_token(self, credentials: "AsanaCredential") -> None:
        """Refresh an expired Asana OAuth token in place before an API call.
        Personal Access Tokens carry no refresh_token and are left untouched."""
        if not isinstance(credentials, AsanaOAuthCredential):
            return

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.asana_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="asana",
            caller_path="execute",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]

    # ------------------------------------------------------------------
    # Dynamic options (workspaces)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        token = _token_from_credential(credential_data or {})
        if not token:
            logger.warning("[AsanaNode] No access token for field options")
            return {"options": [], "next_page_token": None}

        ctx = context or {}

        if field_name == "workspace_gid":
            result = await _asana_request(
                token, "GET", "/workspaces", params={"limit": 100}, action_name="list_workspaces"
            )
            if result.get("status") != "success":
                return {"options": [], "next_page_token": None}
            items = result.get("data") or []
            options = [
                {"value": w.get("gid"), "label": w.get("name") or w.get("gid")}
                for w in items if isinstance(w, dict) and w.get("gid")
            ]

        elif field_name == "project_gid":
            params: Dict[str, Any] = {"limit": 100}
            if ctx.get("workspace_gid"):
                params["workspace"] = ctx["workspace_gid"]
            result = await _asana_request(
                token, "GET", "/projects", params=params, action_name="list_projects"
            )
            if result.get("status") != "success":
                return {"options": [], "next_page_token": None}
            items = result.get("data") or []
            options = [
                {"value": p.get("gid"), "label": p.get("name") or p.get("gid")}
                for p in items if isinstance(p, dict) and p.get("gid")
            ]

        elif field_name == "section_gid":
            project_gid = ctx.get("project_gid")
            if not project_gid:
                return {"options": [], "next_page_token": None}
            result = await _asana_request(
                token, "GET", f"/projects/{project_gid}/sections",
                params={"limit": 100}, action_name="list_sections"
            )
            if result.get("status") != "success":
                return {"options": [], "next_page_token": None}
            items = result.get("data") or []
            options = [
                {"value": s.get("gid"), "label": s.get("name") or s.get("gid")}
                for s in items if isinstance(s, dict) and s.get("gid")
            ]

        elif field_name == "tag_gid":
            workspace_gid = ctx.get("workspace_gid")
            if not workspace_gid:
                ws_result = await _asana_request(
                    token, "GET", "/workspaces", params={"limit": 1}, action_name="list_workspaces"
                )
                workspaces = ws_result.get("data") or [] if ws_result.get("status") == "success" else []
                workspace_gid = workspaces[0].get("gid") if workspaces else None
            if not workspace_gid:
                return {"options": [], "next_page_token": None}
            result = await _asana_request(
                token, "GET", "/tags", params={"workspace": workspace_gid, "limit": 100}, action_name="list_tags"
            )
            if result.get("status") != "success":
                return {"options": [], "next_page_token": None}
            items = result.get("data") or []
            options = [
                {"value": t.get("gid"), "label": t.get("name") or t.get("gid")}
                for t in items if isinstance(t, dict) and t.get("gid")
            ]

        elif field_name == "team_gid":
            workspace_gid = ctx.get("workspace_gid")
            if not workspace_gid:
                return {"options": [], "next_page_token": None}
            result = await _asana_request(
                token, "GET", f"/workspaces/{workspace_gid}/teams",
                params={"limit": 100}, action_name="list_teams"
            )
            if result.get("status") != "success":
                return {"options": [], "next_page_token": None}
            items = result.get("data") or []
            options = [
                {"value": t.get("gid"), "label": t.get("name") or t.get("gid")}
                for t in items if isinstance(t, dict) and t.get("gid")
            ]

        else:
            return {"options": [], "next_page_token": None}

        options = filter_options_by_search(options, normalize_search(search))
        return {"options": options, "next_page_token": None}

    # ------------------------------------------------------------------
    # Webhook trigger registration
    # ------------------------------------------------------------------
    @classmethod
    def _build_webhook_filters(
        cls, event_types: Optional[str]
    ) -> Optional[List[Dict[str, str]]]:
        """Always returns None — no filters sent to Asana on POST /webhooks.

        Asana's filter schema requires ``resource_type`` in every filter entry
        alongside ``action``; without it the API returns 400. Since the
        watched resource type varies (workspace / project / task) and
        ``filter_trigger_payload`` already performs in-band action filtering,
        the simplest correct approach is to register with no server-side filters
        and let Asana deliver all events for the subscribed resource."""
        return None

    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "resource_gid": (config or {}).get("resource_gid"),
            "event_types": (config or {}).get("event_types"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        """Register an Asana webhook.

        Asana immediately POSTs X-Hook-Secret to the target URL after creation;
        ``handle_webhook_handshake`` echoes it back and persists it as
        ``signing_secret``. Until that handshake completes, event payloads are
        rejected by ``verify_webhook_signature`` (returns False when no secret).
        """
        token = _token_from_credential(credential or {})
        if not token:
            raise ValueError("An Asana access token is required to use this trigger")
        resource = (config or {}).get("resource_gid")
        if not resource:
            return {"trigger_registered": False}
        body: Dict[str, Any] = {"resource": resource, "target": webhook_url}
        filters = cls._build_webhook_filters((config or {}).get("event_types"))
        if filters:
            body["filters"] = filters
        result = await _asana_request(
            token, "POST", "/webhooks", json_data=body, action_name="register_webhook"
        )
        if result.get("status") != "success":
            raise ValueError(
                f"Asana webhook registration failed: {result.get('error')}"
            )
        data = result.get("data") or {}
        external_id = data.get("gid") if isinstance(data, dict) else None
        return {
            "trigger_registered": True,
            "external_webhook_id": str(external_id) if external_id else None,
            # signing_secret is set via the X-Hook-Secret handshake in
            # handle_webhook_handshake, not returned here.
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        token = _token_from_credential(credential or {})
        if not external_id or not token:
            return
        await _asana_request(
            token, "DELETE", f"/webhooks/{external_id}", action_name="unregister_webhook"
        )

    @classmethod
    def handle_webhook_handshake(
        cls, body: bytes, headers: Dict[str, str],
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Handle Asana's X-Hook-Secret validation handshake.

        When POST /webhooks is called, Asana immediately POSTs to the target URL
        with ``X-Hook-Secret: <secret>`` and expects it echoed back in the response
        header. The ``__response_headers__`` and ``__signing_secret__`` keys are
        intercepted by webhook_routes._apply_trigger_node_hooks: the header is added
        to the HTTP response, and the secret is persisted into the trigger node's
        config so that future ``X-Hook-Signature`` payloads can be HMAC-verified.
        """
        secret = headers.get("x-hook-secret")
        if not secret:
            return None
        logger.info("[AsanaNode] X-Hook-Secret handshake received — echoing back and persisting")
        return {
            "__response_headers__": {"X-Hook-Secret": secret},
            "__signing_secret__": secret,
        }

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify Asana's ``X-Hook-Signature`` hex HMAC-SHA256 over the raw body."""
        secret = (config or {}).get("signing_secret")
        if not secret:
            # No secret yet — reject until the X-Hook-Secret handshake completes.
            return False
        signature = headers.get("x-hook-signature", "")
        return verify_hmac_sha256_hex(body, secret, signature)

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Drop deliveries whose events don't match the configured ``event_types``.

        Asana batches changes into ``{"events": [{"action": ...}, ...]}`` and
        delivers them to the single registered URL. ``event_types`` defaults to
        all events (``*``); when the user narrows it, accept the delivery only if
        at least one event's ``action`` is in the selected set."""
        selected = _selected_trigger_actions((config or {}).get("event_types"))
        if selected is None:
            return True  # all events
        events = (payload or {}).get("events")
        if not isinstance(events, list):
            return True  # handshake / non-event POST — let downstream hooks handle
        selected_set = set(selected)
        return any(
            isinstance(e, dict) and e.get("action") in selected_set for e in events
        )

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, AsanaNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, AsanaTriggerConfig):
            return {
                "status": "success",
                "action": "on_resource_change",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Asana access token.")
        await self._ensure_fresh_token(credentials)
        token = credentials.access_token

        handlers = {
            # Users
            "get_me": self._get_me,
            "list_users": self._list_users,
            "get_user": self._get_user,
            # Workspaces
            "list_workspaces": self._list_workspaces,
            "list_workspace_members": self._list_workspace_members,
            "add_workspace_user": self._add_workspace_user,
            "remove_workspace_user": self._remove_workspace_user,
            "typeahead_search": self._typeahead_search,
            # Teams
            "list_teams": self._list_teams,
            "get_team": self._get_team,
            "get_team_members": self._get_team_members,
            "add_team_member": self._add_team_member,
            "remove_team_member": self._remove_team_member,
            # Projects
            "list_projects": self._list_projects,
            "get_project": self._get_project,
            "create_project": self._create_project,
            "update_project": self._update_project,
            "delete_project": self._delete_project,
            "duplicate_project": self._duplicate_project,
            "get_project_members": self._get_project_members,
            "add_project_member": self._add_project_member,
            "remove_project_member": self._remove_project_member,
            "add_project_followers": self._add_project_followers,
            "remove_project_followers": self._remove_project_followers,
            "get_project_task_counts": self._get_project_task_counts,
            "get_project_statuses": self._get_project_statuses,
            "create_project_status": self._create_project_status,
            "delete_project_status": self._delete_project_status,
            "get_status_updates": self._get_status_updates,
            "create_status_update": self._create_status_update,
            "delete_status_update": self._delete_status_update,
            "get_project_brief": self._get_project_brief,
            "create_project_brief": self._create_project_brief,
            "update_project_brief": self._update_project_brief,
            "delete_project_brief": self._delete_project_brief,
            "list_project_templates": self._list_project_templates,
            "create_project_from_template": self._create_project_from_template,
            "save_project_as_template": self._save_project_as_template,
            "get_job": self._get_job,
            "get_project_custom_fields": self._get_project_custom_fields,
            # Sections
            "list_sections": self._list_sections,
            "get_section": self._get_section,
            "create_section": self._create_section,
            "update_section": self._update_section,
            "delete_section": self._delete_section,
            "get_section_tasks": self._get_section_tasks,
            # Tasks
            "search_tasks": self._search_tasks,
            "get_task": self._get_task,
            "create_task": self._create_task,
            "update_task": self._update_task,
            "delete_task": self._delete_task,
            "duplicate_task": self._duplicate_task,
            "list_project_tasks": self._list_project_tasks,
            "add_task_to_project": self._add_task_to_project,
            "remove_task_from_project": self._remove_task_from_project,
            "add_task_to_section": self._add_task_to_section,
            "set_task_parent": self._set_task_parent,
            "get_task_projects": self._get_task_projects,
            "list_subtasks": self._list_subtasks,
            "create_subtask": self._create_subtask,
            "get_task_dependencies": self._get_task_dependencies,
            "add_task_dependencies": self._add_task_dependencies,
            "remove_task_dependencies": self._remove_task_dependencies,
            "get_task_dependents": self._get_task_dependents,
            "add_task_dependents": self._add_task_dependents,
            "remove_task_dependents": self._remove_task_dependents,
            "add_followers": self._add_followers,
            "remove_followers": self._remove_followers,
            "get_tasks_for_tag": self._get_tasks_for_tag,
            "list_task_templates": self._list_task_templates,
            "create_task_from_template": self._create_task_from_template,
            # Comments / Stories
            "add_comment": self._add_comment,
            "list_comments": self._list_comments,
            "get_story": self._get_story,
            "update_story": self._update_story,
            "delete_story": self._delete_story,
            # Tags
            "list_tags": self._list_tags,
            "get_tag": self._get_tag,
            "create_tag": self._create_tag,
            "update_tag": self._update_tag,
            "delete_tag": self._delete_tag,
            "add_tag_to_task": self._add_tag_to_task,
            "remove_tag_from_task": self._remove_tag_from_task,
            "get_tags_for_task": self._get_tags_for_task,
            # Custom Fields
            "list_custom_fields": self._list_custom_fields,
            "get_custom_field": self._get_custom_field,
            "create_custom_field": self._create_custom_field,
            "update_custom_field": self._update_custom_field,
            "delete_custom_field": self._delete_custom_field,
            "set_task_custom_field": self._set_task_custom_field,
            "add_custom_field_to_project": self._add_custom_field_to_project,
            "remove_custom_field_from_project": self._remove_custom_field_from_project,
            # Attachments
            "get_task_attachments": self._get_task_attachments,
            "delete_attachment": self._delete_attachment,
            # Time Tracking
            "get_time_tracking_entries": self._get_time_tracking_entries,
            "create_time_tracking_entry": self._create_time_tracking_entry,
            "update_time_tracking_entry": self._update_time_tracking_entry,
            "delete_time_tracking_entry": self._delete_time_tracking_entry,
            # User Task List
            "get_user_task_list": self._get_user_task_list,
            "get_user_task_list_tasks": self._get_user_task_list_tasks,
            # Portfolios
            "list_portfolios": self._list_portfolios,
            "get_portfolio": self._get_portfolio,
            "create_portfolio": self._create_portfolio,
            "update_portfolio": self._update_portfolio,
            "delete_portfolio": self._delete_portfolio,
            "get_portfolio_items": self._get_portfolio_items,
            "add_portfolio_item": self._add_portfolio_item,
            "remove_portfolio_item": self._remove_portfolio_item,
            "add_portfolio_members": self._add_portfolio_members,
            "remove_portfolio_members": self._remove_portfolio_members,
            # Goals
            "list_goals": self._list_goals,
            "get_goal": self._get_goal,
            "create_goal": self._create_goal,
            "update_goal": self._update_goal,
            "delete_goal": self._delete_goal,
            "get_goal_parent_goals": self._get_goal_parent_goals,
            "set_goal_metric": self._set_goal_metric,
            "update_goal_metric": self._update_goal_metric,
            "add_goal_followers": self._add_goal_followers,
            "remove_goal_followers": self._remove_goal_followers,
            # Rules
            "trigger_rule": self._trigger_rule,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, token)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers — Users / Workspaces
    # ------------------------------------------------------------------
    async def _get_me(self, c: AsanaGetMeConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(token, "GET", "/users/me", action_name="get_me")

    async def _list_workspaces(self, c: AsanaListWorkspacesConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", "/workspaces", params={"limit": 100}, action_name="list_workspaces"
        )

    async def _list_users(self, c: AsanaListUsersConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/workspaces/{c.workspace_gid}/users", action_name="list_users"
        )

    async def _list_teams(self, c: AsanaListTeamsConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "GET",
            f"/workspaces/{c.workspace_gid}/teams",
            params={"limit": 100},
            action_name="list_teams",
        )

    async def _list_custom_fields(self, c: AsanaListCustomFieldsConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "GET",
            f"/workspaces/{c.workspace_gid}/custom_fields",
            params={"limit": 100},
            action_name="list_custom_fields",
        )

    # ------------------------------------------------------------------
    # Handlers — Projects
    # ------------------------------------------------------------------
    async def _list_projects(self, c: AsanaListProjectsConfig, token: str) -> Dict[str, Any]:
        params = {
            "workspace": c.workspace_gid,
            "archived": c.archived or None,
            "limit": c.limit,
        }
        return await _asana_request(
            token, "GET", "/projects", params=params, action_name="list_projects"
        )

    async def _get_project(self, c: AsanaGetProjectConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/projects/{c.project_gid}", action_name="get_project"
        )

    async def _create_project(self, c: AsanaCreateProjectConfig, token: str) -> Dict[str, Any]:
        body = {
            "workspace": c.workspace_gid,
            "name": c.name,
            "notes": c.notes,
            "team": c.team_gid,
        }
        return await _asana_request(
            token, "POST", "/projects", json_data=body, action_name="create_project"
        )

    async def _update_project(self, c: AsanaUpdateProjectConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"name": c.name, "notes": c.notes}
        if c.archived in ("true", "false"):
            body["archived"] = c.archived == "true"
        return await _asana_request(
            token, "PUT", f"/projects/{c.project_gid}", json_data=body, action_name="update_project"
        )

    async def _delete_project(self, c: AsanaDeleteProjectConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "DELETE", f"/projects/{c.project_gid}", action_name="delete_project"
        )

    async def _list_project_tasks(self, c: AsanaListProjectTasksConfig, token: str) -> Dict[str, Any]:
        params = {"completed_since": c.completed_since, "limit": c.limit}
        return await _asana_request(
            token,
            "GET",
            f"/projects/{c.project_gid}/tasks",
            params=params,
            action_name="list_project_tasks",
        )

    async def _list_sections(self, c: AsanaListProjectSectionsConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/projects/{c.project_gid}/sections", action_name="list_sections"
        )

    # ------------------------------------------------------------------
    # Handlers — Tasks
    # ------------------------------------------------------------------
    async def _search_tasks(self, c: AsanaSearchTasksConfig, token: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {"text": c.text, "limit": c.limit}
        if c.completed in ("true", "false"):
            params["completed"] = c.completed
        return await _asana_request(
            token,
            "GET",
            f"/workspaces/{c.workspace_gid}/tasks/search",
            params=params,
            action_name="search_tasks",
        )

    async def _get_task(self, c: AsanaGetTaskConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/tasks/{c.task_gid}", action_name="get_task"
        )

    async def _create_task(self, c: AsanaCreateTaskConfig, token: str) -> Dict[str, Any]:
        body = {
            "workspace": c.workspace_gid,
            "name": c.name,
            "notes": c.notes,
            "assignee": c.assignee,
            "due_on": c.due_on,
            "projects": _comma_list(c.projects),
        }
        return await _asana_request(
            token, "POST", "/tasks", json_data=body, action_name="create_task"
        )

    async def _update_task(self, c: AsanaUpdateTaskConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "name": c.name,
            "notes": c.notes,
            "assignee": c.assignee,
            "due_on": c.due_on,
        }
        if c.completed in ("true", "false"):
            body["completed"] = c.completed == "true"
        return await _asana_request(
            token, "PUT", f"/tasks/{c.task_gid}", json_data=body, action_name="update_task"
        )

    async def _delete_task(self, c: AsanaDeleteTaskConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "DELETE", f"/tasks/{c.task_gid}", action_name="delete_task"
        )

    async def _add_task_to_project(self, c: AsanaAddTaskToProjectConfig, token: str) -> Dict[str, Any]:
        body = {"project": c.project_gid, "section": c.section_gid}
        return await _asana_request(
            token,
            "POST",
            f"/tasks/{c.task_gid}/addProject",
            json_data=body,
            action_name="add_task_to_project",
        )

    async def _remove_task_from_project(
        self, c: AsanaRemoveTaskFromProjectConfig, token: str
    ) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/tasks/{c.task_gid}/removeProject",
            json_data={"project": c.project_gid},
            action_name="remove_task_from_project",
        )

    async def _list_subtasks(self, c: AsanaListSubtasksConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/tasks/{c.task_gid}/subtasks", action_name="list_subtasks"
        )

    async def _create_subtask(self, c: AsanaCreateSubtaskConfig, token: str) -> Dict[str, Any]:
        body = {"name": c.name, "notes": c.notes, "assignee": c.assignee}
        return await _asana_request(
            token,
            "POST",
            f"/tasks/{c.task_gid}/subtasks",
            json_data=body,
            action_name="create_subtask",
        )

    async def _add_followers(self, c: AsanaAddFollowersConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/tasks/{c.task_gid}/addFollowers",
            json_data={"followers": _comma_list(c.followers)},
            action_name="add_followers",
        )

    async def _remove_followers(self, c: AsanaRemoveFollowersConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/tasks/{c.task_gid}/removeFollowers",
            json_data={"followers": _comma_list(c.followers)},
            action_name="remove_followers",
        )

    async def _add_task_to_section(self, c: AsanaAddTaskToSectionConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/sections/{c.section_gid}/addTask",
            json_data={"task": c.task_gid},
            action_name="add_task_to_section",
        )

    # ------------------------------------------------------------------
    # Handlers — Comments (stories)
    # ------------------------------------------------------------------
    async def _add_comment(self, c: AsanaAddCommentConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/tasks/{c.task_gid}/stories",
            json_data={"text": c.text},
            action_name="add_comment",
        )

    async def _list_comments(self, c: AsanaListCommentsConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/tasks/{c.task_gid}/stories", action_name="list_comments"
        )

    # ------------------------------------------------------------------
    # Handlers — Tags
    # ------------------------------------------------------------------
    async def _list_tags(self, c: AsanaListTagsConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "GET",
            f"/workspaces/{c.workspace_gid}/tags",
            params={"limit": 100},
            action_name="list_tags",
        )

    async def _add_tag_to_task(self, c: AsanaAddTagToTaskConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/tasks/{c.task_gid}/addTag",
            json_data={"tag": c.tag_gid},
            action_name="add_tag_to_task",
        )

    async def _remove_tag_from_task(self, c: AsanaRemoveTagFromTaskConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/tasks/{c.task_gid}/removeTag",
            json_data={"tag": c.tag_gid},
            action_name="remove_tag_from_task",
        )

    async def _get_tags_for_task(self, c: AsanaGetTagsForTaskConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/tasks/{c.task_gid}/tags", action_name="get_tags_for_task"
        )

    async def _create_tag(self, c: AsanaCreateTagConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"name": c.name}
        if c.color:
            body["color"] = c.color
        return await _asana_request(
            token,
            "POST",
            f"/workspaces/{c.workspace_gid}/tags",
            json_data=body,
            action_name="create_tag",
        )

    # ------------------------------------------------------------------
    # Handlers — Sections CRUD
    # ------------------------------------------------------------------
    async def _create_section(self, c: AsanaCreateSectionConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/projects/{c.project_gid}/sections",
            json_data={"name": c.name},
            action_name="create_section",
        )

    async def _update_section(self, c: AsanaUpdateSectionConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "PUT",
            f"/sections/{c.section_gid}",
            json_data={"name": c.name},
            action_name="update_section",
        )

    async def _delete_section(self, c: AsanaDeleteSectionConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "DELETE", f"/sections/{c.section_gid}", action_name="delete_section"
        )

    # ------------------------------------------------------------------
    # Handlers — Task dependencies
    # ------------------------------------------------------------------
    async def _get_task_dependencies(self, c: AsanaGetTaskDependenciesConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/tasks/{c.task_gid}/dependencies", action_name="get_task_dependencies"
        )

    async def _add_task_dependencies(self, c: AsanaAddDependenciesToTaskConfig, token: str) -> Dict[str, Any]:
        deps = _comma_list(c.dependencies) or []
        return await _asana_request(
            token,
            "POST",
            f"/tasks/{c.task_gid}/addDependencies",
            json_data={"dependencies": deps},
            action_name="add_task_dependencies",
        )

    async def _remove_task_dependencies(self, c: AsanaRemoveDependenciesFromTaskConfig, token: str) -> Dict[str, Any]:
        deps = _comma_list(c.dependencies) or []
        return await _asana_request(
            token,
            "POST",
            f"/tasks/{c.task_gid}/removeDependencies",
            json_data={"dependencies": deps},
            action_name="remove_task_dependencies",
        )

    # ------------------------------------------------------------------
    # Handlers — Duplicate task / project
    # ------------------------------------------------------------------
    async def _duplicate_task(self, c: AsanaDuplicateTaskConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"name": c.name}
        if c.include:
            body["include"] = _comma_list(c.include)
        return await _asana_request(
            token,
            "POST",
            f"/tasks/{c.task_gid}/duplicate",
            json_data=body,
            action_name="duplicate_task",
        )

    async def _duplicate_project(self, c: AsanaDuplicateProjectConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"name": c.name}
        if c.team:
            body["team"] = c.team
        if c.include:
            body["include"] = _comma_list(c.include)
        return await _asana_request(
            token,
            "POST",
            f"/projects/{c.project_gid}/duplicate",
            json_data=body,
            action_name="duplicate_project",
        )

    # ------------------------------------------------------------------
    # Handlers — Story / comment updates
    # ------------------------------------------------------------------
    async def _update_story(self, c: AsanaUpdateStoryConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "PUT",
            f"/stories/{c.story_gid}",
            json_data={"text": c.text},
            action_name="update_story",
        )

    async def _delete_story(self, c: AsanaDeleteStoryConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "DELETE", f"/stories/{c.story_gid}", action_name="delete_story"
        )

    # ------------------------------------------------------------------
    # Handlers — Users (individual)
    # ------------------------------------------------------------------
    async def _get_user(self, c: AsanaGetUserConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(token, "GET", f"/users/{c.user_gid}", action_name="get_user")

    # ------------------------------------------------------------------
    # Handlers — Workspaces (management)
    # ------------------------------------------------------------------
    async def _list_workspace_members(self, c: AsanaListWorkspaceMembersConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "GET",
            f"/workspaces/{c.workspace_gid}/workspace_memberships",
            params={"limit": 100},
            action_name="list_workspace_members",
        )

    async def _add_workspace_user(self, c: AsanaAddWorkspaceUserConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/workspaces/{c.workspace_gid}/addUser",
            json_data={"user": c.user},
            action_name="add_workspace_user",
        )

    async def _remove_workspace_user(self, c: AsanaRemoveWorkspaceUserConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/workspaces/{c.workspace_gid}/removeUser",
            json_data={"user": c.user},
            action_name="remove_workspace_user",
        )

    async def _typeahead_search(self, c: AsanaTypeaheadSearchConfig, token: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "query": c.query,
            "resource_type": c.resource_type,
        }
        if c.count:
            params["count"] = c.count
        return await _asana_request(
            token,
            "GET",
            f"/workspaces/{c.workspace_gid}/typeahead",
            params=params,
            action_name="typeahead_search",
        )

    # ------------------------------------------------------------------
    # Handlers — Teams
    # ------------------------------------------------------------------
    async def _get_team(self, c: AsanaGetTeamConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(token, "GET", f"/teams/{c.team_gid}", action_name="get_team")

    async def _get_team_members(self, c: AsanaGetTeamMembersConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/teams/{c.team_gid}/users", params={"limit": 100}, action_name="get_team_members"
        )

    async def _add_team_member(self, c: AsanaAddTeamMemberConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/teams/{c.team_gid}/addUser",
            json_data={"user": c.user},
            action_name="add_team_member",
        )

    async def _remove_team_member(self, c: AsanaRemoveTeamMemberConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/teams/{c.team_gid}/removeUser",
            json_data={"user": c.user},
            action_name="remove_team_member",
        )

    # ------------------------------------------------------------------
    # Handlers — Project management
    # ------------------------------------------------------------------
    async def _get_project_members(self, c: AsanaGetProjectMembersConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "GET",
            f"/projects/{c.project_gid}/project_memberships",
            params={"limit": 100},
            action_name="get_project_members",
        )

    async def _add_project_member(self, c: AsanaAddProjectMemberConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/projects/{c.project_gid}/addMembers",
            json_data={"members": _comma_list(c.members)},
            action_name="add_project_member",
        )

    async def _remove_project_member(self, c: AsanaRemoveProjectMemberConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/projects/{c.project_gid}/removeMembers",
            json_data={"members": _comma_list(c.members)},
            action_name="remove_project_member",
        )

    async def _add_project_followers(self, c: AsanaAddProjectFollowersConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/projects/{c.project_gid}/addFollowers",
            json_data={"followers": _comma_list(c.followers)},
            action_name="add_project_followers",
        )

    async def _remove_project_followers(self, c: AsanaRemoveProjectFollowersConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/projects/{c.project_gid}/removeFollowers",
            json_data={"followers": _comma_list(c.followers)},
            action_name="remove_project_followers",
        )

    async def _get_project_task_counts(self, c: AsanaGetProjectTaskCountsConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "GET",
            f"/projects/{c.project_gid}/task_counts",
            params={"opt_fields": "num_tasks,num_completed_tasks,num_incomplete_tasks,num_milestones,num_completed_milestones,num_incomplete_milestones"},
            action_name="get_project_task_counts",
        )

    async def _get_project_statuses(self, c: AsanaGetProjectStatusesConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/projects/{c.project_gid}/project_statuses", action_name="get_project_statuses"
        )

    async def _create_project_status(self, c: AsanaCreateProjectStatusConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/projects/{c.project_gid}/project_statuses",
            json_data={"title": c.title, "text": c.text, "color": c.color},
            action_name="create_project_status",
        )

    async def _delete_project_status(self, c: AsanaDeleteProjectStatusConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "DELETE",
            f"/project_statuses/{c.project_status_gid}",
            action_name="delete_project_status",
        )

    async def _get_status_updates(self, c: AsanaGetStatusUpdatesConfig, token: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {"parent": c.parent_gid}
        if c.limit:
            params["limit"] = c.limit
        return await _asana_request(
            token, "GET", "/status_updates", params=params, action_name="get_status_updates"
        )

    async def _create_status_update(self, c: AsanaCreateStatusUpdateConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            "/status_updates",
            json_data={
                "parent": c.parent_gid,
                "title": c.title,
                "text": c.text,
                "status_type": c.status_type,
            },
            action_name="create_status_update",
        )

    async def _delete_status_update(self, c: AsanaDeleteStatusUpdateConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "DELETE", f"/status_updates/{c.status_update_gid}", action_name="delete_status_update"
        )

    async def _get_project_brief(self, c: AsanaGetProjectBriefConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/project_briefs/{c.project_brief_gid}", action_name="get_project_brief"
        )

    async def _create_project_brief(self, c: AsanaCreateProjectBriefConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"project_gid": c.project_gid, "title": c.title}
        if c.html_text:
            body["html_text"] = c.html_text
        return await _asana_request(
            token,
            "POST",
            "/project_briefs",
            json_data=body,
            action_name="create_project_brief",
        )

    async def _update_project_brief(self, c: AsanaUpdateProjectBriefConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if c.title:
            body["title"] = c.title
        if c.html_text:
            body["html_text"] = c.html_text
        return await _asana_request(
            token,
            "PUT",
            f"/project_briefs/{c.project_brief_gid}",
            json_data=body,
            action_name="update_project_brief",
        )

    async def _delete_project_brief(self, c: AsanaDeleteProjectBriefConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "DELETE", f"/project_briefs/{c.project_brief_gid}", action_name="delete_project_brief"
        )

    async def _list_project_templates(self, c: AsanaListProjectTemplatesConfig, token: str) -> Dict[str, Any]:
        # Organization workspaces must use the team-scoped endpoint; personal workspaces
        # can filter by workspace. Prefer team endpoint when team_gid is provided.
        if c.team_gid:
            return await _asana_request(
                token, "GET", f"/teams/{c.team_gid}/project_templates", action_name="list_project_templates"
            )
        params: Dict[str, Any] = {}
        if c.workspace_gid:
            params["workspace"] = c.workspace_gid
        return await _asana_request(
            token, "GET", "/project_templates", params=params, action_name="list_project_templates"
        )

    async def _create_project_from_template(
        self, c: AsanaCreateProjectFromTemplateConfig, token: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"name": c.name}
        if c.team:
            body["team"] = c.team
        if c.public in ("true", "false"):
            body["public"] = c.public == "true"
        return await _asana_request(
            token,
            "POST",
            f"/project_templates/{c.project_template_gid}/instantiateProject",
            json_data=body,
            action_name="create_project_from_template",
        )

    async def _save_project_as_template(self, c: AsanaSaveProjectAsTemplateConfig, token: str) -> Dict[str, Any]:
        # Asana requires `public` field and either `workspace` or `team`.
        body: Dict[str, Any] = {"name": c.name, "public": (c.public == "true") if c.public in ("true", "false") else True}
        if c.team:
            body["team"] = c.team
        elif c.workspace_gid:
            body["workspace"] = c.workspace_gid
        return await _asana_request(
            token,
            "POST",
            f"/projects/{c.project_gid}/saveAsTemplate",
            json_data=body,
            action_name="save_project_as_template",
        )

    async def _get_job(self, c: AsanaGetJobConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(token, "GET", f"/jobs/{c.job_gid}", action_name="get_job")

    async def _get_project_custom_fields(self, c: AsanaGetProjectCustomFieldsConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "GET",
            f"/projects/{c.project_gid}/custom_field_settings",
            params={"limit": 100},
            action_name="get_project_custom_fields",
        )

    # ------------------------------------------------------------------
    # Handlers — Sections (additional)
    # ------------------------------------------------------------------
    async def _get_section(self, c: AsanaGetSectionConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/sections/{c.section_gid}", action_name="get_section"
        )

    async def _get_section_tasks(self, c: AsanaGetSectionTasksConfig, token: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if c.limit:
            params["limit"] = c.limit
        return await _asana_request(
            token, "GET", f"/sections/{c.section_gid}/tasks", params=params, action_name="get_section_tasks"
        )

    # ------------------------------------------------------------------
    # Handlers — Tasks (additional)
    # ------------------------------------------------------------------
    async def _set_task_parent(self, c: AsanaSetTaskParentConfig, token: str) -> Dict[str, Any]:
        # Asana accepts null to unset the parent — send the key explicitly even when null.
        parent_val = c.parent if c.parent else None
        url = f"{ASANA_API_BASE}/tasks/{c.task_gid}/setParent"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"}
        import time as _time
        start = _time.time()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json={"data": {"parent": parent_val}})
        api_ms = round((_time.time() - start) * 1000, 2)
        if resp.status_code >= 400:
            try:
                err = resp.json()
                errors = err.get("errors") if isinstance(err, dict) else None
                message = "; ".join(e.get("message", str(e)) for e in errors) if errors else str(err)
            except Exception:
                message = resp.text
            logger.error(f"[AsanaNode] API error (set_task_parent): {message}")
            return {"status": "error", "action": "set_task_parent", "error": message, "status_code": resp.status_code}
        payload = resp.json()
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        return {"status": "success", "action": "set_task_parent", "data": data, "status_code": resp.status_code, "timing_ms": {"api_request": api_ms}}

    async def _get_task_projects(self, c: AsanaGetTaskProjectsConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/tasks/{c.task_gid}/projects", action_name="get_task_projects"
        )

    async def _get_task_dependents(self, c: AsanaGetTaskDependentsConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/tasks/{c.task_gid}/dependents", action_name="get_task_dependents"
        )

    async def _add_task_dependents(self, c: AsanaAddTaskDependentsConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/tasks/{c.task_gid}/addDependents",
            json_data={"dependents": _comma_list(c.dependents) or []},
            action_name="add_task_dependents",
        )

    async def _remove_task_dependents(self, c: AsanaRemoveTaskDependentsConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/tasks/{c.task_gid}/removeDependents",
            json_data={"dependents": _comma_list(c.dependents) or []},
            action_name="remove_task_dependents",
        )

    async def _get_tasks_for_tag(self, c: AsanaGetTasksForTagConfig, token: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if c.limit:
            params["limit"] = c.limit
        return await _asana_request(
            token, "GET", f"/tags/{c.tag_gid}/tasks", params=params, action_name="get_tasks_for_tag"
        )

    async def _list_task_templates(self, c: AsanaListTaskTemplatesConfig, token: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if c.project_gid:
            params["project"] = c.project_gid
        return await _asana_request(
            token, "GET", "/task_templates", params=params, action_name="list_task_templates"
        )

    async def _create_task_from_template(self, c: AsanaCreateTaskFromTemplateConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/task_templates/{c.task_template_gid}/instantiateTask",
            json_data={},
            action_name="create_task_from_template",
        )

    # ------------------------------------------------------------------
    # Handlers — Stories (individual)
    # ------------------------------------------------------------------
    async def _get_story(self, c: AsanaGetStoryConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(token, "GET", f"/stories/{c.story_gid}", action_name="get_story")

    # ------------------------------------------------------------------
    # Handlers — Tags (full CRUD)
    # ------------------------------------------------------------------
    async def _get_tag(self, c: AsanaGetTagConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(token, "GET", f"/tags/{c.tag_gid}", action_name="get_tag")

    async def _update_tag(self, c: AsanaUpdateTagConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if c.name:
            body["name"] = c.name
        if c.color:
            body["color"] = c.color
        return await _asana_request(
            token, "PUT", f"/tags/{c.tag_gid}", json_data=body, action_name="update_tag"
        )

    async def _delete_tag(self, c: AsanaDeleteTagConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(token, "DELETE", f"/tags/{c.tag_gid}", action_name="delete_tag")

    # ------------------------------------------------------------------
    # Handlers — Custom Fields
    # ------------------------------------------------------------------
    async def _get_custom_field(self, c: AsanaGetCustomFieldConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/custom_fields/{c.custom_field_gid}", action_name="get_custom_field"
        )

    async def _create_custom_field(self, c: AsanaCreateCustomFieldConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "workspace": c.workspace_gid,
            "name": c.name,
            "resource_subtype": c.field_type,
        }
        if c.description:
            body["description"] = c.description
        if c.precision:
            try:
                body["precision"] = int(c.precision)
            except ValueError:
                pass
        return await _asana_request(
            token, "POST", "/custom_fields", json_data=body, action_name="create_custom_field"
        )

    async def _update_custom_field(self, c: AsanaUpdateCustomFieldConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if c.name:
            body["name"] = c.name
        if c.description:
            body["description"] = c.description
        return await _asana_request(
            token,
            "PUT",
            f"/custom_fields/{c.custom_field_gid}",
            json_data=body,
            action_name="update_custom_field",
        )

    async def _delete_custom_field(self, c: AsanaDeleteCustomFieldConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "DELETE", f"/custom_fields/{c.custom_field_gid}", action_name="delete_custom_field"
        )

    async def _set_task_custom_field(self, c: AsanaSetTaskCustomFieldConfig, token: str) -> Dict[str, Any]:
        # Asana accepts custom_fields as {gid: value} in a standard task PUT
        return await _asana_request(
            token,
            "PUT",
            f"/tasks/{c.task_gid}",
            json_data={"custom_fields": {c.custom_field_gid: c.value}},
            action_name="set_task_custom_field",
        )

    async def _add_custom_field_to_project(
        self, c: AsanaAddCustomFieldToProjectConfig, token: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"custom_field": c.custom_field_gid}
        if c.is_important in ("true", "false"):
            body["is_important"] = c.is_important == "true"
        return await _asana_request(
            token,
            "POST",
            f"/projects/{c.project_gid}/addCustomFieldSetting",
            json_data=body,
            action_name="add_custom_field_to_project",
        )

    async def _remove_custom_field_from_project(
        self, c: AsanaRemoveCustomFieldFromProjectConfig, token: str
    ) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/projects/{c.project_gid}/removeCustomFieldSetting",
            json_data={"custom_field": c.custom_field_gid},
            action_name="remove_custom_field_from_project",
        )

    # ------------------------------------------------------------------
    # Handlers — Attachments
    # ------------------------------------------------------------------
    async def _get_task_attachments(self, c: AsanaGetTaskAttachmentsConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/tasks/{c.task_gid}/attachments", action_name="get_task_attachments"
        )

    async def _delete_attachment(self, c: AsanaDeleteAttachmentConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "DELETE", f"/attachments/{c.attachment_gid}", action_name="delete_attachment"
        )

    # ------------------------------------------------------------------
    # Handlers — Time Tracking
    # ------------------------------------------------------------------
    async def _get_time_tracking_entries(
        self, c: AsanaGetTimeTrackingEntriesConfig, token: str
    ) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "GET",
            f"/tasks/{c.task_gid}/time_tracking_entries",
            action_name="get_time_tracking_entries",
        )

    async def _create_time_tracking_entry(
        self, c: AsanaCreateTimeTrackingEntryConfig, token: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"duration_minutes": int(c.duration_minutes)}
        if c.entered_on:
            body["entered_on"] = c.entered_on
        return await _asana_request(
            token,
            "POST",
            f"/tasks/{c.task_gid}/time_tracking_entries",
            json_data=body,
            action_name="create_time_tracking_entry",
        )

    async def _update_time_tracking_entry(
        self, c: AsanaUpdateTimeTrackingEntryConfig, token: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if c.duration_minutes:
            body["duration_minutes"] = int(c.duration_minutes)
        if c.entered_on:
            body["entered_on"] = c.entered_on
        return await _asana_request(
            token,
            "PUT",
            f"/time_tracking_entries/{c.time_tracking_entry_gid}",
            json_data=body,
            action_name="update_time_tracking_entry",
        )

    async def _delete_time_tracking_entry(
        self, c: AsanaDeleteTimeTrackingEntryConfig, token: str
    ) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "DELETE",
            f"/time_tracking_entries/{c.time_tracking_entry_gid}",
            action_name="delete_time_tracking_entry",
        )

    # ------------------------------------------------------------------
    # Handlers — User Task List (My Tasks)
    # ------------------------------------------------------------------
    async def _get_user_task_list(self, c: AsanaGetUserTaskListConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "GET",
            f"/users/{c.user_gid}/user_task_list",
            params={"workspace": c.workspace_gid},
            action_name="get_user_task_list",
        )

    async def _get_user_task_list_tasks(
        self, c: AsanaGetUserTaskListTasksConfig, token: str
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if c.completed_since:
            params["completed_since"] = c.completed_since
        if c.limit:
            params["limit"] = c.limit
        return await _asana_request(
            token,
            "GET",
            f"/user_task_lists/{c.user_task_list_gid}/tasks",
            params=params,
            action_name="get_user_task_list_tasks",
        )

    # ------------------------------------------------------------------
    # Handlers — Portfolios
    # ------------------------------------------------------------------
    async def _list_portfolios(self, c: AsanaListPortfoliosConfig, token: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {"workspace": c.workspace_gid}
        if c.owner:
            params["owner"] = c.owner
        return await _asana_request(
            token, "GET", "/portfolios", params=params, action_name="list_portfolios"
        )

    async def _get_portfolio(self, c: AsanaGetPortfolioConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/portfolios/{c.portfolio_gid}", action_name="get_portfolio"
        )

    async def _create_portfolio(self, c: AsanaCreatePortfolioConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"workspace": c.workspace_gid, "name": c.name}
        if c.public in ("true", "false"):
            body["public"] = c.public == "true"
        return await _asana_request(
            token, "POST", "/portfolios", json_data=body, action_name="create_portfolio"
        )

    async def _update_portfolio(self, c: AsanaUpdatePortfolioConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if c.name:
            body["name"] = c.name
        if c.public in ("true", "false"):
            body["public"] = c.public == "true"
        return await _asana_request(
            token,
            "PUT",
            f"/portfolios/{c.portfolio_gid}",
            json_data=body,
            action_name="update_portfolio",
        )

    async def _delete_portfolio(self, c: AsanaDeletePortfolioConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "DELETE", f"/portfolios/{c.portfolio_gid}", action_name="delete_portfolio"
        )

    async def _get_portfolio_items(self, c: AsanaGetPortfolioItemsConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/portfolios/{c.portfolio_gid}/items", action_name="get_portfolio_items"
        )

    async def _add_portfolio_item(self, c: AsanaAddPortfolioItemConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/portfolios/{c.portfolio_gid}/addItem",
            json_data={"item": c.item},
            action_name="add_portfolio_item",
        )

    async def _remove_portfolio_item(self, c: AsanaRemovePortfolioItemConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/portfolios/{c.portfolio_gid}/removeItem",
            json_data={"item": c.item},
            action_name="remove_portfolio_item",
        )

    async def _add_portfolio_members(self, c: AsanaAddPortfolioMembersConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/portfolios/{c.portfolio_gid}/addMembers",
            json_data={"members": _comma_list(c.members)},
            action_name="add_portfolio_members",
        )

    async def _remove_portfolio_members(
        self, c: AsanaRemovePortfolioMembersConfig, token: str
    ) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/portfolios/{c.portfolio_gid}/removeMembers",
            json_data={"members": _comma_list(c.members)},
            action_name="remove_portfolio_members",
        )

    # ------------------------------------------------------------------
    # Handlers — Goals
    # ------------------------------------------------------------------
    async def _list_goals(self, c: AsanaListGoalsConfig, token: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if c.workspace_gid:
            params["workspace"] = c.workspace_gid
        if c.team_gid:
            params["team"] = c.team_gid
        if c.is_workspace_level == "true":
            params["is_workspace_level"] = "true"
        elif c.is_workspace_level == "false":
            params["is_workspace_level"] = "false"
        return await _asana_request(token, "GET", "/goals", params=params, action_name="list_goals")

    async def _get_goal(self, c: AsanaGetGoalConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(token, "GET", f"/goals/{c.goal_gid}", action_name="get_goal")

    async def _create_goal(self, c: AsanaCreateGoalConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"name": c.name, "workspace": c.workspace_gid}
        if c.notes:
            body["notes"] = c.notes
        if c.team_gid:
            body["team"] = c.team_gid
        if c.due_on:
            body["due_on"] = c.due_on
        if c.start_on:
            body["start_on"] = c.start_on
        return await _asana_request(token, "POST", "/goals", json_data=body, action_name="create_goal")

    async def _update_goal(self, c: AsanaUpdateGoalConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if c.name:
            body["name"] = c.name
        if c.notes:
            body["notes"] = c.notes
        if c.due_on:
            body["due_on"] = c.due_on
        if c.start_on:
            body["start_on"] = c.start_on
        if c.status:
            body["status"] = c.status
        return await _asana_request(
            token, "PUT", f"/goals/{c.goal_gid}", json_data=body, action_name="update_goal"
        )

    async def _delete_goal(self, c: AsanaDeleteGoalConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(token, "DELETE", f"/goals/{c.goal_gid}", action_name="delete_goal")

    async def _get_goal_parent_goals(self, c: AsanaGetGoalParentGoalsConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token, "GET", f"/goals/{c.goal_gid}/parentGoals", action_name="get_goal_parent_goals"
        )

    async def _set_goal_metric(self, c: AsanaSetGoalMetricConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "metric_type": c.metric_type,
            "target_value": float(c.target_value),
        }
        if c.initial_value:
            body["initial_value"] = float(c.initial_value)
        if c.unit:
            body["unit"] = c.unit
        return await _asana_request(
            token,
            "POST",
            f"/goals/{c.goal_gid}/setMetric",
            json_data=body,
            action_name="set_goal_metric",
        )

    async def _update_goal_metric(self, c: AsanaUpdateGoalMetricConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/goals/{c.goal_gid}/setMetricCurrentValue",
            json_data={"current_number_value": float(c.current_value)},
            action_name="update_goal_metric",
        )

    async def _add_goal_followers(self, c: AsanaAddGoalFollowersConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/goals/{c.goal_gid}/addFollowers",
            json_data={"followers": _comma_list(c.followers)},
            action_name="add_goal_followers",
        )

    async def _remove_goal_followers(self, c: AsanaRemoveGoalFollowersConfig, token: str) -> Dict[str, Any]:
        return await _asana_request(
            token,
            "POST",
            f"/goals/{c.goal_gid}/removeFollowers",
            json_data={"followers": _comma_list(c.followers)},
            action_name="remove_goal_followers",
        )

    # ------------------------------------------------------------------
    # Handlers — Rules
    # ------------------------------------------------------------------
    async def _trigger_rule(self, c: AsanaTriggerRuleConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if c.action_data:
            try:
                import json as _json
                body["action_data"] = _json.loads(c.action_data)
            except Exception:
                body["action_data"] = c.action_data
        return await _asana_request(
            token,
            "POST",
            f"/rule_triggers/{c.rule_trigger_gid}/run",
            json_data=body,
            action_name="trigger_rule",
        )
