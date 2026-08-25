"""
Google Tasks workflow node implementation.
Enables managing task lists and tasks via Google OAuth credentials.

Supports 10 operations:
- Task Lists: list_task_lists, get_task_list, create_task_list, update_task_list, delete_task_list
- Tasks: list_tasks, get_task, create_task, update_task, delete_task
"""

import time
import logging
from typing import Dict, Any, Optional, Union, Type, List, Literal, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import require_credential_token
from nodes.oauth.google_oauth import is_token_expired, refresh_access_token
from nodes.scopes.google import GOOGLE_TASKS_SCOPES

logger = logging.getLogger(__name__)

GOOGLE_TASKS_API_BASE = "https://tasks.googleapis.com/tasks/v1"


# ============================================================================
# Google Tasks Node Credential Schema
# ============================================================================


class GoogleTasksOAuthCredential(BaseModel):
    """
    OAuth credential for Google Tasks access.
    Tokens are obtained via OAuth flow, not entered manually.
    """

    credential_type: Literal["google_tasks_oauth"] = Field(
        "google_tasks_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Google"
    )
    refresh_token: str = Field(
        ...,
        title="Refresh Token",
        description="OAuth 2.0 refresh token for automatic renewal",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when access token expires",
    )
    email: str = Field(
        ...,
        title="Google Account",
        description="Email address of the connected Google account",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "google",
            "x-oauth-scopes": ["https://www.googleapis.com/auth/tasks"],
        }
    )


# ============================================================================
# Google Tasks Node Configuration Models - Task Lists
# ============================================================================


class GoogleTasksListTaskListsConfig(BaseModel):
    """Configuration for listing all task lists"""

    operation: Literal["list_all_task_lists"] = Field(
        "list_all_task_lists",
        title="List All Task Lists",
        description="List all task lists",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_all_task_lists",
            "x-category": "Task List",
            "x-is-trigger": False,
            "x-display-name": "List All Task Lists",
            "x-keywords": [
                "my task lists",
                "all task lists",
                "show task lists",
                "browse task lists",
                "todo lists",
            ],
        },
    )
    max_results: Optional[int] = Field(
        100,
        title="Max Results",
        description="Maximum number of task lists to return (1-100)",
        ge=1,
        le=100,
    )


class GoogleTasksGetTaskListConfig(BaseModel):
    """Configuration for getting a single task list"""

    operation: Literal["fetch_task_list"] = Field(
        "fetch_task_list",
        title="Fetch Task List",
        description="Get a specific task list",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_task_list",
            "x-category": "Task List",
            "x-is-trigger": False,
            "x-display-name": "Fetch Task List",
            "x-keywords": [
                "get task list",
                "single task list",
                "task list details",
                "one todo list",
            ],
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List",
        description="Select a task list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "task_list_id",
                "placeholder": "Select a task list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter task list ID",
            },
            "x-resource-type": "google_tasklist",
        },
    )


class GoogleTasksCreateTaskListConfig(BaseModel):
    """Configuration for creating a new task list"""

    operation: Literal["create_new_task_list"] = Field(
        "create_new_task_list",
        title="Create New Task List",
        description="Create a new task list",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_new_task_list",
            "x-category": "Task List",
            "x-is-trigger": False,
            "x-display-name": "Create New Task List",
            "x-keywords": [
                "new task list",
                "start task list",
                "make todo list",
                "add task list",
            ],
            "x-creates-resource": True,
            "x-resource-type": "google_tasklist",
            "x-resource-id-path": "task_list.id",
        },
    )
    title: str = Field(
        ...,
        title="Title",
        description="Title of the new task list",
        json_schema_extra={"placeholder": "My Tasks"},
    )


class GoogleTasksUpdateTaskListConfig(BaseModel):
    """Configuration for updating a task list"""

    operation: Literal["update_task_list_metadata"] = Field(
        "update_task_list_metadata",
        title="Update Task List Metadata",
        description="Update a task list",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_task_list_metadata",
            "x-category": "Task List",
            "x-is-trigger": False,
            "x-display-name": "Update Task List Metadata",
            "x-keywords": [
                "rename task list",
                "edit task list",
                "task list title",
                "change list name",
            ],
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List",
        description="Select a task list to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "task_list_id",
                "placeholder": "Select a task list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter task list ID",
            },
            "x-resource-type": "google_tasklist",
        },
    )
    title: str = Field(
        ...,
        title="New Title",
        description="New title for the task list",
        json_schema_extra={"placeholder": "Updated Task List Name"},
    )


class GoogleTasksDeleteTaskListConfig(BaseModel):
    """Configuration for deleting a task list"""

    operation: Literal["delete_task_list"] = Field(
        "delete_task_list",
        title="Delete Task List",
        description="Delete a task list",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_task_list",
            "x-category": "Task List",
            "x-is-trigger": False,
            "x-display-name": "Delete Task List",
            "x-keywords": [
                "remove task list",
                "delete todo list",
                "trash task list",
                "drop list",
            ],
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List",
        description="Select a task list to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "task_list_id",
                "placeholder": "Select a task list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter task list ID",
            },
            "x-resource-type": "google_tasklist",
        },
    )


# ============================================================================
# Google Tasks Node Configuration Models - Tasks
# ============================================================================


class GoogleTasksListTasksConfig(BaseModel):
    """Configuration for listing tasks in a task list"""

    operation: Literal["list_tasks_in_list"] = Field(
        "list_tasks_in_list",
        title="List Tasks in List",
        description="List tasks in a task list",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_tasks_in_list",
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "List Tasks in List",
            "x-keywords": [
                "tasks in list",
                "show my tasks",
                "todo items",
                "all tasks",
                "list todos",
            ],
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List",
        description="Select a task list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "task_list_id",
                "placeholder": "Select a task list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter task list ID",
            },
            "x-resource-type": "google_tasklist",
        },
    )
    max_results: Optional[int] = Field(
        100,
        title="Max Results",
        description="Maximum number of tasks to return (1-100)",
        ge=1,
        le=100,
    )
    show_completed: Optional[bool] = Field(
        True, title="Show Completed", description="Whether to include completed tasks"
    )
    show_hidden: Optional[bool] = Field(
        False, title="Show Hidden", description="Whether to include hidden tasks"
    )
    due_min: Optional[str] = Field(
        None,
        title="Due After",
        description="Filter tasks due after this date (RFC 3339 format)",
        json_schema_extra={"placeholder": "2024-01-01T00:00:00Z (optional)"},
    )
    due_max: Optional[str] = Field(
        None,
        title="Due Before",
        description="Filter tasks due before this date (RFC 3339 format)",
        json_schema_extra={"placeholder": "2024-12-31T23:59:59Z (optional)"},
    )


class GoogleTasksGetTaskConfig(BaseModel):
    """Configuration for getting a single task"""

    operation: Literal["fetch_task_from_list"] = Field(
        "fetch_task_from_list",
        title="Fetch Task from List",
        description="Get a specific task",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_task_from_list",
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Fetch Task from List",
            "x-keywords": ["get a task", "single task", "task details", "one todo"],
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List",
        description="Select a task list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "task_list_id",
                "placeholder": "Select a task list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter task list ID",
            },
            "x-resource-type": "google_tasklist",
        },
    )
    task_id: str = Field(
        ...,
        title="Task ID",
        description="The ID of the task to retrieve",
        json_schema_extra={"placeholder": "Task ID"},
    )


class GoogleTasksCreateTaskConfig(BaseModel):
    """Configuration for creating a new task"""

    operation: Literal["create_new_task"] = Field(
        "create_new_task",
        title="Create New Task",
        description="Create a new task",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_new_task",
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Create New Task",
            "x-keywords": [
                "new task",
                "add todo",
                "make a task",
                "add to do",
                "create reminder",
            ],
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List",
        description="Select a task list to create the task in",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "task_list_id",
                "placeholder": "Select a task list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter task list ID",
            },
            "x-resource-type": "google_tasklist",
        },
    )
    title: str = Field(
        ...,
        title="Title",
        description="Title of the task",
        json_schema_extra={"placeholder": "Complete project report"},
    )
    notes: Optional[str] = Field(
        None,
        title="Notes",
        description="Additional notes or description for the task",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "Task details..."},
    )
    due: Optional[str] = Field(
        None,
        title="Due Date",
        description="Due date for the task (RFC 3339 format, date only: YYYY-MM-DD)",
        json_schema_extra={"placeholder": "2024-01-15 (optional)"},
    )


class GoogleTasksUpdateTaskConfig(BaseModel):
    """Configuration for updating a task"""

    operation: Literal["update_task_in_list"] = Field(
        "update_task_in_list",
        title="Update Task in List",
        description="Update a task",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_task_in_list",
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Update Task in List",
            "x-keywords": [
                "edit task",
                "mark done",
                "complete task",
                "rename task",
                "change due date",
            ],
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List",
        description="Select a task list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "task_list_id",
                "placeholder": "Select a task list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter task list ID",
            },
            "x-resource-type": "google_tasklist",
        },
    )
    task_id: str = Field(
        ...,
        title="Task ID",
        description="The ID of the task to update",
        json_schema_extra={"placeholder": "Task ID"},
    )
    title: Optional[str] = Field(
        None,
        title="Title",
        description="New title for the task (leave empty to keep current)",
        json_schema_extra={"placeholder": "New title (optional)"},
    )
    notes: Optional[str] = Field(
        None,
        title="Notes",
        description="New notes for the task (leave empty to keep current)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "New notes (optional)",
        },
    )
    due: Optional[str] = Field(
        None,
        title="Due Date",
        description="New due date (RFC 3339 format, date only: YYYY-MM-DD)",
        json_schema_extra={"placeholder": "2024-01-15 (optional)"},
    )
    status: Optional[Literal["needsAction", "completed"]] = Field(
        None,
        title="Status",
        description="Task status",
        json_schema_extra={"placeholder": "Select status (optional)"},
    )


class GoogleTasksDeleteTaskConfig(BaseModel):
    """Configuration for deleting a task"""

    operation: Literal["delete_task_from_list"] = Field(
        "delete_task_from_list",
        title="Delete Task from List",
        description="Delete a task",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_task_from_list",
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Delete Task from List",
            "x-keywords": ["remove task", "delete todo", "trash task", "drop task"],
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List",
        description="Select a task list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "task_list_id",
                "placeholder": "Select a task list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter task list ID",
            },
            "x-resource-type": "google_tasklist",
        },
    )
    task_id: str = Field(
        ...,
        title="Task ID",
        description="The ID of the task to delete",
        json_schema_extra={"placeholder": "Task ID"},
    )


class GoogleTasksClearCompletedConfig(BaseModel):
    """Configuration for clearing all completed tasks from a task list"""

    operation: Literal["clear_completed_tasks"] = Field(
        "clear_completed_tasks",
        title="Clear Completed Tasks",
        description="Clear all completed tasks",
        json_schema_extra={
            "ui:hidden": True,
            "const": "clear_completed_tasks",
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Clear Completed Tasks",
            "x-keywords": [
                "clear completed",
                "remove done tasks",
                "wipe finished",
                "purge completed",
                "delete checked off",
            ],
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List",
        description="Select a task list to clear completed tasks from",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "task_list_id",
                "placeholder": "Select a task list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter task list ID",
            },
            "x-resource-type": "google_tasklist",
        },
    )


class GoogleTasksMoveTaskConfig(BaseModel):
    """Configuration for moving a task to a different position"""

    operation: Literal["move_task_to_position"] = Field(
        "move_task_to_position",
        title="Move Task to Position",
        description="Move a task to a different position",
        json_schema_extra={
            "ui:hidden": True,
            "const": "move_task_to_position",
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Move Task to Position",
            "x-keywords": [
                "reorder task",
                "reposition task",
                "indent task",
                "move under parent",
                "rearrange task",
            ],
        },
    )
    task_list_id: str = Field(
        ...,
        title="Task List",
        description="Select a task list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "task_list_id",
                "placeholder": "Select a task list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter task list ID",
            },
            "x-resource-type": "google_tasklist",
        },
    )
    task_id: str = Field(
        ...,
        title="Task ID",
        description="The ID of the task to move",
        json_schema_extra={"placeholder": "Task ID"},
    )
    parent: Optional[str] = Field(
        None,
        title="Parent Task ID",
        description="ID of parent task to move under (makes this a subtask)",
        json_schema_extra={"placeholder": "Parent task ID (optional)"},
    )
    previous: Optional[str] = Field(
        None,
        title="Previous Task ID",
        description="ID of task to position after",
        json_schema_extra={"placeholder": "Previous task ID (optional)"},
    )


# Union of all config types for oneOf schema
GoogleTasksConfig = Annotated[
    Union[
        GoogleTasksListTaskListsConfig,
        GoogleTasksGetTaskListConfig,
        GoogleTasksCreateTaskListConfig,
        GoogleTasksUpdateTaskListConfig,
        GoogleTasksDeleteTaskListConfig,
        GoogleTasksListTasksConfig,
        GoogleTasksGetTaskConfig,
        GoogleTasksCreateTaskConfig,
        GoogleTasksUpdateTaskConfig,
        GoogleTasksDeleteTaskConfig,
        GoogleTasksClearCompletedConfig,
        GoogleTasksMoveTaskConfig,
    ],
    Discriminator("operation"),
]


class GoogleTasksNodeConfig(NodeConfig[GoogleTasksConfig, GoogleTasksOAuthCredential]):
    """Full configuration for Google Tasks node including credentials"""

    pass


# ============================================================================
# Google Tasks Node Implementation
# ============================================================================


class GoogleTasksNode(WorkflowNode):
    """
    Google Tasks workflow node for managing task lists and tasks.
    """

    edit_examples = [
        "Add new tasks to the Q2 Goals list with due dates and descriptions",
        "Mark all completed items from the Groceries list and clear them out",
        "Create a new task list for the new client project called ProjectAlpha",
        "Move overdue tasks from Q1 to Q2 list and add priority subtasks",
        "List all tasks due this week across all lists and create a summary",
        'Update task status from "todo" to "in_progress" for the sprint tasks',
        'Get all tasks from the "Bugs" list and move critical ones to today',
    ]

    scope_registry = GOOGLE_TASKS_SCOPES
    connection_evidence = ConnectionEvidence(
        field="task_list_id",
        noun="task lists",
    )

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for Google Tasks node"""
        return GoogleTasksNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Load dynamic options for a field.
        """
        logger.info(f"[GoogleTasksNode] load_field_options called: field={field_name}")
        if field_name == "task_list_id":
            return await cls._list_task_lists_options(credential_data, search=search)
        return []

    @classmethod
    async def _list_task_lists_options(
        cls, credential_data: Dict[str, Any], search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List all task lists for dropdown options."""
        access_token = require_credential_token(
            credential_data.get("access_token"),
            "Connect a Google account to load task lists",
        )

        url = f"{GOOGLE_TASKS_API_BASE}/users/@me/lists"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )

                if response.status_code != 200:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    logger.error(f"[GoogleTasksNode] Tasks API error: {error_msg}")
                    raise ValueError(f"Google Tasks API error: {error_msg}")

                data = response.json()
                task_lists = data.get("items", [])

                options = []
                for task_list in task_lists:
                    list_id = task_list.get("id", "")
                    title = task_list.get("title", list_id)

                    options.append(
                        {
                            "value": list_id,
                            "label": title,
                            "metadata": {"updated": task_list.get("updated")},
                        }
                    )

                logger.info(f"[GoogleTasksNode] Found {len(options)} task lists")
                return options

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"[GoogleTasksNode] Error listing task lists: {e}")
            raise ValueError(f"Failed to load Google Tasks options: {e}") from e

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Google Tasks operation."""
        logger.info(f"[GoogleTasksNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config:
            raise ValueError(
                f"[GoogleTasksNode] Configuration is required but not provided for node {self.node_id}"
            )

        if not isinstance(node_config, GoogleTasksNodeConfig):
            raise ValueError(
                f"[GoogleTasksNode] Invalid config type: {type(node_config)}, expected GoogleTasksNodeConfig"
            )

        config = node_config.config
        credentials = node_config.credentials

        if not credentials:
            raise ValueError(
                f"[GoogleTasksNode] Google Tasks credentials are required but not provided. "
                f"Please connect a Google account in the node's credentials tab."
            )

        access_token = await self._ensure_fresh_token(credentials)

        # Execute operation based on config type
        if isinstance(config, GoogleTasksListTaskListsConfig):
            output = await self._list_task_lists(config, access_token)
        elif isinstance(config, GoogleTasksGetTaskListConfig):
            output = await self._get_task_list(config, access_token)
        elif isinstance(config, GoogleTasksCreateTaskListConfig):
            output = await self._create_task_list(config, access_token)
        elif isinstance(config, GoogleTasksUpdateTaskListConfig):
            output = await self._update_task_list(config, access_token)
        elif isinstance(config, GoogleTasksDeleteTaskListConfig):
            output = await self._delete_task_list(config, access_token)
        elif isinstance(config, GoogleTasksListTasksConfig):
            output = await self._list_tasks(config, access_token)
        elif isinstance(config, GoogleTasksGetTaskConfig):
            output = await self._get_task(config, access_token)
        elif isinstance(config, GoogleTasksCreateTaskConfig):
            output = await self._create_task(config, access_token)
        elif isinstance(config, GoogleTasksUpdateTaskConfig):
            output = await self._update_task(config, access_token)
        elif isinstance(config, GoogleTasksDeleteTaskConfig):
            output = await self._delete_task(config, access_token)
        elif isinstance(config, GoogleTasksClearCompletedConfig):
            output = await self._clear_completed(config, access_token)
        elif isinstance(config, GoogleTasksMoveTaskConfig):
            output = await self._move_task(config, access_token)
        else:
            raise ValueError(f"Unexpected config type: {type(config)}")

        await self.emit(output)
        return output

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="google",
        )

    async def _ensure_fresh_token(self, credentials: GoogleTasksOAuthCredential) -> str:
        """Return a valid Google Tasks access token, refreshing + persisting if expired."""
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.google_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="google",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    # ========================================================================
    # Task List Operations
    # ========================================================================

    async def _list_task_lists(
        self, config: GoogleTasksListTaskListsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List all task lists."""
        logger.info(f"[GoogleTasksNode] Listing task lists")

        url = f"{GOOGLE_TASKS_API_BASE}/users/@me/lists"
        params: Dict[str, Any] = {}
        if config.max_results:
            params["maxResults"] = config.max_results

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleTasksNode] List task lists failed: {error_msg}")
                raise ValueError(f"Google Tasks API error: {error_msg}")

            data = response.json()
            task_lists = data.get("items", [])

            simplified_lists = []
            for tl in task_lists:
                simplified_lists.append(
                    {
                        "id": tl.get("id"),
                        "title": tl.get("title"),
                        "updated": tl.get("updated"),
                        "selfLink": tl.get("selfLink"),
                    }
                )

            output = {
                "type": "google_tasks",
                "operation": "list_all_task_lists",
                "task_list_count": len(simplified_lists),
                "task_lists": simplified_lists,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleTasksNode] Listed {len(simplified_lists)} task lists")
            return output

    async def _get_task_list(
        self, config: GoogleTasksGetTaskListConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a single task list."""
        logger.info(f"[GoogleTasksNode] Getting task list {config.task_list_id}")

        url = f"{GOOGLE_TASKS_API_BASE}/users/@me/lists/{config.task_list_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleTasksNode] Get task list failed: {error_msg}")
                raise ValueError(f"Google Tasks API error: {error_msg}")

            tl = response.json()

            output = {
                "type": "google_tasks",
                "operation": "fetch_task_list",
                "task_list": {
                    "id": tl.get("id"),
                    "title": tl.get("title"),
                    "updated": tl.get("updated"),
                    "selfLink": tl.get("selfLink"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleTasksNode] Retrieved task list: {tl.get('title')}")
            return output

    async def _create_task_list(
        self, config: GoogleTasksCreateTaskListConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new task list."""
        logger.info(f"[GoogleTasksNode] Creating task list: {config.title}")

        url = f"{GOOGLE_TASKS_API_BASE}/users/@me/lists"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"title": config.title},
            )

            if response.status_code not in (200, 201):
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleTasksNode] Create task list failed: {error_msg}")
                raise ValueError(f"Google Tasks API error: {error_msg}")

            tl = response.json()

            output = {
                "type": "google_tasks",
                "operation": "create_new_task_list",
                "task_list_id": tl.get("id"),
                "task_list": {
                    "id": tl.get("id"),
                    "title": tl.get("title"),
                    "updated": tl.get("updated"),
                    "selfLink": tl.get("selfLink"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleTasksNode] Created task list: {tl.get('id')}")
            return output

    async def _update_task_list(
        self, config: GoogleTasksUpdateTaskListConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update a task list."""
        logger.info(f"[GoogleTasksNode] Updating task list {config.task_list_id}")

        url = f"{GOOGLE_TASKS_API_BASE}/users/@me/lists/{config.task_list_id}"

        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"title": config.title},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleTasksNode] Update task list failed: {error_msg}")
                raise ValueError(f"Google Tasks API error: {error_msg}")

            tl = response.json()

            output = {
                "type": "google_tasks",
                "operation": "update_task_list_metadata",
                "task_list_id": tl.get("id"),
                "task_list": {
                    "id": tl.get("id"),
                    "title": tl.get("title"),
                    "updated": tl.get("updated"),
                    "selfLink": tl.get("selfLink"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleTasksNode] Updated task list: {tl.get('id')}")
            return output

    async def _delete_task_list(
        self, config: GoogleTasksDeleteTaskListConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a task list."""
        logger.info(f"[GoogleTasksNode] Deleting task list {config.task_list_id}")

        url = f"{GOOGLE_TASKS_API_BASE}/users/@me/lists/{config.task_list_id}"

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in (200, 204):
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleTasksNode] Delete task list failed: {error_msg}")
                raise ValueError(f"Google Tasks API error: {error_msg}")

            output = {
                "type": "google_tasks",
                "operation": "delete_task_list",
                "task_list_id": config.task_list_id,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleTasksNode] Deleted task list: {config.task_list_id}")
            return output

    # ========================================================================
    # Task Operations
    # ========================================================================

    async def _list_tasks(
        self, config: GoogleTasksListTasksConfig, access_token: str
    ) -> Dict[str, Any]:
        """List tasks in a task list."""
        logger.info(f"[GoogleTasksNode] Listing tasks in {config.task_list_id}")

        url = f"{GOOGLE_TASKS_API_BASE}/lists/{config.task_list_id}/tasks"
        params: Dict[str, Any] = {}

        if config.max_results:
            params["maxResults"] = config.max_results
        if config.show_completed is not None:
            params["showCompleted"] = config.show_completed
        if config.show_hidden is not None:
            params["showHidden"] = config.show_hidden
        if config.due_min:
            params["dueMin"] = config.due_min
        if config.due_max:
            params["dueMax"] = config.due_max

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleTasksNode] List tasks failed: {error_msg}")
                raise ValueError(f"Google Tasks API error: {error_msg}")

            data = response.json()
            tasks = data.get("items", [])

            simplified_tasks = []
            for task in tasks:
                simplified_tasks.append(
                    {
                        "id": task.get("id"),
                        "title": task.get("title"),
                        "notes": task.get("notes"),
                        "status": task.get("status"),
                        "due": task.get("due"),
                        "completed": task.get("completed"),
                        "updated": task.get("updated"),
                        "parent": task.get("parent"),
                        "position": task.get("position"),
                        "selfLink": task.get("selfLink"),
                    }
                )

            output = {
                "type": "google_tasks",
                "operation": "list_tasks_in_list",
                "task_list_id": config.task_list_id,
                "task_count": len(simplified_tasks),
                "tasks": simplified_tasks,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleTasksNode] Listed {len(simplified_tasks)} tasks")
            return output

    async def _get_task(
        self, config: GoogleTasksGetTaskConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a single task."""
        logger.info(f"[GoogleTasksNode] Getting task {config.task_id}")

        url = f"{GOOGLE_TASKS_API_BASE}/lists/{config.task_list_id}/tasks/{config.task_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleTasksNode] Get task failed: {error_msg}")
                raise ValueError(f"Google Tasks API error: {error_msg}")

            task = response.json()

            output = {
                "type": "google_tasks",
                "operation": "fetch_task_from_list",
                "task_list_id": config.task_list_id,
                "task": {
                    "id": task.get("id"),
                    "title": task.get("title"),
                    "notes": task.get("notes"),
                    "status": task.get("status"),
                    "due": task.get("due"),
                    "completed": task.get("completed"),
                    "updated": task.get("updated"),
                    "parent": task.get("parent"),
                    "position": task.get("position"),
                    "selfLink": task.get("selfLink"),
                    "links": task.get("links", []),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleTasksNode] Retrieved task: {task.get('title')}")
            return output

    async def _create_task(
        self, config: GoogleTasksCreateTaskConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new task."""
        logger.info(f"[GoogleTasksNode] Creating task: {config.title}")

        url = f"{GOOGLE_TASKS_API_BASE}/lists/{config.task_list_id}/tasks"

        task_body: Dict[str, Any] = {
            "title": config.title,
        }

        if config.notes:
            task_body["notes"] = config.notes
        if config.due:
            # Tasks API expects RFC 3339 date format
            task_body["due"] = (
                f"{config.due}T00:00:00.000Z" if "T" not in config.due else config.due
            )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=task_body,
            )

            if response.status_code not in (200, 201):
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleTasksNode] Create task failed: {error_msg}")
                raise ValueError(f"Google Tasks API error: {error_msg}")

            task = response.json()

            output = {
                "type": "google_tasks",
                "operation": "create_new_task",
                "task_list_id": config.task_list_id,
                "task_id": task.get("id"),
                "task": {
                    "id": task.get("id"),
                    "title": task.get("title"),
                    "notes": task.get("notes"),
                    "status": task.get("status"),
                    "due": task.get("due"),
                    "updated": task.get("updated"),
                    "selfLink": task.get("selfLink"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleTasksNode] Created task: {task.get('id')}")
            return output

    async def _update_task(
        self, config: GoogleTasksUpdateTaskConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update a task."""
        logger.info(f"[GoogleTasksNode] Updating task {config.task_id}")

        # First get the existing task
        get_url = f"{GOOGLE_TASKS_API_BASE}/lists/{config.task_list_id}/tasks/{config.task_id}"

        async with httpx.AsyncClient() as client:
            get_response = await client.get(
                get_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if get_response.status_code != 200:
                error_data = get_response.json()
                error_msg = error_data.get("error", {}).get(
                    "message", get_response.text
                )
                logger.error(
                    f"[GoogleTasksNode] Get task for update failed: {error_msg}"
                )
                raise ValueError(f"Google Tasks API error: {error_msg}")

            existing_task = get_response.json()

            # Update only provided fields
            if config.title:
                existing_task["title"] = config.title
            if config.notes is not None:
                existing_task["notes"] = config.notes
            if config.due:
                existing_task["due"] = (
                    f"{config.due}T00:00:00.000Z"
                    if "T" not in config.due
                    else config.due
                )
            if config.status:
                existing_task["status"] = config.status

            response = await client.put(
                get_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=existing_task,
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleTasksNode] Update task failed: {error_msg}")
                raise ValueError(f"Google Tasks API error: {error_msg}")

            task = response.json()

            output = {
                "type": "google_tasks",
                "operation": "update_task_in_list",
                "task_list_id": config.task_list_id,
                "task_id": task.get("id"),
                "task": {
                    "id": task.get("id"),
                    "title": task.get("title"),
                    "notes": task.get("notes"),
                    "status": task.get("status"),
                    "due": task.get("due"),
                    "completed": task.get("completed"),
                    "updated": task.get("updated"),
                    "selfLink": task.get("selfLink"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleTasksNode] Updated task: {task.get('id')}")
            return output

    async def _delete_task(
        self, config: GoogleTasksDeleteTaskConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a task."""
        logger.info(f"[GoogleTasksNode] Deleting task {config.task_id}")

        url = f"{GOOGLE_TASKS_API_BASE}/lists/{config.task_list_id}/tasks/{config.task_id}"

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in (200, 204):
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleTasksNode] Delete task failed: {error_msg}")
                raise ValueError(f"Google Tasks API error: {error_msg}")

            output = {
                "type": "google_tasks",
                "operation": "delete_task_from_list",
                "task_list_id": config.task_list_id,
                "task_id": config.task_id,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleTasksNode] Deleted task: {config.task_id}")
            return output

    async def _clear_completed(
        self, config: GoogleTasksClearCompletedConfig, access_token: str
    ) -> Dict[str, Any]:
        """Clear all completed tasks from a task list."""
        logger.info(
            f"[GoogleTasksNode] Clearing completed tasks from {config.task_list_id}"
        )

        url = f"{GOOGLE_TASKS_API_BASE}/lists/{config.task_list_id}/clear"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in (200, 204):
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleTasksNode] Clear completed failed: {error_msg}")
                raise ValueError(f"Google Tasks API error: {error_msg}")

            output = {
                "type": "google_tasks",
                "operation": "clear_completed_tasks",
                "task_list_id": config.task_list_id,
                "timestamp": time.time(),
                "status": "success",
                "message": "All completed tasks have been cleared",
            }

            logger.info(
                f"[GoogleTasksNode] Cleared completed tasks from: {config.task_list_id}"
            )
            return output

    async def _move_task(
        self, config: GoogleTasksMoveTaskConfig, access_token: str
    ) -> Dict[str, Any]:
        """Move a task to a different position."""
        logger.info(f"[GoogleTasksNode] Moving task {config.task_id}")

        url = f"{GOOGLE_TASKS_API_BASE}/lists/{config.task_list_id}/tasks/{config.task_id}/move"
        params: Dict[str, Any] = {}
        if config.parent:
            params["parent"] = config.parent
        if config.previous:
            params["previous"] = config.previous

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleTasksNode] Move task failed: {error_msg}")
                raise ValueError(f"Google Tasks API error: {error_msg}")

            task = response.json()

            output = {
                "type": "google_tasks",
                "operation": "move_task_to_position",
                "task_list_id": config.task_list_id,
                "task_id": task.get("id"),
                "task": {
                    "id": task.get("id"),
                    "title": task.get("title"),
                    "parent": task.get("parent"),
                    "position": task.get("position"),
                    "updated": task.get("updated"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleTasksNode] Moved task: {task.get('id')}")
            return output
