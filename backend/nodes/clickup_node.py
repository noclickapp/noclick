"""
ClickUp project-management automation node — comprehensive API coverage (161 ops).

Covers the ENTIRE ClickUp public REST API (v2 + v3) across: Authorization, Tasks
(+ relationships, multi-list, merge, templates, time-in-status), Tags, Checklists,
Comments (task/list/chat-view/threaded), Custom Fields, Lists, Folders, Spaces,
Goals & Key Results, Views, Members, Guests, Users, User Groups, Roles,
Shared Hierarchy, Time Tracking (new + legacy), Webhooks, Workspaces, Docs (v3),
Chat (v3), Audit Logs (v3) — plus a generic ``custom_request`` escape hatch, a
multipart ``create_task_attachment`` op, and a webhook trigger.

Architecture: 23 high-value ops have hand-written rich configs + handlers; the
long tail is a spec-table (``_EXTENDED_SPECS``) that generates one typed config
per endpoint and routes through a single generic dispatcher (``_dispatch_generic``).
Each generated op exposes its path placeholders as fields plus an ``extra_params``
escape hatch for every other API parameter.

Authentication: Personal API token (raw `Authorization` header, no prefix) OR
OAuth 2.0 (Bearer token). ClickUp branches the header format on credential type:
personal `pk_` tokens use NO prefix; OAuth access tokens use the `Bearer ` prefix.

API Base URLs: v2 = https://api.clickup.com/api/v2 ; v3 = https://api.clickup.com/api/v3
Documentation: https://developer.clickup.com/docs

Conventions: dates are Unix timestamps in milliseconds; task-scoped writes carry
``custom_task_ids``/``team_id`` on the QUERY string (see ``_QUERY_ON_WRITE``);
``team_id`` == Workspace ID. OAuth has no scope system; authorization is
per-Workspace, so the Workspace selector resolves valid team IDs via GET /team.
"""

import hashlib
import hmac
import logging
import re
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated, Tuple
from urllib.parse import quote
from pydantic import BaseModel, Field, ConfigDict, Discriminator, create_model
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import guarded_async_client
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.scopes.clickup import CLICKUP_SCOPES

logger = logging.getLogger(__name__)

CLICKUP_API_BASE = "https://api.clickup.com/api/v2"
CLICKUP_API_BASE_V3 = "https://api.clickup.com/api/v3"

# Task-scoped writes carry these as QUERY params (not body) even on POST/PUT/
# DELETE — ClickUp's custom-task-id addressing convention. Workspace-scoped ops
# consume team_id as a PATH field first, so a team_id that survives path
# substitution is always the query-form disambiguator. Applied in generic dispatch.
_QUERY_ON_WRITE = {"custom_task_ids", "team_id"}

# The webhook event types ClickUp can deliver. Exposed in the trigger config so
# the user picks WHICH event(s) fire the workflow. `*` is ClickUp's wildcard for
# "all events". The enum order is (label) human-friendly; the value is the raw
# ClickUp event string ClickUp sends in the inbound payload's `event` field and
# accepts in the `events` array at POST /team/{team_id}/webhook.
CLICKUP_WEBHOOK_EVENTS: List[str] = [
    "*",
    # Tasks
    "taskCreated",
    "taskUpdated",
    "taskDeleted",
    "taskPriorityUpdated",
    "taskStatusUpdated",
    "taskAssigneeUpdated",
    "taskDueDateUpdated",
    "taskTagUpdated",
    "taskMoved",
    "taskCommentPosted",
    "taskCommentUpdated",
    "taskTimeEstimateUpdated",
    "taskTimeTrackedUpdated",
    # Lists
    "listCreated",
    "listUpdated",
    "listDeleted",
    # Folders
    "folderCreated",
    "folderUpdated",
    "folderDeleted",
    # Spaces
    "spaceCreated",
    "spaceUpdated",
    "spaceDeleted",
    # Goals
    "goalCreated",
    "goalUpdated",
    "goalDeleted",
    "keyResultCreated",
    "keyResultUpdated",
    "keyResultDeleted",
]

CLICKUP_WEBHOOK_EVENT_LABELS: List[str] = [
    "All events",
    "Task created",
    "Task updated",
    "Task deleted",
    "Task priority updated",
    "Task status updated",
    "Task assignee updated",
    "Task due date updated",
    "Task tag updated",
    "Task moved",
    "Task comment posted",
    "Task comment updated",
    "Task time estimate updated",
    "Task time tracked updated",
    "List created",
    "List updated",
    "List deleted",
    "Folder created",
    "Folder updated",
    "Folder deleted",
    "Space created",
    "Space updated",
    "Space deleted",
    "Goal created",
    "Goal updated",
    "Goal deleted",
    "Key result created",
    "Key result updated",
    "Key result deleted",
]

# All non-wildcard events — the set ClickUp subscribes to when the user picks
# "All events" (`*`). ClickUp accepts `["*"]` too, but enumerating keeps the
# subscription explicit and makes the runtime filter a no-op pass-through.
ALL_CLICKUP_EVENTS: List[str] = [e for e in CLICKUP_WEBHOOK_EVENTS if e != "*"]


def _selected_trigger_events(config: Optional[Dict[str, Any]]) -> List[str]:
    """Resolve the user-selected webhook event(s) for a ClickUp trigger config.

    Returns the concrete list ClickUp should subscribe to. An empty/missing
    selection or the `*` wildcard expands to every supported event.
    """
    raw = (config or {}).get("event_types")
    selected = _comma_list(raw) if isinstance(raw, str) else (raw or None)
    if not selected or "*" in selected:
        return list(ALL_CLICKUP_EVENTS)
    return [e for e in selected if e in ALL_CLICKUP_EVENTS] or list(ALL_CLICKUP_EVENTS)


# ============================================================================
# Credential Schemas
# ============================================================================


class ClickUpOAuthCredential(BaseModel):
    """OAuth 2.0 credential for ClickUp (authorization_code flow).

    Tokens are obtained via the OAuth flow, not entered manually. ClickUp has no
    scope system; access is granted per-Workspace during consent. ClickUp access
    tokens do not currently expire and no refresh token is issued, so
    refresh_token/expires_at are usually empty.

    Register an OAuth app at: https://app.clickup.com/settings/apps
    """

    credential_type: Literal["clickup_oauth"] = Field(
        "clickup_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="ClickUp OAuth access token (Bearer).",
        json_schema_extra={"ui:widget": "password"},
    )
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    name: Optional[str] = Field(None, title="User Name")
    email: Optional[str] = Field(None, title="Account Email")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "clickup",
            "x-oauth-scopes": [],
            "x-credential-url": "https://app.clickup.com/settings/apps",
        }
    )


class ClickUpPersonalTokenCredential(BaseModel):
    """Personal API token credential for ClickUp.

    Obtain via ClickUp Settings -> Apps -> API Token (token begins with `pk_`).
    Sent as a raw `Authorization` header with NO `Bearer ` prefix.
    """

    credential_type: Literal["clickup_pat"] = Field(
        "clickup_pat", json_schema_extra={"ui:hidden": True}
    )
    personal_token: str = Field(
        ...,
        title="Personal API Token",
        description="Your ClickUp personal API token (starts with pk_) from Settings -> Apps -> API Token",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://app.clickup.com/settings/apps"}
    )


# OAuth first per the Union convention, then the API-token path.
ClickUpCredential = Union[ClickUpOAuthCredential, ClickUpPersonalTokenCredential]


# ============================================================================
# Operation Configs
# ============================================================================


class ClickUpGetTeamsConfig(BaseModel):
    """List the Workspaces (teams) the token can access."""

    operation: Literal["get_teams"] = Field(
        "get_teams",
        json_schema_extra={
            "const": "get_teams",
            "ui:hidden": True,
            "x-category": "Hierarchy",
            "x-is-trigger": False,
            "x-display-name": "Get Authorized Workspaces",
        },
        title="Get Authorized Workspaces",
    )


class ClickUpGetSpacesConfig(BaseModel):
    """List spaces in a Workspace."""

    operation: Literal["get_spaces"] = Field(
        "get_spaces",
        json_schema_extra={
            "const": "get_spaces",
            "ui:hidden": True,
            "x-category": "Hierarchy",
            "x-is-trigger": False,
            "x-display-name": "Get Spaces",
        },
        title="Get Spaces",
    )
    team_id: str = Field(
        ...,
        title="Workspace",
        description="The Workspace (team) to list spaces from",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "team_id",
                "placeholder": "Select a Workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a Workspace ID",
            },
            "x-resource-type": "clickup_workspace",
        },
    )


class ClickUpGetFoldersConfig(BaseModel):
    """List folders in a space."""

    operation: Literal["get_folders"] = Field(
        "get_folders",
        json_schema_extra={
            "const": "get_folders",
            "ui:hidden": True,
            "x-category": "Hierarchy",
            "x-is-trigger": False,
            "x-display-name": "Get Folders",
        },
        title="Get Folders",
    )
    space_id: str = Field(..., title="Space ID", description="The space to list folders from")


class ClickUpGetListsConfig(BaseModel):
    """List the lists inside a folder."""

    operation: Literal["get_lists"] = Field(
        "get_lists",
        json_schema_extra={
            "const": "get_lists",
            "ui:hidden": True,
            "x-category": "Hierarchy",
            "x-is-trigger": False,
            "x-display-name": "Get Lists",
        },
        title="Get Lists",
    )
    folder_id: str = Field(..., title="Folder ID", description="The folder to list lists from")


class ClickUpGetWorkspaceMembersConfig(BaseModel):
    """List members of a Workspace (for assignee selection)."""

    operation: Literal["get_workspace_members"] = Field(
        "get_workspace_members",
        json_schema_extra={
            "const": "get_workspace_members",
            "ui:hidden": True,
            "x-category": "Hierarchy",
            "x-is-trigger": False,
            "x-display-name": "Get Workspace Members",
        },
        title="Get Workspace Members",
    )
    team_id: str = Field(
        ...,
        title="Workspace",
        description="The Workspace (team) whose members to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "team_id",
                "placeholder": "Select a Workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a Workspace ID",
            },
            "x-resource-type": "clickup_workspace",
        },
    )


class ClickUpCreateTaskConfig(BaseModel):
    """Create a new task in a list."""

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
    list_id: str = Field(..., title="List ID", description="The list to create the task in")
    name: str = Field(..., title="Task Name", description="Name of the task")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Task description (Markdown)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    status: Optional[str] = Field(
        None, title="Status", description="Status name (must exist in the list)"
    )
    priority: Optional[str] = Field(
        None,
        title="Priority",
        description="Task priority",
        json_schema_extra={
            "enum": ["", "1", "2", "3", "4"],
            "enumNames": ["None", "Urgent", "High", "Normal", "Low"],
            "x-enum-searchable": True,
        },
    )
    assignees: Optional[str] = Field(
        None, title="Assignees", description="Comma-separated ClickUp user IDs to assign"
    )
    due_date: Optional[str] = Field(
        None, title="Due Date", description="Due date as a Unix timestamp in milliseconds"
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated tag names to apply"
    )


class ClickUpGetTasksConfig(BaseModel):
    """Retrieve tasks in a list (paginated)."""

    operation: Literal["get_tasks"] = Field(
        "get_tasks",
        json_schema_extra={
            "const": "get_tasks",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Get Tasks",
        },
        title="Get Tasks",
    )
    list_id: str = Field(..., title="List ID", description="The list to retrieve tasks from")
    archived: Optional[str] = Field(
        "false",
        title="Include Archived",
        description="Include archived tasks",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    page: Optional[str] = Field(
        "0", title="Page", description="Zero-indexed page number (100 tasks per page)"
    )


class ClickUpGetTaskConfig(BaseModel):
    """Fetch a single task's full details."""

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
    task_id: str = Field(..., title="Task ID", description="The task to retrieve")


class ClickUpUpdateTaskConfig(BaseModel):
    """Modify a task (name, status, priority, dates, etc.)."""

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
    task_id: str = Field(..., title="Task ID", description="The task to update")
    name: Optional[str] = Field(None, title="Task Name", description="New task name")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="New task description (Markdown)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    status: Optional[str] = Field(None, title="Status", description="New status name")
    priority: Optional[str] = Field(
        None,
        title="Priority",
        description="New task priority",
        json_schema_extra={
            "enum": ["", "1", "2", "3", "4"],
            "enumNames": ["None", "Urgent", "High", "Normal", "Low"],
            "x-enum-searchable": True,
        },
    )
    due_date: Optional[str] = Field(
        None, title="Due Date", description="New due date as a Unix timestamp in milliseconds"
    )


class ClickUpDeleteTaskConfig(BaseModel):
    """Remove a task."""

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
    task_id: str = Field(..., title="Task ID", description="The task to delete")


class ClickUpGetFilteredTeamTasksConfig(BaseModel):
    """Query tasks across a whole Workspace by filters."""

    operation: Literal["get_filtered_team_tasks"] = Field(
        "get_filtered_team_tasks",
        json_schema_extra={
            "const": "get_filtered_team_tasks",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Get Filtered Team Tasks",
        },
        title="Get Filtered Team Tasks",
    )
    team_id: str = Field(
        ...,
        title="Workspace",
        description="The Workspace (team) to query tasks across",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "team_id",
                "placeholder": "Select a Workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a Workspace ID",
            },
            "x-resource-type": "clickup_workspace",
        },
    )
    statuses: Optional[str] = Field(
        None, title="Statuses", description="Comma-separated status names to filter by"
    )
    assignees: Optional[str] = Field(
        None, title="Assignees", description="Comma-separated ClickUp user IDs to filter by"
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated tag names to filter by"
    )
    page: Optional[str] = Field(
        "0", title="Page", description="Zero-indexed page number (100 tasks per page)"
    )


class ClickUpCreateListConfig(BaseModel):
    """Create a list inside a folder."""

    operation: Literal["create_list"] = Field(
        "create_list",
        json_schema_extra={
            "const": "create_list",
            "ui:hidden": True,
            "x-category": "Lists & Folders",
            "x-is-trigger": False,
            "x-display-name": "Create List",
        },
        title="Create List",
    )
    folder_id: str = Field(..., title="Folder ID", description="The folder to create the list in")
    name: str = Field(..., title="List Name", description="Name of the new list")
    content: Optional[str] = Field(
        None, title="Description", description="Description / content of the list"
    )


class ClickUpCreateFolderConfig(BaseModel):
    """Create a folder in a space."""

    operation: Literal["create_folder"] = Field(
        "create_folder",
        json_schema_extra={
            "const": "create_folder",
            "ui:hidden": True,
            "x-category": "Lists & Folders",
            "x-is-trigger": False,
            "x-display-name": "Create Folder",
        },
        title="Create Folder",
    )
    space_id: str = Field(..., title="Space ID", description="The space to create the folder in")
    name: str = Field(..., title="Folder Name", description="Name of the new folder")


class ClickUpCreateTaskCommentConfig(BaseModel):
    """Add a comment to a task."""

    operation: Literal["create_task_comment"] = Field(
        "create_task_comment",
        json_schema_extra={
            "const": "create_task_comment",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "Create Task Comment",
        },
        title="Create Task Comment",
    )
    task_id: str = Field(..., title="Task ID", description="The task to comment on")
    comment_text: str = Field(
        ...,
        title="Comment",
        description="The comment text",
        json_schema_extra={"ui:widget": "textarea"},
    )
    assignee: Optional[str] = Field(
        None, title="Assignee", description="ClickUp user ID to assign the comment to"
    )
    notify_all: Optional[str] = Field(
        "false",
        title="Notify All",
        description="Notify all task watchers",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class ClickUpGetTaskCommentsConfig(BaseModel):
    """Retrieve comments on a task."""

    operation: Literal["get_task_comments"] = Field(
        "get_task_comments",
        json_schema_extra={
            "const": "get_task_comments",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "Get Task Comments",
        },
        title="Get Task Comments",
    )
    task_id: str = Field(..., title="Task ID", description="The task to fetch comments from")


class ClickUpGetAccessibleFieldsConfig(BaseModel):
    """List custom fields available in a list."""

    operation: Literal["get_accessible_fields"] = Field(
        "get_accessible_fields",
        json_schema_extra={
            "const": "get_accessible_fields",
            "ui:hidden": True,
            "x-category": "Custom Fields",
            "x-is-trigger": False,
            "x-display-name": "Get Accessible Custom Fields",
        },
        title="Get Accessible Custom Fields",
    )
    list_id: str = Field(..., title="List ID", description="The list whose custom fields to list")


class ClickUpSetCustomFieldConfig(BaseModel):
    """Set a custom field value on a task."""

    operation: Literal["set_custom_field"] = Field(
        "set_custom_field",
        json_schema_extra={
            "const": "set_custom_field",
            "ui:hidden": True,
            "x-category": "Custom Fields",
            "x-is-trigger": False,
            "x-display-name": "Set Custom Field Value",
        },
        title="Set Custom Field Value",
    )
    task_id: str = Field(..., title="Task ID", description="The task to set the field on")
    field_id: str = Field(..., title="Field ID", description="The custom field ID to set")
    value: str = Field(..., title="Value", description="The value to set on the custom field")


class ClickUpCreateTimeEntryConfig(BaseModel):
    """Log a time entry in a Workspace."""

    operation: Literal["create_time_entry"] = Field(
        "create_time_entry",
        json_schema_extra={
            "const": "create_time_entry",
            "ui:hidden": True,
            "x-category": "Time Tracking",
            "x-is-trigger": False,
            "x-display-name": "Create Time Entry",
        },
        title="Create Time Entry",
    )
    team_id: str = Field(
        ...,
        title="Workspace",
        description="The Workspace (team) to log the time entry in",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "team_id",
                "placeholder": "Select a Workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a Workspace ID",
            },
            "x-resource-type": "clickup_workspace",
        },
    )
    start: str = Field(
        ..., title="Start", description="Start time as a Unix timestamp in milliseconds"
    )
    duration: str = Field(
        ..., title="Duration", description="Duration of the entry in milliseconds"
    )
    task_id: Optional[str] = Field(
        None, title="Task ID", description="Task to associate the time entry with"
    )
    description: Optional[str] = Field(
        None, title="Description", description="Description of the time entry"
    )


class ClickUpGetTimeEntriesConfig(BaseModel):
    """Retrieve time entries within a date range."""

    operation: Literal["get_time_entries"] = Field(
        "get_time_entries",
        json_schema_extra={
            "const": "get_time_entries",
            "ui:hidden": True,
            "x-category": "Time Tracking",
            "x-is-trigger": False,
            "x-display-name": "Get Time Entries",
        },
        title="Get Time Entries",
    )
    team_id: str = Field(
        ...,
        title="Workspace",
        description="The Workspace (team) to retrieve time entries from",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "team_id",
                "placeholder": "Select a Workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a Workspace ID",
            },
            "x-resource-type": "clickup_workspace",
        },
    )
    start_date: Optional[str] = Field(
        None, title="Start Date", description="Lower bound as a Unix timestamp in milliseconds"
    )
    end_date: Optional[str] = Field(
        None, title="End Date", description="Upper bound as a Unix timestamp in milliseconds"
    )


class ClickUpStartTimerConfig(BaseModel):
    """Start a running timer (optionally tied to a task)."""

    operation: Literal["start_timer"] = Field(
        "start_timer",
        json_schema_extra={
            "const": "start_timer",
            "ui:hidden": True,
            "x-category": "Time Tracking",
            "x-is-trigger": False,
            "x-display-name": "Start Timer",
        },
        title="Start Timer",
    )
    team_id: str = Field(
        ...,
        title="Workspace",
        description="The Workspace (team) to start the timer in",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "team_id",
                "placeholder": "Select a Workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a Workspace ID",
            },
            "x-resource-type": "clickup_workspace",
        },
    )
    task_id: Optional[str] = Field(
        None, title="Task ID", description="Task to associate the running timer with"
    )
    description: Optional[str] = Field(
        None, title="Description", description="Description of the timer"
    )


class ClickUpStopTimerConfig(BaseModel):
    """Stop the currently running timer."""

    operation: Literal["stop_timer"] = Field(
        "stop_timer",
        json_schema_extra={
            "const": "stop_timer",
            "ui:hidden": True,
            "x-category": "Time Tracking",
            "x-is-trigger": False,
            "x-display-name": "Stop Timer",
        },
        title="Stop Timer",
    )
    team_id: str = Field(
        ...,
        title="Workspace",
        description="The Workspace (team) whose running timer to stop",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "team_id",
                "placeholder": "Select a Workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a Workspace ID",
            },
            "x-resource-type": "clickup_workspace",
        },
    )


class ClickUpCreateGoalConfig(BaseModel):
    """Create a goal in a Workspace."""

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
    team_id: str = Field(
        ...,
        title="Workspace",
        description="The Workspace (team) to create the goal in",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "team_id",
                "placeholder": "Select a Workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a Workspace ID",
            },
            "x-resource-type": "clickup_workspace",
        },
    )
    name: str = Field(..., title="Goal Name", description="Name of the goal")
    due_date: Optional[str] = Field(
        None, title="Due Date", description="Due date as a Unix timestamp in milliseconds"
    )
    description: Optional[str] = Field(
        None, title="Description", description="Description of the goal"
    )


class ClickUpGetGoalsConfig(BaseModel):
    """List Workspace goals."""

    operation: Literal["get_goals"] = Field(
        "get_goals",
        json_schema_extra={
            "const": "get_goals",
            "ui:hidden": True,
            "x-category": "Goals",
            "x-is-trigger": False,
            "x-display-name": "Get Goals",
        },
        title="Get Goals",
    )
    team_id: str = Field(
        ...,
        title="Workspace",
        description="The Workspace (team) whose goals to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "team_id",
                "placeholder": "Select a Workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a Workspace ID",
            },
            "x-resource-type": "clickup_workspace",
        },
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class ClickUpTaskTriggerConfig(BaseModel):
    """Fire the workflow on selected ClickUp webhook event(s).

    The user picks WHICH event(s) fire via ``event_types`` (task/list/folder/
    space/goal lifecycle events, or ``*`` for all). The selection is passed to
    ClickUp's ``POST /team/{team_id}/webhook`` ``events`` array and re-checked at
    runtime against the inbound payload's ``event`` field.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_task_event"] = Field(
        "on_task_event",
        json_schema_extra={
            "const": "on_task_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Task Event",
        },
        title="On Task Event",
    )
    team_id: str = Field(
        ...,
        title="Workspace",
        description="The Workspace (team) to subscribe to events from",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "team_id",
                "placeholder": "Select a Workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a Workspace ID",
            },
            "x-resource-type": "clickup_workspace",
        },
    )
    event_types: str = Field(
        "*",
        title="Trigger On",
        description=(
            "Which ClickUp event fires this workflow. "
            "'All events' (*) subscribes to every event below.\n"
            "- Task created / updated / deleted: a task is added, edited, or removed.\n"
            "- Task priority / status / assignee / due date / tag updated: a specific task field changes.\n"
            "- Task moved: a task changes list/folder/space.\n"
            "- Task comment posted / updated: a comment is added or edited on a task.\n"
            "- Task time estimate / time tracked updated: estimate or logged time changes.\n"
            "- List / Folder / Space created / updated / deleted: hierarchy containers change.\n"
            "- Goal / Key result created / updated / deleted: goals and their key results change."
        ),
        json_schema_extra={
            "enum": CLICKUP_WEBHOOK_EVENTS,
            "enumNames": CLICKUP_WEBHOOK_EVENT_LABELS,
            "x-enum-searchable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="ClickUp posts task events here. Registered automatically when you connect credentials.",
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
# Compact field/model helpers (for the comprehensive long-tail operations)
# ============================================================================


def _opf(value: str, display: str, category: str):
    """Operation discriminator field with display metadata."""
    return Field(
        default=value,
        title=display,
        json_schema_extra={
            "const": value,
            "ui:hidden": True,
            "x-display-name": display,
            "x-category": category,
            "x-is-trigger": False,
        },
    )


def _dyn(field_name: str, label: str) -> Dict[str, Any]:
    return {
        "x-dynamic-options": {
            "field_name": field_name,
            "placeholder": f"Select a {label}...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": f"Or paste a {label} ID",
        }
    }


def _extra():
    return Field(
        None,
        title="Additional Parameters",
        description=(
            "Any other ClickUp API parameters as key/value pairs; merged into the "
            "request body (writes) or query string (reads). Use for optional fields "
            "not surfaced above (e.g. custom_task_ids, page, filters, nested objects)."
        ),
    )


def _id(title: str, *, dyn: Optional[str] = None, required: bool = True):
    extra = _dyn(dyn, title) if dyn else {}
    return Field(... if required else None, title=title, json_schema_extra=extra)


def _titleize(field: str) -> str:
    base = field[:-3] if field.endswith("_id") else field
    return base.replace("_", " ").title() or field


# Path placeholders that should render as a searchable dropdown / nicer label.
_PLACEHOLDER_LABELS: Dict[str, str] = {
    "team_id": "Workspace",
    "workspace_id": "Workspace",
    "space_id": "Space",
    "folder_id": "Folder",
    "list_id": "List",
    "task_id": "Task",
    "goal_id": "Goal",
    "view_id": "View",
    "doc_id": "Doc",
    "page_id": "Page",
    "channel_id": "Channel",
    "message_id": "Message",
    "comment_id": "Comment",
    "checklist_id": "Checklist",
    "webhook_id": "Webhook",
    "tag_name": "Tag",
    "links_to": "Linked Task",
    "guest_id": "Guest",
    "user_id": "User",
    "group_id": "User Group",
    "timer_id": "Time Entry",
}
# Placeholders backed by the team_id dynamic-options loader (Workspace dropdown).
_DYN_PLACEHOLDERS = {"team_id", "workspace_id"}


def _placeholder_field(name: str):
    label = _PLACEHOLDER_LABELS.get(name, _titleize(name))
    if name in _DYN_PLACEHOLDERS:
        extra = _dyn(name, "Workspace")
        extra["x-resource-type"] = "clickup_workspace"
        return (str, Field(..., title=label, json_schema_extra=extra))
    return (str, Field(..., title=label, description=f"{label} ID"))


def _make_ext_model(op: str, display: str, category: str, path: str):
    """Generate a typed config model: path placeholders → required fields, plus a
    generic ``extra_params`` escape hatch for every other API parameter."""
    class_name = "ClickUp" + "".join(p.title() for p in op.split("_")) + "Config"
    fields: Dict[str, Any] = {"operation": (Literal[op], _opf(op, display, category))}
    for ph in re.findall(r"{(\w+)}", path):
        fields[ph] = _placeholder_field(ph)
    fields["extra_params"] = (Optional[Dict[str, Any]], _extra())
    return create_model(class_name, **fields)


# ============================================================================
# Advanced operations (rich hand-written configs)
# ============================================================================


class ClickUpCustomRequestConfig(BaseModel):
    """Escape hatch: call ANY ClickUp endpoint not modeled as a first-class op."""

    operation: Literal["custom_request"] = _opf(
        "custom_request", "Custom API Request", "Advanced"
    )
    http_method: str = Field(
        "GET",
        title="HTTP Method",
        json_schema_extra={
            "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
            "x-enum-searchable": True,
        },
    )
    api_version: str = Field(
        "v2",
        title="API Version",
        description="v2 for most endpoints; v3 for Docs and Chat.",
        json_schema_extra={
            "enum": ["v2", "v3"],
            "enumNames": ["v2 (default)", "v3 (Docs/Chat)"],
            "x-enum-searchable": True,
        },
    )
    path: str = Field(
        ...,
        title="Path",
        description="API path beginning with '/', relative to the version base, e.g. /team or /workspaces/{workspace_id}/docs",
    )
    params: Optional[Dict[str, Any]] = Field(
        None,
        title="Parameters",
        description="Query params for GET; JSON body for POST/PUT/PATCH/DELETE.",
    )


class ClickUpCreateTaskAttachmentConfig(BaseModel):
    """Attach a file (by URL) to a task. NoClick downloads the URL and uploads it
    to ClickUp as multipart/form-data."""

    operation: Literal["create_task_attachment"] = _opf(
        "create_task_attachment", "Create Task Attachment", "Attachments"
    )
    task_id: str = Field(..., title="Task ID", description="The task to attach the file to")
    file_url: str = Field(
        ...,
        title="File URL",
        description="Publicly accessible URL (or upstream resource URL) of the file to attach",
    )
    filename: Optional[str] = Field(
        None, title="Filename", description="Override the attachment filename (defaults to the URL's basename)"
    )
    custom_task_ids: Optional[str] = Field(
        None,
        title="Use Custom Task IDs",
        description="Set to true to address the task by its custom ID (requires Workspace).",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    team_id: Optional[str] = Field(
        None, title="Workspace (for custom IDs)", description="Required when Use Custom Task IDs is true"
    )


# ============================================================================
# Extended operation spec table — comprehensive long-tail coverage.
# (operation, display_name, category, http_method, path_template, api_version)
# Path placeholders become required fields; every op also accepts extra_params.
# ============================================================================

_EXTENDED_SPECS: List[Tuple[str, str, str, str, str, str]] = [
    # ---- Authorization ----
    ("get_authorized_user", "Get Authorized User", "Authorization", "GET", "/user", "v2"),
    # ---- Tasks ----
    ("merge_tasks", "Merge Tasks", "Tasks", "POST", "/task/{task_id}/merge", "v2"),
    ("get_task_time_in_status", "Get Task Time in Status", "Tasks", "GET", "/task/{task_id}/time_in_status", "v2"),
    ("get_bulk_tasks_time_in_status", "Get Bulk Tasks' Time in Status", "Tasks", "GET", "/task/bulk_time_in_status/task_ids", "v2"),
    ("create_task_from_template", "Create Task From Template", "Tasks", "POST", "/list/{list_id}/taskTemplate/{template_id}", "v2"),
    # ---- Task Relationships ----
    ("add_dependency", "Add Dependency", "Task Relationships", "POST", "/task/{task_id}/dependency", "v2"),
    ("delete_dependency", "Delete Dependency", "Task Relationships", "DELETE", "/task/{task_id}/dependency", "v2"),
    ("add_task_link", "Add Task Link", "Task Relationships", "POST", "/task/{task_id}/link/{links_to}", "v2"),
    ("delete_task_link", "Delete Task Link", "Task Relationships", "DELETE", "/task/{task_id}/link/{links_to}", "v2"),
    # ---- Tasks in Multiple Lists ----
    ("add_task_to_list", "Add Task to List", "Tasks in Multiple Lists", "POST", "/list/{list_id}/task/{task_id}", "v2"),
    ("remove_task_from_list", "Remove Task From List", "Tasks in Multiple Lists", "DELETE", "/list/{list_id}/task/{task_id}", "v2"),
    # ---- Tags ----
    ("get_space_tags", "Get Space Tags", "Tags", "GET", "/space/{space_id}/tag", "v2"),
    ("create_space_tag", "Create Space Tag", "Tags", "POST", "/space/{space_id}/tag", "v2"),
    ("edit_space_tag", "Edit Space Tag", "Tags", "PUT", "/space/{space_id}/tag/{tag_name}", "v2"),
    ("delete_space_tag", "Delete Space Tag", "Tags", "DELETE", "/space/{space_id}/tag/{tag_name}", "v2"),
    ("add_tag_to_task", "Add Tag to Task", "Tags", "POST", "/task/{task_id}/tag/{tag_name}", "v2"),
    ("remove_tag_from_task", "Remove Tag From Task", "Tags", "DELETE", "/task/{task_id}/tag/{tag_name}", "v2"),
    # ---- Checklists ----
    ("create_checklist", "Create Checklist", "Checklists", "POST", "/task/{task_id}/checklist", "v2"),
    ("edit_checklist", "Edit Checklist", "Checklists", "PUT", "/checklist/{checklist_id}", "v2"),
    ("delete_checklist", "Delete Checklist", "Checklists", "DELETE", "/checklist/{checklist_id}", "v2"),
    ("create_checklist_item", "Create Checklist Item", "Checklists", "POST", "/checklist/{checklist_id}/checklist_item", "v2"),
    ("edit_checklist_item", "Edit Checklist Item", "Checklists", "PUT", "/checklist/{checklist_id}/checklist_item/{checklist_item_id}", "v2"),
    ("delete_checklist_item", "Delete Checklist Item", "Checklists", "DELETE", "/checklist/{checklist_id}/checklist_item/{checklist_item_id}", "v2"),
    # ---- Comments ----
    ("get_chat_view_comments", "Get Chat View Comments", "Comments", "GET", "/view/{view_id}/comment", "v2"),
    ("create_chat_view_comment", "Create Chat View Comment", "Comments", "POST", "/view/{view_id}/comment", "v2"),
    ("get_list_comments", "Get List Comments", "Comments", "GET", "/list/{list_id}/comment", "v2"),
    ("create_list_comment", "Create List Comment", "Comments", "POST", "/list/{list_id}/comment", "v2"),
    ("update_comment", "Update Comment", "Comments", "PUT", "/comment/{comment_id}", "v2"),
    ("delete_comment", "Delete Comment", "Comments", "DELETE", "/comment/{comment_id}", "v2"),
    ("get_threaded_comments", "Get Threaded Comments", "Comments", "GET", "/comment/{comment_id}/reply", "v2"),
    ("create_threaded_comment", "Create Threaded Comment", "Comments", "POST", "/comment/{comment_id}/reply", "v2"),
    # ---- Custom Fields ----
    ("remove_custom_field_value", "Remove Custom Field Value", "Custom Fields", "DELETE", "/task/{task_id}/field/{field_id}", "v2"),
    ("get_team_custom_fields", "Get Workspace Custom Fields", "Custom Fields", "GET", "/team/{team_id}/field", "v2"),
    # ---- Lists ----
    ("get_folderless_lists", "Get Folderless Lists", "Lists & Folders", "GET", "/space/{space_id}/list", "v2"),
    ("create_folderless_list", "Create Folderless List", "Lists & Folders", "POST", "/space/{space_id}/list", "v2"),
    ("get_list", "Get List", "Lists & Folders", "GET", "/list/{list_id}", "v2"),
    ("update_list", "Update List", "Lists & Folders", "PUT", "/list/{list_id}", "v2"),
    ("delete_list", "Delete List", "Lists & Folders", "DELETE", "/list/{list_id}", "v2"),
    ("create_list_from_template_in_folder", "Create List From Template (Folder)", "Lists & Folders", "POST", "/folder/{folder_id}/list_template/{template_id}", "v2"),
    ("create_folderless_list_from_template", "Create Folderless List From Template", "Lists & Folders", "POST", "/space/{space_id}/list_template/{template_id}", "v2"),
    # ---- Folders ----
    ("get_folder", "Get Folder", "Lists & Folders", "GET", "/folder/{folder_id}", "v2"),
    ("update_folder", "Update Folder", "Lists & Folders", "PUT", "/folder/{folder_id}", "v2"),
    ("delete_folder", "Delete Folder", "Lists & Folders", "DELETE", "/folder/{folder_id}", "v2"),
    ("create_folder_from_template", "Create Folder From Template", "Lists & Folders", "POST", "/space/{space_id}/folder_template/{template_id}", "v2"),
    # ---- Spaces ----
    ("create_space", "Create Space", "Hierarchy", "POST", "/team/{team_id}/space", "v2"),
    ("get_space", "Get Space", "Hierarchy", "GET", "/space/{space_id}", "v2"),
    ("update_space", "Update Space", "Hierarchy", "PUT", "/space/{space_id}", "v2"),
    ("delete_space", "Delete Space", "Hierarchy", "DELETE", "/space/{space_id}", "v2"),
    # ---- Goals ----
    ("get_goal", "Get Goal", "Goals", "GET", "/goal/{goal_id}", "v2"),
    ("update_goal", "Update Goal", "Goals", "PUT", "/goal/{goal_id}", "v2"),
    ("delete_goal", "Delete Goal", "Goals", "DELETE", "/goal/{goal_id}", "v2"),
    ("create_key_result", "Create Key Result", "Goals", "POST", "/goal/{goal_id}/key_result", "v2"),
    ("edit_key_result", "Edit Key Result", "Goals", "PUT", "/key_result/{key_result_id}", "v2"),
    ("delete_key_result", "Delete Key Result", "Goals", "DELETE", "/key_result/{key_result_id}", "v2"),
    # ---- Views ----
    ("get_team_views", "Get Workspace Views", "Views", "GET", "/team/{team_id}/view", "v2"),
    ("get_space_views", "Get Space Views", "Views", "GET", "/space/{space_id}/view", "v2"),
    ("get_folder_views", "Get Folder Views", "Views", "GET", "/folder/{folder_id}/view", "v2"),
    ("get_list_views", "Get List Views", "Views", "GET", "/list/{list_id}/view", "v2"),
    ("create_team_view", "Create Workspace View", "Views", "POST", "/team/{team_id}/view", "v2"),
    ("create_space_view", "Create Space View", "Views", "POST", "/space/{space_id}/view", "v2"),
    ("create_folder_view", "Create Folder View", "Views", "POST", "/folder/{folder_id}/view", "v2"),
    ("create_list_view", "Create List View", "Views", "POST", "/list/{list_id}/view", "v2"),
    ("get_view", "Get View", "Views", "GET", "/view/{view_id}", "v2"),
    ("update_view", "Update View", "Views", "PUT", "/view/{view_id}", "v2"),
    ("delete_view", "Delete View", "Views", "DELETE", "/view/{view_id}", "v2"),
    ("get_view_tasks", "Get View Tasks", "Views", "GET", "/view/{view_id}/task", "v2"),
    # ---- Members ----
    ("get_task_members", "Get Task Members", "Members", "GET", "/task/{task_id}/member", "v2"),
    ("get_list_members", "Get List Members", "Members", "GET", "/list/{list_id}/member", "v2"),
    # ---- Guests (Enterprise) ----
    ("invite_guest_to_workspace", "Invite Guest to Workspace", "Guests", "POST", "/team/{team_id}/guest", "v2"),
    ("get_guest", "Get Guest", "Guests", "GET", "/team/{team_id}/guest/{guest_id}", "v2"),
    ("edit_guest_on_workspace", "Edit Guest on Workspace", "Guests", "PUT", "/team/{team_id}/guest/{guest_id}", "v2"),
    ("remove_guest_from_workspace", "Remove Guest From Workspace", "Guests", "DELETE", "/team/{team_id}/guest/{guest_id}", "v2"),
    ("add_guest_to_task", "Add Guest to Task", "Guests", "POST", "/task/{task_id}/guest/{guest_id}", "v2"),
    ("remove_guest_from_task", "Remove Guest From Task", "Guests", "DELETE", "/task/{task_id}/guest/{guest_id}", "v2"),
    ("add_guest_to_list", "Add Guest to List", "Guests", "POST", "/list/{list_id}/guest/{guest_id}", "v2"),
    ("remove_guest_from_list", "Remove Guest From List", "Guests", "DELETE", "/list/{list_id}/guest/{guest_id}", "v2"),
    ("add_guest_to_folder", "Add Guest to Folder", "Guests", "POST", "/folder/{folder_id}/guest/{guest_id}", "v2"),
    ("remove_guest_from_folder", "Remove Guest From Folder", "Guests", "DELETE", "/folder/{folder_id}/guest/{guest_id}", "v2"),
    # ---- Users (Enterprise) ----
    ("invite_user_to_workspace", "Invite User to Workspace", "Users", "POST", "/team/{team_id}/user", "v2"),
    ("get_user", "Get User", "Users", "GET", "/team/{team_id}/user/{user_id}", "v2"),
    ("edit_user_on_workspace", "Edit User on Workspace", "Users", "PUT", "/team/{team_id}/user/{user_id}", "v2"),
    ("remove_user_from_workspace", "Remove User From Workspace", "Users", "DELETE", "/team/{team_id}/user/{user_id}", "v2"),
    # ---- User Groups (Teams) ----
    ("create_user_group", "Create User Group", "User Groups", "POST", "/team/{team_id}/group", "v2"),
    ("get_user_groups", "Get User Groups", "User Groups", "GET", "/group", "v2"),
    ("update_user_group", "Update User Group", "User Groups", "PUT", "/group/{group_id}", "v2"),
    ("delete_user_group", "Delete User Group", "User Groups", "DELETE", "/group/{group_id}", "v2"),
    # ---- Roles ----
    ("get_custom_roles", "Get Custom Roles", "Roles", "GET", "/team/{team_id}/customroles", "v2"),
    # ---- Shared Hierarchy ----
    ("get_shared_hierarchy", "Get Shared Hierarchy", "Hierarchy", "GET", "/team/{team_id}/shared", "v2"),
    # ---- Time Tracking ----
    ("get_singular_time_entry", "Get Single Time Entry", "Time Tracking", "GET", "/team/{team_id}/time_entries/{timer_id}", "v2"),
    ("update_time_entry", "Update Time Entry", "Time Tracking", "PUT", "/team/{team_id}/time_entries/{timer_id}", "v2"),
    ("delete_time_entry", "Delete Time Entry", "Time Tracking", "DELETE", "/team/{team_id}/time_entries/{timer_id}", "v2"),
    ("get_running_time_entry", "Get Running Time Entry", "Time Tracking", "GET", "/team/{team_id}/time_entries/current", "v2"),
    ("get_time_entry_history", "Get Time Entry History", "Time Tracking", "GET", "/team/{team_id}/time_entries/{timer_id}/history", "v2"),
    ("get_all_tags_from_time_entries", "Get All Time Entry Tags", "Time Tracking", "GET", "/team/{team_id}/time_entries/tags", "v2"),
    ("add_tags_from_time_entries", "Add Tags to Time Entries", "Time Tracking", "POST", "/team/{team_id}/time_entries/tags", "v2"),
    ("remove_tags_from_time_entries", "Remove Tags From Time Entries", "Time Tracking", "DELETE", "/team/{team_id}/time_entries/tags", "v2"),
    ("change_tag_names_from_time_entries", "Rename Time Entry Tag", "Time Tracking", "PUT", "/team/{team_id}/time_entries/tags", "v2"),
    # ---- Time Tracking (legacy / deprecated) ----
    ("track_time", "Track Time (Legacy)", "Time Tracking", "POST", "/task/{task_id}/time", "v2"),
    ("get_tracked_time", "Get Tracked Time (Legacy)", "Time Tracking", "GET", "/task/{task_id}/time", "v2"),
    ("edit_time_tracked", "Edit Tracked Time (Legacy)", "Time Tracking", "PUT", "/task/{task_id}/time/{interval_id}", "v2"),
    ("delete_time_tracked", "Delete Tracked Time (Legacy)", "Time Tracking", "DELETE", "/task/{task_id}/time/{interval_id}", "v2"),
    # ---- Webhooks ----
    ("get_webhooks", "Get Webhooks", "Webhooks", "GET", "/team/{team_id}/webhook", "v2"),
    ("create_webhook", "Create Webhook", "Webhooks", "POST", "/team/{team_id}/webhook", "v2"),
    ("update_webhook", "Update Webhook", "Webhooks", "PUT", "/webhook/{webhook_id}", "v2"),
    ("delete_webhook", "Delete Webhook", "Webhooks", "DELETE", "/webhook/{webhook_id}", "v2"),
    # ---- Workspaces ----
    ("get_workspace_seats", "Get Workspace Seats", "Workspaces", "GET", "/team/{team_id}/seats", "v2"),
    ("get_workspace_plan", "Get Workspace Plan", "Workspaces", "GET", "/team/{team_id}/plan", "v2"),
    # ---- Docs (v3) ----
    ("search_docs", "Search Docs", "Docs", "GET", "/workspaces/{workspace_id}/docs", "v3"),
    ("create_doc", "Create Doc", "Docs", "POST", "/workspaces/{workspace_id}/docs", "v3"),
    ("get_doc", "Get Doc", "Docs", "GET", "/workspaces/{workspace_id}/docs/{doc_id}", "v3"),
    ("get_doc_page_listing", "Get Doc Page Listing", "Docs", "GET", "/workspaces/{workspace_id}/docs/{doc_id}/page_listing", "v3"),
    ("get_doc_pages", "Get Doc Pages", "Docs", "GET", "/workspaces/{workspace_id}/docs/{doc_id}/pages", "v3"),
    ("create_page", "Create Doc Page", "Docs", "POST", "/workspaces/{workspace_id}/docs/{doc_id}/pages", "v3"),
    ("get_page", "Get Doc Page", "Docs", "GET", "/workspaces/{workspace_id}/docs/{doc_id}/pages/{page_id}", "v3"),
    ("edit_page", "Edit Doc Page", "Docs", "PUT", "/workspaces/{workspace_id}/docs/{doc_id}/pages/{page_id}", "v3"),
    # ---- Chat (v3) ----
    ("list_chat_channels", "List Chat Channels", "Chat", "GET", "/workspaces/{workspace_id}/chat/channels", "v3"),
    ("create_chat_channel", "Create Chat Channel", "Chat", "POST", "/workspaces/{workspace_id}/chat/channels", "v3"),
    ("create_chat_location_channel", "Create Chat Location Channel", "Chat", "POST", "/workspaces/{workspace_id}/chat/channels/location", "v3"),
    ("create_chat_direct_message_channel", "Create Chat DM Channel", "Chat", "POST", "/workspaces/{workspace_id}/chat/channels/direct_message", "v3"),
    ("get_chat_channel", "Get Chat Channel", "Chat", "GET", "/workspaces/{workspace_id}/chat/channels/{channel_id}", "v3"),
    ("update_chat_channel", "Update Chat Channel", "Chat", "PATCH", "/workspaces/{workspace_id}/chat/channels/{channel_id}", "v3"),
    ("get_chat_channel_followers", "Get Chat Channel Followers", "Chat", "GET", "/workspaces/{workspace_id}/chat/channels/{channel_id}/followers", "v3"),
    ("get_chat_channel_members", "Get Chat Channel Members", "Chat", "GET", "/workspaces/{workspace_id}/chat/channels/{channel_id}/members", "v3"),
    ("list_chat_messages", "List Chat Messages", "Chat", "GET", "/workspaces/{workspace_id}/chat/channels/{channel_id}/messages", "v3"),
    ("create_chat_message", "Create Chat Message", "Chat", "POST", "/workspaces/{workspace_id}/chat/channels/{channel_id}/messages", "v3"),
    ("update_chat_message", "Update Chat Message", "Chat", "PATCH", "/workspaces/{workspace_id}/chat/messages/{message_id}", "v3"),
    ("delete_chat_message", "Delete Chat Message", "Chat", "DELETE", "/workspaces/{workspace_id}/chat/messages/{message_id}", "v3"),
    ("create_chat_reply", "Create Chat Reply", "Chat", "POST", "/workspaces/{workspace_id}/chat/messages/{message_id}/replies", "v3"),
    ("get_chat_replies", "Get Chat Replies", "Chat", "GET", "/workspaces/{workspace_id}/chat/messages/{message_id}/replies", "v3"),
    ("get_chat_message_reactions", "Get Chat Message Reactions", "Chat", "GET", "/workspaces/{workspace_id}/chat/messages/{message_id}/reactions", "v3"),
    ("create_chat_reaction", "Create Chat Reaction", "Chat", "POST", "/workspaces/{workspace_id}/chat/messages/{message_id}/reactions", "v3"),
    ("delete_chat_reaction", "Delete Chat Reaction", "Chat", "DELETE", "/workspaces/{workspace_id}/chat/messages/{message_id}/reactions/{reaction}", "v3"),
    ("get_chat_message_tagged_users", "Get Chat Message Tagged Users", "Chat", "GET", "/workspaces/{workspace_id}/chat/messages/{message_id}/tagged_users", "v3"),
    # ---- Audit Logs (v3, Enterprise) ----
    ("create_audit_logs", "Create Audit Logs", "Audit Logs", "POST", "/workspaces/{workspace_id}/auditlogs", "v3"),
]

# Build generated models + routing table from the spec.
_EXTENDED_MODELS: List[Any] = []
_EXTENDED_OPERATIONS: Dict[str, Tuple[str, str, str]] = {}
for _op, _disp, _cat, _method, _path, _ver in _EXTENDED_SPECS:
    _EXTENDED_MODELS.append(_make_ext_model(_op, _disp, _cat, _path))
    _EXTENDED_OPERATIONS[_op] = (_method, _path, _ver)

# Path fields per generated op (precomputed for dispatch).
_EXT_PATH_FIELDS: Dict[str, List[str]] = {
    _op: re.findall(r"{(\w+)}", _path) for _op, (_m, _path, _v) in _EXTENDED_OPERATIONS.items()
}


# ============================================================================
# Discriminated Union
# ============================================================================

_EXPLICIT_MEMBERS = [
    ClickUpGetTeamsConfig,
    ClickUpGetSpacesConfig,
    ClickUpGetFoldersConfig,
    ClickUpGetListsConfig,
    ClickUpGetWorkspaceMembersConfig,
    ClickUpCreateTaskConfig,
    ClickUpGetTasksConfig,
    ClickUpGetTaskConfig,
    ClickUpUpdateTaskConfig,
    ClickUpDeleteTaskConfig,
    ClickUpGetFilteredTeamTasksConfig,
    ClickUpCreateListConfig,
    ClickUpCreateFolderConfig,
    ClickUpCreateTaskCommentConfig,
    ClickUpGetTaskCommentsConfig,
    ClickUpGetAccessibleFieldsConfig,
    ClickUpSetCustomFieldConfig,
    ClickUpCreateTimeEntryConfig,
    ClickUpGetTimeEntriesConfig,
    ClickUpStartTimerConfig,
    ClickUpStopTimerConfig,
    ClickUpCreateGoalConfig,
    ClickUpGetGoalsConfig,
    ClickUpCreateTaskAttachmentConfig,
    ClickUpCustomRequestConfig,
]

ClickUpConfig = Annotated[
    Union[tuple(_EXPLICIT_MEMBERS + _EXTENDED_MODELS + [ClickUpTaskTriggerConfig])],
    Discriminator("operation"),
]


class ClickUpNodeConfig(NodeConfig[ClickUpConfig, ClickUpCredential]):
    """Full configuration for the ClickUp node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _comma_int_list(value: Optional[str]) -> Optional[List[int]]:
    parts = _comma_list(value)
    if not parts:
        return None
    out: List[int] = []
    for p in parts:
        if p.isdigit():
            out.append(int(p))
    return out or None


def _auth_header(credential: Dict[str, Any]) -> str:
    """Build the ClickUp Authorization header value.

    OAuth access tokens use the `Bearer ` prefix; personal `pk_` tokens use the
    raw token with NO prefix. Branch on whichever token field is present.
    """
    access_token = credential.get("access_token")
    if access_token:
        return f"Bearer {access_token}"
    personal_token = credential.get("personal_token")
    if personal_token:
        return personal_token
    raise ValueError("No ClickUp token found on the credential")


async def _clickup_request(
    credential: Dict[str, Any],
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
    base_url: str = CLICKUP_API_BASE,
) -> Dict[str, Any]:
    """Make an authenticated ClickUp request and return a structured result.

    ``base_url`` selects the API version (v2 default; pass CLICKUP_API_BASE_V3 for
    Docs/Chat/Audit). ``json_body`` is sent for any non-GET method (ClickUp has a
    few DELETE-with-body endpoints, e.g. delete_space_tag)."""
    url = f"{base_url}{endpoint}"
    headers = {
        "Authorization": _auth_header(credential),
        "Content-Type": "application/json",
    }
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = err.get("err") or err.get("error") or err.get("message") or str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[ClickUpNode] API error ({action_name}): {message}")
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
                    data = response.json()
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
            logger.error(f"[ClickUpNode] Request failed ({action_name}): {msg}")
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


class ClickUpNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """ClickUp project-management automation node."""

    edit_examples = [
        "Create a ClickUp task when a form is submitted",
        "List all tasks in a project list",
        "Update a task's status to Done when a deal closes",
        "Add a comment to a task with the latest status",
        "Trigger a workflow whenever a task is created or updated",
    ]

    scope_registry = CLICKUP_SCOPES
    connection_evidence = ConnectionEvidence(
        field="team_id",
        noun="workspaces",
    )

    @classmethod
    def get_config_model(cls):
        return ClickUpNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring ClickUp OAuth token at credential load (dropdowns,
        trigger registration). ClickUp tokens do not expire and Personal API
        tokens carry no refresh_token, so this is effectively a no-op; it exists
        so the load-time freshen choke point is uniform across OAuth nodes."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.clickup_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="clickup",
        )

    # ------------------------------------------------------------------
    # Dynamic options (Workspaces / teams)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        user_id: str,
        config_data: Dict[str, Any],
        credential_ids: Optional[Dict[str, str]] = None,
        pool=None,
    ) -> Dict[str, Any]:
        if field_name not in ("team_id", "workspace_id"):
            return {"options": []}
        from utils.credential_loader import load_credential

        credential_id = next((cid for cid in (credential_ids or {}).values() if cid), None)
        credential = await load_credential(pool, user_id, credential_id) if credential_id else None
        if not credential:
            return {"options": []}
        result = await _clickup_request(credential, "GET", "/team", action_name="get_teams")
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        teams = data.get("teams", []) if isinstance(data, dict) else []
        options = []
        for team in teams:
            if not isinstance(team, dict):
                continue
            team_id = team.get("id")
            name = team.get("name") or f"Workspace {team_id}"
            if team_id is not None:
                options.append({"label": str(name), "value": str(team_id)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Webhook trigger registration
    # ------------------------------------------------------------------
    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "team_id": (config or {}).get("team_id"),
            "event_types": (config or {}).get("event_types"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        team_id = (config or {}).get("team_id")
        if not team_id:
            raise ValueError("A Workspace (team) is required to register the ClickUp trigger")
        events = _selected_trigger_events(config)
        result = await _clickup_request(
            credential,
            "POST",
            f"/team/{team_id}/webhook",
            json_body={"endpoint": webhook_url, "events": events},
            action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"ClickUp webhook registration failed: {result.get('error')}")
        data = result.get("data") or {}
        webhook = data.get("webhook", data) if isinstance(data, dict) else {}
        external_id = webhook.get("id") if isinstance(webhook, dict) else None
        secret = webhook.get("secret") if isinstance(webhook, dict) else None
        return {
            "external_webhook_id": str(external_id) if external_id else None,
            "signing_secret": secret,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        if not external_id or not credential:
            return
        await _clickup_request(
            credential,
            "DELETE",
            f"/webhook/{external_id}",
            action_name="unregister_webhook",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored — accept (trigger not yet armed)
        sent = headers.get("x-signature")
        if not sent:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sent)

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Skip webhook deliveries whose event type isn't in the user's selection.

        ClickUp delivers every subscribed event to the same endpoint and names
        the event in the payload's top-level ``event`` field. When the user picks
        specific event(s), drop any other event ClickUp delivers (e.g. a stale
        subscription created before the selection was narrowed). ``*`` / empty
        selection passes everything through.
        """
        selected = (config or {}).get("event_types")
        parsed = _comma_list(selected) if isinstance(selected, str) else (selected or None)
        if not parsed or "*" in parsed:
            return True
        event = (payload or {}).get("event")
        if not event:
            return True  # non-event payload (e.g. ping) — don't drop
        return event in parsed

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, ClickUpNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, ClickUpTaskTriggerConfig):
            return {
                "status": "success",
                "action": "on_task_event",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your ClickUp API token.")
        credential = credentials.model_dump()

        handlers = {
            "get_teams": self._get_teams,
            "get_spaces": self._get_spaces,
            "get_folders": self._get_folders,
            "get_lists": self._get_lists,
            "get_workspace_members": self._get_workspace_members,
            "create_task": self._create_task,
            "get_tasks": self._get_tasks,
            "get_task": self._get_task,
            "update_task": self._update_task,
            "delete_task": self._delete_task,
            "get_filtered_team_tasks": self._get_filtered_team_tasks,
            "create_list": self._create_list,
            "create_folder": self._create_folder,
            "create_task_comment": self._create_task_comment,
            "get_task_comments": self._get_task_comments,
            "get_accessible_fields": self._get_accessible_fields,
            "set_custom_field": self._set_custom_field,
            "create_time_entry": self._create_time_entry,
            "get_time_entries": self._get_time_entries,
            "start_timer": self._start_timer,
            "stop_timer": self._stop_timer,
            "create_goal": self._create_goal,
            "get_goals": self._get_goals,
        }
        if op.operation == "custom_request":
            result = await self._custom_request(op, credential)
        elif op.operation == "create_task_attachment":
            result = await self._create_task_attachment(op, credential)
        else:
            handler = handlers.get(op.operation)
            if handler:
                result = await handler(op, credential)
            elif op.operation in _EXTENDED_OPERATIONS:
                result = await self._dispatch_generic(op, credential)
            else:
                raise ValueError(f"Unknown operation: {op.operation}")

        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Generic dispatch (table-driven long-tail operations)
    # ------------------------------------------------------------------
    async def _dispatch_generic(self, config, cred) -> Dict[str, Any]:
        """Route a spec-table operation: substitute path fields, then send the
        remaining params as query (GET) or body (writes). ClickUp's custom-task-id
        keys always ride the query string even on writes."""
        op = config.operation
        method, path_template, version = _EXTENDED_OPERATIONS[op]
        base = CLICKUP_API_BASE_V3 if version == "v3" else CLICKUP_API_BASE

        data = config.model_dump(exclude_none=True)
        data.pop("operation", None)
        extra = data.pop("extra_params", None) or {}

        path = path_template
        for field in _EXT_PATH_FIELDS[op]:
            value = data.pop(field, None)
            if value is None or value == "":
                raise ValueError(f"'{field}' is required for {op}")
            path = path.replace("{" + field + "}", quote(str(value), safe=""))

        # extra_params extend/override the typed fields.
        data.update(extra)

        if method == "GET":
            return await _clickup_request(
                cred, method, path, params=data or None, action_name=op, base_url=base
            )
        # Writes: peel custom-task-id keys back out to the query string.
        query = {k: data.pop(k) for k in list(data) if k in _QUERY_ON_WRITE}
        return await _clickup_request(
            cred, method, path, params=query or None, json_body=data or None,
            action_name=op, base_url=base,
        )

    async def _custom_request(self, c: ClickUpCustomRequestConfig, cred) -> Dict[str, Any]:
        method = (c.http_method or "GET").upper()
        base = CLICKUP_API_BASE_V3 if (c.api_version or "v2") == "v3" else CLICKUP_API_BASE
        path = c.path.strip()
        if not path.startswith("/"):
            path = "/" + path
        params = c.params or {}
        if method == "GET":
            return await _clickup_request(
                cred, method, path, params=params or None, action_name="custom_request", base_url=base
            )
        return await _clickup_request(
            cred, method, path, json_body=params or None, action_name="custom_request", base_url=base
        )

    async def _create_task_attachment(self, c: ClickUpCreateTaskAttachmentConfig, cred) -> Dict[str, Any]:
        """Download the file at file_url and upload it to the task as multipart."""
        import os
        from urllib.parse import urlparse

        query: Dict[str, Any] = {}
        if c.custom_task_ids:
            query["custom_task_ids"] = c.custom_task_ids
        if c.team_id:
            query["team_id"] = c.team_id
        filename = c.filename or os.path.basename(urlparse(c.file_url).path) or "attachment"

        start = time.time()
        try:
            async with guarded_async_client(timeout=60.0) as client:
                src = await client.get(c.file_url)
                if src.status_code >= 400:
                    return {
                        "status": "error", "action": "create_task_attachment",
                        "error": f"Could not download file_url ({src.status_code})",
                        "status_code": src.status_code,
                        "timing_ms": {"download": round((time.time() - start) * 1000, 2)},
                    }
                content = src.content
                up = await client.post(
                    f"{CLICKUP_API_BASE}/task/{quote(str(c.task_id), safe='')}/attachment",
                    headers={"Authorization": _auth_header(cred)},
                    params={k: v for k, v in query.items() if v not in (None, "")} or None,
                    files={"attachment": (filename, content)},
                )
                api_ms = round((time.time() - start) * 1000, 2)
                if up.status_code >= 400:
                    try:
                        message = up.json().get("err") or up.text
                    except Exception:
                        message = up.text
                    return {
                        "status": "error", "action": "create_task_attachment",
                        "error": str(message), "status_code": up.status_code,
                        "timing_ms": {"api_request": api_ms},
                    }
                try:
                    body = up.json()
                except Exception:
                    body = {"raw": up.text}
                return {
                    "status": "success", "action": "create_task_attachment",
                    "data": body, "status_code": up.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            return {
                "status": "error", "action": "create_task_attachment", "error": msg,
                "status_code": 500, "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    async def _get_teams(self, c: ClickUpGetTeamsConfig, cred) -> Dict[str, Any]:
        return await _clickup_request(cred, "GET", "/team", action_name="get_teams")

    async def _get_spaces(self, c: ClickUpGetSpacesConfig, cred) -> Dict[str, Any]:
        return await _clickup_request(
            cred, "GET", f"/team/{c.team_id}/space", action_name="get_spaces"
        )

    async def _get_folders(self, c: ClickUpGetFoldersConfig, cred) -> Dict[str, Any]:
        return await _clickup_request(
            cred, "GET", f"/space/{c.space_id}/folder", action_name="get_folders"
        )

    async def _get_lists(self, c: ClickUpGetListsConfig, cred) -> Dict[str, Any]:
        return await _clickup_request(
            cred, "GET", f"/folder/{c.folder_id}/list", action_name="get_lists"
        )

    async def _get_workspace_members(self, c: ClickUpGetWorkspaceMembersConfig, cred) -> Dict[str, Any]:
        # ClickUp has no /team/{id}/members endpoint — members are embedded in the
        # GET /team payload. Fetch teams, then return the selected Workspace's members.
        result = await _clickup_request(cred, "GET", "/team", action_name="get_workspace_members")
        if result.get("status") != "success":
            return result
        teams = (result.get("data") or {}).get("teams", []) if isinstance(result.get("data"), dict) else []
        team = next((t for t in teams if str(t.get("id")) == str(c.team_id)), None)
        if team is None:
            return {
                "status": "error",
                "action": "get_workspace_members",
                "error": f"Workspace {c.team_id} not found among authorized teams",
                "status_code": 404,
                "timing_ms": result.get("timing_ms", {}),
            }
        return {
            "status": "success",
            "action": "get_workspace_members",
            "data": {"members": team.get("members", [])},
            "status_code": 200,
            "timing_ms": result.get("timing_ms", {}),
        }

    async def _create_task(self, c: ClickUpCreateTaskConfig, cred) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "description": c.description,
            "status": c.status or None,
            "priority": int(c.priority) if c.priority and c.priority.isdigit() else None,
            "assignees": _comma_int_list(c.assignees),
            "due_date": int(c.due_date) if c.due_date and c.due_date.isdigit() else None,
            "tags": _comma_list(c.tags),
        }
        return await _clickup_request(
            cred, "POST", f"/list/{c.list_id}/task", json_body=body, action_name="create_task"
        )

    async def _get_tasks(self, c: ClickUpGetTasksConfig, cred) -> Dict[str, Any]:
        params = {
            "archived": c.archived,
            "page": c.page,
        }
        return await _clickup_request(
            cred, "GET", f"/list/{c.list_id}/task", params=params, action_name="get_tasks"
        )

    async def _get_task(self, c: ClickUpGetTaskConfig, cred) -> Dict[str, Any]:
        return await _clickup_request(
            cred, "GET", f"/task/{c.task_id}", action_name="get_task"
        )

    async def _update_task(self, c: ClickUpUpdateTaskConfig, cred) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "description": c.description,
            "status": c.status or None,
            "priority": int(c.priority) if c.priority and c.priority.isdigit() else None,
            "due_date": int(c.due_date) if c.due_date and c.due_date.isdigit() else None,
        }
        return await _clickup_request(
            cred, "PUT", f"/task/{c.task_id}", json_body=body, action_name="update_task"
        )

    async def _delete_task(self, c: ClickUpDeleteTaskConfig, cred) -> Dict[str, Any]:
        return await _clickup_request(
            cred, "DELETE", f"/task/{c.task_id}", action_name="delete_task"
        )

    async def _get_filtered_team_tasks(self, c: ClickUpGetFilteredTeamTasksConfig, cred) -> Dict[str, Any]:
        params = {
            "statuses[]": _comma_list(c.statuses),
            "assignees[]": _comma_list(c.assignees),
            "tags[]": _comma_list(c.tags),
            "page": c.page,
        }
        return await _clickup_request(
            cred, "GET", f"/team/{c.team_id}/task", params=params, action_name="get_filtered_team_tasks"
        )

    async def _create_list(self, c: ClickUpCreateListConfig, cred) -> Dict[str, Any]:
        body = {"name": c.name, "content": c.content}
        return await _clickup_request(
            cred, "POST", f"/folder/{c.folder_id}/list", json_body=body, action_name="create_list"
        )

    async def _create_folder(self, c: ClickUpCreateFolderConfig, cred) -> Dict[str, Any]:
        return await _clickup_request(
            cred, "POST", f"/space/{c.space_id}/folder", json_body={"name": c.name},
            action_name="create_folder",
        )

    async def _create_task_comment(self, c: ClickUpCreateTaskCommentConfig, cred) -> Dict[str, Any]:
        body = {
            "comment_text": c.comment_text,
            "assignee": int(c.assignee) if c.assignee and c.assignee.isdigit() else None,
            "notify_all": c.notify_all == "true",
        }
        return await _clickup_request(
            cred, "POST", f"/task/{c.task_id}/comment", json_body=body,
            action_name="create_task_comment",
        )

    async def _get_task_comments(self, c: ClickUpGetTaskCommentsConfig, cred) -> Dict[str, Any]:
        return await _clickup_request(
            cred, "GET", f"/task/{c.task_id}/comment", action_name="get_task_comments"
        )

    async def _get_accessible_fields(self, c: ClickUpGetAccessibleFieldsConfig, cred) -> Dict[str, Any]:
        return await _clickup_request(
            cred, "GET", f"/list/{c.list_id}/field", action_name="get_accessible_fields"
        )

    async def _set_custom_field(self, c: ClickUpSetCustomFieldConfig, cred) -> Dict[str, Any]:
        return await _clickup_request(
            cred, "POST", f"/task/{c.task_id}/field/{c.field_id}",
            json_body={"value": c.value}, action_name="set_custom_field",
        )

    async def _create_time_entry(self, c: ClickUpCreateTimeEntryConfig, cred) -> Dict[str, Any]:
        body = {
            "start": int(c.start) if c.start.isdigit() else c.start,
            "duration": int(c.duration) if c.duration.isdigit() else c.duration,
            "tid": c.task_id or None,
            "description": c.description,
        }
        return await _clickup_request(
            cred, "POST", f"/team/{c.team_id}/time_entries", json_body=body,
            action_name="create_time_entry",
        )

    async def _get_time_entries(self, c: ClickUpGetTimeEntriesConfig, cred) -> Dict[str, Any]:
        params = {"start_date": c.start_date, "end_date": c.end_date}
        return await _clickup_request(
            cred, "GET", f"/team/{c.team_id}/time_entries", params=params,
            action_name="get_time_entries",
        )

    async def _start_timer(self, c: ClickUpStartTimerConfig, cred) -> Dict[str, Any]:
        body = {"tid": c.task_id or None, "description": c.description}
        return await _clickup_request(
            cred, "POST", f"/team/{c.team_id}/time_entries/start", json_body=body,
            action_name="start_timer",
        )

    async def _stop_timer(self, c: ClickUpStopTimerConfig, cred) -> Dict[str, Any]:
        return await _clickup_request(
            cred, "POST", f"/team/{c.team_id}/time_entries/stop", action_name="stop_timer"
        )

    async def _create_goal(self, c: ClickUpCreateGoalConfig, cred) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "due_date": int(c.due_date) if c.due_date and c.due_date.isdigit() else None,
            "description": c.description,
        }
        return await _clickup_request(
            cred, "POST", f"/team/{c.team_id}/goal", json_body=body, action_name="create_goal"
        )

    async def _get_goals(self, c: ClickUpGetGoalsConfig, cred) -> Dict[str, Any]:
        return await _clickup_request(
            cred, "GET", f"/team/{c.team_id}/goal", action_name="get_goals"
        )
